"""B11 employee lifecycle QA as the runtime role `hrms_app`: B11-EMP-LIFE, B11-EMP-LINK, B11-EMP-ORDER, B11-EMP-ISO, B11-EMP-FAIL/CONC, B11-PERM-HR.
Only operations that exist are exercised: create, patch (If-Match), deactivate/reactivate (is_active), employment create/terminate/rehire,
assignment history (INITIAL/TRANSFER/MANAGER_CHANGE = branch/department/designation/manager changes). There is no separate 'suspend' or 'transfer' endpoint."""
import asyncio
from uuid import uuid4

import pytest
from b11common import NOIGNORE, build_world, company_counts, diff, drop_world11 as drop_world, perms_of, q, rec, scopes_of, seed_attendance, switch_role
from world import expected_visible, fill, route_inventory

pytestmark = pytest.mark.asyncio
DENY = (401, 403, 404)


async def org_for(client, w, branch):
    h = w.h("ADMIN")
    d = await client.post("/v1/departments", headers=h, json={"name": f"LD-{uuid4().hex[:5]}", "branch_id": branch})
    ds = await client.post("/v1/designations", headers=h, json={"title": f"LT-{uuid4().hex[:5]}", "department_id": d.json()["data"]["id"]})
    assert d.status_code == 201 and ds.status_code == 201
    return {"branch_id": branch, "department_id": d.json()["data"]["id"], "designation_id": ds.json()["data"]["id"]}


async def actions_since(cid, n):
    return [r["action"] for r in await q("SELECT action FROM audit_log WHERE company_id = :c ORDER BY occurred_at, id", c=str(cid))][n:]


async def n_audit(cid):
    return len(await actions_since(cid, 0))


async def emp_row(cid, eid):
    return (await q("SELECT status, is_active, version, first_name, deleted_at FROM employee WHERE company_id = :c AND id = CAST(:i AS uuid)", c=str(cid), i=str(eid)))[0]


# ----------------------------------------------------------------------------------------------------------------------
async def test_hr_admin_lifecycle_state_and_audit(client, seeded_plan_catalogue, monkeypatch):
    c = "B11-EMP-LIFE"
    w = await build_world(client)
    try:
        hr = w.h("HR")
        ox, oy = await org_for(client, w, w.branch_x), await org_for(client, w, w.branch_y)
        await switch_role(monkeypatch, "app")
        steps, problems = [], []

        def note(step, **kw):
            steps.append({"step": step, **kw})

        n0 = await n_audit(w.cid)
        email = f"life-{uuid4().hex[:8]}@personal.example"
        r = await client.post("/v1/employees", headers=hr, json={"first_name": "Lena", "last_name": "Cycle", "personal_email": email})
        assert r.status_code == 201, r.text
        emp = r.json()["data"]
        eid = emp["id"]
        row = await emp_row(w.cid, eid)
        note("create employee", http=r.status_code, db=row, audit=await actions_since(w.cid, n0))
        assert "EMPLOYEE_CREATED" in await actions_since(w.cid, n0)

        # duplicate creation: no uniqueness on e-mail or name exists -> observed, not asserted
        r2 = await client.post("/v1/employees", headers=hr, json={"first_name": "Lena", "last_name": "Cycle", "personal_email": email})
        note("create second employee, same name+e-mail (observation)", http=r2.status_code)

        # employment
        n1 = await n_audit(w.cid)
        em = await client.post(f"/v1/employees/{eid}/employments", headers=hr, json={"legal_entity_id": w.le, "joining_date": "2026-01-01"})
        assert em.status_code == 201, em.text
        emp_id, emp_ver = em.json()["data"]["id"], em.json()["data"]["version"]
        note("create employment", http=em.status_code, audit=await actions_since(w.cid, n1), employee_status=(await emp_row(w.cid, eid))["status"])
        dup = await client.post(f"/v1/employees/{eid}/employments", headers=hr, json={"legal_entity_id": w.le, "joining_date": "2026-03-01"})
        note("second active employment", http=dup.status_code, code=(dup.json().get("error") or {}).get("code"))
        if dup.status_code != 409:
            problems.append("second active employment accepted")

        # assignments: initial, transfer (branch+dept+designation), manager change; overlap / loop refused
        async def assign(body, ver=None):
            return await client.post(f"/v1/employees/{eid}/assignments", headers={**hr, **({"If-Match": str(ver)} if ver else {})}, json=body)
        n2 = await n_audit(w.cid)
        a1 = await assign({"effective_from": "2026-01-01", "change_type": "INITIAL", **ox, "reporting_manager_id": w.eid("M1")})
        a2 = await assign({"effective_from": "2026-06-01", "change_type": "TRANSFER", **oy, "reporting_manager_id": w.eid("M2")}, a1.json()["data"]["version"])
        a3 = await assign({"effective_from": "2026-07-01", "change_type": "MANAGER_CHANGE", **oy, "reporting_manager_id": w.eid("M1")}, a2.json()["data"]["version"])
        cur_ver = a3.json()["data"]["version"]
        rows = await q("SELECT effective_from::text f, effective_to::text t, branch_id::text b, reporting_manager_id::text m FROM employee_assignment WHERE company_id = :c AND employee_id = CAST(:e AS uuid) ORDER BY effective_from", c=str(w.cid), e=eid)
        note("assignments INITIAL, TRANSFER, MANAGER_CHANGE", http=[a1.status_code, a2.status_code, a3.status_code], history=rows, audit=await actions_since(w.cid, n2))
        assert [a1.status_code, a2.status_code, a3.status_code] == [201, 201, 201], (a1.text, a2.text, a3.text)
        open_rows = [x for x in rows if x["t"] is None]
        if len(rows) != 3 or len(open_rows) != 1 or rows[-1]["m"] != w.eid("M1") or rows[1]["b"] != w.branch_y:
            problems.append(f"assignment history inconsistent: {rows}")
        for label, body in (("same effective date again", {"effective_from": "2026-07-01", "change_type": "TRANSFER", **ox}),
                            ("self as reporting manager", {"effective_from": "2026-08-01", "change_type": "MANAGER_CHANGE", **oy, "reporting_manager_id": eid}),
                            ("manager from another tenant", {"effective_from": "2026-08-01", "change_type": "MANAGER_CHANGE", **oy, "reporting_manager_id": str(uuid4())}),
                            ("branch of another tenant", {"effective_from": "2026-08-01", "change_type": "TRANSFER", "branch_id": str(uuid4())})):
            before = await company_counts(w.cid)
            resp = await assign(body, cur_ver)
            ch = diff(before, await company_counts(w.cid), NOIGNORE)
            note(f"invalid assignment: {label}", http=resp.status_code, code=(resp.json().get("error") or {}).get("code"), changed=sorted(ch))
            if resp.status_code < 400 or ch:
                problems.append(f"{label}: {resp.status_code} {sorted(ch)}")

        # profile update with version token
        v = (await emp_row(w.cid, eid))["version"]
        n3 = await n_audit(w.cid)
        u1 = await client.patch(f"/v1/employees/{eid}", headers={**hr, "If-Match": str(v)}, json={"first_name": "Lenora"})
        u2 = await client.patch(f"/v1/employees/{eid}", headers={**hr, "If-Match": str(v)}, json={"first_name": "Stale"})
        row = await emp_row(w.cid, eid)
        note("patch then stale patch", http=[u1.status_code, u2.status_code], db=row, audit=await actions_since(w.cid, n3))
        if (u1.status_code, u2.status_code) != (200, 409) or row["first_name"] != "Lenora":
            problems.append("optimistic concurrency on PATCH")
        miss = await client.patch(f"/v1/employees/{eid}", headers=hr, json={"first_name": "NoToken"})
        note("patch without If-Match", http=miss.status_code)
        if miss.status_code < 400:
            problems.append("PATCH without If-Match accepted")

        # deactivate / reactivate (the only 'suspend' semantics)
        v = (await emp_row(w.cid, eid))["version"]
        n4 = await n_audit(w.cid)
        d1 = await client.delete(f"/v1/employees/{eid}", headers={**hr, "If-Match": str(v)})
        row = await emp_row(w.cid, eid)
        note("deactivate", http=d1.status_code, db=row, audit=await actions_since(w.cid, n4))
        d2 = await client.delete(f"/v1/employees/{eid}", headers={**hr, "If-Match": str(v)})
        note("deactivate again with the old version", http=d2.status_code)
        if d1.status_code != 200 or row["is_active"] or row["deleted_at"] is not None or d2.status_code != 409:
            problems.append("deactivate semantics")
        v = (await emp_row(w.cid, eid))["version"]
        re = await client.patch(f"/v1/employees/{eid}", headers={**hr, "If-Match": str(v)}, json={"is_active": True})
        note("reactivate", http=re.status_code, db=await emp_row(w.cid, eid))

        # confirmation (PROBATION -> ACTIVE) is one-way
        v = (await emp_row(w.cid, eid))["version"]
        n_c = await n_audit(w.cid)
        cf = await client.post(f"/v1/employees/{eid}/confirm", headers={**hr, "If-Match": str(v)}, json={})
        note("confirm", http=cf.status_code, db=await emp_row(w.cid, eid), audit=await actions_since(w.cid, n_c))
        if cf.status_code != 200 or (await emp_row(w.cid, eid))["status"] != "ACTIVE" or "EMPLOYEE_CONFIRMED" not in await actions_since(w.cid, n_c):
            problems.append("confirm did not produce ACTIVE + audit row")

        # linked records, then terminate
        admin = w.h("ADMIN")
        for hh, d in ((9, "IN"), (18, "OUT")):
            pr = await client.post("/v1/attendance/punches", headers=admin, json={"employee_id": eid, "punch_time": f"2026-09-08T{hh:02d}:00:00Z", "direction": d, "reference": "b11"})
            assert pr.status_code == 201, pr.text
        await client.post("/v1/attendance/days/calculate", headers=admin, params={"employee_id": eid, "date": "2026-09-08"})
        from tests.integration.modules.payroll.test_pay_run import _CTC
        for url, body in ((f"/v1/employees/{eid}/compensation", {"effective_from": "2026-01-01", "annual_ctc_minor": _CTC, "currency": "INR", "revision_type": "JOINING", "revision_reason": "b11"}),
                          (f"/v1/employees/{eid}/bank", {"effective_from": "2026-01-01", "account_holder_name": "Synthetic", "account_number_enc": "123456789012", "bank_name": "State Bank", "ifsc": "SBIN0001234", "payment_mode": "BANK"})):
            rr = await client.post(url, headers=hr, json=body)
            assert rr.status_code == 201, (url, rr.text)
        linked = ("punch", "attendance_day", "employee_bank", "employee_compensation", "employee_assignment", "leave_ledger", "employee_document", "onboarding_case", "account_invite")
        before = await company_counts(w.cid)
        n5 = await n_audit(w.cid)
        t = await client.post(f"/v1/employees/{eid}/employments/{emp_id}/terminate", headers={**hr, "If-Match": str(emp_ver)}, json={"last_working_day": "2026-12-31"})
        after = await company_counts(w.cid)
        closed = await q("SELECT count(*) n FROM employee_compensation WHERE company_id = :c AND employee_id = CAST(:e AS uuid) AND effective_to IS NOT NULL", c=str(w.cid), e=eid)
        open_asg = await q("SELECT effective_to::text t FROM employee_assignment WHERE company_id = :c AND employee_id = CAST(:e AS uuid) AND effective_from = '2026-07-01'", c=str(w.cid), e=eid)
        note("terminate", http=t.status_code, body=t.json().get("data", {}).get("status"), linked_counts_before_after={k: [before.get(k), after.get(k)] for k in linked},
             compensation_rows_closed=closed[0]["n"], current_assignment_effective_to=open_asg[0]["t"], audit=await actions_since(w.cid, n5))
        assert t.status_code == 200, t.text
        changed_linked = {k: (before[k], after[k]) for k in linked if before.get(k) != after.get(k)}
        if changed_linked:
            problems.append(f"terminate changed linked history rows: {changed_linked}")
        if open_asg[0]["t"] != "2026-12-31" or closed[0]["n"] != 1:
            problems.append(f"terminate did not close assignment/compensation as designed: {open_asg} {closed}")
        if "EMPLOYMENT_TERMINATED" not in await actions_since(w.cid, n5):
            problems.append("no EMPLOYMENT_TERMINATED audit row")

        # out-of-order after termination
        for label, req in (
            ("terminate again", client.post(f"/v1/employees/{eid}/employments/{emp_id}/terminate", headers={**hr, "If-Match": str(t.json()["data"]["version"])}, json={"last_working_day": "2027-01-31"})),
            ("update terminated employment", client.patch(f"/v1/employees/{eid}/employments/{emp_id}", headers={**hr, "If-Match": str(t.json()["data"]["version"])}, json={"probation_end_date": "2026-04-01"})),
            ("terminate unknown employment", client.post(f"/v1/employees/{eid}/employments/{uuid4()}/terminate", headers={**hr, "If-Match": "1"}, json={"last_working_day": "2027-01-31"})),
            ("terminate before joining date", client.post(f"/v1/employees/{eid}/employments/{emp_id}/terminate", headers={**hr, "If-Match": "1"}, json={"last_working_day": "2025-01-01"})),
            ("confirm again (already ACTIVE)", client.post(f"/v1/employees/{eid}/confirm", headers={**hr, "If-Match": str((await emp_row(w.cid, eid))["version"])}, json={})),
        ):
            b = await company_counts(w.cid)
            resp = await req
            ch = diff(b, await company_counts(w.cid), NOIGNORE)
            note(f"out-of-order: {label}", http=resp.status_code, code=(resp.json().get("error") or {}).get("code"), changed=sorted(ch))
            if resp.status_code < 400 or ch:
                problems.append(f"{label}: {resp.status_code} {sorted(ch)}")
        note("employee row after termination (observation)", db=await emp_row(w.cid, eid))
        rec(c, "HR_ADMIN lifecycle", steps=steps, problems=problems)
        assert not problems, problems
    finally:
        await drop_world(w, monkeypatch)


# ----------------------------------------------------------------------------------------------------------------------
EMP_OPS = {
    "view": ("EMPLOYEE.VIEW", lambda c, h, t: c.get(f"/v1/employees/{t}", headers=h)),
    "patch": ("EMPLOYEE.UPDATE", lambda c, h, t: c.patch(f"/v1/employees/{t}", headers={**h, "If-Match": "1"}, json={"first_name": "Hacked"})),
    "deactivate": ("EMPLOYEE.DEACTIVATE", lambda c, h, t: c.delete(f"/v1/employees/{t}", headers={**h, "If-Match": "1"})),
    "create_employment": ("EMPLOYEE.CREATE", lambda c, h, t: c.post(f"/v1/employees/{t}/employments", headers=h, json={"legal_entity_id": str(uuid4()), "joining_date": "2026-02-01"})),
    "terminate": ("EMPLOYEE.TERMINATE", lambda c, h, t: c.post(f"/v1/employees/{t}/employments/{uuid4()}/terminate", headers={**h, "If-Match": "1"}, json={"last_working_day": "2026-12-31"})),
    "invite": ("EMPLOYEE.INVITE", lambda c, h, t: c.post(f"/v1/employees/{t}/invite", headers=h)),
    "view_compensation": ("EMPLOYEE.VIEW_COMPENSATION", lambda c, h, t: c.get(f"/v1/employees/{t}/compensation", headers=h)),
    "view_bank": ("EMPLOYEE.VIEW_BANKING", lambda c, h, t: c.get(f"/v1/employees/{t}/bank", headers=h)),
    "revise_bank": ("EMPLOYEE.UPDATE_SENSITIVE", lambda c, h, t: c.post(f"/v1/employees/{t}/bank", headers=h, json={"effective_from": "2026-10-01", "account_holder_name": "X", "account_number_enc": "999999999999", "bank_name": "B", "ifsc": "SBIN0009999", "payment_mode": "BANK"})),
    "list_assignments": ("EMPLOYEE.VIEW", lambda c, h, t: c.get(f"/v1/employees/{t}/assignments", headers=h)),
    "add_assignment": (None, lambda c, h, t: c.post(f"/v1/employees/{t}/assignments", headers=h, json={"effective_from": "2026-10-01", "change_type": "MANAGER_CHANGE"})),
}


async def test_authorization_and_scope_per_principal(client, seeded_plan_catalogue, monkeypatch):
    c = "B11-EMP-ISO"
    w = await build_world(client)
    try:
        await switch_role(monkeypatch, "app")
        problems, rows = [], []
        targets = {"E1": w.eid("E1"), "E2": w.eid("E2"), "E3": w.eid("E3")}
        for who in ("E1", "E2", "M1", "BX", "HR"):
            sc = await scopes_of(w, who)
            for op, (perm, fn) in EMP_OPS.items():
                for tkey, tid in targets.items():
                    levels = sc.get(perm) if perm else None
                    if perm is None:                            # assignment create: permission decided inside the handler -> only assert "no unscoped write"
                        expected = "any"
                    elif not levels:
                        expected = "deny403"
                    else:
                        vis = expected_visible(w, who, levels)
                        expected = "allowed" if vis is None or tid in vis else "hidden404"
                    before = await company_counts(w.cid)
                    r = await fn(client, w.h(who), tid)
                    ch = diff(before, await company_counts(w.cid), NOIGNORE)
                    ok = {"deny403": r.status_code == 403 and not ch, "hidden404": r.status_code == 404 and not ch,
                          "allowed": r.status_code not in (401, 403, 404) or r.status_code == 404 and op in ("terminate",), "any": True}[expected]
                    if expected == "any" and r.status_code < 400 and who not in ("HR",) and tkey != "E1":
                        ok = False
                    rows.append({"who": who, "op": op, "target": tkey, "expected": expected, "status": r.status_code, "changed": sorted(ch), "ok": ok})
                    if not ok:
                        problems.append(f"{who} {op} -> {tkey}: expected {expected}, got {r.status_code}, changed {sorted(ch)}")
        # list vs direct-object, and scope smuggling on the list
        lists = {}
        for who in ("M1", "BX", "HR", "E1"):
            sc = await scopes_of(w, who)
            r = await client.get("/v1/employees", headers=w.h(who), params={"limit": 100})
            rs = await client.get("/v1/employees", headers=w.h(who), params={"limit": 100, "employee_id": w.eid("E3"), "branch_id": w.branch_y, "reporting_manager_id": w.eid("M2")})
            got = {x["id"] for x in r.json().get("data", [])} if r.status_code == 200 else set()
            got_s = {x["id"] for x in rs.json().get("data", [])} if rs.status_code == 200 else set()
            levels = sc.get("EMPLOYEE.VIEW_ALL")
            vis = expected_visible(w, who, levels) if levels else None
            lists[who] = {"status": r.status_code, "n": len(got), "smuggled_params_status": rs.status_code, "smuggled_has_E3": w.eid("E3") in got_s, "levels": sorted(levels or [])}
            if levels and vis is not None:
                org_ids = {p.employee_id for p in w.people.values() if p.employee_id}
                if (got & org_ids) - vis:
                    problems.append(f"{who}: list leaks {len((got & org_ids) - vis)} out-of-scope employees")
                if w.eid("E3") in got_s and w.eid("E3") not in vis:
                    problems.append(f"{who}: smuggled filter params exposed E3")
            if not levels and r.status_code != 403:
                problems.append(f"{who}: list without EMPLOYEE.VIEW_ALL returned {r.status_code}")
        # other tenant, forged header, anonymous: every op, A's employee id
        tb = w.h("B_ADMIN")
        for op, (perm, fn) in EMP_OPS.items():
            ba, bb = await company_counts(w.cid), await company_counts(w.tb.company_id)
            r = await fn(client, tb, targets["E1"])
            fa, fb = diff(ba, await company_counts(w.cid), NOIGNORE), diff(bb, await company_counts(w.tb.company_id), NOIGNORE)
            rf = await fn(client, {**tb, "X-Company-Id": str(w.cid)}, targets["E1"])
            ra = await fn(client, {}, targets["E1"])
            rows.append({"who": "B_ADMIN", "op": op, "status": r.status_code, "forged_header": rf.status_code, "anon": ra.status_code, "A_changed": sorted(fa), "B_changed": sorted(fb)})
            if r.status_code != 404 or fa or fb or rf.status_code not in (401, 403, 404) or ra.status_code != 401:
                problems.append(f"{op}: other tenant {r.status_code}/{sorted(fa)}/{sorted(fb)}, forged {rf.status_code}, anon {ra.status_code}")
        rec(c, "authorization and scope", n=len(rows), rows=rows, lists=lists, problems=problems)
        assert not problems, problems
    finally:
        await drop_world(w, monkeypatch)


# ----------------------------------------------------------------------------------------------------------------------
async def test_concurrent_lifecycle_transitions(client, seeded_plan_catalogue, monkeypatch):
    c = "B11-EMP-CONC"
    w = await build_world(client)
    try:
        hr = w.h("HR")
        ox = await org_for(client, w, w.branch_x)
        await switch_role(monkeypatch, "app")
        res = {}
        # parallel creation of one employment episode
        r = await client.post("/v1/employees", headers=hr, json={"first_name": "Conc", "personal_email": f"conc-{uuid4().hex[:6]}@personal.example"})
        eid = r.json()["data"]["id"]
        rs = await asyncio.gather(*[client.post(f"/v1/employees/{eid}/employments", headers=hr, json={"legal_entity_id": w.le, "joining_date": "2026-01-01"}) for _ in range(8)], return_exceptions=True)
        res["parallel employments"] = sorted(str(getattr(x, "status_code", repr(x))) for x in rs)
        res["active employments"] = (await q("SELECT count(*) n FROM employment WHERE company_id = :c AND employee_id = CAST(:e AS uuid) AND status = 'ACTIVE'", c=str(w.cid), e=eid))[0]["n"]
        emp = (await q("SELECT id::text i, version v FROM employment WHERE company_id = :c AND employee_id = CAST(:e AS uuid) AND status = 'ACTIVE'", c=str(w.cid), e=eid))[0]
        # parallel identical assignments
        rs = await asyncio.gather(*[client.post(f"/v1/employees/{eid}/assignments", headers=hr, json={"effective_from": "2026-01-01", "change_type": "INITIAL", **ox}) for _ in range(8)], return_exceptions=True)
        res["parallel assignments"] = sorted(str(getattr(x, "status_code", repr(x))) for x in rs)
        res["open assignments"] = (await q("SELECT count(*) n FROM employee_assignment WHERE company_id = :c AND employee_id = CAST(:e AS uuid) AND effective_to IS NULL", c=str(w.cid), e=eid))[0]["n"]
        # parallel terminate with the same version token
        rs = await asyncio.gather(*[client.post(f"/v1/employees/{eid}/employments/{emp['i']}/terminate", headers={**hr, "If-Match": str(emp["v"])}, json={"last_working_day": "2026-12-31"}) for _ in range(8)], return_exceptions=True)
        res["parallel terminate"] = sorted(str(getattr(x, "status_code", repr(x))) for x in rs)
        res["audit EMPLOYMENT_TERMINATED rows"] = (await q("SELECT count(*) n FROM audit_log WHERE company_id = :c AND action = 'EMPLOYMENT_TERMINATED' AND entity_id = CAST(:i AS uuid)", c=str(w.cid), i=emp["i"]))[0]["n"]
        # parallel deactivate with the same token
        v = (await emp_row(w.cid, eid))["version"]
        rs = await asyncio.gather(*[client.delete(f"/v1/employees/{eid}", headers={**hr, "If-Match": str(v)}) for _ in range(8)], return_exceptions=True)
        res["parallel deactivate"] = sorted(str(getattr(x, "status_code", repr(x))) for x in rs)
        rec(c, "concurrency", results=res)
        assert res["parallel employments"].count("201") == 1 and res["active employments"] == 1, res
        assert res["parallel assignments"].count("201") == 1 and res["open assignments"] == 1, res
        assert res["parallel terminate"].count("200") == 1 and res["audit EMPLOYMENT_TERMINATED rows"] == 1, res
        assert res["parallel deactivate"].count("200") == 1, res
    finally:
        await drop_world(w, monkeypatch)


async def test_audit_failure_during_terminate_leaves_no_partial_state(client, seeded_plan_catalogue, monkeypatch):
    from hrms.core.audit.service import AuditService
    c = "B11-EMP-FAIL"
    w = await build_world(client)
    try:
        hr = w.h("HR")
        ox = await org_for(client, w, w.branch_x)
        await switch_role(monkeypatch, "app")
        eid = (await client.post("/v1/employees", headers=hr, json={"first_name": "Fail", "personal_email": f"f-{uuid4().hex[:6]}@personal.example"})).json()["data"]["id"]
        em = (await client.post(f"/v1/employees/{eid}/employments", headers=hr, json={"legal_entity_id": w.le, "joining_date": "2026-01-01"})).json()["data"]
        assert (await client.post(f"/v1/employees/{eid}/assignments", headers=hr, json={"effective_from": "2026-01-01", "change_type": "INITIAL", **ox})).status_code == 201
        from tests.integration.modules.payroll.test_pay_run import _CTC
        assert (await client.post(f"/v1/employees/{eid}/compensation", headers=hr, json={"effective_from": "2026-01-01", "annual_ctc_minor": _CTC, "currency": "INR", "revision_type": "JOINING", "revision_reason": "b11"})).status_code == 201
        original = AuditService.record
        armed = {"on": True, "hits": 0}

        async def flaky(self, *a, **kw):
            if armed["on"] and kw.get("action") == "EMPLOYMENT_TERMINATED":
                armed["hits"] += 1
                raise RuntimeError("injected audit failure")
            return await original(self, *a, **kw)

        monkeypatch.setattr(AuditService, "record", flaky)
        before = await company_counts(w.cid)
        try:
            r = await client.post(f"/v1/employees/{eid}/employments/{em['id']}/terminate", headers={**hr, "If-Match": str(em["version"])}, json={"last_working_day": "2026-12-31"})
            status = r.status_code
        except Exception as exc:  # noqa: BLE001
            status = f"raised {type(exc).__name__}"
        state = {
            "http": status, "audit_hits": armed["hits"], "tables_changed": sorted(diff(before, await company_counts(w.cid), NOIGNORE)),
            "employment": (await q("SELECT status, last_working_day::text l FROM employment WHERE id = CAST(:i AS uuid) AND company_id = :c", i=em["id"], c=str(w.cid)))[0],
            "open_assignments": (await q("SELECT count(*) n FROM employee_assignment WHERE company_id = :c AND employee_id = CAST(:e AS uuid) AND effective_to IS NULL", c=str(w.cid), e=eid))[0]["n"],
            "open_compensation": (await q("SELECT count(*) n FROM employee_compensation WHERE company_id = :c AND employee_id = CAST(:e AS uuid) AND effective_to IS NULL", c=str(w.cid), e=eid))[0]["n"],
        }
        armed["on"] = False
        ok = await client.post(f"/v1/employees/{eid}/employments/{em['id']}/terminate", headers={**hr, "If-Match": str(em["version"])}, json={"last_working_day": "2026-12-31"})
        state["retry_http"] = ok.status_code
        rec(c, "audit failure during terminate", results=state)
        assert state["tables_changed"] == [] and state["employment"]["status"] == "ACTIVE" and state["open_assignments"] == 1 and state["open_compensation"] == 1, state
        assert state["retry_http"] == 200, state
    finally:
        await drop_world(w, monkeypatch)


# ----------------------------------------------------------------------------------------------------------------------
async def test_hr_admin_ceiling_on_runtime_routes(client, seeded_plan_catalogue, monkeypatch):
    c = "B11-PERM-HR"
    w = await build_world(client)
    try:
        inv = route_inventory()
        restricted = {"PAYROLL.RUN_APPROVE", "PAYROLL.BANK_ADVICE_DOWNLOAD", "SETTINGS.USER.MANAGE", "SETTINGS.ROLE.MANAGE", "ORG.COMPANY.MANAGE", "ORG.BRANCH.MANAGE", "ATTENDANCE.LOCK", "ATTENDANCE.UNLOCK", "ATTENDANCE.POLICY_MANAGE"}
        allowed_reads = {"ATTENDANCE.VIEW", "ATTENDANCE.VIEW_ALL", "ONBOARDING.VIEW"}
        held = await perms_of(w, "HR")
        await switch_role(monkeypatch, "app")
        hr = w.h("HR")
        problems, rows = [], []
        for r in inv:
            if not r["perm"] or r["platform"]:
                continue
            need = set(r["perm"])
            if need & restricted and not (need <= held):
                before = await company_counts(w.cid)
                resp = await client.request(r["method"], fill(r["path"]), headers=hr, json={} if r["method"] != "GET" else None)
                ch = diff(before, await company_counts(w.cid), NOIGNORE)
                rows.append({"op": f"{r['method']} {r['path']}", "needs": sorted(need), "status": resp.status_code, "changed": sorted(ch)})
                if resp.status_code != 403 or ch:
                    problems.append(f"{r['method']} {r['path']}: {resp.status_code} {sorted(ch)}")
            elif r["method"] == "GET" and need <= allowed_reads and need <= held and "{" not in r["path"]:
                resp = await client.get(r["path"], headers=hr)
                rows.append({"op": f"GET {r['path']}", "needs": sorted(need), "status": resp.status_code})
                if resp.status_code in (401, 403):
                    problems.append(f"HR_ADMIN denied an approved read {r['path']}: {resp.status_code}")
        # escalation to COMPANY_ADMIN: invite, assign, self-assign
        esc = {}
        before = await company_counts(w.cid)
        inv_r = await client.post("/v1/users/invite", headers=hr, json={"email": f"esc-{uuid4().hex[:6]}@example.com", "role_code": "COMPANY_ADMIN"})
        esc["invite COMPANY_ADMIN"] = inv_r.status_code
        asg = await client.patch(f"/v1/users/{w.people['E1'].user_id}/roles", headers=hr, json={"role_codes": ["COMPANY_ADMIN"]})
        esc["assign COMPANY_ADMIN to an employee"] = asg.status_code
        selfr = await client.patch(f"/v1/users/{w.people['HR'].user_id}/roles", headers=hr, json={"role_codes": ["COMPANY_ADMIN"]})
        esc["HR_ADMIN self-assigns COMPANY_ADMIN"] = selfr.status_code
        emp_inv = await client.post(f"/v1/employees/{w.eid('E1')}/invite", headers=hr)
        esc["employee invite for an employee that already has a login (role is always EMPLOYEE)"] = emp_inv.status_code
        esc["tables changed by the three escalation attempts"] = sorted(diff(before, await company_counts(w.cid), NOIGNORE))
        roles_after = await scopes_of(w, "E1")
        esc["E1 now holds user/role administration"] = bool({"SETTINGS.USER.MANAGE", "SETTINGS.ROLE.MANAGE"} & set(roles_after))
        for k in ("invite COMPANY_ADMIN", "assign COMPANY_ADMIN to an employee", "HR_ADMIN self-assigns COMPANY_ADMIN"):
            if esc[k] not in (403, 404, 409, 422):
                problems.append(f"escalation {k}: {esc[k]}")
        if esc["E1 now holds user/role administration"]:
            problems.append("E1 gained administration rights")
        rec(c, "HR_ADMIN ceiling", restricted_routes_probed=len([x for x in rows if "needs" in x and set(x['needs']) & restricted]), rows=rows, escalation=esc, problems=problems)
        assert not problems, problems
    finally:
        await drop_world(w, monkeypatch)


async def test_confirm_after_termination_is_refused(client, seeded_plan_catalogue, monkeypatch):
    """A terminated employee still on PROBATION must not be confirmable (a one-way PROBATION -> ACTIVE transition on a person who has left)."""
    c = "B11-EMP-ORDER"
    w = await build_world(client)
    try:
        hr = w.h("HR")
        await switch_role(monkeypatch, "app")
        eid = (await client.post("/v1/employees", headers=hr, json={"first_name": "Left", "personal_email": f"l-{uuid4().hex[:6]}@personal.example"})).json()["data"]["id"]
        em = (await client.post(f"/v1/employees/{eid}/employments", headers=hr, json={"legal_entity_id": w.le, "joining_date": "2026-01-01"})).json()["data"]
        t = await client.post(f"/v1/employees/{eid}/employments/{em['id']}/terminate", headers={**hr, "If-Match": str(em["version"])}, json={"last_working_day": "2026-03-31"})
        assert t.status_code == 200, t.text
        before_row = await emp_row(w.cid, eid)
        n = await n_audit(w.cid)
        cf = await client.post(f"/v1/employees/{eid}/confirm", headers={**hr, "If-Match": str(before_row["version"])}, json={})
        after_row = await emp_row(w.cid, eid)
        rec(c, "confirm after termination", employee_before=before_row, confirm_http=cf.status_code, employee_after=after_row, audit=await actions_since(w.cid, n))
        assert cf.status_code >= 400 and after_row["status"] == before_row["status"], (cf.status_code, before_row, after_row)
    finally:
        await drop_world(w, monkeypatch)
