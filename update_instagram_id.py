#!/usr/bin/env python3
"""
Update Instagram User ID in database from business account ID to correct user ID
"""

import os
import sqlite3
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

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
        print(f"🔗 Using SQLite database (local development)")
        return sqlite3.connect("chata.db")

def update_instagram_user_id():
    """Update Instagram User ID from business account ID to correct user ID"""
    print("🔧 Updating Instagram User ID in database...")
    
    conn = get_db_connection()
    if not conn:
        print("❌ Failed to get database connection")
        return False
    
    try:
        cursor = conn.cursor()
        
        # Check current data
        print("📋 Current Instagram connections:")
        cursor.execute("SELECT id, instagram_user_id, instagram_page_id FROM instagram_connections")
        connections = cursor.fetchall()
        
        for conn_info in connections:
            print(f"  - ID: {conn_info[0]}, User ID: {conn_info[1]}, Page ID: {conn_info[2]}")
        
        # Update the Instagram User ID from business account ID to user ID
        old_id = "17841471490292183"  # Business account ID
        new_id = "71457471009"        # Correct user ID
        
        print(f"🔄 Updating Instagram User ID from {old_id} to {new_id}...")
        
        # Check if we're using PostgreSQL or SQLite
        is_postgres = bool(os.environ.get('DATABASE_URL') and (os.environ.get('DATABASE_URL').startswith('postgres://') or os.environ.get('DATABASE_URL').startswith('postgresql://')))
        
        if is_postgres:
            cursor.execute("""
                UPDATE instagram_connections 
                SET instagram_user_id = %s 
                WHERE instagram_user_id = %s
            """, (new_id, old_id))
        else:
            cursor.execute("""
                UPDATE instagram_connections 
                SET instagram_user_id = ? 
                WHERE instagram_user_id = ?
            """, (new_id, old_id))
        
        rows_updated = cursor.rowcount
        print(f"✅ Updated {rows_updated} row(s)")
        
        # Verify the update
        print("📋 Updated Instagram connections:")
        cursor.execute("SELECT id, instagram_user_id, instagram_page_id FROM instagram_connections")
        connections = cursor.fetchall()
        
        for conn_info in connections:
            print(f"  - ID: {conn_info[0]}, User ID: {conn_info[1]}, Page ID: {conn_info[2]}")
        
        conn.commit()
        print("✅ Database updated successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error updating database: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("🚀 Starting Instagram User ID update...")
    if update_instagram_user_id():
        print("🎉 Update completed successfully!")
    else:
        print("💥 Update failed!")
