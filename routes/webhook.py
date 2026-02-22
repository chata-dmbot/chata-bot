"""Webhook routes — Instagram and Stripe webhooks."""
import logging
import json
import stripe
from flask import Blueprint, request, jsonify

from config import Config
from extensions import limiter
from database import get_db_connection, get_param_placeholder, is_postgres
from services.instagram import _verify_instagram_webhook_signature
from services.stripe_handlers import (
    handle_checkout_session_completed, handle_subscription_created,
    handle_subscription_updated, handle_subscription_deleted,
    handle_invoice_payment_succeeded, handle_invoice_payment_failed
)
from jobs.queue import enqueue_incoming_messages

logger = logging.getLogger("chata.routes.webhook")

webhook_bp = Blueprint('webhook', __name__)


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
        # Meta signs webhooks with the app's main App Secret; use FACEBOOK_APP_SECRET first so verification matches.
        _webhook_secret = (Config.FACEBOOK_APP_SECRET or Config.INSTAGRAM_APP_SECRET or "").strip()
        if not _webhook_secret:
            logger.warning("Neither FACEBOOK_APP_SECRET nor INSTAGRAM_APP_SECRET set - rejecting webhook")
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
        
        # Enqueue to Redis/RQ for background processing by the worker.
        # Instagram expects 200 within 20 seconds; the heavy work (DB, OpenAI, send)
        # happens in the RQ worker process with automatic retries.
        try:
            job_id = enqueue_incoming_messages(incoming_by_sender)
            logger.info(f"Webhook enqueued sender_batches={len(incoming_by_sender)} job_id={job_id}")
        except Exception as e:
            logger.error(f"Failed to enqueue webhook job, falling back to sync processing: {e}")
            try:
                from services.webhook_processor import process_incoming_messages
                process_incoming_messages(incoming_by_sender)
                logger.info("Webhook processed synchronously (Redis fallback)")
            except Exception as sync_err:
                logger.error(f"Synchronous fallback also failed: {sync_err}")

        return "EVENT_RECEIVED", 200
