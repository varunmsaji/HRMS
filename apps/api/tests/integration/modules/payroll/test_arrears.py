"""Integration tests for payroll Phase 5.5 — arrears (`docs/modules/payroll/
00_PAYROLL_IMPLEMENTATION_PLAN.md`, FR-PAY-010, AC-PAY-023.1, decision 15 / D7)."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import _register_tenant
from tests.integration.modules.attendance.test_attendance_security import _cleanup_scoped_users
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

_MONTHS = {
    "2026-08": ("2026-08-01", "2026-08-31", 31),
    "2026-09": ("2026-09-01", "2026-09-30", 30),
    "2026-10": ("2026-10-01", "2026-10-31", 31),
}


async def _finalised_run(
    client: AsyncClient,
    headers: dict[str, str],
    approver: dict[str, str],
    *,
    company_id: UUID,
    legal_entity_id: str,
    month: str,
    paid_days: dict[str, str],
) -> dict[str, Any]:
    start, end, days = _MONTHS[month]
    await _closed_period(
        company_id=company_id,
        legal_entity_id=legal_entity_id,
        start=start,
        end=end,
        paid_days=paid_days,
        days_in_month=days,
    )
    run = await _create_run(client, headers, legal_entity_id, month)
    run = await _action(client, headers, run, "lock-inputs")
    run = await _action(client, headers, run, "compute")
    assert run["error_count"] == 0, run
    # Arrears move net pay — acknowledge any flagged variance, as HR would.
    employees = await client.get(f"/v1/payroll/pay-runs/{run['id']}/employees", headers=headers)
    for row in employees.json()["data"]:
        if row["variance_flagged"]:
            acknowledged = await client.post(
                f"/v1/payroll/pay-runs/{run['id']}/employees/{row['employee_id']}"
                "/acknowledge-variance",
                headers=headers,
                json={"reason": "Arrears"},
            )
            assert acknowledged.status_code == 200, acknowledged.text
    run = (await client.get(f"/v1/payroll/pay-runs/{run['id']}", headers=headers)).json()["data"]
    run = await _action(client, approver, run, "approve")
    return await _action(client, approver, run, "finalise")


async def _lines(
    client: AsyncClient, headers: dict[str, str], run_id: str, employee_id: str
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    response = await client.get(
        f"/v1/payroll/pay-runs/{run_id}/employees/{employee_id}", headers=headers
    )
    assert response.status_code == 200, response.text
    detail = response.json()["data"]
    return detail, {line["component_code"]: line for line in detail["lines"]}


def _prorate(monthly: int, paid: int, days: int) -> int:
    return int((Decimal(monthly) * paid / days).quantize(Decimal(1), rounding=ROUND_HALF_UP))


async def test_backdated_revision_is_paid_once_as_arrears(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """August is finalised on ₹7,20,000; a raise to ₹8,40,000 from 1 August is then recorded.
    September pays August's difference as arrears; October pays nothing more for August."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        approver = await _approver(company_id)
        august = await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-08", paid_days={employee: "31"},
        )  # fmt: skip

        current = await client.get(f"/v1/employees/{employee}/compensation", headers=headers)
        version = current.json()["data"][0]["version"]
        revision = await client.post(
            f"/v1/employees/{employee}/compensation",
            headers={**headers, "If-Match": str(version)},
            json={
                "effective_from": "2026-08-01",
                "annual_ctc_minor": 8_40_000_00,
                "currency": "INR",
                "revision_type": "ANNUAL",
                "revision_reason": "Annual increment, backdated",
            },
        )
        assert revision.status_code == 201, revision.text

        september = await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-09", paid_days={employee: "30"},
        )  # fmt: skip
        detail, lines = await _lines(client, headers, september["id"], employee)
        # Monthly ₹70,000: Basic ₹35,000, HRA ₹14,000, Special ₹21,000 (was 30,000/12,000/18,000).
        assert lines["BASIC"]["amount_minor"] == 3_500_000
        assert lines["ARR_BASIC"]["amount_minor"] == 500_000
        assert lines["ARR_HRA"]["amount_minor"] == 200_000
        assert lines["ARR_SPECIAL_ALLOWANCE"]["amount_minor"] == 300_000
        assert lines["ARR_BASIC"]["line_type"] == "EARNING"
        part = lines["ARR_BASIC"]["trace"]["parts"][0]
        assert part["month"] == "2026-08"
        assert part["pay_run_id"] == august["id"]
        assert part["reasons"] == ["SALARY_CHANGED"]
        assert detail["net_minor"] == 7_000_000 + 1_000_000

        # The payslip shows the arrears among the earnings.
        payslip = await client.get(
            f"/v1/payroll/pay-runs/{september['id']}/employees/{employee}/payslip", headers=headers
        )
        earnings = {e["component_code"]: e for e in payslip.json()["data"]["earnings"]}
        assert earnings["ARR_BASIC"]["note"] == "Aug 2026: ₹5,000.00"

        october = await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-10", paid_days={employee: "31"},
        )  # fmt: skip
        detail, lines = await _lines(client, headers, october["id"], employee)
        assert not [code for code in lines if code.startswith("ARR_")]
        assert detail["net_minor"] == 7_000_000
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_day_correction_is_paid_as_arrears(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """D7 — August was paid for 29 of 31 days; a missed punch is proved later. The closed period
    stays closed; a +1 day correction is paid as arrears in September, exactly once."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        approver = await _approver(company_id)
        august = await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-08", paid_days={employee: "29"},
        )  # fmt: skip

        too_many = await client.post(
            "/v1/payroll/adjustments",
            headers=headers,
            json={
                "source_pay_run_id": august["id"],
                "employee_id": employee,
                "paid_days_delta": "3",
                "reason": "Wrong",
            },
        )
        assert too_many.status_code == 422, too_many.text
        created = await client.post(
            "/v1/payroll/adjustments",
            headers=headers,
            json={
                "source_pay_run_id": august["id"],
                "employee_id": employee,
                "paid_days_delta": "1",
                "reason": "Missed punch on 12 Aug proved by gate log",
            },
        )
        assert created.status_code == 201, created.text
        adjustment = created.json()["data"]
        assert adjustment["status"] == "PENDING"
        assert adjustment["month"] == "2026-08"

        september = await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-09", paid_days={employee: "30"},
        )  # fmt: skip
        _, lines = await _lines(client, headers, september["id"], employee)
        assert lines["ARR_BASIC"]["amount_minor"] == _prorate(3_000_000, 30, 31) - _prorate(
            3_000_000, 29, 31
        )
        assert lines["ARR_BASIC"]["trace"]["parts"][0]["reasons"] == ["DAYS_CORRECTED"]

        listed = await client.get(
            "/v1/payroll/adjustments",
            headers=headers,
            params={"source_pay_run_id": august["id"]},
        )
        (applied,) = listed.json()["data"]
        assert applied["status"] == "APPLIED"
        assert applied["applied_pay_run_id"] == september["id"]
        withdrawn = await client.delete(f"/v1/payroll/adjustments/{applied['id']}", headers=headers)
        assert withdrawn.status_code == 422, withdrawn.text

        october = await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-10", paid_days={employee: "31"},
        )  # fmt: skip
        _, lines = await _lines(client, headers, october["id"], employee)
        assert not [code for code in lines if code.startswith("ARR_")]
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_pending_correction_can_be_withdrawn(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        approver = await _approver(company_id)
        august = await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-08", paid_days={employee: "31"},
        )  # fmt: skip
        created = await client.post(
            "/v1/payroll/adjustments",
            headers=headers,
            json={
                "source_pay_run_id": august["id"],
                "employee_id": employee,
                "paid_days_delta": "-0.5",
                "reason": "Half day not marked",
            },
        )
        assert created.status_code == 201, created.text
        deleted = await client.delete(
            f"/v1/payroll/adjustments/{created.json()['data']['id']}", headers=headers
        )
        assert deleted.status_code == 204, deleted.text

        september = await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-09", paid_days={employee: "30"},
        )  # fmt: skip
        _, lines = await _lines(client, headers, september["id"], employee)
        assert not [code for code in lines if code.startswith("ARR_")]
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_arrears_are_never_paid_by_two_open_runs(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """September and October are both prepared before either is finalised, so both carry
    August's arrears. Whichever finalises second is refused and must lock its inputs again."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        approver = await _approver(company_id)
        await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-08", paid_days={employee: "29"},
        )  # fmt: skip
        august = (await client.get("/v1/payroll/pay-runs", headers=headers)).json()["data"][0]
        created = await client.post(
            "/v1/payroll/adjustments",
            headers=headers,
            json={
                "source_pay_run_id": august["id"],
                "employee_id": employee,
                "paid_days_delta": "2",
                "reason": "Two missed days",
            },
        )
        assert created.status_code == 201, created.text

        runs = {}
        for month in ("2026-09", "2026-10"):
            start, end, days = _MONTHS[month]
            await _closed_period(
                company_id=company_id, legal_entity_id=le, start=start, end=end,
                paid_days={employee: str(days)}, days_in_month=days,
            )  # fmt: skip
            run = await _create_run(client, headers, le, month)
            run = await _action(client, headers, run, "lock-inputs")
            runs[month] = await _action(client, headers, run, "compute")
            _, lines = await _lines(client, headers, run["id"], employee)
            assert "ARR_BASIC" in lines

        september = await _action(client, approver, runs["2026-09"], "approve")
        await _action(client, approver, september, "finalise")

        october = await _action(client, approver, runs["2026-10"], "approve")
        stale = await _action(client, approver, october, "finalise", expect=409)
        assert stale["code"] == "PAY_RUN_ARREARS_STALE"

        # Locking again picks up that August is settled — no arrears left for October.
        october = (
            await client.get(f"/v1/payroll/pay-runs/{october['id']}", headers=headers)
        ).json()["data"]
        october = await _action(
            client, headers, october, "rollback", json={"to_status": "DRAFT", "reason": "Stale"}
        )
        october = await _action(client, headers, october, "lock-inputs")
        october = await _action(client, headers, october, "compute")
        _, lines = await _lines(client, headers, october["id"], employee)
        assert not [code for code in lines if code.startswith("ARR_")]
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
