"""
Chata — AI Instagram DM Automation
Entry point: creates the Flask app, registers blueprints, and starts the server.
"""
from dotenv import load_dotenv
import os
import io
import logging
from datetime import datetime
from flask import Flask, request, redirect, url_for, flash, session, jsonify
from extensions import limiter, csrf
import stripe  # type: ignore[reportMissingImports]

from config import Config
from database import get_db_connection, get_param_placeholder, init_database
from health import health_check, get_system_info

# ---------------------------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------------------------
load_dotenv()

# Configure logging
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("chata")

# Validate required environment variables
try:
    Config.validate_required_vars()
    logger.info("All required environment variables are set")
except ValueError as e:
    logger.error(f"Configuration error: {e}")
    logger.error("Please check your environment variables")

# Refuse to start in production with the default secret key
Config.check_secret_key()

# ---------------------------------------------------------------------------
# Create Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = Config.SECRET_KEY

# Session cookie security — enforce HTTPS-only cookies in production
is_production = bool(os.environ.get('DATABASE_URL'))  # Production uses PostgreSQL
app.config['SESSION_COOKIE_SECURE'] = is_production     # HTTPS-only in production
app.config['SESSION_COOKIE_HTTPONLY'] = True              # No JavaScript access to session cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'            # CSRF protection for top-level navigations

# ---------------------------------------------------------------------------
# Extensions (defined in extensions.py to avoid circular imports)
# ---------------------------------------------------------------------------
limiter.init_app(app)
csrf.init_app(app)

# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------
if Config.STRIPE_SECRET_KEY:
    stripe.api_key = Config.STRIPE_SECRET_KEY
else:
    logger.warning("STRIPE_SECRET_KEY not set. Stripe features will not work.")


# ---------------------------------------------------------------------------
# Middleware: capture raw webhook body for signature verification
# ---------------------------------------------------------------------------
class WebhookRawBodyMiddleware:
    def __init__(self, app_wsgi):
        self.app_wsgi = app_wsgi

    def __call__(self, environ, start_response):
        if environ.get("REQUEST_METHOD") == "POST" and environ.get("PATH_INFO", "").rstrip("/") == "/webhook":
            content_length = environ.get("CONTENT_LENGTH")
            if content_length:
                try:
                    content_length = int(content_length)
                    if 0 < content_length <= 1024 * 1024:
                        body = environ["wsgi.input"].read(content_length)
                        environ["chata.webhook_raw_body"] = body
                        environ["wsgi.input"] = io.BytesIO(body)
                except (ValueError, OSError, TypeError):
                    pass
        return self.app_wsgi(environ, start_response)


app.wsgi_app = WebhookRawBodyMiddleware(app.wsgi_app)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(429)
def ratelimit_handler(e):
    flash("Too many attempts. Please wait a few minutes before trying again.", "error")
    path = request.path or ""
    if "/signup" in path:
        return redirect(url_for("auth.signup"))
    if "/login" in path:
        return redirect(url_for("auth.login"))
    return redirect(url_for("pages.home"))


# ---------------------------------------------------------------------------
# Health-check routes (kept in app.py — tiny)
# ---------------------------------------------------------------------------
@app.route("/health")
def health():
    return jsonify(health_check())


@app.route("/health/detailed")
def health_detailed():
    data = health_check()
    data["system"] = get_system_info()
    return jsonify(data)


@app.route("/ping")
def ping():
    return jsonify({"status": "pong", "timestamp": datetime.utcnow().isoformat()})


@app.route("/webhook/test")
def webhook_test():
    return jsonify({
        "status": "webhook_url_accessible",
        "url": f"{Config.BASE_URL}/webhook",
        "verify_token_set": bool(Config.VERIFY_TOKEN),
        "timestamp": datetime.utcnow().isoformat(),
    })


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------
logger.info("Starting Chata application...")
if init_database():
    logger.info("Database initialized successfully")
else:
    logger.error("Database initialization failed - some features may not work")

logger.info("Running database migration...")
from update_schema import migrate_client_settings
try:
    if migrate_client_settings():
        logger.info("Migration completed successfully")
    else:
        logger.warning("Migration had issues but continuing...")
except Exception as e:
    logger.warning(f"Migration error (continuing anyway): {e}")


# ---------------------------------------------------------------------------
# Register blueprints
# ---------------------------------------------------------------------------
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.payments import payments_bp
from routes.webhook import webhook_bp
from routes.admin import admin_bp
from routes.pages import pages_bp

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(webhook_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(pages_bp)

# Exempt webhook endpoints from CSRF (external services POST to these)
csrf.exempt(webhook_bp)

# ---------------------------------------------------------------------------
# Extensions are in extensions.py — blueprints import from there directly.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Backward-compatibility re-exports
# ---------------------------------------------------------------------------
# Some service modules do a late `from app import ...` to avoid circular deps.
# Keep thin wrappers here so those imports resolve.
from services.subscription import get_setting, set_setting          # noqa: F401
from services.activity import log_activity, get_client_settings, save_client_settings  # noqa: F401
from services.ai import (                                           # noqa: F401
    CONVERSATION_EXAMPLES, CONVERSATION_TEMPLATES, ALL_CONVERSATION_PROMPTS,
    MODEL_CONFIG, DEFAULT_MODEL_CONFIG, normalize_max_tokens,
)
from services.users import get_user_by_id                           # noqa: F401


# ---------------------------------------------------------------------------
# Facebook OAuth config logging
# ---------------------------------------------------------------------------
logger.info(f"Facebook OAuth - App ID: {'Set' if Config.FACEBOOK_APP_ID else 'Not set'}")
logger.info(f"Facebook OAuth - App Secret: {'Set' if Config.FACEBOOK_APP_SECRET else 'Not set'}")
logger.info(f"Facebook OAuth - Redirect URI: {Config.FACEBOOK_REDIRECT_URI}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
