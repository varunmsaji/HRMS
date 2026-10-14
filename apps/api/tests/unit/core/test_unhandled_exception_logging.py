"""FINDING-01 — an unhandled exception must leave a structured server-side trace (request id,
method/path, exception type/message, stack trace) while the client still only ever sees the
existing clean 500 envelope. No tenant/user context is asserted in the first test: the route
under test never establishes one, exercising the "no context available" branch too.

Asserts against real stdout (`capfd`, file-descriptor-level), not `structlog.testing.
capture_logs()`: `configure_logging()`'s `cache_logger_on_first_use=True` means the handler's
module-level `_logger` resolves its bound logger (and the real `PrintLoggerFactory(file=sys.
stdout)` target) the first time any test anywhere in the suite exercises this handler — almost
always long before this file runs. `capture_logs()`'s `structlog.configure()` override can't
retroactively reach an already-cached logger, so it silently captures nothing (proven: it failed
intermittently depending on full-suite test order, while the real JSON line was always printed
correctly in the captured stdout). `capfd` reads the actual OS pipe, so it sees that same real
line regardless of caching or which object currently holds `sys.stdout`."""

import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pytest import CaptureFixture

from hrms.core.errors.handlers import register_exception_handlers
from hrms.core.tenancy.context import clear_context, set_request_id


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom(request: Request) -> None:
        set_request_id("req-unhandled-123")
        raise ValueError("something broke")

    return app


def _find_log_line(raw_stdout: str) -> dict[str, object]:
    for line in raw_stdout.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if parsed.get("event") == "unhandled_exception":
            return parsed
    raise AssertionError(
        f"no unhandled_exception log line found in captured stdout: {raw_stdout!r}"
    )


def test_unhandled_exception_is_logged_with_request_context(capfd: CaptureFixture[str]) -> None:
    clear_context()
    # Starlette's ServerErrorMiddleware re-raises after sending the response (so an outer ASGI
    # server can log it too); `raise_server_exceptions=False` suppresses that re-raise so this
    # test can inspect the response our own handler built.
    with TestClient(_app(), raise_server_exceptions=False) as c:
        r = c.get("/boom")
    captured = capfd.readouterr()

    # the client-facing contract is unchanged: clean 500, no internals leaked
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "ValueError" not in r.text and "something broke" not in r.text

    entry = _find_log_line(captured.out)
    assert entry["level"] == "error"
    assert entry["request_id"] == "req-unhandled-123"
    assert entry["http_method"] == "GET"
    assert entry["http_path"] == "/boom"
    assert entry["exception_type"] == "ValueError"
    # LOG-08 — no separate raw-message field; the message lives only inside the (redacted)
    # traceback below.
    assert "exception_message" not in entry
    # company/user context was never established on this route
    assert entry["company_id"] is None
    assert entry["user_id"] is None
    # the real `format_exc_info` processor (core/observability/logging.py) rendered the full
    # traceback into the line, with the triggering source visible in it — never exposed to the
    # client (asserted above), but present for whoever reads the server-side log.
    assert "Traceback (most recent call last):" in str(entry["exception"])
    assert "ValueError: something broke" in str(entry["exception"])


def test_unhandled_exception_logs_tenant_context_when_available(capfd: CaptureFixture[str]) -> None:
    from uuid import uuid4

    from hrms.core.tenancy.context import TenantContext, set_tenant

    clear_context()
    company_id, user_id = uuid4(), uuid4()
    set_tenant(TenantContext(company_id=company_id, user_id=user_id))
    try:
        with TestClient(_app(), raise_server_exceptions=False) as c:
            r = c.get("/boom")
        captured = capfd.readouterr()
        assert r.status_code == 500

        entry = _find_log_line(captured.out)
        assert entry["company_id"] == str(company_id)
        assert entry["user_id"] == str(user_id)
    finally:
        clear_context()
