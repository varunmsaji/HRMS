"""PAY-B03 — a configured component is either supported and calculated, or refused up front; a
code the pay run computes itself can never be a salary component.

* new components: reserved codes are rejected at the API (422) and nothing is stored;
* structures: a component row that already carries a reserved code (created before this rule)
  cannot be published into a structure;
* unknown / inactive components remain rejected;
* a normal custom component still flows into the breakup."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import _register_tenant
from tests.integration.modules.attendance.test_attendance_security import _cleanup_scoped_users
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.payroll.test_pay_run import _cleanup_pay_runs
from tests.integration.modules.payroll.test_salary_structure import _amounts, _components

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

_CTC = 12_00_000_00


def _component(code: str) -> dict[str, object]:
    return {"code": code, "name": f"{code} test", "component_type": "EARNING"}


async def test_reserved_codes_are_rejected_and_ordinary_codes_work(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        for code in ("OVERTIME", "LEAVE_ENCASHMENT", "DAILY_WAGES", "TDS_EMPLOYEE", "ARR_BONUS"):
            response = await client.post(
                "/v1/payroll/salary-components", headers=headers, json=_component(code)
            )
            assert response.status_code == 422, (code, response.text)
            assert "reserved" in response.text
        assert not {"OVERTIME", "LEAVE_ENCASHMENT", "ARR_BONUS"} & set(
            await _components(client, headers)
        )

        ok = await client.post(
            "/v1/payroll/salary-components", headers=headers, json=_component("CONVEYANCE")
        )
        assert ok.status_code == 201, ok.text
        duplicate = await client.post(
            "/v1/payroll/salary-components", headers=headers, json=_component("CONVEYANCE")
        )
        assert duplicate.status_code == 409, duplicate.text
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_structures_refuse_legacy_reserved_unknown_and_accept_custom_components(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        components = await _components(client, headers)
        basic, special = components["BASIC"]["id"], components["SPECIAL_ALLOWANCE"]["id"]

        # A component row from before the rule existed (inserted directly, as old data would be).
        legacy_id = uuid4()
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text(
                    """
                    INSERT INTO salary_component
                      (id, company_id, code, name, component_type, is_system, is_taxable,
                       is_pf_wage, is_esi_wage, is_prorated, show_on_payslip, display_order,
                       is_active, version, created_at, updated_at)
                    VALUES (:id, :cid, 'OVERTIME', 'Legacy OT', 'EARNING', false, true, false,
                            false, true, true, 0, true, 1, now(), now())
                    """
                ),
                {"id": legacy_id, "cid": str(company_id)},
            )
            await session.commit()

        def structure(code: str, extra_component: str) -> dict[str, object]:
            return {
                "code": code,
                "name": code,
                "lines": [
                    {"salary_component_id": basic, "calculation_type": "PERCENTAGE_OF_CTC",
                     "percentage": "40", "display_order": 10},
                    {"salary_component_id": extra_component, "calculation_type": "FIXED",
                     "amount_monthly_minor": 100_000, "display_order": 20},
                    {"salary_component_id": special, "calculation_type": "BALANCING",
                     "display_order": 30},
                ],
            }  # fmt: skip

        reserved = await client.post(
            "/v1/payroll/salary-structures",
            headers=headers,
            json=structure("WITH_RESERVED", str(legacy_id)),
        )
        assert reserved.status_code == 422, reserved.text
        assert reserved.json()["error"]["code"] == "SALARY_STRUCTURE_INVALID"
        assert "reserved" in reserved.text

        unknown = await client.post(
            "/v1/payroll/salary-structures",
            headers=headers,
            json=structure("WITH_UNKNOWN", str(uuid4())),
        )
        assert unknown.status_code == 422, unknown.text
        assert unknown.json()["error"]["code"] == "SALARY_STRUCTURE_INVALID"

        custom = await client.post(
            "/v1/payroll/salary-components", headers=headers, json=_component("CONVEYANCE")
        )
        assert custom.status_code == 201, custom.text
        good = await client.post(
            "/v1/payroll/salary-structures",
            headers=headers,
            json=structure("WITH_CUSTOM", custom.json()["data"]["id"]),
        )
        assert good.status_code == 201, good.text
        data = good.json()["data"]
        preview = await client.post(
            f"/v1/payroll/salary-structures/{data['id']}/versions/{data['versions'][0]['id']}"
            "/preview",
            headers=headers,
            json={"annual_ctc_minor": _CTC, "pf_applicable": False},
        )
        assert preview.status_code == 200, preview.text
        amounts = _amounts(preview.json()["data"])
        assert amounts["CONVEYANCE"] == 100_000  # not dropped
        assert set(amounts) == {"BASIC", "CONVEYANCE", "SPECIAL_ALLOWANCE"}
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
