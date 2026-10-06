"""PAY-B04 — `POST /payroll/adjustments` is retry-safe and race-safe.

A correction is a *delta* to a finalised month's paid days, so its identity is the client's
`Idempotency-Key` (the shared `core.idempotency` helper, unique per company + operation + key in the
`idempotency_key` table) — never its payload: two identical-looking corrections with different keys
are two real corrections. A per-(run, employee) advisory lock (`pay-adjustment`) makes the "stays
within 0..payable days" check see every earlier correction, so concurrent corrections cannot
overshoot together.

Aug 2026 has 31 days; the employee is paid 21, so there are 10 days of headroom."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from entrypoints.api import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import _register_tenant
from tests.integration.modules.attendance.test_attendance_security import _cleanup_scoped_users
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.payroll.test_arrears import _finalised_run
from tests.integration.modules.payroll.test_pay_run import (
    _approver,
    _cleanup_pay_runs,
    _employee,
    _legal_entity,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

_URL = "/v1/payroll/adjustments"


def _body(run_id: str, employee_id: str, delta: str = "1", reason: str = "Gate log") -> dict:
    return {
        "source_pay_run_id": run_id,
        "employee_id": employee_id,
        "paid_days_delta": delta,
        "reason": reason,
    }


@asynccontextmanager
async def _scenario(
    client: AsyncClient, *, nested: bool = False
) -> AsyncIterator[tuple[dict[str, str], UUID, str, str]]:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        approver = await _approver(company_id)
        run = await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-08", paid_days={employee: "21"},
        )  # fmt: skip
        yield headers, company_id, run["id"], employee
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        if not nested:  # removes every scoped user, so only the outermost scenario may
            await _cleanup_scoped_users()


async def _rows(company_id: UUID) -> list[tuple[str, str]]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        result = await session.execute(
            text(
                "SELECT id::text, paid_days_delta::text FROM pay_adjustment "
                "WHERE company_id = :cid ORDER BY created_at"
            ),
            {"cid": str(company_id)},
        )
        return [(r[0], r[1]) for r in result]


async def _keys(company_id: UUID) -> int:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM idempotency_key "
                        "WHERE company_id = :cid AND operation LIKE 'payroll.%'"
                    ),
                    {"cid": str(company_id)},
                )
            ).scalar_one()
        )


async def test_first_request_replay_and_lost_response_create_one_correction(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _scenario(client) as (headers, company_id, run_id, employee):
        key = f"corr-{uuid4()}"
        body = _body(run_id, employee)
        first = await client.post(_URL, headers={**headers, "Idempotency-Key": key}, json=body)
        assert first.status_code == 201, first.text
        assert "idempotent-replayed" not in first.headers

        # The client never saw that response (timeout) and retries with the same key.
        retry = await client.post(_URL, headers={**headers, "Idempotency-Key": key}, json=body)
        assert retry.status_code == 201, retry.text
        assert retry.headers["Idempotent-Replayed"] == "true"
        assert retry.json()["data"] == first.json()["data"]

        assert await _rows(company_id) == [(first.json()["data"]["id"], "1.00")]
        assert await _keys(company_id) == 1


async def test_same_key_with_a_different_payload_is_refused_and_writes_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _scenario(client) as (headers, company_id, run_id, employee):
        key = f"corr-{uuid4()}"
        ok = await client.post(
            _URL, headers={**headers, "Idempotency-Key": key}, json=_body(run_id, employee, "1")
        )
        assert ok.status_code == 201, ok.text
        clash = await client.post(
            _URL, headers={**headers, "Idempotency-Key": key}, json=_body(run_id, employee, "2")
        )
        assert clash.status_code == 409, clash.text
        assert clash.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
        assert len(await _rows(company_id)) == 1


async def test_distinct_keys_are_distinct_corrections_even_with_identical_bodies(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _scenario(client) as (headers, company_id, run_id, employee):
        body = _body(run_id, employee, "1")
        a = await client.post(
            _URL, headers={**headers, "Idempotency-Key": f"a-{uuid4()}"}, json=body
        )
        b = await client.post(
            _URL, headers={**headers, "Idempotency-Key": f"b-{uuid4()}"}, json=body
        )
        assert a.status_code == b.status_code == 201
        assert a.json()["data"]["id"] != b.json()["data"]["id"]
        assert [d for _, d in await _rows(company_id)] == ["1.00", "1.00"]


async def test_the_key_is_required_and_a_failed_request_does_not_burn_it(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _scenario(client) as (headers, company_id, run_id, employee):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as raw:
            missing = await raw.post(_URL, headers=headers, json=_body(run_id, employee))
            assert missing.status_code == 422, missing.text
            assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

        key = f"corr-{uuid4()}"
        too_many = await client.post(
            _URL, headers={**headers, "Idempotency-Key": key}, json=_body(run_id, employee, "11")
        )
        assert too_many.status_code == 422, too_many.text  # 21 + 11 > 31
        assert await _rows(company_id) == [] and await _keys(company_id) == 0
        fixed = await client.post(
            _URL, headers={**headers, "Idempotency-Key": key}, json=_body(run_id, employee, "3")
        )
        assert fixed.status_code == 201, fixed.text


async def test_concurrent_duplicate_requests_create_exactly_one_correction(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _scenario(client) as (headers, company_id, run_id, employee):
        key = f"corr-{uuid4()}"
        body = _body(run_id, employee, "2")
        responses = await asyncio.gather(
            *(
                client.post(_URL, headers={**headers, "Idempotency-Key": key}, json=body)
                for _ in range(8)
            )
        )
        assert [r.status_code for r in responses] == [201] * 8, [r.text for r in responses]
        assert len({r.json()["data"]["id"] for r in responses}) == 1
        assert sum("idempotent-replayed" in r.headers for r in responses) == 7
        assert len(await _rows(company_id)) == 1
        assert await _keys(company_id) == 1


async def test_concurrent_corrections_with_different_keys_cannot_overshoot_the_payable_days(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Headroom is 10 days. Six corrections of +3 race: at most three fit (9 days). Without the
    per-employee lock every one of them read the same 'earlier' total and all six committed."""
    async with _scenario(client) as (headers, company_id, run_id, employee):
        responses = await asyncio.gather(
            *(
                client.post(
                    _URL,
                    headers={**headers, "Idempotency-Key": f"race-{i}-{uuid4()}"},
                    json=_body(run_id, employee, "3"),
                )
                for i in range(6)
            )
        )
        codes = sorted(r.status_code for r in responses)
        assert codes == [201, 201, 201, 422, 422, 422], [r.text for r in responses]
        deltas = [d for _, d in await _rows(company_id)]
        assert deltas == ["3.00"] * 3
        assert 21 + sum(float(d) for d in deltas) <= 31


async def test_idempotency_keys_and_corrections_are_isolated_between_tenants(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _scenario(client) as (headers_a, company_a, run_a, employee_a):
        async with _scenario(client, nested=True) as (headers_b, company_b, run_b, employee_b):
            key = f"shared-{uuid4()}"
            a = await client.post(
                _URL, headers={**headers_a, "Idempotency-Key": key}, json=_body(run_a, employee_a)
            )
            # The same key in another company is a different key: it executes, it does not replay.
            b = await client.post(
                _URL, headers={**headers_b, "Idempotency-Key": key}, json=_body(run_b, employee_b)
            )
            assert a.status_code == b.status_code == 201
            assert "idempotent-replayed" not in b.headers
            assert a.json()["data"]["id"] != b.json()["data"]["id"]

            # ...and another tenant's run cannot be corrected with one's own credentials.
            cross = await client.post(
                _URL,
                headers={**headers_b, "Idempotency-Key": f"x-{uuid4()}"},
                json=_body(run_a, employee_a),
            )
            assert cross.status_code in (404, 422), cross.text
            assert len(await _rows(company_a)) == 1 and len(await _rows(company_b)) == 1


async def test_a_replay_of_a_withdrawn_correction_still_returns_the_original_response(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Idempotency replays the first response; it does not re-create a withdrawn correction."""
    async with _scenario(client) as (headers, company_id, run_id, employee):
        key = f"corr-{uuid4()}"
        body = _body(run_id, employee)
        first = await client.post(_URL, headers={**headers, "Idempotency-Key": key}, json=body)
        deleted = await client.delete(f"{_URL}/{first.json()['data']['id']}", headers=headers)
        assert deleted.status_code == 204, deleted.text
        replay = await client.post(_URL, headers={**headers, "Idempotency-Key": key}, json=body)
        assert replay.status_code == 201 and replay.json()["data"] == first.json()["data"]
        assert await _rows(company_id) == []
