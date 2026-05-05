"""
Fix admin password hash in database
"""

import psycopg2
import os
import toml

# Read secrets.toml
secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
with open(secrets_path, "r") as f:
    secrets = toml.load(f)

db_url = secrets.get("database_url")

try:
    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()
    
    # Update admin password hash
    correct_hash = "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9"
    
    cursor.execute(
        """UPDATE users SET password_hash = %s 
           WHERE email = 'admin@focusguard.local'""",
        (correct_hash,)
    )
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print("✅ Admin password hash updated!")
    print("Email: admin@focusguard.local")
    print("Password: admin123")
    
except Exception as e:
    print(f"❌ Error: {e}")
