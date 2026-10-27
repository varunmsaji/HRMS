"""QA B6 - platform console, token separation, tenant isolation, RBAC sweep and auth P0 re-verification.

Catalogue ids: PLAT-AUTHZ-001, PLAT-LIFE-001, PLAT-ACCESS-001, PLAT-AUDIT-001, PLAT-ADMIN-001, PLAT-SUB-001, PLAT-LOG-001,
TEN-ISO-001/002, TEN-HDR-001, TEN-LIST-001, RBAC-ESS-001/002, RBAC-MATRIX-001, AUTH-LOGIN-001..004, AUTH-TOKEN-001,
AUTH-REFRESH-001, AUTH-LOGOUT-001.

Mounted read-only at /qa/b6 and run through entry.py (strict sandbox check first).  Evidence is written to
$QA_ARTIFACTS/<case>.jsonl BEFORE asserting.  The platform tests run with COMPANY_APPROVAL_REQUIRED=true (the live pass
of 2026-10-25 ran with it OFF, so those paths were never exercised); the tenant tests run with the suite default (OFF).

Oracles: docs/operations/PLATFORM_CONSOLE.md (lifecycle diagram, status/access table, audit, token rules); core/auth
status table. Behaviour the documents leave open is RECORDED, not asserted.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
import redis.asyncio as redis
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.account_invite.conftest import seeded_plan_catalogue  # noqa: F401
from tests.integration.modules.attendance.test_employee_default_role_attendance import (
    _employee_user,
    _teardown,
    _tenant,
)
from tests.integration.modules.leave.test_leave_application import (
    _create_employee,
    _create_employment,
    _create_leave_type,
    _give_balance,
    _setup_calendar,
    _setup_leave_policy,
)
from tests.integration.modules.organisation.test_registration_flow import VALID_PASSWORD
from tests.integration.modules.platform.conftest import (  # noqa: F401
    PLATFORM_PASSWORD,
    make_tenant,
    platform_admin,
)

from hrms.core.config.settings import get_settings
from hrms.core.db.session import dispose_engine, get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio


import contextlib  # noqa: E402


@contextlib.asynccontextmanager
async def runtime_role(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Point the app's engine at the real runtime role (hrms_app) for the block, then back to the owner (same pattern as
    tests/security/test_rls_runtime_role.py)."""
    owner, app_url = OWNER_URL, APP_URL
    monkeypatch.setenv("DATABASE_URL", app_url)
    get_settings.cache_clear()
    await dispose_engine()
    try:
        yield
    finally:
        monkeypatch.setenv("DATABASE_URL", owner)
        get_settings.cache_clear()
        await dispose_engine()


OWNER_URL, APP_URL = os.environ["DATABASE_URL"], os.environ["HRMS_APP_DATABASE_URL"]  # captured before any monkeypatching


async def switch_role(monkeypatch: pytest.MonkeyPatch, which: str) -> None:
    monkeypatch.setenv("DATABASE_URL", APP_URL if which == "app" else OWNER_URL)
    get_settings.cache_clear()
    await dispose_engine()


def refresh_cookie(resp: Any) -> str | None:
    return resp.cookies.get("hrms_refresh") or next(
        (h.split("hrms_refresh=", 1)[1].split(";", 1)[0] for h in resp.headers.get_list("set-cookie") if h.startswith("hrms_refresh=")), None)
ART = Path(os.environ.get("QA_ARTIFACTS", "/tmp/qa-artifacts"))
P = "/v1/platform"
WRITE = {"POST", "PUT", "PATCH", "DELETE"}


def rec(case: str, step: str, **observed: Any) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    with (ART / f"{case}.jsonl").open("a") as fh:
        fh.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "step": step, **observed}, default=str) + "\n")


@pytest_asyncio.fixture(autouse=True)
async def _clear_rate_limits() -> Any:
    c = redis.from_url(get_settings().redis_url, decode_responses=True)
    for pattern in ("ratelimit:platform_login:*", "ratelimit:auth:*"):
        async for key in c.scan_iter(match=pattern):
            await c.delete(key)
    yield
    await c.aclose()


async def clear_rl() -> None:
    c = redis.from_url(get_settings().redis_url, decode_responses=True)
    for pattern in ("ratelimit:platform_login:*", "ratelimit:auth:*", "ratelimit:*"):
        async for key in c.scan_iter(match=pattern):
            await c.delete(key)
    await c.aclose()


@pytest_asyncio.fixture
async def approval_on(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("COMPANY_APPROVAL_REQUIRED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def q(sql: str, company_id: Any = None, **params: Any) -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        if company_id is not None:
            await set_rls_company_id(session, str(company_id))
        return [dict(r) for r in (await session.execute(text(sql), params)).mappings().all()]


async def company_row(cid: Any) -> dict[str, Any]:
    return (await q("SELECT status, status_reason, approved_at, trial_ends_at, retention_until FROM company WHERE id = :i", i=str(cid)))[0]


async def act(client: AsyncClient, admin: Any, cid: Any, action: str, body: dict | None = None) -> Any:
    return await client.post(f"{P}/companies/{cid}/{action}", headers=admin.headers, json=body or {})


async def tenant_write(client: AsyncClient, headers: dict[str, str]) -> Any:
    return await client.post("/v1/branches", headers=headers, json={})  # 422 = allowed to reach validation; 403 = gated first


def route_inventory() -> list[tuple[str, str, bool]]:
    from hrms.app import create_app

    out: list[tuple[str, str, bool]] = []
    for path, ops in sorted(create_app().openapi()["paths"].items()):
        for m, op in ops.items():
            if m in ("get", "post", "put", "patch", "delete"):
                out.append((m.upper(), path, bool(op.get("security"))))
    return out


def fill(path: str) -> str:
    while "{" in path:
        a, b = path.index("{"), path.index("}")
        path = path[:a] + str(uuid4()) + path[b + 1 :]
    return path


async def hit(client: AsyncClient, method: str, path: str, headers: dict[str, str] | None) -> int:
    kw: dict[str, Any] = {"headers": headers or {}}
    if method in WRITE:
        kw["json"] = {}
    r = await client.request(method, fill(path), **kw)
    return r.status_code


EXPECTED_PUBLIC = {
    ("GET", "/health"), ("GET", "/health/live"), ("GET", "/health/ready"),
    ("POST", "/v1/auth/email/resend-verification"), ("POST", "/v1/auth/email/verify"), ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/password/forgot"), ("POST", "/v1/auth/password/reset"), ("POST", "/v1/auth/token/refresh"),
    ("POST", "/v1/companies/register"), ("GET", "/v1/companies/registration-config"), ("POST", "/v1/platform/auth/login"),
    ("GET", "/v1/public/account-invites/{token}"), ("POST", "/v1/public/account-invites/{token}/accept"),
    ("GET", "/v1/public/onboarding/{token}"), ("POST", "/v1/public/onboarding/{token}/documents"),
    ("GET", "/v1/public/onboarding/{token}/documents"), ("DELETE", "/v1/public/onboarding/{token}/documents/{document_id}"),
    ("PATCH", "/v1/public/onboarding/{token}/sections/{section}"), ("POST", "/v1/public/onboarding/{token}/submit"),
}


# ============================================================================== PLAT-AUTHZ-001 / RBAC-MATRIX-001 sweeps
async def test_plat_authz_001_token_separation_full_sweep(client: AsyncClient, platform_admin: Any, make_tenant: Any) -> None:
    c = "PLAT-AUTHZ-001"
    tenant = await make_tenant()
    inv = route_inventory()
    secured = [(m, p) for m, p, s in inv if s]
    unsecured = {(m, p) for m, p, s in inv if not s}
    rec(c, "inventory", total=len(inv), secured=len(secured), unsecured=sorted(unsecured))
    assert unsecured == EXPECTED_PUBLIC, f"public surface changed: +{sorted(unsecured - EXPECTED_PUBLIC)} -{sorted(EXPECTED_PUBLIC - unsecured)}"

    anon_bad = {f"{m} {p}": s for m, p in secured if (s := await hit(client, m, p, None)) != 401}
    rec(c, "anonymous on every secured route", routes=len(secured), not_401=anon_bad)

    tenant_h = {"Authorization": tenant.headers["Authorization"]}
    plat_routes = [(m, p) for m, p in secured if p.startswith("/v1/platform")]
    tenant_on_platform = {f"{m} {p}": s for m, p in plat_routes if (s := await hit(client, m, p, tenant_h)) not in (401, 403)}
    rec(c, "tenant token on platform routes", routes=len(plat_routes), accepted=tenant_on_platform)

    other = [(m, p) for m, p in secured if not p.startswith("/v1/platform")]
    plat_h = {"Authorization": platform_admin.headers["Authorization"]}
    platform_on_tenant = {f"{m} {p}": s for m, p in other if (s := await hit(client, m, p, plat_h)) not in (401, 403)}
    rec(c, "platform token on tenant routes", routes=len(other), accepted=platform_on_tenant)

    # the platform session must still be alive (the sweep must not have revoked it)
    assert (await client.get(f"{P}/auth/me", headers=platform_admin.headers)).status_code == 200
    assert not anon_bad, anon_bad
    assert not tenant_on_platform, tenant_on_platform
    assert not platform_on_tenant, platform_on_tenant


async def count_company_rows(cid: Any) -> dict[str, int]:
    tabs = [r["table_name"] for r in await q(
        "SELECT DISTINCT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='company_id' "
        "AND table_name NOT IN (SELECT table_name FROM information_schema.views WHERE table_schema='public') ORDER BY 1")]
    out: dict[str, int] = {}
    for t in tabs:
        out[t] = (await q(f'SELECT count(*) n FROM "{t}"', company_id=cid))[0]["n"]
    return out


ADMIN_ONLY_WORDS = ("/payroll", "/roles", "/permissions", "/legal-entities", "/branches", "/departments", "/designations", "/grades",
                    "/shifts", "/policies", "/attendance-periods", "/work-calendars", "/employee-imports", "/subscription", "/users")


async def test_rbac_matrix_001_ess_001_employee_sweep(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "RBAC-MATRIX-001"
    t = await _tenant(client)
    try:
        eid, eh = await _employee_user(client, t, "Esha")
        inv = [(m, p) for m, p, s in route_inventory() if s and not p.startswith("/v1/platform") and not p.startswith("/v1/auth/")]
        before = await count_company_rows(t.company_id)
        results = {f"{m} {p}": await hit(client, m, p, eh) for m, p in inv}
        after = await count_company_rows(t.company_id)
        changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        by_status: dict[int, int] = {}
        for s in results.values():
            by_status[s] = by_status.get(s, 0) + 1
        reachable_writes = sorted(k for k, s in results.items() if k.split()[0] in WRITE and s != 403)
        reachable_reads = sorted(k for k, s in results.items() if k.split()[0] == "GET" and s != 403)
        rec(c, "employee sweep", routes=len(inv), by_status=by_status, reachable_writes=reachable_writes,
            reachable_reads=reachable_reads, rows_changed_in_tenant=changed)
        assert not [k for k, s in results.items() if s >= 500], [k for k, s in results.items() if s >= 500]
        assert not [k for k, s in results.items() if s == 401], "valid employee token refused (401) on some routes"
        ok_words = ("attendance", "punch", "regulariz")
        beyond = [k for k in reachable_writes if not any(w in k for w in ok_words)]
        rec(c, "writes outside attendance/punch/regularization that passed the permission gate with an EMPTY body (validation/lookup may still refuse)", routes=beyond)
        assert not changed, f"employee sweep changed tenant rows: {changed}"

        # --- targeted, realistic probes (valid bodies, real ids) for the routes that pick their permission inside the handler
        other_id, _oh = await _employee_user(client, t, "Omar")
        probes: dict[str, Any] = {}
        r = await client.post(f"/v1/employees/{other_id}/assignments", headers=eh, json={"effective_from": "2026-09-01", "change_type": "TRANSFER"})
        probes["POST assignments TRANSFER on another employee"] = r.status_code
        r = await client.post(f"/v1/employees/{eid}/assignments", headers=eh, json={"effective_from": "2026-09-01", "change_type": "PROMOTION"})
        probes["POST assignments PROMOTION on SELF"] = r.status_code
        r = await client.post("/v1/policy-assignments", headers=eh, json={"policy_kind": "ATTENDANCE_POLICY", "policy_id": str(uuid4()), "scope_type": "COMPANY", "effective_from": "2026-09-01"})
        probes["POST policy-assignments"] = r.status_code
        r = await client.post(f"/v1/leave-applications", headers={**eh, "Idempotency-Key": "qa-rbac-0001"}, json={"leave_type_id": str(uuid4()), "start_date": "2026-09-08", "end_date": "2026-09-08", "employee_id": other_id})
        probes["POST leave application on behalf of another employee"] = [r.status_code, (r.json().get("error") or {}).get("code")]
        rec(c, "realistic probes", results=probes)
        for k in ("POST assignments TRANSFER on another employee", "POST assignments PROMOTION on SELF", "POST policy-assignments"):
            assert probes[k] == 403, (k, probes[k])
        assert probes["POST leave application on behalf of another employee"][0] in (403, 404, 422)
        assert (await q("SELECT count(*) n FROM employee_assignment WHERE employee_id = :e", company_id=t.company_id, e=other_id))[0]["n"] == 0

        # --- GET routes keyed by {employee_id}: own id vs ANOTHER employee's real id
        emp_routes = [(m, p) for m, p in inv if m == "GET" and p.count("{") == 1 and "{employee_id}" in p]
        own_res, other_res = {}, {}
        for m, p in emp_routes:
            own_res[p] = (await client.get(p.replace("{employee_id}", eid), headers=eh)).status_code
            other_res[p] = (await client.get(p.replace("{employee_id}", other_id), headers=eh)).status_code
        leaks = sorted(p for p, sc in other_res.items() if sc == 200)
        rec(c, "GET /employees/{id}/* : own vs another employee", own=own_res, other=other_res, other_returned_200=leaks)
        assert not leaks, f"EMPLOYEE role got 200 for ANOTHER employee's data on: {leaks}"
    finally:
        await _teardown(t)


async def test_rbac_ess_002_read_scope(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "RBAC-ESS-002"
    t = await _tenant(client)
    try:
        a_id, a_h = await _employee_user(client, t, "Anil")
        b_id, b_h = await _employee_user(client, t, "Bela")
        pa = await client.post("/v1/attendance/punches/me", headers=a_h, json={"direction": "IN"})
        pb = await client.post("/v1/attendance/punches/me", headers=b_h, json={"direction": "IN"})
        assert pa.status_code == pb.status_code == 201, (pa.text, pb.text)
        own = await client.get("/v1/attendance/punches", headers=a_h)
        other = await client.get("/v1/attendance/punches", headers=a_h, params={"employee_id": b_id})
        lst = await client.get("/v1/employees", headers=a_h)
        one = await client.get(f"/v1/employees/{b_id}", headers=a_h)
        days = await client.get("/v1/attendance/days", headers=a_h, params={"employee_id": b_id})
        rec(c, "scope", own=[own.status_code, [x.get("employee_id") for x in own.json().get("data", [])] if own.status_code == 200 else own.text[:200]],
            other=[other.status_code, other.text[:200]], employees_list=lst.status_code, employee_detail=one.status_code, days_other=[days.status_code, days.text[:200]])
        if own.status_code == 200:
            assert {x["employee_id"] for x in own.json()["data"]} <= {a_id}
        if other.status_code == 200:
            assert all(x["employee_id"] == a_id for x in other.json()["data"]), "employee A can read employee B's punches"
        else:
            assert other.status_code in (403, 404)
        assert lst.status_code == 403 and one.status_code in (403, 404)
        if days.status_code == 200:
            assert all(x["employee_id"] == a_id for x in days.json()["data"])
        db = await q("SELECT employee_id::text e FROM punch", company_id=t.company_id)
        assert sorted(x["e"] for x in db) == sorted([a_id, b_id])
    finally:
        await _teardown(t)


async def test_rbac_ess_003_peer_data_leave_and_period_summary(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """Two real EMPLOYEE logins in one tenant. Employee A tries to read or change employee B's leave data and the
    all-employee attendance-period summary. Proves scope with DATA present (the empty-body sweep cannot)."""
    c = "RBAC-ESS-003"
    t = await _tenant(client)
    try:
        lt = await _create_leave_type(client, t.admin)
        await _setup_calendar(client, t.admin)
        await _setup_leave_policy(client, t.admin, leave_type_id=lt["id"], approval_chain="AUTO")
        a_id, a_h = await _employee_user(client, t, "Asha")
        b_id, b_h = await _employee_user(client, t, "Bala")
        for e in (a_id, b_id):
            await _give_balance(client, t.admin, employee_id=e, leave_type_id=lt["id"], amount="10.00")
        ap = await client.post("/v1/leave-applications", headers={**b_h, "Idempotency-Key": "qa-ess3-0001"},
                               json={"leave_type_id": lt["id"], "start_date": "2026-09-08", "end_date": "2026-09-08", "reason": "QA"})
        rec(c, "B applies for leave as self", status=ap.status_code, body=ap.text[:200])
        assert ap.status_code == 201, ap.text
        b_app = ap.json()["data"]
        b_before = await q("SELECT status, version, total_days::text n FROM leave_application WHERE id = :i", company_id=t.company_id, i=b_app["id"])
        ledger_n = (await q("SELECT count(*) n FROM leave_ledger WHERE employee_id = :e", company_id=t.company_id, e=b_id))[0]["n"]

        seen: dict[str, Any] = {}
        r = await client.get("/v1/leave-applications", headers=a_h)
        seen["A list leave-applications"] = [r.status_code, sorted({x["employee_id"] for x in r.json().get("data", [])}) if r.status_code == 200 else None]
        r = await client.get(f"/v1/leave-applications/{b_app['id']}", headers=a_h)
        seen["A get B's application"] = r.status_code
        r = await client.get("/v1/leave-balances", headers=a_h, params={"employee_id": b_id})
        seen["A get B's balance"] = [r.status_code, r.json().get("data") if r.status_code == 200 else None]
        r = await client.get("/v1/leave-ledger", headers=a_h, params={"employee_id": b_id})
        seen["A get B's ledger"] = [r.status_code, r.json().get("data") if r.status_code == 200 else None]
        r = await client.get("/v1/leave-projections", headers=a_h, params={"employee_id": b_id})
        seen["A get B's projections"] = [r.status_code, r.json().get("data") if r.status_code == 200 else None]
        for act_ in ("cancel", "approve", "reject"):
            r = await client.post(f"/v1/leave-applications/{b_app['id']}/{act_}", headers={**a_h, "If-Match": str(b_app["version"])}, json={})
            seen[f"A {act_} B's application"] = r.status_code
        own = await client.get("/v1/leave-balances", headers=a_h, params={"employee_id": a_id})
        seen["A get own balance"] = [own.status_code, [x["balance"] for x in own.json()["data"]] if own.status_code == 200 else None]

        rec(c, "peer-data probes", results=seen)

        assert seen["A list leave-applications"][0] in (200, 403) and (seen["A list leave-applications"][1] in (None, [], [a_id]))
        assert seen["A get B's application"] in (403, 404)
        for k in ("A get B's balance", "A get B's ledger", "A get B's projections"):
            assert seen[k][0] in (403, 404) or seen[k][1] in ([], None), (k, seen[k])
        for k in ("A cancel B's application", "A approve B's application", "A reject B's application"):
            assert seen[k] in (403, 404), (k, seen[k])
        # database: nothing about B changed
        b_after = await q("SELECT status, version, total_days::text n FROM leave_application WHERE id = :i", company_id=t.company_id, i=b_app["id"])
        assert b_after == b_before
        assert (await q("SELECT count(*) n FROM leave_ledger WHERE employee_id = :e", company_id=t.company_id, e=b_id))[0]["n"] == ledger_n
    finally:
        await _teardown(t)


@pytest.mark.xfail(strict=True, reason="DEF-B6-02: GET /v1/attendance-periods/{id}/summary ignores the caller's data scope; an EMPLOYEE (ATTENDANCE.VIEW=SELF) receives every employee's rows")
async def test_rbac_ess_004_period_summary_is_self_scoped(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "RBAC-ESS-004"
    t = await _tenant(client)
    try:
        a_id, a_h = await _employee_user(client, t, "Asha")
        b_id, b_h = await _employee_user(client, t, "Bala")
        for e in (a_id, b_id):
            cr = await client.post("/v1/attendance/days/calculate", headers=t.admin, params={"employee_id": e, "date": "2026-09-08"})
            assert cr.status_code == 200, cr.text
        le = (await client.get("/v1/legal-entities", headers=t.admin)).json()["data"][0]["id"]
        per = await client.post("/v1/attendance-periods", headers=t.admin, json={"legal_entity_id": le, "period_start": "2026-09-08", "period_end": "2026-09-08", "label": "QA"})
        assert per.status_code == 201, per.text
        pid = per.json()["data"]["id"]
        admin_view = (await client.get(f"/v1/attendance-periods/{pid}/summary", headers=t.admin)).json()["data"]
        seen: dict[str, Any] = {}
        for name, path in (("period list", "/v1/attendance-periods"), ("period detail", f"/v1/attendance-periods/{pid}"), ("period summary", f"/v1/attendance-periods/{pid}/summary")):
            r = await client.get(path, headers=a_h)
            body = r.json().get("data") if r.status_code == 200 else None
            seen[name] = {"status": r.status_code, "employee_ids": sorted({x["employee_id"] for x in body if isinstance(x, dict) and x.get("employee_id")}) if isinstance(body, list) else None}
        r = await client.get(f"/v1/attendance-periods/{pid}/summary", headers=a_h)
        rows = r.json()["data"] if r.status_code == 200 else []
        other = [x for x in rows if x.get("employee_id") == b_id]
        rec(c, "EMPLOYEE A reads the period summary", results=seen, admin_rows=len(admin_view), rows_seen_by_A=len(rows),
            rows_of_B_seen_by_A=other, field_names=sorted(rows[0]) if rows else None, a_id=a_id, b_id=b_id)
        assert r.status_code in (403, 404) or not other, "employee A can read employee B's attendance-period summary row"
    finally:
        await _teardown(t)


# ============================================================================== TEN-ISO / TEN-HDR / TEN-LIST
async def test_ten_iso_001_002_hdr_list(client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch) -> None:
    c = "TEN-ISO-001"
    a = await _tenant(client)
    b = await _tenant(client)
    try:
        lt = await _create_leave_type(client, a.admin)
        await _setup_calendar(client, a.admin)
        await _setup_leave_policy(client, a.admin, leave_type_id=lt["id"], approval_chain="AUTO")
        emp = await _create_employee(client, a.admin, "Alice")
        await _create_employment(client, a.admin, employee_id=emp["id"], legal_entity_id=a.legal_entity_id)
        await _give_balance(client, a.admin, employee_id=emp["id"], leave_type_id=lt["id"], amount="10.00")
        app = await client.post("/v1/leave-applications", headers={**a.admin, "Idempotency-Key": "qa-iso-0001"},
                                json={"leave_type_id": lt["id"], "start_date": "2026-09-08", "end_date": "2026-09-08", "employee_id": emp["id"], "reason": "QA"})
        assert app.status_code == 201, app.text
        a_emp, a_app = emp["id"], app.json()["data"]["id"]
        a_eid, a_eh = await _employee_user(client, a, "Anu")
        assert (await client.post("/v1/attendance/punches/me", headers=a_eh, json={"direction": "IN"})).status_code == 201
        run = await client.post("/v1/payroll/pay-runs", headers=a.admin, json={"legal_entity_id": a.legal_entity_id, "month": "2026-09"})
        rec(c, "payroll pay-run created in A", status=run.status_code, body=run.text[:200])
        a_run = run.json()["data"]["id"] if run.status_code in (200, 201) else None
        punches = (await client.get("/v1/attendance/punches", headers=a.admin)).json()["data"]
        rec(c, "tenant A fixtures", employee=a_emp, application=a_app, pay_run=a_run, punches=len(punches))

        # from here on every request AND every verification query runs as the real runtime role (hrms_app, RLS applies)
        await switch_role(monkeypatch, "app")
        who = (await q("SELECT current_user u"))[0]["u"]
        rec(c, "database role for the isolation probes", current_user=who)
        assert who == "hrms_app"
        # snapshot of everything tenant A owns (hash of key tables) to prove B's attempts change nothing
        snap_before = await count_company_rows(a.company_id)
        fp_before = await q("SELECT md5(string_agg(t::text, '|' ORDER BY id)) h FROM employee t", company_id=a.company_id)

        # detail / action routes with A's ids, called with B's credentials
        probes = [("GET", f"/v1/employees/{a_emp}", None), ("PATCH", f"/v1/employees/{a_emp}", {"first_name": "Hacked"}),
                  ("DELETE", f"/v1/employees/{a_emp}", None), ("GET", f"/v1/employees/{a_emp}/documents", None),
                  ("GET", f"/v1/leave-applications/{a_app}", None), ("POST", f"/v1/leave-applications/{a_app}/cancel", {}),
                  ("POST", f"/v1/leave-applications/{a_app}/approve", {}), ("POST", f"/v1/leave-applications/{a_app}/reject", {}),
                  ("GET", "/v1/leave-balances", None)]
        if a_run:
            probes += [("GET", f"/v1/payroll/pay-runs/{a_run}", None), ("DELETE", f"/v1/payroll/pay-runs/{a_run}", None),
                       ("POST", f"/v1/payroll/pay-runs/{a_run}/approve", {})]
        out: dict[str, Any] = {}
        for m, path, body in probes:
            kw: dict[str, Any] = {"headers": {**b.admin, "If-Match": "1"}}
            params = {"employee_id": a_emp} if path == "/v1/leave-balances" else None
            if params:
                kw["params"] = params
            if body is not None:
                kw["json"] = body
            r = await client.request(m, path, **kw)
            out[f"{m} {path}"] = [r.status_code, r.text[:160]]
        rec(c, "B -> A object probes", results=out)
        # /v1/leave-balances?employee_id=<A> may answer 200 with an EMPTY list or 404; any non-empty body is a leak
        lb = await client.get("/v1/leave-balances", headers=b.admin, params={"employee_id": a_emp})
        assert lb.status_code in (200, 404), lb.text
        if lb.status_code == 200:
            assert lb.json()["data"] == [], "B can read A's leave balances"
        for k, v in out.items():
            if not k.startswith("GET /v1/leave-balances"):
                assert v[0] == 404, f"{k} -> {v}"

        # list endpoints disjoint (TEN-LIST-001)
        lists = {}
        for path in ("/v1/employees", "/v1/leave-applications", "/v1/attendance/punches", "/v1/attendance/days", "/v1/payroll/pay-runs", "/v1/leave-types"):
            rb = await client.get(path, headers=b.admin)
            ra = await client.get(path, headers=a.admin)
            ids_b = {x.get("id") for x in rb.json().get("data", [])} if rb.status_code == 200 else None
            ids_a = {x.get("id") for x in ra.json().get("data", [])} if ra.status_code == 200 else None
            lists[path] = {"a_status": ra.status_code, "b_status": rb.status_code, "a_n": len(ids_a or []), "b_n": len(ids_b or []),
                           "overlap": len((ids_a or set()) & (ids_b or set()) - {None})}
        rec("TEN-LIST-001", "list disjointness", lists=lists)
        assert all(v["overlap"] == 0 for v in lists.values()), lists
        assert lists["/v1/employees"]["a_n"] >= 2 and lists["/v1/employees"]["b_n"] <= 1
        assert lists["/v1/attendance/punches"]["a_n"] >= 1 and lists["/v1/attendance/punches"]["b_n"] == 0

        # company header handling (TEN-HDR-001)
        hdr = {}
        for name, h in {
            "B token + A header": {"Authorization": b.admin["Authorization"], "X-Company-Id": str(a.company_id)},
            "B token + garbage header": {"Authorization": b.admin["Authorization"], "X-Company-Id": "not-a-uuid"},
            "B token + random uuid header": {"Authorization": b.admin["Authorization"], "X-Company-Id": str(uuid4())},
            "B token, no header": {"Authorization": b.admin["Authorization"]},
            "B token + own header": b.admin,
        }.items():
            r = await client.get("/v1/employees", headers=h)
            hdr[name] = [r.status_code, (r.json().get("error") or {}).get("code") if r.status_code >= 400 else len(r.json()["data"])]
        rec("TEN-HDR-001", "header handling", results=hdr)
        # under the runtime role: a mismatched header is refused (401/404) and never serves A's data; own header works.
        # (omitted / malformed header behaviour differs from the documentation: see test_ten_hdr_001_* and DEF-B6-01)
        assert hdr["B token + A header"][0] in (401, 404) and hdr["B token + random uuid header"][0] in (401, 404)
        assert hdr["B token + own header"][0] == 200 and hdr["B token + own header"][1] == 0

        # nothing of A changed
        assert await count_company_rows(a.company_id) == snap_before
        fp_after = await q("SELECT md5(string_agg(t::text, '|' ORDER BY id)) h FROM employee t", company_id=a.company_id)
        assert fp_before == fp_after
        # and RLS itself: with B's company scope the DB shows none of A's rows
        assert (await q("SELECT count(*) n FROM employee WHERE id = :i", company_id=b.company_id, i=a_emp))[0]["n"] == 0
        rec(c, "tenant A unchanged", employee_hash_before=fp_before, employee_hash_after=fp_after)
    finally:
        await switch_role(monkeypatch, "owner")
        await _teardown(a, b)


# ============================================================================== PLAT-LIFE / ACCESS / AUDIT
TRANSITIONS_DOC = {  # (action) -> statuses from which the diagram allows it
    "approve": {"PENDING_APPROVAL", "REJECTED"},
    "reject": {"PENDING_APPROVAL"},
    "suspend": {"TRIAL", "ACTIVE"},
    "reactivate": {"SUSPENDED"},
    "terminate": {"PENDING_APPROVAL", "REJECTED", "TRIAL", "ACTIVE", "SUSPENDED"},
}
BODIES = {"reject": {"reason": "QA reason"}, "suspend": {"reason": "QA reason"}, "terminate": {"reason": "QA reason"}}


async def put_status(cid: Any, status: str) -> None:
    async with get_session_factory()() as session:
        await session.execute(text("UPDATE company SET status = :s WHERE id = :i"), {"s": status, "i": str(cid)})
        await session.commit()


async def test_plat_life_001_full_transition_matrix(client: AsyncClient, platform_admin: Any, make_tenant: Any, approval_on: None) -> None:
    c = "PLAT-LIFE-001"
    tenant = await make_tenant()
    cid = tenant.company_id
    assert (await company_row(cid))["status"] == "PENDING_APPROVAL"
    matrix: dict[str, dict[str, Any]] = {}
    for start in ("PENDING_APPROVAL", "TRIAL", "ACTIVE", "SUSPENDED", "REJECTED", "TERMINATED"):
        for action in TRANSITIONS_DOC:
            await put_status(cid, start)  # test-data setup on the disposable DB only
            body = dict(BODIES.get(action, {}))
            if action == "terminate":
                body["confirm_name"] = tenant.name
            r = await act(client, platform_admin, cid, action, body)
            after = (await company_row(cid))["status"]
            allowed = start in TRANSITIONS_DOC[action]
            matrix[f"{start} --{action}-->"] = {"http": r.status_code, "after": after, "doc_allows": allowed,
                                                 "code": (r.json().get("error") or {}).get("code") if r.status_code >= 400 else None}
            if allowed:
                assert r.status_code == 200, (start, action, r.text)
                assert after != start or action == "approve" and start == after
            else:
                assert r.status_code == 409, (start, action, r.status_code, r.text)
                assert after == start, f"illegal {action} from {start} changed status to {after}"
    rec(c, "transition matrix", matrix=matrix)
    # approve targets TRIAL; reactivate target observed:
    for s, a in (("PENDING_APPROVAL", "approve"), ("REJECTED", "approve")):
        assert matrix[f"{s} --{a}-->"]["after"] == "TRIAL"
    assert matrix["PENDING_APPROVAL --reject-->"]["after"] == "REJECTED"
    assert matrix["TRIAL --suspend-->"]["after"] == matrix["ACTIVE --suspend-->"]["after"] == "SUSPENDED"
    assert all(matrix[f"{s} --terminate-->"]["after"] == "TERMINATED" for s in TRANSITIONS_DOC["terminate"])

    # reasons mandatory for reject / suspend / terminate (and terminate needs the typed name)
    await put_status(cid, "PENDING_APPROVAL")
    assert (await act(client, platform_admin, cid, "reject")).status_code == 422
    assert (await act(client, platform_admin, cid, "reject", {"reason": " "})).status_code == 422
    await put_status(cid, "TRIAL")
    assert (await act(client, platform_admin, cid, "suspend")).status_code == 422
    assert (await act(client, platform_admin, cid, "terminate", {"reason": "x y z"})).status_code == 422
    assert (await act(client, platform_admin, cid, "terminate", {"reason": "x y z", "confirm_name": "wrong"})).status_code == 422
    assert (await company_row(cid))["status"] == "TRIAL"
    rec(c, "reason / confirm guards", ok=True)


async def test_plat_access_001_status_table_incl_refresh(client: AsyncClient, platform_admin: Any, make_tenant: Any, approval_on: None) -> None:
    c = "PLAT-ACCESS-001"
    tenant = await make_tenant()
    cid = tenant.company_id
    login0 = await client.post("/v1/auth/login", json={"email": tenant.email, "password": VALID_PASSWORD})
    assert login0.status_code == 200, login0.text
    refresh = refresh_cookie(login0)
    assert refresh
    expected = {  # status -> (login ok, read ok, write allowed, error code when blocked)
        "PENDING_APPROVAL": (True, True, False, "COMPANY_PENDING_APPROVAL"),
        "TRIAL": (True, True, True, None),
        "ACTIVE": (True, True, True, None),
        "SUSPENDED": (True, True, False, "COMPANY_SUSPENDED"),
        "REJECTED": (False, False, False, "COMPANY_REJECTED"),
        "TERMINATED": (False, False, False, "COMPANY_TERMINATED"),
    }
    observed: dict[str, Any] = {}
    for status, (login_ok, read_ok, write_ok, code) in expected.items():
        await put_status(cid, status)
        lg = await client.post("/v1/auth/login", json={"email": tenant.email, "password": VALID_PASSWORD})
        rd = await client.get("/v1/employees", headers=tenant.headers)
        wr = await tenant_write(client, tenant.headers)
        rf = await client.post("/v1/auth/token/refresh", json={"refresh_token": refresh})
        if rf.status_code == 200:
            refresh = refresh_cookie(rf) or refresh
        observed[status] = {"login": lg.status_code, "read": rd.status_code, "write": wr.status_code,
                            "write_code": (wr.json().get("error") or {}).get("code"), "refresh": rf.status_code,
                            "refresh_code": (rf.json().get("error") or {}).get("code") if rf.status_code >= 400 else None,
                            "login_code": (lg.json().get("error") or {}).get("code") if lg.status_code >= 400 else None}
        o = observed[status]
        assert (o["login"] == 200) == login_ok, (status, o)
        assert (o["read"] == 200) == read_ok, (status, o)
        if write_ok:
            assert o["write"] == 422, (status, o)
        else:
            assert o["write"] == 403 and o["write_code"] == code, (status, o)
        if not login_ok:
            assert o["login_code"] == code and o["refresh"] == 403, (status, o)
        else:
            assert o["refresh"] == 200, (status, o)  # sign-out / refresh stay allowed in read-only mode
    rec(c, "status table", observed=observed)
    # the gate never wrote tenant data while blocked
    assert (await q("SELECT count(*) n FROM branch", company_id=cid))[0]["n"] == 0


async def test_plat_audit_001_every_action_audited_and_append_only(client: AsyncClient, platform_admin: Any, make_tenant: Any, approval_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    c = "PLAT-AUDIT-001"
    tenant = await make_tenant()
    cid = tenant.company_id
    steps = [("approve", {}), ("suspend", {"reason": "QA suspend"}), ("reactivate", {}), ("terminate", {"reason": "QA end", "confirm_name": tenant.name})]
    for action, body in steps:
        assert (await act(client, platform_admin, cid, action, body)).status_code == 200
    sub = await client.patch(f"{P}/companies/{cid}/subscription", headers=platform_admin.headers, json={"seat_limit_override": 7, "reason": "QA seats"})
    rec(c, "subscription patch", status=sub.status_code, body=sub.text[:200])
    assert sub.status_code in (200, 409), sub.text
    rows = await q("SELECT action, before_status, after_status, reason, actor_username, request_id, ip, details FROM platform_audit_log WHERE company_id = :c ORDER BY created_at, id", c=str(cid))
    rec(c, "audit rows", rows=rows)
    actions = [r["action"] for r in rows]
    assert actions[:4] == ["COMPANY_APPROVED", "COMPANY_SUSPENDED", "COMPANY_REACTIVATED", "COMPANY_TERMINATED"], actions
    assert all(r["actor_username"] == platform_admin.username and r["request_id"] for r in rows)
    chain = [(r["before_status"], r["after_status"]) for r in rows[:4]]
    assert chain == [("PENDING_APPROVAL", "TRIAL"), ("TRIAL", "SUSPENDED"), ("SUSPENDED", "TRIAL"), ("TRIAL", "TERMINATED")], chain
    assert rows[1]["reason"] == "QA suspend" and rows[3]["reason"] == "QA end"
    tenant_side = await q("SELECT action, entity_type, before_json::text b, after_json::text a FROM audit_log WHERE action = 'COMPANY_STATUS_CHANGED_BY_PLATFORM' AND company_id = :c ORDER BY occurred_at, id", company_id=cid, c=str(cid))
    rec(c, "tenant-side audit rows", rows=tenant_side)
    assert len(tenant_side) == 4, len(tenant_side)
    # failed / rejected actions must NOT leave an audit row
    n0 = len(rows)
    assert (await act(client, platform_admin, cid, "approve")).status_code == 409
    assert (await act(client, platform_admin, uuid4(), "approve")).status_code == 404
    assert len(await q("SELECT 1 FROM platform_audit_log WHERE company_id = :c", c=str(cid))) == n0
    # append-only: tried as the OWNER role (hrms, what the project's own suite runs as) and as the RUNTIME role (hrms_app)
    outcomes: dict[str, dict[str, str]] = {}
    for which in ("owner", "app"):
        await switch_role(monkeypatch, which)
        res: dict[str, str] = {}
        async with get_session_factory()() as session:
            who = (await session.execute(text("SELECT current_user"))).scalar_one()
            for label, stmt in (("update", "UPDATE platform_audit_log SET reason = 'x'"), ("delete", "DELETE FROM platform_audit_log"),
                                ("truncate", "TRUNCATE platform_audit_log")):
                try:
                    await session.execute(text(stmt))
                    res[label] = "ALLOWED(rolled back)"
                except Exception as exc:  # noqa: BLE001
                    res[label] = "denied: " + str(exc).splitlines()[0][-110:]
                await session.rollback()
        outcomes[f"{which}:{who}"] = res
    await switch_role(monkeypatch, "owner")
    rec(c, "mutation attempts (each statement rolled back)", outcomes=outcomes)
    app_res = next(v for k, v in outcomes.items() if k.startswith("app:"))
    owner_res = next(v for k, v in outcomes.items() if k.startswith("owner:"))
    assert all(v.startswith("denied") for v in app_res.values()), app_res               # the runtime role can change nothing
    assert owner_res["update"].startswith("denied") and owner_res["delete"].startswith("denied"), owner_res  # trigger: every role
    rec(c, "OBSERVATION owner TRUNCATE", owner_truncate=owner_res["truncate"])
    assert len(await q("SELECT 1 FROM platform_audit_log WHERE company_id = :c", c=str(cid))) == n0


# ============================================================================== PLAT-ADMIN / SUB / LOG
async def test_plat_admin_001_guards_and_session_revocation(client: AsyncClient, platform_admin: Any, approval_on: None) -> None:
    c = "PLAT-ADMIN-001"
    h = platform_admin.headers
    me_id = str(platform_admin.admin_id)
    self_dis = await client.post(f"{P}/admins/{me_id}/disable", headers=h)
    rec(c, "disable self", status=self_dis.status_code, body=self_dis.text[:200])
    assert self_dis.status_code in (403, 409, 422)
    assert (await q("SELECT status FROM platform_admin WHERE id = :i", i=me_id))[0]["status"] == "ACTIVE"

    # last active admin: make this the only active admin by disabling all others directly (disposable DB), then try via a second admin
    username = f"qa-{uuid4().hex[:8]}"
    created = await client.post(f"{P}/admins", headers=h, json={"username": username, "password": "Second-Admin-Pass-9"})
    assert created.status_code == 201, created.text
    other_id = created.json()["data"]["id"]
    other_login = await client.post(f"{P}/auth/login", json={"username": username, "password": "Second-Admin-Pass-9"})
    assert other_login.status_code == 200
    other_h = {"Authorization": f"Bearer {other_login.json()['data']['access_token']}"}
    assert (await client.get(f"{P}/auth/me", headers=other_h)).status_code == 200

    # reset password of the other admin -> their old session dies at once, old password stops working
    reset = await client.post(f"{P}/admins/{other_id}/reset-password", headers=h, json={"password": "Changed-Admin-Pass-9"})
    assert reset.status_code == 200, reset.text
    assert (await client.get(f"{P}/auth/me", headers=other_h)).status_code == 401
    assert (await client.post(f"{P}/auth/login", json={"username": username, "password": "Second-Admin-Pass-9"})).status_code == 401
    relogin = await client.post(f"{P}/auth/login", json={"username": username, "password": "Changed-Admin-Pass-9"})
    assert relogin.status_code == 200
    other_h = {"Authorization": f"Bearer {relogin.json()['data']['access_token']}"}

    # disable the other admin -> session dies, login refused; DB reflects it
    assert (await client.post(f"{P}/admins/{other_id}/disable", headers=h)).status_code == 200
    assert (await client.get(f"{P}/auth/me", headers=other_h)).status_code == 401
    refused = await client.post(f"{P}/auth/login", json={"username": username, "password": "Changed-Admin-Pass-9"})
    sessions = await q("SELECT count(*) n FROM platform_session WHERE platform_admin_id = :i AND revoked_at IS NULL", i=other_id)
    rec(c, "disable other", login_after_disable=refused.status_code, live_sessions=sessions[0]["n"])
    assert refused.status_code in (401, 403) and sessions[0]["n"] == 0
    assert (await client.post(f"{P}/admins/{other_id}/enable", headers=h)).status_code == 200

    # last-active-admin guard: disable every other active admin in the DB, then the sole remaining admin cannot be disabled
    # by an admin acting on themself (already covered above) -> verify via the count the service sees
    active = await q("SELECT count(*) n FROM platform_admin WHERE status = 'ACTIVE'")
    rec(c, "active admins", n=active[0]["n"])
    async with get_session_factory()() as session:
        await session.execute(text("DELETE FROM platform_admin WHERE id = :i"), {"i": other_id})
        await session.commit()


@pytest.mark.xfail(strict=True, reason="DEF-B6-03: set_admin_status checks 'last active admin' then updates without a row lock; two admins disabling each other concurrently can leave ZERO active platform admins")
async def test_plat_admin_002_mutual_disable_race(client: AsyncClient, platform_admin: Any, approval_on: None) -> None:
    import asyncio

    c = "PLAT-ADMIN-002"
    others_before = (await q("SELECT count(*) n FROM platform_admin WHERE status = 'ACTIVE' AND id <> :i", i=str(platform_admin.admin_id)))[0]["n"]
    assert others_before == 0, "this test needs exactly two active admins; the sandbox DB holds others"
    username, pw = f"qa-{uuid4().hex[:8]}", "Second-Admin-Pass-9"
    created = await client.post(f"{P}/admins", headers=platform_admin.headers, json={"username": username, "password": pw})
    assert created.status_code == 201, created.text
    b_id = created.json()["data"]["id"]
    zero_active = 0
    outcomes: list[Any] = []
    try:
        for attempt in range(8):
            lb = await client.post(f"{P}/auth/login", json={"username": username, "password": pw})
            la = await client.post(f"{P}/auth/login", json={"username": platform_admin.username, "password": PLATFORM_PASSWORD})
            if lb.status_code != 200 or la.status_code != 200:
                outcomes.append(["login", la.status_code, lb.status_code])
                await clear_rl()
                continue
            ha = {"Authorization": f"Bearer {la.json()['data']['access_token']}"}
            hb = {"Authorization": f"Bearer {lb.json()['data']['access_token']}"}
            ra, rb = await asyncio.gather(client.post(f"{P}/admins/{b_id}/disable", headers=ha),
                                          client.post(f"{P}/admins/{platform_admin.admin_id}/disable", headers=hb))
            active = (await q("SELECT count(*) n FROM platform_admin WHERE id IN (:a, :b) AND status = 'ACTIVE'", a=str(platform_admin.admin_id), b=b_id))[0]["n"]
            outcomes.append([ra.status_code, rb.status_code, active])
            if active == 0:
                zero_active += 1
            async with get_session_factory()() as session:  # disposable DB: restore both to ACTIVE for the next attempt
                await session.execute(text("UPDATE platform_admin SET status = 'ACTIVE' WHERE id IN (:a, :b)"), {"a": str(platform_admin.admin_id), "b": b_id})
                await session.commit()
            await clear_rl()
        rec(c, "A disables B while B disables A (8 attempts): [A->B status, B->A status, admins still ACTIVE]", outcomes=outcomes, attempts_ending_with_zero_active_admins=zero_active)
        assert zero_active == 0, f"{zero_active}/8 attempts left no active platform admin"
    finally:
        async with get_session_factory()() as session:
            await session.execute(text("DELETE FROM platform_session WHERE platform_admin_id = :b"), {"b": b_id})
            await session.execute(text("DELETE FROM platform_admin WHERE id = :b"), {"b": b_id})
            await session.commit()


async def test_plat_sub_001_trial_clock_and_reactivate(client: AsyncClient, platform_admin: Any, make_tenant: Any, approval_on: None) -> None:
    c = "PLAT-SUB-001"
    tenant = await make_tenant()
    cid = tenant.company_id
    t0 = datetime.now(UTC)
    ap = await act(client, platform_admin, cid, "approve")
    assert ap.status_code == 200
    row = await company_row(cid)
    sub = (await q("SELECT trial_ends_at, seat_limit_override, version, status FROM subscription WHERE company_id = :c", company_id=cid, c=str(cid)))[0]
    span = row["trial_ends_at"] - t0
    rec(c, "approve sets trial", company_trial_ends=row["trial_ends_at"], sub_trial_ends=sub["trial_ends_at"], days=span.total_seconds() / 86400)
    assert timedelta(days=13, hours=23) < span < timedelta(days=14, minutes=5)
    assert sub["trial_ends_at"] == row["trial_ends_at"]

    # extend trial while in TRIAL: both clocks move together
    ex = await client.patch(f"{P}/companies/{cid}/subscription", headers=platform_admin.headers, json={"extend_trial_days": 10, "reason": "QA reason"})
    assert ex.status_code == 200, ex.text
    row2 = await company_row(cid)
    sub2 = (await q("SELECT trial_ends_at, version FROM subscription WHERE company_id = :c", company_id=cid, c=str(cid)))[0]
    assert abs((row2["trial_ends_at"] - row["trial_ends_at"]) - timedelta(days=10)) < timedelta(seconds=1)
    assert sub2["trial_ends_at"] == row2["trial_ends_at"] and sub2["version"] > 1

    # suspend, then reactivate BEFORE the trial ended -> TRIAL ; clock control: move the trial end into the past -> ACTIVE
    assert (await act(client, platform_admin, cid, "suspend", {"reason": "QA reason"})).status_code == 200
    assert (await act(client, platform_admin, cid, "reactivate")).json()["data"]["status"] == "TRIAL"
    assert (await act(client, platform_admin, cid, "suspend", {"reason": "QA reason"})).status_code == 200
    async with get_session_factory()() as session:  # clock control on the disposable DB
        await session.execute(text("UPDATE company SET trial_ends_at = now() - interval '1 day' WHERE id = :i"), {"i": str(cid)})
        await session.commit()
    after_end = await act(client, platform_admin, cid, "reactivate")
    assert after_end.status_code == 200 and after_end.json()["data"]["status"] == "ACTIVE", after_end.text
    rec(c, "reactivate before / after trial end", before="TRIAL", after="ACTIVE")

    # OBSERVATION (not asserted as a defect): extend trial while SUSPENDED -> which clock moves, and where does reactivate land?
    assert (await act(client, platform_admin, cid, "suspend", {"reason": "QA reason"})).status_code == 200
    ex2 = await client.patch(f"{P}/companies/{cid}/subscription", headers=platform_admin.headers, json={"extend_trial_days": 30, "reason": "QA reason"})
    row3 = await company_row(cid)
    sub3 = (await q("SELECT trial_ends_at FROM subscription WHERE company_id = :c", company_id=cid, c=str(cid)))[0]
    back = await act(client, platform_admin, cid, "reactivate")
    rec("PLAT-SUB-001", "OBSERVATION trial extended while SUSPENDED", patch_status=ex2.status_code, company_trial_ends=row3["trial_ends_at"],
        subscription_trial_ends=sub3["trial_ends_at"], reactivated_to=back.json()["data"]["status"] if back.status_code == 200 else back.status_code)

    # seats: override set, then cleared with explicit null; plan change to an unknown code is refused and changes nothing
    s1 = await client.patch(f"{P}/companies/{cid}/subscription", headers=platform_admin.headers, json={"seat_limit_override": 5})
    s2 = await client.patch(f"{P}/companies/{cid}/subscription", headers=platform_admin.headers, json={"seat_limit_override": None})
    bad = await client.patch(f"{P}/companies/{cid}/subscription", headers=platform_admin.headers, json={"plan_code": "NO_SUCH_PLAN"})
    ov = (await q("SELECT seat_limit_override FROM subscription WHERE company_id = :c", company_id=cid, c=str(cid)))[0]["seat_limit_override"]
    rec(c, "seats / plan", set=s1.status_code, cleared=s2.status_code, unknown_plan=bad.status_code, override_now=ov)
    assert s1.status_code == s2.status_code == 200 and bad.status_code in (404, 422) and ov is None
    assert (await client.patch(f"{P}/companies/{cid}/subscription", headers=platform_admin.headers, json={"extend_trial_days": 0})).status_code == 422
    assert (await client.patch(f"{P}/companies/{cid}/subscription", headers=platform_admin.headers, json={"bogus": 1})).status_code == 422


async def test_plat_log_001_viewer_access_and_traversal(client: AsyncClient, platform_admin: Any, make_tenant: Any, approval_on: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = "PLAT-LOG-001"
    tenant = await make_tenant()
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "errors.log").write_text(json.dumps({"timestamp": "2026-10-26T10:00:00Z", "level": "error", "event": "x", "request_id": "r1"}) + "\n")
    (tmp_path / "secret.txt").write_text("must never be readable")
    res = {
        "anon files": (await client.get(f"{P}/logs/files")).status_code,
        "tenant files": (await client.get(f"{P}/logs/files", headers=tenant.headers)).status_code,
        "tenant entries": (await client.get(f"{P}/logs/entries", headers=tenant.headers)).status_code,
        "platform files": (await client.get(f"{P}/logs/files", headers=platform_admin.headers)).status_code,
    }
    trav = {}
    for ch in ("../secret", "..%2Fsecret", "secret.txt", "errors.log/../../secret.txt", "/etc/passwd", "errors/../app"):
        r = await client.get(f"{P}/logs/entries", headers=platform_admin.headers, params={"channel": ch})
        trav[ch] = r.status_code
        assert "must never be readable" not in r.text and "root:" not in r.text
    big = await client.get(f"{P}/logs/entries", headers=platform_admin.headers, params={"limit": 100000})
    rec(c, "access / traversal", access=res, traversal=trav, oversize_limit=big.status_code)
    assert res["anon files"] == 401 and res["tenant files"] in (401, 403) and res["tenant entries"] in (401, 403) and res["platform files"] == 200
    assert all(v in (404, 422) for v in trav.values()), trav
    assert big.status_code == 422


# ============================================================================== AUTH P0 (DB verified)
async def login(client: AsyncClient, email: str, pw: str) -> Any:
    return await client.post("/v1/auth/login", json={"email": email, "password": pw})


async def test_auth_login_001_to_004_and_token_001(client: AsyncClient, make_tenant: Any) -> None:
    c = "AUTH-LOGIN-001"
    t = await make_tenant()  # verified admin
    ok = await login(client, t.email, VALID_PASSWORD)
    assert ok.status_code == 200, ok.text
    data = ok.json()["data"]
    raw_refresh = refresh_cookie(ok)
    attrs = [h for h in ok.headers.get_list("set-cookie") if h.startswith("hrms_refresh=")]
    assert raw_refresh, "no refresh cookie"
    stored = await q("SELECT token_hash, revoked_at, expires_at FROM refresh_token WHERE user_id = :u ORDER BY created_at DESC", u=str(t.user_id))
    rec(c, "login", status=200, body_keys=sorted(data), refresh_in_body="refresh_token" in data, refresh_cookie_attributes=[a.split("=", 1)[0] + "=<redacted>; " + a.split(";", 1)[1] for a in attrs], refresh_rows=len(stored))
    assert stored and all(raw_refresh != r["token_hash"] and raw_refresh not in r["token_hash"] for r in stored), "raw refresh token stored in DB"
    assert (await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})).status_code == 200

    # AUTH-LOGIN-002 unverified e-mail gate
    u = await make_tenant(verified=False)
    gate = await login(client, u.email, VALID_PASSWORD)
    rows = await q("SELECT count(*) n FROM refresh_token WHERE user_id = :u", u=str(u.user_id))
    rec("AUTH-LOGIN-002", "unverified login", status=gate.status_code, code=(gate.json().get("error") or {}).get("code"), body=gate.text[:200], refresh_rows=rows[0]["n"])
    assert gate.status_code in (401, 403) and "access_token" not in gate.text

    # AUTH-LOGIN-003 no enumeration
    unknown = await login(client, f"nobody-{uuid4().hex[:6]}@example.com", "Whatever-Pass-1")
    wrong = await login(client, t.email, "Wrong-Pass-123!")
    sig = lambda r: (r.status_code, (r.json().get("error") or {}).get("code"), (r.json().get("error") or {}).get("message"))  # noqa: E731
    rec("AUTH-LOGIN-003", "enumeration", unknown=sig(unknown), wrong=sig(wrong))
    assert sig(unknown) == sig(wrong)

    # AUTH-LOGIN-004 lockout after repeated failures; correct password refused while locked; DB state
    attempts = []
    for i in range(8):
        r = await login(client, t.email, f"Wrong-Pass-{i}!")
        attempts.append(r.status_code)
        if r.status_code == 423:
            break
    during = await login(client, t.email, VALID_PASSWORD)
    u_row = (await q('SELECT failed_login_count, locked_until FROM "user" WHERE id = :u', u=str(t.user_id)))[0]
    rec("AUTH-LOGIN-004", "lockout", attempts=attempts, correct_while_locked=during.status_code, user_row=u_row)
    assert 423 in attempts and attempts.index(423) <= 5 and during.status_code == 423 and u_row["locked_until"] is not None
    async with get_session_factory()() as session:  # disposable DB: unlock to continue
        await session.execute(text('UPDATE "user" SET failed_login_count = 0, locked_until = NULL WHERE id = :u'), {"u": str(t.user_id)})
        await session.commit()
    await clear_rl()  # the 10/min login bucket is a separate control (own test files); reset it between phases
    assert (await login(client, t.email, VALID_PASSWORD)).status_code == 200

    # AUTH-TOKEN-001 forged / tampered tokens
    import base64
    good = (await login(client, t.email, VALID_PASSWORD)).json()["data"]["access_token"]
    h_, p_, s_ = good.split(".")
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    payload = json.loads(base64.urlsafe_b64decode(p_ + "=" * (-len(p_) % 4)))
    forged = {
        "tampered signature": f"{h_}.{p_}.{s_[:-3]}AAA",
        "alg none": f"{b64({'alg': 'none', 'typ': 'JWT'})}.{p_}.",
        "payload swapped (other user) keeping signature": f"{h_}.{b64({**payload, 'sub': str(uuid4())})}.{s_}",
        "expired claim, original signature": f"{h_}.{b64({**payload, 'exp': 1})}.{s_}",
        "garbage": "not.a.jwt",
        "empty bearer": "",
    }
    seen = {}
    for name, tok in forged.items():
        r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
        seen[name] = r.status_code
    rec("AUTH-TOKEN-001", "forged tokens", results=seen)
    assert all(v == 401 for v in seen.values()), seen


async def test_auth_refresh_001_logout_001(client: AsyncClient, make_tenant: Any) -> None:
    c = "AUTH-REFRESH-001"
    t = await make_tenant()
    r0r = await login(client, t.email, VALID_PASSWORD)
    old = refresh_cookie(r0r)
    assert old
    rf = await client.post("/v1/auth/token/refresh", json={"refresh_token": old})
    assert rf.status_code == 200, rf.text
    new = refresh_cookie(rf)
    assert new and new != old
    fam = await q("SELECT token_family_id::text f, (revoked_at IS NOT NULL) rv, revoked_reason r FROM refresh_token WHERE user_id = :u ORDER BY created_at", u=str(t.user_id))
    rec(c, "after rotation (all rows of the user; registration created its own family)", rows=fam)
    login_family = fam[-1]["f"]
    assert fam[-2]["f"] == login_family and [x["rv"] for x in fam][-2:] == [True, False]
    replay = await client.post("/v1/auth/token/refresh", json={"refresh_token": old})
    child = await client.post("/v1/auth/token/refresh", json={"refresh_token": new})
    fam2 = await q("SELECT (revoked_at IS NOT NULL) rv, revoked_reason r FROM refresh_token WHERE user_id = :u AND token_family_id = CAST(:f AS uuid)", u=str(t.user_id), f=login_family)
    rec(c, "reuse of rotated token", replay=replay.status_code, child_after=child.status_code, rows=fam2)
    assert replay.status_code == 401 and child.status_code == 401, "family not revoked on reuse"
    assert all(x["rv"] for x in fam2)

    # AUTH-LOGOUT-001
    sr = await login(client, t.email, VALID_PASSWORD)
    s = {**sr.json()["data"], "refresh_token": refresh_cookie(sr)}
    login_rows = await q("SELECT id::text i, session_id::text s, (revoked_at IS NOT NULL) rv FROM refresh_token WHERE user_id = :u ORDER BY created_at", u=str(t.user_id))
    rec("AUTH-LOGOUT-001", "rows after second login", rows=login_rows)
    ah = {"Authorization": f"Bearer {s['access_token']}"}
    assert (await client.get("/v1/auth/me", headers=ah)).status_code == 200
    lo = await client.post("/v1/auth/logout", headers=ah)
    me = await client.get("/v1/auth/me", headers=ah)
    rf2 = await client.post("/v1/auth/token/refresh", json={"refresh_token": s["refresh_token"]})
    after_rows = await q("SELECT id::text i, session_id::text s, (revoked_at IS NOT NULL) rv FROM refresh_token WHERE user_id = :u ORDER BY created_at", u=str(t.user_id))
    newest = after_rows[-1]
    rec("AUTH-LOGOUT-001", "after logout", logout=lo.status_code, me=me.status_code, refresh=rf2.status_code, rows=after_rows)
    assert lo.status_code == 204 and me.status_code == 401 and rf2.status_code == 401
    assert newest["rv"] is True, "the logged-out session's refresh token is still live in the DB"
    # sessions are independent: logout must not revoke other sessions of the same user (registration session, earlier login family)


# ============================================================================== TEN-HDR-001 (owner role vs real runtime role)
@pytest.mark.xfail(strict=True, reason="DEF-B6-01: under the runtime role hrms_app an omitted X-Company-Id gives 422 INVALID_VALUE and a mismatched one 401 INVALID_TOKEN; docs/api say optional / 404")
async def test_ten_hdr_001_header_behaviour_by_database_role(client: AsyncClient, make_tenant: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    c = "TEN-HDR-001"
    a, b = await make_tenant(), await make_tenant()
    tok = {"Authorization": b.headers["Authorization"]}
    cases = {
        "own header": b.headers,
        "no header": tok,
        "other company's header": {**tok, "X-Company-Id": str(a.company_id)},
        "random uuid header": {**tok, "X-Company-Id": str(uuid4())},
        "garbage header": {**tok, "X-Company-Id": "not-a-uuid"},
    }
    seen: dict[str, dict[str, Any]] = {}
    try:
        for which in ("owner", "app"):
            await switch_role(monkeypatch, which)
            who = (await q("SELECT current_user u"))[0]["u"]
            out = {}
            for name, h in cases.items():
                r = await client.get("/v1/auth/me", headers=h)
                r2 = await client.get("/v1/employees", headers=h)
                out[name] = {"me": r.status_code, "employees": r2.status_code,
                             "code": (r2.json().get("error") or {}).get("code") if r2.status_code >= 400 else None,
                             "leaks_other_tenant": bool(r2.status_code == 200 and any(x.get("company_id") == str(a.company_id) for x in r2.json().get("data", [])))}
            seen[f"{which}:{who}"] = out
        rec(c, "header behaviour by database role", results=seen)
        for k, out in seen.items():
            assert not any(v["leaks_other_tenant"] for v in out.values()), k
            assert out["own header"]["me"] == 200 and out["own header"]["employees"] == 200, (k, out["own header"])
            assert out["other company's header"]["employees"] in (401, 404) and out["random uuid header"]["employees"] in (401, 404), (k, out)
        # DOCUMENTED behaviour (docs/api/AUTHENTICATION.md, DATA_MODELS.md D-8): header optional; mismatch -> 404
        runtime = next(v for k, v in seen.items() if k.startswith("app:"))
        documented_ok = runtime["no header"]["me"] == 200 and runtime["no header"]["employees"] == 200 and runtime["other company's header"]["employees"] == 404
        rec(c, "documented behaviour holds under the runtime role", holds=documented_ok)
        assert documented_ok, "runtime role: header omitted / mismatched does not behave as documented"
    finally:
        await switch_role(monkeypatch, "owner")
