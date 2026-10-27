"""B11-SG-01..05: the five OBS-HRA-01 `known_gap` handlers, exercised with synthetic custom roles that hold the permission at a
RESTRICTED scope (SELF / REPORTEES / BRANCH), as the runtime role `hrms_app`.

Each test asserts the CORRECT behaviour (an out-of-scope target is refused with 403/404 and changes nothing at all - every company
table incl. audit_log and idempotency_key). A failing test therefore means a CONFIRMED scope defect; the run output is kept as evidence.
Shipped roles hold these permissions at COMPANY only, so this documents a latent (not currently reachable) exposure."""
import pytest
from b11common import (
    NOIGNORE, DAY, build_world, company_counts, day_ids, diff, drop_world11 as drop_world, mk_noaccount, q, rec, scoped, seed_attendance, switch_role,
)

pytestmark = pytest.mark.asyncio

# scope -> (owner employee key, in-scope target keys, out-of-scope target keys)  (world: E1,E2 report to M1 in branch X; E3 reports to M2 in branch Y)
ATT_CASES = {
    "SELF": ("E1", ["E1"], ["E2", "E3"]),
    "REPORTEES": ("M1", ["E1", "E2"], ["E3"]),
    "BRANCH": ("BX", ["E1", "E2"], ["E3"]),
}
DENIED = {403, 404}


async def _run(client, monkeypatch, case, perm, call, *, extra_setup=None):
    w = await build_world(client)
    try:
        await seed_attendance(client, w)
        ctx = {"days": await day_ids(w)}
        if extra_setup:
            ctx.update(await extra_setup(client, w))
        heads = {s: await scoped(w, perm, s, owner) for s, (owner, _i, _o) in ATT_CASES.items()}
        await switch_role(monkeypatch, "app")
        rows, bad = [], []
        for scope, (owner, ins, outs) in ATT_CASES.items():
            for key in ins + outs:
                before = await company_counts(w.cid)
                r = await call(client, w, heads[scope], key, ctx)
                after = await company_counts(w.cid)
                changed = diff(before, after, NOIGNORE)
                inside = key in ins
                rows.append({"scope": scope, "owner": owner, "target": key, "in_scope": inside, "status": r.status_code, "changed": changed})
                if not inside and (r.status_code not in DENIED or changed):
                    bad.append(f"{scope}/{owner} -> out-of-scope {key}: HTTP {r.status_code}, tables changed {changed}")
        # other tenant and forged header controls
        before, before_b = await company_counts(w.cid), await company_counts(w.tb.company_id)
        tb = w.people["B_ADMIN"].headers
        cross = await call(client, w, tb, "E1", ctx)
        forged = await call(client, w, {**tb, "X-Company-Id": str(w.cid)}, "E1", ctx)
        cross_changed = diff(before, await company_counts(w.cid), NOIGNORE)
        b_changed = diff(before_b, await company_counts(w.tb.company_id), NOIGNORE)
        rows.append({"control": "other-tenant admin on tenant A id", "status": cross.status_code, "tenant_A_changed": cross_changed, "tenant_B_changed": b_changed, "body": cross.text[:700]})
        rows.append({"control": "other-tenant admin with forged X-Company-Id", "status": forged.status_code, "tenant_A_changed": cross_changed})
        company = await call(client, w, w.h("ADMIN"), "E3", ctx)
        rows.append({"control": "COMPANY_ADMIN (company scope) on E3", "status": company.status_code})
        if cross.status_code in (200, 201, 202) or forged.status_code in (200, 201, 202) or cross_changed or b_changed:
            bad.append(f"CROSS-TENANT effect: other-tenant admin got HTTP {cross.status_code} (forged header {forged.status_code}); tenant A changed {cross_changed}; tenant B changed {b_changed}")
        rec(case, "results", permission=perm, rows=rows, violations=bad)
        assert not bad, "scope NOT enforced: " + " | ".join(bad)
    finally:
        await drop_world(w, monkeypatch)


async def test_sg01_calculate_day(client, seeded_plan_catalogue, monkeypatch):
    async def call(client, w, h, key, ctx):
        return await client.post("/v1/attendance/days/calculate", headers=h, params={"employee_id": w.eid(key), "date": DAY})
    await _run(client, monkeypatch, "B11-SG-01", "ATTENDANCE.VIEW_ALL", call)


async def test_sg02_recompute_day(client, seeded_plan_catalogue, monkeypatch):
    async def call(client, w, h, key, ctx):
        return await client.post(f"/v1/attendance/days/{ctx['days'][key]}/recompute", headers=h)
    await _run(client, monkeypatch, "B11-SG-02", "ATTENDANCE.RECOMPUTE", call)


async def test_sg03_calculate_range(client, seeded_plan_catalogue, monkeypatch):
    async def call(client, w, h, key, ctx):
        return await client.post("/v1/attendance/days/calculate-range", headers=h, json={"date_from": DAY, "date_to": DAY, "employee_ids": [w.eid(key)]})
    await _run(client, monkeypatch, "B11-SG-03", "ATTENDANCE.RECOMPUTE", call)


async def test_sg03b_calculate_range_company_wide_from_restricted_role(client, seeded_plan_catalogue, monkeypatch):
    """Omitting employee_ids means 'every employee': a SELF/REPORTEES/BRANCH caller must not be able to queue that."""
    w = await build_world(client)
    try:
        heads = {s: await scoped(w, "ATTENDANCE.RECOMPUTE", s, o[0]) for s, o in ATT_CASES.items()}
        await switch_role(monkeypatch, "app")
        res = {}
        for s, h in heads.items():
            before = await company_counts(w.cid)
            r = await client.post("/v1/attendance/days/calculate-range", headers=h, json={"date_from": DAY, "date_to": DAY})
            res[s] = {"status": r.status_code, "changed": diff(before, await company_counts(w.cid), NOIGNORE)}
        rec("B11-SG-03", "company-wide range (employee_ids omitted) from restricted roles", results=res)
        assert all(v["status"] in DENIED for v in res.values()), res
    finally:
        await drop_world(w, monkeypatch)


async def test_sg04_keep_leave(client, seeded_plan_catalogue, monkeypatch):
    """No real work-on-leave conflict is built (needs an approved leave + punches); the discriminator is that an out-of-scope day must be
    refused with 403/404 BEFORE the conflict check, whereas an unenforced route answers the conflict status (409) for any day id."""
    async def call(client, w, h, key, ctx):
        return await client.post(f"/v1/attendance/days/{ctx['days'][key]}/work-on-leave/keep-leave", headers=h, json={"reason": "b11 probe"})
    await _run(client, monkeypatch, "B11-SG-04", "ATTENDANCE.RECOMPUTE", call)


async def test_sg05_invite_employee(client, seeded_plan_catalogue, monkeypatch):
    """EMPLOYEE.INVITE: invites a named employee (creates an invite token row and an email record). Targets here are employees WITHOUT a login:
    NX (branch X, reports to M1) and NY (branch Y, reports to M2)."""
    cases = {"SELF": ("E1", [], ["NX", "NY"]), "REPORTEES": ("M1", ["NX"], ["NY"]), "BRANCH": ("BX", ["NX"], ["NY"])}
    w = await build_world(client)
    try:
        ids = {"NX": await mk_noaccount(client, w, "NX", w.branch_x, "M1"), "NY": await mk_noaccount(client, w, "NY", w.branch_y, "M2")}
        heads = {s: await scoped(w, "EMPLOYEE.INVITE", s, o) for s, (o, _i, _x) in cases.items()}
        await switch_role(monkeypatch, "app")
        rows, bad = [], []
        for scope, (owner, ins, outs) in cases.items():
            for key in outs:
                before = await company_counts(w.cid)
                r = await client.post(f"/v1/employees/{ids[key]}/invite", headers=heads[scope])
                changed = diff(before, await company_counts(w.cid), NOIGNORE)
                rows.append({"scope": scope, "owner": owner, "target": key, "in_scope": False, "status": r.status_code, "changed": changed})
                if r.status_code not in DENIED or changed:
                    bad.append(f"{scope}/{owner} invited out-of-scope {key}: HTTP {r.status_code}, tables changed {sorted(changed)}")
        invites = await q("SELECT count(*) n FROM account_invite WHERE company_id = :c AND employee_id = CAST(:e AS uuid)", c=str(w.cid), e=ids["NY"])
        rows.append({"invites_for_NY_after_all_probes": invites[0]["n"]})
        tb = w.people["B_ADMIN"].headers
        cross = await client.post(f"/v1/employees/{ids['NX']}/invite", headers=tb)
        rows.append({"control": "other-tenant admin", "status": cross.status_code})
        if cross.status_code in (200, 201):
            bad.append("CROSS-TENANT invite accepted")
        rec("B11-SG-05", "results", rows=rows, violations=bad)
        assert not bad, "scope NOT enforced: " + " | ".join(bad)
    finally:
        await drop_world(w, monkeypatch)


async def test_sg01b_calculate_unknown_and_foreign_employee_ids(client, seeded_plan_catalogue, monkeypatch):
    """Existence-oracle / referential check for `POST /attendance/days/calculate`: how does the route answer (a) a random UUID and (b) a UUID of an employee
    that exists in ANOTHER tenant, for the same tenant's COMPANY_ADMIN and for the other tenant's admin? A correct route answers both identically (404)."""
    from uuid import uuid4
    w = await build_world(client)
    try:
        await switch_role(monkeypatch, "app")
        res = {}
        for who in ("ADMIN", "B_ADMIN"):
            for label, eid in (("random-uuid", str(uuid4())), ("tenant-A-employee-E1", w.eid("E1"))):
                before_a, before_b = await company_counts(w.cid), await company_counts(w.tb.company_id)
                r = await client.post("/v1/attendance/days/calculate", headers=w.h(who), params={"employee_id": eid, "date": DAY})
                res[f"{who} / {label}"] = {"status": r.status_code, "A_changed": diff(before_a, await company_counts(w.cid), NOIGNORE),
                                           "B_changed": diff(before_b, await company_counts(w.tb.company_id), NOIGNORE), "code": (r.json().get("error") or {}).get("code") if r.status_code >= 400 else None}
        rec("B11-SG-01", "unknown vs foreign employee id", results=res)
        foreign = res["B_ADMIN / tenant-A-employee-E1"]["status"]
        unknown = res["B_ADMIN / random-uuid"]["status"]
        assert foreign in DENIED and unknown == foreign, f"other-tenant admin: foreign id -> {foreign}, random id -> {unknown} (must be identical 404): {res}"
    finally:
        await drop_world(w, monkeypatch)
