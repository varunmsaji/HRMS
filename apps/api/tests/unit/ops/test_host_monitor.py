"""`infra/monitoring/hrms_monitor.sh` end to end against a fake `docker` binary (mission Phase 10).

The fake answers the exact commands the monitor runs (readiness probe, job_health, logs,
ps/inspect) from files in a temp dir, so each signal can be driven to pass or fail without a
real stack. Also asserts the monitor only ever issues read-only commands."""

import json
import os
import shutil
import stat
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[5] / "infra" / "monitoring" / "hrms_monitor.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None, reason="needs bash and jq"
)

FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_DIR/calls.log"
args="$*"
case "$args" in
  *"exec -T api"*) exit "$(cat "$FAKE_DIR/ready_code")" ;;
  *"hrms.ops.job_health"*) cat "$FAKE_DIR/jobs.json"; exit "$(cat "$FAKE_DIR/jobs_code")" ;;
  *" logs "*" api") cat "$FAKE_DIR/api.log" ;;
  *" logs "*" worker") cat "$FAKE_DIR/worker.log" ;;
  "ps -a "*"--format"*) cat "$FAKE_DIR/services" ;;
  "ps "*"health=unhealthy"*) cat "$FAKE_DIR/unhealthy" ;;
  "ps -aq"*) echo c1; echo c2 ;;
  "inspect"*) cat "$FAKE_DIR/restarts" ;;
  *) exit 0 ;;
esac
"""


def _line(**fields: Any) -> str:
    return json.dumps(fields)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    fake = tmp_path / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    files = {
        "ready_code": "0",
        "jobs.json": json.dumps({"ok": True, "checks": []}),
        "jobs_code": "0",
        "api.log": "\n".join(
            [
                "plain text banner line",
                _line(event="http_request", status_code=200),
                _line(event="http_request", status_code=404, error_code="NOT_FOUND"),
            ]
        ),
        "worker.log": _line(event="celery_task_finished", state="SUCCESS"),
        "unhealthy": "",
        "restarts": "0",
        "services": "postgres running\nredis running\nminio running\napi running\n"
        "worker running\nbeat running\nminio-init exited\nmigrate exited\n",
    }
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    backups = tmp_path / "backups"
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for kind in ("postgres", "minio"):
        (backups / kind).mkdir(parents=True)
        (backups / kind / "backup.log").write_text(f"{stamp} SUCCESS: /x/{kind}.gz (1M)\n")
    return {
        **{k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG")},
        "FAKE_DIR": str(tmp_path),
        "HRMS_COMPOSE_CMD": f"{fake} compose -f docker-compose.prod.yml",
        "HRMS_DOCKER_CMD": str(fake),
        "HRMS_DISK_PATHS": str(tmp_path),
        "HRMS_MAX_DISK_PCT": "100",
        "BACKUP_ROOT": str(backups),
    }


def _run(env: dict[str, str]) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60, check=False
    )
    return proc.returncode, json.loads(proc.stdout)


def _write(env: dict[str, str], name: str, content: str) -> None:
    (Path(env["FAKE_DIR"]) / name).write_text(content)


def test_healthy_stack_passes(env: dict[str, str]) -> None:
    code, report = _run(env)
    assert code == 0, report
    assert report["ok"] is True and report["failing"] == []


def _api(**fields: Any) -> dict[str, str]:
    return {"api.log": _line(**fields)}


def _worker(**fields: Any) -> dict[str, str]:
    return {"worker.log": _line(**fields)}


def _many(name: str, count: int, **fields: Any) -> dict[str, str]:
    return {name: "\n".join(_line(**fields) for _ in range(count))}


SIGNALS: list[tuple[dict[str, str], str]] = [
    ({"ready_code": "1"}, "api_ready"),
    ({"jobs_code": "1"}, "job_health"),
    ({"unhealthy": "c1\n"}, "containers_unhealthy"),
    ({"services": "postgres running\nminio exited\nworker running\n"}, "containers_not_running"),
    ({"services": "postgres running\nworker restarting\n"}, "containers_not_running"),
    ({"services": "redis dead\napi running\n"}, "containers_not_running"),
    ({"restarts": "9"}, "container_restarts"),
    (_many("api.log", 6, event="http_request", status_code=502), "api_5xx"),
    (_api(event="unhandled_exception"), "api_unhandled_exceptions"),
    (_api(event="db_error", error_category="db_connection"), "db_connectivity_errors"),
    (
        _api(event="http_request", status_code=503, error_code="RATE_LIMITER_UNAVAILABLE"),
        "rate_limiter_unavailable",
    ),
    (_api(event="app_error", error_code="DECRYPTION_FAILED"), "pii_integrity_errors"),
    (_worker(event="celery_task_failed"), "task_failures"),
    (_api(event="log_writes_dropped", newly_dropped=3), "log_writes_dropped"),
    (_worker(event="leave_accrual_incomplete"), "partial_runs"),
    (_many("worker.log", 6, event="email.delivery.failed"), "email_delivery_failures"),
    (
        _many("api.log", 11, event="security.face_punch.rejected", reason="NO_MATCH"),
        "face_rejections",
    ),
    (
        _many("api.log", 11, event="security.face_enrollment.rejected", reason="ANGLE_MISMATCH"),
        "face_rejections",
    ),
    (
        _many("api.log", 4, event="security.face_punch.rejected", reason="SPOOF_SUSPECTED"),
        "face_spoof_signals",
    ),
    (
        _many("api.log", 4, event="security.face_punch.rejected", reason="IDENTITY_INCONSISTENT"),
        "face_spoof_signals",
    ),
    (
        _many("api.log", 4, event="security.face_enrollment.rejected", reason="SPOOF_SUSPECTED"),
        "face_spoof_signals",
    ),
    (_worker(event="employee_import.batch.storage_failed"), "storage_and_orphan_failures"),
    (_worker(event="face_deletion_failed", level="error"), "face_deletion_stuck"),
]


@pytest.mark.parametrize(("setup", "failing"), SIGNALS)
def test_each_signal_fails_its_check(
    env: dict[str, str], setup: dict[str, str], failing: str
) -> None:
    for name, content in setup.items():
        _write(env, name, content)
    code, report = _run(env)
    assert code == 1
    assert failing in report["failing"], report["failing"]


def test_a_few_ordinary_face_rejections_do_not_alert(env: dict[str, str]) -> None:
    """Genuine employees fail the camera sometimes: a handful of NO_MATCH / NO_FACE per window
    is the normal baseline, not an alert."""
    _write(
        env,
        "api.log",
        _many("api.log", 8, event="security.face_punch.rejected", reason="NO_FACE")["api.log"],
    )
    code, report = _run(env)
    assert code == 0, report["failing"]


def test_stale_or_failed_backup_fails(env: dict[str, str]) -> None:
    old = (datetime.now(UTC) - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    Path(env["BACKUP_ROOT"], "postgres", "backup.log").write_text(f"{old} SUCCESS: /x.gz (1M)\n")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    later = (datetime.now(UTC) + timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    Path(env["BACKUP_ROOT"], "minio", "backup.log").write_text(
        f"{now} SUCCESS: /m.gz (1M)\n{later} FAILED: mirror exited non-zero\n"
    )
    code, report = _run(env)
    assert code == 1
    assert {"backup_postgres", "backup_minio"} <= set(report["failing"])


def test_alert_command_receives_the_report_only_on_failure(env: dict[str, str]) -> None:
    sink = Path(env["FAKE_DIR"]) / "alert.json"
    env["HRMS_ALERT_COMMAND"] = f"cat > {sink}"
    _run(env)
    assert not sink.exists()
    _write(env, "ready_code", "1")
    _run(env)
    assert json.loads(sink.read_text())["failing"] == ["api_ready"]


def test_monitor_only_issues_read_only_commands(env: dict[str, str]) -> None:
    _run(env)
    calls = Path(env["FAKE_DIR"], "calls.log").read_text()
    for forbidden in (" restart", " stop", " rm", " down", " kill", "FLUSH", " DEL ", "purge"):
        assert forbidden not in calls


def _run_raw(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60, check=False
    )


def test_expected_one_shot_services_are_not_failures(env: dict[str, str]) -> None:
    """`minio-init` and `migrate` exit by design; they must not page anyone."""
    code, report = _run(env)
    assert code == 0 and "containers_not_running" not in report["failing"]


def test_database_and_redis_outages_surface_through_readiness_and_job_health(
    env: dict[str, str],
) -> None:
    """Database down: readiness 503 and the API logs db_connection errors. Redis down: readiness
    503, the limiter is unavailable and `job_health` exits 2 (cannot reach the broker)."""
    for name, content in {
        "ready_code": "1",
        **_api(event="db_error", error_category="db_pool_exhausted"),
    }.items():
        _write(env, name, content)
    code, report = _run(env)
    assert code == 1 and {"api_ready", "db_connectivity_errors"} <= set(report["failing"])

    _write(
        env,
        "api.log",
        _line(event="http_request", status_code=503, error_code="RATE_LIMITER_UNAVAILABLE"),
    )
    _write(env, "jobs.json", json.dumps({"ok": False, "error": "redis_unavailable"}))
    _write(env, "jobs_code", "2")
    code, report = _run(env)
    assert code == 1
    assert {"api_ready", "job_health", "rate_limiter_unavailable"} <= set(report["failing"])
    assert report["job_health"]["error"] == "redis_unavailable"


def test_worker_stopped_is_caught_by_stale_heartbeat_and_container_state(
    env: dict[str, str],
) -> None:
    _write(env, "jobs_code", "1")
    _write(
        env,
        "jobs.json",
        json.dumps({"ok": False, "checks": [{"name": "scheduler_heartbeat", "ok": False}]}),
    )
    _write(env, "services", "postgres running\nworker exited\n")
    code, report = _run(env)
    assert code == 1
    assert {"job_health", "containers_not_running"} <= set(report["failing"])


def test_unparseable_job_health_output_is_a_failure_not_a_crash(env: dict[str, str]) -> None:
    _write(env, "jobs.json", "Traceback (most recent call last): boom")
    _write(env, "jobs_code", "1")
    code, report = _run(env)
    assert code == 1 and "job_health" in report["failing"]
    assert report["job_health"] == {"ok": False, "error": "job_health_unavailable"}


def test_recovery_after_a_simulated_failure(env: dict[str, str]) -> None:
    _write(env, "ready_code", "1")
    _write(env, "services", "postgres running\nminio exited\n")
    assert _run(env)[0] == 1
    _write(env, "ready_code", "0")
    _write(env, "services", "postgres running\nminio running\n")
    code, report = _run(env)
    assert code == 0 and report["failing"] == []


def test_missing_alert_command_is_stated_not_silent(env: dict[str, str]) -> None:
    env.pop("HRMS_ALERT_COMMAND", None)
    _write(env, "ready_code", "1")
    proc = _run_raw(env)
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["failing"] == ["api_ready"]
    assert '{"alert_delivery":"not_configured"}' in proc.stderr


def test_invalid_alert_command_fails_loudly_and_still_exits_1(env: dict[str, str]) -> None:
    env["HRMS_ALERT_COMMAND"] = "/nonexistent/notify-hrms-oncall"
    _write(env, "ready_code", "1")
    proc = _run_raw(env)
    assert proc.returncode == 1
    json.loads(proc.stdout)  # the report is still produced, untouched by the alert's output
    assert '{"alert_delivery":"failed"}' in proc.stderr


def test_alert_command_failure_exit_code_is_reported(env: dict[str, str]) -> None:
    env["HRMS_ALERT_COMMAND"] = "cat >/dev/null; exit 3"
    _write(env, "ready_code", "1")
    assert '{"alert_delivery":"failed"}' in _run_raw(env).stderr


def test_working_fake_alert_command_is_reported_as_sent(env: dict[str, str]) -> None:
    sink = Path(env["FAKE_DIR"]) / "alert.json"
    env["HRMS_ALERT_COMMAND"] = f"cat > {sink}; echo noisy-stdout"
    _write(env, "ready_code", "1")
    proc = _run_raw(env)
    assert '{"alert_delivery":"sent"}' in proc.stderr
    assert "noisy-stdout" not in proc.stdout  # an alert hook cannot corrupt the JSON report
    assert json.loads(proc.stdout)["failing"] == ["api_ready"]


def test_a_hung_alert_command_is_bounded_by_the_timeout(env: dict[str, str]) -> None:
    env["HRMS_ALERT_COMMAND"] = "cat >/dev/null; sleep 30"
    env["HRMS_ALERT_TIMEOUT"] = "1"
    _write(env, "ready_code", "1")
    started = time.monotonic()
    proc = _run_raw(env)
    assert time.monotonic() - started < 15
    assert proc.returncode == 1 and '{"alert_delivery":"failed"}' in proc.stderr


def test_monitor_never_calls_a_mutating_docker_or_compose_subcommand(env: dict[str, str]) -> None:
    """Allow-list, stricter than the deny-list test above: every recorded call must be one of the
    read-only shapes the monitor is documented to use."""
    _run(env)
    allowed = (
        "compose -f docker-compose.prod.yml exec -T api python -c",
        "compose -f docker-compose.prod.yml exec -T worker python -m hrms.ops.job_health",
        "compose -f docker-compose.prod.yml logs --no-color --no-log-prefix --since",
        "ps ",
        "inspect ",
    )
    verbs = {
        "compose", "ps", "inspect", "restart", "stop", "rm", "kill", "down", "up", "exec", "run",
        "start", "pause", "unpause", "prune", "volume", "network", "system", "image", "container",
        "cp", "commit", "build", "pull", "push", "tag", "rmi", "logs",
    }  # fmt: skip
    # The multi-line `python -c` readiness snippet is logged over several lines; only lines that
    # begin with a docker verb are commands.
    calls = [
        line
        for line in Path(env["FAKE_DIR"], "calls.log").read_text().splitlines()
        if line.split(" ", 1)[0] in verbs
    ]
    assert calls
    unexpected = [c for c in calls if not any(c.startswith(a) for a in allowed)]
    assert not unexpected, unexpected


def test_missing_jq_stops_the_monitor_without_touching_docker(
    env: dict[str, str], tmp_path: Path
) -> None:
    bare = tmp_path / "bin"
    bare.mkdir()
    for tool in ("bash", "dirname"):
        found = shutil.which(tool)
        if found:
            (bare / tool).symlink_to(found)
    env = {**env, "PATH": str(bare)}
    proc = subprocess.run(
        [shutil.which("bash") or "bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 2 and json.loads(proc.stdout)["error"] == "jq_not_installed"
    assert not Path(env["FAKE_DIR"], "calls.log").exists()
