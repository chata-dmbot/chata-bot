import sqlite3
import hashlib
import secrets

# Connect to (or create) the database file
conn = sqlite3.connect("chata.db")

# Create a cursor to execute SQL commands
cursor = conn.cursor()

# Create the users table
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    company_name TEXT,
    subscription_plan TEXT DEFAULT 'free',
    subscription_status TEXT DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
""")

# Create the instagram_connections table
cursor.execute("""
CREATE TABLE IF NOT EXISTS instagram_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    instagram_user_id TEXT NOT NULL,
    instagram_page_id TEXT NOT NULL,
    page_access_token TEXT NOT NULL,
    page_name TEXT,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id),
    UNIQUE(instagram_user_id, instagram_page_id)
);
""")

# Create the client_settings table
cursor.execute("""
CREATE TABLE IF NOT EXISTS client_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    instagram_connection_id INTEGER,
    system_prompt TEXT DEFAULT 'You are a friendly digital creator''s assistant. Reply to DMs from fans in a positive, helpful way.',
    temperature REAL DEFAULT 0.8,
    max_tokens INTEGER DEFAULT 100,
    bot_name TEXT DEFAULT 'Chata Bot',
    welcome_message TEXT DEFAULT 'Hi! I''m here to help. How can I assist you today?',
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (instagram_connection_id) REFERENCES instagram_connections (id)
);
""")

# Create the messages table (updated for multi-tenant)
cursor.execute("""
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    instagram_connection_id INTEGER,
    sender_instagram_id TEXT NOT NULL,
    role TEXT NOT NULL,         -- 'user' or 'assistant'
    content TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (instagram_connection_id) REFERENCES instagram_connections (id)
);
""")

# Create the settings table (for global admin settings)
cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
""")

# Create the usage_logs table (for tracking API usage)
cursor.execute("""
CREATE TABLE IF NOT EXISTS usage_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    instagram_connection_id INTEGER,
    action_type TEXT NOT NULL,  -- 'message_sent', 'api_call', etc.
    tokens_used INTEGER DEFAULT 0,
    cost_cents INTEGER DEFAULT 0,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (instagram_connection_id) REFERENCES instagram_connections (id)
);
""")

# Create the activity_logs table (for tracking user activities)
cursor.execute("""
CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,  -- 'login', 'settings_updated', 'bot_activated', etc.
    description TEXT,
    ip_address TEXT,
    user_agent TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);
""")

# Insert default admin settings
cursor.execute("""
INSERT OR IGNORE INTO settings (key, value) VALUES 
('system_prompt', 'You are a friendly digital creator''s assistant. Reply to DMs from fans in a positive, helpful way.'),
('temperature', '0.8'),
('max_tokens', '100')
""")

# Save (commit) changes and close
conn.commit()
conn.close()

print("Multi-tenant database schema created successfully!")
print("Tables created:")
print("- users (client accounts)")
print("- instagram_connections (IG account links)")
print("- client_settings (per-client bot settings)")
print("- messages (updated for multi-tenant)")
print("- settings (global admin settings)")
print("- usage_logs (usage tracking)")
