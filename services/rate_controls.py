"""Redis sliding-window rate limits for webhook processing."""
import logging
import time

from config import Config

logger = logging.getLogger("chata.services.rate_controls")

_redis = None

def _get_redis():
    global _redis
    if _redis is None:
        if not Config.REDIS_URL:
            return None
        from redis import Redis
        _redis = Redis.from_url(Config.REDIS_URL, decode_responses=True)
    return _redis


def _sliding_window_allow(key: str, limit: int, window_seconds: int) -> bool:
    """Return True if the action is within the rate limit, False to throttle."""
    r = _get_redis()
    if r is None:
        return True
    now = time.time()
    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, now - window_seconds)
    pipe.zadd(key, {str(now): now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds + 10)
    results = pipe.execute()
    count = results[2]
    return count <= limit


def allow_sender_message(sender_id: str) -> bool:
    """Per-sender inbound rate limit: 30 messages per 60 seconds."""
    return _sliding_window_allow(f"rl:sender:{sender_id}", 30, 60)


def allow_user_openai(user_id: int) -> bool:
    """Per-user OpenAI call rate limit: 60 requests per 60 seconds."""
    return _sliding_window_allow(f"rl:openai:{user_id}", 60, 60)
