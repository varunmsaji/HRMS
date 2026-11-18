"""R-2 (owner decision D-01b) - late / early mark credit: READ-ONLY impact dry run.

For every UNLOCKED attendance day that has a late or early mark, this runs the real, pure
calculation engine on the day's inputs and writes down what the day WOULD be today - without
storing anything:

  stored      what the day row says now (what payroll would read)
  corrected   the engine as it now stands: one combined mark-credit ceiling per policy version
  no_credit   the same engine with the ceiling forced to 0 (plain grace only)
  unscaled    the same engine with P-05 shift-length scaling switched off (R5: `r5_*` files); the
              difference between `unscaled` and `corrected` is exactly what P-05 changes

`corrected` against `stored` is the change a recalculation would make (it includes any other
engine change since the row was last calculated). `corrected` against `no_credit` isolates the days
whose result depends on beyond-grace mark credit at all, i.e. the ones the R-2 setting can move.

GUARANTEES (each one checked, not assumed)
  * Read only. Every company is processed inside a transaction that starts with
    `SET TRANSACTION READ ONLY`, which makes PostgreSQL refuse any write; the script never calls
    commit, and the transaction is rolled back.
  * Locked days are never calculated, listed as changing, or touched: the set of locked
    attendance_day rows is fingerprinted (count + md5 of every row) before and after the run and
    the script exits non-zero if the two differ.
  * No recalculation, no queue entry, no overtime or leave side effect: `evaluate_day` is the pure
    function; the only service call is the one that BUILDS its input.

Money: the report shows attendance fractions and days only. A rupee figure needs the payroll
divisor, which payroll owns and the owner has not yet confirmed (payroll divides by the days of the
month), so none is computed here.

Usage (from apps/api, as the schema owner so it can read every tenant; a disposable copy of the
data is the usual target):
  PYTHONPATH=src DATABASE_URL=postgresql://... python scripts/attendance_mark_credit_dry_run.py \
      --out-dir /tmp/r2_impact [--company-id UUID] [--date-from 2026-01-01] [--date-to 2026-12-31]
"""

import argparse
import asyncio
import csv
import os
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hrms.modules.attendance import calculation as calc

CANDIDATES = """
SELECT d.employee_id, d.attendance_date, d.attendance_status, d.paid_day_fraction,
       d.lop_fraction, d.engine_version, d.late_minutes, d.is_late
FROM attendance_day d
WHERE d.company_id = :cid AND NOT d.is_locked AND d.worked_minutes > 0
  AND (CAST(:all_days AS boolean) OR d.late_minutes > 0 OR d.early_departure_minutes > 0)
  AND (CAST(:d_from AS date) IS NULL OR d.attendance_date >= CAST(:d_from AS date))
  AND (CAST(:d_to AS date) IS NULL OR d.attendance_date <= CAST(:d_to AS date))
ORDER BY d.attendance_date, d.employee_id
"""
LOCKED_FINGERPRINT = (
    "SELECT count(*), coalesce(md5(string_agg(to_jsonb(d)::text, '|' ORDER BY d.id::text)), '') "
    "FROM attendance_day d WHERE d.is_locked"
)
COLUMNS = [
    "company_id",
    "employee_id",
    "attendance_date",
    "stored_status",
    "stored_paid",
    "corrected_status",
    "corrected_paid",
    "no_credit_status",
    "no_credit_paid",
    "unscaled_status",
    "unscaled_paid",
    "change_p05",
    "change_vs_stored",
    "depends_on_mark_credit",
    "ceiling",
    "qualifying_late",
    "qualifying_early",
    "beyond_grace_credit",
    "both_ends",
    "capped",
    "stored_engine_version",
    "stored_late_minutes",
    "corrected_late_minutes",
    "stored_is_late",
    "corrected_is_late",
    "worked_outside_shift",
    "error",
]


def _frac(value: Any) -> Decimal:
    return Decimal(str(value))


def _transition(before: str, after: str) -> str:
    return f"{before} -> {after}" if before != after else "unchanged"


async def _fingerprint(session_factory: async_sessionmaker[AsyncSession]) -> tuple[int, str]:
    async with session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        row = (await session.execute(text(LOCKED_FINGERPRINT))).one()
        await session.rollback()
    return int(row[0]), str(row[1])


async def _companies(
    session_factory: async_sessionmaker[AsyncSession], only: UUID | None
) -> list[UUID]:
    async with session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        rows = (
            await session.execute(
                text("SELECT DISTINCT company_id FROM attendance_day WHERE NOT is_locked")
            )
        ).all()
        await session.rollback()
    ids = sorted(UUID(str(r[0])) for r in rows)
    return [c for c in ids if only is None or c == only]


async def _company_rows(
    session_factory: async_sessionmaker[AsyncSession],
    company_id: UUID,
    d_from: date | None,
    d_to: date | None,
    limit: int | None,
    all_days: bool,
) -> list[dict[str, Any]]:
    from hrms.core.db.session import set_rls_company_id
    from hrms.modules.attendance.service import AttendanceDayService

    out: list[dict[str, Any]] = []
    async with session_factory() as session:
        # First statement of the transaction: from here PostgreSQL rejects every write.
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await set_rls_company_id(session, str(company_id))
        candidates = (
            await session.execute(
                text(CANDIDATES),
                {"cid": str(company_id), "d_from": d_from, "d_to": d_to, "all_days": all_days},
            )
        ).all()
        service = AttendanceDayService(session)
        for employee_id, day, status, paid, _lop, engine_version, late_min, is_late in candidates[
            :limit
        ]:
            row: dict[str, Any] = {
                "company_id": str(company_id),
                "employee_id": str(employee_id),
                "attendance_date": day.isoformat(),
                "stored_status": status,
                "stored_paid": str(paid),
                "stored_engine_version": engine_version,
                "stored_late_minutes": late_min,
                "stored_is_late": is_late,
                "error": "",
            }
            try:
                calc_input, *_ = await service._build_calculation_input(  # noqa: SLF001
                    company_id, employee_id, day
                )
                if calc_input.policy is None:
                    row["error"] = "no attendance policy resolved for this day"
                    out.append(row)
                    continue
                corrected = calc.evaluate_day(calc_input)
                no_credit = calc.evaluate_day(
                    replace(
                        calc_input, policy=replace(calc_input.policy, mark_credit_ceiling_minutes=0)
                    )
                )
                with patch.object(calc, "scale_hour_bands", lambda bands, _net: bands):
                    unscaled = calc.evaluate_day(calc_input)  # P-05 off: stored bands as they are
                credit = corrected.snapshot.get("grace_band_credit", {})
                qual = credit.get("qualifying_beyond_grace", {})
                row |= {
                    "corrected_status": corrected.attendance_status,
                    "corrected_paid": corrected.paid_day_fraction,
                    "no_credit_status": no_credit.attendance_status,
                    "no_credit_paid": no_credit.paid_day_fraction,
                    "unscaled_status": unscaled.attendance_status,
                    "unscaled_paid": unscaled.paid_day_fraction,
                    "change_p05": _transition(
                        unscaled.attendance_status, corrected.attendance_status
                    ),
                    "change_vs_stored": _transition(status, corrected.attendance_status),
                    "depends_on_mark_credit": (
                        corrected.attendance_status != no_credit.attendance_status
                        or corrected.paid_day_fraction != no_credit.paid_day_fraction
                    ),
                    "corrected_late_minutes": corrected.late_minutes,
                    "corrected_is_late": corrected.is_late,
                    "worked_outside_shift": "worked_outside_shift" in corrected.snapshot,
                    "ceiling": credit.get("ceiling", ""),
                    "qualifying_late": qual.get("in", ""),
                    "qualifying_early": qual.get("out", ""),
                    "beyond_grace_credit": credit.get("beyond_grace_credit", {}).get("total", ""),
                    "both_ends": bool(qual.get("in") and qual.get("out")),
                    "capped": credit.get("capped", ""),
                }
            except Exception as exc:  # noqa: BLE001 - one day's failure is reported, never hidden
                row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            out.append(row)
        await session.rollback()  # never commit
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _summarise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    per: dict[str, Counter[str]] = defaultdict(Counter)
    delta: dict[str, Decimal] = defaultdict(Decimal)
    p05_delta: dict[str, Decimal] = defaultdict(Decimal)
    for r in rows:
        company = r["company_id"]
        per[company]["days_examined"] += 1
        if r["error"]:
            per[company]["errors"] += 1
            continue
        if r["change_vs_stored"] != "unchanged":
            per[company][r["change_vs_stored"]] += 1
            per[company]["days_changed"] += 1
        if r["depends_on_mark_credit"]:
            per[company]["depends_on_mark_credit"] += 1
        if r["both_ends"]:
            per[company]["both_ends_days"] += 1
        delta[company] += _frac(r["corrected_paid"]) - _frac(r["stored_paid"])
        if r["change_p05"] != "unchanged":
            per[company]["p05: " + r["change_p05"]] += 1
            per[company]["p05_days_changed"] += 1
        p05_delta[company] += _frac(r["corrected_paid"]) - _frac(r["unscaled_paid"])
    return [
        {
            "company_id": c,
            **dict(counts),
            "paid_day_fraction_delta": str(delta[c]),
            "p05_paid_day_fraction_delta": str(p05_delta[c]),
        }
        for c, counts in sorted(per.items())
    ]


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--company-id", type=UUID)
    parser.add_argument("--date-from", type=date.fromisoformat)
    parser.add_argument("--date-to", type=date.fromisoformat)
    parser.add_argument("--limit-per-company", type=int)
    parser.add_argument(
        "--all-unlocked-days",
        action="store_true",
        help="examine every unlocked worked day, not only days with a late/early mark (R5)",
    )
    args = parser.parse_args(argv)

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is required (the schema owner, so every tenant is readable)")  # noqa: T201
        return 2
    url = url.replace("postgresql://", "postgresql+asyncpg://", 1).split("?")[0]
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    locked_before = await _fingerprint(factory)
    rows: list[dict[str, Any]] = []
    for company_id in await _companies(factory, args.company_id):
        rows += await _company_rows(
            factory,
            company_id,
            args.date_from,
            args.date_to,
            args.limit_per_company,
            args.all_unlocked_days,
        )
    locked_after = await _fingerprint(factory)
    await engine.dispose()

    _write_csv(args.out_dir / "r2_dry_run_days.csv", rows)
    ok = [r for r in rows if not r["error"]]
    _write_csv(
        args.out_dir / "r2_present_to_half_day.csv",
        [r for r in ok if (r["stored_status"], r["corrected_status"]) == ("PRESENT", "HALF_DAY")],
    )
    _write_csv(
        args.out_dir / "r2_half_day_to_present.csv",
        [r for r in ok if (r["stored_status"], r["corrected_status"]) == ("HALF_DAY", "PRESENT")],
    )
    _write_csv(
        args.out_dir / "r2_depends_on_mark_credit.csv",
        [r for r in ok if r["depends_on_mark_credit"]],
    )
    _write_csv(
        args.out_dir / "r5_p05_changes.csv", [r for r in ok if r["change_p05"] != "unchanged"]
    )
    summary = _summarise(rows)
    if summary:
        keys = sorted({k for s in summary for k in s})
        with (args.out_dir / "r2_dry_run_summary_by_company.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys)
            writer.writeheader()
            writer.writerows(summary)

    transitions = Counter(r["change_vs_stored"] for r in ok)
    print(f"days examined: {len(rows)}  (errors: {len(rows) - len(ok)})")  # noqa: T201
    for name, count in sorted(transitions.items()):
        print(f"  {name}: {count}")  # noqa: T201
    print("R5 (P-05 scaling) against the same engine without it:")  # noqa: T201
    for name, count in sorted(Counter(r["change_p05"] for r in ok).items()):
        print(f"  {name}: {count}")  # noqa: T201
    print(  # noqa: T201
        "days whose result depends on beyond-grace mark credit: "
        f"{sum(1 for r in ok if r['depends_on_mark_credit'])}"
    )
    print(f"locked rows before: {locked_before}")  # noqa: T201
    print(f"locked rows after : {locked_after}")  # noqa: T201
    if locked_before != locked_after:
        print("STOP-SHIP: locked attendance rows changed during the dry run")  # noqa: T201
        return 1
    print("locked rows unchanged (count and md5 identical)")  # noqa: T201
    print(f"files written to {args.out_dir}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
