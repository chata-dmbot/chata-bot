"""Global key-value settings (settings table). Used by AI and others without depending on app."""
from database import get_db_connection, get_param_placeholder


def get_setting(key, default=None):
    """Get a value from the settings table by key."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"SELECT value FROM settings WHERE key = {placeholder}", (key,))
        row = cursor.fetchone()
        return row[0] if row else default
    finally:
        conn.close()


def set_setting(key, value):
    """Update a value in the settings table."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"UPDATE settings SET value = {placeholder} WHERE key = {placeholder}", (value, key))
        conn.commit()
    finally:
        conn.close()
