"""QA B5a - payroll run lifecycle, guards, concurrency, immutability and tenant isolation.

Catalogue ids: PAYROLL-FLOW-001..008, PAYROLL-AUTHZ-001, PAYROLL-SLIP-001, PAYROLL-ADJ-001, PAYROLL-BANK-001, PAYROLL-PIN-001.
NOT in scope (B5b): every PAYROLL-CALC-*, -STAT-*, -TDS-*, -NET-*, PAYROLL-ARR-001.  CL-04 is decided (no rounding during calculation);
nothing here asserts an expected salary amount.  Lifecycle fixtures are deterministic synthetic ones; the only numeric checks are
aggregation identities (run total == sum of its employee rows) and snapshot == attendance summary equality.

Mounted read-only at /qa/b5, run through entry.py.  Evidence: $QA_ARTIFACTS/<case>.jsonl, written BEFORE asserting.
Oracle: PayRunService (state sets), permissions.py docstring (RUN_PROCESS prepares, RUN_APPROVE approves/finalises/pays; D9 maker != checker),
00_PAYROLL_IMPLEMENTATION_PLAN.md (decisions 15, PD-2, D9, D10), ADR 0005.  Where the code and the documents are silent, behaviour is RECORDED.
Role switching: `switch_role(app)` repoints the application engine at the real runtime role hrms_app (RLS applies); verification
queries are always explicitly company-scoped because the owner role bypasses RLS.
"""

import asyncio
import csv
import io
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.account_invite.test_account_invite import _token_from_invite_url
from tests.integration.modules.attendance.test_attendance_day import _register_tenant
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_employee_default_role_attendance import _employee_user
from tests.integration.modules.attendance.test_employee_default_role_attendance import _tenant as _att_tenant
from tests.integration.modules.attendance.test_employee_default_role_attendance import _teardown as _att_teardown
from tests.integration.modules.organisation.test_registration_flow import VALID_PASSWORD, _cleanup
from tests.integration.modules.payroll.test_pay_run import (
    _approver,
    _cleanup_pay_runs,
    _closed_period,
    _create_run,
    _employee,
    _legal_entity,
)

from tests.integration.tenant_wipe import wipe_tenant

from hrms.core.config.settings import get_settings
from hrms.core.db.session import dispose_engine, get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio
ART = Path(os.environ.get("QA_ARTIFACTS", "/tmp/qa-artifacts"))
OWNER_URL, APP_URL = os.environ["DATABASE_URL"], os.environ["HRMS_APP_DATABASE_URL"]
MONTHS = {"2026-08": ("2026-08-01", "2026-08-31", 31), "2026-09": ("2026-09-01", "2026-09-30", 30), "2026-10": ("2026-10-01", "2026-10-31", 31)}
BASE = "/v1/payroll/pay-runs"


def rec(case: str, step: str, **observed: Any) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    with (ART / f"{case}.jsonl").open("a") as fh:
        fh.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "step": step, **observed}, default=str) + "\n")


async def q(sql: str, **params: Any) -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        if params.get("c"):                                  # under hrms_app RLS needs the company scope set on the connection
            await set_rls_company_id(session, str(params["c"]))
        return [dict(r) for r in (await session.execute(text(sql), params)).mappings().all()]


async def switch_role(monkeypatch: pytest.MonkeyPatch, which: str) -> None:
    monkeypatch.setenv("DATABASE_URL", APP_URL if which == "app" else OWNER_URL)
    get_settings.cache_clear()
    await dispose_engine()


async def state(cid: Any, rid: str) -> dict[str, Any]:
    """Everything that must NOT move when an operation is refused."""
    r = (await q("SELECT status, version, updated_at::text u, pay_date::text pd, computed_by_user_id::text cb, approved_by_user_id::text ab, employee_count, error_count, "
                 "gross_minor, net_minor, last_rollback_reason FROM pay_run WHERE id = :i AND company_id = :c", i=rid, c=str(cid)))
    if not r:
        return {"exists": False}
    s = dict(r[0])
    s["employees"] = (await q("SELECT count(*) n FROM pay_run_employee WHERE pay_run_id = :i AND company_id = :c", i=rid, c=str(cid)))[0]["n"]
    s["lines"] = (await q("SELECT count(*) n FROM pay_run_line WHERE pay_run_id = :i AND company_id = :c", i=rid, c=str(cid)))[0]["n"]
    s["audit"] = (await q("SELECT count(*) n FROM audit_log WHERE entity_id = :i AND company_id = :c", i=rid, c=str(cid)))[0]["n"]
    return s


async def audit_actions(cid: Any, rid: str) -> list[dict[str, Any]]:
    return await q("SELECT action, actor_user_id::text actor, before_json->>'status' b, after_json->>'status' a, request_id FROM audit_log WHERE entity_id = :i AND company_id = :c ORDER BY occurred_at, id", i=rid, c=str(cid))


def hdr(h: dict[str, str], version: Any = None) -> dict[str, str]:
    return {**h, "If-Match": str(version)} if version is not None else h


async def act(client: AsyncClient, h: dict[str, str], rid: str, action: str, version: Any, body: dict | None = None) -> Any:
    return await client.post(f"{BASE}/{rid}/{action}", headers=hdr(h, version), json=body)


async def get_run(client: AsyncClient, h: dict[str, str], rid: str) -> dict[str, Any]:
    r = await client.get(f"{BASE}/{rid}", headers=h)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


async def payroll_profile(client: AsyncClient, h: dict[str, str], eid: str, ctc: int = 7_20_000_00) -> None:
    """Compensation, statutory profile, bank and salary assignment for an employee that already exists (same calls as test_pay_run._employee)."""
    steps = [
        (f"/v1/employees/{eid}/compensation", {"effective_from": "2026-01-01", "annual_ctc_minor": ctc, "currency": "INR", "revision_type": "JOINING", "revision_reason": "Initial hire"}),
        (f"/v1/employees/{eid}/statutory", {"effective_from": "2026-01-01", "is_pf_applicable": False, "is_esi_applicable": False, "is_lwf_applicable": False, "tax_regime": "NEW", "revision_reason": "Initial"}),
        (f"/v1/employees/{eid}/bank", {"effective_from": "2026-01-01", "account_holder_name": "Synthetic Holder", "account_number_enc": "123456789012", "bank_name": "State Bank", "ifsc": "SBIN0001234", "payment_mode": "BANK"}),
    ]
    for url, body in steps:
        r = await client.post(url, headers=h, json=body)
        assert r.status_code == 201, (url, r.text)
    structures = await client.get("/v1/payroll/salary-structures", headers=h)
    standard = next(s for s in structures.json()["data"] if s["code"] == "STANDARD")
    r = await client.post(f"/v1/employees/{eid}/salary", headers=h, json={"salary_structure_id": standard["id"], "effective_from": "2026-01-01", "reason": "Joining"})
    assert r.status_code == 201, r.text


async def drop_invites(cid: Any) -> None:
    async with get_session_factory()() as session:
        for table in ("account_invite", "refresh_token", "session"):
            await session.execute(text(f'DELETE FROM "{table}" WHERE company_id = :c'), {"c": str(cid)})
        await session.commit()


async def finalised(client: AsyncClient, h: dict[str, str], approver: dict[str, str], cid: Any, le: str, month: str, paid: dict[str, str]) -> dict[str, Any]:
    start, end, days = MONTHS[month]
    await _closed_period(company_id=cid, legal_entity_id=le, start=start, end=end, paid_days=paid, days_in_month=days)
    run = await _create_run(client, h, le, month)
    r = await act(client, h, run["id"], "lock-inputs", run["version"]); run = r.json()["data"]
    r = await act(client, h, run["id"], "compute", run["version"]); run = r.json()["data"]
    for e in (await client.get(f"{BASE}/{run['id']}/employees", headers=h)).json()["data"]:
        if e["variance_flagged"]:
            await client.post(f"{BASE}/{run['id']}/employees/{e['employee_id']}/acknowledge-variance", headers=h, json={"reason": "synthetic"})
    run = await get_run(client, h, run["id"])
    r = await act(client, approver, run["id"], "approve", run["version"]); assert r.status_code == 200, r.text; run = r.json()["data"]
    r = await act(client, approver, run["id"], "finalise", run["version"]); assert r.status_code == 200, r.text
    return dict(r.json()["data"])


# =================================================================================== PAYROLL-FLOW-001 state machine
ALL_ACTIONS = ["lock-inputs", "compute", "approve", "finalise", "mark-paid", "rollback:DRAFT", "rollback:INPUTS_LOCKED", "patch", "delete"]
ALLOWED = {  # taken from PayRunService (not invented): _require_status / from_statuses / _ROLLBACK_FROM
    "DRAFT": {"lock-inputs", "patch", "delete"},
    "INPUTS_LOCKED": {"compute", "rollback:DRAFT", "patch"},
    "COMPUTED": {"compute", "approve", "rollback:DRAFT", "rollback:INPUTS_LOCKED", "patch"},
    "APPROVED": {"finalise", "rollback:DRAFT", "rollback:INPUTS_LOCKED", "patch"},
    "FINALISED": {"mark-paid"},
    "PAID": set(),
}


async def fire(client: AsyncClient, admin: dict[str, str], approver: dict[str, str], rid: str, version: Any, action: str) -> Any:
    if action == "patch":
        return await client.patch(f"{BASE}/{rid}", headers=hdr(admin, version), json={"pay_date": "2026-10-05"})
    if action == "delete":
        return await client.delete(f"{BASE}/{rid}", headers=admin)
    if action.startswith("rollback:"):
        return await act(client, admin, rid, "rollback", version, {"to_status": action.split(":")[1], "reason": "QA probe"})
    who = approver if action in ("approve", "finalise", "mark-paid") else admin
    return await act(client, who, rid, action, version)


async def test_flow_001_state_machine_every_illegal_action_in_every_state(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "PAYROLL-FLOW-001"
    h, cid, uid = await _register_tenant(client)
    try:
        le = await _legal_entity(client, h)
        e1 = await _employee(client, h, le, name="Ann")
        e2 = await _employee(client, h, le, name="Bob")
        approver = await _approver(cid)
        await _closed_period(company_id=cid, legal_entity_id=le, start="2026-09-01", end="2026-09-30", paid_days={e1: "30", e2: "30"}, days_in_month=30)
        run = await _create_run(client, h, le, "2026-09")
        rid = run["id"]
        matrix: dict[str, dict[str, Any]] = {}
        forward = {"DRAFT": "lock-inputs", "INPUTS_LOCKED": "compute", "COMPUTED": "approve", "APPROVED": "finalise", "FINALISED": "mark-paid"}
        trail = []
        for st in ("DRAFT", "INPUTS_LOCKED", "COMPUTED", "APPROVED", "FINALISED", "PAID"):
            cur = await get_run(client, h, rid)
            assert cur["status"] == st, (st, cur["status"])
            before = await state(cid, rid)
            row: dict[str, Any] = {}
            for action in ALL_ACTIONS:
                if action in ALLOWED[st]:
                    continue
                r = await fire(client, h, approver, rid, cur["version"], action)
                code = (r.json().get("error") or {}).get("code") if r.headers.get("content-type", "").startswith("application/json") else None
                row[action] = {"status": r.status_code, "code": code}
                assert r.status_code == 409 and code == "PAY_RUN_INVALID_TRANSITION", (st, action, r.status_code, r.text[:200])
            after = await state(cid, rid)
            matrix[st] = {"illegal_actions_tried": row, "db_unchanged": before == after}
            assert before == after, f"refused actions changed the database in {st}: {before} -> {after}"
            if st == "COMPUTED":
                # version guards on a legal action: stale and missing If-Match change nothing
                stale = await act(client, approver, rid, "approve", cur["version"] - 1)
                missing = await client.post(f"{BASE}/{rid}/approve", headers=approver)
                matrix[st]["stale_if_match"] = [stale.status_code, (stale.json().get("error") or {}).get("code")]
                matrix[st]["missing_if_match"] = missing.status_code
                assert stale.status_code == 409 and missing.status_code == 422
                assert await state(cid, rid) == before
            if st in forward:
                r = await fire(client, h, approver, rid, cur["version"], forward[st])
                assert r.status_code == 200, (st, r.text[:300])
                nxt = r.json()["data"]
                assert nxt["version"] == cur["version"] + 1, "every transition must bump the version by exactly one"
                trail.append((st, nxt["status"], nxt["version"]))
        acts = await audit_actions(cid, rid)
        rec(c, "state matrix (illegal actions tried per state; DB snapshot compared before/after)", matrix=matrix, trail=trail, audit=acts)
        assert [a["action"] for a in acts] == ["PAYROLL_PAY_RUN_CREATED", "PAYROLL_PAY_RUN_INPUTS_LOCKED", "PAYROLL_PAY_RUN_COMPUTED", "PAYROLL_PAY_RUN_APPROVED", "PAYROLL_PAY_RUN_FINALISED", "PAYROLL_PAY_RUN_PAID"], acts
        assert [(a["b"], a["a"]) for a in acts[1:]] == [("DRAFT", "INPUTS_LOCKED"), ("INPUTS_LOCKED", "COMPUTED"), ("COMPUTED", "APPROVED"), ("APPROVED", "FINALISED"), ("FINALISED", "PAID")]
        assert all(a["request_id"] for a in acts)
    finally:
        await _cleanup_pay_runs(company_id=cid)
        await _cleanup(company_id=cid, user_id=uid)
        await _cleanup_scoped_users()


async def test_flow_001_legal_backward_moves_reset_state_and_are_audited(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "PAYROLL-FLOW-001"
    h, cid, uid = await _register_tenant(client)
    try:
        le = await _legal_entity(client, h)
        e1 = await _employee(client, h, le, name="Ann")
        approver = await _approver(cid)
        await _closed_period(company_id=cid, legal_entity_id=le, start="2026-09-01", end="2026-09-30", paid_days={e1: "30"}, days_in_month=30)
        run = await _create_run(client, h, le, "2026-09"); rid = run["id"]
        run = (await act(client, h, rid, "lock-inputs", run["version"])).json()["data"]
        run = (await act(client, h, rid, "compute", run["version"])).json()["data"]
        locked = await state(cid, rid)
        assert locked["employees"] == 1 and locked["lines"] > 0
        # rollback needs a reason
        noreason = await act(client, h, rid, "rollback", run["version"], {"to_status": "INPUTS_LOCKED"})
        assert noreason.status_code == 422 and await state(cid, rid) == locked
        # COMPUTED -> INPUTS_LOCKED : lines deleted, employee snapshot rows kept, reason stored
        r = await act(client, h, rid, "rollback", run["version"], {"to_status": "INPUTS_LOCKED", "reason": "recheck"})
        assert r.status_code == 200, r.text
        run = r.json()["data"]
        s1 = await state(cid, rid)
        rec(c, "rollback COMPUTED -> INPUTS_LOCKED", before=locked, after=s1)
        assert run["status"] == "INPUTS_LOCKED" and s1["lines"] == 0 and s1["employees"] == 1 and s1["last_rollback_reason"] == "recheck" and s1["net_minor"] in (0, None)
        # recompute then APPROVED -> DRAFT : everything reset, attendance link cleared
        run = (await act(client, h, rid, "compute", run["version"])).json()["data"]
        run = (await act(client, approver, rid, "approve", run["version"])).json()["data"]
        r = await act(client, h, rid, "rollback", run["version"], {"to_status": "DRAFT", "reason": "wrong month"})
        assert r.status_code == 200, r.text
        s2 = await state(cid, rid)
        link = (await q("SELECT attendance_period_id, inputs_locked_at FROM pay_run WHERE id = :i AND company_id = :c", i=rid, c=str(cid)))[0]
        rec(c, "rollback APPROVED -> DRAFT", after=s2, link=link)
        assert s2["status"] == "DRAFT" and s2["employees"] == 0 and s2["lines"] == 0 and link["attendance_period_id"] is None and link["inputs_locked_at"] is None
        # the run can be locked again and ends with the same employee count (restart is clean, no duplicates)
        run = r.json()["data"]
        run = (await act(client, h, rid, "lock-inputs", run["version"])).json()["data"]
        s3 = await state(cid, rid)
        assert s3["employees"] == 1 and run["employee_count"] == 1
        acts = [a["action"] for a in await audit_actions(cid, rid)]
        rec(c, "audit trail", actions=acts)
        assert acts.count("PAYROLL_PAY_RUN_ROLLED_BACK") == 2 and acts[-1] == "PAYROLL_PAY_RUN_INPUTS_LOCKED"
        # delete a draft is audited and removes the run
        run = (await act(client, h, rid, "rollback", run["version"], {"to_status": "DRAFT", "reason": "again"})).json()["data"]
        d = await client.delete(f"{BASE}/{rid}", headers=h)
        assert d.status_code == 204 and (await state(cid, rid)) == {"exists": False}
        assert "PAYROLL_PAY_RUN_DELETED" in [a["action"] for a in await audit_actions(cid, rid)]
    finally:
        await _cleanup_pay_runs(company_id=cid)
        await _cleanup(company_id=cid, user_id=uid)
        await _cleanup_scoped_users()


# =================================================================================== PAYROLL-FLOW-001 create guards / duplicates
async def test_flow_001_create_prerequisites_duplicates_and_parallel_creates(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "PAYROLL-FLOW-001"
    h, cid, uid = await _register_tenant(client)
    t2h, t2cid, t2uid = await _register_tenant(client)
    try:
        le = await _legal_entity(client, h)
        other_le = (await client.post("/v1/legal-entities", headers=t2h, json={"name": "Other tenant LE"})).json()["data"]["id"]
        out: dict[str, Any] = {}

        async def create(body: dict, headers: dict[str, str] | None = None) -> Any:
            return await client.post(BASE, headers=headers or h, json=body)

        cases = {
            "unknown legal entity": {"legal_entity_id": str(uuid4()), "month": "2026-09"},
            "legal entity of another tenant": {"legal_entity_id": other_le, "month": "2026-09"},
            "bad month format": {"legal_entity_id": le, "month": "2026-9"},
            "month 13": {"legal_entity_id": le, "month": "2026-13"},
            "missing month": {"legal_entity_id": le},
            "extra field": {"legal_entity_id": le, "month": "2026-09", "status": "PAID"},
        }
        for label, body in cases.items():
            r = await create(body)
            out[label] = [r.status_code, (r.json().get("error") or {}).get("code")]
            assert 400 <= r.status_code < 500, (label, r.status_code, r.text[:200])
        n_after_bad = (await q("SELECT count(*) n FROM pay_run WHERE company_id = :c", c=str(cid)))[0]["n"]
        out["rows after all refused creates"] = n_after_bad
        assert n_after_bad == 0
        # inactive legal entity
        le2 = (await client.post("/v1/legal-entities", headers=h, json={"name": "Dormant LE"})).json()["data"]
        async with get_session_factory()() as session:
            await session.execute(text("UPDATE legal_entity SET is_active = false WHERE id = :i"), {"i": le2["id"]})
            await session.commit()
        r = await create({"legal_entity_id": le2["id"], "month": "2026-09"})
        out["inactive legal entity"] = [r.status_code, (r.json().get("error") or {}).get("code")]
        assert r.status_code == 422 or r.status_code == 409, r.text
        assert (await q("SELECT count(*) n FROM pay_run WHERE company_id = :c", c=str(cid)))[0]["n"] == 0
        # parallel duplicate creates: exactly one row
        rs = await asyncio.gather(*[create({"legal_entity_id": le, "month": "2026-09"}) for _ in range(8)])
        codes = sorted(r.status_code for r in rs)
        rows = (await q("SELECT count(*) n FROM pay_run WHERE company_id = :c AND legal_entity_id = :l", c=str(cid), l=le))[0]["n"]
        created_audits = (await q("SELECT count(*) n FROM audit_log WHERE company_id = :c AND action = 'PAYROLL_PAY_RUN_CREATED'", c=str(cid)))[0]["n"]
        out["8 parallel creates"] = {"statuses": codes, "rows": rows, "created_audits": created_audits, "duplicate_code": next((r.json()["error"]["code"] for r in rs if r.status_code == 409), None)}
        rec(c, "create guards", results=out)
        assert codes.count(201) == 1 and codes.count(409) == 7 and rows == 1 and created_audits == 1
        # a different month for the same entity is a different run
        r = await create({"legal_entity_id": le, "month": "2026-10"})
        assert r.status_code == 201
        # pay-date edits
        rid = r.json()["data"]["id"]
        early = await client.patch(f"{BASE}/{rid}", headers=hdr(h, 1), json={"pay_date": "2026-10-10"})
        ok = await client.patch(f"{BASE}/{rid}", headers=hdr(h, 1), json={"pay_date": "2026-11-05"})
        rec(c, "pay date", before_month_end=[early.status_code, (early.json().get("error") or {}).get("code")], valid=ok.status_code, version_after=ok.json()["data"]["version"] if ok.status_code == 200 else None)
        assert early.status_code in (409, 422) and ok.status_code == 200 and ok.json()["data"]["version"] == 2
    finally:
        await _cleanup_pay_runs(company_id=cid)
        await _cleanup_pay_runs(company_id=t2cid)
        await _cleanup(company_id=cid, user_id=uid)
        await _cleanup(company_id=t2cid, user_id=t2uid)


# =================================================================================== PAYROLL-FLOW-002 / PIN-001 (real period close)
async def real_close(client: AsyncClient, h: dict[str, str], cid: Any, le: str, month: str) -> dict[str, Any]:
    """Close a month through the attendance engine itself: calculate every employed day, create the period, validate, finalise."""
    from hrms.modules.attendance.tasks import _calculate_range_async

    start, end, _ = MONTHS[month]
    await _calculate_range_async(cid, date.fromisoformat(start), date.fromisoformat(end), None, None, UUID(le))
    per = await client.post("/v1/attendance-periods", headers=h, json={"legal_entity_id": le, "period_start": start, "period_end": end, "label": "QA"})
    assert per.status_code == 201, per.text
    p = per.json()["data"]
    v = await client.post(f"/v1/attendance-periods/{p['id']}/validate", headers=h)
    assert v.status_code == 200 and v.json()["data"]["status"] == "READY", v.text[:400]
    f = await client.post(f"/v1/attendance-periods/{p['id']}/finalize", headers=hdr(h, p["version"]), json={})
    assert f.status_code == 200, f.text
    return dict(f.json()["data"])


async def test_flow_002_lock_requires_a_closed_period_real_close_and_pin_001(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "PAYROLL-FLOW-002"
    h, cid, uid = await _register_tenant(client)
    try:
        from tests.integration.modules.attendance.test_attendance_day import _build_wired_employee, _punch

        wired = await _build_wired_employee(client, h)           # real shift / calendar / attendance policy, so the engine reaches real verdicts
        e1, le = wired["employee"]["id"], wired["branch"]["legal_entity_id"]
        await payroll_profile(client, h, e1)
        e2 = e1
        for day in ("2026-09-07", "2026-09-08", "2026-09-09"):                # three worked days so the frozen summary is not all-absent
            await _punch(client, h, employee_id=e1, hour=9, minute=0, direction="IN", day=day)
            await _punch(client, h, employee_id=e1, hour=18, minute=0, direction="OUT", day=day)
        run = await _create_run(client, h, le, "2026-09"); rid = run["id"]
        results: dict[str, Any] = {}
        before = await state(cid, rid)
        r = await act(client, h, rid, "lock-inputs", run["version"])
        results["no period"] = [r.status_code, (r.json().get("error") or {}).get("code")]
        assert r.status_code == 409 and r.json()["error"]["code"] == "PAY_RUN_ATTENDANCE_NOT_CLOSED" and await state(cid, rid) == before
        # an OPEN period over the month is not enough
        from hrms.modules.attendance.tasks import _calculate_range_async

        await _calculate_range_async(cid, date(2026, 9, 1), date(2026, 9, 30), None, None, UUID(le))
        per = await client.post("/v1/attendance-periods", headers=h, json={"legal_entity_id": le, "period_start": "2026-09-01", "period_end": "2026-09-30", "label": "QA"})
        assert per.status_code == 201, per.text
        pid, pver = per.json()["data"]["id"], per.json()["data"]["version"]
        r = await act(client, h, rid, "lock-inputs", run["version"])
        results["OPEN period"] = [r.status_code, (r.json().get("error") or {}).get("code")]
        assert r.status_code == 409 and r.json()["error"]["code"] == "PAY_RUN_ATTENDANCE_NOT_CLOSED" and await state(cid, rid) == before
        # a period for a DIFFERENT legal entity does not satisfy this run
        # (checked later with the second entity); now close the right one for real
        v = await client.post(f"/v1/attendance-periods/{pid}/validate", headers=h)
        results["validate"] = [v.status_code, v.json()["data"]["status"], v.json()["data"].get("reasons")]
        assert v.status_code == 200 and v.json()["data"]["status"] == "READY", v.text[:300]
        f = await client.post(f"/v1/attendance-periods/{pid}/finalize", headers=hdr(h, pver), json={})
        assert f.status_code == 200 and f.json()["data"]["status"] == "CLOSED", f.text[:300]
        period_version = f.json()["data"]["version"]
        locked = await act(client, h, rid, "lock-inputs", run["version"])
        assert locked.status_code == 200, locked.text
        lr = locked.json()["data"]
        s = await state(cid, rid)
        dbv = (await q("SELECT attendance_period_id::text p, attendance_period_version v FROM pay_run WHERE id = :i AND company_id = :c", i=rid, c=str(cid)))[0]
        results["after real close"] = {"status": lr["status"], "attendance_period_id": lr["attendance_period_id"], "db_period_version_pinned": dbv["v"], "period_version_at_close": period_version, "employees": s["employees"]}
        assert lr["attendance_period_id"] == pid == dbv["p"] and dbv["v"] == period_version and s["employees"] == 1 == lr["employee_count"]
        # PAYROLL-PIN-001: the locked snapshot equals the closed period's frozen summary (equality, not an expected amount)
        summ = {r_["employee_id"]: r_ for r_ in await q("SELECT employee_id::text employee_id, paid_days::text paid, payable_days::text payable, lop_days::text lop FROM attendance_period_summary WHERE attendance_period_id = :p AND company_id = :c", p=pid, c=str(cid))}
        snaps = {r_["employee_id"]: r_ for r_ in await q("SELECT employee_id::text employee_id, paid_days::text paid, payable_days::text payable, lop_days::text lop FROM pay_run_employee WHERE pay_run_id = :i AND company_id = :c", i=rid, c=str(cid))}
        rec("PAYROLL-PIN-001", "snapshot vs frozen summary", summary=summ, snapshot=snaps)
        assert set(summ) == set(snaps) == {e1}
        assert Decimal(summ[e1]["paid"]) > 0, "fixture should have produced non-zero paid days so the equality is meaningful"
        for eid in summ:
            assert Decimal(summ[eid]["paid"]) == Decimal(snaps[eid]["paid"]) and Decimal(summ[eid]["payable"]) == Decimal(snaps[eid]["payable"]) and Decimal(summ[eid]["lop"]) == Decimal(snaps[eid]["lop"]), eid
        # PD-2/decision 15: a period tied to a locked/computed run cannot be silently reopened while approved? (reopen is allowed before finalisation, run then stale)
        run2 = (await act(client, h, rid, "compute", lr["version"])).json()["data"]
        reopened = await client.post(f"/v1/attendance-periods/{pid}/reopen", headers=hdr(h, period_version), json={"reason": "QA correction before payroll"})
        results["reopen while COMPUTED"] = reopened.status_code
        approver = await _approver(cid)
        blocked = await act(client, approver, rid, "approve", run2["version"])
        results["approve after reopen"] = [blocked.status_code, (blocked.json().get("error") or {}).get("code")]
        s_blocked = await state(cid, rid)
        assert reopened.status_code == 200 and blocked.status_code == 409 and blocked.json()["error"]["code"] == "PAY_RUN_ATTENDANCE_CHANGED"
        assert s_blocked["status"] == "COMPUTED" and s_blocked["version"] == run2["version"]
        # recovery: close again, roll back to DRAFT, lock again, compute, approve works
        per2 = (await client.get(f"/v1/attendance-periods/{pid}", headers=h)).json()["data"]
        again = await client.post(f"/v1/attendance-periods/{pid}/validate", headers=h)
        fin = await client.post(f"/v1/attendance-periods/{pid}/finalize", headers=hdr(h, per2["version"]), json={})
        assert fin.status_code == 200, fin.text
        stale = await act(client, approver, rid, "approve", run2["version"])
        results["approve after re-close but WITHOUT re-locking"] = [stale.status_code, (stale.json().get("error") or {}).get("code")]
        assert stale.status_code == 409
        rb = await act(client, h, rid, "rollback", run2["version"], {"to_status": "DRAFT", "reason": "period reopened"})
        assert rb.status_code == 200, rb.text
        relock = await act(client, h, rid, "lock-inputs", rb.json()["data"]["version"]); assert relock.status_code == 200, relock.text
        recomp = await act(client, h, rid, "compute", relock.json()["data"]["version"]); assert recomp.status_code == 200, recomp.text
        ok = await act(client, approver, rid, "approve", recomp.json()["data"]["version"])
        results["approve after rollback + relock + recompute"] = ok.status_code
        assert ok.status_code == 200
        # a period for ANOTHER legal entity does not satisfy a run for this entity
        le_b = (await client.post("/v1/legal-entities", headers=h, json={"name": "Second LE"})).json()["data"]["id"]
        run_b = await _create_run(client, h, le_b, "2026-09")
        rb_ = await act(client, h, run_b["id"], "lock-inputs", run_b["version"])
        results["run of entity B with only entity A's period closed"] = [rb_.status_code, (rb_.json().get("error") or {}).get("code")]
        assert rb_.status_code == 409 and rb_.json()["error"]["code"] == "PAY_RUN_ATTENDANCE_NOT_CLOSED"
        rec(c, "lock prerequisites and recovery", results=results)
    finally:
        await wipe_tenant(company_id=cid, user_id=uid)
        await _cleanup_scoped_users()


# =================================================================================== PAYROLL-FLOW-003 / SLIP-001 under the RUNTIME role
async def test_flow_003_slip_001_full_run_to_paid_as_runtime_role(client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch) -> None:
    c = "PAYROLL-FLOW-003"
    t = await _att_tenant(client)
    try:
        a_id, a_h = await _employee_user(client, t, "Anita")
        b_id, b_h = await _employee_user(client, t, "Bharat")
        for eid in (a_id, b_id):
            await payroll_profile(client, t.admin, eid)
        le = t.legal_entity_id
        approver = await _approver(t.company_id)
        await _closed_period(company_id=t.company_id, legal_entity_id=le, start="2026-09-01", end="2026-09-30", paid_days={a_id: "30", b_id: "28"}, days_in_month=30)
        await switch_role(monkeypatch, "app")                       # from here every request AND check runs as hrms_app (RLS applies)
        who = (await q("SELECT current_user u"))[0]["u"]
        assert who == "hrms_app"
        cid = t.company_id
        run = await _create_run(client, t.admin, le, "2026-09"); rid = run["id"]
        log: list[dict[str, Any]] = []

        async def step(name: str, who_h: dict[str, str], action: str, ver: Any, body: dict | None = None) -> dict[str, Any]:
            r = await act(client, who_h, rid, action, ver, body)
            assert r.status_code == 200, (name, r.status_code, r.text[:300])
            d = r.json()["data"]
            st = await state(cid, rid)
            log.append({"step": name, "api_status": d["status"], "db_status": st["status"], "version": d["version"], "employees": st["employees"], "lines": st["lines"], "audit": st["audit"]})
            assert d["status"] == st["status"] and d["version"] == st["version"]
            return d

        mine_before = await client.get("/v1/me/payslips", headers=a_h)
        run = await step("lock-inputs", t.admin, "lock-inputs", run["version"])
        mine_locked = await client.get("/v1/me/payslips", headers=a_h)
        run = await step("compute", t.admin, "compute", run["version"])
        mine_computed = await client.get("/v1/me/payslips", headers=a_h)
        own_computed = await client.get(f"/v1/me/payslips/{rid}", headers=a_h)
        for e in (await client.get(f"{BASE}/{rid}/employees", headers=t.admin)).json()["data"]:
            if e["variance_flagged"]:
                await client.post(f"{BASE}/{rid}/employees/{e['employee_id']}/acknowledge-variance", headers=t.admin, json={"reason": "synthetic"})
        run = await get_run(client, t.admin, rid)
        run = await step("approve (different user)", approver, "approve", run["version"])
        mine_approved = await client.get("/v1/me/payslips", headers=a_h)
        run = await step("finalise", approver, "finalise", run["version"])
        mine_final = await client.get("/v1/me/payslips", headers=a_h)
        own_final = await client.get(f"/v1/me/payslips/{rid}", headers=a_h)
        b_final = await client.get(f"/v1/me/payslips/{rid}", headers=b_h)
        run = await step("mark-paid", approver, "mark-paid", run["version"])
        slips = {"before lock": mine_before, "locked": mine_locked, "computed": mine_computed, "approved": mine_approved, "finalised": mine_final}
        vis = {k: [v.status_code, len(v.json().get("data", [])) if v.status_code == 200 else None] for k, v in slips.items()}
        vis["own detail while COMPUTED"] = own_computed.status_code
        vis["own detail FINALISED"] = own_final.status_code
        # aggregation identities (not expected amounts)
        emps = (await client.get(f"{BASE}/{rid}/employees", headers=t.admin)).json()["data"]
        net_sum, gross_sum = sum(e["net_minor"] for e in emps), sum(e["gross_minor"] for e in emps)
        final_run = await get_run(client, t.admin, rid)
        rec(c, "full run to PAID as hrms_app", db_role=who, steps=log, payslip_visibility=vis, run_net=final_run["net_minor"], sum_employee_net=net_sum, run_gross=final_run["gross_minor"], sum_employee_gross=gross_sum,
            audit=await audit_actions(cid, rid))
        assert [x["db_status"] for x in log] == ["INPUTS_LOCKED", "COMPUTED", "APPROVED", "FINALISED", "PAID"]
        assert final_run["net_minor"] == net_sum and final_run["gross_minor"] == gross_sum and len(emps) == 2
        # SLIP-001: employees see payslips only from a finalised run
        for k in ("before lock", "locked", "computed", "approved"):
            assert vis[k] == [200, 0], (k, vis[k])
        assert vis["finalised"] == [200, 1] and own_computed.status_code == 404 and own_final.status_code == 200
        assert own_final.json()["data"]["employee_id"] == a_id if "employee_id" in own_final.json()["data"] else True
        # the other employee's slip is a different row; and each sees only their own
        assert b_final.status_code == 200 and b_final.json()["data"] != own_final.json()["data"]
        # no employee can use the admin payslip route
        denied = await client.get(f"{BASE}/{rid}/employees/{b_id}/payslip", headers=a_h)
        assert denied.status_code == 403
        acts = [a["action"] for a in await audit_actions(cid, rid)]
        assert acts == ["PAYROLL_PAY_RUN_CREATED", "PAYROLL_PAY_RUN_INPUTS_LOCKED", "PAYROLL_PAY_RUN_COMPUTED", "PAYROLL_PAY_RUN_APPROVED", "PAYROLL_PAY_RUN_FINALISED", "PAYROLL_PAY_RUN_PAID"]
        # SLIP-001 part 2: payslip of a run that has an employee row for B only is invisible to A; unknown run id -> 404; other tenant -> 404
        unknown = await client.get(f"/v1/me/payslips/{uuid4()}", headers=a_h)
        assert unknown.status_code == 404
        rec("PAYROLL-SLIP-001", "visibility", visibility=vis, other_employee_detail=b_final.status_code, admin_route_as_employee=denied.status_code, unknown_run=unknown.status_code)
    finally:
        await switch_role(monkeypatch, "owner")
        await drop_invites(t.company_id)
        await _cleanup_pay_runs(company_id=t.company_id)
        await _att_teardown(t)
        await _cleanup_scoped_users()


# =================================================================================== PAYROLL-FLOW-004 maker-checker
async def test_flow_004_maker_checker_follows_the_last_computer(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "PAYROLL-FLOW-004"
    h, cid, uid = await _register_tenant(client)
    try:
        le = await _legal_entity(client, h)
        e1 = await _employee(client, h, le, name="Ann")
        await _closed_period(company_id=cid, legal_entity_id=le, start="2026-09-01", end="2026-09-30", paid_days={e1: "30"}, days_in_month=30)
        both, _ = await _create_permission_scoped_user(company_id=cid, permission_codes=["PAYROLL.RUN_VIEW", "PAYROLL.RUN_PROCESS", "PAYROLL.RUN_APPROVE"], data_scope="COMPANY")
        approver = await _approver(cid)
        view_only, _ = await _create_permission_scoped_user(company_id=cid, permission_codes=["PAYROLL.RUN_VIEW"], data_scope="COMPANY")
        proc_only, _ = await _create_permission_scoped_user(company_id=cid, permission_codes=["PAYROLL.RUN_VIEW", "PAYROLL.RUN_PROCESS"], data_scope="COMPANY")
        run = await _create_run(client, h, le, "2026-09"); rid = run["id"]
        run = (await act(client, h, rid, "lock-inputs", run["version"])).json()["data"]
        run = (await act(client, h, rid, "compute", run["version"])).json()["data"]
        admin_id = (await q("SELECT computed_by_user_id::text u FROM pay_run WHERE id = :i AND company_id = :c", i=rid, c=str(cid)))[0]["u"]
        snap = await state(cid, rid)
        res: dict[str, Any] = {}
        same = await act(client, h, rid, "approve", run["version"])          # admin holds RUN_APPROVE but computed it
        res["computer approves own run"] = [same.status_code, (same.json().get("error") or {}).get("code")]
        no_perm = await act(client, proc_only, rid, "approve", run["version"])
        res["processor without RUN_APPROVE"] = no_perm.status_code
        view = await act(client, view_only, rid, "approve", run["version"])
        res["viewer"] = view.status_code
        assert same.status_code == 403 and same.json()["error"]["code"] == "PAY_RUN_MAKER_CHECKER" and no_perm.status_code == 403 and view.status_code == 403
        assert await state(cid, rid) == snap, "refused approvals changed the run"
        # the user who LAST computed is the maker: B (has both permissions) recomputes -> B is now barred, the admin may approve
        recomputed = await act(client, both, rid, "compute", run["version"])
        assert recomputed.status_code == 200, recomputed.text
        run = recomputed.json()["data"]
        who_now = (await q("SELECT computed_by_user_id::text u FROM pay_run WHERE id = :i AND company_id = :c", i=rid, c=str(cid)))[0]["u"]
        res["computed_by changed to the recomputing user"] = who_now != admin_id
        b_try = await act(client, both, rid, "approve", run["version"])
        res["new maker approves"] = [b_try.status_code, (b_try.json().get("error") or {}).get("code")]
        assert who_now != admin_id and b_try.status_code == 403 and b_try.json()["error"]["code"] == "PAY_RUN_MAKER_CHECKER"
        okr = await act(client, h, rid, "approve", run["version"])
        res["previous maker approves after someone else recomputed"] = okr.status_code
        assert okr.status_code == 200
        row = (await q("SELECT approved_by_user_id::text a, computed_by_user_id::text c FROM pay_run WHERE id = :i AND company_id = :c", i=rid, c=str(cid)))[0]
        assert row["a"] != row["c"] and row["a"] == admin_id
        rec(c, "maker-checker", results=res, computed_by=row["c"], approved_by=row["a"])
        # finalise/mark-paid are not maker-checked in the code (approve only): record who may finalise
        fin = await act(client, h, rid, "finalise", okr.json()["data"]["version"])
        rec(c, "OBSERVATION finalise by the user who approved", status=fin.status_code)
    finally:
        await _cleanup_pay_runs(company_id=cid)
        await _cleanup(company_id=cid, user_id=uid)
        await _cleanup_scoped_users()


# =================================================================================== PAYROLL-FLOW-005 inputs changed after lock
async def test_flow_005_inputs_changed_after_lock_block_approval_until_relocked(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "PAYROLL-FLOW-005"
    h, cid, uid = await _register_tenant(client)
    try:
        le = await _legal_entity(client, h)
        e1 = await _employee(client, h, le, name="Ann")
        approver = await _approver(cid)
        await _closed_period(company_id=cid, legal_entity_id=le, start="2026-09-01", end="2026-09-30", paid_days={e1: "30"}, days_in_month=30)
        run = await _create_run(client, h, le, "2026-09"); rid = run["id"]
        run = (await act(client, h, rid, "lock-inputs", run["version"])).json()["data"]
        run = (await act(client, h, rid, "compute", run["version"])).json()["data"]
        before = await state(cid, rid)
        res: dict[str, Any] = {}
        # change an input after the lock: a new compensation revision effective inside the month
        cur = (await client.get(f"/v1/employees/{e1}/compensation", headers=h)).json()["data"]
        comp = await client.post(f"/v1/employees/{e1}/compensation", headers={**h, "If-Match": str(cur[0]["version"])}, json={"effective_from": "2026-09-15", "annual_ctc_minor": 9_00_000_00, "currency": "INR", "revision_type": "ANNUAL", "revision_reason": "QA input change"})
        res["compensation revision accepted"] = comp.status_code
        assert comp.status_code == 201, comp.text
        r = await act(client, approver, rid, "approve", run["version"])
        res["approve after compensation change"] = [r.status_code, (r.json().get("error") or {}).get("code")]
        rec(c, "after input change", results=res, state_before=before, state_after=await state(cid, rid))
        assert r.status_code == 409 and r.json()["error"]["code"] == "PAY_RUN_INPUTS_CHANGED", r.text[:300]
        assert await state(cid, rid) == before, "the refused approval changed the run"
        # the approval message says what changed (kept for the operator)
        res["details"] = r.json()["error"].get("details")
        # recovery: roll back and re-lock, then approval succeeds
        rb = await act(client, h, rid, "rollback", run["version"], {"to_status": "DRAFT", "reason": "input changed"})
        assert rb.status_code == 200
        run = (await act(client, h, rid, "lock-inputs", rb.json()["data"]["version"])).json()["data"]
        run = (await act(client, h, rid, "compute", run["version"])).json()["data"]
        ok = await act(client, approver, rid, "approve", run["version"])
        res["approve after re-lock"] = ok.status_code
        rec(c, "recovery", results=res)
        assert ok.status_code == 200
        # finalised: an input change is no longer able to touch the run at all
        fin = await act(client, approver, rid, "finalise", ok.json()["data"]["version"]); assert fin.status_code == 200, fin.text
        snap = await state(cid, rid)
        cur2 = (await client.get(f"/v1/employees/{e1}/compensation", headers=h)).json()["data"]
        again = await client.post(f"/v1/employees/{e1}/compensation", headers={**h, "If-Match": str(cur2[0]["version"])}, json={"effective_from": "2026-09-20", "annual_ctc_minor": 10_00_000_00, "currency": "INR", "revision_type": "ANNUAL", "revision_reason": "after finalise"})
        assert await state(cid, rid) == snap and (await act(client, h, rid, "compute", fin.json()["data"]["version"])).status_code == 409
        rec(c, "after finalise", later_compensation_change=again.status_code, run_unchanged=True)
    finally:
        await _cleanup_pay_runs(company_id=cid)
        await _cleanup(company_id=cid, user_id=uid)
        await _cleanup_scoped_users()


# =================================================================================== PAYROLL-FLOW-006 variance gate
async def test_flow_006_variance_gate_blocks_until_reason_recorded(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "PAYROLL-FLOW-006"
    h, cid, uid = await _register_tenant(client)
    try:
        le = await _legal_entity(client, h)
        steady = await _employee(client, h, le, name="Steady")
        dropped = await _employee(client, h, le, name="Dropped")
        approver = await _approver(cid)
        aug = await finalised(client, h, approver, cid, le, "2026-08", {steady: "31", dropped: "31"})
        await _closed_period(company_id=cid, legal_entity_id=le, start="2026-09-01", end="2026-09-30", paid_days={steady: "30", dropped: "15"}, days_in_month=30)
        run = await _create_run(client, h, le, "2026-09"); rid = run["id"]
        run = (await act(client, h, rid, "lock-inputs", run["version"])).json()["data"]
        run = (await act(client, h, rid, "compute", run["version"])).json()["data"]
        emps = {e["employee_id"]: e for e in (await client.get(f"{BASE}/{rid}/employees", headers=h)).json()["data"]}
        res: dict[str, Any] = {"previous_run": run["previous_pay_run_id"] == aug["id"], "threshold": run["variance_threshold_percent"], "flag_count": run["variance_flag_count"], "open": run["variance_open_count"]}
        assert run["previous_pay_run_id"] == aug["id"] and run["variance_open_count"] == 1 and emps[dropped]["variance_flagged"] and not emps[steady]["variance_flagged"]
        snap = await state(cid, rid)
        b = await act(client, approver, rid, "approve", run["version"])
        res["approve with an open flag"] = [b.status_code, (b.json().get("error") or {}).get("code"), [x["code"] for x in b.json()["error"]["details"][0]["context"]["reasons"]]]
        assert b.status_code == 409 and b.json()["error"]["code"] == "PAY_RUN_BLOCKED" and await state(cid, rid) == snap
        # acknowledgement guards
        not_flagged = await client.post(f"{BASE}/{rid}/employees/{steady}/acknowledge-variance", headers=h, json={"reason": "no flag here"})
        no_reason = await client.post(f"{BASE}/{rid}/employees/{dropped}/acknowledge-variance", headers=h, json={})
        unprivileged = await client.post(f"{BASE}/{rid}/employees/{dropped}/acknowledge-variance", headers=approver, json={"reason": "approver cannot acknowledge"})
        res["acknowledge: unflagged / no reason / approver-only user"] = [not_flagged.status_code, no_reason.status_code, unprivileged.status_code]
        assert not_flagged.status_code in (409, 422) and no_reason.status_code == 422 and unprivileged.status_code == 403
        assert await state(cid, rid) == snap
        ok = await client.post(f"{BASE}/{rid}/employees/{dropped}/acknowledge-variance", headers=h, json={"reason": "Synthetic reason for QA"})
        assert ok.status_code == 200
        row = (await q("SELECT variance_reason, variance_acknowledged_by_user_id::text u FROM pay_run_employee WHERE pay_run_id = :i AND company_id = :c AND employee_id = :e", i=rid, c=str(cid), e=dropped))[0]
        res["reason stored"] = row
        assert row["variance_reason"] == "Synthetic reason for QA" and row["u"]
        run = await get_run(client, h, rid)
        assert run["variance_open_count"] == 0
        done = await act(client, approver, rid, "approve", run["version"])
        res["approve after the reason"] = done.status_code
        assert done.status_code == 200
        # a reason does not survive a rollback to DRAFT + re-lock (fresh snapshot)  -> record
        rec(c, "variance gate", results=res, exact_15_percent_boundary="NOT TESTED - open question CL-07")
        # acknowledging after approval is refused
        late = await client.post(f"{BASE}/{rid}/employees/{dropped}/acknowledge-variance", headers=h, json={"reason": "too late"})
        assert late.status_code == 409
    finally:
        await _cleanup_pay_runs(company_id=cid)
        await _cleanup(company_id=cid, user_id=uid)
        await _cleanup_scoped_users()


# =================================================================================== PAYROLL-FLOW-007 concurrency
async def test_flow_007_parallel_transitions_have_one_winner_and_no_duplicate_effects(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "PAYROLL-FLOW-007"
    h, cid, uid = await _register_tenant(client)
    try:
        le = await _legal_entity(client, h)
        emps = [await _employee(client, h, le, name=f"E{i}") for i in range(3)]
        approver = await _approver(cid)
        approver2 = await _approver(cid)
        await _closed_period(company_id=cid, legal_entity_id=le, start="2026-09-01", end="2026-09-30", paid_days={e: "30" for e in emps}, days_in_month=30)
        run = await _create_run(client, h, le, "2026-09"); rid = run["id"]
        out: dict[str, Any] = {}

        async def race(label: str, n: int, mk: Any) -> list[Any]:
            rs = await asyncio.gather(*[mk(i) for i in range(n)])
            codes = [r.status_code for r in rs]
            out[label] = {"statuses": sorted(codes), "error_codes": sorted({(r.json().get("error") or {}).get("code") for r in rs if r.status_code >= 400})}
            return rs

        v = run["version"]
        rs = await race("8 parallel lock-inputs, same If-Match", 8, lambda i: act(client, h, rid, "lock-inputs", v))
        s = await state(cid, rid)
        assert [r.status_code for r in rs].count(200) == 1 and s["status"] == "INPUTS_LOCKED" and s["employees"] == 3 == s["employee_count"], (out, s)
        assert (await audit_actions(cid, rid)).__len__() == 2
        v = (await get_run(client, h, rid))["version"]
        rs = await race("6 parallel compute, same If-Match", 6, lambda i: act(client, h, rid, "compute", v))
        s = await state(cid, rid)
        lines_per_emp = (await q("SELECT employee_id::text e, count(*) n FROM pay_run_line WHERE pay_run_id = :i AND company_id = :c GROUP BY 1", i=rid, c=str(cid)))
        assert [r.status_code for r in rs].count(200) == 1 and s["status"] == "COMPUTED"
        assert len({x["n"] for x in lines_per_emp}) == 1 and len(lines_per_emp) == 3, "duplicate or missing lines after racing computes"
        base_lines = s["lines"]
        v = (await get_run(client, h, rid))["version"]
        rs = await race("8 parallel approve by two approvers, same If-Match", 8, lambda i: act(client, approver if i % 2 else approver2, rid, "approve", v))
        s = await state(cid, rid)
        assert [r.status_code for r in rs].count(200) == 1 and s["status"] == "APPROVED"
        v = (await get_run(client, h, rid))["version"]
        rs = await race("8 parallel finalise, same If-Match", 8, lambda i: act(client, approver, rid, "finalise", v))
        s = await state(cid, rid)
        acts = [a["action"] for a in await audit_actions(cid, rid)]
        assert [r.status_code for r in rs].count(200) == 1 and s["status"] == "FINALISED" and s["lines"] == base_lines
        assert acts.count("PAYROLL_PAY_RUN_FINALISED") == 1 and acts.count("PAYROLL_PAY_RUN_APPROVED") == 1
        v = (await get_run(client, h, rid))["version"]
        rs = await race("8 parallel mark-paid, same If-Match", 8, lambda i: act(client, approver, rid, "mark-paid", v))
        s = await state(cid, rid)
        assert [r.status_code for r in rs].count(200) == 1 and s["status"] == "PAID" and (await audit_actions(cid, rid))[-1]["action"] == "PAYROLL_PAY_RUN_PAID"
        rec(c, "parallel single-action races", results=out, final=s)

        # conflicting actions on the same version: approve vs rollback race, fresh run
        await _closed_period(company_id=cid, legal_entity_id=le, start="2026-10-01", end="2026-10-31", paid_days={e: "31" for e in emps}, days_in_month=31)
        r2 = await _create_run(client, h, le, "2026-10"); rid2 = r2["id"]
        r2 = (await act(client, h, rid2, "lock-inputs", r2["version"])).json()["data"]
        r2 = (await act(client, h, rid2, "compute", r2["version"])).json()["data"]
        for e in (await client.get(f"{BASE}/{rid2}/employees", headers=h)).json()["data"]:
            if e["variance_flagged"]:
                await client.post(f"{BASE}/{rid2}/employees/{e['employee_id']}/acknowledge-variance", headers=h, json={"reason": "synthetic"})
        r2 = await get_run(client, h, rid2)
        results = await asyncio.gather(act(client, approver, rid2, "approve", r2["version"]), act(client, h, rid2, "rollback", r2["version"], {"to_status": "DRAFT", "reason": "race"}),
                                       act(client, h, rid2, "compute", r2["version"]))
        s2 = await state(cid, rid2)
        acts2 = [a["action"] for a in await audit_actions(cid, rid2)]
        out["approve vs rollback vs recompute on one version"] = {"statuses": [r.status_code for r in results], "final": s2["status"], "version": s2["version"], "audit_tail": acts2[-3:]}
        rec(c, "conflicting actions", result=out["approve vs rollback vs recompute on one version"])
        assert [r.status_code for r in results].count(200) == 1, "exactly one of the conflicting actions may win"
        assert s2["version"] == r2["version"] + 1
        # internal consistency of whatever won
        if s2["status"] == "DRAFT":
            assert s2["employees"] == 0 and s2["lines"] == 0
        if s2["status"] == "COMPUTED":
            assert s2["lines"] > 0
        if s2["status"] == "APPROVED":
            assert s2["lines"] > 0
        # parallel delete of a draft
        await _closed_period(company_id=cid, legal_entity_id=le, start="2026-08-01", end="2026-08-31", paid_days={e: "31" for e in emps}, days_in_month=31)
        r3 = await _create_run(client, h, le, "2026-08")
        dels = await asyncio.gather(*[client.delete(f"{BASE}/{r3['id']}", headers=h) for _ in range(6)])
        codes = sorted(r.status_code for r in dels)
        out["6 parallel deletes of a DRAFT"] = codes
        rec(c, "parallel delete", statuses=codes)
        assert codes.count(204) == 1 and all(x in (204, 404, 409) for x in codes) and (await state(cid, r3["id"])) == {"exists": False}
        assert [a["action"] for a in await audit_actions(cid, r3["id"])].count("PAYROLL_PAY_RUN_DELETED") == 1
    finally:
        await _cleanup_pay_runs(company_id=cid)
        await _cleanup(company_id=cid, user_id=uid)
        await _cleanup_scoped_users()


# =================================================================================== PAYROLL-FLOW-008 DB immutability as hrms_app
async def test_flow_008_finalised_rows_are_immutable_for_the_runtime_role(client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch) -> None:
    c = "PAYROLL-FLOW-008"
    h, cid, uid = await _register_tenant(client)
    try:
        le = await _legal_entity(client, h)
        e1 = await _employee(client, h, le, name="Ann")
        approver = await _approver(cid)
        fin = await finalised(client, h, approver, cid, le, "2026-09", {e1: "30"})
        draft_run = await _create_run(client, h, le, "2026-10")
        adj = await client.post("/v1/payroll/adjustments", headers={**h, "Idempotency-Key": "qa-adj-fin-0001"}, json={"source_pay_run_id": fin["id"], "employee_id": e1, "paid_days_delta": "-1", "reason": "QA correction"})
        rec(c, "setup", finalised_run=fin["id"], draft_run=draft_run["id"], adjustment=adj.status_code)
        await switch_role(monkeypatch, "app")
        who = (await q("SELECT current_user u"))[0]["u"]
        assert who == "hrms_app"
        attempts = {
            "UPDATE pay_run (finalised)": ("UPDATE pay_run SET pay_date = pay_date + 1 WHERE id = :i", {"i": fin["id"]}),
            "UPDATE pay_run status": ("UPDATE pay_run SET status = 'DRAFT' WHERE id = :i", {"i": fin["id"]}),
            "DELETE pay_run (finalised)": ("DELETE FROM pay_run WHERE id = :i", {"i": fin["id"]}),
            "UPDATE pay_run_employee": ("UPDATE pay_run_employee SET net_minor = net_minor + 1 WHERE pay_run_id = :i", {"i": fin["id"]}),
            "DELETE pay_run_employee": ("DELETE FROM pay_run_employee WHERE pay_run_id = :i", {"i": fin["id"]}),
            "UPDATE pay_run_line": ("UPDATE pay_run_line SET amount_minor = amount_minor + 1 WHERE pay_run_id = :i", {"i": fin["id"]}),
            "DELETE pay_run_line": ("DELETE FROM pay_run_line WHERE pay_run_id = :i", {"i": fin["id"]}),
        }
        fingerprint_before = (await q("SELECT md5(string_agg(t::text, '|' ORDER BY id)) m FROM pay_run t WHERE id = :i AND company_id = :c", i=fin["id"], c=str(cid)))[0]["m"]
        res: dict[str, str] = {}
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(cid))
            for label, (sql, params) in attempts.items():
                try:
                    r = await session.execute(text(sql), params)
                    res[label] = f"ALLOWED rows={r.rowcount}"
                except Exception as exc:  # noqa: BLE001
                    res[label] = "denied: " + str(exc).splitlines()[0][-120:]
                await session.rollback()
                await set_rls_company_id(session, str(cid))
            # a DRAFT run is NOT protected (normal lifecycle)
            r = await session.execute(text("UPDATE pay_run SET pay_date = pay_date WHERE id = :i"), {"i": draft_run["id"]})
            res["UPDATE pay_run (DRAFT, no-op)"] = f"allowed rows={r.rowcount}"
            await session.rollback()
        fingerprint_after = (await q("SELECT md5(string_agg(t::text, '|' ORDER BY id)) m FROM pay_run t WHERE id = :i AND company_id = :c", i=fin["id"], c=str(cid)))[0]["m"]
        rec(c, "mutation attempts as hrms_app against FINALISED rows (each rolled back)", db_role=who, results=res, fingerprint_unchanged=fingerprint_before == fingerprint_after)
        assert all(v.startswith("denied") for k, v in res.items() if "DRAFT" not in k), res
        assert fingerprint_before == fingerprint_after
        # also paid + adjustment (applied corrections) immutability for a PAID run
        paid = (await act(client, approver, fin["id"], "mark-paid", fin["version"])).json()["data"]
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(cid))
            try:
                await session.execute(text("UPDATE pay_run SET status = 'FINALISED' WHERE id = :i"), {"i": fin["id"]})
                res["UPDATE PAID run"] = "ALLOWED"
            except Exception as exc:  # noqa: BLE001
                res["UPDATE PAID run"] = "denied: " + str(exc).splitlines()[0][-100:]
            await session.rollback()
        assert res["UPDATE PAID run"].startswith("denied") and paid["status"] == "PAID"
        # through the API (as hrms_app): every mutation of the finalised run is refused with 409
        api = {
            "patch pay date": (await client.patch(f"{BASE}/{fin['id']}", headers=hdr(h, paid["version"]), json={"pay_date": "2026-10-20"})).status_code,
            "rollback": (await act(client, h, fin["id"], "rollback", paid["version"], {"to_status": "DRAFT", "reason": "x"})).status_code,
            "delete": (await client.delete(f"{BASE}/{fin['id']}", headers=h)).status_code,
            "recompute": (await act(client, h, fin["id"], "compute", paid["version"])).status_code,
            "re-lock": (await act(client, h, fin["id"], "lock-inputs", paid["version"])).status_code,
        }
        rec(c, "API mutations of a PAID run (runtime role)", results=api)
        assert all(v == 409 for v in api.values()), api
        # owner is exempt by design (tenant erasure); observation only
    finally:
        await switch_role(monkeypatch, "owner")
        await _cleanup_pay_runs(company_id=cid)
        await _cleanup(company_id=cid, user_id=uid)
        await _cleanup_scoped_users()


# =================================================================================== PAYROLL-ADJ-001
async def test_adj_001_adjustment_requires_key_and_is_replay_and_race_safe(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "PAYROLL-ADJ-001"
    h, cid, uid = await _register_tenant(client)
    try:
        le = await _legal_entity(client, h)
        e1 = await _employee(client, h, le, name="Ann")
        approver = await _approver(cid)
        fin = await finalised(client, h, approver, cid, le, "2026-09", {e1: "26"})
        draft = await _create_run(client, h, le, "2026-10")
        body = {"source_pay_run_id": fin["id"], "employee_id": e1, "paid_days_delta": "1", "reason": "QA correction"}
        n0 = lambda: q("SELECT count(*) n FROM pay_adjustment WHERE company_id = :c", c=str(cid))  # noqa: E731
        res: dict[str, Any] = {}
        # the suite's test client injects an Idempotency-Key automatically; call the base-class request to send NO header
        nokey = await AsyncClient.request(client, "POST", "/v1/payroll/adjustments", headers=h, json=body)
        short = await AsyncClient.request(client, "POST", "/v1/payroll/adjustments", headers={**h, "Idempotency-Key": "abc"}, json=body)
        res["no key / short key"] = [nokey.status_code, (nokey.json().get("error") or {}).get("code"), short.status_code]
        assert nokey.status_code in (400, 422) and short.status_code in (400, 422) and (await n0())[0]["n"] == 0
        k = "qa-adj-key-0001"
        first = await client.post("/v1/payroll/adjustments", headers={**h, "Idempotency-Key": k}, json=body)
        again = await client.post("/v1/payroll/adjustments", headers={**h, "Idempotency-Key": k}, json=body)
        changed = await client.post("/v1/payroll/adjustments", headers={**h, "Idempotency-Key": k}, json={**body, "paid_days_delta": "2"})
        res["first / replay / same key different body"] = [first.status_code, again.status_code, changed.status_code, (changed.json().get("error") or {}).get("code")]
        assert first.status_code == 201 and again.status_code in (200, 201) and again.json()["data"]["id"] == first.json()["data"]["id"] and changed.status_code == 409
        assert (await n0())[0]["n"] == 1
        # targets: a DRAFT run and an unknown run are refused; bounds
        to_draft = await client.post("/v1/payroll/adjustments", headers={**h, "Idempotency-Key": "qa-adj-key-0002"}, json={**body, "source_pay_run_id": draft["id"]})
        too_big = await client.post("/v1/payroll/adjustments", headers={**h, "Idempotency-Key": "qa-adj-key-0003"}, json={**body, "paid_days_delta": "9"})
        res["adjust a DRAFT run / exceed payable days"] = [to_draft.status_code, too_big.status_code]
        assert to_draft.status_code in (409, 422) and too_big.status_code in (409, 422) and (await n0())[0]["n"] == 1
        # 10 parallel deliveries with ONE key -> one row; 10 parallel DIFFERENT keys with delta 1 each against 4 days of headroom -> bound holds
        rs = await asyncio.gather(*[client.post("/v1/payroll/adjustments", headers={**h, "Idempotency-Key": "qa-adj-same-key"}, json=body) for _ in range(10)])
        res["10 parallel, same key"] = sorted(r.status_code for r in rs)
        assert len({r.json()["data"]["id"] for r in rs if r.status_code in (200, 201)}) == 1 and (await n0())[0]["n"] == 2
        rs = await asyncio.gather(*[client.post("/v1/payroll/adjustments", headers={**h, "Idempotency-Key": f"qa-adj-par-{i:04d}"}, json=body) for i in range(10)])
        total = (await q("SELECT COALESCE(sum(paid_days_delta),0)::text s FROM pay_adjustment WHERE company_id = :c", c=str(cid)))[0]["s"]
        res["10 parallel, different keys"] = {"statuses": sorted(r.status_code for r in rs), "sum_of_deltas_in_db": total}
        rec(c, "adjustments", results=res, payable_days_of_employee=30, paid_days_of_employee=26)
        # employee paid 26 of 30: headroom is 4 days in total; the sum of all deltas can never exceed it
        from decimal import Decimal

        assert Decimal(total) <= Decimal(4), f"corrections overshoot payable days: {total}"
        # withdraw a pending correction; unknown id; audit
        any_id = first.json()["data"]["id"]
        d = await client.delete(f"/v1/payroll/adjustments/{any_id}", headers=h)
        d2 = await client.delete(f"/v1/payroll/adjustments/{any_id}", headers=h)
        assert d.status_code == 204 and d2.status_code == 404
        acts = [r_["action"] for r_ in await q("SELECT action FROM audit_log WHERE company_id = :c AND action LIKE 'PAYROLL_PAY_ADJUSTMENT_%'", c=str(cid))]
        assert acts.count("PAYROLL_PAY_ADJUSTMENT_DELETED") == 1 and acts.count("PAYROLL_PAY_ADJUSTMENT_CREATED") == (await n0())[0]["n"] + 1
    finally:
        await _cleanup_pay_runs(company_id=cid)
        await _cleanup(company_id=cid, user_id=uid)
        await _cleanup_scoped_users()


# =================================================================================== PAYROLL-BANK-001
async def test_bank_001_bank_advice_access_and_csv_escaping(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "PAYROLL-BANK-001"
    h, cid, uid = await _register_tenant(client)
    try:
        le = await _legal_entity(client, h)
        e1 = await _employee(client, h, le, name='=HYPERLINK("http://x")', bank=True)
        e2 = await _employee(client, h, le, name='Comma, "Quote" Name')
        approver = await _approver(cid)
        hr, _ = await _create_permission_scoped_user(company_id=cid, permission_codes=["PAYROLL.RUN_VIEW", "PAYROLL.RUN_PROCESS"], data_scope="COMPANY")
        await _closed_period(company_id=cid, legal_entity_id=le, start="2026-09-01", end="2026-09-30", paid_days={e1: "30", e2: "30"}, days_in_month=30)
        run = await _create_run(client, h, le, "2026-09"); rid = run["id"]
        early = await client.get(f"{BASE}/{rid}/bank-advice", headers=h)
        res: dict[str, Any] = {"before finalise (admin)": [early.status_code, (early.json().get("error") or {}).get("code")]}
        assert early.status_code == 409
        run = (await act(client, h, rid, "lock-inputs", run["version"])).json()["data"]
        run = (await act(client, h, rid, "compute", run["version"])).json()["data"]
        run = (await act(client, approver, rid, "approve", run["version"])).json()["data"]
        approved = await client.get(f"{BASE}/{rid}/bank-advice", headers=h)
        res["while APPROVED (admin)"] = approved.status_code
        run = (await act(client, approver, rid, "finalise", run["version"])).json()["data"]
        n_audit0 = (await q("SELECT count(*) n FROM audit_log WHERE company_id = :c AND action = 'PAYROLL_BANK_ADVICE_DOWNLOADED'", c=str(cid)))[0]["n"]
        for label, hh in {"hr processor": hr, "approver": approver, "anonymous": {}}.items():
            r = await client.get(f"{BASE}/{rid}/bank-advice", headers=hh)
            res[label] = r.status_code
            assert r.status_code in (401, 403), (label, r.status_code)
        emp_id, emp_h = None, None
        ok = await client.get(f"{BASE}/{rid}/bank-advice", headers=h)
        res["company admin after FINALISED"] = ok.status_code
        assert ok.status_code == 200 and ok.headers["content-type"].startswith("text/csv") and "attachment" in ok.headers["content-disposition"] and ok.headers.get("cache-control") == "no-store"
        rows = list(csv.reader(io.StringIO(ok.text)))
        names = [r[1] for r in rows[1:]]
        res["csv"] = {"header": rows[0], "rows": len(rows) - 1, "names": names}
        assert rows[0][:2] == ["Employee code", "Employee name"] and len(rows) == 3 and len(rows[1]) == len(rows[0])
        # the comma/quote name round-trips as ONE field (csv-escaped); formula-leading name handling is recorded
        assert 'Comma, "Quote" Name' in names
        formula_cell = next(n for n in names if "HYPERLINK" in n)
        res["formula-leading name stored as"] = formula_cell
        assert not formula_cell.startswith("="), f"spreadsheet formula injection: a cell starts with '=': {formula_cell!r}"
        n_audit1 = (await q("SELECT count(*) n FROM audit_log WHERE company_id = :c AND action = 'PAYROLL_BANK_ADVICE_DOWNLOADED'", c=str(cid)))[0]["n"]
        aud = (await q("SELECT after_json::text a FROM audit_log WHERE company_id = :c AND action = 'PAYROLL_BANK_ADVICE_DOWNLOADED' ORDER BY occurred_at DESC LIMIT 1", c=str(cid)))
        res["audit rows for downloads (denied downloads add none)"] = [n_audit0, n_audit1]
        rec(c, "bank advice", results=res, audit_payload=aud)
        assert n_audit1 == n_audit0 + 1 and "123456789012" not in aud[0]["a"]
    finally:
        await _cleanup_pay_runs(company_id=cid)
        await _cleanup(company_id=cid, user_id=uid)
        await _cleanup_scoped_users()


# =================================================================================== PAYROLL-AUTHZ-001 roles x endpoints, tenancy (runtime role)
async def invited(client: AsyncClient, admin: dict[str, str], cid: Any, role: str) -> dict[str, str]:
    email = f"{role.lower()}-{uuid4().hex[:8]}@example.com"
    inv = await client.post("/v1/users/invite", headers=admin, json={"email": email, "role_code": role})
    assert inv.status_code in (200, 201), inv.text
    token = _token_from_invite_url(inv.json()["data"]["invite_url"])
    acc = await client.post(f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD})
    assert acc.status_code == 201, acc.text
    return {"Authorization": f"Bearer {acc.json()['data']['access_token']}", "X-Company-Id": str(cid)}


async def test_authz_001_roles_endpoints_and_tenant_isolation_as_runtime_role(client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch) -> None:
    c = "PAYROLL-AUTHZ-001"
    a = await _att_tenant(client)
    b = await _att_tenant(client)
    try:
        cid, bcid = a.company_id, b.company_id
        le, ble = a.legal_entity_id, b.legal_entity_id
        emp_id, emp_h = await _employee_user(client, a, "Esha")
        await payroll_profile(client, a.admin, emp_id)
        approver = await _approver(cid)
        view_only, _ = await _create_permission_scoped_user(company_id=cid, permission_codes=["PAYROLL.RUN_VIEW"], data_scope="COMPANY")
        proc_only, _ = await _create_permission_scoped_user(company_id=cid, permission_codes=["PAYROLL.RUN_VIEW", "PAYROLL.RUN_PROCESS"], data_scope="COMPANY")
        hr = await invited(client, a.admin, cid, "HR_ADMIN")
        mgr = await invited(client, a.admin, cid, "REPORTING_MANAGER")
        grants = await q("SELECT r.code role, array_agg(p.code ORDER BY p.code) codes FROM role r JOIN role_permission rp ON rp.role_id = r.id JOIN permission p ON p.id = rp.permission_id "
                         "WHERE r.company_id = :c AND r.code IN ('COMPANY_ADMIN','HR_ADMIN','REPORTING_MANAGER','EMPLOYEE') AND p.code LIKE 'PAYROLL.%' GROUP BY r.code", c=str(cid))
        rec(c, "payroll grants of the system roles (DB)", grants={g["role"]: g["codes"] for g in grants})
        await _closed_period(company_id=cid, legal_entity_id=le, start="2026-09-01", end="2026-09-30", paid_days={emp_id: "30"}, days_in_month=30)
        # a run in each interesting state for tenant A, built as the owner role (setup)
        draft = await _create_run(client, a.admin, le, "2026-09")
        locked_run = draft
        r1 = await act(client, a.admin, draft["id"], "lock-inputs", draft["version"]); locked_run = r1.json()["data"]
        r2 = await act(client, a.admin, draft["id"], "compute", locked_run["version"]); computed = r2.json()["data"]
        await _closed_period(company_id=bcid, legal_entity_id=ble, start="2026-09-01", end="2026-09-30", paid_days={}, days_in_month=30)
        b_run = await _create_run(client, b.admin, ble, "2026-09")
        await switch_role(monkeypatch, "app")
        assert (await q("SELECT current_user u"))[0]["u"] == "hrms_app"
        rid, ver = computed["id"], computed["version"]
        principals = {"anonymous": {}, "EMPLOYEE (login)": emp_h, "REPORTING_MANAGER": mgr, "HR_ADMIN": hr, "custom RUN_VIEW": view_only, "custom RUN_VIEW+PROCESS": proc_only,
                      "custom RUN_VIEW+APPROVE": approver, "COMPANY_ADMIN": a.admin}
        # Non-mutating probes: a principal that IS permitted gets past the permission gate and is stopped later (stale If-Match 0, duplicate month,
        # wrong status) with 409/422; a principal that is NOT permitted gets 403 (401 anonymous).  So "permitted" == not in (401, 403).
        probes = [  # (label, method, path, body, needs If-Match)
            ("GET pay-runs", "GET", BASE, None, False), ("GET pay-run", "GET", f"{BASE}/{rid}", None, False), ("GET pay-run employees", "GET", f"{BASE}/{rid}/employees", None, False),
            ("GET one employee's pay", "GET", f"{BASE}/{rid}/employees/{emp_id}", None, False), ("GET payslip (admin)", "GET", f"{BASE}/{rid}/employees/{emp_id}/payslip", None, False),
            ("POST create run", "POST", BASE, {"legal_entity_id": le, "month": "2026-09"}, False), ("PATCH pay date", "PATCH", f"{BASE}/{rid}", {"pay_date": "2026-10-09"}, True),
            ("POST lock-inputs", "POST", f"{BASE}/{rid}/lock-inputs", {}, True), ("POST compute", "POST", f"{BASE}/{rid}/compute", {}, True), ("POST approve", "POST", f"{BASE}/{rid}/approve", {}, True),
            ("POST finalise", "POST", f"{BASE}/{rid}/finalise", {}, True), ("POST mark-paid", "POST", f"{BASE}/{rid}/mark-paid", {}, True),
            ("POST rollback", "POST", f"{BASE}/{rid}/rollback", {"to_status": "DRAFT", "reason": "probe"}, True), ("DELETE run", "DELETE", f"{BASE}/{rid}", None, False),
            ("POST acknowledge variance", "POST", f"{BASE}/{rid}/employees/{emp_id}/acknowledge-variance", {"reason": "probe"}, False),
            ("GET bank advice", "GET", f"{BASE}/{rid}/bank-advice", None, False), ("GET adjustments", "GET", "/v1/payroll/adjustments", None, False),
            ("GET my payslips", "GET", "/v1/me/payslips", None, False), ("GET settings", "GET", "/v1/payroll/settings", None, False), ("GET statutory rates", "GET", "/v1/payroll/statutory-rates", None, False),
        ]
        snap = await state(cid, rid)
        counts_before = {t: (await q(f"SELECT count(*) n FROM {t} WHERE company_id = :c", c=str(cid)))[0]["n"] for t in ("pay_run", "pay_run_employee", "pay_run_line", "pay_adjustment")}
        matrix: dict[str, dict[str, int]] = {}
        for pname, ph in principals.items():
            matrix[pname] = {}
            for label, method, path, body, needs_im in probes:
                kw: dict[str, Any] = {"headers": {**ph, **({"If-Match": "0"} if needs_im else {})}}
                if body is not None:
                    kw["json"] = body
                r = await client.request(method, path, **kw)
                matrix[pname][label] = r.status_code
        snap_after = await state(cid, rid)
        counts_after = {t: (await q(f"SELECT count(*) n FROM {t} WHERE company_id = :c", c=str(cid)))[0]["n"] for t in ("pay_run", "pay_run_employee", "pay_run_line", "pay_adjustment")}
        rec(c, "role x endpoint matrix (hrms_app)", matrix=matrix, grants={g["role"]: g["codes"] for g in grants})
        # --- expectations from permissions.py: VIEW reads; PROCESS create/lock/compute/rollback/delete/patch/acknowledge; APPROVE approve/finalise/mark-paid; admin-only bank advice
        reads = ["GET pay-runs", "GET pay-run", "GET pay-run employees", "GET one employee's pay", "GET payslip (admin)", "GET adjustments"]
        process = ["POST create run", "PATCH pay date", "POST lock-inputs", "POST compute", "POST rollback", "DELETE run", "POST acknowledge variance"]
        approve = ["POST approve", "POST finalise", "POST mark-paid"]
        permitted = lambda code: code not in (401, 403)  # noqa: E731
        assert all(v == 401 for v in matrix["anonymous"].values()), matrix["anonymous"]
        for p in ("EMPLOYEE (login)", "REPORTING_MANAGER"):
            bad = {k: v for k, v in matrix[p].items() if k != "GET my payslips" and v != 403}
            assert not bad, (p, bad)
        assert matrix["EMPLOYEE (login)"]["GET my payslips"] == 200
        v = matrix["custom RUN_VIEW"]
        assert all(permitted(v[k]) for k in reads) and all(v[k] == 403 for k in process + approve + ["GET bank advice"]), v
        v = matrix["custom RUN_VIEW+PROCESS"]
        assert all(permitted(v[k]) for k in reads + process) and all(v[k] == 403 for k in approve + ["GET bank advice"]), v
        v = matrix["custom RUN_VIEW+APPROVE"]
        assert all(permitted(v[k]) for k in reads + approve) and all(v[k] == 403 for k in process + ["GET bank advice"]), v
        hr_m = matrix["HR_ADMIN"]
        rec(c, "HR_ADMIN observed", matrix=hr_m)
        assert hr_m["GET bank advice"] == 403 and all(hr_m[k] == 403 for k in approve), "HR_ADMIN must not approve/finalise/pay or download the bank file (D9; BANK_ADVICE_DOWNLOAD is COMPANY_ADMIN only)"
        adm = matrix["COMPANY_ADMIN"]
        assert all(permitted(adm[k]) for k in reads + process + ["GET bank advice"]) and adm["POST approve"] == 403 and permitted(adm["POST finalise"]), adm   # admin computed the run -> maker-checker 403 on approve
        assert snap == snap_after and counts_before == counts_after, "denied requests changed payroll state"
        # --- tenant isolation: tenant B's admin against tenant A's run, every verb, non-mutating form
        iso = {}
        for label, method, path, body, needs_im in probes:
            if rid not in path:
                continue
            kw = {"headers": {**b.admin, **({"If-Match": "0"} if needs_im else {})}}
            if body is not None:
                kw["json"] = body
            iso[label] = (await client.request(method, path, **kw)).status_code
        iso_lists = (await client.get(BASE, headers=b.admin)).json()["data"]
        iso_adj = (await client.get("/v1/payroll/adjustments", headers=b.admin)).json()["data"]
        iso["B lists A's runs"] = len([x for x in iso_lists if x["id"] == rid])
        iso["B sees own run only"] = [x["id"] for x in iso_lists] == [b_run["id"]]
        a_view = await client.get(f"{BASE}/{b_run['id']}", headers=a.admin)
        iso["A reads B's run"] = a_view.status_code
        iso["B downloads A's bank advice"] = (await client.get(f"{BASE}/{rid}/bank-advice", headers=b.admin)).status_code
        iso["B reads A employee's pay"] = (await client.get(f"{BASE}/{rid}/employees/{emp_id}", headers=b.admin)).status_code
        iso["B reads A's payslip via /me"] = (await client.get(f"/v1/me/payslips/{rid}", headers=b.admin)).status_code
        rec(c, "tenant isolation (hrms_app)", results=iso, b_adjustments_visible=len(iso_adj))
        for k, v_ in iso.items():
            if type(v_) is int and k not in ("B lists A's runs",):
                assert v_ in (404,), (k, v_)
        assert iso["B lists A's runs"] == 0 and iso["B sees own run only"] is True
        assert await state(cid, rid) == snap and (await state(bcid, b_run["id"]))["status"] == "DRAFT"
    finally:
        await switch_role(monkeypatch, "owner")
        await drop_invites(a.company_id)
        await _cleanup_pay_runs(company_id=a.company_id)
        await _cleanup_pay_runs(company_id=b.company_id)
        await _att_teardown(a, b)
        await _cleanup_scoped_users()


# =================================================================================== interrupted operations / failed transitions leave nothing behind
async def test_flow_001_interrupted_operations_roll_back_and_can_be_retried(client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch) -> None:
    c = "PAYROLL-FLOW-001"
    from hrms.modules.payroll.repository import PayRunRepository

    h, cid, uid = await _register_tenant(client)
    try:
        le = await _legal_entity(client, h)
        e1 = await _employee(client, h, le, name="Ann")
        approver = await _approver(cid)
        await _closed_period(company_id=cid, legal_entity_id=le, start="2026-09-01", end="2026-09-30", paid_days={e1: "30"}, days_in_month=30)
        run = await _create_run(client, h, le, "2026-09"); rid = run["id"]
        res: dict[str, Any] = {}

        async def boom(*a: Any, **k: Any) -> Any:
            raise RuntimeError("simulated crash mid-operation")

        # 1. crash after the status flipped but while the employee snapshot rows are being written
        orig = PayRunRepository.insert_employees
        monkeypatch.setattr(PayRunRepository, "insert_employees", boom)
        before = await state(cid, rid)
        r = await act(client, h, rid, "lock-inputs", run["version"])
        after = await state(cid, rid)
        res["lock-inputs crashes while inserting snapshot rows"] = {"http": r.status_code, "state_unchanged": before == after, "status": after["status"]}
        assert r.status_code >= 500 and before == after and after["status"] == "DRAFT", (before, after)
        monkeypatch.setattr(PayRunRepository, "insert_employees", orig)
        run = (await act(client, h, rid, "lock-inputs", run["version"])).json()["data"]
        assert run["status"] == "INPUTS_LOCKED" and (await state(cid, rid))["employees"] == 1
        # 2. crash during compute while lines are written
        for name in ("replace_lines", "update_employee"):
            if hasattr(PayRunRepository, name):
                orig2 = getattr(PayRunRepository, name)
                monkeypatch.setattr(PayRunRepository, name, boom)
                snap = await state(cid, rid)
                r = await act(client, h, rid, "compute", run["version"])
                res[f"compute crashes in {name}"] = {"http": r.status_code, "state_unchanged": snap == await state(cid, rid)}
                assert r.status_code >= 500 and snap == await state(cid, rid), (name, snap, await state(cid, rid))
                monkeypatch.setattr(PayRunRepository, name, orig2)
        run2 = await act(client, h, rid, "compute", run["version"])
        assert run2.status_code == 200 and run2.json()["data"]["status"] == "COMPUTED"
        run = run2.json()["data"]
        # 3. crash while approving (audit write fails): the approval must not be half-applied
        from hrms.core.audit.service import AuditService  # noqa: WPS433

        orig_rec = AuditService.record
        async def failing_record(self: Any, *a: Any, **k: Any) -> Any:
            if k.get("action") == "PAYROLL_PAY_RUN_APPROVED":
                raise RuntimeError("simulated audit failure")
            return await orig_rec(self, *a, **k)
        monkeypatch.setattr(AuditService, "record", failing_record)
        snap = await state(cid, rid)
        r = await act(client, approver, rid, "approve", run["version"])
        res["approve with the audit write failing"] = {"http": r.status_code, "state_unchanged": snap == await state(cid, rid), "status": (await state(cid, rid))["status"]}
        monkeypatch.setattr(AuditService, "record", orig_rec)
        assert r.status_code >= 500 and snap == await state(cid, rid), "approve was applied without its audit record"
        ok = await act(client, approver, rid, "approve", run["version"])
        assert ok.status_code == 200
        rec(c, "interrupted operations", results=res)
    finally:
        monkeypatch.undo()
        await _cleanup_pay_runs(company_id=cid)
        await _cleanup(company_id=cid, user_id=uid)
        await _cleanup_scoped_users()


@pytest.mark.xfail(strict=True, reason="DEF-B5A-01: POST /payroll/pay-runs accepts a pay_date before the month ends, which PATCH refuses ('The pay date cannot be before the month ends')")
async def test_flow_001_create_accepts_a_pay_date_that_update_refuses(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    c = "PAYROLL-FLOW-001"
    h, cid, uid = await _register_tenant(client)
    try:
        le = await _legal_entity(client, h)
        r = await client.post(BASE, headers=h, json={"legal_entity_id": le, "month": "2026-09", "pay_date": "2026-09-10"})
        rows = (await q("SELECT pay_date::text pd, period_end::text pe FROM pay_run WHERE company_id = :c", c=str(cid)))
        run = r.json().get("data") or {}
        patch = None
        if r.status_code == 201:
            patch = (await client.patch(f"{BASE}/{run['id']}", headers=hdr(h, run["version"]), json={"pay_date": "2026-09-10"})).status_code
        rec(c, "pay_date before the month ends: create vs update", create=r.status_code, rows=rows, same_value_via_patch=patch)
        assert r.status_code in (409, 422), "create accepted a pay date earlier than the end of the pay month"
    finally:
        await _cleanup_pay_runs(company_id=cid)
        await _cleanup(company_id=cid, user_id=uid)
