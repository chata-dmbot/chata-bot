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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
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
            temperature REAL DEFAULT 0.7,
            max_tokens INTEGER DEFAULT 150,
            auto_reply BOOLEAN DEFAULT TRUE,
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

def _create_sqlite_tables(cursor):
    """Create SQLite tables"""
    # Create users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
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
            temperature REAL DEFAULT 0.7,
            max_tokens INTEGER DEFAULT 150,
            auto_reply BOOLEAN DEFAULT 1,
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
