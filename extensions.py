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

# Rate limit storage: prefer explicit RATE_LIMIT_STORAGE_URI, then REDIS_URL, then memory://.
# memory:// is per-worker and broken in multi-worker production; Redis is required.
_storage_uri = (
    os.environ.get("RATE_LIMIT_STORAGE_URI")
    or os.environ.get("REDIS_URL")
    or "memory://"
)
limiter = Limiter(key_func=get_remote_address, default_limits=["400 per day", "100 per hour"], storage_uri=_storage_uri)
csrf = CSRFProtect()
