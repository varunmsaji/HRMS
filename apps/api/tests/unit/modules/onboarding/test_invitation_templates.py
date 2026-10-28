"""Every built-in invitation template must be sendable as-is."""

import pytest

from hrms.modules.onboarding.invitation_compose import (
    BODY_MAX_LENGTH,
    InvitationValues,
    render_invitation,
    validate_body_template,
    validate_subject_template,
)
from hrms.modules.onboarding.invitation_templates import INVITATION_TEMPLATES

URL = "https://app.example.com/onboarding/TOKEN"
FULL = InvitationValues(
    {
        "candidate_first_name": "Asha",
        "candidate_last_name": "Rao",
        "candidate_name": "Asha Rao",
        "company_name": "Acme <b>Ltd</b>",
        "designation": "Analyst",
        "department": "Finance",
        "joining_date": "15 January 2027",
        "invitation_expiry": "22 January 2027 (UTC)",
    }
)
MINIMAL = InvitationValues(
    {**FULL.values, "designation": None, "department": None, "candidate_last_name": None}
)


def test_there_are_several_templates_with_unique_keys_and_the_standard_default_first() -> None:
    keys = [t.key for t in INVITATION_TEMPLATES]
    assert len(keys) >= 2 and len(set(keys)) == len(keys)
    assert keys[0] == "standard"
    assert all(t.name and t.description for t in INVITATION_TEMPLATES)


@pytest.mark.parametrize("template", INVITATION_TEMPLATES, ids=lambda t: t.key)
def test_template_is_valid_and_within_limits(template) -> None:  # type: ignore[no-untyped-def]
    validate_subject_template(template.subject)
    validate_body_template(template.body)
    assert len(template.body) <= BODY_MAX_LENGTH


@pytest.mark.parametrize("template", INVITATION_TEMPLATES, ids=lambda t: t.key)
@pytest.mark.parametrize("values", [FULL, MINIMAL], ids=["all-values", "optional-missing"])
def test_template_renders_with_no_leftover_placeholders_and_a_single_server_link(
    template,
    values,  # type: ignore[no-untyped-def]
) -> None:
    out = render_invitation(
        subject_template=template.subject,
        body_template=template.body,
        values=values,
        onboarding_url=URL,
    )
    for text in (out.subject, out.text_body, out.html_body):
        assert "{{" not in text and "}}" not in text
    assert out.html_body.count("<a ") == 1 and f'href="{URL}"' in out.html_body
    assert "<b>Ltd</b>" not in out.html_body  # values are escaped
