"""Integration tests for payroll Phase 5.6 — income tax (TDS), new regime only
(`docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md`, FR-PAY-011). The tax math itself is
unit-tested in `tests/unit/modules/payroll/test_income_tax.py`; these exercise the real wiring —
the API, the snapshot, and the year-to-date query over actually finalised runs."""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import _register_tenant
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.payroll.test_pay_run import (
    _action,
    _approver,
    _cleanup_pay_runs,
    _closed_period,
    _create_run,
    _employee,
    _employees,
    _legal_entity,
)

pytestmark = pytest.mark.asyncio

_HIGH_CTC = 36_00_000_00  # ₹36,00,000/yr — comfortably above the new-regime rebate threshold


async def _set_pan(client: AsyncClient, headers: dict[str, str], employee_id: str) -> None:
    current = await client.get(f"/v1/employees/{employee_id}/identity", headers=headers)
    assert current.status_code == 200, current.text
    response = await client.patch(
        f"/v1/employees/{employee_id}/identity",
        headers={**headers, "If-Match": str(current.json()["data"]["version"])},
        json={"pan_number": "ABCDE1234F"},
    )
    assert response.status_code == 200, response.text


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


async def test_high_earner_is_taxed_and_blocked_until_the_rate_is_verified(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le, ctc=_HIGH_CTC)
        await _set_pan(client, headers, employee)
        await _closed_period(
            company_id=company_id, legal_entity_id=le, start="2026-04-01", end="2026-04-30",
            paid_days={employee: "30"}, days_in_month=30,
        )  # fmt: skip
        approver = await _approver(company_id)

        run = await _create_run(client, headers, le, "2026-04")
        run = await _action(client, headers, run, "lock-inputs")
        run = await _action(client, headers, run, "compute")

        employees = await _employees(client, headers, run["id"])
        line = employees[employee]
        assert line["deductions_minor"] > 0
        assert any(i["code"] == "STATUTORY_UNVERIFIED" for i in line["issues"])
        assert run["error_count"] == 1

        blocked = await _action(client, approver, run, "approve", expect=409)
        assert blocked["code"] == "PAY_RUN_BLOCKED"

        rates = await _rates(client, headers)
        await _verify(client, headers, rates[("TDS", None)])
        run = await _action(
            client, headers, run, "rollback", json={"to_status": "DRAFT", "reason": "Verified"}
        )
        run = await _action(client, headers, run, "lock-inputs")
        run = await _action(client, headers, run, "compute")
        assert run["error_count"] == 0

        employees = await _employees(client, headers, run["id"])
        assert employees[employee]["deductions_minor"] > 0
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_ytd_carries_forward_from_an_earlier_finalised_run(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The second month's TDS reflects what the first month's *finalised* run actually paid and
    deducted, not a re-derivation from scratch — proving the year-to-date query reads real rows,
    not just repeats the same monthly estimate."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le, ctc=_HIGH_CTC)
        await _set_pan(client, headers, employee)
        rates = await _rates(client, headers)
        await _verify(client, headers, rates[("TDS", None)])
        approver = await _approver(company_id)

        await _closed_period(
            company_id=company_id, legal_entity_id=le, start="2026-04-01", end="2026-04-30",
            paid_days={employee: "30"}, days_in_month=30,
        )  # fmt: skip
        april = await _create_run(client, headers, le, "2026-04")
        april = await _action(client, headers, april, "lock-inputs")
        april = await _action(client, headers, april, "compute")
        assert april["error_count"] == 0
        april_employees = await _employees(client, headers, april["id"])
        april_tds = next(
            line["amount_minor"]
            for line in (
                await client.get(
                    f"/v1/payroll/pay-runs/{april['id']}/employees/{employee}", headers=headers
                )
            ).json()["data"]["lines"]
            if line["component_code"] == "TDS_EMPLOYEE"
        )
        april = await _action(client, approver, april, "approve")
        april = await _action(client, approver, april, "finalise")

        await _closed_period(
            company_id=company_id, legal_entity_id=le, start="2026-05-01", end="2026-05-31",
            paid_days={employee: "31"}, days_in_month=31,
        )  # fmt: skip
        may = await _create_run(client, headers, le, "2026-05")
        may = await _action(client, headers, may, "lock-inputs")
        may = await _action(client, headers, may, "compute")
        assert may["error_count"] == 0
        may_line = next(
            line
            for line in (
                await client.get(
                    f"/v1/payroll/pay-runs/{may['id']}/employees/{employee}", headers=headers
                )
            ).json()["data"]["lines"]
            if line["component_code"] == "TDS_EMPLOYEE"
        )
        # 11 months remained when April was computed; 11 when May is (Apr counted as already
        # paid, May through Mar = 11). Same annual liability either way (same flat monthly
        # gross), so May's YTD inputs should show April's actual gross and TDS folded in.
        assert (
            may_line["trace"]["ytd_taxable_earnings_minor"]
            == april_employees[employee]["gross_minor"]
        )
        assert may_line["trace"]["ytd_tds_deducted_minor"] == april_tds
        assert may_line["trace"]["months_remaining_in_fy"] == 11
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
