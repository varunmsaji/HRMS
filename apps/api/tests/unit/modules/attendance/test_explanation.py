"""R-C01 — the "why this result" explanation: one test per wording template.

`explain()` reads a stored day and the governing policy; these tests pass a plain namespace with
the day fields, so no database is involved. Thresholds quoted in the text must be the policy's
own values, and a verdict is never recomputed.
"""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from typing import Any

from hrms.modules.attendance.explanation import OvertimeFacts, PolicyBand, PolicyFacts, explain

POLICY = PolicyFacts(
    name="Standard",
    grace_in_minutes=15,
    grace_out_minutes=10,
    hour_bands=[
        PolicyBand(0, 240, "ABSENT"),
        PolicyBand(240, 360, "HALF_DAY"),
        PolicyBand(360, None, "PRESENT"),
    ],
)


def _display(code: str, label: str, tone: str, provisional: bool = False) -> SimpleNamespace:
    return SimpleNamespace(code=code, label=label, tone=tone, provisional=provisional)


def _day(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "attendance_status": "PRESENT",
        "computation_snapshot": {},
        "display": _display("PRESENT", "Present", "success"),
        "timezone": "Asia/Kolkata",
        "worked_minutes": 490,
        "actual_first_in": "2026-11-19T04:00:00+00:00",  # 09:30 IST
        "actual_last_out": "2026-11-19T13:00:00+00:00",  # 18:30 IST
        "scheduled_start": "2026-11-19T04:00:00+00:00",
        "scheduled_end": "2026-11-19T13:00:00+00:00",
        "scheduled_minutes": 480,
        "late_minutes": 0,
        "early_departure_minutes": 0,
        "late_classification": None,
        "early_departure_classification": None,
        "actual_break_minutes": 0,
        "unpaid_break_minutes": 0,
        "calendar_day_type": "WORKING",
        "holiday_name": None,
        "is_regularized": False,
        "is_locked": False,
        "paid_day_fraction": "1.00",
        "lop_fraction": "0.00",
        "leave_fraction": "0.00",
        "ot_minutes_detected": 0,
        "ot_minutes_approved": 0,
        "ot_pending": False,
        "ot_classification": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_present_on_time() -> None:
    out = explain(_day(), POLICY)
    assert out.reason == "Worked 8 h 10 m of 8 h. On time."
    assert out.verdict.label == "Present"
    assert out.pay.label == "1 day paid"
    assert out.provisional is False
    assert {f.key for f in out.facts} >= {"scheduled", "first_in", "grace", "required", "worked"}


def test_half_day_from_hours_quotes_the_policy_band() -> None:
    day = _day(
        attendance_status="HALF_DAY",
        worked_minutes=300,
        display=_display("HALF_DAY", "Half day", "warning"),
        paid_day_fraction="0.50",
        lop_fraction="0.50",
    )
    out = explain(day, POLICY)
    assert out.reason == (
        "Worked 5 h. A full day needs 6 h; 4 h to 6 h is a half day under the Standard policy."
    )
    assert "hour_band:HALF_DAY" in out.rules_applied
    assert out.pay.label == "0.5 day paid, 0.5 day unpaid"


def test_half_day_from_a_late_arrival() -> None:
    day = _day(
        attendance_status="HALF_DAY",
        worked_minutes=400,
        late_minutes=80,
        late_classification="HALF_DAY",
        actual_first_in="2026-11-19T05:20:00+00:00",  # 10:50 IST
        display=_display("HALF_DAY", "Half day", "warning"),
    )
    out = explain(day, POLICY)
    assert out.reason.startswith("Arrived 10:50, 1 h 20 m late.")
    assert "late_band:HALF_DAY" in out.rules_applied


def test_absent_with_no_punches() -> None:
    day = _day(
        attendance_status="ABSENT",
        worked_minutes=0,
        actual_first_in=None,
        actual_last_out=None,
        display=_display("ABSENT", "Absent", "danger"),
        paid_day_fraction="0.00",
        lop_fraction="1.00",
    )
    out = explain(day, POLICY)
    assert out.reason == "No punches on a working day."
    assert out.pay.label == "1 day unpaid"


def test_absent_from_too_few_hours() -> None:
    day = _day(
        attendance_status="ABSENT",
        worked_minutes=100,
        display=_display("ABSENT", "Absent", "danger"),
        paid_day_fraction="0.00",
        lop_fraction="1.00",
    )
    out = explain(day, POLICY)
    assert out.reason == "Worked 1 h 40 m. Under 4 h counts as absent under the Standard policy."


def test_incomplete_with_a_punch_in_only() -> None:
    day = _day(
        attendance_status="INCOMPLETE",
        actual_last_out=None,
        worked_minutes=0,
        display=_display("INCOMPLETE", "Incomplete", "warning"),
    )
    out = explain(day, POLICY)
    assert out.reason.startswith("Punched in at 09:30 with no punch out.")
    assert out.action is not None
    assert out.action.kind == "REQUEST_CORRECTION"
    assert out.action.deadline is None  # no open period known
    assert out.action.consequence == "Counts as absent (unpaid) if not fixed"


def test_holiday_names_the_holiday() -> None:
    day = _day(
        attendance_status="NOT_EXPECTED",
        calendar_day_type="HOLIDAY",
        holiday_name="Diwali",
        worked_minutes=0,
        actual_first_in=None,
        actual_last_out=None,
        display=_display("HOLIDAY", "Holiday", "holiday"),
    )
    assert explain(day, POLICY).reason == "Diwali (holiday). No work expected."


def test_weekly_off() -> None:
    day = _day(
        attendance_status="NOT_EXPECTED",
        calendar_day_type="WEEKLY_OFF",
        display=_display("WEEKLY_OFF", "Weekly off", "holiday"),
    )
    assert explain(day, POLICY).reason == "Weekly off. No work expected."


def test_full_day_leave_and_half_day_leave() -> None:
    full = _day(
        attendance_status="LEAVE",
        leave_fraction="1.00",
        paid_day_fraction="1.00",
        display=_display("LEAVE", "On leave", "on_leave"),
    )
    assert explain(full, POLICY).reason == "On leave for the full day (paid)."
    half = _day(
        attendance_status="HALF_DAY",
        leave_fraction="0.50",
        computation_snapshot={"half_day_leave": {"leave_half": "FIRST"}},
        display=_display("HALF_DAY", "Half day", "warning"),
    )
    out = explain(half, POLICY)
    assert out.reason == "Half day of leave (first); the other half was worked."
    assert "half_day_leave" in out.rules_applied


def test_config_error_tells_the_employee_nothing_technical() -> None:
    day = _day(
        attendance_status="CONFIG_ERROR",
        computation_snapshot={"terminal_reason": "hour_band_not_covered"},
        display=_display("CONFIG_ERROR", "Needs attention", "danger"),
    )
    out = explain(day, POLICY)
    assert out.reason == "We couldn't calculate this day. HR has been told."
    assert "config:hour_band_not_covered" in out.rules_applied


def test_open_day_is_provisional_and_gives_no_verdict_wording() -> None:
    day = _day(
        attendance_status="INCOMPLETE",
        actual_last_out=None,
        display=_display("PRESENT", "Working now", "success", provisional=True),
    )
    out = explain(day, POLICY)
    assert out.provisional is True
    assert out.reason == "Working since 09:30. The result is final after the shift ends."


def test_no_policy_means_no_thresholds_are_quoted() -> None:
    day = _day(
        attendance_status="HALF_DAY",
        worked_minutes=230,
        display=_display("HALF_DAY", "Half day", "warning"),
    )
    out = explain(day, None)
    assert out.reason == "Worked 3 h 50 m, which counts as a half day."
    assert all(f.key not in ("grace", "required") for f in out.facts)


def test_overtime_found_and_approved_come_from_the_day() -> None:
    day = _day(
        ot_minutes_detected=105,
        ot_minutes_approved=90,
        ot_pending=True,
        ot_classification="WEEKDAY",
    )
    out = explain(day, POLICY)
    assert out.overtime is not None
    assert (out.overtime.found_min, out.overtime.approved_min, out.overtime.pending_min) == (
        105,
        90,
        15,
    )
    assert explain(_day(), POLICY).overtime is None


def _incomplete(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "attendance_status": "INCOMPLETE",
        "actual_last_out": None,
        "worked_minutes": 0,
        "display": _display("INCOMPLETE", "Incomplete", "warning"),
        "computation_snapshot": {"inputs": {"punch_ids": ["p1"]}},
    }
    base.update(over)
    return _day(**base)


def test_incomplete_names_the_deadline_and_consequence_in_the_reason() -> None:
    out = explain(_incomplete(), POLICY, correction_deadline=date(2026, 11, 30))
    assert out.action is not None
    assert out.action.deadline == "2026-11-30"
    assert out.reason.endswith("Fix it by 30 Nov. Counts as absent (unpaid) if not fixed.")


def test_incomplete_under_treat_present_counts_as_present_only_with_a_punch() -> None:
    policy = replace(POLICY, incomplete_at_lock_behaviour="TREAT_PRESENT")
    with_punch = explain(_incomplete(), policy)
    assert with_punch.action is not None
    assert with_punch.action.consequence == "Counts as present if not fixed"
    # H-02: no punches at all is a no-show, absent whatever the company chose.
    no_punch = explain(
        _incomplete(
            actual_first_in=None,
            computation_snapshot={"inputs": {"punch_ids": []}},
        ),
        policy,
    )
    assert no_punch.action is not None
    assert no_punch.action.consequence == "Counts as absent (unpaid) if not fixed"


def test_incomplete_under_keep_incomplete_blocks_the_close() -> None:
    policy = replace(POLICY, incomplete_at_lock_behaviour="KEEP_INCOMPLETE")
    out = explain(_incomplete(), policy)
    assert out.action is not None
    assert "cannot close the period" in out.action.consequence


def test_no_action_for_a_locked_or_provisional_or_complete_day() -> None:
    assert explain(_incomplete(is_locked=True), POLICY).action is None
    assert explain(_day(), POLICY).action is None
    working = _incomplete(display=_display("PRESENT", "Working now", "success", provisional=True))
    assert explain(working, POLICY).action is None


def test_overtime_record_is_the_authority_over_the_day_row() -> None:
    day = _day(ot_minutes_detected=105, ot_minutes_approved=0, ot_pending=False)
    pending = OvertimeFacts(105, 90, "PENDING", "WEEKDAY")
    out = explain(day, POLICY, overtime_record=pending)
    assert out.overtime is not None
    assert (out.overtime.found_min, out.overtime.approved_min, out.overtime.pending_min) == (
        105,
        90,
        15,
    )
    assert out.overtime.class_label == "WEEKDAY"
    approved = explain(day, POLICY, overtime_record=OvertimeFacts(105, 105, "APPROVED", "WEEKDAY"))
    assert approved.overtime is not None
    assert approved.overtime.pending_min == 0
    rejected = explain(day, POLICY, overtime_record=OvertimeFacts(105, 0, "REJECTED", "WEEKDAY"))
    assert rejected.overtime is not None
    assert (rejected.overtime.approved_min, rejected.overtime.pending_min) == (0, 0)
