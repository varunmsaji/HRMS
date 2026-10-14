"""Mission Phases 7 and 10 against the real local Redis/Postgres:

* readiness with an unreachable database answers 503 `database: error` (it used to escape as a
  500, because a refused connection is a bare `ConnectionRefusedError`) and logs which
  dependency failed;
* the scheduler heartbeat task writes its timestamp, and `hrms.ops.job_health` reads it back;
* `job_health.main()` runs read-only against the (isolated, see tests/conftest.py) broker DB;
* a task's soft time limit stops an attendance run instead of being counted as one failed
  employee-date."""

import json
import uuid
from datetime import date

import pytest
import redis
from celery.exceptions import SoftTimeLimitExceeded
from pytest import CaptureFixture
from sqlalchemy.ext.asyncio import create_async_engine

from hrms.core.celery_app import SCHEDULER_HEARTBEAT_KEY
from hrms.core.config.settings import get_settings
from hrms.modules.attendance import tasks as attendance_tasks
from hrms.modules.health import service as health_service
from hrms.modules.health.tasks import scheduler_heartbeat
from hrms.ops import job_health


async def test_readiness_with_unreachable_database_is_503_and_logged(
    monkeypatch: pytest.MonkeyPatch, capfd: CaptureFixture[str]
) -> None:
    dead = create_async_engine("postgresql+asyncpg://x:y@127.0.0.1:1/none")
    monkeypatch.setattr(health_service, "get_engine", lambda: dead)
    capfd.readouterr()
    data = await health_service.HealthService().check_ready()
    await dead.dispose()
    assert data.ready is False
    assert data.database == "error"
    lines = [json.loads(x) for x in capfd.readouterr().out.splitlines() if x.startswith("{")]
    (event,) = [e for e in lines if e.get("event") == "readiness_dependency_failed"]
    assert event["dependency"] == "database"
    assert event["level"] == "warning"
    assert event["error_category"] == "dependency_unreachable"
    assert "exception" not in event


async def test_readiness_with_unreachable_redis_is_not_ready_and_logged(
    monkeypatch: pytest.MonkeyPatch, capfd: CaptureFixture[str]
) -> None:
    real = health_service.get_settings()
    unreachable = real.model_copy(update={"redis_url": "redis://127.0.0.1:1/0"})
    monkeypatch.setattr(health_service, "get_settings", lambda: unreachable)
    capfd.readouterr()
    data = await health_service.HealthService().check_ready()
    assert data.ready is False
    assert data.redis == "error"
    assert data.database == "ok"
    lines = [json.loads(x) for x in capfd.readouterr().out.splitlines() if x.startswith("{")]
    (event,) = [e for e in lines if e.get("event") == "readiness_dependency_failed"]
    assert event["dependency"] == "redis"


def test_readiness_does_not_probe_minio_reachability(monkeypatch: pytest.MonkeyPatch) -> None:
    """Documented gap: readiness proves storage *configuration* only. A stopped MinIO leaves the
    API 'ready'; the host monitor catches it via container state, not via this endpoint."""
    real = health_service.get_settings()
    unreachable = real.model_copy(update={"s3_endpoint_url": "http://127.0.0.1:1"})
    monkeypatch.setattr(health_service, "get_settings", lambda: unreachable)
    assert health_service._check_storage_configured() is True


def test_heartbeat_task_writes_a_timestamp_job_health_accepts() -> None:
    client = redis.Redis.from_url(get_settings().redis_url)
    try:
        scheduler_heartbeat.apply().get()
        report = job_health.collect(app_client=client, broker_client=_EmptyBroker())
        (beat,) = [c for c in report["checks"] if c["name"] == "scheduler_heartbeat"]
        assert beat["ok"] is True and beat["value"] < 60
    finally:
        client.delete(SCHEDULER_HEARTBEAT_KEY)
        client.close()


class _EmptyBroker:
    def get(self, name: str) -> None:
        return None

    def llen(self, name: str) -> int:
        return 0

    def lindex(self, name: str, index: int) -> None:
        return None


def test_main_is_read_only_against_the_isolated_broker(capsys: pytest.CaptureFixture[str]) -> None:
    settings = get_settings()
    assert settings.celery_broker != settings.redis_url  # tests/conftest.py isolation
    broker = redis.Redis.from_url(settings.celery_broker)
    queue = "default"
    marker = json.dumps({"body": "", "headers": {"id": f"probe-{uuid.uuid4()}"}})
    broker.lpush(queue, marker)
    try:
        before = broker.llen(queue)
        exit_code = job_health.main()
        report = json.loads(capsys.readouterr().out)
        assert broker.llen(queue) == before  # nothing consumed
        assert exit_code in (0, 1)
        assert report["queues"][queue]["depth"] == before
        assert report["queues"][queue]["unknown_age"] is True  # no enqueue header on the probe
    finally:
        broker.lrem(queue, 1, marker)
        broker.close()


async def test_soft_time_limit_stops_the_attendance_run(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Calc:
        def __init__(self, *_a: object) -> None: ...

        async def calculate(self, *_a: object, **_k: object) -> None:
            raise SoftTimeLimitExceeded()

    monkeypatch.setattr("hrms.modules.attendance.service.AttendanceDayService", _Calc)
    with pytest.raises(SoftTimeLimitExceeded):
        await attendance_tasks._calculate_employee_dates(
            uuid.uuid4(), uuid.uuid4(), [date(2026, 10, 1), date(2026, 10, 2)], actor_user_id=None
        )
