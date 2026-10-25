"""Email copy for the identity module — same `(subject, html_body, text_body)` shape as
`onboarding.email_templates`/`account_invite.email_templates`."""

from hrms.core.links import mobile_html as _mobile_html
from hrms.core.links import mobile_text as _mobile_text


def build_email_verification_email(
    *, first_name: str | None, verify_url: str, mobile_url: str | None = None
) -> tuple[str, str, str]:
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    subject = "Verify your email address"
    text_body = (
        f"{greeting}\n\n"
        "Welcome to HRMS. Please confirm this is your email address by using the secure link "
        f"below:\n\n{verify_url}{_mobile_text(mobile_url)}\n\n"
        "This link is personal to you and expires soon — please don't forward it. If you didn't "
        "create this account, you can safely ignore this email."
    )
    html_body = (
        f"<p>{greeting}</p>"
        "<p>Welcome to HRMS. Please confirm this is your email address by using the secure link "
        f'below:</p><p><a href="{verify_url}">{verify_url}</a></p>{_mobile_html(mobile_url)}'
        "<p>This link is personal to you and expires soon — please don't forward it. If you "
        "didn't create this account, you can safely ignore this email.</p>"
    )
    return subject, html_body, text_body


def build_password_reset_email(
    *, first_name: str | None, reset_url: str, mobile_url: str | None = None
) -> tuple[str, str, str]:
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    subject = "Reset your password"
    text_body = (
        f"{greeting}\n\n"
        f"We received a request to reset your password. Use the secure link below to choose a "
        f"new one:\n\n{reset_url}{_mobile_text(mobile_url)}\n\n"
        "This link is personal to you and expires soon — please don't forward it. If you didn't "
        "request this, you can safely ignore this email; your password will not be changed."
    )
    html_body = (
        f"<p>{greeting}</p>"
        "<p>We received a request to reset your password. Use the secure link below to choose a "
        f'new one:</p><p><a href="{reset_url}">{reset_url}</a></p>{_mobile_html(mobile_url)}'
        "<p>This link is personal to you and expires soon — please don't forward it. If you "
        "didn't request this, you can safely ignore this email; your password will not be "
        "changed.</p>"
    )
    return subject, html_body, text_body
