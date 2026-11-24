"""The attendance digest emails: what they say, what they cap, and that nothing typed by a person
can inject markup."""

from datetime import date

from hrms.modules.attendance.email_templates import (
    build_hr_weekly_digest_email,
    build_manager_daily_digest_email,
)

DAY = date(2026, 11, 24)


def _manager(**overrides: object) -> tuple[str, str, str]:
    base: dict[str, object] = {
        "first_name": "Chitra",
        "day": DAY,
        "team_size": 6,
        "absent": [],
        "not_in_yet": [],
        "late": [],
        "missing_punch": [],
        "pending_regularizations": 0,
        "pending_overtime": 0,
        "app_url": "https://app.example.com/app/attendance",
    }
    return build_manager_daily_digest_email(**{**base, **overrides})  # type: ignore[arg-type]


def test_manager_digest_lists_only_the_sections_that_have_something() -> None:
    subject, html, text = _manager(absent=["Bala"], late=["Asha", "Dev"], pending_regularizations=1)
    assert subject == "Team attendance, Tue 24 Nov 2026: 3 to look at"
    assert "Absent (1): Bala" in text and "Late (2): Asha, Dev" in text
    assert "Waiting for a decision: 1 regularization request" in text
    assert "Not checked in yet" not in text and "Missing a punch" not in text
    assert "your team of 6" in text and "https://app.example.com/app/attendance" in html


def test_a_long_list_is_cut_to_ten_names_and_says_how_many_more() -> None:
    names = [f"Person {i:02d}" for i in range(14)]
    _, _, text = _manager(absent=names)
    assert "Person 09" in text and "Person 10" not in text
    assert "and 4 more" in text and "Absent (14)" in text


def test_a_name_cannot_inject_markup_into_the_html() -> None:
    _, html, _ = _manager(absent=["<script>alert(1)</script>", 'A & "B"'], first_name="<b>x</b>")
    assert "<script>" not in html and "<b>x</b>" not in html
    assert "&lt;script&gt;" in html and "&amp;" in html


def test_manager_digest_greets_without_a_name() -> None:
    _, _, text = _manager(first_name=None, absent=["Bala"])
    assert text.startswith("Hi,\n")


def _hr(**overrides: object) -> tuple[str, str, str]:
    base: dict[str, object] = {
        "week_from": date(2026, 11, 16),
        "week_to": date(2026, 11, 22),
        "rate": 92.5,
        "previous_rate": 90.0,
        "absent_days": 7,
        "leave_days": 12,
        "late_arrivals": 9,
        "on_time_rate": 88.0,
        "frequent_late": ["Asha"],
        "pending_regularizations": 2,
        "pending_overtime": 1,
        "app_url": "https://app.example.com/app/attendance",
    }
    return build_hr_weekly_digest_email(**{**base, **overrides})  # type: ignore[arg-type]


def test_hr_digest_compares_with_the_week_before() -> None:
    subject, _, text = _hr()
    assert subject == "Attendance last week: 92.5%"
    assert "2.5 points up on the week before (90.0%)" in text
    assert "Absent days: 7. Leave days: 12." in text
    assert "Late more than once: Asha." in text
    assert "2 regularization requests, 1 overtime record" in text


def test_hr_digest_handles_a_drop_a_level_week_and_a_missing_week() -> None:
    assert "1.5 points down" in _hr(rate=88.5, previous_rate=90.0)[2]
    assert "Level with the week before (92.5%)" in _hr(previous_rate=92.5)[2]
    assert "no earlier week to compare with" in _hr(previous_rate=None)[2]
    subject, _, text = _hr(rate=None, previous_rate=None, frequent_late=[])
    assert subject == "Attendance last week: n/a" and "Late more than once" not in text
