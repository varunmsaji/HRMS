"""EH-B-04 — every background task is explicitly classified: it retries transient database
failures (idempotent work) or it is listed, with a reason, as not retrying."""

import entrypoints.worker  # noqa: F401 - registers every module's tasks
from sqlalchemy.exc import InterfaceError, OperationalError

from hrms.core.celery_app import IDEMPOTENT_TASK_OPTIONS, celery_app
from hrms.core.task_policy import NO_RETRY_TASKS


def _app_tasks() -> dict[str, object]:
    return {n: t for n, t in celery_app.tasks.items() if not n.startswith("celery.")}


def _retries(task: object) -> bool:
    return bool(getattr(task, "autoretry_for", ()))


def test_every_task_is_either_retrying_or_listed_with_a_reason() -> None:
    unclassified = sorted(
        n for n, t in _app_tasks().items() if not _retries(t) and n not in NO_RETRY_TASKS
    )
    assert unclassified == [], (
        f"classify these in core/task_policy.py or give them retry options: {unclassified}"
    )


def test_no_task_is_both() -> None:
    both = sorted(n for n, t in _app_tasks().items() if _retries(t) and n in NO_RETRY_TASKS)
    assert both == []


def test_the_list_has_no_stale_entries() -> None:
    assert sorted(set(NO_RETRY_TASKS) - set(_app_tasks())) == []
    assert all(reason.strip() for reason in NO_RETRY_TASKS.values())


def test_retry_covers_only_connection_level_database_errors() -> None:
    assert IDEMPOTENT_TASK_OPTIONS["autoretry_for"] == (OperationalError, InterfaceError)
    for name, task in _app_tasks().items():
        if _retries(task):
            assert set(task.autoretry_for) <= {OperationalError, InterfaceError}, name  # type: ignore[attr-defined]
            assert task.acks_late and task.max_retries == 3, name  # type: ignore[attr-defined]


def test_side_effecting_tasks_never_retry() -> None:
    for name in (
        "notification.send_push",
        "email_outbox.deliver_message",
        "employee_import.process_batch",
        "attendance.send_manager_daily_digest_company",
    ):
        assert not _retries(celery_app.tasks[name]), name
