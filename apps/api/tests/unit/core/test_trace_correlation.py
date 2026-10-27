"""Trace correlation: W3C `traceparent` parsing, request-to-log binding, and propagation to a
Celery task. No tracing backend is involved (docs/architecture/OBSERVABILITY_ARCHITECTURE.md §7)."""

import json
from typing import Any

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import CaptureFixture

from hrms.app import create_app
from hrms.core import celery_app as _celery_signals  # noqa: F401 — connects the signal handlers
from hrms.core.observability import trace_context as tc

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN = "00f067aa0ba902b7"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "garbage",
        f"00-{TRACE}-{SPAN}",  # missing flags
        f"00-{'0' * 32}-{SPAN}-01",  # all-zero trace id is invalid
        f"00-{TRACE}-{'0' * 16}-01",  # all-zero span id is invalid
        f"00-{TRACE[:-1]}-{SPAN}-01",  # short
        f"00-{TRACE}-{SPAN}-01\r\nX-Evil: 1",  # header injection attempt
    ],
)
def test_malformed_traceparent_is_ignored_and_a_fresh_trace_starts(raw: str | None) -> None:
    ctx = tc.start_context(raw)
    assert ctx.parent_span_id is None
    assert len(ctx.trace_id) == 32 and ctx.trace_id != TRACE


def test_valid_traceparent_is_continued_with_a_new_span() -> None:
    ctx = tc.start_context(f"00-{TRACE}-{SPAN}-01")
    assert ctx.trace_id == TRACE and ctx.parent_span_id == SPAN and ctx.span_id != SPAN
    assert tc.parse_traceparent(ctx.traceparent()) == (TRACE, ctx.span_id)


def _events(out: str) -> list[dict[str, Any]]:
    rows = []
    for line in out.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def test_request_logs_carry_the_inbound_trace_id(capsys: CaptureFixture[str]) -> None:
    app: FastAPI = create_app()

    @app.get("/__t/trace")
    async def probe() -> dict[str, Any]:
        return {"traceparent": tc.current_traceparent()}

    client = TestClient(app)
    response = client.get("/__t/trace", headers={"traceparent": f"00-{TRACE}-{SPAN}-01"})
    inside = response.json()["traceparent"]
    assert inside.split("-")[1] == TRACE
    (access,) = [e for e in _events(capsys.readouterr().out) if e.get("event") == "http_request"]
    assert access["trace_id"] == TRACE
    assert access["request_id"] == response.headers["x-request-id"]
    # context is restored after the request
    assert "trace_id" not in structlog.contextvars.get_contextvars()


def test_each_request_without_a_header_gets_its_own_trace() -> None:
    client = TestClient(create_app())
    assert client.get("/health/live").status_code == 200  # no crash, nothing to correlate


def test_publisher_stamps_its_trace_on_the_task_message() -> None:
    from celery.signals import before_task_publish

    publisher = tc.start_context(f"00-{TRACE}-{SPAN}-01")
    tokens = structlog.contextvars.bind_contextvars(
        trace_id=publisher.trace_id, span_id=publisher.span_id
    )
    try:
        headers: dict[str, Any] = {"task": "test.trace_probe"}
        before_task_publish.send(sender="test.trace_probe", headers=headers)
    finally:
        structlog.contextvars.reset_contextvars(**tokens)
    assert headers["hrms_traceparent"] == publisher.traceparent()
    assert "hrms_enqueued_at" in headers


def test_worker_continues_the_publishers_trace_with_its_own_span() -> None:
    from celery.signals import task_postrun, task_prerun

    class _Request:
        hrms_traceparent = f"00-{TRACE}-{SPAN}-01"
        hrms_request_id = "req-1"

    class _Task:
        name = "test.trace_probe"
        request = _Request()

    task_prerun.send(sender=_Task, task_id="t-1", task=_Task())
    bound = structlog.contextvars.get_contextvars()
    assert bound["trace_id"] == TRACE
    assert bound["span_id"] != SPAN
    assert bound["request_id"] == "req-1"
    task_postrun.send(sender=_Task, task_id="t-1", task=_Task(), state="SUCCESS")
    assert "trace_id" not in structlog.contextvars.get_contextvars()


def test_a_beat_scheduled_task_starts_its_own_trace() -> None:
    from celery.signals import task_postrun, task_prerun

    class _Task:
        name = "test.trace_probe"

        class request:  # noqa: N801 — attribute bag standing in for Celery's request
            pass

    task_prerun.send(sender=_Task, task_id="t-2", task=_Task())
    assert len(structlog.contextvars.get_contextvars()["trace_id"]) == 32
    task_postrun.send(sender=_Task, task_id="t-2", task=_Task(), state="SUCCESS")
