"""Unit tests for the Workforce Calendar (W1) resolution engine —
`hrms.modules.organisation.calendar_resolution`. Pure-function tests, no database: every
`classify_work_calendar_date` branch (architecture §6.3/§7.3/§8.2), every `WeeklyOffRule`
evaluation shape (§8.1), and the two open-product-decision defaults (PD-CAL-1, PD-CAL-2)."""

from datetime import date
from decimal import Decimal

from hrms.modules.organisation.calendar_resolution import (
    CalendarExceptionData,
    HolidayData,
    WeeklyOffRuleData,
    classify_work_calendar_date,
    evaluate_weekly_off,
)

# ---------------------------------------------------------------------------
# evaluate_weekly_off — per pattern_kind shape
# ---------------------------------------------------------------------------


def test_fixed_weekdays_every_sunday() -> None:
    rules = [
        WeeklyOffRuleData(
            weekday=6,
            nth_in_month=None,
            cycle_start_date=None,
            off_fraction=Decimal("1.00"),
            week_parity=None,
        )
    ]
    is_off, fraction = evaluate_weekly_off(date(2026, 8, 16), rules)  # a Sunday
    assert is_off is True
    assert fraction == Decimal("1.00")

    is_off, _ = evaluate_weekly_off(date(2026, 8, 17), rules)  # Monday
    assert is_off is False


def test_fixed_weekdays_saturday_and_sunday() -> None:
    rules = [
        WeeklyOffRuleData(
            weekday=5,
            nth_in_month=None,
            cycle_start_date=None,
            off_fraction=Decimal("1.00"),
            week_parity=None,
        ),
        WeeklyOffRuleData(
            weekday=6,
            nth_in_month=None,
            cycle_start_date=None,
            off_fraction=Decimal("1.00"),
            week_parity=None,
        ),
    ]
    assert evaluate_weekly_off(date(2026, 8, 15), rules)[0] is True  # Saturday
    assert evaluate_weekly_off(date(2026, 8, 16), rules)[0] is True  # Sunday
    assert evaluate_weekly_off(date(2026, 8, 17), rules)[0] is False  # Monday


def test_nth_weekday_second_and_fourth_saturday() -> None:
    rules = [
        WeeklyOffRuleData(
            weekday=5,
            nth_in_month=2,
            cycle_start_date=None,
            off_fraction=Decimal("1.00"),
            week_parity=None,
        ),
        WeeklyOffRuleData(
            weekday=5,
            nth_in_month=4,
            cycle_start_date=None,
            off_fraction=Decimal("1.00"),
            week_parity=None,
        ),
    ]
    # August 2026 Saturdays: 1st, 8th, 15th, 22nd, 29th -> 2nd Sat = 8th, 4th Sat = 22nd
    assert evaluate_weekly_off(date(2026, 8, 1), rules)[0] is False
    assert evaluate_weekly_off(date(2026, 8, 8), rules)[0] is True
    assert evaluate_weekly_off(date(2026, 8, 15), rules)[0] is False
    assert evaluate_weekly_off(date(2026, 8, 22), rules)[0] is True
    assert evaluate_weekly_off(date(2026, 8, 29), rules)[0] is False


def test_nth_weekday_last_occurrence_in_month() -> None:
    """`nth_in_month=-1` — August 2026 has five Saturdays (1, 8, 15, 22, 29); the last is the
    29th."""
    rules = [
        WeeklyOffRuleData(
            weekday=5,
            nth_in_month=-1,
            cycle_start_date=None,
            off_fraction=Decimal("1.00"),
            week_parity=None,
        )
    ]
    assert evaluate_weekly_off(date(2026, 8, 22), rules)[0] is False
    assert evaluate_weekly_off(date(2026, 8, 29), rules)[0] is True


def test_nth_weekday_last_occurrence_four_saturday_month() -> None:
    """A month with exactly four Saturdays — the 4th Saturday *is* the last one. February
    2026: Saturdays fall on 7, 14, 21, 28 (28 days in the month)."""
    rules = [
        WeeklyOffRuleData(
            weekday=5,
            nth_in_month=-1,
            cycle_start_date=None,
            off_fraction=Decimal("1.00"),
            week_parity=None,
        )
    ]
    assert evaluate_weekly_off(date(2026, 2, 21), rules)[0] is False
    assert evaluate_weekly_off(date(2026, 2, 28), rules)[0] is True


def test_alternate_saturday_parity_across_year_boundary() -> None:
    """Alternate Saturday starting 2026-01-03 (a Saturday, week 0/EVEN = off). Verify parity
    holds across the 2026->2027 year boundary — this is the scenario most likely to break a
    naive `.isocalendar()`-based implementation, which is why `_rule_matches` instead computes
    whole weeks elapsed via plain date arithmetic."""
    cycle_start = date(2026, 1, 3)
    rules = [
        WeeklyOffRuleData(
            weekday=5,
            nth_in_month=None,
            cycle_start_date=cycle_start,
            off_fraction=Decimal("1.00"),
            week_parity="EVEN",
        )
    ]
    assert evaluate_weekly_off(date(2026, 1, 3), rules)[0] is True  # week 0 (EVEN) -> off
    assert evaluate_weekly_off(date(2026, 1, 10), rules)[0] is False  # week 1 (ODD) -> working
    assert evaluate_weekly_off(date(2026, 1, 17), rules)[0] is True  # week 2 (EVEN) -> off
    # Cross the year boundary: 2026-12-26 is 51 weeks after 2026-01-03 (ODD) -> working;
    # 2027-01-02 is 52 weeks after (EVEN) -> off.
    assert evaluate_weekly_off(date(2026, 12, 26), rules)[0] is False
    assert evaluate_weekly_off(date(2027, 1, 2), rules)[0] is True


def test_alternate_no_explicit_parity_defaults_to_cycle_start_week_off() -> None:
    """No documented default for a missing `week_parity` on an ALTERNATE rule — the engine
    treats the cycle-start week itself as the off week (the only reading consistent with
    "alternate Saturday starting from this date is off")."""
    rules = [
        WeeklyOffRuleData(
            weekday=5,
            nth_in_month=None,
            cycle_start_date=date(2026, 1, 3),
            off_fraction=Decimal("1.00"),
            week_parity=None,
        )
    ]
    assert evaluate_weekly_off(date(2026, 1, 3), rules)[0] is True
    assert evaluate_weekly_off(date(2026, 1, 10), rules)[0] is False


def test_saturday_half_day_off_fraction() -> None:
    rules = [
        WeeklyOffRuleData(
            weekday=5,
            nth_in_month=None,
            cycle_start_date=None,
            off_fraction=Decimal("0.50"),
            week_parity=None,
        )
    ]
    is_off, fraction = evaluate_weekly_off(date(2026, 8, 15), rules)
    assert is_off is True
    assert fraction == Decimal("0.50")


def test_custom_pattern_combines_rule_shapes() -> None:
    """CUSTOM = the same rule table, any combination — a plain weekday rule (Sunday) plus an
    NTH_WEEKDAY-shaped rule (2nd Saturday) evaluated together."""
    rules = [
        WeeklyOffRuleData(
            weekday=6,
            nth_in_month=None,
            cycle_start_date=None,
            off_fraction=Decimal("1.00"),
            week_parity=None,
        ),
        WeeklyOffRuleData(
            weekday=5,
            nth_in_month=2,
            cycle_start_date=None,
            off_fraction=Decimal("1.00"),
            week_parity=None,
        ),
    ]
    assert evaluate_weekly_off(date(2026, 8, 16), rules)[0] is True  # Sunday
    assert evaluate_weekly_off(date(2026, 8, 8), rules)[0] is True  # 2nd Saturday
    assert evaluate_weekly_off(date(2026, 8, 1), rules)[0] is False  # 1st Saturday


def test_no_rules_never_off() -> None:
    assert evaluate_weekly_off(date(2026, 8, 16), [])[0] is False


# ---------------------------------------------------------------------------
# classify_work_calendar_date — full precedence
# ---------------------------------------------------------------------------

_NO_RULES: list[WeeklyOffRuleData] = []
_SUNDAY_OFF = [
    WeeklyOffRuleData(
        weekday=6,
        nth_in_month=None,
        cycle_start_date=None,
        off_fraction=Decimal("1.00"),
        week_parity=None,
    )
]


def test_plain_working_day() -> None:
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 17),
        ordered_holiday_lists=[],
        weekly_off_rules=_NO_RULES,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert result.day_type == "WORKING"


def test_weekly_off_no_holiday() -> None:
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 16),  # Sunday
        ordered_holiday_lists=[],
        weekly_off_rules=_SUNDAY_OFF,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert result.day_type == "WEEKLY_OFF"
    assert result.holiday_on_weekly_off is False


def test_public_holiday() -> None:
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 15),
        ordered_holiday_lists=[
            [HolidayData(date=date(2026, 8, 15), name="Independence Day", holiday_type="PUBLIC")]
        ],
        weekly_off_rules=_NO_RULES,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert result.day_type == "HOLIDAY"
    assert result.holiday_name == "Independence Day"


def test_holiday_on_weekly_off_wd_05() -> None:
    """WD-05 — a holiday landing on a weekly-off stays WEEKLY_OFF with a flag; the holiday
    itself is still surfaced via `holiday_name`."""
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 16),  # Sunday
        ordered_holiday_lists=[
            [HolidayData(date=date(2026, 8, 16), name="Some Festival", holiday_type="PUBLIC")]
        ],
        weekly_off_rules=_SUNDAY_OFF,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert result.day_type == "WEEKLY_OFF"
    assert result.holiday_on_weekly_off is True
    assert result.holiday_name == "Some Festival"


def test_holiday_on_weekly_off_does_not_auto_substitute_pd_cal_2() -> None:
    """PD-CAL-2 (open product decision) — default is "stay WEEKLY_OFF", no automatic move to
    the next working day. Substitution requires an explicit `SUBSTITUTE_HOLIDAY` +
    `SPECIAL_WORKING` CalendarException pair, which this test does not supply."""
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 16),
        ordered_holiday_lists=[
            [HolidayData(date=date(2026, 8, 16), name="Some Festival", holiday_type="PUBLIC")]
        ],
        weekly_off_rules=_SUNDAY_OFF,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert result.day_type == "WEEKLY_OFF"
    # The following Monday must NOT have become a holiday by any implicit substitution.
    monday_result = classify_work_calendar_date(
        target_date=date(2026, 8, 17),
        ordered_holiday_lists=[
            [HolidayData(date=date(2026, 8, 16), name="Some Festival", holiday_type="PUBLIC")]
        ],
        weekly_off_rules=_SUNDAY_OFF,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert monday_result.day_type == "WORKING"


def test_optional_holiday_defaults_to_working_pd_cal_1() -> None:
    """PD-CAL-1 (open product decision) — default is "working until Leave applies", i.e. an
    OPTIONAL holiday does NOT make the calendar day type HOLIDAY unless the WorkCalendar's
    `restricted_holidays_are_off_by_default` flag says otherwise."""
    result = classify_work_calendar_date(
        target_date=date(2026, 10, 20),
        ordered_holiday_lists=[
            [HolidayData(date=date(2026, 10, 20), name="Karva Chauth", holiday_type="OPTIONAL")]
        ],
        weekly_off_rules=_NO_RULES,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert result.day_type == "WORKING"
    assert result.optional_holiday_name == "Karva Chauth"


def test_optional_holiday_off_by_default_when_calendar_flag_set() -> None:
    """The sanctioned per-company override for PD-CAL-1:
    `restricted_holidays_are_off_by_default=True`."""
    result = classify_work_calendar_date(
        target_date=date(2026, 10, 20),
        ordered_holiday_lists=[
            [HolidayData(date=date(2026, 10, 20), name="Karva Chauth", holiday_type="OPTIONAL")]
        ],
        weekly_off_rules=_NO_RULES,
        restricted_holidays_are_off_by_default=True,
        exception=None,
    )
    assert result.day_type == "HOLIDAY"
    assert result.holiday_name == "Karva Chauth"


def test_restricted_holiday_defaults_to_working() -> None:
    result = classify_work_calendar_date(
        target_date=date(2026, 4, 14),
        ordered_holiday_lists=[
            [
                HolidayData(
                    date=date(2026, 4, 14), name="Ambedkar Jayanti", holiday_type="RESTRICTED"
                )
            ]
        ],
        weekly_off_rules=_NO_RULES,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert result.day_type == "WORKING"
    assert result.restricted_holiday_name == "Ambedkar Jayanti"


def test_working_holiday_stays_working_but_named() -> None:
    result = classify_work_calendar_date(
        target_date=date(2026, 10, 21),
        ordered_holiday_lists=[
            [
                HolidayData(
                    date=date(2026, 10, 21),
                    name="Festival Working Day",
                    holiday_type="WORKING_HOLIDAY",
                )
            ]
        ],
        weekly_off_rules=_NO_RULES,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert result.day_type == "WORKING"
    assert result.is_holiday_named is True
    assert result.holiday_name == "Festival Working Day"


def test_first_calendar_wins_display_name_on_tie() -> None:
    """§6.3 rule 4 — "First HolidayCalendar in the ordered list supplies the display name if
    types otherwise tie." Two calendars both name the same date; the first list's entry wins."""
    result = classify_work_calendar_date(
        target_date=date(2026, 1, 26),
        ordered_holiday_lists=[
            [
                HolidayData(
                    date=date(2026, 1, 26), name="Republic Day (National)", holiday_type="PUBLIC"
                )
            ],
            [
                HolidayData(
                    date=date(2026, 1, 26), name="Republic Day (Regional)", holiday_type="PUBLIC"
                )
            ],
        ],
        weekly_off_rules=_NO_RULES,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert result.holiday_name == "Republic Day (National)"


def test_exception_shutdown_wins_over_working_day() -> None:
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 29),
        ordered_holiday_lists=[],
        weekly_off_rules=_NO_RULES,
        restricted_holidays_are_off_by_default=False,
        exception=CalendarExceptionData(exception_type="SHUTDOWN", name="Office relocation"),
    )
    assert result.day_type == "SHUTDOWN"
    assert result.exception_type == "SHUTDOWN"


def test_exception_special_working_wins_over_weekly_off() -> None:
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 29),  # a Saturday
        ordered_holiday_lists=[],
        weekly_off_rules=[
            WeeklyOffRuleData(
                weekday=5,
                nth_in_month=None,
                cycle_start_date=None,
                off_fraction=Decimal("1.00"),
                week_parity=None,
            )
        ],
        restricted_holidays_are_off_by_default=False,
        exception=CalendarExceptionData(exception_type="SPECIAL_WORKING", name="Company event"),
    )
    assert result.day_type == "SPECIAL_WORKING"


def test_exception_substitute_holiday_creates_a_holiday() -> None:
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 31),
        ordered_holiday_lists=[],
        weekly_off_rules=_NO_RULES,
        restricted_holidays_are_off_by_default=False,
        exception=CalendarExceptionData(
            exception_type="SUBSTITUTE_HOLIDAY", name="Independence Day (observed)"
        ),
    )
    assert result.day_type == "HOLIDAY"
    assert result.holiday_name == "Independence Day (observed)"


def test_exception_cancel_holiday_falls_through_to_working() -> None:
    """`CANCEL_HOLIDAY` removes the holiday for this WorkCalendar only, then the normal
    weekly-off/working check applies underneath it."""
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 15),
        ordered_holiday_lists=[
            [HolidayData(date=date(2026, 8, 15), name="Independence Day", holiday_type="PUBLIC")]
        ],
        weekly_off_rules=_NO_RULES,
        restricted_holidays_are_off_by_default=False,
        exception=CalendarExceptionData(exception_type="CANCEL_HOLIDAY", name=None),
    )
    assert result.day_type == "WORKING"


def test_exception_cancel_holiday_still_weekly_off_underneath() -> None:
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 16),  # Sunday
        ordered_holiday_lists=[
            [HolidayData(date=date(2026, 8, 16), name="Some Festival", holiday_type="PUBLIC")]
        ],
        weekly_off_rules=_SUNDAY_OFF,
        restricted_holidays_are_off_by_default=False,
        exception=CalendarExceptionData(exception_type="CANCEL_HOLIDAY", name=None),
    )
    assert result.day_type == "WEEKLY_OFF"
    assert result.holiday_on_weekly_off is False  # the holiday was cancelled, not just hidden


# ---------------------------------------------------------------------------
# PAY-012 — half-day weekly off fraction carried through classification
# ---------------------------------------------------------------------------

_HALF_SATURDAY = [
    WeeklyOffRuleData(
        weekday=5,
        nth_in_month=None,
        cycle_start_date=None,
        off_fraction=Decimal("0.50"),
        week_parity=None,
    )
]


def test_half_day_weekly_off_carries_its_fraction() -> None:
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 15),  # Saturday
        ordered_holiday_lists=[],
        weekly_off_rules=_HALF_SATURDAY,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert result.day_type == "WEEKLY_OFF"
    assert result.weekly_off_fraction == Decimal("0.50")


def test_hard_holiday_on_half_day_weekly_off_is_a_full_day_off() -> None:
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 15),
        ordered_holiday_lists=[[HolidayData(date(2026, 8, 15), "Independence Day", "NATIONAL")]],
        weekly_off_rules=_HALF_SATURDAY,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert result.day_type == "WEEKLY_OFF"
    assert result.holiday_on_weekly_off is True
    assert result.weekly_off_fraction is None


def test_holiday_carries_type_and_paid_flag() -> None:
    result = classify_work_calendar_date(
        target_date=date(2026, 8, 17),
        ordered_holiday_lists=[[HolidayData(date(2026, 8, 17), "Founders Day", "COMPANY", False)]],
        weekly_off_rules=_NO_RULES,
        restricted_holidays_are_off_by_default=False,
        exception=None,
    )
    assert result.day_type == "HOLIDAY"
    assert result.holiday_type == "COMPANY"
    assert result.holiday_is_paid is False
