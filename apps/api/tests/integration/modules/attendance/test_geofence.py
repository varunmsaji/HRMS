"""Geofenced self-service punches end to end: real app, database, RBAC, RLS and audit log.

Workplace geofence = `Branch` (latitude/longitude/geofence_radius_m). The HQ branch sits at the
Kochi test point below; "inside"/"outside" points are offsets due north of it."""

import math
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.geofence import EARTH_RADIUS_M
from hrms.modules.attendance.permissions import (
    ATTENDANCE_POLICY_MANAGE,
    ATTENDANCE_PUNCH,
    ATTENDANCE_PUNCH_ON_BEHALF,
    ATTENDANCE_VIEW,
    ATTENDANCE_VIEW_ALL,
)

pytestmark = pytest.mark.asyncio

KOCHI = (9.9312, 76.2673)
RADIUS = 100
PUNCH = "/v1/attendance/punches/me"


def north(metres: float, base: tuple[float, float] = KOCHI) -> tuple[float, float]:
    return base[0] + math.degrees(metres / EARTH_RADIUS_M), base[1]


def fix(at: tuple[float, float] = KOCHI, *, accuracy: float = 10, age: float = 3) -> dict[str, Any]:
    captured = datetime.now(UTC) - timedelta(seconds=age)
    return {
        "latitude": at[0],
        "longitude": at[1],
        "accuracy_m": accuracy,
        "captured_at": captured.isoformat(),
    }


async def _sql(company_id: UUID, query: str, **params: Any) -> list[Any]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        result = await session.execute(text(query), {"cid": str(company_id), **params})
        rows = list(result) if result.returns_rows else []
        await session.commit()
        return rows


async def _wire(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    mode: str | None,
    branch_geo: dict[str, Any] | None = None,
    accuracy: int = 50,
    max_age: int = 60,
    name: str = "Asha",
) -> dict[str, Any]:
    """Employee assigned to a geofenced branch + a COMPANY attendance policy. `mode=None` leaves
    the policy at its defaults (DISABLED), which is what every existing tenant has."""
    geo = (
        {"latitude": KOCHI[0], "longitude": KOCHI[1], "geofence_radius_m": RADIUS}
        if branch_geo is None
        else branch_geo
    )
    employee = (
        await client.post("/v1/employees", headers=headers, json={"first_name": name})
    ).json()["data"]
    legal_entity = (
        await client.post("/v1/legal-entities", headers=headers, json={"name": f"LE {name}"})
    ).json()["data"]
    branch = (
        await client.post(
            "/v1/branches",
            headers=headers,
            json={"legal_entity_id": legal_entity["id"], "name": "HQ", "timezone": "UTC", **geo},
        )
    ).json()["data"]
    department = (
        await client.post(
            "/v1/departments",
            headers=headers,
            json={"name": "Engineering", "branch_id": branch["id"]},
        )
    ).json()["data"]
    designation = (
        await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Engineer", "department_id": department["id"]},
        )
    ).json()["data"]
    employment = await client.post(
        f"/v1/employees/{employee['id']}/employments",
        headers=headers,
        json={"legal_entity_id": legal_entity["id"], "joining_date": "2026-01-01"},
    )
    assert employment.status_code == 201, employment.text
    assignment = await client.post(
        f"/v1/employees/{employee['id']}/assignments",
        headers=headers,
        json={
            "effective_from": "2026-01-01",
            "change_type": "INITIAL",
            "branch_id": branch["id"],
            "department_id": department["id"],
            "designation_id": designation["id"],
        },
    )
    assert assignment.status_code == 201, assignment.text

    policy = (
        await client.post("/v1/attendance-policies", headers=headers, json={"name": "Geo Policy"})
    ).json()["data"]
    version_body: dict[str, Any] = {
        "effective_from": "2026-01-01",
        "hour_bands": [{"min_minutes": 0, "max_minutes": None, "result_status": "PRESENT"}],
    }
    if mode is not None:
        version_body.update(
            geofence_mode=mode, geofence_max_accuracy_m=accuracy, geofence_max_age_seconds=max_age
        )
    draft = await client.post(
        f"/v1/attendance-policies/{policy['id']}/versions", headers=headers, json=version_body
    )
    assert draft.status_code == 201, draft.text
    published = await client.post(
        f"/v1/attendance-policies/{policy['id']}/versions/{draft.json()['data']['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text
    pa = await client.post(
        "/v1/policy-assignments",
        headers=headers,
        json={
            "policy_kind": "ATTENDANCE_POLICY",
            "policy_id": policy["id"],
            "scope_type": "COMPANY",
            "effective_from": "2026-01-01",
        },
    )
    assert pa.status_code == 201, pa.text
    return {
        "employee_id": employee["id"],
        "branch_id": branch["id"],
        "legal_entity_id": legal_entity["id"],
        "policy_id": policy["id"],
    }


@pytest.fixture
async def tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> AsyncIterator[tuple[dict[str, str], UUID]]:
    headers, company_id, user_id = await _register_tenant(client)
    yield headers, company_id
    await _sql(company_id, "DELETE FROM geofence_attempt WHERE company_id = :cid")
    await _sql(company_id, "DELETE FROM employee_workplace_authorization WHERE company_id = :cid")
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)
    await _cleanup_scoped_users()


async def _self(company_id: UUID, employee_id: str) -> dict[str, str]:
    headers, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_PUNCH, ATTENDANCE_VIEW],
        data_scope="SELF",
        caller_employee_id=UUID(employee_id),
    )
    return headers


async def _punch(
    client: AsyncClient, headers: dict[str, str], direction: str = "IN", **extra: Any
) -> Any:
    return await client.post(PUNCH, headers=headers, json={"direction": direction, **extra})


async def _punch_count(company_id: UUID, employee_id: str) -> int:
    rows = await _sql(
        company_id,
        "SELECT count(*) FROM punch WHERE company_id = :cid AND employee_id = :eid",
        eid=employee_id,
    )
    return int(rows[0][0])


async def _attempts(company_id: UUID, employee_id: str) -> list[Any]:
    return await _sql(
        company_id,
        "SELECT outcome, accepted, punch_id, mode, latitude, longitude, distance_m "
        "FROM geofence_attempt WHERE company_id = :cid AND employee_id = :eid "
        "ORDER BY created_at",
        eid=employee_id,
    )


# --- DISABLED = existing behaviour ----------------------------------------------------------


async def test_default_policy_is_disabled_and_punching_is_unchanged(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode=None)
    me = await _self(company_id, wired["employee_id"])

    plain = await _punch(client, me)
    assert plain.status_code == 201, plain.text
    assert plain.json()["data"]["geofence"] is None

    # A fix far outside the branch is ignored — and never stored — when geofencing is off.
    far = await _punch(client, me, "OUT", location=fix(north(50_000)))
    assert far.status_code == 201, far.text
    assert far.json()["data"]["geofence"] is None
    assert await _attempts(company_id, wired["employee_id"]) == []


async def test_policy_version_defaults_to_disabled(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, _ = tenant
    wired = await _wire(client, admin, mode=None)
    versions = await client.get(
        f"/v1/attendance-policies/{wired['policy_id']}/versions", headers=admin
    )
    row = versions.json()["data"][0]
    assert (
        row["geofence_mode"],
        row["geofence_max_accuracy_m"],
        row["geofence_max_age_seconds"],
    ) == (
        "DISABLED",
        100,
        60,
    )


# --- REQUIRED -------------------------------------------------------------------------------


async def test_required_inside_is_accepted_and_recorded(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    me = await _self(company_id, wired["employee_id"])

    response = await _punch(client, me, location=fix(north(60)))
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["source"] == "WEB"
    assert data["geofence"]["outcome"] == "INSIDE" and data["geofence"]["accepted"] is True
    assert data["geofence"]["workplace_name"] == "HQ"
    assert "latitude" not in str(data["geofence"])

    (attempt,) = await _attempts(company_id, wired["employee_id"])
    outcome, accepted, punch_id, mode, lat, lon, distance = attempt
    assert (outcome, accepted, mode) == ("INSIDE", True, "REQUIRED")
    assert str(punch_id) == data["id"]
    # Retained coordinates are rounded to 4 dp (~11 m), not the raw fix.
    assert abs(float(lat) - round(north(60)[0], 4)) < 1e-9
    assert float(lon) == round(KOCHI[1], 4)
    assert 59 <= float(distance) <= 61


async def test_required_outside_is_rejected_without_creating_a_punch(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    me = await _self(company_id, wired["employee_id"])
    probe = fix(north(900))

    response = await _punch(client, me, location=probe)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "PUNCH_OUTSIDE_GEOFENCE"
    assert error["details"][0]["code"] == "OUTSIDE_GEOFENCE"
    assert error["details"][0]["context"]["radius_m"] == RADIUS
    # No coordinates in the error text, and no punch row.
    assert str(probe["latitude"])[:7] not in response.text
    assert await _punch_count(company_id, wired["employee_id"]) == 0

    (attempt,) = await _attempts(company_id, wired["employee_id"])
    assert attempt[0] == "OUTSIDE_GEOFENCE" and attempt[1] is False and attempt[2] is None
    audited = await _sql(
        company_id,
        "SELECT action, after_json FROM audit_log WHERE company_id = :cid "
        "AND action = 'PUNCH_REJECTED_GEOFENCE'",
    )
    assert len(audited) == 1
    assert "latitude" not in str(audited[0][1]) and "longitude" not in str(audited[0][1])


async def test_required_boundary_inside_and_just_outside(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    me = await _self(company_id, wired["employee_id"])
    assert (await _punch(client, me, location=fix(north(99.0), accuracy=0))).status_code == 201
    just_out = await _punch(client, me, "OUT", location=fix(north(104.0), accuracy=0))
    assert just_out.status_code == 422
    assert just_out.json()["error"]["details"][0]["code"] == "OUTSIDE_GEOFENCE"


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (dict, "LOCATION_REQUIRED"),
        (lambda: {"location_error": "PERMISSION_DENIED"}, "LOCATION_UNAVAILABLE_CLIENT"),
        (lambda: {"location_error": "SERVICES_DISABLED"}, "LOCATION_UNAVAILABLE_CLIENT"),
        (lambda: {"location": fix(accuracy=500)}, "LOCATION_TOO_INACCURATE"),
        (lambda: {"location": fix(age=600)}, "LOCATION_STALE"),
        (lambda: {"location": fix(age=-3600)}, "LOCATION_INVALID"),
        (lambda: {"location": fix(north(112), accuracy=30)}, "OUTSIDE_GEOFENCE_UNCERTAIN"),
    ],
)
async def test_required_failure_modes(
    client: AsyncClient,
    tenant: tuple[dict[str, str], UUID],
    extra: Callable[[], dict[str, Any]],
    expected: str,
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    me = await _self(company_id, wired["employee_id"])
    response = await _punch(client, me, **extra())
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"][0]["code"] == expected
    assert await _punch_count(company_id, wired["employee_id"]) == 0
    assert [a[0] for a in await _attempts(company_id, wired["employee_id"])] == [expected]


async def test_policy_thresholds_are_applied_not_client_values(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED", accuracy=15, max_age=10)
    me = await _self(company_id, wired["employee_id"])
    assert (await _punch(client, me, location=fix(accuracy=20))).status_code == 422
    assert (await _punch(client, me, location=fix(age=30))).status_code == 422
    assert (await _punch(client, me, location=fix(accuracy=10, age=2))).status_code == 201


async def test_no_applicable_workplace_when_branch_has_no_geofence(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED", branch_geo={})
    me = await _self(company_id, wired["employee_id"])
    response = await _punch(client, me, location=fix())
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["code"] == "NO_APPLICABLE_WORKPLACE"
    assert await _punch_count(company_id, wired["employee_id"]) == 0


async def test_inactive_branch_geofence_is_not_used(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    me = await _self(company_id, wired["employee_id"])
    await _sql(company_id, "UPDATE branch SET is_active = false WHERE company_id = :cid")
    response = await _punch(client, me, location=fix())
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["code"] == "NO_APPLICABLE_WORKPLACE"


# --- OPTIONAL -------------------------------------------------------------------------------


async def test_optional_never_blocks_but_records_what_required_would_do(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="OPTIONAL")
    me = await _self(company_id, wired["employee_id"])

    outside = await _punch(client, me, location=fix(north(5000)))
    assert outside.status_code == 201, outside.text
    assert outside.json()["data"]["geofence"]["outcome"] == "OUTSIDE_GEOFENCE"
    assert outside.json()["data"]["geofence"]["accepted"] is True
    none = await _punch(client, me, "OUT")
    assert none.status_code == 201, none.text
    assert none.json()["data"]["geofence"]["outcome"] == "NOT_PROVIDED"

    rows = await _attempts(company_id, wired["employee_id"])
    assert [(r[0], r[1], r[3]) for r in rows] == [
        ("OUTSIDE_GEOFENCE", True, "OPTIONAL"),
        ("NOT_PROVIDED", True, "OPTIONAL"),
    ]


# --- multiple workplaces / authorisation ----------------------------------------------------


async def test_extra_authorised_workplace_applies_and_removal_revokes(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    # Employee's own branch is far from the second office; the second office is HQ2.
    hq2_at = north(20_000)
    wired = await _wire(client, admin, mode="REQUIRED")
    hq2 = (
        await client.post(
            "/v1/branches",
            headers=admin,
            json={
                "legal_entity_id": wired["legal_entity_id"],
                "name": "HQ2",
                "timezone": "UTC",
                "latitude": hq2_at[0],
                "longitude": hq2_at[1],
                "geofence_radius_m": 150,
            },
        )
    ).json()["data"]
    me = await _self(company_id, wired["employee_id"])

    # Not authorised for HQ2 yet: a fix there is outside the only applicable fence.
    assert (await _punch(client, me, location=fix(hq2_at))).status_code == 422

    granted = await client.post(
        "/v1/attendance/workplace-authorizations",
        headers=admin,
        json={"employee_id": wired["employee_id"], "branch_id": hq2["id"]},
    )
    assert granted.status_code == 201, granted.text
    ok = await _punch(client, me, location=fix(hq2_at))
    assert ok.status_code == 201, ok.text
    assert ok.json()["data"]["geofence"]["workplace_name"] == "HQ2"
    # The home branch still works too.
    assert (await _punch(client, me, "OUT", location=fix())).status_code == 201

    duplicate = await client.post(
        "/v1/attendance/workplace-authorizations",
        headers=admin,
        json={"employee_id": wired["employee_id"], "branch_id": hq2["id"]},
    )
    assert duplicate.status_code == 409

    removed = await client.delete(
        f"/v1/attendance/workplace-authorizations/{granted.json()['data']['id']}", headers=admin
    )
    assert removed.status_code == 204
    assert (await _punch(client, me, "IN", location=fix(hq2_at))).status_code == 422
    actions = [
        r[0]
        for r in await _sql(
            company_id,
            "SELECT action FROM audit_log WHERE company_id = :cid AND action LIKE "
            "'WORKPLACE_AUTHORIZATION_%' ORDER BY occurred_at",
        )
    ]
    assert actions == ["WORKPLACE_AUTHORIZATION_ADDED", "WORKPLACE_AUTHORIZATION_REMOVED"]


async def test_authorisation_requires_active_configured_same_company_workplace(
    client: AsyncClient,
    tenant: tuple[dict[str, str], UUID],
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    no_geo = (
        await client.post(
            "/v1/branches",
            headers=admin,
            json={"legal_entity_id": wired["legal_entity_id"], "name": "Bare", "timezone": "UTC"},
        )
    ).json()["data"]
    unconfigured = await client.post(
        "/v1/attendance/workplace-authorizations",
        headers=admin,
        json={"employee_id": wired["employee_id"], "branch_id": no_geo["id"]},
    )
    assert unconfigured.status_code == 422
    forged = await client.post(
        "/v1/attendance/workplace-authorizations",
        headers=admin,
        json={"employee_id": wired["employee_id"], "branch_id": str(uuid4())},
    )
    assert forged.status_code == 404
    ghost = await client.post(
        "/v1/attendance/workplace-authorizations",
        headers=admin,
        json={"employee_id": str(uuid4()), "branch_id": wired["branch_id"]},
    )
    assert ghost.status_code == 404


# --- tampering, authorisation, tenancy -------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"company_id": str(uuid4())},
        {"employee_id": str(uuid4())},
        {"branch_id": str(uuid4())},
        {"geofence_id": str(uuid4())},
        {"max_accuracy_m": 99999},
        {"location": {**fix(), "branch_id": str(uuid4())}},
        {"location": {**fix(), "radius_m": 99999}},
        {"location": {**fix(), "latitude": 120}},
        {"location": {**fix(), "accuracy_m": -1}},
        {"location": {**fix(), "captured_at": "2026-10-28T09:00:00"}},
        {"location": fix(), "location_error": "TIMEOUT"},
        {"location_error": "NOT_A_REAL_ERROR"},
    ],
)
async def test_forged_or_malformed_payloads_are_rejected(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], extra: dict[str, Any]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    me = await _self(company_id, wired["employee_id"])
    response = await _punch(client, me, **extra)
    assert response.status_code == 422, response.text
    assert await _punch_count(company_id, wired["employee_id"]) == 0


async def test_punch_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(PUNCH, json={"direction": "IN", "location": fix()})
    assert response.status_code in (401, 403)


async def test_employee_cannot_use_admin_or_review_routes(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    me = await _self(company_id, wired["employee_id"])
    for method, url in (
        ("GET", "/v1/attendance/geofences"),
        ("GET", "/v1/attendance/workplace-authorizations"),
        ("GET", "/v1/attendance/geofence-attempts"),
    ):
        assert (await client.request(method, url, headers=me)).status_code == 403, url
    post = await client.post(
        "/v1/attendance/workplace-authorizations",
        headers=me,
        json={"employee_id": wired["employee_id"], "branch_id": wired["branch_id"]},
    )
    assert post.status_code == 403
    nobody = await client.get("/v1/attendance/geofences")
    assert nobody.status_code in (401, 403)


async def test_attempt_review_needs_view_all_not_policy_manage(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    me = await _self(company_id, wired["employee_id"])
    await _punch(client, me, location=fix(north(900)))

    config_only, _ = await _create_permission_scoped_user(
        company_id=company_id, permission_codes=[ATTENDANCE_POLICY_MANAGE]
    )
    reviewer, _ = await _create_permission_scoped_user(
        company_id=company_id, permission_codes=[ATTENDANCE_VIEW_ALL]
    )
    assert (
        await client.get("/v1/attendance/geofence-attempts", headers=config_only)
    ).status_code == 403
    assert (await client.get("/v1/attendance/geofences", headers=reviewer)).status_code == 403

    listed = await client.get(
        "/v1/attendance/geofence-attempts",
        headers=reviewer,
        params={"accepted": "false", "employee_id": wired["employee_id"]},
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    assert [r["outcome"] for r in rows] == ["OUTSIDE_GEOFENCE"]
    assert rows[0]["accepted"] is False and rows[0]["punch_id"] is None
    assert listed.json()["pagination"]["total"] == 1


async def test_geofence_listing_reports_usage(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, _ = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    listed = await client.get("/v1/attendance/geofences", headers=admin)
    assert listed.status_code == 200, listed.text
    (hq,) = [g for g in listed.json()["data"] if g["branch_id"] == wired["branch_id"]]
    assert hq["configured"] is True and hq["radius_m"] == RADIUS
    assert hq["assigned_employee_count"] == 1 and hq["authorized_employee_count"] == 0


async def test_hr_on_behalf_punch_is_not_geofenced_and_a_rejection_is_not_converted(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    me = await _self(company_id, wired["employee_id"])
    assert (await _punch(client, me, location=fix(north(900)))).status_code == 422

    on_behalf, _ = await _create_permission_scoped_user(
        company_id=company_id, permission_codes=[ATTENDANCE_PUNCH_ON_BEHALF]
    )
    corrected = await client.post(
        "/v1/attendance/punches",
        headers=on_behalf,
        json={
            "employee_id": wired["employee_id"],
            "punch_time": "2026-08-10T09:00:00Z",
            "direction": "IN",
            "reference": "GPS unavailable; verified in person",
        },
    )
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["data"]["source"] == "ADMIN"
    assert corrected.json()["data"]["geofence"] is None
    # The rejected attempt stays on record, still rejected.
    assert [a[1] for a in await _attempts(company_id, wired["employee_id"])] == [False]


async def test_cross_tenant_isolation(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin_a, company_a = tenant
    wired_a = await _wire(client, admin_a, mode="REQUIRED")
    me_a = await _self(company_a, wired_a["employee_id"])
    await _punch(client, me_a, location=fix(north(900)))
    granted = await client.post(
        "/v1/attendance/workplace-authorizations",
        headers=admin_a,
        json={"employee_id": wired_a["employee_id"], "branch_id": wired_a["branch_id"]},
    )
    assert granted.status_code == 201

    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        wired_b = await _wire(client, headers_b, mode="REQUIRED", name="Bala")
        # B sees none of A's attempts, workplaces or authorisations.
        attempts = await client.get("/v1/attendance/geofence-attempts", headers=headers_b)
        assert attempts.json()["data"] == []
        auths = await client.get("/v1/attendance/workplace-authorizations", headers=headers_b)
        assert auths.json()["data"] == []
        names = [
            g["branch_id"]
            for g in (await client.get("/v1/attendance/geofences", headers=headers_b)).json()[
                "data"
            ]
        ]
        assert wired_a["branch_id"] not in names and wired_b["branch_id"] in names
        # B cannot delete A's authorisation, nor authorise A's employee/branch.
        gone = await client.delete(
            f"/v1/attendance/workplace-authorizations/{granted.json()['data']['id']}",
            headers=headers_b,
        )
        assert gone.status_code == 404
        cross = await client.post(
            "/v1/attendance/workplace-authorizations",
            headers=headers_b,
            json={"employee_id": wired_b["employee_id"], "branch_id": wired_a["branch_id"]},
        )
        assert cross.status_code == 404
        cross2 = await client.post(
            "/v1/attendance/workplace-authorizations",
            headers=headers_b,
            json={"employee_id": wired_a["employee_id"], "branch_id": wired_b["branch_id"]},
        )
        assert cross2.status_code == 404
        # A's authorisation still exists.
        still = await client.get("/v1/attendance/workplace-authorizations", headers=admin_a)
        assert len(still.json()["data"]) == 1
    finally:
        await _sql(company_b, "DELETE FROM geofence_attempt WHERE company_id = :cid")
        await _sql(
            company_b, "DELETE FROM employee_workplace_authorization WHERE company_id = :cid"
        )
        await _cleanup_attendance_day(company_id=company_b)
        await _cleanup(company_id=company_b, user_id=user_b)


async def test_database_rejects_cross_company_authorisation_rows(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    """The composite FKs make a mismatched (company, branch) row impossible even for a writer
    that bypasses the API, and RLS hides/blocks other tenants' rows."""
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    other_company = uuid4()
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        with pytest.raises(Exception):  # noqa: B017 - FK or RLS violation, either is the point
            await session.execute(
                text(
                    "INSERT INTO employee_workplace_authorization "
                    "(id, company_id, employee_id, branch_id) VALUES (:i, :c, :e, :b)"
                ),
                {
                    "i": str(uuid4()),
                    "c": str(other_company),
                    "e": wired["employee_id"],
                    "b": wired["branch_id"],
                },
            )
            await session.commit()


# --- idempotency ------------------------------------------------------------------------------


async def test_replayed_idempotency_key_returns_original_and_does_not_re_evaluate(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    me = await _self(company_id, wired["employee_id"])
    key = "geo-key-0001"
    first = await _punch(client, me, location=fix(), idempotency_key=key)
    assert first.status_code == 201, first.text
    # Lost response -> client retries; even a worse location must not undo or duplicate the punch.
    again = await _punch(client, me, location=fix(north(900)), idempotency_key=key)
    assert again.status_code == 201, again.text
    assert again.json()["data"]["id"] == first.json()["data"]["id"]
    assert await _punch_count(company_id, wired["employee_id"]) == 1
    assert len(await _attempts(company_id, wired["employee_id"])) == 1


async def test_rejected_attempt_does_not_burn_the_idempotency_key(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    me = await _self(company_id, wired["employee_id"])
    key = "geo-key-0002"
    assert (
        await _punch(client, me, location=fix(north(900)), idempotency_key=key)
    ).status_code == 422
    ok = await _punch(client, me, location=fix(), idempotency_key=key)
    assert ok.status_code == 201, ok.text
    assert await _punch_count(company_id, wired["employee_id"]) == 1


# --- policy authoring -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"geofence_mode": "ALWAYS"},
        {"geofence_max_accuracy_m": 4},
        {"geofence_max_accuracy_m": 501},
        {"geofence_max_age_seconds": 4},
        {"geofence_max_age_seconds": 301},
    ],
)
async def test_policy_version_geofence_fields_are_bounded(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], body: dict[str, Any]
) -> None:
    admin, _ = tenant
    policy = (
        await client.post("/v1/attendance-policies", headers=admin, json={"name": "P"})
    ).json()["data"]
    created = await client.post(
        f"/v1/attendance-policies/{policy['id']}/versions",
        headers=admin,
        json={"effective_from": "2026-01-01", **body},
    )
    assert created.status_code == 422, created.text


async def test_draft_geofence_fields_can_be_patched_but_not_nulled(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, _ = tenant
    policy = (
        await client.post("/v1/attendance-policies", headers=admin, json={"name": "P2"})
    ).json()["data"]
    draft = (
        await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=admin,
            json={"effective_from": "2026-01-01"},
        )
    ).json()["data"]
    url = f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}"
    ok = await client.patch(
        url, headers={**admin, "If-Match": "1"}, json={"geofence_mode": "OPTIONAL"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["geofence_mode"] == "OPTIONAL"
    nulled = await client.patch(
        url, headers={**admin, "If-Match": "2"}, json={"geofence_mode": None}
    )
    assert nulled.status_code == 422


# --- retention --------------------------------------------------------------------------------


async def test_purge_removes_only_expired_attempts(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    from hrms.modules.attendance.geofence_service import GeofenceService

    admin, company_id = tenant
    wired = await _wire(client, admin, mode="OPTIONAL")
    me = await _self(company_id, wired["employee_id"])
    for _ in range(2):
        assert (await _punch(client, me, location=fix())).status_code == 201
    await _sql(
        company_id,
        "UPDATE geofence_attempt SET created_at = now() - interval '120 days' "
        "WHERE id = (SELECT id FROM geofence_attempt WHERE company_id = :cid LIMIT 1)",
    )
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        removed = await GeofenceService(session).purge_expired_attempts(company_id, 90)
        await session.commit()
    assert removed == 1
    assert len(await _attempts(company_id, wired["employee_id"])) == 1
    assert await _punch_count(company_id, wired["employee_id"]) == 2


async def test_attempt_review_respects_the_reviewers_data_scope(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    me = await _self(company_id, wired["employee_id"])
    await _punch(client, me, location=fix(north(900)))

    other = (
        await client.post("/v1/employees", headers=admin, json={"first_name": "Other"})
    ).json()["data"]
    # A reviewer whose grant is SELF-scoped to someone else must not see this employee's attempts.
    narrow, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_VIEW_ALL],
        data_scope="SELF",
        caller_employee_id=UUID(other["id"]),
    )
    listed = await client.get("/v1/attendance/geofence-attempts", headers=narrow)
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"] == []
    # The same grant at COMPANY scope does see it.
    wide, _ = await _create_permission_scoped_user(
        company_id=company_id, permission_codes=[ATTENDANCE_VIEW_ALL]
    )
    assert (
        len((await client.get("/v1/attendance/geofence-attempts", headers=wide)).json()["data"])
        == 1
    )


@pytest.mark.parametrize("mode", [None, "OPTIONAL", "REQUIRED"])
async def test_my_geofence_policy_endpoint(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], mode: str | None
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode=mode, accuracy=40, max_age=30)
    me = await _self(company_id, wired["employee_id"])
    response = await client.get("/v1/attendance/geofence-policy/me", headers=me)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    if mode is None:
        assert data == {"mode": "DISABLED", "max_accuracy_m": 100, "max_age_seconds": 60}
    else:
        assert data == {"mode": mode, "max_accuracy_m": 40, "max_age_seconds": 30}


async def test_my_geofence_policy_needs_the_punch_permission(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    await _wire(client, admin, mode="REQUIRED")
    viewer, _ = await _create_permission_scoped_user(
        company_id=company_id, permission_codes=[ATTENDANCE_VIEW]
    )
    assert (
        await client.get("/v1/attendance/geofence-policy/me", headers=viewer)
    ).status_code == 403
    assert (await client.get("/v1/attendance/geofence-policy/me")).status_code in (401, 403)


async def test_branch_used_as_an_authorised_workplace_cannot_be_deactivated(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, mode="REQUIRED")
    second = (
        await client.post(
            "/v1/branches",
            headers=admin,
            json={
                "legal_entity_id": wired["legal_entity_id"],
                "name": "Satellite",
                "timezone": "UTC",
                "latitude": KOCHI[0] + 0.5,
                "longitude": KOCHI[1],
                "geofence_radius_m": 80,
            },
        )
    ).json()["data"]
    granted = await client.post(
        "/v1/attendance/workplace-authorizations",
        headers=admin,
        json={"employee_id": wired["employee_id"], "branch_id": second["id"]},
    )
    assert granted.status_code == 201, granted.text

    blocked = await client.patch(
        f"/v1/branches/{second['id']}",
        headers={**admin, "If-Match": str(second["version"])},
        json={"is_active": False},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "BRANCH_HAS_WORKPLACE_AUTHORIZATIONS"
    assert blocked.json()["error"]["details"][0]["context"]["authorization_count"] == 1

    # Removing the authorisation (audited) is the deliberate step that unblocks it.
    removed = await client.delete(
        f"/v1/attendance/workplace-authorizations/{granted.json()['data']['id']}", headers=admin
    )
    assert removed.status_code == 204
    allowed = await client.patch(
        f"/v1/branches/{second['id']}",
        headers={**admin, "If-Match": str(second["version"])},
        json={"is_active": False},
    )
    assert allowed.status_code == 200, allowed.text
