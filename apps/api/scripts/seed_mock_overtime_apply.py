"""Finish `seed_company_mock_overtime.sql`: recalculate the days whose punch-out it moved, so the
attendance ENGINE writes the overtime records, then decide the older ones through the API as a
reviewer would. LOCAL DEV ONLY; the API must be up.

    .venv/bin/python scripts/seed_mock_overtime_apply.py

Deterministic per record: of the records older than three days about half are approved in full, one
in six is approved for less than was detected, one in six is rejected with a reason, and the rest
stay pending; newer records always stay pending. Decisions alternate between the admin and the HR
user. Records that are not pending are left alone, so a re-run changes nothing.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seed_mock_payroll import (  # noqa: E402
    ADMIN_EMAIL,
    DSN,
    Api,
    calculate_days,
    h,
    log,
    token_for,
)

REJECT_REASONS = [
    "Not pre-approved by the reporting manager",
    "Hours are not supported by the work log",
    "Overtime was not requested for this task",
]


async def main() -> None:
    db = await asyncpg.connect(DSN)
    try:
        company_id = await db.fetchval(
            """SELECT uc.company_id FROM "user" u JOIN user_company uc ON uc.user_id = u.id
               WHERE lower(u.email) = $1""",
            ADMIN_EMAIL,
        )
        days = [
            (r["employee_id"], r["attendance_date"])
            for r in await db.fetch(
                """SELECT d.employee_id, d.attendance_date
                   FROM punch p JOIN attendance_day d
                     ON d.employee_id = p.employee_id AND d.company_id = p.company_id
                    AND (p.punch_time AT TIME ZONE d.timezone)::date = d.attendance_date
                   WHERE p.company_id = $1 AND p.raw_payload ? 'mock_overtime_seed'
                     AND NOT d.is_locked""",
                company_id,
            )
        ]
        log(f"overtime: recalculating {len(set(days))} days")
        admin = Api(await token_for(db, ADMIN_EMAIL, company_id))
        await calculate_days(admin, sorted(set(days)))

        cutoff = date.today() - timedelta(days=3)
        decided = {"approved": 0, "approved_less": 0, "rejected": 0, "left_pending": 0}
        apis: dict[str, Api | None] = {}

        async def api_for(email: str) -> Api | None:
            """A reviewer's own token, or None when that user has no live session to borrow."""
            if email not in apis:
                try:
                    apis[email] = Api(await token_for(db, email, company_id))
                except SystemExit:
                    apis[email] = None
            return apis[email]

        for r in await db.fetch(
            """SELECT id, version, minutes_detected FROM overtime_record
               WHERE company_id = $1 AND status = 'PENDING' AND attendance_date < $2
               ORDER BY attendance_date, id""",
            company_id,
            cutoff,
        ):
            roll = h("ot-decision", r["id"]) % 6
            if roll >= 4:
                decided["left_pending"] += 1
                continue
            if roll == 3:
                path, key = f"/overtime/{r['id']}/reject", "rejected"
                body = {"rejection_reason": REJECT_REASONS[h("why", r["id"]) % 3]}
            elif roll == 2 and r["minutes_detected"] > 30:
                less = max(15, r["minutes_detected"] // 2 // 15 * 15)
                path, key = f"/overtime/{r['id']}/approve", "approved_less"
                body = {
                    "reviewer_comment": "Approved for the hours worked on the task",
                    "minutes_approved": less,
                }
            else:
                path, key = f"/overtime/{r['id']}/approve", "approved"
                body = {"reviewer_comment": "Approved - project deadline"}
            done = False
            # A two-stage chain (manager, then HR) takes one decision per stage, each by the
            # person the record names for that stage.
            for _ in range(3):
                row = await db.fetchrow(
                    """SELECT o.status, o.version, o.approval_stage, u.email AS manager_email
                       FROM overtime_record o
                       LEFT JOIN employee m ON m.id = o.resolved_approver_manager_id
                       LEFT JOIN "user" u ON u.id = m.user_id
                       WHERE o.id = $1""",
                    r["id"],
                )
                if row["status"] != "PENDING":
                    done = True
                    break
                email = row["manager_email"] if row["approval_stage"] == "MANAGER" else None
                api = await api_for(email or ADMIN_EMAIL)
                if api is None:
                    break
                try:
                    await api.call("POST", path, version=row["version"], json=body)
                except RuntimeError as exc:
                    log(f"  left pending ({r['id']}): {str(exc)[:120]}")
                    break
            else:
                done = True
            decided[key if done else "left_pending"] += 1
        log(f"overtime decisions: {decided}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
