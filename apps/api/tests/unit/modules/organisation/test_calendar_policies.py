"""Work Calendar phase 4 - pure policy tests (no database).

Policy A  one interpretation of the weekly-off fraction (`weekly_off_fraction_of`,
          `working_fraction_of`)
Policy B  a holiday on a weekly off never creates a substitute; only an explicit exception does
Policy C  `Holiday.is_working` mirrors `holiday_type == WORKING_HOLIDAY`
Policy D  a holiday calendar's validity window (inclusive both ends) decides whether its
          holidays apply
"""

from datetime import date
from decimal import Decimal

import pytest

from hrms.modules.organisation.calendar_resolution import (
    CalendarExceptionData,
    HolidayData,
    HolidayIsWorkingConflictError,
    WeeklyOffRuleData,
    classify_work_calendar_date,
    reconcile_holiday_is_working,
    weekly_off_fraction_of,
    working_fraction_of,
)
from hrms.modules.organisation.schemas import DayTypeRead

SAT = date(2026, 9, 5)  # Saturday
SUN = date(2026, 9, 6)
WED = date(2026, 9, 9)
THU = date(2026, 9, 10)


def _rule(weekday: int, fraction: str = "1.00") -> WeeklyOffRuleData:
    return WeeklyOffRuleData(
        weekday=weekday,
        nth_in_month=None,
        cycle_start_date=None,
        off_fraction=Decimal(fraction),
        week_parity=None,
    )


def _classify(
    target: date,
    *,
    holidays: list[list[HolidayData]] | None = None,
    rules: list[WeeklyOffRuleData] | None = None,
    exception: CalendarExceptionData | None = None,
    restricted_off: bool = False,
) -> DayTypeRead:
    return classify_work_calendar_date(
        target_date=target,
        ordered_holiday_lists=holidays or [],
        weekly_off_rules=rules or [],
        restricted_holidays_are_off_by_default=restricted_off,
        exception=exception,
    )


def _holiday(day: date, name: str = "H", holiday_type: str = "PUBLIC", **extra) -> HolidayData:
    return HolidayData(date=day, name=name, holiday_type=holiday_type, **extra)


# ---------------------------------------------------------------------------
# Policy A - one interpretation of the weekly-off fraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rules", "target", "off", "working"),
    [
        ([_rule(6, "1.00")], SUN, "1.00", "0.00"),  # full weekly off
        ([_rule(5, "0.50")], SAT, "0.50", "0.50"),  # half-day weekly off
        ([_rule(6, "1.00")], WED, None, "1.00"),  # ordinary working day
    ],
)
def test_off_and_working_fractions_are_complementary(rules, target, off, working) -> None:
    day = _classify(target, rules=rules)
    assert working_fraction_of(day) == Decimal(working)
    if off is not None:
        assert day.day_type == "WEEKLY_OFF"
        assert weekly_off_fraction_of(day) == Decimal(off)
        assert weekly_off_fraction_of(day) + working_fraction_of(day) == Decimal("1.00")


def test_unset_weekly_off_fraction_means_a_full_day_off() -> None:
    # A holiday on a half-day weekly off covers the working half too (WD-05): fraction unset.
    day = _classify(SAT, rules=[_rule(5, "0.50")], holidays=[[_holiday(SAT)]])
    assert day.day_type == "WEEKLY_OFF" and day.weekly_off_fraction is None
    assert weekly_off_fraction_of(day) == Decimal("1.00")
    assert working_fraction_of(day) == Decimal("0.00")


@pytest.mark.parametrize(
    ("exception_type", "working"),
    [("SPECIAL_WORKING", "1.00"), ("SHUTDOWN", "0.00"), ("SUBSTITUTE_HOLIDAY", "0.00")],
)
def test_working_fraction_for_exception_days(exception_type: str, working: str) -> None:
    day = _classify(WED, exception=CalendarExceptionData(exception_type, "x"))
    assert working_fraction_of(day) == Decimal(working)


def test_holiday_and_working_holiday_working_fractions() -> None:
    assert working_fraction_of(_classify(WED, holidays=[[_holiday(WED)]])) == Decimal("0.00")
    working_holiday = _classify(WED, holidays=[[_holiday(WED, holiday_type="WORKING_HOLIDAY")]])
    assert working_holiday.day_type == "WORKING"
    assert working_fraction_of(working_holiday) == Decimal("1.00")


def test_half_day_weekly_off_with_optional_holiday_keeps_the_fraction() -> None:
    day = _classify(
        SAT, rules=[_rule(5, "0.50")], holidays=[[_holiday(SAT, holiday_type="OPTIONAL")]]
    )
    assert day.day_type == "WEEKLY_OFF" and day.weekly_off_fraction == Decimal("0.50")
    assert working_fraction_of(day) == Decimal("0.50")


# ---------------------------------------------------------------------------
# Policy B - no automatic substitute holiday
# ---------------------------------------------------------------------------


def test_holiday_on_full_weekly_off_stays_weekly_off_and_creates_no_substitute() -> None:
    holidays = [[_holiday(SUN, "Diwali")]]
    rules = [_rule(6)]
    on_off = _classify(SUN, holidays=holidays, rules=rules)
    assert (on_off.day_type, on_off.holiday_on_weekly_off, on_off.holiday_name) == (
        "WEEKLY_OFF",
        True,
        "Diwali",
    )
    # No other date of the surrounding fortnight becomes a holiday or a day off by itself.
    for offset in range(-7, 8):
        day = date.fromordinal(SUN.toordinal() + offset)
        if day == SUN:
            continue
        result = _classify(day, holidays=holidays, rules=rules)
        assert result.day_type == ("WEEKLY_OFF" if day.weekday() == 6 else "WORKING"), day


def test_holiday_on_half_day_weekly_off_stays_weekly_off_without_substitute() -> None:
    day = _classify(SAT, holidays=[[_holiday(SAT, "Fair")]], rules=[_rule(5, "0.50")])
    assert day.day_type == "WEEKLY_OFF" and day.holiday_on_weekly_off is True
    assert _classify(
        date(2026, 9, 4), holidays=[[_holiday(SAT)]], rules=[_rule(5, "0.50")]
    ).day_type == ("WORKING")


def test_explicit_substitute_exception_on_another_date_is_the_only_substitute() -> None:
    holidays = [[_holiday(SUN, "Diwali")]]
    rules = [_rule(6)]
    substitute = CalendarExceptionData("SUBSTITUTE_HOLIDAY", "Diwali (substitute)")
    on_monday = _classify(date(2026, 9, 7), holidays=holidays, rules=rules, exception=substitute)
    assert on_monday.day_type == "HOLIDAY"
    assert on_monday.exception_type == "SUBSTITUTE_HOLIDAY"
    assert on_monday.holiday_type == "SUBSTITUTE" and on_monday.holiday_is_paid is True
    # The original date is unchanged by the substitute.
    assert _classify(SUN, holidays=holidays, rules=rules).day_type == "WEEKLY_OFF"


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (CalendarExceptionData("SPECIAL_WORKING", "Inventory"), "SPECIAL_WORKING"),
        (CalendarExceptionData("SHUTDOWN", "Plant"), "SHUTDOWN"),
        (CalendarExceptionData("SUBSTITUTE_HOLIDAY", "Sub"), "HOLIDAY"),
        (CalendarExceptionData("CANCEL_HOLIDAY", "Cancelled"), "WORKING"),
    ],
)
def test_exception_overrides_an_overlapping_holiday(exception, expected) -> None:
    assert _classify(WED, holidays=[[_holiday(WED)]], exception=exception).day_type == expected


def test_cancel_holiday_on_a_weekly_off_falls_back_to_the_weekly_off_fraction() -> None:
    day = _classify(
        SAT,
        holidays=[[_holiday(SAT)]],
        rules=[_rule(5, "0.50")],
        exception=CalendarExceptionData("CANCEL_HOLIDAY", "Cancelled"),
    )
    assert day.day_type == "WEEKLY_OFF" and day.weekly_off_fraction == Decimal("0.50")
    assert day.holiday_on_weekly_off is False


def test_first_linked_calendar_wins_overlapping_holidays() -> None:
    day = _classify(WED, holidays=[[_holiday(WED, "National")], [_holiday(WED, "Company")]])
    assert day.holiday_name == "National"


# ---------------------------------------------------------------------------
# Policy C - Holiday.is_working
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("holiday_type", "is_working", "explicit", "outcome"),
    [
        ("PUBLIC", False, False, False),
        ("PUBLIC", False, True, False),
        ("PUBLIC", True, False, False),  # not stated explicitly -> implied value
        ("PUBLIC", True, True, "conflict"),
        ("OPTIONAL", True, True, "conflict"),
        ("WORKING_HOLIDAY", False, False, True),  # omitted -> mirrors the type
        ("WORKING_HOLIDAY", True, True, True),
        ("WORKING_HOLIDAY", False, True, "conflict"),
    ],
)
def test_is_working_mirrors_the_working_holiday_type(
    holiday_type, is_working, explicit, outcome
) -> None:
    if outcome == "conflict":
        with pytest.raises(HolidayIsWorkingConflictError) as info:
            reconcile_holiday_is_working(
                holiday_type=holiday_type, is_working=is_working, explicit=explicit
            )
        assert info.value.code == "HOLIDAY_IS_WORKING_CONFLICT"
    else:
        assert (
            reconcile_holiday_is_working(
                holiday_type=holiday_type, is_working=is_working, explicit=explicit
            )
            is outcome
        )


def test_a_working_holiday_keeps_the_day_working_and_named() -> None:
    day = _classify(WED, holidays=[[_holiday(WED, "Diwali shift", "WORKING_HOLIDAY")]])
    assert (day.day_type, day.holiday_name, day.is_holiday_named) == (
        "WORKING",
        "Diwali shift",
        True,
    )


def test_a_working_holiday_on_a_weekly_off_date_makes_it_a_working_day() -> None:
    """Existing precedence, pinned (not changed): a matched WORKING_HOLIDAY is returned before the
    weekly-off check, so it is the way to say "this weekly-off date is worked and named"."""
    day = _classify(SUN, holidays=[[_holiday(SUN, "x", "WORKING_HOLIDAY")]], rules=[_rule(6)])
    assert (day.day_type, day.holiday_name) == ("WORKING", "x")
    # A cancelling/other exception still outranks it.
    shut = _classify(
        SUN,
        holidays=[[_holiday(SUN, "x", "WORKING_HOLIDAY")]],
        rules=[_rule(6)],
        exception=CalendarExceptionData("SHUTDOWN", "s"),
    )
    assert shut.day_type == "SHUTDOWN"


# ---------------------------------------------------------------------------
# Policy D - holiday-calendar validity window
# ---------------------------------------------------------------------------

_FROM = date(2026, 9, 8)
_TO = date(2026, 9, 12)


def _windowed(
    day: date, valid_from: date | None = _FROM, valid_to: date | None = _TO
) -> HolidayData:
    return _holiday(day, "W", calendar_valid_from=valid_from, calendar_valid_to=valid_to)


@pytest.mark.parametrize(
    ("day", "applies"),
    [
        (date(2026, 9, 7), False),  # the day before validity starts
        (date(2026, 9, 8), True),  # the first valid date (inclusive)
        (date(2026, 9, 10), True),
        (date(2026, 9, 12), True),  # the last valid date (inclusive)
        (date(2026, 9, 13), False),  # the day after validity ends
    ],
)
def test_validity_window_boundaries_are_inclusive(day: date, applies: bool) -> None:
    result = _classify(day, holidays=[[_windowed(day)]])
    assert (result.day_type == "HOLIDAY") is applies


@pytest.mark.parametrize(
    ("valid_from", "valid_to", "day", "applies"),
    [
        (None, None, date(2020, 1, 1), True),  # fully open
        (None, _TO, date(2000, 1, 1), True),  # open start
        (None, _TO, date(2026, 9, 13), False),
        (_FROM, None, date(2099, 1, 1), True),  # open end
        (_FROM, None, date(2026, 9, 7), False),
        (date(2026, 9, 10), date(2026, 9, 9), date(2026, 9, 9), False),  # inverted: nothing
    ],
)
def test_open_ended_and_inverted_windows(valid_from, valid_to, day, applies) -> None:
    result = _classify(day, holidays=[[_windowed(day, valid_from, valid_to)]])
    assert (result.day_type == "HOLIDAY") is applies


def test_holiday_outside_validity_does_not_hide_the_weekly_off_or_working_day() -> None:
    outside = _windowed(SUN, valid_from=date(2027, 1, 1), valid_to=None)
    day = _classify(SUN, holidays=[[outside]], rules=[_rule(6)])
    assert day.day_type == "WEEKLY_OFF" and day.holiday_on_weekly_off is False
    assert _classify(WED, holidays=[[_windowed(WED, date(2027, 1, 1), None)]]).day_type == "WORKING"


def test_overlapping_calendars_fall_through_to_the_one_whose_window_applies() -> None:
    expired_first = _windowed(WED, valid_from=None, valid_to=date(2026, 9, 1))
    current_second = _holiday(WED, "Current", calendar_valid_from=None, calendar_valid_to=None)
    day = _classify(WED, holidays=[[expired_first], [current_second]])
    assert (day.day_type, day.holiday_name) == ("HOLIDAY", "Current")
    # Both inside their windows: the first still wins, as before.
    both = _classify(WED, holidays=[[_windowed(WED, None, None)], [current_second]])
    assert both.holiday_name == "W"


def test_validity_applies_to_exception_free_working_holiday_types_too() -> None:
    outside = _holiday(
        WED, "WH", "WORKING_HOLIDAY", calendar_valid_from=date(2027, 1, 1), calendar_valid_to=None
    )
    assert _classify(WED, holidays=[[outside]]).is_holiday_named is False
