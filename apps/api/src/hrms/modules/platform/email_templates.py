"""Plain notifications to a company's admin about a platform decision. No links or tokens; the
platform's reason text is the only free text and is escaped for the HTML copy."""

from html import escape

_SUBJECTS = {
    "approved": "Your company has been approved",
    "rejected": "Your company registration was not approved",
    "suspended": "Your company has been suspended",
    "reactivated": "Your company has been reactivated",
    "terminated": "Your company account has been closed",
}

_BODIES = {
    "approved": "Your company {company} has been approved. You now have full access.",
    "rejected": "Your registration for {company} was not approved.",
    "suspended": (
        "Your company {company} has been suspended. Your team can still view data, but changes "
        "are disabled until it is reactivated."
    ),
    "reactivated": "Your company {company} has been reactivated. Full access is restored.",
    "terminated": (
        "Your company {company} has been closed. Its data is retained until {retention} and "
        "cannot be accessed in the meantime."
    ),
}


def build_status_email(
    *,
    event: str,
    first_name: str | None,
    company_name: str,
    reason: str | None,
    retention_until: str | None = None,
) -> tuple[str, str, str]:
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    body = _BODIES[event].format(
        company=company_name, retention=retention_until or "the retention date"
    )
    reason_line = f"Reason: {reason}" if reason else ""
    text = "\n\n".join(
        p for p in (greeting, body, reason_line, "Contact support if you have questions.") if p
    )
    html = f"<p>{escape(greeting)}</p><p>{escape(body)}</p>"
    if reason_line:
        html += f"<p>{escape(reason_line)}</p>"
    html += "<p>Contact support if you have questions.</p>"
    return _SUBJECTS[event], html, text
