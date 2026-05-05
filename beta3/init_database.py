"""
Initialize PostgreSQL database for Focus Guard
Run this script once to create all tables and indexes
"""

import psycopg2
import sys
import os
import toml

# Read secrets.toml directly
secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
if not os.path.exists(secrets_path):
    print("❌ Error: .streamlit/secrets.toml not found")
    sys.exit(1)

try:
    with open(secrets_path, "r") as f:
        secrets = toml.load(f)
except Exception as e:
    print(f"❌ Error reading secrets.toml: {e}")
    sys.exit(1)

db_url = secrets.get("database_url")
if not db_url:
    print("❌ Error: database_url not in .streamlit/secrets.toml")
    sys.exit(1)

# SQL для создания таблиц
SQL_SCHEMA = """
-- 1. USERS TABLE
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student',
    is_verified BOOLEAN DEFAULT FALSE,
    verification_code VARCHAR(6),
    verification_code_expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. EXAMS TABLE
CREATE TABLE IF NOT EXISTS exams (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. EXAM ASSIGNMENTS
CREATE TABLE IF NOT EXISTS exam_assignments (
    id SERIAL PRIMARY KEY,
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'assigned',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exam_id, student_id)
);

-- 4. EXAM SESSIONS
CREATE TABLE IF NOT EXISTS exam_sessions (
    id SERIAL PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES exam_assignments(id) ON DELETE CASCADE,
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    final_score FLOAT,
    avg_focus FLOAT,
    min_focus FLOAT,
    blink_rate FLOAT,
    total_violations INTEGER DEFAULT 0,
    submitted_at TIMESTAMP
);

-- 5. FOCUS LOGS
CREATE TABLE IF NOT EXISTS focus_logs (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    focus_level FLOAT,
    warning_type TEXT
);

-- 6. WARNINGS
CREATE TABLE IF NOT EXISTS warnings (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    warning_type TEXT,
    description TEXT
);

-- 7. HISTORY (AUDIT LOG)
CREATE TABLE IF NOT EXISTS history (
    id SERIAL PRIMARY KEY,
    action_type TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    target_exam_id INTEGER REFERENCES exams(id) ON DELETE SET NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details JSONB,
    ip_address TEXT
);

-- CREATE INDEXES
CREATE INDEX IF NOT EXISTS idx_exams_created_by ON exams(created_by);
CREATE INDEX IF NOT EXISTS idx_exam_assignments_exam_id ON exam_assignments(exam_id);
CREATE INDEX IF NOT EXISTS idx_exam_assignments_student_id ON exam_assignments(student_id);
CREATE INDEX IF NOT EXISTS idx_exam_sessions_assignment_id ON exam_sessions(assignment_id);
CREATE INDEX IF NOT EXISTS idx_focus_logs_session_id ON focus_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_warnings_session_id ON warnings(session_id);
CREATE INDEX IF NOT EXISTS idx_history_user_id ON history(user_id);
CREATE INDEX IF NOT EXISTS idx_history_timestamp ON history(timestamp);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
"""

def init_database():
    """Initialize database schema"""
    try:
        print("🔌 Connecting to PostgreSQL...")
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        print("📋 Creating tables and indexes...")
        cursor.execute(SQL_SCHEMA)
        
        # Insert default admin user (password: admin123)
        print("👤 Creating default admin user...")
        cursor.execute("""
            INSERT INTO users (email, password_hash, full_name, role, is_verified)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (email) DO NOTHING
        """, (
            'admin@focusguard.local',
            'a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3',  # SHA256 of admin123
            'Administrator',
            'admin',
            True
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("\n✅ Database initialized successfully!")
        print("📊 Tables created:")
        print("   ✓ users")
        print("   ✓ exams")
        print("   ✓ exam_assignments")
        print("   ✓ exam_sessions")
        print("   ✓ focus_logs")
        print("   ✓ warnings")
        print("   ✓ history")
        print("\n👤 Default admin user created:")
        print("   Email: admin@focusguard.local")
        print("   Password: admin123")
        
        return True
        
    except psycopg2.Error as e:
        print(f"\n❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("🧠 Focus Guard - Database Initialization")
    print("=" * 50)
    
    if init_database():
        sys.exit(0)
    else:
        sys.exit(1)
