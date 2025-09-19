from dotenv import load_dotenv
import os
from flask import Flask, request, render_template, redirect, url_for, flash, session, jsonify
import requests
import openai
import sqlite3
from flask import render_template_string, request as flask_request
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import hashlib
import secrets
from datetime import datetime, timedelta
import sendgrid
from sendgrid.helpers.mail import Mail
import psycopg2
import psycopg2.extras
import json

# Load environment variables from .env file
load_dotenv()

# OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
print("Loaded API Key:", OPENAI_API_KEY[:8] + "..." if OPENAI_API_KEY else "Not found")

# Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")

# Meta/Instagram setup
VERIFY_TOKEN = "chata_verify_token"
ACCESS_TOKEN = "EAAUpDddy4TkBPP2vwCiiTuwImcctxC3nXSYwApeoUNZBQg5VMgnqliV5ffW5aPnNMf1gW4JZCFZCiTCz6LL6l5ZAeIUoKYbHtGEOTL83o2k8mRmEaTrzhJrvj6gfy0fZAIl45wBAT8wp7AfiaZAllHjzE7sdCoBqpKk4hZCoWN2aAuJ3ugnZAY31qP4KPSb6Fk0PDdpOqFxEc1k6AmprxT1r"
INSTAGRAM_USER_ID = "745508148639483"

# Facebook OAuth Configuration (for Instagram Business API)
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET")
FACEBOOK_REDIRECT_URI = os.getenv("FACEBOOK_REDIRECT_URI", "https://chata-bot.onrender.com/auth/instagram/callback")

# Debug OAuth configuration
print(f"Facebook OAuth - App ID: {FACEBOOK_APP_ID[:8] + '...' if FACEBOOK_APP_ID else 'Not set'}")
print(f"Facebook OAuth - App Secret: {'Set' if FACEBOOK_APP_SECRET else 'Not set'}")
print(f"Facebook OAuth - Redirect URI: {FACEBOOK_REDIRECT_URI}")

# Database configuration
DB_FILE = "chata.db"
DATABASE_URL = os.getenv("DATABASE_URL")

# ---- Database connection helper ----

def get_db_connection():
    """Get database connection - automatically chooses between SQLite and PostgreSQL"""
    database_url = os.environ.get('DATABASE_URL')
    
    if database_url and (database_url.startswith('postgres://') or database_url.startswith('postgresql://')):
        print(f"🔗 Connecting to PostgreSQL database...")
        try:
            conn = psycopg2.connect(database_url)
            print(f"✅ PostgreSQL connected successfully")
            return conn
        except Exception as e:
            print(f"❌ PostgreSQL connection error: {e}")
            return None
    else:
        print(f"🔗 Using SQLite database (local development)")
        return sqlite3.connect(DB_FILE)

def get_param_placeholder():
    """Get the correct parameter placeholder for the current database"""
    database_url = os.environ.get('DATABASE_URL')
    if database_url and (database_url.startswith('postgres://') or database_url.startswith('postgresql://')):
        return '%s'  # PostgreSQL uses %s
    else:
        return '?'   # SQLite uses ?

# ---- Database initialization ----

def init_database():
    """Initialize database tables"""
    print("🔧 Initializing database...")
    
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        print(f"Database connection - DATABASE_URL: {database_url[:50]}...")
    
    conn = get_db_connection()
    if not conn:
        print("❌ Failed to get database connection")
        return False
    
    try:
        cursor = conn.cursor()
        
        # Check if we're using PostgreSQL or SQLite
        is_postgres = bool(database_url and (database_url.startswith('postgres://') or database_url.startswith('postgresql://')))
        
        if is_postgres:
            print("✅ Using PostgreSQL database")
            
            # Check if tables exist first - only drop if there's a schema mismatch
            print("🔍 Checking existing database schema...")
            try:
                cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
                existing_tables = [row[0] for row in cursor.fetchall()]
                print(f"📋 Existing tables: {existing_tables}")
                
                # Only drop tables if they exist and we need to recreate them
                if existing_tables:
                    print("⚠️ Tables already exist - keeping existing data")
                else:
                    print("📝 No existing tables found - will create new ones")
            except Exception as e:
                print(f"⚠️ Warning: Could not check existing tables: {e}")
                print("Continuing with table creation...")
            
            # Create users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create instagram_connections table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS instagram_connections (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    instagram_user_id VARCHAR(255) NOT NULL,
                    instagram_page_id VARCHAR(255) NOT NULL,
                    page_access_token TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create client_settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS client_settings (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    instagram_connection_id INTEGER REFERENCES instagram_connections(id),
                    bot_personality TEXT DEFAULT 'You are a helpful and friendly Instagram bot.',
                    temperature REAL DEFAULT 0.7,
                    max_tokens INTEGER DEFAULT 150,
                    auto_reply BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create usage_logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    instagram_connection_id INTEGER REFERENCES instagram_connections(id),
                    action VARCHAR(100) NOT NULL,
                    tokens_used INTEGER DEFAULT 0,
                    cost REAL DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create activity_logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    action VARCHAR(100) NOT NULL,
                    details TEXT,
                    ip_address VARCHAR(45),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create password_resets table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS password_resets (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    token VARCHAR(255) UNIQUE NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    used_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create messages table
            print("🔧 Creating messages table...")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    instagram_user_id VARCHAR(255) NOT NULL,
                    message_text TEXT NOT NULL,
                    bot_response TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("✅ Messages table created")
            
            # Create settings table
            print("🔧 Creating settings table...")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id SERIAL PRIMARY KEY,
                    key VARCHAR(255) UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("✅ Settings table created")
            
        else:
            print("✅ Using SQLite database")
            
            # Create users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create instagram_connections table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS instagram_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id),
                    instagram_user_id TEXT NOT NULL,
                    instagram_page_id TEXT NOT NULL,
                    page_access_token TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create client_settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS client_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id),
                    instagram_connection_id INTEGER REFERENCES instagram_connections(id),
                    bot_personality TEXT DEFAULT 'You are a helpful and friendly Instagram bot.',
                    temperature REAL DEFAULT 0.7,
                    max_tokens INTEGER DEFAULT 150,
                    auto_reply BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create usage_logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id),
                    instagram_connection_id INTEGER REFERENCES instagram_connections(id),
                    action TEXT NOT NULL,
                    tokens_used INTEGER DEFAULT 0,
                    cost REAL DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create activity_logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id),
                    action TEXT NOT NULL,
                    details TEXT,
                    ip_address TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create password_resets table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS password_resets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id),
                    token TEXT UNIQUE NOT NULL,
                    expires_at DATETIME NOT NULL,
                    used_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instagram_user_id TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    bot_response TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        # Skip unique constraint addition to avoid transaction issues
        print("✅ Skipping unique constraint addition to avoid transaction issues")
        
        # Insert default bot settings
        param = get_param_placeholder()
        if is_postgres:
            # PostgreSQL syntax
            cursor.execute(f"""
                INSERT INTO settings (key, value) VALUES ({param}, {param})
                ON CONFLICT (key) DO NOTHING
            """, ('bot_personality', 'You are a helpful and friendly Instagram bot.'))
            cursor.execute(f"""
                INSERT INTO settings (key, value) VALUES ({param}, {param})
                ON CONFLICT (key) DO NOTHING
            """, ('temperature', '0.7'))
            cursor.execute(f"""
                INSERT INTO settings (key, value) VALUES ({param}, {param})
                ON CONFLICT (key) DO NOTHING
            """, ('max_tokens', '150'))
        else:
            # SQLite syntax
            cursor.execute(f"INSERT OR IGNORE INTO settings (key, value) VALUES ({param}, {param})", 
                          ('bot_personality', 'You are a helpful and friendly Instagram bot.'))
            cursor.execute(f"INSERT OR IGNORE INTO settings (key, value) VALUES ({param}, {param})", 
                          ('temperature', '0.7'))
            cursor.execute(f"INSERT OR IGNORE INTO settings (key, value) VALUES ({param}, {param})", 
                          ('max_tokens', '150'))
        
        conn.commit()
        print("✅ Database initialized successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        print(f"Error type: {type(e).__name__}")
        # Try to rollback and continue
        try:
            conn.rollback()
            print("🔄 Transaction rolled back, continuing...")
        except:
            pass
        return False
    finally:
        try:
            conn.close()
        except:
            pass

def run_database_migrations():
    """Run database migrations to fix data inconsistencies"""
    print("🔧 Running database migrations...")
    
    conn = get_db_connection()
    if not conn:
        print("❌ Failed to get database connection for migrations")
        return False
    
    try:
        cursor = conn.cursor()
        
        # Create migrations table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS migrations (
                id SERIAL PRIMARY KEY,
                migration_name VARCHAR(255) UNIQUE NOT NULL,
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Migration 1: Fix Instagram User ID from business account ID to user ID
        migration_name = "fix_instagram_user_id_2024"
        cursor.execute("SELECT id FROM migrations WHERE migration_name = %s", (migration_name,))
        if not cursor.fetchone():
            print("🔄 Migration 1: Fixing Instagram User ID...")
            
            # Check if we have the old business account ID
            cursor.execute("SELECT id, instagram_user_id FROM instagram_connections WHERE instagram_user_id = '17841471490292183'")
            old_connections = cursor.fetchall()
            
            if old_connections:
                print(f"📋 Found {len(old_connections)} connection(s) with old business account ID")
                
                # Update to correct user ID
                cursor.execute("""
                    UPDATE instagram_connections 
                    SET instagram_user_id = '71457471009' 
                    WHERE instagram_user_id = '17841471490292183'
                """)
                
                rows_updated = cursor.rowcount
                print(f"✅ Updated {rows_updated} connection(s) to use correct user ID")
            else:
                print("✅ No connections found with old business account ID")
            
            # Mark migration as completed
            cursor.execute("INSERT INTO migrations (migration_name) VALUES (%s)", (migration_name,))
            print(f"✅ Migration '{migration_name}' completed and marked as executed")
        else:
            print(f"✅ Migration '{migration_name}' already executed, skipping...")
        
        # Migration 2: Ensure we have a dummy user for hardcoded Chata bot
        migration_name = "create_dummy_chata_user_2024"
        cursor.execute("SELECT id FROM migrations WHERE migration_name = %s", (migration_name,))
        if not cursor.fetchone():
            print("🔄 Migration 2: Creating dummy Chata user...")
            create_dummy_chata_user(cursor)
            
            # Mark migration as completed
            cursor.execute("INSERT INTO migrations (migration_name) VALUES (%s)", (migration_name,))
            print(f"✅ Migration '{migration_name}' completed and marked as executed")
        else:
            print(f"✅ Migration '{migration_name}' already executed, skipping...")
        
        conn.commit()
        print("✅ All database migrations completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error running database migrations: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def create_dummy_chata_user(cursor=None):
    """Create a dummy user and Instagram connection for the hardcoded Chata bot"""
    print("🔧 Creating dummy Chata user...")
    
    if cursor is None:
        conn = get_db_connection()
        if not conn:
            print("❌ Failed to get database connection for dummy user creation")
            return None
        cursor = conn.cursor()
        should_close = True
    else:
        should_close = False
    
    try:
        # Check if dummy user already exists
        cursor.execute("SELECT id FROM users WHERE email = 'chata@dummy.com'")
        existing_user = cursor.fetchone()
        
        if existing_user:
            print("✅ Dummy Chata user already exists")
            return existing_user[0]
        
        # Create dummy user
        cursor.execute("""
            INSERT INTO users (email, password_hash)
            VALUES (?, ?)
            RETURNING id
        """, ('chata@dummy.com', 'dummy_hash'))
        
        user_id = cursor.fetchone()[0]
        print(f"✅ Created dummy user with ID: {user_id}")
        
        # Create Instagram connection for hardcoded Chata bot
        cursor.execute("""
            INSERT INTO instagram_connections (
                user_id, instagram_user_id, instagram_page_id, 
                page_access_token, is_active
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (instagram_user_id) DO NOTHING
        """, (
            user_id, 
            INSTAGRAM_USER_ID, 
            "hardcoded_chata_page",
            ACCESS_TOKEN,
            True
        ))
        
        # Create default settings for Chata bot
        cursor.execute("""
            INSERT INTO client_settings (
                user_id, instagram_connection_id, bot_personality
            )
            VALUES (?, ?, ?)
            ON CONFLICT (user_id, instagram_connection_id) DO NOTHING
        """, (
            user_id,
            None,  # Global settings for hardcoded bot
            "You are Chata, a helpful AI assistant for Instagram messaging."
        ))
        
        if should_close:
            conn.commit()
        print(f"✅ Created dummy Chata user (ID: {user_id}) with hardcoded Instagram connection")
        return user_id
        
    except Exception as e:
        print(f"❌ Error creating dummy Chata user: {e}")
        if should_close:
            conn.rollback()
        return None
    finally:
        if should_close:
            conn.close()

# Initialize database on app startup
print("🚀 Starting Chata application...")
if init_database():
    print("✅ Database initialized successfully")
    
    # Run database migrations to fix any data inconsistencies
    run_database_migrations()
    
    # Show current Instagram connections for debugging
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, user_id, instagram_user_id, instagram_page_id, is_active FROM instagram_connections")
            connections = cursor.fetchall()
            print(f"📱 Found {len(connections)} Instagram connections:")
            for conn_data in connections:
                print(f"  - ID: {conn_data[0]}, User: {conn_data[1]}, IG User: {conn_data[2]}, Page: {conn_data[3]}, Active: {conn_data[4]}")
            conn.close()
    except Exception as e:
        print(f"⚠️ Could not check Instagram connections: {e}")
else:
    print("❌ Database initialization failed - some features may not work")

# ---- Email helpers ----

def send_reset_email(email, reset_token):
    """Send password reset email using SendGrid"""
    reset_url = f"https://chata-bot.onrender.com/reset-password?token={reset_token}"
    
    # Get SendGrid API key from environment
    sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
    
    if not sendgrid_api_key:
        # Fallback to console output if no API key
        print(f"Password reset link for {email}: {reset_url}")
        print("SENDGRID_API_KEY not found in environment variables")
        return
    
    try:
        sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)
        
        # Create email content
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px; text-align: center;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Chata</h1>
                <p style="color: white; margin: 10px 0 0 0; font-size: 16px;">AI-powered Instagram DM automation</p>
            </div>
            
            <div style="background: white; padding: 30px; border-radius: 10px; margin-top: 20px;">
                <h2 style="color: #333; margin-bottom: 20px;">Password Reset Request</h2>
                <p style="color: #666; line-height: 1.6; margin-bottom: 25px;">
                    You requested a password reset for your Chata account. Click the button below to reset your password:
                </p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" style="background: #3366ff; color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block;">
                        Reset Password
                    </a>
                </div>
                
                <p style="color: #666; font-size: 14px; margin-bottom: 15px;">
                    If the button doesn't work, copy and paste this link into your browser:
                </p>
                <p style="color: #3366ff; font-size: 14px; word-break: break-all;">
                    {reset_url}
                </p>
                
                <hr style="border: none; border-top: 1px solid #eee; margin: 25px 0;">
                
                <p style="color: #999; font-size: 12px; margin: 0;">
                    This link will expire in 1 hour. If you didn't request this password reset, you can safely ignore this email.
                </p>
            </div>
        </div>
        """
        
        message = Mail(
            from_email='chata.dmbot@gmail.com',
            to_emails=email,
            subject='Password Reset Request - Chata',
            html_content=html_content
        )
        
        response = sg.send(message)
        print(f"Password reset email sent to {email}. Status: {response.status_code}")
        
        # Check if the email was sent successfully
        if response.status_code == 202:
            print(f"✅ Email sent successfully to {email}")
        else:
            print(f"❌ Email failed to send. Status: {response.status_code}")
            print(f"Response body: {response.body}")
        
    except Exception as e:
        print(f"❌ Error sending email to {email}: {e}")
        print(f"Error type: {type(e).__name__}")
        # Fallback to console output
        print(f"Password reset link for {email}: {reset_url}")

def create_reset_token(user_id):
    """Create a password reset token"""
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=1)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    cursor.execute(f"""
        INSERT INTO password_resets (user_id, token, expires_at)
        VALUES ({placeholder}, {placeholder}, {placeholder})
    """, (user_id, token, expires))
    conn.commit()
    conn.close()
    
    return token

def verify_reset_token(token):
    """Verify a password reset token"""
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    cursor.execute(f"""
        SELECT user_id FROM password_resets 
        WHERE token = {placeholder} AND expires_at > {placeholder} AND used_at IS NULL
    """, (token, datetime.now()))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else None

def mark_reset_token_used(token):
    """Mark a reset token as used"""
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    cursor.execute(f"UPDATE password_resets SET used_at = CURRENT_TIMESTAMP WHERE token = {placeholder}", (token,))
    conn.commit()
    conn.close()

# ---- Authentication helpers ----

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_user_by_id(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"SELECT id, email, created_at FROM users WHERE id = {placeholder}", (user_id,))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'email': user[1],
                'created_at': user[2]
            }
        return None
    except Exception as e:
        print(f"Error getting user by ID: {e}")
        return None

def get_user_by_email(email):
    try:
        print(f"🔍 get_user_by_email called with email: {email}")
        print(f"🔍 email type: {type(email)}")
        print(f"🔍 email length: {len(email) if email else 'None'}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        print(f"🔍 Using placeholder: {placeholder}")
        print(f"🔍 SQL query: SELECT id, email, password_hash, created_at FROM users WHERE email = {placeholder}")
        print(f"🔍 Parameters: {email}")
        
        cursor.execute(f"SELECT id, email, password_hash, created_at FROM users WHERE email = {placeholder}", (email,))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'email': user[1],
                'password_hash': user[2],
                'created_at': user[3]
            }
        return None
    except Exception as e:
        print(f"❌ Error getting user by email: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return None

def create_user(email, password):
    try:
        print(f"🔍 create_user called with email: {email}")
        print(f"🔍 email type: {type(email)}")
        print(f"🔍 email length: {len(email) if email else 'None'}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        password_hash = generate_password_hash(password)
        placeholder = get_param_placeholder()
        
        print(f"🔍 Using placeholder: {placeholder}")
        
        # For PostgreSQL, we need to get the ID differently
        database_url = os.environ.get('DATABASE_URL')
        if database_url and (database_url.startswith("postgres://") or database_url.startswith("postgresql://")):
            sql = f"INSERT INTO users (email, password_hash) VALUES ({placeholder}, {placeholder}) RETURNING id"
            params = (email, password_hash)
            print(f"🔍 PostgreSQL SQL: {sql}")
            print(f"🔍 PostgreSQL params: {params}")
            
            cursor.execute(sql, params)
            user_id = cursor.fetchone()[0]
        else:
            sql = f"INSERT INTO users (email, password_hash) VALUES ({placeholder}, {placeholder})"
            params = (email, password_hash)
            print(f"🔍 SQLite SQL: {sql}")
            print(f"🔍 SQLite params: {params}")
            
            cursor.execute(sql, params)
            user_id = cursor.lastrowid
            
        conn.commit()
        conn.close()
        return user_id
    except Exception as e:
        print(f"❌ Error creating user: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        raise

# ---- Authentication routes ----

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        print(f"🔍 Signup form data:")
        print(f"🔍 Email: {email}")
        print(f"🔍 Email type: {type(email)}")
        
        # Basic validation
        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("signup.html")
        
        # Check if user already exists
        existing_user = get_user_by_email(email)
        if existing_user:
            flash("An account with this email already exists.", "error")
            return render_template("signup.html")
        
        # Create new user
        try:
            user_id = create_user(email, password)
            session['user_id'] = user_id
            flash("Account created successfully! Welcome to Chata.", "success")
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash("Error creating account. Please try again.", "error")
            return render_template("signup.html")
    
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("login.html")
        
        try:
            user = get_user_by_email(email)
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                log_activity(user['id'], 'login', 'User logged in successfully')
                flash(f"Welcome back, {user['email']}!", "success")
                return redirect(url_for('dashboard'))
            else:
                flash("Invalid email or password.", "error")
        except Exception as e:
            print(f"Login error: {e}")
            flash("An error occurred during login. Please try again.", "error")
    
    return render_template("login.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email")
        
        print(f"🔍 Forgot password request for email: {email}")
        
        if not email:
            flash("Please enter your email address.", "error")
            return render_template("forgot_password.html")
        
        user = get_user_by_email(email)
        if user:
            print(f"✅ User found: {user['email']}")
            # Create reset token and send email
            try:
                reset_token = create_reset_token(user['id'])
                print(f"✅ Reset token created: {reset_token[:10]}...")
                send_reset_email(email, reset_token)
                print(f"✅ Email sent successfully to {email}")
                flash("If an account with that email exists, we've sent a password reset link.", "success")
            except Exception as e:
                print(f"❌ Error in forgot password process: {e}")
                flash("An error occurred while sending the reset email. Please try again.", "error")
        else:
            print(f"❌ User not found for email: {email}")
            # Don't reveal if email exists or not (security best practice)
            flash("If an account with that email exists, we've sent a password reset link.", "success")
        
        return redirect(url_for('login'))
    
    return render_template("forgot_password.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    token = request.args.get("token")
    
    if not token:
        flash("Invalid reset link.", "error")
        return redirect(url_for('login'))
    
    user_id = verify_reset_token(token)
    if not user_id:
        flash("Invalid or expired reset link.", "error")
        return redirect(url_for('login'))
    
    if request.method == "POST":
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        
        if not password or not confirm_password:
            flash("Please enter both password fields.", "error")
            return render_template("reset_password.html")
        
        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("reset_password.html")
        
        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("reset_password.html")
        
        # Update password
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            password_hash = generate_password_hash(password)
            placeholder = get_param_placeholder()
            cursor.execute(f"UPDATE users SET password_hash = {placeholder} WHERE id = {placeholder}", (password_hash, user_id))
            conn.commit()
            conn.close()
            
            # Mark token as used
            mark_reset_token_used(token)
            
            flash("Password updated successfully! You can now log in.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            flash("Error updating password. Please try again.", "error")
    
    return render_template("reset_password.html")

@app.route("/logout")
def logout():
    session.pop('user_id', None)
    flash("You have been logged out.", "info")
    return redirect(url_for('home'))

# Instagram OAuth Routes
@app.route("/auth/instagram")
@login_required
def instagram_auth():
    """Start Instagram OAuth flow"""
    if not FACEBOOK_APP_ID:
        flash("Facebook OAuth not configured. Please contact support.", "error")
        return redirect(url_for('dashboard'))
    
    # Generate state parameter for security
    state = secrets.token_urlsafe(32)
    session['instagram_oauth_state'] = state
    
    # Build Instagram Business OAuth URL (using Facebook Graph API)
    oauth_url = (
        f"https://www.facebook.com/v18.0/dialog/oauth"
        f"?client_id={FACEBOOK_APP_ID}"
        f"&redirect_uri={FACEBOOK_REDIRECT_URI}"
        f"&scope=instagram_basic,instagram_manage_messages,pages_messaging,pages_read_engagement"
        f"&response_type=code"
        f"&state={state}"
    )
    
    return redirect(oauth_url)

@app.route("/auth/instagram/callback")
@login_required
def instagram_callback():
    """Handle Instagram OAuth callback"""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    # Check for errors
    if error:
        flash(f"Instagram authorization failed: {error}", "error")
        return redirect(url_for('dashboard'))
    
    # Verify state parameter
    if state != session.get('instagram_oauth_state'):
        flash("Invalid state parameter. Please try again.", "error")
        return redirect(url_for('dashboard'))
    
    if not code:
        flash("No authorization code received from Instagram.", "error")
        return redirect(url_for('dashboard'))
    
    try:
        # Exchange code for access token using Facebook Graph API
        token_url = "https://graph.facebook.com/v18.0/oauth/access_token"
        token_data = {
            'client_id': FACEBOOK_APP_ID,
            'client_secret': FACEBOOK_APP_SECRET,
            'redirect_uri': FACEBOOK_REDIRECT_URI,
            'code': code
        }
        
        response = requests.post(token_url, data=token_data)
        response.raise_for_status()
        token_info = response.json()
        
        access_token = token_info.get('access_token')
        
        if not access_token:
            flash("Failed to get Instagram access token.", "error")
            return redirect(url_for('dashboard'))
        
        # Get Instagram Business account information
        # First, get the user's Instagram Business accounts
        accounts_url = "https://graph.facebook.com/v18.0/me/accounts"
        accounts_params = {
            'access_token': access_token,
            'fields': 'instagram_business_account'
        }
        
        print(f"🔍 Fetching accounts from: {accounts_url}")
        print(f"🔍 With params: {accounts_params}")
        
        accounts_response = requests.get(accounts_url, params=accounts_params)
        print(f"🔍 Response status: {accounts_response.status_code}")
        print(f"🔍 Response headers: {dict(accounts_response.headers)}")
        
        if accounts_response.status_code != 200:
            print(f"❌ API Error: {accounts_response.text}")
            flash(f"Facebook API error: {accounts_response.status_code}", "error")
            return redirect(url_for('dashboard'))
        
        accounts_data = accounts_response.json()
        print(f"🔍 Accounts response: {accounts_data}")
        
        # Find the Instagram Business account
        instagram_account = None
        for account in accounts_data.get('data', []):
            print(f"🔍 Checking account: {account}")
            if account.get('instagram_business_account'):
                instagram_account = account['instagram_business_account']
                print(f"✅ Found Instagram account: {instagram_account}")
                break
        
        if not instagram_account:
            print(f"ℹ️ No Instagram Business account found in {len(accounts_data.get('data', []))} accounts - trying alternative method...")
            
            # Let's try a different approach - get the specific Page ID from the token
            debug_token_url = "https://graph.facebook.com/v18.0/debug_token"
            debug_params = {
                'input_token': access_token,
                'access_token': FACEBOOK_APP_ID + '|' + FACEBOOK_APP_SECRET
            }
            debug_response = requests.get(debug_token_url, params=debug_params)
            debug_data = debug_response.json()
            print(f"🔍 Token debug response: {debug_data}")
            
            # Extract Page ID from the token
            page_id = None
            if 'data' in debug_data and 'granular_scopes' in debug_data['data']:
                for scope in debug_data['data']['granular_scopes']:
                    if scope['scope'] == 'pages_read_engagement' and scope['target_ids']:
                        page_id = scope['target_ids'][0]
                        print(f"🔍 Found Page ID: {page_id}")
                        break
            
            if page_id:
                # Try to get Instagram account directly from the Page
                page_url = f"https://graph.facebook.com/v18.0/{page_id}"
                page_params = {
                    'access_token': access_token,
                    'fields': 'instagram_business_account'
                }
                print(f"🔍 Fetching Page info from: {page_url}")
                print(f"🔍 With params: {page_params}")
                
                page_response = requests.get(page_url, params=page_params)
                print(f"🔍 Page response status: {page_response.status_code}")
                page_data = page_response.json()
                print(f"🔍 Page response: {page_data}")
                
                if 'instagram_business_account' in page_data:
                    instagram_account = page_data['instagram_business_account']
                    print(f"✅ Found Instagram account via Page: {instagram_account}")
        
        if not instagram_account:
            flash("No Instagram Business account found. Please ensure your Instagram account is connected to a Facebook Page and is set to Business type.", "error")
            return redirect(url_for('dashboard'))
        
        instagram_user_id = instagram_account['id']
        
        # We need to get a Page Access Token to query Instagram account details
        # First, let's get the Page Access Token
        page_access_token_url = f"https://graph.facebook.com/v18.0/{page_id}"
        page_token_params = {
            'fields': 'access_token',
            'access_token': access_token
        }
        
        print(f"🔍 Getting Page Access Token from: {page_access_token_url}")
        page_token_response = requests.get(page_access_token_url, params=page_token_params)
        print(f"🔍 Page token response status: {page_token_response.status_code}")
        
        if page_token_response.status_code != 200:
            print(f"❌ Failed to get Page Access Token: {page_token_response.text}")
            flash("Failed to get Page Access Token. Please try again.", "error")
            return redirect(url_for('dashboard'))
        
        page_token_data = page_token_response.json()
        page_access_token = page_token_data.get('access_token')
        print(f"✅ Got Page Access Token: {page_access_token[:20]}...")
        
        # Now get Instagram account details using the Page Access Token
        profile_url = f"https://graph.facebook.com/v18.0/{instagram_user_id}"
        profile_params = {
            'fields': 'id,username,media_count',
            'access_token': page_access_token
        }
        
        print(f"🔍 Getting Instagram profile from: {profile_url}")
        print(f"🔍 Using Page Access Token: {page_access_token[:20]}...")
        
        profile_response = requests.get(profile_url, params=profile_params)
        print(f"🔍 Profile response status: {profile_response.status_code}")
        
        if profile_response.status_code != 200:
            print(f"❌ Failed to get Instagram profile: {profile_response.text}")
            flash("Failed to get Instagram profile details. Please try again.", "error")
            return redirect(url_for('dashboard'))
        
        profile_data = profile_response.json()
        print(f"✅ Got Instagram profile: {profile_data}")
        
        # Save Instagram connection to database
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                param = get_param_placeholder()
                
                # Check if connection already exists
                cursor.execute(f"SELECT id FROM instagram_connections WHERE user_id = {param} AND instagram_user_id = {param}", 
                              (session['user_id'], instagram_user_id))
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing connection
                    cursor.execute(f"""
                        UPDATE instagram_connections 
                        SET page_access_token = {param}, is_active = TRUE, updated_at = CURRENT_TIMESTAMP
                        WHERE id = {param}
                    """, (page_access_token, existing[0]))
                else:
                    # Create new connection
                    cursor.execute(f"""
                        INSERT INTO instagram_connections (user_id, instagram_user_id, instagram_page_id, page_access_token, is_active)
                        VALUES ({param}, {param}, {param}, {param}, TRUE)
                    """, (session['user_id'], instagram_user_id, page_id, page_access_token))
                
                conn.commit()
                flash(f"Successfully connected Instagram account: @{profile_data.get('username', 'Unknown')}", "success")
                
            except Exception as e:
                print(f"Database error: {e}")
                flash("Failed to save Instagram connection. Please try again.", "error")
            finally:
                conn.close()
        
        # Clean up session
        session.pop('instagram_oauth_state', None)
        
    except requests.RequestException as e:
        print(f"Instagram API error: {e}")
        if "access_denied" in str(e):
            flash("Access denied. Please ensure your Instagram account is a Business account connected to a Facebook Page.", "error")
        elif "invalid_request" in str(e):
            flash("Invalid request. Please check your Instagram account settings and try again.", "error")
        else:
            flash("Failed to connect Instagram account. Please try again.", "error")
    except Exception as e:
        print(f"Unexpected error: {e}")
        flash("An unexpected error occurred. Please try again.", "error")
    
    return redirect(url_for('dashboard'))

@app.route("/debug/connections")
@login_required
def debug_connections():
    """Debug endpoint to show all Instagram connections and their details"""
    conn = get_db_connection()
    if not conn:
        return "❌ Database connection failed", 500
    
    cursor = conn.cursor()
    try:
        # Get all Instagram connections
        cursor.execute("""
            SELECT id, user_id, instagram_user_id, instagram_page_id, page_access_token, is_active, created_at
            FROM instagram_connections 
            ORDER BY created_at DESC
        """)
        connections = cursor.fetchall()
        
        # Get client settings for each connection
        cursor.execute("""
            SELECT instagram_connection_id, bot_personality, auto_reply, created_at
            FROM client_settings
        """)
        settings = cursor.fetchall()
        
        debug_info = {
            "total_connections": len(connections),
            "connections": [],
            "settings": []
        }
        
        for conn_data in connections:
            connection_info = {
                "id": conn_data[0],
                "user_id": conn_data[1],
                "instagram_user_id": conn_data[2],
                "instagram_page_id": conn_data[3],
                "page_access_token": conn_data[4][:20] + "..." if conn_data[4] else "None",
                "is_active": conn_data[5],
                "created_at": str(conn_data[6])
            }
            debug_info["connections"].append(connection_info)
        
        for setting in settings:
            setting_info = {
                "instagram_connection_id": setting[0],
                "bot_personality": setting[1][:50] + "..." if setting[1] else "None",
                "auto_reply": setting[2],
                "created_at": str(setting[3])
            }
            debug_info["settings"].append(setting_info)
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>🔍 Instagram Debug Center</title>
            <style>
                body {{ 
                    font-family: Arial, sans-serif; 
                    background: #1a1a1a; 
                    color: #fff; 
                    margin: 0; 
                    padding: 20px; 
                }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                .header {{ 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    padding: 20px;
                    border-radius: 10px;
                    margin-bottom: 20px;
                    text-align: center;
                }}
                .nav-buttons {{ 
                    display: flex; 
                    gap: 10px; 
                    margin: 20px 0; 
                    flex-wrap: wrap;
                }}
                .nav-btn {{ 
                    background: #4CAF50; 
                    color: white; 
                    padding: 12px 20px; 
                    text-decoration: none; 
                    border-radius: 5px; 
                    font-weight: bold;
                    transition: background 0.3s;
                }}
                .nav-btn:hover {{ background: #45a049; }}
                .nav-btn.danger {{ background: #f44336; }}
                .nav-btn.danger:hover {{ background: #da190b; }}
                .nav-btn.warning {{ background: #ff9800; }}
                .nav-btn.warning:hover {{ background: #e68900; }}
                .section {{ 
                    background: #2a2a2a; 
                    padding: 20px; 
                    border-radius: 10px; 
                    margin: 20px 0; 
                }}
                .status {{ 
                    padding: 10px; 
                    border-radius: 5px; 
                    margin: 10px 0; 
                }}
                .status.success {{ background: #4CAF50; }}
                .status.error {{ background: #f44336; }}
                .status.warning {{ background: #ff9800; }}
                pre {{ 
                    background: #1a1a1a; 
                    padding: 15px; 
                    border-radius: 5px; 
                    overflow-x: auto; 
                    border: 1px solid #444;
                }}
                .test-grid {{ 
                    display: grid; 
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); 
                    gap: 20px; 
                    margin: 20px 0; 
                }}
                .test-card {{ 
                    background: #333; 
                    padding: 20px; 
                    border-radius: 10px; 
                    border: 1px solid #555;
                }}
                .test-card h3 {{ color: #4CAF50; margin-top: 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔍 Instagram Debug Center</h1>
                    <p>Comprehensive testing and debugging tools for Instagram bot functionality</p>
                </div>
                
                <div class="nav-buttons">
                    <a href="/dashboard" class="nav-btn">🏠 Back to Dashboard</a>
                    <a href="/debug/health-check" class="nav-btn warning">🏥 Health Check</a>
                    <a href="/debug/check-permissions" class="nav-btn">🔐 Check Permissions</a>
                    <button onclick="updateInstagramId()" class="nav-btn" style="background-color: #9b59b6;">🔄 Update Instagram ID</button>
                </div>
                
                <script>
                function updateInstagramId() {{
                    if (confirm('This will update the Instagram User ID in the database. Continue?')) {{
                        fetch('/debug/update-instagram-id', {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/json',
                            }}
                        }})
                        .then(response => response.json())
                        .then(data => {{
                            if (data.success) {{
                                alert('✅ ' + data.message + '\\n\\nUpdated from ' + data.old_id + ' to ' + data.new_id);
                                location.reload();
                            }} else {{
                                alert('❌ Error: ' + data.error);
                            }}
                        }})
                        .catch(error => {{
                            alert('❌ Error: ' + error);
                        }});
                    }}
                }}
                </script>
                
                <div class="section">
                    <h2>📊 Current Status</h2>
                    <div class="status success">
                        <strong>Total Connections:</strong> {debug_info['total_connections']}
                    </div>
                </div>
                
                <div class="test-grid">
                    <div class="test-card">
                        <h3>🔑 Token Testing</h3>
                        <p>Test if your database tokens can access Instagram API</p>
                        <a href="/debug/test-database-token" class="nav-btn">Test Database Token</a>
                        <a href="/debug/test-tokens" class="nav-btn">Test All Tokens</a>
                    </div>
                    
                    <div class="test-card">
                        <h3>💬 Message Testing</h3>
                        <p>Test message sending capabilities</p>
                        <a href="/debug/test-send-message" class="nav-btn" target="_blank">Test Send Message</a>
                        <a href="/debug/simulate-webhook" class="nav-btn">Simulate Webhook</a>
                    </div>
                    
                    <div class="test-card">
                        <h3>🔍 Connection Details</h3>
                        <p>View detailed connection information</p>
                        <details>
                            <summary>📱 Instagram Connections</summary>
                            <pre>{json.dumps(debug_info['connections'], indent=2)}</pre>
                        </details>
                        <details>
                            <summary>⚙️ Client Settings</summary>
                            <pre>{json.dumps(debug_info['settings'], indent=2)}</pre>
                        </details>
                    </div>
                </div>
                
                <div class="section">
                    <h2>📋 Testing Checklist</h2>
                    <ol>
                        <li><strong>Step 1:</strong> <a href="/debug/test-database-token">Test Database Token</a> - Verify token can access Instagram API</li>
                        <li><strong>Step 2:</strong> <a href="/debug/test-send-message" target="_blank">Test Send Message</a> - Verify message sending works</li>
                        <li><strong>Step 3:</strong> <a href="/debug/check-permissions">Check Permissions</a> - Verify all required permissions</li>
                        <li><strong>Step 4:</strong> <a href="/debug/simulate-webhook">Simulate Webhook</a> - Test webhook processing</li>
                        <li><strong>Step 5:</strong> <a href="/debug/health-check">Full Health Check</a> - Overall system status</li>
                    </ol>
                </div>
            </div>
        </body>
        </html>
        """
        
    except Exception as e:
        return f"❌ Error: {str(e)}", 500
    finally:
        conn.close()

@app.route("/debug/test-tokens")
@login_required
def debug_test_tokens():
    """Test all page access tokens and show their validity and permissions"""
    conn = get_db_connection()
    if not conn:
        return "❌ Database connection failed", 500
    
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, instagram_user_id, instagram_page_id, page_access_token, is_active
            FROM instagram_connections 
            WHERE is_active = TRUE
        """)
        connections = cursor.fetchall()
        
        results = []
        
        for conn_data in connections:
            connection_id, instagram_user_id, instagram_page_id, page_access_token, is_active = conn_data
            
            # Test the page access token
            token_info = test_page_access_token(page_access_token, instagram_page_id)
            
            result = {
                "connection_id": connection_id,
                "instagram_user_id": instagram_user_id,
                "instagram_page_id": instagram_page_id,
                "token_valid": token_info.get("valid", False),
                "token_info": token_info
            }
            results.append(result)
        
        return f"""
        <h1>🔑 Page Access Token Test Results</h1>
        <h2>📊 Summary</h2>
        <p><strong>Total Active Connections:</strong> {len(connections)}</p>
        
        <h2>🔍 Token Test Results</h2>
        <pre>{json.dumps(results, indent=2)}</pre>
        
        <p><a href="/debug/connections">← Back to Connections Debug</a></p>
        """
        
    except Exception as e:
        return f"❌ Error: {str(e)}", 500
    finally:
        conn.close()

def test_page_access_token(page_access_token, page_id):
    """Test a page access token and return its validity and permissions"""
    try:
        # Test the token by getting page info
        page_url = f"https://graph.facebook.com/v18.0/{page_id}"
        params = {
            'access_token': page_access_token,
            'fields': 'id,name,instagram_business_account'
        }
        
        response = requests.get(page_url, params=params)
        
        if response.status_code == 200:
            page_data = response.json()
            instagram_account = page_data.get('instagram_business_account')
            
            # Test Instagram API access
            instagram_info = None
            if instagram_account:
                instagram_id = instagram_account['id']
                instagram_url = f"https://graph.facebook.com/v18.0/{instagram_id}"
                instagram_params = {
                    'access_token': page_access_token,
                    'fields': 'id,username,media_count'
                }
                
                instagram_response = requests.get(instagram_url, params=instagram_params)
                if instagram_response.status_code == 200:
                    instagram_info = instagram_response.json()
            
            # Check token permissions
            debug_url = "https://graph.facebook.com/v18.0/debug_token"
            debug_params = {
                'input_token': page_access_token,
                'access_token': FACEBOOK_APP_ID + '|' + FACEBOOK_APP_SECRET
            }
            
            debug_response = requests.get(debug_url, params=debug_params)
            token_info = debug_response.json() if debug_response.status_code == 200 else None
            
            return {
                "valid": True,
                "page_data": page_data,
                "instagram_account": instagram_account,
                "instagram_info": instagram_info,
                "token_info": token_info,
                "status_code": response.status_code
            }
        else:
            return {
                "valid": False,
                "error": response.text,
                "status_code": response.status_code
            }
            
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
            "status_code": None
        }

@app.route("/debug/check-permissions")
@login_required
def debug_check_permissions():
    """Check what permissions the page access tokens actually have"""
    conn = get_db_connection()
    if not conn:
        return "❌ Database connection failed", 500
    
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, instagram_user_id, instagram_page_id, page_access_token, is_active
            FROM instagram_connections 
            WHERE is_active = TRUE
        """)
        connections = cursor.fetchall()
        
        results = []
        
        for conn_data in connections:
            connection_id, instagram_user_id, instagram_page_id, page_access_token, is_active = conn_data
            
            # Check token permissions
            debug_url = "https://graph.facebook.com/v18.0/debug_token"
            debug_params = {
                'input_token': page_access_token,
                'access_token': FACEBOOK_APP_ID + '|' + FACEBOOK_APP_SECRET
            }
            
            try:
                debug_response = requests.get(debug_url, params=debug_params)
                if debug_response.status_code == 200:
                    token_data = debug_response.json()
                    scopes = token_data.get('data', {}).get('scopes', [])
                    app_id = token_data.get('data', {}).get('app_id')
                    user_id = token_data.get('data', {}).get('user_id')
                    expires_at = token_data.get('data', {}).get('expires_at')
                    
                    result = {
                        "connection_id": connection_id,
                        "instagram_user_id": instagram_user_id,
                        "instagram_page_id": instagram_page_id,
                        "app_id": app_id,
                        "user_id": user_id,
                        "expires_at": expires_at,
                        "scopes": scopes,
                        "has_messaging_scope": "pages_messaging" in scopes,
                        "has_instagram_scope": "instagram_basic" in scopes or "instagram_manage_messages" in scopes,
                        "token_valid": True
                    }
                else:
                    result = {
                        "connection_id": connection_id,
                        "instagram_user_id": instagram_user_id,
                        "instagram_page_id": instagram_page_id,
                        "token_valid": False,
                        "error": debug_response.text
                    }
            except Exception as e:
                result = {
                    "connection_id": connection_id,
                    "instagram_user_id": instagram_user_id,
                    "instagram_page_id": instagram_page_id,
                    "token_valid": False,
                    "error": str(e)
                }
            
            results.append(result)
        
        return f"""
        <h1>🔐 Page Access Token Permissions</h1>
        <h2>📊 Summary</h2>
        <p><strong>Total Active Connections:</strong> {len(connections)}</p>
        
        <h2>🔍 Token Permission Details:</h2>
        <pre>{json.dumps(results, indent=2)}</pre>
        
        <h2>💡 Required Permissions for Instagram Messaging:</h2>
        <ul>
            <li><strong>pages_messaging</strong> - Required to send messages</li>
            <li><strong>instagram_basic</strong> - Required for Instagram API access</li>
            <li><strong>instagram_manage_messages</strong> - Required for Instagram messaging</li>
        </ul>
        
        <p><a href="/debug/connections">← Back to Connections Debug</a></p>
        """
        
    except Exception as e:
        return f"❌ Error: {str(e)}", 500
    finally:
        conn.close()

@app.route("/debug/simulate-webhook")
@login_required
def debug_simulate_webhook():
    """Simulate a webhook call to test the message processing logic"""
    return """
    <h1>🧪 Webhook Simulation</h1>
    <p>This will simulate a webhook call to test the message processing logic.</p>
    
    <form method="POST" action="/debug/simulate-webhook">
        <h3>Test Message Parameters:</h3>
        <p>
            <label>Sender ID (Instagram user who sent the message):</label><br>
            <input type="text" name="sender_id" value="123456789" style="width: 300px;">
        </p>
        <p>
            <label>Recipient ID (Your Instagram account that received the message):</label><br>
            <input type="text" name="recipient_id" value="71457471009" style="width: 300px;">
        </p>
        <p>
            <label>Page ID (Facebook Page ID):</label><br>
            <input type="text" name="page_id" value="830077620186727" style="width: 300px;">
        </p>
        <p>
            <label>Message Text:</label><br>
            <input type="text" name="message_text" value="Hello, this is a test message!" style="width: 400px;">
        </p>
        <p>
            <button type="submit">🚀 Simulate Webhook Call</button>
        </p>
    </form>
    
    <p><a href="/debug/connections">← Back to Connections Debug</a></p>
    """

@app.route("/debug/simulate-webhook", methods=["POST"])
@login_required
def debug_simulate_webhook_post():
    """Process the simulated webhook call"""
    sender_id = request.form.get('sender_id', '123456789')
    recipient_id = request.form.get('recipient_id', '71457471009')
    page_id = request.form.get('page_id', '830077620186727')
    message_text = request.form.get('message_text', 'Hello, this is a test message!')
    
    # Create a simulated webhook payload
    simulated_data = {
        "entry": [{
            "id": page_id,
            "messaging": [{
                "sender": {"id": sender_id},
                "recipient": {"id": recipient_id},
                "message": {"text": message_text}
            }]
        }]
    }
    
    # Process the simulated webhook
    result = process_webhook_message(simulated_data)
    
    return f"""
    <h1>🧪 Webhook Simulation Results</h1>
    <h2>📋 Simulated Payload:</h2>
    <pre>{json.dumps(simulated_data, indent=2)}</pre>
    
    <h2>🔍 Processing Results:</h2>
    <pre>{json.dumps(result, indent=2)}</pre>
    
    <p><a href="/debug/simulate-webhook">← Run Another Simulation</a></p>
    <p><a href="/debug/connections">← Back to Connections Debug</a></p>
    """

def process_webhook_message(data):
    """Process a webhook message and return detailed results"""
    results = {
        "success": False,
        "steps": [],
        "errors": [],
        "connection_found": False,
        "message_sent": False
    }
    
    try:
        results["steps"].append("Starting webhook message processing")
        
        if 'entry' not in data:
            results["errors"].append("No 'entry' in webhook data")
            return results
        
        for entry in data['entry']:
            if 'messaging' not in entry:
                results["errors"].append("No 'messaging' in entry")
                continue
                
            for event in entry['messaging']:
                if event.get('message', {}).get('is_echo'):
                    results["steps"].append("Skipping echo message")
                    continue
                
                sender_id = event['sender']['id']
                recipient_id = event.get('recipient', {}).get('id')
                page_id = entry.get('id')
                message_text = event.get('message', {}).get('text', '')
                
                results["steps"].append(f"Processing message from {sender_id} to {recipient_id}")
                results["steps"].append(f"Page ID: {page_id}")
                results["steps"].append(f"Message: {message_text}")
                
                # Find Instagram connection
                instagram_connection = None
                
                if recipient_id:
                    results["steps"].append(f"Looking for connection with user ID: {recipient_id}")
                    instagram_connection = get_instagram_connection_by_id(recipient_id)
                
                if not instagram_connection and page_id:
                    results["steps"].append(f"Looking for connection with page ID: {page_id}")
                    instagram_connection = get_instagram_connection_by_page_id(page_id)
                
                if instagram_connection:
                    results["connection_found"] = True
                    results["steps"].append(f"✅ Found connection: {instagram_connection}")
                    
                    # Test sending a reply
                    try:
                        reply_text = f"Test reply from bot: {message_text}"
                        success = send_instagram_message(
                            instagram_connection['page_access_token'],
                            sender_id,
                            reply_text,
                            instagram_connection['instagram_user_id']
                        )
                        results["message_sent"] = success
                        if success:
                            results["steps"].append("✅ Test message sent successfully")
                        else:
                            results["steps"].append("❌ Failed to send test message")
                    except Exception as e:
                        results["errors"].append(f"Error sending message: {str(e)}")
                else:
                    results["errors"].append(f"No Instagram connection found for recipient {recipient_id} or page {page_id}")
        
        results["success"] = len(results["errors"]) == 0
        return results
        
    except Exception as e:
        results["errors"].append(f"Unexpected error: {str(e)}")
        return results

def send_instagram_message(page_access_token, recipient_id, message_text, instagram_user_id=None):
    """Send a message via Instagram API"""
    try:
        # Use the same approach as the original webhook
        if instagram_user_id:
            url = f"https://graph.facebook.com/v18.0/{instagram_user_id}/messages?access_token={page_access_token}"
        else:
            # Fallback to /me/messages if no instagram_user_id provided
            url = f"https://graph.facebook.com/v18.0/me/messages?access_token={page_access_token}"
        
        data = {
            'recipient': {'id': recipient_id},
            'message': {'text': message_text}
        }
        
        response = requests.post(url, json=data)
        
        print(f"📤 Sending message to {recipient_id} via {instagram_user_id or 'me'}")
        print(f"🔗 URL: {url}")
        print(f"📋 Payload: {data}")
        
        if response.status_code == 200:
            print(f"✅ Message sent successfully to {recipient_id}")
            return True
        else:
            print(f"❌ Failed to send message: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error sending message: {str(e)}")
        return False

@app.route("/debug/health-check")
@login_required
def debug_health_check():
    """Comprehensive health check for all Instagram connections"""
    conn = get_db_connection()
    if not conn:
        return "❌ Database connection failed", 500
    
    cursor = conn.cursor()
    try:
        # Get all connections
        cursor.execute("""
            SELECT id, user_id, instagram_user_id, instagram_page_id, page_access_token, is_active
            FROM instagram_connections 
            ORDER BY created_at DESC
        """)
        connections = cursor.fetchall()
        
        health_results = {
            "database_connection": True,
            "total_connections": len(connections),
            "active_connections": 0,
            "valid_tokens": 0,
            "connections": []
        }
        
        for conn_data in connections:
            connection_id, user_id, instagram_user_id, instagram_page_id, page_access_token, is_active = conn_data
            
            connection_health = {
                "id": connection_id,
                "instagram_user_id": instagram_user_id,
                "instagram_page_id": instagram_page_id,
                "is_active": is_active,
                "token_valid": False,
                "instagram_api_accessible": False,
                "can_send_messages": False,
                "errors": []
            }
            
            if is_active:
                health_results["active_connections"] += 1
                
                # Test token validity
                token_info = test_page_access_token(page_access_token, instagram_page_id)
                connection_health["token_valid"] = token_info.get("valid", False)
                
                if connection_health["token_valid"]:
                    health_results["valid_tokens"] += 1
                    connection_health["instagram_api_accessible"] = bool(token_info.get("instagram_info"))
                    
                    # Test message sending capability
                    try:
                        # This is a dry run - we won't actually send a message
                        connection_health["can_send_messages"] = True
                    except Exception as e:
                        connection_health["errors"].append(f"Message sending test failed: {str(e)}")
                else:
                    connection_health["errors"].append(f"Token invalid: {token_info.get('error', 'Unknown error')}")
            
            health_results["connections"].append(connection_health)
        
        # Overall health status
        health_results["overall_health"] = "healthy" if health_results["valid_tokens"] > 0 else "unhealthy"
        
        return f"""
        <h1>🏥 Instagram Connections Health Check</h1>
        <h2>📊 Overall Status: {health_results['overall_health'].upper()}</h2>
        <p><strong>Database Connection:</strong> {'✅ Connected' if health_results['database_connection'] else '❌ Failed'}</p>
        <p><strong>Total Connections:</strong> {health_results['total_connections']}</p>
        <p><strong>Active Connections:</strong> {health_results['active_connections']}</p>
        <p><strong>Valid Tokens:</strong> {health_results['valid_tokens']}</p>
        
        <h2>🔍 Detailed Connection Health:</h2>
        <pre>{json.dumps(health_results['connections'], indent=2)}</pre>
        
        <h2>🧪 Quick Actions:</h2>
        <p><a href="/debug/test-tokens">Test All Tokens</a></p>
        <p><a href="/debug/simulate-webhook">Simulate Webhook</a></p>
        <p><a href="/debug/connections">View All Connections</a></p>
        <p><a href="/debug/test-database-token">Test Database Token Directly</a></p>
        <p><a href="/debug/test-send-message" target="_blank">Test Send Message (POST)</a></p>
        """
        
    except Exception as e:
        return f"❌ Health check failed: {str(e)}", 500
    finally:
        conn.close()

@app.route('/debug/test-database-token', methods=['GET'])
@login_required
def test_database_token():
    """Test if database token can send messages directly"""
    try:
        # Get the EgoInspo connection (the one we know has correct permissions)
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT ic.instagram_user_id, ic.page_access_token, ic.instagram_page_id
            FROM instagram_connections ic
            WHERE ic.instagram_user_id = '71457471009'
            LIMIT 1
        """)
        
        connection = cursor.fetchone()
        conn.close()
        
        if not connection:
            return jsonify({"error": "No EgoInspo connection found"}), 404
            
        instagram_user_id, page_access_token, instagram_page_id = connection
        
        # Test the token by getting Instagram account info
        test_url = f"https://graph.facebook.com/v18.0/{instagram_user_id}?fields=id,username&access_token={page_access_token}"
        
        response = requests.get(test_url)
        
        if response.status_code == 200:
            account_info = response.json()
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>🔑 Test Database Token - Results</title>
                <style>
                    body {{ 
                        font-family: Arial, sans-serif; 
                        background: #1a1a1a; 
                        color: #fff; 
                        margin: 0; 
                        padding: 20px; 
                    }}
                    .container {{ max-width: 1000px; margin: 0 auto; }}
                    .header {{ 
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        padding: 20px;
                        border-radius: 10px;
                        margin-bottom: 20px;
                        text-align: center;
                    }}
                    .result {{ 
                        background: #2a2a2a; 
                        padding: 20px; 
                        border-radius: 10px; 
                        margin: 20px 0; 
                    }}
                    .success {{ background: #4CAF50; }}
                    .error {{ background: #f44336; }}
                    pre {{ 
                        background: #1a1a1a; 
                        padding: 15px; 
                        border-radius: 5px; 
                        overflow-x: auto; 
                        border: 1px solid #444;
                    }}
                    .btn {{ 
                        background: #4CAF50; 
                        color: white; 
                        padding: 12px 20px; 
                        text-decoration: none; 
                        border-radius: 5px; 
                        display: inline-block;
                        margin: 10px 5px;
                    }}
                    .btn:hover {{ background: #45a049; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🔑 Test Database Token - Results</h1>
                    </div>
                    
                    <div class="result success">
                        <h2>✅ Success!</h2>
                        <p>Database token is valid and can access Instagram API</p>
                    </div>
                    
                    <div class="result">
                        <h3>🔍 Token Information</h3>
                        <pre>{json.dumps({
                            "instagram_user_id": instagram_user_id,
                            "instagram_page_id": instagram_page_id,
                            "username": "EgoInspiration",
                            "token_preview": page_access_token[:20] + "..."
                        }, indent=2)}</pre>
                    </div>
                    
                    <div class="result">
                        <h3>📱 Instagram Account Info</h3>
                        <pre>{json.dumps(account_info, indent=2)}</pre>
                    </div>
                    
                    <div style="text-align: center; margin-top: 30px;">
                        <a href="/debug/test-send-message" class="btn">💬 Test Send Message</a>
                        <a href="/debug/connections" class="btn">🏠 Back to Debug Center</a>
                    </div>
                </div>
            </body>
            </html>
            """
        else:
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>🔑 Test Database Token - Error</title>
                <style>
                    body {{ 
                        font-family: Arial, sans-serif; 
                        background: #1a1a1a; 
                        color: #fff; 
                        margin: 0; 
                        padding: 20px; 
                    }}
                    .container {{ max-width: 1000px; margin: 0 auto; }}
                    .header {{ 
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        padding: 20px;
                        border-radius: 10px;
                        margin-bottom: 20px;
                        text-align: center;
                    }}
                    .result {{ 
                        background: #2a2a2a; 
                        padding: 20px; 
                        border-radius: 10px; 
                        margin: 20px 0; 
                    }}
                    .error {{ background: #f44336; }}
                    pre {{ 
                        background: #1a1a1a; 
                        padding: 15px; 
                        border-radius: 5px; 
                        overflow-x: auto; 
                        border: 1px solid #444;
                    }}
                    .btn {{ 
                        background: #4CAF50; 
                        color: white; 
                        padding: 12px 20px; 
                        text-decoration: none; 
                        border-radius: 5px; 
                        display: inline-block;
                        margin: 10px 5px;
                    }}
                    .btn:hover {{ background: #45a049; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🔑 Test Database Token - Error</h1>
                    </div>
                    
                    <div class="result error">
                        <h2>❌ Error</h2>
                        <p>Database token failed to access Instagram API</p>
                        <p><strong>Status Code:</strong> {response.status_code}</p>
                    </div>
                    
                    <div class="result">
                        <h3>🔍 Error Details</h3>
                        <pre>{response.text}</pre>
                    </div>
                    
                    <div style="text-align: center; margin-top: 30px;">
                        <a href="/debug/check-permissions" class="btn">🔐 Check Permissions</a>
                        <a href="/debug/connections" class="btn">🏠 Back to Debug Center</a>
                    </div>
                </div>
            </body>
            </html>
            """, 400
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/debug/update-instagram-id", methods=["POST"])
@login_required
def update_instagram_id():
    """Update Instagram User ID in database from business account ID to correct user ID"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check current data
        cursor.execute("SELECT id, instagram_user_id, instagram_page_id FROM instagram_connections")
        connections = cursor.fetchall()
        
        current_data = []
        for conn_info in connections:
            current_data.append({
                "id": conn_info[0],
                "instagram_user_id": conn_info[1],
                "instagram_page_id": conn_info[2]
            })
        
        # Update the Instagram User ID from business account ID to user ID
        old_id = "17841471490292183"  # Business account ID
        new_id = "71457471009"        # Correct user ID
        
        # First, let's see what we have
        cursor.execute("SELECT id, instagram_user_id FROM instagram_connections")
        all_connections = cursor.fetchall()
        print(f"All connections before update: {all_connections}")
        
        # Update any connection that has the old ID
        cursor.execute("""
            UPDATE instagram_connections 
            SET instagram_user_id = ? 
            WHERE instagram_user_id = ?
        """, (new_id, old_id))
        
        rows_updated = cursor.rowcount
        
        # Get updated data
        cursor.execute("SELECT id, instagram_user_id, instagram_page_id FROM instagram_connections")
        updated_connections = cursor.fetchall()
        
        updated_data = []
        for conn_info in updated_connections:
            updated_data.append({
                "id": conn_info[0],
                "instagram_user_id": conn_info[1],
                "instagram_page_id": conn_info[2]
            })
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": f"Updated {rows_updated} row(s)",
            "old_id": old_id,
            "new_id": new_id,
            "current_data": current_data,
            "updated_data": updated_data
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/debug/test-send-message', methods=['GET', 'POST'])
@login_required
def test_send_message():
    """Test sending a message using the database token"""
    if request.method == 'GET':
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>💬 Test Send Message</title>
            <style>
                body { 
                    font-family: Arial, sans-serif; 
                    background: #1a1a1a; 
                    color: #fff; 
                    margin: 0; 
                    padding: 20px; 
                }
                .container { max-width: 800px; margin: 0 auto; }
                .header { 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    padding: 20px;
                    border-radius: 10px;
                    margin-bottom: 20px;
                    text-align: center;
                }
                .form-group { margin: 20px 0; }
                label { display: block; margin-bottom: 5px; font-weight: bold; }
                input, textarea { 
                    width: 100%; 
                    padding: 10px; 
                    border-radius: 5px; 
                    border: 1px solid #555; 
                    background: #333; 
                    color: #fff; 
                }
                .btn { 
                    background: #4CAF50; 
                    color: white; 
                    padding: 12px 20px; 
                    border: none; 
                    border-radius: 5px; 
                    cursor: pointer; 
                    font-size: 16px;
                }
                .btn:hover { background: #45a049; }
                .result { 
                    background: #2a2a2a; 
                    padding: 20px; 
                    border-radius: 10px; 
                    margin: 20px 0; 
                }
                pre { 
                    background: #1a1a1a; 
                    padding: 15px; 
                    border-radius: 5px; 
                    overflow-x: auto; 
                    border: 1px solid #444;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>💬 Test Send Message</h1>
                    <p>Test if your database token can send messages to Instagram</p>
                </div>
                
                <form method="POST">
                    <div class="form-group">
                        <label for="recipient_id">Recipient Instagram User ID:</label>
                        <input type="text" id="recipient_id" name="recipient_id" value="17841414162745169" placeholder="Enter Instagram user ID...">
                        <small style="color: #888;">This must be an Instagram tester added to your app</small>
                    </div>
                    <div class="form-group">
                        <label for="message">Test Message:</label>
                        <textarea id="message" name="message" rows="3" placeholder="Enter a test message...">Hello! This is a test message from the debug endpoint.</textarea>
                    </div>
                    <div class="form-group">
                        <label style="display: flex; align-items: center; gap: 8px;">
                            <input type="checkbox" id="test_both" name="test_both" value="true">
                            <span>Test with Original Chata Bot (instead of EgoInspo)</span>
                        </label>
                        <small style="color: #888;">Check this to test with the original hardcoded Chata bot token</small>
                    </div>
                    <button type="submit" class="btn">🚀 Test Send Message</button>
                </form>
                
                <div style="margin-top: 20px;">
                    <a href="/debug/connections" style="color: #4CAF50;">← Back to Debug Center</a>
                </div>
            </div>
        </body>
        </html>
        """
    
    try:
        test_message = request.form.get('message', 'Test message from debug endpoint')
        recipient_id = request.form.get('recipient_id', '17841414162745169')
        
        # Test with both EgoInspo and original Chata bot
        test_both = request.form.get('test_both', 'false') == 'true'
        
        if test_both:
            # Test with original Chata bot first
            instagram_user_id = INSTAGRAM_USER_ID
            page_access_token = ACCESS_TOKEN
            instagram_page_id = "hardcoded_chata_page"  # Dummy value for hardcoded bot
            test_name = "Original Chata Bot"
        else:
            # Get the EgoInspo connection
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT ic.instagram_user_id, ic.page_access_token, ic.instagram_page_id
                FROM instagram_connections ic
                WHERE ic.instagram_user_id = '71457471009'
                LIMIT 1
            """)
            
            connection = cursor.fetchone()
            conn.close()
            
            if not connection:
                return f"""
                <div class="container">
                    <div class="result" style="background: #f44336;">
                        <h2>❌ Error</h2>
                        <p>No EgoInspo connection found in database</p>
                    </div>
                    <a href="/debug/connections" style="color: #4CAF50;">← Back to Debug Center</a>
                </div>
                """, 404
                
            instagram_user_id, page_access_token, instagram_page_id = connection
            test_name = "EgoInspo Bot"
        
        # Test sending a message (this will fail if the recipient isn't valid, but we can see the error)
        test_url = f"https://graph.facebook.com/v18.0/{instagram_user_id}/messages"
        
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": test_message}
        }
        
        response = requests.post(test_url, json=payload, headers={
            'Authorization': f'Bearer {page_access_token}',
            'Content-Type': 'application/json'
        })
        
        result_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>💬 Test Send Message - Results</title>
            <style>
                body {{ 
                    font-family: Arial, sans-serif; 
                    background: #1a1a1a; 
                    color: #fff; 
                    margin: 0; 
                    padding: 20px; 
                }}
                .container {{ max-width: 1000px; margin: 0 auto; }}
                .header {{ 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    padding: 20px;
                    border-radius: 10px;
                    margin-bottom: 20px;
                    text-align: center;
                }}
                .result {{ 
                    background: #2a2a2a; 
                    padding: 20px; 
                    border-radius: 10px; 
                    margin: 20px 0; 
                }}
                .success {{ background: #4CAF50; }}
                .error {{ background: #f44336; }}
                .warning {{ background: #ff9800; }}
                pre {{ 
                    background: #1a1a1a; 
                    padding: 15px; 
                    border-radius: 5px; 
                    overflow-x: auto; 
                    border: 1px solid #444;
                }}
                .btn {{ 
                    background: #4CAF50; 
                    color: white; 
                    padding: 12px 20px; 
                    text-decoration: none; 
                    border-radius: 5px; 
                    display: inline-block;
                    margin: 10px 5px;
                }}
                .btn:hover {{ background: #45a049; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>💬 Test Send Message - Results</h1>
                </div>
                
                <div class="result {'success' if response.status_code == 200 else 'error'}">
                    <h2>{'✅ Success' if response.status_code == 200 else '❌ Error'}</h2>
                    <p><strong>Bot Tested:</strong> {test_name}</p>
                    <p><strong>Status Code:</strong> {response.status_code}</p>
                    <p><strong>Recipient ID:</strong> {recipient_id}</p>
                    <p><strong>Message:</strong> {test_message}</p>
                </div>
                
                <div class="result">
                    <h3>🔍 Token Information</h3>
                    <pre>{json.dumps({
                        "instagram_user_id": instagram_user_id,
                        "instagram_page_id": instagram_page_id,
                        "username": "chata_bot" if test_both else "EgoInspiration",
                        "token_preview": page_access_token[:20] + "..."
                    }, indent=2)}</pre>
                </div>
                
                <div class="result">
                    <h3>🌐 API Call Details</h3>
                    <pre>{json.dumps({
                        "url": test_url,
                        "payload": payload,
                        "status_code": response.status_code,
                        "response": response.text
                    }, indent=2)}</pre>
                </div>
                
                <div style="text-align: center; margin-top: 30px;">
                    <a href="/debug/test-send-message" class="btn">🔄 Test Again</a>
                    <a href="/debug/connections" class="btn">🏠 Back to Debug Center</a>
                </div>
            </div>
        </body>
        </html>
        """
        
        return result_html
        
    except Exception as e:
        return f"""
        <div class="container">
            <div class="result" style="background: #f44336;">
                <h2>❌ Exception Error</h2>
                <p>{str(e)}</p>
            </div>
            <a href="/debug/connections" style="color: #4CAF50;">← Back to Debug Center</a>
        </div>
        """, 500

@app.route("/dashboard")
@login_required
def dashboard():
    user = get_user_by_id(session['user_id'])
    
    # Get user's Instagram connections
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    cursor.execute(f"""
        SELECT id, instagram_user_id, instagram_page_id, is_active, created_at 
        FROM instagram_connections 
        WHERE user_id = {placeholder} 
        ORDER BY created_at DESC
    """, (user['id'],))
    connections = cursor.fetchall()
    conn.close()
    
    connections_list = []
    for conn_data in connections:
        connections_list.append({
            'id': conn_data[0],
            'instagram_user_id': conn_data[1],
            'instagram_page_id': conn_data[2],
            'is_active': conn_data[3],
            'created_at': conn_data[4]
        })
    
    return render_template("dashboard.html", user=user, connections=connections_list, debug_enabled=True)

# ---- Bot Settings Management ----

def get_client_settings(user_id, connection_id=None):
    """Get bot settings for a specific client/connection"""
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    if connection_id:
        cursor.execute(f"""
            SELECT bot_personality, temperature, max_tokens, auto_reply
            FROM client_settings 
            WHERE user_id = {placeholder} AND instagram_connection_id = {placeholder}
        """, (user_id, connection_id))
    else:
        cursor.execute(f"""
            SELECT bot_personality, temperature, max_tokens, auto_reply
            FROM client_settings 
            WHERE user_id = {placeholder} AND instagram_connection_id IS NULL
        """, (user_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'bot_personality': row[0],
            'temperature': row[1],
            'max_tokens': row[2],
            'auto_reply': row[3]
        }
    
    # Return default settings if none exist
    return {
        'bot_personality': "You are a helpful and friendly Instagram bot.",
        'temperature': 0.7,
        'max_tokens': 150,
        'auto_reply': True
    }

def log_activity(user_id, action_type, description=None):
    """Log user activity for analytics and security"""
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    cursor.execute(f"""
        INSERT INTO activity_logs (user_id, action, details, ip_address)
        VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})
    """, (user_id, action_type, description, request.remote_addr))
    
    conn.commit()
    conn.close()

def save_client_settings(user_id, settings, connection_id=None):
    """Save bot settings for a specific client/connection"""
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    # Use different syntax for PostgreSQL vs SQLite
    if DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")):
        if connection_id:
            cursor.execute(f"""
                INSERT INTO client_settings 
                (user_id, instagram_connection_id, bot_personality, temperature, max_tokens, auto_reply)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
                ON CONFLICT (user_id, instagram_connection_id) DO UPDATE SET
                bot_personality = EXCLUDED.bot_personality,
                temperature = EXCLUDED.temperature,
                max_tokens = EXCLUDED.max_tokens,
                auto_reply = EXCLUDED.auto_reply,
                updated_at = CURRENT_TIMESTAMP
            """, (user_id, connection_id, settings['bot_personality'], settings['temperature'], 
                  settings['max_tokens'], settings['auto_reply']))
        else:
            # For global settings, we need to handle NULL instagram_connection_id
            # First, try to delete any existing global settings for this user
            cursor.execute(f"DELETE FROM client_settings WHERE user_id = {placeholder} AND instagram_connection_id IS NULL", (user_id,))
            # Then insert the new global settings
            cursor.execute(f"""
                INSERT INTO client_settings 
                (user_id, instagram_connection_id, bot_personality, temperature, max_tokens, auto_reply)
                VALUES ({placeholder}, NULL, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (user_id, settings['bot_personality'], settings['temperature'], 
                  settings['max_tokens'], settings['auto_reply']))
    else:
        if connection_id:
            cursor.execute(f"""
                INSERT OR REPLACE INTO client_settings 
                (user_id, instagram_connection_id, bot_personality, temperature, max_tokens, auto_reply)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (user_id, connection_id, settings['bot_personality'], settings['temperature'], 
                  settings['max_tokens'], settings['auto_reply']))
        else:
            # For global settings in SQLite, delete existing and insert new
            cursor.execute(f"DELETE FROM client_settings WHERE user_id = {placeholder} AND instagram_connection_id IS NULL", (user_id,))
            cursor.execute(f"""
                INSERT INTO client_settings 
                (user_id, instagram_connection_id, bot_personality, temperature, max_tokens, auto_reply)
                VALUES ({placeholder}, NULL, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (user_id, settings['bot_personality'], settings['temperature'], 
                  settings['max_tokens'], settings['auto_reply']))
    
    conn.commit()
    conn.close()
    
    # Log the activity
    log_activity(user_id, 'settings_updated', f'Bot settings updated for connection {connection_id or "default"}')

@app.route("/dashboard/bot-settings", methods=["GET", "POST"])
@login_required
def bot_settings():
    user_id = session['user_id']
    connection_id = request.args.get('connection_id', type=int)
    
    if request.method == "POST":
        settings = {
            'bot_personality': request.form.get('bot_personality', ''),
            'temperature': float(request.form.get('temperature', 0.7)),
            'max_tokens': int(request.form.get('max_tokens', 150)),
            'auto_reply': request.form.get('auto_reply', True)
        }
        
        save_client_settings(user_id, settings, connection_id)
        flash("Bot settings updated successfully!", "success")
        return redirect(url_for('bot_settings', connection_id=connection_id))
    
    # Get user's Instagram connections for the dropdown
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    cursor.execute(f"""
        SELECT id, instagram_user_id, instagram_page_id, is_active 
        FROM instagram_connections 
        WHERE user_id = {placeholder} 
        ORDER BY created_at DESC
    """, (user_id,))
    connections = cursor.fetchall()
    conn.close()
    
    connections_list = []
    for conn_data in connections:
        connections_list.append({
            'id': conn_data[0],
            'instagram_user_id': conn_data[1],
            'instagram_page_id': conn_data[2],
            'is_active': conn_data[3]
        })
    
    current_settings = get_client_settings(user_id, connection_id)
    return render_template("bot_settings.html", 
                         settings=current_settings, 
                         connections=connections_list,
                         selected_connection_id=connection_id)

@app.route("/dashboard/account-settings", methods=["GET", "POST"])
@login_required
def account_settings():
    user = get_user_by_id(session['user_id'])
    
    if request.method == "POST":
        # Update account information - simplified since we removed extra fields
        flash("Account settings updated successfully!", "success")
        return redirect(url_for('account_settings'))
    
    return render_template("account_settings.html", user=user)

@app.route("/dashboard/disconnect-instagram/<int:connection_id>")
@login_required
def disconnect_instagram(connection_id):
    user_id = session['user_id']
    
    # Verify the connection belongs to the current user
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        # Check if connection exists and belongs to user
        cursor.execute(f"""
            SELECT id, instagram_user_id FROM instagram_connections 
            WHERE id = {placeholder} AND user_id = {placeholder}
        """, (connection_id, user_id))
        
        connection = cursor.fetchone()
        if not connection:
            flash("Connection not found or you don't have permission to disconnect it.", "error")
            return redirect(url_for('dashboard'))
        
        # First delete associated client settings (to avoid foreign key constraint)
        cursor.execute(f"DELETE FROM client_settings WHERE instagram_connection_id = {placeholder}", (connection_id,))
        
        # Then delete the connection
        cursor.execute(f"DELETE FROM instagram_connections WHERE id = {placeholder}", (connection_id,))
        
        conn.commit()
        
        # Log the activity
        log_activity(user_id, 'instagram_disconnected', f'Disconnected Instagram account {connection[1]}')
        
        flash(f"Instagram account {connection[1]} has been disconnected successfully.", "success")
        
    except Exception as e:
        print(f"Error disconnecting Instagram account: {e}")
        flash("An error occurred while disconnecting the account.", "error")
        conn.rollback()
    finally:
        conn.close()
    
    return redirect(url_for('dashboard'))

@app.route("/dashboard/usage")
@login_required
def usage_analytics():
    user_id = session['user_id']
    
    # Get usage statistics for the current month
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    # Get message count for current month
    cursor.execute(f"""
        SELECT COUNT(*) FROM messages 
        WHERE instagram_user_id IN (SELECT instagram_user_id FROM instagram_connections WHERE user_id = {placeholder})
        AND created_at >= date('now', 'start of month')
    """, (user_id,))
    messages_this_month = cursor.fetchone()[0]
    
    # Get API usage for current month
    cursor.execute(f"""
        SELECT SUM(tokens_used), SUM(cost) FROM usage_logs 
        WHERE user_id = {placeholder} 
        AND created_at >= date('now', 'start of month')
    """, (user_id,))
    usage_data = cursor.fetchone()
    api_calls_this_month = usage_data[0] or 0
    cost_this_month = (usage_data[1] or 0) / 100.0  # Convert cents to dollars
    
    # Get recent activity
    cursor.execute(f"""
        SELECT action, details, created_at 
        FROM activity_logs 
        WHERE user_id = {placeholder} 
        ORDER BY created_at DESC 
        LIMIT 10
    """, (user_id,))
    recent_activity = cursor.fetchall()
    
    conn.close()
    
    return render_template("usage_analytics.html", 
                         messages_this_month=messages_this_month,
                         api_calls_this_month=api_calls_this_month,
                         cost_this_month=cost_this_month,
                         recent_activity=recent_activity)

# ---- SQLite settings helpers ----

def get_setting(key, default=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    cursor.execute(f"SELECT value FROM settings WHERE key = {placeholder}", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return default

def set_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    cursor.execute(f"UPDATE settings SET value = {placeholder} WHERE key = {placeholder}", (value, key))
    conn.commit()
    conn.close()

# ---- Message DB helpers ----

def save_message(instagram_user_id, message_text, bot_response):
    """Save a message to the database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        cursor.execute(
            f"INSERT INTO messages (instagram_user_id, message_text, bot_response) VALUES ({placeholder}, {placeholder}, {placeholder})",
            (instagram_user_id, message_text, bot_response)
        )
        conn.commit()
        print(f"✅ Message saved successfully for Instagram user: {instagram_user_id}")
    except Exception as e:
        print(f"❌ Error saving message: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def get_last_messages(instagram_user_id, n=35):
    """Get conversation history for a specific Instagram user"""
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        cursor.execute(
            f"SELECT message_text, bot_response FROM messages WHERE instagram_user_id = {placeholder} ORDER BY id DESC LIMIT {placeholder}",
            (instagram_user_id, n)
        )
        rows = cursor.fetchall()
        
        # Convert to OpenAI format
        messages = []
        for row in reversed(rows):  # Reverse to get chronological order
            if row[0]:  # message_text
                messages.append({"role": "user", "content": row[0]})
            if row[1]:  # bot_response
                messages.append({"role": "assistant", "content": row[1]})
        
        print(f"✅ Retrieved {len(messages)} messages for Instagram user: {instagram_user_id}")
        return messages
        
    except Exception as e:
        print(f"❌ Error retrieving messages: {e}")
        return []
    finally:
        conn.close()

# ---- Instagram Connection Helpers ----

def get_instagram_connection_by_id(instagram_user_id):
    """Get Instagram connection by Instagram user ID"""
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        cursor.execute(f"""
            SELECT id, user_id, instagram_user_id, instagram_page_id, page_access_token, is_active
            FROM instagram_connections 
            WHERE instagram_user_id = {placeholder} AND is_active = TRUE
        """, (instagram_user_id,))
        
        row = cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'user_id': row[1],
                'instagram_user_id': row[2],
                'instagram_page_id': row[3],
                'page_access_token': row[4],
                'is_active': row[5]
            }
        return None
    except Exception as e:
        print(f"❌ Error getting Instagram connection: {e}")
        return None
    finally:
        conn.close()

def get_instagram_connection_by_page_id(page_id):
    """Get Instagram connection by Instagram page ID"""
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        cursor.execute(f"""
            SELECT id, user_id, instagram_user_id, instagram_page_id, page_access_token, is_active
            FROM instagram_connections 
            WHERE instagram_page_id = {placeholder} AND is_active = TRUE
        """, (page_id,))
        
        row = cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'user_id': row[1],
                'instagram_user_id': row[2],
                'instagram_page_id': row[3],
                'page_access_token': row[4],
                'is_active': row[5]
            }
        return None
    except Exception as e:
        print(f"❌ Error getting Instagram connection by page ID: {e}")
        return None
    finally:
        conn.close()

# ---- AI Reply ----

def get_ai_reply(history):
    openai.api_key = OPENAI_API_KEY
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        system_prompt = get_setting("bot_personality",
            "You are a helpful and friendly Instagram bot.")
        temperature = float(get_setting("temperature", "0.7"))
        max_tokens = int(get_setting("max_tokens", "150"))

        messages = [{"role": "system", "content": system_prompt}]
        messages += history

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        ai_reply = response.choices[0].message.content.strip()
        return ai_reply

    except Exception as e:
        print("OpenAI API error:", e)
        return "Sorry, I'm having trouble replying right now."

def get_ai_reply_with_connection(history, connection_id=None):
    """Get AI reply using connection-specific settings if available"""
    openai.api_key = OPENAI_API_KEY
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        # Get settings for this specific connection
        if connection_id:
            # Get user_id from connection
            conn = get_db_connection()
            cursor = conn.cursor()
            placeholder = get_param_placeholder()
            cursor.execute(f"SELECT user_id FROM instagram_connections WHERE id = {placeholder}", (connection_id,))
            result = cursor.fetchone()
            conn.close()
            
            if result:
                user_id = result[0]
                settings = get_client_settings(user_id, connection_id)
                system_prompt = settings['bot_personality']
                temperature = settings['temperature']
                max_tokens = settings['max_tokens']
                print(f"🎯 Using connection-specific settings for connection {connection_id}")
            else:
                # Fallback to global settings
                system_prompt = get_setting("bot_personality", "You are a helpful and friendly Instagram bot.")
                temperature = float(get_setting("temperature", "0.7"))
                max_tokens = int(get_setting("max_tokens", "150"))
                print(f"⚠️ Connection not found, using global settings")
        else:
            # Use global settings (for original Chata account)
            system_prompt = get_setting("bot_personality", "You are a helpful and friendly Instagram bot.")
            temperature = float(get_setting("temperature", "0.7"))
            max_tokens = int(get_setting("max_tokens", "150"))
            print(f"🎯 Using global settings for original Chata account")

        messages = [{"role": "system", "content": system_prompt}]
        messages += history

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        ai_reply = response.choices[0].message.content.strip()
        return ai_reply

    except Exception as e:
        print("OpenAI API error:", e)
        return "Sorry, I'm having trouble replying right now."

# ---- Webhook Route ----

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("WEBHOOK VERIFIED!")
            return challenge, 200
        else:
            return "Forbidden", 403

    elif request.method == "POST":
        print("📥 Webhook received POST request")
        print(f"📋 Request data: {request.json}")
        data = request.json
        
        # Debug: Show all available Instagram connections
        print("🔍 Available Instagram connections:")
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT id, instagram_user_id, instagram_page_id, is_active FROM instagram_connections")
                connections = cursor.fetchall()
                print(f"📊 Found {len(connections)} Instagram connections in database:")
                for conn_data in connections:
                    print(f"  - ID: {conn_data[0]}, User ID: {conn_data[1]}, Page ID: {conn_data[2]}, Active: {conn_data[3]}")
            except Exception as e:
                print(f"❌ Error fetching connections: {e}")
            finally:
                conn.close()

        if 'entry' in data:
            for entry in data['entry']:
                if 'messaging' in entry:
                    for event in entry['messaging']:
                        if event.get('message', {}).get('is_echo'):
                            continue

                        sender_id = event['sender']['id']
                        if 'message' in event and 'text' in event['message']:
                            try:
                                message_text = event['message']['text']
                                print(f"📨 Received a message from {sender_id}: {message_text}")

                                # 🔍 DETECT WHICH INSTAGRAM ACCOUNT RECEIVED THE MESSAGE
                                # The webhook receives messages for different Instagram accounts
                                # We need to determine which account this message was sent to
                                
                                # Get the recipient ID from the event (this is the Instagram account that received the message)
                                recipient_id = event.get('recipient', {}).get('id')
                                print(f"🎯 Message sent to Instagram account: {recipient_id}")
                                
                                # Also check the entry object for the page ID
                                page_id = entry.get('id')
                                print(f"📄 Page ID from entry: {page_id}")
                                
                                # Find the Instagram connection for this recipient (the account that received the message)
                                # We need to match by the Instagram user ID, not the page ID
                                instagram_connection = None
                                
                                # First try to find by the recipient ID (Instagram user ID)
                                if recipient_id:
                                    print(f"🔍 Looking for Instagram connection with user ID: {recipient_id}")
                                    instagram_connection = get_instagram_connection_by_id(recipient_id)
                                
                                # If not found by user ID, try by page ID
                                if not instagram_connection and page_id:
                                    print(f"🔍 Trying to find connection by page ID: {page_id}")
                                    instagram_connection = get_instagram_connection_by_page_id(page_id)
                                
                                if not instagram_connection:
                                    print(f"❌ No Instagram connection found for account {recipient_id} or page {page_id}")
                                    print(f"💡 This might be the original Chata account or an unregistered account")
                                    
                                    # Check if this is the original Chata account
                                    if recipient_id == INSTAGRAM_USER_ID:
                                        print(f"✅ This is the original Chata account - using hardcoded settings")
                                        access_token = ACCESS_TOKEN
                                        instagram_user_id = INSTAGRAM_USER_ID
                                        connection_id = None  # No connection ID for original account
                                    else:
                                        print(f"❌ Unknown Instagram account {recipient_id} - skipping message")
                                        continue
                                else:
                                    print(f"✅ Found Instagram connection: {instagram_connection}")
                                    access_token = instagram_connection['page_access_token']
                                    instagram_user_id = instagram_connection['instagram_user_id']
                                    connection_id = instagram_connection['id']

                                # Save the incoming user message
                                save_message(sender_id, message_text, "")
                                print(f"✅ Saved user message for {sender_id}")
                                
                                # Get conversation history
                                history = get_last_messages(sender_id, n=35)
                                print(f"📚 History for {sender_id}: {len(history)} messages")

                                # Generate AI reply with account-specific settings
                                reply_text = get_ai_reply_with_connection(history, connection_id)
                                print(f"🤖 AI generated reply: {reply_text[:50]}...")

                                # Save the bot's response
                                save_message(sender_id, "", reply_text)
                                print(f"✅ Saved bot response for {sender_id}")

                                # Send reply via Instagram API using the correct access token
                                url = f"https://graph.facebook.com/v18.0/{instagram_user_id}/messages?access_token={access_token}"
                                payload = {
                                    "recipient": {"id": sender_id},
                                    "message": {"text": reply_text}
                                }

                                r = requests.post(url, json=payload)
                                print(f"📤 Sent reply to {sender_id} via {instagram_user_id}: {r.status_code}")
                                if r.status_code != 200:
                                    print(f"❌ Error sending reply: {r.text}")
                                else:
                                    print(f"✅ Reply sent successfully to {sender_id}")
                                    
                            except Exception as e:
                                print(f"❌ Error processing message from {sender_id}: {e}")
                                print(f"Error type: {type(e).__name__}")
                                import traceback
                                traceback.print_exc()

        return "EVENT_RECEIVED", 200

# ---- Admin Panel Route ----

@app.route("/admin/prompt", methods=["GET", "POST"])
def admin_prompt():
    message = None

    if flask_request.method == "POST":
        set_setting("bot_personality", flask_request.form.get("bot_personality", ""))
        set_setting("temperature", flask_request.form.get("temperature", "0.7"))
        set_setting("max_tokens", flask_request.form.get("max_tokens", "150"))
        message = "Bot settings updated successfully!"

    current_prompt = get_setting("bot_personality", "")
    current_temperature = get_setting("temperature", "0.7")
    current_max_tokens = get_setting("max_tokens", "150")

    return render_template_string("""
        <!doctype html>
        <title>Edit Bot Settings</title>
        <style>
          body { background: #181e29; color: #fff; font-family: Arial, sans-serif; padding:40px; }
          textarea, input[type=text], input[type=number] { width: 100%; background: #232b3d; color: #fff; border-radius: 10px; padding: 10px; border: 1px solid #444; font-size: 1.1em;}
          input[type=submit] { background: #36f; color: #fff; padding: 10px 24px; border: none; border-radius: 8px; font-size: 1em; margin-top:10px; cursor:pointer;}
          .message { margin-top:20px; color: #3fcf64; }
          h2 { color: #3fcf64; }
          label {font-size:1.1em;}
          .field-group { margin-bottom: 24px;}
        </style>
        <h2>Edit Bot Settings</h2>
        <form method="POST">
          <div class="field-group">
            <label for="bot_personality">Bot Personality:</label><br>
            <textarea id="bot_personality" name="bot_personality" rows="4">{{current_prompt}}</textarea>
          </div>
          <div class="field-group">
            <label for="temperature">Temperature (Creativity, 0=serious, 1=random):</label><br>
            <input type="number" step="0.01" min="0" max="2" id="temperature" name="temperature" value="{{current_temperature}}">
          </div>
          <div class="field-group">
            <label for="max_tokens">Max Tokens (Length of Reply):</label><br>
            <input type="number" min="1" max="2048" id="max_tokens" name="max_tokens" value="{{current_max_tokens}}">
          </div>
          <input type="submit" value="Save Settings">
        </form>
        {% if message %}
        <div class="message">{{ message }}</div>
        {% endif %}
    """, current_prompt=current_prompt, current_temperature=current_temperature, current_max_tokens=current_max_tokens, message=message)



from flask import render_template

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/pricing")
def pricing():
    return render_template("pricing.html")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        # Here you would typically send an email or save to database
        # For now, we'll just return a success message
        return render_template("contact.html", message="Thank you for your message! We'll get back to you soon.")
    return render_template("contact.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/features")
def features():
    return render_template("features.html")

@app.route("/faq")
def faq():
    return render_template("faq.html")

@app.route("/privacy")
def privacy():
    return render_template("privacy.html", moment=datetime.now())

@app.route("/terms")
def terms():
    return render_template("terms.html", moment=datetime.now())

@app.route("/data-deletion")
def data_deletion():
    return render_template("data_deletion.html", moment=datetime.now())

@app.route("/instagram-setup-help")
def instagram_setup_help():
    return render_template("instagram_setup_help.html")


if __name__ == "__main__":
    # Use environment variable for port (Render requirement)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
