"""Integration tests for payroll Phase 5.4 — payslips and bank advice (`docs/modules/payroll/
00_PAYROLL_IMPLEMENTATION_PLAN.md`, FR-PAY-017/018)."""

import csv
import io
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
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

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio


async def _self_service(company_id: UUID, employee_id: str) -> dict[str, str]:
    headers, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=["PAYROLL.PAYSLIP_VIEW_OWN"],
        data_scope="SELF",
        caller_employee_id=UUID(employee_id),
    )
    return headers


async def test_payslips_and_bank_advice(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        asha = await _employee(client, headers, le, name="Asha")
        cash = await _employee(client, headers, le, name="Cash")
        # Cash is paid in cash — not part of the bank file.
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text("UPDATE employee_bank SET payment_mode = 'CASH' WHERE employee_id = :id"),
                {"id": cash},
            )
            await session.commit()
        await _closed_period(
            company_id=company_id,
            legal_entity_id=le,
            start="2026-09-01",
            end="2026-09-30",
            paid_days={asha: "30", cash: "27"},
            days_in_month=30,
        )
        approver = await _approver(company_id)
        asha_self = await _self_service(company_id, asha)

        run = await _create_run(client, headers, le, "2026-09")
        run = await _action(client, headers, run, "lock-inputs")
        not_computed = await client.get(
            f"/v1/payroll/pay-runs/{run['id']}/employees/{asha}/payslip", headers=headers
        )
        assert not_computed.status_code == 409, not_computed.text
        run = await _action(client, headers, run, "compute")

        # HR preview before finalising.
        preview = await client.get(
            f"/v1/payroll/pay-runs/{run['id']}/employees/{asha}/payslip", headers=headers
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["data"]["is_final"] is False
        # Not visible to the employee, and no bank file, until finalised.
        assert (await client.get("/v1/me/payslips", headers=asha_self)).json()["data"] == []
        hidden = await client.get(f"/v1/me/payslips/{run['id']}", headers=asha_self)
        assert hidden.status_code == 404, hidden.text
        early = await client.get(f"/v1/payroll/pay-runs/{run['id']}/bank-advice", headers=headers)
        assert early.status_code == 409, early.text

        run = await _action(client, approver, run, "approve")
        run = await _action(client, approver, run, "finalise")

        payslip = await client.get(
            f"/v1/payroll/pay-runs/{run['id']}/employees/{asha}/payslip", headers=headers
        )
        data = payslip.json()["data"]
        assert data["is_final"] is True
        assert data["legal_entity_name"] == "Acme LE"
        assert data["employee_name"] == "Asha"
        assert data["date_of_joining"] == "2026-01-01"
        assert data["account_last4"] == "9012"
        assert data["paid_days"] == "30"
        assert {line["component_code"] for line in data["earnings"]} == {
            "BASIC",
            "HRA",
            "SPECIAL_ALLOWANCE",
        }
        assert data["net_minor"] == 6_000_000
        assert data["net_in_words"] == "Rupees Sixty Thousand Only"

        # Self-service: own payslips only.
        mine = await client.get("/v1/me/payslips", headers=asha_self)
        assert mine.status_code == 200, mine.text
        assert [p["pay_run_id"] for p in mine.json()["data"]] == [run["id"]]
        own = await client.get(f"/v1/me/payslips/{run['id']}", headers=asha_self)
        assert own.status_code == 200, own.text
        assert own.json()["data"]["employee_id"] == asha
        # The HR route is not open to the employee.
        other = await client.get(
            f"/v1/payroll/pay-runs/{run['id']}/employees/{cash}/payslip", headers=asha_self
        )
        assert other.status_code == 403, other.text

        # Bank advice — COMPANY_ADMIN only; bank-transfer employees only; full account number.
        forbidden = await client.get(
            f"/v1/payroll/pay-runs/{run['id']}/bank-advice", headers=approver
        )
        assert forbidden.status_code == 403, forbidden.text
        advice = await client.get(f"/v1/payroll/pay-runs/{run['id']}/bank-advice", headers=headers)
        assert advice.status_code == 200, advice.text
        assert advice.headers["content-type"].startswith("text/csv")
        assert advice.headers["cache-control"] == "no-store"
        assert "bank-advice-acme-le-2026-09.csv" in advice.headers["content-disposition"]
        rows = list(csv.reader(io.StringIO(advice.text)))
        assert rows[0][:4] == ["Employee code", "Employee name", "Account holder", "Account number"]
        assert len(rows) == 2
        assert rows[1][1] == "Asha"
        assert rows[1][3] == "123456789012"
        assert rows[1][6] == "60000.00"
        assert rows[1][7] == "Salary Sep 2026"

        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            audited = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log WHERE company_id = :cid "
                        "AND action = 'PAYROLL_BANK_ADVICE_DOWNLOADED'"
                    ),
                    {"cid": str(company_id)},
                )
            ).scalar_one()
        assert audited == 1
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
