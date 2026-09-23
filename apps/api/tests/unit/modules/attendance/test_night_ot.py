"""ATT-005 — `night_ot_mode` honoured as designed (architecture §12.1): `SHIFT_FLAG` reads the
shift's `is_night_shift` flag, `WINDOW` checks the overtime span against the policy's night
window, `BOTH` is either. No DB/HTTP."""

from datetime import UTC, datetime, time, timedelta
from typing import Any

from tests.unit.modules.attendance.test_calculation import _shift

from hrms.modules.attendance.calculation import OvertimePolicyInputs, resolve_is_night_ot

_TZ = "Asia/Kolkata"  # UTC+05:30


def _policy(mode: str, start: time | None = time(22, 0), end: time | None = time(6, 0)) -> Any:
    return OvertimePolicyInputs(
        eligibility="ALWAYS",
        min_ot_minutes=0,
        rounding_minutes=None,
        rounding_mode="NONE",
        requires_post_approval=False,
        daily_cap_minutes=None,
        comp_off_instead_of_pay=False,
        night_ot_mode=mode,
        night_window_start=start,
        night_window_end=end,
        rate_rows=[],
    )


def _ist(hour: int, minute: int = 0, day: int = 10) -> datetime:
    # IST -> UTC: subtract 5h30m.
    return datetime(2026, 8, day, tzinfo=UTC) + timedelta(minutes=hour * 60 + minute - 330)


def _resolve(
    mode: str,
    *,
    last_out_ist: tuple[int, int],
    night_shift: bool = False,
    scheduled_end_ist: tuple[int, int] | None = (18, 0),
    **policy_kwargs: Any,
) -> bool:
    return resolve_is_night_ot(
        shift=_shift(is_night_shift=night_shift),
        policy=_policy(mode, **policy_kwargs),
        timezone=_TZ,
        scheduled_end=_ist(*scheduled_end_ist) if scheduled_end_ist else None,
        last_out=_ist(*last_out_ist),
        worked_minutes=0,
        scheduled_minutes=None,
    )


def test_shift_flag_mode_uses_explicit_night_shift_flag_only() -> None:
    assert _resolve("SHIFT_FLAG", last_out_ist=(23, 0), night_shift=True) is True
    # Working into the night window does not count under SHIFT_FLAG.
    assert _resolve("SHIFT_FLAG", last_out_ist=(23, 0), night_shift=False) is False


def test_window_mode_day_shift_ot_running_into_window_is_night() -> None:
    """The case the audit flagged: a day shift (18:00 end) with OT until 23:00 IST."""
    assert _resolve("WINDOW", last_out_ist=(23, 0)) is True


def test_window_mode_ot_ending_before_window_is_not_night() -> None:
    assert _resolve("WINDOW", last_out_ist=(21, 30)) is False


def test_window_mode_ignores_night_shift_flag() -> None:
    assert _resolve("WINDOW", last_out_ist=(20, 0), night_shift=True) is False


def test_window_mode_unset_window_never_matches() -> None:
    assert _resolve("WINDOW", last_out_ist=(23, 0), start=None, end=None) is False


def test_window_mode_matches_early_morning_part_of_overnight_window() -> None:
    """OT from a shift ending 04:00 running to 05:00 falls in the 22:00-06:00 window that
    opened the previous evening."""
    assert _resolve("WINDOW", scheduled_end_ist=(4, 0), last_out_ist=(5, 0)) is True


def test_window_mode_same_day_window() -> None:
    assert _resolve("WINDOW", last_out_ist=(19, 0), start=time(18, 30), end=time(20, 0)) is True
    assert _resolve("WINDOW", last_out_ist=(18, 20), start=time(18, 30), end=time(20, 0)) is False


def test_both_mode_is_either_condition() -> None:
    assert _resolve("BOTH", last_out_ist=(20, 0), night_shift=True) is True
    assert _resolve("BOTH", last_out_ist=(23, 0), night_shift=False) is True
    assert _resolve("BOTH", last_out_ist=(20, 0), night_shift=False) is False


def test_window_without_scheduled_end_uses_trailing_excess() -> None:
    # FLEX: 600 worked vs 480 required -> 120 min excess ending 23:00 -> span 21:00-23:00.
    result = resolve_is_night_ot(
        shift=_shift(),
        policy=_policy("WINDOW"),
        timezone=_TZ,
        scheduled_end=None,
        last_out=_ist(23, 0),
        worked_minutes=600,
        scheduled_minutes=480,
    )
    assert result is True


def test_night_ot_without_night_rate_row_falls_back_to_normal_rate() -> None:
    from dataclasses import replace

    from hrms.modules.attendance.calculation import OvertimeRateRowData, detect_overtime

    policy = replace(_policy("SHIFT_FLAG"), rate_rows=[OvertimeRateRowData("NORMAL", "OT_1_5X")])
    minutes, classification, eligible = detect_overtime(
        worked_minutes=600,
        scheduled_minutes=480,
        is_shift_ot_eligible=True,
        is_holiday=False,
        is_weekly_off=False,
        is_night=True,
        policy=policy,
    )
    assert (minutes, classification, eligible) == (120, "OT_1_5X", True)
