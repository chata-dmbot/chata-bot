"""Activity and client settings service."""
import json
from flask import request
from database import get_db_connection, get_param_placeholder, is_postgres
from config import Config


def get_client_settings(user_id, connection_id=None, conn=None):
    """
    Get bot settings for a specific client/connection.
    
    Args:
        user_id: User ID
        connection_id: Optional connection ID
        conn: Optional database connection to reuse. If None, opens and closes its own connection.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        if connection_id:
            cursor.execute(f"""
                SELECT bot_personality, bot_name, bot_age, bot_gender, bot_location, bot_occupation, bot_education,
                       use_active_hours, active_start, active_end, links, posts, conversation_samples, faqs, instagram_url, avoid_topics,
                       blocked_users, is_active
                FROM client_settings 
                WHERE user_id = {placeholder} AND instagram_connection_id = {placeholder}
            """, (user_id, connection_id))
        else:
            cursor.execute(f"""
                SELECT bot_personality, bot_name, bot_age, bot_gender, bot_location, bot_occupation, bot_education,
                       use_active_hours, active_start, active_end, links, posts, conversation_samples, faqs, instagram_url, avoid_topics,
                       blocked_users, is_active
                FROM client_settings 
                WHERE user_id = {placeholder} AND instagram_connection_id IS NULL
            """, (user_id,))
        
        row = cursor.fetchone()
    except Exception:
        if should_close:
            try:
                conn.close()
            except Exception:
                pass
        raise
    
    if should_close:
        conn.close()
    
    if row:
        return {
            'bot_personality': row[0] or '',
            'bot_name': row[1] or '',
            'bot_age': row[2] or '',
            'bot_gender': row[3] or '',
            'bot_location': row[4] or '',
            'bot_occupation': row[5] or '',
            'bot_education': row[6] or '',
            'use_active_hours': bool(row[7]) if row[7] is not None else False,
            'active_start': row[8] or '09:00',
            'active_end': row[9] or '18:00',
            'links': json.loads(row[10]) if row[10] else [],
            'posts': json.loads(row[11]) if row[11] else [],
            'conversation_samples': json.loads(row[12]) if row[12] else {},
            'faqs': json.loads(row[13]) if row[13] else [],
            'instagram_url': row[14] or '',
            'avoid_topics': row[15] or '',
            'blocked_users': json.loads(row[16]) if row[16] else [],
            'auto_reply': bool(row[17]) if row[17] is not None else True
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
        'use_active_hours': False,
        'active_start': '09:00',
        'active_end': '18:00',
        'links': [],
        'posts': [],
        'conversation_samples': {},
        'faqs': [],
        'instagram_url': '',
        'avoid_topics': '',
        'blocked_users': [],
        'auto_reply': True
    }


def log_activity(user_id, action_type, description=None, conn=None):
    """
    Log user activity for analytics and security.
    
    Args:
        user_id: User ID
        action_type: Type of action
        description: Optional description
        conn: Optional database connection to reuse. If None, opens and closes its own connection.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Get IP address safely — may not be available in webhook context
        try:
            ip_addr = request.remote_addr
        except RuntimeError:
            ip_addr = None
        
        cursor.execute(f"""
            INSERT INTO activity_logs (user_id, action, details, ip_address)
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})
        """, (user_id, action_type, description, ip_addr))
        
        conn.commit()
    except Exception:
        if should_close:
            try:
                conn.close()
            except Exception:
                pass
        raise
    
    if should_close:
        conn.close()


def save_client_settings(user_id, settings, connection_id=None, conn=None):
    """
    Save bot settings for a specific client/connection.
    
    Args:
        user_id: User ID
        settings: Settings dictionary
        connection_id: Connection ID (required)
        conn: Optional database connection to reuse. If None, opens and closes its own connection.
    """
    if connection_id is None:
        raise ValueError("connection_id must be provided when saving client settings.")

    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
    
        # Prepare the data
        links_json = json.dumps(settings.get('links', []))
        posts_json = json.dumps(settings.get('posts', []))
        samples_json = json.dumps(settings.get('conversation_samples', {}))
        faqs_json = json.dumps(settings.get('faqs', []))
        blocked_users_json = json.dumps(settings.get('blocked_users', []))
    
        # Use different syntax for PostgreSQL vs SQLite
        is_pg = is_postgres()
        
        params = (user_id, connection_id,
                  settings.get('bot_personality', ''), settings.get('bot_name', ''), settings.get('bot_age', ''),
                  settings.get('bot_gender', ''), settings.get('bot_location', ''), settings.get('bot_occupation', ''),
                  settings.get('bot_education', ''), settings.get('use_active_hours', False),
                  settings.get('active_start', '09:00'), settings.get('active_end', '18:00'),
                  links_json, posts_json, samples_json, faqs_json, settings.get('instagram_url', ''), settings.get('avoid_topics', ''),
                  blocked_users_json,
                  settings.get('auto_reply', True))

        cols = """(user_id, instagram_connection_id, bot_personality, bot_name, bot_age, bot_gender, bot_location,
             bot_occupation, bot_education, use_active_hours, active_start, active_end, links, posts, conversation_samples, faqs,
             instagram_url, avoid_topics, blocked_users, is_active)"""

        vals = f"""VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder},
                    {placeholder}, {placeholder})"""

        if is_pg:
            cursor.execute(f"""
                INSERT INTO client_settings {cols}
                {vals}
                ON CONFLICT (user_id, instagram_connection_id) DO UPDATE SET
                bot_personality = EXCLUDED.bot_personality, bot_name = EXCLUDED.bot_name,
                bot_age = EXCLUDED.bot_age, bot_gender = EXCLUDED.bot_gender,
                bot_location = EXCLUDED.bot_location, bot_occupation = EXCLUDED.bot_occupation,
                bot_education = EXCLUDED.bot_education, use_active_hours = EXCLUDED.use_active_hours,
                active_start = EXCLUDED.active_start, active_end = EXCLUDED.active_end,
                links = EXCLUDED.links, posts = EXCLUDED.posts,
                conversation_samples = EXCLUDED.conversation_samples, faqs = EXCLUDED.faqs,
                instagram_url = EXCLUDED.instagram_url, avoid_topics = EXCLUDED.avoid_topics,
                blocked_users = EXCLUDED.blocked_users, is_active = EXCLUDED.is_active,
                updated_at = CURRENT_TIMESTAMP
            """, params)
        else:
            cursor.execute(f"""
                INSERT OR REPLACE INTO client_settings {cols}
                {vals}
            """, params)
    
        conn.commit()
    except Exception:
        if should_close:
            try:
                conn.close()
            except Exception:
                pass
        raise
    
    if should_close:
        conn.close()
