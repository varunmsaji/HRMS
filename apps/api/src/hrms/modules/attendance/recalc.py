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
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
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


async def earliest_unlocked_day(session: AsyncSession, company_id: UUID) -> date | None:
    """The oldest calculated, unlocked day the company has: the earliest date a calendar-wide
    change can still affect. Locked days are never recalculated, so nothing older matters."""
    return (
        await session.execute(
            select(func.min(AttendanceDay.attendance_date)).where(
                AttendanceDay.company_id == company_id, AttendanceDay.is_locked.is_(False)
            )
        )
    ).scalar_one_or_none()


async def request_calendar_recalc(
    session: AsyncSession,
    *,
    company_id: UUID,
    reason: RecalcReason,
    source_entity_type: str,
    source_entity_id: UUID | None,
    requested_by: UUID | None,
    dates: list[tuple[date, date]] | None = None,
    holiday_calendar_id: UUID | None = None,
    weekly_off_pattern_id: UUID | None = None,
    work_calendar_id: UUID | None = None,
) -> int:
    """AC-02 - a holiday, holiday-calendar, weekly-off, work-calendar or calendar-exception change
    queues a recalculation for the people it can touch, over the dates it can touch.

    *Dates*: the given ranges, or - when the change has no single date (a pattern or calendar
    edit) - from the oldest unlocked calculated day to today.
    *People*: the work calendars the change reaches (the calendar itself; every calendar linking
    the holiday calendar; every calendar using the pattern), then the policy assignments of those
    calendars (and of the pattern). An employee-scoped assignment queues that employee; a
    shift-scoped one queues days calculated against that shift; any wider scope, or no assignment
    found at all, queues the whole company - recalculation is idempotent, so an unneeded request
    only costs time, while a missed one leaves a stale day.

    Returns the number of requests queued."""
    from hrms.modules.organisation.models import (
        PolicyAssignment,
        WorkCalendar,
        WorkCalendarHolidayCalendar,
    )

    # AC-03 / P-E - approved leave follows a *dated* change (a holiday or a calendar exception
    # added, edited or removed): refund, debit or a shortfall exception, in this transaction,
    # future leave included. A calendar-wide edit (weekly-off pattern, work calendar, holiday
    # calendar validity; `dates` None) does not rewrite approved leave: Work Calendar policy A is
    # not retroactive, and P-E decided holidays only.
    if dates is not None:
        from hrms.modules.leave.reconciliation import reconcile_after_calendar_change

        await reconcile_after_calendar_change(
            session, company_id=company_id, dates=dates, actor_user_id=requested_by
        )

    ranges = dates
    if ranges is None:
        start = await earliest_unlocked_day(session, company_id)
        if start is None:
            return 0
        ranges = [(start, business_today_for(await _company_timezone(session, company_id)))]

    calendar_ids: set[UUID] = set()
    if work_calendar_id is not None:
        calendar_ids.add(work_calendar_id)
    if holiday_calendar_id is not None:
        calendar_ids.update(
            (
                await session.execute(
                    select(WorkCalendarHolidayCalendar.work_calendar_id).where(
                        WorkCalendarHolidayCalendar.company_id == company_id,
                        WorkCalendarHolidayCalendar.holiday_calendar_id == holiday_calendar_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    if weekly_off_pattern_id is not None:
        calendar_ids.update(
            (
                await session.execute(
                    select(WorkCalendar.id).where(
                        WorkCalendar.company_id == company_id,
                        WorkCalendar.weekly_off_pattern_id == weekly_off_pattern_id,
                        WorkCalendar.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )

    kinds = []
    if calendar_ids:
        kinds.append(
            (PolicyAssignment.policy_kind == "WORK_CALENDAR")
            & (PolicyAssignment.policy_id.in_(calendar_ids))
        )
    if weekly_off_pattern_id is not None:
        kinds.append(
            (PolicyAssignment.policy_kind == "WEEKLY_OFF")
            & (PolicyAssignment.policy_id == weekly_off_pattern_id)
        )
    assignments = []
    if kinds:
        from sqlalchemy import or_

        assignments = list(
            (
                await session.execute(
                    select(PolicyAssignment).where(
                        PolicyAssignment.company_id == company_id,
                        PolicyAssignment.deleted_at.is_(None),
                        PolicyAssignment.is_active.is_(True),
                        or_(*kinds),
                    )
                )
            )
            .scalars()
            .all()
        )

    targets = _targets_for_assignments(assignments)
    queued = 0
    for date_from, date_to in ranges:
        for employee_id, shift_id in targets:
            await request_recalc(
                session,
                company_id=company_id,
                date_from=date_from,
                date_to=date_to,
                reason=reason,
                employee_id=employee_id,
                shift_id=shift_id,
                source_entity_type=source_entity_type,
                source_entity_id=source_entity_id,
                requested_by=requested_by,
            )
            queued += 1
    return queued


def _targets_for_assignments(assignments: list[Any]) -> list[tuple[UUID | None, UUID | None]]:
    """`(employee_id, shift_id)` request targets for the assignments a change reaches. An
    employee- or shift-scoped assignment narrows the request; any wider scope, or no assignment
    at all, is the whole company (a superset: recalculation is idempotent)."""
    company_wide = not assignments or any(
        a.scope_type not in ("EMPLOYEE", "SHIFT") or a.scope_id is None for a in assignments
    )
    if company_wide:
        return [(None, None)]
    employee_ids = {a.scope_id for a in assignments if a.scope_type == "EMPLOYEE" and a.scope_id}
    shift_ids = {a.scope_id for a in assignments if a.scope_type == "SHIFT" and a.scope_id}
    return [(e, None) for e in sorted(employee_ids)] + [(None, sh) for sh in sorted(shift_ids)]


async def request_policy_version_recalc(
    session: AsyncSession,
    *,
    company_id: UUID,
    policy_kind: str,
    policy_id: UUID,
    effective_from: date,
    source_entity_type: str,
    source_entity_id: UUID | None,
    requested_by: UUID | None,
) -> int:
    """AC-07 - publishing a version of an attendance or overtime policy changes the rules for
    everyone assigned that policy, from the version's `effective_from`. Scope: the policy's own
    assignments (never unrelated employees); see `_targets_for_assignments`. Returns the number of
    requests queued. Locked days are untouched, as for every request."""
    from sqlalchemy import or_

    from hrms.modules.organisation.models import PolicyAssignment

    assignments = list(
        (
            await session.execute(
                select(PolicyAssignment).where(
                    PolicyAssignment.company_id == company_id,
                    PolicyAssignment.policy_kind == policy_kind,
                    PolicyAssignment.policy_id == policy_id,
                    PolicyAssignment.deleted_at.is_(None),
                    PolicyAssignment.is_active.is_(True),
                    or_(
                        PolicyAssignment.effective_to.is_(None),
                        PolicyAssignment.effective_to >= effective_from,
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    if not assignments:
        return 0  # nobody is on this policy, so no calculated day can use it
    queued = 0
    for employee_id, shift_id in _targets_for_assignments(assignments):
        await request_recalc(
            session,
            company_id=company_id,
            date_from=effective_from,
            reason="POLICY_VERSION_PUBLISHED",
            employee_id=employee_id,
            shift_id=shift_id,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            requested_by=requested_by,
        )
        queued += 1
    return queued


async def _company_timezone(session: AsyncSession, company_id: UUID) -> str:
    from hrms.modules.organisation.service import OrganisationService

    return (await OrganisationService(session).get_company_profile(company_id)).timezone


def business_today_for(timezone: str) -> date:
    return business_today(timezone)


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
