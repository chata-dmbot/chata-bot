"""Email service — sending transactional emails via SendGrid."""
import logging
import re
import sendgrid
from sendgrid.helpers.mail import Mail
from config import Config

logger = logging.getLogger("chata.services.email")


def get_email_base_template(title, content_html):
    """Base email template with black/blue theme - simplified design"""
    return f"""
    <div style="font-family: 'Inter', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background: #000000;">
        <div style="text-align: center; margin-bottom: 40px; padding: 20px 0;">
            <h1 style="color: #ffffff; margin: 0; font-size: 48px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;">CHATA</h1>
            <p style="color: rgba(255, 255, 255, 0.7); margin: 10px 0 0 0; font-size: 14px; letter-spacing: 0.1em; text-transform: uppercase;">INSTAGRAM AI ENGAGEMENT</p>
        </div>
        
        <div style="padding: 0 20px;">
            <h2 style="color: #ffffff; margin-bottom: 20px; font-size: 24px; font-weight: 600; text-transform: none; letter-spacing: normal;">{title}</h2>
            
            {content_html}
        </div>
    </div>
    """

def send_reset_email(email, reset_token):
    """Send password reset email using SendGrid"""
    reset_url = f"{Config.BASE_URL}/reset-password?token={reset_token}"
    
    # Get SendGrid API key from environment
    sendgrid_api_key = Config.SENDGRID_API_KEY
    
    if not sendgrid_api_key:
        # Fallback to console output if no API key
        logger.info(f"Password reset link for {email}: {reset_url}")
        logger.warning("SENDGRID_API_KEY not found in environment variables")
        return
    
    try:
        sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)
        
        # Create email content with simplified black/blue theme
        content_html = f"""
            <p style="color: rgba(255, 255, 255, 0.9); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
                You recently requested a password reset for your Chata account.
            </p>
            
            <p style="color: rgba(255, 255, 255, 0.8); line-height: 1.7; margin-bottom: 30px; font-size: 16px; text-transform: none; letter-spacing: normal;">
                Click the button below to reset your password. This link will allow you to create a new password for your account.
            </p>
            
            <div style="text-align: center; margin: 35px 0;">
                <a href="{reset_url}" style="background: linear-gradient(135deg, #3366ff 0%, #4d7cff 100%); color: white; padding: 16px 40px; text-decoration: none; border-radius: 10px; font-weight: 600; display: inline-block; box-shadow: 0 4px 15px rgba(51, 102, 255, 0.3); transition: all 0.3s ease; text-transform: none; letter-spacing: normal; font-size: 16px;">
                    Reset Password
                </a>
            </div>
            
            <p style="color: rgba(255, 255, 255, 0.7); font-size: 15px; margin: 30px 0 15px 0; text-transform: none; letter-spacing: normal; text-align: center;">
                If the button doesn't work, copy and paste this link into your browser:
            </p>
            
            <div style="background: rgba(51, 102, 255, 0.1); padding: 15px; border-radius: 8px; border: 1px solid rgba(51, 102, 255, 0.2); margin-bottom: 25px;">
                <p style="color: #3366ff; font-size: 13px; word-break: break-all; margin: 0; text-transform: none; letter-spacing: normal; line-height: 1.5;">
                    {reset_url}
                </p>
            </div>
            
            <hr style="border: none; border-top: 1px solid rgba(255, 255, 255, 0.1); margin: 30px 0;">
            
            <p style="color: rgba(255, 255, 255, 0.6); font-size: 13px; margin: 0 0 10px 0; text-align: center; text-transform: none; letter-spacing: normal; line-height: 1.6;">
                <strong style="color: rgba(255, 255, 255, 0.8);">Important:</strong> This password reset link will expire in <strong style="color: #3366ff;">1 hour</strong> for your security.
            </p>
            <p style="color: rgba(255, 255, 255, 0.5); font-size: 12px; margin: 0; text-align: center; text-transform: none; letter-spacing: normal; line-height: 1.6;">
                If you didn't request this password reset, you can safely ignore this email. Your password will remain unchanged.
            </p>
        """
        
        html_content = get_email_base_template("Password Reset Request", content_html)
        
        from_email = Config.SENDGRID_FROM_EMAIL
        if not from_email:
            logger.warning("SENDGRID_FROM_EMAIL not set. Using default email.")
            from_email = Config.SUPPORT_EMAIL
        
        # Create plain text version
        plain_text = f"""CHATA - INSTAGRAM AI ENGAGEMENT

Password Reset Request

You recently requested a password reset for your Chata account.

Click the button below to reset your password. This link will allow you to create a new password for your account.

Reset Password: {reset_url}

If the button doesn't work, copy and paste this link into your browser:
{reset_url}

Important: This password reset link will expire in 1 hour for your security.

If you didn't request this password reset, you can safely ignore this email. Your password will remain unchanged.
"""
        
        message = Mail(
            from_email=from_email,
            to_emails=email,
            subject='Password Reset Request - Chata',
            html_content=html_content,
            plain_text_content=plain_text
        )
        
        # Add reply-to header
        message.reply_to = from_email
        
        response = sg.send(message)
        logger.info(f"Password reset email sent to {email}. Status: {response.status_code}")
        
        # Check if the email was sent successfully
        if response.status_code == 202:
            logger.info(f"Email sent successfully to {email}")
        else:
            logger.error(f"Email failed to send. Status: {response.status_code}")
            logger.error(f"Response body: {response.body}")
        
    except Exception as e:
        logger.error(f"Error sending email to {email}: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        # Fallback to console output
        logger.info(f"Password reset link for {email}: {reset_url}")

def html_to_plain_text(html_content):
    """Convert HTML email to plain text version for better deliverability"""
    # Remove HTML tags but keep text
    text = re.sub(r'<[^>]+>', '', html_content)
    # Replace common HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text

def send_email_via_sendgrid(email, subject, html_content):
    """Helper function to send emails via SendGrid with improved deliverability"""
    sendgrid_api_key = Config.SENDGRID_API_KEY
    
    if not sendgrid_api_key:
        logger.warning(f"SENDGRID_API_KEY not found. Email not sent to {email}")
        logger.warning(f"Email subject: {subject}")
        return False
    
    try:
        sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)
        
        from_email = Config.SENDGRID_FROM_EMAIL
        if not from_email:
            from_email = Config.SUPPORT_EMAIL
        
        # Create plain text version for better deliverability
        plain_text_content = html_to_plain_text(html_content)
        
        message = Mail(
            from_email=from_email,
            to_emails=email,
            subject=subject,
            html_content=html_content,
            plain_text_content=plain_text_content
        )
        
        # Add reply-to header
        message.reply_to = from_email
        
        response = sg.send(message)
        
        if response.status_code == 202:
            logger.info(f"Email sent successfully to {email}: {subject}")
            logger.debug(f"SendGrid response headers: {dict(response.headers)}")
            if hasattr(response, 'body') and response.body:
                logger.debug(f"SendGrid response body: {response.body}")
            return True
        else:
            logger.error(f"Email failed to send. Status: {response.status_code}")
            logger.debug(f"SendGrid response headers: {dict(response.headers)}")
            if hasattr(response, 'body') and response.body:
                logger.debug(f"SendGrid response body: {response.body}")
            return False
        
    except Exception as e:
        logger.error(f"Error sending email to {email}: {e}")
        return False

def send_welcome_email(email):
    """Send welcome email to new users"""
    dashboard_url = f"{Config.BASE_URL}/dashboard"
    
    content_html = f"""
        <p style="color: rgba(255, 255, 255, 0.9); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            We're excited to have you on board.
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.8); line-height: 1.7; margin-bottom: 30px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            Get started by connecting your Instagram account and setting up your AI. Your AI will automatically respond to messages and help you engage with your audience.
        </p>
        
        <div style="text-align: center; margin: 35px 0;">
            <a href="{dashboard_url}" style="background: linear-gradient(135deg, #3366ff 0%, #4d7cff 100%); color: white; padding: 16px 40px; text-decoration: none; border-radius: 10px; font-weight: 600; display: inline-block; box-shadow: 0 4px 15px rgba(51, 102, 255, 0.3); transition: all 0.3s ease; text-transform: none; letter-spacing: normal; font-size: 16px;">
                Go to Dashboard
            </a>
        </div>
        
        <p style="color: rgba(255, 255, 255, 0.7); font-size: 15px; margin: 30px 0 0 0; text-transform: none; letter-spacing: normal; line-height: 1.7;">
            If you have any questions, feel free to reach out to us. We're here to help!
        </p>
    """
    
    html_content = get_email_base_template("Welcome to Chata!", content_html)
    return send_email_via_sendgrid(email, "Welcome to Chata - Get Started", html_content)

def send_usage_warning_email(email, remaining_replies):
    """Send usage warning email when user is running low on replies"""
    dashboard_url = f"{Config.BASE_URL}/dashboard"
    pricing_url = f"{Config.BASE_URL}/pricing"
    
    if remaining_replies >= 100:
        threshold = 100
        urgency = "low"
        message = f"You have {remaining_replies} replies remaining. Make sure you have enough to keep your AI assistant running smoothly."
    elif remaining_replies >= 50:
        threshold = 50
        urgency = "medium"
        message = f"You have {remaining_replies} replies remaining. Consider purchasing more replies to avoid interruption."
    else:
        threshold = remaining_replies
        urgency = "high"
        message = f"⚠️ You only have {remaining_replies} replies remaining! Your AI assistant will stop responding when you run out."
    
    content_html = f"""
        <p style="color: rgba(255, 255, 255, 0.9); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            {message}
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.8); line-height: 1.7; margin-bottom: 30px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            You can always purchase additional replies for €5 to keep your AI assistant active. Visit your dashboard to buy more replies or upgrade your plan.
        </p>
        
        <div style="text-align: center; margin: 35px 0;">
            <a href="{dashboard_url}" style="background: linear-gradient(135deg, #3366ff 0%, #4d7cff 100%); color: white; padding: 16px 40px; text-decoration: none; border-radius: 10px; font-weight: 600; display: inline-block; box-shadow: 0 4px 15px rgba(51, 102, 255, 0.3); transition: all 0.3s ease; text-transform: none; letter-spacing: normal; font-size: 16px;">
                View Dashboard
            </a>
        </div>
        
        <p style="color: rgba(255, 255, 255, 0.7); font-size: 15px; margin: 30px 0 0 0; text-transform: none; letter-spacing: normal; text-align: center; line-height: 1.7;">
            Or <a href="{pricing_url}" style="color: #3366ff; text-decoration: none;">view our pricing plans</a> to upgrade for more monthly replies.
        </p>
    """
    
    subject = f"Low Reply Count Warning - {remaining_replies} Replies Remaining"
    html_content = get_email_base_template("Reply Count Warning", content_html)
    return send_email_via_sendgrid(email, subject, html_content)

def send_account_deletion_confirmation_email(email, username):
    """Send confirmation email when account is deleted"""
    content_html = f"""
        <p style="color: rgba(255, 255, 255, 0.9); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            Your account has been successfully deleted.
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.8); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            All of your data, including your account information, AI settings, conversation history, and Instagram connections, have been permanently removed from our systems.
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.7); font-size: 15px; margin: 30px 0 0 0; text-transform: none; letter-spacing: normal; line-height: 1.7;">
            This is the last email you will receive from us. We're sorry to see you go, and if you ever decide to return, we'll be here.
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.6); font-size: 14px; margin: 20px 0 0 0; text-transform: none; letter-spacing: normal; line-height: 1.7; text-align: center;">
            Thank you for using Chata.
        </p>
    """
    
    subject = "Account Successfully Deleted - Chata"
    html_content = get_email_base_template("Account Deletion Confirmation", content_html)
    return send_email_via_sendgrid(email, subject, html_content)

def send_data_deletion_request_acknowledgment_email(email):
    """Send auto-reply email acknowledging receipt of data deletion request"""
    content_html = f"""
        <p style="color: rgba(255, 255, 255, 0.9); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            Thank you for contacting us. We have received your data deletion request.
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.8); line-height: 1.7; margin-bottom: 15px; font-size: 16px; text-transform: none; letter-spacing: normal;">
            We will review your request and process it within the shortest possible timeline, typically within 7-14 days, in accordance with applicable data protection laws (GDPR, CCPA, etc.).
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.7); font-size: 15px; margin: 20px 0 0 0; text-transform: none; letter-spacing: normal; line-height: 1.7;">
            If you have any questions or concerns, please don't hesitate to reach out to us at chata.dmbot@gmail.com.
        </p>
        
        <p style="color: rgba(255, 255, 255, 0.6); font-size: 14px; margin: 20px 0 0 0; text-transform: none; letter-spacing: normal; line-height: 1.7;">
            Best regards,<br>
            The Chata Team
        </p>
    """
    
    subject = "Data Deletion Request Received - Chata"
    html_content = get_email_base_template("Data Deletion Request Acknowledgment", content_html)
    return send_email_via_sendgrid(email, subject, html_content)
