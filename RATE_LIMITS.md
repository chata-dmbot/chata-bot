# Rate limits

All limits are **per IP** (via `get_remote_address`). Flask-Limiter is used.

| Route / scope      | Limit             | Note                                    |
|--------------------|-------------------|-----------------------------------------|
| **Signup**         | 10 per 5 minutes  | Relaxed from 3/hour for easier testing  |
| **Login**          | 10 per minute     |                                         |
| **OAuth callback** | 20 per hour       | Instagram connect flow                  |
| **Webhook**        | 150 per minute    | Meta Instagram webhook                  |
| **Default (global)** | 400 per day, 100 per hour | Applies when no route-specific limit |

When a limit is exceeded, the app returns a redirect (not 429) with a flash message:  
*"Too many attempts. Please wait a few minutes before trying again."*

**Defined in:** `app.py`  
- `@limiter.limit(...)` on each route  
- `@app.errorhandler(429)` for the friendly redirect + flash
