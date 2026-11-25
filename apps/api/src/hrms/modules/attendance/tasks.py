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

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.exc import InterfaceError, OperationalError

from hrms.core.celery_app import (
    COMPANY_TASK_LIMITS,
    FANOUT_TASK_LIMITS,
    IDEMPOTENT_TASK_OPTIONS,
    celery_app,
    dispatch_per_company,
)
from hrms.core.db.models.identity import Company
from hrms.core.db.session import run_task, session_scope
from hrms.core.db.timeouts import is_wait_timeout
from hrms.core.observability.classification import RETRYABLE_DB_CATEGORIES, error_category
from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.modules.attendance.exceptions import (
    AttendanceDayLockedError,
    AttendancePeriodClosedError,
)
from hrms.shared.business_time import business_today

_logger = get_logger(__name__)

#: `calculate()` for today plus this many trailing days — absorbs a multi-day outage or a
#: late-approved regularization without a second manual step (`CD-4`, SELECTED).
TRAILING_DAYS = 3

#: F1 - how a task that did not finish every employee-date is reported. A date that failed for a
#: *transient* reason (a lock or statement timeout, a deadlock or serialization victim, a lost
#: connection or exhausted pool) is retried - only that date, never the dates that already
#: succeeded, because every successful calculation writes an audit event and re-running it would
#: write a second one. A date that failed for any other reason (a bug, a constraint, a business
#: rule) would fail identically every time, so it is not retried; the task still finishes the rest
#: of its work and then ends as FAILURE. Either way an incomplete task never ends as SUCCESS.
_TRANSIENT_CATEGORIES = RETRYABLE_DB_CATEGORIES | {
    "db_timeout",
    "db_connection",
    "dependency_unreachable",
    "timeout",
}
#: Delay before retry n (0-based) is `_RETRY_BASE_SECONDS * 2**n`, capped, with jitter - the same
#: schedule the other idempotent tasks use (`IDEMPOTENT_TASK_OPTIONS`).
_RETRY_BASE_SECONDS = 30
_RETRY_MAX_SECONDS = 600


def _is_transient(exc: BaseException) -> bool:
    return (
        is_wait_timeout(exc)
        or isinstance(exc, (OperationalError, InterfaceError))
        or error_category(exc) in _TRANSIENT_CATEGORIES
    )


class IncompleteCalculationError(Exception):
    """Raised by an attendance calculation task that could not finish every employee-date, so
    Celery records FAILURE (and the last-success timestamp is not touched). The message carries
    counts only - never an employee, a date or an exception text."""


@dataclass
class CalcPass:
    """What one pass over a set of employee-dates left undone."""

    calculated: int = 0
    #: (employee, date) pairs that failed for a transient reason and are worth retrying.
    retry: list[tuple[UUID, date]] = field(default_factory=list)
    #: Dates that failed for a reason a retry cannot fix.
    permanent: int = 0


def _pairs_to_wire(pairs: list[tuple[UUID, date]]) -> list[list[str]]:
    return [[str(employee_id), target.isoformat()] for employee_id, target in pairs]


def _pairs_from_wire(raw: list[list[str]] | None) -> list[tuple[UUID, date]] | None:
    if raw is None:
        return None
    return [(UUID(employee_id), date.fromisoformat(target)) for employee_id, target in raw]


def _group_by_employee(pairs: list[tuple[UUID, date]]) -> dict[UUID, list[date]]:
    grouped: dict[UUID, list[date]] = defaultdict(list)
    for employee_id, target in pairs:
        grouped[employee_id].append(target)
    return grouped


def _settle(task: Any, outcome: CalcPass, *, carried_permanent: int, **log_fields: object) -> None:
    """Decides the task's final state from what a pass left undone: returns (SUCCESS) only when
    nothing is outstanding; otherwise retries just the transient failures while attempts remain
    (RETRY), and raises `IncompleteCalculationError` (FAILURE) when they are exhausted or when a
    permanent failure was seen."""
    permanent = carried_permanent + outcome.permanent
    attempt = int(task.request.retries or 0)
    summary = f"{len(outcome.retry)} transient and {permanent} permanent employee-date failure(s)"
    if outcome.retry and attempt < int(task.max_retries or 0):
        delay = min(_RETRY_BASE_SECONDS * 2**attempt, _RETRY_MAX_SECONDS)
        delay = round(delay * random.uniform(0.5, 1.0))  # noqa: S311 - jitter, not security
        safe_log(
            _logger.warning,
            "attendance_calculation_retry",
            task=task.name,
            attempt=attempt + 1,
            pending=len(outcome.retry),
            permanent=permanent,
            calculated=outcome.calculated,
            countdown_seconds=delay,
            **log_fields,
        )
        raise task.retry(
            kwargs={"only": _pairs_to_wire(outcome.retry), "permanent_failed": permanent},
            countdown=delay,
            exc=IncompleteCalculationError(summary),
        )
    if outcome.retry or permanent:
        safe_log(
            _logger.error,
            "attendance_calculation_incomplete",
            task=task.name,
            attempts=attempt + 1,
            transient=len(outcome.retry),
            permanent=permanent,
            calculated=outcome.calculated,
            **log_fields,
        )
        raise IncompleteCalculationError(summary)


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
    failures: list[tuple[date, bool]] | None = None,
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
    employee, unaffected.

    `failures`, when given, receives one `(date, transient)` entry per failed date so the calling
    task can retry exactly the transient ones (F1); the returned counts are unchanged."""
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
            if failures is not None:
                failures.append((target_date, timed_out or _is_transient(exc)))
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


async def _calculate_company_pass(
    company_id: UUID, only: list[tuple[UUID, date]] | None = None
) -> CalcPass:
    """One pass over the company's trailing window - or, when `only` is given (a retry), over
    exactly those employee-dates. Never raises for a failed date: it reports what is left."""
    from hrms.modules.employee.repository import EmployeeRepository
    from hrms.modules.organisation.service import OrganisationService

    work: list[tuple[UUID, list[date]]]
    if only is None:
        # A short read-only transaction for the company's timezone and roster; the calculations
        # below each run (and commit) in their own per-employee transaction.
        async with session_scope(company_id=str(company_id)) as session:
            company = await OrganisationService(session).get_company_profile(company_id)
            # `business_today(company.timezone)`, not `datetime.now(UTC).date()` - see the module
            # docstring's 09:30 IST reasoning. Even though this specific schedule happens to sit
            # above the skew boundary today, the derivation must stay explicit so a future
            # schedule change cannot silently reintroduce `SR-05` at this call site.
            today = business_today(company.timezone)
            employee_ids = [
                employee.id
                for employee in await EmployeeRepository().list_employees(
                    session, company_id=company_id
                )
                if employee.is_active
            ]
        trailing_dates = [today - timedelta(days=offset) for offset in range(TRAILING_DAYS)]
        work = [(employee_id, trailing_dates) for employee_id in employee_ids]
    else:
        work = list(_group_by_employee(only).items())

    result = CalcPass()
    totals = {"calculated": 0, "skipped_locked": 0, "timed_out": 0, "failed": 0}
    for employee_id, dates in work:
        failures: list[tuple[date, bool]] = []
        counts = await _calculate_employee_dates(
            company_id, employee_id, dates, actor_user_id=None, failures=failures
        )
        for key, value in counts.items():
            totals[key] += value
        for failed_date, transient in failures:
            if transient:
                result.retry.append((employee_id, failed_date))
            else:
                result.permanent += 1
    if totals["failed"] or totals["timed_out"]:
        _logger.warning(
            "attendance_scheduled_calculate_incomplete",
            company_id=str(company_id),
            employees=len(work),
            **totals,
        )
    result.calculated = totals["calculated"]
    return result


async def _calculate_company_async(company_id: UUID) -> int:
    """The number of employee-dates calculated; a failed date does not raise here. The Celery task
    uses `_calculate_company_pass` and decides success/retry/failure from what it left undone."""
    return (await _calculate_company_pass(company_id)).calculated


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="attendance.calculate_company",
    **IDEMPOTENT_TASK_OPTIONS,
    **COMPANY_TASK_LIMITS,
)
def calculate_company(
    self: Any,
    company_id: str,
    only: list[list[str]] | None = None,
    permanent_failed: int = 0,
) -> int:
    """`only` and `permanent_failed` are set by the task's own retry (F1): the employee-dates
    still to do, and the permanent failures already seen in earlier attempts."""
    outcome = run_task(_calculate_company_pass(UUID(company_id), _pairs_from_wire(only)))
    _settle(self, outcome, carried_permanent=permanent_failed, company_id=company_id)
    return outcome.calculated


@celery_app.task(name="attendance.run_daily_calculation", **FANOUT_TASK_LIMITS)  # type: ignore[untyped-decorator]
def run_daily_calculation() -> int:
    """Beat-scheduled entrypoint — `celery_app.py`'s `beat_schedule`, `crontab(minute=30,
    hour=9)` under `Celery.conf.timezone = settings.app_timezone_default` (`Asia/Kolkata`), i.e.
    **09:30 IST** (`CD-4`). Fans out one `calculate_company` task per active company rather than
    calculating inline — keeps each tenant's run independently retryable, exactly like
    `leave.run_monthly_accrual`."""
    company_ids = run_task(_list_active_company_ids())
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


async def _calculate_range_pass(
    company_id: UUID,
    date_from: date,
    date_to: date,
    employee_ids: list[UUID] | None,
    actor_user_id: UUID | None,
    legal_entity_id: UUID | None = None,
    only: list[tuple[UUID, date]] | None = None,
) -> tuple[dict[str, int], CalcPass]:
    """Calculates every **employed** day in `[date_from, date_to]` for every employee with an
    employment spell overlapping it (optionally narrowed to `employee_ids`, and to spells in
    `legal_entity_id` — decision 14, one entity's period) — exactly the set of rows
    `AttendancePeriodService`'s EMPLOYEES_WITHOUT_ATTENDANCE gate requires, and no
    NOT_JOINED/EXITED rows outside employment.

    One transaction per employee-date (`_calculate_employee_dates`, shared with the sweep): a
    month for a large company is tens of thousands of employee-dates, and a failure late in the
    run must not roll back everything computed before it."""
    from hrms.modules.employee.service import EmploymentService

    dates_by_employee: dict[UUID, set[date]] = {}
    if only is not None:
        # A retry: exactly the employee-dates that failed transiently last time.
        for employee_id, retry_dates in _group_by_employee(only).items():
            dates_by_employee[employee_id] = set(retry_dates)
    else:
        async with session_scope(company_id=str(company_id)) as session:
            spans = await EmploymentService(session).list_legal_entity_spans(
                company_id, date_from=date_from, date_to=date_to
            )
        wanted = set(employee_ids) if employee_ids is not None else None
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
    result = CalcPass()
    for employee_id, target_dates in dates_by_employee.items():
        failures: list[tuple[date, bool]] = []
        outcome = await _calculate_employee_dates(
            company_id,
            employee_id,
            list(target_dates),
            actor_user_id=actor_user_id,
            failures=failures,
        )
        counts["calculated"] += outcome["calculated"]
        counts["skipped_locked"] += outcome["skipped_locked"]
        counts["failed"] += outcome["failed"] + outcome["timed_out"]
        for failed_date, transient in failures:
            if transient:
                result.retry.append((employee_id, failed_date))
            else:
                result.permanent += 1
    _logger.info(
        "attendance_range_calculate_finished",
        company_id=str(company_id),
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        **counts,
    )
    result.calculated = counts["calculated"]
    return counts, result


async def _calculate_range_async(
    company_id: UUID,
    date_from: date,
    date_to: date,
    employee_ids: list[UUID] | None,
    actor_user_id: UUID | None,
    legal_entity_id: UUID | None = None,
) -> dict[str, int]:
    """The per-outcome counts; a failed date does not raise here. The Celery task uses
    `_calculate_range_pass` and decides success/retry/failure from what it left undone."""
    counts, _ = await _calculate_range_pass(
        company_id, date_from, date_to, employee_ids, actor_user_id, legal_entity_id
    )
    return counts


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="attendance.calculate_range",
    **IDEMPOTENT_TASK_OPTIONS,
    **COMPANY_TASK_LIMITS,
)
def calculate_range(
    self: Any,
    company_id: str,
    date_from: str,
    date_to: str,
    employee_ids: list[str] | None,
    actor_user_id: str | None,
    legal_entity_id: str | None = None,
    only: list[list[str]] | None = None,
    permanent_failed: int = 0,
) -> dict[str, int]:
    """`only` and `permanent_failed` are set by the task's own retry (F1): the employee-dates
    still to do, and the permanent failures already seen in earlier attempts."""
    counts, outcome = run_task(
        _calculate_range_pass(
            UUID(company_id),
            date.fromisoformat(date_from),
            date.fromisoformat(date_to),
            [UUID(e) for e in employee_ids] if employee_ids is not None else None,
            UUID(actor_user_id) if actor_user_id else None,
            UUID(legal_entity_id) if legal_entity_id else None,
            _pairs_from_wire(only),
        )
    )
    _settle(self, outcome, carried_permanent=permanent_failed, company_id=company_id)
    return counts


# ---------------------------------------------------------------------------
# Invariant C - queued recalculation of already-calculated days (`recalc.py`)
# ---------------------------------------------------------------------------


@celery_app.task(  # type: ignore[untyped-decorator]
    name="attendance.process_recalc_requests_company",
    **IDEMPOTENT_TASK_OPTIONS,
    **COMPANY_TASK_LIMITS,
)
def process_recalc_requests_company(company_id: str) -> dict[str, int]:
    from hrms.modules.attendance.recalc import process_company_requests

    return run_task(process_company_requests(UUID(company_id)))


@celery_app.task(name="attendance.run_recalc_requests", **FANOUT_TASK_LIMITS)  # type: ignore[untyped-decorator]
def run_recalc_requests() -> int:
    """Beat safety net (every 5 minutes) for a request whose post-commit kick was lost. The
    request table is under forced RLS, so this fans out per company; a company with nothing
    pending costs one indexed query."""
    company_ids = run_task(_list_active_company_ids())
    return dispatch_per_company(process_recalc_requests_company, company_ids)


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
    return run_task(_send_incomplete_reminders_async(UUID(company_id)))


@celery_app.task(name="attendance.run_incomplete_reminders", **FANOUT_TASK_LIMITS)  # type: ignore[untyped-decorator]
def run_incomplete_reminders() -> int:
    """Beat-scheduled entrypoint, 10:00 IST — after `run_daily_calculation` (09:30) has
    refreshed the trailing days, so a day fixed by a late punch is not reminded about."""
    company_ids = run_task(_list_active_company_ids())
    return dispatch_per_company(send_incomplete_reminders_company, company_ids)


# ---------------------------------------------------------------------------
# Attendance digest emails (`digests.py`)
# ---------------------------------------------------------------------------


async def _send_digests_async(company_id: UUID, kind: str) -> int:
    from hrms.core.config.settings import get_settings
    from hrms.modules.attendance.digests import (
        HR_WEEKLY,
        HrWeeklyDigestService,
        ManagerDailyDigestService,
    )
    from hrms.modules.onboarding.email_sender import get_email_sender
    from hrms.modules.organisation.service import OrganisationService

    settings = get_settings()
    if not settings.attendance_digests_enabled:
        return 0
    async with session_scope(company_id=str(company_id)) as session:
        company = await OrganisationService(session).get_company_profile(company_id)
        service_class = HrWeeklyDigestService if kind == HR_WEEKLY else ManagerDailyDigestService
        result = await service_class(
            session, settings, get_email_sender(settings)
        ).send_for_company(
            company_id, today=business_today(company.timezone), timezone=company.timezone
        )
    _logger.info(
        "attendance_digest_finished",
        company_id=str(company_id),
        kind=kind,
        skipped_already_sent=result.skipped_already_sent,
        skipped_opted_out=result.skipped_opted_out,
        recipients=result.recipients,
        sent=result.sent,
        send_failures=result.send_failures,
    )
    return result.sent


@celery_app.task(name="attendance.send_manager_daily_digest_company", **COMPANY_TASK_LIMITS)  # type: ignore[untyped-decorator]
def send_manager_daily_digest_company(company_id: str) -> int:
    return run_task(_send_digests_async(UUID(company_id), "manager_daily"))


@celery_app.task(name="attendance.send_hr_weekly_digest_company", **COMPANY_TASK_LIMITS)  # type: ignore[untyped-decorator]
def send_hr_weekly_digest_company(company_id: str) -> int:
    return run_task(_send_digests_async(UUID(company_id), "hr_weekly"))


def _digests_enabled() -> bool:
    from hrms.core.config.settings import get_settings

    return get_settings().attendance_digests_enabled


@celery_app.task(name="attendance.run_manager_daily_digest", **FANOUT_TASK_LIMITS)  # type: ignore[untyped-decorator]
def run_manager_daily_digest() -> int:
    """Beat-scheduled, weekday mornings, after the 09:30 calculation has refreshed today. A no-op
    unless `ATTENDANCE_DIGESTS_ENABLED`."""
    if not _digests_enabled():
        return 0
    return dispatch_per_company(
        send_manager_daily_digest_company, run_task(_list_active_company_ids())
    )


@celery_app.task(name="attendance.run_hr_weekly_digest", **FANOUT_TASK_LIMITS)  # type: ignore[untyped-decorator]
def run_hr_weekly_digest() -> int:
    """Beat-scheduled, Monday morning: last week's summary. A no-op unless
    `ATTENDANCE_DIGESTS_ENABLED`."""
    if not _digests_enabled():
        return 0
    return dispatch_per_company(send_hr_weekly_digest_company, run_task(_list_active_company_ids()))


# ---------------------------------------------------------------------------
# Face-record retention (`face_cleanup.py`)
# ---------------------------------------------------------------------------


@celery_app.task(name="attendance.cleanup_face_records_company", **COMPANY_TASK_LIMITS)  # type: ignore[untyped-decorator]
def cleanup_face_records_company(company_id: str) -> dict[str, object]:
    from dataclasses import asdict

    from hrms.core.config.settings import get_settings
    from hrms.modules.attendance.face_cleanup import cleanup_company

    return dict(asdict(run_task(cleanup_company(UUID(company_id), get_settings()))))


@celery_app.task(name="attendance.run_face_cleanup", **FANOUT_TASK_LIMITS)  # type: ignore[untyped-decorator]
def run_face_cleanup() -> int:
    """Beat-scheduled, daily. A no-op until a retention period is configured — none is defaulted,
    it needs a privacy/legal decision — and report-only until `FACE_CLEANUP_DRY_RUN=false`."""
    from hrms.core.config.settings import get_settings
    from hrms.modules.attendance.face_cleanup import _all_company_ids, retention_configured

    if not retention_configured(get_settings()):
        return 0
    return dispatch_per_company(cleanup_face_records_company, run_task(_all_company_ids()))


# ---------------------------------------------------------------------------
# External face-resource deletion outbox (`face_deletion.py`)
# ---------------------------------------------------------------------------


@celery_app.task(  # type: ignore[untyped-decorator]
    name="attendance.process_face_deletions_company",
    **IDEMPOTENT_TASK_OPTIONS,
    **COMPANY_TASK_LIMITS,
)
def process_face_deletions_company(company_id: str) -> dict[str, object]:
    from dataclasses import asdict

    from hrms.core.config.settings import get_settings
    from hrms.modules.attendance.face_deletion import process_company

    return dict(asdict(run_task(process_company(UUID(company_id), get_settings()))))


@celery_app.task(name="attendance.run_face_deletions", **FANOUT_TASK_LIMITS)  # type: ignore[untyped-decorator]
def run_face_deletions() -> int:
    """Beat-scheduled every few minutes. Deletes the Face++ FaceSets / review photos that approve,
    reject and revoke (or a compensated enrollment) queued in `face_external_deletion` — only
    after the transaction that queued them has committed. Idempotent and safe to overlap."""
    from hrms.modules.attendance.face_cleanup import _all_company_ids

    return dispatch_per_company(process_face_deletions_company, run_task(_all_company_ids()))
