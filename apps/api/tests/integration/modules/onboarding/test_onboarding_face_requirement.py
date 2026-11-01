"""Onboarding shows the company's face-enrollment requirement without blocking activation:
the employee is activated normally, and onboarding is only *complete* once the requirement is met
(not required, or HR-approved ENROLLED). The state comes from the attendance module's single
source of truth (`employee_face_profile`), never from onboarding itself."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory, set_rls_company_id

from .test_onboarding_activation import _full_teardown, _verified_case
from .test_onboarding_case import _register_tenant

pytestmark = pytest.mark.asyncio


async def _drop_policy(company_id: UUID) -> None:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("DELETE FROM company_face_policy WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.commit()


async def test_activation_is_not_blocked_but_onboarding_waits_for_required_face(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await client.put(
            "/v1/attendance/face-enrollment-policy",
            headers=headers,
            json={"require_enrollment_on_onboarding": True},
        )
        assert policy.status_code == 200, policy.text

        case = await _verified_case(client, headers, company_id, with_org=True)
        before = (await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)).json()[
            "data"
        ]
        assert before["face_enrollment_required"] is True
        assert before["face_enrollment"] is None  # no employee yet
        assert before["onboarding_requirements_complete"] is False

        activated = await client.post(
            f"/v1/onboarding-cases/{case['id']}/activate", headers=headers
        )
        assert activated.status_code == 200, activated.text  # activation is not blocked

        after = (await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)).json()[
            "data"
        ]
        assert after["status"] == "ACTIVATED"
        assert after["face_enrollment"] == {
            "required": True,
            "state": "NOT_ENROLLED",
            "requirement_met": False,
        }
        assert after["onboarding_requirements_complete"] is False
    finally:
        await _drop_policy(company_id)
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_onboarding_completes_without_face_when_not_required(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)
        assert (
            await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        ).status_code == 200
        data = (await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)).json()[
            "data"
        ]
        assert data["face_enrollment_required"] is False
        assert data["face_enrollment"]["state"] == "NOT_ENROLLED"
        assert data["face_enrollment"]["requirement_met"] is True
        assert data["onboarding_requirements_complete"] is True
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)
