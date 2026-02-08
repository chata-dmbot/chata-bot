"""Auth routes — signup, login, logout, password reset, Instagram OAuth."""
import logging
import secrets
import traceback

from flask import Blueprint, request, render_template, redirect, url_for, flash, session, jsonify

logger = logging.getLogger("chata.routes.auth")
import requests as http_requests
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from database import get_db_connection, get_param_placeholder
from services.auth import login_required, create_reset_token, verify_reset_token, mark_reset_token_used
from services.users import get_user_by_email, get_user_by_username_or_email, get_user_by_username, create_user, get_user_by_id
from services.email import send_reset_email, send_welcome_email
from services.activity import log_activity
from services.instagram import discover_instagram_user_id

auth_bp = Blueprint('auth', __name__)

from extensions import limiter


# ── signup ────────────────────────────────────────────────────────────────

@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("10 per 5 minutes")  # Rate limit: 10 signup attempts per 5 minutes per IP
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password")
        
        logger.debug(f"Signup form data:")
        logger.debug(f"Username: {username}")
        logger.debug(f"Email: {email}")
        
        # Basic validation
        if not username or not email or not password:
            flash("Username, email, and password are required.", "error")
            return render_template("signup.html", form_username=username, form_email=email)
        
        # Validate username (alphanumeric and underscore, 3-20 characters)
        if not username.replace('_', '').replace('-', '').isalnum() or len(username) < 3 or len(username) > 20:
            flash("Username must be 3-20 characters and contain only letters, numbers, underscores, or hyphens.", "error")
            return render_template("signup.html", form_username=username, form_email=email)
        
        # Validate password strength (8+ characters, at least 1 number)
        if len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return render_template("signup.html", form_username=username, form_email=email)
        if not any(c.isdigit() for c in password):
            flash("Password must contain at least one number.", "error")
            return render_template("signup.html", form_username=username, form_email=email)
        
        # Check if username already exists (case-insensitive)
        existing_username = get_user_by_username(username)
        if existing_username:
            logger.debug(f"Signup rejected: username {username!r} already taken by user id={existing_username['id']} email={existing_username['email']!r}")
            flash("This username is already taken. Please choose another one.", "error")
            return render_template("signup.html", form_username=username, form_email=email)
        
        # Check if email already exists
        existing_email = get_user_by_email(email)
        if existing_email:
            flash("An account with this email already exists.", "error")
            return render_template("signup.html", form_username=username, form_email=email)
        
        # Create new user
        try:
            user_id = create_user(username, email, password)
            session['user_id'] = user_id
            
            # Get user data for welcome message
            user = get_user_by_id(user_id)
            
            # Send welcome email
            try:
                send_welcome_email(email)
            except Exception as e:
                logger.warning(f"Failed to send welcome email: {e}")
            
            flash(f"Account created successfully! Welcome to Chata, {username}!", "success")
            return redirect(url_for('dashboard_bp.dashboard'))
        except ValueError as e:
            if str(e) == "username_taken":
                flash("This username is already taken. Please choose another one.", "error")
                return render_template("signup.html", form_username=username, form_email=email)
            raise
        except Exception as e:
            logger.error(f"Signup error: {e}")
            flash("Error creating account. Please try again.", "error")
            return render_template("signup.html", form_username=username, form_email=email)
    
    return render_template("signup.html")


# ── login ─────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")  # Rate limit: 10 login attempts per minute per IP
def login():
    if request.method == "POST":
        username_or_email = request.form.get("username_or_email", "").strip()
        password = request.form.get("password")
        
        if not username_or_email or not password:
            flash("Username/Email and password are required.", "error")
            return render_template("login.html")
        
        try:
            user = get_user_by_username_or_email(username_or_email)
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                log_activity(user['id'], 'login', 'User logged in successfully')
                flash(f"Welcome back, {user['username']}!", "success")
                return redirect(url_for('dashboard_bp.dashboard'))
            else:
                flash("Invalid username/email or password.", "error")
        except Exception as e:
            logger.error(f"Login error: {e}")
            flash("An error occurred during login. Please try again.", "error")
    
    return render_template("login.html")


# ── forgot password ───────────────────────────────────────────────────────

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per 15 minutes")  # Rate limit: 5 forgot-password attempts per 15 minutes per IP
def forgot_password():
    try:
        if request.method == "POST":
            email = request.form.get("email")
            
            logger.debug(f"Forgot password request for email: {email}")
            
            if not email:
                flash("Please enter your email address.", "error")
                return render_template("forgot_password.html")
            
            user = get_user_by_email(email)
            if user:
                logger.debug(f"User found: {user['email']}")
                # Create reset token and send email
                try:
                    reset_token = create_reset_token(user['id'])
                    logger.debug(f"Reset token created: {reset_token[:10]}...")
                    send_reset_email(email, reset_token)
                    logger.info(f"Email sent successfully to {email}")
                    flash("If an account with that email exists, we've sent a password reset link. Please check your spam folder if you don't see it.", "success")
                except Exception as e:
                    logger.error(f"Error in forgot password process: {e}")
                    traceback.print_exc()
                    flash("An error occurred while sending the reset email. Please try again.", "error")
            else:
                logger.debug(f"User not found for email: {email}")
                # Don't reveal if email exists or not (security best practice)
                flash("If an account with that email exists, we've sent a password reset link.", "success")
            
            return redirect(url_for('auth.login'))
        
        return render_template("forgot_password.html")
    except Exception as e:
        logger.error(f"Critical error in forgot_password route: {e}")
        traceback.print_exc()
        flash("An unexpected error occurred. Please try again later.", "error")
        return render_template("forgot_password.html"), 500


# ── reset password ────────────────────────────────────────────────────────

@auth_bp.route("/reset-password", methods=["GET", "POST"])
@limiter.limit("10 per 15 minutes")  # Rate limit: 10 reset-password attempts per 15 minutes per IP
def reset_password():
    token = request.args.get("token")
    
    if not token:
        flash("Invalid reset link.", "error")
        return redirect(url_for('auth.login'))
    
    user_id = verify_reset_token(token)
    if not user_id:
        flash("Invalid or expired reset link.", "error")
        return redirect(url_for('auth.login'))
    
    if request.method == "POST":
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        
        if not password or not confirm_password:
            flash("Please enter both password fields.", "error")
            return render_template("reset_password.html")
        
        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("reset_password.html")
        
        if len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return render_template("reset_password.html")
        
        if not any(c.isdigit() for c in password):
            flash("Password must contain at least one number.", "error")
            return render_template("reset_password.html")
        
        # Update password
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            password_hash = generate_password_hash(password)
            placeholder = get_param_placeholder()
            cursor.execute(f"UPDATE users SET password_hash = {placeholder} WHERE id = {placeholder}", (password_hash, user_id))
            conn.commit()
            
            # Mark token as used
            mark_reset_token_used(token)
            
            flash("Password updated successfully! You can now log in.", "success")
            return redirect(url_for('auth.login'))
        except Exception as e:
            flash("Error updating password. Please try again.", "error")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
    
    return render_template("reset_password.html")


# ── logout ────────────────────────────────────────────────────────────────

@auth_bp.route("/logout")
def logout():
    session.pop('user_id', None)
    flash("You have been logged out.", "info")
    return redirect(url_for('auth.login'))


# ── Instagram OAuth ───────────────────────────────────────────────────────

@auth_bp.route("/auth/instagram")
@login_required
def instagram_auth():
    """Start Instagram OAuth flow"""
    if not Config.FACEBOOK_APP_ID:
        flash("Facebook OAuth not configured. Please contact support.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    # Generate state parameter for security
    state = secrets.token_urlsafe(32)
    session['instagram_oauth_state'] = state
    
    # Build Instagram Business OAuth URL (using Facebook Graph API)
    oauth_url = (
        f"https://www.facebook.com/v18.0/dialog/oauth"
        f"?client_id={Config.FACEBOOK_APP_ID}"
        f"&redirect_uri={Config.FACEBOOK_REDIRECT_URI}"
        f"&scope=instagram_basic,instagram_manage_messages,pages_messaging"
        f"&response_type=code"
        f"&state={state}"
    )
    
    return redirect(oauth_url)


@auth_bp.route("/auth/instagram/callback")
@login_required
@limiter.limit("20 per hour")  # Rate limit: 20 OAuth callbacks per hour per IP
def instagram_callback():
    """Handle Instagram OAuth callback"""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    # Check for errors
    if error:
        flash(f"Instagram authorization failed: {error}", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    # Verify state parameter
    if state != session.get('instagram_oauth_state'):
        flash("Invalid state parameter. Please try again.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    if not code:
        flash("No authorization code received from Instagram.", "error")
        return redirect(url_for('dashboard_bp.dashboard'))
    
    try:
        # Exchange code for access token using Facebook Graph API
        token_url = "https://graph.facebook.com/v18.0/oauth/access_token"
        token_data = {
            'client_id': Config.FACEBOOK_APP_ID,
            'client_secret': Config.FACEBOOK_APP_SECRET,
            'redirect_uri': Config.FACEBOOK_REDIRECT_URI,
            'code': code
        }
        
        response = http_requests.post(token_url, data=token_data)
        response.raise_for_status()
        token_info = response.json()
        
        access_token = token_info.get('access_token')
        
        if not access_token:
            flash("Failed to get Instagram access token.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        # Get Instagram Business account information
        # First, get the user's Instagram Business accounts
        accounts_url = "https://graph.facebook.com/v18.0/me/accounts"
        accounts_params = {
            'access_token': access_token,
            'fields': 'id,name,instagram_business_account'
        }
        
        logger.debug(f"Fetching accounts from: {accounts_url}")
        logger.debug(f"With params: {accounts_params}")
        
        accounts_response = http_requests.get(accounts_url, params=accounts_params)
        logger.debug(f"Response status: {accounts_response.status_code}")
        logger.debug(f"Response headers: {dict(accounts_response.headers)}")
        
        if accounts_response.status_code != 200:
            logger.error(f"API Error: {accounts_response.text}")
            flash(f"Facebook API error: {accounts_response.status_code}", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        accounts_data = accounts_response.json()
        logger.debug(f"Accounts response: {accounts_data}")
        
        # Find the Instagram Business account
        instagram_account = None
        page_id = None  # Initialize page_id here so it's available later
        page_name = None
        
        for account in accounts_data.get('data', []):
            logger.debug(f"Checking account: {account}")
            if account.get('instagram_business_account'):
                instagram_account = account['instagram_business_account']
                # Also extract page_id and page_name if we found the account
                page_id = account.get('id')
                page_name = account.get('name')
                logger.info(f"Found Instagram account: {instagram_account}")
                logger.info(f"Found Page ID: {page_id}, Page Name: {page_name}")
                break
        
        if not instagram_account:
            logger.info(f"No Instagram Business account found in {len(accounts_data.get('data', []))} accounts - trying alternative method...")
            
            # Let's try a different approach - get the specific Page ID from the token
            debug_token_url = "https://graph.facebook.com/v18.0/debug_token"
            debug_params = {
                'input_token': access_token,
                'access_token': Config.FACEBOOK_APP_ID + '|' + Config.FACEBOOK_APP_SECRET
            }
            debug_response = http_requests.get(debug_token_url, params=debug_params)
            debug_data = debug_response.json()
            logger.debug(f"Token debug response: {debug_data}")
            
            # Extract Page ID and Instagram account ID from the token
            instagram_account_id = None
            
            if 'data' in debug_data and 'granular_scopes' in debug_data['data']:
                for scope in debug_data['data']['granular_scopes']:
                    # Get Page ID from pages_messaging scope
                    if scope['scope'] == 'pages_messaging' and scope['target_ids']:
                        page_id = scope['target_ids'][0]
                        logger.debug(f"Found Page ID from pages_messaging: {page_id}")
                    # Get Instagram account ID from instagram_basic or instagram_manage_messages scope
                    elif scope['scope'] in ['instagram_basic', 'instagram_manage_messages'] and scope['target_ids']:
                        instagram_account_id = scope['target_ids'][0]
                        logger.debug(f"Found Instagram account ID from {scope['scope']}: {instagram_account_id}")
            
            # If we have the Instagram account ID directly, use it
            if instagram_account_id:
                instagram_account = {'id': instagram_account_id}
                logger.info(f"Using Instagram account ID from token: {instagram_account_id}")
            # Otherwise, try to get it from the Page
            elif page_id:
                # Try to get Instagram account directly from the Page
                page_url = f"https://graph.facebook.com/v18.0/{page_id}"
                page_params = {
                    'access_token': access_token,
                    'fields': 'instagram_business_account'
                }
                logger.debug(f"Fetching Page info from: {page_url}")
                logger.debug(f"With params: {page_params}")
                
                page_response = http_requests.get(page_url, params=page_params)
                logger.debug(f"Page response status: {page_response.status_code}")
                page_data = page_response.json()
                logger.debug(f"Page response: {page_data}")
                
                if 'instagram_business_account' in page_data:
                    instagram_account = page_data['instagram_business_account']
                    logger.info(f"Found Instagram account via Page: {instagram_account}")
        
        if not instagram_account:
            flash("No Instagram Business account found. Please ensure your Instagram account is connected to a Facebook Page and is set to Business type.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        instagram_user_id = instagram_account['id']
        
        # If we don't have page_id yet, try to get it from /me/accounts without fields filter
        if not page_id:
            logger.info(f"Page ID not found in token, trying to get from /me/accounts...")
            accounts_url_full = "https://graph.facebook.com/v18.0/me/accounts"
            accounts_params_full = {
                'access_token': access_token
            }
            accounts_response_full = http_requests.get(accounts_url_full, params=accounts_params_full)
            if accounts_response_full.status_code == 200:
                accounts_data_full = accounts_response_full.json()
                for account in accounts_data_full.get('data', []):
                    if account.get('instagram_business_account', {}).get('id') == instagram_user_id:
                        page_id = account['id']
                        logger.info(f"Found Page ID from /me/accounts: {page_id}")
                        break
        
        # If we still don't have page_id, we can't proceed
        if not page_id:
            logger.error(f"Could not find Page ID. Token debug: {debug_data}")
            flash("Could not find the Facebook Page associated with your Instagram account. Please ensure your Instagram Business account is properly linked to a Facebook Page.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        # We need to get a Page Access Token to query Instagram account details
        # First, let's get the Page Access Token
        page_access_token_url = f"https://graph.facebook.com/v18.0/{page_id}"
        page_token_params = {
            'fields': 'access_token,name',
            'access_token': access_token
        }
        
        logger.debug(f"Getting Page Access Token from: {page_access_token_url}")
        page_token_response = http_requests.get(page_access_token_url, params=page_token_params)
        logger.debug(f"Page token response status: {page_token_response.status_code}")
        
        if page_token_response.status_code != 200:
            logger.error(f"Failed to get Page Access Token: {page_token_response.text}")
            flash("Failed to get Page Access Token. Please try again.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        page_token_data = page_token_response.json()
        page_access_token = page_token_data.get('access_token')
        if page_name is None:
            page_name = page_token_data.get('name')
        logger.info(f"Got Page Access Token: {page_access_token[:20]}... (page_name={page_name})")
        
        # Now get Instagram account details using the Page Access Token
        profile_url = f"https://graph.facebook.com/v18.0/{instagram_user_id}"
        profile_params = {
            'fields': 'id,username,media_count',
            'access_token': page_access_token
        }
        
        logger.debug(f"Getting Instagram profile from: {profile_url}")
        logger.debug(f"Using Page Access Token: {page_access_token[:20]}...")
        
        profile_response = http_requests.get(profile_url, params=profile_params)
        logger.debug(f"Profile response status: {profile_response.status_code}")
        
        if profile_response.status_code != 200:
            logger.error(f"Failed to get Instagram profile: {profile_response.text}")
            flash("Failed to get Instagram profile details. Please try again.", "error")
            return redirect(url_for('dashboard_bp.dashboard'))
        
        profile_data = profile_response.json()
        logger.info(f"Got Instagram profile: {profile_data}")
        
        # Save Instagram connection to database
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                param = get_param_placeholder()
                
                # Check if connection already exists for this user
                cursor.execute(f"SELECT id FROM instagram_connections WHERE user_id = {param} AND instagram_user_id = {param}", 
                              (session['user_id'], instagram_user_id))
                existing = cursor.fetchone()
                
                # CRITICAL: Check if this Instagram account is already actively connected to a DIFFERENT user
                # If yes, block the connection - one Instagram account can only be connected to one email at a time
                cursor.execute(f"""
                    SELECT id, user_id 
                    FROM instagram_connections 
                    WHERE instagram_user_id = {param} 
                    AND user_id != {param}
                    AND is_active = TRUE
                    LIMIT 1
                """, (instagram_user_id, session['user_id']))
                active_connection_other_user = cursor.fetchone()
                
                if active_connection_other_user:
                    # This Instagram account is already connected to another email account
                    flash("This Instagram account is already connected to another email account. Please disconnect it from the other account first.", "error")
                    return redirect(url_for('dashboard_bp.dashboard'))
                
                # Check if this user has already received the free trial (persistent flag that survives disconnection)
                # Each email account only gets the free trial ONCE, on their first Instagram connection
                cursor.execute(f"""
                    SELECT has_received_free_trial 
                    FROM users 
                    WHERE id = {param}
                """, (session['user_id'],))
                user_result = cursor.fetchone()
                has_received_free_trial = user_result[0] if user_result and user_result[0] else False
                
                # CRITICAL: Check if this Instagram account has EVER been connected before (including disconnected ones)
                # If an Instagram account was previously connected to any email, it has "used up" its free trial eligibility
                # Even if disconnected, connecting it to a new email should NOT grant free trial
                cursor.execute(f"""
                    SELECT id, user_id 
                    FROM instagram_connections 
                    WHERE instagram_user_id = {param}
                    ORDER BY created_at ASC 
                    LIMIT 1
                """, (instagram_user_id,))
                instagram_ever_connected = cursor.fetchone()
                
                # Check if this specific user has ever connected this specific account before
                cursor.execute(f"""
                    SELECT id 
                    FROM instagram_connections 
                    WHERE instagram_user_id = {param} 
                    AND user_id = {param}
                    LIMIT 1
                """, (instagram_user_id, session['user_id']))
                user_previous_connection = cursor.fetchone()
                
                # Determine if free trial should be granted:
                # 1. User must NOT have received free trial before
                # 2. Instagram account must NEVER have been connected before (by any user)
                should_grant_free_trial = not has_received_free_trial and not instagram_ever_connected
                
                logger.debug(f"Instagram connection check for account {instagram_user_id}:")
                logger.debug(f"   - Existing connection for this user: {existing is not None}")
                logger.debug(f"   - User has received free trial: {has_received_free_trial}")
                logger.debug(f"   - Instagram account ever connected: {instagram_ever_connected is not None}")
                logger.debug(f"   - User previously connected this account: {user_previous_connection is not None}")
                logger.debug(f"   - Should grant free trial: {should_grant_free_trial}")
                
                if existing:
                    # Update existing connection (reconnection of same account by same user)
                    cursor.execute(f"""
                        UPDATE instagram_connections 
                        SET page_access_token = {param},
                            instagram_username = {param},
                            instagram_page_name = {param},
                            is_active = TRUE,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = {param}
                    """, (page_access_token, profile_data.get('username'), page_name, existing[0]))
                    
                    # If user had free trial but lost replies (e.g., from database reset), restore them
                    cursor.execute(f"""
                        SELECT replies_limit_monthly, has_received_free_trial
                        FROM users
                        WHERE id = {param}
                    """, (session['user_id'],))
                    user_reply_data = cursor.fetchone()
                    if user_reply_data:
                        current_replies, has_trial = user_reply_data
                        # If user received free trial but has 0 replies, restore 100 free trial replies
                        if has_trial and current_replies == 0:
                            cursor.execute(f"""
                                UPDATE users 
                                SET replies_limit_monthly = 100
                                WHERE id = {param}
                            """, (session['user_id'],))
                            flash(f"Successfully reconnected Instagram account: @{profile_data.get('username', 'Unknown')}. Your 100 free trial replies have been restored! 🎉", "success")
                        else:
                            flash(f"Successfully reconnected Instagram account: @{profile_data.get('username', 'Unknown')}", "success")
                    else:
                        flash(f"Successfully reconnected Instagram account: @{profile_data.get('username', 'Unknown')}", "success")
                else:
                    # Create new connection
                    cursor.execute(f"""
                        INSERT INTO instagram_connections (user_id, instagram_user_id, instagram_page_id, instagram_username, instagram_page_name, page_access_token, is_active)
                        VALUES ({param}, {param}, {param}, {param}, {param}, {param}, TRUE)
                    """, (session['user_id'], instagram_user_id, page_id, profile_data.get('username'), page_name, page_access_token))
                    
                    # Grant free trial ONLY if:
                    # 1. User has NOT received free trial before
                    # 2. Instagram account has NEVER been connected before (by any user, even if disconnected)
                    if should_grant_free_trial:
                        logger.info(f"First Instagram connection for user {session['user_id']} with never-before-connected account - granting 100 free trial replies")
                        cursor.execute(f"""
                            UPDATE users 
                            SET replies_limit_monthly = replies_limit_monthly + 100,
                                has_received_free_trial = TRUE
                            WHERE id = {param}
                        """, (session['user_id'],))
                        flash(f"Successfully connected Instagram account: @{profile_data.get('username', 'Unknown')}. You've received 100 free trial replies! 🎉", "success")
                    else:
                        # No free trial - either user already received it, or Instagram account was connected before
                        if instagram_ever_connected:
                            logger.info(f"Instagram account {instagram_user_id} was previously connected to another email - no free trial granted")
                            flash(f"Successfully connected Instagram account: @{profile_data.get('username', 'Unknown')}. This account was previously connected to another email, so no free trial replies were granted.", "info")
                        else:
                            # User has already received free trial
                            # But check if they lost their replies (e.g., from database reset) and restore them
                            cursor.execute(f"""
                                SELECT replies_limit_monthly
                                FROM users
                                WHERE id = {param}
                            """, (session['user_id'],))
                            current_replies = cursor.fetchone()
                            if current_replies and current_replies[0] == 0:
                                # User had free trial but lost replies - restore them
                                cursor.execute(f"""
                                    UPDATE users 
                                    SET replies_limit_monthly = 100
                                    WHERE id = {param}
                                """, (session['user_id'],))
                                logger.info(f"User {session['user_id']} had free trial but lost replies - restoring 100 free trial replies")
                                flash(f"Successfully connected Instagram account: @{profile_data.get('username', 'Unknown')}. Your 100 free trial replies have been restored! 🎉", "success")
                            else:
                                logger.info(f"User {session['user_id']} has already received free trial - no free trial granted")
                                flash(f"Successfully connected Instagram account: @{profile_data.get('username', 'Unknown')}", "success")
                
                conn.commit()
                
            except Exception as e:
                logger.error(f"Database error: {e}")
                flash("Failed to save Instagram connection. Please try again.", "error")
            finally:
                conn.close()
        
        # Clean up session
        session.pop('instagram_oauth_state', None)
        
    except http_requests.RequestException as e:
        logger.error(f"Instagram API error: {e}")
        if "access_denied" in str(e):
            flash("Access denied. Please ensure your Instagram account is a Business account connected to a Facebook Page.", "error")
        elif "invalid_request" in str(e):
            flash("Invalid request. Please check your Instagram account settings and try again.", "error")
        else:
            flash("Failed to connect Instagram account. Please try again.", "error")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        flash("An unexpected error occurred. Please try again.", "error")
    
    return redirect(url_for('dashboard_bp.dashboard'))
