"""Face enrollment end to end through the real app, database, RBAC and audit log:
HR opens a one-time window -> the employee self-submits five captures -> HR approves/rejects.
The face provider and photo storage are in-memory fakes; nothing here contacts Face++ or MinIO."""

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from entrypoints.api import app
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import FakeFaceProvider, FakePhotoStorage
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
from hrms.modules.attendance.face_verification import (
    FaceMatchResult,
    FaceProviderError,
    LivenessResult,
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
    assert (await _open(client, admin, employee_id)).status_code == 201
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

    # Front must be live and is the anchor; the four turned angles are each checked against it
    # before any is added. The vendor only ever sees the employee UUID.
    expected = ["check_liveness", "enroll"] + ["verify"] * 4 + ["add_reference_photo"] * 4
    assert fake_face_provider.names() == expected
    assert fake_face_provider.calls[1][1]["label"] == employee_id
    assert list(fake_photo_storage.objects.values()) == [IMAGES["front"]]

    # The window is single-use.
    status = await _status(client, admin, employee_id)
    assert status["open_window"] is None
    again = await _submit(client, me)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "FACE_ENROLLMENT_NOT_OPEN"

    # Pending profiles cannot punch.
    punch = await client.post(
        "/v1/attendance/face-punches/me",
        headers=me,
        files={"photo": ("f.jpg", IMAGES["front"], "image/jpeg")},
        data={"direction": "IN"},
    )
    assert punch.status_code == 409
    assert punch.json()["error"]["code"] == "FACE_NOT_ENROLLED"

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
    assert fake_photo_storage.objects == {}

    assert await _audit_actions(company_id) == [
        "FACE_ENROLLMENT_OPENED",
        "FACE_PROFILE_SUBMITTED",
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


async def test_reopening_cancels_the_previous_window(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    first = (await _open(client, admin, employee_id)).json()["data"]
    second = (await _open(client, admin, employee_id)).json()["data"]

    assert (await _status(client, admin, employee_id))["open_window"]["id"] == second["id"]
    rows = await _sql(
        company_id, "SELECT id, status FROM face_enrollment_window WHERE company_id = :cid"
    )
    assert {str(r[0]): r[1] for r in rows} == {first["id"]: "CANCELLED", second["id"]: "OPEN"}


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
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _open(client, admin, employee_id)
    me = await _self_headers(company_id, employee_id)
    fake_face_provider.liveness = LivenessResult("SPOOF", Decimal("0.69"), {"result": "fake"})

    response = await _submit(client, me)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_LIVENESS_FAILED"
    assert fake_face_provider.names() == ["check_liveness"]
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
    ok = FaceMatchResult("MATCHED", Decimal("0.93"), {})
    fake_face_provider.verify_results = [ok, FaceMatchResult("NO_MATCH", None, {}), ok, ok]

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
    fake_face_provider.verify_results = [FaceMatchResult("NO_MATCH", Decimal("0.70"), {})]

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
    assert fake_face_provider.names()[-1] == "delete_person"
    assert (await _open(client, admin, employee_id)).status_code == 201


async def test_revoke_provider_failure_keeps_profile_enrolled(
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

    assert response.status_code == 502
    assert (await _status(client, admin, employee_id))["profile"]["status"] == "ENROLLED"


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
