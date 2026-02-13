"""Webhook routes — Instagram and Stripe webhooks."""
import logging
import threading
from flask import Blueprint, request, jsonify
import json
import os
import time
import requests
import stripe
from config import Config

logger = logging.getLogger("chata.routes.webhook")
from extensions import limiter
from database import get_db_connection, get_param_placeholder, is_postgres
from services.instagram import get_instagram_connection_by_id, get_instagram_connection_by_page_id, upsert_conversation_sender_username, _verify_instagram_webhook_signature
from services.messaging import save_message, get_last_messages
from services.subscription import check_user_reply_limit, increment_reply_count
from services.ai import get_ai_reply_with_connection
from services.activity import get_client_settings
from services.stripe_handlers import (
    handle_checkout_session_completed, handle_subscription_created,
    handle_subscription_updated, handle_subscription_deleted,
    handle_invoice_payment_succeeded, handle_invoice_payment_failed
)

webhook_bp = Blueprint('webhook', __name__)

# Cap concurrent Instagram webhook processors to avoid exhausting DB/connections (Meta will retry)
_WEBHOOK_PROCESSOR_SEMAPHORE = threading.Semaphore(int(os.environ.get("WEBHOOK_PROCESSOR_CONCURRENCY", "20")))


# NOTE: @csrf.exempt must be applied to stripe_webhook during blueprint registration
@webhook_bp.route("/webhook/stripe", methods=["POST"])
@limiter.limit("200 per minute")
def stripe_webhook():
    """Handle Stripe webhook events"""
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    
    if not Config.STRIPE_WEBHOOK_SECRET:
        logger.warning("STRIPE_WEBHOOK_SECRET not set. Rejecting Stripe webhook.")
        return jsonify({'error': 'webhook not configured'}), 503
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, Config.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.warning("Invalid payload")
        return jsonify({'status': 'invalid_payload'}), 400
    except stripe.error.SignatureVerificationError:
        logger.warning("Invalid signature")
        return jsonify({'status': 'invalid_signature'}), 400
    
    event_id = event.get('id')
    # Insert-first idempotency: claim the event before running handlers so retries never run handlers twice
    if event_id:
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                placeholder = get_param_placeholder()
                if is_postgres():
                    cursor.execute(f"INSERT INTO stripe_webhook_events (event_id) VALUES ({placeholder}) ON CONFLICT (event_id) DO NOTHING", (event_id,))
                else:
                    cursor.execute(f"INSERT OR IGNORE INTO stripe_webhook_events (event_id) VALUES ({placeholder})", (event_id,))
                conn.commit()
                if cursor.rowcount == 0:
                    logger.info(f"Webhook event {event_id} already processed, skipping (idempotent)")
                    return jsonify({'status': 'success', 'idempotent': True}), 200
            except Exception as e:
                logger.warning(f"Idempotency insert failed: {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                return jsonify({'error': 'internal error'}), 500
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    # Handle the event
    logger.info(f"Received Stripe webhook: {event['type']}")
    logger.info(f"Event ID: {event.get('id', 'unknown')}")
    
    if event['type'] == 'checkout.session.completed':
        session_obj = event['data']['object']
        logger.info(f"Processing checkout session: {session_obj.get('id')}")
        handle_checkout_session_completed(session_obj)
    
    elif event['type'] == 'customer.subscription.created':
        subscription = event['data']['object']
        logger.info(f"Processing subscription created: {subscription.get('id')}")
        handle_subscription_created(subscription)
    
    elif event['type'] == 'customer.subscription.updated':
        subscription = event['data']['object']
        logger.info(f"Processing subscription updated: {subscription.get('id')}")
        handle_subscription_updated(subscription)
    
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        logger.info(f"Processing subscription deleted: {subscription.get('id')}")
        handle_subscription_deleted(subscription)
    
    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        logger.info(f"Processing invoice payment succeeded: {invoice.get('id')}")
        handle_invoice_payment_succeeded(invoice)
    
    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        logger.info(f"Processing invoice payment failed: {invoice.get('id')}")
        handle_invoice_payment_failed(invoice)
    
    else:
        logger.warning(f"Unhandled webhook event type: {event['type']}")
    
    logger.info(f"Webhook processing completed for {event['type']}")
    return jsonify({'status': 'success'}), 200


# NOTE: @csrf.exempt is applied to webhook_bp in app.py
@webhook_bp.route("/webhook", methods=["GET", "POST"])
@limiter.limit("150 per minute")
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        logger.debug(f"Webhook GET request - mode: {mode}, token present: {bool(token)}")
        if mode == "subscribe" and token == Config.VERIFY_TOKEN:
            logger.info("WEBHOOK VERIFIED!")
            return challenge, 200
        else:
            logger.error("Webhook verification failed - invalid mode or verify token")
            return "Forbidden", 403

    elif request.method == "POST":
        raw_body = request.get_data(cache=True)
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        _webhook_secret = (Config.INSTAGRAM_APP_SECRET or Config.FACEBOOK_APP_SECRET or "").strip()
        if not _webhook_secret:
            logger.warning("Neither INSTAGRAM_APP_SECRET nor FACEBOOK_APP_SECRET set - rejecting webhook")
            return "Forbidden", 403
        if not _verify_instagram_webhook_signature(raw_body, sig_header):
            body_len = len(raw_body) if raw_body else 0
            has_header = bool(sig_header and sig_header.strip())
            header_prefix_ok = sig_header.startswith("sha256=") if sig_header else False
            logger.error(
                "Webhook signature verification failed | body_len=%s has_header=%s header_sha256=%s secret_set=%s",
                body_len, has_header, header_prefix_ok, bool(_webhook_secret),
            )
            return "Forbidden", 403

        logger.info("WEBHOOK RECEIVED POST REQUEST")
        logger.debug(f"Request headers: {dict(request.headers)}")
        logger.debug(f"Request remote address: {request.remote_addr}")
        
        # Parse JSON data (body already read; get_json uses cached body)
        try:
            data = request.get_json(silent=True) or (json.loads(raw_body) if raw_body else None)
            if not data:
                logger.warning("No JSON data in request")
                return "Bad Request", 400
        except Exception as e:
            logger.error(f"Error parsing JSON: {e}")
            return "Bad Request", 400
        
        logger.debug("Webhook POST body received (payload not logged)")
        
        # Build list of processable messages (non-echo, with text) before opening DB.
        # Echo-only or empty payloads return 200 without opening DB (Issue 2).
        incoming_by_sender = {}
        if 'entry' in data:
            for entry in data['entry']:
                if 'messaging' not in entry:
                    continue
                entry_page_id = entry.get('id')
                for event in entry['messaging']:
                    if event.get('message', {}).get('is_echo'):
                        continue
                    message_payload = event.get('message', {})
                    message_text = message_payload.get('text')
                    if not message_text:
                        continue
                    sender_id = event['sender']['id']
                    recipient_id = event.get('recipient', {}).get('id')
                    logger.info(f"Received a message from {sender_id} (length={len(message_text)})")
                    incoming_by_sender.setdefault(sender_id, []).append({
                        "text": message_text,
                        "timestamp": event.get('timestamp', 0),
                        "recipient_id": recipient_id,
                        "page_id": entry_page_id,
                        "mid": message_payload.get('mid'),
                    })
        if not incoming_by_sender:
            logger.info("No processable messages (echo-only or no text). Skipping DB.")
            return "EVENT_RECEIVED", 200
        
        # ── Respond to Instagram immediately, process messages in background ──
        # Instagram expects a 200 within 20 seconds.  The heavy work (DB lookups,
        # OpenAI call, sending the reply) can take 5-15 s, so we offload it to a
        # daemon thread and return right away.  The idempotency claim (P1-8) inside
        # _process_incoming_messages guards against duplicate processing if Instagram
        # retries before the thread finishes.
        thread = threading.Thread(
            target=_process_incoming_messages,
            args=(incoming_by_sender,),
            daemon=False,
            name="webhook-processor",
        )
        thread.start()
        logger.info(f"Dispatched {len(incoming_by_sender)} sender batch(es) to background thread")

        return "EVENT_RECEIVED", 200


# ---------------------------------------------------------------------------
# Background webhook processing (runs in a daemon thread)
# ---------------------------------------------------------------------------

def _process_incoming_messages(incoming_by_sender):
    """
    Process incoming Instagram messages in a background thread.
    Concurrency is capped by _WEBHOOK_PROCESSOR_SEMAPHORE so we don't exhaust DB connections.
    """
    process_start = time.time()
    _WEBHOOK_PROCESSOR_SEMAPHORE.acquire()
    try:
        _process_incoming_messages_impl(incoming_by_sender)
    finally:
        _WEBHOOK_PROCESSOR_SEMAPHORE.release()
    logger.info(f"[bg] Background webhook processing completed in {time.time() - process_start:.2f}s")


def _process_incoming_messages_impl(incoming_by_sender):
    """Actual webhook processing (called with semaphore held)."""
    # Open ONE database connection for the entire processing
    webhook_conn = get_db_connection()
    if not webhook_conn:
        logger.error("[bg] Could not connect to database — messages will be retried by Instagram")
        return
    
    try:
        cursor = webhook_conn.cursor()

        for sender_id, events in incoming_by_sender.items():
            events.sort(key=lambda item: item.get("timestamp", 0))
            combined_preview = " | ".join(evt["text"] for evt in events)
            logger.info(f"[bg] Aggregated {len(events)} incoming message(s) from {sender_id}: {combined_preview}")

            latest_event = events[-1]
            recipient_id = latest_event.get("recipient_id")
            entry_page_id = latest_event.get("page_id")
            message_mid = latest_event.get("mid")

            # Idempotency: atomically claim this message mid using INSERT ... ON CONFLICT.
            # This eliminates the TOCTOU race where two concurrent retries both pass a SELECT check.
            if message_mid:
                placeholder = get_param_placeholder()
                try:
                    is_pg = is_postgres()
                    if is_pg:
                        cursor.execute(
                            f"INSERT INTO instagram_webhook_processed_mids (mid) VALUES ({placeholder}) ON CONFLICT (mid) DO NOTHING",
                            (message_mid,)
                        )
                    else:
                        cursor.execute(
                            f"INSERT OR IGNORE INTO instagram_webhook_processed_mids (mid) VALUES ({placeholder})",
                            (message_mid,)
                        )
                    webhook_conn.commit()
                    if cursor.rowcount == 0:
                        # Row already existed — another worker already claimed this mid
                        logger.info(f"[bg] Message mid={message_mid[:20]}... already processed, skipping (idempotent)")
                        continue
                except Exception as e:
                    logger.warning(f"[bg] Mid idempotency claim failed: {e}")
                    try:
                        webhook_conn.rollback()
                    except Exception:
                        pass
                    # If table is missing, create it so future requests have idempotency
                    err_str = str(e).lower()
                    if "does not exist" in err_str or "relation" in err_str:
                        try:
                            if is_pg:
                                cursor.execute("""
                                    CREATE TABLE IF NOT EXISTS instagram_webhook_processed_mids (
                                        mid VARCHAR(512) PRIMARY KEY,
                                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                    )
                                """)
                            else:
                                cursor.execute("""
                                    CREATE TABLE IF NOT EXISTS instagram_webhook_processed_mids (
                                        mid TEXT PRIMARY KEY,
                                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                    )
                                """)
                            webhook_conn.commit()
                            logger.info("[bg] Created instagram_webhook_processed_mids table (was missing)")
                        except Exception as e2:
                            logger.warning(f"[bg] Could not create instagram_webhook_processed_mids table: {e2}")
                            try:
                                webhook_conn.rollback()
                            except Exception:
                                pass
                    # Proceed without mid idempotency for this request

            logger.info(f"[bg] Message batch targeted Instagram account: {recipient_id}")
            logger.info(f"[bg] Page ID from entry: {entry_page_id}")

            instagram_connection = None
            if recipient_id:
                logger.debug(f"[bg] Looking for Instagram connection with user ID: {recipient_id}")
                instagram_connection = get_instagram_connection_by_id(recipient_id, webhook_conn)
                if instagram_connection:
                    logger.info("[bg] Found connection by Instagram User ID!")
                else:
                    logger.warning(f"[bg] No connection found with Instagram User ID: {recipient_id}")

            if not instagram_connection and entry_page_id:
                logger.debug(f"[bg] Trying to find connection by page ID: {entry_page_id}")
                instagram_connection = get_instagram_connection_by_page_id(entry_page_id, webhook_conn)
                if instagram_connection:
                    logger.info("[bg] Found connection by Page ID!")
                else:
                    logger.warning(f"[bg] No connection found with Page ID: {entry_page_id}")

            if not instagram_connection:
                logger.warning(f"[bg] No Instagram connection found for account {recipient_id} or page {entry_page_id}")
                logger.info("[bg] This might be the original Chata account or an unregistered account")
                if recipient_id == Config.INSTAGRAM_USER_ID:
                    logger.info("[bg] This is the original Chata account - using hardcoded settings")
                    access_token = Config.ACCESS_TOKEN
                    instagram_user_id = Config.INSTAGRAM_USER_ID
                    connection_id = None
                    user_id = None  # No user_id for original Chata account
                else:
                    logger.error(f"[bg] Unknown Instagram account {recipient_id} - skipping message batch")
                    continue
            else:
                _safe = {k: instagram_connection[k] for k in ('id', 'user_id', 'instagram_user_id', 'instagram_page_id', 'is_active') if k in instagram_connection}
                logger.info(f"[bg] Found Instagram connection: {_safe}")
                access_token = instagram_connection['page_access_token']
                instagram_user_id = instagram_connection['instagram_user_id']
                connection_id = instagram_connection['id']
                user_id = instagram_connection['user_id']

            handler_start = time.time()
            
            # Check if bot is paused (only for registered users)
            if instagram_connection and user_id:
                placeholder_check = get_param_placeholder()
                try:
                    cursor.execute(f"""
                        SELECT COALESCE(bot_paused, FALSE) FROM users WHERE id = {placeholder_check}
                    """, (user_id,))
                    pause_result = cursor.fetchone()
                    if pause_result and pause_result[0]:
                        logger.info(f"[bg] Bot is paused for user {user_id}. Skipping reply.")
                        total_duration = time.time() - handler_start
                        logger.info(f"[bg] Total webhook handling time for {sender_id}: {total_duration:.2f}s")
                        continue
                except Exception as e:
                    logger.warning(f"[bg] Error checking bot pause status: {e}")
            
            for event in events:
                save_message(sender_id, event["text"], "", webhook_conn, instagram_connection_id=connection_id)
            logger.info(f"[bg] Saved {len(events)} user message(s) for {sender_id}")

            # Update last webhook timestamp/type for Meta app review temporary UI (pages_manage_metadata)
            if connection_id is not None:
                try:
                    ph = get_param_placeholder()
                    cursor.execute(
                        f"UPDATE instagram_connections SET last_webhook_at = CURRENT_TIMESTAMP, last_webhook_event_type = {ph} WHERE id = {ph}",
                        ("message", connection_id)
                    )
                    webhook_conn.commit()
                except Exception as e:
                    logger.warning(f"[bg] Could not update last_webhook_at: {e}")

            # Ensure sender username is stored for Conversation History (e.g. professional accounts)
            if instagram_connection and connection_id and access_token:
                try:
                    ph = get_param_placeholder()
                    cursor.execute(
                        f"SELECT username FROM conversation_senders WHERE instagram_connection_id = {ph} AND instagram_user_id = {ph}",
                        (connection_id, str(sender_id))
                    )
                    row = cursor.fetchone()
                    if not row or not row[0]:
                        url = f"https://graph.facebook.com/v18.0/{sender_id}?fields=username&access_token={access_token}"
                        r = requests.get(url, timeout=5)
                        if r.status_code == 200:
                            api_data = r.json()
                            uname = (api_data.get("username") or "").strip().lower()
                            if uname:
                                upsert_conversation_sender_username(connection_id, sender_id, uname, webhook_conn)
                except Exception as e:
                    logger.warning(f"[bg] Error fetching/saving sender username for conversation list: {e}")

            # Check reply limit before generating response (only for registered users)
            if instagram_connection and user_id:
                has_limit, remaining, total_used, total_available = check_user_reply_limit(user_id, webhook_conn)
                if not has_limit:
                    logger.warning(f"[bg] User {user_id} has reached reply limit ({total_used}/{total_available}). Skipping reply.")
                    total_duration = time.time() - handler_start
                    logger.info(f"[bg] Total webhook handling time for {sender_id}: {total_duration:.2f}s")
                    continue
                else:
                    logger.info(f"[bg] User {user_id} has {remaining} replies remaining ({total_used}/{total_available})")

            # Check if sender is blocked (only for registered users)
            if instagram_connection and user_id and connection_id:
                try:
                    # Get blocked users from settings
                    client_settings = get_client_settings(user_id, connection_id, webhook_conn)
                    blocked_users = client_settings.get('blocked_users', [])
                    
                    if blocked_users:
                        # Get sender's username from Instagram API
                        try:
                            url = f"https://graph.facebook.com/v18.0/{sender_id}?fields=username&access_token={access_token}"
                            response = requests.get(url, timeout=5)
                            if response.status_code == 200:
                                sender_data = response.json()
                                sender_username = sender_data.get('username', '').lower() if sender_data.get('username') else None
                                
                                if sender_username and sender_username in blocked_users:
                                    logger.info(f"[bg] Sender {sender_username} is in blocked users list. Skipping reply.")
                                    total_duration = time.time() - handler_start
                                    logger.info(f"[bg] Total webhook handling time for {sender_id}: {total_duration:.2f}s")
                                    continue
                                else:
                                    logger.debug(f"[bg] Sender {sender_username} is not blocked. Proceeding with reply.")
                                if sender_username:
                                    upsert_conversation_sender_username(connection_id, sender_id, sender_username, webhook_conn)
                            else:
                                logger.warning(f"[bg] Could not fetch sender username (status {response.status_code}), proceeding anyway")
                        except Exception as e:
                            logger.warning(f"[bg] Error checking if sender is blocked: {e}. Proceeding with reply.")
                except Exception as e:
                    logger.warning(f"[bg] Error getting client settings for blocked users check: {e}. Proceeding with reply.")

            history = get_last_messages(sender_id, 35, webhook_conn, instagram_connection_id=connection_id)
            logger.info(f"[bg] History for {sender_id}: {len(history)} messages")

            ai_start = time.time()
            reply_text = get_ai_reply_with_connection(history, connection_id, webhook_conn)
            ai_duration = time.time() - ai_start
            logger.info(f"[bg] AI reply generation time: {ai_duration:.2f}s")
            logger.info(f"[bg] AI generated reply (length={len(reply_text)})")

            app_review_manual_send = getattr(Config, 'APP_REVIEW_MANUAL_SEND', False)
            save_message(sender_id, "", reply_text, webhook_conn, instagram_connection_id=connection_id, sent_via_api=not app_review_manual_send)
            logger.info(f"[bg] Saved bot response for {sender_id}" + (" (pending approval in Conversation History)" if app_review_manual_send else ""))

            if app_review_manual_send:
                # App Review mode: do not send via API; user will click Send in Conversation History
                pass
            else:
                page_id_for_send = instagram_connection['instagram_page_id'] if instagram_connection else Config.INSTAGRAM_USER_ID
                url = f"https://graph.facebook.com/v18.0/{page_id_for_send}/messages?access_token={access_token}"
                payload = {
                    "recipient": {"id": sender_id},
                    "message": {"text": reply_text}
                }

                send_start = time.time()
                r = requests.post(url, json=payload, timeout=45)
                send_duration = time.time() - send_start
                logger.info(f"[bg] Sent reply to {sender_id} via {instagram_user_id}: {r.status_code} (send time {send_duration:.2f}s)")
                if r.status_code != 200:
                    logger.error(f"[bg] Error sending reply: {r.text}")
                else:
                    logger.info(f"[bg] Reply sent successfully to {sender_id}")
                    # Mid already claimed at the top of the loop (atomic idempotency).
                    # Increment reply count only for registered users and only on successful send
                    if instagram_connection and user_id:
                        increment_reply_count(user_id, webhook_conn)
                
            total_duration = time.time() - handler_start
            logger.info(f"[bg] Total webhook handling time for {sender_id}: {total_duration:.2f}s")

    except Exception as e:
        # Catch-all: errors in background threads are silent unless we log them
        logger.error(f"[bg] Unhandled error processing webhook messages: {e}", exc_info=True)
    finally:
        # Close the shared connection at the end
        if webhook_conn:
            try:
                webhook_conn.close()
            except Exception:
                pass
            logger.debug("[bg] Closed webhook database connection")
