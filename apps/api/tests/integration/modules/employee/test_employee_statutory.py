"""Integration tests for the Employee Statutory API (E-07) —
`/v1/employees/{employee_id}/statutory*`.

Follows the same checklist as `test_employee_compensation.py` (E-06): create, list, get,
mass-assignment rejection, stale-version conflict, cross-tenant isolation, permission matrix —
plus the scenarios specific to this slice: the `employee_statutory_no_overlap` GiST exclusion
constraint's friendly-error surface, the as-of-date read pattern, the "no carry-forward"
semantics, the "no covering employment" rule, rehire compatibility, the once-per-FY tax-regime
switch rule (FR-PAY-006), the deliberately-NOT-enforced PF/ESI applicability/identifier
correlation (plan §17/§26 items 6-7), and — since `docs/modules/employee/
37_EMPLOYEE_COMPENSATION_STATUTORY_DATA_SCOPE_IMPLEMENTATION_REPORT.md` — real `SELF`/
`REPORTEES`/`REPORTEE_TREE`/`COMPANY` data-scope enforcement on `EMPLOYEE.VIEW_STATUTORY`'s two
`GET` routes, closing `EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md` Finding F2 (the plan
§11.3 `COMPANY`-only posture this module originally shipped with contradicted the LOCKED
`RBAC_DATA_SCOPE_DECISIONS.md` Decision E and has been corrected, not preserved).
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
    client: AsyncClient, headers: dict[str, str], first_name: str = "Meera", **extra: Any
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


async def _create_statutory(
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
        f"/v1/employees/{employee_id}/statutory", headers=request_headers, json=body
    )
    assert response.status_code == expected_status, response.text
    return dict(response.json()["data"]) if expected_status < 400 else dict(response.json())


def _joining_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "effective_from": "2027-06-01",
        "is_pf_applicable": True,
        "pf_number": "PF1234567890",
        "is_esi_applicable": False,
        "is_lwf_applicable": True,
        "tax_regime": "NEW",
        "revision_reason": "Initial statutory profile",
    }
    payload.update(overrides)
    return payload


async def _cleanup_statutories(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employee_statutory WHERE company_id = :cid"),
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


async def _teardown(*, company_id: UUID, user_id: UUID | None) -> None:
    """Full teardown in FK-safe order: statutory (-> employee) -> employment (-> employee,
    legal_entity) -> employee (-> number_series) -> the rest (legal_entity/company/roles/user)."""
    await _cleanup_statutories(company_id=company_id)
    await _cleanup_employments(company_id=company_id)
    await _cleanup_employees(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


# --- Create: first statutory row (no current row) --------------------------------------------


async def test_create_first_statutory_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        statutory = await _create_statutory(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        assert statutory["employee_id"] == employee["id"]
        assert statutory["is_pf_applicable"] is True
        assert statutory["pf_number"] == "PF1234567890"
        assert statutory["is_esi_applicable"] is False
        assert statutory["tax_regime"] == "NEW"
        assert statutory["effective_to"] is None
        assert statutory["version"] == 1

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "employee_statutory",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "STATUTORY_REVISED"
            assert audit_rows[0].before_json is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_statutory_without_covering_employment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        # No employment created for this employee at all.

        response = await client.post(
            f"/v1/employees/{employee['id']}/statutory",
            headers=headers,
            json=_joining_payload(),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "NO_ACTIVE_EMPLOYMENT"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_statutory_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/statutory",
            headers=headers,
            json=_joining_payload(version=99, company_id=str(uuid4())),
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_statutory_unknown_employee_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            f"/v1/employees/{uuid4()}/statutory",
            headers=headers,
            json=_joining_payload(),
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_statutory_invalid_tax_regime_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/statutory",
            headers=headers,
            json=_joining_payload(tax_regime="FLAT"),
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_statutory_missing_revision_reason_rejected(
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
            f"/v1/employees/{employee['id']}/statutory", headers=headers, json=payload
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_statutory_negative_vpf_amount_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/statutory",
            headers=headers,
            json=_joining_payload(vpf_amount=-100),
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_statutory_pf_applicable_without_pf_number_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Plan §17/§26 items 6-7: applicability/identifier correlation (`is_pf_applicable=true`
    implying `pf_number IS NOT NULL`) is an explicitly open, undocumented question this slice
    does not invent enforcement for. A PF-applicable row with no `pf_number` must still
    succeed."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        statutory = await _create_statutory(
            client,
            headers,
            employee_id=employee["id"],
            **_joining_payload(is_pf_applicable=True, pf_number=None, is_esi_applicable=True),
        )
        assert statutory["is_pf_applicable"] is True
        assert statutory["pf_number"] is None
        assert statutory["is_esi_applicable"] is True
        assert statutory["esi_ip_number"] is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Read / list (incl. as-of) ----------------------------------------------------------------


async def test_list_statutories_empty_state(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.get(f"/v1/employees/{employee['id']}/statutory", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_get_statutory_not_found(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.get(
            f"/v1/employees/{employee['id']}/statutory/{uuid4()}", headers=headers
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_list_statutories_as_of_date_boundaries(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_statutory(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )
        await _create_statutory(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            effective_from="2029-06-01",
            is_pf_applicable=True,
            pf_number="PF1234567890",
            is_esi_applicable=True,
            esi_ip_number="ESI9876543210",
            is_lwf_applicable=True,
            tax_regime="NEW",
            revision_reason="ESI became applicable",
        )

        async def _as_of(day: str) -> list[dict[str, Any]]:
            resp = await client.get(
                f"/v1/employees/{employee['id']}/statutory",
                headers=headers,
                params={"as_of": day},
            )
            assert resp.status_code == 200
            return list(resp.json()["data"])

        assert len(await _as_of("2027-06-01")) == 1  # first row's start, inclusive
        assert (await _as_of("2029-05-31"))[0]["is_esi_applicable"] is False
        assert (await _as_of("2029-06-01"))[0]["is_esi_applicable"] is True
        assert await _as_of("2027-05-31") == []  # one day before the first row starts

        history = await client.get(f"/v1/employees/{employee['id']}/statutory", headers=headers)
        assert len(history.json()["data"]) == 2
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Revision (no carry-forward) ---------------------------------------------------------------


async def test_revision_closes_current_and_requires_full_new_values(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_statutory(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        second = await _create_statutory(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            effective_from="2029-06-01",
            is_pf_applicable=True,
            pf_number="PF1234567890",
            is_esi_applicable=True,
            esi_ip_number="ESI9876543210",
            is_lwf_applicable=True,
            tax_regime="NEW",
            revision_reason="ESI became applicable",
        )

        assert second["is_esi_applicable"] is True

        first_after = await client.get(
            f"/v1/employees/{employee['id']}/statutory/{first['id']}", headers=headers
        )
        assert first_after.json()["data"]["effective_to"] == "2029-05-31"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_statutory_missing_if_match_when_current_exists_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_statutory(client, headers, employee_id=employee["id"], **_joining_payload())

        response = await client.post(
            f"/v1/employees/{employee['id']}/statutory",
            headers=headers,
            json={
                "effective_from": "2029-06-01",
                "is_pf_applicable": True,
                "is_esi_applicable": True,
                "is_lwf_applicable": True,
                "tax_regime": "NEW",
                "revision_reason": "ESI became applicable",
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "STATUTORY_VERSION_REQUIRED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_statutory_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_statutory(client, headers, employee_id=employee["id"], **_joining_payload())

        response = await client.post(
            f"/v1/employees/{employee['id']}/statutory",
            headers={**headers, "If-Match": "999"},
            json={
                "effective_from": "2029-06-01",
                "is_pf_applicable": True,
                "is_esi_applicable": True,
                "is_lwf_applicable": True,
                "tax_regime": "NEW",
                "revision_reason": "ESI became applicable",
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_statutory_effective_from_not_after_current_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_statutory(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/statutory",
            headers={**headers, "If-Match": str(first["version"])},
            json={
                "effective_from": "2027-06-01",
                "is_pf_applicable": True,
                "is_esi_applicable": True,
                "is_lwf_applicable": True,
                "tax_regime": "NEW",
                "revision_reason": "ESI became applicable",
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_EFFECTIVE_FROM"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Tax-regime once-per-FY switch rule (FR-PAY-006) -------------------------------------------


async def test_tax_regime_switch_within_same_fy_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_statutory(
            client,
            headers,
            employee_id=employee["id"],
            **_joining_payload(effective_from="2027-06-01", tax_regime="OLD"),
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/statutory",
            headers={**headers, "If-Match": str(first["version"])},
            json=_joining_payload(effective_from="2027-12-01", tax_regime="NEW"),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "TAX_REGIME_SWITCH_NOT_ALLOWED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_tax_regime_switch_across_fy_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_statutory(
            client,
            headers,
            employee_id=employee["id"],
            **_joining_payload(effective_from="2027-06-01", tax_regime="OLD"),
        )

        second = await _create_statutory(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            **_joining_payload(effective_from="2028-04-01", tax_regime="NEW"),
        )
        assert second["tax_regime"] == "NEW"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_revision_without_tax_regime_change_allowed_same_fy(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The once-per-FY rule only fires when `tax_regime` actually changes — a same-FY revision
    that leaves `tax_regime` unchanged (e.g. ESI becoming applicable) must succeed."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_statutory(
            client,
            headers,
            employee_id=employee["id"],
            **_joining_payload(effective_from="2027-06-01", tax_regime="OLD"),
        )

        second = await _create_statutory(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            **_joining_payload(
                effective_from="2027-12-01", tax_regime="OLD", is_esi_applicable=True
            ),
        )
        assert second["tax_regime"] == "OLD"
        assert second["is_esi_applicable"] is True
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- GiST exclusion constraint -------------------------------------------------------------


async def test_raw_overlapping_insert_rejected_at_database_level(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Bypasses the service's own close-then-insert logic entirely — a raw `INSERT` with dates
    overlapping the existing row must be rejected by `employee_statutory_no_overlap` itself,
    proving the DB constraint is the actual backstop, not just an application-level check."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_statutory(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SET LOCAL row_security = off"))
            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        """
                        INSERT INTO employee_statutory
                            (id, company_id, employee_id, effective_from, effective_to,
                             is_pf_applicable, is_esi_applicable, is_lwf_applicable, tax_regime,
                             created_at, updated_at, version)
                        VALUES
                            (gen_random_uuid(), :company_id, :employee_id, :effective_from, NULL,
                             true, false, true, 'NEW', now(), now(), 1)
                        """
                    ),
                    {
                        "company_id": str(company_id),
                        "employee_id": employee["id"],
                        "effective_from": date(2027, 12, 1),
                    },
                )
            await session.rollback()
        assert first["effective_to"] is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Rehire compatibility --------------------------------------------------------------------


async def test_rehire_first_statutory_after_gap(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The rejoin scenario: an employee's first spell ends, a gap follows, then a new employment
    episode starts. The rejoin's first statutory row behaves exactly like any other "no current
    row" write — no rehire-specific code path exists. Statutory history remains attached to the
    employee's own identity throughout (plan §9)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity, employment = await _setup_employee_with_employment(
            client, headers, joining_date="2027-06-01"
        )
        pre_exit = await _create_statutory(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        terminate = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert terminate.status_code == 200

        pre_exit_after_terminate = await client.get(
            f"/v1/employees/{employee['id']}/statutory/{pre_exit['id']}", headers=headers
        )
        # `terminate_employment` closes the still-open statutory row at the termination date —
        # "last row closed" (plan §9), the same contract Assignment/Compensation already have.
        assert pre_exit_after_terminate.json()["data"]["effective_to"] == "2030-09-30"

        gap_as_of = await client.get(
            f"/v1/employees/{employee['id']}/statutory",
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

        rehire_statutory = await _create_statutory(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2034-02-01",
            is_pf_applicable=True,
            pf_number="PF1234567890",
            is_esi_applicable=False,
            is_lwf_applicable=True,
            tax_regime="NEW",
            revision_reason="Rejoining statutory profile",
        )

        assert rehire_statutory["employee_id"] == employee["id"]
        assert rehire_statutory["effective_to"] is None

        # Full history remains attached to the same employee identity.
        history = await client.get(f"/v1/employees/{employee['id']}/statutory", headers=headers)
        history_ids = [row["id"] for row in history.json()["data"]]
        assert history_ids == [pre_exit["id"], rehire_statutory["id"]]

        # Employee identity is unaffected — same id/employee_code throughout.
        employee_after = await client.get(f"/v1/employees/{employee['id']}", headers=headers)
        assert employee_after.json()["data"]["employee_code"] == employee["employee_code"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Tenant isolation ------------------------------------------------------------------------


async def test_cannot_get_statutory_from_other_tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, _legal_entity_a, _employment_a = await _setup_employee_with_employment(
            client, headers_a
        )
        statutory_a = await _create_statutory(
            client, headers_a, employee_id=employee_a["id"], **_joining_payload()
        )

        response = await client.get(
            f"/v1/employees/{employee_a['id']}/statutory/{statutory_a['id']}",
            headers=headers_b,
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


async def test_cannot_create_statutory_for_other_tenant_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, _legal_entity_a, _employment_a = await _setup_employee_with_employment(
            client, headers_a
        )

        response = await client.post(
            f"/v1/employees/{employee_a['id']}/statutory",
            headers=headers_b,
            json=_joining_payload(),
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


async def test_cannot_list_statutory_from_other_tenant_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """IDOR check: a cross-tenant `employee_id` in the path must not leak even an empty-vs-404
    distinction that would confirm the ID's existence — list returns 404, not an empty list."""
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, _legal_entity_a, _employment_a = await _setup_employee_with_employment(
            client, headers_a
        )
        await _create_statutory(
            client, headers_a, employee_id=employee_a["id"], **_joining_payload()
        )

        response = await client.get(
            f"/v1/employees/{employee_a['id']}/statutory", headers=headers_b
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
    the given `data_scope` — mirrors `test_employee_compensation.py`'s own inline setup, extended
    with a `data_scope` parameter to support the negative data-scope-discard proof below (plan
    §21 "New, not in 21_")."""
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
                code=f"STATUTORY_TEST_ROLE_{role_id.hex[:8]}",
                name="Statutory test role",
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
                email=f"scoped-stat-{scoped_user_id.hex[:8]}@example.com",
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
                "(SELECT id FROM \"user\" WHERE email LIKE 'scoped-stat-%')"
            )
        )
        await session.execute(text("DELETE FROM \"user\" WHERE email LIKE 'scoped-stat-%'"))
        await session.commit()


async def test_list_statutory_without_view_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_statutory(client, headers, employee_id=employee["id"], **_joining_payload())
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[]
        )

        response = await client.get(
            f"/v1/employees/{employee['id']}/statutory", headers=scoped_headers
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_create_statutory_without_update_sensitive_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_STATUTORY

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[EMPLOYEE_VIEW_STATUTORY]
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/statutory",
            headers=scoped_headers,
            json=_joining_payload(),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_view_statutory_permission_does_not_grant_write(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`.VIEW_STATUTORY` alone reads but cannot write; `.UPDATE_SENSITIVE` alone writes but
    cannot read — the two permissions are strictly independent, mirroring Compensation's own
    `.VIEW_COMPENSATION`/`.UPDATE_COMPENSATION` split."""
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_STATUTORY

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_statutory(client, headers, employee_id=employee["id"], **_joining_payload())
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[EMPLOYEE_VIEW_STATUTORY]
        )

        read_response = await client.get(
            f"/v1/employees/{employee['id']}/statutory", headers=scoped_headers
        )
        assert read_response.status_code == 200
        assert len(read_response.json()["data"]) == 1
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_create_statutory_with_update_sensitive_permission_succeeds(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.employee.permissions import EMPLOYEE_UPDATE_SENSITIVE

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[EMPLOYEE_UPDATE_SENSITIVE]
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/statutory",
            headers=scoped_headers,
            json=_joining_payload(),
        )
        assert response.status_code == 201, response.text

        # The writer alone (without `.VIEW_STATUTORY`) cannot then read it back.
        read_response = await client.get(
            f"/v1/employees/{employee['id']}/statutory", headers=scoped_headers
        )
        assert read_response.status_code == 403
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_view_statutory_self_scope_sees_own_record_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`docs/architecture/EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md` Finding F2 / `docs/
    modules/employee/37_EMPLOYEE_COMPENSATION_STATUTORY_DATA_SCOPE_IMPLEMENTATION_REPORT.md`: a
    caller holding `EMPLOYEE.VIEW_STATUTORY` at `SELF` scope, whose JWT `employee_id` claim
    matches the path `employee_id`, sees their own statutory record; another employee's record
    is invisible (`404`, not `403`, matching every other out-of-scope convention in this module —
    the caller cannot distinguish "out of scope" from "doesn't exist" or "wrong tenant"). This
    replaces `test_view_statutory_ignores_non_company_data_scope`, which asserted the inverse
    (vulnerable) behavior before the resolve-then-discard bug was fixed."""
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_STATUTORY

    headers, company_id, user_id = await _register_tenant(client)
    try:
        self_employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        other_employee, _legal_entity_2, _employment_2 = await _setup_employee_with_employment(
            client, headers
        )
        self_statutory = await _create_statutory(
            client, headers, employee_id=self_employee["id"], **_joining_payload()
        )
        await _create_statutory(
            client,
            headers,
            employee_id=other_employee["id"],
            **_joining_payload(pf_number="PF9999999999"),
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW_STATUTORY],
            data_scope="SELF",
            caller_employee_id=UUID(self_employee["id"]),
        )

        own = await client.get(
            f"/v1/employees/{self_employee['id']}/statutory", headers=scoped_headers
        )
        assert own.status_code == 200
        assert len(own.json()["data"]) == 1
        assert own.json()["data"][0]["pf_number"] == "PF1234567890"

        # Direct single-record ID lookup cannot bypass scope either.
        own_detail = await client.get(
            f"/v1/employees/{self_employee['id']}/statutory/{self_statutory['id']}",
            headers=scoped_headers,
        )
        assert own_detail.status_code == 200

        other = await client.get(
            f"/v1/employees/{other_employee['id']}/statutory", headers=scoped_headers
        )
        assert other.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_view_statutory_self_scope_no_employee_id_sees_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller with a `SELF`-scoped `EMPLOYEE.VIEW_STATUTORY` grant but no linked `employee_id`
    (JWT claim is `None`) must fail closed — the visible set is empty, never falls back to
    `COMPANY`. This is the exact scenario `test_view_statutory_ignores_non_company_data_scope`
    used to assert resolved to `200`/full access before the fix."""
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_STATUTORY

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_statutory(client, headers, employee_id=employee["id"], **_joining_payload())

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW_STATUTORY],
            data_scope="SELF",
            caller_employee_id=None,
        )

        response = await client.get(
            f"/v1/employees/{employee['id']}/statutory", headers=scoped_headers
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_view_statutory_reportees_scope_cannot_see_unrelated_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`RBAC_DATA_SCOPE_DECISIONS.md` Decision F: managers get no Statutory visibility by
    default, but if a tenant *does* grant `EMPLOYEE.VIEW_STATUTORY` at `REPORTEES` scope, it must
    be honored (not silently widened to `COMPANY`) — proves the fix applies to every scope level,
    not just `SELF`. The manager's own record is not implicitly included (`REPORTEES` does not
    imply `SELF`, matching `EmployeeService.resolve_visible_employee_ids`'s existing semantics)."""
    from datetime import UTC, datetime

    from hrms.modules.employee.models import EmployeeAssignment
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_STATUTORY

    headers, company_id, user_id = await _register_tenant(client)
    try:
        manager, _legal_entity, _employment = await _setup_employee_with_employment(client, headers)
        report, _legal_entity_2, _employment_2 = await _setup_employee_with_employment(
            client, headers
        )
        unrelated, _legal_entity_3, _employment_3 = await _setup_employee_with_employment(
            client, headers
        )
        await _create_statutory(
            client,
            headers,
            employee_id=report["id"],
            **_joining_payload(pf_number="PF1111111111"),
        )
        await _create_statutory(
            client,
            headers,
            employee_id=unrelated["id"],
            **_joining_payload(pf_number="PF2222222222"),
        )

        # A minimal `employee_assignment` row, inserted directly, matching the pattern
        # `test_employee_data_scope.py::_assign_manager` already establishes for this exact
        # need — only the columns the `REPORTEES` resolver reads are set.
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
            permission_codes=[EMPLOYEE_VIEW_STATUTORY],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager["id"]),
        )

        report_resp = await client.get(
            f"/v1/employees/{report['id']}/statutory", headers=scoped_headers
        )
        assert report_resp.status_code == 200

        unrelated_resp = await client.get(
            f"/v1/employees/{unrelated['id']}/statutory", headers=scoped_headers
        )
        assert unrelated_resp.status_code == 404

        # REPORTEES does not implicitly include the manager's own record.
        own_resp = await client.get(
            f"/v1/employees/{manager['id']}/statutory", headers=scoped_headers
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


async def test_view_statutory_company_scope_sees_any_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`COMPANY` scope (the default for every existing seeded role) still sees every employee's
    statutory record — the fix does not narrow `COMPANY`-scoped access at all, matching every
    real tenant's current, unchanged behavior."""
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_STATUTORY

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_statutory(client, headers, employee_id=employee["id"], **_joining_payload())

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW_STATUTORY],
            data_scope="COMPANY",
            caller_employee_id=None,
        )

        response = await client.get(
            f"/v1/employees/{employee['id']}/statutory", headers=scoped_headers
        )
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]["pf_number"] == "PF1234567890"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# --- Data-scope enforcement (write path, Finding C / F9) ---------------------------------------
#
# `docs/modules/employee/39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Phase 2:
# `create_statutory` now also resolves and enforces the caller's `DataScope` against the target
# employee, in addition to the bare `EMPLOYEE.UPDATE_SENSITIVE` permission check that already
# existed. An out-of-scope target behaves exactly like a nonexistent one (`404`, not `403`).


async def test_create_statutory_reportees_scope_target_visibility(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller holding `EMPLOYEE.UPDATE_SENSITIVE` at `REPORTEES` scope can write a direct
    report's statutory profile, but an unrelated employee's is invisible (`404`), never `403`."""
    from datetime import UTC, date, datetime

    from hrms.modules.employee.models import EmployeeAssignment
    from hrms.modules.employee.permissions import EMPLOYEE_UPDATE_SENSITIVE

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
            permission_codes=[EMPLOYEE_UPDATE_SENSITIVE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager["id"]),
        )

        in_scope = await client.post(
            f"/v1/employees/{report['id']}/statutory",
            headers=scoped_headers,
            json=_joining_payload(),
        )
        assert in_scope.status_code == 201, in_scope.text

        out_of_scope = await client.post(
            f"/v1/employees/{unrelated['id']}/statutory",
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


async def test_create_statutory_cross_tenant_scoped_actor_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Cross-tenant + data-scope composed on `create_statutory`: a `COMPANY`-scoped actor in
    tenant A cannot write a statutory profile for tenant B's employee, tenant isolation wins
    first."""
    from hrms.modules.employee.permissions import EMPLOYEE_UPDATE_SENSITIVE

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
            permission_codes=[EMPLOYEE_UPDATE_SENSITIVE],
            data_scope="COMPANY",
        )

        response = await client.post(
            f"/v1/employees/{employee_b['id']}/statutory",
            headers={**scoped_headers, "X-Company-Id": str(company_a)},
            json=_joining_payload(),
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)
        await _cleanup_scoped_users()
