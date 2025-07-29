# database.py
import sqlite3
import os

# نام فایل دیتابیس
DB_FILE = "users.db"

def init_db():
    """یک جدول برای کاربران ایجاد می‌کند اگر وجود نداشته باشد"""
    # اگر فایل دیتابیس وجود داشت، آن را حذف نکن
    # این کار باعث می‌شود اطلاعات با هر بار اجرای مجدد ربات باقی بمانند
    db_exists = os.path.exists(DB_FILE)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    if not db_exists:
        print("Creating new database table...")
        cursor.execute('''
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                age INTEGER,
                gender TEXT,
                province TEXT,
                city TEXT,
                bio TEXT,
                interests TEXT,
                profile_photo_id TEXT,
                coins INTEGER DEFAULT 20,
                last_daily_reward DATE,
                likes INTEGER DEFAULT 0,
                dislikes INTEGER DEFAULT 0,
                special_likes INTEGER DEFAULT 0,
                is_banned BOOLEAN DEFAULT 0,
                referred_by INTEGER
            )
        ''')
    else:
        print("Database already exists.")
        
    conn.commit()
    conn.close()

def user_exists(user_id):
    """بررسی می‌کند آیا کاربر در دیتابیس وجود دارد یا خیر"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def add_user(user_id):
    """یک کاربر جدید با مقادیر اولیه اضافه می‌کند"""
    if not user_exists(user_id):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # هر کاربر جدید با ۲۰ سکه شروع می‌کند
        cursor.execute("INSERT INTO users (user_id, coins) VALUES (?, 20)", (user_id,))
        conn.commit()
        conn.close()

def get_user(user_id):
    """اطلاعات یک کاربر را برمی‌گرداند"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # این خط اجازه دسترسی به ستون‌ها با نام را می‌دهد
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result

def update_profile_field(user_id, field, value):
    """یک فیلد خاص از پروفایل کاربر را آپدیت می‌کند"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # استفاده از f-string اینجا امن است چون نام فیلدها از کد می‌آید نه از کاربر
    query = f"UPDATE users SET {field} = ? WHERE user_id = ?"
    cursor.execute(query, (value, user_id))
    conn.commit()
    conn.close()
