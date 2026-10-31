"""Stage 2 of the P1 remediation: the punch -> attendance-day workflow under the real runtime role.

Selected workflow (and why): on-behalf punches (`POST /v1/attendance/punches`), on-demand day
calculation (`POST /v1/attendance/days/calculate`), recompute, and the reads over them
(`GET /v1/attendance/punches`, `GET /v1/attendance/days[/{id}]`). It is small, has a hard tenant
boundary (every table involved - `punch`, `attendance_day`, `employee`, policy tables - carries
`company_id` under `FORCE ROW LEVEL SECURITY`), exercises real application behaviour (service,
repository, scope checks, the best-effort post-commit recalculation), and needs no other module.

How roles are split (docs/blind-audit-2026-10-29/HRMS_P1_VERIFICATION_REPORT.md, V-1):
* privileged setup and teardown - tenant registration, the wired employee graph, cleanup - runs on
  the suite's default (admin) engine, before and after the runtime block;
* every operation under test runs inside `app_as_runtime_role()`, i.e. the application's own engine
  connected as `hrms_app`, which `tests/rls_support.py` first proves is not SUPERUSER / BYPASSRLS.
  `test_requests_are_served_by_the_runtime_role` additionally inspects `pg_stat_activity` to show
  that the backends serving the HTTP requests were `hrms_app` connections.

Not applicable here and therefore not tested: cross-tenant *creates* by raw INSERT (the policy's
WITH CHECK is proven on the probe table in `tests/security/test_rls_harness.py`; the HTTP create
route takes `company_id` from the verified token, never from the body).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine
from tests import rls_support
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio

DAY = "2026-08-10"
NEW_DAY = "2026-08-11"


@dataclass
class Tenant:
    headers: dict[str, str]
    company_id: UUID
    employee_id: str
    day_id: str

    @property
    def token_only(self) -> dict[str, str]:
        return {"Authorization": self.headers["Authorization"]}


async def _provision(client: AsyncClient) -> tuple[Tenant, UUID | None]:
    """Admin-engine setup: register a tenant, wire one employee, record + calculate one day."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        calculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": DAY},
        )
        assert calculated.status_code == 200, calculated.text
        day_id = calculated.json()["data"]["id"]
    except BaseException:
        await _teardown(company_id, user_id)
        raise
    return Tenant(headers, company_id, employee_id, day_id), user_id


async def _teardown(company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


@pytest.fixture
async def tenants(
    client: AsyncClient, seeded_plan_catalogue: None
) -> AsyncIterator[tuple[Tenant, Tenant]]:
    """Two fully provisioned tenants. Teardown is in `finally` and always uses the admin engine
    (the runtime block has exited by then), so a failing test cannot leave rows behind."""
    a, user_a = await _provision(client)
    try:
        b, user_b = await _provision(client)
    except BaseException:
        await _teardown(a.company_id, user_a)
        raise
    try:
        yield a, b
    finally:
        await _teardown(a.company_id, user_a)
        await _teardown(b.company_id, user_b)


@asynccontextmanager
async def _snapshot_guard(admin_engine: AsyncEngine, tenant: Tenant) -> AsyncIterator[None]:
    """Asserts that a tenant's attendance rows are byte-for-byte unchanged across the block."""
    before = await _snapshot(admin_engine, tenant.company_id)
    yield
    assert await _snapshot(admin_engine, tenant.company_id) == before


async def _snapshot(admin_engine: AsyncEngine, company_id: UUID) -> dict[str, Any]:
    async with admin_engine.connect() as conn:  # admin role: not subject to RLS
        punches = (
            await conn.execute(
                text(
                    "SELECT id, punch_time, direction, reference FROM punch "
                    "WHERE company_id = :c ORDER BY id"
                ),
                {"c": str(company_id)},
            )
        ).all()
        days = (
            await conn.execute(
                text(
                    "SELECT id, attendance_status, calculation_version, updated_at "
                    "FROM attendance_day WHERE company_id = :c ORDER BY id"
                ),
                {"c": str(company_id)},
            )
        ).all()
    return {"punches": [tuple(r) for r in punches], "days": [tuple(r) for r in days]}


def _ids(payload: Any) -> set[str]:
    """Every `id` string anywhere in a JSON payload."""
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "id" and isinstance(value, str):
                found.add(value)
            found |= _ids(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= _ids(item)
    return found


# --- evidence that the application really ran as hrms_app ---------------------------------------


async def test_requests_are_served_by_the_runtime_role(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    admin_engine: AsyncEngine,
) -> None:
    a, _ = tenants
    runtime_user = urlsplit(rls_support.runtime_url()).username
    admin_user = urlsplit(rls_support.admin_url()).username
    backends = text(
        "SELECT pid, usename FROM pg_stat_activity WHERE datname = current_database() "
        "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
    )
    async with admin_engine.connect() as conn:  # connections that exist before the block
        before = {row.pid for row in await conn.execute(backends)}
    async with app_as_runtime_role():
        response = await client.get("/v1/attendance/days", headers=a.headers)
        assert response.status_code == 200, response.text
        async with admin_engine.connect() as conn:
            created = {row.usename for row in await conn.execute(backends) if row.pid not in before}
    # Every connection the request opened (the application's own pool) is the runtime role. Using
    # the pids that appeared during the block keeps this independent of connections other tests
    # in the same process may have left open.
    assert created == {runtime_user}, created
    assert runtime_user != admin_user


# --- A: valid tenant access ----------------------------


async def test_valid_tenant_can_punch_calculate_and_read_under_runtime_role(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
) -> None:
    a, _ = tenants
    async with app_as_runtime_role():
        # Writes: two punches, then an explicit calculation for a new day.
        await _punch(
            client,
            a.headers,
            employee_id=a.employee_id,
            hour=9,
            minute=0,
            direction="IN",
            day=NEW_DAY,
        )
        await _punch(
            client,
            a.headers,
            employee_id=a.employee_id,
            hour=18,
            minute=0,
            direction="OUT",
            day=NEW_DAY,
        )
        calculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=a.headers,
            params={"employee_id": a.employee_id, "date": NEW_DAY},
        )
        assert calculated.status_code == 200, calculated.text
        assert calculated.json()["data"]["attendance_status"] == "PRESENT"
        assert calculated.json()["data"]["worked_minutes"] == 540

        # Reads return the tenant's own records, including those written under the admin role.
        days = await client.get("/v1/attendance/days", headers=a.headers)
        assert days.status_code == 200, days.text
        assert {a.day_id, calculated.json()["data"]["id"]} <= {d["id"] for d in days.json()["data"]}
        one = await client.get(f"/v1/attendance/days/{a.day_id}", headers=a.headers)
        assert one.status_code == 200 and one.json()["data"]["id"] == a.day_id
        punches = await client.get(
            "/v1/attendance/punches", headers=a.headers, params={"employee_id": a.employee_id}
        )
        assert punches.status_code == 200, punches.text
        assert len(punches.json()["data"]) == 4  # 2 admin-built + 2 written under hrms_app

        recomputed = await client.post(
            f"/v1/attendance/days/{a.day_id}/recompute", headers=a.headers
        )
        assert recomputed.status_code == 200, recomputed.text


# --- B: cross-tenant reads -----------------------------------------------------------------------


async def test_tenant_a_cannot_read_tenant_b_attendance(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    runtime_engine: AsyncEngine,
) -> None:
    a, b = tenants
    async with app_as_runtime_role():
        a_days = await client.get("/v1/attendance/days", headers=a.headers)
        assert a_days.status_code == 200, a_days.text
        assert b.day_id not in _ids(a_days.json())
        assert a.day_id in _ids(a_days.json())

        # Direct object reference to B's day: indistinguishable from "does not exist".
        by_id = await client.get(f"/v1/attendance/days/{b.day_id}", headers=a.headers)
        assert by_id.status_code == 404, by_id.text
        assert b.day_id not in by_id.text

        # Filtering by B's employee returns none of B's records (empty list or an error).
        by_employee = await client.get(
            "/v1/attendance/days", headers=a.headers, params={"employee_id": b.employee_id}
        )
        assert b.day_id not in by_employee.text and b.employee_id not in by_employee.text
        punches = await client.get(
            "/v1/attendance/punches", headers=a.headers, params={"employee_id": b.employee_id}
        )
        assert punches.status_code in {200, 404, 422}, punches.text
        if punches.status_code == 200:
            assert punches.json()["data"] == []

        # Alternating tenants on the application's pooled connections must not leak context.
        for headers, own, other in ((b.headers, b, a), (a.headers, a, b), (b.headers, b, a)):
            listed = await client.get("/v1/attendance/days", headers=headers)
            assert listed.status_code == 200, listed.text
            assert own.day_id in _ids(listed.json())
            assert other.day_id not in _ids(listed.json())

    # Repository level: the database itself, not only the app's WHERE clauses, hides B from A.
    async with runtime_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(a.company_id)}
        )
        own = (await conn.execute(text("SELECT count(*) FROM punch"))).scalar_one()
        foreign = (
            await conn.execute(
                text("SELECT count(*) FROM punch WHERE company_id = :b"), {"b": str(b.company_id)}
            )
        ).scalar_one()
        days = (
            await conn.execute(
                text("SELECT count(*) FROM attendance_day WHERE company_id = :b"),
                {"b": str(b.company_id)},
            )
        ).scalar_one()
    assert own == 2 and foreign == 0 and days == 0


# --- C: cross-tenant writes ---------------------------------------------------------------


async def test_tenant_a_cannot_write_to_tenant_b_attendance(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    admin_engine: AsyncEngine,
    runtime_engine: AsyncEngine,
) -> None:
    a, b = tenants
    async with _snapshot_guard(admin_engine, b):
        async with app_as_runtime_role():
            punch = await client.post(
                "/v1/attendance/punches",
                headers=a.headers,
                json={
                    "employee_id": b.employee_id,
                    "punch_time": f"{NEW_DAY}T09:00:00Z",
                    "direction": "IN",
                    "reference": "cross-tenant attempt",
                },
            )
            assert punch.status_code in {403, 404, 422}, punch.text

            calculate = await client.post(
                "/v1/attendance/days/calculate",
                headers=a.headers,
                params={"employee_id": b.employee_id, "date": DAY},
            )
            assert calculate.status_code in {403, 404, 422}, calculate.text

            recompute = await client.post(
                f"/v1/attendance/days/{b.day_id}/recompute", headers=a.headers
            )
            assert recompute.status_code == 404, recompute.text

        # Raw statements as A's tenant against B's rows: RLS makes them match nothing.
        async with runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.company_id', :c, true)"), {"c": str(a.company_id)}
            )
            updated = await conn.execute(
                text("UPDATE punch SET reference = 'hacked' WHERE company_id = :b"),
                {"b": str(b.company_id)},
            )
            deleted = await conn.execute(
                text("DELETE FROM attendance_day WHERE company_id = :b"), {"b": str(b.company_id)}
            )
        assert updated.rowcount == 0 and deleted.rowcount == 0
    # And A's own data is intact as well (nothing A-side was collaterally damaged).
    assert (await _snapshot(admin_engine, a.company_id))["days"]


# --- D: missing / invalid tenant context ----------------------------


async def test_unauthenticated_request_with_a_tenant_header_fails_closed(
    client: AsyncClient, tenants: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, b = tenants
    async with app_as_runtime_role():
        for path in ("/v1/attendance/days", "/v1/attendance/punches"):
            response = await client.get(path, headers={"X-Company-Id": str(b.company_id)})
            assert response.status_code == 401, (path, response.text)
            assert b.day_id not in response.text and b.employee_id not in response.text


async def test_token_of_a_with_header_of_b_is_rejected_and_exposes_nothing(
    client: AsyncClient, tenants: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, b = tenants
    spoofed = {**a.headers, "X-Company-Id": str(b.company_id)}
    async with app_as_runtime_role():
        response = await client.get("/v1/attendance/days", headers=spoofed)
        assert response.status_code in {401, 403, 404}, response.text
        assert b.day_id not in response.text and b.employee_id not in response.text


async def test_malformed_and_unknown_tenant_headers_fail_closed(
    client: AsyncClient, tenants: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, b = tenants
    async with app_as_runtime_role():
        for value in ("not-a-uuid", str(uuid4())):
            response = await client.get(
                "/v1/attendance/days",
                headers={"Authorization": a.headers["Authorization"], "X-Company-Id": value},
            )
            assert response.status_code in {400, 401, 403, 404, 422}, (value, response.text)
            assert a.day_id not in response.text and b.day_id not in response.text


async def test_token_only_request_is_served_as_documented(
    client: AsyncClient, tenants: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, b = tenants
    async with app_as_runtime_role():
        response = await client.get("/v1/attendance/days", headers=a.token_only)
        assert response.status_code == 200, response.text
        assert a.day_id in _ids(response.json()) and b.day_id not in _ids(response.json())


async def test_token_only_request_never_exposes_another_tenant(
    client: AsyncClient, tenants: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    """A header-less request never exposes another tenant, whatever it returns."""
    a, b = tenants
    async with app_as_runtime_role():
        try:
            response = await client.get("/v1/attendance/days", headers=a.token_only)
        except DBAPIError:
            return  # an unhandled DB error is a defect (V-4b) but it exposes nothing
        assert b.day_id not in response.text and b.employee_id not in response.text
