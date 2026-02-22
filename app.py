"""
Chata — AI Instagram DM Automation
Entry point: creates the Flask app, registers blueprints, and starts the server.
"""
from dotenv import load_dotenv
import os
import io
import re
import logging
from datetime import datetime, timedelta
from flask import Flask, request, redirect, url_for, flash, session, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from extensions import limiter, csrf
import stripe  # type: ignore[reportMissingImports]

from config import Config
from database import get_db_connection, get_param_placeholder, init_database
from health import health_check

# ---------------------------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Logging — structured JSON in production, plain text locally
# ---------------------------------------------------------------------------
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

class SensitiveDataFilter(logging.Filter):
    """Redact API keys and tokens from log output."""
    _PATTERNS = [
        re.compile(r'sk-[A-Za-z0-9]{20,}'),
        re.compile(r'SG\.[A-Za-z0-9_-]{20,}'),
        re.compile(r'(access_token|authorization|secret|token)=[^\s&]+', re.IGNORECASE),
    ]
    def filter(self, record):
        msg = record.getMessage()
        for pat in self._PATTERNS:
            msg = pat.sub('[REDACTED]', msg)
        record.msg = msg
        record.args = None
        return True

if Config.LOG_JSON:
    try:
        from pythonjsonlogger import json as jsonlogger
        handler = logging.StreamHandler()
        handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler.addFilter(SensitiveDataFilter())
        logging.root.handlers = [handler]
        logging.root.setLevel(getattr(logging, log_level, logging.INFO))
    except ImportError:
        logging.basicConfig(level=getattr(logging, log_level, logging.INFO),
                            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
else:
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO),
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

logger = logging.getLogger("chata")

# ---------------------------------------------------------------------------
# Sentry (optional — only if SENTRY_DSN is set)
# ---------------------------------------------------------------------------
if Config.SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(dsn=Config.SENTRY_DSN, integrations=[FlaskIntegration()], traces_sample_rate=0.1)
        logger.info("Sentry initialized")
    except Exception as e:
        logger.warning(f"Sentry init failed: {e}")

# Validate required environment variables — fatal if missing
Config.validate_required_vars()
logger.info("All required environment variables are set")

# Refuse to start in production with the default secret key
Config.check_secret_key()
Config.check_verify_token()
Config.check_production_database()

# ---------------------------------------------------------------------------
# Create Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = Config.SECRET_KEY

# Session hardening
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=Config.SESSION_TIMEOUT_HOURS)
app.config['SESSION_COOKIE_SECURE'] = Config.SESSION_COOKIE_SECURE
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

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


# ProxyFix: trust X-Forwarded-For from Render's reverse proxy so
# request.remote_addr returns the real client IP (needed for rate limiting).
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
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
    return jsonify(health_check())


@app.route("/ping")
def ping():
    return jsonify({"status": "pong", "timestamp": datetime.utcnow().isoformat()})


@app.route("/webhook/test")
def webhook_test():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------
logger.info("Starting Chata application...")
if init_database():
    logger.info("Database initialized successfully")
else:
    logger.error("Database initialization failed - some features may not work")

if Config.RUN_MIGRATIONS_ON_STARTUP:
    logger.info("Running database migrations...")
    from update_schema import (
        migrate_client_settings,
        migrate_instagram_connections,
        migrate_messages_connection_id,
        migrate_conversation_senders,
        migrate_client_settings_advanced_params,
        migrate_instagram_connections_webhook,
        migrate_queue_tables_and_indexes,
    )
    _migrations = [
        ("migrate_client_settings", migrate_client_settings),
        ("migrate_instagram_connections", migrate_instagram_connections),
        ("migrate_messages_connection_id", migrate_messages_connection_id),
        ("migrate_conversation_senders", migrate_conversation_senders),
        ("migrate_client_settings_advanced_params", migrate_client_settings_advanced_params),
        ("migrate_instagram_connections_webhook", migrate_instagram_connections_webhook),
        ("migrate_queue_tables_and_indexes", migrate_queue_tables_and_indexes),
    ]
    for name, fn in _migrations:
        try:
            if not fn():
                logger.error(f"Migration failed: {name}")
        except Exception as e:
            logger.error(f"Migration error ({name}): {e}")
else:
    logger.info("Skipping migration on startup (RUN_MIGRATIONS_ON_STARTUP=false)")


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
