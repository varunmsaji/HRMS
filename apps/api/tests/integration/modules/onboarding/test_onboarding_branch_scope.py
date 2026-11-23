"""Onboarding cases for a caller limited to their assigned branches (decision D4).

An HR administrator / branch manager without `COMPANY_ADMIN` lists, counts and opens only the cases
whose branch is one of theirs (and still live). A case with no branch is hidden from them. Anything
out of reach answers 404, the same as a missing case. A company administrator is unaffected."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory

from ..employee.test_assigned_branches_scope import _cleanup_access, _restricted_actor
from ..employee.test_employee_data_scope import _cleanup_scoped_actors, _setup_branches
from .test_onboarding_case import (
    _case_payload,
    _cleanup_onboarding_cases,
    _register_tenant,
    _teardown,
)

pytestmark = pytest.mark.asyncio


async def _case(
    client: AsyncClient, headers: dict[str, str], branch_id: UUID | None, **extra: Any
) -> dict[str, Any]:
    body = _case_payload(**extra)
    if branch_id is not None:
        body["branch_id"] = str(branch_id)
    response = await client.post("/v1/onboarding-cases", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _listed(client: AsyncClient, headers: dict[str, str]) -> tuple[set[str], int]:
    response = await client.get("/v1/onboarding-cases", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    return {row["id"] for row in body["data"]}, int(body["pagination"]["total"])


async def _total_counted(client: AsyncClient, headers: dict[str, str]) -> int:
    response = await client.get("/v1/onboarding-cases/status-counts", headers=headers)
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["total"])


async def _delete_branches(company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM branch WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _done(company_id: UUID, admin_id: UUID | None) -> None:
    await _cleanup_access(company_id)
    await _cleanup_onboarding_cases(company_id=company_id)
    await _delete_branches(company_id)
    await _teardown(company_id=company_id, user_id=admin_id)
    await _cleanup_scoped_actors()


async def test_two_hrs_on_disjoint_branches_see_only_their_own_cases(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        blr, mum = await _setup_branches(company_id=company_id, count=2)
        in_blr = await _case(client, headers, blr)
        in_mum = await _case(client, headers, mum)
        hr_blr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr]
        )
        hr_mum, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[mum]
        )

        assert await _listed(client, hr_blr) == ({in_blr["id"]}, 1)
        assert await _listed(client, hr_mum) == ({in_mum["id"]}, 1)
        assert await _total_counted(client, hr_blr) == 1
        assert await _total_counted(client, hr_mum) == 1

        def path(case: dict[str, Any]) -> str:
            return f"/v1/onboarding-cases/{case['id']}"

        assert (await client.get(path(in_blr), headers=hr_blr)).status_code == 200
        assert (await client.get(path(in_mum), headers=hr_blr)).status_code == 404
        assert (await client.get(path(in_mum), headers=hr_mum)).status_code == 200
        assert (await client.get(path(in_blr), headers=hr_mum)).status_code == 404
    finally:
        await _done(company_id, admin_id)


async def test_every_case_route_is_closed_for_a_case_in_another_branch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        blr, mum = await _setup_branches(company_id=company_id, count=2)
        in_mum = await _case(client, headers, mum)
        hr_blr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr]
        )
        base = f"/v1/onboarding-cases/{in_mum['id']}"
        calls = [
            ("GET", base),
            ("GET", f"{base}/messages"),
            ("GET", f"{base}/documents"),
            ("GET", f"{base}/invitation/compose"),
            ("POST", f"{base}/invitation/preview"),
            ("POST", f"{base}/send-invite"),
            ("POST", f"{base}/request-changes"),
            ("POST", f"{base}/cancel"),
            ("POST", f"{base}/activate"),
        ]
        for method, url in calls:
            response = await client.request(method, url, headers=hr_blr, json={})
            assert response.status_code == 404, (method, url, response.status_code, response.text)
        # Nothing happened to it.
        assert (await client.get(base, headers=headers)).json()["data"]["status"] == "DRAFT"
    finally:
        await _done(company_id, admin_id)


async def test_a_restricted_hr_can_act_on_a_case_in_their_branch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        (blr,) = await _setup_branches(company_id=company_id, count=1)
        mine = await _case(client, headers, blr)
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr]
        )
        cancelled = await client.post(f"/v1/onboarding-cases/{mine['id']}/cancel", headers=hr)
        assert cancelled.status_code == 200, cancelled.text
    finally:
        await _done(company_id, admin_id)


async def test_a_case_with_no_branch_is_hidden_from_a_restricted_hr(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        (blr,) = await _setup_branches(company_id=company_id, count=1)
        no_branch = await _case(client, headers, None)
        in_blr = await _case(client, headers, blr)
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr]
        )
        assert await _listed(client, hr) == ({in_blr["id"]}, 1)
        assert await _total_counted(client, hr) == 1
        hidden = await client.get(f"/v1/onboarding-cases/{no_branch['id']}", headers=hr)
        assert hidden.status_code == 404
        # The company admin still sees both.
        assert await _listed(client, headers) == ({no_branch["id"], in_blr["id"]}, 2)
    finally:
        await _done(company_id, admin_id)


async def test_a_restricted_hr_with_no_branches_sees_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        (blr,) = await _setup_branches(company_id=company_id, count=1)
        in_blr = await _case(client, headers, blr)
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[]
        )
        assert await _listed(client, hr) == (set(), 0)
        assert await _total_counted(client, hr) == 0
        assert (
            await client.get(f"/v1/onboarding-cases/{in_blr['id']}", headers=hr)
        ).status_code == 404
    finally:
        await _done(company_id, admin_id)


async def test_a_deactivated_branch_drops_out_of_reach(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        blr, mum = await _setup_branches(company_id=company_id, count=2)
        in_blr = await _case(client, headers, blr)
        in_mum = await _case(client, headers, mum)
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr, mum]
        )
        assert (await _listed(client, hr))[0] == {in_blr["id"], in_mum["id"]}
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("UPDATE branch SET is_active = false WHERE id = :b"), {"b": str(mum)}
            )
            await session.commit()
        assert await _listed(client, hr) == ({in_blr["id"]}, 1)
        assert (
            await client.get(f"/v1/onboarding-cases/{in_mum['id']}", headers=hr)
        ).status_code == 404
    finally:
        await _done(company_id, admin_id)


async def test_creating_a_case_needs_an_assigned_branch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        blr, mum = await _setup_branches(company_id=company_id, count=2)
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr]
        )
        for branch in (mum, None):
            body = _case_payload()
            if branch is not None:
                body["branch_id"] = str(branch)
            refused = await client.post("/v1/onboarding-cases", headers=hr, json=body)
            assert refused.status_code == 403, refused.text
            assert refused.json()["error"]["code"] == "BRANCH_NOT_ASSIGNED"
        ok = await client.post(
            "/v1/onboarding-cases",
            headers=hr,
            json={**_case_payload(), "branch_id": str(blr)},
        )
        assert ok.status_code == 201, ok.text
        assert ok.json()["data"]["branch_id"] == str(blr)
    finally:
        await _done(company_id, admin_id)


async def test_company_admin_sees_every_case_and_creates_without_a_branch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        blr, mum = await _setup_branches(company_id=company_id, count=2)
        ids = {
            (await _case(client, headers, blr))["id"],
            (await _case(client, headers, mum))["id"],
            (await _case(client, headers, None))["id"],
        }
        assert await _listed(client, headers) == (ids, 3)
        assert await _total_counted(client, headers) == 3
    finally:
        await _done(company_id, admin_id)
