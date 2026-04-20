from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
import smtplib
from email.mime.text import MIMEText
import json
import asyncio
from aiokafka import AIOKafkaProducer
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
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
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

# Producer will be initialized on startup
kafka_producer = None

@app.on_event("startup")
async def startup_event():
    global kafka_producer
    kafka_producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    await kafka_producer.start()
    print(f"Kafka Producer started at {KAFKA_BOOTSTRAP_SERVERS}")

@app.on_event("shutdown")
async def shutdown_event():
    if kafka_producer:
        await kafka_producer.stop()
        print("Kafka Producer stopped")

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
        
        token = create_access_token({"sub": db_user['email'], "username": db_user['username']})
        cur.close()
        conn.close()
        return {
            "access_token": token, 
            "token_type": "bearer", 
            "user": {"email": db_user['email'], "username": db_user['username']}
        }
    except Exception as e:
        print(f"Login Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/send")
async def send_email(email: EmailRequest):
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
        # Continue if DB is down but log it, or you could fail here

    # 1. Send via SMTP to GreenMail
    try:
        msg = MIMEText(email.body)
        msg['Subject'] = email.subject
        msg['From'] = email.sender
        msg['To'] = email.recipient

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.send_message(msg)
    except Exception as e:
        print(f"SMTP Error: {e}")

    # 2. Push to Kafka for Spark Streaming
    try:
        email_data = email.dict()
        if kafka_producer:
            await kafka_producer.send_and_wait("emails", json.dumps(email_data).encode("utf-8"))
            print("Email pushed to Kafka")
        else:
            print("Kafka Producer not initialized!")
    except Exception as e:
        print(f"Kafka Error: {e}")

    return {"status": "success", "message": "Email sent"}

@app.get("/emails")
async def get_emails(recipient: Optional[str] = None, sender: Optional[str] = None):
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

@app.get("/stats")
async def get_stats():
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM emails WHERE is_spam = FALSE")
        ham_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM emails WHERE is_spam = TRUE")
        spam_count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return {
            "ham": ham_count,
            "spam": spam_count,
            "total": ham_count + spam_count
        }
    except Exception as e:
        return {"ham": 0, "spam": 0, "total": 0}

@app.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")
    
    # Ensure upload dir exists
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR)

    file_path = os.path.join(UPLOAD_DIR, file.filename)
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"status": "success", "filename": file.filename, "message": "File uploaded for Spark batch processing"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload Error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
