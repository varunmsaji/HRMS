"""The display vocabulary (R-B02): one label per bucket, from the same rules as the dashboards."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from hrms.modules.attendance.day_classification import DISPLAY_TABLE, day_display

TABLE_FIXTURE = Path(__file__).parents[3] / "fixtures" / "day_display_table.json"
TZ = "Asia/Kolkata"
NOW = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)  # 13:30 on 20 Nov in Kolkata
TODAY = date(2026, 11, 20)


def _display(status: str, day_type: str | None = None, **kw):
    args = {
        "status": status,
        "calendar_day_type": day_type,
        "attendance_date": TODAY - timedelta(days=1),
        "has_punch": False,
        "scheduled_end": None,
        "timezone": TZ,
        "now": NOW,
    }
    args.update(kw)
    return day_display(**args)


def test_table_matches_the_committed_fixture_web_and_mobile_check() -> None:
    committed = json.loads(TABLE_FIXTURE.read_text(encoding="utf-8"))
    expected = {k: {"label": v[0], "tone": v[1], "glyph": v[2]} for k, v in DISPLAY_TABLE.items()}
    assert committed == expected


@pytest.mark.parametrize(
    ("status", "day_type", "code"),
    [
        ("NOT_EXPECTED", "HOLIDAY", "HOLIDAY"),  # never "Not expected" for a holiday
        ("NOT_EXPECTED", "WEEKLY_OFF", "WEEKLY_OFF"),
        ("NOT_EXPECTED", "WORKING", "NON_WORKING"),
        ("NOT_JOINED", None, "NOT_EMPLOYED"),
        ("EXITED", None, "NOT_EMPLOYED"),
        ("WFH", None, "REMOTE"),
        ("PRESENT", None, "PRESENT"),
        ("HALF_DAY", None, "HALF_DAY"),
        ("ABSENT", None, "ABSENT"),
        ("LEAVE", None, "LEAVE"),
        ("ON_DUTY", None, "ON_DUTY"),
        ("INCOMPLETE", None, "INCOMPLETE"),
        ("CONFIG_ERROR", None, "CONFIG_ERROR"),
        ("SOMETHING_NEW", None, "NON_WORKING"),
    ],
)
def test_past_day_code_label_and_not_provisional(status, day_type, code) -> None:
    d = _display(status, day_type)
    assert d["code"] == code
    assert d["label"] == DISPLAY_TABLE[code][0]
    assert d["provisional"] is False


def test_holiday_reads_holiday_not_not_expected() -> None:
    assert _display("NOT_EXPECTED", "HOLIDAY")["label"] == "Holiday"


def test_today_open_day_while_shift_runs_is_provisional() -> None:
    running = NOW + timedelta(hours=3)
    punched = _display("INCOMPLETE", attendance_date=TODAY, has_punch=True, scheduled_end=running)
    assert (punched["code"], punched["label"], punched["provisional"]) == (
        "PRESENT",
        "Working now",
        True,
    )
    silent = _display("ABSENT", attendance_date=TODAY, scheduled_end=running)
    assert (silent["code"], silent["label"], silent["provisional"]) == (
        "NOT_CHECKED_IN",
        "Not in yet",
        True,
    )


def test_today_open_day_after_shift_is_a_verdict() -> None:
    over = NOW - timedelta(hours=1)
    d = _display("ABSENT", attendance_date=TODAY, scheduled_end=over)
    assert (d["code"], d["provisional"]) == ("ABSENT", False)


def test_a_finished_day_today_is_never_provisional() -> None:
    d = _display(
        "PRESENT", attendance_date=TODAY, has_punch=True, scheduled_end=NOW + timedelta(hours=3)
    )
    assert (d["code"], d["provisional"]) == ("PRESENT", False)
