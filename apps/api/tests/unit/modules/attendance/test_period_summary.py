"""Unit tests for the payroll-facing period summary aggregation (PAY-002/PAY-003) —
`AttendancePeriodService._aggregate_day_rows` / `_assert_summary_reconciles`, plus the
`leave_fraction` the calculation engine records for it. No DB/HTTP.

Rules under test: `docs/audits/PAYROLL_BUSINESS_DECISIONS.md`, "Derived rules for the attendance
period summary"."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from tests.unit.modules.attendance.test_calculation import _base_input, _punch

from hrms.modules.attendance.calculation import LeaveOverlayEntry, evaluate_day
from hrms.modules.attendance.exceptions import AttendanceSummaryReconciliationError
from hrms.modules.attendance.service import AttendancePeriodService

_EMPLOYEE = uuid4()


def _row(
    status: str,
    *,
    paid: str,
    lop: str,
    leave: str = "0.00",
    day_type: str | None = "WORKING",
    day: int = 1,
    **extra: Any,
) -> SimpleNamespace:
    values: dict[str, Any] = {
        "employee_id": _EMPLOYEE,
        "attendance_date": date(2026, 8, day),
        "attendance_status": status,
        "calendar_day_type": day_type,
        "paid_day_fraction": Decimal(paid),
        "lop_fraction": Decimal(lop),
        "leave_fraction": Decimal(leave),
        "weekly_off_fraction": Decimal("0.00"),
        "unpaid_off_fraction": Decimal("0.00"),
        "ot_classification": None,
        "ot_day_class": None,
        "ot_minutes_approved": 0,
        "comp_off_minutes_earned": 0,
        "is_late": False,
        "worked_minutes": 0,
    }
    values.update(extra)
    values["weekly_off_fraction"] = Decimal(str(values["weekly_off_fraction"]))
    values["unpaid_off_fraction"] = Decimal(str(values["unpaid_off_fraction"]))
    return SimpleNamespace(**values)


def _aggregate(rows: list[SimpleNamespace], period_days: int | None = None) -> dict[str, Any]:
    result: dict[UUID, dict[str, Any]] = AttendancePeriodService._aggregate_day_rows(
        rows,  # type: ignore[arg-type]
        period_days=period_days,
    )
    return result[_EMPLOYEE]


def test_worked_holiday_counts_as_present_only() -> None:
    """PAY-003 defect 1 — previously incremented both `present_days` and `holiday_days`."""
    agg = _aggregate([_row("PRESENT", paid="1.00", lop="0.00", day_type="HOLIDAY")])
    assert agg["present_days"] == Decimal("1.00")
    assert agg["holiday_days"] == Decimal("0.00")


def test_unworked_holiday_shutdown_and_weekly_off_buckets() -> None:
    agg = _aggregate(
        [
            _row("NOT_EXPECTED", paid="1.00", lop="0.00", day_type="HOLIDAY", day=1),
            _row("NOT_EXPECTED", paid="1.00", lop="0.00", day_type="SHUTDOWN", day=2),
            _row("NOT_EXPECTED", paid="1.00", lop="0.00", day_type="WEEKLY_OFF", day=3),
            # roster week-off on a calendar WORKING day
            _row("NOT_EXPECTED", paid="1.00", lop="0.00", day_type="WORKING", day=4),
        ]
    )
    assert agg["holiday_days"] == Decimal("2.00")
    assert agg["weekly_off_days"] == Decimal("2.00")
    assert agg["paid_days"] == Decimal("4.00")


def test_half_day_leave_split_between_leave_and_worked_half() -> None:
    """PAY-003 defect 3 — half-day leave previously landed only in `half_days`."""
    agg = _aggregate([_row("HALF_DAY", paid="1.00", lop="0.00", leave="0.50")])
    assert agg["leave_days"] == Decimal("0.50")
    assert agg["present_days"] == Decimal("0.50")
    assert agg["half_days"] == Decimal("0.00")


def test_half_day_leave_with_unworked_other_half_is_leave_plus_absent() -> None:
    agg = _aggregate([_row("LEAVE", paid="0.50", lop="0.50", leave="0.50")])
    assert agg["leave_days"] == Decimal("0.50")
    assert agg["absent_days"] == Decimal("0.50")
    assert agg["lop_days"] == Decimal("0.50")


def test_band_half_day_without_leave_counts_as_one_half_day() -> None:
    agg = _aggregate([_row("HALF_DAY", paid="0.50", lop="0.50")])
    assert agg["half_days"] == Decimal("1.00")
    assert agg["paid_days"] == Decimal("0.50")


def test_legacy_leave_row_without_leave_fraction_is_full_leave() -> None:
    agg = _aggregate([_row("LEAVE", paid="1.00", lop="0.00", leave="0.00")])
    assert agg["leave_days"] == Decimal("1.00")


def test_previously_unbucketed_statuses_now_have_buckets() -> None:
    """PAY-003 defect 2 — ON_DUTY / INCOMPLETE / CONFIG_ERROR / NOT_JOINED / EXITED fell into
    no bucket."""
    agg = _aggregate(
        [
            _row("ON_DUTY", paid="1.00", lop="0.00", day=1),
            _row("INCOMPLETE", paid="0.00", lop="0.00", day=2),
            _row("CONFIG_ERROR", paid="0.00", lop="0.00", day=3),
            _row("NOT_JOINED", paid="0.00", lop="0.00", day=4),
            _row("EXITED", paid="0.00", lop="0.00", day=5),
        ]
    )
    assert agg["on_duty_days"] == Decimal("1.00")
    assert agg["incomplete_days"] == Decimal("2.00")
    assert agg["not_employed_days"] == Decimal("2.00")
    assert agg["payable_days"] == Decimal("3.00")


def test_resolved_incomplete_days_follow_their_resolved_fractions() -> None:
    agg = _aggregate(
        [
            _row("INCOMPLETE", paid="0.00", lop="1.00", day=1),  # TREAT_ABSENT
            _row("INCOMPLETE", paid="1.00", lop="0.00", day=2),  # TREAT_PRESENT
        ]
    )
    assert agg["absent_days"] == Decimal("1.00")
    assert agg["present_days"] == Decimal("1.00")
    assert agg["incomplete_days"] == Decimal("0.00")


def test_frozen_mode_counts_days_without_rows_as_not_employed_and_reconciles() -> None:
    """A mid-month joiner (joined on the 3rd) in a 5-day period, with rows only for employed
    days — the finalize gate guarantees those rows exist, so the 2 missing days are
    not-employed."""
    rows = [
        _row("PRESENT", paid="1.00", lop="0.00", day=3),
        _row("ABSENT", paid="0.00", lop="1.00", day=4),
        _row("NOT_EXPECTED", paid="1.00", lop="0.00", day_type="WEEKLY_OFF", day=5),
    ]
    agg = _aggregate(rows, period_days=5)
    assert agg["not_employed_days"] == Decimal("2.00")
    assert agg["payable_days"] == Decimal("3.00")
    assert agg["paid_days"] == Decimal("2.00")
    assert agg["lop_days"] == Decimal("1.00")
    AttendancePeriodService._assert_summary_reconciles({_EMPLOYEE: agg}, period_days=5)


def test_reconciliation_rejects_paid_plus_lop_not_equal_payable() -> None:
    agg = _aggregate([_row("PRESENT", paid="1.00", lop="0.50")], period_days=1)
    with pytest.raises(AttendanceSummaryReconciliationError):
        AttendancePeriodService._assert_summary_reconciles({_EMPLOYEE: agg}, period_days=1)


def test_reconciliation_rejects_unresolved_incomplete_day() -> None:
    agg = _aggregate([_row("INCOMPLETE", paid="0.00", lop="0.00")], period_days=1)
    with pytest.raises(AttendanceSummaryReconciliationError):
        AttendancePeriodService._assert_summary_reconciles({_EMPLOYEE: agg}, period_days=1)


# -- engine side: `leave_fraction` ---------------------------------------------------------


def test_engine_records_full_day_leave_fraction() -> None:
    result = evaluate_day(_base_input(leave_entries=[LeaveOverlayEntry("1.00", True)]))
    assert result.attendance_status == "LEAVE"
    assert result.leave_fraction == "1.00"


def test_engine_records_half_day_leave_fraction_with_work() -> None:
    result = evaluate_day(
        _base_input(
            punches=[_punch(3, 30, "IN", day=10), _punch(12, 30, "OUT", day=10)],
            leave_entries=[LeaveOverlayEntry("0.50", True, "FIRST")],
        )
    )
    assert result.attendance_status == "HALF_DAY"
    assert result.leave_fraction == "0.50"
    assert Decimal(result.paid_day_fraction) + Decimal(result.lop_fraction) == Decimal("1.00")


def test_engine_records_no_leave_fraction_without_leave() -> None:
    result = evaluate_day(_base_input())
    assert result.leave_fraction == "0.00"


# -- PAY-012: half-day weekly off -----------------------------------------------------------


def _half_saturday(**overrides: object) -> Any:
    return _base_input(
        calendar_day_type="WEEKLY_OFF",
        weekly_off_fraction="0.50",
        **overrides,
    )


def test_half_weekly_off_worked_is_full_paid_day() -> None:
    result = evaluate_day(
        _half_saturday(punches=[_punch(3, 30, "IN", day=10), _punch(8, 0, "OUT", day=10)])
    )
    assert result.attendance_status == "PRESENT"
    assert result.calendar_day_type == "WEEKLY_OFF"
    assert (result.paid_day_fraction, result.lop_fraction) == ("1.00", "0.00")
    assert result.weekly_off_fraction == "0.50"


def test_half_weekly_off_skipped_is_half_paid_half_lop() -> None:
    from dataclasses import replace

    base = _half_saturday()
    policy = replace(base.policy, missing_punch_behaviour="ABSENT")
    result = evaluate_day(replace(base, policy=policy))
    assert result.attendance_status == "ABSENT"
    assert (result.paid_day_fraction, result.lop_fraction) == ("0.50", "0.50")


def test_half_weekly_off_incomplete_stays_unresolved_until_lock() -> None:
    result = evaluate_day(_half_saturday(punches=[_punch(3, 30, "IN", day=10)]))
    assert result.attendance_status == "INCOMPLETE"
    assert (result.paid_day_fraction, result.lop_fraction) == ("0.00", "0.00")
    assert result.weekly_off_fraction == "0.50"


def test_half_weekly_off_with_half_day_leave_is_fully_paid() -> None:
    result = evaluate_day(_half_saturday(leave_entries=[LeaveOverlayEntry("0.50", True)]))
    assert result.attendance_status == "LEAVE"
    assert (result.paid_day_fraction, result.lop_fraction) == ("1.00", "0.00")


def test_full_weekly_off_unchanged() -> None:
    result = evaluate_day(_base_input(calendar_day_type="WEEKLY_OFF"))
    assert result.attendance_status == "NOT_EXPECTED"
    assert result.weekly_off_fraction == "0.00"


def test_summary_splits_half_weekly_off_day() -> None:
    agg = _aggregate(
        [
            _row("PRESENT", paid="1.00", lop="0.00", day=1, weekly_off_fraction="0.50"),
            _row("ABSENT", paid="0.50", lop="0.50", day=2, weekly_off_fraction="0.50"),
            _row("LEAVE", paid="1.00", lop="0.00", leave="0.50", day=3, weekly_off_fraction="0.50"),
        ],
        period_days=3,
    )
    assert agg["weekly_off_days"] == Decimal("1.50")
    assert agg["present_days"] == Decimal("0.50")
    assert agg["absent_days"] == Decimal("0.50")
    assert agg["leave_days"] == Decimal("0.50")
    assert agg["paid_days"] == Decimal("2.50")
    AttendancePeriodService._assert_summary_reconciles({_EMPLOYEE: agg}, period_days=3)


# -- BUS-011 / BUS-012: work on a full-day leave day ------------------------------------------


def test_full_day_leave_with_overtime_punches_pays_leave_only_and_no_ot() -> None:
    from dataclasses import replace

    from hrms.modules.attendance.calculation import OvertimePolicyInputs

    ot_policy = OvertimePolicyInputs(
        eligibility="ALWAYS",
        min_ot_minutes=0,
        rounding_minutes=None,
        rounding_mode="NONE",
        requires_post_approval=False,
        daily_cap_minutes=None,
        comp_off_instead_of_pay=False,
        night_ot_mode="SHIFT_FLAG",
        night_window_start=None,
        night_window_end=None,
        rate_rows=[],
    )
    base = _base_input(
        ot_policy=ot_policy,
        punches=[_punch(3, 30, "IN", day=10), _punch(15, 30, "OUT", day=10)],  # 12h
    )
    worked = evaluate_day(base)
    assert worked.ot_minutes_detected > 0  # sanity: the same punches do produce OT

    on_leave = evaluate_day(replace(base, leave_entries=[LeaveOverlayEntry("1.00", True)]))
    assert on_leave.attendance_status == "LEAVE"
    assert (on_leave.paid_day_fraction, on_leave.lop_fraction) == ("1.00", "0.00")
    assert on_leave.ot_minutes_detected == 0
    assert on_leave.ot_minutes_approved == 0
    assert on_leave.ot_classification is None
    assert on_leave.comp_off_minutes_earned == 0
    assert on_leave.work_on_leave_flagged is True


def test_ot_buckets_follow_day_class_not_rate_code() -> None:
    """The policy's rate codes are free text (e.g. `OT_NIGHT_2X`) — only the engine's day class
    decides the summary bucket."""
    agg = _aggregate(
        [
            _row(
                "PRESENT",
                paid="1.00",
                lop="0.00",
                day=1,
                ot_classification="OT_NIGHT_2X",
                ot_day_class="NIGHT",
                ot_minutes_approved=60,
            ),
            _row(
                "PRESENT",
                paid="1.00",
                lop="0.00",
                day_type="HOLIDAY",
                day=2,
                ot_classification="OT_HOL",
                ot_day_class="HOLIDAY",
                ot_minutes_approved=120,
            ),
            _row(
                "PRESENT",
                paid="1.00",
                lop="0.00",
                day_type="WEEKLY_OFF",
                day=3,
                ot_classification="OT_WO",
                ot_day_class="WEEKLY_OFF",
                ot_minutes_approved=30,
            ),
            _row(
                "PRESENT",
                paid="1.00",
                lop="0.00",
                day=4,
                ot_classification="NIGHT",
                ot_day_class="NORMAL",
                ot_minutes_approved=15,
            ),
        ]
    )
    assert agg["ot_minutes_night"] == 60
    assert agg["ot_minutes_holiday"] == 120
    assert agg["ot_minutes_weekly_off"] == 30
    assert agg["ot_minutes_normal"] == 15
