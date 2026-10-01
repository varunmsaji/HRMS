"""Face enrollment routes (`/v1/attendance/face-profiles*`) end to end through the real app,
database, RBAC and audit log. The face provider is replaced by an in-memory fake via
`app.dependency_overrides` — nothing here contacts Luxand."""

from typing import Any
from uuid import UUID

import pytest
from entrypoints.api import app
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import FakeFaceProvider
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
    FaceProviderError,
    FaceProviderNoFaceError,
)
from hrms.modules.attendance.permissions import (
    ATTENDANCE_FACE_ENROLLMENT_MANAGE,
    ATTENDANCE_PUNCH,
)

pytestmark = pytest.mark.asyncio

_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


async def _employee(client: AsyncClient, headers: dict[str, str], name: str = "Asha") -> str:
    response = await client.post("/v1/employees", headers=headers, json={"first_name": name})
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["id"])


async def _enroll(
    client: AsyncClient,
    headers: dict[str, str],
    employee_id: str,
    *,
    image: bytes = _JPEG,
    consent: str = "true",
) -> Any:
    return await client.post(
        f"/v1/attendance/face-profiles/{employee_id}",
        headers=headers,
        files={"photo": ("face.jpg", image, "image/jpeg")},
        data={"consent_confirmed": consent},
    )


async def _audit_actions(company_id: UUID) -> list[str]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text(
                "SELECT action FROM audit_log WHERE company_id = :cid "
                "AND entity_type = 'employee_face_profile' ORDER BY occurred_at"
            ),
            {"cid": str(company_id)},
        )
        return [r[0] for r in rows]


async def test_enroll_get_list_happy_path(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers, company_id = face_tenant
    employee_id = await _employee(client, headers)

    response = await _enroll(client, headers, employee_id)

    assert response.status_code == 201, response.text
    profile = response.json()["data"]
    assert profile["status"] == "ENROLLED"
    assert profile["reference_photo_count"] == 1
    assert profile["consent_recorded_at"]
    assert "provider_person_id" not in profile
    # Only the employee UUID is sent to the vendor, never a name.
    assert fake_face_provider.calls == [
        ("enroll", {"label": employee_id, "content_type": "image/jpeg"})
    ]

    got = await client.get(f"/v1/attendance/face-profiles/{employee_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["data"]["id"] == profile["id"]

    listed = await client.get("/v1/attendance/face-profiles", headers=headers)
    assert [p["employee_id"] for p in listed.json()["data"]] == [employee_id]

    assert await _audit_actions(company_id) == ["FACE_PROFILE_ENROLLED"]


async def test_png_is_accepted_and_sniffed(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers, _ = face_tenant
    employee_id = await _employee(client, headers)
    response = await _enroll(client, headers, employee_id, image=_PNG)
    assert response.status_code == 201, response.text
    assert fake_face_provider.calls[0][1]["content_type"] == "image/png"


async def test_enroll_requires_consent(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers, _ = face_tenant
    employee_id = await _employee(client, headers)
    response = await _enroll(client, headers, employee_id, consent="false")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_CONSENT_REQUIRED"
    assert fake_face_provider.calls == []


async def test_enroll_rejects_non_image(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers, _ = face_tenant
    employee_id = await _employee(client, headers)
    response = await _enroll(client, headers, employee_id, image=b"%PDF-1.7 not a face")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_IMAGE_INVALID"
    assert fake_face_provider.calls == []


async def test_enroll_no_face_leaves_no_profile(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers, _ = face_tenant
    employee_id = await _employee(client, headers)
    fake_face_provider.fail_with["enroll"] = FaceProviderNoFaceError("no face")

    response = await _enroll(client, headers, employee_id)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_NOT_DETECTED"
    got = await client.get(f"/v1/attendance/face-profiles/{employee_id}", headers=headers)
    assert got.status_code == 404


async def test_provider_outage_is_502_without_vendor_text(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers, _ = face_tenant
    employee_id = await _employee(client, headers)
    fake_face_provider.fail_with["enroll"] = FaceProviderError("upstream said something secret")

    response = await _enroll(client, headers, employee_id)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "FACE_PROVIDER_FAILED"
    assert "secret" not in response.text


async def test_double_enroll_conflicts(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers, _ = face_tenant
    employee_id = await _employee(client, headers)
    assert (await _enroll(client, headers, employee_id)).status_code == 201

    response = await _enroll(client, headers, employee_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FACE_PROFILE_ALREADY_ENROLLED"
    assert fake_face_provider.names() == ["enroll"]


async def test_reference_photos_up_to_limit(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers, _ = face_tenant
    employee_id = await _employee(client, headers)
    await _enroll(client, headers, employee_id)

    for expected in (2, 3, 4, 5):
        response = await client.post(
            f"/v1/attendance/face-profiles/{employee_id}/photos",
            headers=headers,
            files={"photo": ("f.jpg", _JPEG, "image/jpeg")},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["reference_photo_count"] == expected

    over = await client.post(
        f"/v1/attendance/face-profiles/{employee_id}/photos",
        headers=headers,
        files={"photo": ("f.jpg", _JPEG, "image/jpeg")},
    )
    assert over.status_code == 422
    assert over.json()["error"]["code"] == "FACE_REFERENCE_PHOTO_LIMIT"
    assert fake_face_provider.names().count("add_reference_photo") == 4


async def test_revoke_then_re_enroll(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers, company_id = face_tenant
    employee_id = await _employee(client, headers)
    first = (await _enroll(client, headers, employee_id)).json()["data"]

    revoked = await client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=headers)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["data"]["status"] == "REVOKED"
    assert revoked.json()["data"]["revoked_at"]
    assert fake_face_provider.names() == ["enroll", "delete_person"]

    again = await client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "FACE_PROFILE_NOT_ENROLLED"

    photo_after_revoke = await client.post(
        f"/v1/attendance/face-profiles/{employee_id}/photos",
        headers=headers,
        files={"photo": ("f.jpg", _JPEG, "image/jpeg")},
    )
    assert photo_after_revoke.status_code == 409

    re_enrolled = await _enroll(client, headers, employee_id)
    assert re_enrolled.status_code == 201, re_enrolled.text
    data = re_enrolled.json()["data"]
    assert data["id"] == first["id"]
    assert data["status"] == "ENROLLED"
    assert data["revoked_at"] is None
    assert await _audit_actions(company_id) == [
        "FACE_PROFILE_ENROLLED",
        "FACE_PROFILE_REVOKED",
        "FACE_PROFILE_ENROLLED",
    ]


async def test_revoke_provider_failure_keeps_profile_enrolled(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers, _ = face_tenant
    employee_id = await _employee(client, headers)
    await _enroll(client, headers, employee_id)
    fake_face_provider.fail_with["delete_person"] = FaceProviderError("down")

    response = await client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=headers)

    assert response.status_code == 502
    got = await client.get(f"/v1/attendance/face-profiles/{employee_id}", headers=headers)
    assert got.json()["data"]["status"] == "ENROLLED"


async def test_disabled_provider_is_503(
    client: AsyncClient, face_tenant: tuple[dict[str, str], UUID]
) -> None:
    headers, _ = face_tenant
    employee_id = await _employee(client, headers)
    app.dependency_overrides[get_face_provider] = lambda: None
    try:
        response = await _enroll(client, headers, employee_id)
    finally:
        app.dependency_overrides.pop(get_face_provider, None)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "FACE_VERIFICATION_UNAVAILABLE"


async def test_requires_enrollment_permission(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers, company_id = face_tenant
    employee_id = await _employee(client, headers)
    punch_only, _ = await _create_permission_scoped_user(
        company_id=company_id, permission_codes=[ATTENDANCE_PUNCH], data_scope="COMPANY"
    )

    response = await _enroll(client, punch_only, employee_id)

    assert response.status_code == 403
    assert fake_face_provider.calls == []


async def test_self_scope_cannot_enroll_someone_else(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers, company_id = face_tenant
    own_id = await _employee(client, headers, "Own")
    other_id = await _employee(client, headers, "Other")
    self_scoped, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_FACE_ENROLLMENT_MANAGE],
        data_scope="SELF",
        caller_employee_id=UUID(own_id),
    )

    other = await _enroll(client, self_scoped, other_id)
    assert other.status_code == 404
    assert fake_face_provider.calls == []

    own = await _enroll(client, self_scoped, own_id)
    assert own.status_code == 201, own.text


async def test_cross_tenant_employee_is_404(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
) -> None:
    headers_a, _ = face_tenant
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_b = await _employee(client, headers_b)
        response = await _enroll(client, headers_a, employee_b)
        assert response.status_code == 404
        assert fake_face_provider.calls == []
    finally:
        await _cleanup_attendance_day(company_id=company_b)
        await _cleanup(company_id=company_b, user_id=user_b)
