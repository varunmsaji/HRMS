"""Helpers for modules that produce notifications.

A notification is a side effect of a business change and must never be able to fail or undo it:
`notify` runs every insert inside one SAVEPOINT and swallows (and logs) anything that goes wrong.
It runs in the caller's transaction, so a notification commits with the change that caused it and
disappears if that change rolls back.

Recipients are always resolved server-side from business data (an employee's own login, the
reviewer snapshotted on a request, or the holders of a permission), never taken from a request.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.modules.notification.service import NotificationService
from hrms.modules.notification.types import NotificationType

_logger = get_logger(__name__)


async def employee_user_id(
    session: AsyncSession, company_id: UUID, employee_id: UUID | None
) -> UUID | None:
    """The login linked to an employee, or None when the employee has none."""
    if employee_id is None:
        return None
    result = await session.execute(
        text("SELECT user_id FROM employee WHERE id = :eid AND company_id = :cid"),
        {"eid": employee_id, "cid": company_id},
    )
    return result.scalar_one_or_none()


async def employee_user_ids(
    session: AsyncSession, company_id: UUID, employee_ids: Iterable[UUID]
) -> list[UUID]:
    """Bulk form of `employee_user_id`; employees without a login are skipped."""
    ids = list(employee_ids)
    if not ids:
        return []
    result = await session.execute(
        text(
            "SELECT user_id FROM employee"
            " WHERE company_id = :cid AND id = ANY(:ids) AND user_id IS NOT NULL"
        ),
        {"cid": company_id, "ids": ids},
    )
    return list(result.scalars().all())


async def employee_name(session: AsyncSession, company_id: UUID, employee_id: UUID) -> str:
    row = (
        await session.execute(
            text(
                "SELECT display_name, first_name, last_name FROM employee"
                " WHERE id = :eid AND company_id = :cid"
            ),
            {"eid": employee_id, "cid": company_id},
        )
    ).first()
    if row is None:
        return "An employee"
    if row.display_name:
        return str(row.display_name)
    return " ".join(part for part in (row.first_name, row.last_name) if part) or "An employee"


async def permission_holder_user_ids(
    session: AsyncSession, company_id: UUID, permission_code: str
) -> list[UUID]:
    """Active members of the company holding `permission_code` with company-wide scope - the
    people who can act on anything in the company (e.g. the HR stage of an approval)."""
    rows = await session.execute(
        text(
            """
            SELECT DISTINCT uc.user_id
            FROM user_company uc
            JOIN user_role ur ON ur.user_company_id = uc.id
            JOIN role r ON r.id = ur.role_id AND r.deleted_at IS NULL
            JOIN role_permission rp ON rp.role_id = r.id AND rp.data_scope = 'COMPANY'
            JOIN permission p ON p.id = rp.permission_id AND p.code = :code
            WHERE uc.company_id = :cid AND uc.status = 'ACTIVE'
              AND (r.company_id IS NULL OR r.company_id = :cid)
            """
        ),
        {"cid": company_id, "code": permission_code},
    )
    return list(rows.scalars().all())


async def notify(
    session: AsyncSession,
    *,
    company_id: UUID,
    recipients: Iterable[UUID | None],
    exclude: Iterable[UUID | None] = (),
    type: NotificationType,
    title: str,
    body: str,
    dedupe_key: str,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    action_url: str | None = None,
    action_label: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Sends one notification to each distinct recipient (minus `exclude`, typically the person
    who performed the action). Returns how many were created; 0 on any failure."""
    skip = {u for u in exclude if u is not None}
    targets = list(dict.fromkeys(u for u in recipients if u is not None and u not in skip))
    if not targets:
        return 0
    created = 0
    try:
        async with session.begin_nested():
            service = NotificationService(session)
            for user_id in targets:
                row = await service.create_notification(
                    company_id=company_id,
                    recipient_user_id=user_id,
                    type=type,
                    title=title,
                    body=body,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    action_url=action_url,
                    action_label=action_label,
                    metadata=metadata,
                    dedupe_key=dedupe_key,
                )
                created += row is not None
    except Exception as exc:  # noqa: BLE001 - the business change is the source of truth
        safe_log(_logger.warning, "notification.produce_failed", type=type.code, **safe_error(exc))
        return 0
    return created


async def settle(
    session: AsyncSession,
    *,
    company_id: UUID,
    entity_type: str,
    entity_id: UUID,
    types: Iterable[NotificationType],
) -> None:
    """Marks earlier notifications about one entity as read, e.g. "waiting for your approval"
    once the request has moved on, so nobody is left with a stale call to action."""
    codes = [t.code for t in types]
    try:
        async with session.begin_nested():
            await session.execute(
                text(
                    "UPDATE notification SET read_at = :now, updated_at = :now"
                    " WHERE company_id = :cid AND entity_type = :et AND entity_id = :eid"
                    " AND type = ANY(:codes) AND read_at IS NULL"
                ),
                {
                    "now": datetime.now(UTC),
                    "cid": company_id,
                    "et": entity_type,
                    "eid": entity_id,
                    "codes": codes,
                },
            )
    except Exception as exc:  # noqa: BLE001 - same rule as `notify`
        safe_log(_logger.warning, "notification.settle_failed", **safe_error(exc))
