"""`POST /v1/attendance/face-punches/me` end to end: real app, DB, RBAC; fake face provider and
fake liveness engine (driven through the production `classify_frame`/`aggregate` rules).
Challenge semantics live in `test_face_liveness_session.py`."""

import itertools
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from entrypoints.api import app
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import (
    LIVE_PROBS,
    SPOOF_PROBS,
    UNSURE_PROBS,
    FakeFaceProvider,
    FakeLivenessEngine,
    FakePhotoStorage,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_face_enrollment import (
    _employee,
    enroll_and_approve,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.dependencies import get_face_liveness_engine, get_face_provider
from hrms.modules.attendance.face_verification import FaceMatchResult, FaceProviderError
from hrms.modules.attendance.liveness import (
    LivenessImageError,
    LivenessTimeoutError,
    LivenessUnavailableError,
)
from hrms.modules.attendance.permissions import ATTENDANCE_PUNCH, ATTENDANCE_VIEW

pytestmark = pytest.mark.asyncio

Tenant = tuple[dict[str, str], UUID]
_frame_seq = itertools.count()


def fresh_frames(count: int = 3) -> list[bytes]:
    """Synthetic JPEG-signed frames, unique per call (a re-sent frame is a replayed capture)."""
    return [
        b"\xff\xd8\xff\xe0" + f"frame-{next(_frame_seq)}-{uuid4().hex}".encode() + b"\x00" * 32
        for _ in range(count)
    ]


@pytest.fixture(autouse=True)
def _photo_storage(fake_photo_storage: FakePhotoStorage) -> None:
    """Enrollment stores a review photo; keep it in memory for every test here."""


async def _enrolled_self(
    client: AsyncClient, face_tenant: Tenant, *, enroll: bool = True
) -> tuple[dict[str, str], str]:
    """An employee (self-enrolled and HR-approved unless `enroll=False`) plus headers for a user
    linked to that employee holding `ATTENDANCE.PUNCH`/`ATTENDANCE.VIEW` at SELF scope."""
    admin_headers, company_id = face_tenant
    employee_id = await _employee(client, admin_headers)
    if enroll:
        return await enroll_and_approve(client, admin_headers, company_id, employee_id), employee_id
    self_headers, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_PUNCH, ATTENDANCE_VIEW],
        data_scope="SELF",
        caller_employee_id=UUID(employee_id),
    )
    return self_headers, employee_id


async def challenge(client: AsyncClient, headers: dict[str, str], direction: str = "IN") -> Any:
    return await client.post(
        "/v1/attendance/face-punches/me/liveness-sessions",
        headers=headers,
        json={"direction": direction},
    )


async def issue(client: AsyncClient, headers: dict[str, str], direction: str = "IN") -> str:
    response = await challenge(client, headers, direction)
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["session_id"])


async def submit(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    direction: str = "IN",
    session_id: str | None,
    frames: list[bytes] | None = None,
    key: str | None = None,
    extra: dict[str, str] | None = None,
) -> Any:
    data = {"direction": direction, **(extra or {})}
    if session_id is not None:
        data["liveness_session_id"] = session_id
    if key is not None:
        data["idempotency_key"] = key
    frames = fresh_frames() if frames is None else frames
    return await client.post(
        "/v1/attendance/face-punches/me",
        headers=headers,
        files=[("frames", (f"f{i}.jpg", f, "image/jpeg")) for i, f in enumerate(frames)],
        data=data,
    )


async def face_punch(
    client: AsyncClient,
    headers: dict[str, str],
    direction: str = "IN",
    *,
    frames: list[bytes] | None = None,
    key: str | None = None,
    extra: dict[str, str] | None = None,
) -> Any:
    """The app's flow: get a challenge for `direction`, then submit fresh frames with it. If the
    challenge itself is refused, that response is returned instead."""
    issued = await challenge(client, headers, direction)
    if issued.status_code != 201:
        return issued
    return await submit(
        client,
        headers,
        direction=direction,
        session_id=issued.json()["data"]["session_id"],
        frames=frames,
        key=key,
        extra=extra,
    )


async def _attempts(company_id: UUID) -> list[dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text(
                "SELECT decision, punch_id, similarity, liveness_score, liveness_session_id, "
                "provider_response FROM face_verification_attempt WHERE company_id = :cid "
                "ORDER BY created_at"
            ),
            {"cid": str(company_id)},
        )
        return [dict(r._mapping) for r in rows]


async def _punch_count(client: AsyncClient, headers: dict[str, str]) -> int:
    response = await client.get("/v1/attendance/punches", headers=headers)
    assert response.status_code == 200, response.text
    return len(response.json()["data"])


async def test_live_matched_capture_records_server_timed_face_punch(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    _, company_id = face_tenant
    self_headers, employee_id = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()
    fake_liveness_engine.calls.clear()
    fake_liveness_engine.probs = [[0.02, 0.93, 0.05], [0.01, 0.98, 0.01], [0.03, 0.95, 0.02]]
    frames = fresh_frames()

    response = await face_punch(client, self_headers, "IN", frames=frames)

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["punch"]["source"] == "FACE"
    assert data["punch"]["direction"] == "IN"
    assert data["punch"]["employee_id"] == employee_id
    assert Decimal(data["similarity"]) == Decimal("0.97")
    # The weakest frame's server-side P(real).
    assert Decimal(data["liveness_score"]) == Decimal("0.93")
    # Every frame went through server-side liveness, before the vendor saw anything...
    assert fake_liveness_engine.calls == [frames]
    # ...and EVERY frame was then identity-checked against the employee's own FaceSet — the best
    # live frame first, then the others, each exactly once, each the bytes that passed liveness.
    assert fake_face_provider.names() == ["verify"] * 3
    verified = [call[1]["image"] for call in fake_face_provider.calls]
    assert verified == [frames[1], frames[0], frames[2]]
    assert len({call[1]["person_id"] for call in fake_face_provider.calls}) == 1

    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "MATCHED"
    assert str(attempt["punch_id"]) == data["punch"]["id"]
    assert attempt["liveness_session_id"] is not None
    liveness = attempt["provider_response"]["liveness"]
    assert liveness["decision"] == "LIVE"
    assert [f["live"] for f in liveness["frames"]] == ["0.9300", "0.9800", "0.9500"]
    identity = attempt["provider_response"]["identity"]
    assert identity["primary_frame"] == 1
    assert [f["index"] for f in identity["frames"]] == [1, 0, 2]
    assert {f["decision"] for f in identity["frames"]} == {"MATCHED"}
    assert await _punch_count(client, self_headers) == 1


async def test_low_similarity_is_rejected(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.match = FaceMatchResult("NO_MATCH", Decimal("0.85"))

    response = await face_punch(client, self_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_NOT_MATCHED"
    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "NO_MATCH"
    assert attempt["similarity"] == Decimal("0.85")
    assert attempt["punch_id"] is None
    assert await _punch_count(client, self_headers) == 0


async def test_face_punch_read_accepts_missing_liveness_score() -> None:
    """Punches recorded before server-side liveness have no score; replays must still parse."""
    from hrms.modules.attendance.schemas import FacePunchRead

    assert FacePunchRead.model_fields["liveness_score"].is_required() is False
    assert FacePunchRead.model_fields["liveness_score"].default is None


async def test_not_enrolled_gets_no_challenge(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant, enroll=False)

    response = await face_punch(client, self_headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FACE_NOT_ENROLLED"
    assert fake_face_provider.calls == []
    assert await _attempts(company_id) == []


async def test_profile_revoked_after_challenge_cannot_punch(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    admin_headers, company_id = face_tenant
    self_headers, employee_id = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, self_headers)
    revoked = await client.delete(
        f"/v1/attendance/face-profiles/{employee_id}", headers=admin_headers
    )
    assert revoked.status_code == 200
    fake_face_provider.calls.clear()
    fake_liveness_engine.calls.clear()

    response = await submit(client, self_headers, session_id=session_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FACE_NOT_ENROLLED"
    assert fake_face_provider.calls == [] and fake_liveness_engine.calls == []
    assert [a["decision"] for a in await _attempts(company_id)] == ["NOT_ENROLLED"]


async def test_spoof_is_rejected_before_matching(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()
    fake_liveness_engine.probs = [SPOOF_PROBS]

    response = await face_punch(client, self_headers)

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "FACE_SPOOF_SUSPECTED"
    assert "0.07" not in response.text  # no model scores leak to the client
    assert fake_face_provider.calls == []
    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "SPOOF_SUSPECTED"
    assert attempt["liveness_score"] == Decimal("0.07")
    assert attempt["punch_id"] is None
    assert await _punch_count(client, self_headers) == 0


async def test_one_spoofed_frame_among_live_ones_fails_the_capture(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()
    fake_liveness_engine.probs = [LIVE_PROBS, SPOOF_PROBS, LIVE_PROBS]

    response = await face_punch(client, self_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_SPOOF_SUSPECTED"
    assert fake_face_provider.calls == []
    assert await _punch_count(client, self_headers) == 0


async def test_inconclusive_liveness_is_a_rejection_not_a_pass(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()
    fake_liveness_engine.probs = [LIVE_PROBS, UNSURE_PROBS, LIVE_PROBS]

    response = await face_punch(client, self_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_LIVENESS_INCONCLUSIVE"
    assert fake_face_provider.calls == []
    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "LIVENESS_INCONCLUSIVE"
    assert attempt["provider_response"]["liveness"]["reason"] == "LOW_CONFIDENCE"
    assert await _punch_count(client, self_headers) == 0


@pytest.mark.parametrize(
    ("reason", "code", "decision"),
    [
        ("NO_FACE", "FACE_NOT_DETECTED", "NO_FACE"),
        ("MULTIPLE_FACES", "FACE_MULTIPLE_FACES", "LIVENESS_INCONCLUSIVE"),
        ("FACE_TOO_SMALL", "FACE_LIVENESS_INCONCLUSIVE", "LIVENESS_INCONCLUSIVE"),
    ],
)
async def test_capture_quality_rejections(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
    reason: Any,
    code: str,
    decision: str,
) -> None:
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()
    fake_liveness_engine.unscored = reason

    response = await face_punch(client, self_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert fake_face_provider.calls == []
    assert [a["decision"] for a in await _attempts(company_id)] == [decision]
    assert await _punch_count(client, self_headers) == 0


@pytest.mark.parametrize(
    ("failure", "status", "code", "decision"),
    [
        (LivenessTimeoutError("slow"), 503, "FACE_LIVENESS_TIMEOUT", "LIVENESS_ERROR"),
        (LivenessUnavailableError("gone"), 503, "FACE_LIVENESS_UNAVAILABLE", "LIVENESS_ERROR"),
        (LivenessImageError("bad"), 422, "FACE_IMAGE_INVALID", "LIVENESS_INCONCLUSIVE"),
    ],
)
async def test_liveness_engine_failure_never_punches(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
    failure: Exception,
    status: int,
    code: str,
    decision: str,
) -> None:
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()
    fake_liveness_engine.fail_with = failure

    response = await face_punch(client, self_headers)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert fake_face_provider.calls == []
    assert [a["decision"] for a in await _attempts(company_id)] == [decision]
    assert await _punch_count(client, self_headers) == 0


async def test_client_supplied_liveness_claims_are_ignored(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    """A modified client asserting its own liveness changes nothing: the server's verdict is
    the only one read."""
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_liveness_engine.probs = [SPOOF_PROBS]

    response = await face_punch(
        client,
        self_headers,
        extra={
            "is_live": "true",
            "liveness": "LIVE",
            "liveness_score": "0.99",
            "liveness_decision": "LIVE",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_SPOOF_SUSPECTED"
    assert await _punch_count(client, self_headers) == 0


async def test_wrong_person_is_rejected(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.match = FaceMatchResult("NO_MATCH", None)

    response = await face_punch(client, self_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_NOT_MATCHED"
    assert [a["decision"] for a in await _attempts(company_id)] == ["NO_MATCH"]
    assert await _punch_count(client, self_headers) == 0


async def test_no_face_at_provider(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.match = FaceMatchResult("NO_FACE", None)

    response = await face_punch(client, self_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_NOT_DETECTED"


async def test_provider_outage_or_timeout_is_502_and_logged(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """`FaceProviderError` is what the Face++ adapter raises for transport failures, including
    httpx timeouts (see test_face_verification.py)."""
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.fail_with["verify"] = FaceProviderError("timed out")

    response = await face_punch(client, self_headers)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "FACE_PROVIDER_FAILED"
    assert [a["decision"] for a in await _attempts(company_id)] == ["PROVIDER_ERROR"]
    assert await _punch_count(client, self_headers) == 0


async def test_failed_attempts_are_rate_limited(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    self_headers, _ = await _enrolled_self(client, face_tenant)
    # A successful punch does not count towards the limit.
    assert (await face_punch(client, self_headers, "IN")).status_code == 201

    fake_face_provider.match = FaceMatchResult("NO_MATCH", None)
    for _ in range(5):
        assert (await face_punch(client, self_headers)).status_code == 422
    fake_face_provider.calls.clear()
    fake_face_provider.match = FaceMatchResult("MATCHED", Decimal("0.99"))

    blocked = await face_punch(client, self_headers, "OUT")

    # Refused at the challenge already: no new challenge while over the limit.
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "FACE_ATTEMPTS_EXCEEDED"
    assert fake_face_provider.calls == []


async def test_requires_punch_permission(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin_headers, company_id = face_tenant
    employee_id = await _employee(client, admin_headers)
    view_only, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_VIEW],
        data_scope="SELF",
        caller_employee_id=UUID(employee_id),
    )

    assert (await challenge(client, view_only)).status_code == 403
    assert (await submit(client, view_only, session_id=str(uuid4()))).status_code == 403
    assert fake_face_provider.calls == []


async def test_invalid_direction_and_image(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()
    fake_liveness_engine.calls.clear()

    assert (await challenge(client, self_headers, "SIDEWAYS")).status_code == 422
    session_id = await issue(client, self_headers)
    bad_image = await submit(
        client,
        self_headers,
        session_id=session_id,
        frames=[b"GIF89a not allowed", *fresh_frames(2)],
    )
    assert bad_image.status_code == 422
    assert bad_image.json()["error"]["code"] == "FACE_IMAGE_INVALID"
    assert fake_face_provider.calls == [] and fake_liveness_engine.calls == []


async def test_disabled_provider_is_503(client: AsyncClient, face_tenant: Tenant) -> None:
    app.dependency_overrides[get_face_provider] = lambda: FakeFaceProvider()
    app.dependency_overrides[get_face_liveness_engine] = lambda: FakeLivenessEngine()
    try:
        self_headers, _ = await _enrolled_self(client, face_tenant)
        app.dependency_overrides[get_face_provider] = lambda: None
        issued = await challenge(client, self_headers)
        submitted = await submit(client, self_headers, session_id=str(uuid4()))
    finally:
        app.dependency_overrides.pop(get_face_provider, None)
        app.dependency_overrides.pop(get_face_liveness_engine, None)
    for response in (issued, submitted):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "FACE_VERIFICATION_UNAVAILABLE"


async def test_disabled_liveness_fails_closed(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """No liveness engine -> no face punch at all; never a fallback to "face detected = live"."""
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, self_headers)
    fake_face_provider.calls.clear()
    app.dependency_overrides[get_face_liveness_engine] = lambda: None

    issued = await challenge(client, self_headers)
    submitted = await submit(client, self_headers, session_id=session_id)

    for response in (issued, submitted):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "FACE_LIVENESS_UNAVAILABLE"
    assert fake_face_provider.calls == []
    assert await _punch_count(client, self_headers) == 0
    assert await _attempts(company_id) == []


async def test_rejections_emit_a_redacted_security_event(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_liveness_engine.probs = [SPOOF_PROBS]
    capsys.readouterr()

    assert (await face_punch(client, self_headers)).status_code == 422

    out = capsys.readouterr().out
    events = [line for line in out.splitlines() if "security.face_punch.rejected" in line]
    assert len(events) == 1
    assert '"reason": "SPOOF_SUSPECTED"' in events[0]
    assert "0.07" not in events[0]  # no model score in the operational log
