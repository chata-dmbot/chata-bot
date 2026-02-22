"""Cost and reliability guardrails for OpenAI API calls."""
import logging
import time
from datetime import date

from config import Config

logger = logging.getLogger("chata.services.openai_guardrails")


class OpenAIBudgetExceeded(Exception):
    pass


class OpenAICircuitOpen(Exception):
    pass


# ---------------------------------------------------------------------------
# Token / cost estimation
# ---------------------------------------------------------------------------

COST_PER_1K_PROMPT = 0.00015
COST_PER_1K_COMPLETION = 0.0006


def estimate_cost_usd(prompt_tokens, completion_tokens):
    return (prompt_tokens / 1000) * COST_PER_1K_PROMPT + (completion_tokens / 1000) * COST_PER_1K_COMPLETION


# ---------------------------------------------------------------------------
# Per-user daily budget (database-backed)
# ---------------------------------------------------------------------------

def check_and_reserve_user_budget(user_id, estimated_prompt_tokens=500, estimated_completion_tokens=300):
    """Check user daily budget and reserve estimated cost. Raises OpenAIBudgetExceeded if over."""
    if not user_id:
        return
    est_cost = estimate_cost_usd(estimated_prompt_tokens, estimated_completion_tokens)
    from database import get_db_connection, get_param_placeholder
    conn = get_db_connection()
    if not conn:
        raise OpenAIBudgetExceeded("Database unavailable for budget check.")
    try:
        ph = get_param_placeholder()
        cursor = conn.cursor()
        today = date.today().isoformat()
        from database import is_postgres
        if is_postgres():
            cursor.execute(
                f"INSERT INTO user_daily_ai_usage (user_id, usage_date, estimated_cost_usd) "
                f"VALUES ({ph}, {ph}, {ph}) "
                f"ON CONFLICT (user_id, usage_date) DO UPDATE SET "
                f"estimated_cost_usd = user_daily_ai_usage.estimated_cost_usd + EXCLUDED.estimated_cost_usd, "
                f"requests_count = user_daily_ai_usage.requests_count + 1, "
                f"updated_at = CURRENT_TIMESTAMP",
                (user_id, today, est_cost),
            )
        else:
            cursor.execute(
                f"INSERT INTO user_daily_ai_usage (user_id, usage_date, estimated_cost_usd) "
                f"VALUES ({ph}, {ph}, {ph}) "
                f"ON CONFLICT (user_id, usage_date) DO UPDATE SET "
                f"estimated_cost_usd = estimated_cost_usd + {ph}, "
                f"requests_count = requests_count + 1, "
                f"updated_at = CURRENT_TIMESTAMP",
                (user_id, today, est_cost, est_cost),
            )
        conn.commit()

        cursor.execute(
            f"SELECT estimated_cost_usd FROM user_daily_ai_usage WHERE user_id = {ph} AND usage_date = {ph}",
            (user_id, today),
        )
        row = cursor.fetchone()
        if row and row[0] > Config.OPENAI_DAILY_BUDGET_USD:
            raise OpenAIBudgetExceeded(f"User {user_id} daily budget exceeded (${row[0]:.4f} > ${Config.OPENAI_DAILY_BUDGET_USD})")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Redis circuit breaker
# ---------------------------------------------------------------------------

_CB_KEY = "cb:openai"
_CB_FAILURE_THRESHOLD = 8
_CB_WINDOW_SECONDS = 120
_CB_OPEN_SECONDS = 60


_redis = None

def _get_redis():
    global _redis
    if _redis is None:
        if not Config.REDIS_URL:
            return None
        from redis import Redis
        _redis = Redis.from_url(Config.REDIS_URL, decode_responses=True)
    return _redis


def record_openai_success():
    r = _get_redis()
    if r:
        r.delete(_CB_KEY)


def record_openai_failure():
    r = _get_redis()
    if not r:
        return
    now = time.time()
    pipe = r.pipeline()
    pipe.zremrangebyscore(_CB_KEY, 0, now - _CB_WINDOW_SECONDS)
    pipe.zadd(_CB_KEY, {str(now): now})
    pipe.zcard(_CB_KEY)
    pipe.expire(_CB_KEY, _CB_WINDOW_SECONDS + 10)
    results = pipe.execute()
    count = results[2]
    if count >= _CB_FAILURE_THRESHOLD:
        r.set("cb:openai:open", "1", ex=_CB_OPEN_SECONDS)
        logger.warning("OpenAI circuit breaker OPEN")


def check_circuit_breaker():
    """Raise OpenAICircuitOpen if the circuit breaker is open."""
    r = _get_redis()
    if r and r.get("cb:openai:open"):
        raise OpenAICircuitOpen("OpenAI circuit breaker is open; skipping call")


# ---------------------------------------------------------------------------
# Retry wrapper (tenacity)
# ---------------------------------------------------------------------------

from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type
import openai as _openai


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=10, jitter=2),
    retry=retry_if_exception_type((_openai.APITimeoutError, _openai.APIConnectionError, _openai.RateLimitError)),
    reraise=True,
)
def call_with_retry(client, **kwargs):
    """Call OpenAI chat completions with automatic retry on transient errors."""
    return client.chat.completions.create(**kwargs)
