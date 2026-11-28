"""Celery task that pushes one notification to the recipient's registered phones.

Queued after the notification commits (`NotificationService._queue_push`). The task re-reads the
notification (so it pushes what is stored, and skips one the user already read or dismissed) and
the recipient's tokens, sends to each, and deletes tokens FCM reports as dead. A failed send is
logged and not retried: the in-app notification stays the source of truth.
"""

from uuid import UUID

from sqlalchemy import select

from hrms.core.celery_app import celery_app
from hrms.core.db.session import run_task, session_scope
from hrms.modules.notification.models import Notification
from hrms.modules.notification.push import PushMessage, PushResult, PushSender, get_push_sender
from hrms.modules.notification.repository import DeviceRepository

_PUSH_LIMITS = {"soft_time_limit": 60, "time_limit": 90}


async def push_notification(
    company_id: UUID, notification_id: UUID, sender: PushSender | None = None
) -> dict[str, int]:
    """Returns counts (sent / removed / failed) for logs and tests."""
    sender = sender or get_push_sender()
    counts = {"sent": 0, "removed": 0, "failed": 0}
    dead: list[UUID] = []
    async with session_scope(company_id=str(company_id)) as session:
        note = (
            (
                await session.execute(
                    select(Notification).where(
                        Notification.id == notification_id, Notification.company_id == company_id
                    )
                )
            )
            .scalars()
            .first()
        )
        if note is None or note.read_at is not None or note.dismissed_at is not None:
            return counts
        devices = await DeviceRepository().for_user(
            session, company_id=company_id, user_id=note.recipient_user_id
        )
        message = PushMessage(
            title=note.title,
            body=note.body,
            data={
                "notification_id": str(note.id),
                "type": note.type,
                "action_url": note.action_url or "",
            },
            high_priority=note.priority == "HIGH",
        )
        for device in devices:
            result = await sender.send(device.token, message)
            if result is PushResult.SENT:
                counts["sent"] += 1
            elif result is PushResult.INVALID_TOKEN:
                dead.append(device.id)
                counts["removed"] += 1
            else:
                counts["failed"] += 1
        await DeviceRepository().delete_ids(session, company_id=company_id, ids=dead)
    return counts


@celery_app.task(name="notification.send_push", **_PUSH_LIMITS)  # type: ignore[untyped-decorator]
def send_push(company_id: str, notification_id: str) -> dict[str, int]:
    return run_task(push_notification(UUID(company_id), UUID(notification_id)))


__all__ = ["push_notification", "send_push"]
