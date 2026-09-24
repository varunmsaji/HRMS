"""Integration tests for payroll Phase 5.2 — the pay run (`docs/modules/payroll/
00_PAYROLL_IMPLEMENTATION_PLAN.md` §3–4; decisions 14/15/17/18, PD-2, D3–D11).

Closed attendance periods and their frozen summaries are inserted directly (the attendance
engine has its own tests); everything payroll does is exercised through the API."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import _register_tenant
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

# ₹7,20,000 a year → monthly CTC ₹60,000; with PF not applicable the whole CTC is gross:
# Basic ₹30,000, HRA ₹12,000 (40 %), Special Allowance ₹18,000.
_CTC = 7_20_000_00


async def _cleanup_pay_runs(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "attendance_day",
            "overtime_policy_rate_row",
            "overtime_policy_version",
            "overtime_policy",
            "leave_ledger",
            "leave_type",
            "pay_run_arrear",
            "pay_adjustment",
            "pay_run_line",
            "pay_run_employee",
            "statutory_rate",
            "pay_run",
            "payroll_setting",
            "attendance_period_summary",
            "attendance_period_action",
            "attendance_period",
            "employee_bank",
            "employee_salary",
            "salary_structure_line",
            "salary_structure_version",
            "salary_structure",
            "salary_component",
            "employee_statutory",
            "employee_compensation",
            "employment",
            "employee",
            "number_series",
            "legal_entity",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


async def _legal_entity(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/v1/legal-entities", headers=headers, json={"name": "Acme LE"})
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["id"])


async def _employee(
    client: AsyncClient,
    headers: dict[str, str],
    legal_entity_id: str,
    *,
    name: str = "Ravi",
    ctc: int = _CTC,
    pf: bool = False,
    bank: bool = True,
    salary: bool = True,
    pt_state: str | None = None,
    gender: str | None = None,
    uan: str | None = None,
) -> str:
    employee = await client.post(
        "/v1/employees",
        headers=headers,
        json={"first_name": name, **({"gender": gender} if gender else {})},
    )
    assert employee.status_code == 201, employee.text
    employee_id = str(employee.json()["data"]["id"])
    employment = await client.post(
        f"/v1/employees/{employee_id}/employments",
        headers=headers,
        json={"legal_entity_id": legal_entity_id, "joining_date": "2026-01-01"},
    )
    assert employment.status_code == 201, employment.text
    compensation = await client.post(
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
    assert compensation.status_code == 201, compensation.text
    statutory = await client.post(
        f"/v1/employees/{employee_id}/statutory",
        headers=headers,
        json={
            "effective_from": "2026-01-01",
            "is_pf_applicable": pf,
            "is_esi_applicable": False,
            "is_lwf_applicable": False,
            "tax_regime": "NEW",
            "revision_reason": "Initial statutory profile",
            **({"pt_state_code": pt_state} if pt_state else {}),
        },
    )
    assert statutory.status_code == 201, statutory.text
    if uan:
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, headers["X-Company-Id"])
            await session.execute(
                text("UPDATE employee SET uan_number = :uan WHERE id = :id"),
                {"uan": uan, "id": employee_id},
            )
            await session.commit()
    if bank:
        created = await client.post(
            f"/v1/employees/{employee_id}/bank",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "account_holder_name": name,
                "account_number_enc": "123456789012",
                "bank_name": "State Bank",
                "ifsc": "SBIN0001234",
                "payment_mode": "BANK",
            },
        )
        assert created.status_code == 201, created.text
    if salary:
        structures = await client.get("/v1/payroll/salary-structures", headers=headers)
        standard = next(s for s in structures.json()["data"] if s["code"] == "STANDARD")
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
    return employee_id


async def _closed_period(
    *,
    company_id: UUID,
    legal_entity_id: str,
    start: str,
    end: str,
    paid_days: dict[str, str],
    days_in_month: int,
    status: str = "CLOSED",
) -> str:
    """A closed attendance period with one frozen summary row per employee: `paid_days` paid,
    the rest LOP."""
    period_id = uuid4()
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        now = datetime.now(UTC)
        await session.execute(
            text(
                """
                INSERT INTO attendance_period
                  (id, company_id, legal_entity_id, period_start, period_end, label, status,
                   opened_at, closed_at, version, created_at, updated_at)
                VALUES (:id, :cid, :le, :start, :end, 'test', :status, :now, :now, 1, :now, :now)
                """
            ),
            {
                "id": period_id,
                "cid": str(company_id),
                "le": legal_entity_id,
                "start": datetime.fromisoformat(start).date(),
                "end": datetime.fromisoformat(end).date(),
                "status": status,
                "now": now,
            },
        )
        for employee_id, paid in paid_days.items():
            lop = days_in_month - float(paid)
            await session.execute(
                text(
                    """
                    INSERT INTO attendance_period_summary
                      (id, company_id, attendance_period_id, employee_id, present_days,
                       absent_days, lop_days, on_duty_days, incomplete_days, not_employed_days,
                       unpaid_off_days, paid_days, payable_days, generated_at)
                    VALUES (gen_random_uuid(), :cid, :pid, :eid, :paid, :lop, :lop, 0, 0, 0, 0,
                            :paid, :payable, now())
                    """
                ),
                {
                    "cid": str(company_id),
                    "pid": period_id,
                    "eid": employee_id,
                    "paid": paid,
                    "lop": lop,
                    "payable": days_in_month,
                },
            )
        await session.commit()
    return str(period_id)


async def _approver(company_id: UUID) -> dict[str, str]:
    headers, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=["PAYROLL.RUN_VIEW", "PAYROLL.RUN_APPROVE"],
        data_scope="COMPANY",
    )
    return headers


async def _create_run(
    client: AsyncClient, headers: dict[str, str], legal_entity_id: str, month: str
) -> dict[str, Any]:
    response = await client.post(
        "/v1/payroll/pay-runs",
        headers=headers,
        json={"legal_entity_id": legal_entity_id, "month": month},
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _action(
    client: AsyncClient,
    headers: dict[str, str],
    run: dict[str, Any],
    action: str,
    *,
    expect: int = 200,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/payroll/pay-runs/{run['id']}/{action}",
        headers={**headers, "If-Match": str(run["version"])},
        json=json,
    )
    assert response.status_code == expect, response.text
    body = response.json()
    return dict(body["data"]) if expect == 200 else dict(body["error"])


async def _employees(
    client: AsyncClient, headers: dict[str, str], run_id: str
) -> dict[str, dict[str, Any]]:
    response = await client.get(f"/v1/payroll/pay-runs/{run_id}/employees", headers=headers)
    assert response.status_code == 200, response.text
    return {e["employee_id"]: e for e in response.json()["data"]}


async def test_pay_run_lifecycle(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        full = await _employee(client, headers, le, name="Full")
        lop = await _employee(client, headers, le, name="Lop")
        period_id = await _closed_period(
            company_id=company_id,
            legal_entity_id=le,
            start="2026-09-01",
            end="2026-09-30",
            paid_days={full: "30", lop: "27"},
            days_in_month=30,
        )

        run = await _create_run(client, headers, le, "2026-09")
        assert run["status"] == "DRAFT"
        assert run["period_start"] == "2026-09-01"
        assert run["days_in_month"] == 30
        assert run["pay_date"] == "2026-10-01"  # D11 — first weekday after the month

        duplicate = await client.post(
            "/v1/payroll/pay-runs",
            headers=headers,
            json={"legal_entity_id": le, "month": "2026-09"},
        )
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["error"]["code"] == "PAY_RUN_ALREADY_EXISTS"

        run = await _action(client, headers, run, "lock-inputs")
        assert run["status"] == "INPUTS_LOCKED"
        assert run["attendance_period_id"] == period_id
        assert run["employee_count"] == 2
        assert run["error_count"] == 0

        run = await _action(client, headers, run, "compute")
        assert run["status"] == "COMPUTED"
        employees = await _employees(client, headers, run["id"])
        assert employees[full]["net_minor"] == 6_000_000
        assert employees[lop]["net_minor"] == 5_400_000  # ₹60,000 × 27/30
        assert employees[lop]["lop_days"] == "3"
        assert run["gross_minor"] == run["net_minor"] == 11_400_000

        detail = await client.get(
            f"/v1/payroll/pay-runs/{run['id']}/employees/{lop}", headers=headers
        )
        assert detail.status_code == 200, detail.text
        lines = {line["component_code"]: line for line in detail.json()["data"]["lines"]}
        assert lines["BASIC"]["amount_minor"] == 2_700_000
        assert lines["BASIC"]["full_monthly_minor"] == 3_000_000
        assert lines["BASIC"]["trace"]["paid_days"] == "27"
        assert "EMPLOYER_PF" not in lines  # not PF-applicable
        snapshot = detail.json()["data"]["snapshot"]
        assert snapshot["bank"]["account_last4"] == "9012"
        assert "123456789012" not in str(snapshot)

        # D9 — the user who computed cannot approve.
        maker = await _action(client, headers, run, "approve", expect=403)
        assert maker["code"] == "PAY_RUN_MAKER_CHECKER"

        approver = await _approver(company_id)
        processor_only = await client.post(
            "/v1/payroll/pay-runs",
            headers=approver,
            json={"legal_entity_id": le, "month": "2026-10"},
        )
        assert processor_only.status_code == 403, processor_only.text

        run = await _action(client, approver, run, "approve")
        assert run["status"] == "APPROVED"
        run = await _action(client, approver, run, "finalise")
        assert run["status"] == "FINALISED"

        # Decision 15 — a month whose payroll is finalised never reopens.
        period = await client.get(f"/v1/attendance-periods/{period_id}", headers=headers)
        reopened = await client.post(
            f"/v1/attendance-periods/{period_id}/reopen",
            headers={**headers, "If-Match": str(period.json()["data"]["version"])},
            json={"reason": "Late correction"},
        )
        assert reopened.status_code == 409, reopened.text
        assert reopened.json()["error"]["code"] == "ATTENDANCE_PERIOD_PAYROLL_FINALISED"

        # A finalised run never changes.
        rollback = await _action(
            client,
            headers,
            run,
            "rollback",
            expect=409,
            json={"to_status": "DRAFT", "reason": "Oops"},
        )
        assert rollback["code"] == "PAY_RUN_INVALID_TRANSITION"
        patched = await client.patch(
            f"/v1/payroll/pay-runs/{run['id']}",
            headers={**headers, "If-Match": str(run["version"])},
            json={"pay_date": "2026-10-05"},
        )
        assert patched.status_code == 409, patched.text

        run = await _action(client, approver, run, "mark-paid")
        assert run["status"] == "PAID"
        assert run["paid_by_user_id"] is not None
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_lock_inputs_needs_a_closed_period(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """PD-2 — payroll never reads an unclosed period."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        run = await _create_run(client, headers, le, "2026-09")

        missing = await _action(client, headers, run, "lock-inputs", expect=409)
        assert missing["code"] == "PAY_RUN_ATTENDANCE_NOT_CLOSED"

        await _closed_period(
            company_id=company_id,
            legal_entity_id=le,
            start="2026-09-01",
            end="2026-09-30",
            paid_days={employee: "30"},
            days_in_month=30,
            status="OPEN",
        )
        still_open = await _action(client, headers, run, "lock-inputs", expect=409)
        assert still_open["code"] == "PAY_RUN_ATTENDANCE_NOT_CLOSED"

        # Only a DRAFT run can be deleted.
        deleted = await client.delete(f"/v1/payroll/pay-runs/{run['id']}", headers=headers)
        assert deleted.status_code == 204, deleted.text
        gone = await client.get(f"/v1/payroll/pay-runs/{run['id']}", headers=headers)
        assert gone.status_code == 404
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_validation_errors_block_approval(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        no_salary = await _employee(client, headers, le, name="NoSalary", salary=False)
        pf = await _employee(client, headers, le, name="Pf", pf=True)
        no_bank = await _employee(client, headers, le, name="NoBank", bank=False)
        missing_summary = await _employee(client, headers, le, name="Missing")
        await _closed_period(
            company_id=company_id,
            legal_entity_id=le,
            start="2026-09-01",
            end="2026-09-30",
            paid_days={no_salary: "30", pf: "30", no_bank: "30"},
            days_in_month=30,
        )
        run = await _create_run(client, headers, le, "2026-09")
        run = await _action(client, headers, run, "lock-inputs")
        assert run["employee_count"] == 4
        run = await _action(client, headers, run, "compute")
        assert run["error_count"] == 4

        employees = await _employees(client, headers, run["id"])

        def codes(employee_id: str) -> set[str]:
            return {issue["code"] for issue in employees[employee_id]["issues"]}

        assert "SALARY_MISSING" in codes(no_salary)
        assert "STATUTORY_UNVERIFIED" in codes(pf)  # seeded PF rate not yet signed off
        assert "BANK_MISSING" in codes(no_bank)
        assert "NOT_IN_ATTENDANCE" in codes(missing_summary)

        blocked = await _action(client, await _approver(company_id), run, "approve", expect=409)
        assert blocked["code"] == "PAY_RUN_BLOCKED"

        # Roll back to INPUTS_LOCKED drops the computed pay but keeps the snapshot.
        run = await _action(
            client,
            headers,
            run,
            "rollback",
            json={"to_status": "INPUTS_LOCKED", "reason": "Fix salaries"},
        )
        assert run["status"] == "INPUTS_LOCKED"
        assert run["net_minor"] == 0
        employees = await _employees(client, headers, run["id"])
        assert len(employees) == 4
        assert not any(e["is_computed"] for e in employees.values())

        # Roll back to DRAFT drops the snapshot too.
        run = await _action(
            client, headers, run, "rollback", json={"to_status": "DRAFT", "reason": "Start over"}
        )
        assert run["status"] == "DRAFT"
        assert run["attendance_period_id"] is None
        assert await _employees(client, headers, run["id"]) == {}
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_variance_needs_acknowledgement(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """FR-PAY-014 / D10 — a net pay change above 15 % against the previous finalised run must be
    acknowledged with a reason before approval."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        steady = await _employee(client, headers, le, name="Steady")
        dropped = await _employee(client, headers, le, name="Dropped")
        approver = await _approver(company_id)

        await _closed_period(
            company_id=company_id,
            legal_entity_id=le,
            start="2026-08-01",
            end="2026-08-31",
            paid_days={steady: "31", dropped: "31"},
            days_in_month=31,
        )
        august = await _create_run(client, headers, le, "2026-08")
        august = await _action(client, headers, august, "lock-inputs")
        august = await _action(client, headers, august, "compute")
        assert august["previous_pay_run_id"] is None
        august = await _action(client, approver, august, "approve")
        august = await _action(client, approver, august, "finalise")

        await _closed_period(
            company_id=company_id,
            legal_entity_id=le,
            start="2026-09-01",
            end="2026-09-30",
            paid_days={steady: "30", dropped: "15"},
            days_in_month=30,
        )
        september = await _create_run(client, headers, le, "2026-09")
        september = await _action(client, headers, september, "lock-inputs")
        september = await _action(client, headers, september, "compute")
        assert september["previous_pay_run_id"] == august["id"]
        assert september["variance_threshold_percent"] == "15"
        assert september["variance_flag_count"] == 1
        assert september["variance_open_count"] == 1

        employees = await _employees(client, headers, september["id"])
        assert employees[steady]["variance_flagged"] is False
        assert employees[dropped]["variance_flagged"] is True
        assert employees[dropped]["variance_percent"] == "-50"

        blocked = await _action(client, approver, september, "approve", expect=409)
        reasons = blocked["details"][0]["context"]["reasons"]
        assert [r["code"] for r in reasons] == ["VARIANCE_UNACKNOWLEDGED"]

        acknowledged = await client.post(
            f"/v1/payroll/pay-runs/{september['id']}/employees/{dropped}/acknowledge-variance",
            headers=headers,
            json={"reason": "Unpaid leave for half the month"},
        )
        assert acknowledged.status_code == 200, acknowledged.text
        assert acknowledged.json()["data"]["variance_reason"] == "Unpaid leave for half the month"

        september = (
            await client.get(f"/v1/payroll/pay-runs/{september['id']}", headers=headers)
        ).json()["data"]
        assert september["variance_open_count"] == 0
        # Recomputing with the same result keeps the acknowledgement.
        september = await _action(client, headers, september, "compute")
        assert september["variance_open_count"] == 0

        september = await _action(client, approver, september, "approve")
        assert september["status"] == "APPROVED"
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_reopened_attendance_invalidates_the_snapshot(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Decision 15 allows reopening before payroll is finalised — but the run's snapshot is then
    stale, so approval refuses until the inputs are locked again."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        period_id = await _closed_period(
            company_id=company_id,
            legal_entity_id=le,
            start="2026-09-01",
            end="2026-09-30",
            paid_days={employee: "30"},
            days_in_month=30,
        )
        run = await _create_run(client, headers, le, "2026-09")
        run = await _action(client, headers, run, "lock-inputs")
        run = await _action(client, headers, run, "compute")

        period = await client.get(f"/v1/attendance-periods/{period_id}", headers=headers)
        reopened = await client.post(
            f"/v1/attendance-periods/{period_id}/reopen",
            headers={**headers, "If-Match": str(period.json()["data"]["version"])},
            json={"reason": "Correction before payroll"},
        )
        assert reopened.status_code == 200, reopened.text

        changed = await _action(client, await _approver(company_id), run, "approve", expect=409)
        assert changed["code"] == "PAY_RUN_ATTENDANCE_CHANGED"
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_pay_run_permissions(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        viewer, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=["EMPLOYEE.VIEW"], data_scope="COMPANY"
        )
        listed = await client.get("/v1/payroll/pay-runs", headers=viewer)
        assert listed.status_code == 403, listed.text

        settings = await client.get("/v1/payroll/settings", headers=headers)
        assert settings.status_code == 200, settings.text
        assert settings.json()["data"]["variance_threshold_percent"] == "15"
        updated = await client.put(
            "/v1/payroll/settings",
            headers={**headers, "If-Match": str(settings.json()["data"]["version"])},
            json={"variance_threshold_percent": "10"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["variance_threshold_percent"] == "10"
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_overtime_and_leave_encashment_are_paid(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """D3 — approved OT not taken as comp-off, at the multiplier of the day's OT policy version;
    D4 — leave encashment entries effective in the month."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        period_id = await _closed_period(
            company_id=company_id,
            legal_entity_id=le,
            start="2026-09-01",
            end="2026-09-30",
            paid_days={employee: "30"},
            days_in_month=30,
        )
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            params = {"cid": str(company_id), "eid": employee, "pid": period_id}
            policy_id = (
                await session.execute(
                    text(
                        "INSERT INTO overtime_policy (id, company_id, name) "
                        "VALUES (gen_random_uuid(), :cid, 'OT') RETURNING id"
                    ),
                    params,
                )
            ).scalar_one()
            version_id = (
                await session.execute(
                    text(
                        "INSERT INTO overtime_policy_version (id, company_id, policy_id, status, "
                        "effective_from) VALUES (gen_random_uuid(), :cid, :policy, 'PUBLISHED', "
                        "'2026-01-01') RETURNING id"
                    ),
                    {**params, "policy": policy_id},
                )
            ).scalar_one()
            await session.execute(
                text(
                    "INSERT INTO overtime_policy_rate_row (company_id, policy_version_id, "
                    "day_class, classification_code, multiplier_decimal) "
                    "VALUES (:cid, :version, 'NORMAL', 'OT_2X', 2)"
                ),
                {**params, "version": version_id},
            )
            for day, minutes, comp_off, day_class in (
                ("2026-09-10", 120, 0, "NORMAL"),  # paid at 2×
                ("2026-09-11", 60, 60, "NORMAL"),  # taken as comp-off — never paid
                ("2026-09-12", 30, 0, "HOLIDAY"),  # no multiplier configured — an error
            ):
                await session.execute(
                    text(
                        """
                        INSERT INTO attendance_day
                          (id, company_id, employee_id, attendance_date, attendance_status,
                           timezone, ot_minutes_approved, comp_off_minutes_earned, ot_day_class,
                           overtime_policy_version_id, is_locked, locked_period_id)
                        VALUES (gen_random_uuid(), :cid, :eid, :day, 'PRESENT', 'UTC', :minutes,
                                :comp_off, :day_class, :version, true, :pid)
                        """
                    ),
                    {
                        **params,
                        "day": datetime.fromisoformat(day).date(),
                        "minutes": minutes,
                        "comp_off": comp_off,
                        "day_class": day_class,
                        "version": version_id,
                    },
                )
            leave_type_id = (
                await session.execute(
                    text(
                        "INSERT INTO leave_type (id, company_id, code, name) "
                        "VALUES (gen_random_uuid(), :cid, 'EL', 'Earned leave') RETURNING id"
                    ),
                    params,
                )
            ).scalar_one()
            await session.execute(
                text(
                    "INSERT INTO leave_ledger (id, company_id, employee_id, leave_type_id, "
                    "entry_type, amount, effective_date) VALUES (gen_random_uuid(), :cid, :eid, "
                    ":lt, 'ENCASHMENT', -2, '2026-09-15')"
                ),
                {**params, "lt": leave_type_id},
            )
            await session.commit()

        run = await _create_run(client, headers, le, "2026-09")
        run = await _action(client, headers, run, "lock-inputs")
        run = await _action(client, headers, run, "compute")
        detail = (
            await client.get(
                f"/v1/payroll/pay-runs/{run['id']}/employees/{employee}", headers=headers
            )
        ).json()["data"]
        lines = {line["component_code"]: line for line in detail["lines"]}
        # Basic ₹30,000 ÷ (30 × 8 h) = ₹125/h; 2 h × 2.0 = ₹500.
        assert lines["OVERTIME"]["amount_minor"] == 50_000
        assert [p["minutes"] for p in lines["OVERTIME"]["trace"]["parts"]] == [120]
        # ₹30,000 ÷ 30 = ₹1,000 a day × 2 days.
        assert lines["LEAVE_ENCASHMENT"]["amount_minor"] == 200_000
        assert detail["net_minor"] == 6_000_000 + 50_000 + 200_000
        assert {i["code"] for i in detail["issues"]} == {"OT_MULTIPLIER_MISSING"}
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
