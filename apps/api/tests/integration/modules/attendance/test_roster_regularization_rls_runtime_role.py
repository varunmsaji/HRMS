"""Stage 9 (finding F-10): shift references on roster and regularization writes, under `hrms_app`.

`shift_roster.shift_id` and `attendance_regularization_request.requested_shift_id` are plain foreign
keys, and a foreign-key check ignores RLS, so the database accepts another company's shift. The
service must therefore look the shift up inside the authenticated company first. Before the fix a
foreign shift was stored (HTTP 201) by an ordinary tenant user; an unknown id came back as a
misleading date conflict.

Roles: tenant registration, the wired employee graph, the regularization policy and teardown run on
the suite's admin engine; every API call under test runs inside `app_as_runtime_role()` (the
application's engine connected as `hrms_app`, which `rls_support` first proves is neither SUPERUSER
nor BYPASSRLS); state is asserted on the admin engine. Teardown uses `wipe_tenant`, which removes
only the rows of the two tenants this module created (the attendance cleanup helper does not delete
roster or regularization rows)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tests import rls_support
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _register_tenant,
)
from tests.integration.modules.attendance.test_regularization import (
    _create_regularization_policy,
)
from tests.integration.tenant_wipe import wipe_tenant

pytestmark = pytest.mark.asyncio

ROSTER_DATE = "2026-09-14"
REG_DATE = "2026-08-12"


@dataclass
class Tenant:
    headers: dict[str, str]
    company_id: UUID
    user_id: UUID | None
    employee_id: str
    shift_id: str


async def _provision(client: AsyncClient) -> Tenant:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        await _create_regularization_policy(client, headers, allowed_types=["WRONG_SHIFT"])
    except BaseException:
        await wipe_tenant(company_id=company_id, user_id=user_id)
        raise
    return Tenant(headers, company_id, user_id, wired["employee"]["id"], wired["shift"]["id"])


@pytest.fixture
async def tenants(
    client: AsyncClient, seeded_plan_catalogue: None
) -> AsyncIterator[tuple[Tenant, Tenant]]:
    made: list[Tenant] = []
    try:
        made.append(await _provision(client))
        made.append(await _provision(client))
        yield made[0], made[1]
    finally:
        for tenant in reversed(made):
            await wipe_tenant(company_id=tenant.company_id, user_id=tenant.user_id)


async def _counts(admin_engine: AsyncEngine, tenant: Tenant) -> tuple[int, int]:
    async with admin_engine.connect() as conn:
        rosters = (
            await conn.execute(
                text("SELECT count(*) FROM shift_roster WHERE company_id = :c"),
                {"c": str(tenant.company_id)},
            )
        ).scalar_one()
        requests = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM attendance_regularization_request WHERE company_id = :c"
                ),
                {"c": str(tenant.company_id)},
            )
        ).scalar_one()
    return int(rosters), int(requests)


async def _cross_tenant_rows(admin_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]) -> int:
    """Rows in either tenant whose shift belongs to a different company."""
    ids = [str(t.company_id) for t in tenants]
    async with admin_engine.connect() as conn:
        total = 0
        for sql in (
            "SELECT count(*) FROM shift_roster r JOIN shift s ON s.id = r.shift_id "
            "WHERE r.company_id <> s.company_id AND r.company_id = ANY(:ids)",
            "SELECT count(*) FROM attendance_regularization_request r "
            "JOIN shift s ON s.id = r.requested_shift_id "
            "WHERE r.company_id <> s.company_id AND r.company_id = ANY(:ids)",
        ):
            total += (await conn.execute(text(sql), {"ids": ids})).scalar_one()
    return int(total)


def _roster_body(tenant: Tenant, shift_id: str | None, day: str = ROSTER_DATE) -> dict[str, object]:
    return {"employee_id": tenant.employee_id, "roster_date": day, "shift_id": shift_id}


def _reg_body(tenant: Tenant, shift_id: str, day: str = REG_DATE) -> dict[str, object]:
    return {
        "employee_id": tenant.employee_id,
        "attendance_date": day,
        "request_type": "WRONG_SHIFT",
        "reason": "stage 9",
        "requested_shift_id": shift_id,
    }


def _error(response: object) -> tuple[int, object]:
    r = response  # httpx.Response
    return r.status_code, r.json()["error"]["code"]  # type: ignore[attr-defined]


async def test_requests_are_served_by_the_runtime_role(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: object,
    admin_engine: AsyncEngine,
) -> None:
    a, _ = tenants
    backends = text(
        "SELECT pid, usename FROM pg_stat_activity WHERE datname = current_database() "
        "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
    )
    async with admin_engine.connect() as conn:
        before = {row.pid for row in await conn.execute(backends)}
    async with app_as_runtime_role():  # type: ignore[operator]
        assert (await client.get("/v1/rosters", headers=a.headers)).status_code == 200
        async with admin_engine.connect() as conn:
            created = {r.usename for r in await conn.execute(backends) if r.pid not in before}
    assert created == {urlsplit(rls_support.runtime_url()).username}, created


async def test_foreign_shift_is_rejected_on_roster_create_and_nothing_is_written(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: object,
    admin_engine: AsyncEngine,
) -> None:
    a, b = tenants
    before_a, before_b = await _counts(admin_engine, a), await _counts(admin_engine, b)
    async with app_as_runtime_role():  # type: ignore[operator]
        single = await client.post(
            "/v1/rosters", headers=a.headers, json=_roster_body(a, b.shift_id)
        )
        bulk = await client.post(
            "/v1/rosters/bulk",
            headers=a.headers,
            json={
                "employee_id": a.employee_id,
                "entries": [{"roster_date": ROSTER_DATE, "shift_id": b.shift_id}],
            },
        )
    assert single.status_code == 404, single.text
    assert bulk.status_code == 404, bulk.text
    assert await _counts(admin_engine, a) == before_a
    assert await _counts(admin_engine, b) == before_b
    assert await _cross_tenant_rows(admin_engine, tenants) == 0


async def test_foreign_shift_is_rejected_on_roster_update_and_the_row_is_unchanged(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: object,
    admin_engine: AsyncEngine,
) -> None:
    a, b = tenants
    async with app_as_runtime_role():  # type: ignore[operator]
        created = await client.post(
            "/v1/rosters", headers=a.headers, json=_roster_body(a, a.shift_id)
        )
        assert created.status_code == 201, created.text
        roster = created.json()["data"]
        patched = await client.patch(
            f"/v1/rosters/{roster['id']}",
            headers={**a.headers, "If-Match": str(roster["version"])},
            json={"shift_id": b.shift_id},
        )
    assert patched.status_code == 404, patched.text
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT shift_id, version FROM shift_roster WHERE id = :i"),
                {"i": roster["id"]},
            )
        ).one()
    assert (str(row.shift_id), row.version) == (a.shift_id, roster["version"])
    assert await _cross_tenant_rows(admin_engine, tenants) == 0


async def test_foreign_requested_shift_is_rejected_on_regularization_submit(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: object,
    admin_engine: AsyncEngine,
) -> None:
    a, b = tenants
    before_a, before_b = await _counts(admin_engine, a), await _counts(admin_engine, b)
    async with app_as_runtime_role():  # type: ignore[operator]
        response = await client.post(
            "/v1/regularizations", headers=a.headers, json=_reg_body(a, b.shift_id)
        )
    assert response.status_code == 404, response.text
    assert await _counts(admin_engine, a) == before_a
    assert await _counts(admin_engine, b) == before_b
    assert await _cross_tenant_rows(admin_engine, tenants) == 0


async def test_unknown_and_foreign_shift_ids_get_the_same_external_response(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: object,
) -> None:
    a, b = tenants
    unknown = str(uuid4())
    async with app_as_runtime_role():  # type: ignore[operator]
        roster_foreign = await client.post(
            "/v1/rosters", headers=a.headers, json=_roster_body(a, b.shift_id)
        )
        roster_unknown = await client.post(
            "/v1/rosters", headers=a.headers, json=_roster_body(a, unknown)
        )
        reg_foreign = await client.post(
            "/v1/regularizations", headers=a.headers, json=_reg_body(a, b.shift_id)
        )
        reg_unknown = await client.post(
            "/v1/regularizations", headers=a.headers, json=_reg_body(a, unknown)
        )

    def shape(r: object) -> tuple[int, object, object]:
        body = r.json()["error"]  # type: ignore[attr-defined]
        return r.status_code, body["code"], body["message"]  # type: ignore[attr-defined]

    assert shape(roster_foreign) == shape(roster_unknown)
    assert shape(reg_foreign) == shape(reg_unknown)
    assert shape(roster_foreign)[0] == 404


async def test_own_company_shift_still_works_for_roster_and_regularization(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: object,
    admin_engine: AsyncEngine,
) -> None:
    a, _ = tenants
    async with app_as_runtime_role():  # type: ignore[operator]
        roster = await client.post(
            "/v1/rosters", headers=a.headers, json=_roster_body(a, a.shift_id)
        )
        week_off = await client.post(
            "/v1/rosters",
            headers=a.headers,
            json={
                "employee_id": a.employee_id,
                "roster_date": "2026-09-15",
                "is_week_off_override": True,
            },
        )
        reg = await client.post(
            "/v1/regularizations", headers=a.headers, json=_reg_body(a, a.shift_id)
        )
    assert roster.status_code == 201, roster.text
    assert roster.json()["data"]["shift_id"] == a.shift_id
    assert week_off.status_code == 201, week_off.text  # shift_id=None remains valid
    assert reg.status_code == 201, reg.text
    assert reg.json()["data"]["requested_shift_id"] == a.shift_id
    assert await _counts(admin_engine, a) == (2, 1)
    assert await _cross_tenant_rows(admin_engine, tenants) == 0


async def test_duplicate_date_is_still_a_date_conflict(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: object,
) -> None:
    a, _ = tenants
    async with app_as_runtime_role():  # type: ignore[operator]
        first = await client.post(
            "/v1/rosters", headers=a.headers, json=_roster_body(a, a.shift_id)
        )
        second = await client.post(
            "/v1/rosters", headers=a.headers, json=_roster_body(a, a.shift_id)
        )
    assert first.status_code == 201, first.text
    assert _error(second) == (409, "SHIFT_ROSTER_DATE_CONFLICT")


async def test_other_tenant_cannot_read_or_modify_existing_records(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: object,
    admin_engine: AsyncEngine,
) -> None:
    a, b = tenants
    async with app_as_runtime_role():  # type: ignore[operator]
        roster = (
            await client.post("/v1/rosters", headers=a.headers, json=_roster_body(a, a.shift_id))
        ).json()["data"]
        reg = (
            await client.post(
                "/v1/regularizations", headers=a.headers, json=_reg_body(a, a.shift_id)
            )
        ).json()["data"]
    async with admin_engine.connect() as conn:
        before = (
            await conn.execute(
                text("SELECT status, version, shift_id FROM shift_roster WHERE id = :i"),
                {"i": roster["id"]},
            )
        ).one()
        reg_before = (
            await conn.execute(
                text("SELECT status, version FROM attendance_regularization_request WHERE id = :i"),
                {"i": reg["id"]},
            )
        ).one()

    rid, qid = roster["id"], reg["id"]
    if_match = {**b.headers, "If-Match": str(roster["version"])}
    async with app_as_runtime_role():  # type: ignore[operator]
        attempts = [
            await client.get(f"/v1/rosters/{rid}", headers=b.headers),
            await client.patch(
                f"/v1/rosters/{rid}", headers=if_match, json={"shift_id": b.shift_id}
            ),
            await client.post(f"/v1/rosters/{rid}/publish", headers=if_match),
            await client.delete(f"/v1/rosters/{rid}", headers=if_match),
            await client.get(f"/v1/regularizations/{qid}", headers=b.headers),
            await client.post(
                f"/v1/regularizations/{qid}/cancel",
                headers={**b.headers, "If-Match": str(reg["version"])},
                json={},
            ),
        ]
        listing = await client.get("/v1/rosters", headers=b.headers)
    assert [r.status_code for r in attempts] == [404] * len(attempts), [r.text for r in attempts]
    assert rid not in {x["id"] for x in listing.json()["data"]}
    async with admin_engine.connect() as conn:
        after = (
            await conn.execute(
                text("SELECT status, version, shift_id FROM shift_roster WHERE id = :i"),
                {"i": rid},
            )
        ).one()
        reg_after = (
            await conn.execute(
                text("SELECT status, version FROM attendance_regularization_request WHERE id = :i"),
                {"i": qid},
            )
        ).one()
    assert tuple(after) == tuple(before)
    assert tuple(reg_after) == tuple(reg_before)


async def test_alternating_tenants_over_pooled_connections_keep_their_own_context(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],
    app_as_runtime_role: object,
    admin_engine: AsyncEngine,
) -> None:
    a, b = tenants
    days = ["2026-09-16", "2026-09-17", "2026-09-18", "2026-09-19"]
    async with app_as_runtime_role():  # type: ignore[operator]
        for index, day in enumerate(days):
            tenant, other = (a, b) if index % 2 == 0 else (b, a)
            ok = await client.post(
                "/v1/rosters",
                headers=tenant.headers,
                json=_roster_body(tenant, tenant.shift_id, day),
            )
            denied = await client.post(
                "/v1/rosters",
                headers=tenant.headers,
                json=_roster_body(tenant, other.shift_id, day),
            )
            assert ok.status_code == 201, ok.text
            assert ok.json()["data"]["company_id"] == str(tenant.company_id)
            assert denied.status_code == 404, denied.text
    assert await _counts(admin_engine, a) == (2, 0)
    assert await _counts(admin_engine, b) == (2, 0)
    assert await _cross_tenant_rows(admin_engine, tenants) == 0
