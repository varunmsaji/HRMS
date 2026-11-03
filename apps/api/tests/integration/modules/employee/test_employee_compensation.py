"""Integration tests for the Employee Compensation API (E-06) —
`/v1/employees/{employee_id}/compensation*`.

Follows the same checklist as `test_employee_assignment.py` (E-04): create, list, get,
mass-assignment rejection, stale-version conflict, cross-tenant isolation, permission matrix —
plus the scenarios specific to this slice: the `employee_compensation_no_overlap` GiST
exclusion constraint's friendly-error surface (both via the service's own close-then-insert
path and via a raw insert that bypasses it entirely), the as-of-date read pattern, the "no
carry-forward" semantics (every write states the full new CTC explicitly), the "no covering
employment" rule, rehire compatibility, and PD-1 (Grade `min_ctc`/`max_ctc` does NOT constrain
compensation, plan §16).
"""

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from hrms.core.audit.models import AuditLog
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


async def _create_employee(
    client: AsyncClient, headers: dict[str, str], first_name: str = "Asha", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/employees", headers=headers, json={"first_name": first_name, **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_legal_entity(
    client: AsyncClient, headers: dict[str, str], name: str = "Acme Legal Entity"
) -> dict[str, Any]:
    response = await client.post("/v1/legal-entities", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_employment(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    legal_entity_id: str,
    joining_date: str = "2027-06-01",
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/employees/{employee_id}/employments",
        headers=headers,
        json={"legal_entity_id": legal_entity_id, "joining_date": joining_date},
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_grade(
    client: AsyncClient, headers: dict[str, str], **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/grades", headers=headers, json={"name": "Senior Engineer", **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _setup_employee_with_employment(
    client: AsyncClient, headers: dict[str, str], *, joining_date: str = "2027-06-01"
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    employee = await _create_employee(client, headers)
    legal_entity = await _create_legal_entity(client, headers)
    employment = await _create_employment(
        client,
        headers,
        employee_id=employee["id"],
        legal_entity_id=legal_entity["id"],
        joining_date=joining_date,
    )
    return employee, legal_entity, employment


async def _create_compensation(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    if_match: str | None = None,
    expected_status: int = 201,
    **body: Any,
) -> dict[str, Any]:
    request_headers = dict(headers)
    if if_match is not None:
        request_headers["If-Match"] = if_match
    response = await client.post(
        f"/v1/employees/{employee_id}/compensation", headers=request_headers, json=body
    )
    assert response.status_code == expected_status, response.text
    return dict(response.json()["data"]) if expected_status < 400 else dict(response.json())


def _joining_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "effective_from": "2027-06-01",
        "annual_ctc_minor": 12_00_000_00,
        "currency": "INR",
        "revision_type": "JOINING",
        "revision_reason": "Initial hire",
    }
    payload.update(overrides)
    return payload


async def _cleanup_compensations(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employee_compensation WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.commit()


async def _cleanup_employments(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employment WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _cleanup_employees(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM number_series WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _cleanup_grades(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM grade WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _teardown(*, company_id: UUID, user_id: UUID | None) -> None:
    """Full teardown in FK-safe order: compensation (-> employee) -> employment
    (-> employee, legal_entity) -> employee (-> number_series) -> grade -> the rest
    (legal_entity/company/roles/user)."""
    await _cleanup_compensations(company_id=company_id)
    await _cleanup_employments(company_id=company_id)
    await _cleanup_employees(company_id=company_id)
    await _cleanup_grades(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


# --- Create: first compensation row (no current row) ----------------------------------------


async def test_create_first_compensation_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        compensation = await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        assert compensation["employee_id"] == employee["id"]
        assert compensation["annual_ctc_minor"] == 12_00_000_00
        assert compensation["currency"] == "INR"
        assert compensation["revision_type"] == "JOINING"
        assert compensation["revision_reason"] == "Initial hire"
        assert compensation["effective_to"] is None
        assert compensation["version"] == 1

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "employee_compensation",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "COMPENSATION_REVISED"
            assert audit_rows[0].before_json is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_compensation_without_covering_employment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        # No employment created for this employee at all.

        response = await client.post(
            f"/v1/employees/{employee['id']}/compensation",
            headers=headers,
            json=_joining_payload(),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "NO_ACTIVE_EMPLOYMENT"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_compensation_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/compensation",
            headers=headers,
            json=_joining_payload(version=99, company_id=str(uuid4())),
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_compensation_unknown_employee_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            f"/v1/employees/{uuid4()}/compensation",
            headers=headers,
            json=_joining_payload(),
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_compensation_negative_ctc_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/compensation",
            headers=headers,
            json=_joining_payload(annual_ctc_minor=-1),
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_compensation_invalid_revision_type_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/compensation",
            headers=headers,
            json=_joining_payload(revision_type="NOT_A_REAL_TYPE"),
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_compensation_missing_revision_reason_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        payload = _joining_payload()
        del payload["revision_reason"]

        response = await client.post(
            f"/v1/employees/{employee['id']}/compensation", headers=headers, json=payload
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Read / list (incl. as-of) --------------------------------------------------------------


async def test_list_compensations_empty_state(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.get(f"/v1/employees/{employee['id']}/compensation", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_get_compensation_not_found(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.get(
            f"/v1/employees/{employee['id']}/compensation/{uuid4()}", headers=headers
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_list_compensations_as_of_date_boundaries(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The as-of-date read pattern: 2027 joining CTC, 2029 annual revision — checked at the
    exact `effective_from`/`effective_to` boundaries and just outside them."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )
        await _create_compensation(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            effective_from="2029-01-01",
            annual_ctc_minor=15_00_000_00,
            currency="INR",
            revision_type="ANNUAL",
            revision_reason="Annual increment",
        )

        async def _as_of(day: str) -> list[dict[str, Any]]:
            resp = await client.get(
                f"/v1/employees/{employee['id']}/compensation",
                headers=headers,
                params={"as_of": day},
            )
            assert resp.status_code == 200
            return list(resp.json()["data"])

        assert len(await _as_of("2027-06-01")) == 1  # first row's start, inclusive
        assert (await _as_of("2028-12-31"))[0]["annual_ctc_minor"] == 12_00_000_00
        assert (await _as_of("2029-01-01"))[0]["annual_ctc_minor"] == 15_00_000_00
        assert await _as_of("2027-05-31") == []  # one day before the first row starts

        history = await client.get(f"/v1/employees/{employee['id']}/compensation", headers=headers)
        assert len(history.json()["data"]) == 2
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Revision (no carry-forward) --------------------------------------------------------------


async def test_revision_closes_current_and_requires_full_new_values(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        second = await _create_compensation(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            effective_from="2029-01-01",
            annual_ctc_minor=18_50_000_00,
            currency="INR",
            revision_type="PROMOTION",
            revision_reason="Promotion to Staff Engineer",
        )

        assert second["annual_ctc_minor"] == 18_50_000_00
        assert second["revision_type"] == "PROMOTION"

        first_after = await client.get(
            f"/v1/employees/{employee['id']}/compensation/{first['id']}", headers=headers
        )
        assert first_after.json()["data"]["effective_to"] == "2028-12-31"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_compensation_missing_if_match_when_current_exists_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/compensation",
            headers=headers,
            json={
                "effective_from": "2029-01-01",
                "annual_ctc_minor": 15_00_000_00,
                "currency": "INR",
                "revision_type": "ANNUAL",
                "revision_reason": "Annual increment",
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "COMPENSATION_VERSION_REQUIRED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_compensation_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/compensation",
            headers={**headers, "If-Match": "999"},
            json={
                "effective_from": "2029-01-01",
                "annual_ctc_minor": 15_00_000_00,
                "currency": "INR",
                "revision_type": "ANNUAL",
                "revision_reason": "Annual increment",
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_compensation_effective_from_not_after_current_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/compensation",
            headers={**headers, "If-Match": str(first["version"])},
            json={
                "effective_from": "2027-06-01",
                "annual_ctc_minor": 15_00_000_00,
                "currency": "INR",
                "revision_type": "ANNUAL",
                "revision_reason": "Annual increment",
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_EFFECTIVE_FROM"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- GiST exclusion constraint --------------------------------------------------------------


async def test_raw_overlapping_insert_rejected_at_database_level(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Bypasses the service's own close-then-insert logic entirely — a raw `INSERT` with dates
    overlapping the existing row must be rejected by `employee_compensation_no_overlap` itself,
    proving the DB constraint is the actual backstop, not just an application-level check."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SET LOCAL row_security = off"))
            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        """
                        INSERT INTO employee_compensation
                            (id, company_id, employee_id, annual_ctc_minor, currency,
                             revision_type, effective_from, effective_to,
                             created_at, updated_at, version)
                        VALUES
                            (gen_random_uuid(), :company_id, :employee_id, :annual_ctc_minor,
                             'INR', 'CORRECTION', :effective_from, NULL, now(), now(), 1)
                        """
                    ),
                    {
                        "company_id": str(company_id),
                        "employee_id": employee["id"],
                        "annual_ctc_minor": 20_00_000_00,
                        "effective_from": date(2027, 12, 1),
                    },
                )
            await session.rollback()
        assert first["effective_to"] is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Rehire compatibility --------------------------------------------------------------------


async def test_rehire_first_compensation_after_gap(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The rejoin scenario: an employee's first spell ends, a gap follows, then a new
    employment episode starts. The rejoin's first compensation behaves exactly like any other
    "no current row" write — no rehire-specific code path exists. Compensation history remains
    attached to the employee's own identity throughout (not reset by the rehire).

    `EmploymentService.terminate_employment` closes the still-open `employee_compensation` row
    from the pre-exit spell at `effective_to = last_working_day` (the actual termination date),
    not at the rehire's `effective_from - 1 day`
    (`docs/modules/employee/22_TERMINATION_ASSIGNMENT_COMPENSATION_PLAN.md` §7/§9, mirroring
    `test_employee_assignment.py::test_rehire_first_assignment_after_gap`). As a consequence,
    `get_current_compensation`/`?as_of=` resolve to nothing during the gap, and the rehire's
    first `create_compensation` call takes the "no current row" branch — no `If-Match` is
    supplied or required."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity, employment = await _setup_employee_with_employment(
            client, headers, joining_date="2027-06-01"
        )
        pre_exit = await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        terminate = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert terminate.status_code == 200

        pre_exit_after_terminate = await client.get(
            f"/v1/employees/{employee['id']}/compensation/{pre_exit['id']}", headers=headers
        )
        assert pre_exit_after_terminate.json()["data"]["effective_to"] == "2030-09-30"

        gap_as_of = await client.get(
            f"/v1/employees/{employee['id']}/compensation",
            headers=headers,
            params={"as_of": "2032-01-01"},
        )
        assert gap_as_of.json()["data"] == []

        rehire_employment = await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2034-02-01",
        )
        assert rehire_employment["previous_employment_id"] == employment["id"]

        rehire_compensation = await _create_compensation(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2034-02-01",
            annual_ctc_minor=16_00_000_00,
            currency="INR",
            revision_type="JOINING",
            revision_reason="Rejoining CTC",
        )

        assert rehire_compensation["employee_id"] == employee["id"]
        assert rehire_compensation["effective_to"] is None

        pre_exit_after = await client.get(
            f"/v1/employees/{employee['id']}/compensation/{pre_exit['id']}", headers=headers
        )
        assert pre_exit_after.json()["data"]["effective_to"] == "2030-09-30"

        # Full history remains attached to the same employee identity, both pre-exit and
        # post-rehire rows visible with a gap in between.
        history = await client.get(f"/v1/employees/{employee['id']}/compensation", headers=headers)
        history_ids = [row["id"] for row in history.json()["data"]]
        assert history_ids == [pre_exit["id"], rehire_compensation["id"]]

        # Employee identity is unaffected — same id/employee_code throughout.
        employee_after = await client.get(f"/v1/employees/{employee['id']}", headers=headers)
        assert employee_after.json()["data"]["employee_code"] == employee["employee_code"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- PD-1: Grade min_ctc/max_ctc does NOT constrain compensation ---------------------------


async def test_grade_ctc_band_does_not_block_compensation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Plan §16 PD-1 / §8: no document enforces `annual_ctc_minor` against the employee's
    grade's `min_ctc`/`max_ctc` band, and this slice deliberately does not invent that
    enforcement. A CTC far outside a defined grade band must still succeed."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        grade = await _create_grade(client, headers, min_ctc=10_00_000_00, max_ctc=15_00_000_00)
        assert grade["min_ctc"] == 10_00_000_00
        assert grade["max_ctc"] == 15_00_000_00

        # Far below the grade's min_ctc and far above its max_ctc — both must succeed, since
        # this slice reads no relationship between Compensation and Grade at all (the employee's
        # assignment doesn't even reference this grade in this test).
        below_band = await _create_compensation(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            annual_ctc_minor=1_00_000_00,
            currency="INR",
            revision_type="JOINING",
            revision_reason="Below grade band",
        )
        assert below_band["annual_ctc_minor"] == 1_00_000_00

        above_band = await _create_compensation(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(below_band["version"]),
            effective_from="2029-01-01",
            annual_ctc_minor=50_00_000_00,
            currency="INR",
            revision_type="MARKET",
            revision_reason="Above grade band",
        )
        assert above_band["annual_ctc_minor"] == 50_00_000_00
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Tenant isolation ------------------------------------------------------------------------


async def test_cannot_get_compensation_from_other_tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, _legal_entity_a, _employment_a = await _setup_employee_with_employment(
            client, headers_a
        )
        compensation_a = await _create_compensation(
            client, headers_a, employee_id=employee_a["id"], **_joining_payload()
        )

        response = await client.get(
            f"/v1/employees/{employee_a['id']}/compensation/{compensation_a['id']}",
            headers=headers_b,
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


async def test_cannot_create_compensation_for_other_tenant_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, _legal_entity_a, _employment_a = await _setup_employee_with_employment(
            client, headers_a
        )

        response = await client.post(
            f"/v1/employees/{employee_a['id']}/compensation",
            headers=headers_b,
            json=_joining_payload(),
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


# --- Permission matrix -----------------------------------------------------------------------


async def _create_permission_scoped_user(
    *,
    company_id: UUID,
    permission_codes: list[str],
    data_scope: str = "COMPANY",
    caller_employee_id: UUID | None = None,
) -> tuple[dict[str, str], UUID]:
    """Registers a second user in the same tenant, granted only the given permission codes at
    the given `data_scope` — mirrors `test_employee_assignment.py`'s own inline setup, extended
    with a `data_scope`/`caller_employee_id` parameter matching `test_employee_statutory.py`'s
    and `test_employee_banking.py`'s own equivalent helper."""
    from datetime import UTC, datetime, timedelta
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
                code=f"COMPENSATION_TEST_ROLE_{role_id.hex[:8]}",
                name="Compensation test role",
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
                email=f"scoped-comp-{scoped_user_id.hex[:8]}@example.com",
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
        employee_id=caller_employee_id,
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
                "(SELECT id FROM \"user\" WHERE email LIKE 'scoped-comp-%')"
            )
        )
        await session.execute(text("DELETE FROM \"user\" WHERE email LIKE 'scoped-comp-%'"))
        await session.commit()


async def test_list_compensation_without_view_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[]
        )

        response = await client.get(
            f"/v1/employees/{employee['id']}/compensation", headers=scoped_headers
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_create_compensation_without_update_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_COMPENSATION

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[EMPLOYEE_VIEW_COMPENSATION]
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/compensation",
            headers=scoped_headers,
            json=_joining_payload(),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_create_compensation_with_update_permission_succeeds(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.employee.permissions import EMPLOYEE_UPDATE_COMPENSATION

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[EMPLOYEE_UPDATE_COMPENSATION]
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/compensation",
            headers=scoped_headers,
            json=_joining_payload(),
        )
        assert response.status_code == 201, response.text
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# --- Data-scope enforcement -------------------------------------------------------------------
#
# `docs/architecture/EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md` Finding F3: `.
# VIEW_COMPENSATION`'s two `GET` routes used to resolve a caller's `DataScope` and discard it
# (bind to `_scope: Annotated[object, ...]`), making every grant company-wide regardless of its
# stored `data_scope`. Fixed per `docs/modules/employee/
# 37_EMPLOYEE_COMPENSATION_STATUTORY_DATA_SCOPE_IMPLEMENTATION_REPORT.md` — these tests prove the
# resolved scope is now actually enforced, mirroring `test_employee_banking.py`'s equivalent
# `SELF`/`COMPANY` tests and `test_employee_statutory.py`'s `SELF`/`REPORTEES`/`COMPANY` tests.


async def test_view_compensation_self_scope_sees_own_record_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller holding `EMPLOYEE.VIEW_COMPENSATION` at `SELF` scope, whose JWT `employee_id`
    claim matches the path `employee_id`, sees their own compensation record; another employee's
    record is invisible (`404`, not `403`, matching every other out-of-scope convention in this
    module). Direct single-record ID lookup cannot bypass this either."""
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_COMPENSATION

    headers, company_id, user_id = await _register_tenant(client)
    try:
        self_employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        other_employee, _legal_entity_2, _employment_2 = await _setup_employee_with_employment(
            client, headers
        )
        self_compensation = await _create_compensation(
            client, headers, employee_id=self_employee["id"], **_joining_payload()
        )
        await _create_compensation(
            client,
            headers,
            employee_id=other_employee["id"],
            **_joining_payload(annual_ctc_minor=15_00_000_00),
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW_COMPENSATION],
            data_scope="SELF",
            caller_employee_id=UUID(self_employee["id"]),
        )

        own = await client.get(
            f"/v1/employees/{self_employee['id']}/compensation", headers=scoped_headers
        )
        assert own.status_code == 200
        assert len(own.json()["data"]) == 1
        assert own.json()["data"][0]["annual_ctc_minor"] == 12_00_000_00

        own_detail = await client.get(
            f"/v1/employees/{self_employee['id']}/compensation/{self_compensation['id']}",
            headers=scoped_headers,
        )
        assert own_detail.status_code == 200

        other = await client.get(
            f"/v1/employees/{other_employee['id']}/compensation", headers=scoped_headers
        )
        assert other.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_view_compensation_self_scope_no_employee_id_sees_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller with a `SELF`-scoped `EMPLOYEE.VIEW_COMPENSATION` grant but no linked
    `employee_id` (JWT claim is `None`) must fail closed — the visible set is empty, never falls
    back to `COMPANY`."""
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_COMPENSATION

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW_COMPENSATION],
            data_scope="SELF",
            caller_employee_id=None,
        )

        response = await client.get(
            f"/v1/employees/{employee['id']}/compensation", headers=scoped_headers
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_view_compensation_reportees_scope_sees_direct_reports_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`RBAC_DATA_SCOPE_DECISIONS.md` Decision F: a manager granted `EMPLOYEE.VIEW_COMPENSATION`
    at `REPORTEES` scope (not `COMPANY`) sees a direct report's compensation but not an unrelated
    employee's, and not their own (`REPORTEES` does not imply `SELF`, matching
    `EmployeeService.resolve_visible_employee_ids`'s existing semantics) — proves the fix applies
    to every scope level, not just `SELF`."""
    from datetime import UTC, datetime

    from hrms.modules.employee.models import EmployeeAssignment
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_COMPENSATION

    headers, company_id, user_id = await _register_tenant(client)
    try:
        manager, _legal_entity, _employment = await _setup_employee_with_employment(client, headers)
        report, _legal_entity_2, _employment_2 = await _setup_employee_with_employment(
            client, headers
        )
        unrelated, _legal_entity_3, _employment_3 = await _setup_employee_with_employment(
            client, headers
        )
        await _create_compensation(client, headers, employee_id=report["id"], **_joining_payload())
        await _create_compensation(
            client,
            headers,
            employee_id=unrelated["id"],
            **_joining_payload(annual_ctc_minor=20_00_000_00),
        )

        factory = get_session_factory()
        async with factory() as session:
            now = datetime.now(UTC)
            session.add(
                EmployeeAssignment(
                    id=uuid4(),
                    company_id=company_id,
                    employee_id=UUID(report["id"]),
                    reporting_manager_id=UUID(manager["id"]),
                    effective_from=date(2027, 6, 1),
                    effective_to=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW_COMPENSATION],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager["id"]),
        )

        report_resp = await client.get(
            f"/v1/employees/{report['id']}/compensation", headers=scoped_headers
        )
        assert report_resp.status_code == 200

        unrelated_resp = await client.get(
            f"/v1/employees/{unrelated['id']}/compensation", headers=scoped_headers
        )
        assert unrelated_resp.status_code == 404

        own_resp = await client.get(
            f"/v1/employees/{manager['id']}/compensation", headers=scoped_headers
        )
        assert own_resp.status_code == 404
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM employee_assignment WHERE company_id = :cid"),
                {"cid": str(company_id)},
            )
            await session.commit()
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_view_compensation_company_scope_sees_any_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`COMPANY` scope (the default for every existing seeded role, including `COMPANY_ADMIN`)
    still sees every employee's compensation record — the fix does not narrow `COMPANY`-scoped
    access at all, matching every real tenant's current, unchanged behavior."""
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_COMPENSATION

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW_COMPENSATION],
            data_scope="COMPANY",
            caller_employee_id=None,
        )

        response = await client.get(
            f"/v1/employees/{employee['id']}/compensation", headers=scoped_headers
        )
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]["annual_ctc_minor"] == 12_00_000_00
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_view_compensation_as_of_cannot_bypass_scope(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`?as_of=` is a *which historical row*, not a *whose employee* concern (task's own
    separation of concerns) — an out-of-scope caller cannot use `as_of` to bypass the scope
    check; the effective-dating short-circuit happens only after `_assert_employee_visible`
    already raised `404`."""
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_COMPENSATION

    headers, company_id, user_id = await _register_tenant(client)
    try:
        self_employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        other_employee, _legal_entity_2, _employment_2 = await _setup_employee_with_employment(
            client, headers
        )
        await _create_compensation(
            client, headers, employee_id=other_employee["id"], **_joining_payload()
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW_COMPENSATION],
            data_scope="SELF",
            caller_employee_id=UUID(self_employee["id"]),
        )

        response = await client.get(
            f"/v1/employees/{other_employee['id']}/compensation?as_of=2027-06-01",
            headers=scoped_headers,
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# --- Data-scope enforcement (write path, Finding C / F9) ---------------------------------------
#
# `docs/modules/employee/39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Phase 2:
# `create_compensation` now also resolves and enforces the caller's `DataScope` against the
# target employee, in addition to the bare `EMPLOYEE.UPDATE_COMPENSATION` permission check that
# already existed. An out-of-scope target behaves exactly like a nonexistent one (`404`, not
# `403`).


async def test_create_compensation_reportees_scope_target_visibility(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller holding `EMPLOYEE.UPDATE_COMPENSATION` at `REPORTEES` scope can write a direct
    report's compensation, but an unrelated employee's is invisible (`404`), never `403`."""
    from datetime import UTC, datetime

    from hrms.modules.employee.models import EmployeeAssignment
    from hrms.modules.employee.permissions import EMPLOYEE_UPDATE_COMPENSATION

    headers, company_id, user_id = await _register_tenant(client)
    try:
        manager, _manager_entity, _manager_employment = await _setup_employee_with_employment(
            client, headers
        )
        report, _report_entity, _report_employment = await _setup_employee_with_employment(
            client, headers
        )
        unrelated, _unrelated_entity, _unrelated_employment = await _setup_employee_with_employment(
            client, headers
        )

        factory = get_session_factory()
        async with factory() as session:
            now = datetime.now(UTC)
            session.add(
                EmployeeAssignment(
                    id=uuid4(),
                    company_id=company_id,
                    employee_id=UUID(report["id"]),
                    reporting_manager_id=UUID(manager["id"]),
                    effective_from=date(2027, 6, 1),
                    effective_to=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_UPDATE_COMPENSATION],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager["id"]),
        )

        in_scope = await client.post(
            f"/v1/employees/{report['id']}/compensation",
            headers=scoped_headers,
            json=_joining_payload(),
        )
        assert in_scope.status_code == 201, in_scope.text

        out_of_scope = await client.post(
            f"/v1/employees/{unrelated['id']}/compensation",
            headers=scoped_headers,
            json=_joining_payload(),
        )
        assert out_of_scope.status_code == 404
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM employee_assignment WHERE company_id = :cid"),
                {"cid": str(company_id)},
            )
            await session.commit()
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_create_compensation_cross_tenant_scoped_actor_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Cross-tenant + data-scope composed on `create_compensation`: a `COMPANY`-scoped actor in
    tenant A cannot write compensation for tenant B's employee, tenant isolation wins first."""
    from hrms.modules.employee.permissions import EMPLOYEE_UPDATE_COMPENSATION

    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        _employee_a, _entity_a, _employment_a = await _setup_employee_with_employment(
            client, headers_a
        )
        employee_b, _entity_b, _employment_b = await _setup_employee_with_employment(
            client, headers_b
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_a,
            permission_codes=[EMPLOYEE_UPDATE_COMPENSATION],
            data_scope="COMPANY",
        )

        response = await client.post(
            f"/v1/employees/{employee_b['id']}/compensation",
            headers={**scoped_headers, "X-Company-Id": str(company_a)},
            json=_joining_payload(),
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)
        await _cleanup_scoped_users()
