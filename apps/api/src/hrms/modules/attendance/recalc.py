"""Invariant C - a change that can alter already-calculated attendance queues a recalculation.

Before this, publishing a shift version, assigning a shift, editing a roster, approving a swap or
changing a policy assignment left every `attendance_day` already calculated for the affected
dates as it was, until something else (a punch, the 3-day trailing sweep, a manual range
recalculation) happened to touch it. A day older than the sweep's window kept the old result
forever, and payroll read it.

Writers call `request_recalc` inside their own transaction. It inserts one
`attendance_recalc_request` row (so the request commits or rolls back with the change itself) and,
only once that transaction has committed, kicks `attendance.process_recalc_requests` for the
company. The kick is at-most-once (`core/db/post_commit.py`); the 5-minute Beat entry
`attendance-run-recalc-requests` picks up any request whose kick was lost.

The processor recalculates only **existing, unlocked** `attendance_day` rows in the request's
range (narrowed to the employee and/or the shift the day was calculated against), one
employee-date per transaction, exactly as the sweep does (`tasks._calculate_employee_dates`).
Dates without a row are left for the sweep, a punch or `calculate-range`, as before - the queue
repairs stale results, it does not create rows. A finalized period or a locked day is skipped.
Recalculation is idempotent, so a request processed twice costs time, not correctness.
"""

from collections import defaultdict
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.post_commit import defer_until_commit
from hrms.core.db.session import session_scope
from hrms.core.observability.logging import get_logger, safe_error
from hrms.modules.attendance.models import AttendanceDay, AttendanceRecalcRequest
from hrms.shared.business_time import business_today

_logger = get_logger(__name__)

#: Requests handled per run; the rest wait for the next kick or Beat firing.
BATCH_SIZE = 50
#: After this many failed runs a request is closed with its last error, so one permanently
#: failing day cannot keep the queue busy forever. It stays visible in the table.
MAX_ATTEMPTS = 5

RecalcReason = str  # SHIFT_VERSION_PUBLISHED, ASSIGNMENT_CREATED, ROSTER_CHANGED, ...


async def request_recalc(
    session: AsyncSession,
    *,
    company_id: UUID,
    date_from: date,
    date_to: date | None = None,
    reason: RecalcReason,
    employee_id: UUID | None = None,
    shift_id: UUID | None = None,
    source_entity_type: str | None = None,
    source_entity_id: UUID | None = None,
    requested_by: UUID | None = None,
) -> None:
    """Queue a recalculation of `[date_from, date_to]` in the caller's transaction. `employee_id`
    None means every employee; `shift_id` set means only days calculated against that shift.
    `date_to` None means the company's today (no row exists for a later date) and is clamped to
    it either way. An empty range (a change that only affects the future) is a no-op."""
    from hrms.modules.organisation.service import OrganisationService

    company = await OrganisationService(session).get_company_profile(company_id)
    today = business_today(company.timezone)
    date_to = today if date_to is None else min(date_to, today)
    if date_from > date_to:
        return
    session.add(
        AttendanceRecalcRequest(
            id=uuid4(),
            company_id=company_id,
            employee_id=employee_id,
            shift_id=shift_id,
            date_from=date_from,
            date_to=date_to,
            reason=reason,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            requested_by=requested_by,
            attempts=0,
        )
    )

    async def _kick() -> None:
        from hrms.modules.attendance.tasks import process_recalc_requests_company

        process_recalc_requests_company.delay(str(company_id))

    defer_until_commit(session, _kick)


async def _pending_requests(company_id: UUID) -> list[AttendanceRecalcRequest]:
    async with session_scope(company_id=str(company_id)) as session:
        stmt = (
            select(AttendanceRecalcRequest)
            .where(
                AttendanceRecalcRequest.company_id == company_id,
                AttendanceRecalcRequest.processed_at.is_(None),
            )
            .order_by(AttendanceRecalcRequest.created_at, AttendanceRecalcRequest.id)
            .limit(BATCH_SIZE)
        )
        rows = list((await session.execute(stmt)).scalars().all())
        session.expunge_all()
        return rows


async def _affected_days(
    company_id: UUID, request: AttendanceRecalcRequest
) -> dict[UUID, list[date]]:
    async with session_scope(company_id=str(company_id)) as session:
        stmt = select(AttendanceDay.employee_id, AttendanceDay.attendance_date).where(
            AttendanceDay.company_id == company_id,
            AttendanceDay.attendance_date >= request.date_from,
            AttendanceDay.attendance_date <= request.date_to,
            AttendanceDay.is_locked.is_(False),
        )
        if request.employee_id is not None:
            stmt = stmt.where(AttendanceDay.employee_id == request.employee_id)
        if request.shift_id is not None:
            stmt = stmt.where(AttendanceDay.shift_id == request.shift_id)
        by_employee: dict[UUID, list[date]] = defaultdict(list)
        for employee_id, attendance_date in (await session.execute(stmt)).all():
            by_employee[employee_id].append(attendance_date)
        return by_employee


async def _finish(company_id: UUID, request_id: UUID, *, attempts: int, error: str | None) -> None:
    done = error is None or attempts >= MAX_ATTEMPTS
    async with session_scope(company_id=str(company_id)) as session:
        await session.execute(
            update(AttendanceRecalcRequest)
            .where(
                AttendanceRecalcRequest.company_id == company_id,
                AttendanceRecalcRequest.id == request_id,
            )
            .values(
                attempts=attempts,
                last_error=error,
                processed_at=datetime.now(UTC) if done else None,
            )
        )


async def process_company_requests(company_id: UUID) -> dict[str, int]:
    """Process up to `BATCH_SIZE` pending requests for one company, oldest first. A request is
    closed when every affected day recalculated (or was skipped as locked); a day that failed or
    timed out leaves it pending for the next run, up to `MAX_ATTEMPTS`."""
    from hrms.modules.attendance.tasks import _calculate_employee_dates

    totals = {"requests": 0, "calculated": 0, "skipped_locked": 0, "failed": 0}
    for request in await _pending_requests(company_id):
        totals["requests"] += 1
        attempts = request.attempts + 1
        error: str | None = None
        try:
            for employee_id, dates in (await _affected_days(company_id, request)).items():
                outcome = await _calculate_employee_dates(
                    company_id, employee_id, dates, actor_user_id=request.requested_by
                )
                totals["calculated"] += outcome["calculated"]
                totals["skipped_locked"] += outcome["skipped_locked"]
                not_done = outcome["failed"] + outcome["timed_out"]
                totals["failed"] += not_done
                if not_done:
                    error = f"{not_done} day(s) failed or timed out"
        except Exception as exc:  # noqa: BLE001 - one bad request must not block the rest
            error = type(exc).__name__
            _logger.warning(
                "attendance_recalc_request_failed",
                company_id=str(company_id),
                request_id=str(request.id),
                **safe_error(exc),
            )
        await _finish(company_id, request.id, attempts=attempts, error=error)
        if error is not None and attempts >= MAX_ATTEMPTS:
            _logger.error(
                "attendance_recalc_request_abandoned",
                company_id=str(company_id),
                request_id=str(request.id),
                reason=request.reason,
                last_error=error,
            )
    return totals
