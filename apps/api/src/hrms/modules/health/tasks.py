from hrms.core.celery_app import celery_app


@celery_app.task(name="health.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    return "pong"
