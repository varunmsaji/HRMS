from hrms.core.celery_app import celery_app

# Register module tasks
from hrms.modules.health import tasks as health_tasks  # noqa: F401

app = celery_app
