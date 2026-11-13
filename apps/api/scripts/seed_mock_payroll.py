"""Mock payroll history for the company behind varunmsaji@gmail.com (Varun Company), LOCAL DEV ONLY.

Everything that has a business rule goes through the running API (http://localhost:8000), so the
real attendance and payroll engines produce the numbers:

The pay history starts at the beginning of the financial year (April), so TDS projects the year
from real year-to-date figures.

  1. punches     - attendance periods created for any month that has none, the Aug/Sep "mock"
                   periods (closed without summaries) reopened; every employee-day from 2026-04-01
                   (or joining) to the day before the first punch of another seed is calculated by
                   the engine, mock punches (SQL, reference 'MOCK-SEED-PAYROLL') are written for the
                   days the ENGINE calls working (its weekly-off patterns, Mon-Sat shifts, holiday
                   calendars), and the days are calculated again;
  2. periods     - per month: days the earlier SQL seeds wrote by hand are recalculated, working
                   days with no punch at all get mock punches, seed punches on holidays are
                   removed, KEEP_INCOMPLETE days get their missing punch, pending corrections and
                   overtime are approved; then validate + finalize, freezing the summaries;
  3. salary      - per employee: statutory profile, bank account, CTC + structure from a template
                   (STANDARD / STANDARD_METRO / SENIOR), effective 2026-04-01 or the joining date;
                   statutory rates reviewed by HR and verified by the admin; PAN / UAN on file;
  4. pay runs    - Apr..Oct: created/locked/computed by the HR admin (DEMO-002, maker),
                   approved/finalised/marked paid by the company admin (checker).

  current        - (not in the default run) the open month: the engine re-decides weekends the
                   SQL seeds wrote and special working days, every day up to yesterday is
                   recalculated, and days whose seed punches miss the published roster are
                   re-punched. Run it after seed_company_mock_gap.sql, then
                   seed_company_mock_leave.sql.
                   The engine's cascade also recalculates today, and it leaves an open IN without a
                   first-in (the overview then says "not checked in"), so today's view is put back
                   the way the gap seed writes it.

Each phase skips what already exists, so the script can be re-run after a failure.

Run from apps/api with the API up:
    .venv/bin/python scripts/seed_mock_payroll.py
Access tokens are minted locally with the dev JWT secret for each user's latest live session.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import uuid
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import httpx

from hrms.core.auth.jwt import create_access_token

API = "http://localhost:8000/v1"
DSN = "postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev"
ADMIN_EMAIL = "varunmsaji@gmail.com"
HR_EMAIL = "meera.pillai.demo@example.com"
WINDOW_START = date(2026, 4, 1)
MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
SALARY_FROM = date(2026, 4, 1)
TZ = ZoneInfo("Asia/Kolkata")
REF = "MOCK-SEED-PAYROLL"

# code -> (annual CTC in rupees, template code). Managers on SENIOR, Mumbai on the metro template.
SALARY = {
    "DEMO-001": (3_200_000, "SENIOR"),
    "DEMO-002": (1_800_000, "SENIOR"),
    "DEMO-003": (2_000_000, "SENIOR"),
    "DEMO-004": (1_900_000, "SENIOR"),
    "DEMO-005": (1_700_000, "SENIOR"),
    "DEMO-006": (900_000, "STANDARD"),
    "DEMO-007": (2_200_000, "STANDARD"),
    "DEMO-008": (1_200_000, "STANDARD"),
    "DEMO-009": (1_100_000, "STANDARD"),
    "DEMO-010": (850_000, "STANDARD"),
    "DEMO-011": (540_000, "STANDARD"),
    "DEMO-012": (600_000, "STANDARD_METRO"),
    "DEMO-013": (720_000, "STANDARD_METRO"),
    "DEMO-014": (480_000, "STANDARD_METRO"),
    "DEMO-015": (420_000, "STANDARD_METRO"),
    "DEMO-016": (840_000, "STANDARD"),
    "DEMO-017": (390_000, "STANDARD"),
    "DEMO-018": (360_000, "STANDARD"),
    "DEMO-019": (240_000, "STANDARD"),
    "DEMO-020": (252_000, "STANDARD"),
}
OLD_REGIME: set[str] = set()  # TDS supports only the new regime
BANKS = [
    ("HDFC Bank", "HDFC0001234"),
    ("ICICI Bank", "ICIC0000456"),
    ("State Bank of India", "SBIN0007890"),
    ("Axis Bank", "UTIB0000321"),
]


def h(*parts: Any) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def log(msg: str) -> None:
    print(msg, flush=True)


class Api:
    def __init__(self, token: str) -> None:
        self.c = httpx.AsyncClient(
            base_url=API, timeout=120, headers={"Authorization": f"Bearer {token}"}
        )

    async def call(
        self,
        method: str,
        path: str,
        *,
        ok: tuple[int, ...] = (200, 201, 202, 204),
        version: int | None = None,
        **kw: Any,
    ) -> Any:
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        if version is not None:
            headers["If-Match"] = f'"{version}"'
        r = await self.c.request(method, path, headers=headers, **kw)
        if r.status_code not in ok:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:1500]}")
        return r.json().get("data") if r.content else None


async def token_for(db: asyncpg.Connection, email: str, company_id: uuid.UUID) -> str:
    row = await db.fetchrow(
        """SELECT u.id AS user_id, s.id AS session_id,
                  (SELECT e.id FROM employee e WHERE e.user_id = u.id AND e.company_id = $2
                   AND e.deleted_at IS NULL LIMIT 1) AS employee_id
           FROM "user" u JOIN session s ON s.user_id = u.id
           WHERE lower(u.email) = $1 AND s.revoked_at IS NULL AND s.expires_at > now()
           ORDER BY s.created_at DESC LIMIT 1""",
        email,
        company_id,
    )
    if row is None:
        sys.exit(f"{email} has no live session - sign in once in the app, then re-run")
    return create_access_token(
        user_id=row["user_id"],
        company_id=company_id,
        session_id=row["session_id"],
        employee_id=row["employee_id"],
        ttl_minutes=120,
    )


# ---- 1. punches ------------------------------------------------------------------------------
async def backfill_days(
    db: asyncpg.Connection, company_id: uuid.UUID
) -> list[tuple[uuid.UUID, date]]:
    """Every employee-day from WINDOW_START (or joining) up to the day before the employee's first
    punch from another seed - the stretch that had no attendance at all."""
    emps = await db.fetch(
        """SELECT e.id, em.joining_date,
                  (SELECT min((p.punch_time AT TIME ZONE 'Asia/Kolkata')::date) FROM punch p
                   WHERE p.employee_id = e.id AND p.reference IS DISTINCT FROM $2) AS first_other
           FROM employee e JOIN employment em ON em.employee_id = e.id AND em.deleted_at IS NULL
           WHERE e.company_id = $1 AND e.deleted_at IS NULL AND e.employee_code LIKE 'DEMO-%'
           ORDER BY e.employee_code""",
        company_id,
        REF,
    )
    days = []
    for e in emps:
        d, end = (
            max(WINDOW_START, e["joining_date"]),
            (e["first_other"] or date.today()) - timedelta(days=1),
        )
        while d <= end:
            days.append((e["id"], d))
            d += timedelta(days=1)
    return days


async def write_punches(
    db: asyncpg.Connection, company_id: uuid.UUID, days: list[tuple[uuid.UUID, date]]
) -> None:
    """Punches for the days the engine itself calculated as WORKING (so weekly-off patterns, Mon-Sat
    shifts and each calendar's holidays are the engine's, not guessed), skipping leave. Mostly on
    time; ~7% late, ~2% half days, ~3% absent (no punch; resolved to LOP when the period closes)."""
    wanted = set(days)
    rows_db = await db.fetch(
        """SELECT employee_id, attendance_date, scheduled_start, scheduled_end
           FROM attendance_day WHERE company_id = $1
             AND calendar_day_type IN ('WORKING', 'SPECIAL_WORKING')
             AND attendance_status <> 'LEAVE' AND scheduled_start IS NOT NULL
             AND attendance_date BETWEEN $2 AND $3""",
        company_id,
        WINDOW_START,
        max(d for _, d in days),
    )
    await db.execute(
        """DELETE FROM punch WHERE company_id = $1 AND reference = $2
           AND (punch_time AT TIME ZONE 'Asia/Kolkata')::date BETWEEN $3 AND $4""",
        company_id,
        REF,
        WINDOW_START,
        max(d for _, d in days) + timedelta(days=1),
    )
    rows = _punch_rows(
        company_id, [a for a in rows_db if (a["employee_id"], a["attendance_date"]) in wanted]
    )
    await db.executemany(
        """INSERT INTO punch (company_id, employee_id, punch_time, direction, source,
                              idempotency_key, reference)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        rows,
    )
    log(f"punches: {len(rows)} written for {len(rows_db)} working days")


def _punch_rows(company_id: uuid.UUID, day_rows: list[asyncpg.Record]) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for a in day_rows:
        emp, d = a["employee_id"], a["attendance_date"]
        r = h(emp, d) % 100
        if r < 3:
            continue
        s_in, s_out = a["scheduled_start"], a["scheduled_end"]
        if r < 10:
            t_in = s_in + timedelta(minutes=16 + r * 3)  # late
        else:
            t_in = s_in + timedelta(minutes=(r % 17) - 12)  # 12 min early .. 4 min late
        t_out = t_in + timedelta(minutes=270) if 10 <= r < 12 else s_out + timedelta(minutes=r % 26)
        src = "WEB" if r % 5 == 0 else "MOBILE"
        for direction, t in (("IN", t_in), ("OUT", t_out)):
            rows.append(
                (company_id, emp, t, direction, src, f"mock-payroll-{emp}-{d}-{direction}", REF)
            )
    return rows


# ---- 2. attendance ---------------------------------------------------------------------------
async def calculate_days(api: Api, days: list[tuple[uuid.UUID, date]]) -> None:
    # One employee's days run oldest first (late / break counters are cumulative within a month);
    # a few employees run side by side.
    by_emp: dict[uuid.UUID, list[date]] = {}
    for e, d in days:
        by_emp.setdefault(e, []).append(d)
    sem = asyncio.Semaphore(4)
    done = 0

    async def one_employee(emp: uuid.UUID, dates: list[date]) -> None:
        nonlocal done
        async with sem:
            for d in sorted(dates):
                for attempt in range(6):
                    try:
                        await api.call(
                            "POST",
                            "/attendance/days/calculate",
                            params={"employee_id": str(emp), "date": d.isoformat()},
                        )
                        break
                    except RuntimeError as exc:
                        if "-> 503" not in str(exc) or attempt == 5:
                            raise
                        await asyncio.sleep(1 + attempt)
                done += 1
                if done % 300 == 0:
                    log(f"  calculated {done}/{len(days)}")

    await asyncio.gather(*(one_employee(e, ds) for e, ds in by_emp.items()))
    log(f"attendance: calculated {len(days)} days")


# ---- 3. periods ------------------------------------------------------------------------------
async def _period(db: asyncpg.Connection, company_id: uuid.UUID, month: str) -> asyncpg.Record:
    p = await db.fetchrow(
        """SELECT ap.id, ap.status, ap.version,
                  (SELECT count(*) FROM attendance_period_summary s
                   WHERE s.attendance_period_id = ap.id) AS n
           FROM attendance_period ap WHERE ap.company_id = $1 AND ap.period_start = $2""",
        company_id,
        date.fromisoformat(month + "-01"),
    )
    if p is None:
        sys.exit(f"no attendance period for {month}")
    return p


async def reopen_empty_periods(api: Api, db: asyncpg.Connection, company_id: uuid.UUID) -> None:
    """Months with no period get one (opened through the API); the Aug/Sep mock periods were
    closed with no summaries: reopen so their days can be calculated."""
    le = await db.fetchval(
        "SELECT id FROM legal_entity WHERE company_id = $1 ORDER BY created_at LIMIT 1", company_id
    )
    for month in MONTHS:
        exists = await db.fetchval(
            "SELECT 1 FROM attendance_period WHERE company_id = $1 AND period_start = $2",
            company_id,
            date.fromisoformat(month + "-01"),
        )
        if not exists:
            await api.call(
                "POST", "/attendance-periods", json={"legal_entity_id": str(le), "month": month}
            )
            log(f"period {month}: opened")
        p = await _period(db, company_id, month)
        if p["status"] == "CLOSED" and p["n"] == 0:
            await api.call(
                "POST",
                f"/attendance-periods/{p['id']}/reopen",
                version=p["version"],
                json={
                    "reason": "Mock period was closed without attendance; "
                    "reopened to load attendance for payroll"
                },
            )
            log(f"period {month}: reopened")


async def fix_keep_incomplete(
    api: Api, db: asyncpg.Connection, company_id: uuid.UUID, month: str
) -> None:
    """Days still INCOMPLETE under a KEEP_INCOMPLETE policy block the close. Do what HR would after
    checking with the employee: add the forgotten punch(es) at the shift times, then recalculate."""
    start = date.fromisoformat(month + "-01")
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    stuck = await db.fetch(
        """SELECT ad.employee_id, ad.attendance_date, ad.scheduled_start, ad.scheduled_end,
                  ad.actual_first_in
           FROM attendance_day ad
           JOIN attendance_policy_version v ON v.id = ad.attendance_policy_version_id
           WHERE ad.company_id = $1 AND ad.attendance_date BETWEEN $2 AND $3
             AND ad.attendance_status = 'INCOMPLETE'
             AND v.incomplete_at_lock_behaviour = 'KEEP_INCOMPLETE'
             AND ad.scheduled_start IS NOT NULL""",
        company_id,
        start,
        end,
    )
    rows = []
    for s in stuck:
        emp, d = s["employee_id"], s["attendance_date"]
        if s["actual_first_in"] is None:
            rows.append(
                (
                    company_id,
                    emp,
                    s["scheduled_start"],
                    "IN",
                    "WEB",
                    f"mock-payroll-fix-{emp}-{d}-IN",
                    REF,
                )
            )
        rows.append(
            (
                company_id,
                emp,
                s["scheduled_end"],
                "OUT",
                "WEB",
                f"mock-payroll-fix-{emp}-{d}-OUT",
                REF,
            )
        )
    if rows:
        await db.executemany(
            """INSERT INTO punch (company_id, employee_id, punch_time, direction, source,
                                  idempotency_key, reference)
               VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT DO NOTHING""",
            rows,
        )
        await calculate_days(api, [(s["employee_id"], s["attendance_date"]) for s in stuck])
        log(f"period {month}: added missing punches for {len(stuck)} KEEP_INCOMPLETE day(s)")


async def prepare_month(
    api: Api, db: asyncpg.Connection, company_id: uuid.UUID, month: str
) -> None:
    """Get a month into a closable state the way HR would: days the earlier SQL seeds wrote by hand
    recalculated by the engine, working days with no punch at all given mock punches (the demo
    seed treated working Saturdays as weekends), seed punches on holidays removed (it ignored the
    holiday calendar), then missing punches added and pending corrections / overtime decided."""
    start = date.fromisoformat(month + "-01")
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    emps = await db.fetch(
        """SELECT e.id, em.joining_date FROM employee e
           JOIN employment em ON em.employee_id = e.id AND em.deleted_at IS NULL
           WHERE e.company_id = $1 AND e.deleted_at IS NULL AND em.joining_date <= $2""",
        company_id,
        end,
    )
    ours = set(await backfill_days(db, company_id))  # already calculated by phase 1
    days = [
        (e["id"], start + timedelta(days=i))
        for e in emps
        for i in range((end - start).days + 1)
        if start + timedelta(days=i) >= e["joining_date"]
        and (e["id"], start + timedelta(days=i)) not in ours
    ]
    if days:
        await calculate_days(api, days)
    bare = await db.fetch(
        """SELECT ad.employee_id, ad.attendance_date, ad.scheduled_start, ad.scheduled_end
           FROM attendance_day ad
           WHERE ad.company_id = $1 AND ad.attendance_date BETWEEN $2 AND $3
             AND ad.calendar_day_type IN ('WORKING', 'SPECIAL_WORKING')
             AND ad.attendance_status IN ('INCOMPLETE', 'ABSENT')
             AND ad.scheduled_start IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM punch p WHERE p.employee_id = ad.employee_id
                             AND p.punch_time BETWEEN ad.scheduled_start - interval '3 hours'
                                                  AND ad.scheduled_end + interval '3 hours')""",
        company_id,
        start,
        end,
    )
    if bare:
        rows = _punch_rows(company_id, list(bare))
        await db.executemany(
            """INSERT INTO punch (company_id, employee_id, punch_time, direction, source,
                                  idempotency_key, reference)
               VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT DO NOTHING""",
            rows,
        )
        await calculate_days(api, sorted({(b["employee_id"], b["attendance_date"]) for b in bare}))
        log(f"period {month}: punches for {len(bare)} working day(s) that had none")
    hol = await db.fetch(
        """DELETE FROM punch p USING attendance_day ad
           WHERE p.company_id = $1 AND p.reference = 'demo-seed' AND ad.employee_id = p.employee_id
             -- the holiday's own shift window, so a night shift's OUT from the evening before
             -- (which lands on the holiday's calendar date) is kept
             AND p.punch_time BETWEEN ad.scheduled_start - interval '3 hours'
                                  AND ad.scheduled_end + interval '3 hours'
             AND ad.calendar_day_type = 'HOLIDAY' AND ad.attendance_date BETWEEN $2 AND $3
           RETURNING ad.employee_id, ad.attendance_date""",
        company_id,
        start,
        end,
    )
    if hol:
        await calculate_days(api, sorted({(r["employee_id"], r["attendance_date"]) for r in hol}))
        log(
            f"period {month}: removed seed punches on {len({tuple(r) for r in hol})} holiday day(s)"
        )
    await fix_keep_incomplete(api, db, company_id, month)
    for r in await db.fetch(
        """SELECT id, version FROM attendance_regularization_request WHERE company_id = $1
               AND status = 'SUBMITTED' AND attendance_date BETWEEN $2 AND $3""",
        company_id,
        start,
        end,
    ):
        await api.call(
            "POST",
            f"/regularizations/{r['id']}/approve",
            version=r["version"],
            json={"reviewer_comment": "Verified with the reporting manager"},
        )
        log(f"period {month}: approved correction {r['id']}")
    for r in await db.fetch(
        """SELECT id, version FROM overtime_record WHERE company_id = $1
               AND status = 'PENDING' AND attendance_date BETWEEN $2 AND $3""",
        company_id,
        start,
        end,
    ):
        await api.call(
            "POST",
            f"/overtime/{r['id']}/approve",
            version=r["version"],
            json={"reviewer_comment": "Approved - month-end workload"},
        )
        log(f"period {month}: approved overtime {r['id']}")


async def close_periods(api: Api, db: asyncpg.Connection, company_id: uuid.UUID) -> None:
    for month in MONTHS:
        p = await _period(db, company_id, month)
        pid = str(p["id"])
        if p["status"] == "CLOSED":
            log(f"period {month}: already closed with {p['n']} summaries")
            continue
        await prepare_month(api, db, company_id, month)
        verdict = await api.call("POST", f"/attendance-periods/{pid}/validate")
        status = verdict.get("status") or verdict.get("validation_status")
        if status not in ("READY", None):
            log(f"period {month}: validate says {status}: {str(verdict)[:1500]}")
        cur = await api.call("GET", f"/attendance-periods/{pid}")
        out = await api.call("POST", f"/attendance-periods/{pid}/finalize", version=cur["version"])
        log(f"period {month}: {out['status']}")


async def fix_open_month_weekly_offs(
    api: Api, db: asyncpg.Connection, company_id: uuid.UUID
) -> None:
    """Phase `current`: the open month (up to yesterday) has days the SQL seeds hand-wrote as
    WEEKLY_OFF (they copied a Sat/Sun pattern). Let the engine recalculate exactly those days; where
    it says WORKING (Mon-Sat shifts, published rosters), add mock punches and recalculate again.
    Nothing else in the open month is touched, so pending items and today's state stay as seeded."""
    today = await db.fetchval("SELECT (now() AT TIME ZONE 'Asia/Kolkata')::date")
    start = today.replace(day=1)
    seeded_off = [
        (r["employee_id"], r["attendance_date"])
        for r in await db.fetch(
            """SELECT employee_id, attendance_date FROM attendance_day
           WHERE company_id = $1 AND attendance_date BETWEEN $2 AND $3 AND NOT is_locked
             AND ((calendar_day_type = 'WEEKLY_OFF' AND attendance_status = 'NOT_EXPECTED')
                  -- calendar exceptions (e.g. a worked Saturday): the SQL seeds never wrote these
                  OR calendar_day_type = 'SPECIAL_WORKING'
                  -- weekends seed_company_mock_gap.sql wrote by copying the week before, which
                  -- cannot know about rosters: always let the engine decide those
                  OR (extract(isodow FROM attendance_date) >= 6
                      AND computation_snapshot @> '{"mock_gap_seed": true}'))""",
            company_id,
            start,
            today - timedelta(days=1),
        )
    ]
    if not seeded_off:
        log("current: no weekly-off days to check")
        return
    await calculate_days(api, seeded_off)
    bare = await db.fetch(
        """SELECT ad.employee_id, ad.attendance_date, ad.scheduled_start, ad.scheduled_end
           FROM attendance_day ad
           WHERE ad.company_id = $1 AND ad.calendar_day_type IN ('WORKING', 'SPECIAL_WORKING')
             AND ad.attendance_status IN ('INCOMPLETE', 'ABSENT') AND ad.scheduled_start IS NOT NULL
             AND (ad.employee_id, ad.attendance_date) IN
                 (SELECT * FROM unnest($2::uuid[], $3::date[]))
             AND NOT EXISTS (SELECT 1 FROM punch p WHERE p.employee_id = ad.employee_id
                             AND p.punch_time BETWEEN ad.scheduled_start - interval '3 hours'
                                                  AND ad.scheduled_end + interval '3 hours')""",
        company_id,
        [e for e, _ in seeded_off],
        [d for _, d in seeded_off],
    )
    if bare:
        rows = _punch_rows(company_id, list(bare))
        await db.executemany(
            """INSERT INTO punch (company_id, employee_id, punch_time, direction, source,
                                  idempotency_key, reference)
               VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT DO NOTHING""",
            rows,
        )
        await calculate_days(api, sorted({(b["employee_id"], b["attendance_date"]) for b in bare}))
    log(
        f"current: {len(seeded_off)} weekly-off day(s) rechecked, {len(bare)} were working days "
        f"and got punches"
    )
    await realign_open_month_to_rosters(api, db, company_id, start, today)


async def realign_open_month_to_rosters(
    api: Api, db: asyncpg.Connection, company_id: uuid.UUID, start: date, today: date
) -> None:
    """The SQL seeds punched everyone at their assignment's shift; published rosters move some
    people (e.g. onto the Evening shift). Recalculate the open month with the engine, then for each
    working day whose seed punches sit outside the engine's scheduled window, replace them with
    punches aligned to that window (today: only what has happened by now). Days with no punch at
    all (deliberate no-shows) and days with a pending correction request are left as they are."""
    emps = await db.fetch(
        """SELECT e.id, em.joining_date FROM employee e
           JOIN employment em ON em.employee_id = e.id AND em.deleted_at IS NULL
           WHERE e.company_id = $1 AND e.deleted_at IS NULL AND em.joining_date <= $2""",
        company_id,
        today,
    )
    # Up to yesterday: today's punches come from the (roster-aware) gap seed.
    days = [
        (e["id"], start + timedelta(days=i))
        for e in emps
        for i in range((today - start).days)
        if start + timedelta(days=i) >= e["joining_date"]
    ]
    await calculate_days(api, days)
    await realign_days(api, db, company_id, start, today - timedelta(days=1))
    await restore_today_view(db, company_id)


async def restore_today_view(db: asyncpg.Connection, company_id: uuid.UUID) -> None:
    """Recalculating earlier days cascades into today, and the engine leaves an open IN (checked
    in, shift still running) without `actual_first_in`, which the overview reads as NOT_CHECKED_IN.
    Put today back the way seed_company_mock_gap.sql writes it, and hand the row back to that
    seed."""
    n = await db.execute(
        """WITH p AS (
             SELECT employee_id, min(punch_time) AS t_in FROM punch
             WHERE company_id = $1 AND direction = 'IN'
               AND (punch_time AT TIME ZONE 'Asia/Kolkata')::date
                   = (now() AT TIME ZONE 'Asia/Kolkata')::date
             GROUP BY 1)
           UPDATE attendance_day ad SET
             actual_first_in = p.t_in,
             late_minutes = greatest(
                 0, (extract(epoch FROM (p.t_in - ad.scheduled_start)) / 60)::int - 15
             ),
             is_late = (extract(epoch FROM (p.t_in - ad.scheduled_start)) / 60) > 15,
             missing_punch = false,
             computation_snapshot = coalesce(ad.computation_snapshot, '{}'::jsonb)
                 || '{"mock_gap_seed": true}'::jsonb
           FROM p
           WHERE ad.employee_id = p.employee_id AND ad.company_id = $1
             AND ad.attendance_date = (now() AT TIME ZONE 'Asia/Kolkata')::date
             AND ad.attendance_status = 'INCOMPLETE'
             AND NOT EXISTS (SELECT 1 FROM punch o WHERE o.employee_id = p.employee_id
                             AND o.direction = 'OUT' AND o.punch_time > p.t_in)""",
        company_id,
    )
    log(f"current: today's checked-in view restored ({n.split()[-1]} row(s))")


async def realign_days(
    api: Api, db: asyncpg.Connection, company_id: uuid.UUID, start: date, today: date
) -> None:
    off = await db.fetch(
        """SELECT ad.employee_id, ad.attendance_date, ad.scheduled_start, ad.scheduled_end
           FROM attendance_day ad
           WHERE ad.company_id = $1 AND ad.attendance_date BETWEEN $2 AND $3
             AND ad.calendar_day_type IN ('WORKING', 'SPECIAL_WORKING')
             AND ad.attendance_status IN ('INCOMPLETE', 'ABSENT') AND ad.scheduled_start IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM attendance_regularization_request q
                             WHERE q.attendance_day_id = ad.id AND q.status = 'SUBMITTED')
             -- no check-in anywhere near the rostered start, but seed punches on that date
             AND NOT EXISTS (SELECT 1 FROM punch p WHERE p.employee_id = ad.employee_id
                             AND p.direction = 'IN'
                             AND p.punch_time BETWEEN ad.scheduled_start - interval '3 hours'
                                                  AND ad.scheduled_start + interval '4 hours')
             AND EXISTS (SELECT 1 FROM punch p WHERE p.employee_id = ad.employee_id
                         AND p.reference IN ('demo-seed', 'MOCK-SEED-GAP')
                         AND (p.punch_time AT TIME ZONE ad.timezone)::date = ad.attendance_date)""",
        company_id,
        start,
        today,
    )
    if not off:
        log("current: every working day's punches already match the roster")
        return
    now = await db.fetchval("SELECT now()")
    for a in off:
        # the seed punches of that date, except one another day's shift claims (a night shift's OUT)
        await db.execute(
            """DELETE FROM punch p WHERE p.employee_id = $1
               AND p.reference IN ('demo-seed', 'MOCK-SEED-GAP')
               AND (p.punch_time AT TIME ZONE 'Asia/Kolkata')::date = $2
               AND NOT EXISTS (SELECT 1 FROM attendance_day x WHERE x.employee_id = p.employee_id
                               AND x.attendance_date <> $2 AND x.scheduled_start IS NOT NULL
                               AND p.punch_time BETWEEN x.scheduled_start - interval '3 hours'
                                                    AND x.scheduled_end + interval '3 hours')""",
            a["employee_id"],
            a["attendance_date"],
        )
    rows = [r for r in _punch_rows(company_id, list(off)) if r[2] <= now]  # today: only the past
    await db.executemany(
        """INSERT INTO punch (company_id, employee_id, punch_time, direction, source,
                              idempotency_key, reference)
           VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT DO NOTHING""",
        rows,
    )
    await calculate_days(api, sorted({(a["employee_id"], a["attendance_date"]) for a in off}))
    log(f"current: {len(off)} day(s) re-punched to match the published roster")


# ---- 4. salary, statutory, bank --------------------------------------------------------------
async def setup_salaries(api: Api, db: asyncpg.Connection, company_id: uuid.UUID) -> None:
    templates = {
        r["code"]: r["id"]
        for r in await db.fetch(
            """SELECT code, id FROM salary_structure WHERE company_id = $1 AND employee_id IS NULL
           AND deleted_at IS NULL""",
            company_id,
        )
    }
    non_earning = {
        str(r["id"])
        for r in await db.fetch(
            "SELECT id FROM salary_component WHERE company_id = $1 AND component_type <> 'EARNING'",
            company_id,
        )
    }
    lines: dict[str, list[dict[str, Any]]] = {}
    for code, sid in templates.items():
        s = await api.call("GET", f"/payroll/salary-structures/{sid}")
        ver = next(v for v in s["versions"] if v["status"] == "PUBLISHED")
        keep = (
            "salary_component_id",
            "calculation_type",
            "percentage",
            "amount_monthly_minor",
            "base_salary_component_id",
            "max_monthly_minor",
            "applies_when",
            "display_order",
        )
        # The SENIOR template carries EMPLOYER_ESI as % of gross, which the current validation
        # refuses (only an earning may be). Seniors are above the ESI ceiling, so it is dropped.
        lines[code] = [
            {k: ln.get(k) for k in keep if ln.get(k) is not None}
            for ln in ver["lines"]
            if not (
                ln["calculation_type"] == "PERCENTAGE_OF_GROSS"
                and ln["salary_component_id"] in non_earning
            )
        ]

    emps = await db.fetch(
        """SELECT e.id, e.employee_code, e.first_name, e.last_name, em.joining_date, b.state_code,
                  EXISTS (SELECT 1 FROM employee_salary s WHERE s.employee_id = e.id
                          AND s.deleted_at IS NULL) AS has_salary,
                  EXISTS (SELECT 1 FROM employee_statutory s
                          WHERE s.employee_id = e.id) AS has_stat,
                  EXISTS (SELECT 1 FROM employee_bank s WHERE s.employee_id = e.id
                          AND s.deleted_at IS NULL) AS has_bank
           FROM employee e
           JOIN employment em ON em.employee_id = e.id AND em.deleted_at IS NULL
           JOIN employee_assignment a ON a.employee_id = e.id AND a.effective_to IS NULL
           LEFT JOIN branch b ON b.id = a.branch_id
           WHERE e.company_id = $1 AND e.deleted_at IS NULL AND e.employee_code LIKE 'DEMO-%'
           ORDER BY e.employee_code""",
        company_id,
    )
    for e in emps:
        code, eid = e["employee_code"], str(e["id"])
        ctc, tpl = SALARY[code]
        frm = max(SALARY_FROM, e["joining_date"]).isoformat()
        n = int(code[-3:])
        esi = ctc / 12 <= 21_000 + 2_000  # gross stays under the ESI ceiling
        if not e["has_stat"]:
            await api.call(
                "POST",
                f"/employees/{eid}/statutory",
                json={
                    "effective_from": frm,
                    "is_pf_applicable": True,
                    "pf_number": f"KABNG00{43210 + n:05d}000{1000 + n}",
                    "is_esi_applicable": esi,
                    "esi_ip_number": f"{5300000000 + n * 7919}" if esi else None,
                    "pt_state_code": e["state_code"],
                    "is_lwf_applicable": e["state_code"] == "KA",
                    "tax_regime": "OLD" if code in OLD_REGIME else "NEW",
                    "revision_reason": "Statutory details captured at onboarding",
                },
            )
        if not e["has_bank"]:
            bank, ifsc = BANKS[n % len(BANKS)]
            await api.call(
                "POST",
                f"/employees/{eid}/bank",
                json={
                    "effective_from": frm,
                    "account_holder_name": f"{e['first_name']} {e['last_name']}",
                    "account_number_enc": f"{50100000000000 + h(code) % 10**9}",
                    "bank_name": bank,
                    "ifsc": ifsc,
                    "branch_name": "Main Branch",
                    "payment_mode": "BANK",
                },
            )
        if not e["has_salary"]:
            await api.call(
                "POST",
                f"/employees/{eid}/salary/setup",
                json={
                    "effective_from": frm,
                    "reason": "Annual compensation FY 2026-27",
                    "template_structure_id": str(templates[tpl]),
                    "lines": lines[tpl],
                    "annual_ctc_minor": ctc * 100,
                    "revision_type": "ANNUAL",
                },
            )
        log(f"salary: {code} CTC {ctc:,} on {tpl}")


# ---- 4b. compliance: rate sign-off, PAN/UAN, tax regime ---------------------------------------
async def compliance(hr: Api, admin: Api, db: asyncpg.Connection, company_id: uuid.UUID) -> None:
    # Maker-checker sign-off of the (mock) statutory rates: HR reviews and notes each rate through
    # the API (audited), the company admin verifies it. The rates were inserted by SQL with no
    # audit trail, which the verifier check rightly refuses on its own.
    for r in await db.fetch(
        """SELECT id, scheme, state_code, notes FROM statutory_rate
               WHERE company_id = $1 AND verified_at IS NULL AND effective_to IS NULL""",
        company_id,
    ):
        cur = await hr.call("GET", "/payroll/statutory-rates", params={"per_page": 100})
        row = next(x for x in cur if x["id"] == str(r["id"]))
        note = (r["notes"] or "").split(" | Reviewed")[
            0
        ] + " | Reviewed by HR against the published rates (mock data)"
        row = await hr.call(
            "PATCH",
            f"/payroll/statutory-rates/{r['id']}",
            version=row["version"],
            json={"notes": note[:2000]},
        )
        await admin.call(
            "POST", f"/payroll/statutory-rates/{r['id']}/verify", version=row["version"]
        )
        log(f"compliance: {r['scheme']} {r['state_code'] or ''} rate reviewed and verified")

    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for e in await db.fetch(
        """SELECT e.id, e.employee_code, e.last_name, e.version, e.pan_number_enc IS NULL AS no_pan,
                      e.uan_number IS NULL AS no_uan
               FROM employee e WHERE e.company_id = $1 AND e.deleted_at IS NULL
                 AND e.employee_code LIKE 'DEMO-%'""",
        company_id,
    ):
        if not (e["no_pan"] or e["no_uan"]):
            continue
        n = int(e["employee_code"][-3:])
        body: dict[str, Any] = {}
        if e["no_pan"]:  # invented, PAN-shaped: 4th letter P (individual), 5th the surname initial
            body["pan_number"] = (
                f"{letters[n % 26]}{letters[(n * 7) % 26]}{letters[(n * 3) % 26]}P"
                f"{e['last_name'][0].upper()}{4000 + n * 37:04d}{letters[(n * 11) % 26]}"
            )
        if e["no_uan"]:
            body["uan_number"] = f"{100900000000 + n * 104729}"
        await admin.call("PATCH", f"/employees/{e['id']}/identity", version=e["version"], json=body)
    log("compliance: PAN / UAN on file for every employee")
    # Everyone is created on the NEW regime (OLD_REGIME is empty): the TDS engine does not support
    # the old one, and the app allows only one regime switch per fiscal year.


# ---- 5. pay runs -----------------------------------------------------------------------------
async def run_payroll(hr: Api, admin: Api, db: asyncpg.Connection, company_id: uuid.UUID) -> None:
    le = await db.fetchval(
        "SELECT id FROM legal_entity WHERE company_id = $1 ORDER BY created_at LIMIT 1", company_id
    )
    for month in MONTHS:
        run = await db.fetchrow(
            """SELECT id FROM pay_run WHERE company_id = $1 AND legal_entity_id = $2
               AND to_char(period_start, 'YYYY-MM') = $3""",
            company_id,
            le,
            month,
        )
        if run is None:
            r = await hr.call(
                "POST", "/payroll/pay-runs", json={"legal_entity_id": str(le), "month": month}
            )
        else:
            r = await hr.call("GET", f"/payroll/pay-runs/{run['id']}")
        rid = r["id"]
        if r["status"] == "COMPUTED" and r["error_count"]:
            # Inputs (rates, statutory profiles, PAN) are snapshotted at lock: re-take the snapshot.
            r = await hr.call(
                "POST",
                f"/payroll/pay-runs/{rid}/rollback",
                version=r["version"],
                json={
                    "to_status": "DRAFT",
                    "reason": "Statutory rates verified and PAN captured; re-lock inputs",
                },
            )
        if r["status"] == "DRAFT":
            r = await hr.call("POST", f"/payroll/pay-runs/{rid}/lock-inputs", version=r["version"])
        if r["status"] == "INPUTS_LOCKED" or (r["status"] == "COMPUTED" and r["error_count"]):
            r = await hr.call("POST", f"/payroll/pay-runs/{rid}/compute", version=r["version"])
        if r["status"] == "COMPUTED":
            if r["variance_open_count"]:
                emps = await hr.call(
                    "GET", f"/payroll/pay-runs/{rid}/employees", params={"per_page": 100}
                )
                for pe in emps:
                    if pe["variance_flagged"] and not pe["variance_acknowledged_at"]:
                        await hr.call(
                            "POST",
                            f"/payroll/pay-runs/{rid}/employees/{pe['employee_id']}"
                            "/acknowledge-variance",
                            json={"reason": "Checked: change explained by LOP / joining date"},
                        )
                r = await hr.call("GET", f"/payroll/pay-runs/{rid}")
            if r["error_count"]:
                emps = await hr.call(
                    "GET", f"/payroll/pay-runs/{rid}/employees", params={"per_page": 100}
                )
                for pe in emps:
                    if pe["has_error"]:
                        log(f"  {pe['employee_code']}: {[i for i in pe['issues']]}")
                sys.exit(
                    f"pay run {month} has {r['error_count']} employee error(s); fix and re-run"
                )
            r = await admin.call("POST", f"/payroll/pay-runs/{rid}/approve", version=r["version"])
        if r["status"] == "APPROVED":
            r = await admin.call("POST", f"/payroll/pay-runs/{rid}/finalise", version=r["version"])
        if r["status"] == "FINALISED":
            r = await admin.call("POST", f"/payroll/pay-runs/{rid}/mark-paid", version=r["version"])
        log(
            f"pay run {month}: {r['status']}, {r['employee_count']} employees, "
            f"{r['warning_count']} with warnings"
        )


async def main() -> None:
    db = await asyncpg.connect(DSN)
    company_id = await db.fetchval(
        """SELECT uc.company_id FROM "user" u JOIN user_company uc ON uc.user_id = u.id
           WHERE lower(u.email) = $1""",
        ADMIN_EMAIL,
    )
    admin = Api(await token_for(db, ADMIN_EMAIL, company_id))
    hr = Api(await token_for(db, HR_EMAIL, company_id))
    phases = set(sys.argv[1:]) or {"punches", "periods", "salary", "payroll"}
    if "punches" in phases:
        days = await backfill_days(db, company_id)
        await reopen_empty_periods(admin, db, company_id)
        await calculate_days(admin, days)  # pass 1: the engine decides the day types
        await write_punches(db, company_id, days)
        await calculate_days(admin, days)  # pass 2: with the punches
    if "periods" in phases:
        await close_periods(admin, db, company_id)
    if "salary" in phases:
        await setup_salaries(admin, db, company_id)
        await compliance(hr, admin, db, company_id)
    if "current" in phases:
        await fix_open_month_weekly_offs(admin, db, company_id)
    if "compliance" in phases:
        await compliance(hr, admin, db, company_id)
    if "payroll" in phases:
        await run_payroll(hr, admin, db, company_id)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
