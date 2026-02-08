"""
Flask extensions — created here so both app.py and blueprints can import
without circular dependencies.

Usage:
    from extensions import limiter, csrf
"""
import os
from flask_limiter import Limiter  # type: ignore[reportMissingImports]
from flask_limiter.util import get_remote_address  # type: ignore[reportMissingImports]
from flask_wtf.csrf import CSRFProtect  # type: ignore[reportMissingImports]

# Rate limit storage: use RATE_LIMIT_STORAGE_URI for shared limits across workers (e.g. redis://localhost:6379).
# Default memory:// is per-worker; set to Redis in production for global limits.
_storage_uri = os.environ.get("RATE_LIMIT_STORAGE_URI", "memory://")
limiter = Limiter(key_func=get_remote_address, default_limits=["400 per day", "100 per hour"], storage_uri=_storage_uri)
csrf = CSRFProtect()
