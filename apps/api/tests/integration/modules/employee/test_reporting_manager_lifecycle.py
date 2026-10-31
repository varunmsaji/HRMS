"""Reporting-manager lifecycle on `POST /v1/employees/{id}/assignments`.

Covers what the base assignment suite does not: explicit removal of a manager
(`clear_reporting_manager`), eligibility of a *chosen* manager against the employment lifecycle
(deactivated / deleted / terminated / not employed on the effective date), the effective-dated
history that removal and change leave behind, `If-Match` optimistic locking on those writes, and the
company-wide `reporting-hierarchy` advisory lock that stops two concurrent opposite links from
committing a reporting ring.
"""

import asyncio
from collections.abc import Awaitable
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.audit.models import AuditLog
from hrms.core.db.session import get_session_factory, session_scope, set_rls_company_id
from hrms.modules.employee.exceptions import InvalidReportingManagerError
from hrms.modules.employee.schemas import AssignmentCreate
from hrms.modules.employee.service import EmployeeAssignmentService

from .test_employee_assignment import (
    _create_assignment,
    _create_employee,
    _create_employment,
    _register_tenant,
    _setup_org_structure,
    _teardown,
)

pytestmark = pytest.mark.asyncio

JOINED = "2027-01-01"
FIRST_CHANGE = "2027-03-01"
SECOND_CHANGE = "2027-05-01"


# --- Helpers ---------------------------------------------------------------------------------


async def _hire(
    client: AsyncClient,
    headers: dict[str, str],
    org: dict[str, Any],
    name: str,
    *,
    manager_id: str | None = None,
    joining_date: str = JOINED,
) -> dict[str, Any]:
    """A working employee: employee record + employment episode + first assignment."""
    employee = await _create_employee(client, headers, first_name=name)
    employment = await _create_employment(
        client,
        headers,
        employee_id=employee["id"],
        legal_entity_id=org["legal_entity"]["id"],
        joining_date=joining_date,
    )
    body: dict[str, Any] = {
        "effective_from": joining_date,
        "change_type": "INITIAL",
        "branch_id": org["branch"]["id"],
        "department_id": org["department"]["id"],
        "designation_id": org["designation"]["id"],
    }
    if manager_id is not None:
        body["reporting_manager_id"] = manager_id
    assignment = await _create_assignment(client, headers, employee_id=employee["id"], **body)
    return {"id": employee["id"], "employee": employee, "employment": employment, "row": assignment}


async def _assignments(
    client: AsyncClient, headers: dict[str, str], employee_id: str, **params: str
) -> list[dict[str, Any]]:
    response = await client.get(
        f"/v1/employees/{employee_id}/assignments", headers=headers, params=params
    )
    assert response.status_code == 200, response.text
    return list(response.json()["data"])


async def _current(
    client: AsyncClient, headers: dict[str, str], employee_id: str
) -> dict[str, Any]:
    open_rows = [
        row
        for row in await _assignments(client, headers, employee_id)
        if row["effective_to"] is None
    ]
    assert len(open_rows) == 1
    return open_rows[0]


async def _manager_of(client: AsyncClient, headers: dict[str, str], employee_id: str) -> str | None:
    manager_id = (await _current(client, headers, employee_id))["reporting_manager_id"]
    return None if manager_id is None else str(manager_id)


async def _post_assignment(
    client: AsyncClient,
    headers: dict[str, str],
    employee_id: str,
    body: dict[str, Any],
    *,
    if_match: str | int | None = "current",
):
    """POSTs an assignment; `if_match="current"` looks up the open row's version first."""
    request_headers = dict(headers)
    if if_match == "current":
        if_match = (await _current(client, headers, employee_id))["version"]
    if if_match is not None:
        request_headers["If-Match"] = str(if_match)
    return await client.post(
        f"/v1/employees/{employee_id}/assignments", headers=request_headers, json=body
    )


def _set_manager_body(manager_id: str, effective_from: str = FIRST_CHANGE) -> dict[str, Any]:
    return {
        "effective_from": effective_from,
        "change_type": "MANAGER_CHANGE",
        "reporting_manager_id": manager_id,
    }


def _clear_body(effective_from: str = FIRST_CHANGE) -> dict[str, Any]:
    return {
        "effective_from": effective_from,
        "change_type": "MANAGER_CHANGE",
        "clear_reporting_manager": True,
    }


def _error_message(response: Any) -> str:
    return str(response.json()["error"]["details"][0]["message"])


async def _terminate(
    client: AsyncClient, headers: dict[str, str], person: dict[str, Any], last_working_day: str
) -> None:
    response = await client.post(
        f"/v1/employees/{person['id']}/employments/{person['employment']['id']}/terminate",
        headers={**headers, "If-Match": str(person["employment"]["version"])},
        json={"last_working_day": last_working_day},
    )
    assert response.status_code == 200, response.text


async def _raw(company_id: UUID, sql: str, **params: Any) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(text(sql), params)
        await session.commit()


# --- Eligibility of a chosen manager ---------------------------------------------------------


async def test_assign_active_eligible_manager(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        manager = await _hire(client, headers, org, "Manager")
        report = await _hire(client, headers, org, "Report")

        response = await _post_assignment(
            client, headers, report["id"], _set_manager_body(manager["id"])
        )

        assert response.status_code == 201, response.text
        assert response.json()["data"]["reporting_manager_id"] == manager["id"]
        assert await _manager_of(client, headers, report["id"]) == manager["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_reject_self_as_manager(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        person = await _hire(client, headers, org, "Solo")

        response = await _post_assignment(
            client, headers, person["id"], _set_manager_body(person["id"])
        )

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
        assert "themselves" in _error_message(response)
        assert await _manager_of(client, headers, person["id"]) is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_reject_deleted_manager(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        manager = await _hire(client, headers, org, "Gone")
        report = await _hire(client, headers, org, "Report")
        await _raw(
            company_id, "UPDATE employee SET deleted_at = now() WHERE id = :id", id=manager["id"]
        )

        response = await _post_assignment(
            client, headers, report["id"], _set_manager_body(manager["id"])
        )

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
        assert "valid employee" in _error_message(response)
        assert await _manager_of(client, headers, report["id"]) is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_reject_deactivated_manager(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        manager = await _hire(client, headers, org, "Dormant")
        report = await _hire(client, headers, org, "Report")
        # Hiring moves the employee through PRE_JOINING -> PROBATION, so read the live version.
        live = await client.get(f"/v1/employees/{manager['id']}", headers=headers)
        assert live.status_code == 200, live.text
        deactivated = await client.delete(
            f"/v1/employees/{manager['id']}",
            headers={**headers, "If-Match": str(live.json()["data"]["version"])},
        )
        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["data"]["is_active"] is False

        response = await _post_assignment(
            client, headers, report["id"], _set_manager_body(manager["id"])
        )

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
        assert "deactivated" in _error_message(response)
        assert await _manager_of(client, headers, report["id"]) is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_reject_terminated_manager_including_during_notice(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Termination flips the episode to TERMINATED but it still *covers* dates up to the last
    working day, so a manager serving notice would pass a date-only check. They are refused."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        manager = await _hire(client, headers, org, "Leaver")
        report = await _hire(client, headers, org, "Report")
        await _terminate(client, headers, manager, last_working_day="2027-06-30")

        response = await _post_assignment(
            client, headers, report["id"], _set_manager_body(manager["id"], FIRST_CHANGE)
        )

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
        assert "employment has ended" in _error_message(response)
        assert await _manager_of(client, headers, report["id"]) is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_reject_manager_with_no_employment_on_the_effective_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        report = await _hire(client, headers, org, "Report")
        # Joins after the date the link would take effect.
        late_joiner = await _hire(client, headers, org, "Late", joining_date="2027-09-01")
        # A bare record that was never hired at all.
        never_hired = await _create_employee(client, headers, first_name="Never")

        for candidate_id in (late_joiner["id"], never_hired["id"]):
            response = await _post_assignment(
                client, headers, report["id"], _set_manager_body(candidate_id, FIRST_CHANGE)
            )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
            assert "no employment covering" in _error_message(response)
        assert await _manager_of(client, headers, report["id"]) is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_reject_cross_company_manager(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        org_a = await _setup_org_structure(client, headers_a)
        org_b = await _setup_org_structure(client, headers_b)
        report = await _hire(client, headers_a, org_a, "Report")
        outsider = await _hire(client, headers_b, org_b, "Outsider")

        response = await _post_assignment(
            client, headers_a, report["id"], _set_manager_body(outsider["id"])
        )

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
        assert await _manager_of(client, headers_a, report["id"]) is None
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


# --- Explicit removal, carry-forward, history ------------------------------------------------


async def test_explicit_removal_clears_the_manager(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        manager = await _hire(client, headers, org, "Manager")
        report = await _hire(client, headers, org, "Report", manager_id=manager["id"])
        assert await _manager_of(client, headers, report["id"]) == manager["id"]

        response = await _post_assignment(client, headers, report["id"], _clear_body())

        assert response.status_code == 201, response.text
        assert response.json()["data"]["reporting_manager_id"] is None
        assert await _manager_of(client, headers, report["id"]) is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_clear_with_a_named_manager_is_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        manager = await _hire(client, headers, org, "Manager")
        report = await _hire(client, headers, org, "Report", manager_id=manager["id"])

        response = await _post_assignment(
            client,
            headers,
            report["id"],
            {**_set_manager_body(manager["id"]), "clear_reporting_manager": True},
        )

        assert response.status_code == 422, response.text
        assert await _manager_of(client, headers, report["id"]) == manager["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_omitted_and_null_manager_leave_the_existing_manager_unchanged(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`reporting_manager_id: null` is what the web form sends for a blank field; it must keep
    meaning "no change", never "remove"."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        manager = await _hire(client, headers, org, "Manager")
        report = await _hire(client, headers, org, "Report", manager_id=manager["id"])

        omitted = await _post_assignment(
            client,
            headers,
            report["id"],
            {"effective_from": FIRST_CHANGE, "change_type": "TRANSFER"},
        )
        assert omitted.status_code == 201, omitted.text
        assert omitted.json()["data"]["reporting_manager_id"] == manager["id"]

        explicit_null = await _post_assignment(
            client,
            headers,
            report["id"],
            {
                "effective_from": SECOND_CHANGE,
                "change_type": "TRANSFER",
                "reporting_manager_id": None,
                "clear_reporting_manager": False,
            },
        )
        assert explicit_null.status_code == 201, explicit_null.text
        assert explicit_null.json()["data"]["reporting_manager_id"] == manager["id"]
        assert await _manager_of(client, headers, report["id"]) == manager["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_manager_who_left_does_not_block_an_unrelated_change_to_their_report(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Eligibility applies to *choosing* a manager; it must not freeze the report's record once the
    manager they already have leaves."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        manager = await _hire(client, headers, org, "Leaver")
        report = await _hire(client, headers, org, "Report", manager_id=manager["id"])
        await _terminate(client, headers, manager, last_working_day="2027-02-15")

        response = await _post_assignment(
            client,
            headers,
            report["id"],
            {"effective_from": FIRST_CHANGE, "change_type": "TRANSFER"},
        )

        assert response.status_code == 201, response.text
        assert response.json()["data"]["reporting_manager_id"] == manager["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_clear_on_first_assignment_is_harmless(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        employee = await _create_employee(client, headers, first_name="Fresh")
        await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=org["legal_entity"]["id"],
            joining_date=JOINED,
        )

        response = await _post_assignment(
            client,
            headers,
            employee["id"],
            {
                "effective_from": JOINED,
                "change_type": "INITIAL",
                "branch_id": org["branch"]["id"],
                "department_id": org["department"]["id"],
                "designation_id": org["designation"]["id"],
                "clear_reporting_manager": True,
            },
            if_match=None,
        )

        assert response.status_code == 201, response.text
        assert response.json()["data"]["reporting_manager_id"] is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_assign_change_and_remove_preserve_effective_dated_history(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        first = await _hire(client, headers, org, "First")
        second = await _hire(client, headers, org, "Second")
        report = await _hire(client, headers, org, "Report", manager_id=first["id"])

        changed = await _post_assignment(
            client, headers, report["id"], _set_manager_body(second["id"], FIRST_CHANGE)
        )
        assert changed.status_code == 201, changed.text
        removed = await _post_assignment(client, headers, report["id"], _clear_body(SECOND_CHANGE))
        assert removed.status_code == 201, removed.text

        history = await _assignments(client, headers, report["id"])
        assert [(row["effective_from"], row["effective_to"]) for row in history] == [
            (JOINED, "2027-02-28"),
            (FIRST_CHANGE, "2027-04-30"),
            (SECOND_CHANGE, None),
        ]
        assert [row["reporting_manager_id"] for row in history] == [
            first["id"],
            second["id"],
            None,
        ]

        # As-of reads see the manager in force on that date, including "none".
        for as_of, expected in (
            ("2027-02-15", first["id"]),
            ("2027-04-01", second["id"]),
            ("2027-06-01", None),
        ):
            rows = await _assignments(client, headers, report["id"], as_of=as_of)
            assert [row["reporting_manager_id"] for row in rows] == [expected], as_of

        factory = get_session_factory()
        async with factory() as session:
            audit = (
                (
                    await session.execute(
                        select(AuditLog)
                        .where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "employee_assignment",
                            AuditLog.entity_id.in_([UUID(row["id"]) for row in history]),
                        )
                        .order_by(AuditLog.occurred_at)
                    )
                )
                .scalars()
                .all()
            )
        assert [row.action for row in audit] == ["ASSIGNMENT_CHANGED"] * 3
        assert audit[2].before_json["reporting_manager_id"] == second["id"]
        assert audit[2].after_json["reporting_manager_id"] is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Cycles ----------------------------------------------------------------------------------


async def test_reject_direct_reporting_loop(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        boss = await _hire(client, headers, org, "Boss")
        report = await _hire(client, headers, org, "Report", manager_id=boss["id"])

        response = await _post_assignment(
            client, headers, boss["id"], _set_manager_body(report["id"])
        )

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
        assert "reporting loop" in _error_message(response)
        assert await _manager_of(client, headers, boss["id"]) is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_reject_longer_reporting_ring(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        top = await _hire(client, headers, org, "Top")
        middle = await _hire(client, headers, org, "Middle", manager_id=top["id"])
        bottom = await _hire(client, headers, org, "Bottom", manager_id=middle["id"])

        # Top -> Bottom would close Top <- Middle <- Bottom <- Top.
        response = await _post_assignment(
            client, headers, top["id"], _set_manager_body(bottom["id"])
        )

        assert response.status_code == 422, response.text
        assert "reporting loop" in _error_message(response)
        assert await _manager_of(client, headers, top["id"]) is None

        # A non-looping extension of the same chain is still fine.
        ok = await _post_assignment(client, headers, bottom["id"], _set_manager_body(top["id"]))
        assert ok.status_code == 201, ok.text
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Optimistic locking ----------------------------------------------------------------------


async def test_stale_if_match_is_refused_for_set_and_for_removal(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        manager = await _hire(client, headers, org, "Manager")
        other = await _hire(client, headers, org, "Other")
        report = await _hire(client, headers, org, "Report", manager_id=manager["id"])
        stale_version = (await _current(client, headers, report["id"]))["version"]
        bump = await _post_assignment(
            client,
            headers,
            report["id"],
            {"effective_from": FIRST_CHANGE, "change_type": "TRANSFER"},
        )
        assert bump.status_code == 201, bump.text

        stale_set = await _post_assignment(
            client,
            headers,
            report["id"],
            _set_manager_body(other["id"], SECOND_CHANGE),
            if_match=stale_version,
        )
        stale_clear = await _post_assignment(
            client, headers, report["id"], _clear_body(SECOND_CHANGE), if_match=stale_version
        )

        for response in (stale_set, stale_clear):
            assert response.status_code == 409, response.text
            assert response.json()["error"]["code"] == "STALE_RESOURCE"
        assert await _manager_of(client, headers, report["id"]) == manager["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_missing_if_match_is_refused_when_a_current_assignment_exists(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        manager = await _hire(client, headers, org, "Manager")
        report = await _hire(client, headers, org, "Report", manager_id=manager["id"])

        response = await _post_assignment(
            client, headers, report["id"], _clear_body(), if_match=None
        )

        assert response.status_code in (400, 412, 422, 428), response.text
        assert await _manager_of(client, headers, report["id"]) == manager["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_two_writers_with_the_same_if_match_yield_exactly_one_winner(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Both writes name a manager, so both take the hierarchy lock; the version check must still
    pick exactly one winner."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        first = await _hire(client, headers, org, "First")
        second = await _hire(client, headers, org, "Second")
        report = await _hire(client, headers, org, "Report")
        version = (await _current(client, headers, report["id"]))["version"]

        responses = await asyncio.gather(
            _post_assignment(
                client, headers, report["id"], _set_manager_body(first["id"]), if_match=version
            ),
            _post_assignment(
                client, headers, report["id"], _set_manager_body(second["id"]), if_match=version
            ),
        )

        assert sorted(response.status_code for response in responses) == [201, 409]
        winner = next(r for r in responses if r.status_code == 201).json()["data"]
        assert await _manager_of(client, headers, report["id"]) == winner["reporting_manager_id"]
        assert len([r for r in await _assignments(client, headers, report["id"])]) == 2
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Concurrent ring attempts ----------------------------------------------------------------


async def _link(
    service: EmployeeAssignmentService,
    company_id: UUID,
    employee_id: str,
    manager_id: str,
    *,
    expected_version: int,
) -> None:
    await service.create_assignment(
        company_id,
        UUID(employee_id),
        AssignmentCreate(
            effective_from=date.fromisoformat(FIRST_CHANGE),
            change_type="MANAGER_CHANGE",
            reporting_manager_id=UUID(manager_id),
        ),
        expected_version=expected_version,
        actor_user_id=None,
    )


async def _reporting_edges(company_id: UUID) -> dict[UUID, UUID]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        rows = (
            await session.execute(
                text(
                    "SELECT employee_id, reporting_manager_id FROM employee_assignment "
                    "WHERE company_id = :c AND effective_to IS NULL "
                    "AND reporting_manager_id IS NOT NULL"
                ),
                {"c": str(company_id)},
            )
        ).all()
    return {employee: manager for employee, manager in rows}


def _has_ring(edges: dict[UUID, UUID]) -> bool:
    for start in edges:
        seen, node = {start}, edges.get(start)
        while node is not None:
            if node in seen:
                return True
            seen.add(node)
            node = edges.get(node)
    return False


@pytest.mark.parametrize(
    "lock_enabled",
    [
        True,
        pytest.param(
            False,
            marks=pytest.mark.xfail(
                strict=True,
                reason="control: with the hierarchy lock disabled the second link does not wait "
                "and the pair commits a ring — proves this test can detect the race",
            ),
        ),
    ],
)
async def test_concurrent_opposite_links_cannot_commit_a_ring(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    monkeypatch: pytest.MonkeyPatch,
    lock_enabled: bool,
) -> None:
    """Deterministic interleaving. Transaction 1 links A under B and stays open (uncommitted, lock
    held). Transaction 2 links B under A. Without serialisation transaction 2 reads the committed
    hierarchy (no A -> B link yet), passes its loop check and both commit a ring. With the lock it
    must wait for transaction 1, then see the link and be refused."""
    if not lock_enabled:

        async def _no_lock(*_args: Any, **_kwargs: Any) -> None:
            return None

        monkeypatch.setattr("hrms.modules.employee.service.lock_reporting_hierarchy", _no_lock)

    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        a = await _hire(client, headers, org, "A")
        b = await _hire(client, headers, org, "B")
        version_a = (await _current(client, headers, a["id"]))["version"]
        version_b = (await _current(client, headers, b["id"]))["version"]

        second_attempt: asyncio.Task[None] | None = None

        async def _second_transaction() -> None:
            async with session_scope(company_id=str(company_id)) as session:
                await _link(
                    EmployeeAssignmentService(session),
                    company_id,
                    b["id"],
                    a["id"],
                    expected_version=version_b,
                )

        async with session_scope(company_id=str(company_id)) as first_session:
            await _link(
                EmployeeAssignmentService(first_session),
                company_id,
                a["id"],
                b["id"],
                expected_version=version_a,
            )
            second_attempt = asyncio.create_task(_second_transaction())
            finished, _pending = await asyncio.wait({second_attempt}, timeout=1.5)
            assert not finished, "the opposite link did not wait for the in-flight one"
        # transaction 1 commits here, releasing the lock

        with pytest.raises(InvalidReportingManagerError, match="reporting loop"):
            await second_attempt

        edges = await _reporting_edges(company_id)
        assert edges == {UUID(a["id"]): UUID(b["id"])}
        assert not _has_ring(edges)
    finally:
        if second_attempt is not None and not second_attempt.done():
            second_attempt.cancel()
        await _teardown(company_id=company_id, user_id=user_id)


async def test_free_running_opposite_links_over_http_never_leave_a_ring(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        a = await _hire(client, headers, org, "A")
        b = await _hire(client, headers, org, "B")
        version_a = (await _current(client, headers, a["id"]))["version"]
        version_b = (await _current(client, headers, b["id"]))["version"]

        responses = await asyncio.gather(
            _post_assignment(
                client, headers, a["id"], _set_manager_body(b["id"]), if_match=version_a
            ),
            _post_assignment(
                client, headers, b["id"], _set_manager_body(a["id"]), if_match=version_b
            ),
        )

        assert sorted(response.status_code for response in responses) == [201, 422]
        loser = next(r for r in responses if r.status_code == 422)
        assert "reporting loop" in _error_message(loser)
        assert not _has_ring(await _reporting_edges(company_id))
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_hierarchy_lock_is_per_company(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A link held open in one company must not stall a link in another."""
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        org_a = await _setup_org_structure(client, headers_a)
        org_b = await _setup_org_structure(client, headers_b)
        a1 = await _hire(client, headers_a, org_a, "A1")
        a2 = await _hire(client, headers_a, org_a, "A2")
        b_manager = await _hire(client, headers_b, org_b, "BM")
        b_report = await _hire(client, headers_b, org_b, "BR")
        version_a1 = (await _current(client, headers_a, a1["id"]))["version"]

        async with session_scope(company_id=str(company_a)) as held:
            await _link(
                EmployeeAssignmentService(held),
                company_a,
                a1["id"],
                a2["id"],
                expected_version=version_a1,
            )
            other_company: Awaitable[Any] = _post_assignment(
                client, headers_b, b_report["id"], _set_manager_body(b_manager["id"])
            )
            response = await asyncio.wait_for(other_company, timeout=3.0)
            assert response.status_code == 201, response.text
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)
