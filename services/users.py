"""User service — CRUD operations for user accounts."""
import logging
import os
import sqlite3
from werkzeug.security import generate_password_hash
from database import get_db_connection, get_param_placeholder
from config import Config

try:
    import psycopg2
    _PG_INTEGRITY = (psycopg2.IntegrityError,)
except ImportError:
    _PG_INTEGRITY = ()
_INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + _PG_INTEGRITY

logger = logging.getLogger("chata.services.users")


def get_user_by_id(user_id):
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return None
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"SELECT id, username, email, created_at FROM users WHERE id = {placeholder}", (user_id,))
        user = cursor.fetchone()
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'created_at': user[3]
            }
        return None
    except Exception as e:
        logger.error(f"Error getting user by ID: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def get_user_by_email(email):
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return None
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"SELECT id, username, email, password_hash, created_at FROM users WHERE email = {placeholder}", (email,))
        user = cursor.fetchone()
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
        logger.error(f"Error getting user by email: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def get_user_by_username_or_email(username_or_email):
    """Get user by username or email - for login"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return None
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Try username first, then email
        cursor.execute(f"SELECT id, username, email, password_hash, created_at FROM users WHERE username = {placeholder} OR email = {placeholder}", (username_or_email, username_or_email))
        user = cursor.fetchone()
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
        logger.error(f"Error getting user by username or email: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def get_user_by_username(username):
    """Get user by username only. Uses case-insensitive match so CHATADEMO and chatademo are treated as the same."""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return None
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(
            f"SELECT id, username, email, password_hash, created_at FROM users WHERE LOWER(username) = LOWER({placeholder})",
            (username,)
        )
        user = cursor.fetchone()
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
        logger.error(f"Error getting user by username: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def create_user(username, email, password):
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Database connection failed")
        cursor = conn.cursor()
        password_hash = generate_password_hash(password)
        placeholder = get_param_placeholder()
        
        # Re-check username uniqueness (case-insensitive) right before INSERT to avoid race with concurrent signups
        cursor.execute(f"SELECT id FROM users WHERE LOWER(username) = LOWER({placeholder})", (username,))
        if cursor.fetchone():
            raise ValueError("username_taken")
        
        # For PostgreSQL, we need to get the ID differently
        # Explicitly set replies_limit_monthly to 0 to ensure new users start with 0 replies
        database_url = os.environ.get('DATABASE_URL')
        if database_url and (database_url.startswith("postgres://") or database_url.startswith("postgresql://")):
            sql = f"INSERT INTO users (username, email, password_hash, replies_limit_monthly) VALUES ({placeholder}, {placeholder}, {placeholder}, 0) RETURNING id"
            params = (username, email, password_hash)
            cursor.execute(sql, params)
            user_id = cursor.fetchone()[0]
        else:
            sql = f"INSERT INTO users (username, email, password_hash, replies_limit_monthly) VALUES ({placeholder}, {placeholder}, {placeholder}, 0)"
            params = (username, email, password_hash)
            cursor.execute(sql, params)
            user_id = cursor.lastrowid
            
        conn.commit()
        return user_id
    except _INTEGRITY_ERRORS:
        # Concurrent signup race: another request inserted same username/email first
        raise ValueError("username_taken")
    except Exception:
        raise
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
