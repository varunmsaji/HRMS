"""QA B7 (part 1) - background jobs, Beat schedule, retry/idempotency/scoping, real worker behaviour.

Catalogue ids: JOB-BEAT-001, JOB-LOOP-001, JOB-RETRY-001, JOB-IDEM-001, JOB-HEALTH-001 (normal path; outage path is in
test_b7_failure_phases.py).  Mounted read-only at /qa/b7 and run through entry.py (strict sandbox check first).
Evidence: $QA_ARTIFACTS/<case>.jsonl written BEFORE asserting; worker logs: $QA_ARTIFACTS/worker_<tag>.log.

Real Celery worker: started as a subprocess of the runner (same container, same loopback-only network namespace, same env =
private Redis db 15 as broker/backend), via entry.py so the strict isolation check runs for it too.  Beat is NOT started as a
process (it would fire tasks on the wall clock); the schedule is inspected and evaluated against a controlled clock.
Time control: leave tasks read `business_today` from hrms.modules.leave.tasks, patched in-process only.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from celery.result import AsyncResult
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from tests.integration.modules.employee_import.test_employee_import import _build_csv, _cleanup_employee_rows, _cleanup_org_structure
from tests.integration.modules.employee.test_employee_assignment import _setup_org_structure
from tests.integration.modules.leave.test_leave_accrual import (
    _create_employee,
    _create_employment,
    _create_leave_type,
    _create_legal_entity,
    _create_published_monthly_policy,
    _register_tenant,
    _teardown as _leave_teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.celery_app import celery_app, dispatch_per_company
from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio
ART = Path(os.environ.get("QA_ARTIFACTS", "/tmp/qa-artifacts"))
API_DIR = Path.cwd()


def rec(case: str, step: str, **observed: Any) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    with (ART / f"{case}.jsonl").open("a") as fh:
        fh.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "step": step, **observed}, default=str) + "\n")


async def q(sql: str, company_id: Any = None, **params: Any) -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        if company_id is not None:
            await set_rls_company_id(session, str(company_id))
        return [dict(r) for r in (await session.execute(text(sql), params)).mappings().all()]


def import_all_tasks() -> None:
    from entrypoints import worker  # noqa: F401  (registers every module's tasks, exactly as the real worker does)


# ====================================================================================== real worker helper
class Worker:
    def __init__(self, tag: str, **env: str) -> None:
        self.tag, self.env, self.proc = tag, env, None
        self.log = ART / f"worker_{tag}.log"

    def start(self) -> "Worker":
        ART.mkdir(parents=True, exist_ok=True)
        fh = self.log.open("ab")
        self.proc = subprocess.Popen(
            [sys.executable, "/qa/entry.py", "-m", "celery", "-A", "entrypoints.worker:app", "worker", f"--concurrency={self.env.pop('CONCURRENCY', '1')}", "--pool=prefork",
             "-Q", "default,reports_exports", "--loglevel=INFO", "-n", f"qa-{self.tag}@%h"],
            stdout=fh, stderr=subprocess.STDOUT, cwd=API_DIR, env={**os.environ, **self.env})
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"worker exited early rc={self.proc.returncode}: {self.log.read_text()[-800:]}")
            if celery_app.control.ping(timeout=1.0):
                return self
        raise RuntimeError("worker did not answer ping in 60 s")

    def children(self) -> list[int]:
        out = []
        for p in Path("/proc").iterdir():
            if p.name.isdigit():
                try:
                    if (p / "stat").read_text().rsplit(")", 1)[1].split()[1] == str(self.proc.pid):
                        out.append(int(p.name))
                except (OSError, IndexError):
                    pass
        return out

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(30)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def text(self) -> str:
        return self.log.read_text(errors="replace") if self.log.exists() else ""


@pytest.fixture
def worker_factory():
    made: list[Worker] = []

    def _make(tag: str, **env: str) -> Worker:
        w = Worker(tag, **env).start()
        made.append(w)
        return w

    yield _make
    for w in made:
        w.stop()


def purge_private_broker() -> int:
    """Remove messages left in the DISPOSABLE broker (db 15 of this run's own Redis) by earlier tests."""
    return int(celery_app.control.purge() or 0)


async def accrual_setup(client: AsyncClient, joining: str = "2025-01-01") -> dict[str, Any]:
    headers, company_id, user_id = await _register_tenant(client)
    emp = await _create_employee(client, headers)
    le = await _create_legal_entity(client, headers)
    await _create_employment(client, headers, employee_id=emp["id"], legal_entity_id=le["id"], joining_date=joining)
    lt = await _create_leave_type(client, headers)
    await _create_published_monthly_policy(client, headers, leave_type_id=lt["id"])
    return {"h": headers, "cid": company_id, "uid": user_id, "eid": emp["id"], "lt": lt["id"]}


async def teardown_t(t: dict[str, Any]) -> None:
    await pre_clean(t["cid"])
    await _leave_teardown(company_id=t["cid"])
    await _cleanup(company_id=t["cid"], user_id=t["uid"])


async def pre_clean(cid: Any) -> None:
    async with get_session_factory()() as session:
        for table in ("attendance_day", "leave_ledger", "leave_year_end_run", "employee_import_row_error", "employee_import_batch"):
            try:
                await session.execute(text(f"DELETE FROM {table} WHERE company_id = :c"), {"c": str(cid)})
                await session.commit()
            except Exception:  # noqa: BLE001 - table without company_id / already empty
                await session.rollback()


async def ledger_rows(cid: Any, entry: str | None = None) -> list[dict[str, Any]]:
    return await q("SELECT entry_type, amount::text a, effective_date::text d FROM leave_ledger WHERE company_id = :c AND (CAST(:t AS text) IS NULL OR entry_type = :t) ORDER BY created_at, id",
                   company_id=cid, c=str(cid), t=entry)



async def apply_task(task: Any, args: list[Any]) -> Any:
    """Run a task body eagerly (real code, real DB) in a worker thread: run_task() calls asyncio.run() and disposes the process-global
    engine, which must not happen on the test's own loop.  The engine is disposed on both sides so no connection crosses loops."""
    from hrms.core.db.session import dispose_engine
    await dispose_engine()
    try:
        return await asyncio.get_running_loop().run_in_executor(None, lambda: task.apply(args=args, throw=False))
    finally:
        await dispose_engine()


# ====================================================================================== JOB-BEAT-001
def test_job_beat_001_schedule_maps_to_registered_tasks() -> None:
    c = "JOB-BEAT-001"
    import_all_tasks()
    conf = celery_app.conf
    sched = dict(conf.beat_schedule)
    registered = sorted(n for n in celery_app.tasks if not n.startswith("celery."))
    queues = sorted(qq.name for qq in conf.task_queues)
    rows = {}
    for name, entry in sched.items():
        task = entry["task"]
        route = celery_app.amqp.router.route({}, task, (), {})
        rows[name] = {"task": task, "registered": task in celery_app.tasks, "queue": route["queue"].name, "schedule": str(entry["schedule"])}
    import_queue = celery_app.tasks["employee_import.process_batch"].queue
    rec(c, "schedule vs registry", timezone=conf.timezone, enable_utc=conf.enable_utc, serializers=[conf.task_serializer, conf.result_serializer, list(conf.accept_content)],
        queues=queues, entries=rows, registered_tasks=registered, import_route=import_queue)
    assert len(sched) == 10
    assert all(r["registered"] for r in rows.values()), [k for k, r in rows.items() if not r["registered"]]
    assert all(r["queue"] in queues for r in rows.values())
    assert import_queue == "reports_exports" and "reports_exports" in queues
    assert conf.timezone == "Asia/Kolkata" and conf.enable_utc is True
    assert conf.task_serializer == "json" and list(conf.accept_content) == ["json"]
    # registered tasks that are NOT scheduled (documented per-company workers / on-demand)
    scheduled = {e["task"] for e in sched.values()}
    unscheduled = sorted(set(registered) - scheduled)
    rec(c, "registered but not scheduled", tasks=unscheduled)


def test_job_beat_001_due_times_under_a_controlled_clock() -> None:
    """Evaluate each crontab entry against fixed instants in Asia/Kolkata (no wall clock, no Beat process)."""
    c = "JOB-BEAT-001"
    import_all_tasks()
    ist = ZoneInfo("Asia/Kolkata")

    def due(entry_name: str, now: datetime, last_run: datetime) -> bool:
        sch = celery_app.conf.beat_schedule[entry_name]["schedule"]
        sch = sch.__class__(**{k: getattr(sch, k) for k in ("minute", "hour", "day_of_week", "day_of_month", "month_of_year")}) if hasattr(sch, "minute") else sch
        sch.nowfun = lambda: now
        sch.app = celery_app
        return bool(sch.is_due(last_run).is_due)

    t = lambda h, m, s=0, d=26: datetime(2026, 10, d, h, m, s, tzinfo=ist)  # noqa: E731
    cases = {
        "leave-run-monthly-accrual": [(t(1, 0, 5), t(0, 59), True), (t(1, 0, 5), t(1, 0, 1), False), (t(9, 30), t(1, 0, 1), False)],
        "leave-run-year-end-sweep": [(t(2, 0, 5), t(1, 59), True), (t(1, 0, 5), t(0, 0), False)],
        "attendance-run-daily-calculation": [(t(9, 30, 5), t(9, 29), True), (t(9, 0), t(9, 0), False)],
        "attendance-run-incomplete-reminders": [(t(10, 0, 5), t(9, 59), True)],
        "employee-run-termination-access-sweep": [(t(13, 15, 5), t(13, 14), True), (t(13, 16), t(13, 15, 5), False)],
        "leave-run-comp-off-credit-sweep": [(t(7, 0, 5), t(6, 59), True)],
        "leave-run-comp-off-expiry-sweep": [(t(1, 30, 5), t(1, 29), True)],
        "attendance-run-face-cleanup": [(t(3, 15, 5), t(3, 14), True)],
    }
    seen = {}
    for name, checks in cases.items():
        res = [bool(due(name, now, last)) for now, last, _ in checks]
        seen[name] = {"expected": [e for *_, e in checks], "observed": res}
    # month / year transition: the daily accrual fires on 31 Dec and on 1 Jan alike (no month-end special casing)
    for name_, d in (("dec31", datetime(2026, 12, 31, 1, 0, 5, tzinfo=ist)), ("jan1", datetime(2027, 1, 1, 1, 0, 5, tzinfo=ist))):
        seen[f"leave-run-monthly-accrual @ {name_}"] = {"expected": [True], "observed": [bool(due("leave-run-monthly-accrual", d, d - timedelta(days=1, minutes=-1)))]}
    rec(c, "due-time evaluation (controlled clock, IST)", results=seen)
    for name, r in seen.items():
        assert r["expected"] == r["observed"], (name, r)


# ====================================================================================== JOB-RETRY-001
def _count_calls(monkeypatch: pytest.MonkeyPatch, module: str, attr: str, exc: Exception) -> list[int]:
    calls = [0]

    async def boom(*a: Any, **k: Any) -> int:
        calls[0] += 1
        raise exc

    monkeypatch.setattr(f"{module}.{attr}", boom)
    return calls


def test_job_retry_001_leave_tasks_retry_transient_db_errors_then_fail_logged(monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]) -> None:
    c = "JOB-RETRY-001"
    import_all_tasks()
    from hrms.modules.leave import tasks as lt

    cfg = {}
    for name in ("leave.accrue_company", "leave.credit_comp_off", "leave.sweep_comp_off_expiry", "leave.run_year_end_for_company", "leave.run_monthly_accrual",
                 "leave.run_comp_off_credit_sweep", "leave.run_comp_off_expiry_sweep", "leave.run_year_end_sweep",
                 "attendance.calculate_company", "attendance.run_daily_calculation", "employee.enforce_terminations_company", "employee.run_termination_access_sweep",
                 "employee_import.process_batch", "health.scheduler_heartbeat"):
        t = celery_app.tasks[name]
        cfg[name] = {"acks_late": bool(t.acks_late), "reject_on_worker_lost": bool(t.reject_on_worker_lost), "autoretry_for": [e.__name__ for e in (getattr(t, "autoretry_for", None) or ())],
                     "max_retries": t.max_retries, "soft_time_limit": t.soft_time_limit, "time_limit": t.time_limit}
    rec(c, "retry / ack configuration per task", config=cfg)
    for name in [n for n in cfg if n.startswith("leave.")]:
        assert cfg[name]["acks_late"] and cfg[name]["reject_on_worker_lost"] and cfg[name]["autoretry_for"] == ["OperationalError", "InterfaceError"] and cfg[name]["max_retries"] == 3, name

    cid = str(uuid4())
    transient = OperationalError("SELECT 1", {}, Exception("simulated connection loss"))
    calls = _count_calls(monkeypatch, "hrms.modules.leave.tasks", "_accrue_company_async", transient)
    res = lt.accrue_company.apply(args=[cid], throw=False)
    out = capfd.readouterr().out
    rec(c, "transient OperationalError (eager apply: backoff delays are not waited)", calls=calls[0], state=res.state, failed_event_logged="leave_task_failed" in out)
    assert calls[0] == 4, calls            # 1 attempt + max_retries=3
    assert res.state == "FAILURE" and "leave_task_failed" in out

    calls2 = _count_calls(monkeypatch, "hrms.modules.leave.tasks", "_accrue_company_async", ValueError("logic error"))
    res2 = lt.accrue_company.apply(args=[cid], throw=False)
    rec(c, "logic error is not retried", calls=calls2[0], state=res2.state)
    assert calls2[0] == 1 and res2.state == "FAILURE"

    # first attempt fails, second succeeds -> SUCCESS with the second result
    seq = {"n": 0}

    async def flaky(*a: Any, **k: Any) -> int:
        seq["n"] += 1
        if seq["n"] == 1:
            raise transient
        return 7

    monkeypatch.setattr("hrms.modules.leave.tasks._accrue_company_async", flaky)
    res3 = lt.accrue_company.apply(args=[cid], throw=False)
    rec(c, "recovers after one transient failure", attempts=seq["n"], state=res3.state, result=res3.result)
    assert res3.state == "SUCCESS" and res3.result == 7 and seq["n"] == 2

    # attendance / employee / import: no automatic retry (observation, documented for import)
    for name in ("attendance.calculate_company", "employee.enforce_terminations_company", "employee_import.process_batch"):
        assert cfg[name]["autoretry_for"] == [], name
    rec(c, "OBSERVATION", note="attendance.*, employee.* and employee_import.* tasks have no autoretry and no acks_late; a worker killed mid-run loses the task (see test_job_retry_001_worker_killed_...)")


def test_job_retry_001_fanout_isolates_one_failing_enqueue(capfd: pytest.CaptureFixture[str]) -> None:
    c = "JOB-RETRY-001"
    ids = [uuid4() for _ in range(5)]
    sent: list[str] = []

    class T:
        name = "qa.dummy"

        def delay(self, cid: str, *a: Any) -> None:
            if cid == str(ids[2]):
                raise ConnectionError("broker hiccup")
            sent.append(cid)

    n = dispatch_per_company(T(), ids)
    out = capfd.readouterr().out
    rec(c, "fan-out with one failing enqueue", queued=n, sent=len(sent), incomplete_logged="celery_fanout_incomplete" in out, dispatch_failed_logged="celery_task_dispatch_failed" in out)
    assert n == 4 and len(sent) == 4 and str(ids[2]) not in sent
    assert "celery_fanout_incomplete" in out and "celery_task_dispatch_failed" in out


async def test_job_retry_001_failed_task_leaves_no_partial_state_and_bad_inputs(client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch) -> None:
    c = "JOB-RETRY-001"
    import_all_tasks()
    from hrms.modules.leave import tasks as lt
    from hrms.modules.leave.service import LeaveAccrualService

    t = await accrual_setup(client)
    try:
        monkeypatch.setattr(lt, "business_today", lambda tz: date(2026, 3, 1))
        before = await ledger_rows(t["cid"])
        orig = LeaveAccrualService.run_for_company

        async def write_then_die(self: Any, company_id: Any, *, as_of: date) -> int:
            n = await orig(self, company_id, as_of=as_of)      # rows are written inside the open transaction ...
            assert n == 1
            raise RuntimeError("worker crashed after writing")  # ... and the task then fails

        monkeypatch.setattr(LeaveAccrualService, "run_for_company", write_then_die)
        res = (await apply_task(lt.accrue_company, [str(t["cid"])]))
        after = await ledger_rows(t["cid"])
        rec(c, "task fails after writing", state=res.state, ledger_before=len(before), ledger_after=len(after))
        assert res.state == "FAILURE" and len(after) == len(before), "partial ledger rows survived a failed task"
        monkeypatch.setattr(LeaveAccrualService, "run_for_company", orig)
        ok = (await apply_task(lt.accrue_company, [str(t["cid"])]))
        rows = await ledger_rows(t["cid"], "ACCRUAL")
        rec(c, "re-delivery after the failure succeeds exactly once", state=ok.state, result=ok.result, accrual_rows=rows)
        assert ok.state == "SUCCESS" and ok.result == 1 and len(rows) == 1

        # invalid / missing inputs
        bad = {}
        for label, args in (("not-a-uuid", ["not-a-uuid"]), ("missing argument", []), ("unknown company", [str(uuid4())]), ("None", [None])):
            r = await apply_task(lt.accrue_company, args)
            bad[label] = {"state": r.state, "error": type(r.result).__name__ if r.state == "FAILURE" else r.result}
        rec(c, "invalid inputs", results=bad)
        assert bad["not-a-uuid"]["state"] == "FAILURE" and bad["missing argument"]["state"] == "FAILURE" and bad["None"]["state"] == "FAILURE"
        assert len(await ledger_rows(t["cid"], "ACCRUAL")) == 1
    finally:
        await teardown_t(t)


# ====================================================================================== JOB-IDEM-001 / tenant scoping
async def test_job_idem_001_accrual_twice_parallel_and_tenant_scoping(client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch, worker_factory: Any) -> None:
    c = "JOB-IDEM-001"
    import_all_tasks()
    from hrms.modules.leave import tasks as lt

    a = await accrual_setup(client)
    b = await accrual_setup(client)
    try:
        clock = {"d": date(2026, 3, 1)}
        monkeypatch.setattr(lt, "business_today", lambda tz: clock["d"])
        r1 = (await apply_task(lt.accrue_company, [str(a["cid"])])).result
        r2 = (await apply_task(lt.accrue_company, [str(a["cid"])])).result
        la = await ledger_rows(a["cid"], "ACCRUAL")
        lb = await ledger_rows(b["cid"], "ACCRUAL")
        rec(c, "accrual run twice (as_of 2026-03-01 -> February cycle)", first=r1, second=r2, tenant_a_rows=la, tenant_b_rows=lb)
        assert (r1, r2) == (1, 0) and len(la) == 1 and la[0]["a"] == "1.50"
        assert lb == [], "accrual for tenant A wrote tenant B rows"

        # parallel deliveries: a real worker with 4 processes, real clock, window widened to 28 days so the run is eligible today
        purge_private_broker()
        w = worker_factory("idem", LEAVE_ACCRUAL_RUN_WINDOW_DAYS="28", CONCURRENCY="4")
        try:
            rs = [celery_app.send_task("leave.accrue_company", args=[str(a["cid"])]) for _ in range(6)]
            res = [r.get(timeout=90, propagate=False) for r in rs]
            states = [r.state for r in rs]
        finally:
            w.stop()
        la2 = await ledger_rows(a["cid"], "ACCRUAL")
        bal = (await q("SELECT COALESCE(SUM(amount),0)::text s FROM leave_ledger WHERE company_id = :c", company_id=a["cid"], c=str(a["cid"])))[0]["s"]
        rec(c, "6 parallel deliveries to a 4-process worker (real clock)", states=states, results=res, accrual_rows=len(la2), ledger_sum=bal)
        assert all(s == "SUCCESS" for s in states), states
        assert sum(int(x) for x in res) == 1 and len(la2) == 2 and Decimal_eq(bal, "3.00")
        clock["d"] = date(2026, 4, 1)

        # window boundary: day 5 runs, day 6 does not (leave_accrual_run_window_days=5), no data created
        clock["d"] = date(2026, 5, 6)
        none = (await apply_task(lt.accrue_company, [str(a["cid"])])).result
        clock["d"] = date(2026, 5, 5)
        edge = (await apply_task(lt.accrue_company, [str(a["cid"])])).result
        rec(c, "run-window boundary", day6=none, day5=edge)
        assert none == 0 and edge == 1
        # year transition: 1 Jan accrues the December cycle once
        clock["d"] = date(2027, 1, 1)
        jan = [(await apply_task(lt.accrue_company, [str(a["cid"])])).result for _ in range(2)]
        dec = [r for r in await ledger_rows(a["cid"], "ACCRUAL") if r["d"].startswith("2026-12")]
        rec(c, "year transition 2027-01-01", results=jan, december_rows=dec)
        assert jan == [1, 0] and len(dec) == 1
    finally:
        await teardown_t(a)
        await teardown_t(b)


def Decimal_eq(a: str, b: str) -> bool:
    from decimal import Decimal
    return Decimal(a) == Decimal(b)


async def test_job_idem_001_fanout_selects_only_eligible_companies(client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch) -> None:
    c = "JOB-IDEM-001"
    import_all_tasks()
    from hrms.modules.employee import tasks as et
    from hrms.modules.leave import tasks as lt

    ts = {s: await accrual_setup(client) for s in ("TRIAL", "ACTIVE", "SUSPENDED", "TERMINATED", "PENDING_APPROVAL", "REJECTED")}
    try:
        async with get_session_factory()() as session:
            for s, t in ts.items():
                await session.execute(text("UPDATE company SET status = :s WHERE id = :i"), {"s": s, "i": str(t["cid"])})
            await session.commit()
        picked: dict[str, set[str]] = {}
        for label, fan, target in (("leave.run_monthly_accrual", lt.run_monthly_accrual, lt.accrue_company), ("employee.run_termination_access_sweep", et.run_termination_access_sweep, et.enforce_terminations_company)):
            got: list[str] = []
            monkeypatch.setattr(target, "delay", lambda cid, *a, got=got: got.append(cid))
            n = (await apply_task(fan, [])).result
            picked[label] = set(got)
            assert n == len(got)
        mine = {s: str(t["cid"]) for s, t in ts.items()}
        rec(c, "fan-out eligibility", picked={k: sorted(s for s, cid in mine.items() if cid in v) for k, v in picked.items()})
        for label, got in picked.items():
            assert mine["TRIAL"] in got and mine["ACTIVE"] in got, label
            assert not any(mine[s] in got for s in ("SUSPENDED", "TERMINATED", "PENDING_APPROVAL", "REJECTED")), label
        # OBSERVATION: a per-company task invoked directly does not re-check the company status
        monkeypatch.setattr(lt, "business_today", lambda tz: date(2026, 3, 1))
        direct = (await apply_task(lt.accrue_company, [mine["SUSPENDED"]])).result
        rec(c, "OBSERVATION per-company task on a SUSPENDED company", result=direct)
    finally:
        for t in ts.values():
            await teardown_t(t)


# ====================================================================================== JOB-LOOP-001 / real worker
async def test_job_loop_001_real_worker_runs_tasks_of_different_modules_in_sequence(client: AsyncClient, seeded_plan_catalogue: None, worker_factory: Any) -> None:
    c = "JOB-LOOP-001"
    import_all_tasks()
    purge_private_broker()
    t = await accrual_setup(client)
    org = await _setup_org_structure(client, t["h"])
    w = worker_factory("loop", LEAVE_ACCRUAL_RUN_WINDOW_DAYS="28")
    try:
        cid = str(t["cid"])
        up = await client.post("/v1/employee-imports", headers=t["h"], files={"file": ("employees.csv", _build_csv(org), "text/csv")})
        assert up.status_code == 201, up.text
        batch_id = up.json()["data"]["id"]                       # the API dispatched employee_import.process_batch to the private broker
        jobs = {
            "leave.accrue_company": celery_app.send_task("leave.accrue_company", args=[cid]),
            "attendance.calculate_company": celery_app.send_task("attendance.calculate_company", args=[cid]),
            "employee.enforce_terminations_company": celery_app.send_task("employee.enforce_terminations_company", args=[cid]),
            "leave.credit_comp_off": celery_app.send_task("leave.credit_comp_off", args=[cid]),
            "leave.sweep_comp_off_expiry": celery_app.send_task("leave.sweep_comp_off_expiry", args=[cid]),
            "health.ping": celery_app.send_task("health.ping"),
            "leave.accrue_company (2nd)": celery_app.send_task("leave.accrue_company", args=[cid]),
        }
        out = {}
        for name, r in jobs.items():
            out[name] = {"result": r.get(timeout=90, propagate=False), "state": r.state}
        deadline = time.time() + 90
        status = None
        while time.time() < deadline:
            status = (await q("SELECT status, processed_rows, success_count, error_count FROM employee_import_batch WHERE id = :b", company_id=t["cid"], b=batch_id))[0]
            if status["status"] not in ("PENDING", "PROCESSING"):
                break
            await asyncio.sleep(1)
        log = w.text()
        accr = await ledger_rows(t["cid"], "ACCRUAL")
        rec(c, "single-process worker, consecutive tasks of different modules", results=out, import_batch=status, accrual_rows=accr,
            different_loop_in_log=("different loop" in log), tracebacks_in_log=log.count("Traceback"), worker_pid=w.proc.pid)
        assert all(v["state"] == "SUCCESS" for v in out.values()), out
        assert "different loop" not in log and "Traceback" not in log
        assert status["status"] == "COMPLETED_WITH_ERRORS" and (status["success_count"], status["error_count"]) == (2, 3)
        # the import (same queue pair) may add employees before the accrual runs, so the number of eligible employees is 1..3;
        # what must hold: one accrual row per employee, the first delivery reports exactly what was written, the second writes nothing
        assert out["leave.accrue_company"]["result"] == len(accr) >= 1 and out["leave.accrue_company (2nd)"]["result"] == 0
    finally:
        w.stop()
        await pre_clean(t["cid"])
        await _cleanup_employee_rows(company_id=t["cid"])
        await _cleanup_org_structure(company_id=t["cid"])
        await teardown_t(t)


async def test_job_retry_001_worker_killed_mid_task_leave_redelivered_attendance_lost(client: AsyncClient, seeded_plan_catalogue: None, worker_factory: Any) -> None:
    """Block the first query of a task with an ACCESS EXCLUSIVE lock held by the test, SIGKILL the worker's pool child while the
    task runs, release the lock, then see what the broker does.  Leave tasks are acks_late + reject_on_worker_lost; attendance is not."""
    c = "JOB-RETRY-001"
    import_all_tasks()
    purge_private_broker()
    t = await accrual_setup(client)
    w = worker_factory("kill", LEAVE_ACCRUAL_RUN_WINDOW_DAYS="28")
    outcome: dict[str, Any] = {}
    try:
        cid = str(t["cid"])
        for label, task_name in (("leave.accrue_company", "leave.accrue_company"), ("attendance.calculate_company", "attendance.calculate_company")):
            lock_conn = get_session_factory()()
            await lock_conn.execute(text("LOCK TABLE company IN ACCESS EXCLUSIVE MODE"))   # blocks the task's first read; released by rollback below
            r = celery_app.send_task(task_name, args=[cid])
            deadline = time.time() + 40
            while time.time() < deadline and r.state != "STARTED":
                await asyncio.sleep(0.5)
            started = r.state
            kids = w.children()
            for pid in kids:
                os.kill(pid, signal.SIGKILL)
            await asyncio.sleep(2)
            await lock_conn.rollback()
            await lock_conn.close()
            final = r.get(timeout=60, propagate=False) if label.startswith("leave") else None
            if label.startswith("attendance"):
                await asyncio.sleep(15)
                final = r.state
            outcome[label] = {"state_before_kill": started, "killed_children": len(kids), "final_state": r.state, "final_result": str(final)}
        accr = await ledger_rows(t["cid"], "ACCRUAL")
        rec(c, "worker pool child SIGKILLed while the task ran", outcome=outcome, accrual_rows=accr, worker_still_alive=w.proc.poll() is None,
            log_mentions_worker_lost="WorkerLostError" in w.text())
        assert outcome["leave.accrue_company"]["state_before_kill"] == "STARTED"
        assert outcome["leave.accrue_company"]["final_state"] == "SUCCESS", outcome            # acks_late + reject_on_worker_lost: redelivered and completed
        assert len(accr) == 1, "redelivery must credit exactly once"
        # attendance has no acks_late: whatever happens is recorded as an observation, not asserted
    finally:
        w.stop()
        await teardown_t(t)


# ====================================================================================== JOB-HEALTH-001 (normal path)
async def test_job_health_001_heartbeat_and_job_health_cli(client: AsyncClient, worker_factory: Any) -> None:
    c = "JOB-HEALTH-001"
    import_all_tasks()
    purge_private_broker()
    live = await client.get("/health/live")
    ready = await client.get("/health/ready")
    rec(c, "API probes (all dependencies up)", live=live.status_code, ready=ready.status_code, body=ready.text[:300])
    assert live.status_code == 200 and ready.status_code == 200
    w = worker_factory("health")
    r = celery_app.send_task("health.scheduler_heartbeat")
    assert r.get(timeout=60)
    cmd = [sys.executable, "/qa/entry.py", "-m", "hrms.ops.job_health"]
    ok = subprocess.run(cmd, capture_output=True, text=True, cwd=API_DIR, timeout=60)
    time.sleep(3)
    stale = subprocess.run(cmd, capture_output=True, text=True, cwd=API_DIR, timeout=60, env={**os.environ, "HRMS_HEARTBEAT_MAX_AGE_SECONDS": "1"})
    rec(c, "job_health CLI", fresh_exit=ok.returncode, fresh_out=ok.stdout[:600], stale_exit=stale.returncode, stale_out=stale.stdout[:600])
    assert ok.returncode == 0 and stale.returncode == 1
    w.stop()


async def test_job_retry_001_malformed_payloads_do_not_wedge_a_real_worker(client: AsyncClient, worker_factory: Any) -> None:
    c = "JOB-RETRY-001"
    import_all_tasks()
    purge_private_broker()
    w = worker_factory("malformed")
    unknown = celery_app.send_task("qa.no_such_task", args=[1, 2])
    bad_args = celery_app.send_task("leave.accrue_company", args=[{"not": "a string"}])
    too_many = celery_app.send_task("health.ping", args=[1, 2, 3])
    ok = celery_app.send_task("health.ping")
    res = ok.get(timeout=60)
    bad = bad_args.get(timeout=60, propagate=False)
    many = too_many.get(timeout=60, propagate=False)
    time.sleep(1)
    log = w.text()
    rec(c, "malformed payloads against a real worker", ping_after=res, bad_args_state=bad_args.state, bad_args_error=type(bad).__name__, too_many_args_state=too_many.state,
        too_many_error=type(many).__name__, unknown_task_state=unknown.state, unregistered_logged=("unregistered task" in log.lower() or "unknown task" in log.lower()),
        worker_alive=w.proc.poll() is None)
    assert res == "pong" and bad_args.state == "FAILURE" and too_many.state == "FAILURE" and w.proc.poll() is None
    assert "unregistered task" in log.lower() or "unknown task" in log.lower()
    w.stop()
