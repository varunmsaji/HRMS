"""The Krewoxa logo sits above the greeting in the HTML part of every invitation (no database)."""

from types import SimpleNamespace
from typing import Any, cast

from hrms.modules.onboarding.invitation_compose import (
    BRAND_LOGO_PATH,
    DEFAULT_BODY,
    InvitationValues,
    brand_logo_url,
    with_brand_header,
)
from hrms.modules.onboarding.invitation_service import OnboardingInvitationService

URL = "https://app.example.com/onboarding/TOKEN123"
VALUES = InvitationValues(
    {
        "candidate_first_name": "Asha",
        "candidate_last_name": "Rao",
        "candidate_name": "Asha Rao",
        "company_name": "Acme",
        "designation": "Analyst",
        "department": "Finance",
        "joining_date": "15 January 2027",
        "invitation_expiry": "22 January 2027 (UTC)",
    }
)


def _para(text: str) -> dict[str, Any]:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def _service() -> OnboardingInvitationService:
    settings = SimpleNamespace(web_app_base_url="https://app.krewoxa.com")
    return OnboardingInvitationService(cast(Any, None), cast(Any, settings))


def test_header_escapes_the_logo_url_and_keeps_the_body() -> None:
    out = with_brand_header("<p>Dear Asha,</p>", 'https://x.example/l.png?a=1&b="2"')
    assert 'src="https://x.example/l.png?a=1&amp;b=&quot;2&quot;"' in out
    assert 'alt="Krewoxa"' in out
    assert out.endswith("<p>Dear Asha,</p>")


def test_logo_comes_before_the_greeting_in_plain_and_rich_bodies() -> None:
    logo = f'<img src="https://app.krewoxa.com{BRAND_LOGO_PATH}"'
    header = '<div style="margin:0 0 24px">' + logo
    plain = _service().render(
        subject=None, body=DEFAULT_BODY, values=VALUES, onboarding_url=URL, mobile_url=None
    )
    assert plain.html_body.startswith(header)
    assert plain.html_body.index(logo) < plain.html_body.index("Dear Asha Rao,")
    # the plain-text part stays free of markup
    assert "<img" not in plain.text_body and plain.text_body.startswith("Dear Asha Rao,")

    rich = _service().render(
        subject=None,
        body=None,
        body_doc={
            "type": "doc",
            "content": [_para("Dear {{candidate_name}},"), _para("{{onboarding_url}}")],
        },
        values=VALUES,
        onboarding_url=URL,
        mobile_url=None,
    )
    assert rich.html_body.count("<img") == 1 and rich.html_body.startswith(header)


def test_brand_logo_url_points_at_the_web_app_png() -> None:
    assert brand_logo_url("https://app.krewoxa.com") == "https://app.krewoxa.com" + BRAND_LOGO_PATH
    assert BRAND_LOGO_PATH.endswith(".png")  # mail clients don't render SVG
