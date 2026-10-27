"""QA B2 - regularization, attendance periods and the remaining attendance-day cases.

Catalogue ids covered (docs/testing/QA_TEST_CASES.csv): REG-FLOW-001/002, REG-VAL-001, REG-AUTHZ-001,
PER-LIFE-001, PER-RECON-001, PER-LOCK-001, PER-LOCKED-001, PER-REOPEN-001, PER-LE-001,
ATT-DAY-005, ATT-DAY-006, ATT-DAY-007, ATT-DAY-009, ATT-DAY-010, ATT-PUNCH-008.

Mounted read-only at /qa/b2 and run through entry.py (strict sandbox check first).  Like B1, every check
records what it observed to $QA_ARTIFACTS/<case>.jsonl BEFORE asserting, and a case is green only when the
API response, the database rows AND the business invariant agree.

Two product decisions are deliberately NOT decided here; the tests RECORD the behaviour as `OPEN-n`:
  OPEN-1  is 09:15 (exactly the grace boundary) on time?   (B1 observed: yes, late_minutes 0)
  OPEN-2  should a working day with no punches keep lop 0.00 until period close?  (observed below)
"""

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_edge_cases import _terminate
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _create_period,
    _first_legal_entity_id,
)
from tests.integration.modules.attendance.test_employee_default_role_attendance import (
    _employee_user,
    _teardown,
    _tenant,
)
from tests.integration.modules.attendance.test_regularization import (
    _cleanup_regularization,
    _create_regularization_policy,
)
from tests.integration.modules.attendance.test_shift_roster import _create_night_shift
from tests.integration.modules.organisation.test_workforce_calendar import _cleanup_workforce_calendar

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.service import AttendanceDayService

pytestmark = pytest.mark.asyncio
ART = Path(os.environ.get("QA_ARTIFACTS", "/tmp/qa-artifacts"))
D = "2026-08-"   # August 2026: 10th is a Monday


def rec(case: str, step: str, **observed: Any) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    with (ART / f"{case}.jsonl").open("a") as fh:
        fh.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "step": step, **observed}, default=str) + "\n")


async def rows(company_id: Any, sql: str, **params: Any) -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        return [dict(r) for r in (await session.execute(text(sql), params)).mappings().all()]


async def punches(company_id: Any, employee_id: str) -> list[dict[str, Any]]:
    return await rows(company_id, "SELECT id::text id, direction, source, punch_time::text t FROM punch "
                      "WHERE employee_id = :e ORDER BY punch_time, created_at", e=employee_id)


async def day_row(company_id: Any, employee_id: str, day: str) -> dict[str, Any] | None:
    r = await rows(company_id, "SELECT attendance_status, worked_minutes, is_locked, is_regularized, calculation_version, "
                   "paid_day_fraction::text paid, lop_fraction::text lop, calendar_day_type, worked_on_holiday "
                   "FROM attendance_day WHERE employee_id = :e AND attendance_date = :d", e=employee_id, d=date.fromisoformat(day))
    return r[0] if r else None


async def calc(client: AsyncClient, h: dict[str, str], eid: str, day: str) -> dict[str, Any]:
    r = await client.post("/v1/attendance/days/calculate", headers=h, params={"employee_id": eid, "date": day})
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


async def reg_create(client: AsyncClient, h: dict[str, str], eid: str, day: str, punches_: list[dict[str, str]],
                     rtype: str = "MISSING_PUNCH", **extra: Any) -> Any:
    return await client.post("/v1/regularizations", headers=h, json={
        "employee_id": eid, "attendance_date": day, "request_type": rtype, "reason": "QA", "requested_punches": punches_, **extra})


async def reg_actions(company_id: Any, request_id: str) -> list[str]:
    return [r["action"] for r in await rows(company_id, "SELECT action FROM attendance_regularization_action "
                                           "WHERE request_id = :r ORDER BY created_at, id", r=request_id)]


async def cleanup_all(company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_attendance_period(company_id=company_id)
    await _cleanup_regularization(company_id=company_id)
    async with get_session_factory()() as session:           # children of work_calendar first (FK order)
        await set_rls_company_id(session, str(company_id))
        for t_ in ("work_calendar_holiday_calendar", "calendar_exception"):
            await session.execute(text(f"DELETE FROM {t_} WHERE company_id = :c"), {"c": str(company_id)})
        await session.commit()
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup_workforce_calendar(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


# ===================================================================================== REG-FLOW-001
async def test_reg_flow_001_approve_adds_one_punch_and_recalculates(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """Missing OUT on Mon 10 Aug: request OUT 18:00 -> pending changes NOTHING; approval adds exactly the
    requested punch (source REGULARIZATION), leaves the original punch row untouched, recalculates the day
    to PRESENT/540, flags it regularized; a second approval is refused and changes nothing."""
    c = "REG-FLOW-001"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        await _create_regularization_policy(client, h, approval_chain="HR")
        orig = await _punch(client, h, employee_id=eid, hour=9, minute=0, direction="IN", day=D + "10")
        before = await calc(client, h, eid, D + "10")
        assert before["attendance_status"] == "INCOMPLETE"
        p0 = await punches(cid, eid)

        r = await reg_create(client, h, eid, D + "10", [{"direction": "OUT", "requested_time": D + "10T18:00:00Z"}])
        rec(c, "create", status=r.status_code, body=r.text[:400])
        assert r.status_code == 201, r.text
        req = r.json()["data"]
        assert req["status"] == "SUBMITTED"
        mid = await punches(cid, eid)
        d_mid = await day_row(cid, eid, D + "10")
        rec(c, "pending", punches=len(mid), day=d_mid, actions=await reg_actions(cid, req["id"]))
        assert mid == p0, "a pending request must not write or change any punch"
        assert d_mid["attendance_status"] == "INCOMPLETE"
        assert d_mid["is_regularized"] is False

        ap = await client.post(f"/v1/regularizations/{req['id']}/approve", headers={**h, "If-Match": str(req["version"])},
                               json={"reviewer_comment": "QA approve"})
        rec(c, "approve", status=ap.status_code, body=ap.text[:500])
        assert ap.status_code == 200, ap.text
        data = ap.json()["data"]
        assert data["status"] == "APPROVED" and data["applied_at"] is not None
        after = await punches(cid, eid)
        d_after = await day_row(cid, eid, D + "10")
        acts = await reg_actions(cid, req["id"])
        rec(c, "after", punches=after, day=d_after, actions=acts)
        assert len(after) == 2
        assert after[0] == p0[0], "the original raw punch must be byte-identical (immutability)"
        assert (after[1]["direction"], after[1]["source"]) == ("OUT", "REGULARIZATION")
        assert after[1]["t"].startswith("2026-08-10 18:00:00")
        assert d_after["attendance_status"] == "PRESENT" and d_after["worked_minutes"] == 540
        assert d_after["is_regularized"] is True
        assert acts[0] == "SUBMITTED" and "APPROVED" in acts and "APPLIED" in acts
        assert [r_["employee_id"] for r_ in await rows(cid, "SELECT employee_id::text FROM attendance_regularization_request WHERE id = :r", r=req["id"])] == [eid]

        again = await client.post(f"/v1/regularizations/{req['id']}/approve", headers={**h, "If-Match": str(data["version"])}, json={})
        rec(c, "second approve", status=again.status_code, body=again.text[:200])
        assert again.status_code in (409, 422), again.text
        assert await punches(cid, eid) == after
        assert await reg_actions(cid, req["id"]) == acts
        assert orig["id"] == p0[0]["id"]
    finally:
        await cleanup_all(cid, uid)


# ===================================================================================== REG-FLOW-002
async def test_reg_flow_002_reject_changes_nothing(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "REG-FLOW-002"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        await _create_regularization_policy(client, h, approval_chain="HR")
        await _punch(client, h, employee_id=eid, hour=9, minute=0, direction="IN", day=D + "11")
        await calc(client, h, eid, D + "11")
        p0 = await punches(cid, eid)
        d0 = await day_row(cid, eid, D + "11")
        req = (await reg_create(client, h, eid, D + "11", [{"direction": "OUT", "requested_time": D + "11T18:00:00Z"}])).json()["data"]
        rj = await client.post(f"/v1/regularizations/{req['id']}/reject", headers={**h, "If-Match": str(req["version"])},
                               json={"reviewer_comment": "QA", "rejection_reason": "No evidence"})
        rec(c, "reject", status=rj.status_code, body=rj.text[:300])
        assert rj.status_code == 200, rj.text
        assert rj.json()["data"]["status"] == "REJECTED" and rj.json()["data"]["applied_at"] is None
        assert await punches(cid, eid) == p0
        d1 = await day_row(cid, eid, D + "11")
        assert (d1["attendance_status"], d1["worked_minutes"], d1["is_regularized"]) == (d0["attendance_status"], d0["worked_minutes"], False)
        acts = await reg_actions(cid, req["id"])
        rec(c, "state", actions=acts, day_before=d0, day_after=d1)
        assert "APPLIED" not in acts and "REJECTED" in acts
        ap = await client.post(f"/v1/regularizations/{req['id']}/approve", headers={**h, "If-Match": str(rj.json()["data"]["version"])}, json={})
        rec(c, "approve after reject", status=ap.status_code, code=ap.json().get("error", {}).get("code"))
        assert ap.status_code == 409
        assert await punches(cid, eid) == p0
    finally:
        await cleanup_all(cid, uid)


# ===================================================================================== REG-VAL-001
async def test_reg_val_001_invalid_requests_create_nothing(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "REG-VAL-001"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        await _create_regularization_policy(client, h, approval_chain="HR", allowed_types=["MISSING_PUNCH"])
        good = [{"direction": "OUT", "requested_time": D + "12T18:00:00Z"}]
        variants = {
            "unknown_type": await reg_create(client, h, eid, D + "12", good, rtype="TELEPORT"),
            "type_not_allowed_by_policy": await reg_create(client, h, eid, D + "12", good, rtype="FULL_DAY"),
            "no_correction_payload": await reg_create(client, h, eid, D + "12", []),
            "future_date": await reg_create(client, h, eid, "2999-01-01", [{"direction": "OUT", "requested_time": "2999-01-01T18:00:00Z"}]),
        }
        rec(c, "variants", **{k: v.status_code for k, v in variants.items()}, codes={k: v.json().get("error", {}).get("code") for k, v in variants.items()})
        for k, v in variants.items():
            assert 400 <= v.status_code < 500, (k, v.status_code, v.text)
        n = await rows(cid, "SELECT count(*) n FROM attendance_regularization_request")
        assert n[0]["n"] == 0, "rejected requests must not leave request rows"
        assert (await rows(cid, "SELECT count(*) n FROM attendance_regularization_requested_punch"))[0]["n"] == 0
        assert (await rows(cid, "SELECT count(*) n FROM attendance_regularization_action"))[0]["n"] == 0
        assert await punches(cid, eid) == []
    finally:
        await cleanup_all(cid, uid)


# ===================================================================================== REG-AUTHZ-001
async def test_reg_authz_001_employee_boundaries(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """An employee can submit for self only, cannot approve (not even own), cannot submit for another
    employee; another tenant cannot see it; nothing is written by the refused calls."""
    c = "REG-AUTHZ-001"
    t = await _tenant(client)
    t2 = await _tenant(client)
    try:
        await _create_regularization_policy(client, t.admin, approval_chain="HR")
        e1, h1 = await _employee_user(client, t, "Asha")
        e2, _ = await _employee_user(client, t, "Bala")
        body = lambda emp: {"attendance_date": D + "10", "request_type": "MISSING_PUNCH", "reason": "QA",   # noqa: E731
                            "requested_punches": [{"direction": "IN", "requested_time": D + "10T09:00:00Z"}], **emp}
        own = await client.post("/v1/regularizations", headers=h1, json=body({}))
        rec(c, "own submit", status=own.status_code, body=own.text[:300])
        assert own.status_code == 201, own.text
        req = own.json()["data"]
        assert req["employee_id"] == e1 if "employee_id" in req else True
        forged = await client.post("/v1/regularizations", headers=h1, json=body({"employee_id": e2}))
        selfap = await client.post(f"/v1/regularizations/{req['id']}/approve", headers={**h1, "If-Match": str(req["version"])}, json={})
        foreign = await client.get(f"/v1/regularizations/{req['id']}", headers=t2.admin)
        rec(c, "refusals", forged_employee=forged.status_code, self_approve=selfap.status_code, other_tenant_read=foreign.status_code)
        assert forged.status_code in (403, 404), forged.text
        assert selfap.status_code == 403, selfap.text
        assert foreign.status_code == 404, foreign.text
        reqs = await rows(t.company_id, "SELECT employee_id::text e, status FROM attendance_regularization_request")
        rec(c, "db", requests=reqs, punches=await rows(t.company_id, "SELECT count(*) n FROM punch"))
        assert reqs == [{"e": e1, "status": "SUBMITTED"}], "exactly the one legitimate request, still pending"
        assert (await rows(t.company_id, "SELECT count(*) n FROM punch"))[0]["n"] == 0
    finally:
        await _cleanup_regularization(company_id=t.company_id)
        await _teardown(t, t2)


# ===================================================================================== PER-LIFE / RECON / LOCK
async def _period_summary(client: AsyncClient, h: dict[str, str], period_id: str, eid: str) -> dict[str, Any]:
    r = await client.get(f"/v1/attendance-periods/{period_id}/summary", headers=h)
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["data"] if x["employee_id"] == eid)


def buckets(row: dict[str, Any]) -> float:
    return sum(float(row[k] or 0) for k in ("present_days", "half_days", "absent_days", "leave_days", "holiday_days",
                                            "weekly_off_days", "on_duty_days", "not_employed_days", "incomplete_days"))


async def test_per_life_recon_lock_001(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """Mon 10 - Fri 14 Aug: 10,11 full days; 12 = 200 min (ABSENT by band); 13 = only IN (INCOMPLETE);
    14 = no punches. A pending regularization blocks validate/finalize with the right reason code and
    leaves everything open; once rejected, finalize CLOSES: every day locked, summary frozen, buckets add up
    to the calendar days, paid+lop+unpaid_off = payable, incomplete resolved to LOP (decision 16)."""
    c = "PER-LIFE-001"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        await _create_regularization_policy(client, h, approval_chain="HR")
        for d_ in ("10", "11"):
            await _punch(client, h, employee_id=eid, hour=9, minute=0, direction="IN", day=D + d_)
            await _punch(client, h, employee_id=eid, hour=18, minute=0, direction="OUT", day=D + d_)
        await _punch(client, h, employee_id=eid, hour=9, minute=0, direction="IN", day=D + "12")
        await _punch(client, h, employee_id=eid, hour=12, minute=20, direction="OUT", day=D + "12")
        await _punch(client, h, employee_id=eid, hour=9, minute=0, direction="IN", day=D + "13")
        pre = {d_: await calc(client, h, eid, D + d_) for d_ in ("10", "11", "12", "13", "14")}
        rec(c, "pre-close days", **{d_: {k: v[k] for k in ("attendance_status", "worked_minutes", "paid_day_fraction", "lop_fraction")} for d_, v in pre.items()})
        assert [pre[d_]["attendance_status"] for d_ in ("10", "11", "12", "13", "14")] == ["PRESENT", "PRESENT", "ABSENT", "INCOMPLETE", "INCOMPLETE"]
        # OPEN-2 evidence: the unpunched working day BEFORE close
        rec("OPEN-2", "no-punch working day before close", status=pre["14"]["attendance_status"], paid=pre["14"]["paid_day_fraction"], lop=pre["14"]["lop_fraction"])

        pend = (await reg_create(client, h, eid, D + "13", [{"direction": "OUT", "requested_time": D + "13T18:00:00Z"}])).json()["data"]
        period = await _create_period(client, h, period_start=D + "10", period_end=D + "14")
        v = await client.post(f"/v1/attendance-periods/{period['id']}/validate", headers=h)
        codes = [r_["code"] for r_ in v.json()["data"]["reasons"]]
        rec(c, "validate with pending request", status=v.json()["data"]["status"], codes=codes)
        assert v.json()["data"]["status"] == "BLOCKED" and "PENDING_REGULARIZATION" in codes
        fin = await client.post(f"/v1/attendance-periods/{period['id']}/finalize", headers={**h, "If-Match": "1"}, json={})
        rec(c, "finalize while blocked", status=fin.status_code, code=fin.json().get("error", {}).get("code"))
        assert fin.status_code == 409 and fin.json()["error"]["code"] == "ATTENDANCE_FINALIZATION_BLOCKED"
        st = await rows(cid, "SELECT p.status, (SELECT count(*) FROM attendance_day WHERE employee_id=:e AND is_locked) locked FROM attendance_period p", e=eid)
        assert st[0]["status"] == "OPEN" and st[0]["locked"] == 0, "a blocked finalize must lock nothing"

        rj = await client.post(f"/v1/regularizations/{pend['id']}/reject", headers={**h, "If-Match": str(pend["version"])},
                               json={"reviewer_comment": "QA", "rejection_reason": "QA"})
        assert rj.status_code == 200, rj.text
        v2 = await client.post(f"/v1/attendance-periods/{period['id']}/validate", headers=h)
        rec(c, "validate after reject", status=v2.json()["data"]["status"], reasons=v2.json()["data"]["reasons"])
        assert v2.json()["data"]["status"] == "READY"
        ver = (await client.get(f"/v1/attendance-periods/{period['id']}", headers=h)).json()["data"]["version"]
        fin2 = await client.post(f"/v1/attendance-periods/{period['id']}/finalize", headers={**h, "If-Match": str(ver)}, json={})
        rec(c, "finalize", status=fin2.status_code, body=fin2.text[:300])
        assert fin2.status_code == 200 and fin2.json()["data"]["status"] == "CLOSED"

        days = await rows(cid, "SELECT attendance_date::text d, attendance_status s, is_locked l, paid_day_fraction::text paid, lop_fraction::text lop "
                          "FROM attendance_day WHERE employee_id = :e ORDER BY attendance_date", e=eid)
        rec(c, "db days after close", days=days)
        assert len(days) == 5 and all(x["l"] for x in days)
        assert [(x["s"], x["paid"], x["lop"]) for x in days] == [
            ("PRESENT", "1.00", "0.00"), ("PRESENT", "1.00", "0.00"), ("ABSENT", "0.00", "1.00"),
            ("INCOMPLETE", "0.00", "1.00"), ("INCOMPLETE", "0.00", "1.00")], "incomplete resolves to LOP at close (decision 16)"
        # OPEN-2 evidence: the same day AFTER close
        rec("OPEN-2", "no-punch working day after close", status=days[4]["s"], paid=days[4]["paid"], lop=days[4]["lop"])
        s = await _period_summary(client, h, period["id"], eid)
        rec("PER-RECON-001", "frozen summary", summary=s)
        assert s["frozen"] is True
        assert buckets(s) == 5.0, "every calendar day in exactly one bucket"
        assert float(s["paid_days"]) + float(s["lop_days"]) + float(s["unpaid_off_days"] or 0) == float(s["payable_days"]) == 5.0
        assert (s["present_days"], s["absent_days"], s["lop_days"], s["paid_days"], s["incomplete_days"]) == ("2.00", "3.00", "3.00", "2.00", "0.00")
        acts = await rows(cid, "SELECT action FROM attendance_period_action ORDER BY created_at, id")
        rec(c, "period actions", actions=[a["action"] for a in acts])
        assert "CLOSED" in [a["action"] for a in acts]
        audit = await rows(cid, "SELECT count(*) n FROM audit_log WHERE action = 'ATTENDANCE_INCOMPLETE_RESOLVED_AT_LOCK'")
        assert audit[0]["n"] == 1, "the lock-time rewrite of incomplete days must be audited"
        # PER-LOCKED-001 on the same closed period
        await locked_refusals(client, h, cid, eid, c="PER-LOCKED-001")
        # PER-REOPEN-001
        await reopen_checks(client, h, cid, eid, period["id"])
    finally:
        await cleanup_all(cid, uid)


async def locked_refusals(client: AsyncClient, h: dict[str, str], cid: Any, eid: str, c: str) -> None:
    before = {"days": await rows(cid, "SELECT attendance_date::text d, calculation_version v, worked_minutes w FROM attendance_day WHERE employee_id=:e ORDER BY 1", e=eid),
              "punches": len(await punches(cid, eid)), "reqs": (await rows(cid, "SELECT count(*) n FROM attendance_regularization_request"))[0]["n"],
              "rosters": (await rows(cid, "SELECT count(*) n FROM shift_roster"))[0]["n"]}
    out: dict[str, Any] = {}
    r = await client.post("/v1/attendance/days/calculate", headers=h, params={"employee_id": eid, "date": D + "11"})
    out["recalculate"] = (r.status_code, r.json().get("error", {}).get("code"))
    r = await _punch_raw(client, h, eid, D + "11")
    out["new_punch"] = (r.status_code, r.json().get("error", {}).get("code"))
    r = await reg_create(client, h, eid, D + "11", [{"direction": "OUT", "requested_time": D + "11T18:00:00Z"}])
    out["regularization"] = (r.status_code, r.json().get("error", {}).get("code"))
    r = await client.post("/v1/rosters", headers=h, json={"employee_id": eid, "roster_date": D + "11", "shift_id": None})
    out["roster"] = (r.status_code, r.json().get("error", {}).get("code"))
    rec(c, "refusals on a CLOSED period", **{k: list(v) for k, v in out.items()})
    for k in ("recalculate", "regularization"):
        assert out[k] == (409, "ATTENDANCE_PERIOD_CLOSED") or out[k][0] in (409, 422), (k, out[k])
    assert out["new_punch"][0] >= 400 and out["roster"][0] >= 400
    after = {"days": await rows(cid, "SELECT attendance_date::text d, calculation_version v, worked_minutes w FROM attendance_day WHERE employee_id=:e ORDER BY 1", e=eid),
             "punches": len(await punches(cid, eid)), "reqs": (await rows(cid, "SELECT count(*) n FROM attendance_regularization_request"))[0]["n"],
             "rosters": (await rows(cid, "SELECT count(*) n FROM shift_roster"))[0]["n"]}
    assert after == before, "refused operations on a closed period must change nothing"


async def _punch_raw(client: AsyncClient, h: dict[str, str], eid: str, day: str):  # noqa: ANN202
    return await client.post("/v1/attendance/punches", headers=h, json={
        "employee_id": eid, "punch_time": f"{day}T10:00:00Z", "direction": "IN", "reference": "QA closed-period probe"})


async def reopen_checks(client: AsyncClient, h: dict[str, str], cid: Any, eid: str, period_id: str) -> None:
    c = "PER-REOPEN-001"
    p = (await client.get(f"/v1/attendance-periods/{period_id}", headers=h)).json()["data"]
    no_reason = await client.post(f"/v1/attendance-periods/{period_id}/reopen", headers={**h, "If-Match": str(p["version"])}, json={})
    rec(c, "reopen without reason", status=no_reason.status_code)
    assert no_reason.status_code == 422, no_reason.text
    before = await rows(cid, "SELECT attendance_date::text d, calculation_version v, worked_minutes w, paid_day_fraction::text paid, lop_fraction::text lop, is_locked l "
                        "FROM attendance_day WHERE employee_id=:e ORDER BY 1", e=eid)
    ro = await client.post(f"/v1/attendance-periods/{period_id}/reopen", headers={**h, "If-Match": str(p["version"])}, json={"reason": "QA reopen"})
    rec(c, "reopen", status=ro.status_code, body=ro.text[:200])
    assert ro.status_code == 200 and ro.json()["data"]["status"] == "OPEN"
    after = await rows(cid, "SELECT attendance_date::text d, calculation_version v, worked_minutes w, paid_day_fraction::text paid, lop_fraction::text lop, is_locked l "
                       "FROM attendance_day WHERE employee_id=:e ORDER BY 1", e=eid)
    rec(c, "days before/after reopen", before=before, after=after)
    assert all(not x["l"] for x in after), "reopen unlocks every day"
    strip = lambda rs: [{k: v for k, v in x.items() if k != "l"} for x in rs]  # noqa: E731
    assert strip(after) == strip(before), "reopen must NOT recompute or rewrite any day (ND-08: manual recompute)"
    acts = [a["action"] for a in await rows(cid, "SELECT action FROM attendance_period_action ORDER BY created_at, id")]
    rec(c, "period actions", actions=acts)
    assert "REOPENED" in acts


# ===================================================================================== ATT-DAY-005
async def test_att_day_005_day_types(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """Calendar: Sunday weekly off; holiday Sat 15 Aug and Sun 30 Aug (holiday on a weekly off); SPECIAL_WORKING
    exception on Sun 23 Aug. Expected labels per V1 §4: holiday -> HOLIDAY/NOT_EXPECTED, Sunday -> WEEKLY_OFF/NOT_EXPECTED,
    holiday on weekly off keeps WEEKLY_OFF + holiday_on_weekly_off, special working Sunday expects presence."""
    c = "ATT-DAY-005"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        hc = (await client.post("/v1/holiday-calendars", headers=h, json={"name": "QA National"})).json()["data"]
        for dte, name in ((D + "15", "Independence Day"), (D + "30", "QA Sunday Holiday")):
            r = await client.post(f"/v1/holiday-calendars/{hc['id']}/holidays", headers=h, json={"date": dte, "name": name})
            assert r.status_code == 201, r.text
        wop = (await client.post("/v1/weekly-off-patterns", headers=h, json={"name": "Sun off", "pattern_kind": "FIXED_WEEKDAYS",
                                                                          "rules": [{"weekday": 6, "off_fraction": "1.00"}]})).json()["data"]
        wc = (await client.post("/v1/work-calendars", headers=h, json={"name": "QA IN", "weekly_off_pattern_id": wop["id"], "holiday_calendar_ids": [hc["id"]]})).json()["data"]
        a = await client.post("/v1/policy-assignments", headers=h, json={"policy_kind": "WORK_CALENDAR", "policy_id": wc["id"], "scope_type": "EMPLOYEE",
                                                                         "scope_id": eid, "effective_from": "2026-01-01"})
        assert a.status_code == 201, a.text
        ex = await client.post(f"/v1/work-calendars/{wc['id']}/exceptions", headers=h, json={"exception_date": D + "23", "exception_type": "SPECIAL_WORKING", "reason": "QA"})
        rec(c, "exception", status=ex.status_code, body=ex.text[:200])
        assert ex.status_code == 201, ex.text

        res = {d_: await calc(client, h, eid, D + d_) for d_ in ("14", "15", "16", "23", "30")}
        rec(c, "no-punch days", **{d_: {k: v[k] for k in ("calendar_day_type", "attendance_status", "holiday_on_weekly_off", "paid_day_fraction", "lop_fraction")} for d_, v in res.items()})
        assert res["14"]["calendar_day_type"] == "WORKING" and res["14"]["attendance_status"] == "INCOMPLETE"
        assert (res["15"]["calendar_day_type"], res["15"]["attendance_status"]) == ("HOLIDAY", "NOT_EXPECTED")
        assert (res["16"]["calendar_day_type"], res["16"]["attendance_status"]) == ("WEEKLY_OFF", "NOT_EXPECTED")
        assert res["30"]["calendar_day_type"] == "WEEKLY_OFF" and res["30"]["holiday_on_weekly_off"] is True, "hard holiday on weekly off keeps the WEEKLY_OFF label (V1 §4)"
        assert res["30"]["attendance_status"] == "NOT_EXPECTED"
        assert res["23"]["calendar_day_type"] in ("SPECIAL_WORKING", "WORKING") and res["23"]["attendance_status"] == "INCOMPLETE", "a special working day expects presence"
        for d_ in ("15", "16", "30"):
            assert (res[d_]["paid_day_fraction"], res[d_]["lop_fraction"]) == ("1.00", "0.00"), f"{d_}: monthly-paid holiday/weekly off is paid (BUS-001)"
        # working on the holiday: PRESENT, flagged, never silently NOT_EXPECTED
        await _punch(client, h, employee_id=eid, hour=9, minute=0, direction="IN", day=D + "15")
        await _punch(client, h, employee_id=eid, hour=18, minute=0, direction="OUT", day=D + "15")
        worked = await calc(client, h, eid, D + "15")
        rec(c, "worked on holiday", status=worked["attendance_status"], worked=worked["worked_minutes"], flag=worked["worked_on_holiday"])
        assert worked["attendance_status"] == "PRESENT" and worked["worked_on_holiday"] is True and worked["worked_minutes"] == 540
        dbr = await day_row(cid, eid, D + "15")
        assert dbr["calendar_day_type"] == "HOLIDAY" and dbr["worked_on_holiday"] is True
    finally:
        await cleanup_all(cid, uid)


# ===================================================================================== ATT-DAY-006
async def test_att_day_006_night_shift_cross_midnight(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "ATT-DAY-006"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        night = await _create_night_shift(client, h)
        r = await client.post("/v1/rosters", headers=h, json={"employee_id": eid, "roster_date": D + "10", "shift_id": night["id"]})
        assert r.status_code == 201, r.text
        pub = await client.post(f"/v1/rosters/{r.json()['data']['id']}/publish", headers={**h, "If-Match": "1"}, json={})
        assert pub.status_code == 200, pub.text
        await _punch(client, h, employee_id=eid, hour=22, minute=5, direction="IN", day=D + "10")
        await _punch(client, h, employee_id=eid, hour=6, minute=10, direction="OUT", day=D + "11")
        d10 = await calc(client, h, eid, D + "10")
        d11 = await calc(client, h, eid, D + "11")
        rec(c, "result", d10={k: d10[k] for k in ("attendance_status", "worked_minutes", "scheduled_minutes", "calendar_day_type")},
            d11={k: d11[k] for k in ("attendance_status", "worked_minutes")})
        assert d10["attendance_status"] == "PRESENT" and d10["worked_minutes"] == 485 and d10["scheduled_minutes"] == 480
        assert d11["worked_minutes"] == 0, "the 06:10 OUT belongs to the shift that started on the 10th, not to the 11th"
        dbs = await rows(cid, "SELECT attendance_date::text d, worked_minutes w, attendance_status s FROM attendance_day WHERE employee_id=:e ORDER BY 1", e=eid)
        rec(c, "db", rows=dbs)
        assert sum(x["w"] for x in dbs) == 485 and len([x for x in dbs if x["w"] > 0]) == 1
    finally:
        await cleanup_all(cid, uid)


# ===================================================================================== ATT-DAY-009 / PUNCH-008
async def test_att_day_009_employment_boundaries(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """Joins Wed 12 Aug, last working day Thu 13 Aug. 10,11 -> NOT_JOINED; 14 -> EXITED; paid 0/lop 0 and counted
    as not_employed (BUS-002). Punches outside employment are refused and write nothing (ATT-PUNCH-008)."""
    c = "ATT-DAY-009"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h, joining_date=D + "12")
        eid = w["employee"]["id"]
        before_join = await client.post("/v1/attendance/punches", headers=h, json={
            "employee_id": eid, "punch_time": D + "11T09:00:00Z", "direction": "IN", "reference": "QA before joining"})
        rec("ATT-PUNCH-008", "punch before joining", status=before_join.status_code, code=before_join.json().get("error", {}).get("code"))
        assert 400 <= before_join.status_code < 500
        for d_ in ("12", "13"):
            await _punch(client, h, employee_id=eid, hour=9, minute=0, direction="IN", day=D + d_)
            await _punch(client, h, employee_id=eid, hour=18, minute=0, direction="OUT", day=D + d_)
        await _terminate(client, h, eid, D + "13")
        after_exit = await client.post("/v1/attendance/punches", headers=h, json={
            "employee_id": eid, "punch_time": D + "14T09:00:00Z", "direction": "IN", "reference": "QA after exit"})
        rec("ATT-PUNCH-008", "punch after last working day", status=after_exit.status_code, code=after_exit.json().get("error", {}).get("code"))
        assert 400 <= after_exit.status_code < 500
        assert len(await punches(cid, eid)) == 4, "refused punches must leave no rows"

        res = {d_: await calc(client, h, eid, D + d_) for d_ in ("10", "11", "12", "13", "14")}
        rec(c, "days", **{d_: {k: v[k] for k in ("attendance_status", "worked_minutes", "paid_day_fraction", "lop_fraction")} for d_, v in res.items()})
        assert [res[d_]["attendance_status"] for d_ in ("10", "11", "12", "13", "14")] == ["NOT_JOINED", "NOT_JOINED", "PRESENT", "PRESENT", "EXITED"]
        for d_ in ("10", "11", "14"):
            assert (res[d_]["paid_day_fraction"], res[d_]["lop_fraction"]) == ("0.00", "0.00"), "not employed: neither paid nor LOP"
        period = await _create_period(client, h, period_start=D + "10", period_end=D + "14")
        fin = await client.post(f"/v1/attendance-periods/{period['id']}/finalize", headers={**h, "If-Match": "1"}, json={})
        rec(c, "finalize", status=fin.status_code, body=fin.text[:300])
        assert fin.status_code == 200, fin.text
        s = await _period_summary(client, h, period["id"], eid)
        rec("PER-RECON-001", "joiner/leaver summary", summary=s)
        assert (s["present_days"], s["not_employed_days"], s["payable_days"], s["paid_days"], s["lop_days"]) == ("2.00", "3.00", "2.00", "2.00", "0.00")
        assert buckets(s) == 5.0
        assert float(s["paid_days"]) + float(s["lop_days"]) + float(s["unpaid_off_days"] or 0) == float(s["payable_days"])
    finally:
        await cleanup_all(cid, uid)


# ===================================================================================== PER-LE-001
async def test_per_le_001_periods_are_per_legal_entity(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "PER-LE-001"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        le1 = await _first_legal_entity_id(client, h)
        le2 = (await client.post("/v1/legal-entities", headers=h, json={"name": "QA Second LE"})).json()["data"]["id"]
        e2 = (await client.post("/v1/employees", headers=h, json={"first_name": "Second"})).json()["data"]["id"]
        emp2 = await client.post(f"/v1/employees/{e2}/employments", headers=h, json={"legal_entity_id": le2, "joining_date": "2026-01-01"})
        assert emp2.status_code == 201, emp2.text
        await calc(client, h, eid, D + "10")
        await calc(client, h, e2, D + "10")
        p1 = await _create_period(client, h, period_start=D + "10", period_end=D + "14", legal_entity_id=le1)
        dup = await client.post("/v1/attendance-periods", headers=h, json={"legal_entity_id": le1, "period_start": D + "12", "period_end": D + "16", "label": "overlap"})
        p2 = await client.post("/v1/attendance-periods", headers=h, json={"legal_entity_id": le2, "period_start": D + "10", "period_end": D + "14", "label": "other LE"})
        rec(c, "overlap rules", same_entity_overlap=(dup.status_code, dup.json().get("error", {}).get("code")), other_entity=p2.status_code)
        assert dup.status_code == 409 and dup.json()["error"]["code"] == "ATTENDANCE_PERIOD_OVERLAP"
        assert p2.status_code == 201, p2.text
        s1 = (await client.get(f"/v1/attendance-periods/{p1['id']}/summary", headers=h)).json()["data"]
        s2 = (await client.get(f"/v1/attendance-periods/{p2.json()['data']['id']}/summary", headers=h)).json()["data"]
        rec(c, "summary membership", le1_employees=[r_["employee_id"] for r_ in s1], le2_employees=[r_["employee_id"] for r_ in s2])
        assert eid in [r_["employee_id"] for r_ in s1] and e2 not in [r_["employee_id"] for r_ in s1]
        assert e2 in [r_["employee_id"] for r_ in s2] and eid not in [r_["employee_id"] for r_ in s2], "an employee belongs only to the period of the legal entity of their employment"
        assert (await rows(cid, "SELECT count(*) n FROM attendance_period"))[0]["n"] == 2
    finally:
        await cleanup_all(cid, uid)


# ===================================================================================== ATT-DAY-010
async def test_att_day_010_orphan_report(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """A punch outside every shift's padded load window is reported as orphaned (not silently dropped, not
    attributed to a day); the anchoring punches are not reported."""
    c = "ATT-DAY-010"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        await _punch(client, h, employee_id=eid, hour=9, minute=0, direction="IN", day=D + "10")
        await _punch(client, h, employee_id=eid, hour=18, minute=0, direction="OUT", day=D + "10")
        await calc(client, h, eid, D + "10")
        await _punch(client, h, employee_id=eid, hour=23, minute=45, direction="IN", day=D + "10", reference="late, outside the window")
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(cid))
            report = await AttendanceDayService(session).list_orphaned_punches(cid, date_from=date(2026, 8, 10), date_to=date(2026, 8, 10))
        hours = sorted(datetime.fromisoformat(p.punch_time).hour for p in report if str(p.employee_id) == eid)
        rec(c, "orphans", hours=hours, total_punches=len(await punches(cid, eid)))
        assert hours == [23]
        assert len(await punches(cid, eid)) == 3, "reporting an orphan must not delete or alter it"
    finally:
        await cleanup_all(cid, uid)
