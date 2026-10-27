"""QA B1 - ATT-PUNCH-001..003 and ATT-DAY-001..004 (catalogue: docs/testing/QA_TEST_CASES.csv).

Mounted read-only into the hermetic runner at /qa/b1 and run with the repository's own fixtures:

  stack.sh pytest <RUN> /qa/b1/test_b1_attendance.py -p tests.conftest \
      -p tests.integration.modules.attendance.conftest --rootdir . -c pyproject.toml

It is deliberately NOT inside apps/api/tests (nothing here may run in CI or in a developer's
default run).  Every check records what it observed to $QA_ARTIFACTS/<case>.jsonl BEFORE asserting,
so a failure still leaves evidence.  A case is only green when the API response AND the database
state AND the business invariant agree - an HTTP 2xx alone never passes anything.

Expected values come from docs/business-rules/ATTENDANCE_V1_COMPLETE.md (§8 policy table, §10) and
the existing synthetic fixture (shift 09:00-18:00, no break rule, UTC, Mon-Fri working days in
Aug 2026: 2026-08-10 is a Monday).  Where the documents do not fix a value (inclusive/exclusive
boundary minutes) the test RECORDS the observation and does not assert a direction (CL-16).
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
from tests.integration.modules.attendance.test_employee_default_role_attendance import (
    _employee_user,
    _teardown,
    _tenant,
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


async def punch_rows(company_id: Any, employee_id: str) -> list[dict[str, Any]]:
    return await rows(
        company_id,
        "SELECT id::text, employee_id::text, company_id::text, direction, source, idempotency_key, punch_time "
        "FROM punch WHERE employee_id = :e ORDER BY punch_time, created_at",
        e=employee_id,
    )


async def calc(client: AsyncClient, headers: dict[str, str], employee_id: str, day: str) -> dict[str, Any]:
    r = await client.post("/v1/attendance/days/calculate", headers=headers, params={"employee_id": employee_id, "date": day})
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


# ------------------------------------------------------------------------------------ ATT-PUNCH-001
async def test_att_punch_001_self_punch(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """Self punch: bound to caller, server timestamp, client time refused, bad direction refused,
    no on-behalf for an employee.  DB: exactly the accepted punches exist, tenant-stamped."""
    c = "ATT-PUNCH-001"
    t = await _tenant(client)
    try:
        emp_id, eh = await _employee_user(client, t, "Ravi")
        before = datetime.now(UTC)
        ok = await client.post("/v1/attendance/punches/me", headers=eh, json={"direction": "IN"})
        after = datetime.now(UTC)
        rec(c, "self IN", status=ok.status_code, body=ok.json())
        assert ok.status_code == 201, ok.text
        data = ok.json()["data"]
        assert data["employee_id"] == emp_id
        punched_at = datetime.fromisoformat(data["punch_time"].replace("Z", "+00:00"))
        assert before - timedelta(seconds=30) <= punched_at <= after + timedelta(seconds=30)

        client_time = await client.post("/v1/attendance/punches/me", headers=eh,
                                        json={"direction": "OUT", "punch_time": "2020-01-01T09:00:00Z"})
        bad_dir = await client.post("/v1/attendance/punches/me", headers=eh, json={"direction": "SIDEWAYS"})
        behalf = await client.post("/v1/attendance/punches", headers=eh, json={
            "employee_id": emp_id, "punch_time": "2026-08-10T09:00:00Z", "direction": "IN", "reference": "x"})
        rec(c, "refusals", client_time=client_time.status_code, bad_direction=bad_dir.status_code, on_behalf=behalf.status_code)
        assert client_time.status_code == 422, client_time.text
        assert bad_dir.status_code == 422, bad_dir.text
        assert behalf.status_code == 403, behalf.text

        db = await punch_rows(t.company_id, emp_id)
        rec(c, "db", rows=db)
        assert len(db) == 1, "refused requests must leave no punch rows"
        assert db[0]["direction"] == "IN" and db[0]["employee_id"] == emp_id
        assert db[0]["company_id"] == str(t.company_id)
        assert db[0]["source"] != "ADMIN", "self route must not be recorded as an admin override"
    finally:
        await _teardown(t)


# ------------------------------------------------------------------------------------ ATT-PUNCH-002
async def test_att_punch_002_idempotency_sequential_and_parallel(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "ATT-PUNCH-002"
    t = await _tenant(client)
    try:
        emp_id, eh = await _employee_user(client, t, "Meera")
        first = await client.post("/v1/attendance/punches/me", headers=eh, json={"direction": "IN", "idempotency_key": "qa-k1"})
        again = await client.post("/v1/attendance/punches/me", headers=eh, json={"direction": "IN", "idempotency_key": "qa-k1"})
        rec(c, "replay", first=first.status_code, again=again.status_code, ids=[first.json()["data"]["id"], again.json()["data"]["id"]])
        assert first.status_code == 201 and again.status_code in (200, 201), (first.text, again.text)
        assert first.json()["data"]["id"] == again.json()["data"]["id"]
        assert len(await punch_rows(t.company_id, emp_id)) == 1

        rs = await asyncio.gather(*[
            client.post("/v1/attendance/punches/me", headers=eh, json={"direction": "OUT", "idempotency_key": "qa-par"})
            for _ in range(10)])
        ids = {r.json()["data"]["id"] for r in rs if r.status_code in (200, 201)}
        rec(c, "parallel", statuses=[r.status_code for r in rs], distinct_ids=len(ids))
        assert all(r.status_code in (200, 201) for r in rs), [r.text for r in rs if r.status_code >= 300]
        assert len(ids) == 1
        db = await punch_rows(t.company_id, emp_id)
        rec(c, "db", count=len(db), keys=[r["idempotency_key"] for r in db])
        assert [r["idempotency_key"] for r in db].count("qa-par") == 1
        assert [r["idempotency_key"] for r in db].count("qa-k1") == 1
        assert len(db) == 2
    finally:
        await _teardown(t)


# ------------------------------------------------------------------------------------ ATT-PUNCH-003
async def test_att_punch_003_duplicate_window(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """Policy duplicate window (default 60 s, V1 §8): two IN taps 5 s apart count as ONE for the
    calculation.  Raw punches are never deleted (immutability).  Intake behaviour (stored vs
    refused) is not specified by the documents -> recorded, not asserted (CL-16); the invariants
    asserted are: no 5xx, no deletion of an accepted raw row, and worked_minutes == 540."""
    c = "ATT-PUNCH-003"
    headers, company_id, user_id = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, headers)
        eid = w["employee"]["id"]
        day = "2026-08-11"
        await _punch(client, headers, employee_id=eid, hour=9, minute=0, direction="IN", day=day, idempotency_key="d1")
        dup = await client.post("/v1/attendance/punches", headers=headers, json={
            "employee_id": eid, "punch_time": f"{day}T09:00:05Z", "direction": "IN",
            "reference": "qa duplicate tap", "idempotency_key": "d2"})
        rec(c, "second IN +5s", status=dup.status_code, body=dup.text[:300])
        assert dup.status_code < 500
        await _punch(client, headers, employee_id=eid, hour=18, minute=0, direction="OUT", day=day, idempotency_key="d3")
        stored = await punch_rows(company_id, eid)
        d = await calc(client, headers, eid, day)
        rec(c, "result", stored=len(stored), day={k: d[k] for k in ("attendance_status", "worked_minutes", "missing_punch")})
        assert d["attendance_status"] == "PRESENT"
        assert d["worked_minutes"] == 540
        assert d["missing_punch"] is False
        assert len(stored) == (3 if dup.status_code == 201 else 2), "an accepted raw punch must never disappear"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------------------------------ ATT-DAY-001
async def test_att_day_001_normal_day(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """09:00-18:00 on a working day -> PRESENT, 540 worked, scheduled 540, not late/early, no break
    deduction, engine/version recorded; DB attendance_day row equals the API body; raw punches
    untouched by calculation; recalculation is idempotent."""
    c = "ATT-DAY-001"
    headers, company_id, user_id = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, headers)
        eid = w["employee"]["id"]; day = "2026-08-12"
        await _punch(client, headers, employee_id=eid, hour=9, minute=0, direction="IN", day=day)
        await _punch(client, headers, employee_id=eid, hour=18, minute=0, direction="OUT", day=day)
        d1 = await calc(client, headers, eid, day)
        d2 = await calc(client, headers, eid, day)
        rec(c, "api", first=d1, second=d2)
        for k, v in {"attendance_status": "PRESENT", "worked_minutes": 540, "scheduled_minutes": 540,
                     "late_minutes": 0, "early_departure_minutes": 0, "is_late": False, "is_early_out": False,
                     "missing_punch": False, "calendar_day_type": "WORKING", "unpaid_break_minutes": 0}.items():
            assert d1[k] == v, (k, d1[k], v)
        stable = ("attendance_status", "worked_minutes", "late_minutes", "early_departure_minutes", "paid_day_fraction", "lop_fraction")
        assert {k: d1[k] for k in stable} == {k: d2[k] for k in stable}, "recalculation changed a derived value"
        db = await rows(company_id, "SELECT attendance_status, worked_minutes, late_minutes, is_locked FROM attendance_day "
                        "WHERE employee_id = :e AND attendance_date = :d", e=eid, d=datetime.fromisoformat(day).date())
        rec(c, "db", rows=db)
        assert len(db) == 1 and db[0]["attendance_status"] == "PRESENT" and db[0]["worked_minutes"] == 540
        assert len(await punch_rows(company_id, eid)) == 2
        assert str(d1["paid_day_fraction"]) in ("1", "1.0", "1.00", "1.000")
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def _employee_policy(client: AsyncClient, headers: dict[str, str], employee_id: str, version: dict[str, Any]) -> None:
    pol = (await client.post("/v1/attendance-policies", headers=headers, json={"name": "QA employee policy"})).json()["data"]
    draft = await client.post(f"/v1/attendance-policies/{pol['id']}/versions", headers=headers, json={"effective_from": "2026-01-01", **version})
    assert draft.status_code == 201, draft.text
    pub = await client.post(f"/v1/attendance-policies/{pol['id']}/versions/{draft.json()['data']['id']}/publish",
                            headers={**headers, "If-Match": "1"}, json={})
    assert pub.status_code == 200, pub.text
    asg = await client.post("/v1/policy-assignments", headers=headers, json={
        "policy_kind": "ATTENDANCE_POLICY", "policy_id": pol["id"], "scope_type": "EMPLOYEE",
        "scope_id": employee_id, "effective_from": "2026-01-01"})
    assert asg.status_code == 201, asg.text


# ------------------------------------------------------------------------------------ ATT-DAY-002
async def test_att_day_002_grace_and_late_bands(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """V1 §8 example: grace_in 15, late bands (0-30 => LATE, 31+ => HALF_DAY).
    09:14 -> not late.  09:20 -> late by 5 (V1: 'counts 5 minutes late').  09:50 -> beyond the 30
    min band -> HALF_DAY classification/status.  The exact-boundary minute (09:15) is recorded only."""
    c = "ATT-DAY-002"
    headers, company_id, user_id = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, headers)
        eid = w["employee"]["id"]
        await _employee_policy(client, headers, eid, {
            "grace_in_minutes": 15,
            "hour_bands": [{"min_minutes": 0, "max_minutes": 239, "result_status": "ABSENT"},
                           {"min_minutes": 240, "max_minutes": 479, "result_status": "HALF_DAY"},
                           {"min_minutes": 480, "max_minutes": None, "result_status": "PRESENT"}],
            "late_bands": [{"min_minutes": 0, "max_minutes": 30, "classification": "LATE"},
                           {"min_minutes": 31, "max_minutes": None, "classification": "HALF_DAY"}]})
        plan = [("2026-08-13", 9, 14, 18, 0), ("2026-08-14", 9, 20, 18, 6), ("2026-08-17", 9, 15, 18, 0), ("2026-08-18", 9, 50, 18, 30)]
        out: dict[str, dict[str, Any]] = {}
        for day, h, m, oh, om in plan:
            await _punch(client, headers, employee_id=eid, hour=h, minute=m, direction="IN", day=day)
            await _punch(client, headers, employee_id=eid, hour=oh, minute=om, direction="OUT", day=day)
            out[day] = await calc(client, headers, eid, day)
            rec(c, day, in_=f"{h:02d}:{m:02d}", **{k: out[day][k] for k in ("attendance_status", "worked_minutes", "late_minutes", "is_late", "late_classification")})
        a, b, edge, big = out["2026-08-13"], out["2026-08-14"], out["2026-08-17"], out["2026-08-18"]
        assert a["is_late"] is False and a["late_minutes"] == 0
        assert b["is_late"] is True and b["late_minutes"] == 5, "V1 §8: 09:20 with grace 15 counts 5 minutes late"
        assert b["attendance_status"] == "PRESENT"
        assert big["is_late"] is True
        assert big["late_classification"] == "HALF_DAY" or big["attendance_status"] == "HALF_DAY"
        rec(c, "boundary 09:15 (recorded only, CL-16)", is_late=edge["is_late"], late_minutes=edge["late_minutes"])
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------------------------------ ATT-DAY-003
@pytest.mark.parametrize(("minutes", "expected"), [(239, "ABSENT"), (240, "HALF_DAY"), (479, "HALF_DAY"), (480, "PRESENT")])
async def test_att_day_003_hour_band_boundaries(client: AsyncClient, seeded_plan_catalogue: None, minutes: int, expected: str) -> None:
    """Hour bands 0-239 ABSENT / 240-479 HALF_DAY / 480+ PRESENT.  IN 09:00, OUT 09:00+minutes."""
    c = "ATT-DAY-003"
    headers, company_id, user_id = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, headers)
        eid = w["employee"]["id"]
        await _employee_policy(client, headers, eid, {
            "hour_bands": [{"min_minutes": 0, "max_minutes": 239, "result_status": "ABSENT"},
                           {"min_minutes": 240, "max_minutes": 479, "result_status": "HALF_DAY"},
                           {"min_minutes": 480, "max_minutes": None, "result_status": "PRESENT"}]})
        day = "2026-08-19"
        out = datetime(2026, 8, 19, 9, 0, tzinfo=UTC) + timedelta(minutes=minutes)
        await _punch(client, headers, employee_id=eid, hour=9, minute=0, direction="IN", day=day)
        await _punch(client, headers, employee_id=eid, hour=out.hour, minute=out.minute, direction="OUT", day=day)
        d = await calc(client, headers, eid, day)
        rec(c, f"{minutes} min", expected=expected, status=d["attendance_status"], worked=d["worked_minutes"],
            early=d["early_departure_minutes"], paid=d["paid_day_fraction"], lop=d["lop_fraction"])
        assert d["worked_minutes"] == minutes
        assert d["attendance_status"] == expected
        # payroll-facing consistency: paid + lop fractions describe the same status
        paid, lop = float(d["paid_day_fraction"]), float(d["lop_fraction"])
        assert {"ABSENT": (0.0, 1.0), "HALF_DAY": (0.5, 0.5), "PRESENT": (1.0, 0.0)}[expected] == (paid, lop)
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------------------------------ ATT-DAY-004
async def test_att_day_004_missing_punch(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """Only an IN on a working day -> INCOMPLETE (policy default), missing_punch True, never silently
    PRESENT; only an OUT likewise; no punches on a working day -> not PRESENT either."""
    c = "ATT-DAY-004"
    headers, company_id, user_id = await _register_tenant(client)
    try:
        w = await _build_wired_employee(client, headers)
        eid = w["employee"]["id"]
        await _punch(client, headers, employee_id=eid, hour=9, minute=0, direction="IN", day="2026-08-20")
        d = await calc(client, headers, eid, "2026-08-20")
        rec(c, "only IN", status=d["attendance_status"], missing=d["missing_punch"], worked=d["worked_minutes"], paid=d["paid_day_fraction"])
        assert d["attendance_status"] == "INCOMPLETE" and d["missing_punch"] is True
        assert d["attendance_status"] != "PRESENT"
        await _punch(client, headers, employee_id=eid, hour=18, minute=0, direction="OUT", day="2026-08-21")
        o = await calc(client, headers, eid, "2026-08-21")
        rec(c, "only OUT", status=o["attendance_status"], missing=o["missing_punch"])
        assert o["attendance_status"] == "INCOMPLETE" and o["missing_punch"] is True
        n = await calc(client, headers, eid, "2026-08-24")
        rec(c, "no punches (Mon)", status=n["attendance_status"], paid=n["paid_day_fraction"], lop=n["lop_fraction"])
        assert n["attendance_status"] in ("ABSENT", "INCOMPLETE"), "a working day without punches must not be PRESENT"
        assert n["attendance_status"] != "PRESENT"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
