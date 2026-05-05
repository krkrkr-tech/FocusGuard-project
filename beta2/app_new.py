"""
Focus Guard - AI Proctoring System with Email Verification
Main application with PostgreSQL database integration
"""

import os
os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.3"

import cv2
import mediapipe as mp
import numpy as np
import streamlit as st
import time
from collections import deque
import threading
import queue
import io
import av
from streamlit_webrtc import (
    RTCConfiguration, VideoProcessorBase, WebRtcMode, webrtc_streamer,
)

# Import our modules
from db import (
    register_user, verify_email, login_user, get_user_by_id,
    get_all_users, delete_user, create_teacher_by_admin, check_email_exists,
    create_exam_code, get_exam_code, validate_exam_code, delete_exam_code,
    create_exam, assign_exam_to_student, get_student_exams, get_exams_by_teacher,
    start_exam_session, submit_exam_session, log_focus, log_warning,
    get_session_results, get_session_focus_logs, get_session_warnings,
    log_history, get_history, get_user_history,
    get_student_stats, get_teacher_stats, get_system_stats
)
from email_service import send_verification_email, send_violation_alert, send_exam_completion_email

# ════════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ════════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="Focus Guard", page_icon="🧠", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #0e1117; }
[data-testid="stMetric"] {
    background: #1c2333; border-radius: 10px;
    padding: 12px 16px; border: 1px solid #2a3550;
}
.vrow {
    background: #1f1318; border-left: 3px solid #ff4444;
    border-radius: 0 6px 6px 0; padding: 7px 12px;
    margin: 4px 0; color: #ffaaaa; font-size: 0.88rem;
}
.exam-card {
    background: #1c2333; border-radius: 10px;
    padding: 16px 20px; border: 1px solid #2a3550; margin-bottom: 10px;
}
.badge-pending  { background:#2a2000; color:#ffd60a; border-radius:4px; padding:2px 8px; font-size:.78rem; }
.badge-assigned { background:#002a0a; color:#00ff9d; border-radius:4px; padding:2px 8px; font-size:.78rem; }
.badge-started  { background:#00152a; color:#00b4ff; border-radius:4px; padding:2px 8px; font-size:.78rem; }
.badge-completed { background:#1a0a2a; color:#b366ff; border-radius:4px; padding:2px 8px; font-size:.78rem; }
.success-box {
    background: #0d3d0d; border-left: 4px solid #00ff9d;
    padding: 15px; border-radius: 8px; margin: 10px 0;
}
.error-box {
    background: #3d0d0d; border-left: 4px solid #ff4444;
    padding: 15px; border-radius: 8px; margin: 10px 0;
}
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ════════════════════════════════════════════════════════════════════════════════
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user_id = None
    st.session_state.email = None
    st.session_state.full_name = None
    st.session_state.role = None

if "page" not in st.session_state:
    st.session_state.page = "login"

if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None

if "current_exam" not in st.session_state:
    st.session_state.current_exam = None

# ════════════════════════════════════════════════════════════════════════════════
# AUTH PAGES
# ════════════════════════════════════════════════════════════════════════════════

def register_page():
    """User registration with email verification"""
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("## 🧠 Focus Guard")
        st.caption("AI Proctoring System · Create Account")
        st.divider()
        
        st.info("📧 Verify your email to complete registration")
        
        # Initialize session state for verification
        if "show_verify_form" not in st.session_state:
            st.session_state.show_verify_form = False
        if "verify_email_temp" not in st.session_state:
            st.session_state.verify_email_temp = None
        if "verify_role_temp" not in st.session_state:
            st.session_state.verify_role_temp = None
        if "email_validation_error" not in st.session_state:
            st.session_state.email_validation_error = ""
        
        with st.form("register_form", clear_on_submit=False):
            email = st.text_input("Email", placeholder="student@example.com", key="register_email")
            
            # Real-time email validation
            email_error = ""
            if email:
                import re
                # Check format
                if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
                    email_error = "❌ Invalid email format"
                # Check if already registered
                elif check_email_exists(email):
                    email_error = "❌ Email already registered"
            
            if email_error:
                st.error(email_error)
            elif email:
                st.success("✅ Email available")
            
            full_name = st.text_input("Full Name", placeholder="John Doe")
            password = st.text_input("Password", type="password", placeholder="At least 6 characters")
            password_confirm = st.text_input("Confirm Password", type="password")
            role = st.selectbox("Role", ["student", "teacher"])
            
            if role == "teacher":
                st.caption("⚠️ Teachers must be approved by administrator after email verification")
            
            if st.form_submit_button("Create Account", type="primary", use_container_width=True):
                if not email or not full_name or not password:
                    st.error("Please fill in all fields")
                elif email_error:
                    st.error(email_error)
                elif password != password_confirm:
                    st.error("Passwords do not match")
                elif len(password) < 6:
                    st.error("Password must be at least 6 characters")
                else:
                    # Register user
                    result = register_user(email, password, full_name, role)
                    if result["success"]:
                        st.session_state.show_verify_form = True
                        st.session_state.verify_email_temp = email
                        st.session_state.verify_role_temp = role
                        st.session_state.verification_code = result.get('verification_code')
                        st.success(f"✅ {result['message']}")
                        st.rerun()
                    else:
                        st.error(f"❌ {result['message']}")
        
        # Show verification form inline after registration
        if st.session_state.show_verify_form:
            st.divider()
            st.subheader("📧 Verify Your Email")
            
            st.info(f"Verification code sent to **{st.session_state.verify_email_temp}**")
            st.caption(f"Code for testing: `{st.session_state.verification_code}`", unsafe_allow_html=False)
            
            col1, col2 = st.columns([3, 1])
            with col1:
                code = st.text_input("Enter 6-digit verification code", placeholder="000000", max_chars=6, key="verify_code_input")
            with col2:
                if st.button("Verify", type="primary", use_container_width=True):
                    if not code or len(code) != 6:
                        st.error("Please enter a 6-digit code")
                    else:
                        result = verify_email(st.session_state.verify_email_temp, code)
                        if result["success"]:
                            role = st.session_state.verify_role_temp
                            if role == "teacher":
                                st.markdown(
                                    '<div class="success-box">✅ Email verified! Waiting for administrator approval.</div>',
                                    unsafe_allow_html=True
                                )
                            else:
                                st.markdown(
                                    '<div class="success-box">✅ Email verified! You can now log in.</div>',
                                    unsafe_allow_html=True
                                )
                            st.session_state.show_verify_form = False
                            st.session_state.verify_email_temp = None
                            st.session_state.verify_role_temp = None
                            time.sleep(2)
                            st.rerun()
                        else:
                            st.error(f"❌ {result['message']}")
        
        st.divider()
        if st.button("Already have an account? Sign in →", use_container_width=True):
            st.session_state.page = "login"
            st.rerun()


def login_page():
    """User login"""
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("## 🧠 Focus Guard")
        st.caption("AI Proctoring System · Sign In")
        st.divider()
        
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        
        if st.button("Sign in", use_container_width=True, type="primary"):
            if not email or not password:
                st.error("Please enter email and password")
            else:
                result = login_user(email, password)
                if result["success"]:
                    st.session_state.update({
                        "authenticated": True,
                        "user_id": result["user_id"],
                        "email": result["email"],
                        "full_name": result["full_name"],
                        "role": result["role"],
                    })
                    st.success(f"✅ Welcome back, {result['full_name']}!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"❌ {result['message']}")
        
        st.divider()
        if st.button("Need an account? Register →", use_container_width=True):
            st.session_state.page = "register"
            st.rerun()


# ════════════════════════════════════════════════════════════════════════════════
# MAIN APP PAGES
# ════════════════════════════════════════════════════════════════════════════════

def logout():
    """Logout user"""
    st.session_state.clear()
    st.rerun()

def sidebar_header():
    """Render sidebar header"""
    with st.sidebar:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"### 👤 {st.session_state.get('full_name', 'User')}")
            st.caption(f"`{st.session_state.get('email', '')}`")
        with col2:
            if st.button("🚪", help="Sign out"):
                logout()
        
        st.divider()

# ────────────────────────────────────────────────────────────────────────────────
# ADMIN PAGE
# ────────────────────────────────────────────────────────────────────────────────

def admin_page():
    """Admin panel"""
    sidebar_header()
    
    st.title("🛡️ Admin Panel")
    st.caption("System management and monitoring")
    st.divider()
    
    tab_teachers, tab_students, tab_history, tab_stats = st.tabs(["👨‍🏫 Teachers", "🎓 Students", "📋 History", "📊 Statistics"])
    
    with tab_teachers:
        st.subheader("Manage Teachers")
        st.caption("👇 Teachers can self-register and need your approval to login")
        
        # Unverified teachers (awaiting approval)
        all_users = get_all_users()
        unverified_teachers = [u for u in all_users if u['role'] == 'teacher' and not u['is_verified']]
        verified_teachers = [u for u in all_users if u['role'] == 'teacher' and u['is_verified']]
        
        if unverified_teachers:
            st.warning(f"⏳ **{len(unverified_teachers)} teacher(s) awaiting approval** (email verified, not yet approved)")
            for user in unverified_teachers:
                col1, col2, col3, col4 = st.columns([2, 2, 1.5, 1.5])
                col1.markdown(f"**{user['full_name']}**")
                col2.markdown(f"`{user['email']}`")
                col3.caption(user['created_at'].strftime("%Y-%m-%d"))
                if col4.button("✅ Approve", key=f"app_{user['id']}"):
                    # Approve teacher
                    from db import execute_query
                    execute_query(
                        "UPDATE users SET is_verified = true WHERE id = %s",
                        (user['id'],)
                    )
                    st.success(f"Teacher {user['full_name']} approved!")
                    st.rerun()
        
        st.subheader("✅ Approved Teachers")
        if verified_teachers:
            for user in verified_teachers:
                col1, col2, col3, col4 = st.columns([2, 2, 1.5, 1])
                col1.markdown(f"**{user['full_name']}**")
                col2.markdown(f"`{user['email']}`")
                col3.caption(user['created_at'].strftime("%Y-%m-%d"))
                if col4.button("🗑️", key=f"del_{user['id']}", help="Delete teacher"):
                    if delete_user(user['id']):
                        st.success("Teacher deleted")
                        st.rerun()
        else:
            st.info("No approved teachers yet")
        
        st.divider()
        st.subheader("➕ Create Teacher Directly")
        st.caption("This bypasses email verification - teacher can login immediately")
        with st.form("add_teacher_form"):
            teacher_name = st.text_input("Full Name", placeholder="John Doe")
            teacher_email = st.text_input("Email", placeholder="teacher@example.com")
            teacher_pass = st.text_input("Password", type="password", placeholder="At least 6 characters")
            
            if st.form_submit_button("Create Teacher (Immediate Access)", type="primary", use_container_width=True):
                if not teacher_name or not teacher_email or not teacher_pass:
                    st.error("Fill in all fields")
                elif len(teacher_pass) < 6:
                    st.error("Password must be at least 6 characters")
                else:
                    result = create_teacher_by_admin(teacher_email, teacher_pass, teacher_name)
                    if result["success"]:
                        st.success(f"✅ Teacher {teacher_name} created and can login now")
                    else:
                        st.error(f"❌ {result['message']}")
    
    with tab_students:
        st.subheader("Manage Students")
        all_users = get_all_users()
        students = [u for u in all_users if u['role'] == 'student']
        unverified_students = [u for u in students if not u['is_verified']]
        verified_students = [u for u in students if u['is_verified']]
        
        if unverified_students:
            st.warning(f"⏳ **{len(unverified_students)} student(s) awaiting email verification**")
            for user in unverified_students:
                col1, col2, col3, col4 = st.columns([2, 2, 1.5, 1])
                col1.markdown(f"**{user['full_name']}**")
                col2.markdown(f"`{user['email']}`")
                col3.caption(user['created_at'].strftime("%Y-%m-%d"))
                if col4.button("🗑️", key=f"del_us_{user['id']}", help="Delete unverified student"):
                    if delete_user(user['id']):
                        st.success("Student deleted")
                        st.rerun()
        
        st.subheader("✅ Verified Students")
        if verified_students:
            for user in verified_students:
                col1, col2, col3, col4 = st.columns([2, 2, 1.5, 1])
                col1.markdown(f"**{user['full_name']}**")
                col2.markdown(f"`{user['email']}`")
                col3.caption(user['created_at'].strftime("%Y-%m-%d"))
                if col4.button("🗑️", key=f"del_vs_{user['id']}", help="Delete verified student"):
                    if delete_user(user['id']):
                        st.success("Student deleted")
                        st.rerun()
        else:
            st.info("No verified students yet")
        
        if not students:
            st.info("No students yet")
    
    with tab_history:
        st.subheader("Action History")
        history = get_history(limit=50)
        
        if history:
            for h in history:
                col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
                col1.markdown(f"**{h['action_type']}**")
                col2.caption(f"User: {h['user_id'] or 'System'}")
                col3.caption(h['timestamp'].strftime("%Y-%m-%d %H:%M"))
                if h['details']:
                    col4.caption(str(h['details'])[:30] + "...")
        else:
            st.info("No actions logged yet")
    
    with tab_stats:
        st.subheader("System Statistics")
        stats = get_system_stats()
        
        if stats:
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("👥 Total Users", stats['total_users'] or 0)
            col2.metric("🎓 Students", stats['total_students'] or 0)
            col3.metric("👨‍🏫 Teachers", stats['total_teachers'] or 0)
            col4.metric("📋 Total Exams", stats['total_exams'] or 0)
            col5.metric("✅ Completed", stats['completed_sessions'] or 0)

# ────────────────────────────────────────────────────────────────────────────────
# TEACHER PAGE
# ────────────────────────────────────────────────────────────────────────────────

def teacher_page():
    """Teacher panel"""
    sidebar_header()
    
    st.title("👨‍🏫 Teacher Panel")
    st.divider()
    
    tab_create, tab_results = st.tabs(["➕ Create Exam", "📊 Results"])
    
    with tab_create:
        st.subheader("Create New Exam")
        
        title = st.text_input("Exam Title", placeholder="e.g. Midterm Exam")
        description = st.text_area("Exam Description", placeholder="Enter exam details...")
        
        # Get all students
        all_users = get_all_users()
        students = {u['id']: u['full_name'] for u in all_users if u['role'] == 'student' and u['is_verified']}
        
        if students:
            selected_students = st.multiselect("Assign to students", 
                                              options=list(students.keys()),
                                              format_func=lambda u: students[u])
            
            if st.button("📋 Create Exam", type="primary", use_container_width=True):
                if not title:
                    st.error("Enter exam title")
                else:
                    result = create_exam(title, description, st.session_state.user_id)
                    if result["success"]:
                        exam_id = result["exam_id"]
                        
                        # Assign to students and generate access codes
                        for student_id in selected_students:
                            assign_exam_to_student(exam_id, student_id)
                            # Get the assignment ID and create exam code
                            from db import execute_query
                            assignment = execute_query(
                                "SELECT id FROM exam_assignments WHERE exam_id = %s AND student_id = %s",
                                (exam_id, student_id),
                                fetch_one=True
                            )
                            if assignment:
                                code = create_exam_code(assignment['id'])
                                if code:
                                    st.write(f"✅ {students[student_id]}: `{code}`")
                        
                        st.success(f"✅ Exam created and assigned to {len(selected_students)} student(s)")
                        st.rerun()
        else:
            st.warning("No verified students available")
    
    with tab_results:
        st.subheader("My Exams")
        exams = get_exams_by_teacher(st.session_state.user_id)
        
        if exams:
            for exam in exams:
                st.markdown(f"""<div class="exam-card">
                    <b>{exam['title']}</b><br>
                    <small>{exam['students_assigned']} student(s) assigned · Created: {exam['created_at'].strftime('%Y-%m-%d')}</small>
                </div>""", unsafe_allow_html=True)
        else:
            st.info("You haven't created any exams yet")
    
    stats = get_teacher_stats(st.session_state.user_id)
    if stats:
        st.divider()
        st.subheader("Your Statistics")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📋 Total Exams", stats['total_exams'] or 0)
        col2.metric("👥 Students", stats['total_students'] or 0)
        col3.metric("✅ Sessions Done", stats['completed_sessions'] or 0)
        col4.metric("📊 Avg Score", f"{stats['avg_student_score'] or 0:.1f}/100")

# ────────────────────────────────────────────────────────────────────────────────
# STUDENT PAGE
# ────────────────────────────────────────────────────────────────────────────────

def student_page():
    """Student exam page"""
    sidebar_header()
    
    # Если уже есть активная сессия, показываем экран сдачи экзамена
    if st.session_state.current_session_id:
        st.title("📝 Exam in Progress")
        st.warning("⚠️ Do not close this page until you submit!")
        st.info("Exam session monitoring implementation goes here")
        return
    
    st.title("🎓 Student Dashboard")
    st.divider()
    
    # Get assigned exams
    assigned = get_student_exams(st.session_state.user_id, status="assigned")
    started = get_student_exams(st.session_state.user_id, status="started")
    completed = get_student_exams(st.session_state.user_id, status="completed")
    
    tab_active, tab_history = st.tabs(["📋 Active Exams", "✅ Completed"])
    
    with tab_active:
        if assigned or started:
            for exam in assigned + started:
                st.markdown(f"""<div class="exam-card">
                    <b>{exam['title']}</b> &nbsp;
                    <span class="badge-assigned">{exam['status'].upper()}</span><br>
                    <small>Teacher: {exam['teacher_name']} · Assigned: {exam['assigned_at'].strftime('%Y-%m-%d %H:%M')}</small>
                </div>""", unsafe_allow_html=True)
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    exam_code = st.text_input(
                        "Enter exam code to access", 
                        placeholder="XXXXXXXX",
                        key=f"code_{exam['assignment_id']}"
                    )
                with col2:
                    if st.button("📝 Start", key=f"take_{exam['assignment_id']}", use_container_width=True):
                        if not exam_code or len(exam_code) != 8:
                            st.error("Enter valid 8-character exam code")
                        elif validate_exam_code(exam['assignment_id'], exam_code):
                            # Start exam session
                            result = start_exam_session(exam['assignment_id'])
                            if result["success"]:
                                st.session_state.current_session_id = result["session_id"]
                                st.session_state.current_exam = exam
                                st.rerun()
                            else:
                                st.error("Failed to start exam session")
                        else:
                            st.error("❌ Invalid exam code")
        else:
            st.info("📭 No active exams assigned to you")
    
    with tab_history:
        if completed:
            for exam in completed:
                st.markdown(f"""<div class="exam-card">
                    <b>{exam['title']}</b> &nbsp;
                    <span class="badge-completed">COMPLETED</span><br>
                    <small>Teacher: {exam['teacher_name']} · Assigned: {exam['assigned_at'].strftime('%Y-%m-%d')}</small>
                </div>""", unsafe_allow_html=True)
        else:
            st.info("No completed exams yet")
    
    # Student stats
    stats = get_student_stats(st.session_state.user_id)
    if stats:
        st.divider()
        st.subheader("Your Statistics")
        col1, col2, col3 = st.columns(3)
        col1.metric("📋 Total Exams", stats['total_exams'] or 0)
        col2.metric("✅ Completed", stats['completed_exams'] or 0)
        col3.metric("📊 Avg Score", f"{stats['avg_score'] or 0:.1f}/100")

# ════════════════════════════════════════════════════════════════════════════════
# MAIN ROUTER
# ════════════════════════════════════════════════════════════════════════════════

if not st.session_state.authenticated:
    if st.session_state.page == "register":
        register_page()
    else:
        login_page()
else:
    role = st.session_state.role
    
    if role == "admin":
        admin_page()
    elif role == "teacher":
        teacher_page()
    elif role == "student":
        student_page()
    else:
        st.error("Unknown role")

st.caption("🧠 Focus Guard · AI Proctoring System with PostgreSQL + SendGrid")
