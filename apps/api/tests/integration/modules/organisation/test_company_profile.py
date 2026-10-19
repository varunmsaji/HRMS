from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from hrms.core.audit.models import AuditLog
from hrms.core.db.models.identity import Company
from hrms.core.db.session import get_session_factory
from hrms.modules.organisation.permissions import ORG_COMPANY_MANAGE

from .test_registration_flow import _cleanup, _payload, _register

PROFILE_PATH = "/v1/companies/current"


async def _auth_headers(
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


@pytest.mark.asyncio
async def test_get_company_profile_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        response = await client.get(PROFILE_PATH, headers=headers)
        assert response.status_code == 200
        data = response.json()["data"]

        assert data["id"] == str(company_id)
        assert data["name"]
        assert data["status"] == "TRIAL"
        assert data["primary_legal_entity"] is None
        assert data["version"] == 1
        assert data["legal_name"] is None
        assert data["registration_number"] is None
        assert data["contact"]["email"] is None
        assert data["address"]["line1"] is None
        assert data["locale"]["language_code"] == "en-IN"
        assert data["locale"]["date_format"] == "DD/MM/YYYY"
        assert data["fiscal_year"]["start_month"] == 4
        assert len(data["working_days"]) == 7
        assert data["business_hours"] is None
        assert data["branding"]["logo_url"] is None
        assert data["branding"]["theme"] is None
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_company_profile_requires_auth(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response = await client.get(PROFILE_PATH)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_company_profile_requires_permission(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        factory = get_session_factory()
        async with factory() as session:
            from hrms.core.db.models.identity import Permission, Role, RolePermission

            role = (
                await session.execute(
                    select(Role).where(Role.company_id == company_id, Role.code == "COMPANY_ADMIN")
                )
            ).scalar_one()
            org_perm = (
                await session.execute(
                    select(Permission).where(Permission.code == ORG_COMPANY_MANAGE)
                )
            ).scalar_one()
            await session.execute(
                RolePermission.__table__.delete().where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == org_perm.id,
                )
            )
            await session.commit()

        response = await client.get(PROFILE_PATH, headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_company_profile_cross_tenant_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a_id, user_a_id = await _auth_headers(client)
    _headers_b, company_b_id, _user_b_id = await _auth_headers(client)
    try:
        response = await client.get(
            PROFILE_PATH,
            headers={
                "Authorization": headers_a["Authorization"],
                "X-Company-Id": str(company_b_id),
            },
        )
        assert response.status_code == 404
    finally:
        await _cleanup(company_id=company_a_id, user_id=user_a_id)
        await _cleanup(company_id=company_b_id, user_id=_user_b_id)


@pytest.mark.asyncio
async def test_patch_company_profile_success_and_audit(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        get_response = await client.get(PROFILE_PATH, headers=headers)
        assert get_response.status_code == 200
        version = get_response.json()["data"]["version"]

        patch_response = await client.patch(
            PROFILE_PATH,
            headers={**headers, "If-Match": str(version)},
            json={
                "legal_name": "Acme Manufacturing Private Limited",
                "contact": {
                    "email": "info@acme.example",
                    "phone": "+91-9876543210",
                    "website": None,
                },
                "business_hours": {"start_time": "09:30", "end_time": "18:30"},
            },
        )
        assert patch_response.status_code == 200
        data = patch_response.json()["data"]
        assert data["legal_name"] == "Acme Manufacturing Private Limited"
        assert data["contact"]["email"] == "info@acme.example"
        assert data["business_hours"] == {"start_time": "09:30", "end_time": "18:30"}
        assert data["version"] == version + 1

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.action == "UPDATED",
                            AuditLog.entity_type == "company",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            audit = audit_rows[0]
            assert audit.before_json is not None
            assert audit.after_json is not None
            assert audit.before_json["legal_name"] is None
            assert audit.after_json["legal_name"] == "Acme Manufacturing Private Limited"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_company_profile_non_indian_timezone_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`DEC-TZ-02` (SELECTED) — the SAME authenticated allow-list as registration, in the SAME
    order, on this profile-edit path. Before Phase 2, an admin could switch a live company to
    any of ~600 IANA zones (execution gate §6.3) — not the `TZ-01` "may it change at all" guard
    (Phase 3), a separate question about *which value* is acceptable."""
    headers, company_id, user_id = await _auth_headers(client)
    try:
        get_response = await client.get(PROFILE_PATH, headers=headers)
        version = get_response.json()["data"]["version"]
        response = await client.patch(
            PROFILE_PATH,
            headers={**headers, "If-Match": str(version)},
            json={"timezone": "America/Los_Angeles"},
        )
        assert response.status_code == 422, response.text
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_company_profile_asia_calcutta_canonicalised(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        get_response = await client.get(PROFILE_PATH, headers=headers)
        version = get_response.json()["data"]["version"]
        response = await client.patch(
            PROFILE_PATH,
            headers={**headers, "If-Match": str(version)},
            json={"timezone": "Asia/Calcutta"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["timezone"] == "Asia/Kolkata"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_company_profile_requires_if_match(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        response = await client.patch(
            PROFILE_PATH,
            headers=headers,
            json={"legal_name": "Should Fail"},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_company_profile_stale_version(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        get_response = await client.get(PROFILE_PATH, headers=headers)
        version = get_response.json()["data"]["version"]

        first = await client.patch(
            PROFILE_PATH,
            headers={**headers, "If-Match": str(version)},
            json={"legal_name": "First Update"},
        )
        assert first.status_code == 200

        stale = await client.patch(
            PROFILE_PATH,
            headers={**headers, "If-Match": str(version)},
            json={"legal_name": "Stale Update"},
        )
        assert stale.status_code == 409
        body = stale.json()["error"]
        assert body["code"] == "STALE_RESOURCE"
        assert body["details"][0]["context"]["current"]["legal_name"] == "First Update"
        assert body["details"][0]["context"]["current"]["version"] == version + 1

        factory = get_session_factory()
        async with factory() as session:
            company = (
                await session.execute(select(Company).where(Company.id == company_id))
            ).scalar_one()
            assert company.legal_name == "First Update"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_company_profile_invalid_working_days(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        version = (await client.get(PROFILE_PATH, headers=headers)).json()["data"]["version"]
        response = await client.patch(
            PROFILE_PATH,
            headers={**headers, "If-Match": str(version)},
            json={
                "working_days": [
                    {"day": "MON", "is_working": False, "is_alternate": False},
                    {"day": "TUE", "is_working": False, "is_alternate": False},
                    {"day": "WED", "is_working": False, "is_alternate": False},
                    {"day": "THU", "is_working": False, "is_alternate": False},
                    {"day": "FRI", "is_working": False, "is_alternate": False},
                    {"day": "SAT", "is_working": False, "is_alternate": False},
                    {"day": "SUN", "is_working": False, "is_alternate": False},
                ]
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_WORKING_DAYS"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_company_profile_invalid_business_hours(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        version = (await client.get(PROFILE_PATH, headers=headers)).json()["data"]["version"]
        response = await client.patch(
            PROFILE_PATH,
            headers={**headers, "If-Match": str(version)},
            json={"business_hours": {"start_time": "18:00", "end_time": "09:00"}},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_company_profile_currency_locked_after_trial(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                update(Company).where(Company.id == company_id).values(status="ACTIVE", version=1)
            )
            await session.commit()

        version = (await client.get(PROFILE_PATH, headers=headers)).json()["data"]["version"]
        response = await client.patch(
            PROFILE_PATH,
            headers={**headers, "If-Match": str(version)},
            json={"currency": "USD"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "CURRENCY_LOCKED"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_company_profile_currency_change_allowed_in_trial(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        version = (await client.get(PROFILE_PATH, headers=headers)).json()["data"]["version"]
        response = await client.patch(
            PROFILE_PATH,
            headers={**headers, "If-Match": str(version)},
            json={"currency": "USD"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["currency"] == "USD"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_company_profile_suspended_company_blocked(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                update(Company)
                .where(Company.id == company_id)
                .values(status="SUSPENDED", version=1)
            )
            await session.commit()

        version = (await client.get(PROFILE_PATH, headers=headers)).json()["data"]["version"]
        response = await client.patch(
            PROFILE_PATH,
            headers={**headers, "If-Match": str(version)},
            json={"legal_name": "Blocked"},
        )
        # The platform console's company gate (`core/auth/company_access.py`) refuses writes from a
        # SUSPENDED company before the service runs, with a specific code; the service's own
        # `CompanyWriteBlockedError` (423 LOCKED) is the second line of defence behind it.
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "COMPANY_SUSPENDED"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_company_profile_rejects_immutable_fields(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        version = (await client.get(PROFILE_PATH, headers=headers)).json()["data"]["version"]
        response = await client.patch(
            PROFILE_PATH,
            headers={**headers, "If-Match": str(version)},
            json={"status": "ACTIVE", "id": str(uuid4()), "subdomain": "evil", "version": 99},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_company_profile_cross_tenant_does_not_modify_other_company(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a_id, user_a_id = await _auth_headers(client)
    headers_b, company_b_id, user_b_id = await _auth_headers(client)
    try:
        version_a = (await client.get(PROFILE_PATH, headers=headers_a)).json()["data"]["version"]
        response = await client.patch(
            PROFILE_PATH,
            headers={
                "Authorization": headers_a["Authorization"],
                "X-Company-Id": str(company_b_id),
                "If-Match": str(version_a),
            },
            json={"legal_name": "Cross Tenant Attack"},
        )
        assert response.status_code == 404

        factory = get_session_factory()
        async with factory() as session:
            company_b = (
                await session.execute(select(Company).where(Company.id == company_b_id))
            ).scalar_one()
            assert company_b.legal_name is None
    finally:
        await _cleanup(company_id=company_a_id, user_id=user_a_id)
        await _cleanup(company_id=company_b_id, user_id=user_b_id)


@pytest.mark.asyncio
async def test_registration_authenticates_subsequent_profile_get(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    payload = _payload()
    response = await client.post("/v1/companies/register", json=payload)
    company_id: UUID | None = None
    user_id: UUID | None = None
    try:
        assert response.status_code == 201
        data = response.json()["data"]
        company_id = UUID(data["company_id"])
        factory = get_session_factory()
        async with factory() as session:
            user_id = (
                await session.execute(select(Company.created_by).where(Company.id == company_id))
            ).scalar_one()

        profile = await client.get(
            PROFILE_PATH,
            headers={
                "Authorization": f"Bearer {data['access_token']}",
                "X-Company-Id": str(company_id),
            },
        )
        assert profile.status_code == 200
        assert profile.json()["data"]["name"] == payload["name"]
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)
