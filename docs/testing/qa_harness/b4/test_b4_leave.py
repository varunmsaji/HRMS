"""QA B4 - leave application -> approval/rejection/cancel -> ledger/balance consistency.

Catalogue ids: LEAVE-APPLY-001..004, LEAVE-APPR-001..004, LEAVE-CANCEL-001/002, LEAVE-CONC-001, LEAVE-LEDGER-001,
LEAVE-LOCK-001 (and the LV-28 replacement assertion from docs/testing/qa_live_errata/lv28_replacement.md).

Mounted read-only at /qa/b4 and run through entry.py (strict sandbox check first).  Evidence is written to
$QA_ARTIFACTS/<case>.jsonl BEFORE asserting.  The central invariant, asserted after EVERY scenario, is
    GET /leave-balances.balance  ==  SUM(leave_ledger.amount)  (database)
and ledger rows are never rewritten (leave_ledger is INSERT/SELECT-only for the runtime role).

Rules used as the oracle: PAYROLL_BUSINESS_DECISIONS BUS-004 (cancel authority), BUS-005 (no negative balance by default),
BUS-006 (approval that would overdraw: reject, or approve with excess as LOP - never silently negative).
Behaviour the documents leave open is RECORDED, not asserted (CL-03, CL-25).
Dates: Sept-Oct 2026, Mon 7 Sep 2026 is a Monday; the fixture calendar has Sunday as weekly off and the policy has the
sandwich rule enabled, so every range below stays inside Mon-Fri to keep the day count unambiguous.
"""

import asyncio
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_period import _insert_closed_period
from tests.integration.modules.attendance.test_employee_default_role_attendance import (
    _employee_user,
    _teardown,
    _tenant,
)
from tests.integration.modules.leave.test_leave_application import (
    _create_employee,
    _create_employment,
    _create_leave_type,
    _give_balance,
    _setup_calendar,
    _setup_leave_policy,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio
ART = Path(os.environ.get("QA_ARTIFACTS", "/tmp/qa-artifacts"))


def rec(case: str, step: str, **observed: Any) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    with (ART / f"{case}.jsonl").open("a") as fh:
        fh.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "step": step, **observed}, default=str) + "\n")


async def rows(company_id: Any, sql: str, **params: Any) -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        return [dict(r) for r in (await session.execute(text(sql), params)).mappings().all()]


async def ledger(cid: Any, eid: str) -> list[dict[str, Any]]:
    return await rows(cid, "SELECT entry_type, amount::text a, effective_date::text d FROM leave_ledger WHERE employee_id = :e ORDER BY created_at, id", e=eid)


async def balance(client: AsyncClient, h: dict[str, str], eid: str, lt: str | None = None) -> dict[str, Any]:
    r = await client.get("/v1/leave-balances", headers=h, params={"employee_id": eid})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    return dict(next(x for x in data if x["leave_type_id"] == lt) if lt else data[0])


async def invariant(client: AsyncClient, h: dict[str, str], cid: Any, eid: str, case: str, where: str, lt: str | None = None) -> Decimal:
    """balance (API) == SUM(ledger) (DB) and never negative (policy default, BUS-005)."""
    b = Decimal((await balance(client, h, eid, lt))["balance"])
    s = (await rows(cid, "SELECT COALESCE(SUM(amount),0)::text s FROM leave_ledger WHERE employee_id = :e AND (CAST(:lt AS uuid) IS NULL OR leave_type_id = CAST(:lt AS uuid))", e=eid, lt=lt))[0]["s"]
    rec(case, f"invariant @ {where}", api_balance=str(b), db_sum=s)
    assert b == Decimal(s), f"{where}: API balance {b} != ledger sum {s}"
    assert b >= 0, f"{where}: negative balance"
    return b


async def env(client: AsyncClient, t: Any, *, chain: str = "AUTO", bal: str = "20.00", login: bool = False, name: str = "Priya", **ver: Any) -> dict[str, Any]:
    lt = await _create_leave_type(client, t.admin)
    await _setup_calendar(client, t.admin)
    await _setup_leave_policy(client, t.admin, leave_type_id=lt["id"], approval_chain=chain, **ver)
    if login:
        eid, eh = await _employee_user(client, t, name)
    else:
        emp = await _create_employee(client, t.admin, name)
        await _create_employment(client, t.admin, employee_id=emp["id"], legal_entity_id=t.legal_entity_id)
        eid, eh = emp["id"], t.admin
    await _give_balance(client, t.admin, employee_id=eid, leave_type_id=lt["id"], amount=bal)
    return {"eid": eid, "eh": eh, "lt": lt["id"]}


async def apply(client: AsyncClient, h: dict[str, str], e: dict[str, Any], start: str, end: str, key: str | None = None, **extra: Any) -> Any:
    body = {"leave_type_id": e["lt"], "start_date": start, "end_date": end, **extra}
    return await client.post("/v1/leave-applications", headers={**h, "Idempotency-Key": key or str(uuid4())}, json=body)


# ===================================================================================== LEAVE-APPLY-001 / LEDGER-001
async def test_leave_apply_001_auto_chain_debits_once(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "LEAVE-APPLY-001"
    t = await _tenant(client)
    try:
        e = await env(client, t)
        assert await invariant(client, t.admin, t.company_id, e["eid"], c, "opening") == Decimal("20.00")
        r = await apply(client, t.admin, e, "2026-09-08", "2026-09-08", employee_id=e["eid"], reason="QA")
        rec(c, "apply", status=r.status_code, body=r.text[:300])
        assert r.status_code == 201, r.text
        d = r.json()["data"]
        assert d["status"] == "APPROVED" and d["total_days"] == "1.00"
        assert await invariant(client, t.admin, t.company_id, e["eid"], c, "after apply") == Decimal("19.00")
        led = await ledger(t.company_id, e["eid"])
        rec(c, "ledger", rows=led)
        assert [(x["entry_type"], x["a"]) for x in led][-1] == ("APPLICATION", "-1.00") and len(led) == 2
        apps = await rows(t.company_id, "SELECT status, total_days::text n FROM leave_application WHERE employee_id = :e", e=e["eid"])
        assert apps == [{"status": "APPROVED", "n": "1.00"}]
        proj = await rows(t.company_id, "SELECT count(*) n FROM leave_day_projection WHERE employee_id = :e AND status <> 'CANCELLED'", e=e["eid"])
        assert proj[0]["n"] == 1, "one attendance projection per leave day"
    finally:
        await _teardown(t)


# ===================================================================================== LEAVE-APPLY-002 / 003 / 004
async def test_leave_apply_002_003_004_refusals_change_nothing(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "LEAVE-APPLY-002"
    t = await _tenant(client)
    try:
        e = await env(client, t, bal="3.00")
        ok = await apply(client, t.admin, e, "2026-09-08", "2026-09-09", key="qa-key-0001", employee_id=e["eid"])
        assert ok.status_code == 201, ok.text
        first_id = ok.json()["data"]["id"]
        rep = await apply(client, t.admin, e, "2026-09-08", "2026-09-09", key="qa-key-0001", employee_id=e["eid"])
        mism = await apply(client, t.admin, e, "2026-09-15", "2026-09-15", key="qa-key-0001", employee_id=e["eid"])
        rec(c, "idempotency", replay=(rep.status_code, rep.json().get("data", {}).get("id") == first_id), mismatch=(mism.status_code, mism.json().get("error", {}).get("code")))
        assert rep.status_code in (200, 201) and rep.json()["data"]["id"] == first_id
        assert mism.status_code in (409, 422)
        assert await invariant(client, t.admin, t.company_id, e["eid"], c, "after replay") == Decimal("1.00")
        n_apps = (await rows(t.company_id, "SELECT count(*) n FROM leave_application WHERE employee_id=:e", e=e["eid"]))[0]["n"]
        assert n_apps == 1, "replay/mismatch must not create a second application"
        before_ledger = await ledger(t.company_id, e["eid"])

        c3 = "LEAVE-APPLY-003"
        overlap = await apply(client, t.admin, e, "2026-09-09", "2026-09-10", employee_id=e["eid"])
        over = await apply(client, t.admin, e, "2026-09-14", "2026-09-17", employee_id=e["eid"])        # 4 days > balance 1
        rec(c3, "refusals", overlap=(overlap.status_code, overlap.json().get("error", {}).get("code")), over_balance=(over.status_code, over.json().get("error", {}).get("code")))
        assert overlap.status_code in (409, 422) and over.status_code in (409, 422)
        assert await ledger(t.company_id, e["eid"]) == before_ledger
        assert (await rows(t.company_id, "SELECT count(*) n FROM leave_application WHERE employee_id=:e", e=e["eid"]))[0]["n"] == 1
        await invariant(client, t.admin, t.company_id, e["eid"], c3, "after refusals")

        c4 = "LEAVE-APPLY-004"
        bad = await apply(client, t.admin, e, "2026-09-18", "2026-09-17", employee_id=e["eid"])
        sun = await apply(client, t.admin, e, "2026-09-20", "2026-09-20", employee_id=e["eid"])     # Sunday = weekly off
        rec(c4, "end<start and Sunday-only", end_before_start=bad.status_code, sunday=(sun.status_code, sun.json().get("data", {}).get("total_days") if sun.status_code < 300 else sun.json().get("error", {}).get("code")))
        assert bad.status_code == 422
        after = await invariant(client, t.admin, t.company_id, e["eid"], c4, "after Sunday attempt")
        if sun.status_code < 300:       # CL-03: accepted -> must not have been silently charged
            assert after == Decimal("1.00") - Decimal(sun.json()["data"]["total_days"]) or sun.json()["data"]["total_days"] == "0.00"
        else:
            assert after == Decimal("1.00")
    finally:
        await _teardown(t)


# ===================================================================================== LEAVE-APPR-001 (+ LV-28 replacement)
async def test_leave_appr_001_hr_chain_pending_reserved_then_approved(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "LEAVE-APPR-001"
    t = await _tenant(client)
    try:
        e = await env(client, t, chain="HR", bal="10.00", login=True)
        sub = await client.post("/v1/leave-applications", headers={**e["eh"], "Idempotency-Key": str(uuid4())},
                                json={"leave_type_id": e["lt"], "start_date": "2026-09-08", "end_date": "2026-09-09"})
        rec(c, "employee submit", status=sub.status_code, body=sub.text[:300])
        assert sub.status_code == 201, sub.text
        ap = sub.json()["data"]
        assert ap["status"] in ("SUBMITTED", "PENDING", "PENDING_APPROVAL") or ap["approval_stage"] == "HR"
        # LV-28 replacement: pending does not debit, it is shown as reserved
        b = await balance(client, t.admin, e["eid"])
        rec("LV-28-REPLACEMENT", "pending balance", balance=b["balance"], reserved=b["reserved_balance"])
        assert Decimal(b["balance"]) == Decimal("10.00") and Decimal(b["reserved_balance"]) == Decimal("2.00")
        await invariant(client, t.admin, t.company_id, e["eid"], c, "pending")
        # employee cannot decide
        s_ap = await client.post(f"/v1/leave-applications/{ap['id']}/approve", headers={**e["eh"], "If-Match": str(ap["version"])}, json={})
        s_rj = await client.post(f"/v1/leave-applications/{ap['id']}/reject", headers={**e["eh"], "If-Match": str(ap["version"])}, json={"rejection_reason": "x"})
        rec("LEAVE-APPR-002", "employee decisions", approve=s_ap.status_code, reject=s_rj.status_code)
        assert s_ap.status_code == 403 and s_rj.status_code == 403
        stale = await client.post(f"/v1/leave-applications/{ap['id']}/approve", headers={**t.admin, "If-Match": "999"}, json={})
        rec(c, "stale If-Match", status=stale.status_code)
        assert stale.status_code in (409, 412, 428)
        assert await invariant(client, t.admin, t.company_id, e["eid"], c, "after refused decisions") == Decimal("10.00")
        ok = await client.post(f"/v1/leave-applications/{ap['id']}/approve", headers={**t.admin, "If-Match": str(ap["version"])}, json={})
        rec(c, "HR approve", status=ok.status_code, body=ok.text[:200])
        assert ok.status_code == 200 and ok.json()["data"]["status"] == "APPROVED"
        assert await invariant(client, t.admin, t.company_id, e["eid"], c, "approved") == Decimal("8.00")
        again = await client.post(f"/v1/leave-applications/{ap['id']}/approve", headers={**t.admin, "If-Match": str(ok.json()["data"]["version"])}, json={})
        rec(c, "double approve", status=again.status_code)
        assert again.status_code in (409, 422)
        assert await invariant(client, t.admin, t.company_id, e["eid"], c, "after double approve") == Decimal("8.00")
        assert (await balance(client, t.admin, e["eid"]))["reserved_balance"] in ("0.00", "0", "0.0")
        acts = [r["action"] for r in await rows(t.company_id, "SELECT action FROM leave_application_action ORDER BY created_at, id")]
        rec(c, "actions", actions=acts)
        # cross-tenant read
        t2 = await _tenant(client)
        try:
            foreign = await client.get(f"/v1/leave-applications/{ap['id']}", headers=t2.admin)
            rec("LEAVE-APPR-002", "cross tenant", status=foreign.status_code)
            assert foreign.status_code == 404
        finally:
            await _teardown(t2)
    finally:
        await _teardown(t)


# ===================================================================================== LEAVE-APPR-003
async def test_leave_appr_003_reject_releases_reservation(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "LEAVE-APPR-003"
    t = await _tenant(client)
    try:
        e = await env(client, t, chain="HR", bal="10.00", login=True)
        ap = (await client.post("/v1/leave-applications", headers={**e["eh"], "Idempotency-Key": str(uuid4())},
                                json={"leave_type_id": e["lt"], "start_date": "2026-09-08", "end_date": "2026-09-09"})).json()["data"]
        rj = await client.post(f"/v1/leave-applications/{ap['id']}/reject", headers={**t.admin, "If-Match": str(ap["version"])}, json={"rejection_reason": "QA"})
        rec(c, "reject", status=rj.status_code, body=rj.text[:200])
        assert rj.status_code == 200 and rj.json()["data"]["status"] == "REJECTED"
        b = await balance(client, t.admin, e["eid"])
        assert Decimal(b["balance"]) == Decimal("10.00") and Decimal(b["reserved_balance"]) == 0
        assert await invariant(client, t.admin, t.company_id, e["eid"], c, "after reject") == Decimal("10.00")
        assert len(await ledger(t.company_id, e["eid"])) == 1, "rejection writes no ledger row"
        cn = await client.post(f"/v1/leave-applications/{ap['id']}/cancel", headers={**t.admin, "If-Match": str(rj.json()["data"]["version"])}, json={"reason": "x"})
        rec(c, "cancel after reject", status=cn.status_code)
        assert cn.status_code in (409, 422)
    finally:
        await _teardown(t)


# ===================================================================================== LEAVE-APPR-004
async def test_leave_appr_004_competing_pending_requests_never_overdraw(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """Balance 3. Two pending 2-day applications (reservation is off, so both are accepted as pending). HR approves both.
    BUS-006: the second approval must be rejected or converted (excess as LOP) - never leave the balance negative.
    The exact choice is recorded."""
    c = "LEAVE-APPR-004"
    t = await _tenant(client)
    try:
        e = await env(client, t, chain="HR", bal="3.00", login=True)
        apps = []
        for s, en in (("2026-09-08", "2026-09-09"), ("2026-09-15", "2026-09-16")):
            r = await client.post("/v1/leave-applications", headers={**e["eh"], "Idempotency-Key": str(uuid4())}, json={"leave_type_id": e["lt"], "start_date": s, "end_date": en})
            rec(c, "submit", range=(s, en), status=r.status_code, body=r.text[:160])
            assert r.status_code == 201, r.text
            apps.append(r.json()["data"])
        res = []
        for a in apps:
            r = await client.post(f"/v1/leave-applications/{a['id']}/approve", headers={**t.admin, "If-Match": str(a["version"])}, json={})
            res.append((r.status_code, r.json().get("data", {}).get("status"), r.json().get("data", {}).get("lop_days"), r.json().get("error", {}).get("code")))
            await invariant(client, t.admin, t.company_id, e["eid"], c, f"after approval {len(res)}")
        rec(c, "approvals", results=res, ledger=await ledger(t.company_id, e["eid"]),
            apps=await rows(t.company_id, "SELECT status, total_days::text n, lop_days::text lop FROM leave_application WHERE employee_id=:e ORDER BY start_date", e=e["eid"]))
        final = Decimal((await balance(client, t.admin, e["eid"]))["balance"])
        assert final >= 0 and res[0][0] == 200
        assert res[1][0] == 409 and res[1][3] == "LEAVE_APPLICATION_BALANCE_SHORTFALL", "second approval must be refused with the shortfall (BUS-006)"
        led_refused = await ledger(t.company_id, e["eid"])
        # approver's explicit choice: approve the excess as loss of pay (BUS-006 second option)
        cur = (await client.get(f"/v1/leave-applications/{apps[1]['id']}", headers=t.admin)).json()["data"]
        lop = await client.post(f"/v1/leave-applications/{apps[1]['id']}/approve", headers={**t.admin, "If-Match": str(cur["version"])}, json={"excess_as_lop": True})
        rec(c, "approve excess as LOP", status=lop.status_code, lop_days=lop.json().get("data", {}).get("lop_days"), body=lop.text[:300])
        assert lop.status_code == 200 and lop.json()["data"]["status"] == "APPROVED"
        assert Decimal(lop.json()["data"]["lop_days"]) == Decimal("1.00"), "2 days applied, 1 day of balance left -> 1 day LOP"
        led_lop = await ledger(t.company_id, e["eid"])
        rec(c, "ledger after LOP approval", before=led_refused, after=led_lop)
        assert led_lop[: len(led_refused)] == led_refused and [(x["entry_type"], x["a"]) for x in led_lop[len(led_refused):]] == [("APPLICATION", "-1.00")], "only the covered day is debited"
        assert await invariant(client, t.admin, t.company_id, e["eid"], c, "after LOP approval") == Decimal("0.00")
    finally:
        await _teardown(t)


# ===================================================================================== LEAVE-CANCEL-001 / 002
async def test_leave_cancel_001_002(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "LEAVE-CANCEL-001"
    t = await _tenant(client)
    try:
        e = await env(client, t, bal="20.00")
        r = await apply(client, t.admin, e, "2026-09-08", "2026-09-08", employee_id=e["eid"])
        a = r.json()["data"]
        assert await invariant(client, t.admin, t.company_id, e["eid"], c, "approved") == Decimal("19.00")
        led_before = await ledger(t.company_id, e["eid"])
        stale = await client.post(f"/v1/leave-applications/{a['id']}/cancel", headers={**t.admin, "If-Match": "999"}, json={"reason": "QA"})
        assert stale.status_code in (409, 412, 428)
        cn = await client.post(f"/v1/leave-applications/{a['id']}/cancel", headers={**t.admin, "If-Match": str(a["version"])}, json={"reason": "QA recalled"})
        rec(c, "cancel", status=cn.status_code, body=cn.text[:200])
        assert cn.status_code == 200 and cn.json()["data"]["status"] == "CANCELLED"
        assert await invariant(client, t.admin, t.company_id, e["eid"], c, "cancelled") == Decimal("20.00")
        led = await ledger(t.company_id, e["eid"])
        rec(c, "ledger", before=led_before, after=led)
        assert led[: len(led_before)] == led_before, "original ledger rows are never rewritten"
        assert [(x["entry_type"], x["a"]) for x in led[len(led_before):]] == [("ADJUSTMENT", "1.00")], "exactly one offsetting credit"
        again = await client.post(f"/v1/leave-applications/{a['id']}/cancel", headers={**t.admin, "If-Match": str(cn.json()["data"]["version"])}, json={"reason": "again"})
        rec(c, "second cancel", status=again.status_code)
        assert again.status_code in (409, 422)
        assert await ledger(t.company_id, e["eid"]) == led and await invariant(client, t.admin, t.company_id, e["eid"], c, "after second cancel") == Decimal("20.00")
        proj = await rows(t.company_id, "SELECT status FROM leave_day_projection WHERE employee_id=:e", e=e["eid"])
        assert proj and all(p["status"] == "CANCELLED" for p in proj)

        c2 = "LEAVE-CANCEL-002"
        e2 = await env_second_policy(client, t)
        sub = (await client.post("/v1/leave-applications", headers={**e2["eh"], "Idempotency-Key": str(uuid4())},
                                 json={"leave_type_id": e2["lt"], "start_date": "2026-09-08", "end_date": "2026-09-08"})).json()["data"]
        cn2 = await client.post(f"/v1/leave-applications/{sub['id']}/cancel", headers={**e2["eh"], "If-Match": str(sub["version"])}, json={"reason": "changed my mind"})
        rec(c2, "employee cancels own pending", status=cn2.status_code, body=cn2.text[:200])
        assert cn2.status_code == 200 and cn2.json()["data"]["status"] == "CANCELLED"
        assert len(await ledger(t.company_id, e2["eid"])) == 1, "cancelling a pending request never touches the ledger"
        await invariant(client, t.admin, t.company_id, e2["eid"], c2, "after pending cancel", lt=e2["lt"])
    finally:
        await _teardown(t)


# ===================================================================================== LEAVE-CONC-001
async def test_leave_conc_001_parallel_requests_never_overdraw(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """6 parallel 4-day applications on disjoint Mon-Thu ranges against balance 20 -> exactly 5 accepted, balance 0,
    ledger == balance. Then 6 parallel applications for the SAME dates -> exactly one accepted. No negative balance."""
    c = "LEAVE-CONC-001"
    t = await _tenant(client)
    try:
        e = await env(client, t, bal="20.00")
        ranges = [("2026-09-07", "2026-09-10"), ("2026-09-14", "2026-09-17"), ("2026-09-21", "2026-09-24"),
                  ("2026-09-28", "2026-10-01"), ("2026-10-05", "2026-10-08"), ("2026-10-12", "2026-10-15")]
        rs = await asyncio.gather(*[apply(client, t.admin, e, s, en, employee_id=e["eid"]) for s, en in ranges])
        codes = [(r.status_code, r.json().get("error", {}).get("code")) for r in rs]
        rec(c, "6 disjoint x 4 days vs 20", results=codes)
        accepted = sum(1 for r in rs if r.status_code == 201)
        bal = await invariant(client, t.admin, t.company_id, e["eid"], c, "after disjoint race")
        assert accepted == 5 and bal == Decimal("0.00"), (accepted, bal)
        assert (await rows(t.company_id, "SELECT count(*) n FROM leave_application WHERE employee_id=:e AND status='APPROVED'", e=e["eid"]))[0]["n"] == 5

        e2 = await env_second_type(client, t)
        rs2 = await asyncio.gather(*[apply(client, t.admin, e2, "2026-11-02", "2026-11-02", employee_id=e2["eid"]) for _ in range(6)])
        codes2 = [r.status_code for r in rs2]
        rec(c, "6 identical dates", results=codes2)
        assert codes2.count(201) == 1
        assert await invariant(client, t.admin, t.company_id, e2["eid"], c, "after identical-date race") == Decimal("19.00")
        assert (await rows(t.company_id, "SELECT count(*) n FROM leave_application WHERE employee_id=:e", e=e2["eid"]))[0]["n"] == 1
    finally:
        await _teardown(t)


async def env_second_policy(client: AsyncClient, t: Any) -> dict[str, Any]:
    """Employee with a login on the same tenant, balance 5, under the existing AUTO policy is NOT what we need for a
    pending request, so this creates a second tenant-level HR-chain leave type + policy."""
    lt = await _create_leave_type(client, t.admin, code="SL", name="Sick Leave")
    await _setup_leave_policy(client, t.admin, leave_type_id=lt["id"], approval_chain="HR")
    eid, eh = await _employee_user(client, t, "Meera")
    await _give_balance(client, t.admin, employee_id=eid, leave_type_id=lt["id"], amount="5.00")
    return {"eid": eid, "eh": eh, "lt": lt["id"]}


async def env_second_type(client: AsyncClient, t: Any) -> dict[str, Any]:
    """A second employee reusing the tenant's existing leave type / policy / calendar."""
    lt = (await client.get("/v1/leave-types", headers=t.admin)).json()["data"][0]["id"]
    emp = await _create_employee(client, t.admin, "Second")
    await _create_employment(client, t.admin, employee_id=emp["id"], legal_entity_id=t.legal_entity_id)
    await _give_balance(client, t.admin, employee_id=emp["id"], leave_type_id=lt, amount="20.00")
    return {"eid": emp["id"], "eh": t.admin, "lt": lt}


# ===================================================================================== LEAVE-LOCK-001
async def test_leave_lock_001_closed_period_refuses_and_rolls_back(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """PD-3: leave for dates inside a CLOSED attendance period is refused and the whole transaction rolls back.
    (The CLOSED period row is inserted with the project's own test shortcut; the real close flow is B2.)"""
    c = "LEAVE-LOCK-001"
    t = await _tenant(client)
    try:
        e = await env(client, t, chain="HR", bal="10.00", login=True)
        sub = (await client.post("/v1/leave-applications", headers={**e["eh"], "Idempotency-Key": str(uuid4())},
                                 json={"leave_type_id": e["lt"], "start_date": "2026-09-08", "end_date": "2026-09-08"})).json()["data"]
        await _insert_closed_period(company_id=t.company_id, period_start="2026-09-01", period_end="2026-09-30", legal_entity_id=t.legal_entity_id)
        led0 = await ledger(t.company_id, e["eid"])
        ap = await client.post(f"/v1/leave-applications/{sub['id']}/approve", headers={**t.admin, "If-Match": str(sub["version"])}, json={})
        new = await client.post("/v1/leave-applications", headers={**e["eh"], "Idempotency-Key": str(uuid4())},
                                json={"leave_type_id": e["lt"], "start_date": "2026-09-09", "end_date": "2026-09-09"})
        rec(c, "closed period", approve=(ap.status_code, ap.json().get("error", {}).get("code")), new_application=(new.status_code, new.json().get("error", {}).get("code") if new.status_code >= 300 else "created"))
        assert ap.status_code in (409, 422), ap.text
        st = await rows(t.company_id, "SELECT status FROM leave_application WHERE id = :i", i=sub["id"])
        assert st == [{"status": "SUBMITTED"}] or st[0]["status"] in ("PENDING", "PENDING_APPROVAL"), st
        assert await ledger(t.company_id, e["eid"]) == led0, "failed approval must leave the ledger untouched"
        assert (await rows(t.company_id, "SELECT count(*) n FROM leave_day_projection WHERE employee_id=:e", e=e["eid"]))[0]["n"] == 0
        await invariant(client, t.admin, t.company_id, e["eid"], c, "after refused approval")
        if new.status_code < 300:
            rec(c, "NOTE", detail="submitting a PENDING application into a closed period was accepted; approval is what is refused")
    finally:
        await _teardown(t)
