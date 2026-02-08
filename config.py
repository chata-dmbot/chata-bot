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
    
    # Safety: refuse to start in production with the default placeholder secret key
    _DEFAULT_SECRET = "your-secret-key-change-this-in-production"
    
    # Database Configuration
    DATABASE_URL = os.getenv("DATABASE_URL")
    DB_FILE = "chata.db"  # Fallback for local development
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    
    # Meta/Instagram Configuration
    VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "chata_verify_token")
    ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
    INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID")
    
    # Meta App Review: when True, bot replies are saved but not sent; user must click Send in Conversation History (temporary for review)
    APP_REVIEW_MANUAL_SEND = os.getenv("APP_REVIEW_MANUAL_SEND", "false").lower() in ("true", "1", "yes")
    
    # Debug routes: disabled by default; set to "true" to enable /dashboard/debug/* routes
    DEBUG_ROUTES_ENABLED = os.getenv("DEBUG_ROUTES_ENABLED", "false").lower() in ("true", "1", "yes")
    
    # Admin user IDs (comma-separated): only these user IDs can access /admin/* routes
    ADMIN_USER_IDS = [int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()]

    # Facebook OAuth Configuration
    FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID")
    FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET")
    # Instagram webhook signature verification (X-Hub-Signature-256).
    # Set to "true" = SKIP verification (insecure: anyone who knows the URL can POST). Set to "false" = verify.
    # We default to skip because verification currently fails in production (Render): our HMAC never matches Meta's.
    # Cause: we fixed encoding (Meta sends hex; we now use hexdigest()). Secret matches Meta. Body we receive is
    # valid JSON and looks correct, but bytes we hash != bytes Meta signed. Likely the proxy (Render) decompresses
    # gzip request bodies before our app sees them, so we hash decompressed bytes while Meta signed compressed.
    # We added compact-JSON fallback (no effect). To re-enable verification: set this env to "false", then either
    # ensure the platform passes raw body (no decompression) for POST /webhook, or get Meta's exact body format.
    SKIP_INSTAGRAM_WEBHOOK_SIGNATURE_VERIFICATION = os.getenv("SKIP_INSTAGRAM_WEBHOOK_SIGNATURE_VERIFICATION", "true").lower() in ("true", "1", "yes")
    FACEBOOK_REDIRECT_URI = os.getenv("FACEBOOK_REDIRECT_URI", "https://getchata.com/auth/instagram/callback")
    
    # Email Configuration
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
    SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "chata.dmbot@gmail.com")
    
    # Stripe Configuration
    STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
    STRIPE_STARTER_PLAN_PRICE_ID = os.getenv("STRIPE_STARTER_PLAN_PRICE_ID")
    STRIPE_STANDARD_PLAN_PRICE_ID = os.getenv("STRIPE_STANDARD_PLAN_PRICE_ID")
    STRIPE_ADDON_PRICE_ID = os.getenv("STRIPE_ADDON_PRICE_ID")
    
    # ---------------------------------------------------------------------------
    # Application constants (replace magic numbers throughout the codebase)
    # ---------------------------------------------------------------------------
    BASE_URL = os.getenv("BASE_URL", "https://getchata.com")
    SUPPORT_EMAIL = "chata.dmbot@gmail.com"
    
    # Reply plan limits
    STARTER_MONTHLY_REPLIES = 150
    STANDARD_MONTHLY_REPLIES = 250
    ADDON_REPLIES = 150          # replies per add-on purchase
    REPLY_WARNING_THRESHOLD = 50  # warn user when remaining replies fall to this
    
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
    
    @classmethod
    def check_secret_key(cls):
        """Raise an error if the default SECRET_KEY is used in production (DATABASE_URL is set)."""
        is_production = cls.DATABASE_URL and (
            cls.DATABASE_URL.startswith("postgres://") or cls.DATABASE_URL.startswith("postgresql://")
        )
        if is_production and cls.SECRET_KEY == cls._DEFAULT_SECRET:
            raise RuntimeError(
                "FATAL: SECRET_KEY is still the default placeholder. "
                "Set a strong SECRET_KEY environment variable before running in production."
            )
