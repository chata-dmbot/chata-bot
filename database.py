"""
Database connection and management utilities
"""
import os
import sqlite3
import psycopg2
from config import Config

def get_db_connection():
    """Get database connection - automatically chooses between SQLite and PostgreSQL"""
    database_url = os.environ.get('DATABASE_URL')
    
    if database_url and (database_url.startswith('postgres://') or database_url.startswith('postgresql://')):
        print(f"🔗 Connecting to PostgreSQL database...")
        try:
            conn = psycopg2.connect(database_url)
            print(f"✅ PostgreSQL connected successfully")
            return conn
        except Exception as e:
            print(f"❌ PostgreSQL connection error: {e}")
            return None
    else:
        print(f"Using SQLite database (local development)")
        return sqlite3.connect(Config.DB_FILE)

def get_param_placeholder():
    """Get the correct parameter placeholder for the current database"""
    database_url = os.environ.get('DATABASE_URL')
    if database_url and (database_url.startswith('postgres://') or database_url.startswith('postgresql://')):
        return '%s'  # PostgreSQL uses %s
    else:
        return '?'   # SQLite uses ?

def init_database():
    """Initialize database tables"""
    print("Initializing database...")
    
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        print(f"Database connection - DATABASE_URL: {database_url[:50]}...")
    
    conn = get_db_connection()
    if not conn:
        print("❌ Failed to get database connection")
        return False
    
    try:
        cursor = conn.cursor()
        
        # Check if we're using PostgreSQL or SQLite
        is_postgres = bool(database_url and (database_url.startswith('postgres://') or database_url.startswith('postgresql://')))
        
        if is_postgres:
            print("✅ Using PostgreSQL database")
            _create_postgres_tables(cursor)
        else:
            print("Using SQLite database")
            _create_sqlite_tables(cursor)
        
        # Insert default settings
        _insert_default_settings(cursor, is_postgres)
        
        # Update existing users' reply limits to 5 for testing (if they don't have the column set)
        try:
            if is_postgres:
                cursor.execute("""
                    UPDATE users 
                    SET replies_limit_monthly = 5 
                    WHERE replies_limit_monthly IS NULL OR replies_limit_monthly = 1000
                """)
            else:
                cursor.execute("""
                    UPDATE users 
                    SET replies_limit_monthly = 5 
                    WHERE replies_limit_monthly IS NULL OR replies_limit_monthly = 1000
                """)
            print("✅ Updated existing users' reply limits to 5 for testing")
        except Exception as e:
            print(f"Note: Could not update existing users' limits: {e}")
        
        conn.commit()
        print("Database initialized successfully")
        return True
        
    except Exception as e:
        print(f"Error initializing database: {e}")
        print(f"Error type: {type(e).__name__}")
        try:
            conn.rollback()
            print("Transaction rolled back, continuing...")
        except:
            pass
        return False
    finally:
        try:
            conn.close()
        except:
            pass

def _create_postgres_tables(cursor):
    """Create PostgreSQL tables"""
    # Create users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            replies_sent_monthly INTEGER DEFAULT 0,
            replies_limit_monthly INTEGER DEFAULT 5,
            replies_purchased INTEGER DEFAULT 0,
            replies_used_purchased INTEGER DEFAULT 0,
            last_monthly_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Add new columns to existing users table if they don't exist
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS replies_sent_monthly INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS replies_limit_monthly INTEGER DEFAULT 5")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS replies_purchased INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS replies_used_purchased INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_monthly_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS bot_paused BOOLEAN DEFAULT FALSE")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_warning_sent_at TIMESTAMP")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_warning_threshold INTEGER")
    except Exception as e:
        print(f"Note: Some columns may already exist: {e}")
    
    # Create instagram_connections table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS instagram_connections (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            instagram_user_id VARCHAR(255) NOT NULL,
            instagram_page_id VARCHAR(255) NOT NULL,
            page_access_token TEXT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create client_settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS client_settings (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            instagram_connection_id INTEGER REFERENCES instagram_connections(id),
            bot_personality TEXT DEFAULT 'You are a helpful and friendly Instagram bot.',
            bot_name TEXT,
            bot_age TEXT,
            bot_gender TEXT,
            bot_location TEXT,
            bot_occupation TEXT,
            bot_education TEXT,
            personality_type TEXT,
            bot_values TEXT,
            tone_of_voice TEXT,
            habits_quirks TEXT,
            confidence_level TEXT,
            emotional_range TEXT,
            main_goal TEXT,
            fears_insecurities TEXT,
            what_drives_them TEXT,
            obstacles TEXT,
            backstory TEXT,
            family_relationships TEXT,
            culture_environment TEXT,
            hobbies_interests TEXT,
            reply_style TEXT,
            emoji_slang TEXT,
            conflict_handling TEXT,
            preferred_topics TEXT,
            use_active_hours BOOLEAN DEFAULT FALSE,
            active_start TEXT DEFAULT '09:00',
            active_end TEXT DEFAULT '18:00',
            links TEXT,
            posts TEXT,
            conversation_samples TEXT,
            instagram_url TEXT,
            avoid_topics TEXT,
            temperature REAL DEFAULT 0.7,
            max_tokens INTEGER DEFAULT 150,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create usage_logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usage_logs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            instagram_connection_id INTEGER REFERENCES instagram_connections(id),
            action VARCHAR(100) NOT NULL,
            tokens_used INTEGER DEFAULT 0,
            cost REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create activity_logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            action VARCHAR(100) NOT NULL,
            details TEXT,
            ip_address VARCHAR(45),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create password_resets table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            token VARCHAR(255) UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create messages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            instagram_user_id VARCHAR(255) NOT NULL,
            message_text TEXT NOT NULL,
            bot_response TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id SERIAL PRIMARY KEY,
            key VARCHAR(255) UNIQUE NOT NULL,
            value TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create purchases table for tracking purchased additional replies
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            amount_paid DECIMAL(10, 2) NOT NULL,
            replies_added INTEGER NOT NULL,
            payment_provider VARCHAR(50),
            payment_id VARCHAR(255),
            status VARCHAR(50) DEFAULT 'completed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create subscriptions table for tracking user subscriptions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            stripe_subscription_id VARCHAR(255) UNIQUE NOT NULL,
            stripe_customer_id VARCHAR(255) NOT NULL,
            stripe_price_id VARCHAR(255) NOT NULL,
            plan_type VARCHAR(50) NOT NULL,
            status VARCHAR(50) NOT NULL,
            current_period_start TIMESTAMP,
            current_period_end TIMESTAMP,
            cancel_at_period_end BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

def _create_sqlite_tables(cursor):
    """Create SQLite tables"""
    # Create users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            replies_sent_monthly INTEGER DEFAULT 0,
            replies_limit_monthly INTEGER DEFAULT 5,
            replies_purchased INTEGER DEFAULT 0,
            replies_used_purchased INTEGER DEFAULT 0,
            last_monthly_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Add new columns to existing users table if they don't exist (SQLite doesn't support IF NOT EXISTS for ALTER TABLE)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN replies_sent_monthly INTEGER DEFAULT 0")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN replies_limit_monthly INTEGER DEFAULT 5")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN replies_purchased INTEGER DEFAULT 0")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN replies_used_purchased INTEGER DEFAULT 0")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN last_monthly_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN bot_paused BOOLEAN DEFAULT 0")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN last_warning_sent_at TIMESTAMP")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN last_warning_threshold INTEGER")
    except:
        pass
    
    # Create instagram_connections table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS instagram_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            instagram_user_id TEXT NOT NULL,
            instagram_page_id TEXT NOT NULL,
            page_access_token TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create client_settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS client_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            instagram_connection_id INTEGER REFERENCES instagram_connections(id),
            bot_personality TEXT DEFAULT 'You are a helpful and friendly Instagram bot.',
            bot_name TEXT,
            bot_age TEXT,
            bot_gender TEXT,
            bot_location TEXT,
            bot_occupation TEXT,
            bot_education TEXT,
            personality_type TEXT,
            bot_values TEXT,
            tone_of_voice TEXT,
            habits_quirks TEXT,
            confidence_level TEXT,
            emotional_range TEXT,
            main_goal TEXT,
            fears_insecurities TEXT,
            what_drives_them TEXT,
            obstacles TEXT,
            backstory TEXT,
            family_relationships TEXT,
            culture_environment TEXT,
            hobbies_interests TEXT,
            reply_style TEXT,
            emoji_slang TEXT,
            conflict_handling TEXT,
            preferred_topics TEXT,
            use_active_hours BOOLEAN DEFAULT 0,
            active_start TEXT DEFAULT '09:00',
            active_end TEXT DEFAULT '18:00',
            links TEXT,
            posts TEXT,
            conversation_samples TEXT,
            instagram_url TEXT,
            avoid_topics TEXT,
            temperature REAL DEFAULT 0.7,
            max_tokens INTEGER DEFAULT 150,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create usage_logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            instagram_connection_id INTEGER REFERENCES instagram_connections(id),
            action TEXT NOT NULL,
            tokens_used INTEGER DEFAULT 0,
            cost REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create activity_logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            action TEXT NOT NULL,
            details TEXT,
            ip_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create password_resets table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            token TEXT UNIQUE NOT NULL,
            expires_at DATETIME NOT NULL,
            used_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create messages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instagram_user_id TEXT NOT NULL,
            message_text TEXT NOT NULL,
            bot_response TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create purchases table for tracking purchased additional replies
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            amount_paid REAL NOT NULL,
            replies_added INTEGER NOT NULL,
            payment_provider TEXT,
            payment_id TEXT,
            status TEXT DEFAULT 'completed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create subscriptions table for tracking user subscriptions
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                stripe_subscription_id TEXT UNIQUE NOT NULL,
                stripe_customer_id TEXT NOT NULL,
                stripe_price_id TEXT NOT NULL,
                plan_type TEXT NOT NULL,
                status TEXT NOT NULL,
                current_period_start TIMESTAMP,
                current_period_end TIMESTAMP,
                cancel_at_period_end INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    except Exception as e:
        print(f"Note: subscriptions table may already exist: {e}")

def _insert_default_settings(cursor, is_postgres):
    """Insert default settings into the database"""
    param = get_param_placeholder()
    
    if is_postgres:
        # PostgreSQL syntax
        cursor.execute(f"SELECT id FROM settings WHERE key = {param}", ('bot_personality',))
        if not cursor.fetchone():
            cursor.execute(f"INSERT INTO settings (key, value) VALUES ({param}, {param})", 
                          ('bot_personality', 'You are a helpful and friendly Instagram bot.'))
        
        cursor.execute(f"SELECT id FROM settings WHERE key = {param}", ('temperature',))
        if not cursor.fetchone():
            cursor.execute(f"INSERT INTO settings (key, value) VALUES ({param}, {param})", 
                          ('temperature', '0.7'))
        
        cursor.execute(f"SELECT id FROM settings WHERE key = {param}", ('max_tokens',))
        if not cursor.fetchone():
            cursor.execute(f"INSERT INTO settings (key, value) VALUES ({param}, {param})", 
                          ('max_tokens', '150'))
    else:
        # SQLite syntax
        cursor.execute(f"INSERT OR IGNORE INTO settings (key, value) VALUES ({param}, {param})", 
                      ('bot_personality', 'You are a helpful and friendly Instagram bot.'))
        cursor.execute(f"INSERT OR IGNORE INTO settings (key, value) VALUES ({param}, {param})", 
                      ('temperature', '0.7'))
        cursor.execute(f"INSERT OR IGNORE INTO settings (key, value) VALUES ({param}, {param})", 
                      ('max_tokens', '150'))
