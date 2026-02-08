"""Public page routes — home, pricing, legal pages, support."""
from flask import Blueprint, request, render_template, redirect, url_for, flash, session
from datetime import datetime
from config import Config
from services.auth import login_required
from services.users import get_user_by_id
from services.email import send_email_via_sendgrid, send_data_deletion_request_acknowledgment_email, get_email_base_template

pages_bp = Blueprint('pages', __name__)


@pages_bp.route("/")
def home():
    # Check if user is logged in
    user_logged_in = 'user_id' in session
    user = None
    if user_logged_in:
        user = get_user_by_id(session['user_id'])
    return render_template("index.html", user_logged_in=user_logged_in, user=user)


@pages_bp.route("/pricing")
def pricing():
    """Standalone pricing page"""
    # Check if user is logged in
    user_logged_in = 'user_id' in session
    user = None
    if user_logged_in:
        user = get_user_by_id(session['user_id'])
    return render_template("pricing.html", user_logged_in=user_logged_in, user=user)


@pages_bp.route("/faq")
def faq():
    return render_template("faq.html")


@pages_bp.route("/privacy")
def privacy():
    return render_template("privacy.html", moment=datetime.now())


@pages_bp.route("/terms")
def terms():
    return render_template("terms.html", moment=datetime.now())


@pages_bp.route("/data-deletion")
def data_deletion():
    return render_template("data_deletion.html", moment=datetime.now())


@pages_bp.route("/instagram-setup-help")
def instagram_setup_help():
    return render_template("instagram_setup_help.html")


@pages_bp.route("/support", methods=["GET", "POST"])
@login_required
def support():
    """Support page where users can send messages"""
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        user_id = session.get('user_id')
        
        if not message:
            flash("Please enter a message.", "error")
            return redirect(url_for('pages.support'))
        
        # Get user info
        user = get_user_by_id(user_id)
        user_email = user.get('email', 'Unknown')
        username = user.get('username', 'User')
        
        # Create email content
        content_html = f"""
            <p style="color: rgba(255, 255, 255, 0.9); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
                <strong>Support Request from:</strong> {username} ({user_email})
            </p>
            
            <div style="background: rgba(51, 102, 255, 0.1); padding: 20px; border-radius: 8px; border: 1px solid rgba(51, 102, 255, 0.2); margin: 20px 0;">
                <p style="color: rgba(255, 255, 255, 0.9); font-size: 16px; line-height: 1.7; margin: 0; text-transform: none; letter-spacing: normal; white-space: pre-wrap;">{message}</p>
            </div>
        """
        
        html_content = get_email_base_template("Support Request", content_html)
        
        # Send to support email
        support_email = Config.SUPPORT_EMAIL
        success = send_email_via_sendgrid(support_email, f"Support Request from {username}", html_content)
        
        if success:
            flash("Your message has been sent successfully! We'll get back to you soon.", "success")
        else:
            flash(f"There was an error sending your message. Please try again or email us directly at {Config.SUPPORT_EMAIL}", "error")
        
        return redirect(url_for('pages.support'))
    
    # GET request - show support form
    user_id = session.get('user_id')
    user = get_user_by_id(user_id)
    return render_template("support.html", user=user)
