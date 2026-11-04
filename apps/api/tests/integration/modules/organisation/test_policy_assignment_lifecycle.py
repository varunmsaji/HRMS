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


async def test_coverage_shows_what_applies_and_where_it_comes_from(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        company_policy = await _publish_attendance_policy(client, headers, "Company")
        dept_policy = await _publish_attendance_policy(client, headers, "Department")
        department_id = await _department(client, headers)
        await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json=_body(company_policy["id"], "2026-01-01"),
        )

        async def row(scope: str, scope_id: str | None) -> dict:
            params = {"scope_type": scope, "as_of": "2026-06-01"}
            if scope_id:
                params["scope_id"] = scope_id
            r = await client.get("/v1/policy-assignments/coverage", headers=headers, params=params)
            assert r.status_code == 200, r.text
            rows = r.json()["data"]["rows"]
            assert {x["policy_kind"] for x in rows} >= {"WORK_CALENDAR", "ATTENDANCE_POLICY"}
            return next(x for x in rows if x["policy_kind"] == "ATTENDANCE_POLICY")

        # nothing set on the department: it inherits the company's
        inherited = await row("DEPARTMENT", department_id)
        assert inherited["own"] is None
        assert inherited["applied"]["policy_name"] == "Company"
        assert inherited["applied"]["scope_type"] == "COMPANY"
        assert inherited["applied"]["has_rules"] is True

        created = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json=_body(dept_policy["id"], "2026-02-01", "DEPARTMENT", department_id),
        )
        assert created.status_code == 201, created.text
        own = await row("DEPARTMENT", department_id)
        assert own["own"]["policy_name"] == "Department"
        assert own["own"]["version"] == created.json()["data"]["version"]
        assert own["applied"]["scope_type"] == "DEPARTMENT"
        assert own["applied"]["scope_name"] == "Ops"
        assert own["applied"]["effective_to"] is None

        # a future assignment is set here, but the company's still applies until it starts
        later = await _publish_attendance_policy(client, headers, "Later")
        grade = await client.post("/v1/grades", headers=headers, json={"name": "G1"})
        assert grade.status_code == 201, grade.text
        grade_id = grade.json()["data"]["id"]
        await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json=_body(later["id"], "2026-09-01", "GRADE", grade_id),
        )
        future = await row("GRADE", grade_id)
        assert future["own"]["policy_name"] == "Later"
        assert future["applied"]["policy_name"] == "Company"

        # scope must exist and match its type
        r = await client.get(
            "/v1/policy-assignments/coverage",
            headers=headers,
            params={"scope_type": "DEPARTMENT", "scope_id": str(uuid4()), "as_of": "2026-06-01"},
        )
        assert r.status_code == 422, r.text
        r = await client.get(
            "/v1/policy-assignments/coverage",
            headers=headers,
            params={"scope_type": "DEPARTMENT", "as_of": "2026-06-01"},
        )
        assert r.status_code == 422, r.text
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_batch_is_all_or_nothing(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        attendance = await _publish_attendance_policy(client, headers, "Attendance")
        unpublished = (
            await client.post("/v1/overtime-policies", headers=headers, json={"name": "OT draft"})
        ).json()["data"]

        def batch(*changes: dict, eff: str = "2027-01-01") -> dict:
            return {"scope_type": "COMPANY", "effective_from": eff, "changes": list(changes)}

        good = {"policy_kind": "ATTENDANCE_POLICY", "policy_id": attendance["id"]}
        bad = {"policy_kind": "OVERTIME_POLICY", "policy_id": unpublished["id"]}

        r = await client.post(
            "/v1/policy-assignments/batch", headers=headers, json=batch(good, bad)
        )
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "POLICY_NOT_PUBLISHED"
        assert r.json()["error"]["details"][0]["context"]["policy_kind"] == "OVERTIME_POLICY"
        listed = await client.get("/v1/policy-assignments", headers=headers)
        assert listed.json()["data"] == []

        r = await client.post("/v1/policy-assignments/batch", headers=headers, json=batch(good))
        assert r.status_code == 201, r.text
        version = r.json()["data"][0]["version"]

        # replacing needs the open row's version
        r = await client.post(
            "/v1/policy-assignments/batch", headers=headers, json=batch(good, eff="2027-02-01")
        )
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "POLICY_ASSIGNMENT_VERSION_REQUIRED"
        r = await client.post(
            "/v1/policy-assignments/batch",
            headers=headers,
            json=batch({**good, "expected_version": version}, eff="2027-02-01"),
        )
        assert r.status_code == 201, r.text

        # calendars go through the impact preview
        r = await client.post(
            "/v1/policy-assignments/batch",
            headers=headers,
            json=batch({"policy_kind": "WORK_CALENDAR", "policy_id": str(uuid4())}),
        )
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "POLICY_BATCH_KIND_NOT_ALLOWED"

        r = await client.post(
            "/v1/policy-assignments/batch",
            headers=headers,
            json={"scope_type": "COMPANY", "effective_from": "2027-03-01", "changes": []},
        )
        assert r.status_code == 422, r.text
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


def _setup_body(name: str = "One step", **extra: Any) -> dict:
    return {
        "name": name,
        "rules": {
            "effective_from": "2026-01-01",
            "grace_in_minutes": 10,
            "hour_bands": [{"min_minutes": 0, "max_minutes": None, "result_status": "PRESENT"}],
        },
        **extra,
    }


async def test_policy_setup_creates_publishes_and_assigns_in_one_call(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        r = await client.post(
            "/v1/attendance-policies/setup",
            headers=headers,
            json=_setup_body(publish=True, assign={"scope_type": "COMPANY"}),
        )
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        assert data["version"]["status"] == "PUBLISHED"
        assert data["version"]["grace_in_minutes"] == 10

        listed = (await client.get("/v1/attendance-policies", headers=headers)).json()["data"]
        assert listed[0]["live_from"] == "2026-01-01"
        assert listed[0]["has_draft"] is False
        assert listed[0]["assigned_company_wide"] is True
        assert listed[0]["assigned_group_count"] == 0

        coverage = await client.get(
            "/v1/policy-assignments/coverage",
            headers=headers,
            params={"scope_type": "COMPANY", "as_of": "2026-06-01"},
        )
        row = next(
            x for x in coverage.json()["data"]["rows"] if x["policy_kind"] == "ATTENDANCE_POLICY"
        )
        assert row["applied"]["policy_id"] == data["policy"]["id"]

        # a draft stays unpublished and unassigned
        r = await client.post(
            "/v1/attendance-policies/setup", headers=headers, json=_setup_body("Later")
        )
        assert r.status_code == 201, r.text
        assert r.json()["data"]["version"]["status"] == "DRAFT"
        listed = (await client.get("/v1/attendance-policies", headers=headers)).json()["data"]
        later = next(p for p in listed if p["name"] == "Later")
        assert later["has_draft"] is True and later["live_from"] is None

        # assigning needs publishing
        r = await client.post(
            "/v1/attendance-policies/setup",
            headers=headers,
            json=_setup_body("Bad", assign={"scope_type": "COMPANY"}),
        )
        assert r.status_code == 422, r.text
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_policy_setup_leaves_nothing_behind_when_a_step_fails(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        before = (await client.get("/v1/attendance-policies", headers=headers)).json()["data"]

        # publish fails: no hour bands
        body = _setup_body(publish=True)
        body["rules"]["hour_bands"] = []
        r = await client.post("/v1/attendance-policies/setup", headers=headers, json=body)
        assert r.status_code == 422, r.text

        # assign fails: the company already has an open assignment and no version was sent
        first = await client.post(
            "/v1/attendance-policies/setup",
            headers=headers,
            json=_setup_body("First", publish=True, assign={"scope_type": "COMPANY"}),
        )
        assert first.status_code == 201, first.text
        body = _setup_body("Second", publish=True, assign={"scope_type": "COMPANY"})
        body["rules"]["effective_from"] = "2026-03-01"
        r = await client.post("/v1/attendance-policies/setup", headers=headers, json=body)
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "POLICY_ASSIGNMENT_VERSION_REQUIRED"

        names = [
            p["name"]
            for p in (await client.get("/v1/attendance-policies", headers=headers)).json()["data"]
        ]
        assert names == [p["name"] for p in before] + ["First"]
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_form_context_reports_shift_types_in_use(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        r = await client.get("/v1/attendance-policies/form-context", headers=headers)
        assert r.status_code == 200, r.text
        assert isinstance(r.json()["data"]["shift_types_in_use"], list)
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_overtime_and_regularization_setup_in_one_call(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        overtime = await client.post(
            "/v1/overtime-policies/setup",
            headers=headers,
            json={
                "name": "OT standard",
                "rules": {"effective_from": "2026-01-01", "min_ot_minutes": 30},
                "publish": True,
                "assign": {"scope_type": "COMPANY"},
            },
        )
        assert overtime.status_code == 201, overtime.text
        assert overtime.json()["data"]["version"]["status"] == "PUBLISHED"
        assert overtime.json()["data"]["version"]["min_ot_minutes"] == 30

        regularization = await client.post(
            "/v1/regularization-policies/setup",
            headers=headers,
            json={
                "name": "Corrections",
                "rules": {
                    "effective_from": "2026-01-01",
                    "allowed_types": [{"regularization_type": "MISSING_PUNCH"}],
                },
                "publish": True,
                "assign": {"scope_type": "COMPANY"},
            },
        )
        assert regularization.status_code == 201, regularization.text

        for path, kind, name in (
            ("overtime-policies", "OVERTIME_POLICY", "OT standard"),
            ("regularization-policies", "REGULARIZATION_POLICY", "Corrections"),
        ):
            listed = (await client.get(f"/v1/{path}", headers=headers)).json()["data"]
            assert listed[0]["name"] == name
            assert listed[0]["live_from"] == "2026-01-01"
            assert listed[0]["assigned_company_wide"] is True
            assert listed[0]["has_draft"] is False
            coverage = await client.get(
                "/v1/policy-assignments/coverage",
                headers=headers,
                params={"scope_type": "COMPANY", "as_of": "2026-06-01"},
            )
            row = next(x for x in coverage.json()["data"]["rows"] if x["policy_kind"] == kind)
            assert row["applied"]["policy_name"] == name

        # failures leave nothing behind, and assigning needs publishing
        bad = await client.post(
            "/v1/overtime-policies/setup",
            headers=headers,
            json={"name": "Nope", "rules": {}, "assign": {"scope_type": "COMPANY"}},
        )
        assert bad.status_code == 422, bad.text
        clash = await client.post(
            "/v1/regularization-policies/setup",
            headers=headers,
            json={
                "name": "Second",
                "rules": {"effective_from": "2026-03-01"},
                "publish": True,
                "assign": {"scope_type": "COMPANY"},
            },
        )
        assert clash.status_code == 422, clash.text
        assert clash.json()["error"]["code"] == "POLICY_ASSIGNMENT_VERSION_REQUIRED"
        names = [
            p["name"]
            for p in (await client.get("/v1/regularization-policies", headers=headers)).json()[
                "data"
            ]
        ]
        assert names == ["Corrections"]
        drafts = (await client.get("/v1/overtime-policies", headers=headers)).json()["data"]
        assert [p["name"] for p in drafts] == ["OT standard"]
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)
