"""Reusable assertions for API contract tests (API audit, Phase 9).

One definition of "a well-formed success/error response" so contract tests state only what is
specific to the endpoint under test."""

from typing import Any

from httpx import Response

ERROR_KEYS = {"code", "message", "details", "request_id", "documentation_url"}


def assert_error(response: Response, status: int, code: str | None = None) -> dict[str, Any]:
    assert response.status_code == status, (response.status_code, response.text)
    body = response.json()
    assert set(body) == {"error"}, body
    err = body["error"]
    assert set(err) == ERROR_KEYS, err
    assert isinstance(err["details"], list)
    assert err["request_id"] and err["request_id"] == response.headers["x-request-id"]
    if code is not None:
        assert err["code"] == code, err
    return dict(err)


def assert_data(response: Response, status: int = 200) -> Any:
    assert response.status_code == status, (response.status_code, response.text)
    body = response.json()
    assert "data" in body and "meta" in body, body
    assert body["meta"]["request_id"] == response.headers["x-request-id"]
    return body["data"]


def assert_page(response: Response, *, per_page: int, total: int) -> list[Any]:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pagination"]["per_page"] == per_page
    assert body["pagination"]["total"] == total
    assert body["meta"]["request_id"] == response.headers["x-request-id"]
    return list(body["data"])
