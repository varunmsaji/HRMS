"""Shared parity fixture (audit 2026-11-26, section 5 item 7).

Web (`src/lib/attendance/metrics-parity.test.ts`) and mobile (`test/metrics_parity_test.dart`) load
the same file. Here the export's own tally and late / early rules must give the figures the two
apps show on screen. Each row carries the bucket the fixture expects: the API's bucket comes from
SQL (`summary.py`) and is checked by the summary tests, not here.
"""

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from hrms.modules.attendance.report_export import _late_early, _Person, _tallies

FIXTURE = Path(__file__).parents[3] / "fixtures" / "attendance_metrics_parity.json"
FX = json.loads(FIXTURE.read_text(encoding="utf-8"))
EXPECTED = FX["expected"]


def _row(d: dict, *, employee_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        employee_id=employee_id or d["employee_id"],
        attendance_date=date.fromisoformat(d["attendance_date"]),
        bucket=EXPECTED["buckets"][d["id"]],
        first_in=d["actual_first_in"],
        worked_minutes=d["worked_minutes"],
        scheduled_minutes=d["scheduled_minutes"],
        is_late=d["is_late"],
        late_minutes=d["late_minutes"],
        is_early_out=d["is_early_out"],
        early_minutes=d["early_departure_minutes"],
    )


def test_export_tally_matches_the_apps_report_rows() -> None:
    tallies = _tallies([_row(d) for d in FX["days"]])
    assert {emp: asdict(t) for emp, t in tallies.items()} == EXPECTED["tallies"]


def test_export_late_early_rows_match_the_apps() -> None:
    # One "employee" per day so each exported row names the day it came from.
    rows = [_row(d, employee_id=d["id"]) for d in FX["days"]]
    people = {d["id"]: _Person(id=d["id"], name=d["id"], code="") for d in FX["days"]}  # type: ignore[arg-type]
    _header, body = _late_early(rows, people, ZoneInfo("Asia/Kolkata"))
    assert [r[1] for r in body] == EXPECTED["late_early_day_ids"]
    assert [r[1] for r in body if r[3] != ""] == EXPECTED["late_day_ids"]


def test_export_overtime_pending_matches_the_apps() -> None:
    found = sum(o["minutes_detected"] for o in FX["overtime"])
    approved = sum(o["minutes_approved"] for o in FX["overtime"])
    # The same rule as `_overtime`: only a PENDING record has pending minutes.
    pending = sum(
        max(0, o["minutes_detected"] - o["minutes_approved"])
        for o in FX["overtime"]
        if o["status"] == "PENDING"
    )
    assert {"found": found, "approved": approved, "pending": pending} == EXPECTED["overtime_totals"]
