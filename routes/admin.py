"""Admin routes — admin dashboard, cleanup, system verification."""
import logging
from flask import Blueprint, request, render_template, redirect, url_for, flash, session
import os
import traceback
import stripe
from config import Config

logger = logging.getLogger("chata.routes.admin")
from database import get_db_connection, get_param_placeholder
from services.auth import admin_required

admin_bp = Blueprint('admin', __name__)


@admin_bp.route("/payment-system-verification")
@admin_required
def payment_system_verification():
    """Comprehensive payment system verification and checkup"""
    from datetime import datetime
    
    checks = {
        'stripe_config': {},
        'database_structure': {},
        'webhook_config': {},
        'reply_logic': {},
        'subscriptions': {},
        'environment': {}
    }
    
    # 1. Stripe Configuration Checks
    stripe_checks = []
    stripe_ok = True
    
    if Config.STRIPE_SECRET_KEY:
        stripe_checks.append(('✅', 'STRIPE_SECRET_KEY', 'Set'))
        try:
            stripe.api_key = Config.STRIPE_SECRET_KEY
            stripe.Account.retrieve()  # Test connection
            stripe_checks.append(('✅', 'Stripe API Connection', 'Working'))
        except Exception as e:
            stripe_checks.append(('❌', 'Stripe API Connection', f'Failed: {str(e)[:50]}'))
            stripe_ok = False
    else:
        stripe_checks.append(('❌', 'STRIPE_SECRET_KEY', 'Missing'))
        stripe_ok = False
    
    stripe_checks.append(('✅' if Config.STRIPE_PUBLISHABLE_KEY else '❌', 'STRIPE_PUBLISHABLE_KEY', 'Set' if Config.STRIPE_PUBLISHABLE_KEY else 'Missing'))
    stripe_checks.append(('✅' if Config.STRIPE_WEBHOOK_SECRET else '❌', 'STRIPE_WEBHOOK_SECRET', 'Set' if Config.STRIPE_WEBHOOK_SECRET else 'Missing'))
    
    # Price IDs
    starter_price_id = Config.STRIPE_STARTER_PLAN_PRICE_ID or os.getenv("STRIPE_STARTER_PLAN_PRICE_ID")
    standard_price_id = Config.STRIPE_STANDARD_PLAN_PRICE_ID or os.getenv("STRIPE_STANDARD_PLAN_PRICE_ID")
    addon_price_id = Config.STRIPE_ADDON_PRICE_ID or os.getenv("STRIPE_ADDON_PRICE_ID")
    
    stripe_checks.append(('✅' if starter_price_id else '❌', 'Starter Plan Price ID', starter_price_id[:20] + '...' if starter_price_id else 'Missing'))
    stripe_checks.append(('✅' if standard_price_id else '❌', 'Standard Plan Price ID', standard_price_id[:20] + '...' if standard_price_id else 'Missing'))
    stripe_checks.append(('✅' if addon_price_id else '❌', 'Add-on Price ID', addon_price_id[:20] + '...' if addon_price_id else 'Missing'))
    
    checks['stripe_config'] = {'checks': stripe_checks, 'all_ok': stripe_ok}
    
    # 2. Database Structure Checks
    db_checks = []
    db_ok = True
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if tables exist
        is_postgres = Config.DATABASE_URL and ('postgres' in Config.DATABASE_URL.lower())
        
        if is_postgres:
            cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')")
            users_exists = cursor.fetchone()[0]
            cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'subscriptions')")
            subs_exists = cursor.fetchone()[0]
        else:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            users_exists = cursor.fetchone() is not None
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subscriptions'")
            subs_exists = cursor.fetchone() is not None
        
        db_checks.append(('✅' if users_exists else '❌', 'Users Table', 'Exists' if users_exists else 'Missing'))
        db_checks.append(('✅' if subs_exists else '❌', 'Subscriptions Table', 'Exists' if subs_exists else 'Missing'))
        
        if users_exists:
            if is_postgres:
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")
                columns = [row[0] for row in cursor.fetchall()]
            else:
                cursor.execute("PRAGMA table_info(users)")
                columns = [row[1] for row in cursor.fetchall()]
            
            required_columns = ['replies_sent_monthly', 'replies_limit_monthly', 'replies_purchased', 'replies_used_purchased', 'bot_paused']
            for col in required_columns:
                exists = col in columns
                db_checks.append(('✅' if exists else '❌', f'Users.{col}', 'Exists' if exists else 'Missing'))
                if not exists:
                    db_ok = False
    except Exception as e:
        db_checks.append(('❌', 'Database Connection', f'Error: {str(e)[:50]}'))
        db_ok = False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    
    checks['database_structure'] = {'checks': db_checks, 'all_ok': db_ok}
    
    # 3. Webhook Configuration
    webhook_checks = []
    webhook_url = f"{Config.BASE_URL}/webhook/stripe"
    webhook_checks.append(('ℹ️', 'Webhook URL', webhook_url))
    webhook_checks.append(('✅' if Config.STRIPE_WEBHOOK_SECRET else '❌', 'Webhook Secret', 'Set' if Config.STRIPE_WEBHOOK_SECRET else 'Missing'))
    checks['webhook_config'] = {'checks': webhook_checks, 'all_ok': True}
    
    # 4. Reply Logic Verification
    reply_checks = []
    reply_ok = True
    
    conn = None
    try:
        user_id = session['user_id']
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        cursor.execute(f"""
            SELECT replies_sent_monthly, replies_limit_monthly, replies_purchased, replies_used_purchased
            FROM users WHERE id = {placeholder}
        """, (user_id,))
        user_data = cursor.fetchone()
        
        if user_data:
            sent, limit, purchased, used_purchased = user_data
            total_available = limit + purchased
            total_used = sent + used_purchased
            remaining = max(0, total_available - total_used)
            
            reply_checks.append(('✅', 'Reply Calculation', f'Working (Remaining: {remaining})'))
            reply_checks.append(('ℹ️', 'Monthly Limit', f'{limit}'))
            reply_checks.append(('ℹ️', 'Purchased', f'{purchased}'))
            reply_checks.append(('ℹ️', 'Total Available', f'{total_available}'))
            reply_checks.append(('ℹ️', 'Total Used', f'{total_used}'))
        else:
            reply_checks.append(('❌', 'User Data', 'Not found'))
            reply_ok = False
    except Exception as e:
        reply_checks.append(('❌', 'Reply Logic Check', f'Error: {str(e)[:50]}'))
        reply_ok = False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    
    checks['reply_logic'] = {'checks': reply_checks, 'all_ok': reply_ok}
    
    # 5. Subscription Status
    sub_checks = []
    
    conn = None
    try:
        user_id = session['user_id']
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM subscriptions 
            WHERE user_id = {placeholder} AND status = 'active'
        """, (user_id,))
        active_count = cursor.fetchone()[0]
        
        cursor.execute(f"""
            SELECT COUNT(*) FROM subscriptions 
            WHERE user_id = {placeholder} AND status = 'canceled'
        """, (user_id,))
        canceled_count = cursor.fetchone()[0]
        
        cursor.execute(f"""
            SELECT plan_type, status, stripe_subscription_id, created_at
            FROM subscriptions 
            WHERE user_id = {placeholder}
            ORDER BY created_at DESC
            LIMIT 5
        """, (user_id,))
        recent_subs = cursor.fetchall()
        
        sub_checks.append(('ℹ️', 'Active Subscriptions', str(active_count)))
        sub_checks.append(('ℹ️', 'Canceled Subscriptions', str(canceled_count)))
        
        if recent_subs:
            sub_checks.append(('ℹ️', 'Recent Subscriptions', f'{len(recent_subs)} found'))
            for sub in recent_subs[:3]:
                plan, status, sub_id, created = sub
                status_icon = '✅' if status == 'active' else '❌'
                sub_checks.append((status_icon, f'{plan.title()} ({status})', f'ID: {sub_id[:20]}...'))
        else:
            sub_checks.append(('ℹ️', 'Recent Subscriptions', 'None found'))
    except Exception as e:
        sub_checks.append(('❌', 'Subscription Check', f'Error: {str(e)[:50]}'))
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    
    checks['subscriptions'] = {'checks': sub_checks, 'all_ok': True}
    
    # 6. Environment Variables Summary
    env_checks = []
    env_ok = True
    
    critical_vars = [
        'STRIPE_SECRET_KEY',
        'STRIPE_PUBLISHABLE_KEY',
        'STRIPE_WEBHOOK_SECRET',
        'STRIPE_STARTER_PLAN_PRICE_ID',
        'STRIPE_STANDARD_PLAN_PRICE_ID',
        'STRIPE_ADDON_PRICE_ID'
    ]
    
    for var in critical_vars:
        value = os.getenv(var)
        exists = value is not None and value != ''
        env_checks.append(('✅' if exists else '❌', var, 'Set' if exists else 'Missing'))
        if not exists:
            env_ok = False
    
    checks['environment'] = {'checks': env_checks, 'all_ok': env_ok}
    
    # Calculate overall status
    overall_ok = all([
        checks['stripe_config']['all_ok'],
        checks['database_structure']['all_ok'],
        checks['reply_logic']['all_ok'],
        checks['environment']['all_ok']
    ])
    
    # Generate HTML
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Payment System Verification</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background: #0a0a0a;
                color: #fff;
                padding: 20px;
                line-height: 1.6;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            h1 {{
                color: #4a90e2;
                border-bottom: 2px solid #4a90e2;
                padding-bottom: 10px;
            }}
            .section {{
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
            }}
            .section h2 {{
                color: #51cf66;
                margin-top: 0;
            }}
            .check-item {{
                display: flex;
                align-items: center;
                padding: 8px;
                margin: 5px 0;
                background: rgba(255, 255, 255, 0.02);
                border-radius: 4px;
            }}
            .check-item span:first-child {{
                font-size: 20px;
                margin-right: 10px;
                width: 30px;
            }}
            .status-badge {{
                display: inline-block;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                margin: 20px 0;
            }}
            .status-ok {{
                background: #51cf66;
                color: #000;
            }}
            .status-error {{
                background: #ff6b6b;
                color: #fff;
            }}
            .back-link {{
                display: inline-block;
                margin-top: 20px;
                padding: 10px 20px;
                background: #4a90e2;
                color: #fff;
                text-decoration: none;
                border-radius: 5px;
            }}
            .back-link:hover {{
                background: #357abd;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>💰 Payment System Verification</h1>
            <div class="status-badge {'status-ok' if overall_ok else 'status-error'}">
                {'✅ All Systems Operational' if overall_ok else '❌ Issues Detected'}
            </div>
            
            <div class="section">
                <h2>1. Stripe Configuration</h2>
                {'<p style="color: #51cf66;">✅ All Stripe configuration is correct.</p>' if checks['stripe_config']['all_ok'] else '<p style="color: #ff6b6b;">❌ Some Stripe configuration is missing or incorrect.</p>'}
                {'<br>'.join([f'<div class="check-item"><span>{icon}</span><span><strong>{name}:</strong> {status}</span></div>' for icon, name, status in checks['stripe_config']['checks']])}
            </div>
            
            <div class="section">
                <h2>2. Database Structure</h2>
                {'<p style="color: #51cf66;">✅ Database structure is correct.</p>' if checks['database_structure']['all_ok'] else '<p style="color: #ff6b6b;">❌ Database structure issues detected.</p>'}
                {'<br>'.join([f'<div class="check-item"><span>{icon}</span><span><strong>{name}:</strong> {status}</span></div>' for icon, name, status in checks['database_structure']['checks']])}
            </div>
            
            <div class="section">
                <h2>3. Webhook Configuration</h2>
                {'<br>'.join([f'<div class="check-item"><span>{icon}</span><span><strong>{name}:</strong> {status}</span></div>' for icon, name, status in checks['webhook_config']['checks']])}
            </div>
            
            <div class="section">
                <h2>4. Reply Counting Logic</h2>
                {'<p style="color: #51cf66;">✅ Reply counting logic is working correctly.</p>' if checks['reply_logic']['all_ok'] else '<p style="color: #ff6b6b;">❌ Reply counting logic has issues.</p>'}
                {'<br>'.join([f'<div class="check-item"><span>{icon}</span><span><strong>{name}:</strong> {status}</span></div>' for icon, name, status in checks['reply_logic']['checks']])}
            </div>
            
            <div class="section">
                <h2>5. Subscription Status</h2>
                {'<br>'.join([f'<div class="check-item"><span>{icon}</span><span><strong>{name}:</strong> {status}</span></div>' for icon, name, status in checks['subscriptions']['checks']])}
            </div>
            
            <div class="section">
                <h2>6. Environment Variables</h2>
                {'<p style="color: #51cf66;">✅ All critical environment variables are set.</p>' if checks['environment']['all_ok'] else '<p style="color: #ff6b6b;">❌ Some environment variables are missing.</p>'}
                {'<br>'.join([f'<div class="check-item"><span>{icon}</span><span><strong>{name}:</strong> {status}</span></div>' for icon, name, status in checks['environment']['checks']])}
            </div>
            
            <a href="/dashboard" class="back-link">← Back to Dashboard</a>
        </div>
    </body>
    </html>
    """
    
    return html



@admin_bp.route("/admin/clean-all-users", methods=["POST"])
@admin_required
def clean_all_users():
    """Delete all users and related data - requires admin privileges."""
    
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            flash("Database connection failed.", "error")
            return redirect(url_for('admin.admin_dashboard'))
        
        cursor = conn.cursor()
        
        # Delete in order to respect foreign key constraints
        for table in ['activity_logs', 'purchases', 'subscriptions', 'messages',
                      'client_settings', 'instagram_connections', 'password_resets', 'usage_logs']:
            try:
                cursor.execute(f"DELETE FROM {table}")
                logger.info(f"Deleted all {table}")
            except Exception as e:
                logger.warning(f"Could not delete {table}: {e}")
        
        # Finally, delete all users
        cursor.execute("DELETE FROM users")
        deleted_count = cursor.rowcount
        logger.info(f"Deleted {deleted_count} users")
        
        conn.commit()
        
        flash(f"Successfully cleaned database. Deleted {deleted_count} users and all related data.", "success")
        return redirect(url_for('admin.admin_dashboard'))
        
    except Exception as e:
        logger.error(f"Error cleaning database: {e}")
        logger.error(traceback.format_exc())
        flash("Error cleaning database. Please check logs.", "error")
        return redirect(url_for('admin.admin_dashboard'))
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@admin_bp.route("/admin/chata-internal-dashboard-2024-secure")
@admin_required
def admin_dashboard():
    """Admin dashboard - requires login and admin privileges."""
    logger.info(f"[ADMIN] Admin dashboard accessed via secret URL: {request.path}")
    
    # Get pagination parameters
    users_page = request.args.get('users_page', 1, type=int)
    logs_page = request.args.get('logs_page', 1, type=int)
    users_per_page = 10
    logs_per_page = 10
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = get_param_placeholder()
        
        # Check if using PostgreSQL
        database_url = os.environ.get('DATABASE_URL')
        is_postgres = bool(database_url and (database_url.startswith('postgres://') or database_url.startswith('postgresql://')))
        
        # Get total users count
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        # Get users with active subscriptions
        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) 
            FROM subscriptions 
            WHERE status = 'active'
        """)
        active_subscribers = cursor.fetchone()[0]
        
        # Get users with pagination (limit to 50 total, show 10 per page)
        total_users_to_show = min(50, total_users)
        users_offset = (users_page - 1) * users_per_page
        
        if is_postgres:
            cursor.execute("""
                SELECT 
                    id, username, email, 
                    replies_sent_monthly, 
                    replies_limit_monthly, 
                    replies_purchased, 
                    replies_used_purchased,
                    bot_paused,
                    created_at
                FROM users
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (min(users_per_page, total_users_to_show - users_offset), users_offset))
        else:
            cursor.execute("""
                SELECT 
                    id, username, email, 
                    replies_sent_monthly, 
                    replies_limit_monthly, 
                    replies_purchased, 
                    replies_used_purchased,
                    bot_paused,
                    created_at
                FROM users
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (min(users_per_page, total_users_to_show - users_offset), users_offset))
        users_data = cursor.fetchall()
        
        # Calculate users pagination
        total_users_pages = (total_users_to_show + users_per_page - 1) // users_per_page
        
        # Get all subscriptions
        cursor.execute("""
            SELECT 
                id, user_id, stripe_subscription_id, stripe_customer_id,
                plan_type, status, 
                current_period_start, current_period_end,
                created_at, updated_at
            FROM subscriptions
            ORDER BY updated_at DESC
        """)
        subscriptions_data = cursor.fetchall()
        
        # Get Instagram connections
        cursor.execute("""
            SELECT 
                id, user_id, instagram_user_id, instagram_page_id,
                is_active, created_at
            FROM instagram_connections
            ORDER BY created_at DESC
        """)
        connections_data = cursor.fetchall()
        
        # Get recent purchases
        cursor.execute("""
            SELECT 
                id, user_id, amount_paid, replies_added,
                payment_provider, payment_id, status, created_at
            FROM purchases
            ORDER BY created_at DESC
            LIMIT 50
        """)
        purchases_data = cursor.fetchall()
        
        # Get activity logs with pagination (limit to 50 total, show 10 per page)
        cursor.execute("SELECT COUNT(*) FROM activity_logs")
        total_logs = cursor.fetchone()[0]
        total_logs_to_show = min(50, total_logs)
        logs_offset = (logs_page - 1) * logs_per_page
        
        if is_postgres:
            cursor.execute("""
                SELECT 
                    id, user_id, action, details, ip_address, created_at
                FROM activity_logs
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (min(logs_per_page, total_logs_to_show - logs_offset), logs_offset))
        else:
            cursor.execute("""
                SELECT 
                    id, user_id, action, details, ip_address, created_at
                FROM activity_logs
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (min(logs_per_page, total_logs_to_show - logs_offset), logs_offset))
        activity_logs = cursor.fetchall()
        
        # Calculate logs pagination
        total_logs_pages = (total_logs_to_show + logs_per_page - 1) // logs_per_page
        
        # Format data for template (DB data already fetched, conn will be closed in finally)
        users = []
        for row in users_data:
            users.append({
                'id': row[0],
                'username': row[1],
                'email': row[2],
                'replies_sent_monthly': row[3],
                'replies_limit_monthly': row[4],
                'replies_purchased': row[5],
                'replies_used_purchased': row[6],
                'bot_paused': row[7],
                'created_at': row[8]
            })
        
        subscriptions = []
        for row in subscriptions_data:
            subscriptions.append({
                'id': row[0],
                'user_id': row[1],
                'stripe_subscription_id': row[2],
                'stripe_customer_id': row[3],
                'plan_type': row[4],
                'status': row[5],
                'current_period_start': row[6],
                'current_period_end': row[7],
                'created_at': row[8],
                'updated_at': row[9]
            })
        
        connections = []
        for row in connections_data:
            connections.append({
                'id': row[0],
                'user_id': row[1],
                'instagram_user_id': row[2],
                'instagram_page_id': row[3],
                'is_active': row[4],
                'created_at': row[5]
            })
        
        purchases = []
        for row in purchases_data:
            purchases.append({
                'id': row[0],
                'user_id': row[1],
                'amount_paid': row[2],
                'replies_added': row[3],
                'payment_provider': row[4],
                'payment_id': row[5],
                'status': row[6],
                'created_at': row[7]
            })
        
        logs = []
        for row in activity_logs:
            logs.append({
                'id': row[0],
                'user_id': row[1],
                'action': row[2],
                'details': row[3],
                'ip_address': row[4],
                'created_at': row[5]
            })
        
        return render_template('admin_dashboard.html',
                             total_users=total_users,
                             active_subscribers=active_subscribers,
                             users=users,
                             subscriptions=subscriptions,
                             connections=connections,
                             purchases=purchases,
                             activity_logs=logs,
                             users_page=users_page,
                             total_users_pages=total_users_pages,
                             logs_page=logs_page,
                             total_logs_pages=total_logs_pages,
                             total_users_to_show=total_users_to_show)
        
    except Exception as e:
        logger.error(f"Admin dashboard error: {e}")
        logger.error(traceback.format_exc())
        return "Error loading admin dashboard. Please check logs.", 500
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


