"""LOG-03 — the Celery worker and Beat must log with the same JSON contract as the API.

Runs in a fresh subprocess so the process-global logging configuration under test is exactly
what a worker process gets — no pytest capture handlers, no structlog state left by other tests.
The subprocess imports the real worker entrypoint and then goes through Celery's own logging
bootstrap (`app.log.setup()`, which fires the `setup_logging` signal the worker fires at
startup), twice, to prove a repeated call does not stack handlers. A real-worker run (actual
`celery worker` process, failing task) is recorded in
`docs/audits/LOGGING_ERROR_HANDLING_REMEDIATION_REPORT.md`."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[3]

_SCRIPT = textwrap.dedent(
    """
    import logging, sys
    sys.argv = ["celery", "worker"]
    from entrypoints.worker import app
    app.log.setup(loglevel="INFO")
    app.log.setup(loglevel="INFO")  # repeated bootstrap must not duplicate output

    from hrms.core.observability.logging import get_logger
    get_logger("hrms.test").info("structlog_event", answer=42)
    get_logger("hrms.test").debug("debug_event_filtered_by_LOG_LEVEL")
    try:
        raise ValueError("task blew up")
    except ValueError:
        logging.getLogger("celery.app.trace").error("Task x raised unexpected", exc_info=True)
    logging.getLogger("kombu").info("stdlib_info_line")
    """
)


def _run() -> list[dict[str, object]]:
    env = {**os.environ, "LOG_LEVEL": "INFO", "EMAIL_PROVIDER": "logging"}
    env["PYTHONPATH"] = os.pathsep.join([str(_API_DIR), str(_API_DIR / "src")])
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=_API_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]  # every line must be JSON


def test_worker_process_logs_json_once_with_service_and_traceback() -> None:
    events = _run()
    by_event = {str(e["event"]): e for e in events}

    assert len(events) == 3, events  # no duplicates; the DEBUG line is filtered by LOG_LEVEL
    assert {e["service"] for e in events} == {"worker"}

    assert by_event["structlog_event"]["answer"] == 42
    assert by_event["structlog_event"]["level"] == "info"

    failure = by_event["Task x raised unexpected"]
    assert failure["level"] == "error"
    assert failure["logger"] == "celery.app.trace"
    assert "Traceback (most recent call last)" in str(failure["exception"])
    assert "ValueError: task blew up" in str(failure["exception"])

    assert by_event["stdlib_info_line"]["logger"] == "kombu"
