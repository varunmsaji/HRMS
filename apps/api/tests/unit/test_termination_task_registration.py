"""The termination sweep must actually be consumed by a production worker: registered under the
worker entrypoint, on the default queue the worker listens to, and scheduled by Beat."""

import importlib

from celery.schedules import crontab

from hrms.core.celery_app import celery_app


def test_termination_tasks_are_registered_by_the_worker_entrypoint() -> None:
    importlib.import_module("entrypoints.worker")
    assert "employee.run_termination_access_sweep" in celery_app.tasks
    assert "employee.enforce_terminations_company" in celery_app.tasks


def test_termination_sweep_is_scheduled_and_on_the_default_queue() -> None:
    entry = celery_app.conf.beat_schedule["employee-run-termination-access-sweep"]
    assert entry["task"] == "employee.run_termination_access_sweep"
    assert isinstance(entry["schedule"], crontab)
    # No task_routes override: both tasks land on the default queue the worker consumes
    # (`celery ... worker` runs without `-Q`).
    assert celery_app.conf.task_default_queue == "default"
    assert not (celery_app.conf.task_routes or {})
    for name in ("employee.run_termination_access_sweep", "employee.enforce_terminations_company"):
        assert getattr(celery_app.tasks[name], "queue", None) is None
    assert celery_app.conf.timezone == "Asia/Kolkata"
