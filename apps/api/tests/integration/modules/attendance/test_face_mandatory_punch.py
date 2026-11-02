"""Mandatory face verification for self-service punches by ENROLLED employees.

Rule under test: `POST /attendance/punches/me` answers 403 `FACE_VERIFICATION_REQUIRED` for an
employee whose face profile is ENROLLED; employees with no profile, a PENDING_APPROVAL or a
revoked profile keep the plain punch; the HR on-behalf correction (`POST /attendance/punches`) is
the recovery path and stays available. Challenge replay / expiry / cross-employee semantics are
covered in `test_face_liveness_session.py` and `test_face_punch.py`."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import FakeFaceProvider, FakePhotoStorage
from tests.integration.modules.attendance.test_face_enrollment import (
    _employee,
    _open,
    _self_headers,
    _submit,
)
from tests.integration.modules.attendance.test_face_punch import (
    _enrolled_self,
    _punch_count,
    challenge,
    face_punch,
    submit,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.face_verification import FaceProviderError

pytestmark = pytest.mark.asyncio

Tenant = tuple[dict[str, str], UUID]
PLAIN = "/v1/attendance/punches/me"


@pytest.fixture(autouse=True)
def _photo_storage(fake_photo_storage: FakePhotoStorage) -> None:
    """Enrollment stores a review photo; keep it in memory for every test here."""


async def _audit_actions(company_id: UUID, employee_id: str) -> list[str]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text(
                "SELECT action FROM audit_log WHERE company_id = :c AND entity_id = :e "
                "AND action = 'PUNCH_REJECTED_FACE_REQUIRED'"
            ),
            {"c": str(company_id), "e": employee_id},
        )
        return [r[0] for r in rows]


# --- enforcement ----------------------------------------------------------------------------


async def test_enrolled_employee_plain_punch_out_is_allowed(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """Face verification gates check-in only; a plain check-out always works."""
    me, _ = await _enrolled_self(client, face_tenant)

    response = await client.post(PLAIN, headers=me, json={"direction": "OUT"})

    assert response.status_code == 201, response.text


async def test_enrolled_employee_plain_punch_in_is_403_and_audited(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    me, employee_id = await _enrolled_self(client, face_tenant)

    response = await client.post(PLAIN, headers=me, json={"direction": "IN"})

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FACE_VERIFICATION_REQUIRED"
    assert await _punch_count(client, me) == 0
    assert await _audit_actions(company_id, employee_id) == ["PUNCH_REJECTED_FACE_REQUIRED"]


async def test_enrolled_employee_plain_punch_with_idempotency_key_is_still_refused(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """A key cannot be used to replay an earlier plain punch around the rule."""
    me, _ = await _enrolled_self(client, face_tenant)

    for _ in range(2):
        response = await client.post(
            PLAIN, headers=me, json={"direction": "IN", "idempotency_key": "k" * 20}
        )
        assert response.status_code == 403, response.text
    assert await _punch_count(client, me) == 0


async def test_enrolled_employee_face_punch_in_then_out_succeeds(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    me, _ = await _enrolled_self(client, face_tenant)

    assert (await face_punch(client, me, "IN")).status_code == 201
    assert (await face_punch(client, me, "OUT")).status_code == 201

    punches = (await client.get("/v1/attendance/punches", headers=me)).json()["data"]
    assert sorted((p["direction"], p["source"]) for p in punches) == [
        ("IN", "FACE"),
        ("OUT", "FACE"),
    ]


async def test_direct_api_bypass_attempts_do_not_create_a_punch(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """Direct calls that skip the UI: no body fields (source/employee/time) change the outcome,
    a face punch without a challenge is refused, and the on-behalf route is not open to the
    employee's own SELF grant."""
    me, employee_id = await _enrolled_self(client, face_tenant)

    forged = await client.post(
        PLAIN,
        headers=me,
        json={"direction": "IN", "source": "FACE", "employee_id": employee_id},
    )
    no_challenge = await submit(client, me, session_id=None)
    on_behalf = await client.post(
        "/v1/attendance/punches",
        headers=me,
        json={"employee_id": employee_id, "punch_time": "2026-08-10T09:00:00Z", "direction": "IN"},
    )

    assert forged.status_code in (403, 422), forged.text
    assert no_challenge.status_code >= 400
    assert on_behalf.status_code == 403
    assert await _punch_count(client, me) == 0


async def test_another_employees_verification_cannot_punch_for_me(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """B's challenge presented by A is invalid, and A's plain punch is still refused."""
    a, _ = await _enrolled_self(client, face_tenant)
    b, _ = await _enrolled_self(client, face_tenant)
    b_session = (await challenge(client, b, "IN")).json()["data"]["session_id"]

    stolen = await submit(client, a, session_id=b_session)
    plain = await client.post(PLAIN, headers=a, json={"direction": "IN"})

    assert stolen.status_code >= 400
    assert plain.status_code == 403
    assert await _punch_count(client, a) == 0


# --- policy for employees who are not ENROLLED ------------------------------------------------


async def test_employee_without_a_profile_keeps_the_plain_punch(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    me, _ = await _enrolled_self(client, face_tenant, enroll=False)

    for direction in ("IN", "OUT"):
        response = await client.post(PLAIN, headers=me, json={"direction": direction})
        assert response.status_code == 201, response.text
        assert response.json()["data"]["source"] == "WEB"


async def test_pending_approval_employee_keeps_the_plain_punch(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    assert (await _open(client, admin, employee_id)).status_code == 201
    me = await _self_headers(company_id, employee_id)
    assert (await _submit(client, me)).status_code == 201  # PENDING_APPROVAL, not approved

    status = (await client.get("/v1/attendance/face-enrollment/me", headers=me)).json()["data"]
    response = await client.post(PLAIN, headers=me, json={"direction": "IN"})

    assert status["profile"]["status"] == "PENDING_APPROVAL"
    assert status["face_verification_required"] is False
    assert response.status_code == 201, response.text


async def test_revoked_profile_returns_to_plain_punch(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, _ = face_tenant
    me, employee_id = await _enrolled_self(client, face_tenant)
    assert (await client.post(PLAIN, headers=me, json={"direction": "IN"})).status_code == 403

    revoked = await client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=admin)
    assert revoked.status_code == 200

    status = (await client.get("/v1/attendance/face-enrollment/me", headers=me)).json()["data"]
    assert status["face_verification_required"] is False
    assert (await client.post(PLAIN, headers=me, json={"direction": "IN"})).status_code == 201


async def test_status_flag_is_true_only_when_enrolled(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    me, _ = await _enrolled_self(client, face_tenant)
    status = (await client.get("/v1/attendance/face-enrollment/me", headers=me)).json()["data"]
    assert status["face_verification_required"] is True


# --- tenant isolation and existing protections ------------------------------------------------


async def test_enrolment_in_one_tenant_does_not_affect_another_tenants_employee(
    client: AsyncClient,
    face_tenant: Tenant,
    face_tenant_b: Tenant,
    fake_face_provider: FakeFaceProvider,
) -> None:
    enrolled, _ = await _enrolled_self(client, face_tenant)
    other, _ = await _enrolled_self(client, face_tenant_b, enroll=False)

    assert (await client.post(PLAIN, headers=enrolled, json={"direction": "IN"})).status_code == 403
    assert (await client.post(PLAIN, headers=other, json={"direction": "IN"})).status_code == 201
    assert (await client.get("/v1/attendance/face-enrollment/me", headers=other)).json()["data"][
        "face_verification_required"
    ] is False


async def test_missing_punch_permission_still_wins_over_the_face_rule(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    response = await client.post(PLAIN, json={"direction": "IN"})
    assert response.status_code == 401


async def test_unenrolled_plain_punch_duplicate_protection_is_unchanged(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    me, _ = await _enrolled_self(client, face_tenant, enroll=False)
    body = {"direction": "IN", "idempotency_key": "a" * 20}

    first = await client.post(PLAIN, headers=me, json=body)
    second = await client.post(PLAIN, headers=me, json=body)
    other_direction = await client.post(PLAIN, headers=me, json={**body, "direction": "OUT"})

    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert other_direction.status_code == 409
    assert await _punch_count(client, me) == 1


# --- verification failure, outage, and the HR recovery path -----------------------------------


async def test_provider_outage_does_not_fall_back_to_a_plain_punch(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    me, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.fail_with["verify"] = FaceProviderError("down")

    failed = await face_punch(client, me, "IN")
    plain = await client.post(PLAIN, headers=me, json={"direction": "IN"})

    assert failed.status_code == 502
    assert plain.status_code == 403
    assert await _punch_count(client, me) == 0


async def test_hr_on_behalf_correction_remains_the_recovery_path(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    me, employee_id = await _enrolled_self(client, face_tenant)
    fake_face_provider.fail_with["verify"] = FaceProviderError("down")
    assert (await face_punch(client, me, "IN")).status_code == 502

    corrected = await client.post(
        "/v1/attendance/punches",
        headers=admin,
        json={
            "employee_id": employee_id,
            "punch_time": "2026-08-10T09:00:00Z",
            "direction": "IN",
            "reference": "face service outage",
        },
    )

    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["data"]["source"] == "ADMIN"
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE company_id = :c "
                    "AND action = 'PUNCH_CREATED' AND entity_id = :p"
                ),
                {"c": str(company_id), "p": corrected.json()["data"]["id"]},
            )
        ).scalar_one()
    assert audited == 1


async def test_disabled_face_service_blocks_enrolled_employee_without_fallback(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """Face engine switched off after enrolment: the employee is neither verified nor allowed a
    plain punch (the HR correction is the way through)."""
    from entrypoints.api import app

    from hrms.modules.attendance.dependencies import get_face_provider

    me, _ = await _enrolled_self(client, face_tenant)
    app.dependency_overrides[get_face_provider] = lambda: None
    try:
        issued = await challenge(client, me, "IN")
        plain = await client.post(PLAIN, headers=me, json={"direction": "IN"})
    finally:
        app.dependency_overrides[get_face_provider] = lambda: fake_face_provider
    assert issued.status_code == 503
    assert plain.status_code == 403
