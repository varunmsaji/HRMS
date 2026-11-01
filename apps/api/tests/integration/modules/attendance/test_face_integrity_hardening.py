"""Face attendance integrity hardening, end to end (real app, DB, RBAC; fake Face++ provider and
fake liveness engine — nothing here contacts Face++ or runs the real model):

* every punch frame is identity-checked against the *expected employee's* FaceSet;
* enrollment attempt limits, rejection records and per-angle liveness;
* no provider body is persisted.
"""

import asyncio
import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import (
    LIVE_PROBS,
    SPOOF_PROBS,
    FakeFaceProvider,
    FakeLivenessEngine,
    FakePhotoStorage,
)
from tests.integration.modules.attendance.test_face_enrollment import (
    ANGLES,
    IMAGES,
    _employee,
    _open,
    _self_headers,
    _status,
    _submit,
    enroll_and_approve,
)
from tests.integration.modules.attendance.test_face_punch import (
    _attempts,
    _enrolled_self,
    _punch_count,
    face_punch,
    issue,
    submit,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.face_verification import FaceMatchResult, FaceProviderError

pytestmark = pytest.mark.asyncio

Tenant = tuple[dict[str, str], UUID]

MATCH = FaceMatchResult("MATCHED", Decimal("0.9700"), "req-ok")
MISMATCH = FaceMatchResult("NO_MATCH", Decimal("0.2100"), "req-no")


@pytest.fixture(autouse=True)
def _fakes(fake_photo_storage: FakePhotoStorage, fake_face_provider: FakeFaceProvider) -> None:
    """Every test here needs a configured (fake) provider and in-memory review-photo storage."""


async def _sql(company_id: UUID, query: str) -> list[dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        result = await session.execute(text(query), {"cid": str(company_id)})
        rows = [dict(r._mapping) for r in result] if result.returns_rows else []
        await session.commit()
        return rows


async def _session_statuses(company_id: UUID) -> list[str]:
    rows = await _sql(
        company_id,
        "SELECT status FROM face_liveness_session WHERE company_id = :cid ORDER BY created_at",
    )
    return [r["status"] for r in rows]


# --- Phase 2: identity is verified on every frame, against the expected employee ------------


async def test_every_frame_is_checked_against_the_expected_employees_faceset(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    (profile,) = await _sql(
        company_id, "SELECT provider_person_id FROM employee_face_profile WHERE company_id = :cid"
    )
    fake_face_provider.calls.clear()
    fake_face_provider.verify_results = [
        FaceMatchResult("MATCHED", Decimal("0.9400"), "r1"),
        FaceMatchResult("MATCHED", Decimal("0.9100"), "r2"),
        FaceMatchResult("MATCHED", Decimal("0.9800"), "r3"),
    ]

    response = await face_punch(client, headers)

    assert response.status_code == 201, response.text
    assert {c[1]["person_id"] for c in fake_face_provider.calls} == {profile["provider_person_id"]}
    # The reported similarity is the weakest frame: one strong frame cannot carry a weak one.
    assert Decimal(response.json()["data"]["similarity"]) == Decimal("0.9100")
    (attempt,) = await _attempts(company_id)
    assert attempt["similarity"] == Decimal("0.9100")
    assert [f["request_id"] for f in attempt["provider_response"]["identity"]["frames"]] == [
        "r1",
        "r2",
        "r3",
    ]


@pytest.mark.parametrize("bad_position", [1, 2])
async def test_a_different_person_in_a_later_frame_fails_the_whole_punch(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    bad_position: int,
) -> None:
    """Liveness passed on all three frames — but frame `bad_position` is not the employee. The
    liveness result of one frame must not authorise the identity of another."""
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    results = [MATCH, MATCH, MATCH]
    results[bad_position] = MISMATCH
    fake_face_provider.verify_results = results
    fake_face_provider.calls.clear()

    response = await face_punch(client, headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_NOT_MATCHED"
    assert await _punch_count(client, headers) == 0
    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "IDENTITY_INCONSISTENT"
    assert attempt["punch_id"] is None
    # Stops at the first failing frame; the remaining ones are not paid for.
    assert fake_face_provider.names().count("verify") == bad_position + 1
    # The challenge stays burned: the rejected capture cannot be presented again.
    assert await _session_statuses(company_id) == ["CONSUMED"]


async def test_best_frame_not_matching_is_a_plain_no_match(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.verify_results = [MISMATCH]
    fake_face_provider.calls.clear()

    response = await face_punch(client, headers)

    assert response.status_code == 422
    assert [a["decision"] for a in await _attempts(company_id)] == ["NO_MATCH"]
    assert fake_face_provider.names() == ["verify"]


@pytest.mark.parametrize(
    ("verdict", "status", "code", "decision"),
    [
        (FaceMatchResult("NO_FACE", None), 422, "FACE_NOT_DETECTED", "NO_FACE"),
        (FaceMatchResult("MULTIPLE_FACES", None), 422, "FACE_MULTIPLE_FACES", "AMBIGUOUS_FACE"),
        # A "match" below the configured floor (default 0.90) is not a match.
        (
            FaceMatchResult("MATCHED", Decimal("0.5000")),
            422,
            "FACE_NOT_MATCHED",
            "IDENTITY_INCONSISTENT",
        ),
        # A "match" without a similarity is a malformed verdict: never a pass.
        (FaceMatchResult("MATCHED", None), 422, "FACE_NOT_MATCHED", "IDENTITY_INCONSISTENT"),
        # A verdict this code does not know is a rejection, not a pass.
        (
            FaceMatchResult("SOMETHING_NEW", Decimal("0.99")),
            422,
            "FACE_NOT_MATCHED",
            "IDENTITY_INCONSISTENT",
        ),  # type: ignore[arg-type]
    ],
)
async def test_missing_ambiguous_or_malformed_frame_verdicts_fail_closed(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    verdict: FaceMatchResult,
    status: int,
    code: str,
    decision: str,
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    # Frame 0 is fine; the bad verdict arrives on a later frame.
    fake_face_provider.verify_results = [MATCH, verdict]

    response = await face_punch(client, headers)

    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    (attempt,) = await _attempts(company_id)
    expected = "NO_FACE" if decision == "NO_FACE" else decision
    assert attempt["decision"] == expected
    assert await _punch_count(client, headers) == 0


async def test_provider_error_on_a_later_frame_leaves_no_punch_and_a_reusable_key(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    key = "k" * 20

    class FlakySecondCall(FakeFaceProvider):
        async def verify(self, **kwargs: Any) -> FaceMatchResult:
            self._call("verify", **{k: v for k, v in kwargs.items() if k != "content_type"})
            if self.names().count("verify") == 2:
                raise FaceProviderError("timed out")
            return MATCH

    from entrypoints.api import app

    from hrms.modules.attendance.dependencies import get_face_provider

    flaky = FlakySecondCall()
    app.dependency_overrides[get_face_provider] = lambda: flaky

    failed = await face_punch(client, headers, key=key)

    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "FACE_PROVIDER_FAILED"
    assert await _punch_count(client, headers) == 0
    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "PROVIDER_ERROR"
    # The evidence shows how far the check got, and nothing more.
    assert [f["decision"] for f in attempt["provider_response"]["identity"]["frames"]] == [
        "MATCHED"
    ]

    # The key was never bound to a punch, so a clean retry with it succeeds exactly once.
    app.dependency_overrides[get_face_provider] = lambda: fake_face_provider
    retry = await face_punch(client, headers, key=key)
    assert retry.status_code == 201, retry.text
    assert await _punch_count(client, headers) == 1


async def test_concurrent_submissions_with_a_failing_later_frame_create_nothing(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.verify_results = [MATCH, MISMATCH]
    session_id = await issue(client, headers)
    fake_face_provider.calls.clear()

    results = await asyncio.gather(
        *[submit(client, headers, session_id=session_id, key="c" * 20) for _ in range(4)]
    )

    assert sorted(r.status_code for r in results) == [409, 409, 409, 422]
    assert await _punch_count(client, headers) == 0
    # Only the request that won the challenge reached the provider.
    assert fake_face_provider.names().count("verify") == 2
    assert [a["decision"] for a in await _attempts(company_id)].count("IDENTITY_INCONSISTENT") == 1
    # A failed check cannot be bypassed by presenting the same challenge again.
    again = await submit(client, headers, session_id=session_id, key="c" * 20)
    assert again.status_code == 409
    assert await _punch_count(client, headers) == 0


async def test_each_employee_is_matched_only_against_their_own_faceset(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    asha_headers, asha_id = await _enrolled_self(client, face_tenant)
    ben_id = await _employee(client, admin, "Ben")
    ben_headers = await enroll_and_approve(client, admin, company_id, ben_id)
    profiles = {
        str(r["employee_id"]): r["provider_person_id"]
        for r in await _sql(
            company_id,
            "SELECT employee_id, provider_person_id FROM employee_face_profile "
            "WHERE company_id = :cid",
        )
    }
    assert profiles[asha_id] != profiles[ben_id]

    fake_face_provider.calls.clear()
    assert (await face_punch(client, asha_headers)).status_code == 201
    asha_calls = {c[1]["person_id"] for c in fake_face_provider.calls}
    fake_face_provider.calls.clear()
    assert (await face_punch(client, ben_headers)).status_code == 201
    ben_calls = {c[1]["person_id"] for c in fake_face_provider.calls}

    assert asha_calls == {profiles[asha_id]}
    assert ben_calls == {profiles[ben_id]}


async def test_other_tenants_enrolled_identity_is_never_searched(
    client: AsyncClient,
    face_tenant: Tenant,
    face_tenant_b: Tenant,
    fake_face_provider: FakeFaceProvider,
) -> None:
    _, company_a = face_tenant
    admin_b, company_b = face_tenant_b
    headers_a, _ = await _enrolled_self(client, face_tenant)
    employee_b = await _employee(client, admin_b, "Zed")
    headers_b = await enroll_and_approve(client, admin_b, company_b, employee_b)
    person_a = (
        await _sql(
            company_a,
            "SELECT provider_person_id FROM employee_face_profile WHERE company_id = :cid",
        )
    )[0]["provider_person_id"]
    person_b = (
        await _sql(
            company_b,
            "SELECT provider_person_id FROM employee_face_profile WHERE company_id = :cid",
        )
    )[0]["provider_person_id"]

    fake_face_provider.calls.clear()
    assert (await face_punch(client, headers_a)).status_code == 201
    assert {c[1]["person_id"] for c in fake_face_provider.calls} == {person_a}
    fake_face_provider.calls.clear()
    assert (await face_punch(client, headers_b)).status_code == 201
    assert {c[1]["person_id"] for c in fake_face_provider.calls} == {person_b}
    # A's challenge presented under B's login is not a valid challenge there.
    session_a = await issue(client, headers_a, "OUT")
    stolen = await submit(client, headers_b, direction="OUT", session_id=session_a)
    assert stolen.status_code == 422
    assert stolen.json()["error"]["code"] == "FACE_LIVENESS_CHALLENGE_INVALID"


# --- Phase 4: no provider body is stored ---------------------------------------------------


async def test_attempt_rows_hold_only_minimal_typed_evidence(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    assert (await face_punch(client, headers)).status_code == 201
    fake_face_provider.verify_results = [MATCH, MISMATCH]
    assert (await face_punch(client, headers, "OUT")).status_code == 422

    rows = await _attempts(company_id)

    assert len(rows) == 2
    for row in rows:
        body = row["provider_response"]
        assert set(body) == {"liveness", "identity"}
        assert set(body["identity"]) == {"primary_frame", "frames"}
        for frame in body["identity"]["frames"]:
            assert set(frame) == {"index", "decision", "similarity", "request_id"}
        assert set(body["liveness"]) == {"engine", "decision", "reason", "frames"}
        text_form = json.dumps(body)
        for forbidden in ("face_token", "face_rectangle", "landmark", "faceset", "embedding"):
            assert forbidden not in text_form


# --- Phase 3: enrollment attempt limits, records, per-angle liveness ------------------------


async def _enrollment_attempts(company_id: UUID) -> list[dict[str, Any]]:
    return await _sql(
        company_id,
        "SELECT decision, angle, enrollment_window_id, employee_id, actor_user_id "
        "FROM face_enrollment_attempt WHERE company_id = :cid ORDER BY created_at",
    )


async def _enrolling(
    client: AsyncClient, face_tenant: Tenant, name: str = "Asha"
) -> tuple[dict[str, str], dict[str, str], str, UUID]:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin, name)
    assert (await _open(client, admin, employee_id)).status_code == 201
    return admin, await _self_headers(company_id, employee_id), employee_id, company_id


async def test_rejected_enrollment_is_recorded_without_any_biometric_content(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin, me, employee_id, company_id = await _enrolling(client, face_tenant)
    fake_liveness_engine.probs = [SPOOF_PROBS]
    capsys.readouterr()

    response = await _submit(client, me)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_SPOOF_SUSPECTED"
    (row,) = await _enrollment_attempts(company_id)
    assert (row["decision"], row["angle"]) == ("SPOOF_SUSPECTED", "front")
    assert str(row["employee_id"]) == employee_id
    status = await _status(client, admin, employee_id)
    assert str(row["enrollment_window_id"]) == status["open_window"]["id"]
    out = capsys.readouterr().out
    events = [line for line in out.splitlines() if "security.face_enrollment.rejected" in line]
    assert len(events) == 1
    event = json.loads(events[0])
    assert event["reason"] == "SPOOF_SUSPECTED"
    assert event["angle"] == "front"
    assert "0.07" not in events[0]
    assert fake_face_provider.calls == []


async def test_enrollment_is_limited_per_window_and_a_new_window_resets_it(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    admin, me, employee_id, company_id = await _enrolling(client, face_tenant)
    fake_liveness_engine.probs = [SPOOF_PROBS]

    for _ in range(5):
        assert (await _submit(client, me)).status_code == 422
    fake_liveness_engine.calls.clear()
    fake_liveness_engine.probs = [LIVE_PROBS]  # even a perfect submission is now refused

    blocked = await _submit(client, me)

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "FACE_ENROLLMENT_ATTEMPTS_EXCEEDED"
    # Refused before any engine or provider work, and without writing another row.
    assert fake_liveness_engine.calls == []
    assert fake_face_provider.calls == []
    assert len(await _enrollment_attempts(company_id)) == 5

    # Only HR reopening a window starts a fresh count.
    assert (
        await client.delete(
            f"/v1/attendance/face-profiles/{employee_id}/enrollment-window", headers=admin
        )
    ).status_code == 204
    assert (await _open(client, admin, employee_id)).status_code == 201
    ok = await _submit(client, me)
    assert ok.status_code == 201, ok.text


async def test_concurrent_failing_submissions_cannot_overshoot_the_limit(
    client: AsyncClient, face_tenant: Tenant, fake_liveness_engine: FakeLivenessEngine
) -> None:
    _, me, _, company_id = await _enrolling(client, face_tenant)
    fake_liveness_engine.probs = [SPOOF_PROBS]

    results = await asyncio.gather(*[_submit(client, me) for _ in range(9)])

    # A live reservation refuses a second submission (409) instead of queueing it behind a row
    # lock, so some racers are turned away; those that ran were rejected and counted. Nothing
    # beyond the limit can ever be recorded.
    codes = [r.status_code for r in results]
    assert set(codes) <= {409, 422, 429}
    assert codes.count(422) >= 1
    rows = await _enrollment_attempts(company_id)
    assert len(rows) == codes.count(422) <= 5
    for _ in range(10):
        if len(await _enrollment_attempts(company_id)) >= 5:
            break
        assert (await _submit(client, me)).status_code == 422
    assert len(await _enrollment_attempts(company_id)) == 5
    blocked = await _submit(client, me)
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (
        429,
        "FACE_ENROLLMENT_ATTEMPTS_EXCEEDED",
    )


async def test_provider_outage_is_recorded_but_never_locks_the_employee_out(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, me, _, company_id = await _enrolling(client, face_tenant)
    fake_face_provider.fail_with["enroll"] = FaceProviderError("down")

    for _ in range(7):
        assert (await _submit(client, me)).status_code == 502
    rows = await _enrollment_attempts(company_id)
    assert [r["decision"] for r in rows] == ["PROVIDER_ERROR"] * 7

    fake_face_provider.fail_with.clear()
    assert (await _submit(client, me)).status_code == 201


async def test_failed_angle_is_recorded_with_its_name_and_provider_person_discarded(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, me, _, company_id = await _enrolling(client, face_tenant)
    ok = FaceMatchResult("MATCHED", Decimal("0.93"))
    fake_face_provider.verify_results = [ok, ok, FaceMatchResult("NO_MATCH", None), ok]

    response = await _submit(client, me)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_ENROLLMENT_ANGLE_MISMATCH"
    (row,) = await _enrollment_attempts(company_id)
    assert (row["decision"], row["angle"]) == ("ANGLE_MISMATCH", "up")
    assert fake_face_provider.names()[-1] == "delete_person"


@pytest.mark.parametrize("angle", ["left", "right", "up", "down"])
async def test_every_extra_angle_must_pass_server_side_liveness(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
    fake_photo_storage: FakePhotoStorage,
    angle: str,
) -> None:
    admin, me, employee_id, company_id = await _enrolling(client, face_tenant)
    # A genuine front, then a spoof on exactly one turned angle.
    fake_liveness_engine.per_call = [[SPOOF_PROBS] if a == angle else [LIVE_PROBS] for a in ANGLES]

    response = await _submit(client, me)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_SPOOF_SUSPECTED"
    (row,) = await _enrollment_attempts(company_id)
    assert (row["decision"], row["angle"]) == ("SPOOF_SUSPECTED", angle)
    # Nothing was enrolled at the vendor or stored, and the window stays open to retry.
    assert fake_face_provider.names() == []
    assert fake_photo_storage.objects == {}
    assert (await _status(client, admin, employee_id))["profile"] is None
    assert [call for call in fake_liveness_engine.calls] == [
        [IMAGES[a]] for a in ANGLES[: ANGLES.index(angle) + 1]
    ]


async def test_inconclusive_or_faceless_extra_angle_is_a_rejection(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    _, me, _, company_id = await _enrolling(client, face_tenant)
    fake_liveness_engine.per_call = [[LIVE_PROBS], "NO_FACE"]

    response = await _submit(client, me)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_NOT_DETECTED"
    (row,) = await _enrollment_attempts(company_id)
    assert (row["decision"], row["angle"]) == ("NO_FACE", "left")
    assert fake_face_provider.calls == []


async def test_engine_failure_during_enrollment_is_recorded_and_not_counted(
    client: AsyncClient, face_tenant: Tenant, fake_liveness_engine: FakeLivenessEngine
) -> None:
    from hrms.modules.attendance.liveness import LivenessUnavailableError

    _, me, _, company_id = await _enrolling(client, face_tenant)
    fake_liveness_engine.fail_with = LivenessUnavailableError("model missing")

    for _ in range(6):
        assert (await _submit(client, me)).status_code == 503
    assert {r["decision"] for r in await _enrollment_attempts(company_id)} == {"LIVENESS_ERROR"}

    fake_liveness_engine.fail_with = None
    assert (await _submit(client, me)).status_code == 201


async def test_another_employees_failures_do_not_count_against_you(
    client: AsyncClient, face_tenant: Tenant, fake_liveness_engine: FakeLivenessEngine
) -> None:
    admin, asha_me, _, company_id = await _enrolling(client, face_tenant, "Asha")
    ben_id = await _employee(client, admin, "Ben")
    assert (await _open(client, admin, ben_id)).status_code == 201
    ben_me = await _self_headers(company_id, ben_id)

    fake_liveness_engine.probs = [SPOOF_PROBS]
    for _ in range(5):
        assert (await _submit(client, asha_me)).status_code == 422
    assert (await _submit(client, asha_me)).status_code == 429

    fake_liveness_engine.probs = [LIVE_PROBS]
    assert (await _submit(client, ben_me)).status_code == 201


async def test_limit_does_not_change_reviewer_separation(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    """The enrollee still cannot approve their own enrollment (covered in depth in
    test_face_enrollment.py); a successful submission after earlier rejections stays PENDING."""
    admin, me, employee_id, _ = await _enrolling(client, face_tenant)
    assert (await _submit(client, me)).status_code == 201
    status = await _status(client, admin, employee_id)
    assert status["profile"]["status"] == "PENDING_APPROVAL"
    self_approve = await client.post(
        f"/v1/attendance/face-profiles/{employee_id}/approve", headers=me
    )
    assert self_approve.status_code == 403
