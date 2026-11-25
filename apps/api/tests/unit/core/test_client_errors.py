"""EH-W-02 / EH-M-01 — the client-error ingestion endpoint: bounded, scrubbed, one log event."""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from hrms.core.errors.handlers import register_exception_handlers
from hrms.core.observability import client_errors_router as module

pytestmark = pytest.mark.asyncio


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def error(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(module, "_logger", rec)
    return rec


@pytest.fixture
def client() -> AsyncClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(module.router, prefix="/v1")
    app.dependency_overrides[module._client_error_rate_limit] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


GOOD: dict[str, Any] = {
    "source": "web",
    "kind": "render",
    "error_class": "TypeError",
    "frames": ["/_next/static/chunks/page-1.js:10:5"],
    "path": "/reset-password/abc123secret",
    "request_id": "req-1",
    "reference": "ERR-1A2B3C4D",
}


async def test_a_report_becomes_one_client_error_log_event(
    client: AsyncClient, recorder: _Recorder
) -> None:
    r = await client.post("/v1/client-errors", json=GOOD)
    assert r.status_code == 204 and r.content == b""
    [(event, fields)] = recorder.events
    assert event == "client_error"
    assert fields["source"] == "web" and fields["reference"] == "ERR-1A2B3C4D"
    assert fields["client_request_id"] == "req-1"
    assert fields["frames"] == ["/_next/static/chunks/page-1.js:10:5"]


async def test_a_token_in_the_page_path_is_masked(client: AsyncClient, recorder: _Recorder) -> None:
    await client.post("/v1/client-errors", json=GOOD)
    assert "abc123secret" not in str(recorder.events)


async def test_unknown_fields_such_as_a_message_are_never_logged(
    client: AsyncClient, recorder: _Recorder
) -> None:
    await client.post(
        "/v1/client-errors", json={**GOOD, "message": "salary is 9999999", "stack": "x"}
    )
    assert "9999999" not in str(recorder.events)
    assert "message" not in recorder.events[0][1] and "stack" not in recorder.events[0][1]


@pytest.mark.parametrize(
    "bad",
    [
        {**GOOD, "source": "desktop"},
        {**GOOD, "error_class": "x" * 500},
        {**GOOD, "frames": ["f"] * 50},
        {**GOOD, "status": 9999},
        {k: v for k, v in GOOD.items() if k != "error_class"},
    ],
)
async def test_invalid_or_oversized_reports_are_rejected_and_not_logged(
    client: AsyncClient, recorder: _Recorder, bad: dict[str, Any]
) -> None:
    r = await client.post("/v1/client-errors", json=bad)
    assert r.status_code == 422
    assert recorder.events == []


# --- privacy: what a hostile or careless client can put in a report ----------------------------
HOSTILE = {
    "error_class": "TypeError Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln",
    "kind": "priya@example.com",
    "frames": ["/_next/static/x.js:1:2 token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln"],
    "code": "PAN ABCDE1234F",
    "app_version": "9876543210",
    "request_id": "aadhaar 2345 6789 0123",
    "path": "/reset-password/abc123secret?token=zzz",
}


async def test_whatever_a_client_puts_in_a_report_is_masked_before_it_is_stored(
    client: AsyncClient, recorder: _Recorder
) -> None:
    """The record goes through the same redaction processor as every other log line, so a client
    that stuffs a token, an email, a PAN, an Aadhaar or a phone number into any string field does
    not get it stored."""
    from hrms.core.observability.redaction import redact_event

    r = await client.post("/v1/client-errors", json={**GOOD, **HOSTILE})
    assert r.status_code == 204
    [(event, fields)] = recorder.events
    stored = str(redact_event(None, "error", {"event": event, **fields}))
    for secret in (
        "eyJhbGciOiJIUzI1NiJ9",
        "priya@example.com",
        "ABCDE1234F",
        "2345 6789 0123",
        "abc123secret",
        "zzz",
    ):
        assert secret not in stored, secret


async def test_a_report_has_no_field_that_could_carry_a_message_or_a_payload(
    client: AsyncClient, recorder: _Recorder
) -> None:
    await client.post(
        "/v1/client-errors",
        json={**GOOD, "message": "x", "stack": "y", "body": {"salary": 1}, "headers": {"a": "b"}},
    )
    fields = recorder.events[0][1]
    assert not {"message", "stack", "body", "headers", "payload", "response"} & set(fields)
