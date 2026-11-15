"""Email copy for the onboarding module — one function per template, returning
`(subject, html_body, text_body)` so `EmailSender.send` never has to know about template
rendering. `build_invite_email` (O3), `build_changes_requested_email` (O6), and
`build_activated_email` (O7) — the plan's own three templates, each landing alongside the
endpoint that first needed it."""

from html import escape as _e

from hrms.core.links import mobile_html as _mobile_html
from hrms.core.links import mobile_text as _mobile_text
from hrms.modules.account_invite.email_templates import (
    LoginDetails,
    login_details_html,
    login_details_text,
)


def build_invite_email(
    *, candidate_first_name: str, company_name: str, invite_url: str, mobile_url: str | None = None
) -> tuple[str, str, str]:
    subject = f"Complete your onboarding at {company_name}"
    text_body = (
        f"Hi {candidate_first_name},\n\n"
        f"Welcome to {company_name}! Please complete your onboarding details using the secure "
        f"link below:\n\n{invite_url}{_mobile_text(mobile_url)}\n\n"
        "This link is personal to you — please don't forward it. If you weren't expecting this "
        "email, you can safely ignore it."
    )
    html_body = (
        f"<p>Hi {_e(candidate_first_name)},</p>"
        f"<p>Welcome to <strong>{_e(company_name)}</strong>! Please complete your onboarding "
        f'details using the secure link below:</p><p><a href="{_e(invite_url, quote=True)}">'
        f"{_e(invite_url)}</a></p>"
        f"{_mobile_html(mobile_url)}"
        "<p>This link is personal to you — please don't forward it. If you weren't expecting this "
        "email, you can safely ignore it.</p>"
    )
    return subject, html_body, text_body


def build_changes_requested_email(
    *, candidate_first_name: str, company_name: str, rejected_items: list[tuple[str, str]]
) -> tuple[str, str, str]:
    """`rejected_items` is `(label, reason)` pairs — a section's human-readable label
    (`ONBOARDING_SECTION_LABELS`) or `f"Document: {document_type}"` for a rejected document, paired
    with HR's own rejection reason. Deliberately does not re-include the onboarding link — only
    the token's hash is ever persisted (plan §8.1), so there is no raw link left to resend; the
    original invite email the candidate already has is still valid and still works."""
    subject = f"Action needed: updates requested on your {company_name} onboarding"
    item_lines_text = "\n".join(f"- {label}: {reason}" for label, reason in rejected_items)
    item_lines_html = "".join(
        f"<li><strong>{_e(label)}:</strong> {_e(reason)}</li>" for label, reason in rejected_items
    )
    text_body = (
        f"Hi {candidate_first_name},\n\n"
        f"{company_name}'s HR team has reviewed your onboarding submission and requested a few "
        f"updates before it can be approved:\n\n{item_lines_text}\n\n"
        "Please use the onboarding link you were sent earlier to make these corrections and "
        "resubmit. If you can't find that email, contact HR directly."
    )
    html_body = (
        f"<p>Hi {_e(candidate_first_name)},</p>"
        f"<p><strong>{_e(company_name)}</strong>'s HR team has reviewed your onboarding submission "
        f"and requested a few updates before it can be approved:</p><ul>{item_lines_html}</ul>"
        "<p>Please use the onboarding link you were sent earlier to make these corrections and "
        "resubmit. If you can't find that email, contact HR directly.</p>"
    )
    return subject, html_body, text_body


def build_activated_email(
    *,
    candidate_first_name: str,
    company_name: str,
    employee_code: str,
    login: LoginDetails | None = None,
    set_password_url: str | None = None,
    mobile_url: str | None = None,
    sign_in_url: str | None = None,
) -> tuple[str, str, str]:
    """Sent once activation (O7) has created the real `Employee` row — the one email the new
    employee gets: the welcome, how they sign in (`login`), and the link to set their password
    (`set_password_url`, the account invite issued in the same activation). When no invite could
    be issued (e.g. the address already has an account) it points at `sign_in_url` instead; with
    neither it is a plain welcome notice."""
    subject = (
        f"Welcome to {company_name}! Set up your login"
        if set_password_url
        else f"Welcome to {company_name}!"
    )
    intro_text = (
        f"Hi {candidate_first_name},\n\n"
        f"Your onboarding at {company_name} is complete and your employee record has been "
        f"created (employee code {employee_code}). Welcome aboard!"
    )
    intro_html = (
        f"<p>Hi {_e(candidate_first_name)},</p>"
        f"<p>Your onboarding at <strong>{_e(company_name)}</strong> is complete and your employee "
        f"record has been created (employee code <strong>{_e(employee_code)}</strong>). Welcome "
        "aboard!</p>"
    )
    if set_password_url:
        action_text = (
            "Set your password using the secure link below, then sign in:\n\n"
            f"{set_password_url}{_mobile_text(mobile_url)}"
        )
        action_html = (
            "<p>Set your password using the secure link below, then sign in:</p>"
            f'<p><a href="{_e(set_password_url)}">{_e(set_password_url)}</a></p>'
            f"{_mobile_html(mobile_url)}"
        )
        closing = "This link is personal to you — please don't forward it."
    elif sign_in_url:
        action_text = f"Sign in with your existing password at {sign_in_url}"
        action_html = (
            "<p>Sign in with your existing password at "
            f'<a href="{_e(sign_in_url)}">{_e(sign_in_url)}</a>.</p>'
        )
        closing = "HR will be in touch with any next steps before your start date."
    else:
        action_text = action_html = ""
        closing = "HR will be in touch with any next steps before your start date."

    text_parts = [intro_text]
    html_parts = [intro_html]
    if login is not None:
        text_parts.append(login_details_text(login))
        html_parts.append(login_details_html(login))
    if action_text:
        text_parts.append(action_text)
        html_parts.append(action_html)
    text_parts.append(closing)
    html_parts.append(f"<p>{closing}</p>")
    return subject, "".join(html_parts), "\n\n".join(text_parts)
