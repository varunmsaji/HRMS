from celery import Celery
from celery.schedules import crontab

from hrms.core.config.settings import get_settings


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
        # docs/architecture/04_Background_Job_Architecture.md §5 — "Leave accrual | Monthly
        # cron | leave.run_monthly_accrual" is the only entry with a real task behind it so
        # far; Outbox sweep/Attendance lock are still unimplemented (planned-only in that doc).
        # LEAVE_DECISION_LOG.md LD-14 adds L5's comp-off sweep: credit runs hourly (comp-off is
        # earned continuously via approved overtime, not on a fixed cycle) while expiry runs
        # daily (a validity window can lapse on any calendar day) — both idempotent, so a missed
        # or repeated run is harmless.
        beat_schedule={
            "leave-run-monthly-accrual": {
                "task": "leave.run_monthly_accrual",
                "schedule": crontab(minute=0, hour=1, day_of_month=1),
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
        },
    )
    return app


celery_app = create_celery_app()
