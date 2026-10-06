"""PAY-B02 — a pay run never pays more days than the employee was employed (engine invariant
`paid_days <= employed days in the legal entity <= days in the month`, and `<= payable_days`).

The summary is inserted directly (the attendance engine has its own tests); the employment is
real. A summary that over-states paid days must surface as a blocking employee error with no
amount computed, and the run must not be approvable."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
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
    _employees,
    _legal_entity,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio


async def _set_employment(company_id: object, employee_id: str, **columns: str) -> None:
    sets = ", ".join(f"{name} = :{name}" for name in columns)
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(f"UPDATE employment SET {sets} WHERE employee_id = :eid"),
            {
                "eid": employee_id,
                **{k: (v if k == "status" else _as_date(v)) for k, v in columns.items()},
            },
        )
        await session.commit()


def _as_date(value: str):  # type: ignore[no-untyped-def]
    from datetime import date

    return date.fromisoformat(value)


async def test_overstated_paid_days_are_refused_and_exact_boundaries_pass(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        approver = await _approver(company_id)
        full = await _employee(client, headers, le, name="Full")
        leaver_ok = await _employee(client, headers, le, name="LeaverOk")
        leaver_bad = await _employee(client, headers, le, name="LeaverBad")
        joiner_ok = await _employee(client, headers, le, name="JoinerOk")
        for leaver in (leaver_ok, leaver_bad):
            await _set_employment(
                company_id, leaver, last_working_day="2026-09-10", status="TERMINATED"
            )  # 10 days
        await _set_employment(company_id, joiner_ok, joining_date="2026-09-11")  # 20 days
        await _closed_period(
            company_id=company_id, legal_entity_id=le, start="2026-09-01", end="2026-09-30",
            paid_days={full: "30", leaver_ok: "10", leaver_bad: "30", joiner_ok: "20"},
            days_in_month=30,
        )  # fmt: skip

        run = await _create_run(client, headers, le, "2026-09")
        run = await _action(client, headers, run, "lock-inputs")
        run = await _action(client, headers, run, "compute")
        employees = await _employees(client, headers, run["id"])

        # paid == employed passes, and is paid pro rata
        assert not employees[full]["has_error"] and employees[full]["net_minor"] == 6_000_000
        assert not employees[leaver_ok]["has_error"]
        assert employees[leaver_ok]["net_minor"] == 2_000_000  # 60,000 × 10/30
        assert not employees[joiner_ok]["has_error"]
        assert employees[joiner_ok]["net_minor"] == 4_000_000  # 60,000 × 20/30

        # paid > employed is an error, with nothing computed for that employee
        bad = employees[leaver_bad]
        assert bad["has_error"] and bad["net_minor"] == 0
        assert [i["code"] for i in bad["issues"]] == ["PAID_DAYS_EXCEED_EMPLOYED"]
        assert run["error_count"] == 1

        # and the run cannot move on to approval with it
        refused = await _action(client, approver, run, "approve", expect=409)
        assert refused["code"].startswith("PAY_RUN_")
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
