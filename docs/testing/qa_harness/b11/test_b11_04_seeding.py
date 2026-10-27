"""B11-SEED-N: role/permission seeding consistency for new and existing synthetic tenants (disposable DB, owner role - this is schema/data,
not request authorization). New tenants come from `register_company`; existing tenants from the real `upgrade()`/`downgrade()` of Alembic
revision 20261026090000, loaded from the repository file and executed here against the disposable database only."""
import importlib.util
from pathlib import Path
from uuid import UUID

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from b11common import rec
from sqlalchemy import text
from tests.integration.modules.attendance.test_employee_default_role_attendance import _tenant as new_tenant, _teardown as drop_tenant

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio
MIG = Path("/media/varun/varun12/work/staff-spectrum/HRMS/apps/api/alembic/versions/20261026090000_hr_admin_attendance_onboarding_grants.py")
HR_NEW = {"ATTENDANCE.VIEW", "ATTENDANCE.VIEW_ALL", "ONBOARDING.CREATE", "ONBOARDING.VIEW", "ONBOARDING.REVIEW", "ONBOARDING.ACTIVATE", "ONBOARDING.CANCEL"}


async def snapshot(cid: UUID) -> dict[tuple[str, bool, str], str]:
    async with get_session_factory()() as s:
        await set_rls_company_id(s, str(cid))
        rows = (await s.execute(text(
            "SELECT r.code rc, r.is_system sy, p.code pc, rp.data_scope sc FROM role_permission rp JOIN role r ON r.id = rp.role_id "
            "JOIN permission p ON p.id = rp.permission_id WHERE r.company_id = :c"), {"c": str(cid)})).mappings().all()
    return {(r["rc"], r["sy"], r["pc"]): r["sc"] for r in rows}


async def run_mig(fn: str) -> None:
    spec = importlib.util.spec_from_file_location("b11_hr_mig", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    async with get_session_factory()() as session:
        conn = await session.connection()

        def go(sync_conn):
            with Operations.context(MigrationContext.configure(sync_conn)):
                getattr(mod, fn)()
        await conn.run_sync(go)
        await session.commit()


def by_role(snap, role):
    return {pc: sc for (rc, _sy, pc), sc in snap.items() if rc == role}


async def test_new_tenant_role_matrix(client, seeded_plan_catalogue):
    c = "B11-SEED-N"
    t = await new_tenant(client)
    try:
        snap = await snapshot(t.company_id)
        roles = {r: by_role(snap, r) for r in ("COMPANY_ADMIN", "HR_ADMIN", "REPORTING_MANAGER", "BRANCH_MANAGER", "EMPLOYEE")}
        async with get_session_factory()() as s:
            n_perm = (await s.execute(text("SELECT count(*) FROM permission"))).scalar()
        shape = {r: {"n": len(g), "scopes": sorted(set(g.values()))} for r, g in roles.items()}
        holders = lambda code: sorted(r for r, g in roles.items() if code in g)           # noqa: E731
        facts = {
            "catalogue_permissions": n_perm, "shape": shape,
            "ATTENDANCE.VIEW": {r: roles[r].get("ATTENDANCE.VIEW") for r in roles if "ATTENDANCE.VIEW" in roles[r]},
            "ATTENDANCE.VIEW_ALL": {r: roles[r].get("ATTENDANCE.VIEW_ALL") for r in roles if "ATTENDANCE.VIEW_ALL" in roles[r]},
            "ONBOARDING holders": {code: holders(code) for code in sorted(HR_NEW) if code.startswith("ONBOARDING")},
        }
        rec(c, "fresh tenant role matrix", **facts)
        assert shape["COMPANY_ADMIN"]["scopes"] == ["COMPANY"] and shape["COMPANY_ADMIN"]["n"] == n_perm, shape["COMPANY_ADMIN"]
        assert shape["HR_ADMIN"] == {"n": 39, "scopes": ["COMPANY"]}  # 32 before the HR_ADMIN policy (B10 role matrix) + the 7 approved additions, shape["HR_ADMIN"]
        assert shape["EMPLOYEE"] == {"n": 14, "scopes": ["SELF"]}, shape["EMPLOYEE"]
        assert shape["REPORTING_MANAGER"] == {"n": 5, "scopes": ["REPORTEE_TREE"]}, shape["REPORTING_MANAGER"]
        assert shape["BRANCH_MANAGER"] == {"n": 7, "scopes": ["BRANCH"]}, shape["BRANCH_MANAGER"]
        assert HR_NEW <= set(roles["HR_ADMIN"]) and {roles["HR_ADMIN"][c_] for c_ in HR_NEW} == {"COMPANY"}
        # VIEW and VIEW_ALL are distinct permissions with distinct holders and each at its configured scope
        assert holders("ATTENDANCE.VIEW_ALL") == ["COMPANY_ADMIN", "HR_ADMIN"], holders("ATTENDANCE.VIEW_ALL")
        assert holders("ATTENDANCE.VIEW") == ["BRANCH_MANAGER", "COMPANY_ADMIN", "EMPLOYEE", "HR_ADMIN"], holders("ATTENDANCE.VIEW")
        assert roles["EMPLOYEE"]["ATTENDANCE.VIEW"] == "SELF" and roles["BRANCH_MANAGER"]["ATTENDANCE.VIEW"] == "BRANCH"
        for code in ("ONBOARDING.CREATE", "ONBOARDING.VIEW", "ONBOARDING.REVIEW", "ONBOARDING.ACTIVATE", "ONBOARDING.CANCEL"):
            assert holders(code) == ["COMPANY_ADMIN", "HR_ADMIN"], (code, holders(code))
        # no HR_ADMIN-only grant leaked: everything HR holds beyond the baseline 25 is exactly HR_NEW
        extra_for_other_roles = {r: sorted(set(g) & HR_NEW) for r, g in roles.items() if r not in ("COMPANY_ADMIN", "HR_ADMIN")}
        assert extra_for_other_roles == {"REPORTING_MANAGER": [], "BRANCH_MANAGER": ["ATTENDANCE.VIEW"], "EMPLOYEE": ["ATTENDANCE.VIEW"]}, extra_for_other_roles
    finally:
        await drop_tenant(t)


async def test_migration_on_existing_tenants(client, seeded_plan_catalogue):
    c = "B11-SEED-N"
    t1, t2 = await new_tenant(client), await new_tenant(client)
    try:
        # emulate pre-migration tenants: strip HR_ADMIN's new grants; T2 additionally has a narrower hand-made HR_ADMIN row and a custom role with ONBOARDING.VIEW @SELF
        for t in (t1, t2):
            async with get_session_factory()() as s:
                await set_rls_company_id(s, str(t.company_id))
                codes = ",".join(f"'{x}'" for x in sorted(HR_NEW))
                await s.execute(text(f"DELETE FROM role_permission rp USING role r, permission p WHERE rp.role_id = r.id AND rp.permission_id = p.id AND r.company_id = :c AND r.code = 'HR_ADMIN' AND p.code IN ({codes})"), {"c": str(t.company_id)})
                await s.commit()
        async with get_session_factory()() as s:
            await set_rls_company_id(s, str(t2.company_id))
            await s.execute(text("INSERT INTO role_permission(role_id, permission_id, data_scope) SELECT r.id, p.id, 'REPORTEES' FROM role r, permission p WHERE r.company_id = :c AND r.code = 'HR_ADMIN' AND p.code = 'ONBOARDING.VIEW'"), {"c": str(t2.company_id)})
            await s.execute(text("INSERT INTO role(id, company_id, code, name, is_system, created_at, updated_at) VALUES (gen_random_uuid(), :c, 'CUSTOM_ONB', 'Custom onboarding viewer', false, now(), now())"), {"c": str(t2.company_id)})
            await s.execute(text("INSERT INTO role_permission(role_id, permission_id, data_scope) SELECT r.id, p.id, 'SELF' FROM role r, permission p WHERE r.company_id = :c AND r.code = 'CUSTOM_ONB' AND p.code IN ('ONBOARDING.VIEW', 'ATTENDANCE.VIEW')"), {"c": str(t2.company_id)})
            await s.commit()
        pre = {t.company_id: await snapshot(t.company_id) for t in (t1, t2)}
        await run_mig("upgrade")
        post1 = {t.company_id: await snapshot(t.company_id) for t in (t1, t2)}
        await run_mig("upgrade")
        post2 = {t.company_id: await snapshot(t.company_id) for t in (t1, t2)}
        report = {}
        for t, name in ((t1, "T1 (stripped)"), (t2, "T2 (stripped + narrower row + custom role)")):
            cid = t.company_id
            added = {k: v for k, v in post1[cid].items() if k not in pre[cid]}
            changed = {k: (pre[cid][k], post1[cid][k]) for k in pre[cid] if pre[cid][k] != post1[cid].get(k)}
            removed = [k for k in pre[cid] if k not in post1[cid]]
            report[name] = {"added": sorted(f"{k[0]}:{k[2]}={v}" for k, v in added.items()), "changed": changed, "removed": removed, "second_run_identical": post1[cid] == post2[cid]}
            assert {k[0] for k in added} == {"HR_ADMIN"} and all(k[1] for k in added), added                 # only the system HR_ADMIN role gained rows
            assert not changed and not removed, (changed, removed)                                            # nothing narrower was broadened, nothing removed
            assert post1[cid] == post2[cid]                                                                    # idempotent
        t2grants = by_role(post1[t2.company_id], "HR_ADMIN")
        assert t2grants["ONBOARDING.VIEW"] == "REPORTEES" and {t2grants[x] for x in HR_NEW - {"ONBOARDING.VIEW"}} == {"COMPANY"}
        cust = {pc: sc for (rc, _sy, pc), sc in post1[t2.company_id].items() if rc == "CUSTOM_ONB"}
        assert cust == {"ONBOARDING.VIEW": "SELF", "ATTENDANCE.VIEW": "SELF"}, cust                          # custom roles untouched
        # no duplicate (role, permission) rows anywhere in the disposable database
        async with get_session_factory()() as s:
            dup = (await s.execute(text("SELECT count(*) FROM (SELECT role_id, permission_id FROM role_permission GROUP BY 1, 2 HAVING count(*) > 1) d"))).scalar()
        # downgrade removes COMPANY rows of exactly these codes from system HR_ADMIN (documented, including hand-added rows), keeps non-COMPANY rows
        await run_mig("downgrade")
        down = {t.company_id: await snapshot(t.company_id) for t in (t1, t2)}
        await run_mig("upgrade")
        up = {t.company_id: await snapshot(t.company_id) for t in (t1, t2)}
        for t in (t1, t2):
            hr_down = by_role(down[t.company_id], "HR_ADMIN")
            assert not {k for k, v in hr_down.items() if k in HR_NEW and v == "COMPANY"}
            others_pre = {k: v for k, v in pre[t.company_id].items() if k[0] != "HR_ADMIN"}
            others_down = {k: v for k, v in down[t.company_id].items() if k[0] != "HR_ADMIN"}
            assert others_pre == others_down, "downgrade touched a non-HR_ADMIN role"
            assert up[t.company_id] == post1[t.company_id]
        assert by_role(down[t2.company_id], "HR_ADMIN")["ONBOARDING.VIEW"] == "REPORTEES"
        rec(c, "migration on existing synthetic tenants", report=report, duplicate_role_permission_rows=dup, downgrade_upgrade_roundtrip_equal=True)
        assert dup == 0
    finally:
        await run_mig("upgrade")
        await drop_tenant(t1, t2)
