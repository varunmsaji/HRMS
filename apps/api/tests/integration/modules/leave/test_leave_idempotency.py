"""LM-03 - `Idempotency-Key` on leave adjustments, encashments and applications.

Everything runs against real PostgreSQL: the "concurrent" cases are real concurrent requests, each
on its own connection, serialised by the unique `idempotency_key` row and not by anything mocked.
The failure cases use real rollbacks (a business refusal, and a database-raised error after the
mutation started). Each concurrent case is repeated.
"""

import asyncio
import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from entrypoints.api import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _insert_closed_period,
)
from tests.integration.modules.attendance.test_attendance_security import _cleanup_scoped_users
from tests.integration.modules.leave.test_leave_application import (
    _get_balance,
    _register_tenant,
    _setup_full,
    _teardown,
)
from tests.integration.modules.leave.test_leave_ledger_safety import (
    _drop_pay_runs,
    _insert_finalised_run,
    _ledger_rows,
    _period_id,
)
from tests.integration.modules.leave.test_leave_rbac_matrix import _user_with_default_role
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

_ROUNDS = 3
_PARALLEL = 6

ADJUST = "/v1/leave-ledger/adjustments"
ENCASH = "/v1/leave-ledger/encashments"
APPLY = "/v1/leave-applications"


def _key() -> str:
    return f"test-{uuid.uuid4()}"


def _adjust_body(ctx: dict[str, Any], amount: str = "2.00", **extra: Any) -> dict[str, Any]:
    return {
        "employee_id": ctx["employee"]["id"],
        "leave_type_id": ctx["leave_type"]["id"],
        "amount": amount,
        "effective_date": "2026-09-08",
        "reason": "idempotency test",
        **extra,
    }


def _encash_body(ctx: dict[str, Any], days: str = "1.00", **extra: Any) -> dict[str, Any]:
    return {
        "employee_id": ctx["employee"]["id"],
        "leave_type_id": ctx["leave_type"]["id"],
        "days": days,
        "effective_date": "2026-09-08",
        "reason": "idempotency encashment",
        **extra,
    }


def _apply_body(ctx: dict[str, Any], start: str = "2026-09-08", end: str | None = None) -> dict:
    return {
        "employee_id": ctx["employee"]["id"],
        "leave_type_id": ctx["leave_type"]["id"],
        "start_date": start,
        "end_date": end or start,
    }


async def _post(
    client: AsyncClient, headers: dict[str, str], path: str, body: dict[str, Any], key: str
) -> Any:
    return await client.post(path, headers={**headers, "Idempotency-Key": key}, json=body)


async def _count(sql: str, company_id: UUID | str, **params: Any) -> int:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        row = await session.execute(text(sql), {"c": str(company_id), **params})
        return int(row.scalar_one())


async def _idem_rows(company_id: UUID | str, key: str | None = None) -> int:
    return await _count(
        "SELECT count(*) FROM idempotency_key WHERE company_id = CAST(:c AS uuid) "
        "AND (CAST(:k AS text) IS NULL OR idempotency_key = :k)",
        company_id,
        k=key,
    )


async def _entries(company_id: UUID | str, employee_id: str, entry_type: str) -> int:
    return await _count(
        "SELECT count(*) FROM leave_ledger WHERE company_id = CAST(:c AS uuid) "
        "AND employee_id = CAST(:e AS uuid) AND entry_type = :t",
        company_id,
        e=employee_id,
        t=entry_type,
    )


async def _applications(company_id: UUID | str, employee_id: str) -> int:
    return await _count(
        "SELECT count(*) FROM leave_application WHERE company_id = CAST(:c AS uuid) "
        "AND employee_id = CAST(:e AS uuid)",
        company_id,
        e=employee_id,
    )


async def _audits(company_id: UUID | str, action: str, entity_id: str) -> int:
    return await _count(
        "SELECT count(*) FROM audit_log WHERE company_id = CAST(:c AS uuid) "
        "AND action = :a AND entity_id = CAST(:i AS uuid)",
        company_id,
        a=action,
        i=entity_id,
    )


async def _finish(company_id: UUID, user_id: UUID | None) -> None:
    await _drop_pay_runs(company_id)
    await _cleanup_attendance_period(company_id=company_id)
    await _teardown(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


# --------------------------------------------------------------------------------------------
# Header contract
# --------------------------------------------------------------------------------------------


async def test_the_key_is_required_and_validated_on_all_three_endpoints(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, encashment_allowed=True)
        bodies = {
            ADJUST: _adjust_body(ctx),
            ENCASH: _encash_body(ctx),
            APPLY: _apply_body(ctx),
        }
        baseline = await _idem_rows(company_id)  # the opening balance was keyed by the fixture
        # a plain client: the shared fixture would add a key
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as plain:
            for path, body in bodies.items():
                missing = await plain.post(path, headers=headers, json=body)
                assert missing.status_code == 422, missing.text
                assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
                for bad in ("short", "has space in it!", "x" * 129):
                    invalid = await plain.post(
                        path, headers={**headers, "Idempotency-Key": bad}, json=body
                    )
                    assert invalid.status_code == 422, invalid.text
                    assert invalid.json()["error"]["code"] == "IDEMPOTENCY_KEY_INVALID"
        assert await _idem_rows(company_id) == baseline
        assert await _ledger_rows(company_id, ctx["employee"]["id"]) == 1  # the opening balance
    finally:
        await _finish(company_id, user_id)


# --------------------------------------------------------------------------------------------
# Adjustment
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("amount", ["3.00", "-2.00"])
async def test_adjustment_same_key_replays_the_original_response(
    client: AsyncClient, seeded_plan_catalogue: None, amount: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00")
        employee_id = ctx["employee"]["id"]
        key = _key()
        first = await _post(client, headers, ADJUST, _adjust_body(ctx, amount), key)
        assert first.status_code == 201, first.text
        assert "Idempotent-Replayed" not in first.headers

        second = await _post(client, headers, ADJUST, _adjust_body(ctx, amount), key)
        assert second.status_code == 201, second.text
        assert second.headers["Idempotent-Replayed"] == "true"
        assert second.json()["data"] == first.json()["data"]  # same entry id, amount, timestamps

        entry_id = first.json()["data"]["id"]
        assert await _entries(company_id, employee_id, "ADJUSTMENT") == 2  # opening + this one
        assert await _get_balance(client, headers, employee_id) == str(
            Decimal("10.00") + Decimal(amount)
        )
        assert await _audits(company_id, "LEAVE_LEDGER_ADJUSTMENT_CREATED", entry_id) == 1
        assert await _idem_rows(company_id, key) == 1
    finally:
        await _finish(company_id, user_id)


async def test_adjustment_same_key_with_a_different_body_is_a_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00")
        employee_id = ctx["employee"]["id"]
        key = _key()
        assert (
            await _post(client, headers, ADJUST, _adjust_body(ctx, "1.00"), key)
        ).status_code == 201
        for changed in (
            _adjust_body(ctx, "2.00"),
            _adjust_body(ctx, "1.00", reason="a different reason"),
            _adjust_body(ctx, "1.00", effective_date="2026-09-09"),
        ):
            conflict = await _post(client, headers, ADJUST, changed, key)
            assert conflict.status_code == 409, conflict.text
            assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
        assert await _entries(company_id, employee_id, "ADJUSTMENT") == 2
        assert await _get_balance(client, headers, employee_id) == "11.00"
    finally:
        await _finish(company_id, user_id)


async def test_adjustment_different_keys_are_separate_mutations(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00")
        employee_id = ctx["employee"]["id"]
        ids = set()
        for _ in range(3):
            r = await _post(client, headers, ADJUST, _adjust_body(ctx, "1.00"), _key())
            assert r.status_code == 201, r.text
            ids.add(r.json()["data"]["id"])
        assert len(ids) == 3
        assert await _get_balance(client, headers, employee_id) == "13.00"
    finally:
        await _finish(company_id, user_id)


async def test_adjustment_concurrent_same_key_commits_one_entry(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00")
        employee_id = ctx["employee"]["id"]
        expected = Decimal("10.00")
        for _ in range(_ROUNDS):
            key = _key()
            results = await asyncio.gather(
                *[
                    _post(client, headers, ADJUST, _adjust_body(ctx, "-1.50"), key)
                    for _ in range(_PARALLEL)
                ]
            )
            assert all(r.status_code == 201 for r in results), [r.text for r in results]
            assert len({r.json()["data"]["id"] for r in results}) == 1
            assert sum(1 for r in results if "Idempotent-Replayed" in r.headers) == _PARALLEL - 1
            expected -= Decimal("1.50")
            assert await _get_balance(client, headers, employee_id) == str(expected)
            assert await _idem_rows(company_id, key) == 1
        assert await _entries(company_id, employee_id, "ADJUSTMENT") == 1 + _ROUNDS
    finally:
        await _finish(company_id, user_id)


async def test_adjustment_failed_database_write_leaves_the_key_usable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The mutation starts, the database raises, the transaction rolls back: the claim row goes
    with it, and the very same key then succeeds."""
    headers, company_id, user_id = await _register_tenant(client)
    factory = get_session_factory()
    try:
        ctx = await _setup_full(client, headers, balance="10.00")
        employee_id = ctx["employee"]["id"]
        key = _key()
        body = _adjust_body(ctx, "4.00", reason="idem-boom")
        async with factory() as session:
            await session.execute(
                text(
                    "CREATE OR REPLACE FUNCTION idem_boom() RETURNS trigger AS $$ BEGIN "
                    "IF NEW.reason = 'idem-boom' THEN RAISE EXCEPTION 'injected failure'; END IF; "
                    "RETURN NEW; END $$ LANGUAGE plpgsql"
                )
            )
            await session.execute(
                text(
                    "CREATE TRIGGER idem_boom BEFORE INSERT ON leave_ledger "
                    "FOR EACH ROW EXECUTE FUNCTION idem_boom()"
                )
            )
            await session.commit()
        try:
            failed = await _post(client, headers, ADJUST, body, key)
            assert failed.status_code >= 400, failed.text
            assert await _idem_rows(company_id, key) == 0
            assert await _entries(company_id, employee_id, "ADJUSTMENT") == 1
        finally:
            async with factory() as session:
                await session.execute(text("DROP TRIGGER IF EXISTS idem_boom ON leave_ledger"))
                await session.execute(text("DROP FUNCTION IF EXISTS idem_boom()"))
                await session.commit()

        retried = await _post(client, headers, ADJUST, body, key)
        assert retried.status_code == 201, retried.text
        assert "Idempotent-Replayed" not in retried.headers
        assert await _entries(company_id, employee_id, "ADJUSTMENT") == 2
        assert await _get_balance(client, headers, employee_id) == "14.00"
    finally:
        await _finish(company_id, user_id)


async def test_a_lost_response_is_replayed_not_re_executed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The mutation commits and the client never sees the answer. It knows only the key, so it
    retries; the committed result comes back and nothing is written twice."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00", encashment_allowed=True)
        employee_id = ctx["employee"]["id"]
        for path, body, entry_type in (
            (ADJUST, _adjust_body(ctx, "2.00"), "ADJUSTMENT"),
            (ENCASH, _encash_body(ctx, "1.00"), "ENCASHMENT"),
        ):
            key = _key()
            lost = await _post(client, headers, path, body, key)
            original = lost.json()["data"]  # the client never reads this
            before = await _entries(company_id, employee_id, entry_type)
            retry = await _post(client, headers, path, body, key)
            assert retry.status_code == 201
            assert retry.json()["data"] == original
            assert await _entries(company_id, employee_id, entry_type) == before
        applied_key = _key()
        lost_apply = await _post(client, headers, APPLY, _apply_body(ctx), applied_key)
        original_application = lost_apply.json()["data"]
        retry_apply = await _post(client, headers, APPLY, _apply_body(ctx), applied_key)
        assert retry_apply.status_code == 201
        assert retry_apply.json()["data"] == original_application
        assert await _applications(company_id, employee_id) == 1
    finally:
        await _finish(company_id, user_id)


# --------------------------------------------------------------------------------------------
# Encashment
# --------------------------------------------------------------------------------------------


async def test_encashment_same_key_replays_and_a_different_body_conflicts(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00", encashment_allowed=True)
        employee_id = ctx["employee"]["id"]
        key = _key()
        first = await _post(client, headers, ENCASH, _encash_body(ctx, "2.00"), key)
        assert first.status_code == 201, first.text
        second = await _post(client, headers, ENCASH, _encash_body(ctx, "2.00"), key)
        assert second.status_code == 201 and second.headers["Idempotent-Replayed"] == "true"
        assert second.json()["data"] == first.json()["data"]

        conflict = await _post(client, headers, ENCASH, _encash_body(ctx, "3.00"), key)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"

        assert await _entries(company_id, employee_id, "ENCASHMENT") == 1
        assert await _get_balance(client, headers, employee_id) == "8.00"
        different = await _post(client, headers, ENCASH, _encash_body(ctx, "3.00"), _key())
        assert different.status_code == 201
        assert await _get_balance(client, headers, employee_id) == "5.00"
    finally:
        await _finish(company_id, user_id)


async def test_a_key_is_scoped_to_its_operation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00", encashment_allowed=True)
        key = _key()
        assert (
            await _post(client, headers, ADJUST, _adjust_body(ctx, "1.00"), key)
        ).status_code == 201
        # the same key on another operation is independent, not a replay and not a conflict
        encashed = await _post(client, headers, ENCASH, _encash_body(ctx, "1.00"), key)
        assert encashed.status_code == 201, encashed.text
        assert "Idempotent-Replayed" not in encashed.headers
        assert await _idem_rows(company_id, key) == 2
    finally:
        await _finish(company_id, user_id)


async def test_encashment_concurrent_same_key_encashes_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Balance covers exactly one day: a second execution would be refused or overdraw, so the
    only way every request answers 201 is that they all got the one original."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="1.00", encashment_allowed=True)
        employee_id = ctx["employee"]["id"]
        for _ in range(_ROUNDS):
            top_up = Decimal("1.00") - Decimal(await _get_balance(client, headers, employee_id))
            if top_up:
                await _post(client, headers, ADJUST, _adjust_body(ctx, str(top_up)), _key())
            before = await _entries(company_id, employee_id, "ENCASHMENT")
            key = _key()
            results = await asyncio.gather(
                *[
                    _post(client, headers, ENCASH, _encash_body(ctx, "1.00"), key)
                    for _ in range(_PARALLEL)
                ]
            )
            assert all(r.status_code == 201 for r in results), [r.text for r in results]
            assert len({r.json()["data"]["id"] for r in results}) == 1
            assert await _entries(company_id, employee_id, "ENCASHMENT") == before + 1
            assert await _get_balance(client, headers, employee_id) == "0.00"
    finally:
        await _finish(company_id, user_id)


async def test_encashment_concurrent_different_keys_still_cannot_overdraw(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Idempotency must not weaken the balance lock: distinct keys are distinct requests."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="1.00", encashment_allowed=True)
        employee_id = ctx["employee"]["id"]
        for _ in range(_ROUNDS):
            top_up = Decimal("1.00") - Decimal(await _get_balance(client, headers, employee_id))
            if top_up:
                await _post(client, headers, ADJUST, _adjust_body(ctx, str(top_up)), _key())
            results = await asyncio.gather(
                *[
                    _post(client, headers, ENCASH, _encash_body(ctx, "1.00"), _key())
                    for _ in range(4)
                ]
            )
            assert sorted(r.status_code for r in results).count(201) == 1, [r.text for r in results]
            assert await _get_balance(client, headers, employee_id) == "0.00"
    finally:
        await _finish(company_id, user_id)


async def test_encashment_refusals_roll_back_and_the_key_survives(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Insufficient balance, a closed period and a finalised payroll period each refuse the
    request. None leaves a row behind, and once the cause is fixed the same key goes through."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="1.00", encashment_allowed=True)
        employee_id = ctx["employee"]["id"]

        # insufficient balance
        key = _key()
        too_much = _encash_body(ctx, "5.00")
        refused = await _post(client, headers, ENCASH, too_much, key)
        assert refused.status_code == 422, refused.text
        assert await _idem_rows(company_id, key) == 0
        await _post(client, headers, ADJUST, _adjust_body(ctx, "9.00"), _key())
        ok = await _post(client, headers, ENCASH, too_much, key)
        assert ok.status_code == 201, ok.text
        assert await _entries(company_id, employee_id, "ENCASHMENT") == 1

        # closed period, then finalised payroll period
        await _insert_closed_period(
            company_id=company_id, period_start="2026-08-01", period_end="2026-08-31"
        )
        dated = _encash_body(ctx, "1.00", effective_date="2026-08-20")
        key2 = _key()
        closed = await _post(client, headers, ENCASH, dated, key2)
        assert closed.json()["error"]["code"] == "LEAVE_LEDGER_PERIOD_CLOSED"
        await _insert_finalised_run(company_id, await _period_id(company_id, "2026-08-01"))
        finalised = await _post(client, headers, ENCASH, dated, key2)
        assert finalised.json()["error"]["code"] == "LEAVE_LEDGER_PAYROLL_FINALISED"
        assert await _idem_rows(company_id, key2) == 0
        assert await _entries(company_id, employee_id, "ENCASHMENT") == 1
        # the retry with a date in the open period is the way forward, and may reuse the key
        reused = await _post(client, headers, ENCASH, _encash_body(ctx, "1.00"), key2)
        assert reused.status_code == 201, reused.text
        assert await _entries(company_id, employee_id, "ENCASHMENT") == 2
    finally:
        await _finish(company_id, user_id)


async def test_encashment_racing_an_approval_with_idempotent_retries_spends_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="HR", balance="1.00", encashment_allowed=True
        )
        employee_id = ctx["employee"]["id"]
        application = (await _post(client, headers, APPLY, _apply_body(ctx), _key())).json()["data"]
        key = _key()
        approve, *encashments = await asyncio.gather(
            client.post(
                f"/v1/leave-applications/{application['id']}/approve",
                headers={**headers, "If-Match": str(application["version"])},
                json={},
            ),
            *[_post(client, headers, ENCASH, _encash_body(ctx, "1.00"), key) for _ in range(3)],
        )
        # either the approval or the (single, replayed) encashment took the day, never both
        encash_ok = {r.status_code for r in encashments} == {201}
        assert (approve.status_code == 200) != encash_ok, (
            approve.text,
            [r.text for r in encashments],
        )
        assert len({r.json()["data"]["id"] for r in encashments if r.status_code == 201}) <= 1
        assert Decimal(await _get_balance(client, headers, employee_id)) >= 0
        assert await _entries(company_id, employee_id, "ENCASHMENT") == (1 if encash_ok else 0)
    finally:
        await _finish(company_id, user_id)


# --------------------------------------------------------------------------------------------
# Leave application
# --------------------------------------------------------------------------------------------


async def test_submission_same_key_returns_the_original_application(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00")
        employee_id = ctx["employee"]["id"]
        key = _key()
        first = await _post(client, headers, APPLY, _apply_body(ctx), key)
        assert first.status_code == 201, first.text
        second = await _post(client, headers, APPLY, _apply_body(ctx), key)
        assert second.status_code == 201
        assert second.headers["Idempotent-Replayed"] == "true"
        assert second.json()["data"] == first.json()["data"]
        assert await _applications(company_id, employee_id) == 1
        assert await _get_balance(client, headers, employee_id) == "9.00"  # AUTO: debited once

        conflict = await _post(client, headers, APPLY, _apply_body(ctx, end="2026-09-09"), key)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
        assert await _applications(company_id, employee_id) == 1
    finally:
        await _finish(company_id, user_id)


async def test_submission_concurrent_same_key_creates_one_application(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00")
        employee_id = ctx["employee"]["id"]
        days = ["2026-09-08", "2026-09-09", "2026-09-10"]
        for index, day in enumerate(days):
            key = _key()
            results = await asyncio.gather(
                *[
                    _post(client, headers, APPLY, _apply_body(ctx, day), key)
                    for _ in range(_PARALLEL)
                ]
            )
            assert all(r.status_code == 201 for r in results), [r.text for r in results]
            assert len({r.json()["data"]["id"] for r in results}) == 1
            assert await _applications(company_id, employee_id) == index + 1
            assert await _get_balance(client, headers, employee_id) == str(
                Decimal("10.00") - (index + 1)
            )
    finally:
        await _finish(company_id, user_id)


async def test_submission_overlap_protection_is_not_turned_into_a_replay(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00")
        employee_id = ctx["employee"]["id"]
        key1, key2 = _key(), _key()
        first = await _post(client, headers, APPLY, _apply_body(ctx), key1)
        assert first.status_code == 201
        # genuinely a second request for the same dates, under another key: still refused
        overlap = await _post(client, headers, APPLY, _apply_body(ctx), key2)
        assert overlap.status_code in (409, 422), overlap.text
        assert "Idempotent-Replayed" not in overlap.headers
        assert await _idem_rows(company_id, key2) == 0
        assert await _applications(company_id, employee_id) == 1
        # concurrent overlap with distinct keys: one wins
        results = await asyncio.gather(
            *[
                _post(client, headers, APPLY, _apply_body(ctx, "2026-09-15"), _key())
                for _ in range(4)
            ]
        )
        assert sorted(r.status_code for r in results).count(201) == 1
        assert await _applications(company_id, employee_id) == 2
        # the original key still replays its own application
        replay = await _post(client, headers, APPLY, _apply_body(ctx), key1)
        assert replay.json()["data"] == first.json()["data"]
        # different keys, different dates, behave normally
        other = await _post(client, headers, APPLY, _apply_body(ctx, "2026-09-22"), _key())
        assert other.status_code == 201
        assert await _applications(company_id, employee_id) == 3
    finally:
        await _finish(company_id, user_id)


async def test_submission_refused_then_retried_with_the_same_key_succeeds(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="1.00")
        employee_id = ctx["employee"]["id"]
        key = _key()
        body = _apply_body(ctx, "2026-09-08", "2026-09-10")  # three days against one
        refused = await _post(client, headers, APPLY, body, key)
        assert refused.status_code >= 400, refused.text
        assert await _idem_rows(company_id, key) == 0
        assert await _applications(company_id, employee_id) == 0
        await _post(client, headers, ADJUST, _adjust_body(ctx, "5.00"), _key())
        retried = await _post(client, headers, APPLY, body, key)
        assert retried.status_code == 201, retried.text
        assert await _applications(company_id, employee_id) == 1
    finally:
        await _finish(company_id, user_id)


# --------------------------------------------------------------------------------------------
# Security
# --------------------------------------------------------------------------------------------


async def test_keys_are_isolated_between_companies(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        ctx_a = await _setup_full(client, headers_a, balance="10.00")
        ctx_b = await _setup_full(client, headers_b, balance="10.00")
        key = _key()
        first_a = await _post(client, headers_a, ADJUST, _adjust_body(ctx_a, "1.00"), key)
        assert first_a.status_code == 201
        # B uses the same key with a different body: it is B's own, new key. No conflict, no
        # replay of A's response, and nothing that tells B the key exists elsewhere.
        first_b = await _post(client, headers_b, ADJUST, _adjust_body(ctx_b, "7.00"), key)
        assert first_b.status_code == 201, first_b.text
        assert first_b.json()["data"]["id"] != first_a.json()["data"]["id"]
        assert "Idempotent-Replayed" not in first_b.headers
        assert first_b.json()["data"]["amount"] == "7.00"
        # B replays only its own
        replay_b = await _post(client, headers_b, ADJUST, _adjust_body(ctx_b, "7.00"), key)
        assert replay_b.json()["data"] == first_b.json()["data"]
        # A, naming B's employee under the shared key, is a plain not-found, never B's response
        cross = await _post(client, headers_a, ADJUST, _adjust_body(ctx_b, "7.00"), _key())
        assert cross.status_code == 404
        assert await _idem_rows(company_a, key) == 1
        assert await _idem_rows(company_b, key) == 1
        assert await _get_balance(client, headers_a, ctx_a["employee"]["id"]) == "11.00"
        assert await _get_balance(client, headers_b, ctx_b["employee"]["id"]) == "17.00"
    finally:
        await _finish(company_a, user_a)
        await _finish(company_b, user_b)


async def test_replay_does_not_bypass_authorisation_and_is_bound_to_the_requester(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00", encashment_allowed=True)
        employee_id = UUID(ctx["employee"]["id"])
        key = _key()
        body = _adjust_body(ctx, "2.00")
        original = await _post(client, headers, ADJUST, body, key)
        assert original.status_code == 201

        # a caller without the permission is refused before any key lookup
        employee = await _user_with_default_role(company_id, "EMPLOYEE", employee_id)
        for path, payload in ((ADJUST, body), (ENCASH, _encash_body(ctx))):
            denied = await _post(client, employee, path, payload, key)
            assert denied.status_code == 403, denied.text
            assert "Idempotent-Replayed" not in denied.headers
        # another holder of the permission cannot replay the first user's result either
        other_admin = await _user_with_default_role(company_id, "HR_ADMIN", employee_id)
        stolen = await _post(client, other_admin, ADJUST, body, key)
        assert stolen.status_code == 409
        assert stolen.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
        assert await _entries(company_id, str(employee_id), "ADJUSTMENT") == 2
    finally:
        await _finish(company_id, user_id)
        await _cleanup_scoped_users()


async def test_only_a_digest_and_the_response_are_stored(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00")
        key = _key()
        secret = "very-private-note-7f3a"
        r = await _post(client, headers, ADJUST, _adjust_body(ctx, "1.00", reason=secret), key)
        assert r.status_code == 201
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            row = (
                await session.execute(
                    text(
                        "SELECT request_fingerprint, operation, response_status, completed_at, "
                        "idempotency_key FROM idempotency_key WHERE company_id = CAST(:c AS uuid) "
                        "AND idempotency_key = :k"
                    ),
                    {"c": str(company_id), "k": key},
                )
            ).one()
        fingerprint, operation, status, completed_at, stored_key = row
        assert len(fingerprint) == 64 and set(fingerprint) <= set("0123456789abcdef")
        assert secret not in fingerprint and secret not in stored_key
        assert operation == "leave.ledger.adjustment" and status == 201
        assert completed_at is not None
    finally:
        await _finish(company_id, user_id)
