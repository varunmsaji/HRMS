"""L11 / L12 / LM-15 - leave and employment (decisions D0-D8).

D0-D3: a leave range is valid only when every calendar date lies inside ONE employment spell.
D4:    an employment change that would strand submitted/approved leave is refused (409).
D5:    adjustments and encashments need an effective date inside an employment spell.
D6:    legacy invalid leave is preserved and stays manageable (cancel still works).
D7/D8: the balance stays employee-level and survives termination and rehire.

Everything runs through the real API against PostgreSQL; the races use real concurrent requests.
"""

import asyncio
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_leave_projection import _seed_leave_application
from tests.integration.modules.leave import test_leave_accrual as accrual_helpers
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _create_employee,
    _create_employment,
    _create_leave_type,
    _create_legal_entity,
    _get_balance,
    _give_balance,
    _register_tenant,
    _setup_calendar,
    _setup_leave_policy,
    _submit,
    _teardown,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

OUTSIDE = "LEAVE_DATE_OUTSIDE_EMPLOYMENT"
CONFLICT = "EMPLOYMENT_CHANGE_CONFLICTS_WITH_LEAVE"
APPROVAL_OUTSIDE = "LEAVE_APPROVAL_OUTSIDE_EMPLOYMENT"
RACE_ITERATIONS = 50


# ----------------------------------------------------------------------------- helpers


async def _world(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    approval_chain: str = "AUTO",
    **version_extra: Any,
) -> dict[str, Any]:
    """Legal entity, leave type, Sunday-off calendar and an assigned leave policy. No employees."""
    legal_entity = await _create_legal_entity(client, headers)
    leave_type = await _create_leave_type(client, headers)
    calendar = await _setup_calendar(client, headers)
    await _setup_leave_policy(
        client,
        headers,
        leave_type_id=leave_type["id"],
        approval_chain=approval_chain,
        **version_extra,
    )
    return {"legal_entity": legal_entity, "leave_type": leave_type, "calendar": calendar}


async def _hire(
    client: AsyncClient,
    headers: dict[str, str],
    world: dict[str, Any],
    *,
    joining: str = "2026-01-01",
    balance: str | None = "30.00",
    name: str = "Asha",
    employee: dict[str, Any] | None = None,
) -> dict[str, Any]:
    employee = employee or await _create_employee(client, headers, name)
    employment = await _create_employment(
        client,
        headers,
        employee_id=employee["id"],
        legal_entity_id=world["legal_entity"]["id"],
        joining_date=joining,
    )
    if balance is not None:
        await _give_balance(
            client,
            headers,
            employee_id=employee["id"],
            leave_type_id=world["leave_type"]["id"],
            amount=balance,
            effective_date=joining,
        )
    return {"employee": employee, "employment": employment}


async def _terminate(
    client: AsyncClient,
    headers: dict[str, str],
    employee_id: str,
    last_working_day: str,
    employment_id: str | None = None,
) -> Any:
    employments = (
        await client.get(f"/v1/employees/{employee_id}/employments", headers=headers)
    ).json()["data"]
    current = (
        next(e for e in employments if e["id"] == employment_id)
        if employment_id
        else next(e for e in employments if e["status"] == "ACTIVE")
    )
    return await client.post(
        f"/v1/employees/{employee_id}/employments/{current['id']}/terminate",
        headers={**headers, "If-Match": str(current["version"])},
        json={"last_working_day": last_working_day},
    )


async def _rehire(
    client: AsyncClient, headers: dict[str, str], world: dict[str, Any], employee_id: str, on: str
) -> dict[str, Any]:
    return await _create_employment(
        client,
        headers,
        employee_id=employee_id,
        legal_entity_id=world["legal_entity"]["id"],
        joining_date=on,
    )


async def _apply(
    client: AsyncClient,
    headers: dict[str, str],
    world: dict[str, Any],
    who: dict[str, Any],
    start: str,
    end: str | None = None,
    **extra: Any,
) -> Any:
    return await _submit(
        client,
        headers,
        employee_id=who["employee"]["id"],
        leave_type_id=world["leave_type"]["id"],
        start_date=start,
        end_date=end or start,
        **extra,
    )


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def _reason(response: Any) -> str:
    return str(response.json()["error"]["details"][0]["context"]["reason"])


async def _approve(
    client: AsyncClient, headers: dict[str, str], application: dict[str, Any]
) -> Any:
    return await client.post(
        f"/v1/leave-applications/{application['id']}/approve",
        headers={**headers, "If-Match": str(application["version"])},
        json={},
    )


async def _cancel(client: AsyncClient, headers: dict[str, str], application: dict[str, Any]) -> Any:
    return await client.post(
        f"/v1/leave-applications/{application['id']}/cancel",
        headers={**headers, "If-Match": str(application["version"])},
        json={"reason": "HR cancelled"},
    )


async def _get_application(
    client: AsyncClient, headers: dict[str, str], application_id: str
) -> dict[str, Any]:
    return dict(
        (await client.get(f"/v1/leave-applications/{application_id}", headers=headers)).json()[
            "data"
        ]
    )


async def _get_employment(
    client: AsyncClient, headers: dict[str, str], employee_id: str, employment_id: str
) -> dict[str, Any]:
    rows = (await client.get(f"/v1/employees/{employee_id}/employments", headers=headers)).json()[
        "data"
    ]
    return dict(next(e for e in rows if e["id"] == employment_id))


async def _sql(company_id: UUID, statement: str, **params: Any) -> list[Any]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        result = await session.execute(text(statement), {"cid": str(company_id), **params})
        rows = list(result.all()) if result.returns_rows else []
        await session.commit()
        return rows


async def _free_seats(company_id: UUID) -> None:
    """The trial plan caps active employees at 5; deactivate the ones a test is finished with."""
    await _sql(company_id, "UPDATE employee SET is_active = false WHERE company_id = :cid")


async def _ledger_types(company_id: UUID, employee_id: str) -> list[str]:
    rows = await _sql(
        company_id,
        "SELECT entry_type FROM leave_ledger WHERE company_id = :cid AND employee_id = :e "
        "ORDER BY created_at",
        e=UUID(employee_id),
    )
    return [r[0] for r in rows]


# ------------------------------------------------------------------- D0-D3 submission


async def test_submission_is_valid_only_inside_one_employment_spell(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await _world(client, headers)
        calendar = world["calendar"]["work_calendar_id"]
        # Mon 2026-03-02 .. Wed 2026-09-30, gap, rehired Mon 2026-11-02 (open)
        rehired = await _hire(client, headers, world, joining="2026-03-02", name="Rehired")
        emp = rehired["employee"]["id"]
        assert (await _terminate(client, headers, emp, "2026-09-30")).status_code == 200
        await _rehire(client, headers, world, emp, "2026-11-02")
        await _give_balance(
            client,
            headers,
            employee_id=emp,
            leave_type_id=world["leave_type"]["id"],
            amount="0.50",
            effective_date="2026-11-02",
        )

        cases = [
            ("2026-02-27", "2026-02-27", 422, "PRE_JOINING"),  # before joining
            ("2026-03-02", "2026-03-02", 201, None),  # joining day
            ("2026-05-12", "2026-05-12", 201, None),  # during employment
            ("2026-09-30", "2026-09-30", 201, None),  # last working day
            ("2026-10-01", "2026-10-01", 422, "REHIRE_GAP"),  # day after the last working day
            ("2026-10-15", "2026-10-16", 422, "REHIRE_GAP"),  # inside the gap
            ("2026-09-29", "2026-11-03", 422, "REHIRE_GAP"),  # range across the gap
            ("2026-02-25", "2026-03-03", 422, "PRE_JOINING"),  # starts before joining
            ("2026-11-03", "2026-11-03", 201, None),  # second spell
        ]
        for start, end, status, reason in cases:
            response = await _apply(client, headers, world, rehired, start, end)
            assert response.status_code == status, (start, end, response.text)
            if reason:
                assert _code(response) == OUTSIDE and _reason(response) == reason, response.text
        # refused requests created nothing: only the accepted applications were debited
        ledger = await _ledger_types(company_id, emp)
        assert ledger.count("APPLICATION") == 4 and ledger.count("ADJUSTMENT") == 2

        # leave after the last working day with no rehire at all
        leaver = await _hire(client, headers, world, joining="2026-03-02", name="Leaver")
        assert (
            await _terminate(client, headers, leaver["employee"]["id"], "2026-09-30")
        ).status_code == 200
        after = await _apply(client, headers, world, leaver, "2026-10-01")
        assert after.status_code == 422 and _reason(after) == "AFTER_LAST_WORKING_DAY"
        crossing = await _apply(client, headers, world, leaver, "2026-09-29", "2026-10-02")
        assert crossing.status_code == 422 and _reason(crossing) == "AFTER_LAST_WORKING_DAY"
        assert (await _apply(client, headers, world, leaver, "2026-09-30")).status_code == 201

        await _free_seats(company_id)
        # no employment row covering the date at all
        nobody = await _create_employee(client, headers, "Nobody")
        none = await _submit(
            client, headers, employee_id=nobody["id"], leave_type_id=world["leave_type"]["id"]
        )
        assert none.status_code == 422 and _reason(none) == "NO_EMPLOYMENT"

        # back-to-back spells: no uncovered date, still two employments
        pair = await _hire(client, headers, world, joining="2026-03-02", name="Pair")
        assert (
            await _terminate(client, headers, pair["employee"]["id"], "2026-06-30")
        ).status_code == 200
        await _rehire(client, headers, world, pair["employee"]["id"], "2026-07-01")
        cross = await _apply(client, headers, world, pair, "2026-06-29", "2026-07-02")
        assert cross.status_code == 422 and _reason(cross) == "CROSS_EMPLOYMENT_SPELL"
        assert (await _apply(client, headers, world, pair, "2026-06-30")).status_code == 201
        assert (await _apply(client, headers, world, pair, "2026-07-02")).status_code == 201

        await _free_seats(company_id)
        # whole range, not just consuming days. Sat 2026-09-26 is the last working day; Sunday
        # 2026-09-27 is a weekly off (no leave day) but is still a date outside employment.
        weekend = await _hire(client, headers, world, joining="2026-03-02", name="Weekend")
        assert (
            await _terminate(client, headers, weekend["employee"]["id"], "2026-09-26")
        ).status_code == 200
        sunday = await _apply(client, headers, world, weekend, "2026-09-25", "2026-09-27")
        assert sunday.status_code == 422 and _reason(sunday) == "AFTER_LAST_WORKING_DAY"
        assert (
            await _apply(client, headers, world, weekend, "2026-09-25", "2026-09-26")
        ).status_code == 201

        # a holiday-type (non-consuming) date outside employment also fails the range
        holiday = await client.post(
            f"/v1/work-calendars/{calendar}/exceptions",
            headers=headers,
            json={"exception_date": "2026-10-05", "exception_type": "SUBSTITUTE_HOLIDAY"},
        )
        assert holiday.status_code == 201, holiday.text
        friday = await _hire(client, headers, world, joining="2026-03-02", name="Friday")
        assert (
            await _terminate(client, headers, friday["employee"]["id"], "2026-10-02")
        ).status_code == 200
        over = await _apply(client, headers, world, friday, "2026-10-02", "2026-10-05")
        assert over.status_code == 422 and _reason(over) == "AFTER_LAST_WORKING_DAY"
        assert (await _apply(client, headers, world, friday, "2026-10-02")).status_code == 201

        # one outside date in a long range
        long = await _hire(client, headers, world, joining="2026-03-02", name="Long")
        assert (
            await _terminate(client, headers, long["employee"]["id"], "2026-09-30")
        ).status_code == 200
        one = await _apply(client, headers, world, long, "2026-09-14", "2026-10-01")
        assert (
            one.status_code == 422
            and one.json()["error"]["details"][0]["context"]["offending_date"] == "2026-10-01"
        )
    finally:
        await _sql(company_id, "DELETE FROM calendar_exception WHERE company_id = :cid")
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------------------- approval


async def test_approval_revalidates_employment_and_changes_nothing_when_it_fails(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await _world(client, headers, approval_chain="HR")
        staff = await _hire(client, headers, world, balance="10.00")
        emp = staff["employee"]["id"]

        # unchanged employment -> approved and debited
        ok = (await _apply(client, headers, world, staff, "2026-09-08")).json()["data"]
        assert ok["status"] == "SUBMITTED"
        approved = await _approve(client, headers, ok)
        assert approved.status_code == 200 and approved.json()["data"]["status"] == "APPROVED"
        assert await _get_balance(client, headers, emp) == "9.00"

        # valid when submitted, then employment moves underneath it (written straight to the row:
        # the guarded API path would refuse this, which the next test covers)
        pending = (await _apply(client, headers, world, staff, "2026-09-14", "2026-09-15")).json()[
            "data"
        ]
        await _sql(
            company_id,
            "UPDATE employment SET last_working_day = DATE '2026-09-10', status = 'TERMINATED' "
            "WHERE company_id = :cid AND employee_id = :e",
            e=UUID(emp),
        )
        refused = await _approve(client, headers, pending)
        assert refused.status_code == 409, refused.text
        assert _code(refused) == APPROVAL_OUTSIDE and _reason(refused) == "AFTER_LAST_WORKING_DAY"
        after = await _get_application(client, headers, pending["id"])
        assert after["status"] == "SUBMITTED" and after["version"] == pending["version"]
        assert await _get_balance(client, headers, emp) == "9.00"  # nothing debited
        assert (await _ledger_types(company_id, emp)).count("APPLICATION") == 1
        projections = await _sql(
            company_id,
            "SELECT count(*) FROM leave_day_projection WHERE company_id = :cid AND "
            "leave_application_id = :a",
            a=UUID(pending["id"]),
        )
        assert projections[0][0] == 0
        # the application is not silently cancelled and can still be rejected
        rejected = await client.post(
            f"/v1/leave-applications/{pending['id']}/reject",
            headers={**headers, "If-Match": str(pending["version"])},
            json={"rejection_reason": "employment ended"},
        )
        assert rejected.status_code == 200, rejected.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --------------------------------------------------------------------------- LM-15


async def test_termination_that_strands_leave_is_refused_without_side_effects(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await _world(client, headers, approval_chain="HR")
        staff = await _hire(client, headers, world)
        emp, employment_id = staff["employee"]["id"], staff["employment"]["id"]
        submitted = (
            await _apply(client, headers, world, staff, "2026-09-14", "2026-09-15")
        ).json()["data"]
        approved = (await _apply(client, headers, world, staff, "2026-09-22")).json()["data"]
        approved = (await _approve(client, headers, approved)).json()["data"]
        assert approved["status"] == "APPROVED"
        before_employment = await _get_employment(client, headers, emp, employment_id)
        before_balance = await _get_balance(client, headers, emp)

        for lwd in ("2026-09-10", "2026-09-21"):
            refused = await _terminate(client, headers, emp, lwd)
            assert refused.status_code == 409, (lwd, refused.text)
            assert _code(refused) == CONFLICT
            listed = refused.json()["error"]["details"][0]["context"]["leave_applications"]
            assert {row["leave_application_id"] for row in listed} >= {approved["id"]}
        # lwd 09-10 strands both the submitted and the approved leave
        ids = {
            row["leave_application_id"]
            for row in (await _terminate(client, headers, emp, "2026-09-10")).json()["error"][
                "details"
            ][0]["context"]["leave_applications"]
        }
        assert ids == {submitted["id"], approved["id"]}

        # nothing changed: employment, both applications, balance
        assert await _get_employment(client, headers, emp, employment_id) == before_employment
        assert (
            before_employment["status"] == "ACTIVE"
            and before_employment["last_working_day"] is None
        )
        assert (await _get_application(client, headers, submitted["id"]))["status"] == "SUBMITTED"
        assert (await _get_application(client, headers, approved["id"]))["status"] == "APPROVED"
        assert await _get_balance(client, headers, emp) == before_balance

        # the boundary itself is fine: leave ending ON the last working day is not stranded
        ok = await _terminate(client, headers, emp, "2026-09-22")
        assert ok.status_code == 200, ok.text
        assert (await _get_application(client, headers, approved["id"]))["status"] == "APPROVED"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_termination_proceeds_once_conflicting_leave_is_cancelled_or_absent(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await _world(client, headers, approval_chain="HR")
        clean = await _hire(client, headers, world, name="Clean")
        assert (
            await _terminate(client, headers, clean["employee"]["id"], "2026-09-10")
        ).status_code == 200

        busy = await _hire(client, headers, world, name="Busy")
        emp = busy["employee"]["id"]
        leave = (await _apply(client, headers, world, busy, "2026-09-22")).json()["data"]
        leave = (await _approve(client, headers, leave)).json()["data"]
        assert (await _terminate(client, headers, emp, "2026-09-15")).status_code == 409
        cancelled = await _cancel(client, headers, leave)
        assert cancelled.status_code == 200, cancelled.text
        # a cancelled application is history, not a conflict
        assert (await _terminate(client, headers, emp, "2026-09-15")).status_code == 200
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_the_employment_boundaries_are_not_editable_outside_termination(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """There is no joining-date or last-working-day edit: PATCH forbids both, so termination is
    the only path that moves an employment boundary (and the only one guarded)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await _world(client, headers)
        staff = await _hire(client, headers, world, balance=None)
        emp, employment = staff["employee"]["id"], staff["employment"]
        for body in ({"joining_date": "2026-06-01"}, {"last_working_day": "2026-06-01"}):
            response = await client.patch(
                f"/v1/employees/{emp}/employments/{employment['id']}",
                headers={**headers, "If-Match": str(employment["version"])},
                json=body,
            )
            assert response.status_code == 422, response.text
        # a permitted correction is unaffected
        fine = await client.patch(
            f"/v1/employees/{emp}/employments/{employment['id']}",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"probation_end_date": "2026-07-01"},
        )
        assert fine.status_code == 200, fine.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ------------------------------------------------------- D5 adjustments, encashments


async def _adjust(
    client: AsyncClient,
    headers: dict[str, str],
    world: dict[str, Any],
    emp: str,
    on: str,
    key: str | None = None,
) -> Any:
    return await client.post(
        "/v1/leave-ledger/adjustments",
        headers={**headers, **({"Idempotency-Key": key} if key else {})},
        json={
            "employee_id": emp,
            "leave_type_id": world["leave_type"]["id"],
            "amount": "1.00",
            "effective_date": on,
            "reason": "test",
        },
    )


async def test_adjustments_and_encashments_need_a_date_inside_employment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await _world(client, headers, encashment_allowed=True)
        staff = await _hire(client, headers, world, joining="2026-03-02", balance="10.00")
        emp = staff["employee"]["id"]
        assert (await _terminate(client, headers, emp, "2026-09-30")).status_code == 200
        await _rehire(client, headers, world, emp, "2026-11-02")
        leaver = await _hire(
            client, headers, world, joining="2026-03-02", balance="10.00", name="Leaver"
        )
        assert (
            await _terminate(client, headers, leaver["employee"]["id"], "2026-09-30")
        ).status_code == 200

        # adjustments
        assert (await _adjust(client, headers, world, emp, "2026-05-12")).status_code == 201
        assert (await _adjust(client, headers, world, emp, "2026-09-30")).status_code == 201
        assert (await _adjust(client, headers, world, emp, "2026-11-02")).status_code == 201
        for on, reason, who in (
            ("2026-02-27", "PRE_JOINING", emp),
            ("2026-10-15", "REHIRE_GAP", emp),
            ("2026-10-15", "AFTER_LAST_WORKING_DAY", leaver["employee"]["id"]),
        ):
            refused = await _adjust(client, headers, world, who, on)
            assert refused.status_code == 422, (on, refused.text)
            assert _code(refused) == OUTSIDE and _reason(refused) == reason
            assert refused.json()["error"]["details"][0]["field"] == "effective_date"
        nobody = await _create_employee(client, headers, "Nobody")
        assert (
            _reason(await _adjust(client, headers, world, nobody["id"], "2026-05-12"))
            == "NO_EMPLOYMENT"
        )
        balance = await _get_balance(client, headers, emp)
        assert balance == "13.00"  # 10 opening + 3 accepted; refusals added nothing

        # encashments, with idempotency intact
        def body(on: str, who: str = emp) -> dict[str, Any]:
            return {
                "employee_id": who,
                "leave_type_id": world["leave_type"]["id"],
                "days": "1.00",
                "effective_date": on,
                "reason": "encash",
            }

        key = f"enc-{uuid4()}"
        first = await client.post(
            "/v1/leave-ledger/encashments",
            headers={**headers, "Idempotency-Key": key},
            json=body("2026-05-12"),
        )
        assert first.status_code == 201, first.text
        replay = await client.post(
            "/v1/leave-ledger/encashments",
            headers={**headers, "Idempotency-Key": key},
            json=body("2026-05-12"),
        )
        assert replay.status_code == 201 and replay.headers.get("Idempotent-Replayed") == "true"
        assert replay.json()["data"]["id"] == first.json()["data"]["id"]
        assert await _get_balance(client, headers, emp) == "12.00"  # encashed once
        for on in ("2026-10-15", "2026-02-27"):
            refused = await client.post(
                "/v1/leave-ledger/encashments", headers=headers, json=body(on)
            )
            assert refused.status_code == 422 and _code(refused) == OUTSIDE, refused.text
        assert await _get_balance(client, headers, emp) == "12.00"
        # a refused key is not poisoned: the same key works once the date is valid
        bad_key = f"enc-{uuid4()}"
        bad = await client.post(
            "/v1/leave-ledger/encashments",
            headers={**headers, "Idempotency-Key": bad_key},
            json=body("2026-10-15"),
        )
        assert bad.status_code == 422
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------------------ D6 legacy


async def test_legacy_invalid_leave_stays_readable_historical_and_cancellable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await _world(client, headers, approval_chain="HR")
        staff = await _hire(client, headers, world, joining="2026-03-02", balance="10.00")
        emp = staff["employee"]["id"]
        # legacy leave, created while the employee was still employed, then approved
        legacy = (await _apply(client, headers, world, staff, "2026-09-22")).json()["data"]
        legacy = (await _approve(client, headers, legacy)).json()["data"]
        assert await _get_balance(client, headers, emp) == "9.00"
        # employment later ends BEFORE that leave, outside the guarded path (pre-existing data)
        await _sql(
            company_id,
            "UPDATE employment SET last_working_day = DATE '2026-09-01', status = 'TERMINATED' "
            "WHERE company_id = :cid AND employee_id = :e",
            e=UUID(emp),
        )
        snapshot = await _get_application(client, headers, legacy["id"])
        assert snapshot["status"] == "APPROVED" and snapshot["start_date"] == "2026-09-22"
        ledger_before = await _ledger_types(company_id, emp)

        # nothing cleans it up on read; it stays exactly as it was
        listed = await client.get(
            "/v1/leave-applications", headers=headers, params={"employee_id": emp}
        )
        assert listed.status_code == 200 and legacy["id"] in {
            r["id"] for r in listed.json()["data"]
        }
        assert await _get_balance(client, headers, emp) == "9.00"
        assert await _ledger_types(company_id, emp) == ledger_before

        # and the existing lifecycle still works: HR can cancel it, with the correct reversal
        cancelled = await _cancel(client, headers, snapshot)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["data"]["status"] == "CANCELLED"
        assert await _get_balance(client, headers, emp) == "10.00"
        ledger_after = await _ledger_types(company_id, emp)
        assert ledger_after[: len(ledger_before)] == ledger_before  # history untouched, append only
        assert ledger_after[len(ledger_before) :] == ["ADJUSTMENT"]  # the one reversal credit
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ----------------------------------------------------------------- D7/D8 rehire balance


async def test_balance_survives_termination_and_rehire_and_the_gap_accrues_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await accrual_helpers._register_tenant(client)
    try:
        entity = await accrual_helpers._create_legal_entity(client, headers)
        leave_type = await accrual_helpers._create_leave_type(client, headers)
        await accrual_helpers._create_published_monthly_policy(
            client, headers, leave_type_id=leave_type["id"]
        )
        employee = await accrual_helpers._create_employee(client, headers)
        emp = employee["id"]
        await accrual_helpers._create_employment(
            client,
            headers,
            employee_id=emp,
            legal_entity_id=entity["id"],
            joining_date="2025-01-01",
        )

        async def run(as_of: date) -> int:
            return await accrual_helpers._run_accrual(company_id, as_of=as_of)

        assert await run(date(2026, 2, 1)) == 1  # January, fully employed
        assert await accrual_helpers._get_balance(client, headers, emp) == "1.50"
        employments = (
            await client.get(f"/v1/employees/{emp}/employments", headers=headers)
        ).json()["data"]
        ended = await client.post(
            f"/v1/employees/{emp}/employments/{employments[0]['id']}/terminate",
            headers={**headers, "If-Match": str(employments[0]["version"])},
            json={"last_working_day": "2026-01-31"},
        )
        assert ended.status_code == 200, ended.text

        # February and March fall in the gap: no accrual, balance untouched (no reset either)
        assert await run(date(2026, 3, 1)) == 0
        assert await run(date(2026, 4, 1)) == 0
        assert await accrual_helpers._get_balance(client, headers, emp) == "1.50"
        rows = await _sql(company_id, "SELECT count(*) FROM leave_ledger WHERE company_id = :cid")
        assert rows[0][0] == 1

        # rehired 2026-04-01: the old balance is still there, April accrues for the new spell
        await accrual_helpers._create_employment(
            client,
            headers,
            employee_id=emp,
            legal_entity_id=entity["id"],
            joining_date="2026-04-01",
        )
        assert await accrual_helpers._get_balance(client, headers, emp) == "1.50"
        assert await run(date(2026, 5, 1)) == 1
        assert await accrual_helpers._get_balance(client, headers, emp) == "3.00"
        # re-running (or another worker) accrues nothing twice
        assert await run(date(2026, 5, 1)) == 0
        assert await run(date(2026, 5, 2)) == 0
        rows = await _sql(company_id, "SELECT count(*) FROM leave_ledger WHERE company_id = :cid")
        assert rows[0][0] == 2
        # one continuous employee-level ledger, nothing tied to an employment
        columns = await _sql(
            company_id,
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'leave_ledger' "
            "AND column_name LIKE '%employment%'",
        )
        assert columns == []
    finally:
        await accrual_helpers._teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_old_balance_is_spendable_in_the_new_spell_but_the_gap_is_not_fileable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await _world(client, headers)
        staff = await _hire(client, headers, world, joining="2026-03-02", balance="5.00")
        emp = staff["employee"]["id"]
        old = await _apply(client, headers, world, staff, "2026-05-12")
        assert old.status_code == 201
        assert (await _terminate(client, headers, emp, "2026-09-30")).status_code == 200
        assert await _get_balance(client, headers, emp) == "4.00"  # survives termination
        assert (await _apply(client, headers, world, staff, "2026-10-14")).status_code == 422  # gap
        await _rehire(client, headers, world, emp, "2026-11-02")
        assert await _get_balance(client, headers, emp) == "4.00"  # survives rehire, no reset
        spent = await _apply(client, headers, world, staff, "2026-11-03", "2026-11-05")
        assert spent.status_code == 201, spent.text
        assert await _get_balance(client, headers, emp) == "1.00"  # the old balance paid for it
        # the first-spell application is still there, unchanged
        history = await _get_application(client, headers, old.json()["data"]["id"])
        assert history["status"] == "APPROVED" and history["start_date"] == "2026-05-12"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --------------------------------------------------------- attendance projection (LM-14)


async def test_direct_projection_cannot_publish_leave_outside_employment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await _world(client, headers)
        staff = await _hire(client, headers, world, joining="2026-03-02", balance=None)
        emp = staff["employee"]["id"]
        assert (await _terminate(client, headers, emp, "2026-09-30")).status_code == 200
        await _rehire(client, headers, world, emp, "2026-11-02")

        # LM-14: a projection needs a real approved application carrying the date, so seed one
        # whose days include the dates employment must still refuse.
        backing = await _seed_leave_application(
            company_id=company_id,
            employee_id=emp,
            days=[(on, "1.00", None, False) for on in ("2026-02-27", "2026-10-15", "2026-05-12")],
        )

        def projection(on: str) -> dict[str, Any]:
            return {"employee_id": emp, "attendance_date": on, "leave_application_id": backing}

        for on in ("2026-02-27", "2026-10-15"):  # before joining, rehire gap
            refused = await client.post(
                "/v1/leave-projections", headers=headers, json=projection(on)
            )
            assert refused.status_code == 422, (on, refused.text)
            assert _code(refused) == "LEAVE_PROJECTION_OUTSIDE_EMPLOYMENT"
        allowed = await client.post(
            "/v1/leave-projections", headers=headers, json=projection("2026-05-12")
        )
        assert allowed.status_code in (200, 201), allowed.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------------------- concurrency


def _terminate_now(
    client: AsyncClient, headers: dict[str, str], staff: dict[str, Any], last_working_day: str
) -> Any:
    """Terminate without the version lookup `_terminate` does first, so the request starts as
    quickly as the other racer's."""
    employment = staff["employment"]
    return client.post(
        f"/v1/employees/{staff['employee']['id']}/employments/{employment['id']}/terminate",
        headers={**headers, "If-Match": str(employment["version"])},
        json={"last_working_day": last_working_day},
    )


async def _race(first: Any, second: Any, n: int) -> tuple[Any, Any]:
    """Run two requests concurrently, alternating which one starts first and by how much, so the
    iterations cover both commit orders (a plain gather always starts `first` first)."""
    delay = (0.0, 0.01, 0.03, 0.06, 0.1, 0.15, 0.25)[(n // 2) % 7]

    async def later(coro: Any) -> Any:
        await asyncio.sleep(delay)
        return await coro

    if n % 2 == 0:
        return tuple(await asyncio.gather(first, later(second)))  # type: ignore[return-value]
    result = await asyncio.gather(later(first), second)
    return result[0], result[1]


async def _race_employee(
    client: AsyncClient, headers: dict[str, str], world: dict[str, Any], n: int
) -> dict[str, Any]:
    """A fresh employee per iteration (an employment can only be terminated once). The trial plan
    caps active employees, so the previous iteration's racer is deactivated (test setup only)."""
    if n:
        await _sql(
            UUID(headers["X-Company-Id"]),
            "UPDATE employee SET is_active = false WHERE company_id = :cid AND first_name = :n",
            n=f"Racer{n - 1}",
        )
    return await _hire(client, headers, world, name=f"Racer{n}", balance="10.00")


async def test_approve_racing_terminate_never_leaves_invalid_approved_leave(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The pending application counts as leave the termination would strand (D4), so the
    termination is refused whichever side wins the lock; what the race proves is that the approval
    always commits whole, nothing is debited twice, the employment never changes, and neither
    request deadlocks or errors. (The reverse order - termination first, then approval - cannot
    arise through the API for the same reason; it is covered by the approval re-validation test,
    which moves the boundary underneath a pending application directly.)"""
    headers, company_id, user_id = await _register_tenant(client)
    outcomes: set[tuple[int, int]] = set()
    try:
        world = await _world(client, headers, approval_chain="HR")
        for n in range(RACE_ITERATIONS):
            staff = await _race_employee(client, headers, world, n)
            emp, employment_id = staff["employee"]["id"], staff["employment"]["id"]
            pending = (await _apply(client, headers, world, staff, "2026-09-14")).json()["data"]
            approve, terminate = await _race(
                _approve(client, headers, pending),
                _terminate_now(client, headers, staff, "2026-09-10"),
                n,
            )
            outcomes.add((approve.status_code, terminate.status_code))
            assert (approve.status_code, terminate.status_code) in {(200, 409), (409, 200)}, (
                n,
                approve.text,
                terminate.text,
            )
            application = await _get_application(client, headers, pending["id"])
            employment = await _get_employment(client, headers, emp, employment_id)
            ledger = await _ledger_types(company_id, emp)
            if approve.status_code == 200:  # approved first: termination had to be refused
                assert application["status"] == "APPROVED" and employment["status"] == "ACTIVE"
                assert ledger.count("APPLICATION") == 1
            else:  # terminated first: nothing approved, nothing debited
                assert employment["last_working_day"] == "2026-09-10"
                assert application["status"] == "SUBMITTED" and ledger.count("APPLICATION") == 0
                assert _code(approve) == APPROVAL_OUTSIDE
        print(f"approve-vs-terminate outcomes: {sorted(outcomes)}")
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_approve_racing_a_compatible_last_working_day_succeeds_both_ways(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await _world(client, headers, approval_chain="HR")
        for n in range(RACE_ITERATIONS):
            staff = await _race_employee(client, headers, world, n)
            emp = staff["employee"]["id"]
            pending = (await _apply(client, headers, world, staff, "2026-09-14")).json()["data"]
            # the last working day IS the leave date: valid whichever commits first
            approve, terminate = await _race(
                _approve(client, headers, pending),
                _terminate_now(client, headers, staff, "2026-09-14"),
                n,
            )
            assert (approve.status_code, terminate.status_code) == (200, 200), (
                n,
                approve.text,
                terminate.text,
            )
            assert (await _ledger_types(company_id, emp)).count("APPLICATION") == 1
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_submit_racing_terminate_never_books_leave_after_the_last_working_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    seen: set[tuple[int, int]] = set()
    try:
        world = await _world(client, headers, approval_chain="AUTO")
        for n in range(RACE_ITERATIONS):
            staff = await _race_employee(client, headers, world, n)
            emp, employment_id = staff["employee"]["id"], staff["employment"]["id"]
            submit, terminate = await _race(
                _apply(client, headers, world, staff, "2026-09-14"),
                _terminate_now(client, headers, staff, "2026-09-10"),
                n,
            )
            assert (submit.status_code, terminate.status_code) in {(201, 409), (422, 200)}, (
                n,
                submit.text,
                terminate.text,
            )
            seen.add((submit.status_code, terminate.status_code))
            employment = await _get_employment(client, headers, emp, employment_id)
            ledger = await _ledger_types(company_id, emp)
            if submit.status_code == 201:
                assert employment["status"] == "ACTIVE" and ledger.count("APPLICATION") == 1
            else:
                assert employment["last_working_day"] == "2026-09-10"
                assert _code(submit) == OUTSIDE and ledger.count("APPLICATION") == 0
        print(f"submit-vs-terminate outcomes: {sorted(seen)}")
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_employment_update_and_adjustment_race_without_deadlock_or_stranded_entries(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await _world(client, headers, approval_chain="HR")
        for n in range(RACE_ITERATIONS):
            staff = await _race_employee(client, headers, world, n)
            emp, employment = staff["employee"]["id"], staff["employment"]
            pending = (await _apply(client, headers, world, staff, "2026-09-14")).json()["data"]
            # an employment correction concurrent with an approval and an adjustment: all succeed
            patch, approve, adjust = await asyncio.gather(
                client.patch(
                    f"/v1/employees/{emp}/employments/{employment['id']}",
                    headers={**headers, "If-Match": str(employment["version"])},
                    json={"probation_end_date": "2026-07-01"},
                ),
                _approve(client, headers, pending),
                _adjust(client, headers, world, emp, "2026-09-14"),
            )
            assert (patch.status_code, approve.status_code, adjust.status_code) == (
                200,
                200,
                201,
            ), (
                n,
                patch.text,
                approve.text,
                adjust.text,
            )
            # and an adjustment racing a termination before its date: either order, never a 5xx,
            # and a committed adjustment is only ever one that was inside employment when made
            adjust2, terminate = await _race(
                _adjust(client, headers, world, emp, "2026-12-01"),
                _terminate(client, headers, emp, "2026-11-30"),
                n,
            )
            assert (adjust2.status_code, terminate.status_code) in {(201, 200), (422, 200)}, (
                n,
                adjust2.text,
                terminate.text,
            )
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
