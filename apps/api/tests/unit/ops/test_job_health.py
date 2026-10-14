"""`hrms.ops.job_health` thresholds and failure modes against in-memory Redis stand-ins."""

import json
from datetime import UTC, datetime

import pytest
import redis

from hrms.core.celery_app import ENQUEUED_AT_HEADER
from hrms.ops import job_health

NOW = 1_800_000_000.0


class _Redis:
    def __init__(self, *, beat: float | None = None, queues: dict[str, list[bytes]] | None = None):
        self.beat = beat
        self.queues = queues or {}
        self.commands: list[str] = []

    def get(self, name: str) -> bytes | None:
        self.commands.append("GET")
        if self.beat is None:
            return None
        return datetime.fromtimestamp(self.beat, UTC).isoformat().encode()

    def llen(self, name: str) -> int:
        self.commands.append("LLEN")
        return len(self.queues.get(name, []))

    def lindex(self, name: str, index: int) -> bytes | None:
        self.commands.append("LINDEX")
        q = self.queues.get(name, [])
        return q[index] if q else None


def _msg(enqueued_at: float | None) -> bytes:
    headers = {} if enqueued_at is None else {ENQUEUED_AT_HEADER: enqueued_at}
    return json.dumps({"headers": headers, "body": ""}).encode()


def _checks(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {c["name"]: c for c in report["checks"]}  # type: ignore[index, union-attr]


@pytest.fixture(autouse=True)
def _default_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "HRMS_HEARTBEAT_MAX_AGE_SECONDS",
        "HRMS_QUEUE_MAX_DEPTH",
        "HRMS_QUEUE_MAX_AGE_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)


def test_healthy() -> None:
    client = _Redis(beat=NOW - 30)
    report = job_health.collect(app_client=client, broker_client=client, now=NOW)
    assert report["ok"] is True
    assert set(client.commands) <= {"GET", "LLEN", "LINDEX"}  # read-only vocabulary


def test_worker_or_beat_stopped_means_stale_or_missing_heartbeat() -> None:
    stale = _Redis(beat=NOW - 301)
    report = job_health.collect(app_client=stale, broker_client=stale, now=NOW)
    assert report["ok"] is False and _checks(report)["scheduler_heartbeat"]["ok"] is False

    never = _Redis(beat=None)
    report = job_health.collect(app_client=never, broker_client=never, now=NOW)
    beat = _checks(report)["scheduler_heartbeat"]
    assert beat["ok"] is False and beat["value"] is None


def test_queue_depth_and_oldest_age_thresholds() -> None:
    queue = job_health._queue_names()[0]
    # kombu LPUSHes, so the oldest message is the LAST element.
    deep = [_msg(NOW - 5)] * 101 + [_msg(NOW - 700)]
    client = _Redis(beat=NOW - 1, queues={queue: deep})
    report = job_health.collect(app_client=client, broker_client=client, now=NOW)
    checks = _checks(report)
    assert checks[f"queue_depth:{queue}"]["ok"] is False
    assert checks[f"queue_oldest_age:{queue}"]["ok"] is False
    assert checks[f"queue_oldest_age:{queue}"]["value"] == 700.0
    assert report["queues"][queue]["depth"] == 102


def test_messages_without_the_enqueue_header_are_flagged_unknown_not_failed() -> None:
    queue = job_health._queue_names()[0]
    client = _Redis(beat=NOW - 1, queues={queue: [_msg(None)] * 3})
    report = job_health.collect(app_client=client, broker_client=client, now=NOW)
    assert report["queues"][queue]["unknown_age"] is True
    assert _checks(report)[f"queue_oldest_age:{queue}"]["ok"] is True


def test_thresholds_are_overridable_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HRMS_HEARTBEAT_MAX_AGE_SECONDS", "10")
    monkeypatch.setenv("HRMS_QUEUE_MAX_DEPTH", "1")
    queue = job_health._queue_names()[0]
    client = _Redis(beat=NOW - 60, queues={queue: [_msg(NOW), _msg(NOW)]})
    report = job_health.collect(app_client=client, broker_client=client, now=NOW)
    checks = _checks(report)
    assert checks["scheduler_heartbeat"]["ok"] is False
    assert checks[f"queue_depth:{queue}"]["ok"] is False


def test_garbage_threshold_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HRMS_QUEUE_MAX_DEPTH", "not-a-number")
    assert job_health._threshold("HRMS_QUEUE_MAX_DEPTH", 100) == 100


def test_redis_unreachable_exits_2_with_a_machine_readable_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise redis.ConnectionError("down")

    monkeypatch.setattr(job_health, "collect", refuse)
    assert job_health.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "ok": False,
        "error": "redis_unavailable",
        "type": "ConnectionError",
    }
