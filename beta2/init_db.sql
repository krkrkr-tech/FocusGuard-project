-- ════════════════════════════════════════════════════════════════════════════════
-- DATABASE SCHEMA FOR FOCUS GUARD
-- ════════════════════════════════════════════════════════════════════════════════

-- 1. USERS TABLE
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student', -- student | teacher | admin
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

-- 3. EXAM ASSIGNMENTS (which student gets which exam)
CREATE TABLE IF NOT EXISTS exam_assignments (
    id SERIAL PRIMARY KEY,
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'assigned', -- assigned | started | completed
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exam_id, student_id)
);

-- 4. EXAM SESSIONS (attempt by student)
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

-- 5. FOCUS LOGS (CV data points)
CREATE TABLE IF NOT EXISTS focus_logs (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    focus_level FLOAT,
    warning_type TEXT -- no_face | looking_away | phone_detected | extra_face | blink_detected
);

-- 6. WARNINGS (violation events)
CREATE TABLE IF NOT EXISTS warnings (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    warning_type TEXT, -- person_absent | gaze_away | extra_face | phone | book | suspicious_object
    description TEXT
);

-- 7. EXAM ACCESS CODES (temporary codes for students to access exams)
CREATE TABLE IF NOT EXISTS exam_codes (
    id SERIAL PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES exam_assignments(id) ON DELETE CASCADE,
    code VARCHAR(8) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    used_at TIMESTAMP,
    UNIQUE(assignment_id)
);

-- 8. HISTORY (audit log for admin)
CREATE TABLE IF NOT EXISTS history (
    id SERIAL PRIMARY KEY,
    action_type TEXT NOT NULL, -- create_user | delete_user | create_exam | submit_exam | login | verify_email
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    target_exam_id INTEGER REFERENCES exams(id) ON DELETE SET NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details JSONB,
    ip_address TEXT
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_exams_created_by ON exams(created_by);
CREATE INDEX IF NOT EXISTS idx_exam_assignments_exam_id ON exam_assignments(exam_id);
CREATE INDEX IF NOT EXISTS idx_exam_assignments_student_id ON exam_assignments(student_id);
CREATE INDEX IF NOT EXISTS idx_exam_sessions_assignment_id ON exam_sessions(assignment_id);
CREATE INDEX IF NOT EXISTS idx_focus_logs_session_id ON focus_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_warnings_session_id ON warnings(session_id);
CREATE INDEX IF NOT EXISTS idx_exam_codes_assignment_id ON exam_codes(assignment_id);
CREATE INDEX IF NOT EXISTS idx_exam_codes_code ON exam_codes(code);
CREATE INDEX IF NOT EXISTS idx_history_user_id ON history(user_id);
CREATE INDEX IF NOT EXISTS idx_history_timestamp ON history(timestamp);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Insert default admin user (password: admin123 -> SHA256)
INSERT INTO users (email, password_hash, full_name, role, is_verified)
VALUES ('admin@focusguard.local', 'a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3', 'Administrator', 'admin', true)
ON CONFLICT (email) DO NOTHING;
