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
    # PostgreSQL connection pool size (per process). Increase under heavy webhook load. Clamped 1–50.
    _pool_size = int(os.getenv("DATABASE_POOL_SIZE", "10"))
    DATABASE_POOL_SIZE = max(1, min(50, _pool_size))
    # Run update_schema migration on app startup. Set to "false" to speed startup and run migrations via release command.
    RUN_MIGRATIONS_ON_STARTUP = os.getenv("RUN_MIGRATIONS_ON_STARTUP", "true").lower() not in ("false", "0", "no")
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT", "60"))  # seconds per request; prevents hung connections
    
    # Meta/Instagram Configuration
    _DEFAULT_VERIFY_TOKEN = "chata_verify_token"
    VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", _DEFAULT_VERIFY_TOKEN)
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
    # Instagram app secret: used for webhook X-Hub-Signature-256 verification. If set, used instead of FACEBOOK_APP_SECRET for the webhook (OAuth still uses FACEBOOK_APP_SECRET).
    INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET")
    FACEBOOK_REDIRECT_URI = os.getenv("FACEBOOK_REDIRECT_URI", "https://getchata.com/auth/instagram/callback")
    
    # Email Configuration
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
    SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "hello@getchata.com")
    
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
    SUPPORT_EMAIL = "hello@getchata.com"
    
    # Reply plan limits
    STARTER_MONTHLY_REPLIES = 150
    STANDARD_MONTHLY_REPLIES = 250
    ADDON_REPLIES = 150          # replies per add-on purchase
    REPLY_WARNING_THRESHOLD = 50  # warn user when remaining replies fall to this
    
    # Rate limiting: RATE_LIMIT_STORAGE_URI (default memory://). Set to redis://... in production for shared limits across workers.
    RATE_LIMIT_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")
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

    @classmethod
    def check_verify_token(cls):
        """Warn if VERIFY_TOKEN is unset or still the default in production (consider using a random value for Meta webhook)."""
        import logging
        is_production = cls.DATABASE_URL and (
            cls.DATABASE_URL.startswith("postgres://") or cls.DATABASE_URL.startswith("postgresql://")
        )
        if is_production and (not cls.VERIFY_TOKEN or cls.VERIFY_TOKEN == cls._DEFAULT_VERIFY_TOKEN):
            logging.getLogger("chata").warning(
                "VERIFY_TOKEN is unset or default in production. Consider setting a random VERIFY_TOKEN for Meta webhook security."
            )

    @classmethod
    def check_production_database(cls):
        """When ENV=production, require DATABASE_URL to be set and PostgreSQL (no SQLite in production)."""
        if os.getenv("ENV", "").lower() != "production":
            return
        if not cls.DATABASE_URL or not (
            cls.DATABASE_URL.startswith("postgres://") or cls.DATABASE_URL.startswith("postgresql://")
        ):
            raise RuntimeError(
                "FATAL: ENV=production requires DATABASE_URL to be a PostgreSQL URL. "
                "SQLite is not supported in production."
            )
