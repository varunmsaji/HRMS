"""An unexpected exception inside ANY route reaches the client as the fixed envelope, nothing else.

The real application (`create_app()`, every router, every middleware) is built and a request is
sent to every operation in its OpenAPI schema. FastAPI's dependency solving and endpoint call are
replaced so the route "runs" and raises a sentinel exception carrying text that must never be
shown (SQL, a file path, a secret-looking value). Nothing touches a database or any data: the
endpoints, services and auth dependencies never execute.

The assertions are on the response a user could see: no sentinel, no traceback, no exception class
name; a 500 uses the standard envelope with the generic message and an `ERR-` reference that
matches the request id the response also carries.
"""

import re
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Response
from httpx import ASGITransport, AsyncClient

from hrms.app import create_app
from hrms.core.errors.base import GENERIC_SERVER_ERROR_MESSAGE
from hrms.core.errors.envelope import error_reference

pytestmark = pytest.mark.asyncio

SENTINEL = (
    "SENTINEL-9f3a SELECT salary FROM payroll_run at /srv/hrms/app/service.py:88 key=sk_live_123"
)
FORBIDDEN = (
    "SENTINEL",
    "SELECT",
    "payroll_run",
    "/srv/hrms",
    "sk_live",
    "Traceback",
    "RuntimeError",
)
METHODS = {"get", "post", "put", "patch", "delete"}
#: A route whose request never reaches the (replaced) endpoint, for a reason that is not a defect:
#: e.g. a webhook-style path the middleware answers itself. Everything else must reach it.
MIN_REACHED_SHARE = 0.9


def _operations(app: Any) -> list[tuple[str, str, dict[str, Any]]]:
    spec = app.openapi()
    found: list[tuple[str, str, dict[str, Any]]] = []
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method in METHODS:
                found.append((method.upper(), path, operation))
    return sorted(found, key=lambda o: (o[1], o[0]))


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "00000000-0000-4000-8000-000000000001", path)


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Any:
    async def fake_solve(**_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(errors=[], values={}, background_tasks=None, response=Response())

    async def exploding_endpoint(**_kwargs: Any) -> Any:
        raise RuntimeError(SENTINEL)

    monkeypatch.setattr("fastapi.routing.solve_dependencies", fake_solve)
    monkeypatch.setattr("fastapi.routing.run_endpoint_function", exploding_endpoint)
    return create_app()


async def test_every_operation_hides_an_unexpected_exception(app: Any) -> None:
    operations = _operations(app)
    assert len(operations) > 150, "the OpenAPI schema should list the whole API"
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    reached = 0
    problems: list[str] = []
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for method, path, _operation in operations:
            response = await client.request(
                method,
                _fill(path),
                json={} if method != "GET" else None,
                headers={"X-Request-Id": "route-check-1"},
            )
            text = response.text
            label = f"{method} {path} -> {response.status_code}"
            if any(word in text for word in FORBIDDEN):
                problems.append(f"{label}: body leaks {text[:120]!r}")
                continue
            if response.status_code != 500:
                continue
            reached += 1
            error = response.json().get("error", {})
            expected = (
                error.get("code") == "INTERNAL_ERROR"
                and error.get("message") == GENERIC_SERVER_ERROR_MESSAGE
                and error.get("reference") == error_reference(error.get("request_id", ""))
                and response.headers.get("x-request-id") == error.get("request_id")
                and error.get("details") == []
            )
            if not expected:
                problems.append(f"{label}: not the standard 500 envelope: {error}")
    assert problems == []
    assert reached >= MIN_REACHED_SHARE * len(operations), (
        f"only {reached} of {len(operations)} operations reached the failing endpoint; "
        "the check is not exercising the API"
    )
