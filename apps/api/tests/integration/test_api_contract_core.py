"""Cross-cutting API contract tests: envelopes, request-id propagation, auth/permission/tenant
errors, optimistic concurrency, idempotency-required, and rate limiting. They assert the
documented contract in docs/api (API_OVERVIEW.md, ERROR_HANDLING.md) against the live app."""

import re
from uuid import uuid4

import pytest
from entrypoints.api import app
from httpx import ASGITransport, AsyncClient

from .contract_helpers import assert_data, assert_error
from .modules.account_invite.conftest import seeded_plan_catalogue  # noqa: F401
from .modules.account_invite.test_account_invite import _register_tenant, _teardown
from .modules.account_invite.uac_helpers import Tenant as UacTenant
from .modules.account_invite.uac_helpers import onboard, reset_auth_rate_limit

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]


async def test_request_id_is_echoed_validated_and_replaced(client: AsyncClient) -> None:
    ok = await client.get(
        "/v1/companies/registration-config", headers={"X-Request-Id": "req_abc-123.x"}
    )
    assert ok.headers["x-request-id"] == "req_abc-123.x"
    assert assert_data(ok)["allowed_company_timezones"]
    assert ok.json()["meta"]["request_id"] == "req_abc-123.x"
    # a value outside [A-Za-z0-9][A-Za-z0-9._:-]{0,63} is replaced by a server UUID, never echoed
    for bad in ("has space", "x" * 65, "-leading", "semi;colon"):
        r = await client.get("/v1/companies/registration-config", headers={"X-Request-Id": bad})
        assert r.headers["x-request-id"] != bad
        assert re.fullmatch(r"[0-9a-f-]{36}", r.headers["x-request-id"])
    err = assert_error(
        await client.get("/v1/branches", headers={"X-Request-Id": "trace-1"}), 401, "UNAUTHORIZED"
    )
    assert err["request_id"] == "trace-1"


async def test_framework_errors_use_the_same_envelope(client: AsyncClient) -> None:
    assert_error(await client.get("/v1/definitely-not-a-route"), 404, "NOT_FOUND")
    assert_error(await client.delete("/v1/auth/login"), 405, "METHOD_NOT_ALLOWED")
    bad = assert_error(
        await client.post("/v1/auth/login", json={"email": "nope"}), 422, "REQUEST_VALIDATION_ERROR"
    )
    assert bad["details"][0]["field"].startswith("body.")


async def test_auth_permission_tenant_and_concurrency_contract(client: AsyncClient) -> None:
    await reset_auth_rate_limit()
    headers, company_id, user_id = await _register_tenant(client)
    uac = UacTenant(headers=headers, company_id=company_id, admin_user_id=user_id, emails=[])
    try:
        assert_error(
            await client.get("/v1/branches", headers={"Authorization": "Bearer junk"}),
            401,
            "INVALID_TOKEN",
        )

        # tenant header that does not match the token is a 404, not a data leak
        assert_error(
            await client.get("/v1/branches", headers={**headers, "X-Company-Id": str(uuid4())}),
            404,
            "NOT_FOUND",
        )

        # permission denied names the missing code
        emp = await onboard(client, uac, "EMPLOYEE")
        denied = assert_error(
            await client.get("/v1/companies/current", headers=emp.headers), 403, "PERMISSION_DENIED"
        )
        assert "ORG.COMPANY.MANAGE" in denied["message"]

        # optimistic concurrency: missing -> 422, stale -> 409 carrying the current resource
        company = assert_data(await client.get("/v1/companies/current", headers=headers))
        assert_error(
            await client.patch("/v1/companies/current", headers=headers, json={"name": "Renamed"}),
            422,
        )
        stale = assert_error(
            await client.patch(
                "/v1/companies/current",
                headers={**headers, "If-Match": str(company["version"] + 7)},
                json={"name": "Renamed"},
            ),
            409,
            "STALE_RESOURCE",
        )
        assert stale["details"][0]["context"]["current"]["id"] == company["id"]
        fresh = assert_data(
            await client.patch(
                "/v1/companies/current",
                headers={**headers, "If-Match": str(company["version"])},
                json={"name": company["name"]},
            )
        )
        assert fresh["version"] == company["version"] + 1

        # idempotency-required operations refuse a missing/malformed key before doing any work
        body = {"leave_type_id": str(uuid4()), "start_date": "2026-03-02", "end_date": "2026-03-02"}
        # the shared `client` injects keys on these paths; a plain client has the real contract
        plain = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        assert_error(
            await plain.post("/v1/leave-applications", headers=emp.headers, json=body),
            422,
            "IDEMPOTENCY_KEY_REQUIRED",
        )
        assert_error(
            await plain.post(
                "/v1/leave-applications", headers={**emp.headers, "Idempotency-Key": "x"}, json=body
            ),
            422,
            "IDEMPOTENCY_KEY_INVALID",
        )
    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=uac.emails)


async def test_login_rate_limit_returns_429_with_retry_after(client: AsyncClient) -> None:
    await reset_auth_rate_limit()
    import redis.asyncio as redis

    from hrms.core.config.settings import get_settings

    r = redis.from_url(get_settings().redis_url, decode_responses=True)
    for key in await r.keys("ratelimit:login:*"):
        await r.delete(key)
    email = f"rl-{uuid4().hex[:8]}@example.com"
    last = None
    try:
        for _ in range(12):
            last = await client.post("/v1/auth/login", json={"email": email, "password": "x"})
            if last.status_code == 429:
                break
        assert last is not None
        assert_error(last, 429, "RATE_LIMITED")
        assert int(last.headers["retry-after"]) > 0
    finally:
        for key in await r.keys("ratelimit:login:*"):
            await r.delete(key)
        await r.aclose()
