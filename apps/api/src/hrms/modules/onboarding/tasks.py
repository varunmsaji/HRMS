"""Celery tasks for the transactional e-mail outbox (`email_outbox.py`).

`email_outbox.deliver_message` is the low-latency path: the committing request queues it for the one
message it just stored. `email_outbox.sweep` (Beat, every minute) is the safety net that makes the
design durable: it delivers anything a lost, skipped or failed dispatch left behind, retries
messages whose backoff has elapsed, and takes over from a worker that died mid-send. Both are
idempotent - a
message that is already SENT, FAILED, backing off or leased elsewhere is simply not claimed - so a
duplicate delivery of either task changes nothing.
"""

from uuid import UUID

from hrms.core.celery_app import celery_app
from hrms.core.db.session import run_task
from hrms.modules.onboarding.email_outbox import deliver_due, deliver_message


@celery_app.task(  # type: ignore[untyped-decorator]
    name="email_outbox.deliver_message", soft_time_limit=60, time_limit=90
)
def deliver_outbox_message(message_id: str) -> str:
    return run_task(deliver_message(UUID(message_id)))


@celery_app.task(  # type: ignore[untyped-decorator]
    name="email_outbox.sweep", soft_time_limit=240, time_limit=300
)
def sweep_email_outbox() -> dict[str, int]:
    return run_task(deliver_due())
