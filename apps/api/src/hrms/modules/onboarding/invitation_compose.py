"""HR-editable onboarding invitation: placeholder allowlist, validation and rendering.

One rendering path serves both the side-effect-free preview and the real send, so what HR approves
is byte-for-byte what is queued (only the link differs: a clearly marked inert one in the preview).

Safety by construction rather than by sanitising: the body is plain text. Every character HR types
and every resolved value is HTML-escaped, so markup in either is shown as text and can never become
an element, attribute, script or link. The only link in the HTML is the one the server builds
itself for `{{onboarding_url}}` (http/https only). The subject is a single header line: control
characters (CR/LF included) are rejected, never stripped, so header injection cannot be smuggled in.

Placeholders are `{{name}}`, names come from `PLACEHOLDERS` only. Unknown, malformed or empty names
are rejected, and a placeholder that has no value never reaches the recipient: in the body the
paragraph that holds an unavailable *optional* placeholder is omitted; in the subject it is an
error. Nothing is ever silently replaced by an empty string.
"""

import html
import re
from dataclasses import dataclass
from datetime import date, datetime

from hrms.core.errors.base import ValidationError

SUBJECT_MAX_LENGTH = 150
BODY_MAX_LENGTH = 5000

DEFAULT_SUBJECT = "Welcome to {{company_name}} — Complete Your Onboarding"
DEFAULT_BODY = """Dear {{candidate_name}},

Welcome to {{company_name}}!

We are pleased to begin your pre-joining onboarding for the {{designation}} position.

You will be joining the {{department}} team.

Your proposed joining date is {{joining_date}}.

To get everything ready before your first day, please complete your online onboarding form using the secure link below. The link is personal to you and is valid until {{invitation_expiry}}.

{{onboarding_url}}

What the form asks for:
- Personal information
- Address
- Emergency contact
- Bank details
- Statutory details
- Compensation details
- Previous employment
- Education
- Nominee and family details

Please keep clear copies (photo or scan) of these documents ready to upload:
- Passport-size photograph
- PAN card
- Aadhaar card
- Address proof
- Education certificates
- Previous employment proof, such as a relieving or experience letter
- Bank proof, such as a cancelled cheque or passbook first page

How it works:
1. Open the link and fill in each section. Your progress is saved as you go, so you can leave and come back using the same link until it expires.
2. Upload your documents and submit the form.
3. Our HR team will review your details and documents. If anything needs to be corrected, we will email you exactly what to update, and you can fix it using the same link.
4. Once everything is verified, HR will complete your onboarding and set up your employee record.

Please complete the form well before your joining date so that nothing delays your first day. Please do not share the link with anyone else. It contains your personal details and is meant only for you.

If you have any questions, face any difficulty with the form, or need a new link after this one expires, please contact the HR team.

We look forward to having you with us.

Regards,
{{company_name}} HR Team"""  # noqa: E501

#: Shown in place of the credential when a preview is rendered, and kept in the stored history copy.
PREVIEW_LINK = "PREVIEW-LINK-NOT-ACTIVE"
REDACTED_LINK = "[secure onboarding link - not retained]"
CALL_TO_ACTION = "Complete Onboarding"
FOOTER_TEXT = (
    "This link is personal to you - please don't forward it. If you weren't expecting this "
    "email, you can safely ignore it."
)


@dataclass(frozen=True)
class Placeholder:
    key: str
    label: str
    description: str
    required: bool  # False: may be unavailable for a case (its paragraph is then omitted)
    example: str


PLACEHOLDERS: tuple[Placeholder, ...] = (
    Placeholder("candidate_first_name", "Candidate first name", "", True, "Asha"),
    Placeholder("candidate_last_name", "Candidate last name", "", False, "Verma"),
    Placeholder("candidate_name", "Candidate full name", "", True, "Asha Verma"),
    Placeholder("company_name", "Company name", "", True, "Acme Pvt Ltd"),
    Placeholder("designation", "Designation", "Omitted when not set on the case", False, "Analyst"),
    Placeholder("department", "Department", "Omitted when not set on the case", False, "Finance"),
    Placeholder("joining_date", "Proposed joining date", "", True, "05 November 2026"),
    Placeholder(
        "invitation_expiry",
        "Link expiry date",
        "Preview shows the date a link issued now would expire",
        True,
        "12 November 2026 (UTC)",
    ),
    Placeholder(
        "onboarding_url",
        "Secure onboarding link",
        "Required in the body; not allowed in the subject",
        True,
        "(generated when sent)",
    ),
)
_BY_KEY = {p.key: p for p in PLACEHOLDERS}

_TOKEN = re.compile(r"\{\{\s*([A-Za-z0-9_]*)\s*\}\}")
_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # excludes \t and \n (body only)
_ANY_CONTROL = re.compile(r"[\x00-\x1f\x7f  ]")  # subject: no line breaks at all


def format_date(value: date) -> str:
    """Date-only, so no timezone conversion applies; one fixed locale-independent format."""
    return f"{value.day:02d} {value.strftime('%B %Y')}"


def format_expiry(value: datetime) -> str:
    return f"{format_date(value.date())} (UTC)"


@dataclass(frozen=True)
class InvitationValues:
    """Server-resolved values. `None` marks a value the case does not have."""

    values: dict[str, str | None]


@dataclass(frozen=True)
class RenderedInvitation:
    subject: str
    html_body: str
    text_body: str


def _invalid(field: str, message: str) -> ValidationError:
    return ValidationError(
        message,
        details=[{"field": field, "code": "INVITATION_TEMPLATE_INVALID", "message": message}],
    )


def _check_placeholders(text: str, field: str) -> list[str]:
    names = _TOKEN.findall(text)
    for name in names:
        if name not in _BY_KEY:
            shown = name[:40] if name else "(empty)"
            raise _invalid(field, f"Unsupported placeholder {{{{{shown}}}}}.")
    if "{{" in _TOKEN.sub("", text) or "}}" in _TOKEN.sub("", text):
        raise _invalid(field, "Malformed placeholder: use {{name}} with a supported name.")
    return names


def validate_subject_template(subject: str) -> str:
    if not subject or not subject.strip():
        raise _invalid("subject", "Subject must not be empty.")
    if _ANY_CONTROL.search(subject):
        raise _invalid("subject", "Subject must be a single line without control characters.")
    if len(subject) > SUBJECT_MAX_LENGTH:
        raise _invalid("subject", f"Subject must be at most {SUBJECT_MAX_LENGTH} characters.")
    if "onboarding_url" in _check_placeholders(subject, "subject"):
        raise _invalid("subject", "The onboarding link cannot be used in the subject.")
    return subject.strip()


def validate_body_template(body: str) -> str:
    if not body or not body.strip():
        raise _invalid("body", "Body must not be empty.")
    if _CONTROL.search(body):
        raise _invalid("body", "Body contains unsupported control characters.")
    if len(body) > BODY_MAX_LENGTH:
        raise _invalid("body", f"Body must be at most {BODY_MAX_LENGTH} characters.")
    if "onboarding_url" not in _check_placeholders(body, "body"):
        raise _invalid(
            "body",
            "The body must include the secure onboarding link ({{onboarding_url}}) so the "
            "candidate can complete onboarding.",
        )
    return body.replace("\r\n", "\n").replace("\r", "\n").strip()


def _clean_value(value: str) -> str:
    """Resolved values are single-line: data cannot inject line breaks or controls."""
    return _ANY_CONTROL.sub(" ", value).strip()


def _render_subject(template: str, values: InvitationValues) -> str:
    def sub(match: re.Match[str]) -> str:
        value = values.values.get(match.group(1))
        if value is None or not _clean_value(value):
            raise _invalid(
                "subject",
                f"{{{{{match.group(1)}}}}} is not available for this candidate; "
                "remove it from the subject.",
            )
        return _clean_value(value)

    subject = _TOKEN.sub(sub, template)
    # a value (e.g. a company name) could push a valid template over the limit
    if len(subject) > SUBJECT_MAX_LENGTH * 2:
        raise _invalid("subject", "Subject is too long once placeholders are filled in.")
    return subject


def _paragraph_text(paragraph: str, values: InvitationValues) -> str | None:
    """None when an optional placeholder in it has no value (the paragraph is omitted)."""
    missing = False

    def sub(match: re.Match[str]) -> str:
        nonlocal missing
        value = values.values.get(match.group(1))
        if value is None or not _clean_value(value):
            missing = True
            return ""
        return _clean_value(value)

    out = _TOKEN.sub(sub, paragraph)
    if missing:
        if any(_BY_KEY[n].required for n in _TOKEN.findall(paragraph) if not values.values.get(n)):
            raise _invalid("body", "A required placeholder has no value for this candidate.")
        return None
    return out


def _link_html(url: str, label: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'


def call_to_action_html(onboarding_url: str) -> str:
    """The server-built button + visible address. Shared by the plain-text and rich-text paths."""
    return (
        f'<p style="margin:24px 0">{_link_html(onboarding_url, CALL_TO_ACTION)}'
        f'</p><p style="font-size:12px;color:#555">If the button does not work, '
        f"copy this address into your browser:<br>{html.escape(onboarding_url)}</p>"
    )


def append_mobile_and_footer(
    text_body: str, html_body: str, mobile_url: str | None
) -> tuple[str, str]:
    if mobile_url:
        text_body += (
            "\n\nOn a phone with the HRMS app installed, open it with this link:\n" + mobile_url
        )
        html_body += (
            "<p>On a phone with the HRMS app installed, "
            f"{_link_html(mobile_url, 'open it in the app')}.</p>"
        )
    text_body += "\n\n" + FOOTER_TEXT
    html_body += f'<p style="font-size:12px;color:#555">{html.escape(FOOTER_TEXT)}</p>'
    return text_body, html_body


def render_editable_body(body_template: str, values: InvitationValues) -> str:
    """The body with every placeholder filled in except `{{onboarding_url}}`, which stays a token
    because the real link only exists at send time. Lets HR edit the text they will actually send;
    it is validated and rendered again like any other body on preview/send."""
    body_tpl = validate_body_template(body_template)
    url_values = InvitationValues({**values.values, "onboarding_url": "{{onboarding_url}}"})
    parts: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT.split(body_tpl):
        paragraph = paragraph.strip("\n")
        if not paragraph.strip():
            continue
        text = _paragraph_text(paragraph, url_values)
        if text is not None:
            parts.append(text)
    return "\n\n".join(parts)


def render_invitation(
    *,
    subject_template: str,
    body_template: str,
    values: InvitationValues,
    onboarding_url: str,
    mobile_url: str | None = None,
) -> RenderedInvitation:
    """Validates and renders. Raises `ValidationError` (422) for anything unsendable."""
    subject_tpl = validate_subject_template(subject_template)
    body_tpl = validate_body_template(body_template)
    if not onboarding_url.lower().startswith(("https://", "http://")):
        raise _invalid("body", "The onboarding link must be an http(s) URL.")

    subject = _render_subject(subject_tpl, values)
    url_values = InvitationValues({**values.values, "onboarding_url": onboarding_url})

    text_parts: list[str] = []
    html_parts: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT.split(body_tpl):
        paragraph = paragraph.strip("\n")
        if not paragraph.strip():
            continue
        text = _paragraph_text(paragraph, url_values)
        if text is None:
            continue
        text_parts.append(text)
        if paragraph.strip() == "{{onboarding_url}}":
            html_parts.append(call_to_action_html(onboarding_url))
            continue
        # escape the template text and each value separately so a value can't affect structure
        html_line_parts: list[str] = []
        pos = 0
        for match in _TOKEN.finditer(paragraph):
            html_line_parts.append(html.escape(paragraph[pos : match.start()]))
            name = match.group(1)
            if name == "onboarding_url":
                html_line_parts.append(_link_html(onboarding_url, onboarding_url))
            else:
                html_line_parts.append(html.escape(_clean_value(values.values[name] or "")))
            pos = match.end()
        html_line_parts.append(html.escape(paragraph[pos:]))
        html_parts.append("<p>" + "".join(html_line_parts).replace("\n", "<br>") + "</p>")

    text_body, html_body = append_mobile_and_footer(
        "\n\n".join(text_parts), "".join(html_parts), mobile_url
    )
    return RenderedInvitation(subject=subject, html_body=html_body, text_body=text_body)
