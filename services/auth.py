"""Authentication helpers — decorators and password reset tokens.

Password reset tokens are stored as a SHA-256 hash of the random token, so a
database leak never exposes a usable reset link. The plaintext token is only
ever sent to the user's email and never persisted.
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import session, flash, redirect, url_for
from config import Config
from database import get_db_connection, get_param_placeholder


def _hash_token(token: str) -> str:
    """SHA-256 hex digest of a reset token. 64 chars, fits VARCHAR(255)/TEXT."""
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_reset_token(user_id):
    """Create a password reset token. Returns the plaintext token to email to
    the user; the database stores only its SHA-256 hash."""
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires = datetime.utcnow() + timedelta(hours=1)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"""
            INSERT INTO password_resets (user_id, token, expires_at)
            VALUES ({placeholder}, {placeholder}, {placeholder})
        """, (user_id, token_hash, expires))
        conn.commit()
    finally:
        conn.close()
    
    return token

def verify_reset_token(token):
    """Verify a password reset token by hashing the supplied plaintext token
    and comparing to the stored hash."""
    if not token:
        return None
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"""
            SELECT user_id FROM password_resets 
            WHERE token = {placeholder} AND expires_at > {placeholder} AND used_at IS NULL
        """, (_hash_token(token), datetime.utcnow()))
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        conn.close()

def mark_reset_token_used(token):
    """Mark a reset token as used (matches by hash, not plaintext)."""
    if not token:
        return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(
            f"UPDATE password_resets SET used_at = CURRENT_TIMESTAMP WHERE token = {placeholder}",
            (_hash_token(token),),
        )
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
