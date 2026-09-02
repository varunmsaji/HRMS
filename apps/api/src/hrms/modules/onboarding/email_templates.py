"""Email copy for the onboarding module — one function per template, returning
`(subject, html_body, text_body)` so `EmailSender.send` never has to know about template
rendering. `build_invite_email` (O3), `build_changes_requested_email` (O6), and
`build_activated_email` (O7) — the plan's own three templates, each landing alongside the
endpoint that first needed it."""


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
        f"<li><strong>{label}:</strong> {reason}</li>" for label, reason in rejected_items
    )
    text_body = (
        f"Hi {candidate_first_name},\n\n"
        f"{company_name}'s HR team has reviewed your onboarding submission and requested a few "
        f"updates before it can be approved:\n\n{item_lines_text}\n\n"
        "Please use the onboarding link you were sent earlier to make these corrections and "
        "resubmit. If you can't find that email, contact HR directly."
    )
    html_body = (
        f"<p>Hi {candidate_first_name},</p>"
        f"<p><strong>{company_name}</strong>'s HR team has reviewed your onboarding submission "
        f"and requested a few updates before it can be approved:</p><ul>{item_lines_html}</ul>"
        "<p>Please use the onboarding link you were sent earlier to make these corrections and "
        "resubmit. If you can't find that email, contact HR directly.</p>"
    )
    return subject, html_body, text_body


def build_activated_email(
    *, candidate_first_name: str, company_name: str, employee_code: str
) -> tuple[str, str, str]:
    """Sent once activation (O7) has created the real `Employee` row. Login/account-creation
    itself is out of scope for this slice (plan §14/§13 Q4) — this is a plain welcome notice,
    not an invitation to sign in anywhere."""
    subject = f"Welcome to {company_name}!"
    text_body = (
        f"Hi {candidate_first_name},\n\n"
        f"Your onboarding at {company_name} is complete and your employee record has been "
        f"created (employee code {employee_code}). Welcome aboard — HR will be in touch with "
        "any next steps before your start date."
    )
    html_body = (
        f"<p>Hi {candidate_first_name},</p>"
        f"<p>Your onboarding at <strong>{company_name}</strong> is complete and your employee "
        f"record has been created (employee code <strong>{employee_code}</strong>). Welcome "
        "aboard — HR will be in touch with any next steps before your start date.</p>"
    )
    return subject, html_body, text_body
