#!/usr/bin/env python3
"""
Simple database connection test script
Run this to test if we can connect to the database
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

print("🔍 Testing Database Connection")
if DATABASE_URL:
    # Print only the scheme + host, never the full DSN (which contains credentials).
    try:
        from urllib.parse import urlparse
        parsed = urlparse(DATABASE_URL)
        host = parsed.hostname or "unknown"
        port = parsed.port or "default"
        scheme = parsed.scheme or "unknown"
        print(f"🔍 DATABASE_URL target: {scheme}://{host}:{port}")
    except Exception:
        print("🔍 DATABASE_URL: present (details redacted)")
else:
    print("🔍 DATABASE_URL: None")

if not DATABASE_URL:
    print("❌ No DATABASE_URL found in environment variables")
    exit(1)

try:
    import psycopg2
    print("✅ psycopg2 imported successfully")
    
    # Test connection
    print("🔍 Attempting to connect...")
    conn = psycopg2.connect(DATABASE_URL)
    print("✅ Database connection successful!")
    
    # Test a simple query
    cursor = conn.cursor()
    cursor.execute("SELECT version();")
    version = cursor.fetchone()
    print(f"✅ Database version: {version[0]}")
    
    # Test if we can create a table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS connection_test (
            id SERIAL PRIMARY KEY,
            test_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("✅ Can create tables successfully")
    
    # Clean up
    cursor.execute("DROP TABLE IF EXISTS connection_test")
    conn.commit()
    conn.close()
    print("✅ All tests passed!")
    
except ImportError as e:
    print(f"❌ psycopg2 not installed: {e}")
    print("Install with: pip install psycopg2-binary")
    
except Exception as e:
    print(f"❌ Connection failed: {e}")
    print(f"❌ Error type: {type(e).__name__}")
    
    # Additional debugging info
    if "Network is unreachable" in str(e):
        print("\n🔍 This is a NETWORK issue, not a code issue!")
        print("Possible solutions:")
        print("1. Check Supabase IP restrictions")
        print("2. Verify Supabase database is active")
        print("3. Check if DATABASE_URL is correct")
        print("4. Try using Connection string instead of URI")

