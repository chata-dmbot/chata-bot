"""RQ task entry points for webhook processing."""
import json
import logging

from database import get_db_connection, get_param_placeholder
from services.webhook_processor import process_incoming_messages

logger = logging.getLogger("chata.jobs.webhook_tasks")


def _store_dead_letter(payload, reason, retries=0):
    conn = get_db_connection()
    if not conn:
        return
    try:
        ph = get_param_placeholder()
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO webhook_dead_letters (source, payload_json, reason, retries) "
            f"VALUES ({ph}, {ph}, {ph}, {ph})",
            ("instagram", json.dumps(payload), reason, retries),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to store dead letter: {e}")
    finally:
        conn.close()


def process_incoming_messages_task(incoming_by_sender):
    """Called by rq worker. Wraps process_incoming_messages with dead-letter capture."""
    try:
        process_incoming_messages(incoming_by_sender)
    except Exception as exc:
        logger.exception(f"Webhook task failed: {exc}")
        try:
            _store_dead_letter(incoming_by_sender, str(exc))
        except Exception:
            pass
        raise
