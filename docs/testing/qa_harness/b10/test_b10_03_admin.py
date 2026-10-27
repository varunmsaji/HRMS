"""B10-3: administrative / sensitive WRITE routes with valid bodies, denied principals must be refused (403/404) with NO effect at all
(every company table incl. audit_log and idempotency_key unchanged); privilege-escalation attempts; onboarding; read-only routes that write."""
import pytest
from world import (build_world, company_counts, diff, drop_world, perms_of, q, rec, seed_all, switch_role)

pytestmark = pytest.mark.asyncio
STRICT = frozenset()          # nothing ignored: audit_log, session, refresh_token and idempotency_key are compared too


async def test_sensitive_writes_denied_without_any_effect(client, seeded_plan_catalogue, monkeypatch):
    c = "B10-ADMIN-WRITES"
    w = await build_world(client)
    try:
        s = await seed_all(client, w)
        h = w.h("ADMIN")
        # admin-side ids needed for valid bodies
        sett = (await client.get("/v1/payroll/settings", headers=h)).json()["data"]
        comps = (await client.get("/v1/payroll/salary-components", headers=h)).json()["data"]
        structs = (await client.get("/v1/payroll/salary-structures", headers=h)).json()["data"]
        rates = (await client.get("/v1/payroll/statutory-rates", headers=h)).json()["data"]
        comp_cur = (await client.get(f"/v1/employees/{w.eid('E1')}/compensation", headers=h)).json()["data"][0]
        e1 = w.eid("E1")
        await switch_role(monkeypatch, "app")
        attempts = {
            "PUT payroll settings": ("PUT", "/v1/payroll/settings", {"variance_threshold_percent": "99"}, str(sett["version"])),
            "POST salary component": ("POST", "/v1/payroll/salary-components", {"code": "QA_X", "name": "QA", "component_type": "EARNING", "calculation": "FIXED"}, None),
            "PATCH salary component": ("PATCH", f"/v1/payroll/salary-components/{comps[0]['id']}", {"name": "hacked"}, str(comps[0].get("version", 1))),
            "PATCH salary structure": ("PATCH", f"/v1/payroll/salary-structures/{structs[0]['id']}", {"name": "hacked"}, str(structs[0].get("version", 1))),
            "verify statutory rate": ("POST", f"/v1/payroll/statutory-rates/{rates[0]['id']}/verify", {}, str(rates[0].get("version", 1))),
            "PATCH statutory rate": ("PATCH", f"/v1/payroll/statutory-rates/{rates[0]['id']}", {"parameters": {}}, str(rates[0].get("version", 1))),
            "assign salary to E1": ("POST", f"/v1/employees/{e1}/salary", {"salary_structure_id": structs[0]["id"], "effective_from": "2026-10-01", "reason": "x"}, None),
            "raise OWN compensation (E1)": ("POST", f"/v1/employees/{e1}/compensation", {"effective_from": "2026-10-01", "annual_ctc_minor": 99_00_000_00, "currency": "INR", "revision_type": "ANNUAL", "revision_reason": "self raise"}, str(comp_cur["version"])),
            "change OWN bank (E1)": ("POST", f"/v1/employees/{e1}/bank", {"effective_from": "2026-10-01", "account_holder_name": "Mallory", "account_number_enc": "999999999999", "bank_name": "Other", "ifsc": "SBIN0009999", "payment_mode": "BANK"}, None),
            "change OWN statutory (E1)": ("POST", f"/v1/employees/{e1}/statutory", {"effective_from": "2026-10-01", "is_pf_applicable": True, "is_esi_applicable": False, "is_lwf_applicable": False, "tax_regime": "NEW", "revision_reason": "x"}, None),
            "PATCH OWN employee record (E1)": ("PATCH", f"/v1/employees/{e1}", {"first_name": "Mallory"}, "1"),
            "update OWN identity (E1)": ("PATCH", f"/v1/employees/{e1}/identity", {"pan_number": "ABCDE1234F"}, "1"),
            "terminate employee": ("POST", f"/v1/employees/{e1}/employments/{uuid_zero()}/terminate", {}, "1"),
            "deactivate employee": ("DELETE", f"/v1/employees/{e1}", None, "1"),
            "create employee": ("POST", "/v1/employees", {"first_name": "Mallory"}, None),
            "create branch": ("POST", "/v1/branches", {"legal_entity_id": w.le, "name": "Evil"}, None),
            "create legal entity": ("POST", "/v1/legal-entities", {"name": "Evil LE"}, None),
            "create department": ("POST", "/v1/departments", {"name": "Evil Dept", "branch_id": w.branch_x}, None),
            "create shift": ("POST", "/v1/shifts", {"name": "Evil"}, None),
            "create roster": ("POST", "/v1/rosters", {}, None),
            "create attendance policy": ("POST", "/v1/attendance-policies", {"name": "Evil"}, None),
            "create leave type": ("POST", "/v1/leave-types", {"code": "EVIL", "name": "Evil"}, None),
            "leave ledger adjustment": ("POST", "/v1/leave-ledger/adjustments", {"employee_id": e1, "leave_type_id": s["leave_type"], "amount": "100.00", "effective_date": "2026-09-01", "reason": "x"}, None),
            "create attendance period": ("POST", "/v1/attendance-periods", {"legal_entity_id": w.le, "period_start": "2026-10-01", "period_end": "2026-10-31"}, None),
            "recompute attendance day": ("POST", "/v1/attendance/days/calculate", {}, None),
            "punch on behalf": ("POST", "/v1/attendance/punches", {"employee_id": e1, "punch_time": "2026-09-10T09:00:00Z", "direction": "IN", "reference": "x"}, None),
            "create pay run": ("POST", "/v1/payroll/pay-runs", {"legal_entity_id": w.le, "month": "2026-09"}, None),
            "create onboarding case": ("POST", "/v1/onboarding-cases", {"candidate_first_name": "Eve", "personal_email": "eve@example.com", "proposed_joining_date": "2026-11-01"}, None),
            "invite user as COMPANY_ADMIN": ("POST", "/v1/users/invite", {"email": "mallory@example.com", "role_code": "COMPANY_ADMIN"}, None),
            "upload OWN document (E1)": None,
        }
        report, problems = {}, []
        for who in ("E1", "E2", "M1", "BX", "CUSTV", "CUSTS", "B_ADMIN"):
            have = await perms_of(w, who)
            before = await company_counts(w.cid)
            before_b = await company_counts(w.tb.company_id)
            res = {}
            for label, spec in attempts.items():
                if spec is None:
                    continue
                m, path, body, ver = spec
                if who != "E1" and "(E1)" in label:
                    continue
                if who == "B_ADMIN" and "(E1)" in label:
                    pass
                hh = {**w.h(who), **({"If-Match": ver} if ver else {})}
                r = await client.request(m, path, headers=hh, **({"json": body} if body is not None else {}))
                res[label] = r.status_code
                if who == "B_ADMIN":
                    if r.status_code not in (404, 422, 409, 403, 201, 200, 204):
                        problems.append((who, label, r.status_code))
                elif r.status_code not in (403, 404):
                    # a principal that legitimately holds the needed permission is excluded by the permission lookup below
                    problems.append((who, label, r.status_code, r.text[:120]))
            if who != "B_ADMIN":
                after = await company_counts(w.cid)
                changed = diff(before, after, ignore=STRICT)
                report[who] = {"attempts": len(res), "statuses": sorted(set(res.values())), "company_tables_changed": changed}
                if changed:
                    problems.append((who, "denied writes changed data", changed))
            else:
                # tenant B's own admin performing "the same" calls acts on TENANT B only: tenant A must be untouched
                after_a = await company_counts(w.cid)
                report[who] = {"attempts": len(res), "statuses": sorted(set(res.values())), "tenant_A_changed": diff(before, after_a, ignore=STRICT)}
                if diff(before, after_a, ignore=STRICT):
                    problems.append((who, "tenant B calls changed tenant A", diff(before, after_a, ignore=STRICT)))
        rec(c, "denied sensitive writes", report=report, problems=problems)
        assert not problems, problems
    finally:
        await drop_world(w, monkeypatch)


def uuid_zero() -> str:
    from uuid import uuid4
    return str(uuid4())


async def test_privilege_escalation_and_role_ceiling(client, seeded_plan_catalogue, monkeypatch):
    c = "B10-ESCALATION"
    w = await build_world(client)
    try:
        await seed_all(client, w)
        await switch_role(monkeypatch, "app")
        hr_perms = await perms_of(w, "HR")
        out, problems = {}, []
        before = await company_counts(w.cid)
        roles_before = await q("SELECT uc.user_id::text u, array_agg(r.code ORDER BY r.code) roles FROM user_role ur JOIN user_company uc ON uc.id = ur.user_company_id JOIN role r ON r.id = ur.role_id WHERE uc.company_id = :c GROUP BY 1 ORDER BY 1", c=str(w.cid))
        for who in ("E1", "M1", "BX", "CUSTV"):
            own = w.people[who].user_id
            r = await client.patch(f"/v1/users/{own}/roles", headers=w.h(who), json={"role_codes": ["COMPANY_ADMIN"]})
            out[f"{who} grants itself COMPANY_ADMIN"] = r.status_code
            r2 = await client.post("/v1/users/invite", headers=w.h(who), json={"email": f"x-{who.lower()}@example.com", "role_code": "COMPANY_ADMIN"})
            out[f"{who} invites a COMPANY_ADMIN"] = r2.status_code
            for st in (r.status_code, r2.status_code):
                if st not in (403, 404):
                    problems.append((who, st))
        # HR_ADMIN: user-management permissions and role ceiling
        out["HR holds user-management permissions"] = sorted(p for p in hr_perms if p.startswith("SETTINGS.") or "ROLE" in p)
        e1u = w.people["E1"].user_id
        r = await client.patch(f"/v1/users/{e1u}/roles", headers=w.h("HR"), json={"role_codes": ["COMPANY_ADMIN"]})
        out["HR_ADMIN assigns COMPANY_ADMIN to E1"] = r.status_code
        r = await client.patch(f"/v1/users/{w.people['HR'].user_id}/roles", headers=w.h("HR"), json={"role_codes": ["COMPANY_ADMIN"]})
        out["HR_ADMIN assigns COMPANY_ADMIN to ITSELF"] = r.status_code
        r = await client.post("/v1/users/invite", headers=w.h("HR"), json={"email": "newadmin@example.com", "role_code": "COMPANY_ADMIN"})
        out["HR_ADMIN invites a COMPANY_ADMIN"] = r.status_code
        roles_after = await q("SELECT uc.user_id::text u, array_agg(r.code ORDER BY r.code) roles FROM user_role ur JOIN user_company uc ON uc.id = ur.user_company_id JOIN role r ON r.id = ur.role_id WHERE uc.company_id = :c GROUP BY 1 ORDER BY 1", c=str(w.cid))
        escalated = [x for x in roles_after if "COMPANY_ADMIN" in x["roles"] and x["u"] != str(w.t.user_id)]
        out["users (other than the original admin) holding COMPANY_ADMIN afterwards"] = len(escalated)
        out["role assignments unchanged by the denied attempts"] = roles_before == roles_after
        rec(c, "escalation attempts", results=out, hr_role_assignments=[x for x in roles_after if x['u'] in (e1u, w.people['HR'].user_id)])
        if r.status_code in (200, 201) or escalated:
            problems.append(("HR_ADMIN can mint COMPANY_ADMIN", out))
        assert not problems, problems
        assert roles_before == roles_after or escalated
    finally:
        await drop_world(w, monkeypatch)


async def test_onboarding_routes_scope_and_tenant(client, seeded_plan_catalogue, monkeypatch):
    c = "B10-ONBOARDING"
    w = await build_world(client)
    try:
        h = w.h("ADMIN")
        mk = await client.post("/v1/onboarding-cases", headers=h, json={"candidate_first_name": "Zed", "personal_email": f"zed-{w.cid.hex[:6]}@example.com", "proposed_joining_date": "2026-11-02"})
        assert mk.status_code == 201, mk.text
        case = mk.json()["data"]
        await switch_role(monkeypatch, "app")
        hr_can = (await client.get("/v1/onboarding-cases", headers=w.h("HR"))).status_code
        before = await company_counts(w.cid)
        res, problems = {}, []
        calls = [("GET", "/v1/onboarding-cases", None), ("GET", f"/v1/onboarding-cases/{case['id']}", None), ("POST", f"/v1/onboarding-cases/{case['id']}/send-invite", {}),
                 ("GET", f"/v1/onboarding-cases/{case['id']}/documents", None), ("POST", f"/v1/onboarding-cases/{case['id']}/request-changes", {"message": "x"}),
                 ("POST", f"/v1/onboarding-cases/{case['id']}/activate", {})]
        for who in ("E1", "M1", "BX", "CUSTV", "PAY"):
            for m, path, body in calls:
                r = await client.request(m, path, headers={**w.h(who), "If-Match": "1"}, **({"json": body} if body is not None else {}))
                res[f"{who} {m} {path.split('/v1/')[1][:40]}"] = r.status_code
                if r.status_code != 403:
                    problems.append((who, m, path, r.status_code))
        for m, path, body in calls:
            r = await client.request(m, path, headers={**w.h("B_ADMIN"), "If-Match": "1"}, **({"json": body} if body is not None else {}))
            res[f"B_ADMIN {m} {path.split('/v1/')[1][:40]}"] = r.status_code
            if r.status_code not in (404,) and not (path == "/v1/onboarding-cases" and r.status_code == 200):
                problems.append(("B_ADMIN", m, path, r.status_code))
        lst = (await client.get("/v1/onboarding-cases", headers=w.h("B_ADMIN"))).json()["data"]
        if any(x["id"] == case["id"] for x in lst):
            problems.append(("B_ADMIN list contains tenant A case",))
        after = await company_counts(w.cid)
        case_after = (await q("SELECT status FROM onboarding_case WHERE id = :i AND company_id = :c", i=case["id"], c=str(w.cid)))[0]["status"]
        rec(c, "onboarding", hr_list_status=hr_can, results=res, tenant_a_changed=diff(before, after, ignore=STRICT), case_status=case_after, problems=problems)
        assert not problems, problems
        assert diff(before, after, ignore=STRICT) == {}
    finally:
        await drop_world(w, monkeypatch)


async def test_read_only_routes_that_write(client, seeded_plan_catalogue, monkeypatch):
    """Observation test: which GET routes change the database for a principal who is only allowed to READ?"""
    c = "B10-READONLY"
    w = await build_world(client)
    try:
        await seed_all(client, w)
        await switch_role(monkeypatch, "app")
        findings = {}
        gets = ["/v1/payroll/settings", "/v1/payroll/salary-components", "/v1/payroll/salary-structures", "/v1/payroll/statutory-rates", "/v1/payroll/pay-runs",
                "/v1/payroll/adjustments", "/v1/attendance-periods", "/v1/attendance/days", "/v1/leave-types", "/v1/leave-balances", "/v1/employees", "/v1/onboarding-cases"]
        for path in gets:
            before = await company_counts(w.cid)
            st = (await client.get(path, headers=w.h("HR"))).status_code
            after = await company_counts(w.cid)
            d = diff(before, after, ignore=STRICT)
            if d:
                findings[path] = {"status": st, "tables": d}
        rec(c, "GET routes that changed the database when called by HR_ADMIN", findings=findings)
        # the same GET a second time changes nothing (idempotent seed-on-read)
        again = {}
        for path in findings:
            before = await company_counts(w.cid)
            await client.get(path, headers=w.h("HR"))
            again[path] = diff(before, await company_counts(w.cid), ignore=STRICT)
        rec(c, "second call", changes=again)
        assert all(not v for v in again.values())
    finally:
        await drop_world(w, monkeypatch)


async def test_statutory_rate_edit_and_verify_by_the_same_user(client, seeded_plan_catalogue, monkeypatch):
    """Separation of duties (observation, CL-06 open): can the person who edits a statutory rate also sign it off as verified?

    History: in run b10-20261026b this test recorded the OBSERVATION that HR_ADMIN could edit and then verify the same rate
    (OBS-B10-04; evidence B10-SOD-STATUTORY.jsonl of that run is kept unchanged).  After the HR_ADMIN policy change
    (2026-10-26, hradm-20261026a) the verification is refused for the editor, so the assertions below were updated to the
    new, intended behaviour: edit 200, own verify 403, rate stays unverified; an independent verifier (the company admin) succeeds."""
    c = "B10-SOD-STATUTORY"
    w = await build_world(client)
    try:
        rates = (await client.get("/v1/payroll/statutory-rates", headers=w.h("ADMIN"))).json()["data"]
        rate = rates[0]
        await switch_role(monkeypatch, "app")
        hr = w.h("HR")
        e = await client.patch(f"/v1/payroll/statutory-rates/{rate['id']}", headers={**hr, "If-Match": str(rate["version"])}, json={"notes": "edited by HR (b10)"})
        cur = (await client.get(f"/v1/payroll/statutory-rates?scheme={rate['scheme']}", headers=hr)).json()["data"]
        mine = next(x for x in cur if x["id"] == rate["id"])
        v = await client.post(f"/v1/payroll/statutory-rates/{rate['id']}/verify", headers={**hr, "If-Match": str(mine["version"])}, json={})
        row = (await q("SELECT verified_at IS NOT NULL v, verified_by_user_id::text vb, updated_at::text u FROM statutory_rate WHERE id = :i AND company_id = :c", i=rate["id"], c=str(w.cid)))[0]
        aud = await q("SELECT action, actor_user_id::text a FROM audit_log WHERE entity_id = :i AND company_id = :c ORDER BY occurred_at", i=rate["id"], c=str(w.cid))
        rec(c, "HR edits then verifies the same rate", edit=e.status_code, verify=v.status_code, row=row, hr_user=w.people["HR"].user_id, audit=aud)
        assert e.status_code == 200 and v.status_code == 403 and row["vb"] is None and row["v"] is False
        assert v.json()["error"]["code"] == "STATUTORY_RATE_SELF_VERIFICATION"
        assert [a["a"] for a in aud if a["action"] in ("PAYROLL_STATUTORY_RATE_UPDATED", "PAYROLL_STATUTORY_RATE_VERIFIED")] == [w.people["HR"].user_id]
        independent = await client.post(f"/v1/payroll/statutory-rates/{rate['id']}/verify", headers={**w.h("ADMIN"), "If-Match": str(mine["version"])}, json={})
        assert independent.status_code == 200 and independent.json()["data"]["verified"] is True
    finally:
        await drop_world(w, monkeypatch)
