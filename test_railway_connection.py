#!/usr/bin/env python3
"""
Test script to verify Railway PostgreSQL connection
Run this after setting up Railway and updating your DATABASE_URL
"""

import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_railway_connection():
    """Test the Railway PostgreSQL connection"""
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        print("❌ DATABASE_URL not found in environment variables")
        return False
    
    print(f"🔗 Testing connection to: {database_url[:50]}...")
    
    try:
        # Test connection
        conn = psycopg2.connect(database_url)
        print("✅ Connection successful!")
        
        # Test basic query
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        print(f"✅ Database version: {version[0]}")
        
        # Test table creation
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS test_connection (
                id SERIAL PRIMARY KEY,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✅ Test table created successfully")
        
        # Test insert
        cursor.execute("INSERT INTO test_connection (message) VALUES (%s)", ("Connection test successful!",))
        print("✅ Test insert successful")
        
        # Test select
        cursor.execute("SELECT message FROM test_connection ORDER BY id DESC LIMIT 1")
        result = cursor.fetchone()
        print(f"✅ Test select successful: {result[0]}")
        
        # Clean up
        cursor.execute("DROP TABLE test_connection")
        print("✅ Test table cleaned up")
        
        conn.commit()
        conn.close()
        print("✅ All tests passed! Railway connection is working perfectly.")
        return True
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print(f"Error type: {type(e).__name__}")
        return False

if __name__ == "__main__":
    print("🚀 Testing Railway PostgreSQL Connection...")
    success = test_railway_connection()
    
    if success:
        print("\n🎉 Railway setup is complete! You can now deploy to Render.")
    else:
        print("\n💡 Check your Railway connection string and try again.")
