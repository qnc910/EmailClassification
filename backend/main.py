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
import time

class SimpleMemoryCache:
    def __init__(self, trust_ttl=30, max_ttl=600):
        # self._cache maps: key -> { "data": data, "timestamp": float, "max_id": int, "count": int }
        self._cache = {}
        self.trust_ttl = trust_ttl  # 30 seconds
        self.max_ttl = max_ttl      # 10 minutes (600 seconds)

    def get(self, key):
        entry = self._cache.get(key)
        if not entry:
            return None
        
        now = time.time()
        # If older than max_ttl, completely discard
        if now - entry["timestamp"] > self.max_ttl:
            self._cache.pop(key, None)
            return None
            
        return entry

    def set(self, key, data, max_id=0, count=0):
        self._cache[key] = {
            "data": data,
            "timestamp": time.time(),
            "max_id": max_id,
            "count": count
        }

    def renew_timestamp(self, key):
        if key in self._cache:
            self._cache[key]["timestamp"] = time.time()

    def invalidate_user(self, email: str):
        if not email:
            return
        prefix = f"{email}:"
        keys_to_del = [k for k in self._cache.keys() if k.startswith(prefix)]
        for k in keys_to_del:
            self._cache.pop(k, None)

    def invalidate_admin(self):
        keys_to_del = [k for k in self._cache.keys() if k.startswith("admin:")]
        for k in keys_to_del:
            self._cache.pop(k, None)

    def clear(self):
        self._cache.clear()

db_cache = SimpleMemoryCache()

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
        # Add last_active_at column if not exists
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMP DEFAULT NULL;")
        # Add category column if not exists
        cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT 'inbox';")
        # Add subcategory column if not exists
        cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS subcategory VARCHAR(50) DEFAULT NULL;")
        # Add deleted_at column if not exists
        cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
        # Drop is_spam column if it exists to clean up
        cur.execute("ALTER TABLE emails DROP COLUMN IF EXISTS is_spam;")
        
        # Create email_stats table and trigger for pre-aggregation
        migration_sql = """
        CREATE TABLE IF NOT EXISTS email_stats (
            recipient VARCHAR(255) NOT NULL,
            category VARCHAR(50) NOT NULL,
            subcategory VARCHAR(50) DEFAULT '',
            count INT DEFAULT 0,
            PRIMARY KEY (recipient, category, subcategory)
        );

        CREATE INDEX IF NOT EXISTS idx_email_stats_recipient ON email_stats (recipient);

        CREATE OR REPLACE FUNCTION update_email_stats()
        RETURNS TRIGGER AS $$
        DECLARE
            v_recipient VARCHAR(255);
            v_category VARCHAR(50);
            v_subcategory VARCHAR(50);
        BEGIN
            IF (TG_OP = 'INSERT') THEN
                v_recipient := NEW.recipient;
                v_category := NEW.category;
                v_subcategory := COALESCE(NEW.subcategory, '');
                
                INSERT INTO email_stats (recipient, category, subcategory, count)
                VALUES (v_recipient, v_category, v_subcategory, 1)
                ON CONFLICT (recipient, category, subcategory)
                DO UPDATE SET count = email_stats.count + 1;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_emails_stats ON emails;
        CREATE TRIGGER trg_emails_stats
        AFTER INSERT ON emails
        FOR EACH ROW
        EXECUTE FUNCTION update_email_stats();

        -- Pre-populate and synchronize email_stats from existing emails (including soft-deleted ones)
        INSERT INTO email_stats (recipient, category, subcategory, count)
        SELECT recipient, category, COALESCE(subcategory, ''), COUNT(*)
        FROM emails
        GROUP BY recipient, category, COALESCE(subcategory, '')
        ON CONFLICT (recipient, category, subcategory)
        DO UPDATE SET count = EXCLUDED.count;
        """
        cur.execute(migration_sql)
        
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

class UserUpdate(BaseModel):
    username: str = Field(..., min_length=1)

class PasswordChange(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6)
    confirm_password: str = Field(..., min_length=6)

class AdminUserUpdate(BaseModel):
    password: Optional[str] = None
    role: str = Field(..., pattern="^(admin|user)$")

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
        if user is not None:
            cur.execute("UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE id = %s", (user['id'],))
            conn.commit()
        cur.close()
        conn.close()
        if user is None:
            raise credentials_exception
        return user
    except Exception as e:
        raise credentials_exception

def get_admin_user(current_user: dict = Depends(get_current_user)):
    if current_user.get('role') != 'admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized. Admin access required.")
    return current_user

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

@app.get("/user/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {"email": current_user['email'], "username": current_user['username'], "role": current_user['role']}

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

    # 2. Database persistence is deferred to Spark streaming classifier
    # so that sent emails can be classified properly (e.g. spam/ads/social).
    # Spark streaming classifier retrieves the email from IMAP and inserts it into DB.
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

    # Invalidate cache for sender, recipient and admin stats
    db_cache.invalidate_user(current_user['email'])
    db_cache.invalidate_user(email.recipient)
    db_cache.invalidate_admin()

    return {"status": "success", "message": "Email is being sent"}

@app.get("/emails")
async def get_emails(
    recipient: Optional[str] = None,
    sender: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    user_email = current_user['email']
    cache_key = f"{user_email}:emails:recipient={recipient}:sender={sender}:cat={category}:sub={subcategory}:lim={limit}:off={offset}"
    
    entry = db_cache.get(cache_key)
    if entry:
        now = time.time()
        # 1. Direct trust window
        if now - entry["timestamp"] <= db_cache.trust_ttl:
            return entry["data"]
            
        # 2. Fast DB validation
        try:
            conn = get_db_conn()
            cur = conn.cursor()
            val_query = "SELECT MAX(id), COUNT(*) FROM emails WHERE deleted_at IS NULL"
            val_params = []
            if recipient:
                val_query += " AND recipient = %s"
                val_params.append(recipient)
            elif sender:
                val_query += " AND sender = %s"
                val_params.append(sender)
                
            if category:
                val_query += " AND category = %s"
                val_params.append(category)
                
            if subcategory:
                val_query += " AND subcategory = %s"
                val_params.append(subcategory)
                
            cur.execute(val_query, tuple(val_params))
            row = cur.fetchone()
            cur.close()
            conn.close()
            
            db_max_id = row[0] or 0
            db_count = row[1] or 0
            
            if entry["max_id"] == db_max_id and entry["count"] == db_count:
                db_cache.renew_timestamp(cache_key)
                return entry["data"]
        except Exception as ex:
            print(f"Cache validation error: {ex}")

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
            WHERE e.deleted_at IS NULL
        """
        params = []

        if recipient:
            query += " AND e.recipient = %s"
            params.append(recipient)
        elif sender:
            query += " AND e.sender = %s"
            params.append(sender)
            
        if category:
            query += " AND e.category = %s"
            params.append(category)

        if subcategory:
            query += " AND e.subcategory = %s"
            params.append(subcategory)
            
        query += " ORDER BY e.created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cur.execute(query, tuple(params))
        emails = cur.fetchall()
        
        # Get validation metadata for caching
        val_query = "SELECT MAX(id), COUNT(*) FROM emails WHERE deleted_at IS NULL"
        val_params = []
        if recipient:
            val_query += " AND recipient = %s"
            val_params.append(recipient)
        elif sender:
            val_query += " AND sender = %s"
            val_params.append(sender)
            
        if category:
            val_query += " AND category = %s"
            val_params.append(category)

        if subcategory:
            val_query += " AND subcategory = %s"
            val_params.append(subcategory)
            
        # Use standard cursor for metadata to avoid RealDictCursor KeyError
        meta_cur = conn.cursor()
        meta_cur.execute(val_query, tuple(val_params))
        row = meta_cur.fetchone()
        db_max_id = row[0] or 0
        db_count = row[1] or 0
        meta_cur.close()
        
        cur.close()
        conn.close()
        
        db_cache.set(cache_key, emails, max_id=db_max_id, count=db_count)
        return emails
    except Exception as e:
        print(f"Fetch Error: {e}")
        raise HTTPException(status_code=500, detail=f"Database Error: {str(e)}")

@app.get("/emails/subcategories")
async def get_unique_subcategories(category: str, current_user: dict = Depends(get_current_user)):
    user_email = current_user['email']
    cache_key = f"{user_email}:subcategories:cat={category}"
    
    entry = db_cache.get(cache_key)
    if entry:
        now = time.time()
        # 1. Direct trust window
        if now - entry["timestamp"] <= db_cache.trust_ttl:
            return entry["data"]
            
        # 2. Fast DB validation
        try:
            conn = get_db_conn()
            cur = conn.cursor()
            val_query = "SELECT MAX(id), COUNT(*) FROM emails WHERE recipient = %s AND category = %s AND deleted_at IS NULL"
            cur.execute(val_query, (user_email, category))
            row = cur.fetchone()
            cur.close()
            conn.close()
            
            db_max_id = row[0] or 0
            db_count = row[1] or 0
            
            if entry["max_id"] == db_max_id and entry["count"] == db_count:
                db_cache.renew_timestamp(cache_key)
                return entry["data"]
        except Exception as ex:
            print(f"Cache validation error: {ex}")

    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT subcategory FROM emails WHERE recipient = %s AND category = %s AND subcategory IS NOT NULL AND subcategory != ''",
            (user_email, category)
        )
        rows = cur.fetchall()
        subcategories = [row[0] for row in rows]
        
        # Get validation metadata
        val_query = "SELECT MAX(id), COUNT(*) FROM emails WHERE recipient = %s AND category = %s AND deleted_at IS NULL"
        cur.execute(val_query, (user_email, category))
        row = cur.fetchone()
        db_max_id = row[0] or 0
        db_count = row[1] or 0
        
        cur.close()
        conn.close()
        
        db_cache.set(cache_key, subcategories, max_id=db_max_id, count=db_count)
        return subcategories
    except Exception as e:
        print(f"Subcategory Fetch Error: {e}")
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
        db_cache.invalidate_user(current_user['email'])
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/emails/{email_id}/delete")
async def delete_email(email_id: int, current_user: dict = Depends(get_current_user)):
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("UPDATE emails SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s", (email_id,))
        conn.commit()
        cur.close()
        conn.close()
        db_cache.invalidate_user(current_user['email'])
        db_cache.invalidate_admin()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/emails/{email_id}/restore")
async def restore_email(email_id: int, current_user: dict = Depends(get_current_user)):
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("UPDATE emails SET deleted_at = NULL WHERE id = %s", (email_id,))
        conn.commit()
        cur.close()
        conn.close()
        db_cache.invalidate_user(current_user['email'])
        db_cache.invalidate_admin()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/user/update")
async def update_profile(user_update: UserUpdate, current_user: dict = Depends(get_current_user)):
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("UPDATE users SET username = %s WHERE email = %s", (user_update.username, current_user['email']))
        conn.commit()
        cur.close()
        conn.close()
        db_cache.invalidate_user(current_user['email'])
        db_cache.invalidate_admin()
        return {"status": "success", "username": user_update.username}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/user/change-password")
async def change_password(pass_data: PasswordChange, current_user: dict = Depends(get_current_user)):
    if pass_data.new_password != pass_data.confirm_password:
        raise HTTPException(status_code=400, detail="Mật khẩu xác nhận không khớp")
    try:
        conn = get_db_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT password_hash FROM users WHERE email = %s", (current_user['email'],))
        db_user = cur.fetchone()
        if not db_user or not verify_password(pass_data.old_password, db_user['password_hash']):
            raise HTTPException(status_code=400, detail="Mật khẩu cũ không đúng")
        
        hashed_password = get_password_hash(pass_data.new_password)
        cur.execute("UPDATE users SET password_hash = %s WHERE email = %s", (hashed_password, current_user['email']))
        conn.commit()
        cur.close()
        conn.close()
        db_cache.invalidate_user(current_user['email'])
        return {"status": "success", "message": "Đổi mật khẩu thành công"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
async def get_stats(current_user: dict = Depends(get_current_user)):
    user_email = current_user['email']
    cache_key = f"{user_email}:stats"
    
    entry = db_cache.get(cache_key)
    if entry:
        now = time.time()
        # 1. Direct trust window
        if now - entry["timestamp"] <= db_cache.trust_ttl:
            return entry["data"]
            
        # 2. Fast DB validation
        try:
            conn = get_db_conn()
            cur = conn.cursor()
            val_query = "SELECT MAX(id), COUNT(*) FROM emails WHERE recipient = %s AND deleted_at IS NULL"
            cur.execute(val_query, (user_email,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            
            db_max_id = row[0] or 0
            db_count = row[1] or 0
            
            if entry["max_id"] == db_max_id and entry["count"] == db_count:
                db_cache.renew_timestamp(cache_key)
                return entry["data"]
        except Exception as ex:
            print(f"Cache validation error: {ex}")

    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT category, subcategory, count FROM email_stats WHERE recipient = %s",
            (user_email,)
        )
        rows = cur.fetchall()
        
        # Get validation metadata
        val_query = "SELECT MAX(id), COUNT(*) FROM emails WHERE recipient = %s AND deleted_at IS NULL"
        cur.execute(val_query, (user_email,))
        row = cur.fetchone()
        db_max_id = row[0] or 0
        db_count = row[1] or 0
        
        cur.close()
        conn.close()
        
        stats = {
            "ham": 0,
            "spam": 0,
            "ads": 0,
            "social": 0,
            "total": 0,
            "subcategories": {},
            "subcategory_details": {
                "inbox": {},
                "spam": {},
                "ads": {},
                "social": {}
            }
        }
        for row in rows:
            cat = row[0]
            sub = row[1]
            count = row[2]
            
            if cat == 'inbox':
                stats['ham'] += count
            elif cat in stats:
                stats[cat] += count
            stats['total'] += count
            
            if sub and sub != '':
                stats['subcategories'][sub] = stats['subcategories'].get(sub, 0) + count
                cat_key = 'inbox' if cat == 'inbox' else cat
                if cat_key in stats['subcategory_details']:
                    stats['subcategory_details'][cat_key][sub] = stats['subcategory_details'][cat_key].get(sub, 0) + count
                    
        db_cache.set(cache_key, stats, max_id=db_max_id, count=db_count)
        return stats
    except Exception as e:
        return {"ham": 0, "spam": 0, "ads": 0, "social": 0, "total": 0, "subcategories": {}, "subcategory_details": {"inbox": {}, "spam": {}, "ads": {}, "social": {}}}


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
        db_cache.invalidate_user(current_user['email'])
        db_cache.invalidate_admin()
        return {
            "status": "success", 
            "filename": filename, 
            "message": "Tệp đã được tải lên! Đang xử lý dữ liệu..."
        }
    except Exception as e:
        print(f"Upload Error: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi tải lên: {str(e)}")

# --- Admin Routes ---
@app.get("/admin/users")
async def admin_get_users(admin_user: dict = Depends(get_admin_user)):
    cache_key = "admin:users"
    entry = db_cache.get(cache_key)
    if entry:
        now = time.time()
        # Direct trust window (30s)
        if now - entry["timestamp"] <= db_cache.trust_ttl:
            return entry["data"]
            
        # Fast DB validation
        try:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT MAX(id), COUNT(*) FROM users")
            row = cur.fetchone()
            cur.close()
            conn.close()
            
            db_max_id = row[0] or 0
            db_count = row[1] or 0
            if entry["max_id"] == db_max_id and entry["count"] == db_count:
                db_cache.renew_timestamp(cache_key)
                return entry["data"]
        except Exception as ex:
            print(f"Admin cache validation error: {ex}")

    try:
        conn = get_db_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, username, email, role, created_at FROM users ORDER BY id ASC")
        users = cur.fetchall()
        
        # Get metadata using standard cursor to avoid RealDictCursor KeyError
        meta_cur = conn.cursor()
        meta_cur.execute("SELECT MAX(id), COUNT(*) FROM users")
        row = meta_cur.fetchone()
        db_max_id = row[0] or 0
        db_count = row[1] or 0
        meta_cur.close()
        
        cur.close()
        conn.close()
        
        db_cache.set(cache_key, users, max_id=db_max_id, count=db_count)
        return users
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/admin/users/{user_id}")
async def admin_update_user(user_id: int, update_data: AdminUserUpdate, admin_user: dict = Depends(get_admin_user)):
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        if update_data.password and len(update_data.password) >= 6:
            hashed_password = get_password_hash(update_data.password)
            cur.execute("UPDATE users SET role = %s, password_hash = %s WHERE id = %s", 
                        (update_data.role, hashed_password, user_id))
        else:
            cur.execute("UPDATE users SET role = %s WHERE id = %s", (update_data.role, user_id))
        conn.commit()
        cur.close()
        conn.close()
        db_cache.clear()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: int, admin_user: dict = Depends(get_admin_user)):
    # Prevent self-deletion
    if admin_user['id'] == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own admin account")
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        cur.close()
        conn.close()
        db_cache.clear()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/stats")
async def admin_get_stats(admin_user: dict = Depends(get_admin_user)):
    cache_key = "admin:stats"
    entry = db_cache.get(cache_key)
    if entry:
        now = time.time()
        # Direct trust window (30s)
        if now - entry["timestamp"] <= db_cache.trust_ttl:
            return entry["data"]
            
        # Fast DB validation
        try:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT MAX(id), COUNT(*) FROM emails WHERE deleted_at IS NULL")
            row = cur.fetchone()
            cur.close()
            conn.close()
            
            db_max_id = row[0] or 0
            db_count = row[1] or 0
            if entry["max_id"] == db_max_id and entry["count"] == db_count:
                db_cache.renew_timestamp(cache_key)
                return entry["data"]
        except Exception as ex:
            print(f"Admin stats cache validation error: {ex}")

    try:
        conn = get_db_conn()
        cur = conn.cursor()
        # Admin gets stats for all emails in the system
        cur.execute("SELECT category, subcategory, SUM(count) FROM email_stats GROUP BY category, subcategory")
        rows = cur.fetchall()
        
        # Get metadata
        cur2 = conn.cursor()
        cur2.execute("SELECT MAX(id), COUNT(*) FROM emails WHERE deleted_at IS NULL")
        row = cur2.fetchone()
        db_max_id = row[0] or 0
        db_count = row[1] or 0
        cur2.close()
        
        cur.close()
        conn.close()
        
        stats = {
            "ham": 0,
            "spam": 0,
            "ads": 0,
            "social": 0,
            "total": 0,
            "subcategories": {},
            "subcategory_details": {
                "inbox": {},
                "spam": {},
                "ads": {},
                "social": {}
            }
        }
        for row in rows:
            cat = row[0]
            sub = row[1]
            count = int(row[2] or 0)
            
            if cat == 'inbox':
                stats['ham'] += count
            elif cat in stats:
                stats[cat] += count
            stats['total'] += count
            
            if sub and sub != '':
                stats['subcategories'][sub] = stats['subcategories'].get(sub, 0) + count
                cat_key = 'inbox' if cat == 'inbox' else cat
                if cat_key in stats['subcategory_details']:
                    stats['subcategory_details'][cat_key][sub] = stats['subcategory_details'][cat_key].get(sub, 0) + count
                    
        db_cache.set(cache_key, stats, max_id=db_max_id, count=db_count)
        return stats
    except Exception as e:
        return {"ham": 0, "spam": 0, "ads": 0, "social": 0, "total": 0, "subcategories": {}, "subcategory_details": {"inbox": {}, "spam": {}, "ads": {}, "social": {}}}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
