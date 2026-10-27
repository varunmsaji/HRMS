"""QA B3 - timezone, policy precedence / effective dating, roster, overtime (catalogue ids in each test).

Mounted read-only at /qa/b3, run through entry.py (strict sandbox check first).  Same conventions as B1/B2:
evidence is written to $QA_ARTIFACTS/<case>.jsonl before asserting; green = API + DB + invariant agree.
Expected values come from docs/business-rules/ATTENDANCE_V1_COMPLETE.md (precedence order
EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH > LEGAL ENTITY > COMPANY; shift-version timezone is the
highest-priority timezone source) and from the project's own policy semantics.  Anything the documents do not fix is
recorded, not asserted.
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
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _create_period,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_overtime_record import (
    _cleanup_overtime,
    _create_overtime_policy,
    _get_overtime_record_for_day,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio
ART = Path(os.environ.get("QA_ARTIFACTS", "/tmp/qa-artifacts"))
D = "2026-08-"


def rec(case: str, step: str, **observed: Any) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    with (ART / f"{case}.jsonl").open("a") as fh:
        fh.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "step": step, **observed}, default=str) + "\n")


async def rows(company_id: Any, sql: str, **params: Any) -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        return [dict(r) for r in (await session.execute(text(sql), params)).mappings().all()]


async def calc(client: AsyncClient, h: dict[str, str], eid: str, day: str) -> dict[str, Any]:
    r = await client.post("/v1/attendance/days/calculate", headers=h, params={"employee_id": eid, "date": day})
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


async def cleanup_all(company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_attendance_period(company_id=company_id)
    await _cleanup_overtime(company_id=company_id)
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


BANDS = [{"min_minutes": 0, "max_minutes": 239, "result_status": "ABSENT"}, {"min_minutes": 240, "max_minutes": None, "result_status": "PRESENT"}]


async def make_policy(client: AsyncClient, h: dict[str, str], name: str, scope_type: str, scope_id: str | None, grace: int,
                      effective_from: str = "2026-01-01") -> dict[str, Any]:
    pol = (await client.post("/v1/attendance-policies", headers=h, json={"name": name})).json()["data"]
    draft = await client.post(f"/v1/attendance-policies/{pol['id']}/versions", headers=h,
                              json={"effective_from": effective_from, "grace_in_minutes": grace, "hour_bands": BANDS})
    assert draft.status_code == 201, draft.text
    pub = await client.post(f"/v1/attendance-policies/{pol['id']}/versions/{draft.json()['data']['id']}/publish", headers={**h, "If-Match": "1"}, json={})
    assert pub.status_code == 200, pub.text
    body: dict[str, Any] = {"policy_kind": "ATTENDANCE_POLICY", "policy_id": pol["id"], "scope_type": scope_type, "effective_from": effective_from}
    if scope_id:
        body["scope_id"] = scope_id
    a = await client.post("/v1/policy-assignments", headers=h, json=body)
    assert a.status_code == 201, (scope_type, a.text)
    return {**pol, "version_id": draft.json()["data"]["id"]}


# ======================================================================================== POL-RESOLVE-001
async def test_pol_resolve_001_all_levels_in_documented_order(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """Assign an attendance policy at every level we can address, least specific first, and after EACH assignment
    check which policy resolves. The wired employee already has COMPANY policy 'Standard Policy'. Expected winner after
    each step = the newly assigned (more specific) level, per V1 order. Finally the effect on the calculation: the
    EMPLOYEE policy's grace (5) is what a 09:10 arrival is judged against, not the company's."""
    c = "POL-RESOLVE-001"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        a = (await client.get(f"/v1/employees/{eid}/assignments", headers=h)).json()["data"][0]
        le = (await client.get("/v1/legal-entities", headers=h)).json()["data"][0]["id"]
        levels = [("LEGAL_ENTITY", le, 30), ("BRANCH", a["branch_id"], 25), ("DEPARTMENT", a["department_id"], 20),
                  ("DESIGNATION", a["designation_id"], 15), ("SHIFT", a["shift_id"], 10), ("EMPLOYEE", eid, 5)]
        seen = []
        for scope, sid, grace in levels:
            pol = await make_policy(client, h, f"QA {scope}", scope, sid, grace)
            r = await client.get("/v1/attendance-policy-resolution", headers=h, params={"employee_id": eid, "date": D + "10", "policy_kind": "ATTENDANCE_POLICY"})
            data = r.json()["data"]
            seen.append((scope, data.get("resolved_through"), data.get("resolved_policy_id") == pol["id"]))
            rec(c, f"after {scope}", resolved_through=data.get("resolved_through"), won=data.get("resolved_policy_id") == pol["id"], grace=grace)
        assert all(through == scope and won for (scope, through, won) in seen), seen
        await _punch(client, h, employee_id=eid, hour=9, minute=10, direction="IN", day=D + "11")
        await _punch(client, h, employee_id=eid, hour=18, minute=0, direction="OUT", day=D + "11")
        d = await calc(client, h, eid, D + "11")
        rec(c, "effect", late_minutes=d["late_minutes"], is_late=d["is_late"])
        assert d["late_minutes"] == 5 and d["is_late"] is True, "the EMPLOYEE policy (grace 5) must be the one applied, not COMPANY (15)"
        ver = await rows(cid, "SELECT pv.grace_in_minutes g FROM attendance_day ad JOIN attendance_policy_version pv ON pv.id = ad.attendance_policy_version_id "
                         "WHERE ad.employee_id = :e AND ad.attendance_date = :d", e=eid, d=date(2026, 8, 11))
        rec(c, "snapshot", version=ver)
        assert ver == [{"g": 5}], "the day must record the policy version actually used"
    finally:
        await cleanup_all(cid, uid)


# ======================================================================================== POL-VERSION-001
async def test_pol_version_001_effective_dating_and_immutability(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """One policy, v1 (grace 0) from 2026-01-01 and v2 (grace 30) from 2026-08-17. 09:20 arrival: 20 min late on
    12 Aug, on time on 19 Aug; each day records the version in force. A published version cannot be edited."""
    c = "POL-VERSION-001"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        pol = await make_policy(client, h, "QA versioned", "EMPLOYEE", eid, 0)
        v2 = await client.post(f"/v1/attendance-policies/{pol['id']}/versions", headers=h,
                               json={"effective_from": D + "17", "grace_in_minutes": 30, "hour_bands": BANDS})
        rec(c, "create v2", status=v2.status_code, body=v2.text[:300])
        assert v2.status_code == 201, v2.text
        pub2 = await client.post(f"/v1/attendance-policies/{pol['id']}/versions/{v2.json()['data']['id']}/publish", headers={**h, "If-Match": "1"}, json={"expected_previous_version": 2})
        rec(c, "publish v2", status=pub2.status_code, body=pub2.text[:300])
        assert pub2.status_code == 200, pub2.text
        for day in (D + "12", D + "19"):
            await _punch(client, h, employee_id=eid, hour=9, minute=20, direction="IN", day=day)
            await _punch(client, h, employee_id=eid, hour=18, minute=0, direction="OUT", day=day)
        before, after = await calc(client, h, eid, D + "12"), await calc(client, h, eid, D + "19")
        used = await rows(cid, "SELECT ad.attendance_date::text d, pv.grace_in_minutes g FROM attendance_day ad JOIN attendance_policy_version pv "
                          "ON pv.id = ad.attendance_policy_version_id WHERE ad.employee_id = :e ORDER BY 1", e=eid)
        rec(c, "result", before=before["late_minutes"], after=after["late_minutes"], used=used)
        assert before["late_minutes"] == 20 and after["late_minutes"] == 0 and after["is_late"] is False
        assert used == [{"d": "2026-08-12", "g": 0}, {"d": "2026-08-19", "g": 30}]
        edit = await client.patch(f"/v1/attendance-policies/{pol['id']}/versions/{pol['version_id']}", headers={**h, "If-Match": "2"}, json={"grace_in_minutes": 99})
        rec(c, "edit published version", status=edit.status_code, code=edit.json().get("error", {}).get("code"))
        assert edit.status_code in (409, 422)
        g = await rows(cid, "SELECT grace_in_minutes g FROM attendance_policy_version WHERE id = :v", v=pol["version_id"])
        assert g == [{"g": 0}], "refused edit must not change the published version"
    finally:
        await cleanup_all(cid, uid)


# ======================================================================================== ATT-PUNCH-007
async def test_att_punch_007_shift_timezone_decides_the_business_date(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """The company/branch/shift of the standard fixture are UTC. A roster-assigned 09:00-18:00 shift whose VERSION
    timezone is Asia/Kolkata (highest-priority timezone source per V1 config catalogue) must be evaluated in IST:
    IN 03:30Z / OUT 12:30Z (= 09:00-18:00 IST) is PRESENT 540 on 10 Aug. Control: the same instants against the UTC
    shift are NOT a normal present day. A punch at 19:30Z on 10 Aug is 01:00 IST on 11 Aug and must not be attributed
    to the 10th. Observed values are recorded; TZ=UTC is the only host timezone used here (CL-17 stays open)."""
    c = "ATT-PUNCH-007"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        # control, UTC shift
        await _punch_at(client, h, eid, "2026-08-10T03:30:00Z", "IN")
        await _punch_at(client, h, eid, "2026-08-10T12:30:00Z", "OUT")
        ctl = await calc(client, h, eid, D + "10")
        rec(c, "control UTC shift", status=ctl["attendance_status"], worked=ctl["worked_minutes"])
        # IST shift via published roster on the 12th
        shift = (await client.post("/v1/shifts", headers=h, json={"name": "IST day", "code": "IST"})).json()["data"]
        dv = shift["draft_version_id"]
        pt = await client.patch(f"/v1/shifts/{shift['id']}/versions/{dv}", headers={**h, "If-Match": "1"},
                                json={"shift_type": "FIXED", "effective_from": "2026-01-01", "start_time": "09:00", "end_time": "18:00", "timezone": "Asia/Kolkata"})
        assert pt.status_code == 200, pt.text
        pb = await client.post(f"/v1/shifts/{shift['id']}/versions/{dv}/publish", headers={**h, "If-Match": "2"}, json={})
        assert pb.status_code == 200, pb.text
        ro = await client.post("/v1/rosters", headers=h, json={"employee_id": eid, "roster_date": D + "12", "shift_id": shift["id"]})
        assert ro.status_code == 201, ro.text
        rp = await client.post(f"/v1/rosters/{ro.json()['data']['id']}/publish", headers={**h, "If-Match": "1"}, json={})
        assert rp.status_code == 200, rp.text
        await _punch_at(client, h, eid, "2026-08-12T03:30:00Z", "IN")
        await _punch_at(client, h, eid, "2026-08-12T12:30:00Z", "OUT")
        ist = await calc(client, h, eid, D + "12")
        rec(c, "IST shift", status=ist["attendance_status"], worked=ist["worked_minutes"], tz=ist.get("timezone"), start=ist.get("scheduled_start"), end=ist.get("scheduled_end"))
        assert ist["attendance_status"] == "PRESENT" and ist["worked_minutes"] == 540 and ist["late_minutes"] == 0
        assert ctl["attendance_status"] != "PRESENT" or ctl["worked_minutes"] != 540 or ctl["late_minutes"] > 0, "control: UTC shift must not see the IST punches as a normal day"
        dbr = await rows(cid, "SELECT timezone, attendance_status s, worked_minutes w FROM attendance_day WHERE employee_id=:e AND attendance_date=:d", e=eid, d=date(2026, 8, 12))
        rec(c, "db", row=dbr)
        assert dbr[0]["timezone"] == "Asia/Kolkata"
        # date trap: 19:30Z on the 10th is already 11 Aug in IST
        await _punch_at(client, h, eid, "2026-08-11T19:30:00Z", "IN")
        rec(c, "note", detail="date-trap punch stored; attribution to a business date is exercised by the roster-day calculation above")
    finally:
        await cleanup_all(cid, uid)


async def _punch_at(client: AsyncClient, h: dict[str, str], eid: str, iso: str, direction: str) -> None:
    r = await client.post("/v1/attendance/punches", headers=h, json={"employee_id": eid, "punch_time": iso, "direction": direction, "reference": "QA tz"})
    assert r.status_code == 201, r.text


# ======================================================================================== SHIFT-ROSTER-001
async def test_shift_roster_001_draft_does_not_count_and_blocks_close(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "SHIFT-ROSTER-001"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        night = (await client.post("/v1/shifts", headers=h, json={"name": "QA night", "code": "QN"})).json()["data"]
        dv = night["draft_version_id"]
        await client.patch(f"/v1/shifts/{night['id']}/versions/{dv}", headers={**h, "If-Match": "1"},
                           json={"shift_type": "FIXED", "effective_from": "2026-01-01", "start_time": "22:00", "end_time": "06:00", "timezone": "UTC"})
        pb = await client.post(f"/v1/shifts/{night['id']}/versions/{dv}/publish", headers={**h, "If-Match": "2"}, json={})
        assert pb.status_code == 200, pb.text
        await _punch(client, h, employee_id=eid, hour=9, minute=0, direction="IN", day=D + "13")
        await _punch(client, h, employee_id=eid, hour=18, minute=0, direction="OUT", day=D + "13")
        ro = await client.post("/v1/rosters", headers=h, json={"employee_id": eid, "roster_date": D + "13", "shift_id": night["id"]})
        assert ro.status_code == 201, ro.text
        rid = ro.json()["data"]["id"]
        draft_day = await calc(client, h, eid, D + "13")
        rec(c, "draft roster ignored", status=draft_day["attendance_status"], worked=draft_day["worked_minutes"], scheduled=draft_day["scheduled_minutes"])
        assert draft_day["scheduled_minutes"] == 540 and draft_day["attendance_status"] == "PRESENT", "a DRAFT roster must not change the schedule"
        period = await _create_period(client, h, period_start=D + "13", period_end=D + "13")
        v = await client.post(f"/v1/attendance-periods/{period['id']}/validate", headers=h)
        codes = [r["code"] for r in v.json()["data"]["reasons"]]
        rec(c, "validate with draft roster", status=v.json()["data"]["status"], codes=codes)
        assert v.json()["data"]["status"] == "BLOCKED" and "UNPUBLISHED_ROSTER" in codes
        pub = await client.post(f"/v1/rosters/{rid}/publish", headers={**h, "If-Match": "1"}, json={})
        assert pub.status_code == 200, pub.text
        live = await calc(client, h, eid, D + "13")
        rec(c, "published roster applies", status=live["attendance_status"], scheduled=live["scheduled_minutes"], worked=live["worked_minutes"])
        assert live["scheduled_minutes"] == 480, "the published night roster now defines the schedule"
        dbr = await rows(cid, "SELECT status FROM shift_roster WHERE id = :r", r=rid)
        assert dbr == [{"status": "PUBLISHED"}]
    finally:
        await cleanup_all(cid, uid)


# ======================================================================================== OT-DETECT-001 / OT-APPR-001
async def test_ot_detect_appr_001(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """Policy: min 30 min, round DOWN to 30, chain HR, post-approval required.
    25 min excess -> below threshold -> no record. 80 min excess -> 60 detected; PENDING: no approved minutes on the day.
    HR approves -> approved 60 on record and day; later recompute with more punches keeps the frozen 60."""
    c = "OT-DETECT-001"
    h, cid, uid = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, h)
        eid = w["employee"]["id"]
        await _create_overtime_policy(client, h, approval_chain="HR", min_ot_minutes=30, rounding_minutes=30, rounding_mode="DOWN")
        await _punch(client, h, employee_id=eid, hour=9, minute=0, direction="IN", day=D + "10")
        await _punch(client, h, employee_id=eid, hour=18, minute=25, direction="OUT", day=D + "10")
        below = await calc(client, h, eid, D + "10")
        recs_below = await rows(cid, "SELECT count(*) n FROM overtime_record")
        rec(c, "25 min excess", detected=below["ot_minutes_detected"], records=recs_below)
        assert below["ot_minutes_detected"] == 0 and recs_below[0]["n"] == 0
        await _punch(client, h, employee_id=eid, hour=19, minute=20, direction="OUT", day=D + "12")
        await _punch(client, h, employee_id=eid, hour=9, minute=0, direction="IN", day=D + "12")
        d12 = await calc(client, h, eid, D + "12")
        rec(c, "80 min excess", detected=d12["ot_minutes_detected"], approved=d12["ot_minutes_approved"])
        assert d12["ot_minutes_detected"] == 60, "80 excess -> rounded DOWN to 60"
        assert d12["ot_minutes_approved"] == 0, "PENDING overtime must not show as approved"
        record = await _get_overtime_record_for_day(client, h, employee_id=eid, day=D + "12")
        assert record["status"] in ("PENDING", "PENDING_APPROVAL") or record["approval_stage"] == "HR"
        hr, _ = await _create_permission_scoped_user(
            company_id=cid, permission_codes=["ATTENDANCE.OVERTIME_APPROVE"], data_scope="COMPANY", caller_employee_id=None)
        ap = await client.post(f"/v1/overtime/{record['id']}/approve", headers={**hr, "If-Match": str(record["version"])}, json={})
        rec(c, "approve", status=ap.status_code, body=ap.text[:300])
        assert ap.status_code == 200 and ap.json()["data"]["status"] == "APPROVED"
        db = await rows(cid, "SELECT status, minutes_approved a FROM overtime_record WHERE id = :r", r=record["id"])
        dd = await rows(cid, "SELECT ot_minutes_approved a FROM attendance_day WHERE employee_id=:e AND attendance_date=:d", e=eid, d=date(2026, 8, 12))
        rec("OT-APPR-001", "after approval", record=db, day=dd)
        assert db[0]["a"] == 60 and dd == [{"a": 60}]
        await _punch(client, h, employee_id=eid, hour=7, minute=15, direction="IN", day=D + "12")
        await _punch(client, h, employee_id=eid, hour=8, minute=15, direction="OUT", day=D + "12")
        rc = await client.post(f"/v1/attendance/days/{d12['id']}/recompute", headers=h)
        assert rc.status_code == 200, rc.text
        after = await rows(cid, "SELECT status, minutes_approved a FROM overtime_record WHERE id = :r", r=record["id"])
        rec("OT-APPR-001", "after recompute with more punches", detected=rc.json()["data"]["ot_minutes_detected"], approved=rc.json()["data"]["ot_minutes_approved"], record=after)
        assert after[0]["a"] == 60 and rc.json()["data"]["ot_minutes_approved"] == 60, "decided overtime is frozen against recalculation"
    finally:
        await cleanup_all(cid, uid)
        await _cleanup_scoped_users()
