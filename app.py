from dotenv import load_dotenv
import os
from flask import Flask, request, render_template, redirect, url_for, flash, session, jsonify
import requests
import openai
from flask import render_template_string, request as flask_request
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import secrets
from datetime import datetime, timedelta
import sendgrid
from sendgrid.helpers.mail import Mail
import json

# Import our modular components
from config import Config
from database import get_db_connection, get_param_placeholder, init_database
from health import health_check, get_system_info

# Load environment variables from .env file
load_dotenv()

# Validate required environment variables
try:
    Config.validate_required_vars()
    print("✅ All required environment variables are set")
except ValueError as e:
    print(f"❌ Configuration error: {e}")
    print("Please check your environment variables")

# Flask app
app = Flask(__name__)
app.secret_key = Config.SECRET_KEY

# Debug OAuth configuration
print(f"Facebook OAuth - App ID: {Config.FACEBOOK_APP_ID[:8] + '...' if Config.FACEBOOK_APP_ID else 'Not set'}")
print(f"Facebook OAuth - App Secret: {'Set' if Config.FACEBOOK_APP_SECRET else 'Not set'}")
print(f"Facebook OAuth - Redirect URI: {Config.FACEBOOK_REDIRECT_URI}")

# ---- Health Check Endpoints ----

@app.route("/health")
def health():
    """Health check endpoint for monitoring"""
    return jsonify(health_check())

@app.route("/health/detailed")
def health_detailed():
    """Detailed health check with system information"""
    health_data = health_check()
    health_data["system"] = get_system_info()
    return jsonify(health_data)

@app.route("/ping")
def ping():
    """Simple ping endpoint"""
    return jsonify({"status": "pong", "timestamp": datetime.utcnow().isoformat()})

@app.route("/webhook/test")
def webhook_test():
    """Test endpoint to verify webhook URL is accessible"""
    return jsonify({
        "status": "webhook_url_accessible",
        "url": "https://chata-bot.onrender.com/webhook",
        "verify_token_set": bool(Config.VERIFY_TOKEN),
        "timestamp": datetime.utcnow().isoformat()
    })




# Initialize database on app startup
print("Starting Chata application...")
if init_database():
    print("Database initialized successfully")
else:
    print("Database initialization failed - some features may not work")

# Run migration to add missing columns
print("Running database migration...")
from update_schema import migrate_client_settings
try:
    if migrate_client_settings():
        print("✅ Migration completed successfully")
    else:
        print("⚠️ Migration had issues but continuing...")
except Exception as e:
    print(f"⚠️ Migration error (continuing anyway): {e}")

# ---- Email helpers ----

def send_reset_email(email, reset_token):
    """Send password reset email using SendGrid"""
    reset_url = f"https://chata-bot.onrender.com/reset-password?token={reset_token}"
    
    # Get SendGrid API key from environment
    sendgrid_api_key = Config.SENDGRID_API_KEY
    
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
    if not Config.FACEBOOK_APP_ID:
        flash("Facebook OAuth not configured. Please contact support.", "error")
        return redirect(url_for('dashboard'))
    
    # Generate state parameter for security
    state = secrets.token_urlsafe(32)
    session['instagram_oauth_state'] = state
    
    # Build Instagram Business OAuth URL (using Facebook Graph API)
    oauth_url = (
        f"https://www.facebook.com/v18.0/dialog/oauth"
        f"?client_id={Config.FACEBOOK_APP_ID}"
        f"&redirect_uri={Config.FACEBOOK_REDIRECT_URI}"
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
            'client_id': Config.FACEBOOK_APP_ID,
            'client_secret': Config.FACEBOOK_APP_SECRET,
            'redirect_uri': Config.FACEBOOK_REDIRECT_URI,
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
                'access_token': Config.FACEBOOK_APP_ID + '|' + Config.FACEBOOK_APP_SECRET
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

@app.route("/dashboard")
@login_required
def dashboard():
    # Normal user flow
    user = get_user_by_id(session['user_id'])
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('login'))
    
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
            SELECT bot_personality, bot_name, bot_age, bot_gender, bot_location, bot_occupation, bot_education,
                   personality_type, bot_values, tone_of_voice, habits_quirks, confidence_level, emotional_range,
                   main_goal, fears_insecurities, what_drives_them, obstacles, backstory, family_relationships,
                   culture_environment, hobbies_interests, reply_style, emoji_slang, conflict_handling, preferred_topics,
                   use_active_hours, active_start, active_end, links, posts, instagram_url, avoid_topics, 
                   temperature, max_tokens, is_active
            FROM client_settings 
            WHERE user_id = {placeholder} AND instagram_connection_id = {placeholder}
        """, (user_id, connection_id))
    else:
        cursor.execute(f"""
            SELECT bot_personality, bot_name, bot_age, bot_gender, bot_location, bot_occupation, bot_education,
                   personality_type, bot_values, tone_of_voice, habits_quirks, confidence_level, emotional_range,
                   main_goal, fears_insecurities, what_drives_them, obstacles, backstory, family_relationships,
                   culture_environment, hobbies_interests, reply_style, emoji_slang, conflict_handling, preferred_topics,
                   use_active_hours, active_start, active_end, links, posts, instagram_url, avoid_topics, 
                   temperature, max_tokens, is_active
            FROM client_settings 
            WHERE user_id = {placeholder} AND instagram_connection_id IS NULL
        """, (user_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        import json
        return {
            'bot_personality': row[0] or 'You are a helpful and friendly Instagram bot.',
            'bot_name': row[1] or '',
            'bot_age': row[2] or '',
            'bot_gender': row[3] or '',
            'bot_location': row[4] or '',
            'bot_occupation': row[5] or '',
            'bot_education': row[6] or '',
            'personality_type': row[7] or '',
            'bot_values': row[8] or '',
            'tone_of_voice': row[9] or '',
            'habits_quirks': row[10] or '',
            'confidence_level': row[11] or '',
            'emotional_range': row[12] or '',
            'main_goal': row[13] or '',
            'fears_insecurities': row[14] or '',
            'what_drives_them': row[15] or '',
            'obstacles': row[16] or '',
            'backstory': row[17] or '',
            'family_relationships': row[18] or '',
            'culture_environment': row[19] or '',
            'hobbies_interests': row[20] or '',
            'reply_style': row[21] or '',
            'emoji_slang': row[22] or '',
            'conflict_handling': row[23] or '',
            'preferred_topics': row[24] or '',
            'use_active_hours': bool(row[25]) if row[25] is not None else False,
            'active_start': row[26] or '09:00',
            'active_end': row[27] or '18:00',
            'links': json.loads(row[28]) if row[28] else [],
            'posts': json.loads(row[29]) if row[29] else [],
            'instagram_url': row[30] or '',
            'avoid_topics': row[31] or '',
            'temperature': row[32] or 0.7,
            'max_tokens': row[33] or 150,
            'auto_reply': bool(row[34]) if row[34] is not None else True
        }
    
    # Return default settings if none exist
    return {
        'bot_personality': "You are a helpful and friendly Instagram bot.",
        'bot_name': '',
        'bot_age': '',
        'bot_gender': '',
        'bot_location': '',
        'bot_occupation': '',
        'bot_education': '',
        'personality_type': '',
        'bot_values': '',
        'tone_of_voice': '',
        'habits_quirks': '',
        'confidence_level': '',
        'emotional_range': '',
        'main_goal': '',
        'fears_insecurities': '',
        'what_drives_them': '',
        'obstacles': '',
        'backstory': '',
        'family_relationships': '',
        'culture_environment': '',
        'hobbies_interests': '',
        'reply_style': '',
        'emoji_slang': '',
        'conflict_handling': '',
        'preferred_topics': '',
        'use_active_hours': False,
        'active_start': '09:00',
        'active_end': '18:00',
        'links': [],
        'posts': [],
        'instagram_url': '',
        'avoid_topics': '',
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
    import json
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    # Prepare the data
    links_json = json.dumps(settings.get('links', []))
    posts_json = json.dumps(settings.get('posts', []))
    
    # Use different syntax for PostgreSQL vs SQLite
    if Config.DATABASE_URL and (Config.DATABASE_URL.startswith("postgres://") or Config.DATABASE_URL.startswith("postgresql://")):
        if connection_id:
            cursor.execute(f"""
            INSERT INTO client_settings 
            (user_id, instagram_connection_id, bot_personality, bot_name, bot_age, bot_gender, bot_location, 
             bot_occupation, bot_education, personality_type, bot_values, tone_of_voice, habits_quirks, 
             confidence_level, emotional_range, main_goal, fears_insecurities, what_drives_them, obstacles,
             backstory, family_relationships, culture_environment, hobbies_interests, reply_style, emoji_slang,
             conflict_handling, preferred_topics, use_active_hours, active_start, active_end, links, posts, 
             instagram_url, avoid_topics, temperature, max_tokens, is_active)
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            ON CONFLICT (user_id, instagram_connection_id) DO UPDATE SET
            bot_personality = EXCLUDED.bot_personality,
            bot_name = EXCLUDED.bot_name,
            bot_age = EXCLUDED.bot_age,
            bot_gender = EXCLUDED.bot_gender,
            bot_location = EXCLUDED.bot_location,
            bot_occupation = EXCLUDED.bot_occupation,
            bot_education = EXCLUDED.bot_education,
            personality_type = EXCLUDED.personality_type,
            bot_values = EXCLUDED.bot_values,
            tone_of_voice = EXCLUDED.tone_of_voice,
            habits_quirks = EXCLUDED.habits_quirks,
            confidence_level = EXCLUDED.confidence_level,
            emotional_range = EXCLUDED.emotional_range,
            main_goal = EXCLUDED.main_goal,
            fears_insecurities = EXCLUDED.fears_insecurities,
            what_drives_them = EXCLUDED.what_drives_them,
            obstacles = EXCLUDED.obstacles,
            backstory = EXCLUDED.backstory,
            family_relationships = EXCLUDED.family_relationships,
            culture_environment = EXCLUDED.culture_environment,
            hobbies_interests = EXCLUDED.hobbies_interests,
            reply_style = EXCLUDED.reply_style,
            emoji_slang = EXCLUDED.emoji_slang,
            conflict_handling = EXCLUDED.conflict_handling,
            preferred_topics = EXCLUDED.preferred_topics,
            use_active_hours = EXCLUDED.use_active_hours,
            active_start = EXCLUDED.active_start,
            active_end = EXCLUDED.active_end,
            links = EXCLUDED.links,
            posts = EXCLUDED.posts,
            instagram_url = EXCLUDED.instagram_url,
            avoid_topics = EXCLUDED.avoid_topics,
            temperature = EXCLUDED.temperature,
            max_tokens = EXCLUDED.max_tokens,
            is_active = EXCLUDED.is_active,
            updated_at = CURRENT_TIMESTAMP
        """, (user_id, connection_id, 
              settings.get('bot_personality', ''), settings.get('bot_name', ''), settings.get('bot_age', ''),
              settings.get('bot_gender', ''), settings.get('bot_location', ''), settings.get('bot_occupation', ''),
              settings.get('bot_education', ''), settings.get('personality_type', ''), settings.get('bot_values', ''),
              settings.get('tone_of_voice', ''), settings.get('habits_quirks', ''), settings.get('confidence_level', ''),
              settings.get('emotional_range', ''), settings.get('main_goal', ''), settings.get('fears_insecurities', ''),
              settings.get('what_drives_them', ''), settings.get('obstacles', ''), settings.get('backstory', ''),
              settings.get('family_relationships', ''), settings.get('culture_environment', ''), settings.get('hobbies_interests', ''),
              settings.get('reply_style', ''), settings.get('emoji_slang', ''), settings.get('conflict_handling', ''),
              settings.get('preferred_topics', ''), settings.get('use_active_hours', False), 
              settings.get('active_start', '09:00'), settings.get('active_end', '18:00'), 
              links_json, posts_json, settings.get('instagram_url', ''), settings.get('avoid_topics', ''),
              settings.get('temperature', 0.7), settings.get('max_tokens', 150), 
              settings.get('auto_reply', True)))
        else:
            # For global settings, delete existing and insert new
            cursor.execute(f"DELETE FROM client_settings WHERE user_id = {placeholder} AND instagram_connection_id IS NULL", (user_id,))
            cursor.execute(f"""
                INSERT INTO client_settings 
                (user_id, instagram_connection_id, bot_personality, bot_name, bot_age, bot_gender, bot_location, 
                 bot_occupation, bot_education, personality_type, bot_values, tone_of_voice, habits_quirks, 
                 confidence_level, emotional_range, main_goal, fears_insecurities, what_drives_them, obstacles,
                 backstory, family_relationships, culture_environment, hobbies_interests, reply_style, emoji_slang,
                 conflict_handling, preferred_topics, use_active_hours, active_start, active_end, links, posts, 
                 instagram_url, avoid_topics, temperature, max_tokens, is_active)
                VALUES ({placeholder}, NULL, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (user_id, 
                  settings.get('bot_personality', ''), settings.get('bot_name', ''), settings.get('bot_age', ''),
                  settings.get('bot_gender', ''), settings.get('bot_location', ''), settings.get('bot_occupation', ''),
                  settings.get('bot_education', ''), settings.get('personality_type', ''), settings.get('bot_values', ''),
                  settings.get('tone_of_voice', ''), settings.get('habits_quirks', ''), settings.get('confidence_level', ''),
                  settings.get('emotional_range', ''), settings.get('main_goal', ''), settings.get('fears_insecurities', ''),
                  settings.get('what_drives_them', ''), settings.get('obstacles', ''), settings.get('backstory', ''),
                  settings.get('family_relationships', ''), settings.get('culture_environment', ''), settings.get('hobbies_interests', ''),
                  settings.get('reply_style', ''), settings.get('emoji_slang', ''), settings.get('conflict_handling', ''),
                  settings.get('preferred_topics', ''), settings.get('use_active_hours', False), 
                  settings.get('active_start', '09:00'), settings.get('active_end', '18:00'), 
                  links_json, posts_json, settings.get('instagram_url', ''), settings.get('avoid_topics', ''),
                  settings.get('temperature', 0.7), settings.get('max_tokens', 150), 
                  settings.get('auto_reply', True)))
    else:
        if connection_id:
            cursor.execute(f"""
                INSERT OR REPLACE INTO client_settings 
                (user_id, instagram_connection_id, bot_personality, bot_name, bot_age, bot_gender, bot_location, 
                 bot_occupation, bot_education, personality_type, bot_values, tone_of_voice, habits_quirks, 
                 confidence_level, emotional_range, main_goal, fears_insecurities, what_drives_them, obstacles,
                 backstory, family_relationships, culture_environment, hobbies_interests, reply_style, emoji_slang,
                 conflict_handling, preferred_topics, use_active_hours, active_start, active_end, links, posts, 
                 instagram_url, avoid_topics, temperature, max_tokens, is_active)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (user_id, connection_id, 
                  settings.get('bot_personality', ''), settings.get('bot_name', ''), settings.get('bot_age', ''),
                  settings.get('bot_gender', ''), settings.get('bot_location', ''), settings.get('bot_occupation', ''),
                  settings.get('bot_education', ''), settings.get('personality_type', ''), settings.get('bot_values', ''),
                  settings.get('tone_of_voice', ''), settings.get('habits_quirks', ''), settings.get('confidence_level', ''),
                  settings.get('emotional_range', ''), settings.get('main_goal', ''), settings.get('fears_insecurities', ''),
                  settings.get('what_drives_them', ''), settings.get('obstacles', ''), settings.get('backstory', ''),
                  settings.get('family_relationships', ''), settings.get('culture_environment', ''), settings.get('hobbies_interests', ''),
                  settings.get('reply_style', ''), settings.get('emoji_slang', ''), settings.get('conflict_handling', ''),
                  settings.get('preferred_topics', ''), settings.get('use_active_hours', False), 
                  settings.get('active_start', '09:00'), settings.get('active_end', '18:00'), 
                  links_json, posts_json, settings.get('instagram_url', ''), settings.get('avoid_topics', ''),
                  settings.get('temperature', 0.7), settings.get('max_tokens', 150), 
                  settings.get('auto_reply', True)))
        else:
            # For global settings in SQLite, delete existing and insert new
            cursor.execute(f"DELETE FROM client_settings WHERE user_id = {placeholder} AND instagram_connection_id IS NULL", (user_id,))
            cursor.execute(f"""
                INSERT INTO client_settings 
                (user_id, instagram_connection_id, bot_personality, bot_name, bot_age, bot_gender, bot_location, 
                 bot_occupation, bot_education, personality_type, bot_values, tone_of_voice, habits_quirks, 
                 confidence_level, emotional_range, main_goal, fears_insecurities, what_drives_them, obstacles,
                 backstory, family_relationships, culture_environment, hobbies_interests, reply_style, emoji_slang,
                 conflict_handling, preferred_topics, use_active_hours, active_start, active_end, links, posts, 
                 instagram_url, avoid_topics, temperature, max_tokens, is_active)
                VALUES ({placeholder}, NULL, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (user_id, 
                  settings.get('bot_personality', ''), settings.get('bot_name', ''), settings.get('bot_age', ''),
                  settings.get('bot_gender', ''), settings.get('bot_location', ''), settings.get('bot_occupation', ''),
                  settings.get('bot_education', ''), settings.get('personality_type', ''), settings.get('bot_values', ''),
                  settings.get('tone_of_voice', ''), settings.get('habits_quirks', ''), settings.get('confidence_level', ''),
                  settings.get('emotional_range', ''), settings.get('main_goal', ''), settings.get('fears_insecurities', ''),
                  settings.get('what_drives_them', ''), settings.get('obstacles', ''), settings.get('backstory', ''),
                  settings.get('family_relationships', ''), settings.get('culture_environment', ''), settings.get('hobbies_interests', ''),
                  settings.get('reply_style', ''), settings.get('emoji_slang', ''), settings.get('conflict_handling', ''),
                  settings.get('preferred_topics', ''), settings.get('use_active_hours', False), 
                  settings.get('active_start', '09:00'), settings.get('active_end', '18:00'), 
                  links_json, posts_json, settings.get('instagram_url', ''), settings.get('avoid_topics', ''),
                  settings.get('temperature', 0.7), settings.get('max_tokens', 150), 
                  settings.get('auto_reply', True)))
    
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
        form_connection_id = request.form.get('connection_id')
        if form_connection_id == '':
            connection_id = None
        elif form_connection_id is not None:
            try:
                connection_id = int(form_connection_id)
            except ValueError:
                connection_id = None
    
    if request.method == "POST":
        import json
        
        # Process links
        link_urls = request.form.getlist('link_urls[]')
        link_titles = request.form.getlist('link_titles[]')
        links = []
        for i, url in enumerate(link_urls):
            if url.strip() and i < len(link_titles):
                links.append({'url': url.strip(), 'title': link_titles[i].strip()})
        
        # Process posts
        post_descriptions = request.form.getlist('post_descriptions[]')
        posts = []
        for desc in post_descriptions:
            if desc.strip():
                posts.append({'description': desc.strip()})
        
        settings = {
            'bot_personality': request.form.get('bot_personality', ''),
            'bot_name': request.form.get('bot_name', ''),
            'bot_age': request.form.get('bot_age', ''),
            'bot_gender': request.form.get('bot_gender', ''),
            'bot_location': request.form.get('bot_location', ''),
            'bot_occupation': request.form.get('bot_occupation', ''),
            'bot_education': request.form.get('bot_education', ''),
            'personality_type': request.form.get('personality_type', ''),
            'bot_values': request.form.get('bot_values', ''),
            'tone_of_voice': request.form.get('tone_of_voice', ''),
            'habits_quirks': request.form.get('habits_quirks', ''),
            'confidence_level': request.form.get('confidence_level', ''),
            'emotional_range': request.form.get('emotional_range', ''),
            'main_goal': request.form.get('main_goal', ''),
            'fears_insecurities': request.form.get('fears_insecurities', ''),
            'what_drives_them': request.form.get('what_drives_them', ''),
            'obstacles': request.form.get('obstacles', ''),
            'backstory': request.form.get('backstory', ''),
            'family_relationships': request.form.get('family_relationships', ''),
            'culture_environment': request.form.get('culture_environment', ''),
            'hobbies_interests': request.form.get('hobbies_interests', ''),
            'reply_style': request.form.get('reply_style', ''),
            'emoji_slang': request.form.get('emoji_slang', ''),
            'conflict_handling': request.form.get('conflict_handling', ''),
            'preferred_topics': request.form.get('preferred_topics', ''),
            'use_active_hours': bool(request.form.get('use_active_hours')),
            'active_start': request.form.get('active_start', '09:00'),
            'active_end': request.form.get('active_end', '18:00'),
            'links': links,
            'posts': posts,
            'instagram_url': request.form.get('instagram_url', ''),
            'avoid_topics': request.form.get('avoid_topics', ''),
            'temperature': float(request.form.get('temperature', 0.7)),
            'max_tokens': int(request.form.get('max_tokens', 150)),
            'auto_reply': bool(request.form.get('auto_reply', True))
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

def discover_instagram_user_id(page_access_token, page_id):
    """
    Discover the correct Instagram User ID from a Facebook Page using the Page Access Token.
    This is the proper way to get the Instagram User ID that works with the messaging API.
    """
    try:
        print(f"🔍 Discovering Instagram User ID for Page ID: {page_id}")
        
        # First, get the Instagram Business Account ID from the Page
        url = f"https://graph.facebook.com/v18.0/{page_id}?fields=instagram_business_account&access_token={page_access_token}"
        response = requests.get(url)
        
        if response.status_code != 200:
            print(f"❌ Failed to get Instagram Business Account: {response.text}")
            return None
            
        data = response.json()
        if 'instagram_business_account' not in data:
            print(f"❌ No Instagram Business Account found for Page {page_id}")
            return None
            
        instagram_business_account_id = data['instagram_business_account']['id']
        print(f"✅ Found Instagram Business Account ID: {instagram_business_account_id}")
        
        # Now get the Instagram User ID from the Business Account
        # This is the ID that works with the messaging API
        url = f"https://graph.facebook.com/v18.0/{instagram_business_account_id}?fields=id,username&access_token={page_access_token}"
        response = requests.get(url)
        
        if response.status_code != 200:
            print(f"❌ Failed to get Instagram User details: {response.text}")
            return None
            
        data = response.json()
        instagram_user_id = data['id']
        username = data.get('username', 'Unknown')
        
        print(f"✅ Discovered Instagram User ID: {instagram_user_id} (Username: {username})")
        return instagram_user_id
        
    except Exception as e:
        print(f"❌ Error discovering Instagram User ID: {e}")
        return None

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
    openai.api_key = Config.OPENAI_API_KEY
    try:
        client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)

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
    openai.api_key = Config.OPENAI_API_KEY
    try:
        client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)

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
            system_prompt = build_personality_prompt(settings)
                temperature = settings['temperature']
                max_tokens = settings['max_tokens']
                print(f"🎯 Using connection-specific settings for connection {connection_id}")
                print(f"📝 Bot personality (first 100 chars): {system_prompt[:100]}...")
                print(f"🌡️  Temperature: {temperature}, Max tokens: {max_tokens}")
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


def build_personality_prompt(settings):
    """
    Build a detailed system prompt using the saved settings for a connection.
    This is where the bot's identity, tone, and behaviour are defined.
    """
    lines = []

    # Base personality text
    base_personality = settings.get('bot_personality') or "You are a helpful and friendly Instagram bot."
    lines.append(base_personality.strip())

    # Identity basics
    if settings.get('bot_name'):
        lines.append(f"Your name is {settings['bot_name'].strip()}. Introduce yourself using this name when appropriate.")
    if settings.get('bot_age'):
        lines.append(f"You are {settings['bot_age'].strip()} years old.")
    if settings.get('bot_gender'):
        lines.append(f"Your pronouns / gender identity: {settings['bot_gender'].strip()}. Respectfully embody this identity.")
    if settings.get('bot_location'):
        lines.append(f"You are located in {settings['bot_location'].strip()}.")
    if settings.get('bot_occupation'):
        lines.append(f"Occupation / role: {settings['bot_occupation'].strip()}.")
    if settings.get('bot_education'):
        lines.append(f"Education / background: {settings['bot_education'].strip()}.")

    # Personality & behaviour
    def add_if_present(label, key):
        value = settings.get(key)
        if value:
            lines.append(f"{label}: {value.strip()}")

    add_if_present("Personality type", "personality_type")
    add_if_present("Core values", "bot_values")
    add_if_present("Typical tone of voice", "tone_of_voice")
    add_if_present("Notable habits or quirks", "habits_quirks")
    add_if_present("Confidence level", "confidence_level")
    add_if_present("Emotional range", "emotional_range")
    add_if_present("Primary goal", "main_goal")
    add_if_present("Fears or insecurities", "fears_insecurities")
    add_if_present("What motivates you", "what_drives_them")
    add_if_present("Common obstacles", "obstacles")
    add_if_present("Backstory", "backstory")
    add_if_present("Family & relationships", "family_relationships")
    add_if_present("Culture / environment", "culture_environment")
    add_if_present("Hobbies & interests", "hobbies_interests")
    add_if_present("Preferred reply style", "reply_style")
    add_if_present("Use of emoji / slang", "emoji_slang")
    add_if_present("How you handle conflict", "conflict_handling")
    add_if_present("Topics you enjoy discussing", "preferred_topics")
    add_if_present("Topics to avoid", "avoid_topics")

    # Links & promo material
    links = settings.get('links') or []
    if links:
        formatted_links = "\n".join([f"- {link.get('title') or link.get('url')}: {link.get('url')}" for link in links])
        lines.append("Promotional or important links to share when relevant:\n" + formatted_links)
    else:
        lines.append("No promotional links provided unless the user adds them later.")

    posts = settings.get('posts') or []
    if posts:
        formatted_posts = "\n".join([f"- {post.get('description')}" for post in posts if post.get('description')])
        lines.append("Instagram posts or highlights you can reference:\n" + formatted_posts)

    if settings.get('instagram_url'):
        lines.append(f"Official Instagram profile URL: {settings['instagram_url'].strip()}")

    # Behavioural reminders
    lines.append("Stay in character at all times. Respond like a real person with this identity.")
    lines.append("Always keep responses conversational, concise, and tailored to Instagram DMs.")
    if settings.get('auto_reply') is False:
        lines.append("Auto-reply is disabled, but if you are invoked, respond thoughtfully.")

    combined_prompt = "\n\n".join(lines).strip()
    print(f"🧠 Built system prompt ({len(combined_prompt)} chars)")
    return combined_prompt

# ---- Webhook Route ----

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        print(f"🔍 Webhook GET request - mode: {mode}, token: {token[:10] if token else 'None'}...")
        if mode == "subscribe" and token == Config.VERIFY_TOKEN:
            print("✅ WEBHOOK VERIFIED!")
            return challenge, 200
        else:
            print(f"❌ Webhook verification failed - mode: {mode}, token match: {token == Config.VERIFY_TOKEN}")
            return "Forbidden", 403

    elif request.method == "POST":
        print("=" * 80)
        print("📥 WEBHOOK RECEIVED POST REQUEST")
        print("=" * 80)
        print(f"📋 Request headers: {dict(request.headers)}")
        print(f"📋 Request data: {request.json}")
        print(f"📋 Request remote address: {request.remote_addr}")
        data = request.json
        
        # Debug: Show all available Instagram connections
        print("🔍 Available Instagram connections in database:")
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT id, instagram_user_id, instagram_page_id, is_active FROM instagram_connections")
                connections = cursor.fetchall()
                print(f"📊 Found {len(connections)} Instagram connections:")
                for conn_data in connections:
                    print(f"  - DB ID: {conn_data[0]}")
                    print(f"    Instagram User ID: {conn_data[1]}")
                    print(f"    Instagram Page ID: {conn_data[2]}")
                    print(f"    Active: {conn_data[3]}")
                    print(f"    ---")
            except Exception as e:
                print(f"❌ Error fetching connections: {e}")
                import traceback
                traceback.print_exc()
            finally:
                conn.close()
        else:
            print("❌ Could not connect to database to fetch connections")

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
                                    print(f"🔍 Comparing against database values...")
                                    instagram_connection = get_instagram_connection_by_id(recipient_id)
                                    if instagram_connection:
                                        print(f"✅ Found connection by Instagram User ID!")
                                    else:
                                        print(f"❌ No connection found with Instagram User ID: {recipient_id}")
                                
                                # If not found by user ID, try by page ID
                                if not instagram_connection and page_id:
                                    print(f"🔍 Trying to find connection by page ID: {page_id}")
                                    print(f"🔍 Comparing against database values...")
                                    instagram_connection = get_instagram_connection_by_page_id(page_id)
                                    if instagram_connection:
                                        print(f"✅ Found connection by Page ID!")
                                    else:
                                        print(f"❌ No connection found with Page ID: {page_id}")
                                
                                if not instagram_connection:
                                    print(f"❌ No Instagram connection found for account {recipient_id} or page {page_id}")
                                    print(f"💡 This might be the original Chata account or an unregistered account")
                                    
                                    # Check if this is the original Chata account
                                    if recipient_id == Config.INSTAGRAM_USER_ID:
                                        print(f"✅ This is the original Chata account - using hardcoded settings")
                                        access_token = Config.ACCESS_TOKEN
                                        instagram_user_id = Config.INSTAGRAM_USER_ID
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
                                # Use instagram_page_id for sending messages (Facebook Page ID)
                                page_id = instagram_connection['instagram_page_id'] if instagram_connection else Config.INSTAGRAM_USER_ID
                                url = f"https://graph.facebook.com/v18.0/{page_id}/messages?access_token={access_token}"
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
    # Check if user is logged in
    user_logged_in = 'user_id' in session
    user = None
    if user_logged_in:
        user = get_user_by_id(session['user_id'])
    return render_template("index.html", user_logged_in=user_logged_in, user=user)



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
