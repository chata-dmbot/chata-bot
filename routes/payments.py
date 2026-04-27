"""Payment routes — Stripe checkout, subscription management."""
import logging
import os
from datetime import datetime
from flask import Blueprint, request, redirect, url_for, flash, session, render_template

logger = logging.getLogger("chata.routes.payments")
import stripe
from config import Config

def _base_url():
    """Return the canonical base URL for Stripe redirects (no trailing slash)."""
    return Config.BASE_URL.rstrip("/")
from database import get_db_connection, get_param_placeholder
from services.auth import login_required
from services.activity import log_activity
from services.users import get_user_by_id

payments_bp = Blueprint('payments', __name__)


@payments_bp.route("/checkout/subscription", methods=["POST"])
@login_required
def create_subscription_checkout():
    """Create Stripe Checkout session for subscription"""
    if not Config.STRIPE_SECRET_KEY or not Config.STRIPE_STARTER_PLAN_PRICE_ID:
        flash("❌ Payment system is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    user_id = session['user_id']
    user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
    
    conn = None
    try:
        # Create or retrieve Stripe customer
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Check if user already has a Stripe customer ID in subscriptions table
        cursor.execute(f"""
            SELECT stripe_customer_id FROM subscriptions 
            WHERE user_id = {placeholder} 
            LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            customer_id = result[0]
            logger.info(f"Found existing customer ID in database: {customer_id}")
        else:
            # Check if customer already exists in Stripe by email
            existing_customers = stripe.Customer.list(email=user_email, limit=1)
            if existing_customers.data:
                # Use existing customer
                customer_id = existing_customers.data[0].id
                # Update metadata to ensure user_id is set
                stripe.Customer.modify(customer_id, metadata={'user_id': str(user_id)})
                logger.info(f"Found existing Stripe customer: {customer_id}")
            else:
                # Create new Stripe customer
                customer = stripe.Customer.create(
                    email=user_email,
                    metadata={'user_id': str(user_id)}
                )
                customer_id = customer.id
                logger.info(f"Created new Stripe customer: {customer_id}")
        
        conn.close()
        conn = None  # Mark as closed so finally doesn't double-close
        
        # Create Checkout Session for subscription
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': Config.STRIPE_STARTER_PLAN_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=_base_url() + '/checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=_base_url() + '/dashboard',
            metadata={'user_id': str(user_id), 'type': 'subscription'}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        flash("❌ Payment error. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    except Exception as e:
        logger.error(f"Error creating subscription checkout: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@payments_bp.route("/checkout/standard", methods=["POST"])
@login_required
def create_standard_checkout():
    """Create Stripe Checkout session for Standard plan subscription"""
    # Try to get from Config first, then fallback to direct os.getenv (for Render env var updates)
    # Also check for common typos
    standard_price_id = (
        Config.STRIPE_STANDARD_PLAN_PRICE_ID or 
        os.getenv("STRIPE_STANDARD_PLAN_PRICE_ID") or
        os.getenv("SRTPE_STANDARD_PLAN_PRICE_ID")  # Common typo check
    )
    
    # Debug logging to help diagnose the issue
    logger.debug(f"[STANDARD CHECKOUT] Checking configuration...")
    logger.debug(f"[STANDARD CHECKOUT] STRIPE_SECRET_KEY exists: {bool(Config.STRIPE_SECRET_KEY)}")
    logger.debug(f"[STANDARD CHECKOUT] Config.STRIPE_STANDARD_PLAN_PRICE_ID: '{Config.STRIPE_STANDARD_PLAN_PRICE_ID}'")
    logger.debug(f"[STANDARD CHECKOUT] Direct os.getenv('STRIPE_STANDARD_PLAN_PRICE_ID'): '{os.getenv('STRIPE_STANDARD_PLAN_PRICE_ID')}'")
    logger.debug(f"[STANDARD CHECKOUT] Typo check os.getenv('SRTPE_STANDARD_PLAN_PRICE_ID'): '{os.getenv('SRTPE_STANDARD_PLAN_PRICE_ID')}'")
    logger.debug(f"[STANDARD CHECKOUT] All env vars starting with STRIPE: {[k for k in os.environ.keys() if 'STRIPE' in k or 'SRTPE' in k]}")
    logger.debug(f"[STANDARD CHECKOUT] Final standard_price_id (after fallback): '{standard_price_id}'")
    
    if not Config.STRIPE_SECRET_KEY:
        logger.error(f"[STANDARD CHECKOUT] STRIPE_SECRET_KEY is missing")
        flash("❌ Payment system is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    if not standard_price_id:
        logger.error(f"[STANDARD CHECKOUT] STRIPE_STANDARD_PLAN_PRICE_ID is missing or empty")
        logger.error(f"[STANDARD CHECKOUT] Please verify STRIPE_STANDARD_PLAN_PRICE_ID is set in Render environment variables")
        logger.error(f"[STANDARD CHECKOUT] After adding/updating env vars in Render, you may need to manually redeploy the service")
        flash("❌ Standard plan is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    user_id = session['user_id']
    user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
    
    conn = None
    try:
        # Create or retrieve Stripe customer
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Check if user already has a Stripe customer ID in subscriptions table
        cursor.execute(f"""
            SELECT stripe_customer_id FROM subscriptions 
            WHERE user_id = {placeholder} 
            LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            customer_id = result[0]
            logger.info(f"Found existing customer ID in database: {customer_id}")
        else:
            # Check if customer already exists in Stripe by email
            existing_customers = stripe.Customer.list(email=user_email, limit=1)
            if existing_customers.data:
                customer_id = existing_customers.data[0].id
                stripe.Customer.modify(customer_id, metadata={'user_id': str(user_id)})
                logger.info(f"Found existing Stripe customer: {customer_id}")
            else:
                customer = stripe.Customer.create(
                    email=user_email,
                    metadata={'user_id': str(user_id)}
                )
                customer_id = customer.id
                logger.info(f"Created new Stripe customer: {customer_id}")
        
        conn.close()
        conn = None
        
        # Create Checkout Session for Standard plan subscription
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': standard_price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=_base_url() + '/checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=_base_url() + '/dashboard',
            metadata={'user_id': str(user_id), 'type': 'subscription', 'plan': 'standard'}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        flash("❌ Payment error. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    except Exception as e:
        logger.error(f"Error creating Standard plan checkout: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@payments_bp.route("/checkout/addon", methods=["POST"])
@login_required
def create_addon_checkout():
    """Create Stripe Checkout session for one-time add-on purchase"""
    if not Config.STRIPE_SECRET_KEY or not Config.STRIPE_ADDON_PRICE_ID:
        flash("❌ Payment system is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    user_id = session['user_id']
    user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
    
    conn = None
    try:
        # Add-ons require any active plan (Free or paid)
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()

        cursor.execute(f"""
            SELECT stripe_customer_id, status, plan_type
            FROM subscriptions
            WHERE user_id = {placeholder} AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()

        if not result:
            flash("❌ You need an active plan to purchase add-ons. Activate the Free plan or subscribe first.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))

        customer_id, subscription_status, plan_type = result

        # Free plan rows use a synthetic stripe_customer_id ("free_cust_..."),
        # which Stripe Checkout will reject. Resolve a real cus_... id.
        if not customer_id or not customer_id.startswith('cus_'):
            real_customer_id = None

            # Re-use any real Stripe customer we already have for this user
            cursor.execute(f"""
                SELECT stripe_customer_id
                FROM subscriptions
                WHERE user_id = {placeholder} AND stripe_customer_id LIKE 'cus_%'
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id,))
            existing_real = cursor.fetchone()
            if existing_real and existing_real[0]:
                real_customer_id = existing_real[0]
                logger.info(f"Reusing existing real Stripe customer for free user {user_id}: {real_customer_id}")

            if not real_customer_id:
                try:
                    existing_customers = stripe.Customer.list(email=user_email, limit=1)
                    if existing_customers.data:
                        real_customer_id = existing_customers.data[0].id
                        stripe.Customer.modify(real_customer_id, metadata={'user_id': str(user_id)})
                        logger.info(f"Found existing Stripe customer by email for free user {user_id}: {real_customer_id}")
                except Exception as e:
                    logger.warning(f"Failed to lookup existing Stripe customer by email: {e}")

            if not real_customer_id:
                new_cust = stripe.Customer.create(email=user_email, metadata={'user_id': str(user_id)})
                real_customer_id = new_cust.id
                logger.info(f"Created new Stripe customer for free user {user_id}: {real_customer_id}")

            customer_id = real_customer_id

        conn.close()
        conn = None
        
        # Create Checkout Session for one-time payment
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': Config.STRIPE_ADDON_PRICE_ID,
                'quantity': 1,
            }],
            mode='payment',
            success_url=_base_url() + '/checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=_base_url() + '/dashboard',
            metadata={'user_id': str(user_id), 'type': 'addon'}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        flash("❌ Payment error. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    except Exception as e:
        logger.error(f"Error creating addon checkout: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@payments_bp.route("/checkout/success")
@login_required
def checkout_success():
    """Handle successful checkout"""
    session_id = request.args.get('session_id')
    
    if not session_id:
        flash("❌ Invalid checkout session.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        if checkout_session.metadata.get('user_id') != str(session['user_id']):
            flash("❌ Invalid checkout session.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        if checkout_session.metadata.get('type') == 'subscription':
            plan = checkout_session.metadata.get('plan', 'starter')
            if plan == 'standard':
                flash(f"Standard subscription activated successfully! You now have {Config.STANDARD_MONTHLY_REPLIES} replies per month.", "success")
            else:
                flash(f"Starter subscription activated successfully! You now have {Config.STARTER_MONTHLY_REPLIES} replies per month.", "success")
        elif checkout_session.metadata.get('type') == 'addon':
            flash(f"Payment successful! {Config.ADDON_REPLIES} additional replies have been added to your account.", "success")
        elif checkout_session.metadata.get('type') == 'upgrade':
            flash(f"Subscription upgraded successfully! You now have {Config.STANDARD_MONTHLY_REPLIES} replies per month.", "success")
        elif checkout_session.metadata.get('type') == 'downgrade':
            flash(f"Subscription downgraded successfully! You now have {Config.STARTER_MONTHLY_REPLIES} replies per month.", "success")
        
        return redirect(url_for('dashboard_bp.dashboard'))
        
    except Exception as e:
        logger.error(f"Error processing checkout success: {e}")
        flash("Payment processed. Please check your account.", "success")
        return redirect(url_for('dashboard_bp.dashboard'))


@payments_bp.route("/checkout/upgrade", methods=["POST"])
@login_required
def create_upgrade_checkout():
    """Upgrade from Starter to Standard plan"""
    if not Config.STRIPE_SECRET_KEY:
        flash("❌ Payment system is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    user_id = session['user_id']
    
    # Check if user has active Starter plan
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        cursor.execute(f"""
            SELECT stripe_subscription_id, stripe_customer_id, plan_type, status
            FROM subscriptions
            WHERE user_id = {placeholder} AND status = 'active' AND plan_type = 'starter'
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        subscription = cursor.fetchone()
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    
    if not subscription:
        flash("❌ No active Starter plan found to upgrade.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    subscription_id, customer_id, _, _ = subscription
    
    try:
        user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
        
        standard_price_id = Config.STRIPE_STANDARD_PLAN_PRICE_ID
        if not standard_price_id:
            flash("❌ Standard plan not configured. Please contact support.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': standard_price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=_base_url() + '/checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=_base_url() + '/dashboard',
            metadata={'user_id': str(user_id), 'type': 'upgrade', 'old_subscription_id': subscription_id}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error during upgrade: {e}")
        flash("❌ Upgrade error. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    except Exception as e:
        logger.error(f"Error during upgrade: {e}")
        flash("❌ An error occurred during upgrade. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))


@payments_bp.route("/checkout/downgrade", methods=["POST"])
@login_required
def create_downgrade_checkout():
    """Downgrade from Standard to Starter plan"""
    if not Config.STRIPE_SECRET_KEY:
        flash("❌ Payment system is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    user_id = session['user_id']
    
    # Check if user has active Standard plan
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        cursor.execute(f"""
            SELECT stripe_subscription_id, stripe_customer_id, plan_type, status
            FROM subscriptions
            WHERE user_id = {placeholder} AND status = 'active' AND plan_type = 'standard'
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        subscription = cursor.fetchone()
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    
    if not subscription:
        flash("❌ No active Standard plan found to downgrade.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    subscription_id, customer_id, _, _ = subscription
    
    try:
        user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
        
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': Config.STRIPE_STARTER_PLAN_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=_base_url() + '/checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=_base_url() + '/dashboard',
            metadata={'user_id': str(user_id), 'type': 'downgrade', 'old_subscription_id': subscription_id}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error during downgrade: {e}")
        flash("❌ Downgrade error. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    except Exception as e:
        logger.error(f"Error during downgrade: {e}")
        flash("❌ An error occurred during downgrade. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))


@payments_bp.route("/subscription/cancel", methods=["POST"])
@login_required
def cancel_subscription():
    """Cancel subscription - cancel at period end"""
    user_id = session['user_id']
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Get active subscription - get the most recent one
        cursor.execute(f"""
            SELECT stripe_subscription_id, plan_type
            FROM subscriptions
            WHERE user_id = {placeholder} AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        subscription = cursor.fetchone()
        
        if not subscription:
            flash("❌ No active subscription found.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        subscription_id, plan_type = subscription
        logger.info(f"Canceling subscription {subscription_id} (plan: {plan_type}) for user {user_id}")
        conn.close()
        conn = None
        
        # Cancel subscription in Stripe FIRST — only update DB if Stripe succeeds
        try:
            stripe.Subscription.delete(subscription_id)
            logger.info(f"Immediately canceled subscription {subscription_id} in Stripe")
        except Exception as e:
            logger.error(f"Failed to cancel subscription in Stripe: {e}")
            flash("Could not cancel your subscription. Please try again or contact support.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        # Stripe cancellation succeeded — now update DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE subscriptions 
            SET status = {placeholder},
                updated_at = CURRENT_TIMESTAMP
            WHERE stripe_subscription_id = {placeholder}
        """, ('canceled', subscription_id))
        conn.commit()
        logger.info(f"Marked subscription {subscription_id} as canceled in DB (plan_type '{plan_type}' preserved)")
        
        flash("Subscription canceled. You can still use your remaining replies, but cannot purchase add-ons.", "success")
        return redirect(url_for('dashboard_bp.dashboard'))
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error canceling subscription: {e}")
        flash("❌ Error canceling subscription. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    except Exception as e:
        logger.error(f"Error canceling subscription: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


FREE_PLAN_SUB_PREFIX = "free_"


def _free_subscription_id(user_id):
    """Synthetic id for the Free plan row (no Stripe)."""
    return f"{FREE_PLAN_SUB_PREFIX}{user_id}"


def _user_has_paid_history(cursor, user_id):
    """True if user ever had a paid subscription row (any status)."""
    placeholder = get_param_placeholder()
    cursor.execute(f"""
        SELECT 1 FROM subscriptions
        WHERE user_id = {placeholder}
          AND plan_type IN ('starter', 'standard')
        LIMIT 1
    """, (user_id,))
    return cursor.fetchone() is not None


def _switch_user_to_free(cursor, user_id, grant_monthly: bool):
    """Move all currently remaining replies into purchased.

    - grant_monthly=True  -> first-time Free activation: set monthly = 200 and reset cycle.
    - grant_monthly=False -> downgrade-to-Free path: monthly = 0, leave last_monthly_reset
      alone so the next calendar-month boundary refills monthly to 200 naturally.
    """
    placeholder = get_param_placeholder()
    cursor.execute(f"""
        SELECT COALESCE(replies_limit_monthly, 0),
               COALESCE(replies_sent_monthly, 0),
               COALESCE(replies_purchased, 0),
               COALESCE(replies_used_purchased, 0)
        FROM users WHERE id = {placeholder}
    """, (user_id,))
    row = cursor.fetchone()
    if not row:
        return 0
    m_limit, m_sent, p_total, p_used = row
    carryover = max(0, int(m_limit) - int(m_sent)) + max(0, int(p_total) - int(p_used))

    if grant_monthly:
        cursor.execute(f"""
            UPDATE users
            SET replies_purchased = {placeholder},
                replies_used_purchased = 0,
                replies_limit_monthly = {placeholder},
                replies_sent_monthly = 0,
                last_monthly_reset = CURRENT_TIMESTAMP,
                last_warning_threshold = NULL,
                last_warning_sent_at = NULL
            WHERE id = {placeholder}
        """, (carryover, Config.FREE_MONTHLY_REPLIES, user_id))
    else:
        cursor.execute(f"""
            UPDATE users
            SET replies_purchased = {placeholder},
                replies_used_purchased = 0,
                replies_limit_monthly = 0,
                replies_sent_monthly = 0,
                last_warning_threshold = NULL,
                last_warning_sent_at = NULL
            WHERE id = {placeholder}
        """, (carryover, user_id))
    return carryover


def _ensure_free_subscription_row(cursor, user_id):
    """Insert (or reactivate) the synthetic Free subscription row."""
    placeholder = get_param_placeholder()
    free_sub_id = _free_subscription_id(user_id)
    free_customer_id = f"{FREE_PLAN_SUB_PREFIX}cust_{user_id}"
    free_price_id = "free"
    now_dt = datetime.now()

    cursor.execute(f"""
        SELECT id FROM subscriptions WHERE stripe_subscription_id = {placeholder}
    """, (free_sub_id,))
    existing = cursor.fetchone()
    if existing:
        cursor.execute(f"""
            UPDATE subscriptions
            SET status = 'active',
                plan_type = 'free',
                current_period_start = {placeholder},
                current_period_end = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE stripe_subscription_id = {placeholder}
        """, (now_dt, free_sub_id))
    else:
        cursor.execute(f"""
            INSERT INTO subscriptions
            (user_id, stripe_subscription_id, stripe_customer_id, stripe_price_id,
             plan_type, status, current_period_start, current_period_end)
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder},
                    {placeholder}, {placeholder}, {placeholder}, NULL)
        """, (user_id, free_sub_id, free_customer_id, free_price_id,
              'free', 'active', now_dt))


@payments_bp.route("/checkout/free", methods=["POST"])
@login_required
def activate_free_plan():
    """Activate the Free plan — no Stripe.

    - First-time activation (no paid history): grants 200 monthly + carries
      over any existing remaining replies.
    - Returning user with paid history: preserves remaining replies, no
      immediate 200 grant. Next calendar-month boundary refills to 200.
    """
    user_id = session['user_id']
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()

        # Block if the user already has a paid active subscription
        cursor.execute(f"""
            SELECT plan_type FROM subscriptions
            WHERE user_id = {placeholder} AND status = 'active' AND plan_type != 'free'
            LIMIT 1
        """, (user_id,))
        if cursor.fetchone():
            flash("You already have an active paid plan. Use 'Downgrade to Free' from your dashboard.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))

        # Block if Free is already active
        cursor.execute(f"""
            SELECT id FROM subscriptions
            WHERE user_id = {placeholder} AND status = 'active' AND plan_type = 'free'
            LIMIT 1
        """, (user_id,))
        if cursor.fetchone():
            flash("You're already on the Free plan.", "info")
            return redirect(url_for('dashboard_bp.dashboard'))

        # Look up user existence
        cursor.execute(f"SELECT 1 FROM users WHERE id = {placeholder}", (user_id,))
        if not cursor.fetchone():
            flash("❌ User not found.", "error")
            return redirect(url_for('auth.login'))

        first_time = not _user_has_paid_history(cursor, user_id)
        carryover = _switch_user_to_free(cursor, user_id, grant_monthly=first_time)
        _ensure_free_subscription_row(cursor, user_id)
        conn.commit()

        if first_time:
            log_activity(
                user_id,
                'free_plan_activated',
                f'Free plan first-time activation: +{Config.FREE_MONTHLY_REPLIES} replies/month'
            )
            logger.info(
                f"Free plan first-time activation for user {user_id} "
                f"(+{Config.FREE_MONTHLY_REPLIES}, carried over {carryover})"
            )
            flash(
                f"Free plan activated! You have {Config.FREE_MONTHLY_REPLIES} replies. "
                f"Add-ons (€5 / +{Config.ADDON_REPLIES} replies) are available anytime.",
                "success"
            )
        else:
            log_activity(
                user_id,
                'free_plan_activated_from_paid',
                f'Free plan activated after paid history; preserved {carryover} replies, no immediate grant'
            )
            logger.info(
                f"Free plan activated for user {user_id} after paid history "
                f"(preserved {carryover}, no monthly grant until next reset)"
            )
            flash(
                f"You're on the Free plan. Your {carryover} remaining replies are preserved. "
                f"Your next 200 replies arrive at the start of next month.",
                "success"
            )
        return redirect(url_for('dashboard_bp.dashboard'))

    except Exception as e:
        logger.error(f"Error activating free plan for user {user_id}: {e}")
        flash("❌ An error occurred activating the free plan. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@payments_bp.route("/dashboard/downgrade-to-free", methods=["POST"])
@login_required
def downgrade_to_free():
    """Cancel the user's active paid subscription and switch them to Free.

    - Cancels the Stripe subscription server-side.
    - Preserves all currently remaining replies (moved into the purchased
      bucket) — no replies are ever lost.
    - Does NOT grant 200 immediately; the next calendar-month reset will
      refill monthly to 200.
    """
    user_id = session['user_id']
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()

        # Find the active paid subscription
        cursor.execute(f"""
            SELECT stripe_subscription_id, plan_type
            FROM subscriptions
            WHERE user_id = {placeholder}
              AND status = 'active'
              AND plan_type IN ('starter', 'standard')
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        sub = cursor.fetchone()
        if not sub:
            flash("You don't have an active paid plan to downgrade.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))

        stripe_sub_id, plan_type = sub
        conn.close()
        conn = None

        # Cancel in Stripe first — only mutate DB if Stripe succeeds
        try:
            stripe.Subscription.delete(stripe_sub_id)
            logger.info(f"Canceled Stripe subscription {stripe_sub_id} (downgrade-to-free) for user {user_id}")
        except stripe.error.InvalidRequestError as e:
            # Already canceled in Stripe — proceed with DB cleanup
            logger.warning(f"Stripe subscription may already be canceled: {e}")
        except Exception as e:
            logger.error(f"Stripe cancel failed for downgrade-to-free: {e}")
            flash("Could not cancel your subscription. Please try again or contact support.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))

        # Stripe is now canceled — update DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE subscriptions
            SET status = 'canceled', updated_at = CURRENT_TIMESTAMP
            WHERE stripe_subscription_id = {placeholder}
        """, (stripe_sub_id,))

        carryover = _switch_user_to_free(cursor, user_id, grant_monthly=False)
        _ensure_free_subscription_row(cursor, user_id)
        conn.commit()

        log_activity(
            user_id,
            'downgrade_to_free',
            f'Downgraded {plan_type} to Free; preserved {carryover} replies'
        )
        flash(
            f"You're on the Free plan. Your {carryover} remaining replies are preserved. "
            f"Your next 200 replies arrive at the start of next month.",
            "success"
        )
        return redirect(url_for('dashboard_bp.dashboard'))

    except Exception as e:
        logger.error(f"Error in downgrade_to_free: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
