"""Integration tests for payroll Phase 5.3 — the statutory rate master and statutory deductions in
a pay run (`docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md`, FR-PAY-005/006)."""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import _register_tenant
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.payroll.test_pay_run import (
    _action,
    _approver,
    _cleanup_pay_runs,
    _closed_period,
    _create_run,
    _employee,
    _legal_entity,
)

pytestmark = pytest.mark.asyncio


async def _rates(client: AsyncClient, headers: dict[str, str]) -> dict[tuple[str, str | None], Any]:
    response = await client.get("/v1/payroll/statutory-rates", headers=headers)
    assert response.status_code == 200, response.text
    return {(r["scheme"], r["state_code"]): r for r in response.json()["data"]}


async def _verify(client: AsyncClient, headers: dict[str, str], rate: dict[str, Any]) -> None:
    response = await client.post(
        f"/v1/payroll/statutory-rates/{rate['id']}/verify",
        headers={**headers, "If-Match": str(rate["version"])},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["verified"] is True


async def test_statutory_rate_master(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        rates = await _rates(client, headers)
        assert set(rates) == {("PF", None), ("ESI", None), ("PT", "MH"), ("PT", "KA")}
        assert all(r["is_seeded"] and not r["verified"] for r in rates.values())
        pf = rates[("PF", None)]
        assert pf["parameters"]["wage_ceiling_minor"] == 1_500_000
        assert pf["parameters"]["employee_percent"] == "12"
        # Listing again seeds nothing new.
        assert len(await _rates(client, headers)) == 4

        await _verify(client, headers, pf)

        # Editing a rate clears its verification.
        pf = (await _rates(client, headers))[("PF", None)]
        edited = await client.patch(
            f"/v1/payroll/statutory-rates/{pf['id']}",
            headers={**headers, "If-Match": str(pf["version"])},
            json={"notes": "Checked against the EPFO circular"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["data"]["verified"] is False

        bad = await client.patch(
            f"/v1/payroll/statutory-rates/{pf['id']}",
            headers={**headers, "If-Match": str(edited.json()["data"]["version"])},
            json={"parameters": {**pf["parameters"], "eps_percent": "15"}},
        )
        assert bad.status_code == 422, bad.text

        # A new rate from a later date closes the open one.
        created = await client.post(
            "/v1/payroll/statutory-rates",
            headers=headers,
            json={
                "scheme": "LWF",
                "state_code": "mh",
                "effective_from": "2026-01-01",
                "parameters": {
                    "months": [12, 6],
                    "slabs": [{"min_minor": 0, "employee_minor": 1_200, "employer_minor": 3_600}],
                },
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["data"]["state_code"] == "MH"
        assert created.json()["data"]["parameters"]["months"] == [6, 12]
        later = await client.post(
            "/v1/payroll/statutory-rates",
            headers=headers,
            json={
                "scheme": "LWF",
                "state_code": "MH",
                "effective_from": "2026-07-01",
                "parameters": {
                    "months": [6, 12],
                    "slabs": [{"min_minor": 0, "employee_minor": 2_500, "employer_minor": 7_500}],
                },
            },
        )
        assert later.status_code == 201, later.text
        listed = await client.get(
            "/v1/payroll/statutory-rates", headers=headers, params={"scheme": "LWF"}
        )
        periods = sorted((r["effective_from"], r["effective_to"]) for r in listed.json()["data"])
        assert periods == [("2026-01-01", "2026-06-30"), ("2026-07-01", None)]

        not_later = await client.post(
            "/v1/payroll/statutory-rates",
            headers=headers,
            json={
                "scheme": "LWF",
                "state_code": "MH",
                "effective_from": "2026-03-01",
                "parameters": {
                    "months": [6],
                    "slabs": [{"min_minor": 0, "employee_minor": 1, "employer_minor": 1}],
                },
            },
        )
        assert not_later.status_code == 422, not_later.text

        missing_state = await client.post(
            "/v1/payroll/statutory-rates",
            headers=headers,
            json={"scheme": "PT", "effective_from": "2026-01-01", "parameters": {"slabs": []}},
        )
        assert missing_state.status_code == 422, missing_state.text

        viewer, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=["PAYROLL.RUN_VIEW"], data_scope="COMPANY"
        )
        forbidden = await client.get("/v1/payroll/statutory-rates", headers=viewer)
        assert forbidden.status_code == 403, forbidden.text
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_pay_run_deducts_pf_and_professional_tax(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """PF-applicable, Maharashtra employee on the STANDARD structure, CTC ₹7,20,000: monthly CTC
    ₹60,000 = gross ₹58,200 + employer PF ₹1,800 (structure split). In the run: Basic ₹29,100,
    PF 12 % of ₹15,000 = ₹1,800, PT ₹200."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(
            client, headers, le, pf=True, pt_state="MH", gender="Male", uan="100200300400"
        )
        await _closed_period(
            company_id=company_id,
            legal_entity_id=le,
            start="2026-09-01",
            end="2026-09-30",
            paid_days={employee: "30"},
            days_in_month=30,
        )
        approver = await _approver(company_id)

        run = await _create_run(client, headers, le, "2026-09")
        run = await _action(client, headers, run, "lock-inputs")
        run = await _action(client, headers, run, "compute")
        # The seeded rates are unverified — the run cannot be approved yet.
        assert run["error_count"] == 1
        blocked = await _action(client, approver, run, "approve", expect=409)
        assert blocked["code"] == "PAY_RUN_BLOCKED"

        rates = await _rates(client, headers)
        await _verify(client, headers, rates[("PF", None)])
        await _verify(client, headers, rates[("PT", "MH")])
        # Rates are snapshotted at lock — lock again to pick up the verification.
        run = await _action(
            client, headers, run, "rollback", json={"to_status": "DRAFT", "reason": "Verified"}
        )
        run = await _action(client, headers, run, "lock-inputs")
        run = await _action(client, headers, run, "compute")
        assert run["error_count"] == 0

        detail = (
            await client.get(
                f"/v1/payroll/pay-runs/{run['id']}/employees/{employee}", headers=headers
            )
        ).json()["data"]
        lines = {line["component_code"]: line for line in detail["lines"]}
        assert "EMPLOYER_PF" not in lines  # the structure's CTC-split line is not paid as such
        assert lines["BASIC"]["amount_minor"] == 2_910_000
        assert lines["PF_EMPLOYEE"]["amount_minor"] == 180_000
        assert lines["PF_EMPLOYEE"]["line_type"] == "DEDUCTION"
        assert lines["EPS_EMPLOYER"]["amount_minor"] == 125_000
        assert lines["EPF_EMPLOYER"]["amount_minor"] == 55_000
        assert lines["PT"]["amount_minor"] == 20_000
        assert detail["gross_minor"] == 5_820_000
        assert detail["deductions_minor"] == 200_000
        assert detail["net_minor"] == 5_620_000
        assert detail["snapshot"]["statutory"]["rates"]["PF"]["verified"] is True

        run = await _action(client, approver, run, "approve")
        assert run["status"] == "APPROVED"
        assert run["deductions_minor"] == 200_000
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
