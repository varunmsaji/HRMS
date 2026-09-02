"""Integration tests for the Onboarding module's O1 slice — `/v1/onboarding-cases`
(create/list/detail only; no token/public routes, no review/activation yet, per
`docs/modules/onboarding/01_ONBOARDING_MODULE_PLAN.md` §12 phase table).

Covers: create + envelope shape, permission gating, the duplicate-active-case block (plan §13
Q5), an invalid organisational reference, and cross-tenant isolation (a case in company A is
invisible — `404`, never `403` — to company B), mirroring the conventions established across the
employee module's own test suite (e.g. `test_employee_banking.py`)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.db.session import get_session_factory

from ..organisation.test_registration_flow import _cleanup, _register

pytestmark = pytest.mark.asyncio


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201
    assert company_id is not None
    data = response.json()["data"]
    return (
        {
            "Authorization": f"Bearer {data['access_token']}",
            "X-Company-Id": str(company_id),
        },
        company_id,
        user_id,
    )


def _case_payload(**overrides: Any) -> dict[str, Any]:
    unique = uuid4().hex[:10]
    payload = {
        "candidate_first_name": "Asha",
        "candidate_last_name": "Rao",
        "personal_email": f"asha-{unique}@personal.example",
        "personal_mobile": "9876543210",
        "proposed_joining_date": "2027-01-15",
    }
    payload.update(overrides)
    return payload


async def _cleanup_onboarding_cases(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM onboarding_case WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _teardown(*, company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_onboarding_cases(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def _create_permission_scoped_user(
    *,
    company_id: UUID,
    permission_codes: list[str],
    data_scope: str = "COMPANY",
) -> tuple[dict[str, str], UUID]:
    """Registers a second user in the same tenant, granted only the given permission codes —
    mirrors `test_employee_banking.py::_create_permission_scoped_user` exactly."""
    from uuid import uuid4 as _uuid4

    from hrms.core.auth.jwt import create_access_token
    from hrms.core.auth.passwords import hash_password
    from hrms.core.db.models.identity import (
        Permission,
        Role,
        RolePermission,
        Session,
        User,
        UserCompany,
        UserRole,
    )

    factory = get_session_factory()
    async with factory() as session:
        permissions = (
            (await session.execute(select(Permission).where(Permission.code.in_(permission_codes))))
            .scalars()
            .all()
        )
        assert len(permissions) == len(permission_codes)

        now = datetime.now(UTC)
        role_id = _uuid4()
        session.add(
            Role(
                id=role_id,
                company_id=company_id,
                code=f"ONBOARDING_TEST_ROLE_{role_id.hex[:8]}",
                name="Onboarding test role",
                is_system=False,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        for permission in permissions:
            session.add(
                RolePermission(role_id=role_id, permission_id=permission.id, data_scope=data_scope)
            )

        scoped_user_id = _uuid4()
        session.add(
            User(
                id=scoped_user_id,
                email=f"scoped-onboarding-{scoped_user_id.hex[:8]}@example.com",
                password_hash=hash_password("CorrectHorse9"),
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        user_company = UserCompany(
            id=_uuid4(),
            user_id=scoped_user_id,
            company_id=company_id,
            is_primary=True,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(user_company)
        await session.flush()
        session.add(UserRole(id=_uuid4(), user_company_id=user_company.id, role_id=role_id))
        scoped_session_id = _uuid4()
        session.add(
            Session(
                id=scoped_session_id,
                user_id=scoped_user_id,
                company_id=company_id,
                expires_at=now + timedelta(days=1),
            )
        )
        await session.commit()

    token = create_access_token(
        user_id=scoped_user_id,
        company_id=company_id,
        session_id=scoped_session_id,
        employee_id=None,
    )
    return (
        {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)},
        scoped_user_id,
    )


async def _cleanup_scoped_users() -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                "DELETE FROM session WHERE user_id IN "
                "(SELECT id FROM \"user\" WHERE email LIKE 'scoped-onboarding-%')"
            )
        )
        await session.execute(text("DELETE FROM \"user\" WHERE email LIKE 'scoped-onboarding-%'"))
        await session.commit()


async def test_create_onboarding_case_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/onboarding-cases", headers=headers, json=_case_payload()
        )
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert data["status"] == "DRAFT"
        assert data["candidate_first_name"] == "Asha"
        assert data["employee_id"] is None
        assert data["version"] == 1
        assert data["company_id"] == str(company_id)
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_onboarding_case_duplicate_active_blocked(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        payload = _case_payload()
        first = await client.post("/v1/onboarding-cases", headers=headers, json=payload)
        assert first.status_code == 201, first.text

        second = await client.post(
            "/v1/onboarding-cases",
            headers=headers,
            json=_case_payload(personal_email=payload["personal_email"]),
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "DUPLICATE_ACTIVE_ONBOARDING_CASE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_onboarding_case_invalid_designation_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/onboarding-cases",
            headers=headers,
            json=_case_payload(designation_id=str(uuid4())),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_DESIGNATION"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_onboarding_case_without_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[]
        )
        response = await client.post(
            "/v1/onboarding-cases", headers=scoped_headers, json=_case_payload()
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_list_and_get_onboarding_case(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        created = (
            await client.post("/v1/onboarding-cases", headers=headers, json=_case_payload())
        ).json()["data"]

        list_response = await client.get("/v1/onboarding-cases", headers=headers)
        assert list_response.status_code == 200
        ids = [row["id"] for row in list_response.json()["data"]]
        assert created["id"] in ids

        filtered = await client.get(
            "/v1/onboarding-cases", headers=headers, params={"status": "DRAFT"}
        )
        assert created["id"] in [row["id"] for row in filtered.json()["data"]]

        empty_filter = await client.get(
            "/v1/onboarding-cases", headers=headers, params={"status": "ACTIVATED"}
        )
        assert created["id"] not in [row["id"] for row in empty_filter.json()["data"]]

        get_response = await client.get(
            f"/v1/onboarding-cases/{created['id']}", headers=headers
        )
        assert get_response.status_code == 200
        assert get_response.json()["data"]["id"] == created["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_get_onboarding_case_not_found(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get(f"/v1/onboarding-cases/{uuid4()}", headers=headers)
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_onboarding_case_cross_tenant_isolation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A case created in company A must be invisible — `404`, never `403` — to company B, the
    highest-risk property this slice has (same posture the plan calls out, §10, for the later
    token-based public surface)."""
    headers_a, company_id_a, user_id_a = await _register_tenant(client)
    headers_b, company_id_b, user_id_b = await _register_tenant(client)
    try:
        created = (
            await client.post("/v1/onboarding-cases", headers=headers_a, json=_case_payload())
        ).json()["data"]

        response = await client.get(f"/v1/onboarding-cases/{created['id']}", headers=headers_b)
        assert response.status_code == 404

        list_response = await client.get("/v1/onboarding-cases", headers=headers_b)
        assert created["id"] not in [row["id"] for row in list_response.json()["data"]]
    finally:
        await _teardown(company_id=company_id_a, user_id=user_id_a)
        await _teardown(company_id=company_id_b, user_id=user_id_b)
