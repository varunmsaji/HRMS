"""P-04 and F2 (owner decisions): work before a fixed shift's start, and what "first in" means.

P-04 (option B). On a FIXED shift's working day with NO credited work at all, sessions wholly
before the scheduled start count toward the hour-band classification (capped at the net schedule,
scaled by P-05). Never overtime, comp-off or lateness relief; the real punches are untouched; the
day carries a WORKED_OUTSIDE_SHIFT flag. A session that straddles the start keeps today's rule
(clipped to the start). Flexible and split shifts are unchanged. The early-departure mark is still
recorded.

F2. Lateness, grace and mark credit run from the first CREDITED in-shift presence, so a separate
session before the start cannot erase lateness; a straddling session counts from the start (on
time); a day with only pre-start work gets no automatic late mark. `actual_first_in` keeps the real
punch.

Default day: 09:00-18:00 UTC with an unpaid 13:00-14:00 lunch (net 480); `EIGHT` is 09:00-17:00
with no break (net 480). Grace 10/10, bands ABSENT < 240, HALF_DAY 240-479, PRESENT >= 480.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from tests.unit.modules.attendance.test_attendance_rules_remediation import (
    _LATE_BANDS,
    _day,
    _leave,
    _pay,
    _split_day,
)
from tests.unit.modules.attendance.test_calculation import _policy, _shift

EIGHT: dict[str, Any] = dict(
    shift=_shift(is_ot_eligible=True), scheduled_end=datetime(2026, 8, 10, 17, tzinfo=UTC)
)
FOUR: dict[str, Any] = dict(
    shift=_shift(is_ot_eligible=True), scheduled_end=datetime(2026, 8, 10, 13, tzinfo=UTC)
)


def flag(result: Any) -> dict[str, Any] | None:
    return result.snapshot.get("worked_outside_shift")


# --- P-04: sessions wholly before the start, no credited work ---


def test_a_session_wholly_before_the_start_is_classified_not_absent() -> None:
    """04:30-08:30 only: 240 minutes worked, all before 09:00. Was ABSENT with a full day of LOP."""
    result = _day([(4, 30, "IN"), (8, 30, "OUT")], **EIGHT)
    assert result.attendance_status == "HALF_DAY"
    assert _pay(result) == ("0.50", "0.50")
    assert flag(result) == {
        "flag": "WORKED_OUTSIDE_SHIFT",
        "sessions": 1,
        "minutes": 240,
        "credited_for_classification": 240,
    }


@pytest.mark.parametrize(
    ("start", "end", "minutes", "status"),
    [
        ((5, 1), (9, 0), 239, "ABSENT"),  # just under the half-day threshold
        ((5, 0), (9, 0), 240, "HALF_DAY"),  # exactly at it (the session ends exactly at the start)
        ((4, 59), (9, 0), 241, "HALF_DAY"),  # above it
        ((5, 0), (8, 50), 230, "ABSENT"),
    ],
)
def test_pre_start_work_below_at_and_above_the_half_day_threshold(
    start: tuple[int, int], end: tuple[int, int], minutes: int, status: str
) -> None:
    result = _day([(*start, "IN"), (*end, "OUT")], **EIGHT)
    assert flag(result)["minutes"] == minutes  # type: ignore[index]
    assert result.attendance_status == status


def test_the_credit_is_capped_at_the_net_scheduled_minutes() -> None:
    full = _day([(1, 0, "IN"), (9, 0, "OUT")], **EIGHT)  # 480
    assert full.attendance_status == "PRESENT"
    assert flag(full)["credited_for_classification"] == 480  # type: ignore[index]
    over = _day([(0, 0, "IN"), (9, 0, "OUT")], **EIGHT)  # 540 worked, capped to the 480 net
    assert flag(over)["minutes"] == 540  # type: ignore[index]
    assert flag(over)["credited_for_classification"] == 480  # type: ignore[index]
    assert over.attendance_status == "PRESENT"


def test_several_pre_start_sessions_are_added_without_counting_any_minute_twice() -> None:
    two = _day([(4, 30, "IN"), (6, 30, "OUT"), (7, 0, "IN"), (9, 0, "OUT")], **EIGHT)
    assert flag(two)["sessions"] == 2 and flag(two)["minutes"] == 240  # type: ignore[index]
    assert two.attendance_status == "HALF_DAY"
    touching = _day([(5, 0, "IN"), (7, 0, "OUT"), (7, 0, "IN"), (9, 0, "OUT")], **EIGHT)
    assert flag(touching)["minutes"] == 240  # the shared minute boundary is not counted twice


def test_the_real_punches_and_every_other_figure_are_untouched() -> None:
    result = _day([(4, 30, "IN"), (8, 30, "OUT")], **EIGHT)
    assert result.worked_minutes == 0  # classification only: not worked time
    assert result.ot_minutes_detected == 0 and not result.ot_pending  # never overtime
    assert result.actual_first_in == datetime(2026, 8, 10, 4, 30, tzinfo=UTC)  # not moved to 09:00
    assert result.actual_last_out == datetime(2026, 8, 10, 8, 30, tzinfo=UTC)


def test_a_pre_start_only_day_gets_no_lateness_and_still_records_the_early_departure() -> None:
    result = _day([(4, 30, "IN"), (8, 30, "OUT")], late_bands=_LATE_BANDS, **EIGHT)
    assert result.late_minutes == 0 and result.is_late is False  # F2: no automatic late mark
    assert result.early_departure_minutes > 0  # the existing early-departure recording is kept


# --- P-04: where the rule does NOT apply ---


def test_a_session_straddling_the_start_keeps_the_existing_rule() -> None:
    result = _day([(8, 0, "IN"), (16, 0, "OUT")], **EIGHT)  # clipped to 09:00: 420 credited
    assert result.worked_minutes == 420
    assert flag(result) is None
    assert result.attendance_status == "HALF_DAY"


def test_pre_start_work_plus_normal_shift_work_is_not_credited_twice() -> None:
    result = _day([(8, 0, "IN"), (8, 30, "OUT"), (9, 0, "IN"), (17, 0, "OUT")], **EIGHT)
    assert result.worked_minutes == 480 and flag(result) is None
    assert result.attendance_status == "PRESENT"
    assert result.late_minutes == 0


def test_flexible_and_split_shifts_are_unchanged() -> None:
    flexible = _day(
        [(7, 0, "IN"), (9, 0, "OUT")],
        shift=_shift(shift_type="FLEXIBLE", is_ot_eligible=True, required_minutes=480),
        scheduled_end=datetime(2026, 8, 10, 10, tzinfo=UTC),
    )
    assert flag(flexible) is None
    split = _split_day([(5, 0, "IN"), (8, 30, "OUT")])
    assert flag(split) is None


def test_a_day_off_and_a_half_day_leave_day_are_not_covered() -> None:
    off = _day([(4, 30, "IN"), (8, 30, "OUT")], roster_week_off_override=True, **EIGHT)
    assert flag(off) is None
    leave = _day([(4, 30, "IN"), (8, 30, "OUT")], leave_entries=_leave("SECOND"), **EIGHT)
    assert flag(leave) is None


def test_overtime_after_the_shift_is_not_mixed_up_with_pre_start_work() -> None:
    """08:00-08:50 then 09:00-19:00 against a 17:00 end: the 50 pre-start minutes earn nothing, the
    two hours after the end are overtime exactly as before."""
    result = _day(
        [(8, 0, "IN"), (8, 50, "OUT"), (9, 0, "IN"), (19, 0, "OUT")],
        **EIGHT,
    )
    assert flag(result) is None
    assert result.ot_minutes_detected == 120


# --- P-04 with P-05's scaled bands ---


@pytest.mark.parametrize(
    ("start", "minutes", "status"),
    [((7, 1), 119, "ABSENT"), ((7, 0), 120, "HALF_DAY"), ((5, 0), 240, "PRESENT")],
)
def test_the_hours_are_compared_with_the_scaled_thresholds_on_a_short_shift(
    start: tuple[int, int], minutes: int, status: str
) -> None:
    """A 4-hour shift: the scaled thresholds are 120 (half day) and 240 (full day)."""
    result = _day([(*start, "IN"), (9, 0, "OUT")], **FOUR)
    assert flag(result)["minutes"] == minutes  # type: ignore[index]
    assert result.attendance_status == status


# --- F2: lateness runs from the first CREDITED in-shift presence ---


def test_an_early_session_cannot_erase_lateness() -> None:
    """08:30-08:50 then 11:00-17:00: the 08:30 session is not credited work, so arrival is 11:00."""
    result = _day(
        [(8, 30, "IN"), (8, 50, "OUT"), (11, 0, "IN"), (17, 0, "OUT")],
        late_bands=_LATE_BANDS,
        **EIGHT,
    )
    assert result.late_minutes == 110 and result.is_late is True
    assert result.actual_first_in == datetime(2026, 8, 10, 8, 30, tzinfo=UTC)  # the real punch


def test_an_early_session_and_a_return_within_the_grace_is_on_time_with_grace_credit() -> None:
    """08:30-08:55 then 09:10-17:00: arrival 09:10 is exactly the grace. 470 worked + 10 credited
    = 480. This day was HALF_DAY while the early session counted as the arrival."""
    result = _day([(8, 30, "IN"), (8, 55, "OUT"), (9, 10, "IN"), (17, 0, "OUT")], **EIGHT)
    assert result.worked_minutes == 470
    assert result.late_minutes == 0 and result.is_late is False
    assert result.attendance_status == "PRESENT"


def test_a_straddling_session_counts_from_the_start_and_is_on_time() -> None:
    result = _day([(8, 0, "IN"), (17, 0, "OUT")], late_bands=_LATE_BANDS, **EIGHT)
    assert result.late_minutes == 0 and result.is_late is False


def test_a_late_first_session_is_late_exactly_as_before() -> None:
    result = _day([(10, 30, "IN"), (17, 0, "OUT")], late_bands=_LATE_BANDS, **EIGHT)
    assert result.late_minutes == 80  # 90 minutes late, 10 of grace


def test_flexible_lateness_is_unchanged() -> None:
    result = _day(
        [(8, 30, "IN"), (17, 30, "OUT")],
        shift=_shift(shift_type="FLEXIBLE", is_ot_eligible=True, required_minutes=480),
        scheduled_end=datetime(2026, 8, 10, 10, tzinfo=UTC),
    )
    assert result.late_minutes == 0


# --- the same in every timezone ---


@pytest.mark.parametrize("zone", ["UTC", "Asia/Kolkata", "America/New_York"])
def test_pre_start_work_and_first_presence_do_not_depend_on_the_timezone(zone: str) -> None:
    policy = _policy(grace_in_minutes=10, grace_out_minutes=10)
    pre = _day([(4, 30, "IN"), (8, 30, "OUT")], timezone=zone, policy=policy, **EIGHT)
    assert pre.attendance_status == "HALF_DAY" and flag(pre)["minutes"] == 240  # type: ignore[index]
    late = _day(
        [(8, 30, "IN"), (8, 50, "OUT"), (11, 0, "IN"), (17, 0, "OUT")],
        timezone=zone,
        policy=policy,
        late_bands=_LATE_BANDS,
        **EIGHT,
    )
    assert late.late_minutes == 110
