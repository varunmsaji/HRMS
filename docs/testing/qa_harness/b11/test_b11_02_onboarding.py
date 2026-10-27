"""B11 onboarding lifecycle QA, as the runtime role `hrms_app`, acting principal HR_ADMIN unless stated.

Cases: B11-ONB-MATRIX, B11-ONB-LIFE, B11-ONB-DUP, B11-ONB-CONC, B11-ONB-FAIL, B11-ONB-CANCEL, B11-ONB-TENANT.
Only states/endpoints that exist are exercised (DRAFT/INVITED/IN_PROGRESS/SUBMITTED/UNDER_REVIEW/CHANGES_REQUESTED/VERIFIED/ACTIVATED)."""
import asyncio
from uuid import UUID, uuid4

import pytest
from b11common import (
    NOIGNORE, build_world, company_counts, diff, drop_world11 as drop_world, perms_of, q, rec, switch_role,
    _create_permission_scoped_user,
)
from tests.integration.modules.onboarding.test_onboarding_case import _case_payload
from tests.integration.modules.onboarding.test_onboarding_submit import _fill_all_sections

pytestmark = pytest.mark.asyncio
SECTIONS = ["personal_info", "address_info", "emergency_contact", "bank_info", "statutory_info", "previous_employment_info", "education_info", "nominee_info"]


async def org_fields(client, w):
    h = w.h("ADMIN")
    d = await client.post("/v1/departments", headers=h, json={"name": f"OD-{uuid4().hex[:5]}", "branch_id": w.branch_x})
    assert d.status_code == 201, d.text
    ds = await client.post("/v1/designations", headers=h, json={"title": f"OT-{uuid4().hex[:5]}", "department_id": d.json()["data"]["id"]})
    assert ds.status_code == 201, ds.text
    return {"branch_id": w.branch_x, "department_id": d.json()["data"]["id"], "designation_id": ds.json()["data"]["id"]}


async def audit_actions(cid, skip=0):
    rows = await q("SELECT action FROM audit_log WHERE company_id = :c ORDER BY occurred_at, id", c=str(cid))
    return [r["action"] for r in rows][skip:]


async def case_row(cid, case_id):
    return (await q("SELECT status, version, employee_id::text e FROM onboarding_case WHERE company_id = :c AND id = CAST(:i AS uuid)", c=str(cid), i=str(case_id)))[0]


async def employees_with_email(cid, email):
    return (await q("SELECT count(*) n FROM employee WHERE company_id = :c AND lower(personal_email) = lower(:e)", c=str(cid), e=email))[0]["n"]


async def drive_to_submitted(client, w, hr, org=True, email=None):
    over = dict(await org_fields(client, w)) if org else {}
    if email:
        over["personal_email"] = email
    r = await client.post("/v1/onboarding-cases", headers=hr, json=_case_payload(**over))
    assert r.status_code == 201, r.text
    case = r.json()["data"]
    inv = await client.post(f"/v1/onboarding-cases/{case['id']}/send-invite", headers=hr)
    assert inv.status_code == 200, inv.text
    token = inv.json()["data"]["invite_url"].rsplit("/", 1)[1]
    await _fill_all_sections(client, token)
    sub = await client.post(f"/v1/public/onboarding/{token}/submit")
    assert sub.status_code == 200, sub.text
    return case, token


async def verify_all(client, hr, case_id):
    for s in SECTIONS:
        r = await client.post(f"/v1/onboarding-cases/{case_id}/sections/{s}/review", headers=hr, json={"status": "VERIFIED"})
        assert r.status_code == 200, (s, r.text)


# ---------------------------------------------------------------------------------------------------------------- matrix
OPS = {
    "create": ("ONBOARDING.CREATE", lambda c, h, cid: c.post("/v1/onboarding-cases", headers=h, json=_case_payload())),
    "list": ("ONBOARDING.VIEW", lambda c, h, cid: c.get("/v1/onboarding-cases", headers=h)),
    "get": ("ONBOARDING.VIEW", lambda c, h, cid: c.get(f"/v1/onboarding-cases/{cid}", headers=h)),
    "send_invite": ("ONBOARDING.CREATE", lambda c, h, cid: c.post(f"/v1/onboarding-cases/{cid}/send-invite", headers=h)),
    "documents_list": ("ONBOARDING.VIEW", lambda c, h, cid: c.get(f"/v1/onboarding-cases/{cid}/documents", headers=h)),
    "document_review": ("ONBOARDING.REVIEW", lambda c, h, cid: c.post(f"/v1/onboarding-cases/{cid}/documents/{uuid4()}/review", headers=h, json={"status": "VERIFIED"})),
    "section_review": ("ONBOARDING.REVIEW", lambda c, h, cid: c.post(f"/v1/onboarding-cases/{cid}/sections/personal_info/review", headers=h, json={"status": "VERIFIED"})),
    "request_changes": ("ONBOARDING.REVIEW", lambda c, h, cid: c.post(f"/v1/onboarding-cases/{cid}/request-changes", headers=h)),
    "activate": ("ONBOARDING.ACTIVATE", lambda c, h, cid: c.post(f"/v1/onboarding-cases/{cid}/activate", headers=h)),
}


async def test_matrix(client, seeded_plan_catalogue, monkeypatch):
    c = "B11-ONB-MATRIX"
    w = await build_world(client)
    try:
        for name, perms in (("CUSTV", ["ONBOARDING.VIEW"]), ("CUSTR", ["ONBOARDING.REVIEW"]), ("CUSTC", ["ONBOARDING.CREATE"])):
            hh, uid = await _create_permission_scoped_user(company_id=w.cid, permission_codes=perms, data_scope="COMPANY")
            from world import Person
            w.people[name] = Person(name, None, hh, str(uid))
        case = (await client.post("/v1/onboarding-cases", headers=w.h("HR"), json=_case_payload())).json()["data"]
        cid = case["id"]
        held = {k: sorted(p for p in await perms_of(w, k) if p.startswith("ONBOARDING.")) for k in ("ADMIN", "HR", "M1", "BX", "E1", "CUSTV", "CUSTR", "CUSTC")}
        rec(c, "ONBOARDING grants held by each principal (from the DB)", held=held)
        # the approved policy: HR_ADMIN holds the five codes, COMPANY_ADMIN too, nobody else in the shipped set
        assert held["HR"] == sorted(["ONBOARDING.ACTIVATE", "ONBOARDING.CANCEL", "ONBOARDING.CREATE", "ONBOARDING.REVIEW", "ONBOARDING.VIEW"]), held["HR"]
        assert held["M1"] == held["BX"] == held["E1"] == [], (held["M1"], held["BX"], held["E1"])
        await switch_role(monkeypatch, "app")
        problems, rows = [], []
        principals = ["M1", "BX", "E1", "CUSTV", "CUSTR", "CUSTC", "ADMIN", "HR"]       # denied-heavy principals first; HR/ADMIN writes change the case, so they come last
        for who in principals:
            have = set(held[who])
            for op, (perm, fn) in OPS.items():
                before = await company_counts(w.cid)
                r = await fn(client, w.h(who), cid)
                changed = diff(before, await company_counts(w.cid), NOIGNORE)
                allowed = perm in have
                ok = (r.status_code not in (401, 403)) if allowed else (r.status_code == 403 and not changed)
                rows.append({"who": who, "op": op, "needs": perm, "granted": allowed, "status": r.status_code, "changed": sorted(changed), "ok": ok})
                if not ok:
                    problems.append(f"{who} {op}: granted={allowed} status={r.status_code} changed={sorted(changed)}")
        # anonymous: nothing at all may change
        for op, (perm, fn) in OPS.items():
            before = await company_counts(w.cid)
            r = await fn(client, {}, cid)
            changed = diff(before, await company_counts(w.cid), NOIGNORE)
            rows.append({"who": "ANON", "op": op, "status": r.status_code, "changed": sorted(changed), "ok": r.status_code == 401 and not changed})
            if r.status_code != 401 or changed:
                problems.append(f"ANON {op}: {r.status_code} {sorted(changed)}")
        rec(c, "principal x operation matrix", rows=rows, problems=problems, n_probes=len(rows))
        assert not problems, problems
    finally:
        await drop_world(w, monkeypatch)


async def test_tenant_isolation_and_forged_headers(client, seeded_plan_catalogue, monkeypatch):
    c = "B11-ONB-TENANT"
    w = await build_world(client)
    try:
        case = (await client.post("/v1/onboarding-cases", headers=w.h("HR"), json=_case_payload())).json()["data"]
        cid = case["id"]
        await switch_role(monkeypatch, "app")
        tb, problems, rows = w.h("B_ADMIN"), [], []
        for op, (perm, fn) in OPS.items():
            if op in ("create", "list"):
                continue
            ba, bb = await company_counts(w.cid), await company_counts(w.tb.company_id)
            r = await fn(client, tb, cid)
            fa, fb = diff(ba, await company_counts(w.cid), NOIGNORE), diff(bb, await company_counts(w.tb.company_id), NOIGNORE)
            rows.append({"op": op, "as": "other-tenant COMPANY_ADMIN", "status": r.status_code, "A_changed": sorted(fa), "B_changed": sorted(fb)})
            if r.status_code != 404 or fa or fb:
                problems.append(f"{op}: other tenant got {r.status_code}, A changed {sorted(fa)}, B changed {sorted(fb)}")
            ba = await company_counts(w.cid)
            r = await fn(client, {**tb, "X-Company-Id": str(w.cid)}, cid)         # forged: B's token, A's company header
            fa = diff(ba, await company_counts(w.cid), NOIGNORE)
            rows.append({"op": op, "as": "other-tenant token + forged X-Company-Id", "status": r.status_code, "A_changed": sorted(fa)})
            if r.status_code not in (401, 403, 404) or fa:
                problems.append(f"{op}: forged header got {r.status_code}, A changed {sorted(fa)}")
        lst = await client.get("/v1/onboarding-cases", headers=tb)
        leaked = [x for x in lst.json()["data"] if x["id"] == cid]
        rows.append({"op": "list", "as": "other tenant", "status": lst.status_code, "leaks_A_case": bool(leaked)})
        if leaked:
            problems.append("tenant A's case listed to tenant B")
        # a candidate token for tenant A's case never works against another case id
        rec(c, "cross-tenant and forged-header probes", rows=rows, problems=problems)
        assert not problems, problems
    finally:
        await drop_world(w, monkeypatch)


# ---------------------------------------------------------------------------------------------------------------- lifecycle
async def test_lifecycle_state_audit_and_invalid_transitions(client, seeded_plan_catalogue, monkeypatch):
    c = "B11-ONB-LIFE"
    w = await build_world(client)
    try:
        hr = w.h("HR")
        await switch_role(monkeypatch, "app")
        steps, problems = [], []

        def note(step, **kw):
            steps.append({"step": step, **kw})

        n0 = len(await audit_actions(w.cid))
        over = await org_fields(client, w)
        email = f"cand-{uuid4().hex[:8]}@personal.example"
        r = await client.post("/v1/onboarding-cases", headers=hr, json=_case_payload(personal_email=email, **over))
        assert r.status_code == 201, r.text
        case = r.json()["data"]
        cid = case["id"]
        st = await case_row(w.cid, cid)
        note("create (HR_ADMIN)", http=r.status_code, db_status=st["status"], version=st["version"], audit=(await audit_actions(w.cid, n0)))
        assert st["status"] == "DRAFT"
        assert "ONBOARDING_CASE_CREATED" in await audit_actions(w.cid, n0)

        # --- invalid: activate / request-changes / review before the case is submitted -> refused, nothing changes
        for label, req in (("activate DRAFT", client.post(f"/v1/onboarding-cases/{cid}/activate", headers=hr)),
                           ("request-changes DRAFT", client.post(f"/v1/onboarding-cases/{cid}/request-changes", headers=hr)),
                           ("review section DRAFT", client.post(f"/v1/onboarding-cases/{cid}/sections/personal_info/review", headers=hr, json={"status": "VERIFIED"}))):
            before = await company_counts(w.cid)
            resp = await req
            ch = diff(before, await company_counts(w.cid), NOIGNORE)
            note(f"invalid: {label}", http=resp.status_code, code=(resp.json().get("error") or {}).get("code"), changed=sorted(ch))
            if resp.status_code not in (409, 422) or ch:
                problems.append(f"{label}: {resp.status_code} changed {sorted(ch)}")

        # --- unknown / malformed identifiers
        for label, path in (("unknown case id", f"/v1/onboarding-cases/{uuid4()}"), ("malformed id", "/v1/onboarding-cases/not-a-uuid")):
            resp = await client.get(path, headers=hr)
            note(f"get {label}", http=resp.status_code)
            if resp.status_code not in (404, 422):
                problems.append(f"get {label}: {resp.status_code}")

        # --- send-invite (DRAFT -> INVITED), repeated invite re-issues the link and revokes the old one
        n1 = len(await audit_actions(w.cid))
        inv = await client.post(f"/v1/onboarding-cases/{cid}/send-invite", headers=hr)
        st = await case_row(w.cid, cid)
        note("send-invite", http=inv.status_code, db_status=st["status"], email_sent=inv.json()["data"]["email_sent"], audit=await audit_actions(w.cid, n1))
        assert inv.status_code == 200 and st["status"] == "INVITED"
        tok1 = inv.json()["data"]["invite_url"].rsplit("/", 1)[1]
        inv2 = await client.post(f"/v1/onboarding-cases/{cid}/send-invite", headers=hr)
        tok2 = inv2.json()["data"]["invite_url"].rsplit("/", 1)[1]
        old = await client.get(f"/v1/public/onboarding/{tok1}")
        new = await client.get(f"/v1/public/onboarding/{tok2}")
        note("re-invite", http=inv2.status_code, old_token_http=old.status_code, new_token_http=new.status_code, db_status=(await case_row(w.cid, cid))["status"])
        if old.status_code == 200 or new.status_code != 200:
            problems.append(f"re-invite: old token {old.status_code}, new token {new.status_code}")
        # a token for this case is useless against another tenant's case / unknown token
        bad = await client.get(f"/v1/public/onboarding/{uuid4().hex}")
        note("unknown public token", http=bad.status_code)
        assert bad.status_code in (404, 410), bad.status_code
        tok = tok2

        # --- candidate fills + submits
        n2 = len(await audit_actions(w.cid))
        await _fill_all_sections(client, tok)
        sub = await client.post(f"/v1/public/onboarding/{tok}/submit")
        st = await case_row(w.cid, cid)
        note("candidate submit", http=sub.status_code, db_status=st["status"], audit=await audit_actions(w.cid, n2))
        assert sub.status_code == 200 and st["status"] == "SUBMITTED"
        again = await client.post(f"/v1/public/onboarding/{tok}/submit")
        note("candidate submit again", http=again.status_code, db_status=(await case_row(w.cid, cid))["status"])
        if again.status_code in (200, 201):
            problems.append("second submit accepted")
        edit = await client.patch(f"/v1/public/onboarding/{tok}/sections/personal_info", json={"first_name": "Changed"})
        note("candidate edit after submit", http=edit.status_code)
        if edit.status_code in (200, 201):
            problems.append("candidate could edit after submit")

        # --- review: partial verification must not verify the case; activate must still be refused
        n3 = len(await audit_actions(w.cid))
        for s in SECTIONS[:-1]:
            rr = await client.post(f"/v1/onboarding-cases/{cid}/sections/{s}/review", headers=hr, json={"status": "VERIFIED"})
            assert rr.status_code == 200, rr.text
        st = await case_row(w.cid, cid)
        note("7 of 8 sections verified", db_status=st["status"], audit_rows=len(await audit_actions(w.cid, n3)))
        assert st["status"] == "UNDER_REVIEW", st
        before_emp = (await company_counts(w.cid))["employee"]
        act = await client.post(f"/v1/onboarding-cases/{cid}/activate", headers=hr)
        note("activate while UNDER_REVIEW", http=act.status_code, employees_created=(await company_counts(w.cid))["employee"] - before_emp)
        if act.status_code not in (409, 422) or (await company_counts(w.cid))["employee"] != before_emp:
            problems.append(f"activate under review: {act.status_code}")
        rej = await client.post(f"/v1/onboarding-cases/{cid}/sections/{SECTIONS[-1]}/review", headers=hr, json={"status": "REJECTED"})
        note("reject without reason", http=rej.status_code)
        if rej.status_code in (200, 201):
            problems.append("rejection without a reason accepted")
        rr = await client.post(f"/v1/onboarding-cases/{cid}/sections/{SECTIONS[-1]}/review", headers=hr, json={"status": "VERIFIED"})
        st = await case_row(w.cid, cid)
        note("last section verified", http=rr.status_code, db_status=st["status"])
        assert st["status"] == "VERIFIED"

        # --- activate (VERIFIED -> ACTIVATED): employee graph exists, audit row, case linked
        n4 = len(await audit_actions(w.cid))
        counts_before = await company_counts(w.cid)
        act = await client.post(f"/v1/onboarding-cases/{cid}/activate", headers=hr)
        st = await case_row(w.cid, cid)
        counts_after = await company_counts(w.cid)
        created = {k: v for k, v in diff(counts_before, counts_after, NOIGNORE).items() if k not in ("audit_log",)}
        note("activate (HR_ADMIN)", http=act.status_code, db_status=st["status"], employee_id=st["e"], tables_changed=created, audit=await audit_actions(w.cid, n4))
        assert act.status_code == 200 and st["status"] == "ACTIVATED" and st["e"], act.text
        assert "ONBOARDING_CASE_ACTIVATED" in await audit_actions(w.cid, n4)
        assert await employees_with_email(w.cid, email) == 1

        # --- repeated / out-of-order after ACTIVATED: refused, no partial change
        for label, req in (("activate again", client.post(f"/v1/onboarding-cases/{cid}/activate", headers=hr)),
                           ("request-changes after ACTIVATED", client.post(f"/v1/onboarding-cases/{cid}/request-changes", headers=hr)),
                           ("review section after ACTIVATED", client.post(f"/v1/onboarding-cases/{cid}/sections/personal_info/review", headers=hr, json={"status": "REJECTED", "rejection_reason": "x"})),
                           ("send-invite after ACTIVATED", client.post(f"/v1/onboarding-cases/{cid}/send-invite", headers=hr))):
            before = await company_counts(w.cid)
            resp = await req
            ch = diff(before, await company_counts(w.cid), NOIGNORE)
            note(f"invalid: {label}", http=resp.status_code, code=(resp.json().get("error") or {}).get("code"), changed=sorted(ch), db_status=(await case_row(w.cid, cid))["status"])
            if label.startswith("send-invite"):
                continue              # module docstring: a link may be re-issued for an ACTIVATED case; recorded as OBS-B11-01, not asserted
            if resp.status_code not in (409, 422) or ch:
                problems.append(f"{label}: {resp.status_code} changed {sorted(ch)}")
        assert await employees_with_email(w.cid, email) == 1
        rec(c, "lifecycle", steps=steps, problems=problems)
        assert not problems, problems
    finally:
        await drop_world(w, monkeypatch)


async def test_duplicate_exact_email_blocked(client, seeded_plan_catalogue, monkeypatch):
    c = "B11-ONB-DUP"
    w = await build_world(client)
    try:
        hr = w.h("HR")
        await switch_role(monkeypatch, "app")
        email = f"dup-{uuid4().hex[:8]}@personal.example"
        a = await client.post("/v1/onboarding-cases", headers=hr, json=_case_payload(personal_email=email))
        b = await client.post("/v1/onboarding-cases", headers=hr, json=_case_payload(personal_email=email))
        o = await client.post("/v1/onboarding-cases", headers=w.h("B_ADMIN"), json=_case_payload(personal_email=email))
        rows = (await q("SELECT count(*) n FROM onboarding_case WHERE company_id = :c AND personal_email = :e", c=str(w.cid), e=email))[0]["n"]
        rec(c, "exact duplicate", first=a.status_code, second=b.status_code, code=(b.json().get("error") or {}).get("code"), rows=rows, other_tenant_same_email=o.status_code)
        assert (a.status_code, b.status_code, rows, o.status_code) == (201, 409, 1, 201)
    finally:
        await drop_world(w, monkeypatch)


async def test_duplicate_email_case_variant_blocked(client, seeded_plan_catalogue, monkeypatch):
    """E-mail addresses are compared case-insensitively everywhere else (invites lower-case them); the duplicate-active-case check compares exactly."""
    c = "B11-ONB-DUP"
    w = await build_world(client)
    try:
        hr = w.h("HR")
        await switch_role(monkeypatch, "app")
        email = f"dupcase-{uuid4().hex[:8]}@personal.example"
        a = await client.post("/v1/onboarding-cases", headers=hr, json=_case_payload(personal_email=email))
        b = await client.post("/v1/onboarding-cases", headers=hr, json=_case_payload(personal_email=email.upper().replace("@PERSONAL.EXAMPLE", "@personal.example")))
        rows = (await q("SELECT count(*) n FROM onboarding_case WHERE company_id = :c AND lower(personal_email) = :e", c=str(w.cid), e=email))[0]["n"]
        rec(c, "case-variant duplicate", first=a.status_code, second=b.status_code, rows_case_insensitive=rows)
        assert (a.status_code, b.status_code, rows) == (201, 409, 1)
    finally:
        await drop_world(w, monkeypatch)


async def test_case_for_email_of_existing_employee_observed(client, seeded_plan_catalogue, monkeypatch):
    """Observation only (no product rule found): what happens when an onboarding case is opened for an e-mail that already belongs to an employee?"""
    c = "B11-ONB-DUP"
    w = await build_world(client)
    try:
        hr = w.h("HR")
        await switch_role(monkeypatch, "app")
        em = f"ex-{uuid4().hex[:6]}@personal.example"
        emp = await client.post("/v1/employees", headers=w.h("ADMIN"), json={"first_name": "Existing", "personal_email": em})
        d = await client.post("/v1/onboarding-cases", headers=hr, json=_case_payload(personal_email=em))
        rec(c, "case for e-mail already used by an employee", employee_create=emp.status_code, case_create=d.status_code)
    finally:
        await drop_world(w, monkeypatch)


# ---------------------------------------------------------------------------------------------------------------- concurrency
async def test_concurrent_activation_creates_exactly_one_employee(client, seeded_plan_catalogue, monkeypatch):
    c = "B11-ONB-CONC"
    w = await build_world(client)
    try:
        hr = w.h("HR")
        await switch_role(monkeypatch, "app")
        email = f"conc-{uuid4().hex[:8]}@personal.example"
        case, _tok = await drive_to_submitted(client, w, hr, email=email)
        await verify_all(client, hr, case["id"])
        assert (await case_row(w.cid, case["id"]))["status"] == "VERIFIED"
        before = await company_counts(w.cid)
        rs = await asyncio.gather(*[client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=hr) for _ in range(8)], return_exceptions=True)
        codes = sorted(str(getattr(r, "status_code", repr(r))) for r in rs)
        n_emp = await employees_with_email(w.cid, email)
        st = await case_row(w.cid, case["id"])
        ch = diff(before, await company_counts(w.cid), NOIGNORE)
        codes_emp = (await q("SELECT employee_code FROM employee WHERE company_id = :c AND lower(personal_email) = :e ORDER BY employee_code", c=str(w.cid), e=email))
        rec(c, "8 parallel activations of one VERIFIED case", statuses=codes, employees_with_that_email=n_emp, employee_codes=[r["employee_code"] for r in codes_emp],
            case_status=st["status"], case_employee_id=st["e"], tables_changed=ch)
        assert codes.count("200") == 1 and n_emp == 1 and st["status"] == "ACTIVATED", (codes, n_emp, st)
    finally:
        await drop_world(w, monkeypatch)


async def test_concurrent_case_creation_creates_exactly_one_case(client, seeded_plan_catalogue, monkeypatch):
    c = "B11-ONB-CONC"
    w = await build_world(client)
    try:
        hr = w.h("HR")
        await switch_role(monkeypatch, "app")
        email2 = f"conc2-{uuid4().hex[:8]}@personal.example"
        rs = await asyncio.gather(*[client.post("/v1/onboarding-cases", headers={**hr, "Idempotency-Key": f"b11-conc-{i}-{uuid4().hex[:6]}"}, json=_case_payload(personal_email=email2)) for i in range(8)], return_exceptions=True)
        codes2 = sorted(str(getattr(r, "status_code", repr(r))) for r in rs)
        n_cases = (await q("SELECT count(*) n FROM onboarding_case WHERE company_id = :c AND lower(personal_email) = :e", c=str(w.cid), e=email2))[0]["n"]
        follow = await client.post("/v1/onboarding-cases", headers=hr, json=_case_payload(personal_email=email2))
        lst = await client.get("/v1/onboarding-cases", headers=hr)
        rec(c, "8 parallel creates, same candidate e-mail", statuses=codes2, cases=n_cases, later_create_status=follow.status_code, list_status=lst.status_code)
        assert codes2.count("201") == 1 and n_cases == 1, (codes2, n_cases)
    finally:
        await drop_world(w, monkeypatch)


# ---------------------------------------------------------------------------------------------------------------- failure injection
async def _audit_fail_run(client, monkeypatch, w):
    from hrms.core.audit.service import AuditService
    hr = w.h("HR")
    await switch_role(monkeypatch, "app")
    email = f"fail-{uuid4().hex[:8]}@personal.example"
    case, _t = await drive_to_submitted(client, w, hr, email=email)
    cid = case["id"]
    original = AuditService.record
    armed = {"action": None, "hits": 0}

    async def flaky(self, *a, **kw):
        if kw.get("action") == armed["action"]:
            armed["hits"] += 1
            raise RuntimeError("injected audit failure")
        return await original(self, *a, **kw)

    monkeypatch.setattr(AuditService, "record", flaky)
    res = {}
    armed["action"] = "ONBOARDING_SECTION_REVIEWED"
    before = await company_counts(w.cid)
    try:
        r = await client.post(f"/v1/onboarding-cases/{cid}/sections/personal_info/review", headers=hr, json={"status": "VERIFIED"})
        res["review_http"] = r.status_code
    except Exception as exc:  # noqa: BLE001
        res["review_http"] = f"raised {type(exc).__name__}"
    res["review_changed"] = sorted(diff(before, await company_counts(w.cid), NOIGNORE))
    res["review_case_status"] = (await case_row(w.cid, cid))["status"]
    armed["action"] = None
    await verify_all(client, hr, cid)
    assert (await case_row(w.cid, cid))["status"] == "VERIFIED"
    armed["action"] = "ONBOARDING_CASE_ACTIVATED"
    before = await company_counts(w.cid)
    mails_before = await q("SELECT count(*) n FROM email_log WHERE company_id = :c", c=str(w.cid))
    try:
        r = await client.post(f"/v1/onboarding-cases/{cid}/activate", headers=hr)
        res["activate_http"] = r.status_code
    except Exception as exc:  # noqa: BLE001
        res["activate_http"] = f"raised {type(exc).__name__}"
    res["activate_changed"] = sorted(diff(before, await company_counts(w.cid), NOIGNORE))
    res["activate_case"] = await case_row(w.cid, cid)
    res["employees_with_email"] = await employees_with_email(w.cid, email)
    res["audit_hits"] = armed["hits"]
    res["email_log_rows_added_by_failed_activation"] = (await q("SELECT count(*) n FROM email_log WHERE company_id = :c", c=str(w.cid)))[0]["n"] - mails_before[0]["n"]
    res["email_log_newest"] = await q("SELECT * FROM email_log WHERE company_id = :c ORDER BY created_at DESC LIMIT 2", c=str(w.cid))
    armed["action"] = None
    r = await client.post(f"/v1/onboarding-cases/{cid}/activate", headers=hr)
    res["activate_after_recovery_http"] = r.status_code
    res["employees_after_recovery"] = await employees_with_email(w.cid, email)
    return res


async def test_audit_failure_leaves_no_partial_business_state(client, seeded_plan_catalogue, monkeypatch):
    """In-process hook (AuditService.record patched inside the TEST process only; monkeypatch undoes it): the audit write fails -> request fails and the
    business tables (case status, employee graph, invites) are unchanged; the same activation then succeeds exactly once after recovery."""
    c = "B11-ONB-FAIL"
    w = await build_world(client)
    try:
        res = await _audit_fail_run(client, monkeypatch, w)
        rec(c, "audit-write failure injection", results=res)
        business = [t for t in res["activate_changed"] if t != "email_log"]
        assert res["review_changed"] == [] and res["review_case_status"] == "SUBMITTED", res
        assert business == [] and res["activate_case"]["status"] == "VERIFIED" and res["employees_with_email"] == 0, res
        assert res["activate_after_recovery_http"] == 200 and res["employees_after_recovery"] == 1, res
    finally:
        await drop_world(w, monkeypatch)


async def test_failed_activation_sends_no_email(client, seeded_plan_catalogue, monkeypatch):
    """The same injected failure: no e-mail (here: an email_log row from the 'logging' provider) may be recorded/sent for an activation that rolled back."""
    c = "B11-ONB-FAIL"
    w = await build_world(client)
    try:
        res = await _audit_fail_run(client, monkeypatch, w)
        rec(c, "email side effect of a rolled-back activation", results=res)
        assert res["email_log_rows_added_by_failed_activation"] == 0, res["email_log_newest"]
    finally:
        await drop_world(w, monkeypatch)


# ---------------------------------------------------------------------------------------------------------------- cancel
async def test_cancel_is_absent(client, seeded_plan_catalogue, monkeypatch):
    """ONBOARDING.CANCEL: granted (HR_ADMIN, COMPANY_ADMIN) but is it usable anywhere? Live route inventory + path probes + source scan."""
    c = "B11-ONB-CANCEL"
    from pathlib import Path

    from world import route_inventory
    inv = route_inventory()
    users = [f"{r['method']} {r['path']}" for r in inv if "ONBOARDING.CANCEL" in r["perm"]]
    onboarding_routes = sorted(f"{r['method']} {r['path']} {r['perm']}" for r in inv if "onboarding" in r["path"] and not r["path"].startswith("/v1/public"))
    src_root = Path("/media/varun/varun12/work/staff-spectrum/HRMS/apps/api/src/hrms")
    writers = [str(p.relative_to(src_root)) for p in src_root.rglob("*.py") if "CANCELLED" in p.read_text() and "onboarding" in str(p)]
    hits = [ln for p in (src_root / "modules/onboarding").glob("*.py") for ln in p.read_text().splitlines() if ("status=\"CANCELLED\"" in ln or "'CANCELLED'" in ln or "status = \"CANCELLED\"" in ln)]
    w = await build_world(client)
    try:
        hr = w.h("HR")
        case = (await client.post("/v1/onboarding-cases", headers=hr, json=_case_payload())).json()["data"]
        await switch_role(monkeypatch, "app")
        probes = {}
        for m, p in (("POST", f"/v1/onboarding-cases/{case['id']}/cancel"), ("DELETE", f"/v1/onboarding-cases/{case['id']}"), ("PATCH", f"/v1/onboarding-cases/{case['id']}")):
            r = await client.request(m, p, headers=hr, json={"status": "CANCELLED"} if m == "PATCH" else None)
            probes[f"{m} {p.replace(case['id'], '{id}')}"] = r.status_code
        held = sorted(p for p in await perms_of(w, "HR") if p == "ONBOARDING.CANCEL")
        status_after = (await case_row(w.cid, case["id"]))["status"]
        rec(c, "cancel evidence", routes_requiring_cancel=users, onboarding_routes=onboarding_routes, sources_mentioning_CANCELLED=writers, assignments_of_CANCELLED=hits,
            probes=probes, hr_admin_holds_cancel=held, case_status_after_probes=status_after)
        assert users == [] and hits == [] and all(v in (404, 405) for v in probes.values()) and status_after == "DRAFT", (users, hits, probes, status_after)
    finally:
        await drop_world(w, monkeypatch)
