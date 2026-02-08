"""Stripe webhook event handlers."""
import logging
import os
import stripe
from datetime import datetime, timedelta
from config import Config
from database import get_db_connection, get_param_placeholder
from services.subscription import add_purchased_replies

logger = logging.getLogger("chata.services.stripe_handlers")


def log_activity(user_id, action_type, description=None, conn=None):
    """Proxy to app.log_activity – late import to avoid circular dependency."""
    from app import log_activity as _log
    return _log(user_id, action_type, description, conn)


# ---- Stripe object helpers ----

def _stripe_obj_id(obj):
    """Get id from a Stripe object (dict from webhook or StripeObject)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get('id')
    return getattr(obj, 'id', None)


def _stripe_subscription_items_data(sub):
    """
    Get list of subscription items from a Subscription (dict or StripeObject).
    Use bracket/dict access to avoid .items conflicting with Python's dict.items().
    """
    if sub is None:
        return []
    try:
        if isinstance(sub, dict):
            items_container = sub.get('items')
        else:
            items_container = sub.get('items') if hasattr(sub, 'get') else sub['items']
        if items_container is None:
            return []
        if isinstance(items_container, dict):
            return items_container.get('data', [])
        if hasattr(items_container, 'data'):
            data = items_container.data
            return list(data) if data else []
        return []
    except (KeyError, TypeError, AttributeError):
        return []


def _stripe_price_id_from_items(items_list):
    """Extract price id from first item in list (item can be dict or object)."""
    if not items_list:
        return None
    item = items_list[0]
    try:
        if isinstance(item, dict):
            price = item.get('price')
            if isinstance(price, dict):
                return price.get('id')
            return price if isinstance(price, str) else None
        price = getattr(item, 'price', None)
        if price is None:
            return None
        if isinstance(price, str):
            return price
        return getattr(price, 'id', None)
    except (TypeError, AttributeError):
        return None


# ---- Webhook event handlers ----

def handle_checkout_session_completed(session_obj):
    """Handle completed checkout session"""
    try:
        logger.info(f"Checkout session metadata: {session_obj.metadata}")
        
        user_id_str = session_obj.metadata.get('user_id')
        if not user_id_str:
            logger.warning(f"No user_id in checkout session metadata - this is likely a test event")
            return
        
        user_id = int(user_id_str)
        session_type = session_obj.metadata.get('type')
        
        logger.info(f"Processing checkout for user {user_id}, type: {session_type}")
        
        if session_type == 'upgrade':
            # Handle upgrade - cancel old Starter subscription
            old_subscription_id = session_obj.metadata.get('old_subscription_id')
            if old_subscription_id:
                try:
                    # Cancel the old subscription in Stripe
                    stripe.Subscription.modify(old_subscription_id, cancel_at_period_end=False)
                    stripe.Subscription.delete(old_subscription_id)
                    logger.info(f"Cancelled old subscription {old_subscription_id} for user {user_id}")
                    
                    # Mark old subscription as canceled in database
                    conn = None
                    try:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        placeholder = get_param_placeholder()
                        cursor.execute(f"""
                            UPDATE subscriptions 
                            SET status = {placeholder}
                            WHERE stripe_subscription_id = {placeholder}
                        """, ('canceled', old_subscription_id))
                        conn.commit()
                        logger.info(f"Marked old subscription as canceled in database")
                    finally:
                        if conn:
                            try:
                                conn.close()
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"Error canceling old subscription: {e}")
            
            # For upgrades, try to get price ID from checkout session line items
            try:
                # Retrieve the full checkout session to get line items
                full_session = stripe.checkout.Session.retrieve(session_obj.id, expand=['line_items'])
                if hasattr(full_session, 'line_items') and hasattr(full_session.line_items, 'data'):
                    line_items = full_session.line_items.data
                    if line_items and len(line_items) > 0:
                        line_item = line_items[0]
                        if hasattr(line_item, 'price') and hasattr(line_item.price, 'id'):
                            price_id_from_session = line_item.price.id
                            logger.info(f"Got price ID from checkout session: {price_id_from_session}")
                            # Store in session metadata for later retrieval (we'll use a different approach)
            except Exception as e:
                logger.warning(f"Could not get price ID from checkout session: {e}")
        
        elif session_type == 'downgrade':
            # Handle downgrade - cancel old Standard subscription so only the new Starter is active
            old_subscription_id = session_obj.metadata.get('old_subscription_id')
            if old_subscription_id:
                try:
                    # Cancel the old subscription in Stripe
                    stripe.Subscription.modify(old_subscription_id, cancel_at_period_end=False)
                    stripe.Subscription.delete(old_subscription_id)
                    logger.info(f"Cancelled old subscription {old_subscription_id} for user {user_id} (downgrade)")
                    
                    # Mark old subscription as canceled in database
                    conn = None
                    try:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        placeholder = get_param_placeholder()
                        cursor.execute(f"""
                            UPDATE subscriptions 
                            SET status = {placeholder}
                            WHERE stripe_subscription_id = {placeholder}
                        """, ('canceled', old_subscription_id))
                        conn.commit()
                        logger.info(f"Marked old subscription as canceled in database (downgrade)")
                    finally:
                        if conn:
                            try:
                                conn.close()
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"Error canceling old subscription on downgrade: {e}")
        
        if session_type == 'addon':
            # Handle one-time add-on purchase
            amount = session_obj.amount_total / 100  # Convert cents to euros
            replies_to_add = Config.ADDON_REPLIES  # €5 for 150 replies
            success = add_purchased_replies(
                user_id, 
                amount, 
                payment_provider="stripe", 
                payment_id=session_obj.id
            )
            if success:
                log_activity(user_id, 'stripe_addon_purchase', f'Purchased {replies_to_add} replies via Stripe')
                logger.info(f"Added {replies_to_add} replies for user {user_id} from Stripe payment")
    except Exception as e:
        logger.error(f"Error handling checkout session completed: {e}")
        import traceback
        traceback.print_exc()

def handle_subscription_created(subscription):
    """Handle new subscription creation (subscription can be dict from webhook or StripeObject)."""
    try:
        subscription_id = _stripe_obj_id(subscription)
        customer_id = subscription.get('customer') if isinstance(subscription, dict) else getattr(subscription, 'customer', None)
        if not subscription_id or not customer_id:
            logger.error(f"Missing subscription id or customer id in subscription object")
            return
        logger.info(f"Processing subscription created: {subscription_id}")
        logger.info(f"Customer ID: {customer_id}")
        
        customer = stripe.Customer.retrieve(customer_id)
        logger.debug(f"Customer metadata: {customer.metadata}")
        
        user_id_str = customer.metadata.get('user_id')
        if not user_id_str:
            logger.error(f"No user_id in customer metadata for customer {customer_id}")
            return
        
        user_id = int(user_id_str)
        logger.info(f"Processing subscription for user ID: {user_id}")
        
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to get DB connection for subscription creation")
            return
        try:
            cursor = conn.cursor()
            placeholder = get_param_placeholder()
        
            # Get price ID and period dates from subscription - retrieve fresh with expanded items for reliability
            price_id = None
            current_period_start = None
            current_period_end = None
            subscription_status = None
            
            try:
                logger.info(f"Retrieving subscription {subscription_id} with expanded items...")
                expanded_sub = stripe.Subscription.retrieve(subscription_id, expand=['items.data.price'])
                
                subscription_status = expanded_sub.get('status') if isinstance(expanded_sub, dict) else getattr(expanded_sub, 'status', None)
                
                items_list = _stripe_subscription_items_data(expanded_sub)
                price_id = _stripe_price_id_from_items(items_list)
                if price_id:
                    logger.info(f"Found price ID from expanded subscription: {price_id}")
                
                if hasattr(expanded_sub, 'current_period_start') and expanded_sub.current_period_start:
                    current_period_start = datetime.fromtimestamp(expanded_sub.current_period_start)
                else:
                    current_period_start = datetime.now()
                
                if hasattr(expanded_sub, 'current_period_end') and expanded_sub.current_period_end:
                    current_period_end = datetime.fromtimestamp(expanded_sub.current_period_end)
                else:
                    current_period_end = datetime.now() + timedelta(days=30)
                
                if not price_id:
                    logger.error(f"Could not determine price ID from subscription")
                        
            except Exception as e:
                logger.warning(f"Error retrieving subscription details: {e}")
                import traceback
                traceback.print_exc()
                logger.error(f"Could not retrieve subscription details, price_id remains None")
                subscription_status = 'active'
                current_period_start = datetime.now()
                current_period_end = datetime.now() + timedelta(days=30)
            
            logger.info(f"Price ID: {price_id}")
            
            # If price_id is None, try alternative methods
            if not price_id:
                try:
                    logger.info(f"Trying alternative method to get price ID...")
                    try:
                        items_list_api = stripe.SubscriptionItem.list(subscription=subscription_id, limit=1)
                        if items_list_api and len(items_list_api.data) > 0:
                            price_id = _stripe_price_id_from_items(list(items_list_api.data))
                            if price_id:
                                logger.info(f"Retrieved price ID via SubscriptionItem.list: {price_id}")
                    except Exception as e1:
                        logger.warning(f"SubscriptionItem.list failed: {e1}")
                    
                    if not price_id:
                        items_orig = _stripe_subscription_items_data(subscription)
                        price_id = _stripe_price_id_from_items(items_orig)
                        if price_id:
                            logger.info(f"Retrieved price ID via original subscription: {price_id}")
                except Exception as e:
                    logger.warning(f"All alternative methods failed: {e}")
            
            # Determine plan type based on price ID
            standard_price_id = Config.STRIPE_STANDARD_PLAN_PRICE_ID or os.getenv("STRIPE_STANDARD_PLAN_PRICE_ID")
            starter_price_id = Config.STRIPE_STARTER_PLAN_PRICE_ID or os.getenv("STRIPE_STARTER_PLAN_PRICE_ID")
            
            logger.info(f"Comparing price_id '{price_id}' with standard '{standard_price_id}' and starter '{starter_price_id}'")
            
            plan_type = 'starter'
            replies_limit = Config.STARTER_MONTHLY_REPLIES
            
            if price_id:
                if standard_price_id and price_id == standard_price_id:
                    plan_type = 'standard'
                    replies_limit = 1500
                    logger.info(f"Detected Standard plan - setting replies_limit to 1500")
                elif starter_price_id and price_id == starter_price_id:
                    plan_type = 'starter'
                    replies_limit = Config.STARTER_MONTHLY_REPLIES
                    logger.info(f"Detected Starter plan - setting replies_limit to {Config.STARTER_MONTHLY_REPLIES}")
                else:
                    logger.warning(f"Price ID {price_id} doesn't match known plans, defaulting to Starter")
            else:
                logger.error(f"Price ID is None - cannot determine plan type. This is an error!")
                logger.warning(f"Skipping database insertion due to missing price_id")
                return
            
            # Check if using PostgreSQL
            is_postgres = Config.DATABASE_URL and (Config.DATABASE_URL.startswith("postgres://") or Config.DATABASE_URL.startswith("postgresql://"))
            
            if is_postgres:
                cursor.execute(f"""
                    INSERT INTO subscriptions 
                    (user_id, stripe_subscription_id, stripe_customer_id, stripe_price_id, 
                     plan_type, status, current_period_start, current_period_end)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                            {placeholder}, {placeholder}, {placeholder}, {placeholder})
                    ON CONFLICT (stripe_subscription_id) DO UPDATE SET
                    plan_type = EXCLUDED.plan_type,
                    stripe_price_id = EXCLUDED.stripe_price_id,
                    status = EXCLUDED.status,
                    current_period_start = EXCLUDED.current_period_start,
                    current_period_end = EXCLUDED.current_period_end,
                    updated_at = CURRENT_TIMESTAMP
                """, (user_id, subscription_id, customer_id, price_id,
                      plan_type, subscription_status, current_period_start, current_period_end))
            else:
                cursor.execute(f"""
                    INSERT OR REPLACE INTO subscriptions 
                    (user_id, stripe_subscription_id, stripe_customer_id, stripe_price_id, 
                     plan_type, status, current_period_start, current_period_end)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, 
                            {placeholder}, {placeholder}, {placeholder}, {placeholder})
                """, (user_id, subscription_id, customer_id, price_id,
                      plan_type, subscription_status, current_period_start, current_period_end))
            
            logger.info(f"Subscription record created in database")
            
            # Get current replies_limit_monthly from users table to preserve existing replies
            cursor.execute(f"""
                SELECT replies_limit_monthly FROM users WHERE id = {placeholder}
            """, (user_id,))
            user_data = cursor.fetchone()
            current_replies_limit = user_data[0] if user_data else 0
            
            logger.info(f"Adding {replies_limit} replies to user {user_id}'s existing {current_replies_limit} replies")
            
            if current_replies_limit > 0:
                cursor.execute(f"""
                    UPDATE users 
                    SET replies_limit_monthly = replies_limit_monthly + {placeholder}
                    WHERE id = {placeholder}
                """, (replies_limit, user_id))
                logger.info(f"Added {replies_limit} replies (new total: {current_replies_limit + replies_limit})")
            else:
                cursor.execute(f"""
                    UPDATE users 
                    SET replies_limit_monthly = {placeholder}
                    WHERE id = {placeholder}
                """, (replies_limit, user_id))
                logger.info(f"Set replies_limit_monthly to {replies_limit} (no existing replies)")
            
            conn.commit()
            
            plan_name = 'Standard' if plan_type == 'standard' else 'Starter'
            log_activity(user_id, 'stripe_subscription_created', f'{plan_name} plan subscription activated')
            logger.info(f"Subscription created for user {user_id}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
        
    except Exception as e:
        logger.error(f"Error handling subscription created: {e}")
        import traceback
        traceback.print_exc()

def handle_subscription_updated(subscription):
    """Handle subscription updates (including upgrades/downgrades). Subscription can be dict from webhook or StripeObject."""
    try:
        subscription_id = _stripe_obj_id(subscription)
        customer_id = subscription.get('customer') if isinstance(subscription, dict) else getattr(subscription, 'customer', None)
        if not subscription_id or not customer_id:
            logger.error(f"Missing subscription id or customer id in subscription object")
            return
        customer = stripe.Customer.retrieve(customer_id)
        user_id_str = customer.metadata.get('user_id')
        
        if not user_id_str:
            logger.error(f"No user_id in customer metadata")
            return
        
        user_id = int(user_id_str)
        
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to get DB connection for subscription update")
            return
        try:
            cursor = conn.cursor()
            placeholder = get_param_placeholder()
        
            is_postgres = Config.DATABASE_URL and (Config.DATABASE_URL.startswith("postgres://") or Config.DATABASE_URL.startswith("postgresql://"))
            cancel_at_period_end = subscription.get('cancel_at_period_end', False) if isinstance(subscription, dict) else getattr(subscription, 'cancel_at_period_end', False)
            
            cancel_value = cancel_at_period_end if is_postgres else (1 if cancel_at_period_end else 0)
            
            cursor.execute(f"""
                SELECT status, plan_type, stripe_price_id FROM subscriptions WHERE stripe_subscription_id = {placeholder}
            """, (subscription_id,))
            existing_sub_data = cursor.fetchone()
            existing_status = existing_sub_data[0] if existing_sub_data else None
            existing_plan_type = existing_sub_data[1] if existing_sub_data else None
            existing_price_id = existing_sub_data[2] if existing_sub_data and len(existing_sub_data) > 2 else None
            
            if existing_status == 'canceled' or cancel_at_period_end:
                logger.warning(f"Subscription {subscription_id} is canceled - preserving existing plan_type '{existing_plan_type}'")
                
                expanded_sub = stripe.Subscription.retrieve(subscription_id, expand=['items.data.price'])
                items_list = _stripe_subscription_items_data(expanded_sub)
                price_id = _stripe_price_id_from_items(items_list)
                final_price_id = price_id if price_id else existing_price_id
                
                _cps = subscription.get('current_period_start') if isinstance(subscription, dict) else getattr(subscription, 'current_period_start', None)
                _cpe = subscription.get('current_period_end') if isinstance(subscription, dict) else getattr(subscription, 'current_period_end', None)
                period_start = datetime.fromtimestamp(_cps) if _cps else datetime.now()
                period_end = datetime.fromtimestamp(_cpe) if _cpe else datetime.now() + timedelta(days=30)
                
                if final_price_id:
                    cursor.execute(f"""
                        UPDATE subscriptions 
                        SET status = {placeholder}, stripe_price_id = {placeholder},
                            current_period_start = {placeholder}, current_period_end = {placeholder},
                            cancel_at_period_end = {placeholder}, updated_at = CURRENT_TIMESTAMP
                        WHERE stripe_subscription_id = {placeholder}
                    """, ('canceled', final_price_id, period_start, period_end, cancel_value, subscription_id))
                else:
                    cursor.execute(f"""
                        UPDATE subscriptions 
                        SET status = {placeholder}, current_period_start = {placeholder},
                            current_period_end = {placeholder}, cancel_at_period_end = {placeholder},
                            updated_at = CURRENT_TIMESTAMP
                        WHERE stripe_subscription_id = {placeholder}
                    """, ('canceled', period_start, period_end, cancel_value, subscription_id))
                
                conn.commit()
                logger.info(f"Subscription updated (canceled): {subscription_id} (plan_type preserved: {existing_plan_type})")
                return
            
            # Active subscription - process upgrades/downgrades
            expanded_sub = stripe.Subscription.retrieve(subscription_id, expand=['items.data.price'])
            items_list = _stripe_subscription_items_data(expanded_sub)
            price_id = _stripe_price_id_from_items(items_list)
            standard_price_id = Config.STRIPE_STANDARD_PLAN_PRICE_ID or os.getenv("STRIPE_STANDARD_PLAN_PRICE_ID")
            starter_price_id = Config.STRIPE_STARTER_PLAN_PRICE_ID or os.getenv("STRIPE_STARTER_PLAN_PRICE_ID")
            new_plan_type = 'starter'
            if price_id:
                if standard_price_id and price_id == standard_price_id:
                    new_plan_type = 'standard'
                elif starter_price_id and price_id == starter_price_id:
                    new_plan_type = 'starter'
            
            cursor.execute(f"""
                SELECT plan_type, replies_limit_monthly
                FROM subscriptions s
                JOIN users u ON s.user_id = u.id
                WHERE s.stripe_subscription_id = {placeholder} AND s.user_id = {placeholder}
            """, (subscription_id, user_id))
            current_sub = cursor.fetchone()
            
            if current_sub:
                old_plan_type = current_sub[0]
                if old_plan_type == 'starter' and new_plan_type == 'standard':
                    logger.info(f"Detected upgrade from Starter to Standard for user {user_id}")
                    cursor.execute(f"""
                        UPDATE users SET replies_limit_monthly = replies_limit_monthly + 1500
                        WHERE id = {placeholder}
                    """, (user_id,))
                elif old_plan_type == 'standard' and new_plan_type == 'starter':
                    logger.info(f"Detected downgrade from Standard to Starter for user {user_id}")
                    cursor.execute(f"""
                        UPDATE users SET replies_limit_monthly = replies_limit_monthly + 150
                        WHERE id = {placeholder}
                    """, (user_id,))
                else:
                    logger.info(f"Plan type unchanged: {old_plan_type} -> {new_plan_type}")
            
            _status = subscription.get('status', 'active') if isinstance(subscription, dict) else getattr(subscription, 'status', 'active')
            _cps = subscription.get('current_period_start') if isinstance(subscription, dict) else getattr(subscription, 'current_period_start', None)
            _cpe = subscription.get('current_period_end') if isinstance(subscription, dict) else getattr(subscription, 'current_period_end', None)
            period_start = datetime.fromtimestamp(_cps) if _cps else datetime.now()
            period_end = datetime.fromtimestamp(_cpe) if _cpe else datetime.now() + timedelta(days=30)
            
            cursor.execute(f"""
                UPDATE subscriptions 
                SET status = {placeholder}, plan_type = {placeholder}, stripe_price_id = {placeholder},
                    current_period_start = {placeholder}, current_period_end = {placeholder},
                    cancel_at_period_end = {placeholder}, updated_at = CURRENT_TIMESTAMP
                WHERE stripe_subscription_id = {placeholder}
            """, (_status, new_plan_type, price_id, period_start, period_end, cancel_value, subscription_id))
            
            conn.commit()
            logger.info(f"Subscription updated: {subscription_id} (plan: {new_plan_type})")
        finally:
            try:
                conn.close()
            except Exception:
                pass
        
    except Exception as e:
        logger.error(f"Error handling subscription updated: {e}")
        import traceback
        traceback.print_exc()

def handle_subscription_deleted(subscription):
    """Handle subscription cancellation - keep remaining replies but mark as canceled. Subscription can be dict from webhook or StripeObject."""
    try:
        subscription_id = _stripe_obj_id(subscription)
        customer_id = subscription.get('customer') if isinstance(subscription, dict) else getattr(subscription, 'customer', None)
        if not subscription_id or not customer_id:
            logger.error(f"Missing subscription id or customer id in subscription object")
            return
        customer = stripe.Customer.retrieve(customer_id)
        user_id_str = customer.metadata.get('user_id')
        
        if not user_id_str:
            logger.error(f"No user_id in customer metadata for canceled subscription")
            return
        
        user_id = int(user_id_str)
        logger.info(f"Processing subscription cancellation for user {user_id}")
        
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to get DB connection for subscription deletion")
            return
        try:
            cursor = conn.cursor()
            placeholder = get_param_placeholder()
        
            # Update subscription status to canceled but keep it in database
            # IMPORTANT: Only update status, NOT plan_type - preserve the plan type
            cursor.execute(f"""
                SELECT plan_type, status
                FROM subscriptions
                WHERE stripe_subscription_id = {placeholder}
            """, (subscription_id,))
            current_sub = cursor.fetchone()
            current_plan_type = current_sub[0] if current_sub else None
            
            if current_sub:
                logger.info(f"Updating subscription {subscription_id} from status '{current_sub[1]}' to 'canceled', preserving plan_type '{current_plan_type}'")
            
            cursor.execute(f"""
                UPDATE subscriptions 
                SET status = {placeholder}, updated_at = CURRENT_TIMESTAMP
                WHERE stripe_subscription_id = {placeholder}
            """, ('canceled', subscription_id))
            
            # Verify plan_type wasn't changed
            cursor.execute(f"""
                SELECT plan_type, status FROM subscriptions
                WHERE stripe_subscription_id = {placeholder}
            """, (subscription_id,))
            verify = cursor.fetchone()
            if verify and current_sub and verify[0] != current_plan_type:
                logger.warning(f"Plan type changed during cancellation - restoring")
                cursor.execute(f"""
                    UPDATE subscriptions SET plan_type = {placeholder}
                    WHERE stripe_subscription_id = {placeholder}
                """, (current_plan_type, subscription_id))
            
            # Get current reply counts for logging
            cursor.execute(f"""
                SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
                FROM users WHERE id = {placeholder}
            """, (user_id,))
            reply_data = cursor.fetchone()
            
            if reply_data:
                total_used = reply_data[0] + reply_data[3]
                total_available = reply_data[1] + reply_data[2]
                remaining = max(0, total_available - total_used)
                logger.info(f"User {user_id} has {remaining} remaining replies after cancellation")
            
            conn.commit()
            
            log_activity(user_id, 'stripe_subscription_canceled', 'Subscription canceled - remaining replies preserved')
            logger.info(f"Subscription canceled for user {user_id} (remaining replies preserved)")
        finally:
            try:
                conn.close()
            except Exception:
                pass
        
    except Exception as e:
        logger.error(f"Error handling subscription deleted: {e}")
        import traceback
        traceback.print_exc()

def handle_invoice_payment_succeeded(invoice):
    """Handle successful monthly subscription payment"""
    try:
        # Retrieve invoice with expanded subscription to ensure we can access it
        invoice_id = invoice.id if hasattr(invoice, 'id') else None
        subscription_id = None
        
        if invoice_id:
            try:
                # Retrieve invoice with expanded subscription
                expanded_invoice = stripe.Invoice.retrieve(invoice_id, expand=['subscription'])
                
                # Get subscription ID - can be a string ID or object
                if hasattr(expanded_invoice, 'subscription'):
                    if expanded_invoice.subscription is None:
                        logger.warning(f"Invoice {invoice_id} has no subscription (one-time payment)")
                        return
                    elif isinstance(expanded_invoice.subscription, str):
                        subscription_id = expanded_invoice.subscription
                    elif hasattr(expanded_invoice.subscription, 'id'):
                        subscription_id = expanded_invoice.subscription.id
                    else:
                        subscription_id = str(expanded_invoice.subscription)
                else:
                    logger.warning(f"Invoice {invoice_id} has no subscription attribute")
                    return
            except Exception as e:
                logger.warning(f"Error retrieving invoice: {e}")
                # Fallback: try direct access
                if hasattr(invoice, 'subscription') and invoice.subscription:
                    subscription_id = invoice.subscription.id if hasattr(invoice.subscription, 'id') else str(invoice.subscription)
                elif isinstance(invoice, dict) and 'subscription' in invoice:
                    subscription_id = invoice['subscription']
                    if isinstance(subscription_id, dict) and 'id' in subscription_id:
                        subscription_id = subscription_id['id']
        
        if not subscription_id:
            logger.warning(f"No subscription ID in invoice - this might be a one-time payment or test event")
            return
        
        logger.info(f"Invoice payment succeeded for subscription: {subscription_id}")
        
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to get DB connection for invoice payment")
            return
        try:
            cursor = conn.cursor()
            placeholder = get_param_placeholder()
            
            # Get user from subscription
            cursor.execute(f"""
                SELECT user_id FROM subscriptions 
                WHERE stripe_subscription_id = {placeholder}
            """, (subscription_id,))
            result = cursor.fetchone()
            
            if result:
                user_id = result[0]
                logger.info(f"Resetting monthly replies for user {user_id}")
                
                # Get plan type to set correct monthly limit
                cursor.execute(f"""
                    SELECT plan_type FROM subscriptions 
                    WHERE stripe_subscription_id = {placeholder} AND user_id = {placeholder}
                """, (subscription_id, user_id))
                plan_result = cursor.fetchone()
                
                if plan_result:
                    plan_type = plan_result[0]
                    if plan_type == 'standard':
                        monthly_limit = 1500
                    else:
                        monthly_limit = Config.STARTER_MONTHLY_REPLIES
                else:
                    monthly_limit = Config.STARTER_MONTHLY_REPLIES
                
                # Add monthly replies at the start of new billing period (don't reset, just add)
                cursor.execute(f"""
                    UPDATE users 
                    SET replies_sent_monthly = 0,
                        replies_limit_monthly = replies_limit_monthly + {placeholder},
                        last_monthly_reset = CURRENT_TIMESTAMP
                    WHERE id = {placeholder}
                """, (monthly_limit, user_id))
                
                conn.commit()
                log_activity(user_id, 'stripe_invoice_paid', 'Monthly subscription payment succeeded')
                logger.info(f"Monthly payment succeeded for user {user_id} - added {monthly_limit} replies")
            else:
                logger.warning(f"No subscription found in database for subscription_id: {subscription_id}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
        
    except Exception as e:
        logger.error(f"Error handling invoice payment succeeded: {e}")
        import traceback
        traceback.print_exc()

def handle_invoice_payment_failed(invoice):
    """Handle failed subscription payment"""
    try:
        # Get subscription ID - handle both object attribute and dictionary access
        subscription_id = None
        try:
            if hasattr(invoice, 'subscription') and invoice.subscription:
                subscription_id = invoice.subscription.id if hasattr(invoice.subscription, 'id') else str(invoice.subscription)
            elif isinstance(invoice, dict) and 'subscription' in invoice:
                subscription_id = invoice['subscription']
                if isinstance(subscription_id, dict) and 'id' in subscription_id:
                    subscription_id = subscription_id['id']
        except Exception as e:
            logger.warning(f"Could not access invoice.subscription: {e}")
        
        if not subscription_id:
            logger.warning(f"No subscription ID in invoice - skipping payment failure handling")
            return
        
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to get DB connection for invoice payment failure")
            return
        try:
            cursor = conn.cursor()
            placeholder = get_param_placeholder()
            
            cursor.execute(f"""
                SELECT user_id FROM subscriptions 
                WHERE stripe_subscription_id = {placeholder}
            """, (subscription_id,))
            result = cursor.fetchone()
            
            if result:
                user_id = result[0]
                log_activity(user_id, 'stripe_payment_failed', 'Monthly subscription payment failed')
                logger.warning(f"Payment failed for user {user_id}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
        
    except Exception as e:
        logger.error(f"Error handling invoice payment failed: {e}")
