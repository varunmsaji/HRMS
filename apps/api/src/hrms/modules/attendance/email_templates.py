"""Email copy for the attendance module — same `(subject, html_body, text_body)` shape as
`onboarding.email_templates`/`identity.email_templates`."""

from datetime import date
from html import escape


def _format_date(value: date) -> str:
    return value.strftime("%a %d %b %Y")


def build_face_enrollment_requested_email(
    *, first_name: str | None, company_name: str, expires_at: str, app_url: str
) -> tuple[str, str, str]:
    """HR opened a face-enrollment window for this employee. Carries no token, photo or score:
    the employee signs in and the server decides whether enrollment is still available."""
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    subject = "Face Enrollment Requested"
    intro = f"{company_name} has requested that you complete face enrollment for face attendance."
    when = f"Please complete it before {expires_at}."
    how = "Sign in to your HRMS account and open Face Attendance Setup to get started."
    text_body = f"{greeting}\n\n{intro}\n\n{when}\n\n{how}\n\n{app_url}"
    html_body = (
        f"<p>{escape(greeting)}</p><p>{escape(intro)}</p><p>{escape(when)}</p>"
        f'<p>{escape(how)}</p><p><a href="{escape(app_url)}">{escape(app_url)}</a></p>'
    )
    return subject, html_body, text_body


def build_incomplete_days_reminder_email(
    *,
    first_name: str | None,
    period_label: str,
    period_end: date,
    incomplete_dates: list[date],
    regularizations_url: str,
) -> tuple[str, str, str]:
    """PAY-006 — to an employee with unresolved INCOMPLETE days in an open period."""
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    count = len(incomplete_dates)
    noun = "day" if count == 1 else "days"
    subject = f"Action needed: {count} attendance {noun} with a missing punch"
    lines = [_format_date(d) for d in incomplete_dates]
    intro = (
        f"Your attendance for {period_label} (closes after {_format_date(period_end)}) has "
        f"{count} {noun} with a missing punch:"
    )
    outro = (
        "Please submit a regularization request for each of these days before the period is "
        "closed. Days still incomplete at close may be treated as absent (loss of pay)."
    )
    text_body = (
        f"{greeting}\n\n{intro}\n\n"
        + "\n".join(f"  - {line}" for line in lines)
        + f"\n\n{outro}\n\n{regularizations_url}"
    )
    html_body = (
        f"<p>{escape(greeting)}</p><p>{escape(intro)}</p><ul>"
        + "".join(f"<li>{escape(line)}</li>" for line in lines)
        + f"</ul><p>{escape(outro)}</p>"
        f'<p><a href="{escape(regularizations_url)}">Submit a regularization</a></p>'
    )
    return subject, html_body, text_body


def build_incomplete_days_hr_digest_email(
    *,
    period_label: str,
    period_end: date,
    employee_count: int,
    incomplete_day_count: int,
    employees_without_email: int,
    period_url: str,
    no_punch_day_count: int = 0,
) -> tuple[str, str, str]:
    """PAY-006 — to users who can close the period (`ATTENDANCE.LOCK`). H-02: it says how many of
    the days had no punches at all (counted as absent at close whatever the policy says) and that a
    day with a punch - an IN-only day included - follows the policy, so "count as present" pays
    it."""
    subject = f"{period_label}: {incomplete_day_count} incomplete attendance days to resolve"
    summary = (
        f"{employee_count} employees have {incomplete_day_count} incomplete attendance days "
        f"in {period_label} (ends {_format_date(period_end)}). They have been reminded to "
        "regularize them."
    )
    unreachable = (
        f"{employees_without_email} of them have no login email and could not be reminded."
        if employees_without_email
        else ""
    )
    no_punch = (
        f"{no_punch_day_count} of them have no punches at all and will be counted as absent when "
        "the period is closed, whatever the policy says."
        if no_punch_day_count
        else ""
    )
    outro = (
        "Days with at least one punch (a day with only an IN punch included) are resolved per the "
        "attendance policy when the period is closed: where the policy says to count them as "
        "present, such a day is paid in full."
    )
    text_body = "\n\n".join(
        part for part in (summary, unreachable, no_punch, outro, period_url) if part
    )
    html_body = (
        f"<p>{escape(summary)}</p>"
        + (f"<p>{escape(unreachable)}</p>" if unreachable else "")
        + (f"<p>{escape(no_punch)}</p>" if no_punch else "")
        + f"<p>{escape(outro)}</p>"
        f'<p><a href="{escape(period_url)}">Open the attendance period</a></p>'
    )
    return subject, html_body, text_body


def _names(names: list[str], limit: int = 10) -> str:
    """`Asha, Bala and 3 more`: a long list stays one line and never grows the email unboundedly."""
    shown = names[:limit]
    more = len(names) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


def build_manager_daily_digest_email(
    *,
    first_name: str | None,
    day: date,
    team_size: int,
    absent: list[str],
    not_in_yet: list[str],
    late: list[str],
    missing_punch: list[str],
    pending_regularizations: int,
    pending_overtime: int,
    app_url: str,
) -> tuple[str, str, str]:
    """Weekday digest to a manager: what in their direct reports' day needs a look. Names are the
    reports' own, never anyone outside the team."""
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    noteworthy = len(absent) + len(not_in_yet) + len(late) + len(missing_punch)
    subject = f"Team attendance, {_format_date(day)}: {noteworthy} to look at"
    intro = f"Here is how your team of {team_size} is doing on {_format_date(day)}."
    sections: list[tuple[str, str]] = []
    if absent:
        sections.append((f"Absent ({len(absent)})", _names(absent)))
    if not_in_yet:
        sections.append((f"Not checked in yet ({len(not_in_yet)})", _names(not_in_yet)))
    if late:
        sections.append((f"Late ({len(late)})", _names(late)))
    if missing_punch:
        sections.append((f"Missing a punch ({len(missing_punch)})", _names(missing_punch)))
    waiting: list[str] = []
    if pending_regularizations:
        noun = (
            "regularization request" if pending_regularizations == 1 else "regularization requests"
        )
        waiting.append(f"{pending_regularizations} {noun}")
    if pending_overtime:
        waiting.append(
            f"{pending_overtime} overtime {'record' if pending_overtime == 1 else 'records'}"
        )
    if waiting:
        sections.append(("Waiting for a decision", " and ".join(waiting)))
    outro = "Open the attendance page for the details and to act on them."
    text_body = (
        f"{greeting}\n\n{intro}\n\n"
        + "\n".join(f"{title}: {body}" for title, body in sections)
        + f"\n\n{outro}\n\n{app_url}"
    )
    html_body = (
        f"<p>{escape(greeting)}</p><p>{escape(intro)}</p><ul>"
        + "".join(f"<li><strong>{escape(t)}:</strong> {escape(b)}</li>" for t, b in sections)
        + f"</ul><p>{escape(outro)}</p>"
        f'<p><a href="{escape(app_url)}">Open attendance</a></p>'
    )
    return subject, html_body, text_body


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def build_hr_weekly_digest_email(
    *,
    week_from: date,
    week_to: date,
    rate: float | None,
    previous_rate: float | None,
    absent_days: int,
    leave_days: int,
    late_arrivals: int,
    on_time_rate: float | None,
    frequent_late: list[str],
    pending_regularizations: int,
    pending_overtime: int,
    app_url: str,
    patterns: list[str] | None = None,
) -> tuple[str, str, str]:
    """Monday digest to people who see the whole company: last week against the week before."""
    span = f"{_format_date(week_from)} to {_format_date(week_to)}"
    subject = f"Attendance last week: {_pct(rate)}"
    if rate is not None and previous_rate is not None:
        change = rate - previous_rate
        direction = "up" if change > 0 else "down"
        trend = (
            f"{abs(change):.1f} points {direction} on the week before ({_pct(previous_rate)})."
            if abs(change) >= 0.05
            else f"Level with the week before ({_pct(previous_rate)})."
        )
    else:
        trend = "There is no earlier week to compare with."
    lines = [
        f"Attendance rate: {_pct(rate)}. {trend}",
        f"Absent days: {absent_days}. Leave days: {leave_days}.",
        f"Late arrivals: {late_arrivals} (on time {_pct(on_time_rate)} of complete days).",
    ]
    if frequent_late:
        lines.append(f"Late more than once: {_names(frequent_late, 5)}.")
    if patterns:
        lines.append(f"Patterns to look at: {_names(patterns, 5)}.")
    lines.append(
        f"Waiting for a decision: {pending_regularizations} regularization "
        f"{'request' if pending_regularizations == 1 else 'requests'}, "
        f"{pending_overtime} overtime {'record' if pending_overtime == 1 else 'records'}."
    )
    intro = f"Company attendance for {span}."
    text_body = f"{intro}\n\n" + "\n".join(lines) + f"\n\n{app_url}"
    html_body = (
        f"<p>{escape(intro)}</p><ul>"
        + "".join(f"<li>{escape(line)}</li>" for line in lines)
        + f'</ul><p><a href="{escape(app_url)}">Open attendance</a></p>'
    )
    return subject, html_body, text_body
