"""H-01 (owner decision): hour bands must cover every worked-minute count.

* Publication refuses hour bands that do not start at minute 0, leave a gap, or end bounded
  (`_validate_hour_band_coverage`). Late-mark and early-departure bands are not subject to it: a
  gap there means "no mark".
* The engine never turns uncovered minutes into a silent PRESENT: it returns `CONFIG_ERROR`, which
  blocks period close until HR publishes a corrected version and the day is recalculated. This is
  what a published version that predates the rule meets.
* Day-off work does not consult the hour bands, so a gapped policy does not block it.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from tests.unit.modules.attendance.test_attendance_rules_remediation import (
    _day,
    _pay,
    _split_day,
)
from tests.unit.modules.attendance.test_calculation import _policy

from hrms.modules.attendance.calculation import BandData
from hrms.modules.attendance.exceptions import InvalidPolicyBandError
from hrms.modules.attendance.service import _validate_bands, _validate_hour_band_coverage


def _bands(*spec: tuple[int, int | None]) -> list[Any]:
    return [SimpleNamespace(min_minutes=lo, max_minutes=hi) for lo, hi in spec]


# --- publication validation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec",
    [
        [(0, None)],  # one open band
        [(0, 239), (240, None)],
        [(0, 239), (240, 479), (480, None)],
        [(480, None), (0, 239), (240, 479)],  # order of storage does not matter
        [(0, 0), (1, 1), (2, None)],  # one-minute bands are contiguous
    ],
)
def test_contiguous_bands_from_zero_to_open_ended_are_accepted(
    spec: list[tuple[int, int | None]],
) -> None:
    _validate_hour_band_coverage(_bands(*spec))
    _validate_bands(_bands(*spec), required=True, field="hour_bands")


def test_no_bands_is_left_to_the_required_check() -> None:
    _validate_hour_band_coverage([])  # `_validate_bands(required=True)` reports "at least one"


@pytest.mark.parametrize(
    ("spec", "fragment"),
    [
        ([(240, None)], "must start at 0 minutes"),
        ([(1, 239), (240, None)], "must start at 0 minutes"),
        ([(0, 239), (300, None)], "minutes 240 to 299 are not covered"),
        ([(0, 100), (102, 200), (201, None)], "minutes 101 to 101 are not covered"),
        ([(0, 239), (240, 479)], "must be open-ended"),
        ([(0, 479)], "must be open-ended"),
    ],
)
def test_gaps_a_missing_start_and_a_bounded_last_band_are_refused(
    spec: list[tuple[int, int | None]], fragment: str
) -> None:
    with pytest.raises(InvalidPolicyBandError) as raised:
        _validate_hour_band_coverage(_bands(*spec))
    assert fragment in str(raised.value.details[0]["message"])
    assert raised.value.details[0]["field"] == "hour_bands"


# --- the engine on a version published before the rule ---

_GAPPED_FROM_240 = [BandData(240, None, "PRESENT")]  # nothing covers 1-239 minutes
_GAP_IN_THE_MIDDLE = [
    BandData(0, 239, "ABSENT"),
    BandData(300, None, "PRESENT"),  # 240-299 uncovered
]


def test_uncovered_minutes_are_a_config_error_not_a_silent_present() -> None:
    result = _day([(10, 0, "IN"), (10, 30, "OUT")], hour_bands=_GAPPED_FROM_240)  # 30 minutes
    assert result.attendance_status == "CONFIG_ERROR"
    assert result.snapshot["terminal_reason"] == "hour_band_not_covered"
    assert result.snapshot["hour_band_gap"]["minutes"] > 0
    assert _pay(result) == ("0.00", "0.00")  # not paid, not LOP: it cannot be classified


def test_a_gap_in_the_middle_is_a_config_error_too() -> None:
    # 09:00-13:00 worked 240 minutes (+ grace credit) lands in 240-299
    result = _day([(9, 0, "IN"), (14, 30, "OUT")], hour_bands=_GAP_IN_THE_MIDDLE)
    assert result.attendance_status == "CONFIG_ERROR"


def test_minutes_inside_a_covered_range_are_unaffected_by_a_gap_elsewhere() -> None:
    covered = _day([(9, 0, "IN"), (18, 0, "OUT")], hour_bands=_GAP_IN_THE_MIDDLE)  # 480 worked
    assert covered.attendance_status == "PRESENT"
    absent = _day([(9, 0, "IN"), (10, 0, "OUT")], hour_bands=_GAP_IN_THE_MIDDLE)  # 60 worked
    assert absent.attendance_status == "ABSENT"


def test_a_zero_punch_day_never_consults_the_bands() -> None:
    result = _day([], hour_bands=_GAPPED_FROM_240)
    assert result.attendance_status != "CONFIG_ERROR"  # no minutes, no lookup


def test_day_off_work_is_not_blocked_by_a_gapped_policy() -> None:
    """Work on a weekly off or holiday is paid as day-off work; it does not use the hour bands."""
    result = _day(
        [(9, 0, "IN"), (9, 30, "OUT")],
        hour_bands=_GAPPED_FROM_240,
        roster_week_off_override=True,
    )
    assert result.attendance_status != "CONFIG_ERROR"


def test_a_split_shift_with_uncovered_minutes_is_a_config_error() -> None:
    # `IGNORE`: no missed-block verdict, so the day reaches the hour-band lookup
    result = _split_day(
        [(9, 0, "IN"), (9, 40, "OUT"), (17, 0, "IN"), (17, 20, "OUT")],
        hour_bands=_GAPPED_FROM_240,
        policy=_policy(
            grace_in_minutes=10,
            grace_out_minutes=10,
            split_shift_missed_block_behaviour="IGNORE",
        ),
    )
    assert result.attendance_status == "CONFIG_ERROR"
    assert result.snapshot["terminal_reason"] == "hour_band_not_covered"


def test_the_standard_bands_still_classify_every_minute_count() -> None:
    """Regression: with contiguous bands there is no CONFIG_ERROR at any length of day."""
    for hours in range(1, 14):
        result = _day([(6, 0, "IN"), (6 + hours, 0, "OUT")])
        assert result.attendance_status in ("ABSENT", "HALF_DAY", "PRESENT"), hours
