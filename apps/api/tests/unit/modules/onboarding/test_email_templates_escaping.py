"""HTML interpolation in the onboarding notification builders must escape untrusted values.

Scope: these three builders are separate from the invitation renderer
(`invitation_compose` / `invitation_rich_text`), which does NOT protect them.
"""

from html.parser import HTMLParser

from hrms.modules.account_invite.email_templates import LoginDetails, build_account_invite_email
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


def test_activated_escapes_login_details_and_links() -> None:
    _, html_body, text_body = build_activated_email(
        candidate_first_name="Asha",
        company_name="Acme",
        employee_code=EVIL,
        login=LoginDetails(email=EVIL, company_code=EVIL, employee_code=EVIL),
        set_password_url='https://x.example/accept-invite/"><script>alert(1)</script>',
    )
    _assert_inert(html_body)
    assert EVIL in text_body


def test_activated_with_password_link_carries_login_details() -> None:
    subject, html_body, text_body = build_activated_email(
        candidate_first_name="Asha",
        company_name="Acme",
        employee_code="EMP-0007",
        login=LoginDetails(email="asha@example.com", company_code="ACME", employee_code="EMP-0007"),
        set_password_url="https://app.example/accept-invite/tok",
        sign_in_url="https://app.example/login",
    )
    assert subject == "Welcome to Acme! Set up your login"
    for body in (html_body, text_body):
        assert "asha@example.com" in body and "ACME" in body and "EMP-0007" in body
        assert "https://app.example/accept-invite/tok" in body
        # The set-password link replaces the plain "sign in" pointer.
        assert "https://app.example/login" not in body


def test_activated_without_invite_points_at_sign_in() -> None:
    subject, html_body, text_body = build_activated_email(
        candidate_first_name="Asha",
        company_name="Acme",
        employee_code="EMP-0007",
        login=LoginDetails(email="asha@example.com", company_code="ACME", employee_code="EMP-0007"),
        sign_in_url="https://app.example/login",
    )
    assert subject == "Welcome to Acme!"
    assert "existing password" in text_body and "https://app.example/login" in html_body
    assert "accept-invite" not in text_body


def test_account_invite_login_details_are_escaped() -> None:
    _, html_body, text_body = build_account_invite_email(
        first_name="Asha",
        company_name="Acme",
        invite_url="https://app.example/accept-invite/tok",
        login=LoginDetails(email=EVIL, company_code=EVIL, employee_code=EVIL),
    )
    _assert_inert(html_body)
    assert "Company code" in text_body and EVIL in text_body
