"""
Database module for Focus Guard
Handles all PostgreSQL operations
"""

import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import hashlib
import secrets
import json
from datetime import datetime, timedelta
from contextlib import contextmanager

@contextmanager
def get_db_connection():
    """Get database connection from secrets"""
    conn = None
    try:
        db_url = st.secrets.get("database_url") or ""
        if not db_url:
            raise ValueError("database_url not configured in secrets")
        conn = psycopg2.connect(db_url)
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        st.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()

def execute_query(query, params=None, fetch=False, fetch_one=False):
    """Execute a query"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(query, params or ())
            
            if fetch:
                return cur.fetchall()
            elif fetch_one:
                return cur.fetchone()
            else:
                return cur.rowcount
    except Exception as e:
        st.error(f"Query error: {e}")
        return None

# ════════════════════════════════════════════════════════════════════════════════
# USER MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def check_email_exists(email: str) -> bool:
    """Check if email is already registered"""
    try:
        result = execute_query(
            "SELECT id FROM users WHERE email = %s",
            (email,),
            fetch_one=True
        )
        return result is not None
    except:
        return False

def generate_verification_code() -> str:
    """Generate 6-digit verification code"""
    return ''.join([str(secrets.randbelow(10)) for _ in range(6)])

def register_user(email: str, password: str, full_name: str, role: str = 'student') -> dict:
    """Register new user"""
    try:
        # Check if user exists
        existing = execute_query(
            "SELECT id FROM users WHERE email = %s",
            (email,),
            fetch_one=True
        )
        
        if existing:
            return {"success": False, "message": "Email already registered"}
        
        # Generate verification code
        verification_code = generate_verification_code()
        expires_at = datetime.now() + timedelta(minutes=10)
        
        # Insert user
        user = execute_query(
            """INSERT INTO users 
            (email, password_hash, full_name, role, verification_code, verification_code_expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, email, full_name, role""",
            (email, hash_password(password), full_name, role, verification_code, expires_at),
            fetch_one=True
        )
        
        if user:
            # Log action
            try:
                log_history(user['id'], "register", details={"email": email})
            except:
                pass  # Logging failure shouldn't block registration
            
            # Send verification email
            try:
                from email_service import send_verification_email
                send_verification_email(email, verification_code, full_name)
            except Exception as email_error:
                # Don't fail registration if email fails, log it instead
                try:
                    log_history(user['id'], "email_send_failed", details={"error": str(email_error)})
                except:
                    pass
            
            return {
                "success": True,
                "message": "Registration successful. Check your email for verification code.",
                "user_id": user['id'],
                "verification_code": verification_code  # For testing only
            }
        
    except Exception as e:
        return {"success": False, "message": f"Registration error: {e}"}

def create_teacher_by_admin(email: str, password: str, full_name: str) -> dict:
    """Create teacher by admin (auto-verified, no email verification needed)"""
    try:
        # Check if user exists
        existing = execute_query(
            "SELECT id FROM users WHERE email = %s",
            (email,),
            fetch_one=True
        )
        
        if existing:
            return {"success": False, "message": "Email already registered"}
        
        # Insert teacher as verified
        user = execute_query(
            """INSERT INTO users 
            (email, password_hash, full_name, role, is_verified)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, email, full_name, role""",
            (email, hash_password(password), full_name, 'teacher', True),
            fetch_one=True
        )
        
        if user:
            try:
                log_history(user['id'], "admin_create_teacher", details={"email": email})
            except:
                pass
            
            return {
                "success": True,
                "message": "Teacher created and verified successfully",
                "user_id": user['id']
            }
        
    except Exception as e:
        return {"success": False, "message": f"Error creating teacher: {e}"}

def create_student_by_admin(email: str, password: str, full_name: str) -> dict:
    """Create student by admin (auto-verified, no email verification needed)"""
    try:
        # Check if user exists
        existing = execute_query(
            "SELECT id FROM users WHERE email = %s",
            (email,),
            fetch_one=True
        )
        
        if existing:
            return {"success": False, "message": "Email already registered"}
        
        # Insert student as verified
        user = execute_query(
            """INSERT INTO users 
            (email, password_hash, full_name, role, is_verified)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, email, full_name, role""",
            (email, hash_password(password), full_name, 'student', True),
            fetch_one=True
        )
        
        if user:
            try:
                log_history(user['id'], "admin_create_student", details={"email": email})
            except:
                pass
            
            return {
                "success": True,
                "message": "Student created and verified successfully",
                "user_id": user['id']
            }
        
    except Exception as e:
        return {"success": False, "message": f"Error creating student: {e}"}

def create_admin_by_admin(email: str, password: str, full_name: str, admin_type: str = 'super') -> dict:
    """Create admin by existing admin with specific type"""
    try:
        # Validate admin_type
        valid_types = ['super', 'email_checker', 'exam_manager', 'student_manager']
        if admin_type not in valid_types:
            return {"success": False, "message": f"Invalid admin type. Must be one of: {', '.join(valid_types)}"}
        
        # Check if user exists
        existing = execute_query(
            "SELECT id FROM users WHERE email = %s",
            (email,),
            fetch_one=True
        )
        
        if existing:
            return {"success": False, "message": "Email already registered"}
        
        # Insert admin as verified with admin_type
        user = execute_query(
            """INSERT INTO users 
            (email, password_hash, full_name, role, is_verified, admin_type)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, email, full_name, role, admin_type""",
            (email, hash_password(password), full_name, 'admin', True, admin_type),
            fetch_one=True
        )
        
        if user:
            try:
                log_history(user['id'], "admin_create_admin", details={"email": email, "admin_type": admin_type})
            except:
                pass
            
            return {
                "success": True,
                "message": f"Admin ({admin_type}) created successfully",
                "user_id": user['id']
            }
        
    except Exception as e:
        return {"success": False, "message": f"Error creating admin: {e}"}

def verify_email(email: str, verification_code: str) -> dict:
    """Verify email with code"""
    try:
        user = execute_query(
            """SELECT id, role, verification_code, verification_code_expires_at 
            FROM users WHERE email = %s""",
            (email,),
            fetch_one=True
        )
        
        if not user:
            return {"success": False, "message": "User not found"}
        
        # Check if code expired
        expires_at = user['verification_code_expires_at']
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        if expires_at < datetime.now():
            return {"success": False, "message": "Verification code expired"}
        
        # Check code
        if user['verification_code'] != verification_code:
            return {"success": False, "message": "Invalid verification code"}
        
        # For students: mark as verified (email is verification for approval)
        # For teachers: only clear verification code, keep is_verified=false (admin approval needed)
        if user['role'] == 'student':
            execute_query(
                """UPDATE users 
                SET is_verified = true, verification_code = NULL, verification_code_expires_at = NULL
                WHERE id = %s""",
                (user['id'],)
            )
        else:  # teacher
            execute_query(
                """UPDATE users 
                SET verification_code = NULL, verification_code_expires_at = NULL
                WHERE id = %s""",
                (user['id'],)
            )
        
        log_history(user['id'], "verify_email")
        
        return {"success": True, "message": "Email verified successfully"}
        
    except Exception as e:
        return {"success": False, "message": f"Verification error: {e}"}

def login_user(email: str, password: str) -> dict:
    """Login user"""
    try:
        user = execute_query(
            """SELECT id, email, full_name, role, is_verified, password_hash
            FROM users WHERE email = %s""",
            (email,),
            fetch_one=True
        )
        
        # Generic error message for security (prevents account enumeration)
        if not user:
            return {"success": False, "message": "Incorrect email or password"}
        
        if not user['is_verified']:
            return {"success": False, "message": "Incorrect email or password"}
        
        if user['password_hash'] != hash_password(password):
            return {"success": False, "message": "Incorrect email or password"}
        
        log_history(user['id'], "login")
        
        return {
            "success": True,
            "user_id": user['id'],
            "email": user['email'],
            "full_name": user['full_name'],
            "role": user['role']
        }
        
    except Exception as e:
        return {"success": False, "message": "Incorrect email or password"}

def get_user_by_id(user_id: int) -> dict:
    """Get user by ID"""
    return execute_query(
        "SELECT id, email, full_name, role, is_verified, created_at FROM users WHERE id = %s",
        (user_id,),
        fetch_one=True
    )

def get_all_users() -> list:
    """Get all users"""
    return execute_query(
        "SELECT id, email, full_name, role, is_verified, created_at FROM users ORDER BY created_at DESC",
        fetch=True
    )

def delete_user(user_id: int) -> bool:
    """Delete user"""
    try:
        execute_query("DELETE FROM users WHERE id = %s", (user_id,))
        log_history(None, "delete_user", target_user_id=user_id)
        return True
    except:
        return False

# ════════════════════════════════════════════════════════════════════════════════
# EXAM CODE MANAGEMENT (for exam access)
# ════════════════════════════════════════════════════════════════════════════════

def generate_exam_code() -> str:
    """Generate random 8-character exam access code"""
    import string
    chars = string.ascii_uppercase + string.digits
    return ''.join([chars[secrets.randbelow(len(chars))] for _ in range(8)])

def create_exam_code(assignment_id: int) -> str:
    """Create unique exam access code for an assignment"""
    try:
        code = generate_exam_code()
        expires_at = datetime.now() + timedelta(hours=24)  # Code expires in 24 hours
        
        execute_query(
            """INSERT INTO exam_codes (assignment_id, code, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (assignment_id) DO UPDATE SET code = %s
            """,
            (assignment_id, code, expires_at, code)
        )
        return code
    except Exception as e:
        return None

def get_exam_code(assignment_id: int) -> str:
    """Get exam code for an assignment"""
    try:
        result = execute_query(
            "SELECT code FROM exam_codes WHERE assignment_id = %s",
            (assignment_id,),
            fetch_one=True
        )
        return result['code'] if result else None
    except:
        return None

def validate_exam_code(assignment_id: int, code: str) -> bool:
    """Validate exam code and mark as used"""
    try:
        result = execute_query(
            """SELECT id, expires_at, used_at FROM exam_codes 
            WHERE assignment_id = %s AND code = %s""",
            (assignment_id, code),
            fetch_one=True
        )
        
        if not result:
            return False
        
        # Check if already used
        if result['used_at']:
            return False
        
        # Check if expired
        if result['expires_at']:
            expires_at = result['expires_at']
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            if expires_at < datetime.now():
                return False
        
        # Mark as used
        execute_query(
            "UPDATE exam_codes SET used_at = NOW() WHERE id = %s",
            (result['id'],)
        )
        return True
    except:
        return False

def delete_exam_code(assignment_id: int) -> bool:
    """Delete exam code after exam completion"""
    try:
        execute_query(
            "DELETE FROM exam_codes WHERE assignment_id = %s",
            (assignment_id,)
        )
        return True
    except:
        return False

# ════════════════════════════════════════════════════════════════════════════════
# EXAM MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════════

def create_exam(title: str, description: str, created_by_id: int) -> dict:
    """Create exam"""
    try:
        exam = execute_query(
            """INSERT INTO exams (title, description, created_by)
            VALUES (%s, %s, %s)
            RETURNING id, title, created_by, created_at""",
            (title, description, created_by_id),
            fetch_one=True
        )
        
        if exam:
            log_history(created_by_id, "create_exam", target_exam_id=exam['id'])
            return {"success": True, "exam_id": exam['id']}
        
    except Exception as e:
        return {"success": False, "message": str(e)}

def assign_exam_to_student(exam_id: int, student_id: int) -> bool:
    """Assign exam to student"""
    try:
        execute_query(
            """INSERT INTO exam_assignments (exam_id, student_id)
            VALUES (%s, %s)
            ON CONFLICT (exam_id, student_id) DO UPDATE SET status = 'assigned'""",
            (exam_id, student_id)
        )
        return True
    except:
        return False

def get_student_exams(student_id: int, status: str = None) -> list:
    """Get exams assigned to student"""
    query = """
        SELECT 
            e.id, e.title, e.description, e.created_by,
            u.full_name as teacher_name,
            ea.id as assignment_id,
            ea.status,
            ea.assigned_at
        FROM exam_assignments ea
        JOIN exams e ON ea.exam_id = e.id
        JOIN users u ON e.created_by = u.id
        WHERE ea.student_id = %s
    """
    
    params = [student_id]
    
    if status:
        query += " AND ea.status = %s"
        params.append(status)
    
    query += " ORDER BY ea.assigned_at DESC"
    
    return execute_query(query, params, fetch=True)

def get_exams_by_teacher(teacher_id: int) -> list:
    """Get all exams created by teacher"""
    return execute_query(
        """SELECT e.id, e.title, e.description, e.created_at,
        COUNT(DISTINCT ea.student_id) as students_assigned
        FROM exams e
        LEFT JOIN exam_assignments ea ON e.id = ea.exam_id
        WHERE e.created_by = %s
        GROUP BY e.id
        ORDER BY e.created_at DESC""",
        (teacher_id,),
        fetch=True
    )

# ════════════════════════════════════════════════════════════════════════════════
# EXAM SESSION MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════════

def start_exam_session(assignment_id: int) -> dict:
    """Start exam session"""
    try:
        session = execute_query(
            """INSERT INTO exam_sessions (assignment_id)
            VALUES (%s)
            RETURNING id, start_time""",
            (assignment_id,),
            fetch_one=True
        )
        
        if session:
            # Update assignment status
            execute_query(
                "UPDATE exam_assignments SET status = 'started' WHERE id = %s",
                (assignment_id,)
            )
            
            return {"success": True, "session_id": session['id']}
        
    except Exception as e:
        return {"success": False, "message": str(e)}

def submit_exam_session(session_id: int, avg_focus: float, min_focus: float, 
                       blink_rate: float, total_violations: int, focus_scores: list) -> bool:
    """Submit exam session with results"""
    try:
        # Calculate final score (weighted formula)
        focus_weight = 0.6
        violation_weight = 0.4
        violation_penalty = (total_violations * 2)  # 2 points per violation
        
        final_score = max(0, (avg_focus * focus_weight) - (violation_penalty * violation_weight))
        
        execute_query(
            """UPDATE exam_sessions 
            SET end_time = CURRENT_TIMESTAMP,
                avg_focus = %s,
                min_focus = %s,
                blink_rate = %s,
                total_violations = %s,
                final_score = %s,
                submitted_at = CURRENT_TIMESTAMP
            WHERE id = %s""",
            (avg_focus, min_focus, blink_rate, total_violations, final_score, session_id)
        )
        
        # Update assignment status
        execute_query(
            """UPDATE exam_assignments 
            SET status = 'completed'
            WHERE id = (SELECT assignment_id FROM exam_sessions WHERE id = %s)""",
            (session_id,)
        )
        
        return True
        
    except Exception as e:
        st.error(f"Submit error: {e}")
        return False

def log_focus(session_id: int, focus_level: float, warning_type: str = None) -> bool:
    """Log focus data point"""
    try:
        execute_query(
            """INSERT INTO focus_logs (session_id, focus_level, warning_type)
            VALUES (%s, %s, %s)""",
            (session_id, focus_level, warning_type)
        )
        return True
    except:
        return False

def log_warning(session_id: int, warning_type: str, description: str = None) -> bool:
    """Log warning/violation"""
    try:
        execute_query(
            """INSERT INTO warnings (session_id, warning_type, description)
            VALUES (%s, %s, %s)""",
            (session_id, warning_type, description)
        )
        return True
    except:
        return False

def get_session_results(session_id: int) -> dict:
    """Get exam session results"""
    return execute_query(
        """SELECT id, avg_focus, min_focus, blink_rate, total_violations, 
        final_score, start_time, end_time, submitted_at
        FROM exam_sessions WHERE id = %s""",
        (session_id,),
        fetch_one=True
    )

def get_session_focus_logs(session_id: int) -> list:
    """Get focus logs for session"""
    return execute_query(
        """SELECT focus_level, warning_type, timestamp
        FROM focus_logs WHERE session_id = %s
        ORDER BY timestamp ASC""",
        (session_id,),
        fetch=True
    )

def get_session_warnings(session_id: int) -> list:
    """Get warnings for session"""
    return execute_query(
        """SELECT warning_type, description, timestamp
        FROM warnings WHERE session_id = %s
        ORDER BY timestamp ASC""",
        (session_id,),
        fetch=True
    )

# ════════════════════════════════════════════════════════════════════════════════
# HISTORY & AUDIT LOG
# ════════════════════════════════════════════════════════════════════════════════

def log_history(user_id: int, action_type: str, target_user_id: int = None, 
               target_exam_id: int = None, details: dict = None, ip_address: str = None) -> bool:
    """Log action to history"""
    try:
        execute_query(
            """INSERT INTO history 
            (user_id, action_type, target_user_id, target_exam_id, details, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s)""",
            (user_id, action_type, target_user_id, target_exam_id, 
             json.dumps(details) if details else None, ip_address)
        )
        return True
    except:
        return False

def get_history(limit: int = 100) -> list:
    """Get action history"""
    return execute_query(
        """SELECT id, action_type, user_id, target_user_id, target_exam_id,
        timestamp, details FROM history
        ORDER BY timestamp DESC LIMIT %s""",
        (limit,),
        fetch=True
    )

def get_user_history(user_id: int, limit: int = 50) -> list:
    """Get user history"""
    return execute_query(
        """SELECT id, action_type, timestamp, details
        FROM history WHERE user_id = %s
        ORDER BY timestamp DESC LIMIT %s""",
        (user_id, limit),
        fetch=True
    )

# ════════════════════════════════════════════════════════════════════════════════
# STATISTICS & ANALYTICS
# ════════════════════════════════════════════════════════════════════════════════

def get_student_stats(student_id: int) -> dict:
    """Get student statistics"""
    stats = execute_query(
        """SELECT 
        COUNT(DISTINCT ea.id) as total_exams,
        COUNT(DISTINCT CASE WHEN ea.status = 'completed' THEN ea.id END) as completed_exams,
        AVG(es.final_score) as avg_score,
        AVG(es.avg_focus) as avg_focus,
        SUM(es.total_violations) as total_violations
        FROM exam_assignments ea
        LEFT JOIN exam_sessions es ON ea.id = es.assignment_id
        WHERE ea.student_id = %s""",
        (student_id,),
        fetch_one=True
    )
    return stats or {}

def get_teacher_stats(teacher_id: int) -> dict:
    """Get teacher statistics"""
    stats = execute_query(
        """SELECT 
        COUNT(DISTINCT e.id) as total_exams,
        COUNT(DISTINCT ea.student_id) as total_students,
        COUNT(DISTINCT CASE WHEN ea.status = 'completed' THEN ea.id END) as completed_sessions,
        AVG(es.final_score) as avg_student_score
        FROM exams e
        LEFT JOIN exam_assignments ea ON e.id = ea.exam_id
        LEFT JOIN exam_sessions es ON ea.id = es.assignment_id
        WHERE e.created_by = %s""",
        (teacher_id,),
        fetch_one=True
    )
    return stats or {}

def get_system_stats() -> dict:
    """Get system-wide statistics"""
    stats = execute_query(
        """SELECT 
        (SELECT COUNT(*) FROM users) as total_users,
        (SELECT COUNT(*) FROM users WHERE role = 'student') as total_students,
        (SELECT COUNT(*) FROM users WHERE role = 'teacher') as total_teachers,
        (SELECT COUNT(*) FROM exams) as total_exams,
        (SELECT COUNT(*) FROM exam_sessions WHERE submitted_at IS NOT NULL) as completed_sessions
        """,
        fetch_one=True
    )
    return stats or {}
