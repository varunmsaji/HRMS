"""Comp-off balance safety (`docs/audits/COMPOFF_POLICY_SAFETY_REVIEW.md`) — existing fractional
balances and historical credits are never rewritten, a later overtime-policy version never
changes how an earlier overtime record is credited, and the credit/expiry sweeps are idempotent
under re-runs and concurrent runs.

Same service-layer approach and helpers as `test_leave_comp_off.py`.
"""

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_overtime_record import (
    _cleanup_overtime,
    _create_overtime_policy,
    _get_overtime_record_for_day,
    _ot_calculate_day,
)
from tests.integration.modules.leave.test_leave_comp_off import (
    _adjust,
    _create_leave_type,
    _credit,
    _expire,
    _get_balance,
    _teardown_leave,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave.service import LeaveCompOffService

pytestmark = pytest.mark.asyncio


async def _ledger_rows(company_id: UUID, entry_type: str) -> list[dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text(
                "SELECT amount, reference_id FROM leave_ledger "
                "WHERE company_id = :cid AND entry_type = :et"
            ),
            {"cid": str(company_id), "et": entry_type},
        )
        return [dict(r._mapping) for r in rows]


async def _publish_ot_version(
    client: AsyncClient, headers: dict[str, str], policy_id: str, **overrides: Any
) -> None:
    body: dict[str, Any] = {
        "eligibility": "ALWAYS",
        "min_ot_minutes": 0,
        "approval_chain": "AUTO",
        "requires_post_approval": True,
        "comp_off_instead_of_pay": True,
        **overrides,
    }
    draft = await client.post(
        f"/v1/overtime-policies/{policy_id}/versions", headers=headers, json=body
    )
    assert draft.status_code == 201, draft.text
    published = await client.post(
        f"/v1/overtime-policies/{policy_id}/versions/{draft.json()['data']['id']}/publish",
        headers={**headers, "If-Match": "1"},
        # The first version's row `version` after its own publish.
        json={"expected_previous_version": 2},
    )
    assert published.status_code == 200, published.text


async def _setup_credited(
    client: AsyncClient, headers: dict[str, str], **ot_overrides: Any
) -> tuple[str, dict[str, Any]]:
    """One employee with one AUTO_APPROVED 60-minute comp-off record on 2026-08-10, a comp-off
    leave type, and that record credited (60 / 480 = 0.13 days)."""
    wired = await _build_wired_employee(client, headers)
    employee_id = str(wired["employee"]["id"])
    await _create_overtime_policy(
        client,
        headers,
        approval_chain="AUTO",
        comp_off_instead_of_pay=True,
        comp_off_day_length_minutes=480,
        **ot_overrides,
    )
    await _ot_calculate_day(client, headers, employee_id=employee_id)
    leave_type = await _create_leave_type(client, headers, is_comp_off=True)
    return employee_id, leave_type


async def test_fractional_balances_are_never_rounded_by_the_sweeps(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Proportional credits and HR adjustments leave arbitrary 2-dp balances. Re-running the
    credit sweep and a not-yet-due expiry sweep must leave every one of them exactly as is."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id, leave_type = await _setup_credited(client, headers, comp_off_expiry_days=90)
        assert await _credit(company_id) == 1

        for top_up, expected in (
            (None, "0.13"),
            ("0.12", "0.25"),
            ("0.25", "0.50"),
            ("0.25", "0.75"),
        ):
            if top_up is not None:
                await _adjust(
                    client,
                    headers,
                    employee_id=employee_id,
                    leave_type_id=leave_type["id"],
                    amount=top_up,
                )
            assert await _credit(company_id) == 0
            assert await _expire(company_id, as_of=date(2026, 11, 7)) == 0
            assert await _get_balance(client, headers, employee_id) == expected

        # The original credit row itself is untouched.
        credits = await _ledger_rows(company_id, "COMP_OFF_CREDIT")
        assert [c["amount"] for c in credits] == [Decimal("0.13")]
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_later_policy_version_does_not_change_how_an_earlier_record_is_credited(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A credit is computed from the policy version that produced its overtime record — also
    for a record still waiting to be credited when a new version is published — and an existing
    credit is never recomputed."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        policy = await _create_overtime_policy(
            client,
            headers,
            approval_chain="AUTO",
            comp_off_instead_of_pay=True,
            comp_off_day_length_minutes=480,
        )
        await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["comp_off_minutes"] == 60

        # New version (half the day length) published before the record is credited.
        await _publish_ot_version(
            client,
            headers,
            policy["id"],
            effective_from="2026-08-01",
            comp_off_day_length_minutes=240,
        )
        await _create_leave_type(client, headers, is_comp_off=True)

        assert await _credit(company_id) == 1
        # 60 / 480 (the record's own version), not 60 / 240.
        assert await _get_balance(client, headers, employee_id) == "0.13"

        # Recalculating the day and re-running the sweep changes nothing.
        await _ot_calculate_day(client, headers, employee_id=employee_id)
        assert await _credit(company_id) == 0
        assert await _get_balance(client, headers, employee_id) == "0.13"
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_default_60_day_expiry_boundary_and_late_catch_up(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Decision 13 default: earned 2026-08-10 -> expiry date 2026-10-09 (still usable on
    10-08). A sweep that first runs well after the expiry date still expires it, once."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id, _ = await _setup_credited(client, headers)
        assert await _credit(company_id) == 1

        assert await _expire(company_id, as_of=date(2026, 10, 8)) == 0
        assert await _get_balance(client, headers, employee_id) == "0.13"

        assert await _expire(company_id, as_of=date(2026, 12, 1)) == 1
        assert await _get_balance(client, headers, employee_id) == "0.00"

        assert await _expire(company_id, as_of=date(2026, 12, 2)) == 0
        assert await _get_balance(client, headers, employee_id) == "0.00"
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_concurrent_expiry_sweeps_expire_a_credit_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Sweep A expires the credit but has not committed yet when sweep B starts. B must wait
    for A and then see A's offset — not read "not expired yet" and offset it a second time."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id, _ = await _setup_credited(client, headers, comp_off_expiry_days=90)
        assert await _credit(company_id) == 1

        factory = get_session_factory()
        async with factory() as session_a:
            await set_rls_company_id(session_a, str(company_id))
            first = await LeaveCompOffService(session_a).expire_company(
                company_id, as_of=date(2026, 11, 8)
            )
            second_task = asyncio.create_task(_expire(company_id, as_of=date(2026, 11, 8)))
            await asyncio.sleep(0.5)
            await session_a.commit()
        second = await second_task

        assert (first, second) == (1, 0)
        assert len(await _ledger_rows(company_id, "ADJUSTMENT")) == 1
        assert await _get_balance(client, headers, employee_id) == "0.00"
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_concurrent_credit_sweeps_credit_a_record_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id, _ = await _setup_credited(client, headers)

        results = await asyncio.gather(_credit(company_id), _credit(company_id))
        assert sorted(results) == [0, 1]
        assert len(await _ledger_rows(company_id, "COMP_OFF_CREDIT")) == 1
        assert await _get_balance(client, headers, employee_id) == "0.13"
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_expiry_never_touches_a_negative_comp_off_balance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id, leave_type = await _setup_credited(client, headers, comp_off_expiry_days=90)
        assert await _credit(company_id) == 1
        await _adjust(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type["id"],
            amount="-1.00",
        )
        assert await _get_balance(client, headers, employee_id) == "-0.87"

        assert await _expire(company_id, as_of=date(2026, 11, 8)) == 0
        assert await _credit(company_id) == 0
        assert await _get_balance(client, headers, employee_id) == "-0.87"
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
