from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, status, BackgroundTasks, Security
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
import smtplib
from email.mime.text import MIMEText
import json
import asyncio
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Optional
import os
import shutil
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_DB = "emaildb"
POSTGRES_USER = "postgres"
POSTGRES_PASS = "123456"
SMTP_SERVER = os.getenv("SMTP_SERVER", "greenmail")
SMTP_PORT = 3025
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")

# Security
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-123")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 1 day

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

@app.on_event("startup")
async def startup_event():
    print("Backend started")
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        # Add role column if not exists
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user';")
        # Add category column if not exists
        cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT 'inbox';")
        # Drop is_spam column if it exists to clean up
        cur.execute("ALTER TABLE emails DROP COLUMN IF EXISTS is_spam;")
        conn.commit()
        cur.close()
        conn.close()
        print("Database schema updated")
    except Exception as e:
        print(f"Error updating DB schema: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    print("Backend stopped")

# Models
class UserRegister(BaseModel):
    username: str = Field(..., min_length=1)
    email: EmailStr
    password: str = Field(..., min_length=6)

class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)

class EmailRequest(BaseModel):
    sender: EmailStr
    recipient: EmailStr
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)

# Database Helper
def get_db_conn():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASS
    )

# Auth Helpers
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    try:
        conn = get_db_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user is None:
            raise credentials_exception
        return user
    except Exception as e:
        raise credentials_exception

def send_smtp_email(sender: str, recipient: str, subject: str, body: str):
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = recipient

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.send_message(msg)
    except Exception as e:
        print(f"SMTP Error: {e}")

# --- Routes ---

@app.post("/register")
async def register(user: UserRegister):
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s OR username = %s", (user.email, user.username))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="User already exists")
        
        hashed_password = get_password_hash(user.password)
        cur.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
            (user.username, user.email, hashed_password)
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "success", "message": "User registered successfully"}
    except Exception as e:
        print(f"Register Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/login")
async def login(user: UserLogin):
    try:
        conn = get_db_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE email = %s", (user.email,))
        db_user = cur.fetchone()
        if not db_user or not verify_password(user.password, db_user['password_hash']):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        token = create_access_token({"sub": db_user['email'], "username": db_user['username'], "role": db_user['role']})
        cur.close()
        conn.close()
        return {
            "access_token": token, 
            "token_type": "bearer", 
            "user": {"email": db_user['email'], "username": db_user['username'], "role": db_user['role']}
        }
    except Exception as e:
        print(f"Login Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/send")
async def send_email(email: EmailRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    # 0. Basic Validation
    if not "@" in email.recipient or not "." in email.recipient:
        raise HTTPException(status_code=400, detail="Địa chỉ email không hợp lệ!")

    # 0. Prevent self-sending
    if email.sender == email.recipient:
        raise HTTPException(status_code=400, detail="Bạn không thể gửi thư cho chính mình!")

    # 1. Validate recipient existence in our user database
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s", (email.recipient,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail=f"Recipient {email.recipient} does not exist in our system")
        cur.close()
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        print(f"Validation Error: {e}")

    # 2. Persist to database immediately for fast UI response
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO emails (sender, recipient, subject, body, category, is_read) VALUES (%s, %s, %s, %s, %s, %s)",
            (current_user['email'], email.recipient, email.subject, email.body, 'inbox', False)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB Error during send: {e}")
        # Even if DB persistence fails locally, we still queue the email sending
        # though it's better to log it for debugging.

    # 3. Add SMTP sending to background tasks
    background_tasks.add_task(
        send_smtp_email, 
        current_user['email'], 
        email.recipient, 
        email.subject, 
        email.body
    )

    return {"status": "success", "message": "Email is being sent"}

@app.get("/emails")
async def get_emails(recipient: Optional[str] = None, sender: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    try:
        conn = get_db_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT e.*, 
                   u_sender.username as sender_name, 
                   u_recipient.username as recipient_name
            FROM emails e
            LEFT JOIN users u_sender ON e.sender = u_sender.email
            LEFT JOIN users u_recipient ON e.recipient = u_recipient.email
        """
        
        if recipient:
            query += " WHERE e.recipient = %s"
            cur.execute(query + " ORDER BY e.created_at DESC", (recipient,))
        elif sender:
            query += " WHERE e.sender = %s"
            cur.execute(query + " ORDER BY e.created_at DESC", (sender,))
        else:
            cur.execute(query + " ORDER BY e.created_at DESC")
            
        emails = cur.fetchall()
        cur.close()
        conn.close()
        return emails
    except Exception as e:
        print(f"Fetch Error: {e}")
        raise HTTPException(status_code=500, detail=f"Database Error: {str(e)}")

@app.patch("/emails/{email_id}/read")
async def mark_as_read(email_id: int, current_user: dict = Depends(get_current_user)):
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("UPDATE emails SET is_read = TRUE WHERE id = %s", (email_id,))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
async def get_stats(current_user: dict = Depends(get_current_user)):
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT category, COUNT(*) FROM emails WHERE sender = 'batch_upload@system' AND recipient = %s GROUP BY category", (current_user['email'],))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        stats = {"ham": 0, "spam": 0, "ads": 0, "social": 0, "total": 0}
        for row in rows:
            cat = row[0]
            count = row[1]
            if cat == 'inbox':
                stats['ham'] += count
            elif cat in stats:
                stats[cat] += count
            stats['total'] += count
            
        return stats
    except Exception as e:
        return {"ham": 0, "spam": 0, "total": 0}


@app.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ tệp tin CSV!")
    
    # Ensure upload dir exists
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR)

    # Add timestamp and user email to filename to ensure Spark readStream treats it as a new file and knows the owner
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Format: useremail___timestamp_filename.csv
    safe_email = current_user['email'].replace('@', '_at_')
    filename = f"{safe_email}___{timestamp}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    print(f"Uploading file to: {file_path}")
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {
            "status": "success", 
            "filename": filename, 
            "message": "Tệp đã được tải lên! Spark đang xử lý dữ liệu..."
        }
    except Exception as e:
        print(f"Upload Error: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi tải lên: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
