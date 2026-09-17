"""Integration tests for C-11 subscription summary and C-12 company dashboard."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.organisation.models import CompanyFeatureFlag, Subscription
from hrms.modules.organisation.permissions import DASHBOARD_COMPANY_VIEW, ORG_COMPANY_MANAGE
from hrms.seed.plan_catalogue import SEAT_LIMIT_FEATURE_CODE

from .test_registration_flow import _cleanup, _register

SUBSCRIPTION_PATH = "/v1/companies/current/subscription"
DASHBOARD_PATH = "/v1/dashboards/company"


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
async def test_get_subscription_summary_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        response = await client.get(SUBSCRIPTION_PATH, headers=headers)
        assert response.status_code == 200
        data = response.json()["data"]

        assert data["plan"]["code"] == "FREE"
        assert data["plan"]["name"] == "Free"
        assert data["status"] == "TRIALING"
        assert data["trial_ends_at"] is not None
        assert data["seat_limit"] == 5
        features = {item["code"]: item for item in data["features"]}
        assert SEAT_LIMIT_FEATURE_CODE in features
        assert features[SEAT_LIMIT_FEATURE_CODE]["source"] == "PLAN"
        assert features[SEAT_LIMIT_FEATURE_CODE]["is_enabled"] is True
        assert features[SEAT_LIMIT_FEATURE_CODE]["limit_value"] == 5
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_subscription_summary_company_override(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        now = datetime.now(UTC)
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            session.add(
                CompanyFeatureFlag(
                    id=uuid4(),
                    company_id=company_id,
                    feature_code="BETA_PAYROLL_V2",
                    is_enabled=True,
                    overrides_plan=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        response = await client.get(SUBSCRIPTION_PATH, headers=headers)
        assert response.status_code == 200
        features = {item["code"]: item for item in response.json()["data"]["features"]}
        assert features["BETA_PAYROLL_V2"]["source"] == "COMPANY_OVERRIDE"
        assert features["BETA_PAYROLL_V2"]["is_enabled"] is True
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                CompanyFeatureFlag.__table__.delete().where(
                    CompanyFeatureFlag.company_id == company_id
                )
            )
            await session.commit()
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_subscription_requires_auth(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response = await client.get(SUBSCRIPTION_PATH)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_subscription_requires_permission(
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

        response = await client.get(SUBSCRIPTION_PATH, headers=headers)
        assert response.status_code == 403
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_dashboard_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        response = await client.get(DASHBOARD_PATH, headers=headers)
        assert response.status_code == 200
        data = response.json()["data"]

        assert data["setup_progress"]["status"] in {"IN_PROGRESS", "COMPLETE"}
        assert data["setup_progress"]["steps_total"] >= 1
        assert data["setup_progress"]["steps_completed"] >= 0
        assert data["subscription"] is not None
        assert data["subscription"]["plan_code"] == "FREE"
        assert data["subscription"]["status"] == "TRIALING"
        assert data["branch_count"] is None
        assert data["department_count"] is None
        assert data["employee_count"] is None
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_dashboard_requires_dashboard_permission(
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
            dash_perm = (
                await session.execute(
                    select(Permission).where(Permission.code == DASHBOARD_COMPANY_VIEW)
                )
            ).scalar_one()
            await session.execute(
                RolePermission.__table__.delete().where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == dash_perm.id,
                )
            )
            await session.commit()

        response = await client.get(DASHBOARD_PATH, headers=headers)
        assert response.status_code == 403
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_dashboard_requires_auth(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response = await client.get(DASHBOARD_PATH)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_subscription_idempotent_get(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        first = await client.get(SUBSCRIPTION_PATH, headers=headers)
        second = await client.get(SUBSCRIPTION_PATH, headers=headers)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["data"] == second.json()["data"]
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_subscription_summary_no_active_subscription_returns_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Registration always creates a TRIALING row when a default plan exists — simulate a
    company that never got one (or had it hard-deleted) by removing it after the fact."""
    headers, company_id, user_id = await _auth_headers(client)
    try:
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                Subscription.__table__.delete().where(Subscription.company_id == company_id)
            )
            await session.commit()

        response = await client.get(SUBSCRIPTION_PATH, headers=headers)
        assert response.status_code == 404

        dashboard = await client.get(DASHBOARD_PATH, headers=headers)
        assert dashboard.status_code == 200
        assert dashboard.json()["data"]["subscription"] is None
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_subscription_summary_expired_subscription_returns_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A terminal-status (EXPIRED) subscription is not "active" — `get_active_subscription`
    excludes CANCELED/EXPIRED rows, so the read path behaves the same as "no subscription"."""
    headers, company_id, user_id = await _auth_headers(client)
    try:
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                Subscription.__table__.update()
                .where(Subscription.company_id == company_id)
                .values(status="EXPIRED")
            )
            await session.commit()

        response = await client.get(SUBSCRIPTION_PATH, headers=headers)
        assert response.status_code == 404
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)
