"""`GET /v1/employees/{employee_id}/direct-reports` — authorization, tenant isolation, pagination.

The endpoint is gated by `EMPLOYEE.VIEW` and narrowed by the caller's data scope. What these tests
pin down:

* the manager must be visible to the caller (or be the caller — "my team"); anything else is the
  same 404 a nonexistent or cross-tenant id gets, so ids cannot be probed;
* rows are intersected with the caller's visible set, and `total` counts only those rows, so
  neither a page nor a count reveals people the caller cannot see;
* pagination happens after authorization, never around it.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from .test_employee_assignment import _cleanup_scoped_users, _create_permission_scoped_user
from .test_reporting_manager_lifecycle import (
    _hire,
    _raw,
    _register_tenant,
    _setup_org_structure,
    _teardown,
    _terminate,
)

pytestmark = pytest.mark.asyncio

EMPLOYEE_VIEW = "EMPLOYEE.VIEW"
EMPLOYEE_CREATE = "EMPLOYEE.CREATE"  # a real permission that must NOT open this endpoint

#: Exactly the fields of `DirectReportRead`. A new field has to be added here on purpose — in
#: particular nothing from `EmployeeRead`'s personal data may creep in unnoticed.
EXPECTED_KEYS = {
    "employee_id",
    "employee_code",
    "first_name",
    "middle_name",
    "last_name",
    "display_name",
    "status",
    "is_active",
    "branch_id",
    "department_id",
    "designation_id",
    "reporting_since",
    "employment_joining_date",
    "employment_last_working_day",
}


async def _team(client: AsyncClient, headers: dict[str, str], company_id: UUID) -> dict[str, Any]:
    """        Mgr
              /  |  \\    \\
            R1  R2  R3  SubMgr          Other (reports to no one)
                              \\
                            SubReport
    """
    # A fresh tenant's plan allows five employees; this team is larger. The per-company override
    # (not the shared plan catalogue) is the sanctioned knob for that.
    await _raw(
        company_id,
        "UPDATE subscription SET seat_limit_override = 50 WHERE company_id = :c",
        c=str(company_id),
    )
    org = await _setup_org_structure(client, headers)
    mgr = await _hire(client, headers, org, "Mgr")
    reports = [await _hire(client, headers, org, f"R{n}", manager_id=mgr["id"]) for n in (1, 2, 3)]
    sub_mgr = await _hire(client, headers, org, "SubMgr", manager_id=mgr["id"])
    sub_report = await _hire(client, headers, org, "SubReport", manager_id=sub_mgr["id"])
    other = await _hire(client, headers, org, "Other")
    return {
        "org": org,
        "mgr": mgr,
        "reports": reports,
        "sub_mgr": sub_mgr,
        "sub_report": sub_report,
        "other": other,
    }


def _ids(response: Any) -> set[str]:
    return {row["employee_id"] for row in response.json()["data"]}


async def _get(client: AsyncClient, headers: dict[str, str], manager_id: str, **params: Any) -> Any:
    return await client.get(
        f"/v1/employees/{manager_id}/direct-reports", headers=headers, params=params
    )


async def _scoped(
    company_id: UUID, person: dict[str, Any] | None, scope: str, code: str = EMPLOYEE_VIEW
) -> dict[str, str]:
    headers, _user_id = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[code],
        data_scope=scope,
        caller_employee_id=UUID(person["id"]) if person is not None else None,
    )
    return headers


async def _deactivate(client: AsyncClient, headers: dict[str, str], employee_id: str) -> None:
    live = await client.get(f"/v1/employees/{employee_id}", headers=headers)
    assert live.status_code == 200, live.text
    response = await client.delete(
        f"/v1/employees/{employee_id}",
        headers={**headers, "If-Match": str(live.json()["data"]["version"])},
    )
    assert response.status_code == 200, response.text


# --- Company scope (HR / admin) --------------------------------------------------------------


async def test_company_scope_lists_exactly_the_direct_reports(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)

        response = await _get(client, headers, team["mgr"]["id"])

        assert response.status_code == 200, response.text
        expected = {r["id"] for r in team["reports"]} | {team["sub_mgr"]["id"]}
        assert _ids(response) == expected  # direct only: not SubReport, not Other
        assert response.json()["pagination"]["total"] == 4
        row = response.json()["data"][0]
        assert set(row) == EXPECTED_KEYS
        assert row["reporting_since"] == "2027-01-01"
        assert row["is_active"] is True
        assert row["employment_joining_date"] == "2027-01-01"
        assert row["branch_id"] == team["org"]["branch"]["id"]
        assert row["department_id"] == team["org"]["department"]["id"]
        assert row["designation_id"] == team["org"]["designation"]["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_response_carries_no_personal_data(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        response = await _get(client, headers, team["mgr"]["id"])
        leaked = {
            "date_of_birth",
            "gender",
            "blood_group",
            "personal_email",
            "personal_mobile",
            "present_address_line1",
            "permanent_address_line1",
            "emergency_contact_phone",
            "photo_url",
            "custom_fields",
            "company_id",
        }
        for row in response.json()["data"]:
            assert not leaked & set(row)
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_manager_with_no_reports_returns_an_empty_page(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)

        response = await _get(client, headers, team["other"]["id"])

        assert response.status_code == 200, response.text
        assert response.json()["data"] == []
        meta = response.json()["pagination"]
        assert (meta["page"], meta["total"], meta["total_pages"]) == (1, 0, 0)
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_unknown_manager_is_404_and_malformed_id_is_422(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        missing = await _get(client, headers, "00000000-0000-4000-8000-000000000000")
        malformed = await _get(client, headers, "not-a-uuid")

        assert missing.status_code == 404, missing.text
        assert malformed.status_code == 422, malformed.text
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Pagination ------------------------------------------------------------------------------


async def test_pages_partition_the_full_set_without_gaps_or_repeats(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        full = _ids(await _get(client, headers, team["mgr"]["id"]))
        assert len(full) == 4

        seen: list[str] = []
        for page in (1, 2, 3):
            response = await _get(client, headers, team["mgr"]["id"], page=page, per_page=2)
            assert response.status_code == 200, response.text
            meta = response.json()["pagination"]
            assert (meta["total"], meta["total_pages"], meta["per_page"]) == (4, 2, 2)
            seen.extend(row["employee_id"] for row in response.json()["data"])

        assert len(seen) == len(set(seen)) == 4  # page 3 is past the end: empty
        assert set(seen) == full
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"per_page": 0},
        {"per_page": 100000},
        {"page": "x"},
        {"include_inactive": "maybe"},
    ],
)
async def test_invalid_paging_parameters_are_rejected_not_clamped(
    client: AsyncClient, seeded_plan_catalogue: None, params: dict[str, Any]
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        response = await _get(client, headers, team["mgr"]["id"], **params)
        assert response.status_code == 422, response.text
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Data scope: managers and ordinary employees ---------------------------------------------


async def test_reportees_manager_sees_own_team_but_not_the_reports_of_those_reports(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        mgr_headers = await _scoped(company_id, team["mgr"], "REPORTEES")

        own = await _get(client, mgr_headers, team["mgr"]["id"])
        assert own.status_code == 200, own.text
        assert _ids(own) == {r["id"] for r in team["reports"]} | {team["sub_mgr"]["id"]}

        # SubMgr is Mgr's own report, so visible — but SubReport is two levels down, not visible
        # to a REPORTEES caller: empty page, and the count must not betray that one exists.
        below = await _get(client, mgr_headers, team["sub_mgr"]["id"])
        assert below.status_code == 200, below.text
        assert below.json()["data"] == []
        assert below.json()["pagination"]["total"] == 0
        # ...while an unrestricted caller does see SubReport under SubMgr.
        admin_view = await _get(client, headers, team["sub_mgr"]["id"])
        assert _ids(admin_view) == {team["sub_report"]["id"]}
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_reportee_tree_manager_can_walk_down_but_only_one_level_at_a_time(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        mgr_headers = await _scoped(company_id, team["mgr"], "REPORTEE_TREE")

        own = await _get(client, mgr_headers, team["mgr"]["id"])
        down = await _get(client, mgr_headers, team["sub_mgr"]["id"])

        assert team["sub_report"]["id"] not in _ids(own)  # direct reports only, not the tree
        assert _ids(down) == {team["sub_report"]["id"]}
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_manager_cannot_read_an_unrelated_managers_team(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """IDOR: swapping the path id for someone outside the caller's scope is a plain 404 — the same
    answer as an id that does not exist."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        rival = await _hire(client, headers, team["org"], "Rival")
        await _hire(client, headers, team["org"], "RivalReport", manager_id=rival["id"])
        mgr_headers = await _scoped(company_id, team["mgr"], "REPORTEE_TREE")

        response = await _get(client, mgr_headers, rival["id"])
        nonexistent = await _get(client, mgr_headers, "00000000-0000-4000-8000-000000000000")

        assert response.status_code == 404, response.text
        # Indistinguishable from an id that does not exist at all (request ids aside).
        assert nonexistent.status_code == 404
        out_of_scope = {**response.json()["error"], "request_id": None}
        missing = {**nonexistent.json()["error"], "request_id": None}
        assert out_of_scope == missing
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_ordinary_employee_cannot_enumerate_anyones_team(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        report = team["reports"][0]
        employee_headers = await _scoped(company_id, report, "SELF")

        their_manager = await _get(client, employee_headers, team["mgr"]["id"])
        a_colleague = await _get(client, employee_headers, team["reports"][1]["id"])
        someone_else = await _get(client, employee_headers, team["other"]["id"])
        own = await _get(client, employee_headers, report["id"])

        assert their_manager.status_code == 404, their_manager.text  # cannot list their boss's team
        assert a_colleague.status_code == 404, a_colleague.text
        assert someone_else.status_code == 404, someone_else.text
        assert own.status_code == 200, own.text  # their own (empty) team is fine
        assert own.json()["data"] == []
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_a_caller_without_an_employee_record_and_scoped_access_sees_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Fails closed: no `employee_id` in the token plus a non-company scope resolves to an empty
    visible set, never to company-wide access."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        nobody = await _scoped(company_id, None, "REPORTEE_TREE")

        response = await _get(client, nobody, team["mgr"]["id"])

        assert response.status_code == 404, response.text
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_pagination_cannot_be_used_to_reach_rows_outside_the_callers_scope(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        mgr_headers = await _scoped(company_id, team["mgr"], "REPORTEES")

        for page, per_page in ((1, 1), (2, 1), (1, 100), (50, 100)):
            response = await _get(
                client, mgr_headers, team["sub_mgr"]["id"], page=page, per_page=per_page
            )
            assert response.status_code == 200, response.text
            assert response.json()["data"] == []
            assert response.json()["pagination"]["total"] == 0
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# --- Permission ------------------------------------------------------------------------------


async def test_missing_permission_is_403_and_missing_token_is_401(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        wrong_permission = await _scoped(company_id, team["mgr"], "COMPANY", code=EMPLOYEE_CREATE)

        forbidden = await _get(client, wrong_permission, team["mgr"]["id"])
        anonymous = await client.get(f"/v1/employees/{team['mgr']['id']}/direct-reports")

        assert forbidden.status_code == 403, forbidden.text
        assert anonymous.status_code == 401, anonymous.text
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# --- Tenant isolation ------------------------------------------------------------------------


async def test_other_tenants_ids_are_invisible_in_both_directions(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        team_a = await _team(client, headers_a, company_a)
        team_b = await _team(client, headers_b, company_b)

        a_asks_for_b = await _get(client, headers_a, team_b["mgr"]["id"])
        b_asks_for_a = await _get(client, headers_b, team_a["mgr"]["id"])

        assert a_asks_for_b.status_code == 404, a_asks_for_b.text
        assert b_asks_for_a.status_code == 404, b_asks_for_a.text
        # Each tenant still sees its own team, and none of the other's.
        own_a = await _get(client, headers_a, team_a["mgr"]["id"])
        assert _ids(own_a).isdisjoint(_ids(await _get(client, headers_b, team_b["mgr"]["id"])))
        assert own_a.json()["pagination"]["total"] == 4
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


async def test_a_token_for_one_tenant_cannot_be_pointed_at_another_with_the_header(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        team_b = await _team(client, headers_b, company_b)
        spoofed = {**headers_a, "X-Company-Id": str(company_b)}

        response = await _get(client, spoofed, team_b["mgr"]["id"])

        assert response.status_code in (401, 403, 404), response.text
        assert team_b["reports"][0]["id"] not in response.text
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


# --- Deleted / inactive / departed -----------------------------------------------------------


async def test_deactivated_and_deleted_reports_are_hidden_unless_inactive_is_requested(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        r1, r2, r3 = (r["id"] for r in team["reports"])
        await _deactivate(client, headers, r2)
        await _raw(company_id, "UPDATE employee SET deleted_at = now() WHERE id = :id", id=r3)

        default = await _get(client, headers, team["mgr"]["id"])
        with_inactive = await _get(client, headers, team["mgr"]["id"], include_inactive=True)

        assert _ids(default) == {r1, team["sub_mgr"]["id"]}
        assert default.json()["pagination"]["total"] == 2
        # Deactivated people come back (flagged); soft-deleted ones never do.
        assert _ids(with_inactive) == {r1, r2, team["sub_mgr"]["id"]}
        flagged = {row["employee_id"]: row["is_active"] for row in with_inactive.json()["data"]}
        assert flagged[r2] is False and flagged[r1] is True
        assert with_inactive.json()["pagination"]["total"] == 3
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_a_terminated_report_no_longer_appears(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Termination closes the employee's open assignment (`effective_to = last_working_day`), and
    "direct report" means a *current* (open) assignment — the same definition the `REPORTEES` data
    scope uses, so this list and the manager's visibility never disagree."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        leaver = team["reports"][0]
        await _terminate(client, headers, leaver, last_working_day="2027-02-15")

        response = await _get(client, headers, team["mgr"]["id"], include_inactive=True)

        assert leaver["id"] not in _ids(response)
        assert response.json()["pagination"]["total"] == 3
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_a_departed_manager_can_still_be_queried_to_find_orphaned_reports(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        await _terminate(client, headers, team["mgr"], last_working_day="2027-02-15")

        response = await _get(client, headers, team["mgr"]["id"])

        assert response.status_code == 200, response.text
        assert response.json()["pagination"]["total"] == 4
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_changing_or_removing_a_manager_moves_the_report_between_lists(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        team = await _team(client, headers, company_id)
        mover = team["reports"][0]
        live = await client.get(f"/v1/employees/{mover['id']}/assignments", headers=headers)
        version = [a for a in live.json()["data"] if a["effective_to"] is None][0]["version"]

        moved = await client.post(
            f"/v1/employees/{mover['id']}/assignments",
            headers={**headers, "If-Match": str(version)},
            json={
                "effective_from": "2027-03-01",
                "change_type": "MANAGER_CHANGE",
                "reporting_manager_id": team["other"]["id"],
            },
        )
        assert moved.status_code == 201, moved.text

        old = await _get(client, headers, team["mgr"]["id"])
        new = await _get(client, headers, team["other"]["id"])
        assert mover["id"] not in _ids(old)
        assert _ids(new) == {mover["id"]}
        assert new.json()["data"][0]["reporting_since"] == "2027-03-01"

        current = [
            a
            for a in (
                await client.get(f"/v1/employees/{mover['id']}/assignments", headers=headers)
            ).json()["data"]
            if a["effective_to"] is None
        ][0]
        removed = await client.post(
            f"/v1/employees/{mover['id']}/assignments",
            headers={**headers, "If-Match": str(current["version"])},
            json={
                "effective_from": "2027-05-01",
                "change_type": "MANAGER_CHANGE",
                "clear_reporting_manager": True,
            },
        )
        assert removed.status_code == 201, removed.text
        assert (await _get(client, headers, team["other"]["id"])).json()["data"] == []
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
