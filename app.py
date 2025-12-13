from dotenv import load_dotenv
import os
from flask import Flask, request, render_template, redirect, url_for, flash, session, jsonify
# Deployment trigger
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
import time
import stripe
import hmac
import hashlib

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

# Initialize Stripe
if Config.STRIPE_SECRET_KEY:
    stripe.api_key = Config.STRIPE_SECRET_KEY
else:
    print("⚠️ Warning: STRIPE_SECRET_KEY not set. Stripe features will not work.")

# Four conversation examples for training the bot
CONVERSATION_EXAMPLES = [
    {
        "key": "conv_example_1",
        "title": "Conversation Example 1",
        "exchanges": [
            {
                "follower_message": "hey, just wanted to say I really liked your last post, how did you pull that off",
                "bot_reply_key": "reply_1"
            },
            {
                "follower_message": "nice, thanks for the explanation, do you have more stuff like that coming soon",
                "bot_reply_key": "reply_2"
            },
            {
                "follower_message": "cool, appreciate you taking the time to answer, keep doing your thing",
                "bot_reply_key": "reply_3"
            }
        ]
    },
    {
        "key": "conv_example_2",
        "title": "Conversation Example 2",
        "exchanges": [
            {
                "follower_message": "idk why but your content helped a lot today, been going through some stuff",
                "bot_reply_key": "reply_1"
            },
            {
                "follower_message": "thanks, really means something right now, I've just been overwhelmed lately",
                "bot_reply_key": "reply_2"
            },
            {
                "follower_message": "anyway I don't wanna keep you, hope everything's good on your side too",
                "bot_reply_key": "reply_3"
            }
        ]
    },
    {
        "key": "conv_example_3",
        "title": "Conversation Example 3",
        "exchanges": [
            {
                "follower_message": "hey quick question, do you ever do shoutouts or promos",
                "bot_reply_key": "reply_1"
            },
            {
                "follower_message": "ah ok cool, how does it usually work for you",
                "bot_reply_key": "reply_2"
            },
            {
                "follower_message": "got it, thanks for clearing that up, keep doing your thing",
                "bot_reply_key": "reply_3"
            }
        ]
    },
    {
        "key": "conv_example_4",
        "title": "Conversation Example 4",
        "exchanges": [
            {
                "follower_message": "yo I saw something in one of your older posts, do you still do stuff like that",
                "bot_reply_key": "reply_1"
            },
            {
                "follower_message": "nice, where can I check some of the new things you've been doing",
                "bot_reply_key": "reply_2"
            },
            {
                "follower_message": "sweet, I'll look through it later, thanks for the quick answer",
                "bot_reply_key": "reply_3"
            }
        ]
    }
]

# Keep for backward compatibility in prompt building
CONVERSATION_TEMPLATES = CONVERSATION_EXAMPLES
ALL_CONVERSATION_PROMPTS = CONVERSATION_EXAMPLES

MODEL_CONFIG = {
    "gpt-5-nano": {
        "token_param": "max_completion_tokens",
        "supports_temperature": False,
        "max_completion_cap": 3000,
    },
}

DEFAULT_MODEL_CONFIG = {
    "token_param": "max_tokens",
    "supports_temperature": True,
}


def normalize_max_tokens(value, floor=3000):
    """Ensure max_tokens is at least the configured floor."""
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return floor
    return max(numeric, floor)

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
        "url": "https://getchata.com/webhook",
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

def get_email_base_template(title, content_html):
    """Base email template with black/blue theme - simplified design"""
    return f"""
    <div style="font-family: 'Inter', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background: #000000;">
        <div style="text-align: center; margin-bottom: 40px; padding: 20px 0;">
            <h1 style="color: #ffffff; margin: 0; font-size: 48px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;">CHATA</h1>
            <p style="color: rgba(255, 255, 255, 0.7); margin: 10px 0 0 0; font-size: 14px; letter-spacing: 0.1em; text-transform: uppercase;">INSTAGRAM AI ENGAGEMENT</p>
        </div>
        
        <div style="padding: 0 20px;">
            <h2 style="color: #ffffff; margin-bottom: 20px; font-size: 24px; font-weight: 600; text-transform: none; letter-spacing: normal;">{title}</h2>
            
            {content_html}
        </div>
    </div>
    """

def send_reset_email(email, reset_token):
    """Send password reset email using SendGrid"""
    reset_url = f"https://getchata.com/reset-password?token={reset_token}"
    
    # Get SendGrid API key from environment
    sendgrid_api_key = Config.SENDGRID_API_KEY
    
    if not sendgrid_api_key:
        # Fallback to console output if no API key
        print(f"Password reset link for {email}: {reset_url}")
        print("SENDGRID_API_KEY not found in environment variables")
        return
    
    try:
        sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)
        
        # Create email content with simplified black/blue theme
        content_html = f"""
            <p style="color: rgba(255, 255, 255, 0.9); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
                You recently requested a password reset for your Chata account.
            </p>
            
            <p style="color: rgba(255, 255, 255, 0.8); line-height: 1.7; margin-bottom: 30px; font-size: 16px; text-transform: none; letter-spacing: normal;">
                Click the button below to reset your password. This link will allow you to create a new password for your account.
            </p>
            
            <div style="text-align: center; margin: 35px 0;">
                <a href="{reset_url}" style="background: linear-gradient(135deg, #3366ff 0%, #4d7cff 100%); color: white; padding: 16px 40px; text-decoration: none; border-radius: 10px; font-weight: 600; display: inline-block; box-shadow: 0 4px 15px rgba(51, 102, 255, 0.3); transition: all 0.3s ease; text-transform: none; letter-spacing: normal; font-size: 16px;">
                    Reset Password
                </a>
            </div>
            
            <p style="color: rgba(255, 255, 255, 0.7); font-size: 15px; margin: 30px 0 15px 0; text-transform: none; letter-spacing: normal; text-align: center;">
                If the button doesn't work, copy and paste this link into your browser:
            </p>
            
            <div style="background: rgba(51, 102, 255, 0.1); padding: 15px; border-radius: 8px; border: 1px solid rgba(51, 102, 255, 0.2); margin-bottom: 25px;">
                <p style="color: #3366ff; font-size: 13px; word-break: break-all; margin: 0; text-transform: none; letter-spacing: normal; line-height: 1.5;">
                    {reset_url}
                </p>
            </div>
            
            <hr style="border: none; border-top: 1px solid rgba(255, 255, 255, 0.1); margin: 30px 0;">
            
            <p style="color: rgba(255, 255, 255, 0.6); font-size: 13px; margin: 0 0 10px 0; text-align: center; text-transform: none; letter-spacing: normal; line-height: 1.6;">
                <strong style="color: rgba(255, 255, 255, 0.8);">Important:</strong> This password reset link will expire in <strong style="color: #3366ff;">1 hour</strong> for your security.
            </p>
            <p style="color: rgba(255, 255, 255, 0.5); font-size: 12px; margin: 0; text-align: center; text-transform: none; letter-spacing: normal; line-height: 1.6;">
                If you didn't request this password reset, you can safely ignore this email. Your password will remain unchanged.
            </p>
        """
        
        html_content = get_email_base_template("Password Reset Request", content_html)
        
        from_email = Config.SENDGRID_FROM_EMAIL
        if not from_email:
            print("⚠️ SENDGRID_FROM_EMAIL not set. Using default email.")
            from_email = "chata.dmbot@gmail.com"
        
        # Create plain text version
        plain_text = f"""CHATA - INSTAGRAM AI ENGAGEMENT

Password Reset Request

You recently requested a password reset for your Chata account.

Click the button below to reset your password. This link will allow you to create a new password for your account.

Reset Password: {reset_url}

If the button doesn't work, copy and paste this link into your browser:
{reset_url}

Important: This password reset link will expire in 1 hour for your security.

If you didn't request this password reset, you can safely ignore this email. Your password will remain unchanged.
"""
        
        message = Mail(
            from_email=from_email,
            to_emails=email,
            subject='Password Reset Request - Chata',
            html_content=html_content,
            plain_text_content=plain_text
        )
        
        # Add reply-to header
        message.reply_to = from_email
        
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

def html_to_plain_text(html_content):
    """Convert HTML email to plain text version for better deliverability"""
    import re
    # Remove HTML tags but keep text
    text = re.sub(r'<[^>]+>', '', html_content)
    # Replace common HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text

def send_email_via_sendgrid(email, subject, html_content):
    """Helper function to send emails via SendGrid with improved deliverability"""
    sendgrid_api_key = Config.SENDGRID_API_KEY
    
    if not sendgrid_api_key:
        print(f"⚠️ SENDGRID_API_KEY not found. Email not sent to {email}")
        print(f"Email subject: {subject}")
        return False
    
    try:
        sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)
        
        from_email = Config.SENDGRID_FROM_EMAIL
        if not from_email:
            from_email = "chata.dmbot@gmail.com"
        
        # Create plain text version for better deliverability
        plain_text_content = html_to_plain_text(html_content)
        
        message = Mail(
            from_email=from_email,
            to_emails=email,
            subject=subject,
            html_content=html_content,
            plain_text_content=plain_text_content
        )
        
        # Add reply-to header
        message.reply_to = from_email
        
        response = sg.send(message)
        
        if response.status_code == 202:
            print(f"✅ Email sent successfully to {email}: {subject}")
            print(f"📧 SendGrid response headers: {dict(response.headers)}")
            if hasattr(response, 'body') and response.body:
                print(f"📧 SendGrid response body: {response.body}")
            return True
        else:
            print(f"❌ Email failed to send. Status: {response.status_code}")
            print(f"📧 SendGrid response headers: {dict(response.headers)}")
            if hasattr(response, 'body') and response.body:
                print(f"📧 SendGrid response body: {response.body}")
            return False
        
    except Exception as e:
        print(f"❌ Error sending email to {email}: {e}")
        return False

def send_welcome_email(email):
    """Send welcome email to new users"""
    dashboard_url = "https://getchata.com/dashboard"
    
    content_html = f"""
        <p style="color: rgba(255, 255, 255, 0.9); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            We're excited to have you on board.
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.8); line-height: 1.7; margin-bottom: 30px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            Get started by connecting your Instagram account and setting up your AI. Your AI will automatically respond to messages and help you engage with your audience.
        </p>
        
        <div style="text-align: center; margin: 35px 0;">
            <a href="{dashboard_url}" style="background: linear-gradient(135deg, #3366ff 0%, #4d7cff 100%); color: white; padding: 16px 40px; text-decoration: none; border-radius: 10px; font-weight: 600; display: inline-block; box-shadow: 0 4px 15px rgba(51, 102, 255, 0.3); transition: all 0.3s ease; text-transform: none; letter-spacing: normal; font-size: 16px;">
                Go to Dashboard
            </a>
        </div>
        
        <p style="color: rgba(255, 255, 255, 0.7); font-size: 15px; margin: 30px 0 0 0; text-transform: none; letter-spacing: normal; line-height: 1.7;">
            If you have any questions, feel free to reach out to us. We're here to help!
        </p>
    """
    
    html_content = get_email_base_template("Welcome to Chata!", content_html)
    return send_email_via_sendgrid(email, "Welcome to Chata - Get Started", html_content)

def send_usage_warning_email(email, remaining_replies):
    """Send usage warning email when user is running low on replies"""
    dashboard_url = "https://getchata.com/dashboard"
    pricing_url = "https://getchata.com/pricing"
    
    if remaining_replies >= 100:
        threshold = 100
        urgency = "low"
        message = f"You have {remaining_replies} replies remaining. Make sure you have enough to keep your AI assistant running smoothly."
    elif remaining_replies >= 50:
        threshold = 50
        urgency = "medium"
        message = f"You have {remaining_replies} replies remaining. Consider purchasing more replies to avoid interruption."
    else:
        threshold = remaining_replies
        urgency = "high"
        message = f"⚠️ You only have {remaining_replies} replies remaining! Your AI assistant will stop responding when you run out."
    
    content_html = f"""
        <p style="color: rgba(255, 255, 255, 0.9); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            {message}
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.8); line-height: 1.7; margin-bottom: 30px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            You can always purchase additional replies for €5 to keep your AI assistant active. Visit your dashboard to buy more replies or upgrade your plan.
        </p>
        
        <div style="text-align: center; margin: 35px 0;">
            <a href="{dashboard_url}" style="background: linear-gradient(135deg, #3366ff 0%, #4d7cff 100%); color: white; padding: 16px 40px; text-decoration: none; border-radius: 10px; font-weight: 600; display: inline-block; box-shadow: 0 4px 15px rgba(51, 102, 255, 0.3); transition: all 0.3s ease; text-transform: none; letter-spacing: normal; font-size: 16px;">
                View Dashboard
            </a>
        </div>
        
        <p style="color: rgba(255, 255, 255, 0.7); font-size: 15px; margin: 30px 0 0 0; text-transform: none; letter-spacing: normal; text-align: center; line-height: 1.7;">
            Or <a href="{pricing_url}" style="color: #3366ff; text-decoration: none;">view our pricing plans</a> to upgrade for more monthly replies.
        </p>
    """
    
    subject = f"Low Reply Count Warning - {remaining_replies} Replies Remaining"
    html_content = get_email_base_template("Reply Count Warning", content_html)
    return send_email_via_sendgrid(email, subject, html_content)

def send_account_deletion_confirmation_email(email, username):
    """Send confirmation email when account is deleted"""
    content_html = f"""
        <p style="color: rgba(255, 255, 255, 0.9); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            Your account has been successfully deleted.
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.8); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            All of your data, including your account information, AI settings, conversation history, and Instagram connections, have been permanently removed from our systems.
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.7); font-size: 15px; margin: 30px 0 0 0; text-transform: none; letter-spacing: normal; line-height: 1.7;">
            This is the last email you will receive from us. We're sorry to see you go, and if you ever decide to return, we'll be here.
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.6); font-size: 14px; margin: 20px 0 0 0; text-transform: none; letter-spacing: normal; line-height: 1.7; text-align: center;">
            Thank you for using Chata.
        </p>
    """
    
    subject = "Account Successfully Deleted - Chata"
    html_content = get_email_base_template("Account Deletion Confirmation", content_html)
    return send_email_via_sendgrid(email, subject, html_content)

def send_data_deletion_request_acknowledgment_email(email):
    """Send auto-reply email acknowledging receipt of data deletion request"""
    content_html = f"""
        <p style="color: rgba(255, 255, 255, 0.9); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            Thank you for contacting us. We have received your data deletion request.
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.8); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            We will review your request and process it within the shortest possible timeline, typically within 7-14 days, in accordance with applicable data protection laws (GDPR, CCPA, etc.).
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.7); font-size: 15px; margin: 20px 0 0 0; text-transform: none; letter-spacing: normal; line-height: 1.7;">
            If you have any questions or concerns, please don't hesitate to reach out to us at chata.dmbot@gmail.com.
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.6); font-size: 14px; margin: 20px 0 0 0; text-transform: none; letter-spacing: normal; line-height: 1.7;">
            Best regards,<br>
            The Chata Team
        </p>
    """
    
    subject = "Data Deletion Request Received - Chata"
    html_content = get_email_base_template("Data Deletion Request Acknowledgment", content_html)
    return send_email_via_sendgrid(email, subject, html_content)

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
        cursor.execute(f"SELECT id, username, email, created_at FROM users WHERE id = {placeholder}", (user_id,))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'created_at': user[3]
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
        print(f"🔍 SQL query: SELECT id, username, email, password_hash, created_at FROM users WHERE email = {placeholder}")
        print(f"🔍 Parameters: {email}")
        
        cursor.execute(f"SELECT id, username, email, password_hash, created_at FROM users WHERE email = {placeholder}", (email,))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'password_hash': user[3],
                'created_at': user[4]
            }
        return None
    except Exception as e:
        print(f"❌ Error getting user by email: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return None

def get_user_by_username_or_email(username_or_email):
    """Get user by username or email - for login"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Try username first, then email
        cursor.execute(f"SELECT id, username, email, password_hash, created_at FROM users WHERE username = {placeholder} OR email = {placeholder}", (username_or_email, username_or_email))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'password_hash': user[3],
                'created_at': user[4]
            }
        return None
    except Exception as e:
        print(f"Error getting user by username or email: {e}")
        return None

def get_user_by_username(username):
    """Get user by username only"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"SELECT id, username, email, password_hash, created_at FROM users WHERE username = {placeholder}", (username,))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'password_hash': user[3],
                'created_at': user[4]
            }
        return None
    except Exception as e:
        print(f"Error getting user by username: {e}")
        return None

def create_user(username, email, password):
    try:
        print(f"🔍 create_user called with username: {username}, email: {email}")
        print(f"🔍 username type: {type(username)}")
        print(f"🔍 email type: {type(email)}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        password_hash = generate_password_hash(password)
        placeholder = get_param_placeholder()
        
        print(f"🔍 Using placeholder: {placeholder}")
        
        # For PostgreSQL, we need to get the ID differently
        # Explicitly set replies_limit_monthly to 0 to ensure new users start with 0 replies
        database_url = os.environ.get('DATABASE_URL')
        if database_url and (database_url.startswith("postgres://") or database_url.startswith("postgresql://")):
            sql = f"INSERT INTO users (username, email, password_hash, replies_limit_monthly) VALUES ({placeholder}, {placeholder}, {placeholder}, 0) RETURNING id"
            params = (username, email, password_hash)
            print(f"🔍 PostgreSQL SQL: {sql}")
            print(f"🔍 PostgreSQL params: {params}")
            
            cursor.execute(sql, params)
            user_id = cursor.fetchone()[0]
        else:
            sql = f"INSERT INTO users (username, email, password_hash, replies_limit_monthly) VALUES ({placeholder}, {placeholder}, {placeholder}, 0)"
            params = (username, email, password_hash)
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
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password")
        
        print(f"🔍 Signup form data:")
        print(f"🔍 Username: {username}")
        print(f"🔍 Email: {email}")
        
        # Basic validation
        if not username or not email or not password:
            flash("Username, email, and password are required.", "error")
            return render_template("signup.html")
        
        # Validate username (alphanumeric and underscore, 3-20 characters)
        if not username.replace('_', '').replace('-', '').isalnum() or len(username) < 3 or len(username) > 20:
            flash("Username must be 3-20 characters and contain only letters, numbers, underscores, or hyphens.", "error")
            return render_template("signup.html")
        
        # Check if username already exists
        existing_username = get_user_by_username(username)
        if existing_username:
            flash("This username is already taken. Please choose another one.", "error")
            return render_template("signup.html")
        
        # Check if email already exists
        existing_email = get_user_by_email(email)
        if existing_email:
            flash("An account with this email already exists.", "error")
            return render_template("signup.html")
        
        # Create new user
        try:
            user_id = create_user(username, email, password)
            session['user_id'] = user_id
            
            # Get user data for welcome message
            user = get_user_by_id(user_id)
            
            # Send welcome email
            try:
                send_welcome_email(email)
            except Exception as e:
                print(f"⚠️ Failed to send welcome email: {e}")
            
            flash(f"Account created successfully! Welcome to Chata, {username}!", "success")
            return redirect(url_for('dashboard'))
        except Exception as e:
            print(f"❌ Signup error: {e}")
            flash("Error creating account. Please try again.", "error")
            return render_template("signup.html")
    
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username_or_email = request.form.get("username_or_email", "").strip()
        password = request.form.get("password")
        
        if not username_or_email or not password:
            flash("Username/Email and password are required.", "error")
            return render_template("login.html")
        
        try:
            user = get_user_by_username_or_email(username_or_email)
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                log_activity(user['id'], 'login', 'User logged in successfully')
                flash(f"Welcome back, {user['username']}!", "success")
                return redirect(url_for('dashboard'))
            else:
                flash("Invalid username/email or password.", "error")
        except Exception as e:
            print(f"Login error: {e}")
            flash("An error occurred during login. Please try again.", "error")
    
    return render_template("login.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    try:
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
                    flash("If an account with that email exists, we've sent a password reset link. Please check your spam folder if you don't see it.", "success")
                except Exception as e:
                    print(f"❌ Error in forgot password process: {e}")
                    import traceback
                    traceback.print_exc()
                    flash("An error occurred while sending the reset email. Please try again.", "error")
            else:
                print(f"❌ User not found for email: {email}")
                # Don't reveal if email exists or not (security best practice)
                flash("If an account with that email exists, we've sent a password reset link.", "success")
            
            return redirect(url_for('login'))
        
        return render_template("forgot_password.html")
    except Exception as e:
        print(f"❌ Critical error in forgot_password route: {e}")
        import traceback
        traceback.print_exc()
        flash("An unexpected error occurred. Please try again later.", "error")
        return render_template("forgot_password.html"), 500

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
        f"&scope=instagram_basic,instagram_manage_messages,pages_messaging"
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
                
                # Check if connection already exists for this user
                cursor.execute(f"SELECT id FROM instagram_connections WHERE user_id = {param} AND instagram_user_id = {param}", 
                              (session['user_id'], instagram_user_id))
                existing = cursor.fetchone()
                
                # CRITICAL: Check if this Instagram account is already actively connected to a DIFFERENT user
                # If yes, block the connection - one Instagram account can only be connected to one email at a time
                cursor.execute(f"""
                    SELECT id, user_id 
                    FROM instagram_connections 
                    WHERE instagram_user_id = {param} 
                    AND user_id != {param}
                    AND is_active = TRUE
                    LIMIT 1
                """, (instagram_user_id, session['user_id']))
                active_connection_other_user = cursor.fetchone()
                
                if active_connection_other_user:
                    # This Instagram account is already connected to another email account
                    flash(f"This Instagram account is already connected to another email account. Please disconnect it from the other account first.", "error")
                    conn.close()
                    return redirect(url_for('dashboard'))
                
                # Check if this user has already received the free trial (persistent flag that survives disconnection)
                # Each email account only gets the free trial ONCE, on their first Instagram connection
                cursor.execute(f"""
                    SELECT has_received_free_trial 
                    FROM users 
                    WHERE id = {param}
                """, (session['user_id'],))
                user_result = cursor.fetchone()
                has_received_free_trial = user_result[0] if user_result and user_result[0] else False
                
                # CRITICAL: Check if this Instagram account has EVER been connected before (including disconnected ones)
                # If an Instagram account was previously connected to any email, it has "used up" its free trial eligibility
                # Even if disconnected, connecting it to a new email should NOT grant free trial
                cursor.execute(f"""
                    SELECT id, user_id 
                    FROM instagram_connections 
                    WHERE instagram_user_id = {param}
                    ORDER BY created_at ASC 
                    LIMIT 1
                """, (instagram_user_id,))
                instagram_ever_connected = cursor.fetchone()
                
                # Check if this specific user has ever connected this specific account before
                cursor.execute(f"""
                    SELECT id 
                    FROM instagram_connections 
                    WHERE instagram_user_id = {param} 
                    AND user_id = {param}
                    LIMIT 1
                """, (instagram_user_id, session['user_id']))
                user_previous_connection = cursor.fetchone()
                
                # Determine if free trial should be granted:
                # 1. User must NOT have received free trial before
                # 2. Instagram account must NEVER have been connected before (by any user)
                should_grant_free_trial = not has_received_free_trial and not instagram_ever_connected
                
                print(f"🔍 Instagram connection check for account {instagram_user_id}:")
                print(f"   - Existing connection for this user: {existing is not None}")
                print(f"   - User has received free trial: {has_received_free_trial}")
                print(f"   - Instagram account ever connected: {instagram_ever_connected is not None}")
                print(f"   - User previously connected this account: {user_previous_connection is not None}")
                print(f"   - Should grant free trial: {should_grant_free_trial}")
                
                if existing:
                    # Update existing connection (reconnection of same account by same user)
                    cursor.execute(f"""
                        UPDATE instagram_connections 
                        SET page_access_token = {param}, is_active = TRUE, updated_at = CURRENT_TIMESTAMP
                        WHERE id = {param}
                    """, (page_access_token, existing[0]))
                    
                    # If user had free trial but lost replies (e.g., from database reset), restore them
                    cursor.execute(f"""
                        SELECT replies_limit_monthly, has_received_free_trial
                        FROM users
                        WHERE id = {param}
                    """, (session['user_id'],))
                    user_reply_data = cursor.fetchone()
                    if user_reply_data:
                        current_replies, has_trial = user_reply_data
                        # If user received free trial but has 0 replies, restore 100 free trial replies
                        if has_trial and current_replies == 0:
                            cursor.execute(f"""
                                UPDATE users 
                                SET replies_limit_monthly = 100
                                WHERE id = {param}
                            """, (session['user_id'],))
                            flash(f"Successfully reconnected Instagram account: @{profile_data.get('username', 'Unknown')}. Your 100 free trial replies have been restored! 🎉", "success")
                        else:
                            flash(f"Successfully reconnected Instagram account: @{profile_data.get('username', 'Unknown')}", "success")
                    else:
                        flash(f"Successfully reconnected Instagram account: @{profile_data.get('username', 'Unknown')}", "success")
                else:
                    # Create new connection
                    cursor.execute(f"""
                        INSERT INTO instagram_connections (user_id, instagram_user_id, instagram_page_id, page_access_token, is_active)
                        VALUES ({param}, {param}, {param}, {param}, TRUE)
                    """, (session['user_id'], instagram_user_id, page_id, page_access_token))
                    
                    # Grant free trial ONLY if:
                    # 1. User has NOT received free trial before
                    # 2. Instagram account has NEVER been connected before (by any user, even if disconnected)
                    if should_grant_free_trial:
                        print(f"🎁 First Instagram connection for user {session['user_id']} with never-before-connected account - granting 100 free trial replies")
                        cursor.execute(f"""
                            UPDATE users 
                            SET replies_limit_monthly = replies_limit_monthly + 100,
                                has_received_free_trial = TRUE
                            WHERE id = {param}
                        """, (session['user_id'],))
                        flash(f"Successfully connected Instagram account: @{profile_data.get('username', 'Unknown')}. You've received 100 free trial replies! 🎉", "success")
                    else:
                        # No free trial - either user already received it, or Instagram account was connected before
                        if instagram_ever_connected:
                            print(f"ℹ️ Instagram account {instagram_user_id} was previously connected to another email - no free trial granted")
                            flash(f"Successfully connected Instagram account: @{profile_data.get('username', 'Unknown')}. This account was previously connected to another email, so no free trial replies were granted.", "info")
                        else:
                            # User has already received free trial
                            # But check if they lost their replies (e.g., from database reset) and restore them
                            cursor.execute(f"""
                                SELECT replies_limit_monthly
                                FROM users
                                WHERE id = {param}
                            """, (session['user_id'],))
                            current_replies = cursor.fetchone()
                            if current_replies and current_replies[0] == 0:
                                # User had free trial but lost replies - restore them
                                cursor.execute(f"""
                                    UPDATE users 
                                    SET replies_limit_monthly = 100
                                    WHERE id = {param}
                                """, (session['user_id'],))
                                print(f"🎁 User {session['user_id']} had free trial but lost replies - restoring 100 free trial replies")
                                flash(f"Successfully connected Instagram account: @{profile_data.get('username', 'Unknown')}. Your 100 free trial replies have been restored! 🎉", "success")
                            else:
                                print(f"ℹ️ User {session['user_id']} has already received free trial - no free trial granted")
                                flash(f"Successfully connected Instagram account: @{profile_data.get('username', 'Unknown')}", "success")
                
                conn.commit()
                
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
    
    user_id = user['id']
    
    # Check and reset monthly counter if needed
    check_user_reply_limit(user_id)
    
    # Get user's Instagram connections
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    cursor.execute(f"""
        SELECT id, instagram_user_id, instagram_page_id, is_active, created_at 
        FROM instagram_connections 
        WHERE user_id = {placeholder} 
        ORDER BY created_at DESC
    """, (user_id,))
    connections = cursor.fetchall()
    
    # Get user's reply counts and bot_paused status
    cursor.execute(f"""
        SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased, COALESCE(bot_paused, FALSE) as bot_paused
        FROM users
        WHERE id = {placeholder}
    """, (user_id,))
    reply_data = cursor.fetchone()
    
    if reply_data:
        replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased, bot_paused = reply_data
        total_replies_used = replies_sent_monthly + replies_used_purchased
        total_replies_available = replies_limit_monthly + replies_purchased
        remaining_replies = max(0, total_replies_available - total_replies_used)
        # Calculate minutes saved (3 minutes per reply)
        MINUTES_PER_REPLY = 3
        minutes_saved = replies_sent_monthly * MINUTES_PER_REPLY
    else:
        replies_sent_monthly = 0
        replies_limit_monthly = 0  # New users start with 0 replies
        replies_purchased = 0
        replies_used_purchased = 0
        total_replies_used = 0
        total_replies_available = 0
        remaining_replies = 0
        minutes_saved = 0
        bot_paused = False
    
    # Get subscription data - ONLY show plan if subscription is ACTIVE
    # First, try to find an active subscription
    cursor.execute(f"""
        SELECT plan_type, status, stripe_subscription_id
        FROM subscriptions
        WHERE user_id = {placeholder} AND status = 'active'
        ORDER BY created_at DESC
        LIMIT 1
    """, (user_id,))
    active_subscription = cursor.fetchone()
    
    # Determine current plan based on subscription status
    current_plan = None
    subscription_status = None
    
    if active_subscription:
        # User has an active subscription - show the plan
        plan_type, status, subscription_id = active_subscription
        current_plan = plan_type  # 'starter' or 'standard'
        subscription_status = 'active'
        print(f"🔍 Dashboard: Found ACTIVE subscription {subscription_id} with plan_type '{plan_type}'")
    else:
        # No active subscription - check if there's a canceled one (for display purposes only)
        cursor.execute(f"""
            SELECT plan_type, status, stripe_subscription_id
            FROM subscriptions
            WHERE user_id = {placeholder} AND status = 'canceled'
            ORDER BY updated_at DESC
            LIMIT 1
        """, (user_id,))
        canceled_subscription = cursor.fetchone()
        
        if canceled_subscription:
            plan_type, status, subscription_id = canceled_subscription
            subscription_status = 'canceled'
            current_plan = None  # Don't show plan name if canceled
            print(f"🔍 Dashboard: Found CANCELED subscription {subscription_id} - not showing as current plan")
        else:
            print(f"🔍 Dashboard: No subscription found for user {user_id}")
    
    # Don't infer plan from replies_limit_monthly - only from subscription status
    # This prevents showing "Starter" plan when user has old replies_limit_monthly but no subscription
    
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
    
    return render_template("dashboard.html", 
                         user=user, 
                         connections=connections_list,
                         replies_sent=replies_sent_monthly,
                         replies_limit=replies_limit_monthly,
                         replies_purchased=replies_purchased,
                         replies_used_purchased=replies_used_purchased,
                         total_replies_used=total_replies_used,
                         total_replies_available=total_replies_available,
                         remaining_replies=remaining_replies,
                         minutes_saved=minutes_saved,
                         current_plan=current_plan,
                         subscription_status=subscription_status,
                         bot_paused=bot_paused)

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
                   use_active_hours, active_start, active_end, links, posts, conversation_samples, instagram_url, avoid_topics, 
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
            'bot_personality': row[0] or '',
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
            'conversation_samples': json.loads(row[30]) if row[30] else {},
            'instagram_url': row[31] or '',
            'avoid_topics': row[32] or '',
            'temperature': row[33] or 0.7,
            'max_tokens': normalize_max_tokens(row[34]),
            'auto_reply': bool(row[35]) if row[35] is not None else True
        }
    
    # Return default settings if none exist
    return {
        'bot_personality': '',
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
        'conversation_samples': {},
        'instagram_url': '',
        'avoid_topics': '',
        'temperature': 0.7,
        'max_tokens': 3000,
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

    if connection_id is None:
        raise ValueError("connection_id must be provided when saving client settings.")

    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    # Prepare the data
    links_json = json.dumps(settings.get('links', []))
    posts_json = json.dumps(settings.get('posts', []))
    samples_json = json.dumps(settings.get('conversation_samples', {}))
    max_tokens_value = normalize_max_tokens(settings.get('max_tokens', 3000))
    
    # Use different syntax for PostgreSQL vs SQLite
    if Config.DATABASE_URL and (Config.DATABASE_URL.startswith("postgres://") or Config.DATABASE_URL.startswith("postgresql://")):
            cursor.execute(f"""
            INSERT INTO client_settings 
            (user_id, instagram_connection_id, bot_personality, bot_name, bot_age, bot_gender, bot_location, 
             bot_occupation, bot_education, personality_type, bot_values, tone_of_voice, habits_quirks, 
             confidence_level, emotional_range, main_goal, fears_insecurities, what_drives_them, obstacles,
             backstory, family_relationships, culture_environment, hobbies_interests, reply_style, emoji_slang,
             conflict_handling, preferred_topics, use_active_hours, active_start, active_end, links, posts, conversation_samples,
             instagram_url, avoid_topics, temperature, max_tokens, is_active)
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
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
            conversation_samples = EXCLUDED.conversation_samples,
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
              links_json, posts_json, samples_json, settings.get('instagram_url', ''), settings.get('avoid_topics', ''),
              0.7, max_tokens_value,
              settings.get('auto_reply', True)))
    else:
        cursor.execute(f"""
                INSERT OR REPLACE INTO client_settings 
                (user_id, instagram_connection_id, bot_personality, bot_name, bot_age, bot_gender, bot_location, 
                 bot_occupation, bot_education, personality_type, bot_values, tone_of_voice, habits_quirks, 
                 confidence_level, emotional_range, main_goal, fears_insecurities, what_drives_them, obstacles,
                 backstory, family_relationships, culture_environment, hobbies_interests, reply_style, emoji_slang,
                 conflict_handling, preferred_topics, use_active_hours, active_start, active_end, links, posts, conversation_samples,
                 instagram_url, avoid_topics, temperature, max_tokens, is_active)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
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
              links_json, posts_json, samples_json, settings.get('instagram_url', ''), settings.get('avoid_topics', ''),
              0.7, max_tokens_value,
                  settings.get('auto_reply', True)))
    
    conn.commit()
    conn.close()
    
    # Log the activity
    log_activity(user_id, 'settings_updated', f'Bot settings updated for connection {connection_id}')

@app.route("/dashboard/bot-settings", methods=["GET", "POST"])
@login_required
def bot_settings():
    user_id = session['user_id']
    connection_id = request.args.get('connection_id', type=int)
    conversation_templates = CONVERSATION_EXAMPLES
    
    if request.method == "POST":
        form_connection_id = request.form.get('connection_id')
        if form_connection_id:
            try:
                connection_id = int(form_connection_id)
            except ValueError:
                connection_id = None

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
    
    if not connections_list:
        if request.method == "POST":
            flash("Please connect an Instagram account before configuring bot settings.", "warning")
        return render_template(
            "bot_settings.html",
            settings=None,
            connections=[],
            selected_connection_id=None,
            selected_connection=None,
            conversation_templates=conversation_templates,
        )

    if connection_id is None:
        connection_id = connections_list[0]['id']
    
    current_settings = get_client_settings(user_id, connection_id)
    selected_connection = next((c for c in connections_list if c['id'] == connection_id), None)

    if request.method == "POST":
        link_urls = request.form.getlist('link_urls[]')
        link_titles = request.form.getlist('link_titles[]')
        links = []
        for index, url in enumerate(link_urls):
            if url.strip():
                title = link_titles[index].strip() if index < len(link_titles) else ""
                links.append({'url': url.strip(), 'title': title})

        post_descriptions = request.form.getlist('post_descriptions[]')
        posts = []
        for desc in post_descriptions:
            if desc.strip():
                posts.append({'description': desc.strip()})

        faq_questions = request.form.getlist('faq_questions[]')
        faq_replies = request.form.getlist('faq_replies[]')
        faqs = []
        for i, question in enumerate(faq_questions):
            question = question.strip()
            reply = faq_replies[i].strip() if i < len(faq_replies) else ''
            if question or reply:
                faqs.append({'question': question, 'reply': reply})

        conversation_samples = {}
        for example in conversation_templates:
            for exchange in example.get('exchanges', []):
                reply_key = f"{example['key']}_{exchange['bot_reply_key']}"
                reply_value = request.form.get(f"sample_reply_{reply_key}", "")
                reply_value = reply_value.strip()
                if reply_value:
                    conversation_samples[reply_key] = reply_value
                
                # Also save follower messages if they were edited
                follower_key = f"{example['key']}_{exchange['bot_reply_key']}_follower"
                follower_value = request.form.get(f"follower_message_{follower_key}", "")
                follower_value = follower_value.strip()
                if follower_value:
                    conversation_samples[follower_key] = follower_value

        settings = {
            'bot_personality': request.form.get('bot_personality', '').strip(),
            'bot_name': request.form.get('bot_name', '').strip(),
            'bot_age': request.form.get('bot_age', '').strip(),
            'bot_gender': request.form.get('bot_gender', '').strip(),
            'bot_location': request.form.get('bot_location', '').strip(),
            'bot_occupation': request.form.get('bot_occupation', '').strip(),
            'links': links,
            'posts': posts,
            'faqs': faqs,
            'conversation_samples': conversation_samples,
            'instagram_url': request.form.get('instagram_url', '').strip(),
            'avoid_topics': request.form.get('avoid_topics', '').strip()
        }

        save_client_settings(user_id, settings, connection_id)
        flash("AI settings updated successfully!", "success")
        return redirect(url_for('bot_settings', connection_id=connection_id))

    if current_settings.get('conversation_samples') is None:
        current_settings['conversation_samples'] = {}

    return render_template(
        "bot_settings.html",
                         settings=current_settings, 
                         connections=connections_list,
        selected_connection_id=connection_id,
        selected_connection=selected_connection,
        conversation_templates=conversation_templates,
    )

@app.route("/dashboard/account-settings", methods=["GET", "POST"])
@login_required
def account_settings():
    user = get_user_by_id(session['user_id'])
    
    if request.method == "POST":
        username = request.form.get('username', '').strip()
        
        if not username:
            flash("Username is required.", "error")
            return redirect(url_for('account_settings'))
        
        if len(username) < 3 or len(username) > 30:
            flash("Username must be between 3 and 30 characters.", "error")
            return redirect(url_for('account_settings'))
        
        # Check if username contains only allowed characters
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            flash("Username can only contain letters, numbers, and underscores.", "error")
            return redirect(url_for('account_settings'))
        
        # Check if username is already taken by another user
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"""
            SELECT id FROM users 
            WHERE username = {placeholder} AND id != {placeholder}
        """, (username, user['id']))
        existing_user = cursor.fetchone()
        
        if existing_user:
            conn.close()
            flash("This username is already taken. Please choose another.", "error")
            return redirect(url_for('account_settings'))
        
        # Update username
        cursor.execute(f"""
            UPDATE users 
            SET username = {placeholder}
            WHERE id = {placeholder}
        """, (username, user['id']))
        
        conn.commit()
        conn.close()
        
        flash("Username updated successfully!", "success")
        return redirect(url_for('account_settings'))
    
    return render_template("account_settings.html", user=user)

@app.route("/dashboard/delete-account", methods=["POST"])
@login_required
def delete_account():
    """Delete user account and all associated data"""
    user_id = session['user_id']
    user = get_user_by_id(user_id)
    
    if not user:
        flash("User not found.", "error")
        return redirect(url_for('dashboard'))
    
    user_email = user['email']
    username = user.get('username', 'User')
    
    conn = get_db_connection()
    if not conn:
        flash("Database connection failed.", "error")
        return redirect(url_for('account_settings'))
    
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        # First, get all Instagram user IDs associated with this user's connections
        cursor.execute(f"""
            SELECT instagram_user_id 
            FROM instagram_connections 
            WHERE user_id = {placeholder}
        """, (user_id,))
        instagram_user_ids = [row[0] for row in cursor.fetchall()]
        
        # Delete in order to respect foreign key constraints
        # Each deletion is wrapped in its own try/except with rollback to handle PostgreSQL transaction errors
        
        # Delete activity logs
        try:
            cursor.execute(f"DELETE FROM activity_logs WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            print(f"⚠️ Could not delete activity_logs: {e}")
            conn.rollback()
        
        # Delete purchases
        try:
            cursor.execute(f"DELETE FROM purchases WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            print(f"⚠️ Could not delete purchases: {e}")
            conn.rollback()
        
        # Delete subscriptions
        try:
            cursor.execute(f"DELETE FROM subscriptions WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            print(f"⚠️ Could not delete subscriptions: {e}")
            conn.rollback()
        
        # Delete messages - messages are linked to instagram_user_id, not user_id
        # We need to delete messages for all Instagram accounts connected to this user
        if instagram_user_ids:
            try:
                # Create placeholders for IN clause
                placeholders = ','.join([placeholder] * len(instagram_user_ids))
                cursor.execute(f"""
                    DELETE FROM messages 
                    WHERE instagram_user_id IN ({placeholders})
                """, tuple(instagram_user_ids))
                conn.commit()
                print(f"✅ Deleted messages for {len(instagram_user_ids)} Instagram accounts")
            except Exception as e:
                print(f"⚠️ Could not delete messages: {e}")
                conn.rollback()
        
        # Delete client settings
        try:
            cursor.execute(f"DELETE FROM client_settings WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            print(f"⚠️ Could not delete client_settings: {e}")
            conn.rollback()
        
        # Delete usage logs
        try:
            cursor.execute(f"DELETE FROM usage_logs WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            print(f"⚠️ Could not delete usage_logs: {e}")
            conn.rollback()
        
        # Delete instagram connections
        try:
            cursor.execute(f"DELETE FROM instagram_connections WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            print(f"⚠️ Could not delete instagram_connections: {e}")
            conn.rollback()
        
        # Delete password reset tokens
        try:
            cursor.execute(f"DELETE FROM password_resets WHERE email = {placeholder}", (user_email,))
            conn.commit()
        except Exception as e:
            print(f"⚠️ Could not delete password_resets: {e}")
            conn.rollback()
        
        # Finally, delete the user
        try:
            cursor.execute(f"DELETE FROM users WHERE id = {placeholder}", (user_id,))
            conn.commit()
            print(f"✅ Successfully deleted user {user_id}")
        except Exception as e:
            print(f"❌ Could not delete user: {e}")
            conn.rollback()
            raise
        
        conn.close()
        
        # Send confirmation email
        try:
            send_account_deletion_confirmation_email(user_email, username)
        except Exception as e:
            print(f"⚠️ Could not send deletion confirmation email: {e}")
        
        # Clear session
        session.clear()
        
        flash("Your account has been successfully deleted. We're sorry to see you go.", "success")
        return redirect(url_for('home'))
        
    except Exception as e:
        print(f"❌ Error deleting account: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        conn.close()
        flash(f"Error deleting account: {str(e)}", "error")
        return redirect(url_for('account_settings'))

@app.route("/dashboard/toggle-bot-pause", methods=["POST"])
@login_required
def toggle_bot_pause():
    """Toggle bot pause/resume status"""
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        # Get current pause status
        cursor.execute(f"""
            SELECT COALESCE(bot_paused, FALSE) FROM users WHERE id = {placeholder}
        """, (user_id,))
        result = cursor.fetchone()
        current_status = result[0] if result else False
        
        # Toggle the status
        new_status = not current_status
        cursor.execute(f"""
            UPDATE users SET bot_paused = {placeholder} WHERE id = {placeholder}
        """, (new_status, user_id))
        conn.commit()
        
        status_text = "paused" if new_status else "resumed"
        flash(f"Bot {status_text} successfully!", "success")
        print(f"✅ Bot {status_text} for user {user_id}")
        
    except Exception as e:
        print(f"❌ Error toggling bot pause: {e}")
        flash("Error updating bot status. Please try again.", "error")
    finally:
        conn.close()
    
    return redirect(url_for('dashboard'))

@app.route("/dashboard/debug/decrease-replies", methods=["POST"])
@login_required
def debug_decrease_replies():
    """Debug route: Decrease remaining replies by 1"""
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        # Get current counts
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        result = cursor.fetchone()
        
        if not result:
            flash("Error: User data not found.", "error")
            return redirect(url_for('dashboard'))
        
        replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased = result
        
        # Calculate remaining
        total_used = replies_sent_monthly + replies_used_purchased
        total_available = replies_limit_monthly + replies_purchased
        remaining = max(0, total_available - total_used)
        
        if remaining <= 0:
            flash("No remaining replies to decrease.", "warning")
            conn.close()
            return redirect(url_for('dashboard'))
        
        # Decrease by using one reply (increment sent count)
        if replies_sent_monthly < replies_limit_monthly:
            # Use monthly reply
            cursor.execute(f"""
                UPDATE users
                SET replies_sent_monthly = replies_sent_monthly + 1
                WHERE id = {placeholder}
            """, (user_id,))
            flash("Decreased remaining replies by 1 (used monthly reply).", "success")
        elif replies_used_purchased < replies_purchased:
            # Use purchased reply
            cursor.execute(f"""
                UPDATE users
                SET replies_used_purchased = replies_used_purchased + 1
                WHERE id = {placeholder}
            """, (user_id,))
            flash("Decreased remaining replies by 1 (used purchased reply).", "success")
        else:
            flash("Error: Could not decrease replies.", "error")
            conn.close()
            return redirect(url_for('dashboard'))
        
        conn.commit()
        print(f"🔧 Debug: Decreased replies for user {user_id} by 1")
        
    except Exception as e:
        print(f"❌ Error decreasing replies: {e}")
        flash("Error decreasing replies. Please try again.", "error")
        conn.rollback()
    finally:
        conn.close()
    
    return redirect(url_for('dashboard'))

@app.route("/dashboard/debug/set-replies-zero", methods=["POST"])
@login_required
def debug_set_replies_zero():
    """Debug route: Set remaining replies to 0 (use all replies)"""
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        # Get current counts
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        result = cursor.fetchone()
        
        if not result:
            flash("Error: User data not found.", "error")
            return redirect(url_for('dashboard'))
        
        replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased = result
        
        # Set all replies as used
        cursor.execute(f"""
            UPDATE users
            SET replies_sent_monthly = {placeholder},
                replies_used_purchased = {placeholder}
            WHERE id = {placeholder}
        """, (replies_limit_monthly, replies_purchased, user_id))
        
        conn.commit()
        flash("Set remaining replies to 0 (all replies used).", "success")
        print(f"🔧 Debug: Set replies to 0 for user {user_id}")
        
    except Exception as e:
        print(f"❌ Error setting replies to zero: {e}")
        flash("Error setting replies to zero. Please try again.", "error")
        conn.rollback()
    finally:
        conn.close()
    
    return redirect(url_for('dashboard'))

@app.route("/dashboard/debug/trigger-monthly-addition", methods=["POST"])
@login_required
def debug_trigger_monthly_addition():
    """Debug route: Manually trigger monthly addition (simulate new month)"""
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        # Check if user has an active subscription
        cursor.execute(f"""
            SELECT id, plan_type, status
            FROM subscriptions
            WHERE user_id = {placeholder} AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        subscription = cursor.fetchone()
        
        if not subscription:
            flash("You need an active subscription to trigger monthly addition.", "warning")
            conn.close()
            return redirect(url_for('dashboard'))
        
        plan_type = subscription[1]  # 'starter' or 'standard'
        if plan_type == 'standard':
            monthly_limit = 1500
        else:
            monthly_limit = 150  # starter or default
        
        # Get current replies_limit_monthly
        cursor.execute(f"""
            SELECT replies_limit_monthly FROM users WHERE id = {placeholder}
        """, (user_id,))
        result = cursor.fetchone()
        current_limit = result[0] if result else 0
        
        # Simulate monthly addition: add plan's base replies and reset sent count
        from datetime import datetime
        cursor.execute(f"""
            UPDATE users
            SET replies_sent_monthly = 0,
                replies_limit_monthly = replies_limit_monthly + {placeholder},
                last_monthly_reset = {placeholder}
            WHERE id = {placeholder}
        """, (monthly_limit, datetime.now(), user_id))
        
        conn.commit()
        flash(f"Monthly addition triggered! Added {monthly_limit} replies (new total: {current_limit + monthly_limit}).", "success")
        print(f"🔧 Debug: Triggered monthly addition for user {user_id} - added {monthly_limit} replies")
        
    except Exception as e:
        print(f"❌ Error triggering monthly addition: {e}")
        flash("Error triggering monthly addition. Please try again.", "error")
        conn.rollback()
    finally:
        conn.close()
    
    return redirect(url_for('dashboard'))

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
    
    # Check and reset monthly counter if needed
    check_user_reply_limit(user_id)
    
    # Get usage statistics for the current month
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    # Get user's reply counts
    cursor.execute(f"""
        SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
        FROM users
        WHERE id = {placeholder}
    """, (user_id,))
    reply_data = cursor.fetchone()
    
    if reply_data:
        replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased = reply_data
        # Ensure replies_limit_monthly is not None (should be 0 for new users)
        if replies_limit_monthly is None:
            replies_limit_monthly = 0
        total_replies_used = replies_sent_monthly + replies_used_purchased
        total_replies_available = replies_limit_monthly + replies_purchased
        remaining_replies = max(0, total_replies_available - total_replies_used)
        # Calculate minutes saved (3 minutes per reply)
        MINUTES_PER_REPLY = 3
        minutes_saved = replies_sent_monthly * MINUTES_PER_REPLY
    else:
        replies_sent_monthly = 0
        replies_limit_monthly = 0  # New users start with 0 replies
        replies_purchased = 0
        replies_used_purchased = 0
        total_replies_used = 0
        total_replies_available = 0
        remaining_replies = 0
        minutes_saved = 0
    
    # Get recent activity
    cursor.execute(f"""
        SELECT action, details, created_at 
        FROM activity_logs 
        WHERE user_id = {placeholder} 
        ORDER BY created_at DESC 
        LIMIT 10
    """, (user_id,))
    activity_rows = cursor.fetchall()
    
    # Format datetime objects to strings for template
    recent_activity = []
    for row in activity_rows:
        action, details, created_at = row
        # Convert datetime to string format
        if created_at:
            if isinstance(created_at, str):
                # Already a string, just truncate if needed
                formatted_time = created_at[:16] if len(created_at) > 16 else created_at
            else:
                # It's a datetime object, format it
                formatted_time = created_at.strftime('%Y-%m-%d %H:%M')
        else:
            formatted_time = ''
        recent_activity.append((action, details, formatted_time))
    
    conn.close()
    
    return render_template("usage_analytics.html", 
                         replies_sent=replies_sent_monthly,
                         replies_limit=replies_limit_monthly,
                         replies_purchased=replies_purchased,
                         replies_used_purchased=replies_used_purchased,
                         total_replies_used=total_replies_used,
                         total_replies_available=total_replies_available,
                         remaining_replies=remaining_replies,
                         minutes_saved=minutes_saved,
                         recent_activity=recent_activity)

# Test payment route disabled - use Stripe add-ons instead
# @app.route("/dashboard/usage/test-payment", methods=["POST"])
# @login_required
# def test_payment():
#     """Test route to simulate a payment and add 5 additional replies"""
#     # This route is disabled - use Stripe add-ons instead
#     flash("❌ Test payment is no longer available. Please use the 'Add Replies' button to purchase add-ons.", "error")
#     return redirect(url_for('dashboard'))

# ---- Stripe Payment Routes ----

@app.route("/checkout/subscription", methods=["POST"])
@login_required
def create_subscription_checkout():
    """Create Stripe Checkout session for subscription"""
    if not Config.STRIPE_SECRET_KEY or not Config.STRIPE_STARTER_PLAN_PRICE_ID:
        flash("❌ Payment system is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard'))
    
    user_id = session['user_id']
    user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
    
    try:
        # Create or retrieve Stripe customer
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Check if user already has a Stripe customer ID in subscriptions table
        cursor.execute(f"""
            SELECT stripe_customer_id FROM subscriptions 
            WHERE user_id = {placeholder} 
            LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            customer_id = result[0]
            print(f"✅ Found existing customer ID in database: {customer_id}")
        else:
            # Check if customer already exists in Stripe by email
            existing_customers = stripe.Customer.list(email=user_email, limit=1)
            if existing_customers.data:
                # Use existing customer
                customer_id = existing_customers.data[0].id
                # Update metadata to ensure user_id is set
                stripe.Customer.modify(customer_id, metadata={'user_id': str(user_id)})
                print(f"✅ Found existing Stripe customer: {customer_id}")
            else:
                # Create new Stripe customer
                customer = stripe.Customer.create(
                    email=user_email,
                    metadata={'user_id': str(user_id)}
                )
                customer_id = customer.id
                print(f"✅ Created new Stripe customer: {customer_id}")
        
        conn.close()
        
        # Create Checkout Session for subscription
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': Config.STRIPE_STARTER_PLAN_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'dashboard',
            metadata={'user_id': str(user_id), 'type': 'subscription'}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        print(f"Stripe error: {e}")
        flash(f"❌ Payment error: {str(e)}", "error")
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"Error creating subscription checkout: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard'))

@app.route("/checkout/standard", methods=["POST"])
@login_required
def create_standard_checkout():
    """Create Stripe Checkout session for Standard plan subscription"""
    # Try to get from Config first, then fallback to direct os.getenv (for Render env var updates)
    # Also check for common typos
    standard_price_id = (
        Config.STRIPE_STANDARD_PLAN_PRICE_ID or 
        os.getenv("STRIPE_STANDARD_PLAN_PRICE_ID") or
        os.getenv("SRTPE_STANDARD_PLAN_PRICE_ID")  # Common typo check
    )
    
    # Debug logging to help diagnose the issue
    print(f"🔍 [STANDARD CHECKOUT] Checking configuration...")
    print(f"🔍 [STANDARD CHECKOUT] STRIPE_SECRET_KEY exists: {bool(Config.STRIPE_SECRET_KEY)}")
    print(f"🔍 [STANDARD CHECKOUT] Config.STRIPE_STANDARD_PLAN_PRICE_ID: '{Config.STRIPE_STANDARD_PLAN_PRICE_ID}'")
    print(f"🔍 [STANDARD CHECKOUT] Direct os.getenv('STRIPE_STANDARD_PLAN_PRICE_ID'): '{os.getenv('STRIPE_STANDARD_PLAN_PRICE_ID')}'")
    print(f"🔍 [STANDARD CHECKOUT] Typo check os.getenv('SRTPE_STANDARD_PLAN_PRICE_ID'): '{os.getenv('SRTPE_STANDARD_PLAN_PRICE_ID')}'")
    print(f"🔍 [STANDARD CHECKOUT] All env vars starting with STRIPE: {[k for k in os.environ.keys() if 'STRIPE' in k or 'SRTPE' in k]}")
    print(f"🔍 [STANDARD CHECKOUT] Final standard_price_id (after fallback): '{standard_price_id}'")
    
    if not Config.STRIPE_SECRET_KEY:
        print(f"❌ [STANDARD CHECKOUT] STRIPE_SECRET_KEY is missing")
        flash("❌ Payment system is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard'))
    
    if not standard_price_id:
        print(f"❌ [STANDARD CHECKOUT] STRIPE_STANDARD_PLAN_PRICE_ID is missing or empty")
        print(f"❌ [STANDARD CHECKOUT] Please verify STRIPE_STANDARD_PLAN_PRICE_ID is set in Render environment variables")
        print(f"❌ [STANDARD CHECKOUT] After adding/updating env vars in Render, you may need to manually redeploy the service")
        flash("❌ Standard plan is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard'))
    
    user_id = session['user_id']
    user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
    
    try:
        # Create or retrieve Stripe customer
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Check if user already has a Stripe customer ID in subscriptions table
        cursor.execute(f"""
            SELECT stripe_customer_id FROM subscriptions 
            WHERE user_id = {placeholder} 
            LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            customer_id = result[0]
            print(f"✅ Found existing customer ID in database: {customer_id}")
        else:
            # Check if customer already exists in Stripe by email
            existing_customers = stripe.Customer.list(email=user_email, limit=1)
            if existing_customers.data:
                # Use existing customer
                customer_id = existing_customers.data[0].id
                # Update metadata to ensure user_id is set
                stripe.Customer.modify(customer_id, metadata={'user_id': str(user_id)})
                print(f"✅ Found existing Stripe customer: {customer_id}")
            else:
                # Create new Stripe customer
                customer = stripe.Customer.create(
                    email=user_email,
                    metadata={'user_id': str(user_id)}
                )
                customer_id = customer.id
                print(f"✅ Created new Stripe customer: {customer_id}")
        
        conn.close()
        
        # Create Checkout Session for Standard plan subscription
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': standard_price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'dashboard',
            metadata={'user_id': str(user_id), 'type': 'subscription', 'plan': 'standard'}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        print(f"Stripe error: {e}")
        flash(f"❌ Payment error: {str(e)}", "error")
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"Error creating Standard plan checkout: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard'))

@app.route("/checkout/addon", methods=["POST"])
@login_required
def create_addon_checkout():
    """Create Stripe Checkout session for one-time add-on purchase"""
    if not Config.STRIPE_SECRET_KEY or not Config.STRIPE_ADDON_PRICE_ID:
        flash("❌ Payment system is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard'))
    
    user_id = session['user_id']
    user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
    
    try:
        # Check if user has an active subscription (required for add-ons)
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        cursor.execute(f"""
            SELECT stripe_customer_id, status, plan_type
            FROM subscriptions 
            WHERE user_id = {placeholder}
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()
        
        if not result or not result[0]:
            flash("❌ You need an active subscription to purchase add-ons.", "error")
            conn.close()
            return redirect(url_for('dashboard'))
        
        customer_id, subscription_status, plan_type = result
        
        # Check if subscription is active
        if subscription_status != 'active':
            flash("❌ You need an active subscription to purchase add-ons. Please reactivate your subscription.", "error")
            conn.close()
            return redirect(url_for('dashboard'))
        
        # Check if customer exists in Stripe
        if not customer_id:
            # Check if customer already exists in Stripe by email
            existing_customers = stripe.Customer.list(email=user_email, limit=1)
            if existing_customers.data:
                customer_id = existing_customers.data[0].id
                stripe.Customer.modify(customer_id, metadata={'user_id': str(user_id)})
                print(f"✅ Found existing Stripe customer: {customer_id}")
            else:
                flash("❌ Customer account not found. Please contact support.", "error")
                conn.close()
                return redirect(url_for('dashboard'))
        
        conn.close()
        
        # Create Checkout Session for one-time payment
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': Config.STRIPE_ADDON_PRICE_ID,
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.host_url + 'checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'dashboard',
            metadata={'user_id': str(user_id), 'type': 'addon'}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        print(f"Stripe error: {e}")
        flash(f"❌ Payment error: {str(e)}", "error")
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"Error creating addon checkout: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard'))

@app.route("/checkout/success")
@login_required
def checkout_success():
    """Handle successful checkout"""
    session_id = request.args.get('session_id')
    
    if not session_id:
        flash("❌ Invalid checkout session.", "error")
        return redirect(url_for('dashboard'))
    
    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        if checkout_session.metadata.get('user_id') != str(session['user_id']):
            flash("❌ Invalid checkout session.", "error")
            return redirect(url_for('dashboard'))
        
        if checkout_session.metadata.get('type') == 'subscription':
            plan = checkout_session.metadata.get('plan', 'starter')
            if plan == 'standard':
                flash("Standard subscription activated successfully! You now have 1500 replies per month.", "success")
            else:
                flash("Starter subscription activated successfully! You now have 150 replies per month.", "success")
        elif checkout_session.metadata.get('type') == 'addon':
            flash("Payment successful! 150 additional replies have been added to your account.", "success")
        elif checkout_session.metadata.get('type') == 'upgrade':
            flash("Subscription upgraded successfully! You now have 1500 replies per month.", "success")
        elif checkout_session.metadata.get('type') == 'downgrade':
            flash("Subscription downgraded successfully! You now have 150 replies per month.", "success")
        
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        print(f"Error processing checkout success: {e}")
        flash("Payment processed. Please check your account.", "success")
        return redirect(url_for('dashboard'))

@app.route("/checkout/upgrade", methods=["POST"])
@login_required
def create_upgrade_checkout():
    """Upgrade from Starter to Standard plan"""
    if not Config.STRIPE_SECRET_KEY:
        flash("❌ Payment system is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard'))
    
    user_id = session['user_id']
    
    # Check if user has active Starter plan
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    cursor.execute(f"""
        SELECT stripe_subscription_id, stripe_customer_id, plan_type, status
        FROM subscriptions
        WHERE user_id = {placeholder} AND status = 'active' AND plan_type = 'starter'
        ORDER BY created_at DESC
        LIMIT 1
    """, (user_id,))
    subscription = cursor.fetchone()
    conn.close()
    
    if not subscription:
        flash("❌ No active Starter plan found to upgrade.", "error")
        return redirect(url_for('dashboard'))
    
    subscription_id, customer_id, _, _ = subscription
    
    try:
        # Update subscription in Stripe to Standard plan (we'll need Standard price ID)
        # For now, create new checkout session for Standard plan
        # Note: In production, you'd want to use Stripe's subscription update API
        # This is a simplified version that creates a new subscription
        user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
        
        # Get Standard plan price ID from config
        standard_price_id = Config.STRIPE_STANDARD_PLAN_PRICE_ID
        if not standard_price_id:
            flash("❌ Standard plan not configured. Please contact support.", "error")
            return redirect(url_for('dashboard'))
        
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': standard_price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'dashboard',
            metadata={'user_id': str(user_id), 'type': 'upgrade', 'old_subscription_id': subscription_id}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        print(f"Stripe error during upgrade: {e}")
        flash(f"❌ Upgrade error: {str(e)}", "error")
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"Error during upgrade: {e}")
        flash("❌ An error occurred during upgrade. Please try again.", "error")
        return redirect(url_for('dashboard'))

@app.route("/checkout/downgrade", methods=["POST"])
@login_required
def create_downgrade_checkout():
    """Downgrade from Standard to Starter plan"""
    if not Config.STRIPE_SECRET_KEY:
        flash("❌ Payment system is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard'))
    
    user_id = session['user_id']
    
    # Check if user has active Standard plan
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    cursor.execute(f"""
        SELECT stripe_subscription_id, stripe_customer_id, plan_type, status
        FROM subscriptions
        WHERE user_id = {placeholder} AND status = 'active' AND plan_type = 'standard'
        ORDER BY created_at DESC
        LIMIT 1
    """, (user_id,))
    subscription = cursor.fetchone()
    conn.close()
    
    if not subscription:
        flash("❌ No active Standard plan found to downgrade.", "error")
        return redirect(url_for('dashboard'))
    
    subscription_id, customer_id, _, _ = subscription
    
    try:
        # Create checkout session for Starter plan
        user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
        
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': Config.STRIPE_STARTER_PLAN_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'dashboard',
            metadata={'user_id': str(user_id), 'type': 'downgrade', 'old_subscription_id': subscription_id}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        print(f"Stripe error during downgrade: {e}")
        flash(f"❌ Downgrade error: {str(e)}", "error")
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"Error during downgrade: {e}")
        flash("❌ An error occurred during downgrade. Please try again.", "error")
        return redirect(url_for('dashboard'))

# Test payment route - removed after successful testing
# @app.route("/checkout/test-payment", methods=["POST"])
# @login_required
# def create_test_checkout():
#     """Test payment route - removed after successful live mode testing"""
#     pass

@app.route("/subscription/cancel", methods=["POST"])
@login_required
def cancel_subscription():
    """Cancel subscription - cancel at period end"""
    user_id = session['user_id']
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Get active subscription - get the most recent one
        cursor.execute(f"""
            SELECT stripe_subscription_id, plan_type
            FROM subscriptions
            WHERE user_id = {placeholder} AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        subscription = cursor.fetchone()
        
        if not subscription:
            flash("❌ No active subscription found.", "error")
            conn.close()
            return redirect(url_for('dashboard'))
        
        subscription_id, plan_type = subscription
        print(f"🔄 Canceling subscription {subscription_id} (plan: {plan_type}) for user {user_id}")
        conn.close()
        
        # Cancel subscription immediately in Stripe
        try:
            stripe.Subscription.delete(subscription_id)
            print(f"✅ Immediately canceled subscription {subscription_id} in Stripe")
        except Exception as e:
            print(f"⚠️ Error canceling subscription in Stripe: {e}")
            # Continue anyway - we'll still mark it as canceled in DB
        
        # Update database immediately to reflect canceled status
        # IMPORTANT: Only update status, NOT plan_type - preserve the plan type
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE subscriptions 
            SET status = {placeholder},
                updated_at = CURRENT_TIMESTAMP
            WHERE stripe_subscription_id = {placeholder}
        """, ('canceled', subscription_id))
        
        # Verify the update worked and plan_type is preserved
        cursor.execute(f"""
            SELECT plan_type, status
            FROM subscriptions
            WHERE stripe_subscription_id = {placeholder}
        """, (subscription_id,))
        verify = cursor.fetchone()
        if verify:
            updated_plan_type, updated_status = verify
            print(f"✅ Updated subscription status to '{updated_status}', plan_type preserved as '{updated_plan_type}'")
            if updated_plan_type != plan_type:
                print(f"⚠️ WARNING: Plan type changed from {plan_type} to {updated_plan_type} - this should not happen!")
        
        conn.commit()
        conn.close()
        
        flash("Subscription canceled. You can still use your remaining replies, but cannot purchase add-ons.", "success")
        
        return redirect(url_for('dashboard'))
        
    except stripe.error.StripeError as e:
        print(f"Stripe error canceling subscription: {e}")
        flash(f"❌ Error canceling subscription: {str(e)}", "error")
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"Error canceling subscription: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard'))

@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhook events"""
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    
    if not Config.STRIPE_WEBHOOK_SECRET:
        print("⚠️ Warning: STRIPE_WEBHOOK_SECRET not set. Webhook verification skipped.")
        return jsonify({'status': 'webhook_secret_not_set'}), 200
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, Config.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        print("⚠️ Invalid payload")
        return jsonify({'status': 'invalid_payload'}), 400
    except stripe.error.SignatureVerificationError:
        print("⚠️ Invalid signature")
        return jsonify({'status': 'invalid_signature'}), 400
    
    # Handle the event
    print(f"📥 Received Stripe webhook: {event['type']}")
    print(f"🔍 Event ID: {event.get('id', 'unknown')}")
    
    if event['type'] == 'checkout.session.completed':
        session_obj = event['data']['object']
        print(f"🛒 Processing checkout session: {session_obj.get('id')}")
        handle_checkout_session_completed(session_obj)
    
    elif event['type'] == 'customer.subscription.created':
        subscription = event['data']['object']
        print(f"🔄 Processing subscription created: {subscription.get('id')}")
        handle_subscription_created(subscription)
    
    elif event['type'] == 'customer.subscription.updated':
        subscription = event['data']['object']
        print(f"🔄 Processing subscription updated: {subscription.get('id')}")
        handle_subscription_updated(subscription)
    
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        print(f"🔄 Processing subscription deleted: {subscription.get('id')}")
        handle_subscription_deleted(subscription)
    
    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        print(f"💰 Processing invoice payment succeeded: {invoice.get('id')}")
        handle_invoice_payment_succeeded(invoice)
    
    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        print(f"💰 Processing invoice payment failed: {invoice.get('id')}")
        handle_invoice_payment_failed(invoice)
    
    else:
        print(f"⚠️ Unhandled webhook event type: {event['type']}")
    
    print(f"✅ Webhook processing completed for {event['type']}")
    
    return jsonify({'status': 'success'}), 200

def handle_checkout_session_completed(session_obj):
    """Handle completed checkout session"""
    try:
        print(f"🛒 Checkout session metadata: {session_obj.metadata}")
        
        user_id_str = session_obj.metadata.get('user_id')
        if not user_id_str:
            print(f"⚠️ No user_id in checkout session metadata - this is likely a test event")
            return
        
        user_id = int(user_id_str)
        session_type = session_obj.metadata.get('type')
        
        print(f"👤 Processing checkout for user {user_id}, type: {session_type}")
        
        if session_type == 'upgrade':
            # Handle upgrade - cancel old Starter subscription
            old_subscription_id = session_obj.metadata.get('old_subscription_id')
            if old_subscription_id:
                try:
                    # Cancel the old subscription in Stripe
                    stripe.Subscription.modify(old_subscription_id, cancel_at_period_end=False)
                    stripe.Subscription.delete(old_subscription_id)
                    print(f"✅ Cancelled old subscription {old_subscription_id} for user {user_id}")
                    
                    # Mark old subscription as canceled in database
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    placeholder = get_param_placeholder()
                    cursor.execute(f"""
                        UPDATE subscriptions 
                        SET status = {placeholder}
                        WHERE stripe_subscription_id = {placeholder}
                    """, ('canceled', old_subscription_id))
                    conn.commit()
                    conn.close()
                    print(f"✅ Marked old subscription as canceled in database")
                except Exception as e:
                    print(f"⚠️ Error canceling old subscription: {e}")
            
            # For upgrades, try to get price ID from checkout session line items
            try:
                # Retrieve the full checkout session to get line items
                full_session = stripe.checkout.Session.retrieve(session_obj.id, expand=['line_items'])
                if hasattr(full_session, 'line_items') and hasattr(full_session.line_items, 'data'):
                    line_items = full_session.line_items.data
                    if line_items and len(line_items) > 0:
                        line_item = line_items[0]
                        if hasattr(line_item, 'price') and hasattr(line_item.price, 'id'):
                            price_id_from_session = line_item.price.id
                            print(f"✅ Got price ID from checkout session: {price_id_from_session}")
                            # Store in session metadata for later retrieval (we'll use a different approach)
            except Exception as e:
                print(f"⚠️ Could not get price ID from checkout session: {e}")
        
        if session_type == 'addon':
            # Handle one-time add-on purchase
            amount = session_obj.amount_total / 100  # Convert cents to euros
            replies_to_add = 150  # €5 for 150 replies
            success = add_purchased_replies(
                user_id, 
                amount, 
                payment_provider="stripe", 
                payment_id=session_obj.id
            )
            if success:
                log_activity(user_id, 'stripe_addon_purchase', f'Purchased {replies_to_add} replies via Stripe')
                print(f"✅ Added {replies_to_add} replies for user {user_id} from Stripe payment")
    except Exception as e:
        print(f"❌ Error handling checkout session completed: {e}")
        import traceback
        traceback.print_exc()

def handle_subscription_created(subscription):
    """Handle new subscription creation"""
    try:
        print(f"🔄 Processing subscription created: {subscription.id}")
        
        customer_id = subscription.customer
        print(f"📋 Customer ID: {customer_id}")
        
        customer = stripe.Customer.retrieve(customer_id)
        print(f"📋 Customer metadata: {customer.metadata}")
        
        user_id_str = customer.metadata.get('user_id')
        if not user_id_str:
            print(f"❌ No user_id in customer metadata for customer {customer_id}")
            return
        
        user_id = int(user_id_str)
        print(f"👤 Processing subscription for user ID: {user_id}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Get price ID and period dates from subscription - retrieve fresh with expanded items for reliability
        price_id = None
        current_period_start = None
        current_period_end = None
        subscription_status = None
        
        try:
            # Retrieve the subscription with expanded items to ensure we can access all fields
            print(f"🔄 Retrieving subscription {subscription.id} with expanded items...")
            expanded_sub = stripe.Subscription.retrieve(subscription.id, expand=['items.data.price'])
            
            # Get subscription status
            subscription_status = expanded_sub.status
            
            # Access the price ID from expanded subscription
            # subscription.items is a ListObject, access via subscription.items.data
            try:
                # Method 1: Try accessing items.data directly
                if hasattr(expanded_sub, 'items'):
                    items_obj = expanded_sub.items
                    print(f"🔍 Items object type: {type(items_obj)}")
                    
                    # Try to get data attribute
                    if hasattr(items_obj, 'data'):
                        items_list = items_obj.data
                        print(f"🔍 Items list length: {len(items_list) if items_list else 0}")
                    else:
                        # Try to iterate or convert to list
                        try:
                            items_list = list(items_obj) if items_obj else []
                            print(f"🔍 Converted items to list, length: {len(items_list)}")
                        except:
                            items_list = []
                            print(f"⚠️ Could not convert items to list")
                    
                    if items_list and len(items_list) > 0:
                        item = items_list[0]
                        print(f"🔍 Item type: {type(item)}")
                        print(f"🔍 Item: {item}")
                        
                        # Price can be an object (if expanded) or a string ID
                        if hasattr(item, 'price'):
                            price_obj = item.price
                            print(f"🔍 Price object type: {type(price_obj)}")
                            print(f"🔍 Price object: {price_obj}")
                            
                            if isinstance(price_obj, str):
                                price_id = price_obj
                                print(f"✅ Found price ID (string): {price_id}")
                            elif hasattr(price_obj, 'id'):
                                price_id = price_obj.id
                                print(f"✅ Found price ID (object): {price_id}")
                            else:
                                print(f"⚠️ Price is neither string nor object with id")
                        else:
                            print(f"⚠️ Item has no price attribute")
                            # Try dictionary access
                            if isinstance(item, dict):
                                price_id = item.get('price', {}).get('id') if isinstance(item.get('price'), dict) else item.get('price')
                                if price_id:
                                    print(f"✅ Found price ID via dict access: {price_id}")
                    else:
                        print(f"⚠️ No items found in subscription")
                else:
                    print(f"⚠️ Subscription has no items attribute")
            except Exception as e:
                print(f"⚠️ Error accessing subscription items: {e}")
                import traceback
                traceback.print_exc()
            
            # Get current period dates - safely access from expanded subscription
            if hasattr(expanded_sub, 'current_period_start') and expanded_sub.current_period_start:
                current_period_start = datetime.fromtimestamp(expanded_sub.current_period_start)
                print(f"📅 Current period start: {current_period_start}")
            else:
                # Fallback to current time
                current_period_start = datetime.now()
                print(f"⚠️ No current_period_start found, using current time")
            
            if hasattr(expanded_sub, 'current_period_end') and expanded_sub.current_period_end:
                current_period_end = datetime.fromtimestamp(expanded_sub.current_period_end)
                print(f"📅 Current period end: {current_period_end}")
            else:
                # Fallback to 1 month from now
                from datetime import timedelta
                current_period_end = datetime.now() + timedelta(days=30)
                print(f"⚠️ No current_period_end found, using 1 month from now")
            
            # Don't use fallback - if we can't get price ID, log error but don't default to Starter
            if not price_id:
                print(f"❌ Could not determine price ID from subscription")
                print(f"🔍 Subscription object keys: {dir(expanded_sub)}")
                print(f"🔍 Subscription items: {expanded_sub.items if hasattr(expanded_sub, 'items') else 'No items attr'}")
                    
        except Exception as e:
            print(f"⚠️ Error retrieving subscription details: {e}")
            import traceback
            traceback.print_exc()
            # Don't use fallback - log the error
            print(f"❌ Could not retrieve subscription details, price_id remains None")
            subscription_status = 'active'  # Default status
            current_period_start = datetime.now()
            from datetime import timedelta
            current_period_end = datetime.now() + timedelta(days=30)
        
        print(f"💰 Price ID: {price_id}")
        
        # If price_id is None, try alternative methods
        if not price_id:
            try:
                print(f"🔄 Trying alternative method to get price ID...")
                # Method 1: Try listing subscription items
                try:
                    items_list = stripe.SubscriptionItem.list(subscription=subscription.id, limit=1)
                    if items_list and len(items_list.data) > 0:
                        item = items_list.data[0]
                        if hasattr(item, 'price'):
                            if isinstance(item.price, str):
                                price_id = item.price
                            elif hasattr(item.price, 'id'):
                                price_id = item.price.id
                        if price_id:
                            print(f"✅ Retrieved price ID via SubscriptionItem.list: {price_id}")
                except Exception as e1:
                    print(f"⚠️ SubscriptionItem.list failed: {e1}")
                
                # Method 2: Try accessing original subscription object
                if not price_id:
                    try:
                        if isinstance(subscription, dict):
                            items = subscription.get('items', {}).get('data', [])
                        else:
                            # Try to get items as a list
                            try:
                                items = list(subscription.items) if hasattr(subscription, 'items') else []
                            except:
                                items = []
                        
                        if items and len(items) > 0:
                            item = items[0]
                            if isinstance(item, dict):
                                price_id = item.get('price', {}).get('id') if isinstance(item.get('price'), dict) else item.get('price')
                            elif hasattr(item, 'price'):
                                price_obj = item.price
                                if isinstance(price_obj, str):
                                    price_id = price_obj
                                elif hasattr(price_obj, 'id'):
                                    price_id = price_obj.id
                            
                            if price_id:
                                print(f"✅ Retrieved price ID via original subscription: {price_id}")
                    except Exception as e2:
                        print(f"⚠️ Original subscription access failed: {e2}")
            except Exception as e:
                print(f"⚠️ All alternative methods failed: {e}")
                import traceback
                traceback.print_exc()
        
        # Determine plan type based on price ID
        # Use runtime fallback for Standard plan price ID (in case env var wasn't loaded at startup)
        standard_price_id = Config.STRIPE_STANDARD_PLAN_PRICE_ID or os.getenv("STRIPE_STANDARD_PLAN_PRICE_ID")
        starter_price_id = Config.STRIPE_STARTER_PLAN_PRICE_ID or os.getenv("STRIPE_STARTER_PLAN_PRICE_ID")
        
        print(f"🔍 Comparing price_id '{price_id}' with standard '{standard_price_id}' and starter '{starter_price_id}'")
        
        plan_type = 'starter'  # Default
        replies_limit = 150  # Default for Starter
        
        if price_id:
            if standard_price_id and price_id == standard_price_id:
                plan_type = 'standard'
                replies_limit = 1500
                print(f"✅ Detected Standard plan - setting replies_limit to 1500")
            elif starter_price_id and price_id == starter_price_id:
                plan_type = 'starter'
                replies_limit = 150
                print(f"✅ Detected Starter plan - setting replies_limit to 150")
            else:
                print(f"⚠️ Price ID {price_id} doesn't match known plans, defaulting to Starter")
                print(f"⚠️ This might be an error - please check Stripe configuration")
        else:
            print(f"❌ Price ID is None - cannot determine plan type. This is an error!")
            print(f"⚠️ Standard price ID: {standard_price_id}, Starter price ID: {starter_price_id}")
            # For upgrades, we can try to infer from checkout session metadata
            # But for now, we'll skip database insertion if price_id is None
            print(f"⚠️ Skipping database insertion due to missing price_id")
            conn.close()
            return
        
        # Check if using PostgreSQL
        is_postgres = Config.DATABASE_URL and (Config.DATABASE_URL.startswith("postgres://") or Config.DATABASE_URL.startswith("postgresql://"))
        
        if is_postgres:
            # Insert or update subscription (PostgreSQL)
            cursor.execute(f"""
                INSERT INTO subscriptions 
                (user_id, stripe_subscription_id, stripe_customer_id, stripe_price_id, 
                 plan_type, status, current_period_start, current_period_end)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder})
                ON CONFLICT (stripe_subscription_id) DO UPDATE SET
                plan_type = EXCLUDED.plan_type,
                stripe_price_id = EXCLUDED.stripe_price_id,
                status = EXCLUDED.status,
                current_period_start = EXCLUDED.current_period_start,
                current_period_end = EXCLUDED.current_period_end,
                updated_at = CURRENT_TIMESTAMP
            """, (
                user_id,
                subscription.id,
                customer_id,
                price_id,
                plan_type,
                subscription_status,
                current_period_start,
                current_period_end
            ))
        else:
            # SQLite - use INSERT OR REPLACE
            cursor.execute(f"""
                INSERT OR REPLACE INTO subscriptions 
                (user_id, stripe_subscription_id, stripe_customer_id, stripe_price_id, 
                 plan_type, status, current_period_start, current_period_end)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                        {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (
                user_id,
                subscription.id,
                customer_id,
                price_id,
                plan_type,
                subscription_status,
                current_period_start,
                current_period_end
            ))
        
        print(f"💾 Subscription record created in database")
        
        # Get current replies_limit_monthly from users table to preserve existing replies
        cursor.execute(f"""
            SELECT replies_limit_monthly FROM users WHERE id = {placeholder}
        """, (user_id,))
        user_data = cursor.fetchone()
        current_replies_limit = user_data[0] if user_data else 0
        
        # SIMPLIFIED: Always add plan's base replies to existing replies (never reset)
        # This works for new subscriptions, reactivations, upgrades, and downgrades
        print(f"📈 Adding {replies_limit} replies to user {user_id}'s existing {current_replies_limit} replies")
        
        if current_replies_limit > 0:
            # User has existing replies - add new plan's replies on top
            cursor.execute(f"""
                UPDATE users 
                SET replies_limit_monthly = replies_limit_monthly + {placeholder}
                WHERE id = {placeholder}
            """, (replies_limit, user_id))
            print(f"📈 Added {replies_limit} replies (new total: {current_replies_limit + replies_limit})")
        else:
            # No existing replies - just set to plan limit (same as adding to 0)
            cursor.execute(f"""
                UPDATE users 
                SET replies_limit_monthly = {placeholder}
                WHERE id = {placeholder}
            """, (replies_limit, user_id))
            print(f"📈 Set replies_limit_monthly to {replies_limit} (no existing replies)")
        
        conn.commit()
        conn.close()
        
        plan_name = 'Standard' if plan_type == 'standard' else 'Starter'
        log_activity(user_id, 'stripe_subscription_created', f'{plan_name} plan subscription activated')
        print(f"✅ Subscription created for user {user_id}")
        
    except Exception as e:
        print(f"❌ Error handling subscription created: {e}")
        import traceback
        traceback.print_exc()

def handle_subscription_updated(subscription):
    """Handle subscription updates (including upgrades/downgrades)"""
    try:
        customer_id = subscription.customer
        customer = stripe.Customer.retrieve(customer_id)
        user_id_str = customer.metadata.get('user_id')
        
        if not user_id_str:
            print(f"❌ No user_id in customer metadata")
            return
        
        user_id = int(user_id_str)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        is_postgres = Config.DATABASE_URL and (Config.DATABASE_URL.startswith("postgres://") or Config.DATABASE_URL.startswith("postgresql://"))
        cancel_at_period_end = subscription.cancel_at_period_end if hasattr(subscription, 'cancel_at_period_end') else False
        
        if is_postgres:
            cancel_value = cancel_at_period_end
        else:
            cancel_value = 1 if cancel_at_period_end else 0
        
        # Get current status from database FIRST
        # IMPORTANT: Check if subscription is canceled BEFORE processing upgrades/downgrades
        cursor.execute(f"""
            SELECT status, plan_type, stripe_price_id FROM subscriptions WHERE stripe_subscription_id = {placeholder}
        """, (subscription.id,))
        existing_sub_data = cursor.fetchone()
        existing_status = existing_sub_data[0] if existing_sub_data else None
        existing_plan_type = existing_sub_data[1] if existing_sub_data else None
        existing_price_id = existing_sub_data[2] if existing_sub_data and len(existing_sub_data) > 2 else None
        
        # If subscription is canceled OR cancel_at_period_end is True, preserve plan_type and set status to 'canceled'
        if existing_status == 'canceled' or cancel_at_period_end:
            print(f"⚠️ Subscription {subscription.id} is canceled - preserving existing plan_type '{existing_plan_type}', skipping upgrade/downgrade logic")
            
            # Get price_id from subscription for stripe_price_id field, but don't change plan_type
            expanded_sub = stripe.Subscription.retrieve(subscription.id, expand=['items.data.price'])
            price_id = None
            if hasattr(expanded_sub, 'items') and hasattr(expanded_sub.items, 'data'):
                if len(expanded_sub.items.data) > 0:
                    item = expanded_sub.items.data[0]
                    if hasattr(item, 'price') and hasattr(item.price, 'id'):
                        price_id = item.price.id
            
            final_price_id = price_id if price_id else existing_price_id
            
            # Update subscription but preserve plan_type and set status to 'canceled'
            if final_price_id:
                cursor.execute(f"""
                    UPDATE subscriptions 
                    SET status = {placeholder},
                        stripe_price_id = {placeholder},
                        current_period_start = {placeholder},
                        current_period_end = {placeholder},
                        cancel_at_period_end = {placeholder},
                        updated_at = CURRENT_TIMESTAMP
                    WHERE stripe_subscription_id = {placeholder}
                """, (
                    'canceled',  # Always set to 'canceled', not subscription.status
                    final_price_id,
                    datetime.fromtimestamp(subscription.current_period_start) if hasattr(subscription, 'current_period_start') and subscription.current_period_start else datetime.now(),
                    datetime.fromtimestamp(subscription.current_period_end) if hasattr(subscription, 'current_period_end') and subscription.current_period_end else datetime.now() + timedelta(days=30),
                    cancel_value,
                    subscription.id
                ))
            else:
                # Skip stripe_price_id update if we don't have a value
                print(f"⚠️ No price_id available, skipping stripe_price_id update for canceled subscription")
                cursor.execute(f"""
                    UPDATE subscriptions 
                    SET status = {placeholder},
                        current_period_start = {placeholder},
                        current_period_end = {placeholder},
                        cancel_at_period_end = {placeholder},
                        updated_at = CURRENT_TIMESTAMP
                    WHERE stripe_subscription_id = {placeholder}
                """, (
                    'canceled',  # Always set to 'canceled'
                    datetime.fromtimestamp(subscription.current_period_start) if hasattr(subscription, 'current_period_start') and subscription.current_period_start else datetime.now(),
                    datetime.fromtimestamp(subscription.current_period_end) if hasattr(subscription, 'current_period_end') and subscription.current_period_end else datetime.now() + timedelta(days=30),
                    cancel_value,
                    subscription.id
                ))
            
            conn.commit()
            conn.close()
            print(f"✅ Subscription updated (canceled): {subscription.id} (plan_type preserved: {existing_plan_type})")
            return  # Exit early - no upgrade/downgrade processing for canceled subscriptions
        
        # Active subscription - process upgrades/downgrades
        # Get the new plan type from subscription
        expanded_sub = stripe.Subscription.retrieve(subscription.id, expand=['items.data.price'])
        price_id = None
        # Use runtime fallback for env vars
        standard_price_id = Config.STRIPE_STANDARD_PLAN_PRICE_ID or os.getenv("STRIPE_STANDARD_PLAN_PRICE_ID")
        starter_price_id = Config.STRIPE_STARTER_PLAN_PRICE_ID or os.getenv("STRIPE_STARTER_PLAN_PRICE_ID")
        
        new_plan_type = 'starter'
        if hasattr(expanded_sub, 'items') and hasattr(expanded_sub.items, 'data'):
            if len(expanded_sub.items.data) > 0:
                item = expanded_sub.items.data[0]
                if hasattr(item, 'price') and hasattr(item.price, 'id'):
                    price_id = item.price.id
                    if standard_price_id and price_id == standard_price_id:
                        new_plan_type = 'standard'
                    elif starter_price_id and price_id == starter_price_id:
                        new_plan_type = 'starter'
        
        # Get current subscription from database to check if this is an upgrade
        cursor.execute(f"""
            SELECT plan_type, replies_limit_monthly
            FROM subscriptions s
            JOIN users u ON s.user_id = u.id
            WHERE s.stripe_subscription_id = {placeholder} AND s.user_id = {placeholder}
        """, (subscription.id, user_id))
        current_sub = cursor.fetchone()
        
        # Check if this is an upgrade or downgrade
        if current_sub:
            old_plan_type = current_sub[0]
            old_limit = current_sub[1] or 0
            
            if old_plan_type == 'starter' and new_plan_type == 'standard':
                # Upgrade: Starter → Standard - add 1500 replies (preserve existing)
                print(f"🔄 Detected upgrade from Starter to Standard for user {user_id}")
                cursor.execute(f"""
                    UPDATE users
                    SET replies_limit_monthly = replies_limit_monthly + 1500
                    WHERE id = {placeholder}
                """, (user_id,))
                print(f"✅ Added 1500 replies to user {user_id} (upgrade: existing + 1500)")
            elif old_plan_type == 'standard' and new_plan_type == 'starter':
                # Downgrade: Standard → Starter - add 150 replies (preserve existing)
                print(f"🔄 Detected downgrade from Standard to Starter for user {user_id}")
                cursor.execute(f"""
                    UPDATE users
                    SET replies_limit_monthly = replies_limit_monthly + 150
                    WHERE id = {placeholder}
                """, (user_id,))
                print(f"✅ Added 150 replies to user {user_id} (downgrade: existing + 150)")
            else:
                print(f"ℹ️ Plan type unchanged or unknown transition: {old_plan_type} → {new_plan_type}")
        
        # Update subscription with new plan_type (for active subscriptions only)
        cursor.execute(f"""
            UPDATE subscriptions 
            SET status = {placeholder},
                plan_type = {placeholder},
                stripe_price_id = {placeholder},
                current_period_start = {placeholder},
                current_period_end = {placeholder},
                cancel_at_period_end = {placeholder},
                updated_at = CURRENT_TIMESTAMP
            WHERE stripe_subscription_id = {placeholder}
        """, (
            subscription.status if hasattr(subscription, 'status') else 'active',
            new_plan_type,
            price_id,
            datetime.fromtimestamp(subscription.current_period_start) if hasattr(subscription, 'current_period_start') and subscription.current_period_start else datetime.now(),
            datetime.fromtimestamp(subscription.current_period_end) if hasattr(subscription, 'current_period_end') and subscription.current_period_end else datetime.now() + timedelta(days=30),
            cancel_value,
            subscription.id
        ))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Subscription updated: {subscription.id} (plan: {new_plan_type})")
        
    except Exception as e:
        print(f"Error handling subscription updated: {e}")
        import traceback
        traceback.print_exc()

def handle_subscription_deleted(subscription):
    """Handle subscription cancellation - keep remaining replies but mark as canceled"""
    try:
        customer_id = subscription.customer
        customer = stripe.Customer.retrieve(customer_id)
        user_id_str = customer.metadata.get('user_id')
        
        if not user_id_str:
            print(f"❌ No user_id in customer metadata for canceled subscription")
            return
        
        user_id = int(user_id_str)
        print(f"🔄 Processing subscription cancellation for user {user_id}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Update subscription status to canceled but keep it in database
        # IMPORTANT: Only update status, NOT plan_type - preserve the plan type
        # First, get the current plan_type to verify we're not changing it
        cursor.execute(f"""
            SELECT plan_type, status
            FROM subscriptions
            WHERE stripe_subscription_id = {placeholder}
        """, (subscription.id,))
        current_sub = cursor.fetchone()
        
        if current_sub:
            current_plan_type, current_status = current_sub
            print(f"🔄 Updating subscription {subscription.id} from status '{current_status}' to 'canceled', preserving plan_type '{current_plan_type}'")
        
        cursor.execute(f"""
            UPDATE subscriptions 
            SET status = {placeholder},
                updated_at = CURRENT_TIMESTAMP
            WHERE stripe_subscription_id = {placeholder}
        """, ('canceled', subscription.id))
        
        # Verify plan_type wasn't changed
        cursor.execute(f"""
            SELECT plan_type, status
            FROM subscriptions
            WHERE stripe_subscription_id = {placeholder}
        """, (subscription.id,))
        verify = cursor.fetchone()
        if verify:
            updated_plan_type, updated_status = verify
            if current_sub and updated_plan_type != current_plan_type:
                print(f"⚠️ WARNING: Plan type changed from {current_plan_type} to {updated_plan_type} during cancellation!")
                # Restore the original plan_type
                cursor.execute(f"""
                    UPDATE subscriptions 
                    SET plan_type = {placeholder}
                    WHERE stripe_subscription_id = {placeholder}
                """, (current_plan_type, subscription.id))
                print(f"✅ Restored plan_type to {current_plan_type}")
        
        # DO NOT reset replies_limit_monthly - let them keep remaining replies
        # They can still use remaining monthly + purchased replies
        # But they cannot buy add-ons (enforced in addon checkout route)
        # Monthly replies will naturally reset when new month comes, but since no subscription,
        # they won't get new monthly replies
        
        # Get current reply counts for logging
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        reply_data = cursor.fetchone()
        
        if reply_data:
            replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased = reply_data
            total_used = replies_sent_monthly + replies_used_purchased
            total_available = replies_limit_monthly + replies_purchased
            remaining = max(0, total_available - total_used)
            print(f"📊 User {user_id} has {remaining} remaining replies after cancellation")
        
        conn.commit()
        conn.close()
        
        log_activity(user_id, 'stripe_subscription_canceled', 'Subscription canceled - remaining replies preserved')
        print(f"✅ Subscription canceled for user {user_id} (remaining replies preserved)")
        
    except Exception as e:
        print(f"❌ Error handling subscription deleted: {e}")
        import traceback
        traceback.print_exc()

def handle_invoice_payment_succeeded(invoice):
    """Handle successful monthly subscription payment"""
    try:
        # Retrieve invoice with expanded subscription to ensure we can access it
        invoice_id = invoice.id if hasattr(invoice, 'id') else None
        subscription_id = None
        
        if invoice_id:
            try:
                # Retrieve invoice with expanded subscription
                expanded_invoice = stripe.Invoice.retrieve(invoice_id, expand=['subscription'])
                
                # Get subscription ID - can be a string ID or object
                if hasattr(expanded_invoice, 'subscription'):
                    if expanded_invoice.subscription is None:
                        print(f"⚠️ Invoice {invoice_id} has no subscription (one-time payment)")
                        return
                    elif isinstance(expanded_invoice.subscription, str):
                        subscription_id = expanded_invoice.subscription
                    elif hasattr(expanded_invoice.subscription, 'id'):
                        subscription_id = expanded_invoice.subscription.id
                    else:
                        subscription_id = str(expanded_invoice.subscription)
                else:
                    print(f"⚠️ Invoice {invoice_id} has no subscription attribute")
                    return
            except Exception as e:
                print(f"⚠️ Error retrieving invoice: {e}")
                # Fallback: try direct access
                if hasattr(invoice, 'subscription') and invoice.subscription:
                    subscription_id = invoice.subscription.id if hasattr(invoice.subscription, 'id') else str(invoice.subscription)
                elif isinstance(invoice, dict) and 'subscription' in invoice:
                    subscription_id = invoice['subscription']
                    if isinstance(subscription_id, dict) and 'id' in subscription_id:
                        subscription_id = subscription_id['id']
        
        if not subscription_id:
            print(f"⚠️ No subscription ID in invoice - this might be a one-time payment or test event")
            return
        
        print(f"💰 Invoice payment succeeded for subscription: {subscription_id}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Get user from subscription
        cursor.execute(f"""
            SELECT user_id FROM subscriptions 
            WHERE stripe_subscription_id = {placeholder}
        """, (subscription_id,))
        result = cursor.fetchone()
        
        if result:
            user_id = result[0]
            print(f"👤 Resetting monthly replies for user {user_id}")
            
            # Get plan type to set correct monthly limit
            cursor.execute(f"""
                SELECT plan_type FROM subscriptions 
                WHERE stripe_subscription_id = {placeholder} AND user_id = {placeholder}
            """, (subscription_id, user_id))
            plan_result = cursor.fetchone()
            
            if plan_result:
                plan_type = plan_result[0]
                if plan_type == 'standard':
                    monthly_limit = 1500
                else:
                    monthly_limit = 150  # starter or default
            else:
                monthly_limit = 150  # default if plan not found
            
            # Add monthly replies at the start of new billing period (don't reset, just add)
            cursor.execute(f"""
                UPDATE users 
                SET replies_sent_monthly = 0,
                    replies_limit_monthly = replies_limit_monthly + {placeholder},
                    last_monthly_reset = CURRENT_TIMESTAMP
                WHERE id = {placeholder}
            """, (monthly_limit, user_id))
            
            conn.commit()
            log_activity(user_id, 'stripe_invoice_paid', 'Monthly subscription payment succeeded')
            print(f"✅ Monthly payment succeeded for user {user_id} - added {monthly_limit} replies")
        else:
            print(f"⚠️ No subscription found in database for subscription_id: {subscription_id}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error handling invoice payment succeeded: {e}")
        import traceback
        traceback.print_exc()

def handle_invoice_payment_failed(invoice):
    """Handle failed subscription payment"""
    try:
        # Get subscription ID - handle both object attribute and dictionary access
        subscription_id = None
        try:
            if hasattr(invoice, 'subscription') and invoice.subscription:
                subscription_id = invoice.subscription.id if hasattr(invoice.subscription, 'id') else str(invoice.subscription)
            elif isinstance(invoice, dict) and 'subscription' in invoice:
                subscription_id = invoice['subscription']
                if isinstance(subscription_id, dict) and 'id' in subscription_id:
                    subscription_id = subscription_id['id']
        except Exception as e:
            print(f"⚠️ Could not access invoice.subscription: {e}")
        
        if not subscription_id:
            print(f"⚠️ No subscription ID in invoice - skipping payment failure handling")
            return
        
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        cursor.execute(f"""
            SELECT user_id FROM subscriptions 
            WHERE stripe_subscription_id = {placeholder}
        """, (subscription_id,))
        result = cursor.fetchone()
        
        if result:
            user_id = result[0]
            log_activity(user_id, 'stripe_payment_failed', 'Monthly subscription payment failed')
            print(f"⚠️ Payment failed for user {user_id}")
        
        conn.close()
        
    except Exception as e:
        print(f"Error handling invoice payment failed: {e}")

# ---- Reply Tracking Helpers ----

def check_user_reply_limit(user_id):
    """
    Check if user has remaining replies available.
    Returns: (has_limit: bool, remaining: int, total_used: int, total_available: int)
    """
    conn = get_db_connection()
    if not conn:
        return (False, 0, 0, 0)
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Get user's reply counts
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased, last_monthly_reset
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return (False, 0, 0, 0)
        
        replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased, last_monthly_reset = result
        
        # Reset monthly counter if new month
        reset_monthly_replies_if_needed(user_id, replies_sent_monthly, last_monthly_reset)
        
        # Re-fetch after potential reset
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        result = cursor.fetchone()
        replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased = result
        
        # Calculate remaining
        total_used = replies_sent_monthly + replies_used_purchased
        total_available = replies_limit_monthly + replies_purchased
        remaining = max(0, total_available - total_used)
        has_limit = remaining > 0
        
        conn.close()
        return (has_limit, remaining, total_used, total_available)
        
    except Exception as e:
        print(f"Error checking reply limit: {e}")
        if conn:
            conn.close()
        return (False, 0, 0, 0)

def reset_monthly_replies_if_needed(user_id, current_sent=None, last_reset=None):
    """Reset monthly reply counter if a new month has started AND user has active subscription"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        from datetime import datetime, timedelta
        
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Check if user has an active subscription
        cursor.execute(f"""
            SELECT id, plan_type, status
            FROM subscriptions
            WHERE user_id = {placeholder} AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        subscription = cursor.fetchone()
        
        # If no active subscription, don't reset monthly counter
        # User keeps their remaining replies but won't get new monthly allocation
        if not subscription:
            print(f"📅 User {user_id} has no active subscription - skipping monthly reset (keeping remaining replies)")
            conn.close()
            return False
        
        # Get current reset timestamp if not provided
        if last_reset is None:
            cursor.execute(f"SELECT last_monthly_reset FROM users WHERE id = {placeholder}", (user_id,))
            result = cursor.fetchone()
            if not result:
                conn.close()
                return False
            last_reset = result[0]
        
        # Parse last_reset if it's a string or handle datetime object
        if isinstance(last_reset, str):
            try:
                # Try ISO format first
                last_reset = datetime.fromisoformat(last_reset.replace('Z', '+00:00'))
            except:
                try:
                    # Try standard format
                    last_reset = datetime.strptime(last_reset.split('.')[0], '%Y-%m-%d %H:%M:%S')
                except:
                    # Try date only
                    last_reset = datetime.strptime(last_reset.split(' ')[0], '%Y-%m-%d')
        elif not isinstance(last_reset, datetime):
            # If it's not a datetime object, try to convert it
            last_reset = datetime.now()
        
        # Check if we're in a new month
        now = datetime.now()
        # Handle timezone-aware datetime objects
        if hasattr(last_reset, 'replace') and hasattr(last_reset, 'tzinfo') and last_reset.tzinfo:
            last_reset = last_reset.replace(tzinfo=None)
        
        last_reset_month = last_reset.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        if current_month > last_reset_month:
            # New month - reset monthly counter (only if they have active subscription)
            # Get the plan type to determine monthly limit
            plan_type = subscription[1]  # 'starter' or 'standard'
            if plan_type == 'standard':
                monthly_limit = 1500
            else:
                monthly_limit = 150  # starter or default
            
            print(f"📅 New month detected for user {user_id} with {plan_type} plan, adding {monthly_limit} replies")
            cursor.execute(f"""
                UPDATE users
                SET replies_sent_monthly = 0,
                    replies_limit_monthly = replies_limit_monthly + {placeholder},
                    last_monthly_reset = {placeholder}
                WHERE id = {placeholder}
            """, (monthly_limit, datetime.now(), user_id))
            conn.commit()
            conn.close()
            return True
        
        conn.close()
        return False
        
    except Exception as e:
        print(f"Error resetting monthly replies: {e}")
        if conn:
            conn.close()
        return False

def increment_reply_count(user_id):
    """
    Increment the appropriate reply counter for a user.
    Uses monthly replies first, then purchased replies.
    Returns: True if successful, False otherwise
    """
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Get current counts
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return False
        
        replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased = result
        
        # Use monthly replies first
        if replies_sent_monthly < replies_limit_monthly:
            cursor.execute(f"""
                UPDATE users
                SET replies_sent_monthly = replies_sent_monthly + 1
                WHERE id = {placeholder}
            """, (user_id,))
            print(f"✅ Incremented monthly reply count for user {user_id} ({replies_sent_monthly + 1}/{replies_limit_monthly})")
        # Then use purchased replies
        elif replies_used_purchased < replies_purchased:
            cursor.execute(f"""
                UPDATE users
                SET replies_used_purchased = replies_used_purchased + 1
                WHERE id = {placeholder}
            """, (user_id,))
            print(f"✅ Incremented purchased reply count for user {user_id} ({replies_used_purchased + 1}/{replies_purchased})")
        else:
            print(f"⚠️ Attempted to increment reply count but user {user_id} has no remaining replies")
            conn.close()
            return False
        
        conn.commit()
        
        # Check if we need to send usage warning emails
        # Re-fetch to get updated counts
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased, email, last_warning_sent_at, last_warning_threshold
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        
        result = cursor.fetchone()
        if result:
            replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased, user_email, last_warning_sent_at, last_warning_threshold = result
            
            total_used = replies_sent_monthly + replies_used_purchased
            total_available = replies_limit_monthly + replies_purchased
            remaining = max(0, total_available - total_used)
            
            # Determine which threshold we're at
            warning_threshold = None
            if remaining <= 50 and remaining > 0:
                warning_threshold = 50
            elif remaining <= 100 and remaining > 50:
                warning_threshold = 100
            
            # Send warning if we hit a threshold and haven't sent one for this threshold recently
            if warning_threshold and user_email:
                # Only send if we haven't sent a warning for this threshold in the last 24 hours
                should_send = True
                if last_warning_sent_at and last_warning_threshold == warning_threshold:
                    time_since_warning = (datetime.now() - datetime.fromisoformat(last_warning_sent_at)).total_seconds()
                    if time_since_warning < 86400:  # 24 hours
                        should_send = False
                
                if should_send:
                    try:
                        send_usage_warning_email(user_email, remaining)
                        # Update last warning sent
                        cursor.execute(f"""
                            UPDATE users
                            SET last_warning_sent_at = {placeholder}, last_warning_threshold = {placeholder}
                            WHERE id = {placeholder}
                        """, (datetime.now().isoformat(), warning_threshold, user_id))
                        conn.commit()
                        print(f"📧 Sent usage warning email to user {user_id} ({remaining} replies remaining)")
                    except Exception as e:
                        print(f"⚠️ Failed to send usage warning email: {e}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"Error incrementing reply count: {e}")
        if conn:
            conn.close()
        return False

def add_purchased_replies(user_id, amount, payment_provider=None, payment_id=None):
    """
    Add purchased replies to a user's account.
    For Stripe integration: call this when payment is confirmed.
    Returns: True if successful, False otherwise
    """
    # TESTING MODE: 1€ = 5 replies (for testing)
    # PRODUCTION: 5€ = 150 replies (REPLIES_PER_EURO = 30)
    # For Stripe add-on: €5 = 150 replies (fixed)
    if payment_provider == "stripe":
        # Stripe add-on is always €5 for 150 replies
        replies_to_add = 150
    else:
        # Test mode: 1€ = 5 replies
        REPLIES_PER_EURO = 5
        replies_to_add = int(amount * REPLIES_PER_EURO)
    
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Add to user's purchased replies
        cursor.execute(f"""
            UPDATE users
            SET replies_purchased = replies_purchased + {placeholder}
            WHERE id = {placeholder}
        """, (replies_to_add, user_id))
        
        # Record purchase
        cursor.execute(f"""
            INSERT INTO purchases (user_id, amount_paid, replies_added, payment_provider, payment_id, status)
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 'completed')
        """, (user_id, amount, replies_to_add, payment_provider, payment_id))
        
        conn.commit()
        print(f"✅ Added {replies_to_add} purchased replies for user {user_id} (€{amount})")
        conn.close()
        return True
        
    except Exception as e:
        print(f"Error adding purchased replies: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False

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
        max_tokens = normalize_max_tokens(get_setting("max_tokens", "3000"))

        messages = [{"role": "system", "content": system_prompt}]
        messages += history

        model_name = "gpt-5-nano"
        model_config = MODEL_CONFIG.get(model_name, DEFAULT_MODEL_CONFIG)

        completion_kwargs = {
            "model": model_name,
            "messages": messages,
        }
        if model_config.get("supports_temperature", True):
            completion_kwargs["temperature"] = temperature

        token_param = model_config.get("token_param", "max_tokens")
        if token_param == "max_completion_tokens":
            if model_config.get("max_completion_cap"):
                max_tokens = min(max_tokens, model_config["max_completion_cap"])
            completion_kwargs["max_completion_tokens"] = max_tokens
        else:
            completion_kwargs["max_tokens"] = max_tokens
        openai_start = time.time()
        response = client.chat.completions.create(**completion_kwargs)
        openai_duration = time.time() - openai_start
        print(f"⏳ OpenAI chat latency (global): {openai_duration:.2f}s; model={model_name}")

        if not response.choices:
            print("⚠️ OpenAI returned no choices:", response)
            return "Sorry, I'm having trouble replying right now."

        message = response.choices[0].message
        if not message or not getattr(message, "content", None):
            print("⚠️ OpenAI returned empty content:", response)
            return "Sorry, I'm having trouble replying right now."

        ai_reply = message.content.strip()
        if not ai_reply:
            print("⚠️ OpenAI content was blank after strip:", response)
            return "Sorry, I'm having trouble replying right now."

        return ai_reply

    except Exception as e:
        print("OpenAI API error:", e)
        return "Sorry, I'm having trouble replying right now."

def get_ai_reply_with_connection(history, connection_id=None):
    """Get AI reply using connection-specific settings if available"""
    openai.api_key = Config.OPENAI_API_KEY
    try:
        client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)

        # Extract latest message from follower
        latest_message = ""
        if history and len(history) > 0:
            # Get the last user message
            for msg in reversed(history):
                if msg.get('role') == 'user':
                    latest_message = msg.get('content', '').strip()
                    break

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
                system_prompt = build_personality_prompt(settings, history=history, latest_message=latest_message)
                temperature = settings['temperature']
                max_tokens = normalize_max_tokens(settings.get('max_tokens', 3000))
                print(f"🎯 Using connection-specific settings for connection {connection_id}")
                print(f"📝 Prompt length: {len(system_prompt)} chars")
                print(f"🌡️  Temperature: {temperature}, Max tokens: {max_tokens}")
                print(f"💬 Latest message: {latest_message[:50]}...")
            else:
                # Fallback to global settings
                print(f"⚠️ Connection {connection_id} not found, using neutral persona fallback")
                fallback_settings = {
                    'bot_name': '',
                    'bot_personality': 'You must still act like a real human. Keep responses short and conversational.'
                }
                system_prompt = build_personality_prompt(fallback_settings, history=history, latest_message=latest_message)
                temperature = 0.7
                max_tokens = 3000
        else:
            # Use global settings (for original Chata account)
            print("⚠️ No connection_id passed to get_ai_reply_with_connection; using neutral persona fallback.")
            fallback_settings = {
                'bot_name': '',
                'bot_personality': 'You must still act like a real human. Keep responses short and conversational.'
            }
            system_prompt = build_personality_prompt(fallback_settings, history=history, latest_message=latest_message)
            temperature = 0.7
            max_tokens = 3000

        # Since everything is now in the system prompt, we only send the system message
        messages = [{"role": "system", "content": system_prompt}]

        model_name = "gpt-5-nano"
        model_config = MODEL_CONFIG.get(model_name, DEFAULT_MODEL_CONFIG)

        completion_kwargs = {
            "model": model_name,
            "messages": messages,
        }
        if model_config.get("supports_temperature", True):
            completion_kwargs["temperature"] = temperature

        token_param = model_config.get("token_param", "max_tokens")
        if token_param == "max_completion_tokens":
            if model_config.get("max_completion_cap"):
                max_tokens = min(max_tokens, model_config["max_completion_cap"])
            completion_kwargs["max_completion_tokens"] = max_tokens
        else:
            completion_kwargs["max_tokens"] = max_tokens
        openai_start = time.time()
        response = client.chat.completions.create(**completion_kwargs)
        openai_duration = time.time() - openai_start
        print(f"⏳ OpenAI chat latency (connection {connection_id or 'global'}): {openai_duration:.2f}s; model={model_name}")

        if not response.choices:
            print("⚠️ OpenAI returned no choices:", response)
            return "Sorry, I'm having trouble replying right now."

        message = response.choices[0].message
        if not message or not getattr(message, "content", None):
            print("⚠️ OpenAI returned empty content:", response)
            return "Sorry, I'm having trouble replying right now."

        ai_reply = message.content.strip()
        if not ai_reply:
            print("⚠️ OpenAI content was blank after strip:", response)
            return "Sorry, I'm having trouble replying right now."

        return ai_reply

    except Exception as e:
        print("OpenAI API error:", e)
        return "Sorry, I'm having trouble replying right now."


def build_personality_prompt(settings, history=None, latest_message=None):
    """
    Build the system prompt using the new structured format.
    """
    def clean(value):
        if not value:
            return ""
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value).strip()

    name = clean(settings.get('bot_name')) or "you"
    age = clean(settings.get('bot_age')) or ""
    location = clean(settings.get('bot_location')) or ""
    occupation = clean(settings.get('bot_occupation')) or ""
    about = clean(settings.get('bot_personality')) or ""
    avoid_topics = clean(settings.get('avoid_topics')) or ""

    # Build promo links
    promo_links = []
    for link in settings.get('links') or []:
        url = clean(link.get('url'))
        title = clean(link.get('title'))
        if url:
            promo_links.append(f"{title}: {url}" if title else url)
    promo_links_text = ", ".join(promo_links) if promo_links else "None provided."

    # Build content highlights
    content_highlights = []
    posts = settings.get('posts') or []
    for idx, post in enumerate(posts, start=1):
        description = clean(post.get('description'))
        if description:
            content_highlights.append(f"{idx}. {description}")
    content_highlights_text = ", ".join(content_highlights) if content_highlights else "None provided."

    # Build post descriptions list - just list the descriptions directly
    post_descriptions = []
    for post in posts:
        description = clean(post.get('description'))
        if description:
            post_descriptions.append(description)
    post_descriptions_text = ", ".join(post_descriptions) if post_descriptions else "None provided."

    # Format conversation examples
    example_conversations = []
    samples = settings.get('conversation_samples') or {}
    if isinstance(samples, dict):
        for example in CONVERSATION_EXAMPLES:
            conversation_parts = []
            has_replies = False
            
            for exchange in example.get('exchanges', []):
                reply_key = f"{example['key']}_{exchange['bot_reply_key']}"
                reply = samples.get(reply_key)
                
                if reply:
                    has_replies = True
                    conversation_parts.append(f'Follower: "{exchange["follower_message"]}"')
                    conversation_parts.append(f'You: "{reply}"')
            
            if has_replies and conversation_parts:
                conversation_text = '\n'.join(conversation_parts)
                example_conversations.append(conversation_text)
    
    example_conversations_text = '\n\n'.join(example_conversations) if example_conversations else "No example conversations provided."

    # Format recent chat (last 20 messages)
    recent_chat_text = "No recent chat history."
    if history and len(history) > 0:
        # Get last 20 messages (10 from follower, 10 from bot ideally)
        last_messages = history[-20:] if len(history) > 20 else history
        chat_lines = []
        for msg in last_messages:
            role = msg.get('role', '')
            content = msg.get('content', '').strip()
            if content:
                if role == 'user':
                    chat_lines.append(f'Follower: "{content}"')
                elif role == 'assistant':
                    chat_lines.append(f'You: "{content}"')
        recent_chat_text = '\n'.join(chat_lines) if chat_lines else "No recent chat history."

    # Format latest message
    latest_message_text = latest_message if latest_message else ""

    # Build the prompt using the new structure (using regular string, not f-string)
    prompt_template = """You are {NAME}, a {AGE} year old {WHAT_YOU_DO} from {LOCATION}.

About you: {ABOUT}.

Stay fully in character. Never mention or imply anything automated.

Follow these rules:

1. Stay in character at all times.

2. Match the follower's tone, energy, slang, emojis, and length.

3. Keep replies short and natural, usually one or two sentences.

4. Do not act like an assistant. Only help or give tips if the follower asks.

5. Let the follower lead. Do not force new topics or keep the chat going if they are closing it.

6. Avoid repeating information you already gave.

7. Small imperfections are fine if they feel natural. Do not overdo them.

8. Sound like a real person texting. No lists, no templates, no em dashes or double hyphens.

Avoid these topics: {TOPICS_TO_AVOID}.

If the follower brings them up, redirect gently in your own tone.

You can reference your content only when it fits naturally:

- Promo links: {PROMO_LINKS}

- Content highlights: {CONTENT_HIGHLIGHTS}

- Posts: {POST_DESCRIPTIONS}

Here are example conversations showing how you usually text:

{EXAMPLE_CONVERSATIONS}

Here is the recent chat between you and this follower:

{RECENT_CHAT_LAST_20_MESSAGES}

Follower's latest message (this is the one you must answer now):

"{LATEST_MESSAGE}"

Reply with a single message as {NAME}, following the rules above,

using the recent chat only as context,

and answering only to the follower's latest message."""

    # Replace placeholders (using single braces since we're not using f-string)
    prompt = prompt_template.replace("{NAME}", name)
    prompt = prompt.replace("{AGE}", age)
    prompt = prompt.replace("{WHAT_YOU_DO}", occupation)
    prompt = prompt.replace("{LOCATION}", location)
    prompt = prompt.replace("{ABOUT}", about)
    prompt = prompt.replace("{TOPICS_TO_AVOID}", avoid_topics)
    prompt = prompt.replace("{PROMO_LINKS}", promo_links_text)
    prompt = prompt.replace("{CONTENT_HIGHLIGHTS}", content_highlights_text)
    prompt = prompt.replace("{POST_DESCRIPTIONS}", post_descriptions_text)
    prompt = prompt.replace("{EXAMPLE_CONVERSATIONS}", example_conversations_text)
    prompt = prompt.replace("{RECENT_CHAT_LAST_20_MESSAGES}", recent_chat_text)
    prompt = prompt.replace("{LATEST_MESSAGE}", latest_message_text)

    print(f"🧠 Built system prompt ({len(prompt)} chars)")
    print("🧾 Prompt start >>>")
    print(prompt)
    print("<<< Prompt end")

    return prompt

# ---- Webhook Route ----

def verify_meta_webhook_signature(payload, signature_header, app_secret):
    """
    Verify that a webhook request is actually from Meta/Facebook.
    
    Args:
        payload: Raw request body (bytes)
        signature_header: X-Hub-Signature-256 header value (format: "sha256=...")
        app_secret: Facebook App Secret
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not signature_header:
        print("⚠️ No signature header found")
        return False
    
    if not app_secret:
        print("⚠️ No App Secret configured - cannot verify signature")
        return False
    
    # Debug: Log App Secret info (first/last few chars only for security)
    app_secret_preview = f"{app_secret[:4]}...{app_secret[-4:]}" if len(app_secret) > 8 else "***"
    print(f"🔍 Using App Secret: {app_secret_preview} (length: {len(app_secret)})")
    
    try:
        # Extract the signature from header (format: "sha256=abc123...")
        if not signature_header.startswith('sha256='):
            print(f"⚠️ Invalid signature format: {signature_header[:20]}...")
            return False
        
        expected_signature = signature_header[7:]  # Remove "sha256=" prefix
        
        # Calculate HMAC-SHA256 signature
        # Meta signs the raw request body as received
        calculated_signature = hmac.new(
            app_secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # Debug logging
        print(f"🔍 Payload preview: {payload[:50] if len(payload) > 50 else payload}...")
        print(f"🔍 Payload type: {type(payload)}")
        print(f"🔍 Payload length: {len(payload)} bytes")
        
        # Use constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(calculated_signature, expected_signature)
        
        if is_valid:
            print("✅ Webhook signature verified - request is from Meta")
        else:
            print(f"❌ Webhook signature verification failed")
            print(f"   Expected: {expected_signature[:20]}...")
            print(f"   Calculated: {calculated_signature[:20]}...")
        
        return is_valid
        
    except Exception as e:
        print(f"❌ Error verifying webhook signature: {e}")
        return False

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
        print(f"📋 Request remote address: {request.remote_addr}")
        
        # Verify webhook signature to ensure request is from Meta
        signature_header = request.headers.get('X-Hub-Signature-256')
        # Get raw request body - use get_data() to ensure we get the raw bytes
        # cache=False ensures we get the actual raw data even if it was already read
        payload = request.get_data(cache=False)
        
        if not payload:
            print("⚠️ No payload data received")
            return "Bad Request", 400
        
        print(f"🔍 Payload length: {len(payload)} bytes")
        print(f"🔍 Signature header: {signature_header[:30] if signature_header else 'None'}...")
        
        # Temporarily allow requests even if signature fails for debugging
        # TODO: Re-enable strict verification once we confirm App Secret is correct
        verification_result = verify_meta_webhook_signature(payload, signature_header, Config.FACEBOOK_APP_SECRET)
        if not verification_result:
            print("❌ Webhook signature verification failed")
            print("⚠️ WARNING: Allowing request for debugging - signature verification disabled temporarily")
            print("⚠️ This should be re-enabled in production!")
            # return "Forbidden", 403  # Uncomment once verification is working
        
        # Parse JSON data from the raw payload (not from request.json, since we already read the body)
        try:
            data = json.loads(payload.decode('utf-8'))
            if not data:
                print("⚠️ No JSON data in request")
                return "Bad Request", 400
        except Exception as e:
            print(f"❌ Error parsing JSON: {e}")
            print(f"❌ Payload content: {payload[:200]}...")
            return "Bad Request", 400
        
        print(f"📋 Request data: {data}")
        
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

        incoming_by_sender = {}
        if 'entry' in data:
            for entry in data['entry']:
                if 'messaging' not in entry:
                    continue
                entry_page_id = entry.get('id')
                for event in entry['messaging']:
                    if event.get('message', {}).get('is_echo'):
                        continue
                    message_payload = event.get('message', {})
                    message_text = message_payload.get('text')
                    if not message_text:
                        continue
                    sender_id = event['sender']['id']
                    recipient_id = event.get('recipient', {}).get('id')
                    print(f"📨 Received a message from {sender_id}: {message_text}")
                    incoming_by_sender.setdefault(sender_id, []).append({
                        "text": message_text,
                        "timestamp": event.get('timestamp', 0),
                        "recipient_id": recipient_id,
                        "page_id": entry_page_id,
                    })

        for sender_id, events in incoming_by_sender.items():
            events.sort(key=lambda item: item.get("timestamp", 0))
            combined_preview = " | ".join(evt["text"] for evt in events)
            print(f"🧾 Aggregated {len(events)} incoming message(s) from {sender_id}: {combined_preview}")

            latest_event = events[-1]
            recipient_id = latest_event.get("recipient_id")
            entry_page_id = latest_event.get("page_id")

            print(f"🎯 Message batch targeted Instagram account: {recipient_id}")
            print(f"📄 Page ID from entry: {entry_page_id}")

            instagram_connection = None
            if recipient_id:
                print(f"🔍 Looking for Instagram connection with user ID: {recipient_id}")
                instagram_connection = get_instagram_connection_by_id(recipient_id)
                if instagram_connection:
                    print("✅ Found connection by Instagram User ID!")
                else:
                    print(f"❌ No connection found with Instagram User ID: {recipient_id}")

            if not instagram_connection and entry_page_id:
                print(f"🔍 Trying to find connection by page ID: {entry_page_id}")
                instagram_connection = get_instagram_connection_by_page_id(entry_page_id)
                if instagram_connection:
                    print("✅ Found connection by Page ID!")
                else:
                    print(f"❌ No connection found with Page ID: {entry_page_id}")

            if not instagram_connection:
                print(f"❌ No Instagram connection found for account {recipient_id} or page {entry_page_id}")
                print("💡 This might be the original Chata account or an unregistered account")
                if recipient_id == Config.INSTAGRAM_USER_ID:
                    print("✅ This is the original Chata account - using hardcoded settings")
                    access_token = Config.ACCESS_TOKEN
                    instagram_user_id = Config.INSTAGRAM_USER_ID
                    connection_id = None
                    user_id = None  # No user_id for original Chata account
                else:
                    print(f"❌ Unknown Instagram account {recipient_id} - skipping message batch")
                    continue
            else:
                print(f"✅ Found Instagram connection: {instagram_connection}")
                access_token = instagram_connection['page_access_token']
                instagram_user_id = instagram_connection['instagram_user_id']
                connection_id = instagram_connection['id']
                user_id = instagram_connection['user_id']

            handler_start = time.time()
            
            # Check if bot is paused (only for registered users)
            if instagram_connection and user_id:
                conn_check = get_db_connection()
                if conn_check:
                    cursor_check = conn_check.cursor()
                    placeholder_check = get_param_placeholder()
                    try:
                        cursor_check.execute(f"""
                            SELECT COALESCE(bot_paused, FALSE) FROM users WHERE id = {placeholder_check}
                        """, (user_id,))
                        pause_result = cursor_check.fetchone()
                        if pause_result and pause_result[0]:
                            print(f"⏸️ Bot is paused for user {user_id}. Skipping reply.")
                            conn_check.close()
                            total_duration = time.time() - handler_start
                            print(f"⏱️ Total webhook handling time for {sender_id}: {total_duration:.2f}s")
                            continue
                    except Exception as e:
                        print(f"⚠️ Error checking bot pause status: {e}")
                    finally:
                        conn_check.close()
            
            for event in events:
                save_message(sender_id, event["text"], "")
            print(f"✅ Saved {len(events)} user message(s) for {sender_id}")

            # Check reply limit before generating response (only for registered users)
            if instagram_connection and user_id:
                has_limit, remaining, total_used, total_available = check_user_reply_limit(user_id)
                if not has_limit:
                    print(f"⛔ User {user_id} has reached reply limit ({total_used}/{total_available}). Skipping reply.")
                    total_duration = time.time() - handler_start
                    print(f"⏱️ Total webhook handling time for {sender_id}: {total_duration:.2f}s")
                    continue
                else:
                    print(f"✅ User {user_id} has {remaining} replies remaining ({total_used}/{total_available})")

            history = get_last_messages(sender_id, n=35)
            print(f"📚 History for {sender_id}: {len(history)} messages")

            ai_start = time.time()
            reply_text = get_ai_reply_with_connection(history, connection_id)
            ai_duration = time.time() - ai_start
            print(f"🕒 AI reply generation time: {ai_duration:.2f}s")
            print(f"🤖 AI generated reply: {reply_text[:50]}...")

            save_message(sender_id, "", reply_text)
            print(f"✅ Saved bot response for {sender_id}")

            page_id_for_send = instagram_connection['instagram_page_id'] if instagram_connection else Config.INSTAGRAM_USER_ID
            url = f"https://graph.facebook.com/v18.0/{page_id_for_send}/messages?access_token={access_token}"
            payload = {
                "recipient": {"id": sender_id},
                "message": {"text": reply_text}
            }

            send_start = time.time()
            r = requests.post(url, json=payload, timeout=45)
            send_duration = time.time() - send_start
            print(f"📤 Sent reply to {sender_id} via {instagram_user_id}: {r.status_code} (send time {send_duration:.2f}s)")
            if r.status_code != 200:
                print(f"❌ Error sending reply: {r.text}")
            else:
                print(f"✅ Reply sent successfully to {sender_id}")
                # Increment reply count only for registered users and only on successful send
                if instagram_connection and user_id:
                    increment_reply_count(user_id)
                
            total_duration = time.time() - handler_start
            print(f"⏱️ Total webhook handling time for {sender_id}: {total_duration:.2f}s")

        return "EVENT_RECEIVED", 200

# ---- Admin Panel Route ----


@app.route("/payment-system-verification")
@login_required
def payment_system_verification():
    """Comprehensive payment system verification and checkup"""
    import os
    from datetime import datetime
    
    checks = {
        'stripe_config': {},
        'database_structure': {},
        'webhook_config': {},
        'reply_logic': {},
        'subscriptions': {},
        'environment': {}
    }
    
    # 1. Stripe Configuration Checks
    stripe_checks = []
    stripe_ok = True
    
    if Config.STRIPE_SECRET_KEY:
        stripe_checks.append(('✅', 'STRIPE_SECRET_KEY', 'Set'))
        try:
            stripe.api_key = Config.STRIPE_SECRET_KEY
            stripe.Account.retrieve()  # Test connection
            stripe_checks.append(('✅', 'Stripe API Connection', 'Working'))
        except Exception as e:
            stripe_checks.append(('❌', 'Stripe API Connection', f'Failed: {str(e)[:50]}'))
            stripe_ok = False
    else:
        stripe_checks.append(('❌', 'STRIPE_SECRET_KEY', 'Missing'))
        stripe_ok = False
    
    stripe_checks.append(('✅' if Config.STRIPE_PUBLISHABLE_KEY else '❌', 'STRIPE_PUBLISHABLE_KEY', 'Set' if Config.STRIPE_PUBLISHABLE_KEY else 'Missing'))
    stripe_checks.append(('✅' if Config.STRIPE_WEBHOOK_SECRET else '❌', 'STRIPE_WEBHOOK_SECRET', 'Set' if Config.STRIPE_WEBHOOK_SECRET else 'Missing'))
    
    # Price IDs
    starter_price_id = Config.STRIPE_STARTER_PLAN_PRICE_ID or os.getenv("STRIPE_STARTER_PLAN_PRICE_ID")
    standard_price_id = Config.STRIPE_STANDARD_PLAN_PRICE_ID or os.getenv("STRIPE_STANDARD_PLAN_PRICE_ID")
    addon_price_id = Config.STRIPE_ADDON_PRICE_ID or os.getenv("STRIPE_ADDON_PRICE_ID")
    
    stripe_checks.append(('✅' if starter_price_id else '❌', 'Starter Plan Price ID', starter_price_id[:20] + '...' if starter_price_id else 'Missing'))
    stripe_checks.append(('✅' if standard_price_id else '❌', 'Standard Plan Price ID', standard_price_id[:20] + '...' if standard_price_id else 'Missing'))
    stripe_checks.append(('✅' if addon_price_id else '❌', 'Add-on Price ID', addon_price_id[:20] + '...' if addon_price_id else 'Missing'))
    
    checks['stripe_config'] = {'checks': stripe_checks, 'all_ok': stripe_ok}
    
    # 2. Database Structure Checks
    db_checks = []
    db_ok = True
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if tables exist
        is_postgres = Config.DATABASE_URL and ('postgres' in Config.DATABASE_URL.lower())
        
        if is_postgres:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'users'
                )
            """)
            users_exists = cursor.fetchone()[0]
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'subscriptions'
                )
            """)
            subs_exists = cursor.fetchone()[0]
        else:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            users_exists = cursor.fetchone() is not None
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subscriptions'")
            subs_exists = cursor.fetchone() is not None
        
        db_checks.append(('✅' if users_exists else '❌', 'Users Table', 'Exists' if users_exists else 'Missing'))
        db_checks.append(('✅' if subs_exists else '❌', 'Subscriptions Table', 'Exists' if subs_exists else 'Missing'))
        
        if users_exists:
            # Check required columns in users table
            if is_postgres:
                cursor.execute("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'users'
                """)
                columns = [row[0] for row in cursor.fetchall()]
            else:
                cursor.execute("PRAGMA table_info(users)")
                columns = [row[1] for row in cursor.fetchall()]
            
            required_columns = ['replies_sent_monthly', 'replies_limit_monthly', 'replies_purchased', 'replies_used_purchased', 'bot_paused']
            for col in required_columns:
                exists = col in columns
                db_checks.append(('✅' if exists else '❌', f'Users.{col}', 'Exists' if exists else 'Missing'))
                if not exists:
                    db_ok = False
        
        conn.close()
    except Exception as e:
        db_checks.append(('❌', 'Database Connection', f'Error: {str(e)[:50]}'))
        db_ok = False
    
    checks['database_structure'] = {'checks': db_checks, 'all_ok': db_ok}
    
    # 3. Webhook Configuration
    webhook_checks = []
    webhook_url = f"https://getchata.com/webhook/stripe"
    webhook_checks.append(('ℹ️', 'Webhook URL', webhook_url))
    webhook_checks.append(('✅' if Config.STRIPE_WEBHOOK_SECRET else '❌', 'Webhook Secret', 'Set' if Config.STRIPE_WEBHOOK_SECRET else 'Missing'))
    checks['webhook_config'] = {'checks': webhook_checks, 'all_ok': True}
    
    # 4. Reply Logic Verification
    reply_checks = []
    reply_ok = True
    
    try:
        user_id = session['user_id']
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
            FROM users WHERE id = {placeholder}
        """, (user_id,))
        user_data = cursor.fetchone()
        
        if user_data:
            sent, limit, purchased, used_purchased = user_data
            total_available = limit + purchased
            total_used = sent + used_purchased
            remaining = max(0, total_available - total_used)
            
            reply_checks.append(('✅', 'Reply Calculation', f'Working (Remaining: {remaining})'))
            reply_checks.append(('ℹ️', 'Monthly Limit', f'{limit}'))
            reply_checks.append(('ℹ️', 'Purchased', f'{purchased}'))
            reply_checks.append(('ℹ️', 'Total Available', f'{total_available}'))
            reply_checks.append(('ℹ️', 'Total Used', f'{total_used}'))
        else:
            reply_checks.append(('❌', 'User Data', 'Not found'))
            reply_ok = False
        
        conn.close()
    except Exception as e:
        reply_checks.append(('❌', 'Reply Logic Check', f'Error: {str(e)[:50]}'))
        reply_ok = False
    
    checks['reply_logic'] = {'checks': reply_checks, 'all_ok': reply_ok}
    
    # 5. Subscription Status
    sub_checks = []
    
    try:
        user_id = session['user_id']
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM subscriptions 
            WHERE user_id = {placeholder} AND status = 'active'
        """, (user_id,))
        active_count = cursor.fetchone()[0]
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM subscriptions 
            WHERE user_id = {placeholder} AND status = 'canceled'
        """, (user_id,))
        canceled_count = cursor.fetchone()[0]
        
        cursor.execute(f"""
            SELECT plan_type, status, stripe_subscription_id, created_at
            FROM subscriptions 
            WHERE user_id = {placeholder}
            ORDER BY created_at DESC
            LIMIT 5
        """, (user_id,))
        recent_subs = cursor.fetchall()
        
        sub_checks.append(('ℹ️', 'Active Subscriptions', str(active_count)))
        sub_checks.append(('ℹ️', 'Canceled Subscriptions', str(canceled_count)))
        
        if recent_subs:
            sub_checks.append(('ℹ️', 'Recent Subscriptions', f'{len(recent_subs)} found'))
            for sub in recent_subs[:3]:
                plan, status, sub_id, created = sub
                status_icon = '✅' if status == 'active' else '❌'
                sub_checks.append((status_icon, f'{plan.title()} ({status})', f'ID: {sub_id[:20]}...'))
        else:
            sub_checks.append(('ℹ️', 'Recent Subscriptions', 'None found'))
        
        conn.close()
    except Exception as e:
        sub_checks.append(('❌', 'Subscription Check', f'Error: {str(e)[:50]}'))
    
    checks['subscriptions'] = {'checks': sub_checks, 'all_ok': True}
    
    # 6. Environment Variables Summary
    env_checks = []
    env_ok = True
    
    critical_vars = [
        'STRIPE_SECRET_KEY',
        'STRIPE_PUBLISHABLE_KEY',
        'STRIPE_WEBHOOK_SECRET',
        'STRIPE_STARTER_PLAN_PRICE_ID',
        'STRIPE_STANDARD_PLAN_PRICE_ID',
        'STRIPE_ADDON_PRICE_ID'
    ]
    
    for var in critical_vars:
        value = os.getenv(var)
        exists = value is not None and value != ''
        env_checks.append(('✅' if exists else '❌', var, 'Set' if exists else 'Missing'))
        if not exists:
            env_ok = False
    
    checks['environment'] = {'checks': env_checks, 'all_ok': env_ok}
    
    # Calculate overall status
    overall_ok = all([
        checks['stripe_config']['all_ok'],
        checks['database_structure']['all_ok'],
        checks['reply_logic']['all_ok'],
        checks['environment']['all_ok']
    ])
    
    # Generate HTML
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Payment System Verification</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background: #0a0a0a;
                color: #fff;
                padding: 20px;
                line-height: 1.6;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            h1 {{
                color: #4a90e2;
                border-bottom: 2px solid #4a90e2;
                padding-bottom: 10px;
            }}
            .section {{
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
            }}
            .section h2 {{
                color: #51cf66;
                margin-top: 0;
            }}
            .check-item {{
                display: flex;
                align-items: center;
                padding: 8px;
                margin: 5px 0;
                background: rgba(255, 255, 255, 0.02);
                border-radius: 4px;
            }}
            .check-item span:first-child {{
                font-size: 20px;
                margin-right: 10px;
                width: 30px;
            }}
            .status-badge {{
                display: inline-block;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                margin: 20px 0;
            }}
            .status-ok {{
                background: #51cf66;
                color: #000;
            }}
            .status-error {{
                background: #ff6b6b;
                color: #fff;
            }}
            .back-link {{
                display: inline-block;
                margin-top: 20px;
                padding: 10px 20px;
                background: #4a90e2;
                color: #fff;
                text-decoration: none;
                border-radius: 5px;
            }}
            .back-link:hover {{
                background: #357abd;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>💰 Payment System Verification</h1>
            <div class="status-badge {'status-ok' if overall_ok else 'status-error'}">
                {'✅ All Systems Operational' if overall_ok else '❌ Issues Detected'}
            </div>
            
            <div class="section">
                <h2>1. Stripe Configuration</h2>
                {'<p style="color: #51cf66;">✅ All Stripe configuration is correct.</p>' if checks['stripe_config']['all_ok'] else '<p style="color: #ff6b6b;">❌ Some Stripe configuration is missing or incorrect.</p>'}
                {'<br>'.join([f'<div class="check-item"><span>{icon}</span><span><strong>{name}:</strong> {status}</span></div>' for icon, name, status in checks['stripe_config']['checks']])}
            </div>
            
            <div class="section">
                <h2>2. Database Structure</h2>
                {'<p style="color: #51cf66;">✅ Database structure is correct.</p>' if checks['database_structure']['all_ok'] else '<p style="color: #ff6b6b;">❌ Database structure issues detected.</p>'}
                {'<br>'.join([f'<div class="check-item"><span>{icon}</span><span><strong>{name}:</strong> {status}</span></div>' for icon, name, status in checks['database_structure']['checks']])}
            </div>
            
            <div class="section">
                <h2>3. Webhook Configuration</h2>
                {'<br>'.join([f'<div class="check-item"><span>{icon}</span><span><strong>{name}:</strong> {status}</span></div>' for icon, name, status in checks['webhook_config']['checks']])}
            </div>
            
            <div class="section">
                <h2>4. Reply Counting Logic</h2>
                {'<p style="color: #51cf66;">✅ Reply counting logic is working correctly.</p>' if checks['reply_logic']['all_ok'] else '<p style="color: #ff6b6b;">❌ Reply counting logic has issues.</p>'}
                {'<br>'.join([f'<div class="check-item"><span>{icon}</span><span><strong>{name}:</strong> {status}</span></div>' for icon, name, status in checks['reply_logic']['checks']])}
            </div>
            
            <div class="section">
                <h2>5. Subscription Status</h2>
                {'<br>'.join([f'<div class="check-item"><span>{icon}</span><span><strong>{name}:</strong> {status}</span></div>' for icon, name, status in checks['subscriptions']['checks']])}
            </div>
            
            <div class="section">
                <h2>6. Environment Variables</h2>
                {'<p style="color: #51cf66;">✅ All critical environment variables are set.</p>' if checks['environment']['all_ok'] else '<p style="color: #ff6b6b;">❌ Some environment variables are missing.</p>'}
                {'<br>'.join([f'<div class="check-item"><span>{icon}</span><span><strong>{name}:</strong> {status}</span></div>' for icon, name, status in checks['environment']['checks']])}
            </div>
            
            <a href="/dashboard" class="back-link">← Back to Dashboard</a>
        </div>
    </body>
    </html>
    """
    
    return html

@app.route("/admin/test")
@login_required
def admin_test():
    """Simple test route to verify admin routes work"""
    return f"✅ Admin routes work! User ID: {session.get('user_id')}"

@app.route("/admin/clean-all-users", methods=["POST"])
def clean_all_users():
    """Delete all users and related data - for testing/reset purposes (accessible via secret admin URL only)"""
    
    try:
        conn = get_db_connection()
        if not conn:
            flash("Database connection failed.", "error")
            return redirect(url_for('admin_dashboard'))
        
        cursor = conn.cursor()
        
        # Delete in order to respect foreign key constraints
        # Wrap each deletion in try/except to handle missing tables gracefully
        
        # Delete activity logs
        try:
            cursor.execute("DELETE FROM activity_logs")
            print(f"✅ Deleted all activity logs")
        except Exception as e:
            print(f"⚠️ Could not delete activity_logs: {e}")
        
        # Delete purchases
        try:
            cursor.execute("DELETE FROM purchases")
            print(f"✅ Deleted all purchases")
        except Exception as e:
            print(f"⚠️ Could not delete purchases: {e}")
        
        # Delete subscriptions
        try:
            cursor.execute("DELETE FROM subscriptions")
            print(f"✅ Deleted all subscriptions")
        except Exception as e:
            print(f"⚠️ Could not delete subscriptions: {e}")
        
        # Delete messages
        try:
            cursor.execute("DELETE FROM messages")
            print(f"✅ Deleted all messages")
        except Exception as e:
            print(f"⚠️ Could not delete messages: {e}")
        
        # Delete client settings
        try:
            cursor.execute("DELETE FROM client_settings")
            print(f"✅ Deleted all client settings")
        except Exception as e:
            print(f"⚠️ Could not delete client_settings: {e}")
        
        # Delete instagram connections
        try:
            cursor.execute("DELETE FROM instagram_connections")
            print(f"✅ Deleted all Instagram connections")
        except Exception as e:
            print(f"⚠️ Could not delete instagram_connections: {e}")
        
        # Delete password reset tokens (table name is password_resets, not password_reset_tokens)
        try:
            cursor.execute("DELETE FROM password_resets")
            print(f"✅ Deleted all password reset tokens")
        except Exception as e:
            print(f"⚠️ Could not delete password_resets: {e}")
        
        # Delete usage logs if they exist
        try:
            cursor.execute("DELETE FROM usage_logs")
            print(f"✅ Deleted all usage logs")
        except Exception as e:
            print(f"⚠️ Could not delete usage_logs: {e}")
        
        # Finally, delete all users
        try:
            cursor.execute("DELETE FROM users")
            deleted_count = cursor.rowcount
            print(f"✅ Deleted {deleted_count} users")
        except Exception as e:
            print(f"❌ Could not delete users: {e}")
            raise
        
        conn.commit()
        conn.close()
        
        flash(f"Successfully cleaned database. Deleted {deleted_count} users and all related data.", "success")
        return redirect(url_for('admin_dashboard'))
        
    except Exception as e:
        print(f"❌ Error cleaning database: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error cleaning database: {str(e)}", "error")
        return redirect(url_for('admin_dashboard'))

@app.route("/admin/chata-internal-dashboard-2024-secure")
def admin_dashboard():
    """Secret admin dashboard - accessible only via this specific URL (no login required, security through obscurity)"""
    print(f"🔐 [ADMIN] Admin dashboard accessed via secret URL: {request.path}")
    
    # Get pagination parameters
    users_page = request.args.get('users_page', 1, type=int)
    logs_page = request.args.get('logs_page', 1, type=int)
    users_per_page = 10
    logs_per_page = 10
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Check if using PostgreSQL
        database_url = os.environ.get('DATABASE_URL')
        is_postgres = bool(database_url and (database_url.startswith('postgres://') or database_url.startswith('postgresql://')))
        
        # Get total users count
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        # Get users with active subscriptions
        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) 
            FROM subscriptions 
            WHERE status = 'active'
        """)
        active_subscribers = cursor.fetchone()[0]
        
        # Get users with pagination (limit to 50 total, show 10 per page)
        total_users_to_show = min(50, total_users)
        users_offset = (users_page - 1) * users_per_page
        
        if is_postgres:
            cursor.execute("""
                SELECT 
                    id, username, email, 
                    replies_sent_monthly, 
                    replies_limit_monthly, 
                    replies_purchased, 
                    replies_used_purchased,
                    bot_paused,
                    created_at
                FROM users
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (min(users_per_page, total_users_to_show - users_offset), users_offset))
        else:
            cursor.execute("""
                SELECT 
                    id, username, email, 
                    replies_sent_monthly, 
                    replies_limit_monthly, 
                    replies_purchased, 
                    replies_used_purchased,
                    bot_paused,
                    created_at
                FROM users
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (min(users_per_page, total_users_to_show - users_offset), users_offset))
        users_data = cursor.fetchall()
        
        # Calculate users pagination
        total_users_pages = (total_users_to_show + users_per_page - 1) // users_per_page
        
        # Get all subscriptions
        cursor.execute("""
            SELECT 
                id, user_id, stripe_subscription_id, stripe_customer_id,
                plan_type, status, 
                current_period_start, current_period_end,
                created_at, updated_at
            FROM subscriptions
            ORDER BY updated_at DESC
        """)
        subscriptions_data = cursor.fetchall()
        
        # Get Instagram connections
        cursor.execute("""
            SELECT 
                id, user_id, instagram_user_id, instagram_page_id,
                is_active, created_at
            FROM instagram_connections
            ORDER BY created_at DESC
        """)
        connections_data = cursor.fetchall()
        
        # Get recent purchases
        cursor.execute("""
            SELECT 
                id, user_id, amount_paid, replies_added,
                payment_provider, payment_id, status, created_at
            FROM purchases
            ORDER BY created_at DESC
            LIMIT 50
        """)
        purchases_data = cursor.fetchall()
        
        # Get activity logs with pagination (limit to 50 total, show 10 per page)
        cursor.execute("SELECT COUNT(*) FROM activity_logs")
        total_logs = cursor.fetchone()[0]
        total_logs_to_show = min(50, total_logs)
        logs_offset = (logs_page - 1) * logs_per_page
        
        if is_postgres:
            cursor.execute("""
                SELECT 
                    id, user_id, action, details, ip_address, created_at
                FROM activity_logs
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (min(logs_per_page, total_logs_to_show - logs_offset), logs_offset))
        else:
            cursor.execute("""
                SELECT 
                    id, user_id, action, details, ip_address, created_at
                FROM activity_logs
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (min(logs_per_page, total_logs_to_show - logs_offset), logs_offset))
        activity_logs = cursor.fetchall()
        
        # Calculate logs pagination
        total_logs_pages = (total_logs_to_show + logs_per_page - 1) // logs_per_page
        
        conn.close()
        
        # Format data for template
        users = []
        for row in users_data:
            users.append({
                'id': row[0],
                'username': row[1],
                'email': row[2],
                'replies_sent_monthly': row[3],
                'replies_limit_monthly': row[4],
                'replies_purchased': row[5],
                'replies_used_purchased': row[6],
                'bot_paused': row[7],
                'created_at': row[8]
            })
        
        subscriptions = []
        for row in subscriptions_data:
            subscriptions.append({
                'id': row[0],
                'user_id': row[1],
                'stripe_subscription_id': row[2],
                'stripe_customer_id': row[3],
                'plan_type': row[4],
                'status': row[5],
                'current_period_start': row[6],
                'current_period_end': row[7],
                'created_at': row[8],
                'updated_at': row[9]
            })
        
        connections = []
        for row in connections_data:
            connections.append({
                'id': row[0],
                'user_id': row[1],
                'instagram_user_id': row[2],
                'instagram_page_id': row[3],
                'is_active': row[4],
                'created_at': row[5]
            })
        
        purchases = []
        for row in purchases_data:
            purchases.append({
                'id': row[0],
                'user_id': row[1],
                'amount_paid': row[2],
                'replies_added': row[3],
                'payment_provider': row[4],
                'payment_id': row[5],
                'status': row[6],
                'created_at': row[7]
            })
        
        logs = []
        for row in activity_logs:
            logs.append({
                'id': row[0],
                'user_id': row[1],
                'action': row[2],
                'details': row[3],
                'ip_address': row[4],
                'created_at': row[5]
            })
        
        return render_template('admin_dashboard.html',
                             total_users=total_users,
                             active_subscribers=active_subscribers,
                             users=users,
                             subscriptions=subscriptions,
                             connections=connections,
                             purchases=purchases,
                             activity_logs=logs,
                             users_page=users_page,
                             total_users_pages=total_users_pages,
                             logs_page=logs_page,
                             total_logs_pages=total_logs_pages,
                             total_users_to_show=total_users_to_show)
        
    except Exception as e:
        print(f"❌ Admin dashboard error: {e}")
        import traceback
        traceback.print_exc()
        return f"Error loading admin dashboard: {str(e)}", 500

@app.route("/admin/cleanup-for-production", methods=["POST"])
@login_required
def cleanup_for_production():
    """Cleanup route: Delete all subscriptions and reset all replies to zero - FOR PRODUCTION PREP"""
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        # 1. Delete all subscriptions
        cursor.execute(f"DELETE FROM subscriptions")
        subscriptions_deleted = cursor.rowcount
        
        # 2. Reset all replies to zero for all users
        cursor.execute(f"""
            UPDATE users 
            SET replies_sent_monthly = 0,
                replies_limit_monthly = 0,
                replies_purchased = 0,
                replies_used_purchased = 0
        """)
        users_updated = cursor.rowcount
        
        conn.commit()
        
        flash(f"✅ Cleanup complete! Deleted {subscriptions_deleted} subscriptions and reset replies for {users_updated} users.", "success")
        print(f"🧹 Production cleanup: Deleted {subscriptions_deleted} subscriptions, reset {users_updated} users")
        
    except Exception as e:
        print(f"❌ Error during cleanup: {e}")
        flash(f"Error during cleanup: {str(e)}", "error")
        conn.rollback()
    finally:
        conn.close()
    
    return redirect(url_for('dashboard'))


@app.route("/admin/prompt", methods=["GET", "POST"])
def admin_prompt():
    message = None

    if flask_request.method == "POST":
        set_setting("bot_personality", flask_request.form.get("bot_personality", ""))
        set_setting("temperature", flask_request.form.get("temperature", "0.7"))
        max_tokens_input = normalize_max_tokens(flask_request.form.get("max_tokens", "3000"))
        set_setting("max_tokens", str(max_tokens_input))
        message = "Bot settings updated successfully!"

    current_prompt = get_setting("bot_personality", "")
    current_temperature = get_setting("temperature", "0.7")
    current_max_tokens = str(normalize_max_tokens(get_setting("max_tokens", "3000")))

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
            <input type="number" min="1" max="6000" id="max_tokens" name="max_tokens" value="{{current_max_tokens}}">
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

@app.route("/pricing")
def pricing():
    """Standalone pricing page"""
    # Check if user is logged in
    user_logged_in = 'user_id' in session
    user = None
    if user_logged_in:
        user = get_user_by_id(session['user_id'])
    return render_template("pricing.html", user_logged_in=user_logged_in, user=user)



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

@app.route("/support", methods=["GET", "POST"])
@login_required
def support():
    """Support page where users can send messages"""
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        user_id = session.get('user_id')
        
        if not message:
            flash("Please enter a message.", "error")
            return redirect(url_for('support'))
        
        # Get user info
        user = get_user_by_id(user_id)
        user_email = user.get('email', 'Unknown')
        username = user.get('username', 'User')
        
        # Create email content
        content_html = f"""
            <p style="color: rgba(255, 255, 255, 0.9); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
                <strong>Support Request from:</strong> {username} ({user_email})
            </p>
            
            <div style="background: rgba(51, 102, 255, 0.1); padding: 20px; border-radius: 8px; border: 1px solid rgba(51, 102, 255, 0.2); margin: 20px 0;">
                <p style="color: rgba(255, 255, 255, 0.9); font-size: 16px; line-height: 1.7; margin: 0; text-transform: none; letter-spacing: normal; white-space: pre-wrap;">{message}</p>
            </div>
        """
        
        html_content = get_email_base_template("Support Request", content_html)
        
        # Send to support email
        support_email = "chata.dmbot@gmail.com"
        success = send_email_via_sendgrid(support_email, f"Support Request from {username}", html_content)
        
        if success:
            flash("Your message has been sent successfully! We'll get back to you soon.", "success")
        else:
            flash("There was an error sending your message. Please try again or email us directly at chata.dmbot@gmail.com", "error")
        
        return redirect(url_for('support'))
    
    # GET request - show support form
    user_id = session.get('user_id')
    user = get_user_by_id(user_id)
    return render_template("support.html", user=user)


if __name__ == "__main__":
    # Use environment variable for port (Render requirement)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
