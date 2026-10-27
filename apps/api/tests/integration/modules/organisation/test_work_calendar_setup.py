"""Work-calendar guided setup, range API and permissions (approved decisions A and B).

Needs the disposable integration stack (the root conftest refuses the shared dev stack).
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from tests.integration.modules.account_invite.uac_helpers import Tenant as UacTenant
from tests.integration.modules.account_invite.uac_helpers import onboard, teardown

from hrms.core.db.models.identity import Permission, Role, RolePermission
from hrms.core.db.session import get_session_factory
from hrms.modules.organisation.permissions import ORG_CALENDAR_MANAGE

from .test_registration_flow import _register
from .test_workforce_calendar import (
    _cleanup_workforce_calendar,
    _create_holiday,
    _create_holiday_calendar,
)

pytestmark = pytest.mark.asyncio

_CALENDAR_TABLES = (
    "policy_assignment",
    "calendar_exception",
    "work_calendar_holiday_calendar",
    "work_calendar",
    "weekly_off_rule",
    "weekly_off_pattern",
    "holiday",
    "holiday_calendar",
)


async def _new_tenant(client: AsyncClient) -> tuple[UacTenant, UUID]:
    response, company_id, user_id = await _register(client)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}", "X-Company-Id": str(company_id)}
    return UacTenant(
        headers=headers, company_id=company_id, admin_user_id=user_id, emails=[]
    ), company_id


async def _row_counts(company_id: UUID) -> dict[str, int]:
    async with get_session_factory()() as session:
        return {
            table: (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE company_id = :c"),
                    {"c": str(company_id)},
                )
            ).scalar_one()
            for table in _CALENDAR_TABLES
        }


async def _audit_actions(company_id: UUID) -> list[str]:
    async with get_session_factory()() as session:
        rows = await session.execute(
            text("SELECT action FROM audit_log WHERE company_id = :c"), {"c": str(company_id)}
        )
        return [r[0] for r in rows]


def _confirm_body(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "Head office",
        "weekly_off_weekdays": [5, 6],
        "holiday_calendar_ids": [],
        "effective_from": "2026-09-01",
        "confirm": True,
        **overrides,
    }


async def test_new_company_is_setup_required_with_unconfirmed_suggestion(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant, company_id = await _new_tenant(client)
    try:
        response = await client.get("/v1/work-calendar-setup", headers=tenant.headers)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["state"] == "SETUP_REQUIRED"
        assert data["suggestion"]["confirmed"] is False
        assert data["suggestion"]["holidays_included"] is False
        assert data["suggestion"]["weekly_off_weekdays"] == [5, 6]
        # nothing was created by registration or by reading the suggestion
        assert set((await _row_counts(company_id)).values()) == {0}
    finally:
        await teardown(tenant)


async def test_preview_writes_nothing_and_adds_no_holidays(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant, company_id = await _new_tenant(client)
    try:
        holiday_calendar = await _create_holiday_calendar(client, tenant.headers)
        await _create_holiday(client, tenant.headers, holiday_calendar["id"], date="2026-09-07")
        before = await _row_counts(company_id)
        audit_before = await _audit_actions(company_id)

        response = await client.post(
            "/v1/work-calendar-setup/preview",
            headers=tenant.headers,
            json={
                "weekly_off_weekdays": [5, 6],
                "holiday_calendar_ids": [holiday_calendar["id"]],
                "effective_from": "2026-09-01",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["preview_only"] is True
        kinds = {d["date"]: d["day_type"] for d in data["days"]}
        assert kinds["2026-09-05"] == "WEEKLY_OFF"  # Saturday
        assert kinds["2026-09-07"] == "HOLIDAY"  # the admin's own holiday
        assert kinds["2026-09-08"] == "WORKING"

        assert await _row_counts(company_id) == before
        assert await _audit_actions(company_id) == audit_before
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await teardown(tenant)


async def test_confirm_activates_once_and_audits(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant, company_id = await _new_tenant(client)
    try:
        first = await client.post(
            "/v1/work-calendar-setup/confirm", headers=tenant.headers, json=_confirm_body()
        )
        assert first.status_code == 201, first.text
        confirmed = first.json()["data"]
        assert confirmed["scope_type"] == "COMPANY"
        assert confirmed["confirmed_by"] == str(tenant.admin_user_id)

        counts = await _row_counts(company_id)
        assert counts["policy_assignment"] == 1
        assert counts["work_calendar"] == 1
        assert counts["weekly_off_pattern"] == 1
        assert counts["holiday"] == 0 and counts["holiday_calendar"] == 0  # no holidays seeded
        assert "WORK_CALENDAR_SETUP_CONFIRMED" in await _audit_actions(company_id)

        status = (await client.get("/v1/work-calendar-setup", headers=tenant.headers)).json()
        assert status["data"]["state"] == "CONFIGURED"

        # repeated request: refused, nothing duplicated
        again = await client.post(
            "/v1/work-calendar-setup/confirm", headers=tenant.headers, json=_confirm_body()
        )
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "WORK_CALENDAR_ALREADY_CONFIGURED"
        assert (await _row_counts(company_id)) == counts

        # the range API reflects what was activated
        days = await client.get(
            f"/v1/work-calendars/{confirmed['work_calendar_id']}/days",
            headers=tenant.headers,
            params={"from": "2026-09-04", "to": "2026-09-08"},
        )
        assert days.status_code == 200, days.text
        kinds = [d["day_type"] for d in days.json()["data"]["days"]]
        assert kinds == ["WORKING", "WEEKLY_OFF", "WEEKLY_OFF", "WORKING", "WORKING"]
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await teardown(tenant)


async def test_concurrent_confirms_create_exactly_one_assignment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant, company_id = await _new_tenant(client)
    try:
        results = await asyncio.gather(
            *(
                client.post(
                    "/v1/work-calendar-setup/confirm",
                    headers=tenant.headers,
                    json=_confirm_body(name=f"Calendar {i}"),
                )
                for i in range(3)
            )
        )
        assert sorted(r.status_code for r in results) == [201, 409, 409], [r.text for r in results]
        counts = await _row_counts(company_id)
        assert counts["policy_assignment"] == 1 and counts["work_calendar"] == 1
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await teardown(tenant)


async def test_confirm_requires_explicit_acknowledgement_and_rejects_client_company_id(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant, company_id = await _new_tenant(client)
    try:
        body = _confirm_body()
        del body["confirm"]
        assert (
            await client.post("/v1/work-calendar-setup/confirm", headers=tenant.headers, json=body)
        ).status_code == 422
        assert (
            await client.post(
                "/v1/work-calendar-setup/confirm",
                headers=tenant.headers,
                json=_confirm_body(company_id=str(uuid4())),
            )
        ).status_code == 422
        assert (await _row_counts(company_id))["policy_assignment"] == 0
    finally:
        await teardown(tenant)


async def test_hr_admin_can_activate_but_hr_without_grant_and_employee_cannot(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant, company_id = await _new_tenant(client)
    try:
        employee = await onboard(client, tenant, "EMPLOYEE")
        assert (
            await client.get("/v1/work-calendar-setup", headers=employee.headers)
        ).status_code == 403
        assert (
            await client.post(
                "/v1/work-calendar-setup/confirm", headers=employee.headers, json=_confirm_body()
            )
        ).status_code == 403

        hr = await onboard(client, tenant, "HR_ADMIN")
        async with get_session_factory()() as session:
            role = (
                await session.execute(
                    select(Role).where(Role.company_id == company_id, Role.code == "HR_ADMIN")
                )
            ).scalar_one()
            perm = (
                await session.execute(
                    select(Permission).where(Permission.code == ORG_CALENDAR_MANAGE)
                )
            ).scalar_one()
            # registration must have granted it
            granted = (
                await session.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id, RolePermission.permission_id == perm.id
                    )
                )
            ).scalar_one_or_none()
            assert granted is not None
        ok = await client.post(
            "/v1/work-calendar-setup/confirm", headers=hr.headers, json=_confirm_body()
        )
        assert ok.status_code == 201, ok.text

        # an HR_ADMIN whose grant was removed is denied by the backend
        async with get_session_factory()() as session:
            await session.execute(
                RolePermission.__table__.delete().where(
                    RolePermission.role_id == role.id, RolePermission.permission_id == perm.id
                )
            )
            await session.commit()
        denied = await client.get("/v1/work-calendar-setup", headers=hr.headers)
        assert denied.status_code == 403
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await teardown(tenant)


async def test_range_api_is_tenant_scoped_and_bounded(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant_a, company_a = await _new_tenant(client)
    tenant_b, company_b = await _new_tenant(client)
    try:
        created = await client.post(
            "/v1/work-calendar-setup/confirm", headers=tenant_a.headers, json=_confirm_body()
        )
        calendar_id = created.json()["data"]["work_calendar_id"]

        # another company's calendar is indistinguishable from a missing one
        cross = await client.get(
            f"/v1/work-calendars/{calendar_id}/days",
            headers=tenant_b.headers,
            params={"from": "2026-09-01", "to": "2026-09-07"},
        )
        assert cross.status_code == 404

        for params in (
            {"from": "2026-09-10", "to": "2026-09-01"},  # reversed
            {"from": "2026-01-01", "to": "2026-12-31"},  # longer than the limit
        ):
            bad = await client.get(
                f"/v1/work-calendars/{calendar_id}/days", headers=tenant_a.headers, params=params
            )
            assert bad.status_code == 422, bad.text
            assert bad.json()["error"]["code"] == "CALENDAR_RANGE_INVALID"
    finally:
        await _cleanup_workforce_calendar(company_id=company_a)
        await teardown(tenant_a)
        await teardown(tenant_b)
