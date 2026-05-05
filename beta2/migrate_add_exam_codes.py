import psycopg2

db_url = 'postgresql://postgres:TErawNUiaLqDvhFLIVCClaJRNTjhgpSl@metro.proxy.rlwy.net:13219/railway'
conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Create exam_codes table
sql = """
CREATE TABLE IF NOT EXISTS exam_codes (
    id SERIAL PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES exam_assignments(id) ON DELETE CASCADE,
    code VARCHAR(8) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    used_at TIMESTAMP,
    UNIQUE(assignment_id)
);

CREATE INDEX IF NOT EXISTS idx_exam_codes_assignment_id ON exam_codes(assignment_id);
CREATE INDEX IF NOT EXISTS idx_exam_codes_code ON exam_codes(code);
"""

cur.execute(sql)
conn.commit()

print("✅ exam_codes table created successfully")

cur.close()
conn.close()
