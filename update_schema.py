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

if __name__ == "__main__":
    print("🔧 Running database migration to add missing columns...")
    if migrate_client_settings():
        print("✅ Your database is now updated and ready!")
    else:
        print("❌ Migration failed. Please check the errors above.")
