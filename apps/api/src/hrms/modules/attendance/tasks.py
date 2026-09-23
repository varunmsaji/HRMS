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
manual step."""

import asyncio
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select

from hrms.core.celery_app import celery_app
from hrms.core.db.models.identity import Company
from hrms.core.db.session import session_scope
from hrms.core.observability.logging import get_logger
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


async def _calculate_company_async(company_id: UUID) -> int:
    from hrms.modules.attendance.service import AttendanceDayService
    from hrms.modules.employee.repository import EmployeeRepository
    from hrms.modules.organisation.service import OrganisationService

    async with session_scope(company_id=str(company_id)) as session:
        company = await OrganisationService(session).get_company_profile(company_id)
        # `business_today(company.timezone)`, not `datetime.now(UTC).date()` — see the module
        # docstring's 09:30 IST reasoning. Even though this specific schedule happens to sit
        # above the skew boundary today, the derivation must stay explicit so a future schedule
        # change cannot silently reintroduce `SR-05` at this call site.
        today = business_today(company.timezone)
        trailing_dates = [today - timedelta(days=offset) for offset in range(TRAILING_DAYS)]

        employees = await EmployeeRepository().list_employees(session, company_id=company_id)
        service = AttendanceDayService(session)
        calculated = 0
        for employee in employees:
            if not employee.is_active:
                continue
            for target_date in trailing_dates:
                try:
                    # Own `SAVEPOINT` per employee-date — this task shares one session across
                    # every employee in the company (the same per-company-session shape
                    # `leave/tasks.py` uses), so one employee's failure must not poison the
                    # transaction for every employee after it in the loop. Mirrors
                    # `PunchService._try_immediate_calculate`'s own reasoning exactly.
                    async with session.begin_nested():
                        await service.calculate(
                            company_id,
                            employee.id,
                            target_date,
                            actor_user_id=None,
                        )
                    calculated += 1
                except (AttendanceDayLockedError, AttendancePeriodClosedError):
                    # Expected, not a failure — a finalized period or a locked day is exactly
                    # the state this sweep must never touch.
                    continue
                except Exception:  # noqa: BLE001 - best-effort per employee-date, see docstring
                    _logger.warning(
                        "attendance_scheduled_calculate_failed",
                        company_id=str(company_id),
                        employee_id=str(employee.id),
                        attendance_date=target_date.isoformat(),
                    )
        return calculated


@celery_app.task(name="attendance.calculate_company")  # type: ignore[untyped-decorator]
def calculate_company(company_id: str) -> int:
    return asyncio.run(_calculate_company_async(UUID(company_id)))


@celery_app.task(name="attendance.run_daily_calculation")  # type: ignore[untyped-decorator]
def run_daily_calculation() -> int:
    """Beat-scheduled entrypoint — `celery_app.py`'s `beat_schedule`, `crontab(minute=30,
    hour=9)` under `Celery.conf.timezone = settings.app_timezone_default` (`Asia/Kolkata`), i.e.
    **09:30 IST** (`CD-4`). Fans out one `calculate_company` task per active company rather than
    calculating inline — keeps each tenant's run independently retryable, exactly like
    `leave.run_monthly_accrual`."""
    company_ids = asyncio.run(_list_active_company_ids())
    for company_id in company_ids:
        calculate_company.delay(str(company_id))
    return len(company_ids)


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
) -> dict[str, int]:
    """Calculates every **employed** day in `[date_from, date_to]` for every employee with an
    employment spell overlapping it (optionally narrowed to `employee_ids`) — exactly the set of
    rows `AttendancePeriodService`'s EMPLOYEES_WITHOUT_ATTENDANCE gate requires, and no
    NOT_JOINED/EXITED rows outside employment.

    One transaction per employee (not one for the whole company, unlike the 3-day nightly
    sweep): a month for a large company is tens of thousands of employee-dates, and a failure
    late in the run must not roll back everything computed before it. Within an employee, each
    date still gets its own `SAVEPOINT`, exactly as `_calculate_company_async` does."""
    from hrms.modules.attendance.service import AttendanceDayService
    from hrms.modules.employee.service import EmploymentService

    async with session_scope(company_id=str(company_id)) as session:
        spans = await EmploymentService(session).list_spans_overlapping(
            company_id, date_from=date_from, date_to=date_to
        )
    wanted = set(employee_ids) if employee_ids is not None else None
    dates_by_employee: dict[UUID, set[date]] = {}
    for employee_id, joining_date, last_working_day in spans:
        if wanted is not None and employee_id not in wanted:
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
        async with session_scope(company_id=str(company_id)) as session:
            service = AttendanceDayService(session)
            for target_date in sorted(target_dates):
                try:
                    async with session.begin_nested():
                        await service.calculate(
                            company_id, employee_id, target_date, actor_user_id=actor_user_id
                        )
                    counts["calculated"] += 1
                except (AttendanceDayLockedError, AttendancePeriodClosedError):
                    counts["skipped_locked"] += 1
                except Exception:  # noqa: BLE001 - best-effort per employee-date, like the sweep
                    counts["failed"] += 1
                    _logger.warning(
                        "attendance_range_calculate_failed",
                        company_id=str(company_id),
                        employee_id=str(employee_id),
                        attendance_date=target_date.isoformat(),
                    )
    _logger.info(
        "attendance_range_calculate_finished",
        company_id=str(company_id),
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        **counts,
    )
    return counts


@celery_app.task(name="attendance.calculate_range")  # type: ignore[untyped-decorator]
def calculate_range(
    company_id: str,
    date_from: str,
    date_to: str,
    employee_ids: list[str] | None,
    actor_user_id: str | None,
) -> dict[str, int]:
    return asyncio.run(
        _calculate_range_async(
            UUID(company_id),
            date.fromisoformat(date_from),
            date.fromisoformat(date_to),
            [UUID(e) for e in employee_ids] if employee_ids is not None else None,
            UUID(actor_user_id) if actor_user_id else None,
        )
    )
