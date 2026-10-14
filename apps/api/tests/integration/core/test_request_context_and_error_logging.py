"""LOG-01 / LOG-02 / LOG-05 (`docs/audits/LOGGING_ERROR_HANDLING_OBSERVABILITY_PLAN.md`) — request
correlation and 5xx logging, exercised through a real `create_app()` middleware stack (not a bare
`FastAPI()`), because both original defects lived in the interaction between layers:

* an unhandled exception reached Starlette's outermost `ServerErrorMiddleware` after
  `TenancyMiddleware` had already cleared the request id, so the log line and the response both
  said `"unknown"`, and the 500 skipped CORS (browsers saw a network error);
* handled 5xx responses (`AppError` with a 5xx status, `DBAPIError`) were never logged at all.

Each test builds its own `create_app()` and adds throwaway routes to it, so the shared
`entrypoints.api.app` used by the rest of the suite is never modified. Log output is read from
the real stdout pipe (`capfd`), as `tests/unit/core/test_unhandled_exception_logging.py` explains.
"""

import json
from collections.abc import Iterator
from typing import Annotated, Any
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pytest import CaptureFixture
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from hrms.app import create_app
from hrms.core.config.settings import get_settings
from hrms.core.crypto.errors import (
    DecryptionFailedError,
    EncryptionUnavailableError,
    UnknownKeyVersionError,
)
from hrms.core.db.session import get_session_factory
from hrms.core.errors.base import ConflictError, NotFoundError
from hrms.core.observability.request_context import resolve_request_id
from hrms.core.tenancy.context import TenantContext, set_tenant
from hrms.shared.rate_limit import RateLimiterUnavailableError

ORIGIN = "http://localhost:3000"
SENTINEL = "s3ntinel-value-4f9c"


def _events(raw: str) -> list[dict[str, Any]]:
    out = []
    for line in raw.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "event" in parsed:
            out.append(parsed)
    return out


def _only(events: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matching = [e for e in events if e["event"] == name]
    assert len(matching) == 1, f"expected exactly one {name!r}, got {matching}"
    return matching[0]


class _LockNotAvailableError(Exception):
    sqlstate = "55P03"


def _wait_timeout() -> DBAPIError:
    orig = Exception("adapter")
    orig.__cause__ = _LockNotAvailableError("lock")
    return DBAPIError("SELECT 1", {}, orig)


def _verified_tenant() -> TenantContext:
    """Stands in for `get_tenant_context`: sets a membership-verified tenant (user_id present)
    inside the route's dependency — which runs in a child task of the BaseHTTPMiddleware layers,
    exactly where the real dependency runs."""
    ctx = TenantContext(company_id=UUID(int=1), user_id=UUID(int=2))
    set_tenant(ctx)
    return ctx


@pytest.fixture
def app() -> FastAPI:
    assert ORIGIN in get_settings().effective_cors_origins
    app = create_app()

    @app.get("/__t/boom")
    async def boom() -> None:
        raise ValueError("internal-detail-7731")

    @app.get("/__t/boom-after-tenant")
    async def boom_after_tenant(_: Annotated[TenantContext, Depends(_verified_tenant)]) -> None:
        raise ValueError("internal-detail-7731")

    def _failing_dependency() -> None:
        raise RuntimeError("internal-detail-7731")

    @app.get("/__t/boom-in-dependency")
    async def boom_in_dependency(_: Annotated[None, Depends(_failing_dependency)]) -> None:
        return None

    @app.get("/__t/app-error/{kind}")
    async def app_error(kind: str) -> None:
        if kind == "redis":
            cause = RedisConnectionError("Error 111 connecting to redis:6379")
            raise RateLimiterUnavailableError("Rate limiter unavailable") from cause
        if kind == "encryption-unavailable":
            raise EncryptionUnavailableError("encryption unavailable")
        if kind == "decryption-failed":
            raise DecryptionFailedError("decryption failed")
        if kind == "unknown-key":
            raise UnknownKeyVersionError("unknown key version")
        if kind == "not-found":
            raise NotFoundError("Resource not found")
        raise ConflictError("conflict")

    @app.get("/__t/db/{kind}")
    async def db(kind: str) -> None:
        if kind == "timeout":
            raise _wait_timeout()
        # A real driver error through the real engine, with a sentinel bound parameter.
        async with get_session_factory()() as session:
            await session.execute(
                text("SELECT * FROM table_that_does_not_exist_xyz WHERE a = :v"),
                {"v": SENTINEL},
            )

    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # raise_server_exceptions=True (the default): if any layer re-raised the exception to the
    # server — which is what makes uvicorn print a second, unstructured traceback — the call
    # below would raise instead of returning the 500.
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------------------------
# LOG-01 — unhandled exceptions keep their correlation, CORS and security headers
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/__t/boom", "/__t/boom-in-dependency"])
def test_unhandled_exception_keeps_request_id_cors_and_headers(
    client: TestClient, capfd: CaptureFixture[str], path: str
) -> None:
    capfd.readouterr()
    r = client.get(path, headers={"X-Request-Id": "client-req-42", "Origin": ORIGIN})
    events = _events(capfd.readouterr().out)

    assert r.status_code == 500
    body = r.json()["error"]
    assert body["code"] == "INTERNAL_ERROR"
    assert body["request_id"] == "client-req-42"
    assert r.headers["x-request-id"] == "client-req-42"
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert r.headers["access-control-allow-credentials"] == "true"
    assert "x-request-id" in r.headers["access-control-expose-headers"].lower()
    assert r.headers["content-security-policy"]
    assert "Traceback" not in r.text and "internal-detail-7731" not in r.text

    entry = _only(events, "unhandled_exception")
    assert entry["level"] == "error"
    assert entry["request_id"] == "client-req-42"
    assert entry["http_path"] == path
    assert "Traceback (most recent call last)" in entry["exception"]
    assert len([e for e in events if "exception" in e]) == 1  # one traceback, not two


def test_unhandled_exception_raised_inside_a_middleware_layer(
    monkeypatch: pytest.MonkeyPatch, capfd: CaptureFixture[str]
) -> None:
    """A failure in another middleware (here the upload-size guard, which sits inside
    Tenancy/ProxyHeaders) is caught the same way as one in a route."""
    from hrms.core import uploads

    original = uploads.MaxUploadSizeMiddleware.__call__

    async def exploding(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] == "http" and scope["path"] == "/__t/mw":
            raise RuntimeError("middleware exploded")
        await original(self, scope, receive, send)

    monkeypatch.setattr(uploads.MaxUploadSizeMiddleware, "__call__", exploding)
    with TestClient(create_app()) as c:
        capfd.readouterr()
        r = c.get("/__t/mw", headers={"X-Request-Id": "mw-req-1", "Origin": ORIGIN})
    events = _events(capfd.readouterr().out)
    assert r.status_code == 500
    assert r.json()["error"]["request_id"] == "mw-req-1"
    assert r.headers["x-request-id"] == "mw-req-1"
    assert r.headers["access-control-allow-origin"] == ORIGIN
    entry = _only(events, "unhandled_exception")
    assert entry["request_id"] == "mw-req-1"
    assert entry["exception_type"] == "RuntimeError"


def test_unhandled_exception_logs_the_verified_tenant(
    client: TestClient, capfd: CaptureFixture[str]
) -> None:
    capfd.readouterr()
    r = client.get("/__t/boom-after-tenant")
    entry = _only(_events(capfd.readouterr().out), "unhandled_exception")
    assert r.status_code == 500
    assert entry["company_id"] == str(UUID(int=1))
    assert entry["user_id"] == str(UUID(int=2))


def test_unverified_company_header_is_never_logged_as_the_tenant(
    client: TestClient, capfd: CaptureFixture[str]
) -> None:
    capfd.readouterr()
    client.get("/__t/boom", headers={"X-Company-Id": str(uuid4())})
    entry = _only(_events(capfd.readouterr().out), "unhandled_exception")
    assert entry["company_id"] is None and entry["user_id"] is None


def test_logging_failure_does_not_change_the_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hrms.core.errors import handlers

    class _BrokenLogger:
        def __getattr__(self, _name: str):  # type: ignore[no-untyped-def]
            def _raise(*_a: object, **_k: object) -> None:
                raise OSError("stdout closed")

            return _raise

    monkeypatch.setattr(handlers, "_logger", _BrokenLogger())
    crash = client.get("/__t/boom", headers={"X-Request-Id": "still-correlated"})
    assert crash.status_code == 500
    assert crash.json()["error"]["request_id"] == "still-correlated"
    busy = client.get("/__t/app-error/redis")
    assert busy.status_code == 503
    assert busy.json()["error"]["code"] == "RATE_LIMITER_UNAVAILABLE"


# --------------------------------------------------------------------------------------------
# LOG-02 — handled 5xx responses are logged once, with safe fields; 4xx are not
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "status", "code", "level", "has_traceback", "cause_type"),
    [
        ("redis", 503, "RATE_LIMITER_UNAVAILABLE", "warning", False, "ConnectionError"),
        ("encryption-unavailable", 503, "ENCRYPTION_UNAVAILABLE", "warning", False, None),
        ("decryption-failed", 500, "DECRYPTION_FAILED", "error", True, None),
        ("unknown-key", 500, "UNKNOWN_KEY_VERSION", "error", True, None),
    ],
)
def test_5xx_app_errors_are_logged_once(
    client: TestClient,
    capfd: CaptureFixture[str],
    kind: str,
    status: int,
    code: str,
    level: str,
    has_traceback: bool,
    cause_type: str | None,
) -> None:
    capfd.readouterr()
    r = client.get(f"/__t/app-error/{kind}", headers={"X-Request-Id": f"req-{kind}"})
    events = _events(capfd.readouterr().out)

    assert r.status_code == status
    assert r.json()["error"]["code"] == code  # envelope and code unchanged
    entry = _only(events, "app_error")
    assert entry["level"] == level
    assert entry["error_code"] == code
    assert entry["status_code"] == status
    assert entry["request_id"] == f"req-{kind}"
    assert entry["http_path"] == "/__t/app-error/{kind}"  # route template, not the raw path
    assert entry["cause_type"] == cause_type
    assert ("exception" in entry) is has_traceback
    assert "unhandled_exception" not in {e["event"] for e in events}


@pytest.mark.parametrize("kind", ["not-found", "conflict"])
def test_4xx_app_errors_are_not_logged_as_failures(
    client: TestClient, capfd: CaptureFixture[str], kind: str
) -> None:
    capfd.readouterr()
    r = client.get(f"/__t/app-error/{kind}")
    assert r.status_code in (404, 409)
    events = _events(capfd.readouterr().out)
    assert not [e for e in events if e["level"] in ("error", "warning")]


def test_database_wait_timeout_is_a_logged_503(
    client: TestClient, capfd: CaptureFixture[str]
) -> None:
    capfd.readouterr()
    r = client.get("/__t/db/timeout")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "DATABASE_BUSY"
    assert r.headers["retry-after"] == "2"
    entry = _only(_events(capfd.readouterr().out), "db_wait_timeout")
    assert entry["level"] == "warning"
    assert entry["sqlstate"] == "55P03"
    assert "exception" not in entry


def test_generic_database_error_is_logged_without_bound_values(
    client: TestClient, capfd: CaptureFixture[str]
) -> None:
    """Needs the local test database (a read-only failing SELECT). The real engine's
    `hide_parameters=True` keeps the sentinel bound value out of the traceback; the response
    leaks neither SQL nor the value."""
    capfd.readouterr()
    r = client.get("/__t/db/generic", headers={"X-Request-Id": "req-db"})
    raw = capfd.readouterr().out
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "table_that_does_not_exist" not in r.text and SENTINEL not in r.text

    entry = _only(_events(raw), "db_error")
    assert entry["level"] == "error"
    assert entry["request_id"] == "req-db"
    assert entry["sqlstate"] == "42P01"
    assert "Traceback" in entry["exception"]
    assert SENTINEL not in raw


# --------------------------------------------------------------------------------------------
# LOG-05 — request-id validation
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ("a" * 64, True),  # exact upper bound (audit_log.request_id is VARCHAR(64))
        ("a", True),  # exact lower bound
        (str(uuid4()), True),  # web client
        ("req_1760000000000_9f3a2b", True),  # mobile client
        ("a" * 65, False),
        ("", False),
        (None, False),
        ("has space", False),
        ("line\nbreak", False),
        ("tab\there", False),
        ('quote"', False),
        ("../path", False),
        ("-leading-dash", False),
        ("ünïcode", False),
        ("x" * 3000, False),
    ],
)
def test_resolve_request_id_policy(raw: str | None, kept: bool) -> None:
    resolved = resolve_request_id(raw)
    if kept:
        assert resolved == raw
    else:
        assert resolved != raw
        assert UUID(resolved)  # a fresh UUID replaces it


@pytest.mark.parametrize(
    "header",
    [None, "a" * 65, "x" * 3000, "has space", "ünïcode".encode()],
)
def test_bad_or_missing_request_id_is_replaced_end_to_end(
    client: TestClient, capfd: CaptureFixture[str], header: str | bytes | None
) -> None:
    headers = {} if header is None else {"X-Request-Id": header}
    capfd.readouterr()
    r = client.get("/__t/boom", headers=headers)
    entry = _only(_events(capfd.readouterr().out), "unhandled_exception")
    generated = r.headers["x-request-id"]
    assert UUID(generated)
    assert r.json()["error"]["request_id"] == generated
    assert entry["request_id"] == generated


def test_valid_request_id_reaches_successful_responses(client: TestClient) -> None:
    r = client.get("/health/live", headers={"X-Request-Id": "ok-req-1"})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == "ok-req-1"
    r = client.get("/health/live")
    assert UUID(r.headers["x-request-id"])
