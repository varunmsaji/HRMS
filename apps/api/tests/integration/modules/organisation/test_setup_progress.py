from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update

from hrms.core.db.models.identity import Company
from hrms.core.db.session import get_session_factory
from hrms.modules.organisation.models import CompanySetupProgress
from hrms.modules.organisation.permissions import ORG_COMPANY_MANAGE

from .test_registration_flow import _cleanup, _register

SETUP_PROGRESS_PATH = "/v1/companies/current/setup-progress"
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
async def test_get_setup_progress_success_newly_registered_company(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A freshly registered company always has valid defaults for every field
    `company_profile_is_complete` checks (name, currency, timezone, fy_start_month, >=1
    working day) — so the one V1 step, COMPANY_PROFILE, is complete immediately, matching
    04_API_Design.md §5's "implicitly complete once registration finishes"."""
    headers, company_id, user_id = await _auth_headers(client)
    try:
        response = await client.get(SETUP_PROGRESS_PATH, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert "meta" in body and "request_id" in body["meta"]

        data = body["data"]
        assert data["status"] == "COMPLETE"
        assert data["current_step"] is None
        assert data["steps"] == [
            {"code": "COMPANY_PROFILE", "label": "Company Profile", "is_complete": True}
        ]
        assert data["started_at"] is not None
        assert data["completed_at"] is not None
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_setup_progress_requires_auth(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response = await client.get(SETUP_PROGRESS_PATH)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_setup_progress_requires_permission(
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

        response = await client.get(SETUP_PROGRESS_PATH, headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_setup_progress_cross_tenant_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a_id, user_a_id = await _auth_headers(client)
    _headers_b, company_b_id, _user_b_id = await _auth_headers(client)
    try:
        response = await client.get(
            SETUP_PROGRESS_PATH,
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
async def test_get_setup_progress_incomplete_when_required_field_missing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Simulates a data-integrity gap the API layer itself can never produce (Pydantic
    already enforces `name` non-empty on every write) to prove `company_profile_is_complete`
    is a real predicate over row state, not a hardcoded True — same direct-DB-manipulation
    technique already used by `test_patch_company_profile_currency_locked_after_trial`."""
    headers, company_id, user_id = await _auth_headers(client)
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(update(Company).where(Company.id == company_id).values(name=""))
            await session.commit()

        response = await client.get(SETUP_PROGRESS_PATH, headers=headers)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "IN_PROGRESS"
        assert data["current_step"] == "COMPANY_PROFILE"
        assert data["steps"] == [
            {"code": "COMPANY_PROFILE", "label": "Company Profile", "is_complete": False}
        ]
        assert data["completed_at"] is None

        async with factory() as session:
            company = (
                await session.execute(select(Company).where(Company.id == company_id))
            ).scalar_one()
            assert company.onboarded_at is None
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_setup_progress_recovers_after_profile_fixed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Covers 'partially completed' -> 'fully completed', and proves setup-progress stays
    consistent with C-09: an update made through `PATCH /companies/current` is reflected on
    the very next `GET .../setup-progress` read."""
    headers, company_id, user_id = await _auth_headers(client)
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(update(Company).where(Company.id == company_id).values(name=""))
            await session.commit()

        broken = await client.get(SETUP_PROGRESS_PATH, headers=headers)
        assert broken.json()["data"]["status"] == "IN_PROGRESS"

        version = (await client.get(PROFILE_PATH, headers=headers)).json()["data"]["version"]
        patch_response = await client.patch(
            PROFILE_PATH,
            headers={**headers, "If-Match": str(version)},
            json={"name": "Acme Restored"},
        )
        assert patch_response.status_code == 200

        fixed = await client.get(SETUP_PROGRESS_PATH, headers=headers)
        assert fixed.status_code == 200
        data = fixed.json()["data"]
        assert data["status"] == "COMPLETE"
        assert data["steps"][0]["is_complete"] is True
        assert data["completed_at"] is not None
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_setup_progress_sets_onboarded_at_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        first = await client.get(SETUP_PROGRESS_PATH, headers=headers)
        assert first.json()["data"]["status"] == "COMPLETE"

        factory = get_session_factory()
        async with factory() as session:
            company = (
                await session.execute(select(Company).where(Company.id == company_id))
            ).scalar_one()
            onboarded_at_first = company.onboarded_at
            assert onboarded_at_first is not None

        second = await client.get(SETUP_PROGRESS_PATH, headers=headers)
        assert second.status_code == 200

        async with factory() as session:
            company = (
                await session.execute(select(Company).where(Company.id == company_id))
            ).scalar_one()
            assert company.onboarded_at == onboarded_at_first
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_setup_progress_persists_recomputed_row_state(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Database-consistency check: the recomputed status is written back to the
    `company_setup_progress` row itself (03_Database_Design.md §3 — "recomputed not
    hand-edited"), not just returned in the response body."""
    headers, company_id, user_id = await _auth_headers(client)
    try:
        response = await client.get(SETUP_PROGRESS_PATH, headers=headers)
        assert response.status_code == 200

        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(CompanySetupProgress).where(
                        CompanySetupProgress.company_id == company_id
                    )
                )
            ).scalar_one()
            assert row.status == "COMPLETE"
            assert row.steps_completed == ["COMPANY_PROFILE"]
            assert row.current_step is None
            assert row.completed_at is not None
            assert row.version == 2  # bumped once from the registration-time insert
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_setup_progress_idempotent_on_repeated_read(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        first = (await client.get(SETUP_PROGRESS_PATH, headers=headers)).json()["data"]
        second = (await client.get(SETUP_PROGRESS_PATH, headers=headers)).json()["data"]
        assert first == second
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_setup_progress_row_always_exists_after_registration(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """No 404/409 documented for this endpoint (04_API_Design.md §5) — the row is created
    at registration and is never independently deleted."""
    headers, company_id, user_id = await _auth_headers(client)
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(CompanySetupProgress).where(
                        CompanySetupProgress.company_id == company_id
                    )
                )
            ).scalar_one_or_none()
            assert row is not None
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_company_setup_progress_rls_policy_configured() -> None:
    """RLS/tenant structural expectation (C-04's `company_setup_progress` policy) — a
    catalog check, since the `hrms` test role is a superuser with `rolbypassrls = true`
    and transparently bypasses RLS regardless of `FORCE ROW LEVEL SECURITY`, matching the
    precedent in `test_company_feature_flag_constraint.py`."""
    factory = get_session_factory()
    async with factory() as session:
        relrowsecurity, relforcerowsecurity = (
            await session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'company_setup_progress'"
                )
            )
        ).one()
        assert relrowsecurity is True
        assert relforcerowsecurity is True

        policy_qual = (
            await session.execute(
                text(
                    "SELECT qual FROM pg_policies "
                    "WHERE tablename = 'company_setup_progress' AND policyname = 'tenant_isolation'"
                )
            )
        ).scalar_one()
        assert policy_qual == "(company_id = (current_setting('app.company_id'::text, true))::uuid)"
