"""Email copy for the account-invite module — one function per template, same
`(subject, html_body, text_body)` shape as `onboarding.email_templates`."""

from dataclasses import dataclass
from html import escape as _e

from hrms.core.links import mobile_html as _mobile_html
from hrms.core.links import mobile_text as _mobile_text


@dataclass(frozen=True, slots=True)
class LoginDetails:
    """How an employee signs in: their email, or their company code plus employee ID."""

    email: str
    company_code: str | None = None
    employee_code: str | None = None

    @property
    def has_employee_id(self) -> bool:
        return bool(self.company_code and self.employee_code)


def login_details_text(details: LoginDetails) -> str:
    lines = ["Your login details:", f"  Email: {details.email}"]
    if details.has_employee_id:
        lines += [
            f"  Company code: {details.company_code}",
            f"  Employee ID: {details.employee_code}",
            "",
            "You can sign in with your email, or with your company code and employee ID.",
        ]
    return "\n".join(lines)


def login_details_html(details: LoginDetails) -> str:
    rows = [("Email", details.email)]
    if details.has_employee_id:
        rows += [
            ("Company code", details.company_code or ""),
            ("Employee ID", details.employee_code or ""),
        ]
    items = "".join(f"<li>{label}: <strong>{_e(value)}</strong></li>" for label, value in rows)
    html = f"<p><strong>Your login details</strong></p><ul>{items}</ul>"
    if details.has_employee_id:
        html += "<p>You can sign in with your email, or with your company code and employee ID.</p>"
    return html


def build_account_invite_email(
    *,
    first_name: str | None,
    company_name: str,
    invite_url: str,
    mobile_url: str | None = None,
    login: LoginDetails | None = None,
) -> tuple[str, str, str]:
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    subject = f"You've been invited to {company_name} on HRMS"
    text_body = (
        f"{greeting}\n\n"
        f"You've been invited to create your login for {company_name}. Set your password using "
        f"the secure link below:\n\n{invite_url}{_mobile_text(mobile_url)}\n\n"
        + (f"{login_details_text(login)}\n\n" if login else "")
        + "This link is personal to you — please don't forward it. If you weren't expecting this "
        "email, you can safely ignore it."
    )
    html_body = (
        f"<p>{greeting}</p>"
        f"<p>You've been invited to create your login for <strong>{company_name}</strong>. Set "
        f'your password using the secure link below:</p><p><a href="{invite_url}">{invite_url}'
        f"</a></p>{_mobile_html(mobile_url)}"
        + (login_details_html(login) if login else "")
        + "<p>This link is personal to you — please don't forward it. If you weren't expecting "
        "this email, you can safely ignore it.</p>"
    )
    return subject, html_body, text_body
