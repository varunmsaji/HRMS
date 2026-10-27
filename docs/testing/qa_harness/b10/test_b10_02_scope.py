"""B10-2: DATA-SCOPE contract with real records, as the runtime role hrms_app.

A permission gate is not enough: for every scope-bearing route the set of records returned/acted on must be limited to the caller's
permitted employees.  Oracle (RBAC_DATA_SCOPE_DECISIONS.md + EmployeeService.resolve_visible_employee_ids): SELF -> own; REPORTEES /
REPORTEE_TREE -> reportees (not self); BRANCH -> employees whose current assignment branch is the caller's; COMPANY -> all; grants of one
permission from several roles are unioned.  Out-of-scope DIRECT-OBJECT access must not return 200 (not even an empty 200), and lists
must not contain out-of-scope employees.  Every denial is followed by a database comparison.
"""
import pytest
from world import (build_world, company_counts, diff, drop_world, expected_visible, q, rec, scopes_of, seed_all, switch_role, DAY)

pytestmark = pytest.mark.asyncio
ALL = ["M1", "M2", "BX", "BY", "E1", "E2", "E3"]


async def vis(w, who: str, perm: str):
    """'NOPERM' | None (company) | set of employee ids"""
    sc = (await scopes_of(w, who)).get(perm)
    if not sc:
        return "NOPERM"
    return expected_visible(w, who, sc)


def ids_in(rows: list[dict], key: str = "employee_id") -> set[str]:
    return {r[key] for r in rows if isinstance(r, dict) and r.get(key)}


async def get(client, w, who, path, **params):
    r = await client.get(path, headers=w.h(who), params=params or None)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return r.status_code, body


def leak(expected, got: set[str]) -> set[str]:
    return set() if expected is None else got - expected


# ----------------------------------------------------------------------------------------------------- DEF-B6-02 and its family
# DEF-B6-02 was a strict xfail until the 2026-10-26 fix (hradm-20261026a): it XPASSed(strict) on the fixed code, then the marker was removed.
# Original reason: GET /v1/attendance-periods/{id}/summary ignored the data scope for every ATTENDANCE.VIEW holder.
async def test_attendance_period_summary_scope_for_every_attendance_view_holder(client, seeded_plan_catalogue, monkeypatch):
    c = "B10-SCOPE-ATT-PERIOD"
    w = await build_world(client)
    try:
        s = await seed_all(client, w)
        pid = s["period_id"]
        await switch_role(monkeypatch, "app")
        res, leaks = {}, {}
        for who in ("E1", "E2", "E3", "BX", "BY", "CUSTV", "CUSTS", "HR", "ADMIN"):
            exp = await vis(w, who, "ATTENDANCE.VIEW")
            st, body = await get(client, w, who, f"/v1/attendance-periods/{pid}/summary")
            if exp == "NOPERM":
                res[who] = {"status": st, "note": "no ATTENDANCE.VIEW (HR_ADMIN holds VIEW_ALL only)"}
                assert st == 403, (who, st)
                continue
            got = ids_in(body.get("data", [])) if st == 200 else set()
            res[who] = {"status": st, "rows": len(got), "expected_visible": "ALL" if exp is None else len(exp), "out_of_scope_rows": sorted(leak(exp, got))}
            if leak(exp, got):
                leaks[who] = len(leak(exp, got))
            lst = await get(client, w, who, "/v1/attendance-periods")
            det = await get(client, w, who, f"/v1/attendance-periods/{pid}")
            res[who]["period_list_status"], res[who]["period_detail_status"] = lst[0], det[0]
        rec(c, "attendance-period summary by principal", results=res, principals_with_out_of_scope_rows=leaks)
        assert not leaks, f"principals receiving other employees' summary rows: {leaks}"
    finally:
        await drop_world(w, monkeypatch)


# ----------------------------------------------------------------------------------------------------- scope-bound attendance reads
async def test_attendance_reads_respect_scope(client, seeded_plan_catalogue, monkeypatch):
    c = "B10-SCOPE-ATT"
    w = await build_world(client)
    try:
        await seed_all(client, w)
        await switch_role(monkeypatch, "app")
        report: dict = {}
        problems: list = []
        days_by_emp = {r["employee_id"]: r["id"] for r in (await client.get("/v1/attendance/days", headers=w.h("ADMIN"))).json()["data"]}
        regs_by_emp = {r["employee_id"]: r["id"] for r in (await client.get("/v1/regularizations", headers=w.h("ADMIN"))).json()["data"]}
        assert len(days_by_emp) >= 4 and len(regs_by_emp) == 2
        for who in ("E1", "E2", "E3", "BX", "BY", "CUSTV", "CUSTS", "HR", "ADMIN"):
            exp = await vis(w, who, "ATTENDANCE.VIEW")
            row: dict = {}
            if exp == "NOPERM":                      # e.g. HR_ADMIN holds ATTENDANCE.VIEW_ALL, not ATTENDANCE.VIEW
                sts = {p_: (await get(client, w, who, p_))[0] for p_ in ("/v1/attendance/punches", "/v1/attendance/days", "/v1/regularizations")}
                report[who] = {"no ATTENDANCE.VIEW": sts}
                problems.extend((who, p_, st) for p_, st in sts.items() if st != 403)
                continue
            for label, path in (("punches", "/v1/attendance/punches"), ("days", "/v1/attendance/days"), ("regularizations", "/v1/regularizations")):
                st, body = await get(client, w, who, path)
                got = ids_in(body.get("data", [])) if st == 200 else set()
                bad = leak(exp, got)
                row[label] = {"status": st, "employees_returned": len(got), "out_of_scope": sorted(bad)}
                if st != 200 or bad:
                    problems.append((who, label, st, sorted(bad)))
                if exp is not None and exp and label != "regularizations":
                    assert got, f"{who} {label}: vacuous - nothing returned although {len(exp)} employees are in scope"
                # filter smuggling: ask explicitly for an out-of-scope employee
                other = next((e for e in ("E3", "E1") if exp is not None and w.eid(e) not in exp), None)
                if other:
                    st2, b2 = await get(client, w, who, path, employee_id=w.eid(other))
                    got2 = ids_in(b2.get("data", [])) if st2 == 200 else set()
                    row[f"{label}_filter_other_employee"] = {"status": st2, "rows": len(got2)}
                    if got2:
                        problems.append((who, f"{label} ?employee_id={other}", st2, sorted(got2)))
            # direct-object access
            d_res = {}
            for emp, did in days_by_emp.items():
                st, body = await get(client, w, who, f"/v1/attendance/days/{did}")
                inscope = exp is None or emp in exp
                d_res[emp[:8]] = (st, inscope)
                if (not inscope and st == 200) or (inscope and st != 200):
                    problems.append((who, "day detail", emp[:8], st, inscope))
            for emp, rid in regs_by_emp.items():
                st, body = await get(client, w, who, f"/v1/regularizations/{rid}")
                inscope = exp is None or emp in exp
                d_res["reg:" + emp[:8]] = (st, inscope)
                if (not inscope and st == 200) or (inscope and st != 200):
                    problems.append((who, "regularization detail", emp[:8], st, inscope))
            row["direct_object"] = d_res
            report[who] = row
        rec(c, "attendance reads by principal", report=report, problems=problems)
        assert not problems, problems
    finally:
        await drop_world(w, monkeypatch)


# ----------------------------------------------------------------------------------------------------- employee directory and sensitive sub-resources
SENSITIVE = [  # (suffix, permission)
    ("", "EMPLOYEE.VIEW"), ("/employments", "EMPLOYEE.VIEW"), ("/assignments", "EMPLOYEE.VIEW"), ("/identity", "EMPLOYEE.VIEW_SENSITIVE"),
    ("/compensation", "EMPLOYEE.VIEW_COMPENSATION"), ("/salary", "EMPLOYEE.VIEW_COMPENSATION"), ("/statutory", "EMPLOYEE.VIEW_STATUTORY"),
    ("/bank", "EMPLOYEE.VIEW_BANKING"), ("/experience", "EMPLOYEE.VIEW_EXPERIENCE"), ("/education", "EMPLOYEE.VIEW_EXPERIENCE"),
    ("/dependents", "EMPLOYEE.VIEW_NOMINEE"), ("/documents", "EMPLOYEE.VIEW_DOCUMENTS"),
]


async def test_employee_records_respect_scope(client, seeded_plan_catalogue, monkeypatch):
    c = "B10-SCOPE-EMP"
    w = await build_world(client)
    try:
        await seed_all(client, w)
        await switch_role(monkeypatch, "app")
        problems: list = []
        report: dict = {}
        # directory list (EMPLOYEE.VIEW_ALL)
        for who in ("M1", "BX", "BY", "E1", "CUSTV", "HR", "ADMIN", "PAY"):
            exp = await vis(w, who, "EMPLOYEE.VIEW_ALL")
            st, body = await get(client, w, who, "/v1/employees")
            if exp == "NOPERM":
                report[f"{who} directory"] = st
                if st != 403:
                    problems.append((who, "directory without permission", st))
                continue
            got = {r["id"] for r in body.get("data", [])} if st == 200 else set()
            report[f"{who} directory"] = {"status": st, "returned": len(got), "out_of_scope": sorted(leak(exp, got))}
            if st != 200 or leak(exp, got):
                problems.append((who, "directory", st, sorted(leak(exp, got))))
            if exp:
                assert got, f"{who}: vacuous directory"
        # per-employee direct-object access
        grid: dict = {}
        for who in ("E1", "E2", "M1", "BX", "BY", "HR", "ADMIN"):
            for suffix, perm in SENSITIVE:
                exp = await vis(w, who, perm)
                for tgt in ("E1", "E2", "E3", "M1"):
                    st, body = await get(client, w, who, f"/v1/employees/{w.eid(tgt)}{suffix}")
                    key = f"{who}|{suffix or '/'}|{tgt}"
                    if exp == "NOPERM":
                        grid[key] = (st, "no-permission")
                        if st != 403:
                            problems.append((key, "expected 403 (no permission)", st))
                    else:
                        inscope = exp is None or w.eid(tgt) in exp
                        grid[key] = (st, "in-scope" if inscope else "OUT-OF-SCOPE")
                        if not inscope and st == 200:
                            problems.append((key, "out-of-scope employee record returned 200", st))
                        if inscope and st != 200:
                            problems.append((key, "in-scope access refused", st))
        # in-scope data really is returned (non-vacuous): E1 reads own compensation / bank / documents with content
        own = {}
        for suffix in ("/compensation", "/bank", "/statutory", "/documents", "/salary"):
            st, body = await get(client, w, "E1", f"/v1/employees/{w.eid('E1')}{suffix}")
            own[suffix] = (st, len(body.get("data", [])) if isinstance(body.get("data"), list) else "obj")
            if suffix != "/salary":
                assert st == 200 and body["data"], (suffix, st)
        rec(c, "employee records by principal", directory=report, own_records=own, cells=len(grid), grid=grid, problems=problems)
        assert not problems, problems
    finally:
        await drop_world(w, monkeypatch)


# ----------------------------------------------------------------------------------------------------- approvals respect scope; denials change nothing
async def test_approvals_respect_scope_and_denials_change_nothing(client, seeded_plan_catalogue, monkeypatch):
    c = "B10-SCOPE-APPROVE"
    w = await build_world(client)
    try:
        s = await seed_all(client, w)
        await switch_role(monkeypatch, "app")
        regs, apps = s["regs"], s["apps"]
        problems, log = [], {}

        async def state():
            return {
                "regs": await q("SELECT id::text id, status, version FROM attendance_regularization_request WHERE company_id = :c ORDER BY id", c=str(w.cid)),
                "reg_actions": (await q("SELECT count(*) n FROM attendance_regularization_action WHERE company_id = :c", c=str(w.cid)))[0]["n"],
                "punches": (await q("SELECT count(*) n FROM punch WHERE company_id = :c", c=str(w.cid)))[0]["n"],
                "apps": await q("SELECT id::text id, status, version FROM leave_application WHERE company_id = :c ORDER BY id", c=str(w.cid)),
                "ledger": (await q("SELECT count(*) n FROM leave_ledger WHERE company_id = :c", c=str(w.cid)))[0]["n"],
                "leave_actions": (await q("SELECT count(*) n FROM leave_application_action WHERE company_id = :c", c=str(w.cid)))[0]["n"],
            }

        before = await state()
        denied_expected = []     # (who, kind, target) where the target is OUT of the caller's scope or the caller lacks the permission
        for kind, perm, objs, base, body in (
            ("regularization", "ATTENDANCE.REGULARIZATION_APPROVE", regs, "/v1/regularizations", {}),
            ("leave", "LEAVE.APPLICATION_APPROVE", apps, "/v1/leave-applications", {}),
        ):
            for who in ("E1", "E2", "M1", "M2", "BX", "BY", "CUSTV", "CUSTS", "PAY"):
                exp = await vis(w, who, perm)
                for tgt, obj in objs.items():
                    for verb in ("approve", "reject"):
                        inscope = exp not in ("NOPERM",) and (exp is None or w.eid(tgt) in exp)
                        if inscope:
                            continue                       # in-scope attempts change state; they are exercised afterwards, one at a time
                        r = await client.post(f"{base}/{obj['id']}/{verb}", headers={**w.h(who), "If-Match": str(obj["version"])}, json={"reviewer_comment": "b10", "rejection_reason": "b10"})
                        denied_expected.append(f"{who} {kind} {verb} {tgt}")
                        log[f"{who}|{kind}|{verb}|{tgt}"] = r.status_code
                        if r.status_code not in (403, 404):
                            problems.append((who, kind, verb, tgt, "out-of-scope/no-permission action answered", r.status_code, r.text[:160]))
        after = await state()
        rec(c, "denied approvals", attempts=len(denied_expected), statuses=log, state_unchanged=before == after, problems=problems)
        assert not problems, problems
        assert before == after, "a denied approve/reject changed requests, actions, punches or the leave ledger"
        # in-scope approvals: M1 approves E1's regularization; M2's reportee E3 request stays untouched
        ok = {}
        r1 = await client.post(f"/v1/regularizations/{regs['E1']['id']}/approve", headers={**w.h("M1"), "If-Match": str(regs["E1"]["version"])}, json={})
        ok["M1 approves E1 regularization"] = r1.status_code
        r3 = await client.post(f"/v1/leave-applications/{apps['E1']['id']}/approve", headers={**w.h("M1"), "If-Match": str(apps["E1"]["version"])}, json={})
        ok["M1 approves E1 leave"] = r3.status_code
        r4 = await client.post(f"/v1/leave-applications/{apps['E3']['id']}/reject", headers={**w.h("BY"), "If-Match": str(apps["E3"]["version"])}, json={"reviewer_comment": "b10", "rejection_reason": "b10 reject"})
        ok["BY (branch Y manager) rejects E3 leave"] = r4.status_code
        e3_reg_status = (await q("SELECT status FROM attendance_regularization_request WHERE id = :i AND company_id = :c", i=regs["E3"]["id"], c=str(w.cid)))[0]["status"]
        a1 = await q("SELECT status FROM leave_application WHERE id = :i AND company_id = :c", i=apps["E1"]["id"], c=str(w.cid))
        a3 = await q("SELECT status FROM leave_application WHERE id = :i AND company_id = :c", i=apps["E3"]["id"], c=str(w.cid))
        audit = await q("SELECT action, actor_user_id::text actor FROM audit_log WHERE company_id = :c AND action ILIKE '%APPROV%' OR action ILIKE '%REJECT%' ORDER BY occurred_at", c=str(w.cid))
        rec(c, "in-scope approvals", results=ok, e3_regularization_status=e3_reg_status, leave_statuses={"E1": a1[0]["status"], "E3": a3[0]["status"]}, audit=audit)
        assert e3_reg_status == "SUBMITTED"
    finally:
        await drop_world(w, monkeypatch)


# ----------------------------------------------------------------------------------------------------- imperative (handler-level) routes
async def test_handler_level_routes_respect_scope(client, seeded_plan_catalogue, monkeypatch):
    c = "B10-SCOPE-IMPERATIVE"
    w = await build_world(client)
    try:
        s = await seed_all(client, w)
        await switch_role(monkeypatch, "app")
        problems, report = [], {}
        # leave applications: list / detail
        for who in ("E1", "E2", "E3", "M1", "M2", "BX", "BY", "HR", "ADMIN", "PAY", "CUSTV"):
            exp_appr = await vis(w, who, "LEAVE.APPLICATION_APPROVE")
            allowed = None if exp_appr is None else (set() if exp_appr == "NOPERM" else set(exp_appr))
            if allowed is not None and w.people[who].employee_id:
                allowed.add(w.people[who].employee_id)                    # own applications are always visible
            st, body = await get(client, w, who, "/v1/leave-applications")
            got = ids_in(body.get("data", [])) if st == 200 else set()
            bad = leak(allowed, got)
            report[f"{who} list"] = {"status": st, "employees": len(got), "out_of_scope": sorted(bad)}
            if st == 200 and bad:
                problems.append((who, "leave-applications list shows out-of-scope employees", sorted(bad)))
            for tgt, obj in s["apps"].items():
                st2, _ = await get(client, w, who, f"/v1/leave-applications/{obj['id']}")
                inscope = allowed is None or w.eid(tgt) in allowed
                report[f"{who} detail {tgt}"] = (st2, inscope)
                if st2 == 200 and not inscope:
                    problems.append((who, f"leave application of {tgt} returned 200 out of scope"))
            # balances / ledger for another employee
            for tgt in ("E1", "E3"):
                for path in ("/v1/leave-balances", "/v1/leave-ledger"):
                    stb, bb = await get(client, w, who, path, employee_id=w.eid(tgt))
                    exp_b = await vis(w, who, "LEAVE.BALANCE_VIEW_ALL")
                    allowed_b = None if exp_b is None else (set() if exp_b == "NOPERM" else set(exp_b))
                    if allowed_b is not None and w.people[who].employee_id:
                        allowed_b.add(w.people[who].employee_id)
                    inscope = allowed_b is None or w.eid(tgt) in allowed_b
                    data = bb.get("data", []) if stb == 200 else []
                    report[f"{who} {path} for {tgt}"] = (stb, len(data), inscope)
                    if not inscope and stb == 200 and data:
                        problems.append((who, f"{path} for {tgt} returned data out of scope", len(data)))
        # on-behalf creation and cross-employee writes must be refused and write nothing
        before = {k: v for k, v in (await company_counts(w.cid)).items()}
        attempts = {
            "E1 leave application for E2": ("POST", "/v1/leave-applications", w.h("E1"), {"leave_type_id": s["leave_type"], "start_date": "2026-09-22", "end_date": "2026-09-22", "employee_id": w.eid("E2"), "reason": "b10"}),
            "E1 regularization for E2": ("POST", "/v1/regularizations", w.h("E1"), {"employee_id": w.eid("E2"), "attendance_date": "2026-09-10", "request_type": "FULL_DAY", "reason": "b10", "requested_punches": [{"direction": "IN", "requested_time": "2026-09-10T09:00:00Z"}, {"direction": "OUT", "requested_time": "2026-09-10T18:00:00Z"}]}),
            "E2 cancels E1's regularization": ("POST", f"/v1/regularizations/{s['regs']['E1']['id']}/cancel", w.h("E2"), {}),
            "E2 cancels E1's leave": ("POST", f"/v1/leave-applications/{s['apps']['E1']['id']}/cancel", w.h("E2"), {}),
            "M1 cancels E3's leave": ("POST", f"/v1/leave-applications/{s['apps']['E3']['id']}/cancel", w.h("M1"), {}),
            "M1 transfers E1 (assignment)": ("POST", f"/v1/employees/{w.eid('E1')}/assignments", w.h("M1"), {"effective_from": "2026-10-01", "change_type": "TRANSFER", "branch_id": w.branch_y}),
            "BX promotes E1 (assignment)": ("POST", f"/v1/employees/{w.eid('E1')}/assignments", w.h("BX"), {"effective_from": "2026-10-01", "change_type": "PROMOTION"}),
            "E1 policy assignment": ("POST", "/v1/policy-assignments", w.h("E1"), {"policy_kind": "ATTENDANCE_POLICY", "policy_id": s["leave_type"], "scope_type": "COMPANY", "effective_from": "2026-10-01"}),
            "M1 policy assignment (leave)": ("POST", "/v1/policy-assignments", w.h("M1"), {"policy_kind": "LEAVE_POLICY", "policy_id": s["leave_type"], "leave_type_id": s["leave_type"], "scope_type": "COMPANY", "effective_from": "2026-10-01"}),
        }
        res = {}
        for label, (m, path, hh, body) in attempts.items():
            hh2 = {**hh, **({"If-Match": "1", "Idempotency-Key": f"b10-{abs(hash(label))}-001"} if m == "POST" else {})}
            r = await client.request(m, path, headers=hh2, json=body)
            res[label] = r.status_code
            if r.status_code < 400 or r.status_code >= 500:
                problems.append((label, "was not refused", r.status_code, r.text[:200]))
        after = await company_counts(w.cid)
        res["tables_changed_by_the_refused_writes"] = diff(before, after)
        problems_tables = diff(before, after)
        if problems_tables:
            problems.append(("refused writes changed data", problems_tables))
        # read-only GETs of handler-level routes by a user without any employee link
        pay_leave = (await get(client, w, "PAY", "/v1/leave-applications"))[0], (await get(client, w, "PAY", "/v1/leave-balances", employee_id=w.eid("E1")))[0]
        res["PAY (no employee link) leave list / balances"] = pay_leave
        rec(c, "handler-level routes", report=report, refused_writes=res, problems=problems)
        assert not problems, problems
    finally:
        await drop_world(w, monkeypatch)


# ----------------------------------------------------------------------------------------------------- cross-tenant with real identifiers
async def test_cross_tenant_real_identifiers(client, seeded_plan_catalogue, monkeypatch):
    c = "B10-SCOPE-TENANT"
    w = await build_world(client)
    try:
        s = await seed_all(client, w)
        docs = (await client.get(f"/v1/employees/{w.eid('E1')}/documents", headers=w.h("ADMIN"))).json()["data"]
        day_id = (await client.get("/v1/attendance/days", headers=w.h("ADMIN"))).json()["data"][0]["id"]
        await switch_role(monkeypatch, "app")
        before = await company_counts(w.cid)
        h = w.h("B_ADMIN")
        e1 = w.eid("E1")
        probes = {
            "attendance period detail": ("GET", f"/v1/attendance-periods/{s['period_id']}", None),
            "attendance period summary": ("GET", f"/v1/attendance-periods/{s['period_id']}/summary", None),
            "attendance day": ("GET", f"/v1/attendance/days/{day_id}", None),
            "regularization": ("GET", f"/v1/regularizations/{s['regs']['E1']['id']}", None),
            "regularization approve": ("POST", f"/v1/regularizations/{s['regs']['E1']['id']}/approve", {}),
            "leave application": ("GET", f"/v1/leave-applications/{s['apps']['E1']['id']}", None),
            "leave approve": ("POST", f"/v1/leave-applications/{s['apps']['E1']['id']}/approve", {}),
            "employee": ("GET", f"/v1/employees/{e1}", None),
            "compensation": ("GET", f"/v1/employees/{e1}/compensation", None),
            "bank": ("GET", f"/v1/employees/{e1}/bank", None),
            "documents": ("GET", f"/v1/employees/{e1}/documents", None),
            "document delete": ("DELETE", f"/v1/employees/{e1}/documents/{docs[0]['id']}", None),
            "assignment create": ("POST", f"/v1/employees/{e1}/assignments", {"effective_from": "2026-10-01", "change_type": "TRANSFER"}),
        }
        res, problems = {}, []
        for label, (m, path, body) in probes.items():
            kw = {"headers": {**h, "If-Match": "1"}}
            if body is not None:
                kw["json"] = body
            r = await client.request(m, path, **kw)
            res[label] = r.status_code
            if r.status_code != 404:
                problems.append((label, r.status_code, r.text[:160]))
        lists = {}
        for path in ("/v1/attendance/punches", "/v1/attendance/days", "/v1/regularizations", "/v1/leave-applications", "/v1/employees", "/v1/leave-projections", "/v1/overtime"):
            st, body = await get(client, w, "B_ADMIN", path)
            n = len(body.get("data", [])) if st == 200 else None
            lists[path] = (st, n)
            if st == 200 and n:
                mine = {r_.get("employee_id") or r_.get("id") for r_ in body["data"]}
                if mine & {w.eid(x) for x in ALL}:
                    problems.append((path, "tenant B list contains tenant A employees"))
        after = await company_counts(w.cid)
        rec(c, "tenant B admin against tenant A identifiers (hrms_app)", probes=res, lists=lists, tenant_a_unchanged=diff(before, after) == {}, problems=problems)
        assert not problems, problems
        assert diff(before, after) == {}
    finally:
        await drop_world(w, monkeypatch)


# ----------------------------------------------------------------------------------------------------- approver scope for regularization (BRANCH vs REPORTEE_TREE), stale versions, repeat approvals
async def test_regularization_approver_scope_branch_stale_and_repeat(client, seeded_plan_catalogue, monkeypatch):
    c = "B10-SCOPE-REG-APPROVER"
    w = await build_world(client)
    try:
        s = await seed_all(client, w)
        h = w.h("ADMIN")
        day = "2026-09-10"
        await client.post("/v1/attendance/punches", headers=h, json={"employee_id": w.eid("E2"), "punch_time": f"{day}T09:00:00Z", "direction": "IN", "reference": "b10"})
        mk = await client.post("/v1/regularizations", headers=w.h("E2"), json={"employee_id": w.eid("E2"), "attendance_date": day, "request_type": "MISSING_PUNCH", "reason": "b10",
                               "requested_punches": [{"direction": "OUT", "requested_time": f"{day}T18:00:00Z"}]})
        assert mk.status_code == 201, mk.text
        req = mk.json()["data"]
        await switch_role(monkeypatch, "app")

        async def snap():
            r = (await q("SELECT status, version FROM attendance_regularization_request WHERE id = :i AND company_id = :c", i=req["id"], c=str(w.cid)))[0]
            return dict(r), (await q("SELECT count(*) n FROM punch WHERE company_id = :c", c=str(w.cid)))[0]["n"], (await q("SELECT count(*) n FROM attendance_regularization_action WHERE request_id = :i AND company_id = :c", i=req["id"], c=str(w.cid)))[0]["n"]

        base = await snap()
        out = {}
        # wrong branch / wrong manager / no permission: refused, nothing changes
        for who in ("BY", "M2", "E1", "E3", "CUSTV"):
            r = await client.post(f"/v1/regularizations/{req['id']}/approve", headers={**w.h(who), "If-Match": str(req["version"])}, json={})
            out[f"{who} approves E2's request"] = r.status_code
            assert r.status_code in (403, 404), (who, r.status_code)
        assert await snap() == base
        # stale version from an in-scope approver: 409, nothing changes
        stale = await client.post(f"/v1/regularizations/{req['id']}/approve", headers={**w.h("M1"), "If-Match": str(req["version"] + 5)}, json={})
        out["M1 approves with a stale If-Match"] = stale.status_code
        assert stale.status_code == 409 and await snap() == base
        # branch manager of E2's branch (not the line manager): record what the system does
        bx = await client.post(f"/v1/regularizations/{req['id']}/approve", headers={**w.h("BX"), "If-Match": str(req["version"])}, json={})
        out["BX (branch X manager, not E2's line manager) approves"] = bx.status_code
        after_bx = await snap()
        if bx.status_code == 200:
            ok_first = "BX"
        else:
            m1 = await client.post(f"/v1/regularizations/{req['id']}/approve", headers={**w.h("M1"), "If-Match": str(req["version"])}, json={})
            out["M1 (line manager) approves"] = m1.status_code
            assert m1.status_code == 200, m1.text
            ok_first = "M1"
        done = await snap()
        # repeat approval by anyone: refused, no second punch, no second action
        again = await client.post(f"/v1/regularizations/{req['id']}/approve", headers={**w.h("M1"), "If-Match": str(done[0]["version"])}, json={})
        out["second approval"] = again.status_code
        final = await snap()
        rec(c, "regularization approver scope", results=out, first_successful_approver=ok_first, before=base, after_first=done, after_repeat=final)
        assert again.status_code in (409, 422) and final == done
        assert done[1] == base[1] + 1, "approval must add exactly one punch"
    finally:
        await drop_world(w, monkeypatch)
