"""API audit H-4 - `Idempotency-Key` on POST /employees and POST /onboarding-cases (opt-in).

Covers: no header = unchanged behaviour; sequential retry replays; concurrent duplicates create
exactly one row; incompatible reuse is a 409; keys are scoped per tenant and per user-visible
operation; a malformed key is a 422; and a request that fails does not consume the key."""

import asyncio
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory, set_rls_company_id

from ...tenant_wipe import wipe_tenant
from ..account_invite.test_account_invite import _register_tenant

pytestmark = pytest.mark.asyncio


async def _count(company_id, table: str) -> int:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        return int(
            (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE company_id = :c"),
                    {"c": str(company_id)},
                )
            ).scalar_one()
        )


async def test_employee_create_idempotency(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    other_headers, other_company, other_user = await _register_tenant(client)
    try:
        body = {"first_name": "Asha", "personal_email": f"a-{uuid4().hex[:6]}@example.com"}
        key = f"idem-{uuid4()}"

        # no header: two calls, two employees (behaviour unchanged)
        a = await client.post("/v1/employees", headers=headers, json={"first_name": "Plain"})
        b = await client.post("/v1/employees", headers=headers, json={"first_name": "Plain"})
        assert (
            a.status_code == b.status_code == 201
            and a.json()["data"]["id"] != b.json()["data"]["id"]
        )
        assert "idempotent-replayed" not in a.headers

        first = await client.post(
            "/v1/employees", headers={**headers, "Idempotency-Key": key}, json=body
        )
        assert first.status_code == 201
        retry = await client.post(
            "/v1/employees", headers={**headers, "Idempotency-Key": key}, json=body
        )
        assert retry.status_code == 201
        assert retry.headers["idempotent-replayed"] == "true"
        assert retry.json()["data"] == first.json()["data"]  # same employee, same code
        assert await _count(company_id, "employee") == 3

        # same key, different body -> conflict, nothing created
        clash = await client.post(
            "/v1/employees",
            headers={**headers, "Idempotency-Key": key},
            json={**body, "first_name": "Other"},
        )
        assert (
            clash.status_code == 409 and clash.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
        )
        assert await _count(company_id, "employee") == 3

        # malformed key is rejected, not ignored
        bad = await client.post(
            "/v1/employees", headers={**headers, "Idempotency-Key": "short"}, json=body
        )
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "IDEMPOTENCY_KEY_INVALID"

        # the same key in another tenant is an independent operation
        other = await client.post(
            "/v1/employees", headers={**other_headers, "Idempotency-Key": key}, json=body
        )
        assert other.status_code == 201 and "idempotent-replayed" not in other.headers
        assert other.json()["data"]["id"] != first.json()["data"]["id"]

        # a schema-invalid request never consumes the key
        k2 = f"idem-{uuid4()}"
        assert (
            await client.post(
                "/v1/employees", headers={**headers, "Idempotency-Key": k2}, json={"first_name": ""}
            )
        ).status_code == 422
        ok = await client.post(
            "/v1/employees",
            headers={**headers, "Idempotency-Key": k2},
            json={"first_name": "Fixed"},
        )
        assert ok.status_code == 201 and "idempotent-replayed" not in ok.headers
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)
        await wipe_tenant(company_id=other_company, user_id=other_user)


async def test_concurrent_duplicates_create_exactly_one_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        key = f"idem-{uuid4()}"
        body = {"first_name": "Racer", "personal_email": f"r-{uuid4().hex[:6]}@example.com"}
        results = await asyncio.gather(
            *[
                client.post("/v1/employees", headers={**headers, "Idempotency-Key": key}, json=body)
                for _ in range(6)
            ]
        )
        assert [r.status_code for r in results] == [201] * 6, [r.text for r in results]
        assert len({r.json()["data"]["id"] for r in results}) == 1
        assert sum(1 for r in results if r.headers.get("idempotent-replayed") == "true") == 5
        assert await _count(company_id, "employee") == 1
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_onboarding_case_create_idempotency(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        body = {
            "candidate_first_name": "Neha",
            "candidate_last_name": "Rao",
            "personal_email": f"n-{uuid4().hex[:6]}@example.com",
            "proposed_joining_date": "2026-12-01",
        }
        probe = await client.post("/v1/onboarding-cases", headers=headers, json=body)
        if probe.status_code == 422:  # schema moved on: show the contract the test must follow
            pytest.fail(probe.text)
        assert probe.status_code == 201, probe.text
        key = f"idem-{uuid4()}"
        body2 = {**body, "personal_email": f"m-{uuid4().hex[:6]}@example.com"}
        h = {**headers, "Idempotency-Key": key}
        first = await client.post("/v1/onboarding-cases", headers=h, json=body2)
        again = await client.post("/v1/onboarding-cases", headers=h, json=body2)
        assert first.status_code == again.status_code == 201
        assert again.headers["idempotent-replayed"] == "true"
        assert first.json()["data"]["id"] == again.json()["data"]["id"]
        assert await _count(company_id, "onboarding_case") == 2
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)
