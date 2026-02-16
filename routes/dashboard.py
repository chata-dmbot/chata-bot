"""Dashboard routes — user dashboard, settings, conversation history."""
import logging
import time
from flask import Blueprint, request, render_template, redirect, url_for, flash, session, jsonify

logger = logging.getLogger("chata.routes.dashboard")
import requests
import json
import stripe  # type: ignore[reportMissingImports]
from config import Config
from database import get_db_connection, get_param_placeholder, is_postgres
from extensions import csrf
from services.auth import login_required
from services.users import get_user_by_id
from services.messaging import get_conversation_list, get_messages_for_conversation, get_conversation_message_count
from services.subscription import check_user_reply_limit, reset_monthly_replies_if_needed, increment_reply_count
from services.activity import log_activity, get_client_settings, save_client_settings
from services.email import send_account_deletion_confirmation_email

dashboard_bp = Blueprint('dashboard_bp', __name__)

# Throttle Stripe reconciliation: avoid calling Stripe on every dashboard load (cache 5 min)
_STRIPE_STATUS_CACHE_TTL = 300  # seconds
_stripe_status_cache = {}  # (user_id, sub_id) -> (stripe_status, cached_at)


# ---------------------------------------------------------------------------
# Dashboard home
# ---------------------------------------------------------------------------

@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    # Normal user flow
    user = get_user_by_id(session['user_id'])
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    user_id = user['id']
    
    # Check and reset monthly counter if needed
    check_user_reply_limit(user_id)
    
    # Get user's Instagram connections
    conn = get_db_connection()
    if not conn:
        flash("Database error. Please try again.", "error")
        return redirect(url_for('auth.login'))
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"""
            SELECT id, instagram_user_id, instagram_page_id, instagram_username, instagram_page_name, is_active, created_at,
                   COALESCE(webhook_subscription_active, FALSE) as webhook_subscription_active,
                   last_webhook_at, last_webhook_event_type
            FROM instagram_connections 
            WHERE user_id = {placeholder} 
            ORDER BY created_at DESC
        """, (user_id,))
        connections = cursor.fetchall()
    
        # Get user's reply counts, bot_paused status, and subscription data in a single query
        # This combines 3 separate queries into 1 for better performance
        cursor.execute(f"""
            SELECT 
                u.replies_sent_monthly, 
                u.replies_limit_monthly, 
                u.replies_purchased, 
                u.replies_used_purchased, 
                COALESCE(u.bot_paused, FALSE) as bot_paused,
                (SELECT plan_type FROM subscriptions WHERE user_id = u.id AND status = 'active' ORDER BY created_at DESC LIMIT 1) as active_plan_type,
                (SELECT status FROM subscriptions WHERE user_id = u.id AND status = 'active' ORDER BY created_at DESC LIMIT 1) as active_status,
                (SELECT stripe_subscription_id FROM subscriptions WHERE user_id = u.id AND status = 'active' ORDER BY created_at DESC LIMIT 1) as active_subscription_id,
                (SELECT plan_type FROM subscriptions WHERE user_id = u.id AND status = 'canceled' ORDER BY updated_at DESC LIMIT 1) as canceled_plan_type,
                (SELECT status FROM subscriptions WHERE user_id = u.id AND status = 'canceled' ORDER BY updated_at DESC LIMIT 1) as canceled_status,
                (SELECT stripe_subscription_id FROM subscriptions WHERE user_id = u.id AND status = 'canceled' ORDER BY updated_at DESC LIMIT 1) as canceled_subscription_id
            FROM users u
            WHERE u.id = {placeholder}
        """, (user_id,))
        combined_data = cursor.fetchone()
        
        if combined_data:
            replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased, bot_paused, \
            active_plan_type, active_status, active_subscription_id, \
            canceled_plan_type, canceled_status, canceled_subscription_id = combined_data
            
            total_replies_used = replies_sent_monthly + replies_used_purchased
            total_replies_available = replies_limit_monthly + replies_purchased
            remaining_replies = max(0, total_replies_available - total_replies_used)
            MINUTES_PER_REPLY = 3
            minutes_saved = replies_sent_monthly * MINUTES_PER_REPLY
            
            current_plan = None
            subscription_status = None
            
            if active_plan_type is not None and active_status == 'active':
                stripe_status = None
                if active_subscription_id and Config.STRIPE_SECRET_KEY:
                    cache_key = (user_id, active_subscription_id)
                    now = time.time()
                    if cache_key in _stripe_status_cache:
                        cached_status, cached_at = _stripe_status_cache[cache_key]
                        if now - cached_at < _STRIPE_STATUS_CACHE_TTL:
                            stripe_status = cached_status
                    if stripe_status is None:
                        try:
                            sub = stripe.Subscription.retrieve(active_subscription_id)
                            stripe_status = sub.get('status') if isinstance(sub, dict) else getattr(sub, 'status', None)
                            _stripe_status_cache[cache_key] = (stripe_status, now)
                        except Exception as stripe_e:
                            logger.warning(f"Dashboard: Could not reconcile with Stripe: {stripe_e}")
                            stripe_status = None
                    if stripe_status is not None and stripe_status in ('canceled', 'unpaid', 'incomplete_expired'):
                        sync_conn = get_db_connection()
                        if sync_conn:
                            try:
                                sync_cursor = sync_conn.cursor()
                                sync_ph = get_param_placeholder()
                                sync_cursor.execute(f"""
                                    UPDATE subscriptions SET status = {sync_ph}, updated_at = CURRENT_TIMESTAMP
                                    WHERE stripe_subscription_id = {sync_ph}
                                """, ('canceled', active_subscription_id))
                                sync_conn.commit()
                                logger.info(f"Dashboard: Reconciled subscription {active_subscription_id} with Stripe (status={stripe_status}), marked canceled in DB")
                            except Exception as sync_e:
                                logger.warning(f"Dashboard reconciliation update failed: {sync_e}")
                            finally:
                                try:
                                    sync_conn.close()
                                except Exception:
                                    pass
                        subscription_status = 'canceled'
                        current_plan = None
                    else:
                        current_plan = active_plan_type
                        subscription_status = 'active'
                        if stripe_status is not None:
                            logger.info(f"Dashboard: Found ACTIVE subscription {active_subscription_id} with plan_type '{active_plan_type}' (Stripe status={stripe_status})")
                else:
                    current_plan = active_plan_type
                    subscription_status = 'active'
                    logger.info(f"Dashboard: Found ACTIVE subscription {active_subscription_id} with plan_type '{active_plan_type}'")
            elif canceled_plan_type is not None and canceled_status == 'canceled':
                subscription_status = 'canceled'
                current_plan = None
                logger.info(f"Dashboard: Found CANCELED subscription {canceled_subscription_id} - not showing as current plan")
            else:
                logger.info(f"Dashboard: No subscription found for user {user_id}")
        else:
            replies_sent_monthly = 0
            replies_limit_monthly = 0
            replies_purchased = 0
            replies_used_purchased = 0
            total_replies_used = 0
            total_replies_available = 0
            remaining_replies = 0
            minutes_saved = 0
            bot_paused = False
            current_plan = None
            subscription_status = None
    finally:
        conn.close()
    
    connections_list = []
    webhook_status = {'active': False, 'last_webhook_at': None, 'last_webhook_at_str': None, 'last_webhook_event_type': None}
    for conn_data in connections:
        c = {
            'id': conn_data[0],
            'instagram_user_id': conn_data[1],
            'instagram_page_id': conn_data[2],
            'instagram_username': conn_data[3],
            'instagram_page_name': conn_data[4],
            'is_active': conn_data[5],
            'created_at': conn_data[6],
            'webhook_subscription_active': conn_data[7] if len(conn_data) > 7 else False,
            'last_webhook_at': conn_data[8] if len(conn_data) > 8 else None,
            'last_webhook_event_type': conn_data[9] if len(conn_data) > 9 else None,
        }
        connections_list.append(c)
        if c.get('webhook_subscription_active'):
            webhook_status['active'] = True
        if c.get('last_webhook_at'):
            if webhook_status['last_webhook_at'] is None or (c['last_webhook_at'] and c['last_webhook_at'] > webhook_status['last_webhook_at']):
                webhook_status['last_webhook_at'] = c['last_webhook_at']
                webhook_status['last_webhook_event_type'] = c.get('last_webhook_event_type')
    if webhook_status['last_webhook_at']:
        t = webhook_status['last_webhook_at']
        webhook_status['last_webhook_at_str'] = t.strftime('%Y-%m-%d %H:%M:%S') if hasattr(t, 'strftime') else str(t)
    
    return render_template("dashboard.html", 
                         user=user, 
                         connections=connections_list,
                         app_review_manual_send=Config.APP_REVIEW_MANUAL_SEND,
                         webhook_status=webhook_status,
                         replies_sent=replies_sent_monthly,
                         replies_limit=replies_limit_monthly,
                         replies_purchased=replies_purchased,
                         replies_used_purchased=replies_used_purchased,
                         total_replies_used=total_replies_used,
                         total_replies_available=total_replies_available,
                         remaining_replies=remaining_replies,
                         minutes_saved=minutes_saved,
                         current_plan=current_plan,
                         subscription_status=subscription_status,
                         bot_paused=bot_paused)


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

@dashboard_bp.route("/dashboard/conversation-history")
@login_required
def conversation_history():
    """Conversation history page for one Instagram connection: list of conversations, expandable to show messages."""
    connection_id = request.args.get("connection_id", type=int)
    if not connection_id:
        flash("Please select an Instagram connection.", "error")
        return redirect(url_for("dashboard_bp.dashboard"))
    user_id = session["user_id"]
    conn = get_db_connection()
    if not conn:
        flash("Database error. Please try again.", "error")
        return redirect(url_for("dashboard_bp.dashboard"))
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(
            f"SELECT id, instagram_page_name, instagram_username FROM instagram_connections WHERE id = {placeholder} AND user_id = {placeholder}",
            (connection_id, user_id)
        )
        row = cursor.fetchone()
        if not row:
            flash("Instagram connection not found.", "error")
            return redirect(url_for("dashboard_bp.dashboard"))
        connection_name = row[2] or row[1] or "Instagram"  # Instagram username first, then page name
        conversations = get_conversation_list(connection_id, conn)
    finally:
        conn.close()
    return render_template(
        "conversation_history.html",
        connection_id=connection_id,
        connection_name=connection_name,
        conversations=conversations,
    )


@dashboard_bp.route("/api/conversation-history/<int:connection_id>/<instagram_user_id>/messages")
@login_required
def api_conversation_messages(connection_id, instagram_user_id):
    """Return JSON list of messages for one conversation (for expandable dropdown)."""
    user_id = session["user_id"]
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database error"}), 500
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(
            f"SELECT 1 FROM instagram_connections WHERE id = {placeholder} AND user_id = {placeholder}",
            (connection_id, user_id)
        )
        if not cursor.fetchone():
            return jsonify({"error": "Connection not found"}), 404
        try:
            limit = min(max(1, int(request.args.get("limit", 10))), 50)
        except (ValueError, TypeError):
            limit = 10
        try:
            offset = max(0, min(int(request.args.get("offset", 0)), 1000))
        except (ValueError, TypeError):
            offset = 0
        messages = get_messages_for_conversation(connection_id, instagram_user_id, limit=limit, offset=offset, conn=conn)
        total = get_conversation_message_count(connection_id, instagram_user_id, conn=conn)
        return jsonify({"messages": messages, "total": total})
    finally:
        conn.close()


@dashboard_bp.route("/api/conversation-history/<int:connection_id>/<instagram_user_id>/send-pending", methods=["POST"])
@login_required
@csrf.exempt
def api_send_pending_reply(connection_id, instagram_user_id):
    """Send a pending bot reply (App Review manual-send mode). Request body: {"message_id": 123}."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    message_id = data.get("message_id")
    if not message_id:
        return jsonify({"error": "message_id required"}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database error"}), 500
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(
            f"SELECT 1 FROM instagram_connections WHERE id = {placeholder} AND user_id = {placeholder}",
            (connection_id, user_id)
        )
        if not cursor.fetchone():
            return jsonify({"error": "Connection not found"}), 404
        # PostgreSQL: sent_via_api is BOOLEAN (FALSE). SQLite: INTEGER (0).
        is_pg = is_postgres()
        pending_cond = "sent_via_api = FALSE" if is_pg else "(sent_via_api = 0 OR sent_via_api = FALSE)"
        cursor.execute(
            f"SELECT bot_response FROM messages WHERE id = {placeholder} AND instagram_connection_id = {placeholder} AND instagram_user_id = {placeholder} AND {pending_cond}",
            (message_id, connection_id, instagram_user_id)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Pending message not found or already sent"}), 404
        reply_text = row[0] or ""
        if not reply_text:
            return jsonify({"error": "No reply text"}), 400
        cursor.execute(
            f"SELECT page_access_token, instagram_page_id, user_id FROM instagram_connections WHERE id = {placeholder}",
            (connection_id,)
        )
        conn_row = cursor.fetchone()
        if not conn_row:
            return jsonify({"error": "Connection not found"}), 404
        page_access_token, page_id, conn_user_id = conn_row[0], conn_row[1], conn_row[2]
        if not page_id:
            page_id = Config.INSTAGRAM_USER_ID
        url = f"https://graph.facebook.com/v18.0/{page_id}/messages?access_token={page_access_token}"
        payload = {"recipient": {"id": instagram_user_id}, "message": {"text": reply_text}}
        r = requests.post(url, json=payload, timeout=45)
        if r.status_code != 200:
            return jsonify({"error": "Failed to send", "details": r.text}), 502
        ph = get_param_placeholder()
        try:
            cursor.execute(f"UPDATE messages SET sent_via_api = {ph} WHERE id = {ph}", (True if ph == '%s' else 1, message_id))
        except Exception as col_err:
            err_str = str(col_err).lower()
            if "sent_via_api" in err_str and ("no such column" in err_str or "does not exist" in err_str or "undefinedcolumn" in err_str):
                pass
            else:
                raise
        conn.commit()
        if conn_user_id:
            increment_reply_count(conn_user_id, conn)
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error sending pending reply: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"error": "Server error"}), 500
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bot settings
# ---------------------------------------------------------------------------

@dashboard_bp.route("/dashboard/bot-settings", methods=["GET", "POST"])
@login_required
def bot_settings():
    from services.ai import CONVERSATION_EXAMPLES

    user_id = session['user_id']
    connection_id = request.args.get('connection_id', type=int)
    conversation_templates = CONVERSATION_EXAMPLES
    
    if request.method == "POST":
        form_connection_id = request.form.get('connection_id')
        if form_connection_id:
            try:
                connection_id = int(form_connection_id)
            except ValueError:
                connection_id = None

    # Open ONE connection and reuse it for all database operations
    conn = get_db_connection()
    if not conn:
        flash("Database error. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        cursor.execute(f"""
            SELECT id, instagram_user_id, instagram_page_id, instagram_username, instagram_page_name, is_active 
            FROM instagram_connections 
            WHERE user_id = {placeholder} 
            ORDER BY created_at DESC
        """, (user_id,))
        connections = cursor.fetchall()
        
        connections_list = []
        for conn_data in connections:
            connections_list.append({
                'id': conn_data[0],
                'instagram_user_id': conn_data[1],
                'instagram_page_id': conn_data[2],
                'instagram_username': conn_data[3],
                'instagram_page_name': conn_data[4],
                'is_active': conn_data[5]
            })
        
        if not connections_list:
            if request.method == "POST":
                flash("Please connect an Instagram account before configuring bot settings.", "warning")
            return render_template(
                "bot_settings.html",
                settings=None,
                connections=[],
                selected_connection_id=None,
                selected_connection=None,
                conversation_templates=conversation_templates,
            )

        if connection_id is None:
            connection_id = connections_list[0]['id']
        
        current_settings = get_client_settings(user_id, connection_id, conn)
        selected_connection = next((c for c in connections_list if c['id'] == connection_id), None)

        if request.method == "POST":
            link_urls = request.form.getlist('link_urls[]')
            link_titles = request.form.getlist('link_titles[]')
            links = []
            for index, url in enumerate(link_urls):
                if url.strip():
                    title = link_titles[index].strip() if index < len(link_titles) else ""
                    links.append({'url': url.strip(), 'title': title})

            post_descriptions = request.form.getlist('post_descriptions[]')
            posts = []
            for desc in post_descriptions:
                if desc.strip():
                    posts.append({'description': desc.strip()})

            faq_questions = request.form.getlist('faq_questions[]')
            faq_replies = request.form.getlist('faq_replies[]')
            faqs = []
            for i, question in enumerate(faq_questions):
                question = question.strip()
                reply = faq_replies[i].strip() if i < len(faq_replies) else ''
                if question or reply:
                    faqs.append({'question': question, 'reply': reply})

            conversation_samples = {}
            for example in conversation_templates:
                for exchange in example.get('exchanges', []):
                    reply_key = f"{example['key']}_{exchange['bot_reply_key']}"
                    reply_value = request.form.get(f"sample_reply_{reply_key}", "")
                    reply_value = reply_value.strip()
                    if reply_value:
                        conversation_samples[reply_key] = reply_value
                    
                    follower_key = f"{example['key']}_{exchange['bot_reply_key']}_follower"
                    follower_value = request.form.get(f"follower_message_{follower_key}", "")
                    follower_value = follower_value.strip()
                    if follower_value:
                        conversation_samples[follower_key] = follower_value

            settings = {
                'bot_personality': request.form.get('bot_personality', '').strip(),
                'bot_name': request.form.get('bot_name', '').strip(),
                'bot_age': request.form.get('bot_age', '').strip(),
                'bot_gender': request.form.get('bot_gender', '').strip(),
                'bot_location': request.form.get('bot_location', '').strip(),
                'bot_occupation': request.form.get('bot_occupation', '').strip(),
                'links': links,
                'posts': posts,
                'faqs': faqs,
                'conversation_samples': conversation_samples,
                'instagram_url': request.form.get('instagram_url', '').strip(),
                'avoid_topics': request.form.get('avoid_topics', '').strip(),
                'blocked_users': [username.strip().lstrip('@').lower() for username in request.form.get('blocked_users', '').strip().split('\n') if username.strip()] if request.form.get('blocked_users') else []
            }

            save_client_settings(user_id, settings, connection_id, conn)
            log_activity(user_id, 'settings_updated', f'Bot settings updated for connection {connection_id}', conn)
            flash("AI settings updated successfully!", "success")
            return redirect(url_for('dashboard_bp.bot_settings', connection_id=connection_id))

        if current_settings.get('conversation_samples') is None:
            current_settings['conversation_samples'] = {}

    finally:
        conn.close()

    # render_template happens after DB connection is closed — data already fetched
    return render_template(
        "bot_settings.html",
        settings=current_settings, 
        connections=connections_list,
        selected_connection_id=connection_id,
        selected_connection=selected_connection,
        conversation_templates=conversation_templates,
    )


# ---------------------------------------------------------------------------
# Account settings
# ---------------------------------------------------------------------------

@dashboard_bp.route("/dashboard/account-settings", methods=["GET", "POST"])
@login_required
def account_settings():
    user = get_user_by_id(session['user_id'])
    
    if request.method == "POST":
        username = request.form.get('username', '').strip()
        
        if not username:
            flash("Username is required.", "error")
            return redirect(url_for('dashboard_bp.account_settings'))
        
        if len(username) < 3 or len(username) > 30:
            flash("Username must be between 3 and 30 characters.", "error")
            return redirect(url_for('dashboard_bp.account_settings'))
        
        # Check if username contains only allowed characters
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            flash("Username can only contain letters, numbers, and underscores.", "error")
            return redirect(url_for('dashboard_bp.account_settings'))
        
        # Check if username is already taken by another user (case-insensitive)
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            placeholder = get_param_placeholder()
            cursor.execute(f"""
                SELECT id FROM users 
                WHERE LOWER(username) = LOWER({placeholder}) AND id != {placeholder}
            """, (username, user['id']))
            existing_user = cursor.fetchone()
            
            if existing_user:
                flash("This username is already taken. Please choose another.", "error")
                return redirect(url_for('dashboard_bp.account_settings'))
            
            # Update username
            cursor.execute(f"""
                UPDATE users 
                SET username = {placeholder}
                WHERE id = {placeholder}
            """, (username, user['id']))
            
            conn.commit()
            
            flash("Username updated successfully!", "success")
            return redirect(url_for('dashboard_bp.account_settings'))
        finally:
            conn.close()
    
    return render_template("account_settings.html", user=user)


# ---------------------------------------------------------------------------
# Delete account
# ---------------------------------------------------------------------------

@dashboard_bp.route("/dashboard/delete-account", methods=["POST"])
@login_required
def delete_account():
    """Delete user account and all associated data"""
    user_id = session['user_id']
    user = get_user_by_id(user_id)
    
    if not user:
        flash("User not found.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    user_email = user['email']
    username = user.get('username', 'User')
    
    conn = get_db_connection()
    if not conn:
        flash("Database connection failed.", "error")
        return redirect(url_for('dashboard_bp.account_settings'))
    
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        # First, get all Instagram user IDs associated with this user's connections
        cursor.execute(f"""
            SELECT instagram_user_id 
            FROM instagram_connections 
            WHERE user_id = {placeholder}
        """, (user_id,))
        instagram_user_ids = [row[0] for row in cursor.fetchall()]
        
        # Delete in order to respect foreign key constraints
        # Each deletion is wrapped in its own try/except with rollback to handle PostgreSQL transaction errors
        
        # Delete activity logs
        try:
            cursor.execute(f"DELETE FROM activity_logs WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            logger.warning(f"Could not delete activity_logs: {e}")
            conn.rollback()
        
        # Delete purchases
        try:
            cursor.execute(f"DELETE FROM purchases WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            logger.warning(f"Could not delete purchases: {e}")
            conn.rollback()
        
        # Delete subscriptions
        try:
            cursor.execute(f"DELETE FROM subscriptions WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            logger.warning(f"Could not delete subscriptions: {e}")
            conn.rollback()
        
        # Delete messages - messages are linked to instagram_user_id, not user_id
        # We need to delete messages for all Instagram accounts connected to this user
        if instagram_user_ids:
            try:
                # Create placeholders for IN clause
                placeholders = ','.join([placeholder] * len(instagram_user_ids))
                cursor.execute(f"""
                    DELETE FROM messages 
                    WHERE instagram_user_id IN ({placeholders})
                """, tuple(instagram_user_ids))
                conn.commit()
                logger.info(f"Deleted messages for {len(instagram_user_ids)} Instagram accounts")
            except Exception as e:
                logger.warning(f"Could not delete messages: {e}")
                conn.rollback()
        
        # Delete client settings
        try:
            cursor.execute(f"DELETE FROM client_settings WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            logger.warning(f"Could not delete client_settings: {e}")
            conn.rollback()
        
        # Delete usage logs
        try:
            cursor.execute(f"DELETE FROM usage_logs WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            logger.warning(f"Could not delete usage_logs: {e}")
            conn.rollback()
        
        # Delete instagram connections
        try:
            cursor.execute(f"DELETE FROM instagram_connections WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            logger.warning(f"Could not delete instagram_connections: {e}")
            conn.rollback()
        
        # Delete password reset tokens
        try:
            cursor.execute(f"DELETE FROM password_resets WHERE user_id = {placeholder}", (user_id,))
            conn.commit()
        except Exception as e:
            logger.warning(f"Could not delete password_resets: {e}")
            conn.rollback()
        
        # Finally, delete the user
        try:
            cursor.execute(f"DELETE FROM users WHERE id = {placeholder}", (user_id,))
            conn.commit()
            logger.info(f"Successfully deleted user {user_id}")
        except Exception as e:
            logger.error(f"Could not delete user: {e}")
            conn.rollback()
            raise
        
        conn.close()
        
        # Send confirmation email
        try:
            send_account_deletion_confirmation_email(user_email, username)
        except Exception as e:
            logger.warning(f"Could not send deletion confirmation email: {e}")
        
        # Clear session
        session.clear()
        
        flash("Your account has been successfully deleted. We're sorry to see you go.", "success")
        return redirect(url_for('pages.home'))
        
    except Exception as e:
        logger.error(f"Error deleting account: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        conn.close()
        logger.error(f"Error deleting account for user {session.get('user_id')}: {e}")
        flash("An error occurred while deleting your account. Please try again or contact support.", "error")
        return redirect(url_for('dashboard_bp.account_settings'))


# ---------------------------------------------------------------------------
# Toggle bot pause
# ---------------------------------------------------------------------------

@dashboard_bp.route("/dashboard/toggle-bot-pause", methods=["POST"])
@login_required
def toggle_bot_pause():
    """Toggle bot pause/resume status"""
    user_id = session['user_id']
    
    conn = get_db_connection()
    if not conn:
        flash("Database error. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        # Get current pause status
        cursor.execute(f"""
            SELECT COALESCE(bot_paused, FALSE) FROM users WHERE id = {placeholder}
        """, (user_id,))
        result = cursor.fetchone()
        current_status = result[0] if result else False
        
        # Toggle the status
        new_status = not current_status
        cursor.execute(f"""
            UPDATE users SET bot_paused = {placeholder} WHERE id = {placeholder}
        """, (new_status, user_id))
        conn.commit()
        
        status_text = "paused" if new_status else "resumed"
        flash(f"Bot {status_text} successfully!", "success")
        logger.info(f"Bot {status_text} for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error toggling bot pause: {e}")
        flash("Error updating bot status. Please try again.", "error")
    finally:
        conn.close()
    
    return redirect(url_for('dashboard_bp.dashboard'))


# ---------------------------------------------------------------------------
# Debug routes
# ---------------------------------------------------------------------------

@dashboard_bp.route("/dashboard/debug/instagram-token", methods=["GET"])
@login_required
def debug_instagram_token():
    """Debug route: Verify Facebook user token — debug_token scopes and /me/accounts count. Pass ?token=USER_ACCESS_TOKEN."""
    if not Config.DEBUG_ROUTES_ENABLED:
        return jsonify({"error": "Not found"}), 404
    token = request.args.get("token")
    if not token or not token.strip():
        return jsonify({"error": "Missing query parameter: token=USER_ACCESS_TOKEN"}), 400
    token = token.strip()
    if not Config.FACEBOOK_APP_ID or not Config.FACEBOOK_APP_SECRET:
        return jsonify({"error": "Facebook app not configured"}), 503
    app_token = f"{Config.FACEBOOK_APP_ID}|{Config.FACEBOOK_APP_SECRET}"
    out = {}
    try:
        # debug_token
        debug_resp = requests.get(
            "https://graph.facebook.com/v18.0/debug_token",
            params={"input_token": token, "access_token": app_token},
            timeout=10
        )
        if debug_resp.status_code != 200:
            out["debug_token_error"] = f"status={debug_resp.status_code} body={debug_resp.text[:500]}"
        else:
            debug_data = debug_resp.json()
            out["debug_token"] = debug_data.get("data", {})
            out["scopes"] = out["debug_token"].get("scopes", [])
            out["granular_scopes"] = out["debug_token"].get("granular_scopes", [])
        # /me/accounts
        acc_resp = requests.get(
            "https://graph.facebook.com/v18.0/me/accounts",
            params={"access_token": token, "fields": "id,name,access_token,instagram_business_account"},
            timeout=10
        )
        if acc_resp.status_code != 200:
            out["me_accounts_error"] = f"status={acc_resp.status_code} body={acc_resp.text[:500]}"
            out["me_accounts_count"] = 0
            out["accounts"] = []
        else:
            acc_data = acc_resp.json()
            accounts_list = acc_data.get("data", [])
            out["me_accounts_count"] = len(accounts_list)
            # Redact access_token in response
            out["accounts"] = [
                {"id": a.get("id"), "name": a.get("name"), "has_ig": bool(a.get("instagram_business_account")), "access_token": "***" if a.get("access_token") else None}
                for a in accounts_list
            ]
    except Exception as e:
        out["error"] = str(e)
    return jsonify(out)


@dashboard_bp.route("/dashboard/debug/decrease-replies", methods=["POST"])
@login_required
def debug_decrease_replies():
    """Debug route: Decrease remaining replies by 1"""
    if not Config.DEBUG_ROUTES_ENABLED:
        return "Not found", 404
    user_id = session['user_id']
    
    conn = get_db_connection()
    if not conn:
        flash("Database error.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        # Get current counts
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        result = cursor.fetchone()
        
        if not result:
            flash("Error: User data not found.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased = result
        
        # Calculate remaining
        total_used = replies_sent_monthly + replies_used_purchased
        total_available = replies_limit_monthly + replies_purchased
        remaining = max(0, total_available - total_used)
        
        if remaining <= 0:
            flash("No remaining replies to decrease.", "warning")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        # Decrease by using one reply (increment sent count)
        if replies_sent_monthly < replies_limit_monthly:
            cursor.execute(f"""
                UPDATE users
                SET replies_sent_monthly = replies_sent_monthly + 1
                WHERE id = {placeholder}
            """, (user_id,))
            flash("Decreased remaining replies by 1 (used monthly reply).", "success")
        elif replies_used_purchased < replies_purchased:
            cursor.execute(f"""
                UPDATE users
                SET replies_used_purchased = replies_used_purchased + 1
                WHERE id = {placeholder}
            """, (user_id,))
            flash("Decreased remaining replies by 1 (used purchased reply).", "success")
        else:
            flash("Error: Could not decrease replies.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        conn.commit()
        logger.debug(f"Debug: Decreased replies for user {user_id} by 1")
        
    except Exception as e:
        logger.error(f"Error decreasing replies: {e}")
        flash("Error decreasing replies. Please try again.", "error")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()
    
    return redirect(url_for('dashboard_bp.dashboard'))


@dashboard_bp.route("/dashboard/debug/set-replies-zero", methods=["POST"])
@login_required
def debug_set_replies_zero():
    """Debug route: Set remaining replies to 0 (use all replies)"""
    if not Config.DEBUG_ROUTES_ENABLED:
        return "Not found", 404
    user_id = session['user_id']
    
    conn = get_db_connection()
    if not conn:
        flash("Database error.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        # Get current counts
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        result = cursor.fetchone()
        
        if not result:
            flash("Error: User data not found.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased = result
        
        # Set all replies as used
        cursor.execute(f"""
            UPDATE users
            SET replies_sent_monthly = {placeholder},
                replies_used_purchased = {placeholder}
            WHERE id = {placeholder}
        """, (replies_limit_monthly, replies_purchased, user_id))
        
        conn.commit()
        flash("Set remaining replies to 0 (all replies used).", "success")
        logger.debug(f"Debug: Set replies to 0 for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error setting replies to zero: {e}")
        flash("Error setting replies to zero. Please try again.", "error")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()
    
    return redirect(url_for('dashboard_bp.dashboard'))


@dashboard_bp.route("/dashboard/debug/trigger-monthly-addition", methods=["POST"])
@login_required
def debug_trigger_monthly_addition():
    """Debug route: Manually trigger monthly addition (simulate new month)"""
    if not Config.DEBUG_ROUTES_ENABLED:
        return "Not found", 404
    user_id = session['user_id']
    
    conn = get_db_connection()
    if not conn:
        flash("Database error.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        # Check if user has an active subscription
        cursor.execute(f"""
            SELECT id, plan_type, status
            FROM subscriptions
            WHERE user_id = {placeholder} AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        subscription = cursor.fetchone()
        
        if not subscription:
            flash("You need an active subscription to trigger monthly addition.", "warning")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        plan_type = subscription[1]  # 'starter' or 'standard'
        if plan_type == 'standard':
            monthly_limit = 1500
        else:
            monthly_limit = Config.STARTER_MONTHLY_REPLIES  # starter or default
        
        # Get current replies_limit_monthly
        cursor.execute(f"""
            SELECT replies_limit_monthly FROM users WHERE id = {placeholder}
        """, (user_id,))
        result = cursor.fetchone()
        current_limit = result[0] if result else 0
        
        # Simulate monthly addition: add plan's base replies and reset sent count
        from datetime import datetime
        cursor.execute(f"""
            UPDATE users
            SET replies_sent_monthly = 0,
                replies_limit_monthly = replies_limit_monthly + {placeholder},
                last_monthly_reset = {placeholder}
            WHERE id = {placeholder}
        """, (monthly_limit, datetime.now(), user_id))
        
        conn.commit()
        flash(f"Monthly addition triggered! Added {monthly_limit} replies (new total: {current_limit + monthly_limit}).", "success")
        logger.debug(f"Debug: Triggered monthly addition for user {user_id} - added {monthly_limit} replies")
        
    except Exception as e:
        logger.error(f"Error triggering monthly addition: {e}")
        flash("Error triggering monthly addition. Please try again.", "error")
        conn.rollback()
    finally:
        conn.close()
    
    return redirect(url_for('dashboard_bp.dashboard'))


# ---------------------------------------------------------------------------
# Disconnect Instagram
# ---------------------------------------------------------------------------

@dashboard_bp.route("/dashboard/disconnect-instagram/<int:connection_id>", methods=["POST"])
@login_required
def disconnect_instagram(connection_id):
    user_id = session['user_id']
    
    # Verify the connection belongs to the current user
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholder = get_param_placeholder()
    
    try:
        # Check if connection exists and belongs to user
        cursor.execute(f"""
            SELECT id, instagram_user_id FROM instagram_connections 
            WHERE id = {placeholder} AND user_id = {placeholder}
        """, (connection_id, user_id))
        
        connection = cursor.fetchone()
        if not connection:
            flash("Connection not found or you don't have permission to disconnect it.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        # Delete dependent rows first (foreign key constraints)
        cursor.execute(f"DELETE FROM conversation_senders WHERE instagram_connection_id = {placeholder}", (connection_id,))
        cursor.execute(f"DELETE FROM messages WHERE instagram_connection_id = {placeholder}", (connection_id,))
        cursor.execute(f"DELETE FROM usage_logs WHERE instagram_connection_id = {placeholder}", (connection_id,))
        cursor.execute(f"DELETE FROM client_settings WHERE instagram_connection_id = {placeholder}", (connection_id,))
        
        # Then delete the connection
        cursor.execute(f"DELETE FROM instagram_connections WHERE id = {placeholder}", (connection_id,))
        
        conn.commit()
        
        # Log the activity
        log_activity(user_id, 'instagram_disconnected', f'Disconnected Instagram account {connection[1]}')
        
        flash(f"Instagram account {connection[1]} has been disconnected successfully.", "success")
        
    except Exception as e:
        logger.error(f"Error disconnecting Instagram account: {e}")
        flash("An error occurred while disconnecting the account.", "error")
        conn.rollback()
    finally:
        conn.close()
    
    return redirect(url_for('dashboard_bp.dashboard'))


# ---------------------------------------------------------------------------
# Usage analytics
# ---------------------------------------------------------------------------

@dashboard_bp.route("/dashboard/usage")
@login_required
def usage_analytics():
    user_id = session['user_id']
    
    # Get usage statistics for the current month
    # Open connection once and reuse it for all operations
    conn = get_db_connection()
    if not conn:
        flash("Database error. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Check and reset monthly counter if needed - reuse the same connection
        check_user_reply_limit(user_id, conn)
        
        # Get user's reply counts
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        reply_data = cursor.fetchone()
        
        if reply_data:
            replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased = reply_data
            if replies_limit_monthly is None:
                replies_limit_monthly = 0
            total_replies_used = replies_sent_monthly + replies_used_purchased
            total_replies_available = replies_limit_monthly + replies_purchased
            remaining_replies = max(0, total_replies_available - total_replies_used)
            MINUTES_PER_REPLY = 3
            minutes_saved = replies_sent_monthly * MINUTES_PER_REPLY
        else:
            replies_sent_monthly = 0
            replies_limit_monthly = 0
            replies_purchased = 0
            replies_used_purchased = 0
            total_replies_used = 0
            total_replies_available = 0
            remaining_replies = 0
            minutes_saved = 0
        
        # Get recent activity
        cursor.execute(f"""
            SELECT action, details, created_at 
            FROM activity_logs 
            WHERE user_id = {placeholder} 
            ORDER BY created_at DESC 
            LIMIT 10
        """, (user_id,))
        activity_rows = cursor.fetchall()
        
        recent_activity = []
        for row in activity_rows:
            action, details, created_at = row
            if created_at:
                if isinstance(created_at, str):
                    formatted_time = created_at[:16] if len(created_at) > 16 else created_at
                else:
                    formatted_time = created_at.strftime('%Y-%m-%d %H:%M')
            else:
                formatted_time = ''
            recent_activity.append((action, details, formatted_time))
        
    finally:
        conn.close()
    
    return render_template("usage_analytics.html", 
                         replies_sent=replies_sent_monthly,
                         replies_limit=replies_limit_monthly,
                         replies_purchased=replies_purchased,
                         replies_used_purchased=replies_used_purchased,
                         total_replies_used=total_replies_used,
                         total_replies_available=total_replies_available,
                         remaining_replies=remaining_replies,
                         minutes_saved=minutes_saved,
                         recent_activity=recent_activity)
