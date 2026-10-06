"""LM-11 - every Leave Celery task is safe to redeliver and bounded, and one company failing to
enqueue never stops the others."""

import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import InterfaceError, OperationalError

from hrms.core.celery_app import celery_app
from hrms.modules.leave import tasks as leave_tasks

_COMPANY_TASKS = (
    "leave.accrue_company",
    "leave.credit_comp_off",
    "leave.sweep_comp_off_expiry",
    "leave.run_year_end_for_company",
)
_FANOUT_TASKS = (
    "leave.run_monthly_accrual",
    "leave.run_comp_off_credit_sweep",
    "leave.run_comp_off_expiry_sweep",
    "leave.run_year_end_sweep",
)


def _task(name: str):  # type: ignore[no-untyped-def]
    importlib.import_module("entrypoints.worker")
    return celery_app.tasks[name]


@pytest.mark.parametrize("name", _COMPANY_TASKS + _FANOUT_TASKS)
def test_leave_tasks_acknowledge_late_retry_transient_db_errors_and_are_time_bounded(
    name: str,
) -> None:
    task = _task(name)
    # a worker killed mid-run is redelivered rather than lost (every task is idempotent)
    assert task.acks_late is True
    assert task.reject_on_worker_lost is True
    # connection-level failures retry with backoff, a bounded number of times
    assert OperationalError in task.autoretry_for and InterfaceError in task.autoretry_for
    assert task.max_retries == 3
    assert task.retry_backoff
    # and no run can hang forever
    assert task.soft_time_limit and task.time_limit and task.soft_time_limit < task.time_limit
    expected_soft = 1500 if name in _COMPANY_TASKS else 120
    assert task.soft_time_limit == expected_soft


def test_the_year_end_task_accepts_an_operator_supplied_date() -> None:
    import inspect

    parameters = inspect.signature(_task("leave.run_year_end_for_company").run).parameters
    assert list(parameters) == ["company_id", "as_of"]
    assert parameters["as_of"].default is None


def test_year_end_is_still_scheduled_daily_so_the_catch_up_window_can_act() -> None:
    entry = celery_app.conf.beat_schedule["leave-run-year-end-sweep"]
    assert entry["task"] == "leave.run_year_end_sweep"
    assert str(entry["schedule"]).startswith("<crontab: 0 2 * * *")


def test_one_company_failing_to_enqueue_does_not_stop_the_rest() -> None:
    queued: list[str] = []

    def delay(company_id: str, *args: object) -> None:
        if company_id == bad:
            raise ConnectionError("broker down")
        queued.append(company_id)

    first, bad, last = str(uuid4()), str(uuid4()), str(uuid4())
    fake = SimpleNamespace(name="leave.test", delay=delay)
    count = leave_tasks._dispatch(fake, [first, bad, last])  # type: ignore[list-item]
    assert count == 2
    assert queued == [first, last]


def test_a_failed_leave_task_is_logged_with_its_id_and_arguments(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from structlog.testing import capture_logs

    task = _task("leave.accrue_company")
    company = str(uuid4())
    with capture_logs() as logs:
        task.on_failure(RuntimeError("boom"), "task-123", (company,), {}, None)
    failures = [entry for entry in logs if entry["event"] == "leave_task_failed"]
    assert len(failures) == 1
    assert failures[0]["task"] == "leave.accrue_company"
    assert failures[0]["task_id"] == "task-123"
    assert failures[0]["task_args"] == [company]
    assert "RuntimeError: boom" in failures[0]["error"]
