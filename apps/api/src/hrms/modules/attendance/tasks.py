"""Celery tasks owned by the Attendance module — `attendance.run_daily_calculation`
(`F-14`/`PAY-001`, `DEC-TZ-07`/`CD-4` SELECTED, execution gate §16). Before this task existed, an
`attendance_day` row was created only by an interactive `POST /attendance/days/calculate` call or
by `PunchService`'s own best-effort immediate hook (`service.py`) — a period could not be
finalized, and Payroll had no input at all, until a human or a punch happened to trigger one.

Two-tier fan-out, on the exact pattern `leave/tasks.py` already established (`company_id` first
argument, no ambient request context; one no-arg Beat entrypoint enumerates active companies and
dispatches one per-company task, so one tenant's failure/retry never blocks another's).

**Why 09:30 `Asia/Kolkata`, trailing 3 days (`CD-4`, gate §16.3).** 09:30 IST is past the outer
edge of a `22:00-06:00` shift's ±2h punch-load pad (08:00 IST) *and* past the 05:30 IST/UTC-date
skew boundary (`TZ-06`/`SR-05`) — so `datetime.now(UTC).date()` would happen to give the right
answer at exactly this hour, which is precisely why this task calls `business_today()` explicitly
and documents why: moving this schedule earlier "to have results ready by 09:00" without
re-reading this note would silently reintroduce `SR-05`'s defect at a new call site. The 3-day
trailing window re-runs `calculate()` for today and the two days before it (idempotent by
construction — `calculate()` is full-row replacement, WD-10) so a missed Beat firing
(`OPS-006` — no leader election, duplicate or dropped firings are possible by design), a
multi-day outage, or a late-approved regularization is absorbed by the next run without a second
manual step.

**Transaction scope.** The sweep calculates each employee-date in its own transaction
(`_calculate_employee_dates`), committing before the next. `calculate()` takes a `FOR UPDATE` row
lock that is held until commit, so a company-wide transaction would keep every already-processed
employee's `attendance_day` row locked until the whole run finished, queueing their morning punches
behind it (measured: a punch waited the full hold). One row's lock is held for one calculation
instead. `calculate()` also bounds its lock and statement waits (`core/db/timeouts.py`), so a
blocked step fails cleanly and the sweep moves on.
"""

import asyncio
from datetime import date, timedelta
from uuid import UUID

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from hrms.core.celery_app import (
    COMPANY_TASK_LIMITS,
    FANOUT_TASK_LIMITS,
    celery_app,
    dispatch_per_company,
)
from hrms.core.db.models.identity import Company
from hrms.core.db.session import session_scope
from hrms.core.db.timeouts import is_wait_timeout
from hrms.core.observability.logging import get_logger, safe_error
from hrms.modules.attendance.exceptions import (
    AttendanceDayLockedError,
    AttendancePeriodClosedError,
)
from hrms.shared.business_time import business_today

_logger = get_logger(__name__)

#: `calculate()` for today plus this many trailing days — absorbs a multi-day outage or a
#: late-approved regularization without a second manual step (`CD-4`, SELECTED).
TRAILING_DAYS = 3


async def _list_active_company_ids() -> list[UUID]:
    async with session_scope() as session:
        stmt = select(Company.id).where(Company.status.in_(("TRIAL", "ACTIVE")))
        return list((await session.execute(stmt)).scalars().all())


async def _calculate_employee_dates(
    company_id: UUID,
    employee_id: UUID,
    target_dates: list[date],
    *,
    actor_user_id: UUID | None,
) -> dict[str, int]:
    """Calculates `target_dates` for ONE employee, each date in its OWN short transaction that is
    committed before the next starts. Shared by the nightly sweep and the range backfill, so both
    have the same transaction scope.

    `calculate()` takes a `FOR UPDATE` row lock that is held until commit. Holding it across a whole
    company starves everyone's punches (the original defect); holding it across even one employee's
    several dates is still wider than needed - a concurrent punch for that employee calculating a
    different date can then form a lock cycle with this transaction (observed as a deadlock). One
    transaction per employee-date holds exactly one row's locks, in the same order every caller
    uses, so no cycle is possible and a failure rolls back only that date.

    Outcomes are counted, never raised: `skipped_locked` (a finalized period/locked day, expected),
    `timed_out` (a lock or statement timeout - the date is left for the next run), `failed` (any
    other error). A failure on one date leaves the employee's other dates, and every other
    employee, unaffected."""
    from hrms.modules.attendance.service import AttendanceDayService

    counts = {"calculated": 0, "skipped_locked": 0, "timed_out": 0, "failed": 0}
    for target_date in sorted(target_dates):
        try:
            async with session_scope(company_id=str(company_id)) as session:
                await AttendanceDayService(session).calculate(
                    company_id, employee_id, target_date, actor_user_id=actor_user_id
                )
            counts["calculated"] += 1
        except (AttendanceDayLockedError, AttendancePeriodClosedError):
            # Expected, not a failure - a finalized period or a locked day is exactly
            # the state the sweep must never touch.
            counts["skipped_locked"] += 1
        except SoftTimeLimitExceeded:
            # The task's own time limit — stop the run, do not count it as one employee-date
            # failing and carry on until the hard limit kills the process.
            raise
        except Exception as exc:  # noqa: BLE001 - best-effort per employee-date
            timed_out = is_wait_timeout(exc)
            counts["timed_out" if timed_out else "failed"] += 1
            _logger.warning(
                "attendance_scheduled_calculate_timed_out"
                if timed_out
                else "attendance_scheduled_calculate_failed",
                company_id=str(company_id),
                employee_id=str(employee_id),
                attendance_date=target_date.isoformat(),
                **safe_error(exc),
            )
    return counts


async def _calculate_company_async(company_id: UUID) -> int:
    from hrms.modules.employee.repository import EmployeeRepository
    from hrms.modules.organisation.service import OrganisationService

    # A short read-only transaction for the company's timezone and roster; the calculations below
    # each run (and commit) in their own per-employee transaction.
    async with session_scope(company_id=str(company_id)) as session:
        company = await OrganisationService(session).get_company_profile(company_id)
        # `business_today(company.timezone)`, not `datetime.now(UTC).date()` - see the module
        # docstring's 09:30 IST reasoning. Even though this specific schedule happens to sit
        # above the skew boundary today, the derivation must stay explicit so a future schedule
        # change cannot silently reintroduce `SR-05` at this call site.
        today = business_today(company.timezone)
        employee_ids = [
            employee.id
            for employee in await EmployeeRepository().list_employees(
                session, company_id=company_id
            )
            if employee.is_active
        ]
    trailing_dates = [today - timedelta(days=offset) for offset in range(TRAILING_DAYS)]

    totals = {"calculated": 0, "skipped_locked": 0, "timed_out": 0, "failed": 0}
    for employee_id in employee_ids:
        counts = await _calculate_employee_dates(
            company_id, employee_id, trailing_dates, actor_user_id=None
        )
        for key, value in counts.items():
            totals[key] += value
    if totals["failed"] or totals["timed_out"]:
        _logger.warning(
            "attendance_scheduled_calculate_incomplete",
            company_id=str(company_id),
            employees=len(employee_ids),
            **totals,
        )
    return totals["calculated"]


@celery_app.task(name="attendance.calculate_company", **COMPANY_TASK_LIMITS)  # type: ignore[untyped-decorator]
def calculate_company(company_id: str) -> int:
    return asyncio.run(_calculate_company_async(UUID(company_id)))


@celery_app.task(name="attendance.run_daily_calculation", **FANOUT_TASK_LIMITS)  # type: ignore[untyped-decorator]
def run_daily_calculation() -> int:
    """Beat-scheduled entrypoint — `celery_app.py`'s `beat_schedule`, `crontab(minute=30,
    hour=9)` under `Celery.conf.timezone = settings.app_timezone_default` (`Asia/Kolkata`), i.e.
    **09:30 IST** (`CD-4`). Fans out one `calculate_company` task per active company rather than
    calculating inline — keeps each tenant's run independently retryable, exactly like
    `leave.run_monthly_accrual`."""
    company_ids = asyncio.run(_list_active_company_ids())
    return dispatch_per_company(calculate_company, company_ids)


# ---------------------------------------------------------------------------
# PAY-001 — date-range backfill (`POST /attendance/days/calculate-range`)
# ---------------------------------------------------------------------------


def _employed_dates(
    span_start: date, span_end: date | None, date_from: date, date_to: date
) -> list[date]:
    start = max(span_start, date_from)
    end = min(span_end or date_to, date_to)
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


async def _calculate_range_async(
    company_id: UUID,
    date_from: date,
    date_to: date,
    employee_ids: list[UUID] | None,
    actor_user_id: UUID | None,
    legal_entity_id: UUID | None = None,
) -> dict[str, int]:
    """Calculates every **employed** day in `[date_from, date_to]` for every employee with an
    employment spell overlapping it (optionally narrowed to `employee_ids`, and to spells in
    `legal_entity_id` — decision 14, one entity's period) — exactly the set of rows
    `AttendancePeriodService`'s EMPLOYEES_WITHOUT_ATTENDANCE gate requires, and no
    NOT_JOINED/EXITED rows outside employment.

    One transaction per employee-date (`_calculate_employee_dates`, shared with the sweep): a
    month for a large company is tens of thousands of employee-dates, and a failure late in the
    run must not roll back everything computed before it."""
    from hrms.modules.employee.service import EmploymentService

    async with session_scope(company_id=str(company_id)) as session:
        spans = await EmploymentService(session).list_legal_entity_spans(
            company_id, date_from=date_from, date_to=date_to
        )
    wanted = set(employee_ids) if employee_ids is not None else None
    dates_by_employee: dict[UUID, set[date]] = {}
    for employee_id, span_legal_entity_id, joining_date, last_working_day in spans:
        if wanted is not None and employee_id not in wanted:
            continue
        if legal_entity_id is not None and span_legal_entity_id != legal_entity_id:
            continue
        dates_by_employee.setdefault(employee_id, set()).update(
            _employed_dates(joining_date, last_working_day, date_from, date_to)
        )

    counts = {
        "employees": len(dates_by_employee),
        "calculated": 0,
        "skipped_locked": 0,
        "failed": 0,
    }
    for employee_id, target_dates in dates_by_employee.items():
        outcome = await _calculate_employee_dates(
            company_id, employee_id, list(target_dates), actor_user_id=actor_user_id
        )
        counts["calculated"] += outcome["calculated"]
        counts["skipped_locked"] += outcome["skipped_locked"]
        counts["failed"] += outcome["failed"] + outcome["timed_out"]
    _logger.info(
        "attendance_range_calculate_finished",
        company_id=str(company_id),
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        **counts,
    )
    return counts


@celery_app.task(name="attendance.calculate_range", **COMPANY_TASK_LIMITS)  # type: ignore[untyped-decorator]
def calculate_range(
    company_id: str,
    date_from: str,
    date_to: str,
    employee_ids: list[str] | None,
    actor_user_id: str | None,
    legal_entity_id: str | None = None,
) -> dict[str, int]:
    return asyncio.run(
        _calculate_range_async(
            UUID(company_id),
            date.fromisoformat(date_from),
            date.fromisoformat(date_to),
            [UUID(e) for e in employee_ids] if employee_ids is not None else None,
            UUID(actor_user_id) if actor_user_id else None,
            UUID(legal_entity_id) if legal_entity_id else None,
        )
    )


# ---------------------------------------------------------------------------
# PAY-006 — pre-cutoff reminders for unresolved INCOMPLETE days (`reminders.py`)
# ---------------------------------------------------------------------------


async def _send_incomplete_reminders_async(company_id: UUID) -> int:
    from hrms.core.config.settings import get_settings
    from hrms.modules.attendance.reminders import IncompleteDayReminderService
    from hrms.modules.onboarding.email_sender import get_email_sender
    from hrms.modules.organisation.service import OrganisationService

    settings = get_settings()
    async with session_scope(company_id=str(company_id)) as session:
        company = await OrganisationService(session).get_company_profile(company_id)
        results = await IncompleteDayReminderService(
            session, settings, get_email_sender(settings)
        ).send_for_company(company_id, today=business_today(company.timezone))
    notified = sum(r.employees_notified for r in results)
    _logger.info(
        "attendance_incomplete_reminders_finished",
        company_id=str(company_id),
        periods=len(results),
        employees_notified=notified,
    )
    return notified


@celery_app.task(name="attendance.send_incomplete_reminders_company", **COMPANY_TASK_LIMITS)  # type: ignore[untyped-decorator]
def send_incomplete_reminders_company(company_id: str) -> int:
    return asyncio.run(_send_incomplete_reminders_async(UUID(company_id)))


@celery_app.task(name="attendance.run_incomplete_reminders", **FANOUT_TASK_LIMITS)  # type: ignore[untyped-decorator]
def run_incomplete_reminders() -> int:
    """Beat-scheduled entrypoint, 10:00 IST — after `run_daily_calculation` (09:30) has
    refreshed the trailing days, so a day fixed by a late punch is not reminded about."""
    company_ids = asyncio.run(_list_active_company_ids())
    return dispatch_per_company(send_incomplete_reminders_company, company_ids)
