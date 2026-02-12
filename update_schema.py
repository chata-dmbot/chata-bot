#!/usr/bin/env python3
"""
Migration script to add missing columns to client_settings table
Run this once to update your existing database schema
"""
import os
from dotenv import load_dotenv
from database import get_db_connection

load_dotenv()

def migrate_client_settings():
    """Add missing columns to client_settings table"""
    conn = get_db_connection()
    if not conn:
        print("❌ Failed to connect to database")
        return False
    
    cursor = conn.cursor()
    
    try:
        # Add all missing columns if they don't exist
        columns_to_add = [
            ('bot_name', 'TEXT'),
            ('bot_age', 'TEXT'),
            ('bot_gender', 'TEXT'),
            ('bot_location', 'TEXT'),
            ('bot_occupation', 'TEXT'),
            ('bot_education', 'TEXT'),
            ('personality_type', 'TEXT'),
            ('bot_values', 'TEXT'),
            ('tone_of_voice', 'TEXT'),
            ('habits_quirks', 'TEXT'),
            ('confidence_level', 'TEXT'),
            ('emotional_range', 'TEXT'),
            ('main_goal', 'TEXT'),
            ('fears_insecurities', 'TEXT'),
            ('what_drives_them', 'TEXT'),
            ('obstacles', 'TEXT'),
            ('backstory', 'TEXT'),
            ('family_relationships', 'TEXT'),
            ('culture_environment', 'TEXT'),
            ('hobbies_interests', 'TEXT'),
            ('reply_style', 'TEXT'),
            ('emoji_slang', 'TEXT'),
            ('conflict_handling', 'TEXT'),
            ('preferred_topics', 'TEXT'),
            ('use_active_hours', 'BOOLEAN DEFAULT FALSE'),
            ('active_start', "TEXT DEFAULT '09:00'"),
            ('active_end', "TEXT DEFAULT '18:00'"),
            ('links', 'TEXT'),
            ('posts', 'TEXT'),
            ('conversation_samples', 'TEXT'),
            ('faqs', 'TEXT'),
            ('instagram_url', 'TEXT'),
            ('avoid_topics', 'TEXT'),
            ('blocked_users', 'TEXT'),
            ('is_active', 'BOOLEAN DEFAULT TRUE'),
        ]
        
        # Check database type
        db_url = os.environ.get('DATABASE_URL', '')
        is_postgres = db_url.startswith('postgres://') or db_url.startswith('postgresql://')
        
        for column_name, column_type in columns_to_add:
            try:
                if is_postgres:
                    # PostgreSQL: Check if column exists, then add
                    cursor.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name='client_settings' AND column_name=%s
                    """, (column_name,))
                    
                    if not cursor.fetchone():
                        cursor.execute(f"ALTER TABLE client_settings ADD COLUMN {column_name} {column_type}")
                        print(f"✅ Added column: {column_name}")
                    else:
                        print(f"⏭️  Column already exists: {column_name}")
                else:
                    # SQLite: Try to add, ignore if exists
                    try:
                        cursor.execute(f"ALTER TABLE client_settings ADD COLUMN {column_name} {column_type}")
                        print(f"✅ Added column: {column_name}")
                    except Exception as e:
                        if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                            print(f"⏭️  Column already exists: {column_name}")
                        else:
                            raise
                            
            except Exception as e:
                print(f"❌ Error adding column {column_name}: {e}")
                return False
        
        conn.commit()
        print("✅ Migration completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def migrate_instagram_connections():
    """Add instagram_page_name and instagram_username to instagram_connections"""
    conn = get_db_connection()
    if not conn:
        print("❌ Failed to connect to database")
        return False
    
    cursor = conn.cursor()
    
    try:
        db_url = os.environ.get('DATABASE_URL', '')
        is_postgres = db_url.startswith('postgres://') or db_url.startswith('postgresql://')
        
        for column_name, column_type in [('instagram_page_name', 'VARCHAR(255)' if is_postgres else 'TEXT'),
                                         ('instagram_username', 'VARCHAR(255)' if is_postgres else 'TEXT')]:
            try:
                if is_postgres:
                    cursor.execute("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name='instagram_connections' AND column_name=%s
                    """, (column_name,))
                    if not cursor.fetchone():
                        cursor.execute(f"ALTER TABLE instagram_connections ADD COLUMN {column_name} {column_type}")
                        print(f"✅ Added column instagram_connections.{column_name}")
                else:
                    cursor.execute(f"ALTER TABLE instagram_connections ADD COLUMN {column_name} {column_type}")
                    print(f"✅ Added column instagram_connections.{column_name}")
            except Exception as e:
                if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                    print(f"⏭️  Column instagram_connections.{column_name} already exists")
                else:
                    raise
        
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ instagram_connections migration failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def migrate_messages_connection_id():
    """Add instagram_connection_id to messages table so messages can be scoped per Instagram connection"""
    conn = get_db_connection()
    if not conn:
        print("❌ Failed to connect to database")
        return False
    
    cursor = conn.cursor()
    
    try:
        db_url = os.environ.get('DATABASE_URL', '')
        is_postgres = db_url.startswith('postgres://') or db_url.startswith('postgresql://')
        
        column_name = 'instagram_connection_id'
        if is_postgres:
            # Check if column exists in PostgreSQL
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='messages' AND column_name=%s
            """, (column_name,))
            if not cursor.fetchone():
                cursor.execute("""
                    ALTER TABLE messages 
                    ADD COLUMN instagram_connection_id INTEGER REFERENCES instagram_connections(id)
                """)
                print("✅ Added column messages.instagram_connection_id")
            else:
                print("⏭️  Column messages.instagram_connection_id already exists")
        else:
            # SQLite: try to add, ignore if it already exists
            try:
                cursor.execute("""
                    ALTER TABLE messages 
                    ADD COLUMN instagram_connection_id INTEGER REFERENCES instagram_connections(id)
                """)
                print("✅ Added column messages.instagram_connection_id")
            except Exception as e:
                if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                    print("⏭️  Column messages.instagram_connection_id already exists")
                else:
                    raise
        
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ messages table migration failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def migrate_conversation_senders():
    """Create conversation_senders table for caching sender usernames (search by username)."""
    conn = get_db_connection()
    if not conn:
        print("❌ Failed to connect to database")
        return False
    cursor = conn.cursor()
    try:
        db_url = os.environ.get('DATABASE_URL', '')
        is_postgres = db_url.startswith('postgres://') or db_url.startswith('postgresql://')
        if is_postgres:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_senders (
                    instagram_connection_id INTEGER REFERENCES instagram_connections(id),
                    instagram_user_id VARCHAR(255) NOT NULL,
                    username VARCHAR(255),
                    PRIMARY KEY (instagram_connection_id, instagram_user_id)
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_senders (
                    instagram_connection_id INTEGER REFERENCES instagram_connections(id),
                    instagram_user_id TEXT NOT NULL,
                    username TEXT,
                    PRIMARY KEY (instagram_connection_id, instagram_user_id)
                )
            """)
        conn.commit()
        print("✅ conversation_senders table ready")
        return True
    except Exception as e:
        print(f"❌ conversation_senders migration failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def migrate_instagram_connections_webhook():
    """Add webhook status columns to instagram_connections (for Meta app review temporary UI)."""
    conn = get_db_connection()
    if not conn:
        print("❌ Failed to connect to database")
        return False
    cursor = conn.cursor()
    try:
        db_url = os.environ.get('DATABASE_URL', '')
        is_postgres = db_url.startswith('postgres://') or db_url.startswith('postgresql://')
        columns_to_add = [
            ('webhook_subscription_active', 'BOOLEAN DEFAULT FALSE' if is_postgres else 'BOOLEAN DEFAULT 0'),
            ('last_webhook_at', 'TIMESTAMP' if is_postgres else 'TIMESTAMP'),
            ('last_webhook_event_type', 'VARCHAR(64)' if is_postgres else 'TEXT'),
        ]
        for column_name, column_type in columns_to_add:
            try:
                if is_postgres:
                    cursor.execute("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name='instagram_connections' AND column_name=%s
                    """, (column_name,))
                    if not cursor.fetchone():
                        cursor.execute(f"ALTER TABLE instagram_connections ADD COLUMN {column_name} {column_type}")
                        print(f"✅ Added column instagram_connections.{column_name}")
                    else:
                        print(f"⏭️  Column instagram_connections.{column_name} already exists")
                else:
                    try:
                        cursor.execute(f"ALTER TABLE instagram_connections ADD COLUMN {column_name} {column_type}")
                        print(f"✅ Added column instagram_connections.{column_name}")
                    except Exception as e:
                        if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                            print(f"⏭️  Column instagram_connections.{column_name} already exists")
                        else:
                            raise
            except Exception as e:
                print(f"❌ Error adding instagram_connections.{column_name}: {e}")
                return False
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ instagram_connections webhook migration failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    print("🔧 Running database migration to add missing columns...")
    ok1 = migrate_client_settings()
    ok2 = migrate_instagram_connections()
    ok3 = migrate_messages_connection_id()
    ok4 = migrate_conversation_senders()
    ok5 = migrate_instagram_connections_webhook()
    if ok1 and ok2 and ok3 and ok4 and ok5:
        print("✅ Your database is now updated and ready!")
    else:
        print("❌ Migration failed. Please check the errors above.")
