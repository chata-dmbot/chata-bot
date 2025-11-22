"""
Configuration settings for Chata application
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Base configuration class"""
    
    # Flask Configuration
    SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
    
    # Database Configuration
    DATABASE_URL = os.getenv("DATABASE_URL")
    DB_FILE = "chata.db"  # Fallback for local development
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    
    # Meta/Instagram Configuration
    VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "chata_verify_token")
    ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
    INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID")
    
    # Facebook OAuth Configuration
    FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID")
    FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET")
    FACEBOOK_REDIRECT_URI = os.getenv("FACEBOOK_REDIRECT_URI", "https://chata-bot.onrender.com/auth/instagram/callback")
    
    # Email Configuration
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
    
    # Stripe Configuration
    STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
    STRIPE_STARTER_PLAN_PRICE_ID = os.getenv("STRIPE_STARTER_PLAN_PRICE_ID")
    STRIPE_STANDARD_PLAN_PRICE_ID = os.getenv("STRIPE_STANDARD_PLAN_PRICE_ID")
    STRIPE_ADDON_PRICE_ID = os.getenv("STRIPE_ADDON_PRICE_ID")
    
    # Production Settings
    PORT = int(os.environ.get("PORT", 5000))
    
    @staticmethod
    def validate_required_vars():
        """Validate that all required environment variables are set"""
        required_vars = [
            'OPENAI_API_KEY',
            'ACCESS_TOKEN',
            'INSTAGRAM_USER_ID',
            'FACEBOOK_APP_ID',
            'FACEBOOK_APP_SECRET'
        ]
        
        missing_vars = []
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        return True
