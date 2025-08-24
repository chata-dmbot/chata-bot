import sqlite3

conn = sqlite3.connect("chata.db")
cursor = conn.cursor()

# Create settings table if it doesn't exist
cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

# Insert default settings if not already set
cursor.execute(
    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
    ("system_prompt", "You are a friendly digital creator's assistant. Reply to DMs from fans in a positive, helpful way.")
)
cursor.execute(
    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
    ("temperature", "0.8")
)
cursor.execute(
    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
    ("max_tokens", "100")
)

conn.commit()
conn.close()

print("Settings table created and default values set!")
