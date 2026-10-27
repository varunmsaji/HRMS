"""B11 shared helpers. Re-exports the B10 synthetic world (mounted at /qa/b10) and adds employee/onboarding fixtures.
Everything is synthetic (random ids, @example.com); nothing here talks to anything outside the disposable stack."""
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

for _p in ("/qa/b10", str(Path(__file__).resolve().parent.parent / "b10")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from httpx import AsyncClient  # noqa: E402
from tests.integration.modules.account_invite.test_account_invite import _create_employee  # noqa: E402
from tests.integration.modules.attendance.test_attendance_security import _create_permission_scoped_user  # noqa: E402
from world import (  # noqa: E402,F401
    DAY, World, build_world, company_counts, diff, drop_world, perms_of, q, rec, scopes_of, seed_attendance, switch_role,
)

NOIGNORE: frozenset[str] = frozenset()      # compare EVERY company table, incl. audit_log / idempotency_key / session


async def mk_noaccount(client: AsyncClient, w: World, key: str, branch: str, manager_key: str | None) -> str:
    """An employee with an employment and a branch assignment but NO login (so it can be invited)."""
    h = w.h("ADMIN")
    email = f"{key.lower()}-{uuid4().hex[:8]}@example.com"
    emp = await _create_employee(client, h, key, personal_email=email)
    r = await client.post(f"/v1/employees/{emp['id']}/employments", headers=h, json={"legal_entity_id": w.le, "joining_date": "2026-01-01"})
    assert r.status_code == 201, r.text
    d = await client.post("/v1/departments", headers=h, json={"name": f"D-{key}-{uuid4().hex[:4]}", "branch_id": branch})
    assert d.status_code == 201, d.text
    ds = await client.post("/v1/designations", headers=h, json={"title": f"T-{key}-{uuid4().hex[:4]}", "department_id": d.json()["data"]["id"]})
    assert ds.status_code == 201, ds.text
    body = {"effective_from": "2026-01-01", "change_type": "INITIAL", "branch_id": branch, "department_id": d.json()["data"]["id"], "designation_id": ds.json()["data"]["id"]}
    if manager_key:
        body["reporting_manager_id"] = w.eid(manager_key)
    a = await client.post(f"/v1/employees/{emp['id']}/assignments", headers=h, json=body)
    assert a.status_code == 201, a.text
    return str(emp["id"])


async def scoped(w: World, perm: str, scope: str, owner: str) -> dict[str, str]:
    """A fresh custom role holding exactly `perm` at `scope`, attached to a fresh user linked to employee `owner`."""
    hh, _uid = await _create_permission_scoped_user(company_id=w.cid, permission_codes=[perm], data_scope=scope, caller_employee_id=UUID(w.eid(owner)))
    return hh


async def day_ids(w: World) -> dict[str, str]:
    """employee key -> attendance_day id for DAY (seed_attendance must have run)."""
    rows = await q("SELECT id::text i, employee_id::text e FROM attendance_day WHERE company_id = :c", c=str(w.cid))
    by_emp = {r["e"]: r["i"] for r in rows}
    return {k: by_emp[w.eid(k)] for k in ("E1", "E2", "E3", "M1") if w.eid(k) in by_emp}


def row_status(r: Any) -> int:
    return int(r.status_code)


async def drop_world11(w: World, monkeypatch: Any) -> None:
    """drop_world + removal of rows that a cross-tenant probe may have created in the OTHER tenant and that reference this tenant's
    employees (the attendance_day FK has no tenant check, so wipe_tenant cannot delete the employee until they are gone)."""
    from sqlalchemy import text as _t
    from hrms.core.db.session import get_session_factory, set_rls_company_id
    await switch_role(monkeypatch, "owner")
    for cid in (w.cid, w.tb.company_id):
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(cid))
            for tb in ("attendance_break", "attendance_day"):
                await session.execute(_t(f"DELETE FROM {tb} WHERE company_id = :c"), {"c": str(cid)})
            await session.commit()
    await drop_world(w, monkeypatch)
