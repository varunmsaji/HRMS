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
) -> tuple[str, str, str]:
    """PAY-006 — to users who can close the period (`ATTENDANCE.LOCK`)."""
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
    outro = (
        "Days still incomplete when the period is closed are resolved per the attendance policy."
    )
    text_body = "\n\n".join(part for part in (summary, unreachable, outro, period_url) if part)
    html_body = (
        f"<p>{escape(summary)}</p>"
        + (f"<p>{escape(unreachable)}</p>" if unreachable else "")
        + f"<p>{escape(outro)}</p>"
        f'<p><a href="{escape(period_url)}">Open the attendance period</a></p>'
    )
    return subject, html_body, text_body
