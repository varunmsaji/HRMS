"""Structured rich-text body for the onboarding invitation.

The client sends a constrained JSON document (the shape TipTap/ProseMirror emits), never HTML. The
document is validated against a closed schema and *every byte of HTML is generated here* with
`html.escape`; client markup is not an accepted input, so there is no sanitiser to bypass. Anything
outside the schema is rejected (422), never silently stripped. See
`docs/design/ONBOARDING_RICH_TEXT_CONTRACT.md`.

Preview and send both call `render_invitation_document`; the real invitation URL is supplied by the
caller (an inert placeholder URL in preview) and can only appear through the `{{onboarding_url}}`
paragraph, which must be the sole, unformatted text of a top-level paragraph and occur exactly once.
"""

import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from hrms.modules.onboarding.invitation_compose import (
    _BY_KEY,
    _TOKEN,
    BODY_MAX_LENGTH,
    InvitationValues,
    RenderedInvitation,
    _check_placeholders,
    _clean_value,
    _invalid,
    _render_subject,
    append_mobile_and_footer,
    call_to_action_html,
    validate_subject_template,
)

MAX_DEPTH = 6
MAX_NODES = 500
MAX_HREF_LENGTH = 2000
HEADING_LEVELS = (2, 3)

_BLOCK_CONTAINER_TYPES = {"bulletList": "ul", "orderedList": "ol"}
_MARK_TAGS = {"bold": "strong", "italic": "em", "underline": "u"}
_LINK_EXTRA_ATTRS = {"target", "rel", "class"}  # editors emit these: accepted, never output
_ORDERED_LIST_ATTRS = {"start", "type"}

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # text nodes: no controls (no raw \n either)
_HREF_FORBIDDEN = re.compile(r"[^\x21-\x7e]")  # whitespace, controls and all non-ASCII
_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")
_MAILTO = re.compile(r"^mailto:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", re.IGNORECASE)
_URLISH = re.compile(r"(?:https?://|www\.)[^\s]+", re.IGNORECASE)
_CTA_TEXT = re.compile(r"^\s*\{\{\s*onboarding_url\s*\}\}\s*$")


def _bad(message: str) -> Exception:
    return _invalid("body", message)


@dataclass
class _Budget:
    nodes: int = 0
    text_chars: int = 0

    def node(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise _bad("The message is too complex.")

    def text(self, value: str) -> None:
        self.text_chars += len(value)
        if self.text_chars > BODY_MAX_LENGTH:
            raise _bad(f"Body must be at most {BODY_MAX_LENGTH} characters.")


def _expect_dict(node: object, what: str) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise _bad(f"Invalid {what} in the message.")
    return node


def _check_keys(node: dict[str, Any], allowed: set[str], what: str) -> None:
    extra = set(node) - allowed - {"type"}
    if extra:
        raise _bad(f"Unsupported property in {what}: {sorted(map(str, extra))[0][:40]}.")


def _children(node: dict[str, Any], *, required: bool) -> list[Any]:
    content = node.get("content")
    if content is None:
        if required:
            raise _bad("The message is empty.")
        return []
    if not isinstance(content, list):
        raise _bad("Invalid message structure.")
    return content


# ----------------------------------------------------------------------------------------- URLs


def validate_href(href: object, onboarding_url: str) -> str:
    if not isinstance(href, str) or not href:
        raise _bad("A link needs an address.")
    if len(href) > MAX_HREF_LENGTH:
        raise _bad("A link address is too long.")
    if _HREF_FORBIDDEN.search(href) or "\\" in href:
        raise _bad("A link address contains unsupported characters.")
    if "{{" in href or "}}" in href:
        raise _bad("A link address cannot contain placeholders.")
    lowered = href.lower()
    if lowered.startswith("mailto:"):
        if not _MAILTO.match(href):
            raise _bad("Enter a plain email address for a mailto link.")
        return href
    if not (lowered.startswith("https://") or lowered.startswith("http://")):
        raise _bad("Links must start with https://, http:// or mailto:.")
    parts = urlsplit(href)
    host = parts.hostname or ""
    if not host or not _HOST.match(host) or "@" in parts.netloc:
        raise _bad("A link address is not valid.")
    try:
        parts.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError:
        raise _bad("A link address is not valid.") from None
    _reject_reserved_target(parts.hostname or "", parts.path, onboarding_url)
    return href


def _reject_reserved_target(host: str, path: str, onboarding_url: str) -> None:
    """The onboarding path of this app is reserved for the server-built credential link."""
    server = urlsplit(onboarding_url)
    if (server.hostname or "").lower() == host.lower() and path.lower().startswith("/onboarding"):
        raise _bad("Links to the onboarding page are added by the system; use {{onboarding_url}}.")


def _host_of(url_text: str) -> str:
    text = url_text if "://" in url_text else "https://" + url_text
    host = (urlsplit(text).hostname or "").lower()
    return host.removeprefix("www.")


def _check_link_label(label: str, href: str) -> None:
    """Visible link text that looks like an address must point at that same host."""
    target_host = (urlsplit(href).hostname or "").lower().removeprefix("www.")
    for match in _URLISH.finditer(label):
        shown = match.group(0).rstrip(".,;:)")
        if _host_of(shown) != target_host:
            raise _bad("A link's visible address must match where it goes.")


# ------------------------------------------------------------------------------------- validation


@dataclass(frozen=True)
class _Mark:
    kind: str
    href: str | None = None


@dataclass(frozen=True)
class _Text:
    text: str
    marks: tuple[_Mark, ...]


@dataclass(frozen=True)
class _Break:
    pass


_Inline = _Text | _Break


@dataclass(frozen=True)
class _Paragraph:
    inline: list[_Inline]


@dataclass(frozen=True)
class _Cta:
    pass


@dataclass(frozen=True)
class _Heading:
    level: int
    inline: list[_Inline]


@dataclass(frozen=True)
class _ListBlock:
    ordered: bool
    items: list[list[_Inline]]


_Block = _Paragraph | _Cta | _Heading | _ListBlock


def _validate_marks(raw: object, budget: _Budget, onboarding_url: str) -> tuple[_Mark, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _bad("Invalid formatting in the message.")
    marks: list[_Mark] = []
    seen: set[str] = set()
    for item in raw:
        mark = _expect_dict(item, "formatting")
        budget.node()
        kind = mark.get("type")
        if not isinstance(kind, str) or kind in seen:
            raise _bad("Unsupported formatting in the message.")
        seen.add(kind)
        _check_keys(mark, {"attrs"}, "formatting")
        attrs = mark.get("attrs")
        if kind in _MARK_TAGS:
            if attrs not in (None, {}):
                raise _bad("Unsupported formatting option.")
            marks.append(_Mark(kind))
        elif kind == "link":
            attrs = _expect_dict(attrs, "link")
            _check_keys(attrs, {"href"} | _LINK_EXTRA_ATTRS, "link")
            for extra in _LINK_EXTRA_ATTRS & set(attrs):
                if attrs[extra] is not None and not isinstance(attrs[extra], str):
                    raise _bad("Invalid link option.")
            marks.append(_Mark("link", validate_href(attrs.get("href"), onboarding_url)))
        else:
            raise _bad(f"Unsupported formatting: {kind[:30]}.")
    return tuple(marks)


def _validate_inline(raw: object, budget: _Budget, onboarding_url: str) -> _Inline:
    node = _expect_dict(raw, "text")
    budget.node()
    kind = node.get("type")
    if kind == "hardBreak":
        _check_keys(node, set(), "line break")
        return _Break()
    if kind != "text":
        raise _bad("Unsupported content in a paragraph.")
    _check_keys(node, {"text", "marks"}, "text")
    text = node.get("text")
    if not isinstance(text, str) or not text:
        raise _bad("Invalid text in the message.")
    if _CONTROL.search(text):
        raise _bad("Body contains unsupported control characters.")
    budget.text(text)
    marks = _validate_marks(node.get("marks"), budget, onboarding_url)
    names = _check_placeholders(text, "body")  # per node: a placeholder can't hide across runs
    if "onboarding_url" in names:
        raise _bad("The secure link must be on its own line, with no formatting.")
    for mark in marks:
        if mark.kind == "link" and mark.href is not None:
            _check_link_label(text, mark.href)
    return _Text(text, marks)


def _validate_inlines(node: dict[str, Any], budget: _Budget, onboarding_url: str) -> list[_Inline]:
    return [_validate_inline(c, budget, onboarding_url) for c in _children(node, required=False)]


def _is_cta(node: dict[str, Any]) -> bool:
    content = node.get("content")
    if not (isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict)):
        return False
    only = content[0]
    return (
        only.get("type") == "text"
        and not only.get("marks")
        and isinstance(only.get("text"), str)
        and bool(_CTA_TEXT.match(only["text"]))
        and set(only) <= {"type", "text", "marks"}
    )


def _validate_block(raw: object, budget: _Budget, onboarding_url: str, depth: int) -> _Block:
    node = _expect_dict(raw, "paragraph")
    budget.node()
    if depth > MAX_DEPTH:
        raise _bad("The message is nested too deeply.")
    kind = node.get("type")
    if kind == "paragraph":
        _check_keys(node, {"content"}, "paragraph")
        if _is_cta(node):
            budget.node()
            budget.text("{{onboarding_url}}")
            return _Cta()
        return _Paragraph(_validate_inlines(node, budget, onboarding_url))
    if kind == "heading":
        _check_keys(node, {"attrs", "content"}, "heading")
        attrs = _expect_dict(node.get("attrs"), "heading")
        _check_keys(attrs, {"level"}, "heading")
        level = attrs.get("level")
        if type(level) is not int or level not in HEADING_LEVELS:
            raise _bad("Headings must be level 2 or 3.")
        return _Heading(level, _validate_inlines(node, budget, onboarding_url))
    if kind in _BLOCK_CONTAINER_TYPES:
        _check_keys(node, {"attrs", "content"}, "list")
        list_attrs = node.get("attrs")
        if list_attrs is not None:
            _check_keys(_expect_dict(list_attrs, "list"), _ORDERED_LIST_ATTRS, "list")
        items: list[list[_Inline]] = []
        for item in _children(node, required=True):
            li = _expect_dict(item, "list item")
            budget.node()
            if li.get("type") != "listItem":
                raise _bad("Unsupported content in a list.")
            _check_keys(li, {"content"}, "list item")
            entries = _children(li, required=True)
            if len(entries) != 1:
                raise _bad("List items may contain a single paragraph.")
            inner = _expect_dict(entries[0], "list item")
            budget.node()
            if inner.get("type") != "paragraph":
                raise _bad("List items may contain a single paragraph.")
            _check_keys(inner, {"content"}, "paragraph")
            items.append(_validate_inlines(inner, budget, onboarding_url))
        return _ListBlock(kind == "orderedList", items)
    raise _bad(f"Unsupported content in the message: {str(kind)[:30]}.")


def validate_document(body_doc: object, onboarding_url: str) -> list[_Block]:
    root = _expect_dict(body_doc, "message")
    if root.get("type") != "doc":
        raise _bad("Invalid message structure.")
    _check_keys(root, {"content"}, "message")
    budget = _Budget()
    budget.node()
    blocks = [_validate_block(b, budget, onboarding_url, 1) for b in _children(root, required=True)]
    ctas = sum(isinstance(b, _Cta) for b in blocks)
    if ctas != 1:
        raise _bad(
            "The body must include the secure onboarding link ({{onboarding_url}}) exactly once, "
            "on its own line."
        )
    return blocks


# -------------------------------------------------------------------------------------- rendering


class _Omit(Exception):  # noqa: N818 - control-flow signal, not an error
    """An optional placeholder has no value: the enclosing block is omitted."""


def _resolve(name: str, values: InvitationValues) -> str:
    value = values.values.get(name)
    cleaned = _clean_value(value) if value is not None else ""
    if cleaned:
        return cleaned
    if _BY_KEY[name].required:
        raise _bad("A required placeholder has no value for this candidate.")
    raise _Omit


def _fill(template: str, values: InvitationValues) -> tuple[str, str]:
    """(escaped html, plain text): template text and each value are escaped independently."""
    html_parts: list[str] = []
    text_parts: list[str] = []
    pos = 0
    for match in _TOKEN.finditer(template):
        literal = template[pos : match.start()]
        html_parts.append(html.escape(literal))
        text_parts.append(literal)
        value = _resolve(match.group(1), values)
        html_parts.append(html.escape(value))
        text_parts.append(value)
        pos = match.end()
    tail = template[pos:]
    html_parts.append(html.escape(tail))
    text_parts.append(tail)
    return "".join(html_parts), "".join(text_parts)


def _render_inlines(inlines: list[_Inline], values: InvitationValues) -> tuple[str, str]:
    html_out: list[str] = []
    text_out: list[str] = []
    for item in inlines:
        if isinstance(item, _Break):
            html_out.append("<br>")
            text_out.append("\n")
            continue
        piece_html, piece_text = _fill(item.text, values)
        href: str | None = None
        for mark in item.marks:
            if mark.kind == "link":
                href = mark.href
            else:
                tag = _MARK_TAGS[mark.kind]
                piece_html = f"<{tag}>{piece_html}</{tag}>"
        if href is not None:
            piece_html = (
                f'<a href="{html.escape(href, quote=True)}" rel="noopener noreferrer">'
                f"{piece_html}</a>"
            )
            if piece_text != href:
                piece_text = f"{piece_text} ({href})"
        html_out.append(piece_html)
        text_out.append(piece_text)
    return "".join(html_out), "".join(text_out)


def _render_blocks(
    blocks: list[_Block], values: InvitationValues, onboarding_url: str
) -> tuple[list[str], list[str]]:
    html_parts: list[str] = []
    text_parts: list[str] = []
    for block in blocks:
        if isinstance(block, _Cta):
            html_parts.append(call_to_action_html(onboarding_url))
            text_parts.append(onboarding_url)
            continue
        try:
            if isinstance(block, _Paragraph):
                h, t = _render_inlines(block.inline, values)
                if t.strip():
                    html_parts.append(f"<p>{h}</p>")
                    text_parts.append(t)
            elif isinstance(block, _Heading):
                h, t = _render_inlines(block.inline, values)
                if t.strip():
                    html_parts.append(f"<h{block.level}>{h}</h{block.level}>")
                    text_parts.append(t)
            else:
                items_html: list[str] = []
                items_text: list[str] = []
                for number, item in enumerate(block.items, start=1):
                    try:
                        h, t = _render_inlines(item, values)
                    except _Omit:
                        continue  # only this item is dropped
                    if t.strip():
                        items_html.append(f"<li>{h}</li>")
                        items_text.append(f"{number}. {t}" if block.ordered else f"- {t}")
                if items_html:
                    tag = "ol" if block.ordered else "ul"
                    html_parts.append(f"<{tag}>{''.join(items_html)}</{tag}>")
                    text_parts.append("\n".join(items_text))
        except _Omit:
            continue  # the paragraph/heading holding an unavailable optional value is omitted
    return html_parts, text_parts


def render_invitation_document(
    *,
    subject_template: str,
    body_doc: object,
    values: InvitationValues,
    onboarding_url: str,
    mobile_url: str | None = None,
) -> RenderedInvitation:
    """Validates and renders a rich-text invitation. Raises `ValidationError` (422) for anything
    unsendable. Same output type and footer as `render_invitation`, so preview and send (and the
    redacted history copy) treat both bodies identically."""
    subject_tpl = validate_subject_template(subject_template)
    if not onboarding_url.lower().startswith(("https://", "http://")):
        raise _bad("The onboarding link must be an http(s) URL.")
    blocks = validate_document(body_doc, onboarding_url)
    subject = _render_subject(subject_tpl, values)
    html_parts, text_parts = _render_blocks(blocks, values, onboarding_url)
    text_body, html_body = append_mobile_and_footer(
        "\n\n".join(text_parts), "".join(html_parts), mobile_url
    )
    return RenderedInvitation(subject=subject, html_body=html_body, text_body=text_body)
