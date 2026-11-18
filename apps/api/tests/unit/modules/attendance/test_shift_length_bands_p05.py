"""P-05 (owner decision): shift-length-aware hour bands, and a required PRESENT band.

The stored bands describe one full day. The reference full-day length is the minimum of the lowest
`PRESENT` band. A day whose net scheduled minutes are SHORTER than that reference has every band
threshold scaled by net / reference (rounded half-up to whole minutes), so a 4-hour shift worked in
full is a full day. Never scaled upward. Fixed, flexible and split shifts use their own net minutes;
the worked half of a half-day leave is judged on the same scaled bands. Grace, the D-01 mark credit
and the R-2 ceiling keep their own rules; publication requires a PRESENT band.

Standard bands throughout: ABSENT 0-239, HALF_DAY 240-479, PRESENT 480+ (reference 480).
"""

from datetime import UTC, datetime, time
from types import SimpleNamespace
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

from hrms.modules.attendance.calculation import BandData, ShiftDutyBlockData, scale_hour_bands
from hrms.modules.attendance.exceptions import InvalidPolicyBandError
from hrms.modules.attendance.service import _validate_hour_bands_have_present

STANDARD = [
    BandData(0, 239, "ABSENT"),
    BandData(240, 479, "HALF_DAY"),
    BandData(480, None, "PRESENT"),
]


def _thresholds(bands: list[BandData]) -> list[tuple[int, int | None, str]]:
    return [(b.min_minutes, b.max_minutes, b.classification) for b in bands]


# --- the scaling function ---


@pytest.mark.parametrize(
    ("net", "expected"),
    [
        (240, [(0, 119, "ABSENT"), (120, 239, "HALF_DAY"), (240, None, "PRESENT")]),  # 4 h
        (360, [(0, 179, "ABSENT"), (180, 359, "HALF_DAY"), (360, None, "PRESENT")]),  # 6 h
        (330, [(0, 164, "ABSENT"), (165, 329, "HALF_DAY"), (330, None, "PRESENT")]),  # 5.5 h
        (120, [(0, 59, "ABSENT"), (60, 119, "HALF_DAY"), (120, None, "PRESENT")]),  # 2 h
    ],
)
def test_shorter_shifts_scale_every_threshold_in_proportion(
    net: int, expected: list[tuple[int, int | None, str]]
) -> None:
    assert _thresholds(scale_hour_bands(STANDARD, net)) == expected


@pytest.mark.parametrize("net", [480, 481, 540, 720, 1440])
def test_a_shift_equal_to_or_longer_than_the_reference_is_never_scaled(net: int) -> None:
    assert scale_hour_bands(STANDARD, net) is STANDARD  # unchanged, not even copied


@pytest.mark.parametrize("net", [None, 0, -5])
def test_no_usable_net_schedule_means_no_scaling(net: int | None) -> None:
    assert scale_hour_bands(STANDARD, net) is STANDARD


def test_a_policy_without_a_present_band_has_no_reference_and_is_left_alone() -> None:
    legacy = [BandData(0, 239, "ABSENT"), BandData(240, None, "HALF_DAY")]
    assert scale_hour_bands(legacy, 120) is legacy


def test_the_reference_is_the_lowest_present_band() -> None:
    """Two PRESENT bands (e.g. a later one for long days): the lowest one is the full day."""
    bands = [
        BandData(0, 239, "ABSENT"),
        BandData(240, 479, "HALF_DAY"),
        BandData(480, 599, "PRESENT"),
        BandData(600, None, "PRESENT"),
    ]
    scaled = _thresholds(scale_hour_bands(bands, 240))
    assert scaled[2][:2] == (240, 299) and scaled[0][:2] == (0, 119)


def test_rounding_is_half_up_to_whole_minutes() -> None:
    # 7 / 480 * 240 = 3.5 -> 4 (half up), and 1 / 480 * 240 = 0.5 -> 1
    assert scale_hour_bands(STANDARD, 7)[1].min_minutes == 4
    scaled = scale_hour_bands(STANDARD, 1)
    # the HALF_DAY band would span 1..0 (narrower than a scaled minute), so it disappears and its
    # neighbours share the boundary: ABSENT is minute 0 only, everything from 1 is PRESENT
    assert _thresholds(scaled) == [(0, 0, "ABSENT"), (1, None, "PRESENT")]


@pytest.mark.parametrize("net", range(1, 480))
def test_scaled_bands_always_cover_every_minute_exactly_once(net: int) -> None:
    """Neighbouring bands share their scaled boundary, so contiguity (H-01) survives scaling for
    every net length - no gap, no overlap, first at 0, last open-ended."""
    scaled = scale_hour_bands(STANDARD, net)
    assert scaled[0].min_minutes == 0 and scaled[-1].max_minutes is None
    for lower, upper in zip(scaled, scaled[1:], strict=False):
        assert lower.max_minutes is not None and upper.min_minutes == lower.max_minutes + 1
    assert scaled[-1].classification == "PRESENT" and scaled[-1].min_minutes == net


def test_a_legacy_gap_stays_where_it_was() -> None:
    gapped = [BandData(0, 239, "ABSENT"), BandData(300, None, "PRESENT")]  # 240-299 uncovered
    scaled = scale_hour_bands(gapped, 300)  # reference 300 -> factor 1: unchanged
    assert scaled is gapped


# --- whole days through the engine ---

FOUR_HOURS = dict(  # 09:00-13:00, no break: net 240
    shift=_shift(is_ot_eligible=True), scheduled_end=datetime(2026, 8, 10, 13, tzinfo=UTC)
)
SIX_HOURS = dict(
    shift=_shift(is_ot_eligible=True), scheduled_end=datetime(2026, 8, 10, 15, tzinfo=UTC)
)


#: Grace 0: a minute short is a minute short, so the scaled thresholds themselves are what is tested
#: (the grace and mark interplay has its own tests below).
NO_GRACE = _policy(grace_in_minutes=0, grace_out_minutes=0)


def _status(punches: list[tuple[Any, ...]], **overrides: Any) -> str:
    return _day(punches, policy=NO_GRACE, **overrides).attendance_status


def test_a_four_hour_shift_worked_in_full_is_a_full_day() -> None:
    """The finding (MA-05): it was HALF_DAY because 240 < 480 against the stored bands."""
    result = _day([(9, 0, "IN"), (13, 0, "OUT")], policy=NO_GRACE, **FOUR_HOURS)
    assert result.attendance_status == "PRESENT"
    assert _pay(result) == ("1.00", "0.00")


@pytest.mark.parametrize(
    ("out_hour", "out_minute", "worked", "status"),
    [
        (10, 58, 118, "ABSENT"),  # just under half of 240
        (11, 0, 120, "HALF_DAY"),  # the scaled half-day threshold, exactly
        (12, 59, 239, "HALF_DAY"),
        (13, 0, 240, "PRESENT"),  # the scaled full-day threshold, exactly
    ],
)
def test_the_scaled_boundaries_on_a_four_hour_shift(
    out_hour: int, out_minute: int, worked: int, status: str
) -> None:
    result = _day([(9, 0, "IN"), (out_hour, out_minute, "OUT")], policy=NO_GRACE, **FOUR_HOURS)
    assert result.worked_minutes == worked
    assert result.attendance_status == status


def test_a_six_hour_shift() -> None:
    assert _status([(9, 0, "IN"), (15, 0, "OUT")], **SIX_HOURS) == "PRESENT"
    assert _status([(9, 0, "IN"), (14, 59, "OUT")], **SIX_HOURS) == "HALF_DAY"
    assert _status([(9, 0, "IN"), (11, 59, "OUT")], **SIX_HOURS) == "ABSENT"  # 179 < 180


def test_a_shift_as_long_as_the_reference_is_unchanged() -> None:
    eight = dict(
        shift=_shift(is_ot_eligible=True), scheduled_end=datetime(2026, 8, 10, 17, tzinfo=UTC)
    )
    assert _status([(9, 0, "IN"), (17, 0, "OUT")], **eight) == "PRESENT"
    assert _status([(9, 0, "IN"), (16, 59, "OUT")], **eight) == "HALF_DAY"  # 479


def test_a_longer_shift_is_never_scaled_upward() -> None:
    nine = dict(
        shift=_shift(is_ot_eligible=True), scheduled_end=datetime(2026, 8, 10, 18, tzinfo=UTC)
    )
    assert _status([(9, 0, "IN"), (16, 59, "OUT")], **nine) == "HALF_DAY"  # 479 < 480, not 540


def test_a_flexible_shift_uses_its_required_minutes() -> None:
    flexible = dict(
        shift=_shift(shift_type="FLEXIBLE", is_ot_eligible=True, required_minutes=240),
        scheduled_end=datetime(2026, 8, 10, 13, tzinfo=UTC),
    )
    assert _status([(9, 0, "IN"), (13, 0, "OUT")], **flexible) == "PRESENT"
    assert _status([(9, 0, "IN"), (12, 59, "OUT")], **flexible) == "HALF_DAY"


def test_a_split_shift_uses_the_sum_of_its_duty_blocks() -> None:
    """Two 4-hour blocks (net 480) are a full day; two 2-hour blocks (net 240) are a full day too,
    because that is the shift - not half of an 8-hour day."""
    full = _split_day([(9, 0, "IN"), (13, 0, "OUT"), (17, 0, "IN"), (21, 0, "OUT")])
    assert full.attendance_status == "PRESENT"
    short = [
        ShiftDutyBlockData(1, time(9, 0), time(11, 0), False),
        ShiftDutyBlockData(2, time(17, 0), time(19, 0), False),
    ]
    result = _day(
        [(9, 0, "IN"), (11, 0, "OUT"), (17, 0, "IN"), (19, 0, "OUT")],
        shift=_shift(shift_type="SPLIT", is_ot_eligible=True, duty_blocks=short),
        scheduled_end=datetime(2026, 8, 10, 19, 0, tzinfo=UTC),
    )
    assert result.worked_minutes == 240
    assert result.attendance_status == "PRESENT"


def test_half_day_leave_on_a_short_shift_judges_the_worked_half_on_the_scaled_bands() -> None:
    """4-hour shift, first half on leave, the second half (2 hours) worked in full: the worked half
    is a full half (not a half-day verdict twice), the leave stays 0.50."""
    result = _day([(11, 0, "IN"), (13, 0, "OUT")], leave_entries=_leave("FIRST"), **FOUR_HOURS)
    assert _pay(result) == ("1.00", "0.00")


# --- grace and marks interact with the scaled bands by their own rules ---


def test_grace_credit_counts_against_the_scaled_threshold() -> None:
    """Arrives 09:10 (exactly the 10-minute grace) on the 4-hour shift: 230 worked + 10 credited
    reaches the scaled 240."""
    result = _day([(9, 10, "IN"), (13, 0, "OUT")], **FOUR_HOURS)
    assert result.worked_minutes == 230
    assert result.attendance_status == "PRESENT"
    beyond = _day([(9, 11, "IN"), (13, 0, "OUT")], **FOUR_HOURS)  # H-05: no credit beyond grace
    assert beyond.attendance_status == "HALF_DAY"


def test_a_late_mark_credit_counts_against_the_scaled_threshold() -> None:
    result = _day([(9, 40, "IN"), (13, 0, "OUT")], late_bands=_LATE_BANDS, **FOUR_HOURS)
    # 200 worked + 10 grace + 30 mark = 240 = the scaled full-day threshold
    assert result.attendance_status == "PRESENT"


# --- the engine is the same in every timezone ---


@pytest.mark.parametrize("zone", ["UTC", "Asia/Kolkata", "America/New_York"])
def test_shift_scaling_does_not_depend_on_the_timezone(zone: str) -> None:
    result = _day(
        [(9, 0, "IN"), (13, 0, "OUT")],
        timezone=zone,
        policy=_policy(grace_in_minutes=10, grace_out_minutes=10),
        **FOUR_HOURS,
    )
    assert result.attendance_status == "PRESENT"


# --- publication requires a PRESENT band ---


def _rows(*statuses: str) -> list[Any]:
    return [SimpleNamespace(result_status=s) for s in statuses]


def test_a_version_with_a_present_band_is_accepted() -> None:
    _validate_hour_bands_have_present(_rows("ABSENT", "HALF_DAY", "PRESENT"))
    _validate_hour_bands_have_present(_rows("PRESENT"))
    _validate_hour_bands_have_present([])  # "at least one band" is another check's message


@pytest.mark.parametrize(
    "statuses", [("ABSENT", "HALF_DAY"), ("ABSENT",), ("HALF_DAY", "HALF_DAY")]
)
def test_a_version_without_a_present_band_is_refused(statuses: tuple[str, ...]) -> None:
    with pytest.raises(InvalidPolicyBandError) as raised:
        _validate_hour_bands_have_present(_rows(*statuses))
    assert "PRESENT" in str(raised.value.details[0]["message"])
    assert raised.value.details[0]["field"] == "hour_bands"
