# ruff: noqa: E501 - long literals in test data
"""Rendering / validation rules of the HR-editable invitation (pure functions, no database)."""

import pytest

from hrms.core.errors.base import ValidationError
from hrms.modules.onboarding.invitation_compose import (
    DEFAULT_BODY,
    DEFAULT_SUBJECT,
    PLACEHOLDERS,
    InvitationValues,
    render_invitation,
    validate_body_template,
    validate_subject_template,
)

URL = "https://app.example.com/onboarding/TOKEN123"


def _values(**over: str | None) -> InvitationValues:
    base: dict[str, str | None] = {
        "candidate_first_name": "Asha",
        "candidate_last_name": "Rao",
        "candidate_name": "Asha Rao",
        "company_name": "Acme <b>Ltd</b>",
        "designation": "Analyst",
        "department": "Finance",
        "joining_date": "15 January 2027",
        "invitation_expiry": "22 January 2027 (UTC)",
    }
    base.update(over)
    return InvitationValues(base)


def _render(subject: str = DEFAULT_SUBJECT, body: str = DEFAULT_BODY, **over: str | None):
    return render_invitation(
        subject_template=subject, body_template=body, values=_values(**over), onboarding_url=URL
    )


def test_default_template_resolves_every_placeholder() -> None:
    out = _render()
    for text in (out.subject, out.text_body, out.html_body):
        assert "{{" not in text and "}}" not in text
    assert out.subject.startswith("Welcome to Acme <b>Ltd</b>")  # subject is plain text
    assert "Dear Asha Rao," in out.text_body
    assert "15 January 2027" in out.text_body and "22 January 2027 (UTC)" in out.text_body
    assert URL in out.text_body and URL in out.html_body


def test_every_catalogued_placeholder_is_accepted() -> None:
    body = "\n\n".join(f"{{{{{p.key}}}}}" for p in PLACEHOLDERS if p.key != "onboarding_url")
    out = _render(body=body + "\n\n{{onboarding_url}}")
    assert "{{" not in out.text_body


def test_dynamic_values_are_escaped_in_html() -> None:
    out = _render()
    assert "<b>Ltd</b>" not in out.html_body
    assert "Acme &lt;b&gt;Ltd&lt;/b&gt;" in out.html_body


def test_markup_typed_by_hr_is_shown_as_text() -> None:
    body = 'Hi <script>alert(1)</script> <img src=x onerror=alert(1)> <a href="javascript:x">k</a>\n\n{{onboarding_url}}'
    out = _render(body=body)
    assert "<script" not in out.html_body and "<img" not in out.html_body
    assert 'href="javascript' not in out.html_body
    assert "&lt;script&gt;" in out.html_body
    # the only anchors are the server-built ones
    assert out.html_body.count("<a ") == 1 and f'href="{URL}"' in out.html_body


def test_missing_optional_value_omits_its_paragraph() -> None:
    out = _render(designation=None)
    assert "position" not in out.text_body and "{{" not in out.text_body
    assert "Welcome to Acme" in out.text_body


def test_missing_optional_in_subject_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _render(subject="Your {{designation}} role", designation=None)


def test_missing_required_value_is_rejected_not_blanked() -> None:
    with pytest.raises(ValidationError):
        _render(joining_date=None)


@pytest.mark.parametrize(
    "template",
    ["Hi {{nope}}", "Hi {{}}", "Hi {{company_name", "Hi company_name}}", "{{{{company_name}}"],
)
def test_unsupported_or_malformed_placeholders_rejected(template: str) -> None:
    with pytest.raises(ValidationError):
        validate_subject_template(template)
    with pytest.raises(ValidationError):
        validate_body_template(template + "\n\n{{onboarding_url}}")


@pytest.mark.parametrize(
    "subject", ["", "   ", "a\nb", "a\r\nBcc: x@y.z", "a\x00b", "a b", "x" * 151]
)
def test_invalid_subjects_rejected(subject: str) -> None:
    with pytest.raises(ValidationError):
        validate_subject_template(subject)


def test_subject_cannot_carry_the_link() -> None:
    with pytest.raises(ValidationError):
        validate_subject_template("Go {{onboarding_url}}")


def test_body_must_contain_the_link() -> None:
    with pytest.raises(ValidationError):
        validate_body_template("Hello there")


def test_value_with_line_breaks_cannot_break_the_subject() -> None:
    out = _render(company_name="Acme\r\nBcc: evil@x.test")
    assert "\r" not in out.subject and "\n" not in out.subject


def test_non_http_link_refused() -> None:
    with pytest.raises(ValidationError):
        render_invitation(
            subject_template="s",
            body_template="{{onboarding_url}}",
            values=_values(),
            onboarding_url="javascript:alert(1)",
        )
