"""RQ queue helpers for webhook processing."""
import logging
from redis import Redis
from rq import Queue, Retry

from config import Config

logger = logging.getLogger("chata.jobs.queue")


def get_redis_connection():
    if not Config.REDIS_URL:
        raise RuntimeError("REDIS_URL is required for background processing.")
    return Redis.from_url(Config.REDIS_URL)


def get_webhook_queue():
    return Queue(
        Config.RQ_QUEUE_NAME,
        connection=get_redis_connection(),
        default_timeout=Config.RQ_DEFAULT_TIMEOUT_SECONDS,
    )


def enqueue_incoming_messages(incoming_by_sender):
    """Enqueue incoming sender batches with retry/backoff policy."""
    queue = get_webhook_queue()
    retry = Retry(max=5, interval=[5, 15, 30, 60, 120])
    job = queue.enqueue(
        "jobs.webhook_tasks.process_incoming_messages_task",
        incoming_by_sender,
        retry=retry,
        job_timeout=Config.RQ_DEFAULT_TIMEOUT_SECONDS,
        result_ttl=3600,
        failure_ttl=7 * 24 * 3600,
    )
    logger.info(f"Enqueued webhook processing job_id={job.id} sender_batches={len(incoming_by_sender)}")
    return job.id
