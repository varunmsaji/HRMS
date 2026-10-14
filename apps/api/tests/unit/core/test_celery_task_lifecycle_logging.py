"""LOG-03 follow-up / mission Phase 7 — every task run leaves a lifecycle trail: one
`celery_task_finished` (state + duration) per run, a `celery_task_retry` per scheduled retry
classified by the *underlying* failure, `celery_task_failed` once retries are exhausted, and an
error for a message naming an unregistered task. None of them carries raw exception text."""

import pytest
import structlog
from celery.signals import task_unknown
from structlog.testing import capture_logs

from hrms.core.celery_app import celery_app


@pytest.fixture(autouse=True)
def _uncached_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cache_logger_on_first_use` lets a module-level logger keep whatever pipeline was active
    when an earlier test first used it, which `capture_logs()` cannot intercept. A fresh proxy
    per test makes these assertions independent of test order."""
    monkeypatch.setattr(
        "hrms.core.celery_app._logger", structlog.get_logger("hrms.core.celery_app")
    )


@celery_app.task(name="test.lifecycle_ok")
def _ok() -> int:
    return 7


@celery_app.task(name="test.lifecycle_flaky", bind=True, max_retries=2, default_retry_delay=0)
def _flaky(self) -> None:  # type: ignore[no-untyped-def]
    raise self.retry(exc=ConnectionError("broker down secret-detail"))


def _named(logs: list[dict], name: str) -> list[dict]:  # type: ignore[type-arg]
    return [e for e in logs if e.get("event") == name]


def test_success_emits_one_finished_event_with_duration() -> None:
    with capture_logs() as logs:
        result = _ok.apply()
    assert result.get() == 7
    (finished,) = _named(logs, "celery_task_finished")
    assert finished["log_level"] == "info"
    assert finished["task"] == "test.lifecycle_ok"
    assert finished["state"] == "SUCCESS"
    assert finished["duration_ms"] >= 0
    assert _named(logs, "celery_task_failed") == []
    # The task's log context is restored afterwards.
    assert "task_id" not in structlog.contextvars.get_contextvars()


def test_retries_are_logged_then_exhaustion_is_a_failure() -> None:
    with capture_logs() as logs:
        result = _flaky.apply()
    assert result.state == "FAILURE"

    retries = _named(logs, "celery_task_retry")
    assert [r["retries"] for r in retries] == [0, 1]
    assert all(r["log_level"] == "warning" for r in retries)
    assert all(r["exception_type"] == "ConnectionError" for r in retries)

    (failed,) = _named(logs, "celery_task_failed")
    assert failed["retries"] == 2
    assert failed["exception_type"] == "ConnectionError"

    states = [e["state"] for e in _named(logs, "celery_task_finished")]
    assert states.count("RETRY") == 2 and states.count("FAILURE") == 1
    assert "secret-detail" not in str(logs)


def test_unknown_task_message_is_an_error() -> None:
    with capture_logs() as logs:
        task_unknown.send(sender=None, name="renamed.task", id="tid-1", message=None, exc=None)
    (entry,) = _named(logs, "celery_task_unknown")
    assert entry["log_level"] == "error"
    assert entry["task"] == "renamed.task"
    assert entry["task_id"] == "tid-1"
