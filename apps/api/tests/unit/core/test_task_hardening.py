"""Mission Phase 7 — background-job reliability invariants (LOG-10/LOG-12).

* every registered task has a hard time limit (a hung task can no longer hold one of the two
  worker slots forever);
* a fan-out keeps dispatching after one company's enqueue fails, and says so;
* the publisher stamps an enqueue time so queue age is measurable;
* `hrms.ops.job_health` is read-only and flags a stale scheduler heartbeat and an old or deep
  queue."""

import json
from datetime import UTC, datetime
from typing import Any

import entrypoints.worker  # noqa: F401 — registers every task module, as the real worker does
import pytest
import structlog
from structlog.testing import capture_logs

from hrms.core.celery_app import (
    ENQUEUED_AT_HEADER,
    SCHEDULER_HEARTBEAT_KEY,
    _propagate_request_id,
    celery_app,
    dispatch_per_company,
)
from hrms.ops import job_health


@pytest.fixture(autouse=True)
def _uncached_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cache_logger_on_first_use` lets a module-level logger keep whatever pipeline was active
    when an earlier test first used it, which `capture_logs()` cannot intercept. A fresh proxy
    per test makes these assertions independent of test order."""
    monkeypatch.setattr(
        "hrms.core.celery_app._logger", structlog.get_logger("hrms.core.celery_app")
    )


def _app_tasks() -> dict[str, Any]:
    return {n: t for n, t in celery_app.tasks.items() if not n.startswith(("celery.", "test."))}


def test_every_registered_task_has_a_hard_time_limit() -> None:
    tasks = _app_tasks()
    assert "health.scheduler_heartbeat" in tasks
    missing = sorted(name for name, task in tasks.items() if not task.time_limit)
    assert missing == [], f"tasks without a hard time limit: {missing}"


def test_soft_limit_is_below_hard_limit_wherever_both_are_set() -> None:
    for name, task in _app_tasks().items():
        if task.soft_time_limit:
            assert task.soft_time_limit < task.time_limit, name


def test_the_create_only_import_has_no_soft_limit() -> None:
    # A soft limit would raise mid-batch and leave a partly imported batch (see tasks.py).
    task = celery_app.tasks["employee_import.process_batch"]
    assert task.soft_time_limit is None and task.time_limit


def test_scheduler_heartbeat_is_scheduled() -> None:
    entries = {e["task"] for e in celery_app.conf.beat_schedule.values()}
    assert "health.scheduler_heartbeat" in entries


class _FlakyTask:
    name = "test.flaky_dispatch"

    def __init__(self, failing: set[str]) -> None:
        self.failing, self.queued = failing, []

    def delay(self, company_id: str, *args: Any) -> None:
        if company_id in self.failing:
            raise ConnectionError("broker hiccup secret-detail")
        self.queued.append(company_id)


def test_fan_out_continues_past_a_failed_enqueue() -> None:
    task = _FlakyTask(failing={"c2"})
    with capture_logs() as logs:
        queued = dispatch_per_company(task, ["c1", "c2", "c3"])  # type: ignore[list-item]
    assert queued == 2
    assert task.queued == ["c1", "c3"]
    (failed,) = [e for e in logs if e["event"] == "celery_task_dispatch_failed"]
    assert failed["company_id"] == "c2"
    assert failed["error_category"] == "dependency_unreachable"
    (short,) = [e for e in logs if e["event"] == "celery_fanout_incomplete"]
    assert (short["queued"], short["failed"], short["log_level"]) == (2, 1, "error")
    assert "secret-detail" not in repr(logs)


def test_publisher_stamps_enqueue_time() -> None:
    headers: dict[str, Any] = {}
    _propagate_request_id(headers=headers)
    assert isinstance(headers[ENQUEUED_AT_HEADER], float)


# ---- job_health ---------------------------------------------------------------------------


class _ReadOnlyRedis:
    """Implements only the commands job_health may use, and records them."""

    def __init__(self, strings: dict[str, bytes], lists: dict[str, list[bytes]]) -> None:
        self.strings, self.lists, self.calls = strings, lists, []

    def get(self, name: str) -> bytes | None:
        self.calls.append("get")
        return self.strings.get(name)

    def llen(self, name: str) -> int:
        self.calls.append("llen")
        return len(self.lists.get(name, []))

    def lindex(self, name: str, index: int) -> bytes | None:
        self.calls.append("lindex")
        items = self.lists.get(name, [])
        return items[index] if items else None


NOW = 1_800_000_000.0


def _message(enqueued_at: float | None) -> bytes:
    headers = {} if enqueued_at is None else {ENQUEUED_AT_HEADER: enqueued_at}
    return json.dumps({"body": "x", "headers": headers}).encode()


def _beat(age_seconds: float) -> bytes:
    return datetime.fromtimestamp(NOW - age_seconds, tz=UTC).isoformat().encode()


def test_healthy_when_heartbeat_is_fresh_and_queues_are_empty() -> None:
    app = _ReadOnlyRedis({SCHEDULER_HEARTBEAT_KEY: _beat(30)}, {})
    report = job_health.collect(app_client=app, broker_client=_ReadOnlyRedis({}, {}), now=NOW)
    assert report["ok"] is True
    assert report["queues"]["default"]["depth"] == 0


def test_stale_or_missing_heartbeat_fails() -> None:
    stale = _ReadOnlyRedis({SCHEDULER_HEARTBEAT_KEY: _beat(900)}, {})
    report = job_health.collect(app_client=stale, broker_client=_ReadOnlyRedis({}, {}), now=NOW)
    (beat,) = [c for c in report["checks"] if c["name"] == "scheduler_heartbeat"]
    assert beat["ok"] is False and beat["value"] == 900.0
    missing = job_health.collect(
        app_client=_ReadOnlyRedis({}, {}), broker_client=_ReadOnlyRedis({}, {}), now=NOW
    )
    assert missing["ok"] is False


def test_old_and_unknown_age_messages_are_reported_without_consuming() -> None:
    app = _ReadOnlyRedis({SCHEDULER_HEARTBEAT_KEY: _beat(10)}, {})
    # LPUSH order: index 0 newest, index -1 oldest.
    broker = _ReadOnlyRedis(
        {},
        {
            "default": [_message(NOW - 5), _message(NOW - 1200)],
            "reports_exports": [_message(None)],
        },
    )
    report = job_health.collect(app_client=app, broker_client=broker, now=NOW)
    assert report["queues"]["default"] == {
        "depth": 2,
        "oldest_age_seconds": 1200.0,
        "unknown_age": False,
    }
    assert report["queues"]["reports_exports"]["unknown_age"] is True
    failing = {c["name"] for c in report["checks"] if not c["ok"]}
    assert failing == {"queue_oldest_age:default"}
    assert set(broker.calls) <= {"llen", "lindex"}  # never a consuming command
    assert len(broker.lists["default"]) == 2


def test_depth_threshold_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HRMS_QUEUE_MAX_DEPTH", "1")
    app = _ReadOnlyRedis({SCHEDULER_HEARTBEAT_KEY: _beat(10)}, {})
    broker = _ReadOnlyRedis({}, {"default": [_message(NOW), _message(NOW)]})
    report = job_health.collect(app_client=app, broker_client=broker, now=NOW)
    assert {c["name"] for c in report["checks"] if not c["ok"]} == {"queue_depth:default"}
