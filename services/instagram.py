"""Instagram service — API helpers for Instagram/Meta Graph API."""
import base64
import hashlib
import hmac
import logging

import requests

from config import Config
from database import get_db_connection, get_param_placeholder

logger = logging.getLogger("chata.services.instagram")


def upsert_conversation_sender_username(instagram_connection_id, instagram_user_id, username, conn=None):
    """Store or update sender username for conversation history search (called from webhook when we have it)."""
    if not username or not instagram_connection_id:
        return
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    try:
        cursor.execute(
            f"INSERT INTO conversation_senders (instagram_connection_id, instagram_user_id, username) VALUES ({placeholder}, {placeholder}, {placeholder})",
            (instagram_connection_id, str(instagram_user_id), username)
        )
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        err = str(e).lower()
        if "unique" in err or "duplicate" in err or "constraint" in err:
            try:
                cursor.execute(
                    f"UPDATE conversation_senders SET username = {placeholder} WHERE instagram_connection_id = {placeholder} AND instagram_user_id = {placeholder}",
                    (username, instagram_connection_id, str(instagram_user_id))
                )
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
    finally:
        if should_close:
            conn.close()


def discover_instagram_user_id(page_access_token, page_id):
    """
    Discover the correct Instagram User ID from a Facebook Page using the Page Access Token.
    This is the proper way to get the Instagram User ID that works with the messaging API.
    """
    try:
        logger.info(f"Discovering Instagram User ID for Page ID: {page_id}")
        
        # First, get the Instagram Business Account ID from the Page
        url = f"https://graph.facebook.com/v18.0/{page_id}?fields=instagram_business_account&access_token={page_access_token}"
        response = requests.get(url)
        
        if response.status_code != 200:
            logger.error(f"Failed to get Instagram Business Account: {response.text}")
            return None
            
        data = response.json()
        if 'instagram_business_account' not in data:
            logger.error(f"No Instagram Business Account found for Page {page_id}")
            return None
            
        instagram_business_account_id = data['instagram_business_account']['id']
        logger.info(f"Found Instagram Business Account ID: {instagram_business_account_id}")
        
        # Now get the Instagram User ID from the Business Account
        # This is the ID that works with the messaging API
        url = f"https://graph.facebook.com/v18.0/{instagram_business_account_id}?fields=id,username&access_token={page_access_token}"
        response = requests.get(url)
        
        if response.status_code != 200:
            logger.error(f"Failed to get Instagram User details: {response.text}")
            return None
            
        data = response.json()
        instagram_user_id = data['id']
        username = data.get('username', 'Unknown')
        
        logger.info(f"Discovered Instagram User ID: {instagram_user_id} (Username: {username})")
        return instagram_user_id
        
    except Exception as e:
        logger.error(f"Error discovering Instagram User ID: {e}")
        return None


def get_instagram_connection_by_id(instagram_user_id, conn=None):
    """
    Get Instagram connection by Instagram user ID.
    
    Args:
        instagram_user_id: Instagram user ID
        conn: Optional database connection to reuse. If None, opens and closes its own connection.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        cursor.execute(f"""
            SELECT id, user_id, instagram_user_id, instagram_page_id, instagram_username, instagram_page_name, page_access_token, is_active
            FROM instagram_connections 
            WHERE instagram_user_id = {placeholder} AND is_active = TRUE
        """, (instagram_user_id,))
        
        row = cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'user_id': row[1],
                'instagram_user_id': row[2],
                'instagram_page_id': row[3],
                'instagram_username': row[4],
                'instagram_page_name': row[5],
                'page_access_token': row[6],
                'is_active': row[7]
            }
        return None
    except Exception as e:
        logger.error(f"Error getting Instagram connection: {e}")
        return None
    finally:
        if should_close:
            conn.close()


def get_instagram_connection_by_page_id(page_id, conn=None):
    """
    Get Instagram connection by Instagram page ID.
    
    Args:
        page_id: Instagram page ID
        conn: Optional database connection to reuse. If None, opens and closes its own connection.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        cursor.execute(f"""
            SELECT id, user_id, instagram_user_id, instagram_page_id, instagram_username, instagram_page_name, page_access_token, is_active
            FROM instagram_connections 
            WHERE instagram_page_id = {placeholder} AND is_active = TRUE
        """, (page_id,))
        
        row = cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'user_id': row[1],
                'instagram_user_id': row[2],
                'instagram_page_id': row[3],
                'instagram_username': row[4],
                'instagram_page_name': row[5],
                'page_access_token': row[6],
                'is_active': row[7]
            }
        return None
    except Exception as e:
        logger.error(f"Error getting Instagram connection by page ID: {e}")
        return None
    finally:
        if should_close:
            conn.close()


def _verify_instagram_webhook_signature(raw_body, signature_header):
    """Verify X-Hub-Signature-256 (HMAC SHA256 of raw body with app secret). Returns True if valid or header missing/empty.
    Uses INSTAGRAM_APP_SECRET if set, otherwise FACEBOOK_APP_SECRET (so you can test Instagram secret without changing OAuth)."""
    if not signature_header or not raw_body:
        return False
    # Prefer Instagram app secret for webhook if set; else Facebook app secret. Strip env vars (trailing newline when pasted).
    secret = (Config.INSTAGRAM_APP_SECRET or Config.FACEBOOK_APP_SECRET or "").strip().encode("utf-8")
    if not secret:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    received = signature_header[len(prefix):].strip()
    expected = hmac.new(secret, raw_body, digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)
