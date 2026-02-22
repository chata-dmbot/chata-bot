"""
Health check and monitoring utilities
"""
import os
from datetime import datetime
from database import get_db_connection
from config import Config


def _is_production():
    """True when running in production (PostgreSQL in use)."""
    url = os.environ.get("DATABASE_URL") or getattr(Config, "DATABASE_URL", None)
    return bool(url and (url.startswith("postgres://") or url.startswith("postgresql://")))


def health_check():
    """Comprehensive health check for the application.
    In production, checks return only 'healthy' or 'unhealthy' (no env var names or exception details).
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {}
    }
    production = _is_production()

    # Check database connection
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            conn.close()
            health_status["checks"]["database"] = "healthy"
        else:
            health_status["checks"]["database"] = "unhealthy"
            health_status["status"] = "unhealthy"
    except Exception as e:
        health_status["checks"]["database"] = "unhealthy" if production else f"unhealthy: {str(e)}"
        health_status["status"] = "unhealthy"

    # Check environment variables
    required_vars = [
        'OPENAI_API_KEY',
        'FACEBOOK_APP_ID',
        'FACEBOOK_APP_SECRET',
        'SECRET_KEY',
        'VERIFY_TOKEN',
        'REDIS_URL',
        'STRIPE_SECRET_KEY',
        'STRIPE_WEBHOOK_SECRET',
    ]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        health_status["checks"]["environment"] = "unhealthy" if production else f"unhealthy: missing {', '.join(missing_vars)}"
        health_status["status"] = "unhealthy"
    else:
        health_status["checks"]["environment"] = "healthy"

    # Check OpenAI API (basic connectivity)
    try:
        import openai
        openai.api_key = Config.OPENAI_API_KEY
        if Config.OPENAI_API_KEY and Config.OPENAI_API_KEY.startswith('sk-'):
            health_status["checks"]["openai"] = "healthy"
        else:
            health_status["checks"]["openai"] = "unhealthy" if production else "unhealthy: invalid API key format"
            health_status["status"] = "unhealthy"
    except Exception as e:
        health_status["checks"]["openai"] = "unhealthy" if production else f"unhealthy: {str(e)}"
        health_status["status"] = "unhealthy"

    return health_status

def get_system_info():
    """Get system information for monitoring"""
    return {
        "python_version": os.sys.version,
        "environment": os.getenv("FLASK_ENV", "development"),
        "database_type": "postgresql" if os.getenv("DATABASE_URL") else "sqlite",
        "timestamp": datetime.utcnow().isoformat()
    }
