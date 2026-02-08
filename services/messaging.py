"""Messaging service — save and retrieve messages and conversations."""
import logging
from database import get_db_connection, get_param_placeholder
from config import Config

logger = logging.getLogger("chata.services.messaging")


def save_message(instagram_user_id, message_text, bot_response, conn=None, instagram_connection_id=None, sent_via_api=True):
    """
    Save a message to the database.
    
    Args:
        instagram_user_id: Instagram user ID (the sender who DMed the page)
        message_text: Message text from user
        bot_response: Bot response text
        conn: Optional database connection to reuse. If None, opens and closes its own connection.
        instagram_connection_id: Optional. Which Instagram connection (page) this message belongs to.
        sent_via_api: If False, reply is saved but not yet sent (App Review manual-send mode). Default True.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    sent_val = True if sent_via_api else False
    if get_param_placeholder() == '?':
        sent_val = 1 if sent_via_api else 0

    try:
        cursor.execute(
            f"INSERT INTO messages (instagram_user_id, instagram_connection_id, message_text, bot_response, sent_via_api) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})",
            (instagram_user_id, instagram_connection_id, message_text, bot_response, sent_val)
        )
        conn.commit()
        logger.info(f"Message saved successfully for Instagram user: {instagram_user_id}")
    except Exception as e:
        err_str = str(e).lower()
        try:
            conn.rollback()
        except Exception:
            pass
        if "infailedsqltransaction" in err_str or "transaction is aborted" in err_str:
            try:
                cursor.execute(
                    f"INSERT INTO messages (instagram_user_id, instagram_connection_id, message_text, bot_response, sent_via_api) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})",
                    (instagram_user_id, instagram_connection_id, message_text, bot_response, sent_val)
                )
                conn.commit()
                logger.info(f"Message saved successfully for Instagram user: {instagram_user_id}")
            except Exception as e2:
                err_str2 = str(e2).lower()
                try:
                    conn.rollback()
                except Exception:
                    pass
                if "instagram_connection_id" in err_str2 and ("does not exist" in err_str2 or "undefinedcolumn" in err_str2):
                    cursor.execute(
                        f"INSERT INTO messages (instagram_user_id, message_text, bot_response, sent_via_api) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})",
                        (instagram_user_id, message_text, bot_response, sent_val)
                    )
                    conn.commit()
                    logger.info(f"Message saved (legacy schema) for Instagram user: {instagram_user_id}")
                else:
                    logger.error(f"Error saving message: {e2}")
                    conn.rollback()
                    raise
        elif "instagram_connection_id" in err_str and ("does not exist" in err_str or "undefinedcolumn" in err_str):
            cursor.execute(
                f"INSERT INTO messages (instagram_user_id, message_text, bot_response, sent_via_api) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})",
                (instagram_user_id, message_text, bot_response, sent_val)
            )
            conn.commit()
            logger.info(f"Message saved (legacy schema) for Instagram user: {instagram_user_id}")
        else:
            logger.error(f"Error saving message: {e}")
            raise
    finally:
        if should_close:
            conn.close()

def get_last_messages(instagram_user_id, n=35, conn=None, instagram_connection_id=None):
    """
    Get conversation history for a specific Instagram user (sender).
    
    Args:
        instagram_user_id: Instagram user ID (the sender)
        n: Number of messages to retrieve (default: 35)
        conn: Optional database connection to reuse. If None, opens and closes its own connection.
        instagram_connection_id: Optional. When set, only messages for this connection are returned.
    
    Returns:
        List of messages in OpenAI format
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        if instagram_connection_id is not None:
            try:
                cursor.execute(
                    f"SELECT message_text, bot_response FROM messages WHERE instagram_user_id = {placeholder} AND instagram_connection_id = {placeholder} ORDER BY id DESC LIMIT {placeholder}",
                    (instagram_user_id, instagram_connection_id, n)
                )
            except Exception as col_err:
                err_str = str(col_err).lower()
                if "instagram_connection_id" in err_str and ("does not exist" in err_str or "undefinedcolumn" in err_str or "infailedsqltransaction" in err_str):
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    cursor.execute(
                        f"SELECT message_text, bot_response FROM messages WHERE instagram_user_id = {placeholder} ORDER BY id DESC LIMIT {placeholder}",
                        (instagram_user_id, n)
                    )
                else:
                    raise
        else:
            cursor.execute(
                f"SELECT message_text, bot_response FROM messages WHERE instagram_user_id = {placeholder} ORDER BY id DESC LIMIT {placeholder}",
                (instagram_user_id, n)
            )
        rows = cursor.fetchall()
        
        # Convert to OpenAI format
        messages = []
        for row in reversed(rows):  # Reverse to get chronological order
            if row[0]:  # message_text
                messages.append({"role": "user", "content": row[0]})
            if row[1]:  # bot_response
                messages.append({"role": "assistant", "content": row[1]})
        
        logger.info(f"Retrieved {len(messages)} messages for Instagram user: {instagram_user_id}")
        return messages
        
    except Exception as e:
        logger.error(f"Error retrieving messages: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return []
    finally:
        if should_close:
            conn.close()


def get_conversation_list(instagram_connection_id, conn=None):
    """
    Get list of conversations (distinct senders) for an Instagram connection.
    Ordered by instagram_user_id (no heavy aggregation). Includes username when cached.
    Returns list of dicts: [{"instagram_user_id": str, "username": str or None}, ...]
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    try:
        # Simple distinct list; join optional username from conversation_senders if table exists
        cursor.execute(
            f"""
            SELECT DISTINCT m.instagram_user_id
            FROM messages m
            WHERE m.instagram_connection_id = {placeholder}
            ORDER BY m.instagram_user_id
            """,
            (instagram_connection_id,)
        )
        user_ids = [row[0] for row in cursor.fetchall()]
        # Try to attach usernames from conversation_senders (may not exist yet)
        result = []
        for uid in user_ids:
            username = None
            try:
                cursor.execute(
                    f"SELECT username FROM conversation_senders WHERE instagram_connection_id = {placeholder} AND instagram_user_id = {placeholder}",
                    (instagram_connection_id, str(uid))
                )
                r = cursor.fetchone()
                if r and r[0]:
                    username = r[0]
            except Exception:
                pass
            result.append({"instagram_user_id": uid, "username": username})
        return result
    except Exception as e:
        logger.error(f"Error getting conversation list: {e}")
        return []
    finally:
        if should_close:
            conn.close()


def get_messages_for_conversation(instagram_connection_id, instagram_user_id, limit=10, offset=0, conn=None):
    """
    Get messages for one conversation (one sender, one connection), chronological order.
    Returns list of dicts: [{"id": int, "message_text": str, "bot_response": str, "created_at": ..., "sent_via_api": bool}, ...]
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    try:
        cursor.execute(
            f"""
            SELECT id, message_text, bot_response, created_at, sent_via_api
            FROM messages
            WHERE instagram_connection_id = {placeholder} AND instagram_user_id = {placeholder}
            ORDER BY id ASC
            LIMIT {placeholder} OFFSET {placeholder}
            """,
            (instagram_connection_id, instagram_user_id, limit, offset)
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            sent = row[4] if len(row) > 4 else True
            if sent is None:
                sent = True
            if hasattr(sent, 'numerator'):  # 0/1 from SQLite
                sent = bool(sent)
            result.append({
                "id": row[0],
                "message_text": row[1] or "",
                "bot_response": row[2] or "",
                "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]) if row[3] else None,
                "sent_via_api": sent,
            })
        return result
    except Exception as e:
        err_str = str(e).lower()
        if "sent_via_api" in err_str and ("does not exist" in err_str or "undefinedcolumn" in err_str or "no such column" in err_str):
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                cursor.execute(
                    f"""
                    SELECT id, message_text, bot_response, created_at
                    FROM messages
                    WHERE instagram_connection_id = {placeholder} AND instagram_user_id = {placeholder}
                    ORDER BY id ASC
                    LIMIT {placeholder} OFFSET {placeholder}
                    """,
                    (instagram_connection_id, instagram_user_id, limit, offset)
                )
                rows = cursor.fetchall()
                return [
                    {
                        "id": row[0],
                        "message_text": row[1] or "",
                        "bot_response": row[2] or "",
                        "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]) if row[3] else None,
                        "sent_via_api": True,
                    }
                    for row in rows
                ]
            except Exception:
                pass
        logger.error(f"Error getting messages for conversation: {e}")
        return []
    finally:
        if should_close:
            conn.close()


def get_conversation_message_count(instagram_connection_id, instagram_user_id, conn=None):
    """Total number of message rows for this conversation (for 'Load more' cap)."""
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    try:
        cursor.execute(
            f"""
            SELECT COUNT(*) FROM messages
            WHERE instagram_connection_id = {placeholder} AND instagram_user_id = {placeholder}
            """,
            (instagram_connection_id, instagram_user_id)
        )
        return cursor.fetchone()[0]
    except Exception as e:
        return 0
    finally:
        if should_close:
            conn.close()
