"""Integration tests for the employee Salary tab setup — CTC and structure edited together, a
template changed for one employee saved as that employee's own structure."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.employee.test_employee_compensation import _create_employee
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.payroll.test_salary_structure import (
    _CTC,
    _amounts,
    _cleanup_payroll,
    _setup_employee,
    _structures,
)

pytestmark = pytest.mark.asyncio


def _inputs(lines: list[dict[str, Any]], **changes: dict[str, Any]) -> list[dict[str, Any]]:
    """A structure version's lines as save/preview inputs, with per-component-code changes."""
    return [
        {
            "salary_component_id": line["salary_component_id"],
            "calculation_type": line["calculation_type"],
            "percentage": line["percentage"],
            "amount_monthly_minor": line["amount_monthly_minor"],
            "base_salary_component_id": line["base_salary_component_id"],
            "max_monthly_minor": line["max_monthly_minor"],
            "applies_when": line["applies_when"],
            "display_order": line["display_order"],
            **changes.get(line["component_code"], {}),
        }
        for line in lines
    ]


async def test_setup_assigns_template_or_employee_own_structure(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _setup_employee(client, headers)
        standard = (await _structures(client, headers))["STANDARD"]
        template_lines = standard["versions"][0]["lines"]

        empty = await client.get(
            f"/v1/employees/{employee_id}/salary/setup",
            headers=headers,
            params={"as_of": "2026-01-01"},
        )
        assert empty.status_code == 200, empty.text
        data = empty.json()["data"]
        assert data["annual_ctc_minor"] == _CTC
        assert data["pay_basis"] == "MONTHLY"
        assert data["assignment"] is None and data["lines"] == []

        # Live preview: Basic at 45% of gross (the template has 50%), nothing saved.
        forty_five = _inputs(template_lines, BASIC={"percentage": "45"})
        preview = await client.post(
            f"/v1/employees/{employee_id}/salary/setup/preview",
            headers=headers,
            json={"annual_ctc_minor": _CTC, "as_of": "2026-01-01", "lines": forty_five},
        )
        assert preview.status_code == 200, preview.text
        breakup = preview.json()["data"]["breakup"]
        amounts = _amounts(breakup)
        assert amounts["BASIC"] == round(breakup["gross_monthly_minor"] * 0.45 / 100) * 100
        assert amounts["HRA"] == round(amounts["BASIC"] * 0.4 / 100) * 100
        assert preview.json()["data"]["pf_applicable"] is True
        history = await client.get(f"/v1/employees/{employee_id}/salary", headers=headers)
        assert history.json()["data"] == []

        # Unchanged template lines → the template itself is assigned.
        saved = await client.post(
            f"/v1/employees/{employee_id}/salary/setup",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "reason": "Joining",
                "template_structure_id": standard["id"],
                "lines": _inputs(template_lines),
            },
        )
        assert saved.status_code == 200, saved.text
        data = saved.json()["data"]
        assert data["salary_structure_id"] == standard["id"]
        assert data["is_customised"] is False

        # Changed lines with a new CTC → a new compensation row and the employee's own structure.
        raised = 15_00_000_00
        saved = await client.post(
            f"/v1/employees/{employee_id}/salary/setup",
            headers=headers,
            json={
                "effective_from": "2026-04-01",
                "reason": "Annual review",
                "template_structure_id": standard["id"],
                "lines": forty_five,
                "annual_ctc_minor": raised,
                "revision_type": "ANNUAL",
            },
        )
        assert saved.status_code == 200, saved.text
        data = saved.json()["data"]
        assert data["is_customised"] is True
        assert data["template_structure_id"] == standard["id"]
        assert data["annual_ctc_minor"] == raised
        own_id = data["salary_structure_id"]
        assert own_id != standard["id"]
        lines = {line["component_code"]: line for line in data["lines"]}
        assert lines["BASIC"]["percentage"] == "45"

        compensation = await client.get(
            f"/v1/employees/{employee_id}/compensation", headers=headers
        )
        assert [c["annual_ctc_minor"] for c in compensation.json()["data"]][-1] == raised
        april = await client.get(
            f"/v1/employees/{employee_id}/salary/breakup",
            headers=headers,
            params={"as_of": "2026-04-15"},
        )
        assert april.status_code == 200, april.text
        assert april.json()["data"]["breakup"]["annual_ctc_minor"] == raised

        # The template is untouched and the employee's structure is not a company template.
        structures = await _structures(client, headers)
        assert set(structures) == {"STANDARD", "STANDARD_METRO"}
        (template_version,) = structures["STANDARD"]["versions"]
        assert template_version["id"] == standard["versions"][0]["id"]

        # Changing it again versions the same structure; saving the same lines is a no-op.
        sixty = _inputs(template_lines, BASIC={"percentage": "60"})
        saved = await client.post(
            f"/v1/employees/{employee_id}/salary/setup",
            headers=headers,
            json={
                "effective_from": "2026-07-01",
                "reason": "Basic raised",
                "template_structure_id": standard["id"],
                "lines": sixty,
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["salary_structure_id"] == own_id
        own = await client.get(f"/v1/payroll/salary-structures/{own_id}", headers=headers)
        assert sorted(v["effective_from"] for v in own.json()["data"]["versions"]) == [
            "2026-04-01",
            "2026-07-01",
        ]
        history = await client.get(f"/v1/employees/{employee_id}/salary", headers=headers)
        assert [r["effective_from"] for r in history.json()["data"]] == ["2026-01-01", "2026-04-01"]

        # Another employee cannot be assigned this employee's structure.
        created = await client.post("/v1/employees", headers=headers, json={"first_name": "Ravi"})
        assert created.status_code == 201, created.text
        refused = await client.post(
            f"/v1/employees/{created.json()['data']['id']}/salary",
            headers=headers,
            json={"salary_structure_id": own_id, "effective_from": "2026-01-01", "reason": "x"},
        )
        assert refused.status_code == 422, refused.text
        assert "another employee" in refused.json()["error"]["message"]
    finally:
        await _cleanup_payroll(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_setup_rejects_invalid_lines_and_needs_both_permissions(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _setup_employee(client, headers)
        standard = (await _structures(client, headers))["STANDARD"]
        template_lines = standard["versions"][0]["lines"]

        # No balancing line → refused, as on the structure editor.
        no_balance = [
            line for line in _inputs(template_lines) if line["calculation_type"] != "BALANCING"
        ]
        preview = await client.post(
            f"/v1/employees/{employee_id}/salary/setup/preview",
            headers=headers,
            json={"annual_ctc_minor": _CTC, "as_of": "2026-01-01", "lines": no_balance},
        )
        assert preview.status_code == 422, preview.text

        body = {
            "effective_from": "2026-01-01",
            "reason": "Joining",
            "template_structure_id": standard["id"],
            "lines": _inputs(template_lines),
        }
        scoped_headers, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=["PAYROLL.SETUP_MANAGE"], data_scope="COMPANY"
        )
        response = await client.post(
            f"/v1/employees/{employee_id}/salary/setup", headers=scoped_headers, json=body
        )
        assert response.status_code == 403, response.text
    finally:
        await _cleanup_payroll(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_setup_save_stays_inside_the_compensation_scope(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`EMPLOYEE.UPDATE_COMPENSATION` granted at SELF scope reaches the caller's own record only;
    another employee's salary is 404, as for every out-of-scope employee."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        own_id = await _setup_employee(client, headers)
        other_id = (await _create_employee(client, headers, first_name="Ravi"))["id"]
        standard = (await _structures(client, headers))["STANDARD"]
        body = {
            "effective_from": "2026-01-01",
            "reason": "Joining",
            "template_structure_id": standard["id"],
            "lines": _inputs(standard["versions"][0]["lines"]),
        }
        scoped_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=["PAYROLL.SETUP_MANAGE", "EMPLOYEE.UPDATE_COMPENSATION"],
            data_scope="SELF",
            caller_employee_id=UUID(own_id),
        )

        other = await client.post(
            f"/v1/employees/{other_id}/salary/setup", headers=scoped_headers, json=body
        )
        assert other.status_code == 404, other.text
        own = await client.post(
            f"/v1/employees/{own_id}/salary/setup", headers=scoped_headers, json=body
        )
        assert own.status_code == 200, own.text
    finally:
        await _cleanup_payroll(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
