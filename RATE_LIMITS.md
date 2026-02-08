# Rate limits

All limits are **per IP** (via `get_remote_address`). Flask-Limiter is used.

**Storage:** By default limits are stored in memory (per worker). For shared limits across workers in production, set `RATE_LIMIT_STORAGE_URI` to a Redis URL (e.g. `redis://localhost:6379`).

| Route / scope      | Limit             | Note                                    |
|--------------------|-------------------|-----------------------------------------|
| **Signup**         | 10 per 5 minutes  | Relaxed from 3/hour for easier testing  |
| **Login**          | 10 per minute     |                                         |
| **OAuth callback** | 20 per hour       | Instagram connect flow                  |
| **Webhook**        | 150 per minute    | Meta Instagram webhook                  |
| **Default (global)** | 400 per day, 100 per hour | Applies when no route-specific limit |

When a limit is exceeded, the app returns a redirect (not 429) with a flash message:  
*"Too many attempts. Please wait a few minutes before trying again."*

**Defined in:** `app.py` (error handler), `routes/auth.py` (signup, login, OAuth), `routes/webhook.py` (webhook 150/min).  
- `@limiter.limit(...)` on each route  
- `@app.errorhandler(429)` for the friendly redirect + flash
