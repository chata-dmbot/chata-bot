"""
Flask extensions — created here so both app.py and blueprints can import
without circular dependencies.

Usage:
    from extensions import limiter, csrf
"""
from flask_limiter import Limiter  # type: ignore[reportMissingImports]
from flask_limiter.util import get_remote_address  # type: ignore[reportMissingImports]
from flask_wtf.csrf import CSRFProtect  # type: ignore[reportMissingImports]

# These are created *unbound* — app.py calls init_app() on them during startup.
limiter = Limiter(key_func=get_remote_address, default_limits=["400 per day", "100 per hour"], storage_uri="memory://")
csrf = CSRFProtect()
