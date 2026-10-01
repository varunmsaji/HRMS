"""`POST /v1/attendance/face-punches/me` end to end: real app, DB, RBAC; fake face provider."""

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from entrypoints.api import app
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import FakeFaceProvider, FakePhotoStorage
from tests.integration.modules.attendance.test_attendance_security import (
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_face_enrollment import (
    IMAGES,
    _employee,
    enroll_and_approve,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.dependencies import get_face_provider
from hrms.modules.attendance.face_verification import (
    FaceMatchResult,
    FaceProviderError,
    LivenessResult,
)
from hrms.modules.attendance.permissions import ATTENDANCE_PUNCH, ATTENDANCE_VIEW

pytestmark = pytest.mark.asyncio

Tenant = tuple[dict[str, str], UUID]
_JPEG = IMAGES["front"]


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


async def _face_punch(
    client: AsyncClient, headers: dict[str, str], direction: str = "IN", image: bytes = _JPEG
) -> Any:
    return await client.post(
        "/v1/attendance/face-punches/me",
        headers=headers,
        files={"photo": ("frame.jpg", image, "image/jpeg")},
        data={"direction": direction},
    )


async def _attempts(company_id: UUID) -> list[dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text(
                "SELECT decision, punch_id, similarity, liveness_score FROM "
                "face_verification_attempt WHERE company_id = :cid ORDER BY created_at"
            ),
            {"cid": str(company_id)},
        )
        return [dict(r._mapping) for r in rows]


async def _punch_count(client: AsyncClient, headers: dict[str, str]) -> int:
    response = await client.get("/v1/attendance/punches", headers=headers)
    assert response.status_code == 200, response.text
    return len(response.json()["data"])


async def test_matched_face_records_server_timed_face_punch(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    self_headers, employee_id = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()

    response = await _face_punch(client, self_headers, "IN")

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["punch"]["source"] == "FACE"
    assert data["punch"]["direction"] == "IN"
    assert data["punch"]["employee_id"] == employee_id
    assert Decimal(data["similarity"]) == Decimal("0.97")
    assert Decimal(data["liveness_score"]) == Decimal("0.95")
    # Liveness first: a spoof never reaches (or pays for) the match call.
    assert fake_face_provider.names() == ["check_liveness", "verify"]

    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "MATCHED"
    assert str(attempt["punch_id"]) == data["punch"]["id"]
    assert await _punch_count(client, self_headers) == 1


async def test_not_enrolled_is_rejected_and_logged(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant, enroll=False)

    response = await _face_punch(client, self_headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FACE_NOT_ENROLLED"
    assert fake_face_provider.calls == []
    assert [a["decision"] for a in await _attempts(company_id)] == ["NOT_ENROLLED"]


async def test_revoked_profile_cannot_punch(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin_headers, _ = face_tenant
    self_headers, employee_id = await _enrolled_self(client, face_tenant)
    revoked = await client.delete(
        f"/v1/attendance/face-profiles/{employee_id}", headers=admin_headers
    )
    assert revoked.status_code == 200

    response = await _face_punch(client, self_headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FACE_NOT_ENROLLED"


async def test_spoof_is_rejected_before_matching(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()
    fake_face_provider.liveness = LivenessResult("SPOOF", Decimal("0.6944"), {"result": "fake"})

    response = await _face_punch(client, self_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_LIVENESS_FAILED"
    assert fake_face_provider.names() == ["check_liveness"]
    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "LIVENESS_FAILED"
    assert attempt["liveness_score"] == Decimal("0.6944")
    assert attempt["punch_id"] is None
    assert await _punch_count(client, self_headers) == 0


async def test_wrong_person_is_rejected(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.match = FaceMatchResult("NO_MATCH", None, {"message": "Not verified"})

    response = await _face_punch(client, self_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_NOT_MATCHED"
    assert [a["decision"] for a in await _attempts(company_id)] == ["NO_MATCH"]
    assert await _punch_count(client, self_headers) == 0


async def test_no_face_in_frame(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.liveness = LivenessResult("NO_FACE", None, {"message": "no faces"})

    response = await _face_punch(client, self_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_NOT_DETECTED"


async def test_provider_outage_is_502_and_logged(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.fail_with["verify"] = FaceProviderError("down")

    response = await _face_punch(client, self_headers)

    assert response.status_code == 502
    assert [a["decision"] for a in await _attempts(company_id)] == ["PROVIDER_ERROR"]
    assert await _punch_count(client, self_headers) == 0


async def test_failed_attempts_are_rate_limited(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    self_headers, _ = await _enrolled_self(client, face_tenant)
    # A successful punch does not count towards the limit.
    assert (await _face_punch(client, self_headers, "IN")).status_code == 201

    fake_face_provider.match = FaceMatchResult("NO_MATCH", None, {"message": "Not verified"})
    for _ in range(5):
        assert (await _face_punch(client, self_headers)).status_code == 422
    fake_face_provider.calls.clear()
    fake_face_provider.match = FaceMatchResult("MATCHED", Decimal("0.99"), {"message": "verified"})

    blocked = await _face_punch(client, self_headers, "OUT")

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

    response = await _face_punch(client, view_only)

    assert response.status_code == 403
    assert fake_face_provider.calls == []


async def test_invalid_direction_and_image(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    self_headers, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()

    assert (await _face_punch(client, self_headers, "SIDEWAYS")).status_code == 422
    bad_image = await _face_punch(client, self_headers, image=b"GIF89a not allowed")
    assert bad_image.status_code == 422
    assert bad_image.json()["error"]["code"] == "FACE_IMAGE_INVALID"
    assert fake_face_provider.calls == []


async def test_disabled_provider_is_503(client: AsyncClient, face_tenant: Tenant) -> None:
    app.dependency_overrides[get_face_provider] = lambda: FakeFaceProvider()
    try:
        self_headers, _ = await _enrolled_self(client, face_tenant)
        app.dependency_overrides[get_face_provider] = lambda: None
        response = await _face_punch(client, self_headers)
    finally:
        app.dependency_overrides.pop(get_face_provider, None)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "FACE_VERIFICATION_UNAVAILABLE"
