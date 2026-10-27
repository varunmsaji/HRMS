"""B10 synthetic world: one company with two branches, five role-holders plus employees, custom roles, and a second tenant.

Branch X : BX  (BRANCH_MANAGER of X)   M1 (REPORTING_MANAGER)  E1, E2 (report to M1)
Branch Y : BY  (BRANCH_MANAGER of Y)   M2 (REPORTING_MANAGER)  E3 (reports to M2)
Users without an employee record: HR (system HR_ADMIN), PAY (custom: PAYROLL RUN_VIEW+RUN_PROCESS+SETUP_MANAGE @COMPANY),
CUSTV (custom: ATTENDANCE.VIEW @REPORTEES, linked to M1's employee), CUSTS (custom: ATTENDANCE.VIEW @SELF, linked to E1's employee).
Second tenant: admin only.  Everything is synthetic; all identifiers are random."""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.account_invite.test_account_invite import _token_from_invite_url
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_employee_default_role_attendance import _employee_user
from tests.integration.modules.attendance.test_employee_default_role_attendance import _tenant as _att_tenant
from tests.integration.modules.attendance.test_employee_default_role_attendance import _teardown as _att_teardown
from tests.integration.modules.organisation.test_registration_flow import VALID_PASSWORD
from tests.integration.tenant_wipe import wipe_tenant

from hrms.core.config.settings import get_settings
from hrms.core.db.session import dispose_engine, get_session_factory, set_rls_company_id

ART = Path(os.environ.get("QA_ARTIFACTS", "/tmp/qa-artifacts"))
OWNER_URL, APP_URL = os.environ["DATABASE_URL"], os.environ["HRMS_APP_DATABASE_URL"]
DAY = "2026-09-08"           # a Tuesday


def rec(case: str, step: str, **observed: Any) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    with (ART / f"{case}.jsonl").open("a") as fh:
        fh.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "step": step, **observed}, default=str) + "\n")


async def q(sql: str, **params: Any) -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        if params.get("c"):
            await set_rls_company_id(session, str(params["c"]))
        return [dict(r) for r in (await session.execute(text(sql), params)).mappings().all()]


async def switch_role(monkeypatch: Any, which: str) -> None:
    monkeypatch.setenv("DATABASE_URL", APP_URL if which == "app" else OWNER_URL)
    get_settings.cache_clear()
    await dispose_engine()


@dataclass
class Person:
    name: str
    employee_id: str | None
    headers: dict[str, str]
    user_id: str | None = None
    branch: str | None = None


@dataclass
class World:
    t: Any
    tb: Any
    cid: Any
    le: str
    branch_x: str
    branch_y: str
    people: dict[str, Person] = field(default_factory=dict)
    anon: dict[str, str] = field(default_factory=dict)

    def h(self, who: str) -> dict[str, str]:
        return self.people[who].headers

    def eid(self, who: str) -> str:
        return str(self.people[who].employee_id)


async def user_id_for(email: str) -> str:
    return str((await q('SELECT id FROM "user" WHERE email = :e', e=email))[0]["id"])


async def mk_branch(client: AsyncClient, h: dict[str, str], le: str, name: str) -> dict[str, str]:
    b = (await client.post("/v1/branches", headers=h, json={"legal_entity_id": le, "name": name})).json()["data"]
    d = (await client.post("/v1/departments", headers=h, json={"name": f"Dept {name}", "branch_id": b["id"]}))
    assert d.status_code == 201, d.text
    ds = (await client.post("/v1/designations", headers=h, json={"title": f"Role {name}", "department_id": d.json()["data"]["id"]}))
    assert ds.status_code == 201, ds.text
    return {"branch": b["id"], "dept": d.json()["data"]["id"], "desig": ds.json()["data"]["id"]}


async def build_world(client: AsyncClient) -> World:
    t = await _att_tenant(client)
    tb = await _att_tenant(client)
    h = t.admin
    async with get_session_factory()() as session:      # the trial plan allows 5 employees; the disposable DB gets a larger override
        await session.execute(text("UPDATE subscription SET seat_limit_override = 50 WHERE company_id = :c"), {"c": str(t.company_id)})
        await session.commit()
    org_x = await mk_branch(client, h, t.legal_entity_id, "X")
    org_y = await mk_branch(client, h, t.legal_entity_id, "Y")
    w = World(t=t, tb=tb, cid=t.company_id, le=t.legal_entity_id, branch_x=org_x["branch"], branch_y=org_y["branch"])

    async def employee(key: str, org: dict[str, str], role_codes: list[str] | None, manager: str | None) -> None:
        eid, eh = await _employee_user(client, t, key)
        email = t.emails[-1]
        uid = await user_id_for(email)
        body = {"effective_from": "2026-01-01", "change_type": "INITIAL", "branch_id": org["branch"], "department_id": org["dept"], "designation_id": org["desig"]}
        if manager:
            body["reporting_manager_id"] = manager
        r = await client.post(f"/v1/employees/{eid}/assignments", headers=h, json=body)
        assert r.status_code == 201, (key, r.text)
        if role_codes:
            rr = await client.patch(f"/v1/users/{uid}/roles", headers=h, json={"role_codes": role_codes})
            assert rr.status_code == 200, (key, rr.text)
        w.people[key] = Person(key, eid, eh, uid, org["branch"])

    await employee("M1", org_x, ["EMPLOYEE", "REPORTING_MANAGER"], None)
    await employee("M2", org_y, ["EMPLOYEE", "REPORTING_MANAGER"], None)
    await employee("BX", org_x, ["EMPLOYEE", "BRANCH_MANAGER"], None)
    await employee("BY", org_y, ["EMPLOYEE", "BRANCH_MANAGER"], None)
    await employee("E1", org_x, None, w.eid("M1"))
    await employee("E2", org_x, None, w.eid("M1"))
    await employee("E3", org_y, None, w.eid("M2"))

    # users without an employee record
    async def invited(role: str) -> Person:
        email = f"{role.lower()}-{uuid4().hex[:8]}@example.com"
        inv = await client.post("/v1/users/invite", headers=h, json={"email": email, "role_code": role})
        assert inv.status_code in (200, 201), inv.text
        tok = _token_from_invite_url(inv.json()["data"]["invite_url"])
        acc = await client.post(f"/v1/public/account-invites/{tok}/accept", json={"password": VALID_PASSWORD})
        assert acc.status_code == 201, acc.text
        return Person(role, None, {"Authorization": f"Bearer {acc.json()['data']['access_token']}", "X-Company-Id": str(t.company_id)}, await user_id_for(email))

    w.people["HR"] = await invited("HR_ADMIN")
    w.people["ADMIN"] = Person("ADMIN", None, h, str(t.user_id))
    pay_h, pay_uid = await _create_permission_scoped_user(company_id=t.company_id, permission_codes=["PAYROLL.RUN_VIEW", "PAYROLL.RUN_PROCESS", "PAYROLL.SETUP_MANAGE"], data_scope="COMPANY")
    w.people["PAY"] = Person("PAY", None, pay_h, str(pay_uid))
    cv_h, cv_uid = await _create_permission_scoped_user(company_id=t.company_id, permission_codes=["ATTENDANCE.VIEW"], data_scope="REPORTEES", caller_employee_id=UUID(w.eid("M1")))
    w.people["CUSTV"] = Person("CUSTV", w.eid("M1"), cv_h, str(cv_uid))
    cs_h, cs_uid = await _create_permission_scoped_user(company_id=t.company_id, permission_codes=["ATTENDANCE.VIEW"], data_scope="SELF", caller_employee_id=UUID(w.eid("E1")))
    w.people["CUSTS"] = Person("CUSTS", w.eid("E1"), cs_h, str(cs_uid))
    w.people["B_ADMIN"] = Person("B_ADMIN", None, tb.admin, str(tb.user_id))
    w.anon = {}
    return w


async def drop_world(w: World, monkeypatch: Any) -> None:
    await switch_role(monkeypatch, "owner")
    for cid in (w.cid, w.tb.company_id):
        async with get_session_factory()() as session:
            for table in ("account_invite", "refresh_token", "session"):
                await session.execute(text(f'DELETE FROM "{table}" WHERE company_id = :c'), {"c": str(cid)})
            await session.commit()
    await wipe_tenant(company_id=w.cid, user_id=w.t.user_id)
    await wipe_tenant(company_id=w.tb.company_id, user_id=w.tb.user_id)
    await _cleanup_scoped_users()
    async with get_session_factory()() as session:
        await session.execute(text("DELETE FROM \"user\" WHERE email LIKE '%@example.com' AND id NOT IN (SELECT user_id FROM user_company)"))
        await session.commit()


async def perms_of(w: World, who: str) -> set[str]:
    p = w.people[who]
    rows = await q("SELECT DISTINCT pm.code FROM user_role ur JOIN user_company uc ON uc.id = ur.user_company_id JOIN role_permission rp ON rp.role_id = ur.role_id JOIN permission pm ON pm.id = rp.permission_id WHERE uc.user_id = CAST(:u AS uuid)", u=p.user_id, c=str(w.cid))
    return {r["code"] for r in rows}


async def scopes_of(w: World, who: str) -> dict[str, set[str]]:
    p = w.people[who]
    rows = await q("SELECT pm.code, rp.data_scope sc FROM user_role ur JOIN user_company uc ON uc.id = ur.user_company_id JOIN role_permission rp ON rp.role_id = ur.role_id JOIN permission pm ON pm.id = rp.permission_id WHERE uc.user_id = CAST(:u AS uuid)", u=p.user_id, c=str(w.cid))
    out: dict[str, set[str]] = {}
    for r in rows:
        out.setdefault(r["code"], set()).add(r["sc"])
    return out


async def company_counts(cid: Any) -> dict[str, int]:
    tabs = [r["table_name"] for r in await q(
        "SELECT DISTINCT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='company_id' "
        "AND table_name NOT IN (SELECT table_name FROM information_schema.views WHERE table_schema='public') ORDER BY 1")]
    out: dict[str, int] = {}
    for tb in tabs:
        out[tb] = (await q(f'SELECT count(*) n FROM "{tb}" WHERE company_id = :c', c=str(cid)))[0]["n"]
    return out


def diff(a: dict[str, int], b: dict[str, int], ignore: set[str] = frozenset({"audit_log", "session", "refresh_token", "idempotency_key"})) -> dict[str, tuple[int, int]]:
    return {k: (a[k], b.get(k, 0)) for k in a if a[k] != b.get(k, 0) and k not in ignore}


async def seed_attendance(client: AsyncClient, w: World) -> dict[str, Any]:
    """Punches (admin on behalf) for E1, E2, E3, M1 on DAY, calculated days, an OPEN attendance period for the legal entity."""
    h = w.t.admin
    for who in ("E1", "E2", "E3", "M1"):
        for hh, d in ((9, "IN"), (18, "OUT")):
            r = await client.post("/v1/attendance/punches", headers=h, json={"employee_id": w.eid(who), "punch_time": f"{DAY}T{hh:02d}:00:00Z", "direction": d, "reference": "b10"})
            assert r.status_code == 201, (who, r.text)
        c = await client.post("/v1/attendance/days/calculate", headers=h, params={"employee_id": w.eid(who), "date": DAY})
        assert c.status_code == 200, c.text
    per = await client.post("/v1/attendance-periods", headers=h, json={"legal_entity_id": w.le, "period_start": DAY, "period_end": DAY, "label": "b10"})
    assert per.status_code == 201, per.text
    return {"period_id": per.json()["data"]["id"], "period_version": per.json()["data"]["version"]}


def route_inventory() -> list[dict[str, Any]]:
    """Every operation with the permission code(s) its dependencies require and whether the DataScope is bound to a used parameter."""
    from fastapi.routing import APIRoute

    from hrms.app import create_app

    app = create_app()
    rows: list[dict[str, Any]] = []

    def walk(dep: Any, acc: dict[str, Any]) -> None:
        for d in dep.dependencies:
            walk(d, acc)
        fn = dep.call
        if fn is None:
            return
        qn = getattr(fn, "__qualname__", "")
        if getattr(fn, "__name__", "") == "dependency" and qn.startswith("require_permission"):
            for c in getattr(fn, "__closure__", None) or ():
                try:
                    v = c.cell_contents
                except ValueError:
                    continue
                if isinstance(v, str):
                    acc["perm"].append(v)
        if "get_current_platform_admin" in qn:
            acc["platform"] = True
        if "get_current_user" in qn:
            acc["auth"] = True

    def all_routes(rs: Any, prefix: str = "") -> Any:
        for r in rs:
            if isinstance(r, APIRoute):
                yield prefix, r
            elif type(r).__name__ == "_IncludedRouter":
                yield from all_routes(r.original_router.routes, prefix + (r.include_context.prefix or ""))

    for prefix, r in all_routes(app.routes):
        acc: dict[str, Any] = {"perm": [], "platform": False, "auth": False}
        walk(r.dependant, acc)
        sp = [d.name for d in r.dependant.dependencies if d.call is not None and getattr(d.call, "__qualname__", "").startswith("require_permission") and d.name]
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            rows.append({"method": m, "path": prefix + r.path, "perm": sorted(set(acc["perm"])), "scope_param": sp, "scope_used": any(not p.startswith("_") for p in sp),
                         "platform": acc["platform"], "auth": acc["auth"] or bool(acc["perm"]) or acc["platform"]})
    return rows


def fill(path: str) -> str:
    while "{" in path:
        a, b = path.index("{"), path.index("}")
        path = path[:a] + str(uuid4()) + path[b + 1:]
    return path


# --------------------------------------------------------------------------- expected visibility (oracle from RBAC_DATA_SCOPE_DECISIONS + resolve_visible_employee_ids)
def expected_visible(w: World, who: str, levels: set[str]) -> set[str] | None:
    """None = COMPANY (everything).  SELF -> own; REPORTEES / REPORTEE_TREE -> reportees (self NOT included); BRANCH -> every employee whose current branch is the caller's."""
    if "COMPANY" in levels:
        return None
    me = w.people[who]
    out: set[str] = set()
    if me.employee_id is None:
        return out
    if "SELF" in levels:
        out.add(me.employee_id)
    if levels & {"REPORTEES", "REPORTEE_TREE"}:
        out |= {w.eid(k) for k, mgr in REPORTS.items() if mgr == _key_of(w, me.employee_id)}
    if "BRANCH" in levels:
        out |= {p.employee_id for p in w.people.values() if p.employee_id and p.branch == me.branch and p.name in ORG_EMPLOYEES}
    return out


ORG_EMPLOYEES = {"M1", "M2", "BX", "BY", "E1", "E2", "E3"}
REPORTS = {"E1": "M1", "E2": "M1", "E3": "M2"}          # direct reports (no deeper tree in this world)


def _key_of(w: World, eid: str) -> str | None:
    return next((k for k, p in w.people.items() if p.employee_id == eid and k in ORG_EMPLOYEES), None)


async def seed_all(client: AsyncClient, w: World) -> dict[str, Any]:
    from tests.integration.modules.attendance.test_regularization import _create_regularization_policy
    from tests.integration.modules.leave.test_leave_application import (
        _create_leave_type, _give_balance, _setup_calendar, _setup_leave_policy)
    from tests.integration.modules.payroll.test_pay_run import _closed_period  # noqa: F401
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    h = w.t.admin
    out: dict[str, Any] = {}
    out.update(await seed_attendance(client, w))
    # --- regularization requests (policy chain MANAGER): E1 and E3 each forget their OUT punch on the next day
    await _create_regularization_policy(client, h, approval_chain="MANAGER")
    day2 = "2026-09-09"
    regs = {}
    for who in ("E1", "E3"):
        await client.post("/v1/attendance/punches", headers=h, json={"employee_id": w.eid(who), "punch_time": f"{day2}T09:00:00Z", "direction": "IN", "reference": "b10"})
        r = await client.post("/v1/regularizations", headers=w.h(who), json={"employee_id": w.eid(who), "attendance_date": day2, "request_type": "MISSING_PUNCH", "reason": "b10",
                              "requested_punches": [{"direction": "OUT", "requested_time": f"{day2}T18:00:00Z"}]})
        assert r.status_code == 201, (who, r.text)
        regs[who] = r.json()["data"]
    out["regs"] = regs
    # --- leave: type + calendar + policy (chain MANAGER) + balances + one pending application each for E1 and E3
    lt = await _create_leave_type(client, h)
    await _setup_calendar(client, h)
    await _setup_leave_policy(client, h, leave_type_id=lt["id"], approval_chain="MANAGER")
    apps = {}
    for who in ("E1", "E2", "E3"):
        await _give_balance(client, h, employee_id=w.eid(who), leave_type_id=lt["id"], amount="10.00")
    for i, who in enumerate(("E1", "E3")):
        r = await client.post("/v1/leave-applications", headers={**w.h(who), "Idempotency-Key": f"b10-leave-{who}-0001"},
                              json={"leave_type_id": lt["id"], "start_date": "2026-09-21", "end_date": "2026-09-21", "reason": "b10"})
        assert r.status_code == 201, (who, r.text)
        apps[who] = r.json()["data"]
    out["leave_type"] = lt["id"]
    out["apps"] = apps
    # --- payroll profile (compensation, statutory, bank, salary assignment) and one document for E1 and E3
    from tests.integration.modules.payroll.test_pay_run import _CTC
    for who in ("E1", "E3"):
        eid = w.eid(who)
        for url, body in (
            (f"/v1/employees/{eid}/compensation", {"effective_from": "2026-01-01", "annual_ctc_minor": _CTC, "currency": "INR", "revision_type": "JOINING", "revision_reason": "b10"}),
            (f"/v1/employees/{eid}/statutory", {"effective_from": "2026-01-01", "is_pf_applicable": False, "is_esi_applicable": False, "is_lwf_applicable": False, "tax_regime": "NEW", "revision_reason": "b10"}),
            (f"/v1/employees/{eid}/bank", {"effective_from": "2026-01-01", "account_holder_name": "Synthetic", "account_number_enc": "123456789012", "bank_name": "State Bank", "ifsc": "SBIN0001234", "payment_mode": "BANK"}),
        ):
            r = await client.post(url, headers=h, json=body)
            assert r.status_code == 201, (url, r.text)
        up = await client.post(f"/v1/employees/{eid}/documents", headers=h, data={"document_type": "PAN"}, files={"file": ("pan.jpg", b"\xff\xd8\xff" + b"b10-synthetic", "image/jpeg")})
        assert up.status_code == 201, up.text
    return out
