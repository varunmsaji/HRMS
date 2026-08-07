from celery import Celery

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
    )
    return app


celery_app = create_celery_app()
