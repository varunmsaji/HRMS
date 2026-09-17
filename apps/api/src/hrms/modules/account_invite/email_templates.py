"""Email copy for the account-invite module — one function per template, same
`(subject, html_body, text_body)` shape as `onboarding.email_templates`."""


def build_account_invite_email(
    *, first_name: str | None, company_name: str, invite_url: str
) -> tuple[str, str, str]:
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    subject = f"You've been invited to {company_name} on HRMS"
    text_body = (
        f"{greeting}\n\n"
        f"You've been invited to create your login for {company_name}. Set your password using "
        f"the secure link below:\n\n{invite_url}\n\n"
        "This link is personal to you — please don't forward it. If you weren't expecting this "
        "email, you can safely ignore it."
    )
    html_body = (
        f"<p>{greeting}</p>"
        f"<p>You've been invited to create your login for <strong>{company_name}</strong>. Set "
        f'your password using the secure link below:</p><p><a href="{invite_url}">{invite_url}'
        "</a></p>"
        "<p>This link is personal to you — please don't forward it. If you weren't expecting this "
        "email, you can safely ignore it.</p>"
    )
    return subject, html_body, text_body
