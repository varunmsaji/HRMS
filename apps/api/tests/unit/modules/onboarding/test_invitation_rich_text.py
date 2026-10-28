# ruff: noqa: E501 - long literals in test data
"""Security + behaviour tests of the structured rich-text invitation renderer (pure, no database).

The client sends a constrained JSON document, never HTML; the server validates it against a closed
schema and generates all markup itself. See docs/design/ONBOARDING_RICH_TEXT_CONTRACT.md.
"""

import copy
from html.parser import HTMLParser
from typing import Any

import pytest

from hrms.core.errors.base import ValidationError
from hrms.modules.onboarding.invitation_compose import (
    DEFAULT_SUBJECT,
    PREVIEW_LINK,
    InvitationValues,
    render_invitation,
)
from hrms.modules.onboarding.invitation_rich_text import render_invitation_document

URL = "https://app.example.com/onboarding/TOKEN123"
PREVIEW_URL = f"https://app.example.com/onboarding/{PREVIEW_LINK}"


def _values(**over: str | None) -> InvitationValues:
    base: dict[str, str | None] = {
        "candidate_first_name": "Asha",
        "candidate_last_name": "Rao",
        "candidate_name": "Asha Rao",
        "company_name": 'Acme <img src=x onerror=alert(1)> "Ltd"',
        "designation": "Analyst",
        "department": "Finance",
        "joining_date": "15 January 2027",
        "invitation_expiry": "22 January 2027 (UTC)",
    }
    base.update(over)
    return InvitationValues(base)


def txt(text: str, *marks: dict[str, Any]) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


def para(*inline: dict[str, Any]) -> dict[str, Any]:
    return {"type": "paragraph", "content": list(inline)}


def link(href: str) -> dict[str, Any]:
    return {"type": "link", "attrs": {"href": href}}


LINK_PARA = para(txt("{{onboarding_url}}"))


def doc(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "content": list(blocks)}


def good_doc() -> dict[str, Any]:
    return doc(
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [txt("Welcome {{candidate_first_name}}")],
        },
        para(txt("Hello ", {"type": "bold"}), txt("{{company_name}}", {"type": "italic"})),
        {"type": "bulletList", "content": [{"type": "listItem", "content": [para(txt("One"))]}]},
        LINK_PARA,
    )


ALLOWED_TAGS = {"p", "h2", "h3", "ul", "ol", "li", "strong", "em", "u", "a", "br"}


class _Audit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS:
            self.problems.append(f"tag {tag}")
        for name, value in attrs:
            ok = (tag == "a" and name in {"href", "rel"}) or (
                tag == "p"
                and name == "style"
                and value in {"margin:24px 0", "font-size:12px;color:#555"}
            )
            if not ok:
                self.problems.append(f"attr {tag}.{name}")
            if name == "href" and not (value or "").lower().startswith(
                ("https://", "http://", "mailto:")
            ):
                self.problems.append(f"href {value}")


def assert_output_is_allowlisted(html_body: str) -> None:
    """Parses the *output* the way a mail client would: only allowlisted tags/attributes exist."""
    audit = _Audit()
    audit.feed(html_body)
    audit.close()
    assert audit.problems == []


def render(body_doc: Any, *, subject: str = DEFAULT_SUBJECT, url: str = URL, **over: str | None):
    return render_invitation_document(
        subject_template=subject, body_doc=body_doc, values=_values(**over), onboarding_url=url
    )


def rejected(body_doc: Any, **kw: Any) -> ValidationError:
    with pytest.raises(ValidationError) as exc:
        render(body_doc, **kw)
    return exc.value


# ---------------------------------------------------------------------------------- happy path


def test_formatting_survives_to_html_and_text() -> None:
    out = render(good_doc())
    assert "<h2>Welcome Asha</h2>" in out.html_body
    assert "<strong>Hello </strong>" in out.html_body
    assert "<em>Acme" in out.html_body
    assert (
        "<ul><li><p>One</p></li></ul>" in out.html_body or "<ul><li>One</li></ul>" in out.html_body
    )
    assert f'href="{URL}"' in out.html_body
    assert "Welcome Asha" in out.text_body and "- One" in out.text_body and URL in out.text_body
    assert_output_is_allowlisted(out.html_body)


def test_underline_and_safe_link_render_with_rel() -> None:
    d = doc(
        para(
            txt("Policy", {"type": "underline"}),
            txt(" page", link("https://example.org/p?a=1&b=2")),
        ),
        LINK_PARA,
    )
    html_body = render(d).html_body
    assert "<u>Policy</u>" in html_body
    assert 'href="https://example.org/p?a=1&amp;b=2"' in html_body
    assert 'rel="noopener noreferrer"' in html_body


def test_mailto_link_allowed() -> None:
    d = doc(para(txt("Write to HR", link("mailto:hr@example.org"))), LINK_PARA)
    assert 'href="mailto:hr@example.org"' in render(d).html_body


def test_preview_and_send_share_the_renderer_and_differ_only_in_the_link() -> None:
    preview = render(good_doc(), url=PREVIEW_URL)
    sent = render(good_doc(), url=URL)
    assert preview.subject == sent.subject
    assert preview.html_body.replace(PREVIEW_URL, URL) == sent.html_body
    assert preview.text_body.replace(PREVIEW_URL, URL) == sent.text_body
    assert PREVIEW_LINK in preview.html_body and "TOKEN123" not in preview.html_body


def test_document_equivalent_to_plain_text_renders_like_legacy_plain_text() -> None:
    legacy = render_invitation(
        subject_template="Hi",
        body_template="Hello {{candidate_name}}\n\n{{onboarding_url}}",
        values=_values(),
        onboarding_url=URL,
    )
    rich = render(doc(para(txt("Hello {{candidate_name}}")), LINK_PARA), subject="Hi")
    assert rich.html_body == legacy.html_body
    assert rich.text_body == legacy.text_body


def test_missing_optional_value_omits_the_paragraph() -> None:
    d = doc(para(txt("Role: {{designation}}")), para(txt("Hello")), LINK_PARA)
    out = render(d, designation=None)
    assert "Role" not in out.html_body and "Hello" in out.html_body


def test_missing_required_value_is_an_error() -> None:
    d = doc(para(txt("Hi {{candidate_name}}")), LINK_PARA)
    assert rejected(d, candidate_name=None).details[0]["field"] == "body"


# ------------------------------------------------------------- malicious HTML / active content


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        '<img src=x onerror="alert(1)">',
        '<iframe src="https://evil.example"></iframe>',
        '<object data="x"></object><embed src="x">',
        '<a href="javascript:alert(1)">x</a>',
        '<div style="background:url(javascript:alert(1))">x</div>',
        "<svg onload=alert(1)>",
        "</p><script>alert(1)</script><p>",
    ],
)
def test_markup_typed_into_text_is_escaped_never_an_element(payload: str) -> None:
    out = render(doc(para(txt(payload)), LINK_PARA))
    assert "<script" not in out.html_body.lower()
    assert "<img" not in out.html_body.lower() and "<iframe" not in out.html_body.lower()
    assert "<svg" not in out.html_body.lower() and "<object" not in out.html_body.lower()
    assert "&lt;" in out.html_body
    assert_output_is_allowlisted(out.html_body)


@pytest.mark.parametrize(
    "node_type",
    ["script", "iframe", "image", "img", "table", "codeBlock", "blockquote", "html", "rawHtml"],
)
def test_unsupported_node_types_are_rejected(node_type: str) -> None:
    rejected(doc({"type": node_type, "content": [txt("x")]}, LINK_PARA))


@pytest.mark.parametrize(
    "mark", ["code", "strike", "highlight", "textStyle", "color", "style", "script"]
)
def test_unsupported_marks_are_rejected(mark: str) -> None:
    rejected(doc(para(txt("x", {"type": mark})), LINK_PARA))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["content"][0].update(attrs={"style": "color:red"}),
        lambda d: d["content"][0].update(attrs={"class": "x"}),
        lambda d: d["content"][0].update(attrs={"onclick": "alert(1)"}),
        lambda d: d["content"][0].update(html="<b>x</b>"),
        lambda d: d["content"][0].update(innerHTML="<b>x</b>"),
        lambda d: d.update(attrs={"x": 1}),
        lambda d: d["content"][0]["content"][0].update(style="x"),
    ],
)
def test_unknown_keys_and_attributes_are_rejected_not_stripped(mutate: Any) -> None:
    d = doc(para(txt("hello")), LINK_PARA)
    mutate(d)
    rejected(d)


@pytest.mark.parametrize("level", [0, 1, 4, 7, "2", None, True])
def test_heading_level_is_limited(level: Any) -> None:
    rejected(doc({"type": "heading", "attrs": {"level": level}, "content": [txt("x")]}, LINK_PARA))


def test_mark_attrs_other_than_href_are_rejected() -> None:
    bad = {"type": "link", "attrs": {"href": "https://example.org", "style": "x"}}
    rejected(doc(para(txt("a", bad)), LINK_PARA))
    rejected(doc(para(txt("a", {"type": "bold", "attrs": {"onclick": "x"}})), LINK_PARA))


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        "<p>hi</p>",
        5,
        {"type": "paragraph"},
        {"type": "doc"},
        {"type": "doc", "content": []},
        {"type": "doc", "content": "x"},
    ],
)
def test_non_document_inputs_are_rejected(bad: Any) -> None:
    rejected(bad)


def test_client_supplied_html_string_is_never_accepted() -> None:
    rejected("<p>hello</p><a href='https://x'>{{onboarding_url}}</a>")


def test_tolerated_link_attrs_are_dropped_not_rendered() -> None:
    extras = {
        "type": "link",
        "attrs": {"href": "https://example.org", "target": "_blank", "rel": "x", "class": "c"},
    }
    html_body = render(doc(para(txt("go", extras)), LINK_PARA)).html_body
    assert (
        "target=" not in html_body and 'class="c"' not in html_body and 'rel="x"' not in html_body
    )


# --------------------------------------------------------------------------------- unsafe URLs


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        " javascript:alert(1)",
        "java\tscript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "blob:https://x/y",
        "ftp://example.org/x",
        "tel:+911234567890",
        "//evil.example/x",
        "/relative/path",
        "relative",
        "",
        "https://",
        "https:///nohost",
        "https://good.example@evil.example/",
        "https://user:pw@example.org/",
        "https://exa mple.org/",
        "https://example.org/\nx",
        "https://example.org\\@evil.example",
        "https://example.org/{{company_name}}",
        "https://example.org/" + "a" * 2100,
        "mailto:",
        "mailto:not-an-address",
        "mailto:a@b.c?bcc=x@y.z&body=<script>",
        "&#106;avascript:alert(1)",
        "%6Aavascript:alert(1)",
        "https://example.org/\x00",
    ],
)
def test_dangerous_or_malformed_urls_are_rejected(href: str) -> None:
    rejected(doc(para(txt("click", link(href))), LINK_PARA))


def test_link_href_must_be_a_string() -> None:
    for bad in (None, 5, ["https://x"], {"a": 1}):
        rejected(doc(para(txt("click", {"type": "link", "attrs": {"href": bad}})), LINK_PARA))


def test_link_text_that_names_another_host_is_rejected() -> None:
    rejected(
        doc(para(txt("https://mybank.example/login", link("https://evil.example/"))), LINK_PARA)
    )
    rejected(doc(para(txt("www.mybank.example", link("https://evil.example/"))), LINK_PARA))
    # matching host is fine
    render(doc(para(txt("https://example.org/a", link("https://example.org/b"))), LINK_PARA))


def test_user_links_cannot_impersonate_or_reuse_the_secure_link() -> None:
    rejected(doc(para(txt("Open your portal", link(URL))), LINK_PARA))
    rejected(
        doc(
            para(txt("Open your portal", link("https://app.example.com/onboarding/anything"))),
            LINK_PARA,
        )
    )
    rejected(doc(para(txt("Open", link("{{onboarding_url}}"))), LINK_PARA))


# ---------------------------------------------------------------------------- placeholder abuse


def test_placeholder_values_are_escaped_in_html_and_not_reinterpreted() -> None:
    out = render(doc(para(txt("At {{company_name}}", {"type": "bold"})), LINK_PARA))
    assert "<img" not in out.html_body
    assert "&lt;img src=x onerror=alert(1)&gt;" in out.html_body
    assert "&quot;Ltd&quot;" in out.html_body


def test_value_cannot_inject_a_placeholder_or_link() -> None:
    out = render(
        doc(para(txt("Hi {{candidate_name}}")), LINK_PARA),
        candidate_name="{{onboarding_url}} <a href='https://evil'>",
    )
    assert out.html_body.count(URL) == 2  # CTA href + visible address only; value stayed text
    assert "<a href='https://evil'>" not in out.html_body


def test_value_in_a_link_label_cannot_alter_the_href() -> None:
    d = doc(para(txt("{{company_name}}", link("https://example.org/x"))), LINK_PARA)
    html_body = render(d, company_name='"><script>alert(1)</script>').html_body
    assert "<script" not in html_body and 'href="https://example.org/x"' in html_body


@pytest.mark.parametrize(
    "text",
    [
        "{{nope}}",
        "{{ }}",
        "{{",
        "}}",
        "{{candidate_name",
        "{{{{candidate_name}}}}",
        "{{company_name}",
    ],
)
def test_unknown_or_malformed_placeholders_are_rejected(text: str) -> None:
    rejected(doc(para(txt(text)), LINK_PARA))


def test_placeholder_split_across_formatted_runs_is_rejected() -> None:
    rejected(doc(para(txt("{{comp", {"type": "bold"}), txt("any_name}}")), LINK_PARA))


def test_placeholders_in_headings_and_lists_are_resolved_and_escaped() -> None:
    d = doc(
        {"type": "heading", "attrs": {"level": 3}, "content": [txt("{{company_name}}")]},
        {
            "type": "orderedList",
            "content": [{"type": "listItem", "content": [para(txt("{{candidate_name}}"))]}],
        },
        LINK_PARA,
    )
    out = render(d)
    assert (
        "<h3>Acme &lt;img" in out.html_body
        and "<ol>" in out.html_body
        and "<img" not in out.html_body
    )


# -------------------------------------------------------------------------- subject injection


@pytest.mark.parametrize(
    "subject",
    [
        "Hi\r\nBcc: attacker@evil.example",
        "Hi\nBcc: x",
        "Hi\rBcc: x",
        "Hi Bcc: x",
        "Hi\x00",
        "Hi\x1b[0m",
        "",
        "   ",
        "x" * 151,
        "{{onboarding_url}}",
        "Hi {{nope}}",
    ],
)
def test_subject_rules_apply_to_rich_bodies(subject: str) -> None:
    rejected(good_doc(), subject=subject)


def test_value_with_crlf_cannot_break_the_subject() -> None:
    out = render(
        good_doc(),
        subject="Welcome to {{company_name}}",
        company_name="Acme\r\nBcc: x@evil.example",
    )
    assert "\r" not in out.subject and "\n" not in out.subject


def test_subject_stays_plain_text() -> None:
    out = render(good_doc(), subject="Hello <b>{{candidate_first_name}}</b>")
    assert out.subject == "Hello <b>Asha</b>"  # header text; never interpreted as HTML


# ------------------------------------------------------------------- invitation link placement


def test_missing_link_placeholder_is_rejected() -> None:
    rejected(doc(para(txt("no link here"))))


def test_duplicate_link_placeholder_is_rejected() -> None:
    rejected(doc(LINK_PARA, para(txt("again")), copy.deepcopy(LINK_PARA)))


@pytest.mark.parametrize(
    "block",
    [
        para(txt("Click {{onboarding_url}} now")),
        para(txt("{{onboarding_url}}", {"type": "bold"})),
        para(txt("{{onboarding_url}}", link("https://example.org"))),
        para(txt("{{onboarding_url}}"), txt(" extra")),
        {"type": "heading", "attrs": {"level": 2}, "content": [txt("{{onboarding_url}}")]},
        {
            "type": "bulletList",
            "content": [{"type": "listItem", "content": [para(txt("{{onboarding_url}}"))]}],
        },
        para(txt("{{ onboarding_url }}"), {"type": "hardBreak"}),
    ],
)
def test_link_placeholder_only_valid_as_a_lone_plain_top_level_paragraph(
    block: dict[str, Any],
) -> None:
    rejected(doc(block))


def test_link_placeholder_tolerates_inner_spaces_like_legacy() -> None:
    out = render(doc(para(txt("{{ onboarding_url }}"))))
    assert f'href="{URL}"' in out.html_body


def test_non_http_server_link_is_refused() -> None:
    rejected(good_doc(), url="javascript:alert(1)")
    rejected(good_doc(), url="data:text/html,x")


def test_only_the_server_link_is_ever_the_credential() -> None:
    out = render(good_doc())
    assert out.html_body.count(URL) == 2 and out.text_body.count(URL) == 1


# ------------------------------------------------------------------------------------ limits


def test_size_depth_and_node_limits() -> None:
    rejected(doc(para(txt("x" * 5001)), LINK_PARA))
    rejected(doc(*[para(txt("a")) for _ in range(600)], LINK_PARA))
    nested: dict[str, Any] = para(txt("x"))
    for _ in range(12):
        nested = {"type": "bulletList", "content": [{"type": "listItem", "content": [nested]}]}
    rejected(doc(nested, LINK_PARA))


def test_control_characters_and_empty_text_are_rejected() -> None:
    rejected(doc(para(txt("a\x00b")), LINK_PARA))
    rejected(doc(para(txt("a\x1bb")), LINK_PARA))
    rejected(doc(para(txt("")), LINK_PARA))
    rejected(doc(para(txt(None)), LINK_PARA))  # type: ignore[arg-type]


def test_documents_are_not_mutated() -> None:
    d = good_doc()
    before = copy.deepcopy(d)
    render(d)
    assert d == before
