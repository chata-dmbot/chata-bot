#!/usr/bin/env python3
import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL:
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Check Instagram connections
        cursor.execute('SELECT id, user_id, instagram_user_id, instagram_page_id, is_active FROM instagram_connections')
        connections = cursor.fetchall()
        print('📱 Instagram Connections:')
        for conn_data in connections:
            print(f'  ID: {conn_data[0]}, User: {conn_data[1]}, IG User ID: {conn_data[2]}, Page ID: {conn_data[3]}, Active: {conn_data[4]}')
        
        # Check client settings
        cursor.execute('SELECT id, user_id, instagram_connection_id, bot_personality FROM client_settings')
        settings = cursor.fetchall()
        print('\n⚙️ Client Settings:')
        for setting in settings:
            print(f'  ID: {setting[0]}, User: {setting[1]}, Connection: {setting[2]}, Personality: {setting[3][:50]}...')
        
        conn.close()
    except Exception as e:
        print(f'Error: {e}')
else:
    print('No DATABASE_URL found')
