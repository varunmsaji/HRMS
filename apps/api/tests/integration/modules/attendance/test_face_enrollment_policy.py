"""Company face-enrollment policy, the derived enrollment state, self-service start and the
onboarding view. Reuses the existing enrollment infrastructure (window, liveness, consent, HR
approval); nothing here can mark an employee enrolled without a real submission + approval."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.conftest import FakeFaceProvider
from tests.integration.modules.attendance.test_attendance_day import (
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_face_enrollment import (
    _audit_actions,
    _employee,
    _open,
    _self_headers,
    _submit,
    enroll_and_approve,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio

Tenant = tuple[dict[str, str], UUID]
POLICY = "/v1/attendance/face-enrollment-policy"


async def _set(client: AsyncClient, headers: dict[str, str], value: bool) -> object:
    return await client.put(
        POLICY, headers=headers, json={"require_enrollment_on_onboarding": value}
    )


async def test_policy_defaults_to_not_required_and_can_be_toggled_with_audit(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    got = await client.get(POLICY, headers=admin)
    assert got.json()["data"] == {"require_enrollment_on_onboarding": False}

    on = await _set(client, admin, True)
    assert on.status_code == 200 and on.json()["data"]["require_enrollment_on_onboarding"] is True
    assert (await client.get(POLICY, headers=admin)).json()["data"][
        "require_enrollment_on_onboarding"
    ] is True
    off = await _set(client, admin, False)
    assert off.json()["data"]["require_enrollment_on_onboarding"] is False

    from tests.integration.modules.attendance.test_face_enrollment import _sql

    rows = await _sql(
        company_id,
        "SELECT action FROM audit_log WHERE company_id = :cid AND "
        "action = 'FACE_ENROLLMENT_POLICY_UPDATED'",
    )
    assert len(rows) == 2


async def test_policy_requires_enrollment_manage_permission_and_rejects_extra_fields(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    me = await _self_headers(company_id, employee_id)
    assert (await client.get(POLICY, headers=me)).status_code == 403
    assert (await _set(client, me, True)).status_code == 403  # type: ignore[attr-defined]
    bad = await client.put(
        POLICY, headers=admin, json={"require_enrollment_on_onboarding": True, "company_id": "x"}
    )
    assert bad.status_code == 422


async def test_policy_is_per_company(client: AsyncClient, face_tenant: Tenant) -> None:
    admin_a, _ = face_tenant
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        await _set(client, admin_a, True)
        got_b = await client.get(POLICY, headers=headers_b)
        assert got_b.json()["data"]["require_enrollment_on_onboarding"] is False
    finally:
        from tests.integration.modules.attendance.test_face_enrollment import _sql

        await _sql(company_b, "DELETE FROM company_face_policy WHERE company_id = :cid")
        await _cleanup_attendance_day(company_id=company_b)
        await _cleanup(company_id=company_b, user_id=user_b)


async def test_state_flows_not_enrolled_to_available_pending_enrolled(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    me = await _self_headers(company_id, employee_id)

    def state(r: object) -> str:
        return r.json()["data"]["enrollment_state"]  # type: ignore[attr-defined]

    first = await client.get("/v1/attendance/face-enrollment/me", headers=me)
    assert state(first) == "NOT_ENROLLED"
    assert first.json()["data"]["company_requires_enrollment"] is False

    await _set(client, admin, True)
    again = await client.get("/v1/attendance/face-enrollment/me", headers=me)
    assert again.json()["data"]["company_requires_enrollment"] is True
    assert state(again) == "NOT_ENROLLED"  # enabling the policy never fakes enrollment

    started = await client.post("/v1/attendance/face-enrollment/me/window", headers=me)
    assert started.status_code == 201, started.text
    assert state(await client.get("/v1/attendance/face-enrollment/me", headers=me)) == (
        "ENROLLMENT_AVAILABLE"
    )

    assert (await _submit(client, me)).status_code == 201
    assert state(await client.get("/v1/attendance/face-enrollment/me", headers=me)) == (
        "PENDING_APPROVAL"
    )
    # Still not usable for face punches until HR approves.
    assert (await client.get("/v1/attendance/face-enrollment/me", headers=me)).json()["data"][
        "face_verification_required"
    ] is False

    approved = await client.post(
        f"/v1/attendance/face-profiles/{employee_id}/approve", headers=admin
    )
    assert approved.status_code == 200
    assert state(await client.get("/v1/attendance/face-enrollment/me", headers=me)) == "ENROLLED"


async def test_self_start_is_self_only_audited_and_blocked_while_enrolled(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    other_id = await _employee(client, admin, "Other")
    me = await _self_headers(company_id, employee_id)

    # No employee id in the request: the route cannot be pointed at someone else.
    assert (
        await client.post(
            "/v1/attendance/face-enrollment/me/window", headers=me, params={"employee_id": other_id}
        )
    ).status_code == 201
    other_state = await client.get(
        f"/v1/attendance/face-profiles/{other_id}/enrollment", headers=admin
    )
    assert other_state.json()["data"]["open_window"] is None  # untouched
    own_state = await client.get(
        f"/v1/attendance/face-profiles/{employee_id}/enrollment", headers=admin
    )
    assert own_state.json()["data"]["open_window"] is not None

    assert "FACE_ENROLLMENT_OPENED" in await _audit_actions(company_id)

    # Once enrolled, self-start must not silently replace the enrollment.
    await enroll_and_approve(client, admin, company_id, employee_id)
    again = await client.post("/v1/attendance/face-enrollment/me/window", headers=me)
    assert again.status_code == 409, again.text


async def test_self_start_needs_punch_permission_and_hr_open_still_works(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    me = await _self_headers(company_id, employee_id)
    # HR initiation is unchanged and still gated away from the employee.
    assert (await _open(client, me, employee_id)).status_code == 403
    assert (await _open(client, admin, employee_id)).status_code == 201
    # Anonymous self-start is refused.
    assert (await client.post("/v1/attendance/face-enrollment/me/window")).status_code in (401, 403)
