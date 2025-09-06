from dotenv import load_dotenv
import os
from flask import Flask, request, render_template, redirect, url_for, flash, session
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

# Instagram OAuth Configuration
INSTAGRAM_APP_ID = os.getenv("INSTAGRAM_APP_ID")
INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET")
INSTAGRAM_REDIRECT_URI = os.getenv("INSTAGRAM_REDIRECT_URI", "https://chata-bot.onrender.com/auth/instagram/callback")

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
        conn.rollback()
        return False
    finally:
        conn.close()

# Initialize database on app startup
print("🚀 Starting Chata application...")
if init_database():
    print("✅ Database initialized successfully")
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
    if not INSTAGRAM_APP_ID:
        flash("Instagram OAuth not configured. Please contact support.", "error")
        return redirect(url_for('dashboard'))
    
    # Generate state parameter for security
    state = secrets.token_urlsafe(32)
    session['instagram_oauth_state'] = state
    
    # Build Instagram OAuth URL
    oauth_url = (
        f"https://api.instagram.com/oauth/authorize"
        f"?client_id={INSTAGRAM_APP_ID}"
        f"&redirect_uri={INSTAGRAM_REDIRECT_URI}"
        f"&scope=user_profile,user_media"
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
        # Exchange code for access token
        token_url = "https://api.instagram.com/oauth/access_token"
        token_data = {
            'client_id': INSTAGRAM_APP_ID,
            'client_secret': INSTAGRAM_APP_SECRET,
            'grant_type': 'authorization_code',
            'redirect_uri': INSTAGRAM_REDIRECT_URI,
            'code': code
        }
        
        response = requests.post(token_url, data=token_data)
        response.raise_for_status()
        token_info = response.json()
        
        access_token = token_info.get('access_token')
        user_id = token_info.get('user_id')
        
        if not access_token or not user_id:
            flash("Failed to get Instagram access token.", "error")
            return redirect(url_for('dashboard'))
        
        # Get user profile information
        profile_url = f"https://graph.instagram.com/{user_id}"
        profile_params = {
            'fields': 'id,username,account_type,media_count',
            'access_token': access_token
        }
        
        profile_response = requests.get(profile_url, params=profile_params)
        profile_response.raise_for_status()
        profile_data = profile_response.json()
        
        # Save Instagram connection to database
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                param = get_param_placeholder()
                
                # Check if connection already exists
                cursor.execute(f"SELECT id FROM instagram_connections WHERE user_id = {param} AND instagram_user_id = {param}", 
                              (session['user_id'], user_id))
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing connection
                    cursor.execute(f"""
                        UPDATE instagram_connections 
                        SET page_access_token = {param}, is_active = TRUE, updated_at = CURRENT_TIMESTAMP
                        WHERE id = {param}
                    """, (access_token, existing[0]))
                else:
                    # Create new connection
                    cursor.execute(f"""
                        INSERT INTO instagram_connections (user_id, instagram_user_id, instagram_page_id, page_access_token, is_active)
                        VALUES ({param}, {param}, {param}, {param}, TRUE)
                    """, (session['user_id'], user_id, user_id, access_token))
                
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
        flash("Failed to connect Instagram account. Please try again.", "error")
    except Exception as e:
        print(f"Unexpected error: {e}")
        flash("An unexpected error occurred. Please try again.", "error")
    
    return redirect(url_for('dashboard'))

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
    
    return render_template("dashboard.html", user=user, connections=connections_list)

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
                auto_reply = EXCLUDED.auto_reply
            """, (user_id, connection_id, settings['bot_personality'], settings['temperature'], 
                  settings['max_tokens'], settings['auto_reply']))
        else:
            cursor.execute(f"""
                INSERT INTO client_settings 
                (user_id, bot_personality, temperature, max_tokens, auto_reply)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
                ON CONFLICT (user_id) DO UPDATE SET
                bot_personality = EXCLUDED.bot_personality,
                temperature = EXCLUDED.temperature,
                max_tokens = EXCLUDED.max_tokens,
                auto_reply = EXCLUDED.auto_reply
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
            cursor.execute(f"""
                INSERT OR REPLACE INTO client_settings 
                (user_id, bot_personality, temperature, max_tokens, auto_reply)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
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
    
    if request.method == "POST":
        settings = {
            'bot_personality': request.form.get('bot_personality', ''),
            'temperature': float(request.form.get('temperature', 0.7)),
            'max_tokens': int(request.form.get('max_tokens', 150)),
            'auto_reply': request.form.get('auto_reply', True)
        }
        
        save_client_settings(user_id, settings)
        flash("Bot settings updated successfully!", "success")
        return redirect(url_for('bot_settings'))
    
    current_settings = get_client_settings(user_id)
    return render_template("bot_settings.html", settings=current_settings)

@app.route("/dashboard/account-settings", methods=["GET", "POST"])
@login_required
def account_settings():
    user = get_user_by_id(session['user_id'])
    
    if request.method == "POST":
        # Update account information - simplified since we removed extra fields
        flash("Account settings updated successfully!", "success")
        return redirect(url_for('account_settings'))
    
    return render_template("account_settings.html", user=user)

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

                                # Save the incoming user message
                                save_message(sender_id, message_text, "")
                                print(f"✅ Saved user message for {sender_id}")
                                
                                # Get conversation history
                                history = get_last_messages(sender_id, n=35)
                                print(f"📚 History for {sender_id}: {len(history)} messages")

                                # Generate AI reply
                                reply_text = get_ai_reply(history)
                                print(f"🤖 AI generated reply: {reply_text[:50]}...")

                                # Save the bot's response
                                save_message(sender_id, "", reply_text)
                                print(f"✅ Saved bot response for {sender_id}")

                                # Send reply via Instagram API
                                url = f"https://graph.facebook.com/v18.0/{INSTAGRAM_USER_ID}/messages?access_token={ACCESS_TOKEN}"
                                payload = {
                                    "recipient": {"id": sender_id},
                                    "message": {"text": reply_text}
                                }

                                r = requests.post(url, json=payload)
                                print(f"📤 Sent reply to {sender_id}: {r.status_code}")
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


if __name__ == "__main__":
    # Use environment variable for port (Render requirement)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
