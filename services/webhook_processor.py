"""Background processing for Instagram webhook messages."""
import logging
import time
import requests

from config import Config
from database import get_db_connection, get_param_placeholder, is_postgres
from services.ai import get_ai_reply_with_connection
from services.activity import get_client_settings
from services.instagram import (
    get_instagram_connection_by_id,
    get_instagram_connection_by_page_id,
    upsert_conversation_sender_username,
)
from services.messaging import get_last_messages, save_message
from services.subscription import check_user_reply_limit, increment_reply_count
from services.rate_controls import allow_sender_message, allow_user_openai

logger = logging.getLogger("chata.services.webhook_processor")


def _claim_message_mid(cursor, conn, mid):
    if not mid:
        return True
    ph = get_param_placeholder()
    if is_postgres():
        cursor.execute(
            f"INSERT INTO instagram_webhook_processed_mids (mid) VALUES ({ph}) ON CONFLICT (mid) DO NOTHING",
            (mid,),
        )
    else:
        cursor.execute(
            f"INSERT OR IGNORE INTO instagram_webhook_processed_mids (mid) VALUES ({ph})",
            (mid,),
        )
    conn.commit()
    return cursor.rowcount > 0


def process_incoming_messages(incoming_by_sender):
    """Main background processing workflow."""
    webhook_conn = get_db_connection()
    if not webhook_conn:
        raise RuntimeError("Database connection unavailable for webhook processing")

    try:
        cursor = webhook_conn.cursor()
        for sender_id, events in incoming_by_sender.items():
            if not allow_sender_message(sender_id):
                logger.warning(f"[worker] sender throttled sender={sender_id}")
                continue
            events.sort(key=lambda item: item.get("timestamp", 0))
            latest_event = events[-1]
            recipient_id = latest_event.get("recipient_id")
            entry_page_id = latest_event.get("page_id")
            message_mid = latest_event.get("mid")

            if message_mid and not _claim_message_mid(cursor, webhook_conn, message_mid):
                logger.info(f"[worker] mid={message_mid[:20]} already processed; skipping")
                continue

            instagram_connection = None
            if recipient_id:
                instagram_connection = get_instagram_connection_by_id(recipient_id, webhook_conn)
            if not instagram_connection and entry_page_id:
                instagram_connection = get_instagram_connection_by_page_id(entry_page_id, webhook_conn)

            if not instagram_connection:
                if recipient_id == Config.INSTAGRAM_USER_ID:
                    access_token = Config.ACCESS_TOKEN
                    connection_id = None
                    user_id = None
                    page_id_for_send = Config.INSTAGRAM_USER_ID
                else:
                    logger.warning(f"[worker] unknown instagram destination recipient={recipient_id} page={entry_page_id}")
                    continue
            else:
                access_token = instagram_connection.get("page_access_token")
                connection_id = instagram_connection.get("id")
                user_id = instagram_connection.get("user_id")
                page_id_for_send = instagram_connection.get("instagram_page_id")

            if not access_token or not page_id_for_send:
                logger.warning(f"[worker] missing send credentials for sender={sender_id}, connection={connection_id}")
                continue

            for event in events:
                save_message(sender_id, event["text"], "", webhook_conn, instagram_connection_id=connection_id)

            if user_id:
                ph = get_param_placeholder()
                cursor.execute(f"SELECT COALESCE(bot_paused, FALSE) FROM users WHERE id = {ph}", (user_id,))
                pause_row = cursor.fetchone()
                if pause_row and pause_row[0]:
                    logger.info(f"[worker] bot paused user={user_id}; skipping")
                    continue

                has_limit, remaining, _, _ = check_user_reply_limit(user_id, webhook_conn)
                if not has_limit:
                    logger.warning(f"[worker] quota exceeded user={user_id}")
                    continue
                logger.info(f"[worker] user={user_id} remaining_replies={remaining}")

            if connection_id:
                client_settings = get_client_settings(user_id, connection_id, webhook_conn)
                blocked_users = set(client_settings.get("blocked_users") or [])
                try:
                    url = f"https://graph.facebook.com/v18.0/{sender_id}?fields=username&access_token={access_token}"
                    profile_resp = requests.get(url, timeout=5)
                    if profile_resp.status_code == 200:
                        sender_username = (profile_resp.json().get("username") or "").lower()
                        if sender_username:
                            upsert_conversation_sender_username(connection_id, sender_id, sender_username, webhook_conn)
                        if sender_username in blocked_users:
                            logger.info(f"[worker] blocked sender username={sender_username}; skipping")
                            continue
                except Exception as sender_error:
                    logger.warning(f"[worker] sender profile check failed: {sender_error}")

            history = get_last_messages(sender_id, 35, webhook_conn, instagram_connection_id=connection_id)
            if user_id and not allow_user_openai(user_id):
                logger.warning(f"[worker] user openai throttled user={user_id}")
                continue
            ai_start = time.time()
            reply_text = get_ai_reply_with_connection(history, connection_id, webhook_conn)
            logger.info(f"[worker] ai_generation_seconds={time.time() - ai_start:.2f}")
            if not reply_text:
                logger.warning("[worker] ai generation failed or budget blocked; no reply sent")
                continue

            app_review_manual_send = getattr(Config, "APP_REVIEW_MANUAL_SEND", False)
            save_message(
                sender_id,
                "",
                reply_text,
                webhook_conn,
                instagram_connection_id=connection_id,
                sent_via_api=not app_review_manual_send,
            )
            if app_review_manual_send:
                continue

            payload = {"recipient": {"id": sender_id}, "message": {"text": reply_text}}
            send_url = f"https://graph.facebook.com/v18.0/{page_id_for_send}/messages?access_token={access_token}"
            send_resp = requests.post(send_url, json=payload, timeout=30)
            if send_resp.status_code != 200:
                logger.error(f"[worker] failed sending message sender={sender_id} code={send_resp.status_code}")
                continue
            if user_id:
                increment_reply_count(user_id, webhook_conn)
    finally:
        try:
            webhook_conn.close()
        except Exception:
            pass
