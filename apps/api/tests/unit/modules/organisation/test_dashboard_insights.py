from datetime import date

from hrms.modules.organisation.dashboard_insights import (
    CompanyDashboardInsights,
    KpiComparison,
    LeaveStatistics,
    _next_birthday,
    leave_period,
)


def test_birthday_later_this_year() -> None:
    assert _next_birthday(date(1990, 11, 4), date(2026, 10, 31)) == date(2026, 11, 4)


def test_birthday_today_counts_as_today() -> None:
    assert _next_birthday(date(1990, 10, 31), date(2026, 10, 31)) == date(2026, 10, 31)


def test_birthday_already_passed_rolls_to_next_year() -> None:
    assert _next_birthday(date(1990, 3, 14), date(2026, 10, 31)) == date(2027, 3, 14)


def test_leap_day_birthday_in_non_leap_year_falls_on_28_feb() -> None:
    assert _next_birthday(date(1992, 2, 29), date(2026, 10, 31)) == date(2027, 2, 28)


def test_leave_period_is_the_month_or_year_containing_today() -> None:
    today = date(2026, 2, 15)
    assert leave_period(today, "month") == (date(2026, 2, 1), date(2026, 2, 28))
    assert leave_period(today, "year") == (date(2026, 1, 1), date(2026, 12, 31))
    assert leave_period(date(2024, 2, 15), "month") == (date(2024, 2, 1), date(2024, 2, 29))


def test_empty_insights_are_zero_lists_not_placeholders() -> None:
    today = date(2026, 10, 31)
    start, end = leave_period(today, "month")
    insights = CompanyDashboardInsights(
        today=today,
        kpi_comparison=KpiComparison(
            headcount_prev_month_end=0,
            yesterday=date(2026, 10, 30),
            yesterday_present=0,
            yesterday_on_leave=0,
        ),
        headcount_trend=[],
        leave_statistics=LeaveStatistics(
            scope="month", period_start=start, period_end=end, total_days=0, by_type=[]
        ),
        upcoming_birthdays=[],
        recent_activities=[],
    )
    assert insights.leave_statistics.total_days == 0
    assert insights.upcoming_birthdays == []
    assert insights.recent_activities == []
