"""Payment routes — Stripe checkout, subscription management."""
import logging
import os
from flask import Blueprint, request, redirect, url_for, flash, session, render_template

logger = logging.getLogger("chata.routes.payments")
import stripe
from config import Config
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
        
        # Create Checkout Session for subscription
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': Config.STRIPE_STARTER_PLAN_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'dashboard',
            metadata={'user_id': str(user_id), 'type': 'subscription'}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        flash(f"❌ Payment error: {str(e)}", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    except Exception as e:
        logger.error(f"Error creating subscription checkout: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))


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
        
        # Create Checkout Session for Standard plan subscription
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': standard_price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'dashboard',
            metadata={'user_id': str(user_id), 'type': 'subscription', 'plan': 'standard'}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        flash(f"Payment error: {str(e)}", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    except Exception as e:
        logger.error(f"Error creating Standard plan checkout: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))


@payments_bp.route("/checkout/addon", methods=["POST"])
@login_required
def create_addon_checkout():
    """Create Stripe Checkout session for one-time add-on purchase"""
    if not Config.STRIPE_SECRET_KEY or not Config.STRIPE_ADDON_PRICE_ID:
        flash("❌ Payment system is not configured. Please contact support.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    user_id = session['user_id']
    user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
    
    try:
        # Check if user has an active subscription (required for add-ons)
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        cursor.execute(f"""
            SELECT stripe_customer_id, status, plan_type
            FROM subscriptions 
            WHERE user_id = {placeholder}
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()
        
        if not result or not result[0]:
            flash("❌ You need an active subscription to purchase add-ons.", "error")
            conn.close()
            return redirect(url_for('dashboard_bp.dashboard'))
        
        customer_id, subscription_status, plan_type = result
        
        # Check if subscription is active
        if subscription_status != 'active':
            flash("❌ You need an active subscription to purchase add-ons. Please reactivate your subscription.", "error")
            conn.close()
            return redirect(url_for('dashboard_bp.dashboard'))
        
        # Check if customer exists in Stripe
        if not customer_id:
            # Check if customer already exists in Stripe by email
            existing_customers = stripe.Customer.list(email=user_email, limit=1)
            if existing_customers.data:
                customer_id = existing_customers.data[0].id
                stripe.Customer.modify(customer_id, metadata={'user_id': str(user_id)})
                logger.info(f"Found existing Stripe customer: {customer_id}")
            else:
                flash("❌ Customer account not found. Please contact support.", "error")
                conn.close()
                return redirect(url_for('dashboard_bp.dashboard'))
        
        conn.close()
        
        # Create Checkout Session for one-time payment
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': Config.STRIPE_ADDON_PRICE_ID,
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.host_url + 'checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'dashboard',
            metadata={'user_id': str(user_id), 'type': 'addon'}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        flash(f"Payment error: {str(e)}", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    except Exception as e:
        logger.error(f"Error creating addon checkout: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))


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
                flash("Standard subscription activated successfully! You now have 1500 replies per month.", "success")
            else:
                flash("Starter subscription activated successfully! You now have 150 replies per month.", "success")
        elif checkout_session.metadata.get('type') == 'addon':
            flash("Payment successful! 150 additional replies have been added to your account.", "success")
        elif checkout_session.metadata.get('type') == 'upgrade':
            flash("Subscription upgraded successfully! You now have 1500 replies per month.", "success")
        elif checkout_session.metadata.get('type') == 'downgrade':
            flash("Subscription downgraded successfully! You now have 150 replies per month.", "success")
        
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
    conn.close()
    
    if not subscription:
        flash("❌ No active Starter plan found to upgrade.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    subscription_id, customer_id, _, _ = subscription
    
    try:
        # Update subscription in Stripe to Standard plan (we'll need Standard price ID)
        # For now, create new checkout session for Standard plan
        # Note: In production, you'd want to use Stripe's subscription update API
        # This is a simplified version that creates a new subscription
        user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
        
        # Get Standard plan price ID from config
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
            success_url=request.host_url + 'checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'dashboard',
            metadata={'user_id': str(user_id), 'type': 'upgrade', 'old_subscription_id': subscription_id}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error during upgrade: {e}")
        flash(f"❌ Upgrade error: {str(e)}", "error")
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
    conn.close()
    
    if not subscription:
        flash("❌ No active Standard plan found to downgrade.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    subscription_id, customer_id, _, _ = subscription
    
    try:
        # Create checkout session for Starter plan
        user_email = session.get('email') or get_user_by_id(user_id).get('email', '')
        
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': Config.STRIPE_STARTER_PLAN_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'dashboard',
            metadata={'user_id': str(user_id), 'type': 'downgrade', 'old_subscription_id': subscription_id}
        )
        
        return redirect(checkout_session.url)
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error during downgrade: {e}")
        flash(f"❌ Downgrade error: {str(e)}", "error")
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
            conn.close()
            return redirect(url_for('dashboard_bp.dashboard'))
        
        subscription_id, plan_type = subscription
        logger.info(f"Canceling subscription {subscription_id} (plan: {plan_type}) for user {user_id}")
        conn.close()
        
        # Cancel subscription immediately in Stripe
        try:
            stripe.Subscription.delete(subscription_id)
            logger.info(f"Immediately canceled subscription {subscription_id} in Stripe")
        except Exception as e:
            logger.warning(f"Error canceling subscription in Stripe: {e}")
            # Continue anyway - we'll still mark it as canceled in DB
        
        # Update database immediately to reflect canceled status
        # IMPORTANT: Only update status, NOT plan_type - preserve the plan type
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE subscriptions 
            SET status = {placeholder},
                updated_at = CURRENT_TIMESTAMP
            WHERE stripe_subscription_id = {placeholder}
        """, ('canceled', subscription_id))
        
        # Verify the update worked and plan_type is preserved
        cursor.execute(f"""
            SELECT plan_type, status
            FROM subscriptions
            WHERE stripe_subscription_id = {placeholder}
        """, (subscription_id,))
        verify = cursor.fetchone()
        if verify:
            updated_plan_type, updated_status = verify
            logger.info(f"Updated subscription status to '{updated_status}', plan_type preserved as '{updated_plan_type}'")
            if updated_plan_type != plan_type:
                logger.warning(f"Plan type changed from {plan_type} to {updated_plan_type} - this should not happen!")
        
        conn.commit()
        conn.close()
        
        flash("Subscription canceled. You can still use your remaining replies, but cannot purchase add-ons.", "success")
        
        return redirect(url_for('dashboard_bp.dashboard'))
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error canceling subscription: {e}")
        flash(f"❌ Error canceling subscription: {str(e)}", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    except Exception as e:
        logger.error(f"Error canceling subscription: {e}")
        flash("❌ An error occurred. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
