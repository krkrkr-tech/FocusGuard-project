import psycopg2

db_url = 'postgresql://postgres:TErawNUiaLqDvhFLIVCClaJRNTjhgpSl@metro.proxy.rlwy.net:13219/railway'
conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Delete the unverified user
cur.execute("DELETE FROM users WHERE email = %s", ('gazizkajrat70@gmail.com',))
conn.commit()

print(f"Deleted user: gazizkajrat70@gmail.com")
print(f"Rows deleted: {cur.rowcount}")

cur.close()
conn.close()
