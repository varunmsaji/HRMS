# ruff: noqa: E501 - long literals in test data
"""`body_doc` (structured rich text) through the real preview / send / history path.

Mirrors `test_invitation_compose.py` (same fixtures and transaction pattern; dispatch is `none`, so
nothing is ever handed to a mail provider). The pure renderer's exhaustive payload matrix lives in
`tests/unit/modules/onboarding/test_invitation_rich_text.py`; this file proves the wiring: the
contract with `body`, the lifecycle (no side effects on preview, same rendering on send), and
that the credential link is server-only.
"""

from html.parser import HTMLParser
from typing import Any

import pytest
from httpx import AsyncClient

from hrms.core.config.settings import get_settings
from hrms.modules.onboarding.invitation_compose import brand_logo_url, with_brand_header

from .test_invitation_compose import (  # noqa: F401 - fixtures are collected by name
    GOOD_BODY,
    _counts,
    _no_dispatch,
    _outbox_for,
    _q,
    _send,
    _url,
)
from .test_onboarding_case import _register_tenant
from .test_onboarding_invite import _create_case, _teardown_with_tokens, _token_from_invite_url

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]

SUBJECT = "Welcome to {{company_name}}"


def _t(text: str, *marks: dict[str, Any]) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


def _p(*inline: dict[str, Any]) -> dict[str, Any]:
    return {"type": "paragraph", "content": list(inline)}


LINK_P = _p(_t("{{onboarding_url}}"))


def _doc(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "content": list(blocks)}


GOOD_DOC = _doc(
    {"type": "heading", "attrs": {"level": 2}, "content": [_t("Hello {{candidate_first_name}}")]},
    _p(
        _t("Join ", {"type": "bold"}),
        _t("{{company_name}}", {"type": "italic"}),
        _t(" - see ", {"type": "underline"}),
        _t("our site", {"type": "link", "attrs": {"href": "https://example.org/about"}}),
    ),
    {"type": "orderedList", "content": [{"type": "listItem", "content": [_p(_t("Bring ID"))]}]},
    LINK_P,
)


class _Audit(HTMLParser):
    allowed = {"p", "h2", "h3", "ul", "ol", "li", "strong", "em", "u", "a", "br"}

    def __init__(self) -> None:
        super().__init__()
        self.bad: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self.allowed:
            self.bad.append(tag)
        for name, value in attrs:
            if not ((tag == "a" and name in {"href", "rel"}) or (tag == "p" and name == "style")):
                self.bad.append(f"{tag}.{name}")
            if name == "href" and not (value or "").startswith(("https://", "http://", "mailto:")):
                self.bad.append(f"href={value}")


def _without_brand_header(html_body: str) -> str:
    """Every invitation opens with the system's own logo header (not HR-authored content). It must
    be exactly that header, and the rest of the body is what the allowlist audits."""
    header = with_brand_header("", brand_logo_url(get_settings().web_app_base_url))
    assert html_body.startswith(header)
    return html_body[len(header) :]


def _assert_allowlisted(html_body: str) -> None:
    audit = _Audit()
    audit.feed(_without_brand_header(html_body))
    assert audit.bad == []


async def _preview(client: AsyncClient, headers: dict[str, str], case_id: str, **body: Any) -> Any:
    return await client.post(_url(case_id, "invitation/preview"), headers=headers, json=body)


# ------------------------------------------------------------------------ request contract


@pytest.mark.parametrize(
    "payload",
    [
        {"subject": SUBJECT},  # neither representation
        {"subject": SUBJECT, "body": GOOD_BODY, "body_doc": GOOD_DOC},  # both: ambiguous
        {"subject": SUBJECT, "body_doc": GOOD_DOC, "onboarding_url": "https://evil.example/x"},
        {"subject": SUBJECT, "body_doc": GOOD_DOC, "token": "abc"},
        {"subject": SUBJECT, "body_doc": "<p>{{onboarding_url}}</p>"},  # HTML string, not a doc
        {"subject": SUBJECT, "body_doc": [GOOD_DOC]},
    ],
)
async def test_preview_rejects_ambiguous_or_forged_requests(
    client: AsyncClient, payload: dict[str, Any]
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        before = await _counts(company_id, case["id"])
        r = await _preview(client, headers, case["id"], **payload)
        assert r.status_code == 422, r.text
        assert await _counts(company_id, case["id"]) == before
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_send_rejects_both_representations_and_url_or_token_override(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        for extra in (
            {"body": GOOD_BODY, "body_doc": GOOD_DOC},
            {"body_doc": GOOD_DOC, "invite_url": "https://evil.example/x"},
            {"body_doc": GOOD_DOC, "onboarding_url": "https://evil.example/x"},
            {"body_doc": GOOD_DOC, "token": "abc"},
        ):
            r = await _send(client, headers, case["id"], subject=SUBJECT, **extra)
            assert r.status_code == 422, r.text
        assert await _counts(company_id, case["id"]) == {"outbox": 0, "message": 0, "token": 0}
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------------------------- preview


async def test_legacy_plain_text_preview_unchanged(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        r = await _preview(client, headers, case["id"], subject=SUBJECT, body=GOOD_BODY)
        assert r.status_code == 200, r.text
        assert "PREVIEW-LINK-NOT-ACTIVE" in r.json()["data"]["text_body"]
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_document_preview_renders_formatting_and_has_no_side_effects(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        before = await _counts(company_id, case["id"])
        audit_before = await _q(company_id, "SELECT count(*) FROM audit_log WHERE company_id=:cid")
        r = await _preview(client, headers, case["id"], subject=SUBJECT, body_doc=GOOD_DOC)
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert (
            "<h2>Hello Asha</h2>" in d["html_body"] and "<strong>Join </strong>" in d["html_body"]
        )
        assert "<ol><li>Bring ID</li></ol>" in d["html_body"]
        assert 'href="https://example.org/about"' in d["html_body"]
        assert "PREVIEW-LINK-NOT-ACTIVE" in d["html_body"] and d["link_is_placeholder"] is True
        _assert_allowlisted(d["html_body"])
        assert (
            await _counts(company_id, case["id"])
            == before
            == {"outbox": 0, "message": 0, "token": 0}
        )
        assert (
            await _q(company_id, "SELECT count(*) FROM audit_log WHERE company_id=:cid")
            == audit_before
        )
        got = await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)
        assert got.json()["data"]["status"] == "DRAFT"  # onboarding state untouched
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize(
    "bad_doc",
    [
        _doc(_p(_t("hi"))),  # no link placeholder
        _doc(LINK_P, LINK_P),  # duplicate
        _doc(_p(_t("{{onboarding_url}}", {"type": "bold"}))),  # formatted
        _doc(
            {"type": "bulletList", "content": [{"type": "listItem", "content": [LINK_P]}]}
        ),  # nested
        _doc(_p(_t("x {{nope}}")), LINK_P),  # unknown placeholder
        _doc(_p(_t("{{comp", {"type": "bold"}), _t("any_name}}")), LINK_P),  # split placeholder
        _doc({"type": "iframe"}, LINK_P),  # unknown node
        _doc(_p(_t("x", {"type": "code"})), LINK_P),  # unknown mark
        _doc(
            {"type": "paragraph", "attrs": {"style": "x"}, "content": [_t("a")]}, LINK_P
        ),  # unknown attr
        _doc(_p(_t("go", {"type": "link", "attrs": {"href": "javascript:alert(1)"}})), LINK_P),
        _doc(_p(_t("go", {"type": "link", "attrs": {"href": "//evil.example/x"}})), LINK_P),
        _doc(
            _p(_t("go", {"type": "link", "attrs": {"href": "https://good.example@evil.example/"}})),
            LINK_P,
        ),
        _doc(
            _p(_t("go", {"type": "link", "attrs": {"href": "https://xn--80ak6aa92e.com/‮"}})), LINK_P
        ),
        _doc(_p(_t("go", {"type": "link", "attrs": {"href": "https://аpple.example/"}})), LINK_P),
        _doc(_p(_t("a\x00b")), LINK_P),
        _doc(_p(_t("x" * 6000)), LINK_P),
    ],
)
async def test_invalid_documents_are_rejected_not_partially_rendered(
    client: AsyncClient, bad_doc: dict[str, Any]
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        r = await _preview(client, headers, case["id"], subject=SUBJECT, body_doc=bad_doc)
        assert r.status_code == 422, r.text
        assert r.json()["error"]["details"][0]["code"] == "INVITATION_TEMPLATE_INVALID"
        assert "html_body" not in r.text
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_excessive_depth_and_size_are_rejected(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        nested: dict[str, Any] = _p(_t("x"))
        for _ in range(40):
            nested = {"type": "bulletList", "content": [{"type": "listItem", "content": [nested]}]}
        many = _doc(*[_p(_t("a")) for _ in range(800)], LINK_P)
        for bad in (_doc(nested, LINK_P), many):
            r = await _preview(client, headers, case["id"], subject=SUBJECT, body_doc=bad)
            assert r.status_code == 422, r.text[:200]
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize(
    "subject",
    [
        "Hi\r\nBcc: x@y.test",
        "Hi Bcc: x@y.test",
        "Hi x",
        "Hi\x00",
        "",
        "{{onboarding_url}}",
        "x" * 151,
    ],
)
async def test_subject_rules_apply_to_documents(client: AsyncClient, subject: str) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        r = await _preview(client, headers, case["id"], subject=subject, body_doc=GOOD_DOC)
        assert r.status_code == 422, r.text
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_special_characters_in_case_data_are_escaped_in_every_context(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        evil = "<img src=x onerror=alert(1)>\"'&"
        case = await _create_case(client, headers, candidate_first_name=evil)
        doc = _doc(
            {"type": "heading", "attrs": {"level": 3}, "content": [_t("{{candidate_first_name}}")]},
            _p(
                _t(
                    "{{candidate_name}}",
                    {"type": "link", "attrs": {"href": "https://example.org/x"}},
                )
            ),
            LINK_P,
        )
        r = await _preview(client, headers, case["id"], subject=SUBJECT, body_doc=doc)
        assert r.status_code == 200, r.text
        html_body = r.json()["data"]["html_body"]
        authored = _without_brand_header(html_body)
        assert "<img" not in authored and "&lt;img src=x onerror=alert(1)&gt;" in authored
        _assert_allowlisted(html_body)
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


# --------------------------------------------------------------------------------- send


async def test_document_send_matches_preview_uses_real_url_and_redacts_history(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        preview = (
            await _preview(client, headers, case["id"], subject=SUBJECT, body_doc=GOOD_DOC)
        ).json()["data"]
        r = await _send(client, headers, case["id"], subject=SUBJECT, body_doc=GOOD_DOC)
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        raw = _token_from_invite_url(d["invite_url"])
        assert d["email_queued"] is True and d["case"]["status"] == "INVITED"

        (row,) = await _outbox_for(company_id)
        # what HR previewed is what was queued; only the link differs
        assert row.subject == preview["subject"]
        # the body HR previewed is the body queued (real link swapped in); the send adds only the
        # optional mobile-app paragraph before the shared footer
        footer = '<p style="font-size:12px;color:#555">This link'
        approved = preview["html_body"].split(footer)[0].replace("PREVIEW-LINK-NOT-ACTIVE", raw)
        assert row.html_body.startswith(approved)
        assert d["invite_url"] in row.html_body and "PREVIEW-LINK-NOT-ACTIVE" not in row.html_body
        _assert_allowlisted(row.html_body)

        msgs = (await client.get(_url(case["id"], "messages"), headers=headers)).json()["data"]
        assert len(msgs) == 1 and "not retained" in msgs[0]["body_text"]
        assert raw not in msgs[0]["body_text"] and "Bring ID" in msgs[0]["body_text"]
        stored = await _q(company_id, "SELECT subject, rendered_text_body FROM onboarding_message")
        audit = await _q(
            company_id,
            "SELECT after_json::text FROM audit_log WHERE action='ONBOARDING_INVITE_SENT'",
        )
        assert audit and not any(raw in str(c) for r_ in stored + audit for c in r_)
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_invalid_document_send_mints_no_token_and_queues_nothing(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        bad = _doc(_p(_t("no link")))
        r = await _send(client, headers, case["id"], subject=SUBJECT, body_doc=bad)
        assert r.status_code == 422, r.text
        assert await _counts(company_id, case["id"]) == {"outbox": 0, "message": 0, "token": 0}
        got = await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)
        assert got.json()["data"]["status"] == "DRAFT"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_document_send_is_idempotent_per_request_id(client: AsyncClient) -> None:
    from uuid import uuid4

    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        rid = str(uuid4())
        first = await _send(
            client, headers, case["id"], subject=SUBJECT, body_doc=GOOD_DOC, send_request_id=rid
        )
        second = await _send(
            client, headers, case["id"], subject=SUBJECT, body_doc=GOOD_DOC, send_request_id=rid
        )
        assert first.status_code == second.status_code == 200
        assert (
            second.json()["data"]["replayed"] is True
            and second.json()["data"]["invite_url"] is None
        )
        assert await _counts(company_id, case["id"]) == {"outbox": 1, "message": 1, "token": 1}
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_mixed_legacy_and_document_sends_coexist(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        a = await _send(client, headers, case["id"], subject=SUBJECT, body=GOOD_BODY)
        b = await _send(client, headers, case["id"], subject=SUBJECT, body_doc=GOOD_DOC)
        assert a.status_code == b.status_code == 200
        assert (await _counts(company_id, case["id"]))["message"] == 2
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------------ built-in templates


async def test_compose_offers_templates_and_each_previews_and_sends_via_the_real_path(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        d = (await client.get(_url(case["id"], "invitation/compose"), headers=headers)).json()[
            "data"
        ]
        templates = d["templates"]
        assert len(templates) >= 2 and templates[0]["key"] == "standard"
        assert templates[0]["body"] == d["default_body"]  # first template is the default
        before = await _counts(company_id, case["id"])
        for t in templates:
            r = await _preview(client, headers, case["id"], subject=t["subject"], body=t["body"])
            assert r.status_code == 200, (t["key"], r.text)
            out = r.json()["data"]
            assert "{{" not in out["text_body"] + out["html_body"] + out["subject"]
            assert "PREVIEW-LINK-NOT-ACTIVE" in out["html_body"]
            _assert_allowlisted(out["html_body"])
        assert await _counts(company_id, case["id"]) == before  # choosing/previewing sends nothing

        last = templates[-1]
        sent = await _send(client, headers, case["id"], subject=last["subject"], body=last["body"])
        assert sent.status_code == 200, sent.text
        (row,) = await _outbox_for(company_id)
        assert sent.json()["data"]["invite_url"] in row.html_body
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)
