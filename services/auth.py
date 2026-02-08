"""Authentication helpers — decorators and password reset tokens."""
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import session, flash, redirect, url_for
from config import Config
from database import get_db_connection, get_param_placeholder


def create_reset_token(user_id):
    """Create a password reset token"""
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=1)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"""
            INSERT INTO password_resets (user_id, token, expires_at)
            VALUES ({placeholder}, {placeholder}, {placeholder})
        """, (user_id, token, expires))
        conn.commit()
    finally:
        conn.close()
    
    return token

def verify_reset_token(token):
    """Verify a password reset token"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"""
            SELECT user_id FROM password_resets 
            WHERE token = {placeholder} AND expires_at > {placeholder} AND used_at IS NULL
        """, (token, datetime.now()))
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        conn.close()

def mark_reset_token_used(token):
    """Mark a reset token as used"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"UPDATE password_resets SET used_at = CURRENT_TIMESTAMP WHERE token = {placeholder}", (token,))
        conn.commit()
    finally:
        conn.close()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Require login + user ID in ADMIN_USER_IDS list."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('auth.login'))
        if session['user_id'] not in Config.ADMIN_USER_IDS:
            flash('Access denied.', 'error')
            return redirect(url_for('dashboard_bp.dashboard'))
        return f(*args, **kwargs)
    return decorated_function
