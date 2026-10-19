"""Face-punch idempotency (`idempotency_key` on `POST /v1/attendance/face-punches/me`):
replay, concurrency, retry after a lost response, failure cleanliness, key misuse, isolation.

Every retry here follows the app's real flow: a fresh liveness challenge and a fresh capture,
carrying the SAME idempotency key — the key, not the challenge, identifies the punch operation."""

import asyncio
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import (
    FakeFaceProvider,
    FakeLivenessEngine,
    FakePhotoStorage,
)
from tests.integration.modules.attendance.test_face_punch import (
    Tenant,
    _attempts,
    _enrolled_self,
    _punch_count,
    face_punch,
    issue,
    submit,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.face_verification import FaceMatchResult, FaceProviderError
from hrms.modules.attendance.repository import PunchRepository

pytestmark = pytest.mark.asyncio

KEY = "idem_1700000000000000_abcdef01_12345678"


@pytest.fixture(autouse=True)
def _photo_storage(fake_photo_storage: FakePhotoStorage) -> None:
    """Enrollment stores a review photo; keep it in memory for every test here."""


async def _punch(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    direction: str = "IN",
    key: str | None = KEY,
) -> Any:
    return await face_punch(client, headers, direction, key=key)


async def _stored_keys(company_id: UUID) -> list[str | None]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text("SELECT idempotency_key FROM punch WHERE company_id = :c"), {"c": str(company_id)}
        )
        return [r[0] for r in rows]


async def test_same_key_replays_original_without_second_punch_or_verification(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()
    fake_liveness_engine.calls.clear()

    first = await _punch(client, headers)
    calls_after_first = list(fake_face_provider.calls)
    second = await _punch(client, headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    a, b = first.json()["data"], second.json()["data"]
    assert a["punch"]["id"] == b["punch"]["id"]
    assert a["punch"]["punch_time"] == b["punch"]["punch_time"]
    assert (a["similarity"], a["liveness_score"]) == (b["similarity"], b["liveness_score"])
    assert fake_face_provider.calls == calls_after_first  # replay never reaches the provider
    assert len(fake_liveness_engine.calls) == 1  # ...nor re-runs liveness
    assert await _punch_count(client, headers) == 1
    assert len(await _attempts(company_id)) == 1
    # Stored under the face namespace, so it cannot collide with a self-punch key.
    assert await _stored_keys(company_id) == [f"face:{KEY}"]


async def test_no_key_keeps_previous_behaviour(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)

    assert (await _punch(client, headers, key=None)).status_code == 201
    assert (await _punch(client, headers, key=None)).status_code == 201
    assert await _punch_count(client, headers) == 2


async def test_different_keys_are_different_punches(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)

    first = await _punch(client, headers, direction="IN", key=KEY)
    second = await _punch(client, headers, direction="OUT", key=KEY[:-1] + "9")

    assert first.status_code == second.status_code == 201
    assert first.json()["data"]["punch"]["id"] != second.json()["data"]["punch"]["id"]
    assert await _punch_count(client, headers) == 2


async def test_concurrent_same_key_creates_exactly_one_punch(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """A double-submitted punch: same challenge, same key, sent six times at once."""
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, headers)
    fake_face_provider.calls.clear()

    results = await asyncio.gather(
        *[submit(client, headers, session_id=session_id, key=KEY) for _ in range(6)]
    )

    assert [r.status_code for r in results] == [201] * 6, [r.text for r in results]
    assert len({r.json()["data"]["punch"]["id"] for r in results}) == 1
    assert await _punch_count(client, headers) == 1
    matched = [a for a in await _attempts(company_id) if a["decision"] == "MATCHED"]
    assert len(matched) == 1
    # The advisory lock makes the duplicates wait and replay: one provider verification only.
    # One request did the work: every frame verified once, by that request only.
    assert fake_face_provider.names().count("verify") == 3


async def test_retry_after_lost_response_returns_original(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """The server committed, the client timed out and never saw the 201 — the retry carries the
    same key and gets the original punch back."""
    headers, _ = await _enrolled_self(client, face_tenant)

    lost = await _punch(client, headers)  # response "lost": the client ignores it
    assert lost.status_code == 201
    retry = await _punch(client, headers)

    assert retry.status_code == 201
    assert retry.json()["data"]["punch"]["id"] == lost.json()["data"]["punch"]["id"]
    assert await _punch_count(client, headers) == 1


async def test_retry_while_first_is_in_flight_with_a_new_challenge_returns_one_punch(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """The app timed out mid-request and retried (new challenge, new capture, same key) while
    the first request was still running on the server: one punch, both get it."""
    headers, _ = await _enrolled_self(client, face_tenant)
    first_session = await issue(client, headers)
    first = asyncio.create_task(submit(client, headers, session_id=first_session, key=KEY))
    await asyncio.sleep(0)
    # Issuing the retry's challenge supersedes the first one only if the first has not been
    # presented yet; either way exactly one punch results and the key settles it.
    second = await _punch(client, headers)
    first_result = await first

    ok = [r for r in (first_result, second) if r.status_code == 201]
    assert ok, (first_result.text, second.text)
    assert len({r.json()["data"]["punch"]["id"] for r in ok}) == 1
    assert await _punch_count(client, headers) == 1


async def test_rejected_attempt_leaves_key_reusable(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.match = FaceMatchResult("NO_MATCH", None)

    rejected = await _punch(client, headers)
    assert rejected.status_code == 422
    assert await _stored_keys(company_id) == []

    fake_face_provider.match = FaceMatchResult("MATCHED", Decimal("0.97"))
    retry = await _punch(client, headers)

    assert retry.status_code == 201, retry.text
    assert await _punch_count(client, headers) == 1


async def test_provider_outage_leaves_key_reusable(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.fail_with["verify"] = FaceProviderError("down")

    assert (await _punch(client, headers)).status_code == 502
    assert await _stored_keys(company_id) == []

    fake_face_provider.fail_with.clear()
    assert (await _punch(client, headers)).status_code == 201
    assert await _punch_count(client, headers) == 1


async def test_database_failure_during_punch_write_leaves_no_record(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The DB fails while the punch is written: nothing is committed (no punch, no MATCHED
    attempt, no key), and the same key succeeds once the database is healthy again."""
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    real_insert = PunchRepository.insert
    state = {"fail": True}

    async def flaky_insert(self: PunchRepository, session: Any, *, data: dict[str, Any]) -> Any:
        if state["fail"]:
            raise RuntimeError("simulated database failure")
        return await real_insert(self, session, data=data)

    monkeypatch.setattr(PunchRepository, "insert", flaky_insert)

    failed = await _punch(client, headers)
    assert failed.status_code == 500
    assert await _stored_keys(company_id) == []
    assert [a for a in await _attempts(company_id) if a["decision"] == "MATCHED"] == []

    state["fail"] = False
    ok = await _punch(client, headers)
    assert ok.status_code == 201, ok.text
    assert await _punch_count(client, headers) == 1


async def test_same_key_other_direction_is_a_conflict_not_a_silent_drop(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)
    assert (await _punch(client, headers, direction="IN")).status_code == 201

    clash = await _punch(client, headers, direction="OUT")

    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "DUPLICATE_PUNCH_IDEMPOTENCY_KEY"
    assert await _punch_count(client, headers) == 1


@pytest.mark.parametrize("bad", ["short", "x" * 65, "has space in the key!!", "a/b" * 8])
async def test_malformed_key_is_rejected_before_any_work(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider, bad: str
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()

    response = await _punch(client, headers, key=bad)

    assert response.status_code == 422
    assert fake_face_provider.calls == []
    assert await _punch_count(client, headers) == 0


async def test_face_key_does_not_collide_with_self_punch_key(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)
    assert (await _punch(client, headers, key=KEY)).status_code == 201

    plain = await client.post(
        "/v1/attendance/punches/me",
        headers=headers,
        json={"direction": "IN", "idempotency_key": KEY},
    )

    assert plain.status_code == 201, plain.text
    assert plain.json()["data"]["source"] == "WEB"
    assert await _punch_count(client, headers) == 2


async def test_self_punch_key_reused_with_other_direction_is_a_conflict(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)
    body = {"direction": "IN", "idempotency_key": KEY}
    assert (
        await client.post("/v1/attendance/punches/me", headers=headers, json=body)
    ).status_code == 201

    clash = await client.post(
        "/v1/attendance/punches/me", headers=headers, json={**body, "direction": "OUT"}
    )

    assert clash.status_code == 409
    assert await _punch_count(client, headers) == 1


async def test_other_employee_cannot_replay_or_collide(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    from tests.integration.modules.attendance.test_face_enrollment import (
        _employee,
        enroll_and_approve,
    )

    admin_headers, company_id = face_tenant
    first_headers, _ = await _enrolled_self(client, face_tenant)
    second_employee = await _employee(client, admin_headers)
    second_headers = await enroll_and_approve(client, admin_headers, company_id, second_employee)

    assert (await _punch(client, first_headers)).status_code == 201
    clash = await _punch(client, second_headers)

    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "DUPLICATE_PUNCH_IDEMPOTENCY_KEY"
    assert await _punch_count(client, second_headers) == 0


async def test_same_key_in_another_tenant_is_independent(
    client: AsyncClient,
    face_tenant: Tenant,
    face_tenant_b: Tenant,
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers_a, _ = await _enrolled_self(client, face_tenant)
    headers_b, _ = await _enrolled_self(client, face_tenant_b)

    a = await _punch(client, headers_a)
    b = await _punch(client, headers_b)

    assert a.status_code == b.status_code == 201, (a.text, b.text)
    assert a.json()["data"]["punch"]["id"] != b.json()["data"]["punch"]["id"]
    assert await _punch_count(client, headers_a) == 1
    assert await _punch_count(client, headers_b) == 1


async def test_raw_key_never_appears_in_logs(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)
    caplog.set_level(logging.DEBUG)
    assert (await _punch(client, headers, direction="IN")).status_code == 201
    assert (await _punch(client, headers, direction="IN")).status_code == 201
    assert (await _punch(client, headers, direction="OUT")).status_code == 409

    captured = capfd.readouterr()
    everything = captured.out + captured.err + caplog.text
    assert KEY not in everything
    assert "attendance.face_punch.replayed" in everything
    assert "attendance.face_punch.idempotency_conflict" in everything
