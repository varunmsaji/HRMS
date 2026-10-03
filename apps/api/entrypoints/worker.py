from hrms.core.celery_app import celery_app

# Register module tasks
from hrms.modules.attendance import tasks as attendance_tasks  # noqa: F401
from hrms.modules.employee import tasks as employee_tasks  # noqa: F401
from hrms.modules.employee_import import tasks as employee_import_tasks  # noqa: F401
from hrms.modules.health import tasks as health_tasks  # noqa: F401
from hrms.modules.leave import tasks as leave_tasks  # noqa: F401

app = celery_app
