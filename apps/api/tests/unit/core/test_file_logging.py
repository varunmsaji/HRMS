"""Local per-module log files: routing, de-duplication, tracebacks, redaction, rotation and
retention, multi-process safety, failure handling and isolation.

Every test owns a temporary directory (`tmp_path`). Nothing here reads, writes or rotates the
developer's real `apps/api/logs`, and `tests/conftest.py` forces `LOG_TO_FILES=false` for the rest
of the suite so ordinary tests cannot either (`test_default_test_environment_writes_no_files`).
"""

import json
import multiprocessing
import os
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pytest import CaptureFixture, MonkeyPatch

from hrms.core.config.settings import get_settings
from hrms.core.errors.base import AppError
from hrms.core.observability import file_sink
from hrms.core.observability.file_sink import (
    ALL_CHANNELS,
    FileLoggingConfig,
    FileLoggingUnavailableError,
    RotatingLineFile,
    install_file_sink,
    resolve_channels,
    uninstall_file_sink,
)
from hrms.core.observability.logging import API_ROOT, configure_logging, get_logger
from hrms.core.observability.operations import logged_operation

_API_DIR = Path(__file__).resolve().parents[3]


def _read(directory: Path, channel: str) -> list[dict[str, object]]:
    path = directory / f"{channel}.log"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _events(directory: Path, channel: str) -> list[str]:
    return [str(e["event"]) for e in _read(directory, channel)]


@pytest.fixture
def log_dir(tmp_path: Path, monkeypatch: MonkeyPatch) -> Iterator[Path]:
    directory = tmp_path / "nested" / "logs"  # does not exist yet
    monkeypatch.setenv("LOG_TO_FILES", "true")
    monkeypatch.setenv("LOG_DIR", str(directory))
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    get_settings.cache_clear()
    configure_logging()
    yield directory
    uninstall_file_sink()
    get_settings.cache_clear()


# --- initialisation, isolation -----------------------------------------------------------------


def test_missing_log_directory_is_created(log_dir: Path) -> None:
    assert log_dir.is_dir()


def test_default_test_environment_writes_no_files(
    tmp_path: Path, monkeypatch: MonkeyPatch, capfd: CaptureFixture[str]
) -> None:
    """The suite-wide default (conftest) is file logging OFF, so no test run touches `logs/`."""
    monkeypatch.delenv("LOG_DIR", raising=False)
    get_settings.cache_clear()
    assert os.environ["LOG_TO_FILES"] == "false"
    configure_logging()
    get_logger("hrms.modules.attendance.service").info("should_only_reach_stdout")
    assert file_sink.current_sink() is None
    assert "should_only_reach_stdout" in capfd.readouterr().out


def test_relative_log_dir_is_anchored_to_api_root_not_cwd(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from hrms.core.observability.logging import resolve_log_dir

    monkeypatch.chdir(tmp_path)
    assert resolve_log_dir("logs") == API_ROOT / "logs"
    assert resolve_log_dir(str(tmp_path / "abs")) == tmp_path / "abs"


# --- routing ----------------------------------------------------------------------------------


def test_events_reach_their_module_file_and_app_log_only(log_dir: Path) -> None:
    get_logger("hrms.modules.attendance.service").info("punch_x")
    get_logger("hrms.modules.leave.service").info("leave_x")
    get_logger("hrms.modules.payroll.service").info("payroll_x")
    get_logger("hrms.modules.employee.service").info("employee_x")
    get_logger("hrms.modules.onboarding.service").info("onboarding_x")
    get_logger("hrms.documents").info("document_x")
    get_logger("hrms.modules.identity.service").info("identity_x")
    get_logger("hrms.modules.onboarding.email_sender").info("sender_x")

    assert _events(log_dir, "attendance") == ["punch_x"]
    assert _events(log_dir, "leave") == ["leave_x"]
    assert _events(log_dir, "payroll") == ["payroll_x"]
    assert _events(log_dir, "employees") == ["employee_x"]
    assert _events(log_dir, "recruitment") == ["onboarding_x"]
    assert _events(log_dir, "documents") == ["document_x"]
    assert _events(log_dir, "auth") == ["identity_x"]
    assert _events(log_dir, "notifications") == ["sender_x"]
    assert _events(log_dir, "app") == [
        "punch_x",
        "leave_x",
        "payroll_x",
        "employee_x",
        "onboarding_x",
        "document_x",
        "identity_x",
        "sender_x",
    ]
    assert _read(log_dir, "errors") == []


def test_event_name_and_entity_routing() -> None:
    assert resolve_channels({"event": "security.login.failed"}) == ("auth",)
    assert resolve_channels({"event": "email.delivery.failed"}) == ("notifications",)
    assert resolve_channels({"event": "db_deadlock"}) == ("database",)
    assert resolve_channels({"event": "celery_task_failed"}) == ("background_jobs",)
    audit = {"event": "business.audit_recorded", "logger": "hrms.business"}
    assert resolve_channels({**audit, "entity_type": "pay_run"}) == ("payroll",)
    assert resolve_channels({**audit, "entity_type": "leave_application"}) == ("leave",)
    assert resolve_channels({**audit, "entity_type": "punch"}) == ("attendance",)
    assert resolve_channels({**audit, "entity_type": "employee_document"}) == ("documents",)
    assert resolve_channels({**audit, "entity_type": "employee"}) == ("employees",)
    # a record from an unknown logger goes to app.log only
    assert resolve_channels({"event": "x", "logger": "somewhere.else"}) == ()


def test_task_context_adds_background_jobs_and_owning_module() -> None:
    event = {
        "event": "celery_task_finished",
        "logger": "hrms.core.celery_app",
        "task_name": "attendance.run_daily_calculation",
    }
    assert resolve_channels(event) == ("background_jobs", "attendance")
    leave = {"event": "leave_accrual_employee_failed", "logger": "hrms.modules.leave.tasks"}
    assert resolve_channels({**leave, "task_name": "leave.run_monthly_accrual"}) == (
        "leave",
        "background_jobs",
    )


def test_failing_request_is_routed_to_its_module_but_a_successful_one_is_not() -> None:
    base = {"event": "http_request", "logger": "hrms.http", "http_path": "/v1/payroll/pay-runs"}
    assert resolve_channels({**base, "level": "info", "status_code": 200}) == ("api",)
    assert resolve_channels({**base, "level": "info", "status_code": 409}) == ("api", "payroll")
    leave = {**base, "http_path": "/v1/leave-applications/{id}/approve"}
    assert resolve_channels({**leave, "level": "error", "status_code": 500}) == ("api", "leave")


def test_repeated_configuration_does_not_duplicate_lines(log_dir: Path) -> None:
    configure_logging()
    configure_logging()
    get_logger("hrms.modules.attendance.service").info("only_once")
    assert _events(log_dir, "attendance") == ["only_once"]
    assert _events(log_dir, "app") == ["only_once"]


def test_log_level_filters_debug(log_dir: Path) -> None:
    get_logger("hrms.modules.leave.service").debug("noisy")
    assert _read(log_dir, "leave") == []


# --- errors, tracebacks, redaction ---------------------------------------------------------------


def test_traceback_is_written_once_in_errors_log_only(log_dir: Path) -> None:
    logger = get_logger("hrms.modules.payroll.service")
    try:
        raise ZeroDivisionError("boom")  # noqa: TRY301
    except ZeroDivisionError:
        logger.exception("payroll_compute_failed", run_id="r1")

    errors = _read(log_dir, "errors")
    assert [e["event"] for e in errors] == ["payroll_compute_failed"]
    assert "ZeroDivisionError" in str(errors[0]["exception"])
    for channel in ("payroll", "app"):
        (entry,) = _read(log_dir, channel)
        assert entry["exception"] == file_sink.TRACEBACK_PLACEHOLDER
        assert entry["run_id"] == "r1"
    total = sum(
        (log_dir / f"{c}.log").read_text().count("Traceback")
        for c in ALL_CHANNELS
        if (log_dir / f"{c}.log").exists()
    )
    assert total == 1


def test_secrets_never_reach_any_file(log_dir: Path) -> None:
    get_logger("hrms.modules.identity.service").warning(
        "security.login.failed",
        password="hunter2",
        refresh_token="abc.def.ghi",
        note="Authorization: Bearer abcdefghijklmnop contact jane.doe@example.com",
        bank_account_number="1234567890",
        salary={"ctc": 1200000},
    )
    blob = "".join(p.read_text() for p in log_dir.glob("*.log"))
    for secret in (
        "hunter2",
        "abc.def.ghi",
        "abcdefghijklmnop",
        "jane.doe@example.com",
        "1234567890",
        "1200000",
    ):
        assert secret not in blob
    assert "[REDACTED]" in blob


def _failing_app() -> FastAPI:
    from hrms.app import create_app

    app = create_app()

    @app.get("/v1/payroll/__boom")
    async def boom(request: Request) -> None:
        raise ValueError("secret detail jane@example.com")

    return app


def test_request_id_and_traceback_in_server_logs_but_not_in_response(log_dir: Path) -> None:
    configure_logging()  # create_app() configured with the test default; point it at our dir
    with TestClient(_failing_app(), raise_server_exceptions=False) as client:
        configure_logging()
        response = client.get("/v1/payroll/__boom", headers={"X-Request-Id": "req-file-1"})
        client.get("/v1/leave/__missing", headers={"X-Request-Id": "req-file-2"})

    assert response.status_code == 500
    assert "ValueError" not in response.text and "jane@example.com" not in response.text
    assert response.headers["x-request-id"] == "req-file-1"

    (crash,) = [e for e in _read(log_dir, "errors") if e["event"] == "unhandled_exception"]
    assert crash["request_id"] == "req-file-1"
    assert "ValueError" in str(crash["exception"])
    assert "jane@example.com" not in json.dumps(crash)  # redacted in the traceback

    api = {
        str(e.get("request_id")): e for e in _read(log_dir, "api") if e["event"] == "http_request"
    }
    assert api["req-file-1"]["status_code"] == 500
    assert api["req-file-2"]["status_code"] == 404
    # the failing payroll request is also visible in payroll.log, the leave 404 in leave.log
    assert "req-file-1" in {e.get("request_id") for e in _read(log_dir, "payroll")}
    assert "req-file-2" in {e.get("request_id") for e in _read(log_dir, "leave")}


# --- operation logging ----------------------------------------------------------------------------


class _ConflictError(AppError):
    code = "CONFLICT"
    status_code = 409


class _InvalidError(AppError):
    code = "VALIDATION_FAILED"
    status_code = 422


@logged_operation("leave.application.approve", logger_name="hrms.modules.leave.service")
async def _op(
    company_id: object, application_id: object, *, mode: str, body: str = "", direction: str = "IN"
) -> str:
    if mode == "conflict":
        raise _ConflictError("nope")
    if mode == "invalid":
        raise _InvalidError("bad")
    if mode == "crash":
        raise RuntimeError("db password=hunter2")
    return "ok"


def test_logged_operation_outcomes_and_safety(log_dir: Path) -> None:
    import asyncio
    import uuid

    company, application = uuid.uuid4(), uuid.uuid4()

    async def run() -> None:
        assert (
            await _op(company, application, mode="ok", body="SECRET-BODY", direction="IN") == "ok"
        )
        for mode, exc in (
            ("conflict", _ConflictError),
            ("invalid", _InvalidError),
            ("crash", RuntimeError),
        ):
            with pytest.raises(exc):
                await _op(company, application, mode=mode)

    asyncio.run(run())
    leave = _read(log_dir, "leave")
    assert [(e["outcome"], e["level"]) for e in leave] == [
        ("succeeded", "info"),
        ("rejected", "warning"),  # 409
        ("rejected", "info"),  # 422
        ("failed", "error"),
    ]
    assert leave[0]["company_id"] == str(company)
    assert leave[0]["application_id"] == str(application)
    assert leave[0]["direction"] == "IN"
    assert leave[1]["error_code"] == "CONFLICT"
    assert "duration_ms" in leave[0]
    blob = (log_dir / "leave.log").read_text()
    assert "SECRET-BODY" not in blob and "hunter2" not in blob
    # failure line is compact: no traceback and therefore no errors.log duplicate of a stack
    failed = leave[3]
    assert failed["exception_type"] == "RuntimeError" and "exception" not in failed
    assert "Traceback" not in (log_dir / "errors.log").read_text()


# --- rotation and retention ----------------------------------------------------------------------


def test_size_rotation_is_bounded_and_leaves_unrelated_files_alone(tmp_path: Path) -> None:
    (tmp_path / "attendance.log.notes").write_text("keep")
    (tmp_path / "other.log.1").write_text("keep")
    sink = RotatingLineFile(tmp_path / "attendance.log", max_bytes=200, backup_count=3)
    for i in range(60):
        assert sink.write(json.dumps({"event": f"e{i}", "pad": "x" * 40}))
    names = sorted(p.name for p in tmp_path.iterdir() if not p.name.startswith("."))
    assert names == [
        "attendance.log",
        "attendance.log.1",
        "attendance.log.2",
        "attendance.log.3",
        "attendance.log.notes",
        "other.log.1",
    ]
    for p in tmp_path.glob("attendance.log*"):
        if p.suffix != ".notes":
            assert p.stat().st_size <= 200
    # newest lines are in the live file, the sequence across files is contiguous and ordered
    ordered = []
    for suffix in ("3", "2", "1"):
        ordered += (tmp_path / f"attendance.log.{suffix}").read_text().splitlines()
    ordered += (tmp_path / "attendance.log").read_text().splitlines()
    numbers = [int(json.loads(line)["event"][1:]) for line in ordered]
    assert numbers == sorted(numbers) and numbers[-1] == 59
    assert (tmp_path / "other.log.1").read_text() == "keep"
    assert (tmp_path / "attendance.log.notes").read_text() == "keep"


def test_retention_deletes_only_old_numbered_backups(tmp_path: Path) -> None:
    target = tmp_path / "leave.log"
    old = tmp_path / "leave.log.2"
    fresh = tmp_path / "leave.log.1"
    unrelated = tmp_path / "leave.log.bak"
    for p in (old, fresh, unrelated):
        p.write_text("x")
    ten_days_ago = time.time() - 10 * 86400
    os.utime(old, (ten_days_ago, ten_days_ago))
    os.utime(unrelated, (ten_days_ago, ten_days_ago))
    sink = RotatingLineFile(target, max_bytes=0, backup_count=5, retention_days=7)
    assert sink.write('{"event":"x"}')
    assert not old.exists()
    assert fresh.exists() and unrelated.exists()


def _hammer(args: tuple[str, int, int]) -> None:
    path, worker, count = args
    sink = RotatingLineFile(Path(path), max_bytes=4_000, backup_count=500)
    for i in range(count):
        sink.write(json.dumps({"w": worker, "i": i, "pad": "y" * 60}))


def test_concurrent_processes_neither_lose_nor_interleave_lines(tmp_path: Path) -> None:
    workers, per_worker = 6, 150
    target = tmp_path / "attendance.log"
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(workers) as pool:
        pool.map(_hammer, [(str(target), w, per_worker) for w in range(workers)])
    lines = []
    for p in tmp_path.glob("attendance.log*"):
        lines += p.read_text().splitlines()
    parsed = [json.loads(line) for line in lines]  # any torn/interleaved line fails here
    assert len(parsed) == workers * per_worker
    assert {(e["w"], e["i"]) for e in parsed} == {
        (w, i) for w in range(workers) for i in range(per_worker)
    }
    assert len(list(tmp_path.glob("attendance.log.*"))) > 3  # rotation really happened


# --- failure handling -----------------------------------------------------------------------------


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unwritable_directory_falls_back_to_stdout_loudly(
    tmp_path: Path, capfd: CaptureFixture[str]
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    config = FileLoggingConfig(
        directory=locked / "logs", max_bytes=1000, backup_count=1, retention_days=0
    )
    try:
        assert install_file_sink(config, required=False) is None
        err = capfd.readouterr().err
        assert "file_logging_unavailable" in err and "not writable" in err
        with pytest.raises(FileLoggingUnavailableError):
            install_file_sink(config, required=True)
    finally:
        locked.chmod(0o700)
        uninstall_file_sink()


def test_write_failures_are_dropped_counted_and_reported_after_recovery(tmp_path: Path) -> None:
    target = tmp_path / "gone" / "payroll.log"
    sink = RotatingLineFile(target, max_bytes=0, backup_count=1)
    assert sink.write("lost") is False  # directory missing: must not raise
    assert sink.dropped_writes == 1
    target.parent.mkdir()
    sink._retry_at = 0.0
    assert sink.write(json.dumps({"event": "after"})) is True
    events = [json.loads(line)["event"] for line in target.read_text().splitlines()]
    assert events == ["log_file_writes_dropped", "after"]


def test_logging_survives_a_broken_file_sink(log_dir: Path, capfd: CaptureFixture[str]) -> None:
    import shutil

    shutil.rmtree(log_dir)  # disk/volume disappears while running
    get_logger("hrms.modules.attendance.service").info("still_logged_to_stdout")
    assert "still_logged_to_stdout" in capfd.readouterr().out


# --- background workers ---------------------------------------------------------------------------

_WORKER_SCRIPT = textwrap.dedent(
    """
    import sys, structlog
    sys.argv = ["celery", "worker"]
    from entrypoints.worker import app
    app.log.setup(loglevel="INFO")
    from hrms.core.observability.logging import get_logger
    structlog.contextvars.bind_contextvars(
        task_id="t-1", task_name="attendance.run_daily_calculation"
    )
    get_logger("hrms.modules.attendance.tasks").warning(
        "attendance_scheduled_calculate_failed", company_id="c-1"
    )
    structlog.contextvars.clear_contextvars()
    try:
        raise RuntimeError("task blew up")
    except RuntimeError:
        import logging
        logging.getLogger("celery.app.trace").error("Task x raised unexpected", exc_info=True)
    """
)


def test_worker_process_writes_task_logs_to_module_and_background_files(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "LOG_TO_FILES": "true",
        "LOG_DIR": str(tmp_path / "logs"),
        "LOG_LEVEL": "INFO",
        "PYTHONPATH": os.pathsep.join([str(_API_DIR), str(_API_DIR / "src")]),
    }
    subprocess.run(
        [sys.executable, "-c", _WORKER_SCRIPT],
        cwd=tmp_path,  # deliberately not the API dir: the path must not depend on the cwd
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    logs = tmp_path / "logs"
    for channel in ("attendance", "background_jobs"):
        (entry,) = [
            e for e in _read(logs, channel) if e["event"] == "attendance_scheduled_calculate_failed"
        ]
        assert entry["task_id"] == "t-1" and entry["service"] == "worker"
    assert "Task x raised unexpected" in _events(logs, "background_jobs")
    (celery_error,) = _read(logs, "errors")
    assert "RuntimeError" in str(celery_error["exception"])
    assert structlog is not None  # keep import used for type checkers


def test_dropped_file_writes_are_exported_as_a_metric(tmp_path: Path) -> None:
    """A log directory that cannot be written is visible in Prometheus, not only in the log the
    failure itself prevents from being written."""
    from prometheus_client import REGISTRY

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    sink = RotatingLineFile(blocker / "app.log", max_bytes=0, backup_count=1)
    before = REGISTRY.get_sample_value("hrms_log_dropped_writes_total", {"source": "file"}) or 0.0
    assert sink.write('{"event": "lost"}') is False
    after = REGISTRY.get_sample_value("hrms_log_dropped_writes_total", {"source": "file"}) or 0.0
    assert after == before + 1
