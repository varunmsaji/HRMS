"""Integration tests for the Employee Banking API (E-08) —
`/v1/employees/{employee_id}/bank*`.

Follows the same checklist as `test_employee_statutory.py` (E-07): create, list, get,
mass-assignment rejection, stale-version conflict, cross-tenant isolation, permission matrix,
the `employee_bank_no_overlap` GiST exclusion constraint's friendly-error surface, the as-of-date
read pattern, the "no covering employment" rule, and rehire compatibility — plus the scenarios
that are load-bearing *differences* from every prior slice
(`docs/modules/employee/33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md`):

- Termination does **not** close the current bank row (plan §7) — the opposite of Statutory's
  own "last row closed" contract.
- Rehire's first bank write, because the pre-exit row was never auto-closed, takes the
  close-then-insert branch (`If-Match` required) rather than the "no current row" branch every
  other sub-resource's rehire write takes (plan §7).
- `EMPLOYEE.VIEW_BANKING` is `SELF`-scoped by default (plan §8/§15 PD-1 Option 2, implementing
  the LOCKED `RBAC_DATA_SCOPE_DECISIONS.md` Decision E) — the opposite of Statutory's
  `COMPANY`-only posture.
"""

from datetime import UTC, date, datetime, timedelta
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


async def _create_bank(
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
        f"/v1/employees/{employee_id}/bank", headers=request_headers, json=body
    )
    assert response.status_code == expected_status, response.text
    return dict(response.json()["data"]) if expected_status < 400 else dict(response.json())


def _bank_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "effective_from": "2027-06-01",
        "account_holder_name": "Meera Iyer",
        "account_number_enc": "1234567890",
        "bank_name": "State Bank",
        "ifsc": "SBIN0001234",
        "branch_name": "MG Road",
        "payment_mode": "BANK",
    }
    payload.update(overrides)
    return payload


async def _cleanup_banks(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employee_bank WHERE company_id = :cid"), {"cid": str(company_id)}
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
    """Full teardown in FK-safe order: bank (-> employee) -> employment (-> employee,
    legal_entity) -> employee (-> number_series) -> the rest (legal_entity/company/roles/user)."""
    await _cleanup_banks(company_id=company_id)
    await _cleanup_employments(company_id=company_id)
    await _cleanup_employees(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


# --- Create: first bank row (no current row) ----------------------------------------------------


async def test_create_first_bank_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        bank = await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())

        assert bank["employee_id"] == employee["id"]
        assert bank["bank_name"] == "State Bank"
        assert bank["ifsc"] == "SBIN0001234"
        assert bank["payment_mode"] == "BANK"
        assert bank["effective_to"] is None
        assert bank["is_primary"] is True
        assert bank["verification_status"] == "PENDING"
        assert bank["penny_drop_reference"] is None
        assert bank["version"] == 1

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "employee_bank",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "BANK_REVISED"
            assert audit_rows[0].before_json is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_bank_without_covering_employment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        # No employment created for this employee at all.

        response = await client.post(
            f"/v1/employees/{employee['id']}/bank", headers=headers, json=_bank_payload()
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "NO_ACTIVE_EMPLOYMENT"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_bank_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/bank",
            headers=headers,
            json=_bank_payload(version=99, is_primary=False, verification_status="VERIFIED"),
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_bank_unknown_employee_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            f"/v1/employees/{uuid4()}/bank", headers=headers, json=_bank_payload()
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_bank_invalid_payment_mode_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/bank",
            headers=headers,
            json=_bank_payload(payment_mode="CRYPTO"),
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_bank_missing_payment_mode_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        payload = _bank_payload()
        del payload["payment_mode"]

        response = await client.post(
            f"/v1/employees/{employee['id']}/bank", headers=headers, json=payload
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_bank_minimal_fields_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Only `effective_from`/`payment_mode` are required — no source document requires
    `account_number_enc`/`ifsc`/etc. on every write."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )

        bank = await _create_bank(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            payment_mode="CASH",
        )
        assert bank["payment_mode"] == "CASH"
        assert bank["account_number_enc"] is None
        assert bank["ifsc"] is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Read / list (incl. as-of) --------------------------------------------------------------------


async def test_list_banks_empty_state(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.get(f"/v1/employees/{employee['id']}/bank", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_get_bank_not_found(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.get(
            f"/v1/employees/{employee['id']}/bank/{uuid4()}", headers=headers
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_list_banks_as_of_date_boundaries(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())
        await _create_bank(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            effective_from="2029-06-01",
            bank_name="HDFC Bank",
            ifsc="HDFC0001234",
            payment_mode="BANK",
        )

        async def _as_of(day: str) -> list[dict[str, Any]]:
            resp = await client.get(
                f"/v1/employees/{employee['id']}/bank",
                headers=headers,
                params={"as_of": day},
            )
            assert resp.status_code == 200
            return list(resp.json()["data"])

        assert len(await _as_of("2027-06-01")) == 1  # first row's start, inclusive
        assert (await _as_of("2029-05-31"))[0]["bank_name"] == "State Bank"
        assert (await _as_of("2029-06-01"))[0]["bank_name"] == "HDFC Bank"
        assert await _as_of("2027-05-31") == []  # one day before the first row starts

        history = await client.get(f"/v1/employees/{employee['id']}/bank", headers=headers)
        assert len(history.json()["data"]) == 2
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Revision ------------------------------------------------------------------------------------


async def test_revision_closes_current_and_inserts_new(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())

        second = await _create_bank(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            effective_from="2029-06-01",
            bank_name="HDFC Bank",
            ifsc="HDFC0001234",
            payment_mode="BANK",
        )

        assert second["bank_name"] == "HDFC Bank"

        first_after = await client.get(
            f"/v1/employees/{employee['id']}/bank/{first['id']}", headers=headers
        )
        assert first_after.json()["data"]["effective_to"] == "2029-05-31"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_bank_missing_if_match_when_current_exists_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())

        response = await client.post(
            f"/v1/employees/{employee['id']}/bank",
            headers=headers,
            json={"effective_from": "2029-06-01", "payment_mode": "BANK"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "BANK_VERSION_REQUIRED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_bank_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())

        response = await client.post(
            f"/v1/employees/{employee['id']}/bank",
            headers={**headers, "If-Match": "999"},
            json={"effective_from": "2029-06-01", "payment_mode": "BANK"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_bank_effective_from_not_after_current_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())

        response = await client.post(
            f"/v1/employees/{employee['id']}/bank",
            headers={**headers, "If-Match": str(first["version"])},
            json={"effective_from": "2027-06-01", "payment_mode": "BANK"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_EFFECTIVE_FROM"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- GiST exclusion constraint ---------------------------------------------------------------


async def test_raw_overlapping_insert_rejected_at_database_level(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Bypasses the service's own close-then-insert logic entirely — a raw `INSERT` with dates
    overlapping the existing row must be rejected by `employee_bank_no_overlap` itself, proving
    the DB constraint is the actual backstop, not just an application-level check."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        first = await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SET LOCAL row_security = off"))
            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        """
                        INSERT INTO employee_bank
                            (id, company_id, employee_id, effective_from, effective_to,
                             payment_mode, created_at, updated_at, version)
                        VALUES
                            (gen_random_uuid(), :company_id, :employee_id, :effective_from, NULL,
                             'BANK', now(), now(), 1)
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


# --- Termination interaction — the load-bearing difference from every sibling ----------------


async def test_bank_row_not_closed_by_terminate_employment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The negative counterpart to Statutory's `test_rehire_first_statutory_after_gap`'s "last
    row closed" assertion — Banking's current row must remain open (`effective_to IS NULL`)
    through and after `terminate_employment`, since it is still needed for full-and-final
    settlement payout after the employee has left (plan §7)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, employment = await _setup_employee_with_employment(
            client, headers, joining_date="2027-06-01"
        )
        bank = await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())

        terminate = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert terminate.status_code == 200

        bank_after_terminate = await client.get(
            f"/v1/employees/{employee['id']}/bank/{bank['id']}", headers=headers
        )
        assert bank_after_terminate.json()["data"]["effective_to"] is None
        assert bank_after_terminate.json()["data"]["version"] == 1

        # No BANK_REVISED audit event was written by termination itself.
        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "employee_bank",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1  # only the original create, none from termination
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Rehire compatibility — materially different from every sibling's rehire test ------------


async def test_rehire_first_bank_write_requires_if_match(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Because the pre-exit bank row is never auto-closed at termination (unlike Statutory), the
    rehire's first bank write finds a still-"current" row (`effective_to IS NULL`) and must take
    the close-then-insert branch, requiring `If-Match` — the opposite of Statutory's/
    Compensation's own rehire write, which always takes the "no current row" branch."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity, employment = await _setup_employee_with_employment(
            client, headers, joining_date="2027-06-01"
        )
        pre_exit = await _create_bank(
            client, headers, employee_id=employee["id"], **_bank_payload()
        )

        terminate = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert terminate.status_code == 200

        rehire_employment = await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2034-02-01",
        )
        assert rehire_employment["previous_employment_id"] == employment["id"]

        # Without If-Match: rejected, since a current row (the pre-exit one) still exists.
        missing_if_match = await client.post(
            f"/v1/employees/{employee['id']}/bank",
            headers=headers,
            json={
                "effective_from": "2034-02-01",
                "bank_name": "HDFC Bank",
                "payment_mode": "BANK",
            },
        )
        assert missing_if_match.status_code == 422
        assert missing_if_match.json()["error"]["code"] == "BANK_VERSION_REQUIRED"

        # With the pre-exit row's own version as If-Match: succeeds, closing it.
        rehire_bank = await _create_bank(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(pre_exit["version"]),
            effective_from="2034-02-01",
            bank_name="HDFC Bank",
            payment_mode="BANK",
        )
        assert rehire_bank["employee_id"] == employee["id"]
        assert rehire_bank["effective_to"] is None

        pre_exit_after = await client.get(
            f"/v1/employees/{employee['id']}/bank/{pre_exit['id']}", headers=headers
        )
        assert pre_exit_after.json()["data"]["effective_to"] == "2034-01-31"

        # Full history remains attached to the same employee identity.
        history = await client.get(f"/v1/employees/{employee['id']}/bank", headers=headers)
        history_ids = [row["id"] for row in history.json()["data"]]
        assert history_ids == [pre_exit["id"], rehire_bank["id"]]

        # Employee identity is unaffected — same id/employee_code throughout.
        employee_after = await client.get(f"/v1/employees/{employee['id']}", headers=headers)
        assert employee_after.json()["data"]["employee_code"] == employee["employee_code"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Tenant isolation ------------------------------------------------------------------------


async def test_cannot_get_bank_from_other_tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, _legal_entity_a, _employment_a = await _setup_employee_with_employment(
            client, headers_a
        )
        bank_a = await _create_bank(
            client, headers_a, employee_id=employee_a["id"], **_bank_payload()
        )

        response = await client.get(
            f"/v1/employees/{employee_a['id']}/bank/{bank_a['id']}", headers=headers_b
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


async def test_cannot_create_bank_for_other_tenant_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, _legal_entity_a, _employment_a = await _setup_employee_with_employment(
            client, headers_a
        )

        response = await client.post(
            f"/v1/employees/{employee_a['id']}/bank", headers=headers_b, json=_bank_payload()
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


async def test_cannot_list_bank_from_other_tenant_employee(
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
        await _create_bank(client, headers_a, employee_id=employee_a["id"], **_bank_payload())

        response = await client.get(f"/v1/employees/{employee_a['id']}/bank", headers=headers_b)
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
    the given `data_scope` — mirrors `test_employee_statutory.py`'s own inline setup."""
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
                code=f"BANKING_TEST_ROLE_{role_id.hex[:8]}",
                name="Banking test role",
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
                email=f"scoped-bank-{scoped_user_id.hex[:8]}@example.com",
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
                "(SELECT id FROM \"user\" WHERE email LIKE 'scoped-bank-%')"
            )
        )
        await session.execute(text("DELETE FROM \"user\" WHERE email LIKE 'scoped-bank-%'"))
        await session.commit()


async def test_list_bank_without_view_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[]
        )

        response = await client.get(f"/v1/employees/{employee['id']}/bank", headers=scoped_headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_create_bank_without_update_sensitive_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_BANKING

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[EMPLOYEE_VIEW_BANKING]
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/bank",
            headers=scoped_headers,
            json=_bank_payload(),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_view_banking_permission_does_not_grant_write(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`.VIEW_BANKING` alone reads but cannot write; `.UPDATE_SENSITIVE` alone writes but
    cannot read — the two permissions are strictly independent, mirroring Statutory's own
    `.VIEW_STATUTORY`/`.UPDATE_SENSITIVE` split."""
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_BANKING

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[EMPLOYEE_VIEW_BANKING]
        )

        read_response = await client.get(
            f"/v1/employees/{employee['id']}/bank", headers=scoped_headers
        )
        assert read_response.status_code == 200
        assert len(read_response.json()["data"]) == 1
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_create_bank_with_update_sensitive_permission_succeeds(
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
            f"/v1/employees/{employee['id']}/bank",
            headers=scoped_headers,
            json=_bank_payload(),
        )
        assert response.status_code == 201, response.text

        # The writer alone (without `.VIEW_BANKING`) cannot then read it back.
        read_response = await client.get(
            f"/v1/employees/{employee['id']}/bank", headers=scoped_headers
        )
        assert read_response.status_code == 403
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# --- Data-scope: SELF-scoped by default — the opposite of Statutory's COMPANY-only posture ------


async def test_view_banking_self_scope_sees_own_record_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Plan §8/§15 PD-1 Option 2: `EMPLOYEE.VIEW_BANKING` implements the LOCKED
    `RBAC_DATA_SCOPE_DECISIONS.md` Decision E directly — a caller holding `.VIEW_BANKING` with
    only `SELF` scope, whose JWT `employee_id` claim matches the path `employee_id`, sees their
    own bank record; a different employee's record is invisible (`404`, not `403`, matching
    every other out-of-scope convention in this module)."""
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_BANKING

    headers, company_id, user_id = await _register_tenant(client)
    try:
        self_employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        other_employee, _legal_entity_2, _employment_2 = await _setup_employee_with_employment(
            client, headers
        )
        await _create_bank(client, headers, employee_id=self_employee["id"], **_bank_payload())
        await _create_bank(
            client,
            headers,
            employee_id=other_employee["id"],
            **_bank_payload(bank_name="Other Bank"),
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW_BANKING],
            data_scope="SELF",
            caller_employee_id=UUID(self_employee["id"]),
        )

        own = await client.get(f"/v1/employees/{self_employee['id']}/bank", headers=scoped_headers)
        assert own.status_code == 200
        assert len(own.json()["data"]) == 1
        assert own.json()["data"][0]["bank_name"] == "State Bank"

        other = await client.get(
            f"/v1/employees/{other_employee['id']}/bank", headers=scoped_headers
        )
        assert other.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_view_banking_self_scope_no_employee_id_sees_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller with a `SELF`-scoped grant but no linked `employee_id` (JWT claim is `None`)
    must fail closed — visible set is empty, never falls back to `COMPANY`."""
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_BANKING

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW_BANKING],
            data_scope="SELF",
            caller_employee_id=None,
        )

        response = await client.get(f"/v1/employees/{employee['id']}/bank", headers=scoped_headers)
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_view_banking_company_scope_sees_any_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`COMPANY` scope (e.g. `COMPANY_ADMIN`'s default grant) still sees every employee's bank
    record — `SELF`-scoping the code does not remove `COMPANY`'s own short-circuit."""
    from hrms.modules.employee.permissions import EMPLOYEE_VIEW_BANKING

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW_BANKING],
            data_scope="COMPANY",
            caller_employee_id=None,
        )

        response = await client.get(f"/v1/employees/{employee['id']}/bank", headers=scoped_headers)
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# --- Sensitive-field / logging exposure -------------------------------------------------------


async def test_account_number_absent_without_view_banking_permission(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Whole-sub-resource gating (plan §16 PD-3 default) — without `.VIEW_BANKING` the entire
    resource is inaccessible (`403`), so `account_number_enc` is never present in any response
    body a non-permitted caller receives."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[]
        )

        response = await client.get(f"/v1/employees/{employee['id']}/bank", headers=scoped_headers)
        assert response.status_code == 403
        assert "account_number_enc" not in response.text
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_bank_audit_snapshot_uses_response_model_convention(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Audit `before`/`after` snapshots are built from the same `BankRead` model as the API
    response (`bank_to_audit_dict`) — no extra plaintext fields beyond what the API itself would
    ever return, same pre-existing, project-wide convention every prior slice uses."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _legal_entity, _employment = await _setup_employee_with_employment(
            client, headers
        )
        bank = await _create_bank(client, headers, employee_id=employee["id"], **_bank_payload())

        factory = get_session_factory()
        async with factory() as session:
            audit_row = (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.company_id == company_id,
                        AuditLog.entity_type == "employee_bank",
                        AuditLog.entity_id == UUID(bank["id"]),
                    )
                )
            ).scalar_one()
            assert set(audit_row.after_json.keys()) == set(bank.keys())
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Data-scope enforcement (write path, Finding C / F9) ---------------------------------------
#
# `docs/modules/employee/39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Phase 2:
# `create_bank` used to call an `_assert_employee_exists` helper that resolved no `DataScope`
# at all (unlike its sibling `list_banks`/`get_bank`, which already enforced scope). It now
# resolves and enforces the caller's `DataScope` against the target employee too, in addition to
# the bare `EMPLOYEE.UPDATE_SENSITIVE` permission check that already existed. An out-of-scope
# target behaves exactly like a nonexistent one (`404`, not `403`).


async def test_create_bank_reportees_scope_target_visibility(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller holding `EMPLOYEE.UPDATE_SENSITIVE` at `REPORTEES` scope can write a direct
    report's bank record, but an unrelated employee's is invisible (`404`), never `403`."""
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
            f"/v1/employees/{report['id']}/bank",
            headers=scoped_headers,
            json=_bank_payload(),
        )
        assert in_scope.status_code == 201, in_scope.text

        out_of_scope = await client.post(
            f"/v1/employees/{unrelated['id']}/bank",
            headers=scoped_headers,
            json=_bank_payload(),
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


async def test_create_bank_cross_tenant_scoped_actor_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Cross-tenant + data-scope composed on `create_bank`: a `COMPANY`-scoped actor in tenant A
    cannot write a bank record for tenant B's employee, tenant isolation wins first."""
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
            f"/v1/employees/{employee_b['id']}/bank",
            headers={**scoped_headers, "X-Company-Id": str(company_a)},
            json=_bank_payload(),
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)
        await _cleanup_scoped_users()
