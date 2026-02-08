"""Webhook routes — Instagram and Stripe webhooks."""
import logging
import threading
from flask import Blueprint, request, jsonify
import json
import os
import time
import hmac
import hashlib
import base64
import requests
import stripe
from config import Config

logger = logging.getLogger("chata.routes.webhook")
from database import get_db_connection, get_param_placeholder
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


# NOTE: @csrf.exempt must be applied to stripe_webhook during blueprint registration
@webhook_bp.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhook events"""
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    
    if not Config.STRIPE_WEBHOOK_SECRET:
        logger.warning("STRIPE_WEBHOOK_SECRET not set. Webhook verification skipped.")
        return jsonify({'status': 'webhook_secret_not_set'}), 200
    
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
    if event_id:
        # Idempotency: skip if we already processed this event (handles retries and out-of-order delivery)
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                placeholder = get_param_placeholder()
                cursor.execute(f"SELECT 1 FROM stripe_webhook_events WHERE event_id = {placeholder}", (event_id,))
                if cursor.fetchone():
                    conn.close()
                    logger.info(f"Webhook event {event_id} already processed, skipping (idempotent)")
                    return jsonify({'status': 'success', 'idempotent': True}), 200
            except Exception as e:
                logger.warning(f"Idempotency check failed: {e}")
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
    
    # Mark event as processed for idempotency (so retries are skipped)
    if event_id:
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                placeholder = get_param_placeholder()
                is_postgres = Config.DATABASE_URL and (Config.DATABASE_URL.startswith("postgres://") or Config.DATABASE_URL.startswith("postgresql://"))
                if is_postgres:
                    cursor.execute(f"INSERT INTO stripe_webhook_events (event_id) VALUES ({placeholder}) ON CONFLICT (event_id) DO NOTHING", (event_id,))
                else:
                    cursor.execute(f"INSERT OR IGNORE INTO stripe_webhook_events (event_id) VALUES ({placeholder})", (event_id,))
                conn.commit()
            except Exception as e:
                logger.warning(f"Failed to store webhook event id: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
    
    logger.info(f"Webhook processing completed for {event['type']}")
    
    return jsonify({'status': 'success'}), 200


# NOTE: @csrf.exempt and @limiter.limit("150 per minute") must be applied to webhook during blueprint registration
@webhook_bp.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        logger.debug(f"Webhook GET request - mode: {mode}, token: {token[:10] if token else 'None'}...")
        if mode == "subscribe" and token == Config.VERIFY_TOKEN:
            logger.info("WEBHOOK VERIFIED!")
            return challenge, 200
        else:
            logger.error(f"Webhook verification failed - mode: {mode}, token match: {token == Config.VERIFY_TOKEN}")
            return "Forbidden", 403

    elif request.method == "POST":
        # Single canonical raw body for signature verification (Meta: hash exact bytes received; see research PDF).
        # request.get_data(cache=True) reads once and caches; our middleware may have already read wsgi.input
        # and replaced it with BytesIO(body), in which case get_data() returns the same bytes.
        raw_body = request.get_data(cache=True)
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        body_source = "middleware" if request.environ.get("chata.webhook_raw_body") is not None else "get_data"
        content_encoding = request.headers.get("Content-Encoding", "") or "(none)"
        # Safe diagnostic: no secrets logged; Content-Encoding helps spot proxy decompression (Facebook may send gzip, we must verify same bytes they signed)
        logger.debug(f"Webhook signature check: body_len={len(raw_body) if raw_body else 0} has_sig={bool(sig_header)} body_source={body_source} Content-Encoding={content_encoding!r}")
        if not raw_body:
            logger.warning("Webhook raw body is empty - signature will fail (body may have been read elsewhere)")
        # Signature verification: see config.py SKIP_INSTAGRAM_WEBHOOK_SIGNATURE_VERIFICATION and
        # WEBHOOK_SIGNATURE_IMPLEMENTATION_NOTES.md (single canonical raw body, no parse before verify).
        if Config.SKIP_INSTAGRAM_WEBHOOK_SIGNATURE_VERIFICATION:
            _sig_ok = True
        else:
            # #region agent log
            _sig_ok = bool(Config.FACEBOOK_APP_SECRET and _verify_instagram_webhook_signature(raw_body, sig_header))
            if not Config.FACEBOOK_APP_SECRET:
                _sig_ok = None
            try:
                _dp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.cursor', 'debug.log')
                with open(_dp, 'a', encoding='utf-8') as _f:
                    _f.write(json.dumps({"hypothesisId": "H2", "message": "webhook_signature", "data": {"signature_verified": _sig_ok, "has_header": bool(sig_header)}, "timestamp": int(time.time() * 1000), "sessionId": "debug-session"}) + "\n")
            except Exception:
                pass
            # #endregion
            if Config.FACEBOOK_APP_SECRET:
                if not _sig_ok and raw_body:
                    # Fallback: proxy/WSGI may have re-serialized JSON (different whitespace/key order).
                    # Try verifying with compact JSON; Meta often sends compact payloads.
                    try:
                        body_str = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
                        compact_body = json.dumps(json.loads(body_str), separators=(",", ":")).encode("utf-8")
                        if _verify_instagram_webhook_signature(compact_body, sig_header):
                            _sig_ok = True
                            logger.info("Webhook signature verified using compact JSON fallback (raw body bytes differed from Meta's)")
                    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                        pass
                if not _sig_ok:
                    _secret_str = (Config.FACEBOOK_APP_SECRET or "").strip()
                    secret_len = len(_secret_str)
                    _secret = _secret_str.encode("utf-8")
                    _received = sig_header[len("sha256="):].strip() if sig_header.startswith("sha256=") else ""
                    _expected = hmac.new(_secret, raw_body, digestmod=hashlib.sha256).hexdigest()
                    # Body fingerprint: SHA256 of raw body (what we're hashing)
                    body_sha = hashlib.sha256(raw_body).hexdigest() if raw_body else ""
                    # Safe secret hints: compare with Meta App secret (first 2 + last 4 chars only)
                    secret_prefix = _secret_str[:2] if len(_secret_str) >= 2 else ""
                    secret_suffix = _secret_str[-4:] if len(_secret_str) >= 4 else ""
                    logger.error("Webhook signature verification failed")
                    logger.error("Formula: HMAC-SHA256(raw_body, FACEBOOK_APP_SECRET) == X-Hub-Signature-256 (raw body = bytes as received)")
                    logger.error(f"secret_len={secret_len} (expected 32) | secret_prefix={secret_prefix!r} secret_suffix={secret_suffix!r} (compare with Meta Chata app secret)")
                    logger.error(f"body_sha256_preview={body_sha[:16]}... (fingerprint of body we hashed)")
                    logger.error(f"expected_sig_preview={_expected[:12]!r} received_sig_preview={_received[:12]!r}")
                    # Body diagnostics: if something upstream changed the body, we need to see what we actually received
                    logger.error(f"body_len={len(raw_body)} content_encoding={request.headers.get('Content-Encoding', '(none)')!r}")
                    logger.error(f"body_first_80_bytes_hex={raw_body[:80].hex()!r}")
                    logger.error(f"received_sig_full={_received!r}")
                    return "Forbidden", 403
            else:
                logger.warning("FACEBOOK_APP_SECRET not set - skipping webhook signature verification")
        
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
        
        logger.debug(f"Request data: {data}")
        
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
                    logger.info(f"Received a message from {sender_id}: {message_text}")
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
            daemon=True,
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
    
    This function is the *exact same logic* that used to run synchronously inside
    the webhook POST handler.  It opens its own DB connection, processes each
    sender's messages (idempotency check, AI reply, send via API), and closes
    the connection when done.
    
    Runs outside of a Flask request context — only uses module-level imports
    (Config, database helpers, service functions, logger).
    """
    process_start = time.time()
    
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
                    is_pg = Config.DATABASE_URL and (Config.DATABASE_URL.startswith("postgres://") or Config.DATABASE_URL.startswith("postgresql://"))
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
            logger.info(f"[bg] AI generated reply: {reply_text[:50]}...")

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
    
    total_process_time = time.time() - process_start
    logger.info(f"[bg] Background webhook processing completed in {total_process_time:.2f}s")
