"""B10-4: do custom roles with a RESTRICTED scope on a permission whose route ignores the scope silently become company-wide?
(No API can create such roles today - roles are created by seed/DB - so this documents latent risk, it does not show an exploitable path.)"""
from uuid import UUID

import pytest
from tests.integration.modules.attendance.test_attendance_security import _create_permission_scoped_user
from tests.integration.modules.leave.test_leave_application import _create_leave_type, _give_balance, _setup_calendar, _setup_leave_policy
from world import build_world, company_counts, diff, drop_world, q, rec, switch_role

pytestmark = pytest.mark.asyncio


# DEF-B10-01 was a strict xfail until the 2026-10-26 fix (hradm-20261026a): it XPASSed(strict) on the fixed code, then the marker was removed.
# Original reason: POST /v1/leave-ledger/adjustments ignored the data scope of LEAVE.BALANCE_ADJUST.
async def test_restricted_scope_on_scope_ignoring_routes(client, seeded_plan_catalogue, monkeypatch):
    c = "B10-CUSTOM-SCOPE"
    w = await build_world(client)
    try:
        h = w.h("ADMIN")
        lt = await _create_leave_type(client, h)
        await _setup_calendar(client, h)
        await _setup_leave_policy(client, h, leave_type_id=lt["id"], approval_chain="MANAGER")
        for who in ("E1", "E3"):
            await _give_balance(client, h, employee_id=w.eid(who), leave_type_id=lt["id"], amount="5.00")
        roles = {}
        for perm, scope, owner in (("LEAVE.BALANCE_ADJUST", "SELF", "E1"), ("ATTENDANCE.RECOMPUTE", "SELF", "E1"), ("ATTENDANCE.PUNCH_ON_BEHALF", "REPORTEES", "M1")):
            hh, uid = await _create_permission_scoped_user(company_id=w.cid, permission_codes=[perm], data_scope=scope, caller_employee_id=UUID(w.eid(owner)))
            roles[perm] = (hh, scope, owner)
        await switch_role(monkeypatch, "app")
        before = await company_counts(w.cid)
        res = {}
        hh, scope, owner = roles["LEAVE.BALANCE_ADJUST"]
        r = await client.post("/v1/leave-ledger/adjustments", headers=hh, json={"employee_id": w.eid("E3"), "leave_type_id": lt["id"], "amount": "100.00", "effective_date": "2026-09-01", "reason": "b10 custom-scope probe"})
        res["LEAVE.BALANCE_ADJUST @SELF (owner E1) adjusts E3's balance"] = r.status_code
        hh, scope, owner = roles["ATTENDANCE.RECOMPUTE"]
        r = await client.post("/v1/attendance/days/calculate", headers=hh, params={"employee_id": w.eid("E3"), "date": "2026-09-08"})
        res["ATTENDANCE.RECOMPUTE @SELF (owner E1) recomputes E3's day"] = r.status_code
        hh, scope, owner = roles["ATTENDANCE.PUNCH_ON_BEHALF"]
        r = await client.post("/v1/attendance/punches", headers=hh, json={"employee_id": w.eid("E3"), "punch_time": "2026-09-08T09:00:00Z", "direction": "IN", "reference": "b10"})
        res["ATTENDANCE.PUNCH_ON_BEHALF @REPORTEES (owner M1) punches for E3 (not M1's report)"] = r.status_code
        r2 = await client.post("/v1/attendance/punches", headers=hh, json={"employee_id": w.eid("E1"), "punch_time": "2026-09-08T09:01:00Z", "direction": "IN", "reference": "b10"})
        res["same role punches for E1 (M1's report)"] = r2.status_code
        ledger = (await q("SELECT COALESCE(sum(amount),0)::text s FROM leave_ledger WHERE employee_id = CAST(:e AS uuid) AND company_id = :c", e=w.eid("E3"), c=str(w.cid)))[0]["s"]
        rec(c, "restricted-scope custom roles on scope-ignoring routes", results=res, e3_ledger_sum=ledger, changed=diff(before, await company_counts(w.cid)))
        out_of_scope_ok = [k for k, v in res.items() if "E3" in k and v in (200, 201)]
        rec(c, "VERDICT", out_of_scope_actions_accepted=out_of_scope_ok)
        assert not out_of_scope_ok, out_of_scope_ok
    finally:
        await drop_world(w, monkeypatch)
