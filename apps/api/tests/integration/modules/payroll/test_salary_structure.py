"""Integration tests for payroll Phase 5.1 — salary components, structures and employee salary
assignment (`docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md`, decisions D1–D6)."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

_CTC = 12_00_000_00  # ₹12,00,000 a year


async def _cleanup_payroll(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "employee_salary",
            "salary_structure_line",
            "salary_structure_version",
            "salary_structure",
            "salary_component",
            "employee_statutory",
            "employee_compensation",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


async def _setup_employee(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    ctc: int | None = _CTC,
    pf: bool = True,
) -> str:
    wired = await _build_wired_employee(client, headers)
    employee_id = str(wired["employee"]["id"])
    if ctc is not None:
        response = await client.post(
            f"/v1/employees/{employee_id}/compensation",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "annual_ctc_minor": ctc,
                "currency": "INR",
                "revision_type": "JOINING",
                "revision_reason": "Initial hire",
            },
        )
        assert response.status_code == 201, response.text
    response = await client.post(
        f"/v1/employees/{employee_id}/statutory",
        headers=headers,
        json={
            "effective_from": "2026-01-01",
            "is_pf_applicable": pf,
            "is_esi_applicable": False,
            "is_lwf_applicable": False,
            "tax_regime": "NEW",
            "revision_reason": "Initial statutory profile",
        },
    )
    assert response.status_code == 201, response.text
    return employee_id


async def _structures(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get("/v1/payroll/salary-structures", headers=headers)
    assert response.status_code == 200, response.text
    return {s["code"]: s for s in response.json()["data"]}


async def _components(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get("/v1/payroll/salary-components", headers=headers)
    assert response.status_code == 200, response.text
    return {c["code"]: c for c in response.json()["data"]}


def _amounts(breakup: dict[str, Any]) -> dict[str, int]:
    return {line["component_code"]: line["monthly_minor"] for line in breakup["lines"]}


async def test_defaults_are_seeded_once(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        components = await _components(client, headers)
        assert {"BASIC", "HRA", "SPECIAL_ALLOWANCE", "EMPLOYER_PF", "EMPLOYER_ESI"} <= set(
            components
        )
        assert all(c["is_system"] for c in components.values())

        structures = await _structures(client, headers)
        assert set(structures) == {"STANDARD", "STANDARD_METRO"}
        (version,) = structures["STANDARD"]["versions"]
        assert version["status"] == "PUBLISHED"
        lines = {line["component_code"]: line for line in version["lines"]}
        assert lines["BASIC"]["calculation_type"] == "PERCENTAGE_OF_GROSS"
        assert lines["HRA"]["percentage"] == "40"
        assert lines["SPECIAL_ALLOWANCE"]["calculation_type"] == "BALANCING"
        assert lines["EMPLOYER_PF"]["max_monthly_minor"] == 180_000
        metro = {
            line["component_code"]: line
            for line in structures["STANDARD_METRO"]["versions"][0]["lines"]
        }
        assert metro["HRA"]["percentage"] == "50"

        # Listing again seeds nothing new.
        assert len(await _structures(client, headers)) == 2
        assert len(await _components(client, headers)) == len(components)

        # A system component's type is fixed; its other fields are editable.
        basic = components["BASIC"]
        refused = await client.patch(
            f"/v1/payroll/salary-components/{basic['id']}",
            headers={**headers, "If-Match": str(basic["version"])},
            json={"component_type": "DEDUCTION"},
        )
        assert refused.status_code == 422, refused.text
        renamed = await client.patch(
            f"/v1/payroll/salary-components/{basic['id']}",
            headers={**headers, "If-Match": str(basic["version"])},
            json={"name": "Basic Salary"},
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["data"]["name"] == "Basic Salary"
    finally:
        await _cleanup_payroll(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_assign_structure_and_read_breakup(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _setup_employee(client, headers)
        standard = (await _structures(client, headers))["STANDARD"]

        assigned = await client.post(
            f"/v1/employees/{employee_id}/salary",
            headers=headers,
            json={
                "salary_structure_id": standard["id"],
                "effective_from": "2026-01-01",
                "reason": "Joining",
            },
        )
        assert assigned.status_code == 201, assigned.text

        breakup = await client.get(
            f"/v1/employees/{employee_id}/salary/breakup",
            headers=headers,
            params={"as_of": "2026-08-10"},
        )
        assert breakup.status_code == 200, breakup.text
        data = breakup.json()["data"]
        assert data["pay_basis"] == "MONTHLY"
        assert data["pf_applicable"] is True
        amounts = _amounts(data["breakup"])
        assert amounts["EMPLOYER_PF"] == 180_000
        assert amounts["BASIC"] == 4_910_000
        assert amounts["HRA"] == 1_964_000
        assert data["breakup"]["gross_monthly_minor"] == 9_820_000
        assert (
            data["breakup"]["gross_monthly_minor"]
            + data["breakup"]["employer_contributions_monthly_minor"]
            == 10_000_000
        )

        # Effective-dated: a later assignment closes this one; the same date is refused.
        same_day = await client.post(
            f"/v1/employees/{employee_id}/salary",
            headers=headers,
            json={
                "salary_structure_id": standard["id"],
                "effective_from": "2026-01-01",
                "reason": "Duplicate",
            },
        )
        assert same_day.status_code == 422, same_day.text
        assert same_day.json()["error"]["code"] == "EMPLOYEE_SALARY_INVALID"
        metro = (await _structures(client, headers))["STANDARD_METRO"]
        moved = await client.post(
            f"/v1/employees/{employee_id}/salary",
            headers=headers,
            json={
                "salary_structure_id": metro["id"],
                "effective_from": "2026-09-01",
                "reason": "Moved to a metro office",
            },
        )
        assert moved.status_code == 201, moved.text
        history = await client.get(f"/v1/employees/{employee_id}/salary", headers=headers)
        rows = history.json()["data"]
        assert [(r["effective_from"], r["effective_to"]) for r in rows] == [
            ("2026-01-01", "2026-08-31"),
            ("2026-09-01", None),
        ]
        september = await client.get(
            f"/v1/employees/{employee_id}/salary/breakup",
            headers=headers,
            params={"as_of": "2026-09-15"},
        )
        september_amounts = _amounts(september.json()["data"]["breakup"])
        assert september_amounts["HRA"] == september_amounts["BASIC"] // 2

        # A daily rate is refused for a monthly-paid employee.
        daily = await client.post(
            f"/v1/employees/{employee_id}/salary",
            headers=headers,
            json={"daily_rate_minor": 80_000, "effective_from": "2026-10-01", "reason": "x"},
        )
        assert daily.status_code == 422, daily.text
    finally:
        await _cleanup_payroll(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_assignment_requires_ctc_and_breakup_reports_why(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _setup_employee(client, headers, ctc=None)
        standard = (await _structures(client, headers))["STANDARD"]
        refused = await client.post(
            f"/v1/employees/{employee_id}/salary",
            headers=headers,
            json={
                "salary_structure_id": standard["id"],
                "effective_from": "2026-01-01",
                "reason": "Joining",
            },
        )
        assert refused.status_code == 422, refused.text
        assert "CTC" in refused.json()["error"]["message"]

        missing = await client.get(
            f"/v1/employees/{employee_id}/salary/breakup",
            headers=headers,
            params={"as_of": "2026-08-10"},
        )
        assert missing.status_code == 422, missing.text
        assert missing.json()["error"]["code"] == "SALARY_BREAKUP_UNAVAILABLE"
    finally:
        await _cleanup_payroll(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_structure_draft_publish_lifecycle(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        components = await _components(client, headers)
        basic, special = components["BASIC"]["id"], components["SPECIAL_ALLOWANCE"]["id"]

        invalid = await client.post(
            "/v1/payroll/salary-structures",
            headers=headers,
            json={
                "code": "BROKEN",
                "name": "Broken",
                "lines": [
                    {"salary_component_id": basic, "calculation_type": "FIXED",
                     "amount_monthly_minor": 1_000_000},
                ],
            },
        )  # fmt: skip
        assert invalid.status_code == 422, invalid.text
        assert invalid.json()["error"]["code"] == "SALARY_STRUCTURE_INVALID"

        lines = [
            {"salary_component_id": basic, "calculation_type": "PERCENTAGE_OF_CTC",
             "percentage": "40", "display_order": 10},
            {"salary_component_id": special, "calculation_type": "BALANCING",
             "display_order": 20},
        ]  # fmt: skip
        created = await client.post(
            "/v1/payroll/salary-structures",
            headers=headers,
            json={"code": "FLAT", "name": "Flat", "lines": lines},
        )
        assert created.status_code == 201, created.text
        structure = created.json()["data"]
        (draft,) = structure["versions"]
        assert draft["status"] == "DRAFT"

        preview = await client.post(
            f"/v1/payroll/salary-structures/{structure['id']}/versions/{draft['id']}/preview",
            headers=headers,
            json={"annual_ctc_minor": _CTC, "pf_applicable": True},
        )
        assert preview.status_code == 200, preview.text
        assert _amounts(preview.json()["data"]) == {
            "BASIC": 4_000_000,
            "SPECIAL_ALLOWANCE": 6_000_000,
        }

        publish_url = (
            f"/v1/payroll/salary-structures/{structure['id']}/versions/{draft['id']}/publish"
        )
        published = await client.post(
            publish_url,
            headers={**headers, "If-Match": str(draft["version"])},
            json={"effective_from": "2026-04-01"},
        )
        assert published.status_code == 200, published.text

        # A published version is immutable; changes go into a new draft copied from it.
        immutable = await client.put(
            f"/v1/payroll/salary-structures/{structure['id']}/versions/{draft['id']}/lines",
            headers={**headers, "If-Match": "2"},
            json={"lines": lines},
        )
        assert immutable.status_code == 409, immutable.text
        second = await client.post(
            f"/v1/payroll/salary-structures/{structure['id']}/versions",
            headers=headers,
            json={},
        )
        assert second.status_code == 201, second.text
        new_draft = next(v for v in second.json()["data"]["versions"] if v["status"] == "DRAFT")
        assert len(new_draft["lines"]) == 2
        duplicate = await client.post(
            f"/v1/payroll/salary-structures/{structure['id']}/versions",
            headers=headers,
            json={},
        )
        assert duplicate.status_code == 409, duplicate.text

        too_early = await client.post(
            f"/v1/payroll/salary-structures/{structure['id']}/versions/{new_draft['id']}/publish",
            headers={**headers, "If-Match": str(new_draft["version"])},
            json={"effective_from": "2026-04-01"},
        )
        assert too_early.status_code == 422, too_early.text
        republished = await client.post(
            f"/v1/payroll/salary-structures/{structure['id']}/versions/{new_draft['id']}/publish",
            headers={**headers, "If-Match": str(new_draft["version"])},
            json={"effective_from": "2026-10-01"},
        )
        assert republished.status_code == 200, republished.text
        versions = {v["version_number"]: v for v in republished.json()["data"]["versions"]}
        assert versions[1]["effective_to"] == "2026-09-30"
        assert versions[2]["effective_from"] == "2026-10-01"
    finally:
        await _cleanup_payroll(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_bulk_assign_skips_those_already_assigned(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _setup_employee(client, headers)
        standard = (await _structures(client, headers))["STANDARD"]
        body = {"salary_structure_id": standard["id"], "effective_from": "2026-04-01"}

        first = await client.post("/v1/payroll/salary-assignments/bulk", headers=headers, json=body)
        assert first.status_code == 200, first.text
        assert first.json()["data"]["assigned"] == [employee_id]

        second = await client.post(
            "/v1/payroll/salary-assignments/bulk", headers=headers, json=body
        )
        data = second.json()["data"]
        assert data["assigned"] == []
        assert data["skipped"] == [
            {"employee_id": employee_id, "reason": "Already has a salary assignment"}
        ]
    finally:
        await _cleanup_payroll(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_setup_requires_payroll_permission(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        scoped_headers, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=["EMPLOYEE.VIEW"], data_scope="COMPANY"
        )
        for path in ("/v1/payroll/salary-components", "/v1/payroll/salary-structures"):
            response = await client.get(path, headers=scoped_headers)
            assert response.status_code == 403, response.text
    finally:
        await _cleanup_payroll(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
