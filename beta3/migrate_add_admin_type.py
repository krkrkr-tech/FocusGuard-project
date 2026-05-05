"""
Migration: Add admin_type column to support limited admin roles
"""
import psycopg2
import toml
import os

# Read from .streamlit/secrets.toml
secrets_path = ".streamlit/secrets.toml"
with open(secrets_path, 'r') as f:
    secrets = toml.load(f)

DATABASE_URL = secrets.get("database_url")

try:
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    # Add admin_type column if it doesn't exist
    cursor.execute("""
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS admin_type VARCHAR(50) DEFAULT NULL;
    """)
    
    print("✅ Added admin_type column to users table")
    
    # Set existing admins to 'super' type (full access)
    cursor.execute("""
        UPDATE users 
        SET admin_type = 'super' 
        WHERE role = 'admin' AND admin_type IS NULL;
    """)
    
    print(f"✅ Set {cursor.rowcount} existing admins to 'super' type")
    
    conn.commit()
    cursor.close()
    conn.close()
    print("✅ Migration completed successfully")
    
except Exception as e:
    print(f"❌ Migration failed: {e}")
    if conn:
        conn.rollback()
        conn.close()
