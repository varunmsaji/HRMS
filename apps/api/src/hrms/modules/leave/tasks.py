"""Celery tasks owned by the Leave module — L3's monthly accrual (LEAVE_DECISION_LOG.md LD-06),
L5's comp-off credit + expiry sweep (LD-07/LD-14), and the year-end sweep (yearly accrual +
carry-forward cap enforcement, LD-20/LD-21).

Two-tier fan-out, per `docs/architecture/04_Background_Job_Architecture.md` §3's "`company_id`
first argument on every task, no ambient request context" convention: each Beat-scheduled,
no-arg entrypoint (`run_monthly_accrual`, `run_comp_off_credit_sweep`,
`run_comp_off_expiry_sweep`) enumerates active companies and dispatches one per-company task, so
one tenant's failure/retry never blocks another's. Tasks are sync (Celery's default), each
bridging into this codebase's async session/service layer via `asyncio.run` — there is no prior
async-task precedent here to mirror; `health.ping` takes no arguments and opens no DB session.
"""

import asyncio
from datetime import date
from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy import select
from sqlalchemy.exc import InterfaceError, OperationalError

from hrms.core.celery_app import celery_app
from hrms.core.config.settings import get_settings
from hrms.core.db.models.identity import Company
from hrms.core.db.session import session_scope
from hrms.core.observability.logging import get_logger, safe_error
from hrms.shared.business_time import business_today

_logger = get_logger(__name__)


class _LeaveTask(Task):  # type: ignore[misc]
    """LM-11 - failures of a Leave background task are logged with the task id and its arguments
    (never swallowed by Celery's result backend alone). Alerting on the `leave_task_failed` event
    is an operations concern; the structured record is what an operator searches for."""

    def on_failure(
        self, exc: BaseException, task_id: str, args: Any, kwargs: Any, einfo: Any
    ) -> None:
        _logger.error(
            "leave_task_failed",
            task=self.name,
            task_id=task_id,
            task_args=[str(a) for a in args],
            **safe_error(exc),
        )


#: Every Leave task is idempotent (cycle keys, unique indexes, year-end markers), so it is safe to
#: acknowledge late (a worker killed mid-run is redelivered, not lost), to retry transient database
#: failures with backoff, and to bound run time. Retries are limited to connection-level errors; a
#: logic error is not retried blindly.
_TASK_OPTIONS: dict[str, Any] = {
    "base": _LeaveTask,
    "acks_late": True,
    "reject_on_worker_lost": True,
    "autoretry_for": (OperationalError, InterfaceError),
    "retry_backoff": 30,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "max_retries": 3,
}
#: A per-company run (accrual, year-end, a comp-off sweep) and the cheap fan-out that dispatches
#: them. Soft limit raises inside the task so it can stop cleanly; the hard limit kills it.
_COMPANY_LIMITS: dict[str, Any] = {"soft_time_limit": 1500, "time_limit": 1800}
_FANOUT_LIMITS: dict[str, Any] = {"soft_time_limit": 120, "time_limit": 180}


def _dispatch(task: Any, company_ids: list[UUID], *args: Any) -> int:
    """Queues one per-company task each. One company's enqueue failing (broker hiccup) is logged
    and does not stop the rest; returns how many were queued."""
    queued = 0
    for company_id in company_ids:
        try:
            task.delay(str(company_id), *args)
            queued += 1
        except Exception as exc:  # noqa: BLE001 - isolate one company, see above
            _logger.warning(
                "leave_task_dispatch_failed",
                task=getattr(task, "name", str(task)),
                company_id=str(company_id),
                **safe_error(exc),
            )
    return queued


async def _list_active_company_ids() -> list[UUID]:
    async with session_scope() as session:
        stmt = select(Company.id).where(Company.status.in_(("TRIAL", "ACTIVE")))
        return list((await session.execute(stmt)).scalars().all())


async def _accrue_company_async(company_id: UUID) -> int:
    from hrms.modules.leave.service import LeaveAccrualService
    from hrms.modules.organisation.service import OrganisationService

    async with session_scope(company_id=str(company_id)) as session:
        company = await OrganisationService(session).get_company_profile(company_id)
        # `business_today(company.timezone)`, not `datetime.now(UTC).date()` (`TZ-06`/gate
        # §16.3). `celery_app.py`'s `beat_schedule` fires this at `crontab(hour=1)` under
        # `Celery.conf.timezone = settings.app_timezone_default` (`Asia/Kolkata`), i.e. **01:00
        # IST** — squarely inside the 00:00-05:29 IST window where the UTC calendar date is
        # still *yesterday*. A `datetime.now(UTC).date()` `as_of` here computed the wrong
        # (previous) month's 1st on every run, every month. If this schedule is ever moved to
        # or past 05:30 IST the divergence stops being observable — `business_today` must stay
        # regardless, so the bug cannot resurface the next time the schedule changes.
        as_of = business_today(company.timezone)
        # Scheduled daily (see `celery_app.py`); accrues only inside the first days of the month
        # so a missed day-1 firing is repaired, while later days stay no-ops.
        if as_of.day > get_settings().leave_accrual_run_window_days:
            return 0
        return await LeaveAccrualService(session).run_for_company(company_id, as_of=as_of)


@celery_app.task(name="leave.accrue_company", **_TASK_OPTIONS, **_COMPANY_LIMITS)  # type: ignore[untyped-decorator]
def accrue_company(company_id: str) -> int:
    return asyncio.run(_accrue_company_async(UUID(company_id)))


@celery_app.task(name="leave.run_monthly_accrual", **_TASK_OPTIONS, **_FANOUT_LIMITS)  # type: ignore[untyped-decorator]
def run_monthly_accrual() -> int:
    """Beat-scheduled entrypoint (monthly cron, `celery_app.py`'s `beat_schedule`). Fans out one
    `accrue_company` task per active company rather than accruing inline — keeps each tenant's
    run independently retryable."""
    company_ids = asyncio.run(_list_active_company_ids())
    return _dispatch(accrue_company, company_ids)


async def _credit_comp_off_async(company_id: UUID) -> int:
    from hrms.modules.leave.service import LeaveCompOffService

    async with session_scope(company_id=str(company_id)) as session:
        return await LeaveCompOffService(session).credit_company(company_id)


@celery_app.task(name="leave.credit_comp_off", **_TASK_OPTIONS, **_COMPANY_LIMITS)  # type: ignore[untyped-decorator]
def credit_comp_off(company_id: str) -> int:
    return asyncio.run(_credit_comp_off_async(UUID(company_id)))


@celery_app.task(name="leave.run_comp_off_credit_sweep", **_TASK_OPTIONS, **_FANOUT_LIMITS)  # type: ignore[untyped-decorator]
def run_comp_off_credit_sweep() -> int:
    """Beat-scheduled entrypoint for L5's comp-off credit engine (LD-07/LD-14). Runs more often
    than monthly accrual — comp-off is earned continuously via approved overtime, not on a
    fixed cycle — but is idempotent per `overtime_record_id` (`LeaveCompOffService.
    credit_company`), so a shorter interval or a re-run never double-credits."""
    company_ids = asyncio.run(_list_active_company_ids())
    return _dispatch(credit_comp_off, company_ids)


async def _sweep_comp_off_expiry_async(company_id: UUID) -> int:
    from hrms.modules.leave.service import LeaveCompOffService
    from hrms.modules.organisation.service import OrganisationService

    async with session_scope(company_id=str(company_id)) as session:
        company = await OrganisationService(session).get_company_profile(company_id)
        # See `_accrue_company_async` above — this sweep fires at `crontab(minute=30, hour=1)`
        # = **01:30 IST**, also inside the 00:00-05:29 IST divergence window, so the same
        # `business_today()` requirement applies.
        return await LeaveCompOffService(session).expire_company(
            company_id, as_of=business_today(company.timezone)
        )


@celery_app.task(name="leave.sweep_comp_off_expiry", **_TASK_OPTIONS, **_COMPANY_LIMITS)  # type: ignore[untyped-decorator]
def sweep_comp_off_expiry(company_id: str) -> int:
    return asyncio.run(_sweep_comp_off_expiry_async(UUID(company_id)))


@celery_app.task(name="leave.run_comp_off_expiry_sweep", **_TASK_OPTIONS, **_FANOUT_LIMITS)  # type: ignore[untyped-decorator]
def run_comp_off_expiry_sweep() -> int:
    """Beat-scheduled entrypoint for L5's expiry sweep (LD-07/LD-14) — daily, since a comp-off
    validity window (e.g. 30/60/90 days) can lapse on any calendar day, unlike accrual's
    calendar-month cadence."""
    company_ids = asyncio.run(_list_active_company_ids())
    return _dispatch(sweep_comp_off_expiry, company_ids)


async def _run_year_end_async(company_id: UUID, as_of: date | None = None) -> int:
    from hrms.modules.leave.service import LeaveAccrualService
    from hrms.modules.organisation.service import OrganisationService

    async with session_scope(company_id=str(company_id)) as session:
        company = await OrganisationService(session).get_company_profile(company_id)
        # See `_accrue_company_async` above — this sweep fires at `crontab(hour=2)` =
        # **02:00 IST**, also inside the 00:00-05:29 IST divergence window, so the same
        # `business_today()` requirement applies. An operator may pass `as_of` explicitly to
        # recover a missed year start beyond the catch-up window (decision 16); the run is
        # idempotent per employee, so over-running is harmless.
        return await LeaveAccrualService(session).run_year_end_for_company(
            company_id, as_of=as_of or business_today(company.timezone)
        )


@celery_app.task(name="leave.run_year_end_for_company", **_TASK_OPTIONS, **_COMPANY_LIMITS)  # type: ignore[untyped-decorator]
def run_year_end_for_company(company_id: str, as_of: str | None = None) -> int:
    """Per-company year-end run. Normally dispatched by `run_year_end_sweep` with no `as_of` (the
    company-local business date, 5-day catch-up window). **Operator path** (decision 16): to
    recover a missed leave-year start run
    `celery -A entrypoints.worker call leave.run_year_end_for_company --args
    '["<company-uuid>", "<YYYY-MM-DD>"]'`, where the date is the day to process "as of" (the
    catch-up window then looks back from it). Safe to repeat."""
    return asyncio.run(
        _run_year_end_async(UUID(company_id), date.fromisoformat(as_of) if as_of else None)
    )


@celery_app.task(name="leave.run_year_end_sweep", **_TASK_OPTIONS, **_FANOUT_LIMITS)  # type: ignore[untyped-decorator]
def run_year_end_sweep() -> int:
    """Beat-scheduled entrypoint for LD-21's year-end processing — daily, since under
    `ANNIVERSARY` a different employee's leave year can start on any calendar day (only
    `CALENDAR`/`FINANCIAL`/`CUSTOM` share one company-wide date). Each per-company run checks
    every employee's own leave-year-start date and is a no-op for one whose year doesn't start
    today — idempotent either way (`exists_for_cycle`), so a daily cadence costs nothing beyond
    the check itself."""
    company_ids = asyncio.run(_list_active_company_ids())
    return _dispatch(run_year_end_for_company, company_ids)
