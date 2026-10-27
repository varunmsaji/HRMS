"""Unit tests for the range classifier and the guided-setup schemas. No database."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from hrms.modules.organisation.calendar_resolution import (
    MAX_CALENDAR_RANGE_DAYS,
    CalendarExceptionData,
    CalendarRangeInvalidError,
    HolidayData,
    WeeklyOffRuleData,
    classify_date_range,
    classify_work_calendar_date,
    validate_calendar_range,
)
from hrms.modules.organisation.calendar_setup import (
    SUGGESTED_WEEKLY_OFF_WEEKDAYS,
    WorkCalendarSetupConfig,
    WorkCalendarSetupConfirmRequest,
)


def _off(weekday: int) -> WeeklyOffRuleData:
    return WeeklyOffRuleData(
        weekday=weekday,
        nth_in_month=None,
        cycle_start_date=None,
        off_fraction=Decimal("1.00"),
        week_parity=None,
    )


def test_range_matches_single_date_classifier_for_every_day() -> None:
    holidays = [
        [
            HolidayData(date=date(2026, 8, 15), name="Independence Day", holiday_type="PUBLIC"),
            HolidayData(date=date(2026, 8, 20), name="Fest", holiday_type="OPTIONAL"),
        ]
    ]
    exceptions = {date(2026, 8, 22): CalendarExceptionData("SPECIAL_WORKING", "Catch-up")}
    rules = [_off(5), _off(6)]
    start, end = date(2026, 8, 1), date(2026, 8, 31)

    ranged = classify_date_range(
        start=start,
        end=end,
        ordered_holiday_lists=holidays,
        weekly_off_rules=rules,
        restricted_holidays_are_off_by_default=False,
        exception_by_date=exceptions,
    )

    assert len(ranged) == 31
    for item in ranged:
        single = classify_work_calendar_date(
            target_date=item.date,
            ordered_holiday_lists=holidays,
            weekly_off_rules=rules,
            restricted_holidays_are_off_by_default=False,
            exception=exceptions.get(item.date),
        )
        assert item == single


def test_range_keeps_optional_holiday_a_working_day() -> None:
    days = classify_date_range(
        start=date(2026, 8, 20),
        end=date(2026, 8, 20),
        ordered_holiday_lists=[
            [HolidayData(date=date(2026, 8, 20), name="Fest", holiday_type="OPTIONAL")]
        ],
        weekly_off_rules=[],
        restricted_holidays_are_off_by_default=False,
        exception_by_date={},
    )
    assert days[0].day_type == "WORKING"
    assert days[0].optional_holiday_name == "Fest"


def test_no_calendar_composition_is_all_working_but_only_in_pure_preview() -> None:
    # The pure function is a calculator over a *proposed* composition. The live resolver still
    # fails closed without an assignment (covered by the integration suite).
    days = classify_date_range(
        start=date(2026, 8, 3),
        end=date(2026, 8, 9),
        ordered_holiday_lists=[],
        weekly_off_rules=[_off(5), _off(6)],
        restricted_holidays_are_off_by_default=False,
        exception_by_date={},
    )
    assert [d.day_type for d in days] == ["WORKING"] * 5 + ["WEEKLY_OFF"] * 2


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 8, 10), date(2026, 8, 9)),
        (date(2026, 1, 1), date(2026, 1, 1).replace(year=2027)),
    ],
)
def test_invalid_ranges_are_rejected(start: date, end: date) -> None:
    with pytest.raises(CalendarRangeInvalidError):
        validate_calendar_range(start, end)


def test_range_at_the_limit_is_accepted() -> None:
    start = date(2026, 1, 1)
    end = date.fromordinal(start.toordinal() + MAX_CALENDAR_RANGE_DAYS - 1)
    validate_calendar_range(start, end)
    with pytest.raises(CalendarRangeInvalidError):
        validate_calendar_range(start, date.fromordinal(end.toordinal() + 1))


def test_suggestion_is_saturday_sunday_off() -> None:
    assert SUGGESTED_WEEKLY_OFF_WEEKDAYS == (5, 6)


def test_setup_config_validation() -> None:
    ok = WorkCalendarSetupConfig(weekly_off_weekdays=[6, 5], effective_from=date(2026, 9, 1))
    assert ok.weekly_off_weekdays == [5, 6]
    for bad in ([7], [-1], [5, 5], [0, 1, 2, 3, 4, 5, 6]):
        with pytest.raises(PydanticValidationError):
            WorkCalendarSetupConfig(weekly_off_weekdays=bad, effective_from=date(2026, 9, 1))
    with pytest.raises(PydanticValidationError):
        WorkCalendarSetupConfig(effective_from=date(2026, 9, 1), company_id="x")  # type: ignore[call-arg]


def test_confirm_requires_explicit_true() -> None:
    base = {"name": "Head office", "effective_from": date(2026, 9, 1)}
    WorkCalendarSetupConfirmRequest(**base, confirm=True)
    with pytest.raises(PydanticValidationError):
        WorkCalendarSetupConfirmRequest(**base)  # type: ignore[arg-type]
    with pytest.raises(PydanticValidationError):
        WorkCalendarSetupConfirmRequest(**base, confirm=False)  # type: ignore[arg-type]
