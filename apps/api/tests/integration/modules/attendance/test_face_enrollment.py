"""Face enrollment end to end through the real app, database, RBAC and audit log:
HR opens a one-time window -> the employee self-submits five captures -> HR approves/rejects.
The face provider and photo storage are in-memory fakes; nothing here contacts Face++ or MinIO."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from entrypoints.api import app
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import (
    SPOOF_PROBS,
    FakeFaceProvider,
    FakeLivenessEngine,
    FakePhotoStorage,
    run_deletion_worker,
)
from tests.integration.modules.attendance.test_attendance_day import (
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _create_permission_scoped_user,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.dependencies import get_face_provider
from hrms.modules.attendance.email_templates import build_face_enrollment_requested_email
from hrms.modules.attendance.face_verification import (
    FaceMatchResult,
    FaceProviderError,
)
from hrms.modules.attendance.permissions import (
    ATTENDANCE_FACE_ENROLLMENT_MANAGE,
    ATTENDANCE_PUNCH,
    ATTENDANCE_VIEW,
)

pytestmark = pytest.mark.asyncio

Tenant = tuple[dict[str, str], UUID]
ANGLES = ("front", "left", "right", "up", "down")


def _jpeg(tag: str) -> bytes:
    return b"\xff\xd8\xff\xe0" + tag.encode() + b"\x00" * 32


IMAGES = {angle: _jpeg(angle) for angle in ANGLES}


async def _employee(client: AsyncClient, headers: dict[str, str], name: str = "Asha") -> str:
    response = await client.post("/v1/employees", headers=headers, json={"first_name": name})
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["id"])


async def _self_headers(company_id: UUID, employee_id: str) -> dict[str, str]:
    headers, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_PUNCH, ATTENDANCE_VIEW],
        data_scope="SELF",
        caller_employee_id=UUID(employee_id),
    )
    return headers


async def _open(client: AsyncClient, headers: dict[str, str], employee_id: str) -> Any:
    return await client.post(
        f"/v1/attendance/face-profiles/{employee_id}/enrollment-window", headers=headers
    )


async def _submit(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    images: dict[str, bytes] = IMAGES,
    consent: str = "true",
) -> Any:
    return await client.post(
        "/v1/attendance/face-enrollment/me",
        headers=headers,
        files={angle: (f"{angle}.jpg", body, "image/jpeg") for angle, body in images.items()},
        data={"consent_confirmed": consent},
    )


async def _status(client: AsyncClient, headers: dict[str, str], employee_id: str) -> Any:
    response = await client.get(
        f"/v1/attendance/face-profiles/{employee_id}/enrollment", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def enroll_and_approve(
    client: AsyncClient, admin: dict[str, str], company_id: UUID, employee_id: str
) -> dict[str, str]:
    """Drives the whole happy path; returns the employee's own headers."""
    opened = await _open(client, admin, employee_id)
    # An already-open window (e.g. the employee started it themselves) is fine to reuse.
    assert opened.status_code == 201 or (
        opened.json()["error"]["code"] == "FACE_ENROLLMENT_WINDOW_ALREADY_OPEN"
    )
    me = await _self_headers(company_id, employee_id)
    submitted = await _submit(client, me)
    assert submitted.status_code == 201, submitted.text
    approved = await client.post(
        f"/v1/attendance/face-profiles/{employee_id}/approve", headers=admin
    )
    assert approved.status_code == 200, approved.text
    return me


async def _sql(company_id: UUID, query: str) -> list[Any]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        result = await session.execute(text(query), {"cid": str(company_id)})
        rows = list(result) if result.returns_rows else []
        await session.commit()
        return rows


async def _audit_actions(company_id: UUID) -> list[str]:
    rows = await _sql(
        company_id,
        "SELECT action FROM audit_log WHERE company_id = :cid AND entity_type IN "
        "('employee_face_profile', 'face_enrollment_window') ORDER BY occurred_at",
    )
    return [r[0] for r in rows]


async def test_full_self_enrollment_with_hr_approval(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)

    opened = await _open(client, admin, employee_id)
    assert opened.status_code == 201, opened.text
    assert opened.json()["data"]["status"] == "OPEN"

    me = await _self_headers(company_id, employee_id)
    mine = await client.get("/v1/attendance/face-enrollment/me", headers=me)
    assert mine.json()["data"]["open_window"]["id"] == opened.json()["data"]["id"]
    assert mine.json()["data"]["profile"] is None

    submitted = await _submit(client, me)
    assert submitted.status_code == 201, submitted.text
    profile = submitted.json()["data"]
    assert profile["status"] == "PENDING_APPROVAL"
    assert profile["reference_photo_count"] == 5
    assert profile["has_review_photo"] is True
    assert "provider_person_id" not in profile and "review_photo_key" not in profile

    # Every capture must pass server-side liveness (our own engine, not the vendor), one call
    # per image; the front is the anchor and the four turned angles are each checked against it
    # before any is added. The vendor only ever sees the employee UUID.
    assert fake_liveness_engine.calls == [[IMAGES[angle]] for angle in ANGLES]
    expected = ["enroll"] + ["verify"] * 4 + ["add_reference_photo"] * 4
    assert fake_face_provider.names() == expected
    assert fake_face_provider.calls[0][1]["label"] == employee_id
    assert list(fake_photo_storage.objects.values()) == [IMAGES["front"]]

    # The window is single-use.
    status = await _status(client, admin, employee_id)
    assert status["open_window"] is None
    again = await _submit(client, me)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "FACE_ENROLLMENT_NOT_OPEN"

    # Pending profiles cannot punch: not even a liveness challenge is issued.
    challenge = await client.post(
        "/v1/attendance/face-punches/me/liveness-sessions", headers=me, json={"direction": "IN"}
    )
    assert challenge.status_code == 409
    assert challenge.json()["error"]["code"] == "FACE_NOT_ENROLLED"

    photo = await client.get(
        f"/v1/attendance/face-profiles/{employee_id}/review-photo", headers=admin
    )
    assert photo.status_code == 200
    assert photo.content == IMAGES["front"]
    assert photo.headers["content-type"] == "image/jpeg"
    assert "no-store" in photo.headers["cache-control"]

    approved = await client.post(
        f"/v1/attendance/face-profiles/{employee_id}/approve", headers=admin
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "ENROLLED"
    assert approved.json()["data"]["has_review_photo"] is False
    # Nothing external is touched by the approval itself: the photo is deleted by the
    # post-commit worker from the outbox row the approval queued.
    assert list(fake_photo_storage.objects.values()) == [IMAGES["front"]]
    report = await run_deletion_worker(company_id, fake_face_provider, fake_photo_storage)
    assert (report.claimed, report.done) == (1, 1)
    assert fake_photo_storage.objects == {}

    assert await _audit_actions(company_id) == [
        "FACE_ENROLLMENT_OPENED",
        "FACE_PROFILE_SUBMITTED",
        "FACE_REVIEW_PHOTO_VIEWED",
        "FACE_PROFILE_APPROVED",
    ]


async def test_submit_without_window_is_rejected(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    me = await _self_headers(company_id, employee_id)

    response = await _submit(client, me)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FACE_ENROLLMENT_NOT_OPEN"
    assert fake_face_provider.calls == []


async def test_expired_window_is_unusable(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _open(client, admin, employee_id)
    await _sql(
        company_id,
        "UPDATE face_enrollment_window SET opened_at = now() - interval '3 days', "
        "expires_at = now() - interval '1 day' WHERE company_id = :cid",
    )
    me = await _self_headers(company_id, employee_id)

    assert (await _status(client, admin, employee_id))["open_window"] is None
    response = await _submit(client, me)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FACE_ENROLLMENT_NOT_OPEN"

    # HR can open a fresh one; the stale row is marked EXPIRED, not left OPEN.
    assert (await _open(client, admin, employee_id)).status_code == 201
    statuses = await _sql(
        company_id,
        "SELECT status FROM face_enrollment_window WHERE company_id = :cid ORDER BY opened_at",
    )
    assert [r[0] for r in statuses] == ["EXPIRED", "OPEN"]


async def test_hr_cannot_open_a_second_live_window(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    first = (await _open(client, admin, employee_id)).json()["data"]
    dup = await _open(client, admin, employee_id)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "FACE_ENROLLMENT_WINDOW_ALREADY_OPEN"
    assert (await _status(client, admin, employee_id))["open_window"]["id"] == first["id"]

    # Cancelling first is the explicit path to a fresh window; audit carries previous/new state.
    url = f"/v1/attendance/face-profiles/{employee_id}/enrollment-window"
    assert (await client.delete(url, headers=admin)).status_code == 204
    second = (await _open(client, admin, employee_id)).json()["data"]
    rows = await _sql(
        company_id, "SELECT id, status FROM face_enrollment_window WHERE company_id = :cid"
    )
    assert {str(r[0]): r[1] for r in rows} == {first["id"]: "CANCELLED", second["id"]: "OPEN"}
    audit = await _sql(
        company_id,
        "SELECT before_json, after_json FROM audit_log WHERE company_id = :cid"
        " AND action = 'FACE_ENROLLMENT_OPENED' ORDER BY occurred_at DESC LIMIT 1",
    )
    assert audit[0][0]["enrollment_state"] == "NOT_ENROLLED"
    assert audit[0][1]["enrollment_state"] == "ENROLLMENT_AVAILABLE"


async def test_hr_can_cancel_an_open_window(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _open(client, admin, employee_id)
    url = f"/v1/attendance/face-profiles/{employee_id}/enrollment-window"

    assert (await client.delete(url, headers=admin)).status_code == 204
    me = await _self_headers(company_id, employee_id)
    assert (await _submit(client, me)).status_code == 409
    assert (await client.delete(url, headers=admin)).status_code == 404


async def test_consent_is_required(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _open(client, admin, employee_id)
    me = await _self_headers(company_id, employee_id)

    response = await _submit(client, me, consent="false")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_CONSENT_REQUIRED"
    assert fake_face_provider.calls == []


async def test_all_five_angles_are_required_and_must_be_images(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _open(client, admin, employee_id)
    me = await _self_headers(company_id, employee_id)

    missing = await _submit(client, me, images={k: v for k, v in IMAGES.items() if k != "down"})
    assert missing.status_code == 422

    not_image = await _submit(client, me, images={**IMAGES, "left": b"GIF89a"})
    assert not_image.status_code == 422
    assert not_image.json()["error"]["code"] == "FACE_IMAGE_INVALID"
    assert fake_face_provider.calls == []


async def test_spoofed_front_is_rejected_and_window_stays_open(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _open(client, admin, employee_id)
    me = await _self_headers(company_id, employee_id)
    fake_liveness_engine.probs = [SPOOF_PROBS]

    response = await _submit(client, me)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_SPOOF_SUSPECTED"
    # Rejected before anything reaches (or is enrolled at) the vendor.
    assert fake_face_provider.names() == []
    assert fake_photo_storage.objects == {}
    # A failed attempt does not burn the window — the employee can retry.
    assert (await _status(client, admin, employee_id))["open_window"] is not None


async def test_mismatched_angle_discards_everything(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _open(client, admin, employee_id)
    me = await _self_headers(company_id, employee_id)
    ok = FaceMatchResult("MATCHED", Decimal("0.93"))
    fake_face_provider.verify_results = [ok, FaceMatchResult("NO_MATCH", None), ok, ok]

    response = await _submit(client, me)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "FACE_ENROLLMENT_ANGLE_MISMATCH"
    assert error["details"][0]["field"] == "right"
    assert "add_reference_photo" not in fake_face_provider.names()
    assert fake_face_provider.names()[-1] == "delete_person"
    assert fake_photo_storage.objects == {}
    status = await _status(client, admin, employee_id)
    assert status["profile"] is None
    assert status["open_window"] is not None


async def test_turned_angle_below_angle_threshold_is_rejected(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _open(client, admin, employee_id)
    me = await _self_headers(company_id, employee_id)
    # The provider matched, but with low similarity — below the 0.80 angle floor.
    fake_face_provider.verify_results = [FaceMatchResult("NO_MATCH", Decimal("0.70"))]

    response = await _submit(client, me)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "left"


async def test_storage_failure_cleans_up_provider_person(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _open(client, admin, employee_id)
    me = await _self_headers(company_id, employee_id)
    fake_photo_storage.fail_put = True

    # LOG-01 — an unhandled error is now rendered as the standard 500 envelope by the app itself
    # (`RequestContextMiddleware`) instead of escaping to the server/test transport.
    response = await _submit(client, me)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "storage down" not in response.text

    assert fake_face_provider.names()[-1] == "delete_person"
    assert (await _status(client, admin, employee_id))["profile"] is None


async def test_reject_deletes_biometrics_and_allows_retry(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _open(client, admin, employee_id)
    me = await _self_headers(company_id, employee_id)
    await _submit(client, me)

    rejected = await client.post(
        f"/v1/attendance/face-profiles/{employee_id}/reject",
        headers=admin,
        json={"note": "Not the employee in the photo"},
    )

    assert rejected.status_code == 200, rejected.text
    data = rejected.json()["data"]
    assert data["status"] == "REJECTED"
    assert data["review_note"] == "Not the employee in the photo"
    # Deferred until after commit: the request itself deletes nothing outside the database.
    assert "delete_person" not in fake_face_provider.names()
    assert len(fake_photo_storage.objects) == 1
    await run_deletion_worker(company_id, fake_face_provider, fake_photo_storage)
    assert fake_face_provider.names()[-1] == "delete_person"
    assert fake_photo_storage.objects == {}
    photo = await client.get(
        f"/v1/attendance/face-profiles/{employee_id}/review-photo", headers=admin
    )
    assert photo.status_code == 404

    assert (await _open(client, admin, employee_id)).status_code == 201
    resubmitted = await _submit(client, me)
    assert resubmitted.status_code == 201, resubmitted.text
    assert resubmitted.json()["data"]["id"] == data["id"]
    assert resubmitted.json()["data"]["review_note"] is None


async def test_window_cannot_open_while_pending_or_enrolled(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _open(client, admin, employee_id)
    await _submit(client, await _self_headers(company_id, employee_id))

    pending = await _open(client, admin, employee_id)
    assert pending.status_code == 409
    assert pending.json()["error"]["code"] == "FACE_PROFILE_PENDING_APPROVAL"

    await client.post(f"/v1/attendance/face-profiles/{employee_id}/approve", headers=admin)
    enrolled = await _open(client, admin, employee_id)
    assert enrolled.status_code == 409
    assert enrolled.json()["error"]["code"] == "FACE_PROFILE_ALREADY_ENROLLED"

    again = await client.post(f"/v1/attendance/face-profiles/{employee_id}/approve", headers=admin)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "FACE_PROFILE_NOT_PENDING"


async def test_revoke_then_reopen(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await enroll_and_approve(client, admin, company_id, employee_id)

    revoked = await client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=admin)
    assert revoked.status_code == 200
    assert revoked.json()["data"]["status"] == "REVOKED"
    assert "delete_person" not in fake_face_provider.names()
    await run_deletion_worker(company_id, fake_face_provider, fake_photo_storage)
    assert fake_face_provider.names()[-1] == "delete_person"
    assert (await _open(client, admin, employee_id)).status_code == 201


async def test_revoke_survives_a_provider_outage_and_the_deletion_is_retried(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await enroll_and_approve(client, admin, company_id, employee_id)
    fake_face_provider.fail_with["delete_person"] = FaceProviderError("down")

    response = await client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=admin)

    # The local state change is what authorises the deletion and it is not hostage to the
    # provider: the profile is revoked (and can no longer punch) at once.
    assert response.status_code == 200
    assert (await _status(client, admin, employee_id))["profile"]["status"] == "REVOKED"
    now = datetime.now(UTC)

    failed = await run_deletion_worker(company_id, fake_face_provider, fake_photo_storage, now=now)
    # Two rows: the review photo queued by the approval (deleted fine) and the FaceSet.
    assert (failed.claimed, failed.failed, failed.done) == (2, 1, 1)
    row = (
        await _sql(
            company_id,
            "SELECT status, attempts, last_error_code FROM face_external_deletion "
            "WHERE kind = 'PROVIDER_PERSON'",
        )
    )[0]
    assert tuple(row) == ("PENDING", 1, "PROVIDER_ERROR")

    # Backed off: an immediate rerun finds nothing due, a later one (provider back) succeeds.
    assert (
        await run_deletion_worker(company_id, fake_face_provider, fake_photo_storage, now=now)
    ).claimed == 0
    del fake_face_provider.fail_with["delete_person"]
    later = await run_deletion_worker(
        company_id, fake_face_provider, fake_photo_storage, now=now + timedelta(hours=2)
    )
    assert (later.claimed, later.done) == (1, 1)
    assert fake_face_provider.names().count("delete_person") == 2
    # Duplicate execution after completion does nothing.
    again = await run_deletion_worker(
        company_id, fake_face_provider, fake_photo_storage, now=now + timedelta(hours=3)
    )
    assert again.claimed == 0


async def test_disabled_provider_is_503(client: AsyncClient, face_tenant: Tenant) -> None:
    admin, _ = face_tenant
    employee_id = await _employee(client, admin)
    app.dependency_overrides[get_face_provider] = lambda: None
    try:
        response = await _open(client, admin, employee_id)
    finally:
        app.dependency_overrides.pop(get_face_provider, None)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "FACE_VERIFICATION_UNAVAILABLE"


async def test_hr_actions_require_enrollment_permission(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    me = await _self_headers(company_id, employee_id)

    # An employee cannot open their own window — that is HR's gate.
    assert (await _open(client, me, employee_id)).status_code == 403
    approve = await client.post(f"/v1/attendance/face-profiles/{employee_id}/approve", headers=me)
    assert approve.status_code == 403


async def test_self_scoped_manager_cannot_open_for_someone_else(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    own_id = await _employee(client, admin, "Own")
    other_id = await _employee(client, admin, "Other")
    scoped, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_FACE_ENROLLMENT_MANAGE],
        data_scope="SELF",
        caller_employee_id=UUID(own_id),
    )

    assert (await _open(client, scoped, other_id)).status_code == 404


async def test_cross_tenant_employee_is_404(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin_a, _ = face_tenant
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_b = await _employee(client, headers_b)
        assert (await _open(client, admin_a, employee_b)).status_code == 404
        status = await client.get(
            f"/v1/attendance/face-profiles/{employee_b}/enrollment", headers=admin_a
        )
        assert status.status_code == 404
    finally:
        await _cleanup_attendance_day(company_id=company_b)
        await _cleanup(company_id=company_b, user_id=user_b)


async def test_enrollee_cannot_approve_or_reject_their_own_enrollment(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """Holding the enrollment-manage permission is not enough to approve your own face: the
    enrolled face is what every later punch is matched against."""
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin, "Self")
    both, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_FACE_ENROLLMENT_MANAGE, ATTENDANCE_PUNCH, ATTENDANCE_VIEW],
        data_scope="SELF",
        caller_employee_id=UUID(employee_id),
    )
    assert (await _open(client, admin, employee_id)).status_code == 201
    assert (await _submit(client, both)).status_code == 201

    for action in ("approve", "reject"):
        response = await client.post(
            f"/v1/attendance/face-profiles/{employee_id}/{action}",
            headers=both,
            json={"note": "ok"} if action == "reject" else None,
        )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FACE_ENROLLMENT_SELF_APPROVAL_NOT_ALLOWED"

    # Still pending; a different reviewer can decide it.
    assert (await _status(client, admin, employee_id))["profile"]["status"] == "PENDING_APPROVAL"
    approved = await client.post(
        f"/v1/attendance/face-profiles/{employee_id}/approve", headers=admin
    )
    assert approved.status_code == 200, approved.text


async def test_hr_window_audit_has_no_biometric_payload_and_expired_window_can_be_reinitiated(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _open(client, admin, employee_id)
    await _sql(
        company_id,
        "UPDATE face_enrollment_window SET opened_at = now() - interval '2 hours',"
        " expires_at = now() - interval '1 minute'"
        " WHERE company_id = :cid",
    )
    # An expired window is not "live": HR can initiate again, and the stale row is EXPIRED.
    assert (await _open(client, admin, employee_id)).status_code == 201
    audit = await _sql(
        company_id,
        "SELECT after_json::text FROM audit_log WHERE company_id = :cid"
        " AND action = 'FACE_ENROLLMENT_OPENED'",
    )
    assert audit and all("embedding" not in r[0] and "photo" not in r[0] for r in audit)


# --- HR-initiation notification (email via the transactional outbox) -------------------------


async def _link_employee_user(company_id: UUID, employee_id: str) -> str:
    """Gives the employee a login (the email target) and returns that user's email."""
    _, user_id = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_PUNCH],
        data_scope="SELF",
        caller_employee_id=UUID(employee_id),
    )
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("UPDATE employee SET user_id = :u WHERE id = :e AND company_id = :c"),
            {"u": user_id, "e": employee_id, "c": company_id},
        )
        email = (
            await session.execute(text('SELECT email FROM "user" WHERE id = :u'), {"u": user_id})
        ).scalar_one()
        await session.commit()
    return str(email)


async def _outbox(company_id: UUID) -> list[Any]:
    return await _sql(
        company_id,
        "SELECT company_id, recipient, subject, message_id, kind"
        " FROM email_outbox WHERE company_id = :cid AND failure_kind = 'face_enrollment_requested'",
    )


async def test_initiation_queues_exactly_one_email_and_duplicates_add_none(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    email = await _link_employee_user(company_id, employee_id)

    opened = await _open(client, admin, employee_id)
    assert opened.status_code == 201
    data = opened.json()["data"]
    assert data["notification_status"] == "QUEUED"  # in the outbox - not claimed as delivered

    rows = await _outbox(company_id)
    assert len(rows) == 1
    assert rows[0].company_id == company_id and rows[0].recipient == email
    assert rows[0].message_id == f"face_enrollment_requested:{data['id']}"
    assert rows[0].subject == "Face Enrollment Requested"
    # (The outbox blanks bodies once sent, so the copy is checked on the template itself.)
    _, html, text_body = build_face_enrollment_requested_email(
        first_name="Asha", company_name="Acme", expires_at="soon", app_url="https://app.test"
    )
    for forbidden in ("token", "embedding", "liveness", "score", "photo"):
        assert forbidden not in (html + text_body).lower()

    # A second initiate is a 409 and queues nothing.
    assert (await _open(client, admin, employee_id)).status_code == 409
    assert len(await _outbox(company_id)) == 1
    # The employee's own start never mails anyone.
    me = await _self_headers(company_id, employee_id)
    await client.post("/v1/attendance/face-enrollment/me/window", headers=me)
    assert len(await _outbox(company_id)) == 1


async def test_no_login_email_reports_not_supported_and_still_opens_the_window(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    opened = await _open(client, admin, employee_id)
    assert opened.status_code == 201
    assert opened.json()["data"]["notification_status"] == "NOT_SUPPORTED"
    assert await _outbox(company_id) == []
    assert (await _status(client, admin, employee_id))["enrollment_state"] == "ENROLLMENT_AVAILABLE"


async def test_notification_failure_never_undoes_the_window(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _link_employee_user(company_id, employee_id)

    async def boom(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr("hrms.modules.onboarding.email_sender.queue_email_after_commit", boom)
    opened = await _open(client, admin, employee_id)
    assert opened.status_code == 201
    assert opened.json()["data"]["notification_status"] == "FAILED"
    status = await _status(client, admin, employee_id)
    assert status["enrollment_state"] == "ENROLLMENT_AVAILABLE"
    assert status["open_window"]["id"] == opened.json()["data"]["id"]
    assert await _outbox(company_id) == []
    # The employee can still enroll from the canonical status - no email needed.
    me = await _self_headers(company_id, employee_id)
    assert (await _submit(client, me)).status_code == 201


async def test_refused_initiations_send_nothing(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _link_employee_user(company_id, employee_id)
    me = await _self_headers(company_id, employee_id)
    other = await _employee(client, admin, "Other")

    assert (await _open(client, me, other)).status_code == 403  # employee, someone else
    assert (await _open(client, me, employee_id)).status_code == 403  # no manage permission
    assert (
        await client.post(f"/v1/attendance/face-profiles/{employee_id}/enrollment-window")
    ).status_code in (401, 403)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_b = await _employee(client, headers_b)
        assert (await _open(client, admin, employee_b)).status_code == 404  # cross-tenant
        assert await _outbox(company_b) == []
    finally:
        await _cleanup_attendance_day(company_id=company_b)
        await _cleanup(company_id=company_b, user_id=user_b)
    assert await _outbox(company_id) == []
