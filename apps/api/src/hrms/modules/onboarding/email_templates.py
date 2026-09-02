"""Email copy for the onboarding module (O3) — one function per template, returning
`(subject, html_body, text_body)` so `EmailSender.send` never has to know about template
rendering. Only `build_invite_email` exists yet — `changes-requested` (O6) and `activated` (O7)
templates land alongside the endpoints that first need them (module docstring,
`email_sender.py`)."""


def build_invite_email(
    *, candidate_first_name: str, company_name: str, invite_url: str
) -> tuple[str, str, str]:
    subject = f"Complete your onboarding at {company_name}"
    text_body = (
        f"Hi {candidate_first_name},\n\n"
        f"Welcome to {company_name}! Please complete your onboarding details using the secure "
        f"link below:\n\n{invite_url}\n\n"
        "This link is personal to you — please don't forward it. If you weren't expecting this "
        "email, you can safely ignore it."
    )
    html_body = (
        f"<p>Hi {candidate_first_name},</p>"
        f"<p>Welcome to <strong>{company_name}</strong>! Please complete your onboarding details "
        f'using the secure link below:</p><p><a href="{invite_url}">{invite_url}</a></p>'
        "<p>This link is personal to you — please don't forward it. If you weren't expecting this "
        "email, you can safely ignore it.</p>"
    )
    return subject, html_body, text_body
