"""Mock shift-swap requests for the company behind varunmsaji@gmail.com (Varun Company), LOCAL DEV
ONLY, made through the running API (http://localhost:8000) so the roster, audit trail, notifications
and recalculation requests are exactly what the app writes:

    .venv/bin/python scripts/seed_mock_swaps.py

Eight requests for the published week 23-28 Nov, between two people of the same department who are
on different shifts that day: three left waiting (one still without the colleague's agreement),
three approved (the roster rows are really swapped) and two declined with a note. Nobody is in two
of these on the same day. If the week already has that many requests it does nothing, so a re-run
adds nothing.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seed_mock_payroll import ADMIN_EMAIL, DSN, Api, h, log, token_for  # noqa: E402

DATES = [date(2026, 11, 23) + timedelta(days=i) for i in range(6)]
#: (outcome, counterpart already agreed) for each request, in order.
PLAN = [
    ("PENDING", True),
    ("PENDING", True),
    ("PENDING", False),
    ("APPROVED", True),
    ("APPROVED", True),
    ("APPROVED", True),
    ("DECLINED", True),
    ("DECLINED", True),
]
REASONS = [
    "Family function in the evening; colleague agreed to cover.",
    "Doctor's appointment in the morning.",
    "Child's school event, would like the earlier shift.",
    "Travel plans, need the later shift that day.",
    "Exam preparation; swapping to get the evening free.",
    "Relative visiting from out of town.",
]
DECLINE_NOTES = [
    "Not enough cover on that shift that day.",
    "Another request for the same shift was approved first.",
]


async def main() -> None:
    db = await asyncpg.connect(DSN)
    try:
        company_id = await db.fetchval(
            """SELECT uc.company_id FROM "user" u JOIN user_company uc ON uc.user_id = u.id
               WHERE lower(u.email) = $1""",
            ADMIN_EMAIL,
        )
        api = Api(await token_for(db, ADMIN_EMAIL, company_id))
        existing = await db.fetchval(
            "SELECT count(*) FROM shift_swap_request WHERE company_id = $1 AND swap_date >= $2",
            company_id,
            DATES[0],
        )
        if existing >= len(PLAN):
            log(f"swaps: {existing} requests already cover this week, nothing to add")
            return
        busy: set[tuple[date, str]] = set()
        for r in await db.fetch(
            """SELECT swap_date, requester_employee_id::text a, counterpart_employee_id::text b
               FROM shift_swap_request WHERE company_id = $1 AND swap_date >= $2""",
            company_id,
            DATES[0],
        ):
            busy |= {(r["swap_date"], r["a"]), (r["swap_date"], r["b"])}

        made = {"PENDING": 0, "APPROVED": 0, "DECLINED": 0}
        for i, (outcome, agreed) in enumerate(PLAN):
            # Start from a date picked for this request and move on to the next one when there is
            # no pair on it or the app refuses the pairing.
            for k in range(len(DATES)):
                day = DATES[(i * 2 + h("swap-day", i) + k) % len(DATES)]
                rows = await db.fetch(
                    """SELECT r.employee_id::text AS emp, r.shift_id, a.department_id
                       FROM shift_roster r
                       JOIN employee_assignment a ON a.employee_id = r.employee_id
                            AND a.effective_to IS NULL AND a.deleted_at IS NULL
                       WHERE r.company_id = $1 AND r.roster_date = $2 AND r.status = 'PUBLISHED'
                         AND r.deleted_at IS NULL AND NOT r.is_week_off_override
                       ORDER BY md5(r.employee_id::text || $3)""",
                    company_id,
                    day,
                    f"swap{i}",
                )
                rows = [r for r in rows if (day, r["emp"]) not in busy]
                pair = next(
                    (
                        (a, b)
                        for a in rows
                        for b in rows
                        if a["emp"] != b["emp"]
                        and a["department_id"] == b["department_id"]
                        and a["shift_id"] != b["shift_id"]
                    ),
                    None,
                )
                if pair is None:
                    continue
                a, b = pair
                try:
                    created = await api.call(
                        "POST",
                        "/rosters/swap-requests",
                        json={
                            "requester_employee_id": a["emp"],
                            "counterpart_employee_id": b["emp"],
                            "swap_date": day.isoformat(),
                            "reason": REASONS[h("swap-why", i) % len(REASONS)],
                            "counterpart_consented": agreed,
                        },
                    )
                except RuntimeError as exc:
                    if "-> 409" not in str(exc):
                        raise
                    busy |= {(day, a["emp"]), (day, b["emp"])}
                    continue
                busy |= {(day, a["emp"]), (day, b["emp"])}
                sid = created["id"]
                if outcome == "APPROVED":
                    await api.call(
                        "POST",
                        f"/rosters/swap-requests/{sid}/approve",
                        json={"note": "Approved - both shifts stay covered."},
                    )
                elif outcome == "DECLINED":
                    await api.call(
                        "POST",
                        f"/rosters/swap-requests/{sid}/decline",
                        json={"note": DECLINE_NOTES[made["DECLINED"] % len(DECLINE_NOTES)]},
                    )
                made[outcome] += 1
                log(f"swap {created.get('reference')}: {outcome} on {day}")
                break
            else:
                log(f"swap {i}: no usable pair this week, skipped")
        log(f"swap requests made: {made}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
