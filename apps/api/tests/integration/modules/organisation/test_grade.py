"""Integration tests for the Grade API — Sprint 3 vertical slice.

Covers the `/v1/grades` surface: create, list, get, update, validation (`min_ctc <=
max_ctc`, code uniqueness, mass-assignment), deactivation/reactivation (no dependency-
blocking rule applies this slice — see docs/modules/grade/00_GRADE_AUDIT.md §6.3), audit
records, and not-found behavior. Also covers the Designation↔Grade relationship
(`designation.grade_id`) added by this slice. Tenant isolation and permission-matrix
coverage live in the sibling `test_cross_tenant_isolation.py` / `test_permission_matrix.py`
files.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.audit.models import AuditLog
from hrms.core.db.session import get_session_factory

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


async def _create_grade(
    client: AsyncClient, headers: dict[str, str], code: str = "L5", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/grades", headers=headers, json={"code": code, "name": "Senior Engineer", **extra}
    )
    assert response.status_code == 201
    return dict(response.json()["data"])


async def _cleanup_grades_and_designations(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM designation WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM grade WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_grades_empty_state(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/grades", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_grade_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/grades",
            headers=headers,
            json={"code": "L5", "name": "Senior Engineer", "level": 5},
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["code"] == "L5"
        assert data["level"] == 5
        assert data["is_active"] is True
        assert data["version"] == 1
        assert data["company_id"] == str(company_id)

        listed = await client.get("/v1/grades", headers=headers)
        assert len(listed.json()["data"]) == 1

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "grade",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "GRADE_CREATED"
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_grade_with_ctc_band_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/grades",
            headers=headers,
            json={
                "code": "L5",
                "name": "Senior Engineer",
                "min_ctc": 1_000_000,
                "max_ctc": 2_000_000,
            },
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["min_ctc"] == 1_000_000
        assert data["max_ctc"] == 2_000_000
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_grade_invalid_ctc_range_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/grades",
            headers=headers,
            json={
                "code": "L5",
                "name": "Senior Engineer",
                "min_ctc": 2_000_000,
                "max_ctc": 1_000_000,
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_CTC_RANGE"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_grade_duplicate_code_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_grade(client, headers, code="L5")
        response = await client.post(
            "/v1/grades", headers=headers, json={"code": "L5", "name": "Duplicate"}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "GRADE_CODE_ALREADY_EXISTS"
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_grade_same_code_different_tenant_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        await _create_grade(client, headers_a, code="L5")
        response = await client.post(
            "/v1/grades", headers=headers_b, json={"code": "L5", "name": "Senior Engineer"}
        )
        assert response.status_code == 201
    finally:
        await _cleanup_grades_and_designations(company_id=company_a)
        await _cleanup_grades_and_designations(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_create_grade_missing_required_fields_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post("/v1/grades", headers=headers, json={})
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_grade_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/grades",
            headers=headers,
            json={"code": "L5", "name": "Senior Engineer", "is_active": False, "version": 99},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_grade_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        grade = await _create_grade(client, headers)
        response = await client.patch(
            f"/v1/grades/{grade['id']}",
            headers={**headers, "If-Match": str(grade["version"])},
            json={"id": str(uuid4()), "company_id": str(uuid4())},
        )
        assert response.status_code == 422

        after = await client.get(f"/v1/grades/{grade['id']}", headers=headers)
        assert after.json()["data"]["id"] == grade["id"]
        assert after.json()["data"]["company_id"] == str(company_id)
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_grade_not_found(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get(f"/v1/grades/{uuid4()}", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_grade_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        grade = await _create_grade(client, headers)
        response = await client.patch(
            f"/v1/grades/{grade['id']}",
            headers={**headers, "If-Match": str(grade["version"])},
            json={"level": 6},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["level"] == 6
        assert data["version"] == 2
        assert data["code"] == "L5"
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_grade_invalid_ctc_range_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        grade = await _create_grade(client, headers, min_ctc=1_000_000, max_ctc=2_000_000)
        response = await client.patch(
            f"/v1/grades/{grade['id']}",
            headers={**headers, "If-Match": str(grade["version"])},
            json={"max_ctc": 500_000},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_CTC_RANGE"
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_grade_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        grade = await _create_grade(client, headers)
        response = await client.patch(
            f"/v1/grades/{grade['id']}",
            headers={**headers, "If-Match": "999"},
            json={"name": "Renamed"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivate_grade_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        grade = await _create_grade(client, headers)
        response = await client.request(
            "DELETE",
            f"/v1/grades/{grade['id']}",
            headers={**headers, "If-Match": str(grade["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(grade["id"]),
                            AuditLog.action == "GRADE_DEACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivate_grade_not_blocked_by_active_designation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """No documented dependency-blocking rule applies to Grade this slice — see
    docs/modules/grade/00_GRADE_AUDIT.md §6.3. A grade referenced by an active designation
    can still be deactivated."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        grade = await _create_grade(client, headers)
        await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Software Engineer", "grade_id": grade["id"]},
        )

        response = await client.request(
            "DELETE",
            f"/v1/grades/{grade['id']}",
            headers={**headers, "If-Match": str(grade["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_reactivate_grade_via_patch(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        grade = await _create_grade(client, headers)
        deactivated = await client.request(
            "DELETE",
            f"/v1/grades/{grade['id']}",
            headers={**headers, "If-Match": str(grade["version"])},
        )
        assert deactivated.json()["data"]["is_active"] is False
        version_after_deactivate = deactivated.json()["data"]["version"]

        reactivated = await client.patch(
            f"/v1/grades/{grade['id']}",
            headers={**headers, "If-Match": str(version_after_deactivate)},
            json={"is_active": True},
        )
        assert reactivated.status_code == 200
        assert reactivated.json()["data"]["is_active"] is True

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(grade["id"]),
                            AuditLog.action == "GRADE_REACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_multiple_grades_supported(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_grade(client, headers, code="L4")
        await _create_grade(client, headers, code="L5")
        listed = await client.get("/v1/grades", headers=headers)
        codes = {row["code"] for row in listed.json()["data"]}
        assert codes == {"L4", "L5"}
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- Designation ↔ Grade relationship (added this slice) ---------------------------------


@pytest.mark.asyncio
async def test_create_designation_with_grade_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        grade = await _create_grade(client, headers)
        response = await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Software Engineer", "grade_id": grade["id"]},
        )
        assert response.status_code == 201
        assert response.json()["data"]["grade_id"] == grade["id"]
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_designation_invalid_grade_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Software Engineer", "grade_id": str(uuid4())},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_GRADE"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_designation_cross_tenant_grade_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        grade_b = await _create_grade(client, headers_b)

        response = await client.post(
            "/v1/designations",
            headers=headers_a,
            json={"title": "Software Engineer", "grade_id": grade_b["id"]},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_GRADE"
    finally:
        await _cleanup_grades_and_designations(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_update_designation_grade_id_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        grade = await _create_grade(client, headers)
        designation = await client.post(
            "/v1/designations", headers=headers, json={"title": "Software Engineer"}
        )
        designation_data = designation.json()["data"]
        assert designation_data["grade_id"] is None

        response = await client.patch(
            f"/v1/designations/{designation_data['id']}",
            headers={**headers, "If-Match": str(designation_data["version"])},
            json={"grade_id": grade["id"]},
        )
        assert response.status_code == 200
        assert response.json()["data"]["grade_id"] == grade["id"]
    finally:
        await _cleanup_grades_and_designations(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
