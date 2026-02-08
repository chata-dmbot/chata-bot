"""Activity and client settings service."""
import json
from flask import request
from database import get_db_connection, get_param_placeholder
from config import Config


def normalize_max_tokens(value, floor=3000):
    """Ensure max_tokens is at least the configured floor."""
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return floor
    return max(numeric, floor)


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
                       personality_type, bot_values, tone_of_voice, habits_quirks, confidence_level, emotional_range,
                       main_goal, fears_insecurities, what_drives_them, obstacles, backstory, family_relationships,
                       culture_environment, hobbies_interests, reply_style, emoji_slang, conflict_handling, preferred_topics,
                       use_active_hours, active_start, active_end, links, posts, conversation_samples, faqs, instagram_url, avoid_topics,
                       blocked_users, temperature, max_tokens, is_active
                FROM client_settings 
                WHERE user_id = {placeholder} AND instagram_connection_id = {placeholder}
            """, (user_id, connection_id))
        else:
            cursor.execute(f"""
                SELECT bot_personality, bot_name, bot_age, bot_gender, bot_location, bot_occupation, bot_education,
                       personality_type, bot_values, tone_of_voice, habits_quirks, confidence_level, emotional_range,
                       main_goal, fears_insecurities, what_drives_them, obstacles, backstory, family_relationships,
                       culture_environment, hobbies_interests, reply_style, emoji_slang, conflict_handling, preferred_topics,
                       use_active_hours, active_start, active_end, links, posts, conversation_samples, faqs, instagram_url, avoid_topics,
                       blocked_users, temperature, max_tokens, is_active
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
            'faqs': json.loads(row[31]) if row[31] else [],
            'instagram_url': row[32] or '',
            'avoid_topics': row[33] or '',
            'blocked_users': json.loads(row[34]) if row[34] else [],
            'temperature': row[35] or 0.7,
            'max_tokens': normalize_max_tokens(row[36]),
            'auto_reply': bool(row[37]) if row[37] is not None else True
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
        'faqs': [],
        'instagram_url': '',
        'avoid_topics': '',
        'blocked_users': [],
        'temperature': 0.7,
        'max_tokens': 3000,
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
        max_tokens_value = normalize_max_tokens(settings.get('max_tokens', 3000))
    
        # Use different syntax for PostgreSQL vs SQLite
        is_pg = Config.DATABASE_URL and (Config.DATABASE_URL.startswith("postgres://") or Config.DATABASE_URL.startswith("postgresql://"))
        
        params = (user_id, connection_id, 
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
                  links_json, posts_json, samples_json, faqs_json, settings.get('instagram_url', ''), settings.get('avoid_topics', ''),
                  blocked_users_json, 0.7, max_tokens_value,
                  settings.get('auto_reply', True))
        
        cols = """(user_id, instagram_connection_id, bot_personality, bot_name, bot_age, bot_gender, bot_location, 
             bot_occupation, bot_education, personality_type, bot_values, tone_of_voice, habits_quirks, 
             confidence_level, emotional_range, main_goal, fears_insecurities, what_drives_them, obstacles,
             backstory, family_relationships, culture_environment, hobbies_interests, reply_style, emoji_slang,
             conflict_handling, preferred_topics, use_active_hours, active_start, active_end, links, posts, conversation_samples, faqs,
             instagram_url, avoid_topics, blocked_users, temperature, max_tokens, is_active)"""
        
        vals = f"""VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                    {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})"""
        
        if is_pg:
            cursor.execute(f"""
                INSERT INTO client_settings {cols}
                {vals}
                ON CONFLICT (user_id, instagram_connection_id) DO UPDATE SET
                bot_personality = EXCLUDED.bot_personality, bot_name = EXCLUDED.bot_name,
                bot_age = EXCLUDED.bot_age, bot_gender = EXCLUDED.bot_gender,
                bot_location = EXCLUDED.bot_location, bot_occupation = EXCLUDED.bot_occupation,
                bot_education = EXCLUDED.bot_education, personality_type = EXCLUDED.personality_type,
                bot_values = EXCLUDED.bot_values, tone_of_voice = EXCLUDED.tone_of_voice,
                habits_quirks = EXCLUDED.habits_quirks, confidence_level = EXCLUDED.confidence_level,
                emotional_range = EXCLUDED.emotional_range, main_goal = EXCLUDED.main_goal,
                fears_insecurities = EXCLUDED.fears_insecurities, what_drives_them = EXCLUDED.what_drives_them,
                obstacles = EXCLUDED.obstacles, backstory = EXCLUDED.backstory,
                family_relationships = EXCLUDED.family_relationships, culture_environment = EXCLUDED.culture_environment,
                hobbies_interests = EXCLUDED.hobbies_interests, reply_style = EXCLUDED.reply_style,
                emoji_slang = EXCLUDED.emoji_slang, conflict_handling = EXCLUDED.conflict_handling,
                preferred_topics = EXCLUDED.preferred_topics, use_active_hours = EXCLUDED.use_active_hours,
                active_start = EXCLUDED.active_start, active_end = EXCLUDED.active_end,
                links = EXCLUDED.links, posts = EXCLUDED.posts,
                conversation_samples = EXCLUDED.conversation_samples, faqs = EXCLUDED.faqs,
                instagram_url = EXCLUDED.instagram_url, avoid_topics = EXCLUDED.avoid_topics,
                blocked_users = EXCLUDED.blocked_users, temperature = EXCLUDED.temperature,
                max_tokens = EXCLUDED.max_tokens, is_active = EXCLUDED.is_active,
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
