import sys
from typing import Any

import structlog
from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    before_task_publish,
    setup_logging,
    task_failure,
    task_postrun,
    task_prerun,
)
from kombu import Queue  # type: ignore[import-untyped]

from hrms.core.config.settings import get_settings
from hrms.core.observability.logging import configure_logging, get_logger
from hrms.core.tenancy.context import current_request_id

_logger = get_logger(__name__)


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        "hrms",
        broker=settings.celery_broker,
        backend=settings.celery_backend,
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone=settings.app_timezone_default,
        enable_utc=True,
        task_track_started=True,
        task_default_queue="default",
        # PRA-04 — every queue a task routes to must be declared here. A worker started without
        # `-Q` (docker-compose.prod.yml, apps/api/README.md) consumes exactly the queues in
        # `task_queues`; before this list existed it consumed only `default`, so
        # `employee_import.process_batch` (`queue="reports_exports"`) was never picked up and
        # every import batch stayed PENDING. Names match what Celery auto-created before, so
        # messages already waiting in Redis under `reports_exports` are consumed as-is.
        task_queues=(
            Queue("default", routing_key="default"),
            Queue("reports_exports", routing_key="reports_exports"),
        ),
        # docs/architecture/04_Background_Job_Architecture.md §5 — "Leave accrual | Monthly
        # cron | leave.run_monthly_accrual" is the only entry with a real task behind it so
        # far; Outbox sweep/Attendance lock are still unimplemented (planned-only in that doc).
        # LEAVE_DECISION_LOG.md LD-14 adds L5's comp-off sweep: credit runs hourly (comp-off is
        # earned continuously via approved overtime, not on a fixed cycle) while expiry runs
        # daily (a validity window can lapse on any calendar day) — both idempotent, so a missed
        # or repeated run is harmless.
        beat_schedule={
            # Daily, not day-1 only (PRA-07): `leave.accrue_company` only acts during the first
            # `leave_accrual_run_window_days` days of a month and every write is idempotent, so
            # the extra runs are no-ops - but a missed day-1 firing is repaired the next day.
            "leave-run-monthly-accrual": {
                "task": "leave.run_monthly_accrual",
                "schedule": crontab(minute=0, hour=1),
            },
            "leave-run-comp-off-credit-sweep": {
                "task": "leave.run_comp_off_credit_sweep",
                "schedule": crontab(minute=0),
            },
            "leave-run-comp-off-expiry-sweep": {
                "task": "leave.run_comp_off_expiry_sweep",
                "schedule": crontab(minute=30, hour=1),
            },
            # LD-21 — yearly accrual + carry-forward cap enforcement, gated on each employee's
            # own leave-year-start date (LD-20). Daily since ANNIVERSARY-type companies have a
            # different start date per employee; idempotent, so this costs nothing on the vast
            # majority of days where nothing is due.
            "leave-run-year-end-sweep": {
                "task": "leave.run_year_end_sweep",
                "schedule": crontab(minute=0, hour=2),
            },
            # `DEC-TZ-07`/`CD-4` (SELECTED, execution gate §16.3) — daily, trailing 3 days
            # (`attendance/tasks.py::TRAILING_DAYS`). 09:30 is past the outer edge of a
            # `22:00-06:00` shift's ±2h punch pad (08:00) *and* past the 05:30 UTC-date skew
            # boundary (`TZ-06`/`SR-05`) under this same `timezone` config — see
            # `attendance/tasks.py`'s module docstring before moving this earlier.
            "attendance-run-daily-calculation": {
                "task": "attendance.run_daily_calculation",
                "schedule": crontab(minute=30, hour=9),
            },
            # Decision 5 — ends login access once a future-dated termination's last working
            # day has passed. Hourly rather than once a day: the company-local day boundary
            # differs per company timezone, and the sweep is idempotent so extra runs cost
            # nothing. Each company's "today" comes from its own timezone, never the server's.
            "employee-run-termination-access-sweep": {
                "task": "employee.run_termination_access_sweep",
                "schedule": crontab(minute=15),
            },
            # PAY-006 — after the 09:30 calculation, so reminders reflect today's refresh.
            "attendance-run-incomplete-reminders": {
                "task": "attendance.run_incomplete_reminders",
                "schedule": crontab(minute=0, hour=10),
            },
        },
    )
    return app


celery_app = create_celery_app()


@task_failure.connect  # type: ignore[untyped-decorator]
def _log_unhandled_task_failure(
    sender: Any = None,
    task_id: str | None = None,
    exception: BaseException | None = None,
    traceback: Any = None,
    einfo: Any = None,
    **_kwargs: Any,
) -> None:
    """FINDING-01 — a company-wide backstop so every task's failure leaves a structured,
    server-side trace even if its module defines no `on_failure` of its own (unlike Leave's
    `_LeaveTask`, §`leave/tasks.py`). Celery fires `task_failure` for any task that raises and is
    not retried, independent of a custom `on_failure`, so Leave tasks log twice under their own
    distinct event name plus this one — redundant, not harmful."""
    _logger.error(
        "celery_task_failed",
        task=getattr(sender, "name", str(sender)),
        task_id=task_id,
        exception_type=type(exception).__name__ if exception else "unknown",
        exception_message=str(exception) if exception else "",
    )


#: Message header carrying the API request id into a task it dispatched (LOG-03). Namespaced so
#: it can never collide with one of Celery's own protocol headers.
_REQUEST_ID_HEADER = "hrms_request_id"


@setup_logging.connect  # type: ignore[untyped-decorator]
def _configure_worker_logging(**_kwargs: Any) -> None:
    """LOG-03 — the worker and Beat used to run with structlog unconfigured (console-format
    lines, `LOG_LEVEL` ignored) while Celery configured its own plaintext stdlib handlers.
    Connecting this signal tells Celery not to configure logging itself; instead the same JSON
    contract the API uses is applied, including the stdlib tree, so Celery's own records (task
    received/succeeded, and "Task ... raised unexpected" with its traceback) become JSON lines
    too. That Celery record is the single traceback for a failed task; `celery_task_failed`
    below stays a compact, searchable summary without repeating it. The level comes from
    `LOG_LEVEL` (Settings), the same source the API uses, not the `--loglevel` CLI flag."""
    service = "beat" if "beat" in sys.argv else "worker"
    configure_logging(service, configure_stdlib=True)


@before_task_publish.connect  # type: ignore[untyped-decorator]
def _propagate_request_id(headers: dict[str, Any] | None = None, **_kwargs: Any) -> None:
    """A task enqueued while serving an HTTP request carries that request's (already validated)
    id, so the worker's log lines can be joined to the API's. Beat-scheduled tasks have none."""
    request_id = current_request_id()
    if headers is not None and request_id is not None:
        headers.setdefault(_REQUEST_ID_HEADER, request_id)


#: structlog contextvar tokens per running task id, so `task_postrun` restores exactly the
#: context that existed before the task (relevant when a task runs eagerly inside a request).
_task_log_tokens: dict[str, Any] = {}


@task_prerun.connect  # type: ignore[untyped-decorator]
def _bind_task_context(task_id: str | None = None, task: Any = None, **_kwargs: Any) -> None:
    request_id = getattr(getattr(task, "request", None), _REQUEST_ID_HEADER, None)
    tokens = structlog.contextvars.bind_contextvars(
        task_id=task_id,
        task_name=getattr(task, "name", None),
        **({"request_id": request_id} if isinstance(request_id, str) else {}),
    )
    if task_id is not None:
        _task_log_tokens[task_id] = tokens


@task_postrun.connect  # type: ignore[untyped-decorator]
def _restore_task_context(task_id: str | None = None, **_kwargs: Any) -> None:
    tokens = _task_log_tokens.pop(task_id, None) if task_id is not None else None
    if tokens:
        structlog.contextvars.reset_contextvars(**tokens)
