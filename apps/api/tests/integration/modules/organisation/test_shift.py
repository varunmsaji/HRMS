"""Integration tests for the Shift (identity) API.

W2 trimmed `Shift` to identity-only (name/code/active) — the nine legacy schedule/
evaluation fields moved to `ShiftVersion` (see test_shift_version.py for that surface).
Covers `/v1/shifts`: create (incl. auto-created initial draft version), list, get, update,
mass-assignment rejection, deactivation/reactivation, audit records, and not-found behavior.
Tenant isolation and permission-matrix coverage live in the sibling
`test_cross_tenant_isolation.py` / `test_permission_matrix.py` files.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.audit.models import AuditLog
from hrms.core.db.session import get_session_factory, set_rls_company_id

from .test_registration_flow import _cleanup, _register


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


async def _create_shift(
    client: AsyncClient, headers: dict[str, str], code: str = "GEN", **extra: Any
) -> dict[str, Any]:
    payload = {"code": code, "name": "General Shift", **extra}
    response = await client.post("/v1/shifts", headers=headers, json=payload)
    assert response.status_code == 201
    return dict(response.json()["data"])


async def _cleanup_shifts(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        # A pooled connection that has ever had `app.company_id` set reverts to `''` (not
        # NULL) once its transaction ends — a Postgres custom-GUC-placeholder quirk, not an
        # RLS bug. Setting it explicitly here avoids `invalid input syntax for type uuid: ""`
        # on this unscoped raw cleanup query.
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("DELETE FROM shift_version WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM shift WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_shifts_empty_state(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/shifts", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_shift_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/shifts", headers=headers, json={"code": "GEN", "name": "General Shift"}
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["code"] == "GEN"
        assert data["is_active"] is True
        assert data["version"] == 1
        assert data["company_id"] == str(company_id)
        # An empty DRAFT ShiftVersion is created in the same transaction — a shift with no
        # schedule at all is meaningless downstream.
        assert data["draft_version_id"] is not None
        assert data["current_version_id"] is None

        listed = await client.get("/v1/shifts", headers=headers)
        assert len(listed.json()["data"]) == 1
        assert listed.json()["data"][0]["draft_version_id"] == data["draft_version_id"]

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "shift",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "SHIFT_CREATED"

            version_audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "shift_version",
                            AuditLog.action == "SHIFT_VERSION_CREATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(version_audit_rows) == 1
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_shift_rejects_legacy_schedule_fields(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`extra="forbid"` on `ShiftCreate` — the nine legacy schedule/evaluation fields the
    pre-W2 API used to accept are now a 422, not just ignored."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/shifts",
            headers=headers,
            json={"name": "Bad Shift", "start_time": "09:00", "end_time": "18:00"},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_shift_same_code_different_tenant_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """No uniqueness constraint on `code` — see docs/modules/shift-rules/
    00_SHIFT_RULES_AUDIT.md §2 (unlike Grade's DB-level constraint)."""
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        await _create_shift(client, headers_a, code="GEN")
        response = await client.post(
            "/v1/shifts", headers=headers_b, json={"code": "GEN", "name": "General Shift"}
        )
        assert response.status_code == 201
    finally:
        await _cleanup_shifts(company_id=company_a)
        await _cleanup_shifts(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_create_shift_missing_required_fields_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post("/v1/shifts", headers=headers, json={})
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_shift_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/shifts",
            headers=headers,
            json={"name": "General Shift", "is_active": False, "version": 99},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_shift_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        response = await client.patch(
            f"/v1/shifts/{shift['id']}",
            headers={**headers, "If-Match": str(shift["version"])},
            json={"id": str(uuid4()), "company_id": str(uuid4())},
        )
        assert response.status_code == 422

        after = await client.get(f"/v1/shifts/{shift['id']}", headers=headers)
        assert after.json()["data"]["id"] == shift["id"]
        assert after.json()["data"]["company_id"] == str(company_id)
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_shift_not_found(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get(f"/v1/shifts/{uuid4()}", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_shift_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        response = await client.patch(
            f"/v1/shifts/{shift['id']}",
            headers={**headers, "If-Match": str(shift["version"])},
            json={"name": "Renamed Shift"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["name"] == "Renamed Shift"
        assert data["version"] == 2
        assert data["code"] == "GEN"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_shift_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        response = await client.patch(
            f"/v1/shifts/{shift['id']}",
            headers={**headers, "If-Match": "999"},
            json={"name": "Renamed"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivate_shift_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        response = await client.request(
            "DELETE",
            f"/v1/shifts/{shift['id']}",
            headers={**headers, "If-Match": str(shift["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(shift["id"]),
                            AuditLog.action == "SHIFT_DEACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_reactivate_shift_via_patch(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        deactivated = await client.request(
            "DELETE",
            f"/v1/shifts/{shift['id']}",
            headers={**headers, "If-Match": str(shift["version"])},
        )
        assert deactivated.json()["data"]["is_active"] is False
        version_after_deactivate = deactivated.json()["data"]["version"]

        reactivated = await client.patch(
            f"/v1/shifts/{shift['id']}",
            headers={**headers, "If-Match": str(version_after_deactivate)},
            json={"is_active": True},
        )
        assert reactivated.status_code == 200
        assert reactivated.json()["data"]["is_active"] is True

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(shift["id"]),
                            AuditLog.action == "SHIFT_REACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_multiple_shifts_supported(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_shift(client, headers, code="GEN")
        await _create_shift(client, headers, code="NGT")
        listed = await client.get("/v1/shifts", headers=headers)
        codes = {row["code"] for row in listed.json()["data"]}
        assert codes == {"GEN", "NGT"}
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
