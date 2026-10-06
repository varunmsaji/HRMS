"""FINDING-01 — background-job half of the requirement: a task that raises and is not retried
must leave a structured server-side trace too, even for modules (Attendance, Employee,
Organisation) that define no `on_failure` of their own, unlike Leave's `_LeaveTask`."""

from structlog.testing import capture_logs

from hrms.core.celery_app import celery_app


def test_unhandled_task_failure_is_logged() -> None:
    @celery_app.task(name="test.always_fails")
    def always_fails() -> None:
        raise RuntimeError("task exploded")

    with capture_logs() as logs:
        # `.apply()` runs the task eagerly in-process (no broker needed) and, unlike a real
        # worker dispatch, surfaces the task's own exception via `.get()` — exactly what drives
        # Celery's trace machinery to fire the `task_failure` signal either way.
        result = always_fails.apply()

    entries = [e for e in logs if e.get("event") == "celery_task_failed"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["log_level"] == "error"
    assert entry["task"] == "test.always_fails"
    assert entry["task_id"] == result.id
    assert entry["exception_type"] == "RuntimeError"
    assert entry["exception_message"] == "task exploded"
