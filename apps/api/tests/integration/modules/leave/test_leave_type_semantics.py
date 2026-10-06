"""Decision 11 / LM-04 — a leave type's semantic fields freeze once the type has been used, and a
cancellation reverses exactly what the ledger shows was debited (never what the leave type's
*current* flags say should have been)."""

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.leave.test_leave_application import (
    _create_employee,
    _create_employment,
    _create_leave_type,
    _create_legal_entity,
    _give_balance,
    _register_tenant,
    _setup_calendar,
    _setup_full,
    _setup_leave_policy,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio


async def _patch_type(
    client: AsyncClient, headers: dict[str, str], leave_type: dict[str, Any], **body: Any
) -> Any:
    return await client.patch(
        f"/v1/leave-types/{leave_type['id']}",
        headers={**headers, "If-Match": str(leave_type["version"])},
        json=body,
    )


async def _force_flag(company_id: UUID, leave_type_id: str, **flags: bool) -> None:
    """Flips a flag directly in the database - the state a legacy row could be in, which the API
    now refuses to produce."""
    sets = ", ".join(f"{name} = :{name}" for name in flags)
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(f"UPDATE leave_type SET {sets} WHERE id = CAST(:id AS uuid)"),
            {"id": leave_type_id, **flags},
        )
        await session.commit()


async def _ledger_total(company_id: UUID, employee_id: str, leave_type_id: str) -> Decimal:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        row = await session.execute(
            text(
                "SELECT coalesce(sum(amount), 0) FROM leave_ledger WHERE "
                "employee_id = CAST(:e AS uuid) AND leave_type_id = CAST(:t AS uuid)"
            ),
            {"e": employee_id, "t": leave_type_id},
        )
        return Decimal(row.scalar_one())


async def _entries(company_id: UUID, employee_id: str, entry_type: str) -> int:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        row = await session.execute(
            text(
                "SELECT count(*) FROM leave_ledger WHERE employee_id = CAST(:e AS uuid) "
                "AND entry_type = :t"
            ),
            {"e": employee_id, "t": entry_type},
        )
        return int(row.scalar_one())


async def test_semantic_flags_can_change_before_first_use(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        leave_type = await _create_leave_type(client, headers)
        changed = await _patch_type(
            client,
            headers,
            leave_type,
            requires_balance=False,
            is_paid_default=False,
            is_comp_off=True,
        )
        assert changed.status_code == 200, changed.text
        data = changed.json()["data"]
        assert (data["requires_balance"], data["is_paid_default"], data["is_comp_off"]) == (
            False,
            False,
            True,
        )
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_semantic_flags_are_locked_once_an_application_exists(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR")
        employee_id, leave_type = ctx["employee"]["id"], ctx["leave_type"]
        submitted = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type["id"]
        )
        assert submitted.status_code == 201, submitted.text
        # drop the opening-balance ledger row's effect: the lock must hold on the application alone
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            used = (
                await session.execute(
                    text("SELECT count(*) FROM leave_application WHERE leave_type_id = :t"),
                    {"t": leave_type["id"]},
                )
            ).scalar_one()
        assert used == 1

        for field, value in (
            ("requires_balance", False),
            ("is_comp_off", True),
            ("is_paid_default", False),
        ):
            refused = await _patch_type(client, headers, leave_type, **{field: value})
            assert refused.status_code == 409, refused.text
            body = refused.json()["error"]
            assert body["code"] == "LEAVE_TYPE_IN_USE"
            assert body["details"][0]["field"] == field
        # nothing was rewritten
        fetched = await client.get(f"/v1/leave-types/{leave_type['id']}", headers=headers)
        data = fetched.json()["data"]
        assert data["requires_balance"] is True
        assert data["is_comp_off"] is False
        assert data["is_paid_default"] is True
        assert data["version"] == leave_type["version"]
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_semantic_flags_are_locked_once_a_ledger_entry_exists(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        legal_entity = await _create_legal_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )
        leave_type = await _create_leave_type(client, headers)
        # a ledger entry and no application at all
        await _give_balance(
            client, headers, employee_id=employee["id"], leave_type_id=leave_type["id"]
        )
        refused = await _patch_type(client, headers, leave_type, requires_balance=False)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "LEAVE_TYPE_IN_USE"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_non_semantic_edits_and_unchanged_values_still_work_after_use(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers)
        leave_type = ctx["leave_type"]
        # the same value is not a change; renaming and deactivating are not semantic
        same = await _patch_type(client, headers, leave_type, requires_balance=True)
        assert same.status_code == 200, same.text
        renamed = await client.patch(
            f"/v1/leave-types/{leave_type['id']}",
            headers={**headers, "If-Match": str(same.json()["data"]["version"])},
            json={"name": "Earned Leave (renamed)"},
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["data"]["name"] == "Earned Leave (renamed)"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_cancel_after_requires_balance_was_switched_off_still_restores_the_debit(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The flag is turned off *after* approval (only possible on legacy data now). The old code
    saw `requires_balance=False` at cancel time and skipped the credit, leaving the employee
    short for good."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="AUTO", balance="20.00")
        employee_id, leave_type = ctx["employee"]["id"], ctx["leave_type"]
        approved = (
            await _submit(client, headers, employee_id=employee_id, leave_type_id=leave_type["id"])
        ).json()["data"]
        assert approved["status"] == "APPROVED"
        assert await _ledger_total(company_id, employee_id, leave_type["id"]) == Decimal("19.00")

        await _force_flag(company_id, leave_type["id"], requires_balance=False)

        cancelled = await client.post(
            f"/v1/leave-applications/{approved['id']}/cancel",
            headers={**headers, "If-Match": str(approved["version"])},
            json={"reason": "recalled"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert await _ledger_total(company_id, employee_id, leave_type["id"]) == Decimal("20.00")
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_cancel_after_requires_balance_was_switched_on_does_not_invent_a_credit(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A leave type that never drew a balance is approved, then (legacy data) flagged as
    balance-backed. Its application never debited anything, so cancelling must credit nothing -
    the old code would have minted `total_days` of balance out of nothing."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        legal_entity = await _create_legal_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )
        lop_type = await _create_leave_type(
            client, headers, code="LOP", name="Loss of pay", requires_balance=False
        )
        await _setup_calendar(client, headers)
        await _setup_leave_policy(
            client, headers, leave_type_id=lop_type["id"], approval_chain="AUTO"
        )
        approved = (
            await _submit(client, headers, employee_id=employee["id"], leave_type_id=lop_type["id"])
        ).json()["data"]
        assert approved["status"] == "APPROVED"
        assert await _entries(company_id, employee["id"], "APPLICATION") == 0

        await _force_flag(company_id, lop_type["id"], requires_balance=True)

        cancelled = await client.post(
            f"/v1/leave-applications/{approved['id']}/cancel",
            headers={**headers, "If-Match": str(approved["version"])},
            json={"reason": "recalled"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert await _entries(company_id, employee["id"], "ADJUSTMENT") == 0
        assert await _ledger_total(company_id, employee["id"], lop_type["id"]) == Decimal("0")
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_cancel_credits_only_the_days_that_were_actually_debited(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Two days submitted against a two-day balance, then the balance drops to one day before
    approval, so the second day is approved as LOP. Only one day was debited, so the reversal
    returns one day - never the application's whole `total_days` - and cannot repeat."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR", balance="2.00")
        employee_id, leave_type = ctx["employee"]["id"], ctx["leave_type"]
        application = (
            await _submit(
                client,
                headers,
                employee_id=employee_id,
                leave_type_id=leave_type["id"],
                start_date="2026-09-08",
                end_date="2026-09-09",
            )
        ).json()["data"]
        await _give_balance(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type["id"],
            amount="-1.00",
        )
        approved = await client.post(
            f"/v1/leave-applications/{application['id']}/approve",
            headers={**headers, "If-Match": str(application["version"])},
            json={"excess_as_lop": True},
        )
        assert approved.status_code == 200, approved.text
        data = approved.json()["data"]
        assert Decimal(str(data["lop_days"])) == Decimal("1.00")
        assert await _ledger_total(company_id, employee_id, leave_type["id"]) == Decimal("0.00")

        cancelled = await client.post(
            f"/v1/leave-applications/{application['id']}/cancel",
            headers={**headers, "If-Match": str(data["version"])},
            json={"reason": "recalled"},
        )
        assert cancelled.status_code == 200, cancelled.text
        # 2.00 opening - 1.00 adjustment - 1.00 debit + 1.00 reversal
        assert await _ledger_total(company_id, employee_id, leave_type["id"]) == Decimal("1.00")
        again = await client.post(
            f"/v1/leave-applications/{application['id']}/cancel",
            headers={**headers, "If-Match": str(cancelled.json()["data"]["version"])},
            json={"reason": "again"},
        )
        assert again.status_code == 409, again.text
        assert await _ledger_total(company_id, employee_id, leave_type["id"]) == Decimal("1.00")
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
