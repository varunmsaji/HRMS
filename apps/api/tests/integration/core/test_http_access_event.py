"""The structured `http_request` access event (`RequestContextMiddleware`) through a real
`create_app()` stack: exactly one event per request, carrying the same request id the client
sees, the route *template* (never a raw token-bearing path), status, duration, the handled error
code, and only membership-verified tenant context. Successful health probes stay quiet.

Throwaway routes are added to a fresh `create_app()`, as in
`test_request_context_and_error_logging.py`; log output is read from the real stdout pipe."""

import json
from typing import Annotated, Any
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from pytest import CaptureFixture

from hrms.app import create_app
from hrms.core.errors.base import ConflictError
from hrms.core.tenancy.context import TenantContext, set_tenant


def _access_events(raw: str) -> list[dict[str, Any]]:
    out = []
    for line in raw.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get("event") == "http_request":
            out.append(parsed)
    return out


class _Body(BaseModel):
    name: str


def _verified_tenant() -> TenantContext:
    ctx = TenantContext(company_id=UUID(int=11), user_id=UUID(int=22))
    set_tenant(ctx)
    return ctx


@pytest.fixture
def app() -> FastAPI:
    app = create_app()

    @app.get("/__t/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    @app.get("/__t/tenant-item/{item_id}")
    async def tenant_item(
        item_id: str, _: Annotated[TenantContext, Depends(_verified_tenant)]
    ) -> dict[str, str]:
        return {"id": item_id}

    @app.post("/__t/validated")
    async def validated(body: _Body) -> dict[str, str]:
        return {"name": body.name}

    @app.post("/__t/conflict")
    async def conflict() -> None:
        raise ConflictError("already exists")

    @app.get("/__t/crash")
    async def crash() -> None:
        raise ValueError("crash-detail")

    return app


def _one(capfd: CaptureFixture[str]) -> dict[str, Any]:
    events = _access_events(capfd.readouterr().out)
    assert len(events) == 1, events
    return events[0]


def test_success_logs_the_template_status_duration_and_request_id(
    app: FastAPI, capfd: CaptureFixture[str]
) -> None:
    with TestClient(app) as c:
        capfd.readouterr()
        r = c.get("/__t/items/emp-SENSITIVE-42", headers={"X-Request-Id": "acc-req-1"})
    assert r.status_code == 200
    event = _one(capfd)
    assert event["level"] == "info"
    assert event["request_id"] == "acc-req-1" == r.headers["x-request-id"]
    assert event["http_method"] == "GET"
    assert event["http_path"] == "/__t/items/{item_id}"
    assert event["status_code"] == 200
    assert isinstance(event["duration_ms"], (int, float)) and event["duration_ms"] >= 0
    assert event["error_code"] is None
    assert event["company_id"] is None and event["user_id"] is None
    assert event["service"] == "api"
    assert "emp-SENSITIVE-42" not in json.dumps(event)


def test_verified_tenant_context_is_included(app: FastAPI, capfd: CaptureFixture[str]) -> None:
    with TestClient(app) as c:
        capfd.readouterr()
        c.get("/__t/tenant-item/x", headers={"X-Company-Id": str(UUID(int=99))})
    event = _one(capfd)
    assert event["company_id"] == str(UUID(int=11))
    assert event["user_id"] == str(UUID(int=22))
    # The unverified header value is never logged.
    assert str(UUID(int=99)) not in json.dumps(event)


def test_handled_business_error_records_its_code_at_info(
    app: FastAPI, capfd: CaptureFixture[str]
) -> None:
    with TestClient(app) as c:
        capfd.readouterr()
        r = c.post("/__t/conflict")
    assert r.status_code == 409
    event = _one(capfd)
    assert event["level"] == "info"
    assert event["status_code"] == 409
    assert event["error_code"] == "CONFLICT"


def test_validation_and_not_found_record_their_codes(
    app: FastAPI, capfd: CaptureFixture[str]
) -> None:
    with TestClient(app) as c:
        capfd.readouterr()
        c.get("/v1/does-not-exist")
        assert _one(capfd)["error_code"] == "HTTP_ERROR"
        c.post("/__t/validated", json={})
        event = _one(capfd)
    assert event["status_code"] == 422
    assert event["error_code"] == "REQUEST_VALIDATION_ERROR"
    assert event["http_path"] == "/__t/validated"


def test_unhandled_crash_yields_one_access_event_with_status_500(
    app: FastAPI, capfd: CaptureFixture[str]
) -> None:
    with TestClient(app) as c:
        capfd.readouterr()
        r = c.get("/__t/crash", headers={"X-Request-Id": "acc-crash-1"})
    assert r.status_code == 500
    event = _one(capfd)
    assert event["status_code"] == 500
    assert event["error_code"] == "INTERNAL_ERROR"
    assert event["request_id"] == "acc-crash-1"


def test_token_route_logs_the_template_not_the_token(
    app: FastAPI, capfd: CaptureFixture[str]
) -> None:
    token = "inv-SENTINEL-token-0042"
    with TestClient(app) as c:
        capfd.readouterr()
        c.get(f"/v1/public/account-invites/{token}")
        raw = capfd.readouterr().out
    assert token not in raw
    (event,) = _access_events(raw)
    assert event["http_path"] == "/v1/public/account-invites/{token}"


def test_successful_health_probes_are_not_logged(app: FastAPI, capfd: CaptureFixture[str]) -> None:
    with TestClient(app) as c:
        capfd.readouterr()
        assert c.get("/health/live").status_code == 200
    assert _access_events(capfd.readouterr().out) == []
