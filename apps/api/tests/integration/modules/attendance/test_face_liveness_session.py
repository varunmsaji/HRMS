"""Server-issued liveness challenges (`POST /v1/attendance/face-punches/me/liveness-sessions`)
and how a face punch must present them: single use, short-lived, bound to employee + tenant +
direction, burned whatever the outcome, and replayed captures refused."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import (
    SPOOF_PROBS,
    FakeFaceProvider,
    FakeLivenessEngine,
    FakePhotoStorage,
)
from tests.integration.modules.attendance.test_face_punch import (
    Tenant,
    _attempts,
    _enrolled_self,
    _punch_count,
    challenge,
    fresh_frames,
    issue,
    submit,
)

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.schemas import FACE_LIVENESS_FRAME_MAX_BYTES

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _photo_storage(fake_photo_storage: FakePhotoStorage) -> None:
    """Enrollment stores a review photo; keep it in memory for every test here."""


async def _sessions(company_id: UUID) -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text(
                "SELECT id, status, direction, issued_at, expires_at, consumed_at, frame_digests "
                "FROM face_liveness_session WHERE company_id = :c ORDER BY issued_at"
            ),
            {"c": str(company_id)},
        )
        return [dict(r._mapping) for r in rows]


async def _expire(company_id: UUID, session_id: str) -> None:
    past = datetime.now(UTC) - timedelta(minutes=10)
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("UPDATE face_liveness_session SET issued_at = :i, expires_at = :e WHERE id = :id"),
            {"i": past - timedelta(minutes=2), "e": past, "id": session_id},
        )
        await session.commit()


async def test_issue_returns_short_lived_challenge_bound_to_caller(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()

    response = await challenge(client, headers, "OUT")

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert set(data) == {"session_id", "direction", "expires_at", "frames_required"}
    assert data["direction"] == "OUT"
    assert data["frames_required"] == get_settings().face_liveness_frames
    (row,) = await _sessions(company_id)
    assert str(row["id"]) == data["session_id"]
    assert row["status"] == "ISSUED" and row["consumed_at"] is None
    ttl = (row["expires_at"] - row["issued_at"]).total_seconds()
    assert ttl == get_settings().face_liveness_session_ttl_seconds
    assert fake_face_provider.calls == []  # issuing a challenge never touches the vendor


async def test_session_is_single_use_even_after_success(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, headers)
    assert (await submit(client, headers, session_id=session_id)).status_code == 201
    fake_face_provider.calls.clear()
    fake_liveness_engine.calls.clear()

    reused = await submit(client, headers, session_id=session_id)

    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "FACE_LIVENESS_CHALLENGE_USED"
    assert fake_face_provider.calls == [] and fake_liveness_engine.calls == []
    assert await _punch_count(client, headers) == 1
    assert [a["decision"] for a in await _attempts(company_id)] == [
        "MATCHED",
        "CHALLENGE_REJECTED",
    ]


async def test_failed_liveness_still_burns_the_session(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    """The request transaction rolls back on a rejection; the challenge must stay burned."""
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, headers)
    fake_liveness_engine.probs = [SPOOF_PROBS]
    assert (await submit(client, headers, session_id=session_id)).status_code == 422

    fake_liveness_engine.probs = [[0.02, 0.95, 0.03]]
    retry = await submit(client, headers, session_id=session_id)

    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "FACE_LIVENESS_CHALLENGE_USED"
    (row,) = await _sessions(company_id)
    assert row["status"] == "CONSUMED"
    assert await _punch_count(client, headers) == 0


async def test_expired_session_is_refused_and_burned(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, headers)
    await _expire(company_id, session_id)
    fake_face_provider.calls.clear()
    fake_liveness_engine.calls.clear()

    response = await submit(client, headers, session_id=session_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FACE_LIVENESS_CHALLENGE_EXPIRED"
    assert fake_face_provider.calls == [] and fake_liveness_engine.calls == []
    assert (await _sessions(company_id))[0]["status"] == "CONSUMED"
    assert await _punch_count(client, headers) == 0


async def test_session_is_bound_to_direction(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, headers, "IN")
    fake_face_provider.calls.clear()

    response = await submit(client, headers, direction="OUT", session_id=session_id)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_LIVENESS_CHALLENGE_INVALID"
    assert fake_face_provider.calls == []
    assert await _punch_count(client, headers) == 0


async def test_new_session_supersedes_the_previous_one(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    first = await issue(client, headers)
    second = await issue(client, headers)

    stale = await submit(client, headers, session_id=first)
    fresh = await submit(client, headers, session_id=second)

    assert stale.status_code == 422
    assert stale.json()["error"]["code"] == "FACE_LIVENESS_CHALLENGE_INVALID"
    assert fresh.status_code == 201, fresh.text
    assert [r["status"] for r in await _sessions(company_id)] == ["SUPERSEDED", "CONSUMED"]


async def test_another_employees_session_is_invalid_and_not_burned(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    owner_headers, _ = await _enrolled_self(client, face_tenant)
    other_headers, _ = await _enrolled_self(client, face_tenant)
    owners = await issue(client, owner_headers)

    stolen = await submit(client, other_headers, session_id=owners)

    assert stolen.status_code == 422
    assert stolen.json()["error"]["code"] == "FACE_LIVENESS_CHALLENGE_INVALID"
    assert await _punch_count(client, other_headers) == 0
    # The owner's challenge was not burned by someone else presenting it.
    assert (await submit(client, owner_headers, session_id=owners)).status_code == 201


async def test_other_tenants_session_and_unknown_ids_are_invalid(
    client: AsyncClient,
    face_tenant: Tenant,
    face_tenant_b: Tenant,
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers_a, _ = await _enrolled_self(client, face_tenant)
    headers_b, _ = await _enrolled_self(client, face_tenant_b)
    session_b = await issue(client, headers_b)

    cross = await submit(client, headers_a, session_id=session_b)
    unknown = await submit(client, headers_a, session_id=str(uuid4()))
    garbage = await submit(client, headers_a, session_id="not-a-uuid")

    for response in (cross, unknown):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "FACE_LIVENESS_CHALLENGE_INVALID"
    assert garbage.status_code == 422
    assert await _punch_count(client, headers_a) == 0
    assert (await submit(client, headers_b, session_id=session_b)).status_code == 201


async def test_punch_without_challenge_is_refused(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    """Including the pre-liveness app contract: one `photo` and no challenge."""
    headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()
    fake_liveness_engine.calls.clear()

    no_session = await submit(client, headers, session_id=None)
    legacy = await client.post(
        "/v1/attendance/face-punches/me",
        headers=headers,
        files={"photo": ("f.jpg", fresh_frames(1)[0], "image/jpeg")},
        data={"direction": "IN"},
    )

    for response in (no_session, legacy):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "FACE_LIVENESS_CHALLENGE_REQUIRED"
    assert fake_face_provider.calls == [] and fake_liveness_engine.calls == []
    assert await _punch_count(client, headers) == 0


@pytest.mark.parametrize("count", [1, 2, 4, 6])
async def test_frame_count_must_match_exactly(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider, count: int
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, headers)

    response = await submit(client, headers, session_id=session_id, frames=fresh_frames(count))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_IMAGE_INVALID"
    assert await _punch_count(client, headers) == 0
    # A malformed request does not burn the challenge.
    assert (await submit(client, headers, session_id=session_id)).status_code == 201


async def test_oversized_frame_is_refused(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, headers)
    big = b"\xff\xd8\xff\xe0" + b"\x00" * FACE_LIVENESS_FRAME_MAX_BYTES

    response = await submit(client, headers, session_id=session_id, frames=[big, *fresh_frames(2)])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_IMAGE_INVALID"


async def test_duplicate_frame_within_one_capture_is_a_replay(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, headers)
    fake_liveness_engine.calls.clear()
    one = fresh_frames(1)[0]

    response = await submit(client, headers, session_id=session_id, frames=[one, one, one])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_CAPTURE_REPLAYED"
    assert fake_liveness_engine.calls == []


async def test_frames_from_an_earlier_capture_are_refused(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    """Re-submitting a recorded capture (byte-identical frames) with a fresh challenge."""
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    frames = fresh_frames()
    assert (
        await submit(client, headers, session_id=await issue(client, headers), frames=frames)
    ).status_code == 201
    fake_face_provider.calls.clear()
    fake_liveness_engine.calls.clear()

    # Even a single reused frame mixed with new ones.
    replay = await submit(
        client,
        headers,
        direction="OUT",
        session_id=await issue(client, headers, "OUT"),
        frames=[*fresh_frames(2), frames[0]],
    )

    assert replay.status_code == 422
    assert replay.json()["error"]["code"] == "FACE_CAPTURE_REPLAYED"
    assert fake_face_provider.calls == [] and fake_liveness_engine.calls == []
    assert await _punch_count(client, headers) == 1
    assert (await _attempts(company_id))[-1]["decision"] == "CAPTURE_REPLAYED"


async def test_concurrent_submissions_of_one_challenge_create_one_punch(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """No idempotency key: the single-use challenge alone stops a double punch."""
    headers, _ = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, headers)
    fake_face_provider.calls.clear()

    results = await asyncio.gather(
        *[submit(client, headers, session_id=session_id) for _ in range(5)]
    )

    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409, 409, 409], [r.text for r in results]
    assert {r.json()["error"]["code"] for r in results if r.status_code == 409} == {
        "FACE_LIVENESS_CHALLENGE_USED"
    }
    assert await _punch_count(client, headers) == 1
    # One request did the work: every frame verified once, by that request only.
    assert fake_face_provider.names().count("verify") == 3


async def test_challenge_issuance_is_rate_limited(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)
    monkeypatch.setattr(get_settings(), "face_liveness_sessions_per_window", 3)

    statuses = [(await challenge(client, headers)).status_code for _ in range(4)]

    assert statuses == [201, 201, 201, 429]


async def test_frames_never_reach_the_logs(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, _ = await _enrolled_self(client, face_tenant)
    caplog.set_level(logging.DEBUG)
    marker = f"SENSITIVE-FRAME-{uuid4().hex}"
    frames = [b"\xff\xd8\xff\xe0" + f"{marker}-{i}".encode() for i in range(3)]

    assert (
        await submit(client, headers, session_id=await issue(client, headers), frames=frames)
    ).status_code == 201
    fake_liveness_engine.probs = [SPOOF_PROBS]
    spoof_frames = [b"\xff\xd8\xff\xe0" + f"{marker}-spoof-{i}".encode() for i in range(3)]
    assert (
        await submit(
            client,
            headers,
            direction="OUT",
            session_id=await issue(client, headers, "OUT"),
            frames=spoof_frames,
        )
    ).status_code == 422

    captured = capfd.readouterr()
    assert marker not in captured.out + captured.err + caplog.text
