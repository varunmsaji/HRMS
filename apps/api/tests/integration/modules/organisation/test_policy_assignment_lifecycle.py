"""Assigning only published policies, finding the open assignment to replace, and ending an
override so its scope falls back to the next wider assignment."""

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from ...tenant_wipe import wipe_tenant
from ..employee.test_employee_assignment import _register_tenant
from .conftest import seeded_plan_catalogue  # noqa: F401

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]


async def _publish_attendance_policy(client: AsyncClient, headers: dict, name: str) -> dict:
    policy = (
        await client.post("/v1/attendance-policies", headers=headers, json={"name": name})
    ).json()["data"]
    draft = (
        await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "hour_bands": [{"min_minutes": 0, "max_minutes": None, "result_status": "PRESENT"}],
            },
        )
    ).json()["data"]
    published = await client.post(
        f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text
    return policy


def _body(policy_id: str, eff: str, scope: str = "COMPANY", scope_id: str | None = None) -> dict:
    body: dict[str, Any] = {
        "policy_kind": "ATTENDANCE_POLICY",
        "policy_id": policy_id,
        "scope_type": scope,
        "effective_from": eff,
    }
    if scope_id:
        body["scope_id"] = scope_id
    return body


async def _end(client: AsyncClient, headers: dict, row: dict, to: str, version: int | None = None):
    return await client.post(
        f"/v1/policy-assignments/{row['id']}/end",
        headers={**headers, "If-Match": str(version or row["version"])},
        json={"effective_to": to},
    )


async def _department(client: AsyncClient, headers: dict) -> str:
    r = await client.post("/v1/departments", headers=headers, json={"name": "Ops"})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


async def test_unpublished_and_inactive_policies_cannot_be_assigned(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        draft_only = (
            await client.post("/v1/attendance-policies", headers=headers, json={"name": "Draft"})
        ).json()["data"]
        r = await client.post(
            "/v1/policy-assignments", headers=headers, json=_body(draft_only["id"], "2027-01-01")
        )
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "POLICY_NOT_PUBLISHED"

        retired = await _publish_attendance_policy(client, headers, "Retired")
        deactivated = await client.patch(
            f"/v1/attendance-policies/{retired['id']}",
            headers={**headers, "If-Match": str(retired["version"])},
            json={"is_active": False},
        )
        assert deactivated.status_code == 200, deactivated.text
        r = await client.post(
            "/v1/policy-assignments", headers=headers, json=_body(retired["id"], "2027-01-01")
        )
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "INVALID_POLICY_REFERENCE"

        live = await _publish_attendance_policy(client, headers, "Live")
        everything = await client.get("/v1/attendance-policies", headers=headers)
        assert len(everything.json()["data"]) == 3
        assignable = await client.get(
            "/v1/attendance-policies", headers=headers, params={"assignable": "true"}
        )
        assert [p["id"] for p in assignable.json()["data"]] == [live["id"]]
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_current_only_finds_the_open_row_to_replace(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        first = await _publish_attendance_policy(client, headers, "First")
        second = await _publish_attendance_policy(client, headers, "Second")
        created = await client.post(
            "/v1/policy-assignments", headers=headers, json=_body(first["id"], "2027-01-01")
        )
        assert created.status_code == 201, created.text

        params = {
            "policy_kind": "ATTENDANCE_POLICY",
            "scope_type": "COMPANY",
            "current_only": "true",
        }
        found = await client.get("/v1/policy-assignments", headers=headers, params=params)
        open_row = found.json()["data"][0]

        replaced = await client.post(
            "/v1/policy-assignments",
            headers={**headers, "If-Match": str(open_row["version"])},
            json=_body(second["id"], "2027-02-01"),
        )
        assert replaced.status_code == 201, replaced.text

        found = await client.get("/v1/policy-assignments", headers=headers, params=params)
        assert [r["policy_id"] for r in found.json()["data"]] == [second["id"]]
        assert found.json()["pagination"]["total"] == 1
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_ending_an_override_falls_back_to_the_company_policy(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        company_policy = await _publish_attendance_policy(client, headers, "Company")
        dept_policy = await _publish_attendance_policy(client, headers, "Department")
        department_id = await _department(client, headers)
        company_row = (
            await client.post(
                "/v1/policy-assignments",
                headers=headers,
                json=_body(company_policy["id"], "2027-01-01"),
            )
        ).json()["data"]
        override = (
            await client.post(
                "/v1/policy-assignments",
                headers=headers,
                json=_body(dept_policy["id"], "2027-01-01", "DEPARTMENT", department_id),
            )
        ).json()["data"]

        # the company-wide row is the safety net
        r = await _end(client, headers, company_row, "2027-03-31")
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "POLICY_ASSIGNMENT_NOT_ENDABLE"

        r = await _end(client, headers, override, "2026-12-31")
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "INVALID_EFFECTIVE_TO"

        r = await _end(client, headers, override, "2027-03-31", version=override["version"] + 5)
        assert r.status_code == 409, r.text

        r = await _end(client, headers, override, "2027-03-31")
        assert r.status_code == 200, r.text
        ended = r.json()["data"]
        assert ended["effective_to"] == "2027-03-31"
        assert ended["version"] == override["version"] + 1

        r = await _end(client, headers, ended, "2027-04-30")
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "POLICY_ASSIGNMENT_NOT_ENDABLE"

        # a fresh override at that scope needs no If-Match any more: nothing is open there
        again = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json=_body(dept_policy["id"], "2027-05-01", "DEPARTMENT", department_id),
        )
        assert again.status_code == 201, again.text

        r = await client.post(
            f"/v1/policy-assignments/{uuid4()}/end",
            headers={**headers, "If-Match": "1"},
            json={"effective_to": "2027-03-31"},
        )
        assert r.status_code == 404, r.text
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)
