"""HTML interpolation in the onboarding notification builders must escape untrusted values.

Scope: these three builders are separate from the invitation renderer
(`invitation_compose` / `invitation_rich_text`), which does NOT protect them.
"""

from html.parser import HTMLParser

from hrms.modules.onboarding.email_templates import (
    build_activated_email,
    build_changes_requested_email,
    build_invite_email,
)

EVIL = "<img src=x onerror=alert(1)><script>alert(2)</script>\"'"


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: set[str] = set()
        self.attrs: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)
        self.attrs.update(name for name, _ in attrs)


def _assert_inert(html_body: str) -> None:
    parsed = _Tags()
    parsed.feed(html_body)
    assert parsed.tags <= {"p", "strong", "ul", "li", "a"}
    assert parsed.attrs <= {"href"}


def test_changes_requested_escapes_name_company_label_and_reason() -> None:
    subject, html_body, text_body = build_changes_requested_email(
        candidate_first_name=EVIL, company_name=EVIL, rejected_items=[(EVIL, EVIL)]
    )
    _assert_inert(html_body)
    assert "&lt;script&gt;" in html_body
    assert EVIL in text_body and EVIL in subject  # plain text / header keep the literal value


def test_activated_escapes_name_company_and_employee_code() -> None:
    _, html_body, text_body = build_activated_email(
        candidate_first_name=EVIL, company_name=EVIL, employee_code=EVIL
    )
    _assert_inert(html_body)
    assert EVIL in text_body


def test_invite_builder_escapes_values_and_url() -> None:
    _, html_body, _ = build_invite_email(
        candidate_first_name=EVIL,
        company_name=EVIL,
        invite_url='https://x.example/o/"><script>alert(1)</script>',
    )
    _assert_inert(html_body)


def test_ordinary_values_render_unchanged() -> None:
    _, html_body, _ = build_activated_email(
        candidate_first_name="Asha", company_name="Acme", employee_code="E-001"
    )
    assert html_body.startswith("<p>Hi Asha,</p>") and "<strong>E-001</strong>" in html_body
