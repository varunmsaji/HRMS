"""Run the attendance engine over the days `seed_company_mock_breaks.sql` wrote break events for, so
the engine writes the break rows (and any excess-break flags). LOCAL DEV ONLY; the API must be up.

    .venv/bin/python scripts/seed_mock_breaks_recalc.py

Uses the same locally minted token and `calculate_days` as `seed_mock_payroll.py`. Safe to re-run:
recalculating a day with the same inputs gives the same result.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seed_mock_payroll import ADMIN_EMAIL, DSN, Api, calculate_days, log, token_for  # noqa: E402


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
                """SELECT DISTINCT be.employee_id, be.attendance_date
                   FROM attendance_break_event be
                   WHERE be.company_id = $1 AND be.meta ->> 'mock_breaks_seed' = 'true'""",
                company_id,
            )
        ]
        log(f"breaks: recalculating {len(days)} days")
        api = Api(await token_for(db, ADMIN_EMAIL, company_id))
        await calculate_days(api, days)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
