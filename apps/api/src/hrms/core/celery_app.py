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
        beat_schedule={
            "leave-run-monthly-accrual": {
                "task": "leave.run_monthly_accrual",
                "schedule": crontab(minute=0, hour=1, day_of_month=1),
            },
        },
    )
    return app


celery_app = create_celery_app()
