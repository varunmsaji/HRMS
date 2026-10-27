"""B10-1: permission matrix over EVERY permission-gated operation x principal, as the runtime role hrms_app.

Oracle: a principal is permitted on an operation iff the permission code its dependency requires is among the principal's effective
permissions (read from the DB: user -> user_company -> user_role -> role_permission).  Permitted => the request passes the permission gate
(status not 401/403; random ids/empty bodies then end in 404/409/422).  Denied => exactly 403.  Anonymous => 401.
Denied probes must leave every company-scoped table unchanged (strict).  Permitted probes' side effects are recorded (informational).
Operations whose permission is checked inside the handler (no require_permission dependency) are listed separately and covered by targeted tests."""
import asyncio
import pytest
from world import (build_world, company_counts, diff, drop_world, fill, perms_of, q, rec, route_inventory, switch_role)

pytestmark = pytest.mark.asyncio
WRITE = {"POST", "PUT", "PATCH", "DELETE"}
SKIP = {("POST", "/v1/auth/logout")}


async def hit(client, method, path, headers):
    kw = {"headers": {**headers, **({"If-Match": "0"} if method in WRITE else {})}}
    if method in WRITE:
        kw["json"] = {}
    r = await client.request(method, fill(path), **kw)
    return r.status_code


async def test_matrix_all_permission_gated_operations(client, seeded_plan_catalogue, monkeypatch):
    c = "B10-MATRIX"
    w = await build_world(client)
    try:
        inv = route_inventory()
        gated = [r for r in inv if r["perm"] and not r["platform"]]
        imperative = [r for r in inv if r["auth"] and not r["perm"] and not r["platform"] and (r["method"], r["path"]) not in SKIP]
        public = [r for r in inv if not r["auth"]]
        rec(c, "inventory", operations=len(inv), permission_gated=len(gated), imperative_auth_only=[f"{r['method']} {r['path']}" for r in imperative], platform=sum(1 for r in inv if r["platform"]), public=len(public))
        await switch_role(monkeypatch, "app")
        assert (await q("SELECT current_user u"))[0]["u"] == "hrms_app"
        principals = ["E1", "M1", "BX", "HR", "PAY", "CUSTV", "CUSTS"]
        mism: list[dict] = []
        summary: dict[str, dict] = {}
        for who in principals:
            have = await perms_of(w, who)
            allowed = [r for r in gated if r["perm"][0] in have]
            denied = [r for r in gated if r["perm"][0] not in have]
            before = await company_counts(w.cid)
            den_res = {}
            for r in denied:
                st = await hit(client, r["method"], r["path"], w.h(who))
                den_res[f"{r['method']} {r['path']}"] = st
                if st != 403:
                    mism.append({"who": who, "op": f"{r['method']} {r['path']}", "perm": r["perm"][0], "expected": "403", "got": st})
            after = await company_counts(w.cid)
            changed = diff(before, after)
            before2 = await company_counts(w.cid)
            alw_res = {}
            for r in allowed:
                if r["method"] in WRITE and who in ("HR",) and False:
                    continue
                st = await hit(client, r["method"], r["path"], w.h(who))
                alw_res[f"{r['method']} {r['path']}"] = st
                if st in (401, 403):
                    mism.append({"who": who, "op": f"{r['method']} {r['path']}", "perm": r["perm"][0], "expected": "permitted (not 401/403)", "got": st})
            after2 = await company_counts(w.cid)
            summary[who] = {"permissions": len(have), "denied_probed": len(denied), "denied_not_403": sum(1 for v in den_res.values() if v != 403), "denied_changed_tables": changed,
                            "permitted_probed": len(allowed), "permitted_got_401_403": sum(1 for v in alw_res.values() if v in (401, 403)), "permitted_side_effects_tables": diff(before2, after2)}
            assert not changed, f"{who}: DENIED requests changed data: {changed}"
        # anonymous
        anon = {f"{r['method']} {r['path']}": await hit(client, r["method"], r["path"], {}) for r in gated}
        bad_anon = {k: v for k, v in anon.items() if v != 401}
        summary["anonymous"] = {"probed": len(anon), "not_401": bad_anon}
        rec(c, "matrix results", summary=summary, mismatches=mism)
        assert not bad_anon, bad_anon
        assert not mism, mism
    finally:
        await drop_world(w, monkeypatch)
