"""Subscription service — reply limits, monthly resets, settings."""
import logging
from datetime import datetime
from database import get_db_connection, get_param_placeholder
from config import Config

logger = logging.getLogger("chata.services.subscription")


def check_user_reply_limit(user_id, conn=None):
    """
    Check if user has remaining replies available.
    
    Args:
        user_id: User ID
        conn: Optional database connection to reuse. If None, opens and closes its own connection.
    
    Returns: (has_limit: bool, remaining: int, total_used: int, total_available: int)
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    
    if not conn:
        return (False, 0, 0, 0)
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Get user's reply counts
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased, last_monthly_reset
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        
        result = cursor.fetchone()
        if not result:
            if should_close:
                conn.close()
            return (False, 0, 0, 0)
        
        replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased, last_monthly_reset = result
        
        # Reset monthly counter if new month - pass connection to avoid opening another one
        reset_monthly_replies_if_needed(user_id, replies_sent_monthly, last_monthly_reset, conn)
        
        # Re-fetch after potential reset
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        result = cursor.fetchone()
        replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased = result
        
        # Calculate remaining
        total_used = replies_sent_monthly + replies_used_purchased
        total_available = replies_limit_monthly + replies_purchased
        remaining = max(0, total_available - total_used)
        has_limit = remaining > 0
        
        if should_close:
            conn.close()
        return (has_limit, remaining, total_used, total_available)
        
    except Exception as e:
        logger.error(f"Error checking reply limit: {e}")
        if conn and should_close:
            conn.close()
        return (False, 0, 0, 0)

def reset_monthly_replies_if_needed(user_id, current_sent=None, last_reset=None, conn=None):
    """
    Reset monthly reply counter if a new month has started AND user has active subscription.
    
    Args:
        user_id: User ID
        current_sent: Current sent count (optional)
        last_reset: Last reset timestamp (optional)
        conn: Optional database connection to reuse. If None, opens and closes its own connection.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    
    if not conn:
        return False
    
    try:
        from datetime import datetime, timedelta
        
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
        
        # If no active subscription, don't reset monthly counter
        # User keeps their remaining replies but won't get new monthly allocation
        if not subscription:
            logger.info(f"User {user_id} has no active subscription - skipping monthly reset (keeping remaining replies)")
            if should_close:
                conn.close()
            return False
        
        # Get current reset timestamp if not provided
        if last_reset is None:
            cursor.execute(f"SELECT last_monthly_reset FROM users WHERE id = {placeholder}", (user_id,))
            result = cursor.fetchone()
            if not result:
                if should_close:
                    conn.close()
                return False
            last_reset = result[0]
        
        # Parse last_reset if it's a string or handle datetime object
        if isinstance(last_reset, str):
            try:
                # Try ISO format first
                last_reset = datetime.fromisoformat(last_reset.replace('Z', '+00:00'))
            except:
                try:
                    # Try standard format
                    last_reset = datetime.strptime(last_reset.split('.')[0], '%Y-%m-%d %H:%M:%S')
                except:
                    # Try date only
                    last_reset = datetime.strptime(last_reset.split(' ')[0], '%Y-%m-%d')
        elif not isinstance(last_reset, datetime):
            # If it's not a datetime object, try to convert it
            last_reset = datetime.now()
        
        # Check if we're in a new month
        now = datetime.now()
        # Handle timezone-aware datetime objects
        if hasattr(last_reset, 'replace') and hasattr(last_reset, 'tzinfo') and last_reset.tzinfo:
            last_reset = last_reset.replace(tzinfo=None)
        
        last_reset_month = last_reset.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        if current_month > last_reset_month:
            plan_type = subscription[1]  # 'starter' or 'standard'
            if plan_type == 'standard':
                monthly_limit = Config.STANDARD_MONTHLY_REPLIES
            else:
                monthly_limit = Config.STARTER_MONTHLY_REPLIES

            now = datetime.now()
            logger.info(f"New month detected for user {user_id} with {plan_type} plan, setting limit to {monthly_limit}")
            # Conditional WHERE prevents double-reset when concurrent requests both see the old month
            cursor.execute(f"""
                UPDATE users
                SET replies_sent_monthly = 0,
                    replies_limit_monthly = {placeholder},
                    last_monthly_reset = {placeholder}
                WHERE id = {placeholder}
                  AND (last_monthly_reset IS NULL OR last_monthly_reset < {placeholder})
            """, (monthly_limit, now, user_id, now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)))
            conn.commit()
            if should_close:
                conn.close()
            return True
        
        if should_close:
            conn.close()
        return False
        
    except Exception as e:
        logger.error(f"Error resetting monthly replies: {e}")
        if conn and should_close:
            conn.close()
        return False

def increment_reply_count(user_id, conn=None):
    """
    Increment the appropriate reply counter for a user.
    Uses monthly replies first, then purchased replies.
    
    Args:
        user_id: User ID
        conn: Optional database connection to reuse. If None, opens and closes its own connection.
    
    Returns: True if successful, False otherwise
    """
    from services.email import send_usage_warning_email

    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Atomic increment: try monthly first, then purchased.
        # The WHERE clause ensures we only increment if there's capacity,
        # preventing race conditions when multiple messages arrive simultaneously.
        
        # Try monthly replies first (atomic: only increments if sent < limit)
        cursor.execute(f"""
            UPDATE users
            SET replies_sent_monthly = replies_sent_monthly + 1
            WHERE id = {placeholder}
            AND replies_sent_monthly < replies_limit_monthly
        """, (user_id,))
        
        if cursor.rowcount > 0:
            conn.commit()
            # Re-fetch for logging
            cursor.execute(f"""
                SELECT replies_sent_monthly, replies_limit_monthly FROM users WHERE id = {placeholder}
            """, (user_id,))
            row = cursor.fetchone()
            if row:
                logger.info(f"Incremented monthly reply count for user {user_id} ({row[0]}/{row[1]})")
        else:
            # Try purchased replies (atomic: only increments if used < purchased)
            cursor.execute(f"""
                UPDATE users
                SET replies_used_purchased = replies_used_purchased + 1
                WHERE id = {placeholder}
                AND replies_used_purchased < replies_purchased
            """, (user_id,))
            
            if cursor.rowcount > 0:
                conn.commit()
                cursor.execute(f"""
                    SELECT replies_used_purchased, replies_purchased FROM users WHERE id = {placeholder}
                """, (user_id,))
                row = cursor.fetchone()
                if row:
                    logger.info(f"Incremented purchased reply count for user {user_id} ({row[0]}/{row[1]})")
            else:
                logger.warning(f"Attempted to increment reply count but user {user_id} has no remaining replies")
                if should_close:
                    conn.close()
                return False
        
        # Check if we need to send usage warning emails
        # Re-fetch to get updated counts
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased, email, last_warning_sent_at, last_warning_threshold
            FROM users
            WHERE id = {placeholder}
        """, (user_id,))
        
        result = cursor.fetchone()
        if result:
            replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased, user_email, last_warning_sent_at, last_warning_threshold = result
            
            total_used = replies_sent_monthly + replies_used_purchased
            total_available = replies_limit_monthly + replies_purchased
            remaining = max(0, total_available - total_used)
            
            # Determine which threshold we're at
            warning_threshold = None
            if remaining <= Config.REPLY_WARNING_THRESHOLD and remaining > 0:
                warning_threshold = Config.REPLY_WARNING_THRESHOLD
            elif remaining <= 100 and remaining > 50:
                warning_threshold = 100
            
            # Send warning if we hit a threshold and haven't sent one for this threshold recently
            if warning_threshold and user_email:
                # Only send if we haven't sent a warning for this threshold in the last 24 hours
                should_send = True
                if last_warning_sent_at and last_warning_threshold == warning_threshold:
                    try:
                        # Handle both string and datetime objects
                        if isinstance(last_warning_sent_at, str):
                            warning_time = datetime.fromisoformat(last_warning_sent_at.replace('Z', '+00:00'))
                        elif isinstance(last_warning_sent_at, datetime):
                            warning_time = last_warning_sent_at
                        else:
                            warning_time = datetime.now()  # Fallback
                        
                        # Calculate time difference safely
                        now = datetime.now()
                        if warning_time.tzinfo:
                            warning_time = warning_time.replace(tzinfo=None)
                        time_diff = now - warning_time
                        time_since_warning = time_diff.total_seconds()
                        if time_since_warning < 86400:  # 24 hours
                            should_send = False
                    except Exception as e:
                        logger.warning(f"Error parsing last_warning_sent_at: {e}")
                        # If we can't parse it, send the warning to be safe
                        should_send = True
                
                if should_send:
                    try:
                        send_usage_warning_email(user_email, remaining)
                        # Update last warning sent
                        cursor.execute(f"""
                            UPDATE users
                            SET last_warning_sent_at = {placeholder}, last_warning_threshold = {placeholder}
                            WHERE id = {placeholder}
                        """, (datetime.now().isoformat(), warning_threshold, user_id))
                        conn.commit()
                        logger.info(f"Sent usage warning email to user {user_id} ({remaining} replies remaining)")
                    except Exception as e:
                        logger.warning(f"Failed to send usage warning email: {e}")
        
        if should_close:
            conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Error incrementing reply count: {e}")
        if conn and should_close:
            conn.close()
        return False

def add_purchased_replies(user_id, amount, payment_provider=None, payment_id=None):
    """
    Add purchased replies to a user's account.
    For Stripe integration: call this when payment is confirmed.
    Returns: True if successful, False otherwise
    """
    # TESTING MODE: 1€ = 5 replies (for testing)
    # PRODUCTION: 5€ = 150 replies (REPLIES_PER_EURO = 30)
    # For Stripe add-on: €5 = 150 replies (fixed)
    if payment_provider == "stripe":
        # Stripe add-on is always €5 for 150 replies
        replies_to_add = Config.ADDON_REPLIES
    else:
        # Test mode: 1€ = 5 replies
        REPLIES_PER_EURO = 5
        replies_to_add = int(amount * REPLIES_PER_EURO)
    
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Add to user's purchased replies
        cursor.execute(f"""
            UPDATE users
            SET replies_purchased = replies_purchased + {placeholder}
            WHERE id = {placeholder}
        """, (replies_to_add, user_id))
        
        # Record purchase
        cursor.execute(f"""
            INSERT INTO purchases (user_id, amount_paid, replies_added, payment_provider, payment_id, status)
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 'completed')
        """, (user_id, amount, replies_to_add, payment_provider, payment_id))
        
        conn.commit()
        logger.info(f"Added {replies_to_add} purchased replies for user {user_id} (EUR{amount})")
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Error adding purchased replies: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False

# ---- Global settings (delegated to services.settings) ----
from services.settings import get_setting, set_setting  # noqa: F401 - re-export for callers
