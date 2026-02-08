"""
Database connection and management utilities.
Uses connection pooling for PostgreSQL in production.
"""
import os
import logging
import sqlite3
import psycopg2
import psycopg2.pool
from config import Config

logger = logging.getLogger("chata.database")

# ---------------------------------------------------------------------------
# PostgreSQL connection pool (initialised lazily on first use)
# ---------------------------------------------------------------------------
_pg_pool = None


def _get_pg_pool():
    """Return (and lazily create) the PostgreSQL connection pool."""
    global _pg_pool
    if _pg_pool is None:
        database_url = os.environ.get('DATABASE_URL')
        if database_url:
            _pg_pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=database_url,
            )
    return _pg_pool


class _PooledConnection:
    """Thin wrapper so conn.close() returns the connection to the pool
    instead of actually closing it.  Delegates everything else to the
    real psycopg2 connection."""

    def __init__(self, real_conn, pool):
        self._conn = real_conn
        self._pool = pool

    def close(self):
        """Return connection to pool instead of closing it."""
        try:
            self._pool.putconn(self._conn)
        except Exception:
            self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_db_connection():
    """Get database connection — uses pool for PostgreSQL, direct for SQLite."""
    database_url = os.environ.get('DATABASE_URL')

    if database_url and (database_url.startswith('postgres://') or database_url.startswith('postgresql://')):
        pool = _get_pg_pool()
        if pool:
            try:
                conn = pool.getconn()
                return _PooledConnection(conn, pool)
            except Exception as e:
                logger.error(f"PostgreSQL pool error: {e}")
                return None
        else:
            try:
                return psycopg2.connect(database_url)
            except Exception as e:
                logger.error(f"PostgreSQL connection error: {e}")
                return None
    else:
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
    logger.info("Initializing database...")
    
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        logger.info(f"Database connection - DATABASE_URL: {database_url[:50]}...")
    
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to get database connection")
        return False
    
    try:
        cursor = conn.cursor()
        
        # Check if we're using PostgreSQL or SQLite
        is_postgres = bool(database_url and (database_url.startswith('postgres://') or database_url.startswith('postgresql://')))
        
        if is_postgres:
            logger.info("Using PostgreSQL database")
            _create_postgres_tables(cursor)
        else:
            logger.info("Using SQLite database")
            _create_sqlite_tables(cursor)
        
        # Insert default settings
        _insert_default_settings(cursor, is_postgres)
        
        # Set existing users without subscriptions to 0 replies ONLY if they never received free trial
        # This preserves free trial replies that users earned
        try:
            if is_postgres:
                cursor.execute("""
                    UPDATE users 
                    SET replies_limit_monthly = 0 
                    WHERE id NOT IN (
                        SELECT DISTINCT user_id FROM subscriptions WHERE status = 'active'
                    ) 
                    AND (replies_limit_monthly IS NULL OR replies_limit_monthly > 0)
                    AND (has_received_free_trial IS NULL OR has_received_free_trial = FALSE)
                """)
            else:
                cursor.execute("""
                    UPDATE users 
                    SET replies_limit_monthly = 0 
                    WHERE id NOT IN (
                        SELECT DISTINCT user_id FROM subscriptions WHERE status = 'active'
                    ) 
                    AND (replies_limit_monthly IS NULL OR replies_limit_monthly > 0)
                    AND (has_received_free_trial IS NULL OR has_received_free_trial = 0)
                """)
            logger.info("Updated users without active subscriptions to 0 replies (preserving free trial replies)")
        except Exception as e:
            logger.warning(f"Could not update existing users' limits: {e}")
        
        conn.commit()
        logger.info("Database initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        try:
            conn.rollback()
            logger.info("Transaction rolled back, continuing...")
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
            username VARCHAR(255) UNIQUE NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            replies_sent_monthly INTEGER DEFAULT 0,
            replies_limit_monthly INTEGER DEFAULT 0,
            replies_purchased INTEGER DEFAULT 0,
            replies_used_purchased INTEGER DEFAULT 0,
            last_monthly_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Add new columns to existing users table if they don't exist
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(255)")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS replies_sent_monthly INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS replies_limit_monthly INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS replies_purchased INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS replies_used_purchased INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_monthly_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS bot_paused BOOLEAN DEFAULT FALSE")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_warning_sent_at TIMESTAMP")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_warning_threshold INTEGER")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS has_received_free_trial BOOLEAN DEFAULT FALSE")
    except Exception as e:
        logger.debug(f"Some columns may already exist: {e}")
    
    # Create instagram_connections table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS instagram_connections (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            instagram_user_id VARCHAR(255) NOT NULL,
            instagram_page_id VARCHAR(255) NOT NULL,
            instagram_page_name VARCHAR(255),
            instagram_username VARCHAR(255),
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
            faqs TEXT,
            instagram_url TEXT,
            avoid_topics TEXT,
            blocked_users TEXT,
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
            instagram_connection_id INTEGER REFERENCES instagram_connections(id),
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
    
    # Create stripe_webhook_events table for webhook idempotency (avoid processing same event twice)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stripe_webhook_events (
            event_id VARCHAR(255) PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Indexes on instagram_connections for fast webhook lookups by recipient
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_instagram_connections_user_id ON instagram_connections(instagram_user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_instagram_connections_page_id ON instagram_connections(instagram_page_id)")
    cursor.execute("ALTER TABLE instagram_connections ADD COLUMN IF NOT EXISTS instagram_page_name TEXT")
    cursor.execute("ALTER TABLE instagram_connections ADD COLUMN IF NOT EXISTS instagram_username TEXT")
    
    # Instagram webhook idempotency: avoid processing same message (mid) twice on retries
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS instagram_webhook_processed_mids (
            mid VARCHAR(512) PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Cache sender usernames for conversation history search
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_senders (
            instagram_connection_id INTEGER REFERENCES instagram_connections(id),
            instagram_user_id VARCHAR(255) NOT NULL,
            username VARCHAR(255),
            PRIMARY KEY (instagram_connection_id, instagram_user_id)
        )
    """)
    # App Review mode: bot reply saved but not sent until user clicks Send in Conversation History
    cursor.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS sent_via_api BOOLEAN DEFAULT TRUE")

def _create_sqlite_tables(cursor):
    """Create SQLite tables"""
    # Create users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            replies_sent_monthly INTEGER DEFAULT 0,
            replies_limit_monthly INTEGER DEFAULT 0,
            replies_purchased INTEGER DEFAULT 0,
            replies_used_purchased INTEGER DEFAULT 0,
            last_monthly_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Add new columns to existing users table if they don't exist (SQLite doesn't support IF NOT EXISTS for ALTER TABLE)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN replies_sent_monthly INTEGER DEFAULT 0")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN replies_limit_monthly INTEGER DEFAULT 0")
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
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN has_received_free_trial BOOLEAN DEFAULT 0")
    except:
        pass
    
    # Create instagram_connections table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS instagram_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            instagram_user_id TEXT NOT NULL,
            instagram_page_id TEXT NOT NULL,
            instagram_page_name TEXT,
            instagram_username TEXT,
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
            faqs TEXT,
            instagram_url TEXT,
            avoid_topics TEXT,
            blocked_users TEXT,
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
            instagram_connection_id INTEGER REFERENCES instagram_connections(id),
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
        logger.debug(f"Subscriptions table may already exist: {e}")
    
    # Create stripe_webhook_events table for webhook idempotency
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stripe_webhook_events (
                event_id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    except Exception as e:
        logger.debug(f"stripe_webhook_events table may already exist: {e}")
    
    # Indexes on instagram_connections for fast webhook lookups
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_instagram_connections_user_id ON instagram_connections(instagram_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_instagram_connections_page_id ON instagram_connections(instagram_page_id)")
    except Exception as e:
        logger.debug(f"instagram_connections indexes may already exist: {e}")
    
    # Instagram webhook idempotency (processed message ids)
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS instagram_webhook_processed_mids (
                mid TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    except Exception as e:
        logger.debug(f"instagram_webhook_processed_mids table may already exist: {e}")
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_senders (
                instagram_connection_id INTEGER REFERENCES instagram_connections(id),
                instagram_user_id TEXT NOT NULL,
                username TEXT,
                PRIMARY KEY (instagram_connection_id, instagram_user_id)
            )
        """)
    except Exception as e:
        logger.debug(f"conversation_senders table may already exist: {e}")
    try:
        cursor.execute("ALTER TABLE messages ADD COLUMN sent_via_api INTEGER DEFAULT 1")
    except Exception as e:
        logger.debug(f"messages.sent_via_api column may already exist: {e}")

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
