import sys
import os
sys.path.append('/app')
from main import get_db_conn, get_password_hash

def create_admin():
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        
        # Check if user exists
        cur.execute("SELECT id FROM users WHERE email = 'admin@gmail.com' OR username = 'admin'")
        if cur.fetchone():
            print("User already exists!")
            
            # Update to admin just in case it exists as normal user
            hashed = get_password_hash("admin")
            cur.execute("UPDATE users SET role = 'admin', password_hash = %s WHERE email = 'admin@gmail.com' OR username = 'admin'", (hashed,))
            conn.commit()
            print("Updated existing user to admin with password 'admin'")
            return
            
        hashed_password = get_password_hash("admin")
        cur.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            ("admin", "admin@gmail.com", hashed_password, "admin")
        )
        conn.commit()
        cur.close()
        conn.close()
        print("Admin user created successfully!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    create_admin()
