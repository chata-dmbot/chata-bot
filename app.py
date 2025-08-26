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

# Database configuration
DB_FILE = "chata.db"
DATABASE_URL = os.getenv("DATABASE_URL")

# ---- Database connection helper ----

def get_db_connection():
    """Get database connection - SQLite for local, PostgreSQL for production"""
    print(f"🔍 Database connection - DATABASE_URL: {DATABASE_URL[:20] if DATABASE_URL else 'None'}...")
    
    if DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")):
        # PostgreSQL (production)
        print("✅ Using PostgreSQL database")
        import psycopg2
        from urllib.parse import urlparse
        
        # Parse the DATABASE_URL
        url = urlparse(DATABASE_URL)
        
        conn = psycopg2.connect(
            host=url.hostname,
            port=url.port,
            database=url.path[1:],  # Remove leading slash
            user=url.username,
            password=url.password
        )
        print(f"✅ PostgreSQL connected to: {url.hostname}:{url.port}/{url.path[1:]}")
        return conn
    else:
        # SQLite (local development)
        print("📱 Using SQLite database (local development)")
        return sqlite3.connect(DB_FILE)

def get_param_placeholder():
    """Get the correct parameter placeholder for the current database"""
    if DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")):
        return "%s"  # PostgreSQL
    else:
        return "?"   # SQLite

# ---- Database initialization ----

def init_database():
    """Initialize database tables if they don't exist"""
    try:
        print("🔧 Initializing database...")
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if we're using PostgreSQL
        is_postgres = DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://"))
        print(f"🔍 Database type: {'PostgreSQL' if is_postgres else 'SQLite'}")
        
        # Create the users table
        if is_postgres:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                company_name VARCHAR(255),
                subscription_plan VARCHAR(50) DEFAULT 'free',
                subscription_status VARCHAR(50) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
        else:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                first_name TEXT,
                last_name TEXT,
                company_name TEXT,
                subscription_plan TEXT DEFAULT 'free',
                subscription_status TEXT DEFAULT 'active',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)

        # Create the instagram_connections table
        if is_postgres:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS instagram_connections (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                instagram_user_id VARCHAR(255) NOT NULL,
                instagram_page_id VARCHAR(255) NOT NULL,
                page_access_token TEXT NOT NULL,
                page_name VARCHAR(255),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE(instagram_user_id, instagram_page_id)
            );
            """)
        else:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS instagram_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                instagram_user_id TEXT NOT NULL,
                instagram_page_id TEXT NOT NULL,
                page_access_token TEXT NOT NULL,
                page_name TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE(instagram_user_id, instagram_page_id)
            );
            """)

        # Create the client_settings table
        if is_postgres:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS client_settings (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                instagram_connection_id INTEGER,
                system_prompt TEXT DEFAULT 'You are a friendly digital creator''s assistant. Reply to DMs from fans in a positive, helpful way.',
                temperature REAL DEFAULT 0.8,
                max_tokens INTEGER DEFAULT 100,
                bot_name VARCHAR(255) DEFAULT 'Chata Bot',
                welcome_message TEXT DEFAULT 'Hi! I''m here to help. How can I assist you today?',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (instagram_connection_id) REFERENCES instagram_connections (id)
            );
            """)
        else:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS client_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                instagram_connection_id INTEGER,
                system_prompt TEXT DEFAULT 'You are a friendly digital creator''s assistant. Reply to DMs from fans in a positive, helpful way.',
                temperature REAL DEFAULT 0.8,
                max_tokens INTEGER DEFAULT 100,
                bot_name TEXT DEFAULT 'Chata Bot',
                welcome_message TEXT DEFAULT 'Hi! I''m here to help. How can I assist you today?',
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (instagram_connection_id) REFERENCES instagram_connections (id)
            );
            """)

        # Create the messages table (updated for multi-tenant)
        if is_postgres:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                instagram_connection_id INTEGER,
                sender_instagram_id VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL,         -- 'user' or 'assistant'
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (instagram_connection_id) REFERENCES instagram_connections (id)
            );
            """)
        else:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                instagram_connection_id INTEGER,
                sender_instagram_id TEXT NOT NULL,
                role TEXT NOT NULL,         -- 'user' or 'assistant'
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (instagram_connection_id) REFERENCES instagram_connections (id)
            );
            """)

        # Create the settings table (for global admin settings)
        if is_postgres:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id SERIAL PRIMARY KEY,
                key VARCHAR(255) UNIQUE NOT NULL,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
        else:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)

        # Create the usage_logs table (for tracking API usage)
        if is_postgres:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                instagram_connection_id INTEGER,
                action_type VARCHAR(100) NOT NULL,  -- 'message_sent', 'api_call', etc.
                tokens_used INTEGER DEFAULT 0,
                cost_cents INTEGER DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (instagram_connection_id) REFERENCES instagram_connections (id)
            );
            """)
        else:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                instagram_connection_id INTEGER,
                action_type TEXT NOT NULL,  -- 'message_sent', 'api_call', etc.
                tokens_used INTEGER DEFAULT 0,
                cost_cents INTEGER DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (instagram_connection_id) REFERENCES instagram_connections (id)
            );
            """)

        # Create the activity_logs table (for tracking user activities)
        if is_postgres:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                action_type VARCHAR(100) NOT NULL,  -- 'login', 'settings_updated', 'bot_activated', etc.
                description TEXT,
                ip_address VARCHAR(45),
                user_agent TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            );
            """)
        else:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,  -- 'login', 'settings_updated', 'bot_activated', etc.
                description TEXT,
                ip_address TEXT,
                user_agent TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            );
            """)

        # Create password_resets table for forgot password functionality
        if is_postgres:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_resets (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                token VARCHAR(255) NOT NULL UNIQUE,
                expires_at TIMESTAMP NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """)
        else:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT NOT NULL UNIQUE,
                expires_at DATETIME NOT NULL,
                used INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """)

        # Insert default admin settings
        if is_postgres:
            cursor.execute("""
            INSERT INTO settings (key, value) VALUES 
            ('system_prompt', 'You are a friendly digital creator''s assistant. Reply to DMs from fans in a positive, helpful way.'),
            ('temperature', '0.8'),
            ('max_tokens', '100')
            ON CONFLICT (key) DO NOTHING
            """)
        else:
            cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES 
            ('system_prompt', 'You are a friendly digital creator''s assistant. Reply to DMs from fans in a positive, helpful way.'),
            ('temperature', '0.8'),
            ('max_tokens', '100')
            """)

        # Create indexes for better performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users (email)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_instagram_connections_user_id ON instagram_connections (user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_client_settings_user_id ON client_settings (user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages (user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id ON usage_logs (user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_user_id ON activity_logs (user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_password_resets_token ON password_resets (token)")

        conn.commit()
        conn.close()
        print("✅ Database initialized successfully!")
        
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()

# Initialize database on app startup
init_database()

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
        WHERE token = {placeholder} AND expires_at > {placeholder} AND used = 0
    """, (token, datetime.now()))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else None

def mark_reset_token_used(token):
    """Mark a reset token as used"""
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    cursor.execute(f"UPDATE password_resets SET used = 1 WHERE token = {placeholder}", (token,))
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
        cursor.execute(f"SELECT id, email, first_name, last_name, company_name, subscription_plan FROM users WHERE id = {placeholder}", (user_id,))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'email': user[1],
                'first_name': user[2],
                'last_name': user[3],
                'company_name': user[4],
                'subscription_plan': user[5]
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
        print(f"🔍 SQL query: SELECT id, email, password_hash, first_name, last_name FROM users WHERE email = {placeholder}")
        print(f"🔍 Parameters: {email}")
        
        cursor.execute(f"SELECT id, email, password_hash, first_name, last_name FROM users WHERE email = {placeholder}", (email,))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'email': user[1],
                'password_hash': user[2],
                'first_name': user[3],
                'last_name': user[4]
            }
        return None
    except Exception as e:
        print(f"❌ Error getting user by email: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return None

def create_user(email, password, first_name, last_name, company_name):
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
        if DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")):
            sql = f"INSERT INTO users (email, password_hash, first_name, last_name, company_name) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}) RETURNING id"
            params = (email, password_hash, first_name, last_name, company_name)
            print(f"🔍 PostgreSQL SQL: {sql}")
            print(f"🔍 PostgreSQL params: {params}")
            
            cursor.execute(sql, params)
            user_id = cursor.fetchone()[0]
        else:
            sql = f"INSERT INTO users (email, password_hash, first_name, last_name, company_name) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})"
            params = (email, password_hash, first_name, last_name, company_name)
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
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        company_name = request.form.get("company_name")
        
        print(f"🔍 Signup form data:")
        print(f"🔍 Email: {email}")
        print(f"🔍 Email type: {type(email)}")
        print(f"🔍 First name: {first_name}")
        print(f"🔍 Last name: {last_name}")
        print(f"🔍 Company name: {company_name}")
        
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
            user_id = create_user(email, password, first_name, last_name, company_name)
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
                flash(f"Welcome back, {user['first_name'] or 'User'}!", "success")
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

@app.route("/dashboard")
@login_required
def dashboard():
    user = get_user_by_id(session['user_id'])
    
    # Get user's Instagram connections
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    cursor.execute(f"""
        SELECT id, page_name, instagram_user_id, is_active, created_at 
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
            'page_name': conn_data[1],
            'instagram_user_id': conn_data[2],
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
            SELECT system_prompt, temperature, max_tokens, bot_name, welcome_message
            FROM client_settings 
            WHERE user_id = {placeholder} AND instagram_connection_id = {placeholder}
        """, (user_id, connection_id))
    else:
        cursor.execute(f"""
            SELECT system_prompt, temperature, max_tokens, bot_name, welcome_message
            FROM client_settings 
            WHERE user_id = {placeholder} AND instagram_connection_id IS NULL
        """, (user_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'system_prompt': row[0],
            'temperature': row[1],
            'max_tokens': row[2],
            'bot_name': row[3],
            'welcome_message': row[4]
        }
    
    # Return default settings if none exist
    return {
        'system_prompt': "You are a friendly digital creator's assistant. Reply to DMs from fans in a positive, helpful way.",
        'temperature': 0.8,
        'max_tokens': 100,
        'bot_name': 'Chata Bot',
        'welcome_message': 'Hi! I\'m here to help. How can I assist you today?'
    }

def log_activity(user_id, action_type, description=None):
    """Log user activity for analytics and security"""
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    cursor.execute(f"""
        INSERT INTO activity_logs (user_id, action_type, description, ip_address, user_agent)
        VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
    """, (user_id, action_type, description, request.remote_addr, request.headers.get('User-Agent')))
    
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
                (user_id, instagram_connection_id, system_prompt, temperature, max_tokens, bot_name, welcome_message)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
                ON CONFLICT (user_id, instagram_connection_id) DO UPDATE SET
                system_prompt = EXCLUDED.system_prompt,
                temperature = EXCLUDED.temperature,
                max_tokens = EXCLUDED.max_tokens,
                bot_name = EXCLUDED.bot_name,
                welcome_message = EXCLUDED.welcome_message
            """, (user_id, connection_id, settings['system_prompt'], settings['temperature'], 
                  settings['max_tokens'], settings['bot_name'], settings['welcome_message']))
        else:
            cursor.execute(f"""
                INSERT INTO client_settings 
                (user_id, system_prompt, temperature, max_tokens, bot_name, welcome_message)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
                ON CONFLICT (user_id) DO UPDATE SET
                system_prompt = EXCLUDED.system_prompt,
                temperature = EXCLUDED.temperature,
                max_tokens = EXCLUDED.max_tokens,
                bot_name = EXCLUDED.bot_name,
                welcome_message = EXCLUDED.welcome_message
            """, (user_id, settings['system_prompt'], settings['temperature'], 
                  settings['max_tokens'], settings['bot_name'], settings['welcome_message']))
    else:
        if connection_id:
            cursor.execute(f"""
                INSERT OR REPLACE INTO client_settings 
                (user_id, instagram_connection_id, system_prompt, temperature, max_tokens, bot_name, welcome_message)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (user_id, connection_id, settings['system_prompt'], settings['temperature'], 
                  settings['max_tokens'], settings['bot_name'], settings['welcome_message']))
        else:
            cursor.execute(f"""
                INSERT OR REPLACE INTO client_settings 
                (user_id, system_prompt, temperature, max_tokens, bot_name, welcome_message)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (user_id, settings['system_prompt'], settings['temperature'], 
                  settings['max_tokens'], settings['bot_name'], settings['welcome_message']))
    
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
            'system_prompt': request.form.get('system_prompt', ''),
            'temperature': float(request.form.get('temperature', 0.8)),
            'max_tokens': int(request.form.get('max_tokens', 100)),
            'bot_name': request.form.get('bot_name', 'Chata Bot'),
            'welcome_message': request.form.get('welcome_message', '')
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
        # Update account information
        first_name = request.form.get('first_name', '')
        last_name = request.form.get('last_name', '')
        company_name = request.form.get('company_name', '')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"""
            UPDATE users 
            SET first_name = {placeholder}, last_name = {placeholder}, company_name = {placeholder}
            WHERE id = {placeholder}
        """, (first_name, last_name, company_name, user['id']))
        conn.commit()
        conn.close()
        
        log_activity(user['id'], 'profile_updated', 'Account profile information updated')
        flash("Account information updated successfully!", "success")
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
        WHERE user_id = {placeholder} 
        AND timestamp >= date('now', 'start of month')
    """, (user_id,))
    messages_this_month = cursor.fetchone()[0]
    
    # Get API usage for current month
    cursor.execute(f"""
        SELECT SUM(tokens_used), SUM(cost_cents) FROM usage_logs 
        WHERE user_id = {placeholder} 
        AND timestamp >= date('now', 'start of month')
    """, (user_id,))
    usage_data = cursor.fetchone()
    api_calls_this_month = usage_data[0] or 0
    cost_this_month = (usage_data[1] or 0) / 100.0  # Convert cents to dollars
    
    # Get recent activity
    cursor.execute(f"""
        SELECT action_type, description, timestamp 
        FROM activity_logs 
        WHERE user_id = {placeholder} 
        ORDER BY timestamp DESC 
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

def save_message(user_id, role, content):
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    cursor.execute(
        f"INSERT INTO messages (user_id, role, content) VALUES ({placeholder}, {placeholder}, {placeholder})",
        (user_id, role, content)
    )
    conn.commit()
    conn.close()

def get_last_messages(user_id, n=35):
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    cursor.execute(
        f"SELECT role, content FROM messages WHERE user_id = {placeholder} ORDER BY id DESC LIMIT {placeholder}",
        (user_id, n)
    )
    rows = cursor.fetchall()
    conn.close()
    rows.reverse()
    return [{"role": role, "content": content} for role, content in rows]

# ---- AI Reply ----

def get_ai_reply(history):
    openai.api_key = OPENAI_API_KEY
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        system_prompt = get_setting("system_prompt",
            "You are a friendly digital creator's assistant. Reply to DMs from fans in a positive, helpful way.")
        temperature = float(get_setting("temperature", "0.8"))
        max_tokens = int(get_setting("max_tokens", "100"))

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
        print("Webhook received POST:", request.json)
        data = request.json

        if 'entry' in data:
            for entry in data['entry']:
                if 'messaging' in entry:
                    for event in entry['messaging']:
                        if event.get('message', {}).get('is_echo'):
                            continue

                        sender_id = event['sender']['id']
                        if 'message' in event and 'text' in event['message']:
                            message_text = event['message']['text']
                            print(f"Received a message from {sender_id}: {message_text}")

                            save_message(sender_id, "user", message_text)
                            history = get_last_messages(sender_id, n=35)
                            print(f"History for {sender_id} BEFORE reply: {history}")

                            reply_text = get_ai_reply(history)

                            save_message(sender_id, "assistant", reply_text)
                            print(f"History for {sender_id} AFTER reply: {get_last_messages(sender_id, n=10)}")

                            url = f"https://graph.facebook.com/v18.0/{INSTAGRAM_USER_ID}/messages?access_token={ACCESS_TOKEN}"
                            payload = {
                                "recipient": {"id": sender_id},
                                "message": {"text": reply_text}
                            }

                            r = requests.post(url, json=payload)
                            print("Sent reply:", r.text)

        return "EVENT_RECEIVED", 200

# ---- Admin Panel Route ----

@app.route("/admin/prompt", methods=["GET", "POST"])
def admin_prompt():
    message = None

    if flask_request.method == "POST":
        set_setting("system_prompt", flask_request.form.get("system_prompt", ""))
        set_setting("temperature", flask_request.form.get("temperature", "0.8"))
        set_setting("max_tokens", flask_request.form.get("max_tokens", "100"))
        message = "Bot settings updated successfully!"

    current_prompt = get_setting("system_prompt", "")
    current_temperature = get_setting("temperature", "0.8")
    current_max_tokens = get_setting("max_tokens", "100")

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
            <label for="system_prompt">System Prompt (Bot Role/Personality):</label><br>
            <textarea id="system_prompt" name="system_prompt" rows="4">{{current_prompt}}</textarea>
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
