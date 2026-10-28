# Onboarding invitation — rich-text contract (Phase B design)

Status: renderer + backend tests implemented; **API wiring and the frontend editor are not
enabled** until this design and its security tests are approved.

## Decision: a structured document, not HTML

The client sends a constrained JSON document (`body_doc`, the shape TipTap/ProseMirror emits
natively). The server **validates it against a closed schema and generates every byte of HTML
itself** with `html.escape`. The server never parses, "cleans" or forwards client HTML.

Why not an HTML allowlist + sanitizer: no HTML sanitizer is installed (`uv.lock` has none), and a
sanitizer is a parser-differential surface (mutation XSS). A schema-validated tree has no such
surface, needs **no new backend dependency**, and extends the existing guarantee in
`invitation_compose.py` ("safety by construction": every character escaped, the only link is the
server-built one). Client HTML is simply not an accepted input.

Editor dependency (frontend, later phase): TipTap `@tiptap/react` + `starter-kit` limited to
paragraph, heading(2–3), bold, italic, underline, bullet/ordered list, hard break, link, history.
Its JSON output is the wire format. Nothing else is needed.

## Wire contract (backward compatible)

* `body` (plain text, current behaviour) is unchanged and remains the default.
* New optional `body_doc` (object) on preview and send. If present it is used instead of `body`;
  sending both is rejected (when wired). Old callers/drafts and the default template keep working.
* Subject stays plain text with the existing rules (single line, ≤150, no controls, no link).

## Allowed document

| Node | Allowed attrs | Children |
| --- | --- | --- |
| `doc` | – | blocks |
| `paragraph` | – | inline |
| `heading` | `level` ∈ {2,3} | inline |
| `bulletList` / `orderedList` | (`start` int tolerated, dropped) | `listItem` |
| `listItem` | – | `paragraph` only (no nesting) |
| `text` | – (`marks`) | – |
| `hardBreak` | – | – |

Marks: `bold`, `italic`, `underline`, `link{href}` (`target`/`rel`/`class` tolerated, dropped,
never rendered). Anything else — unknown node/mark/key/attr, wrong types, `style`, `class`,
images, tables, nesting beyond one list level — is **rejected (422), never stripped**.
Limits: depth ≤ 6, ≤ 500 nodes, total text ≤ `BODY_MAX_LENGTH` (5000), no control characters,
no empty text nodes.

Output tags: `p h2 h3 ul ol li strong em u a br`. The only attributes ever emitted are `href` and
`rel="noopener noreferrer"` on `a`. No `style`/`class`/`on*`/`id`.

## Link rules (`link.href`)

* Schemes: `https`, `http`, `mailto` only. Everything else (`javascript:`, `data:`, `vbscript:`,
  `file:`, `blob:`, scheme-relative `//x`, relative paths) is rejected.
* No whitespace/control chars/backslashes, ≤ 2000 chars, no `{{ }}` (links cannot carry
  placeholders), http(s) needs a host and **no userinfo** (`https://good@evil`), mailto needs a
  plausible address.
* A link may not point into the app's onboarding path or equal the server link: that URL is
  reserved for the server.
* If the visible text itself looks like a URL/host, it must match the href's host (blocks the
  classic "text says bank.com, href goes elsewhere" trick). Residual risk: descriptive link text
  can still mislead; HR is a trusted-but-fallible author, and the real credential link is never
  user-authored.

## Placeholders

Same `{{name}}` catalogue and validation as today, applied **per text node** (a placeholder split
across marked runs is "malformed" and rejected, so formatting can't hide one). Template text and
resolved value are escaped separately; values are single-line (`_clean_value`). Missing optional
value ⇒ its paragraph/list item is omitted; missing required ⇒ error; nothing silently blank.

## Invitation link

`{{onboarding_url}}` must occur **exactly once**, as the sole, unmarked text of a top-level
paragraph. Anywhere else (heading, list, mark, inside a link, twice, absent) is rejected. The
renderer replaces that paragraph with the same server-built call-to-action markup the plain-text
path uses, from the `onboarding_url` argument. Preview passes the inert
`…/onboarding/PREVIEW-LINK-NOT-ACTIVE`; send passes the freshly minted URL; history keeps the
existing redaction (`REDACTED_LINK`).

## One renderer for preview and send

`render_invitation_document()` is the only entry point; it returns the same
`RenderedInvitation(subject, html_body, text_body)` as `render_invitation()`. The service layer
(not changed in this step) will call it from both preview and send exactly as it calls the legacy
function, preserving: preview has no token/outbox/message/audit side effects; send validates the
final document **before** any token is issued; idempotency (`send_request_id`), the outbox and
the token lifecycle are untouched.

## Out of scope / follow-ups

* Wiring `body_doc` into schemas/service/router, and persisting a document snapshot (history
  currently stores redacted plain text, which stays sufficient).
* Finding for Phase E: `email_templates.build_invite_email / build_changes_requested_email /
  build_activated_email` interpolate candidate/company/rejection-reason text into HTML **without
  escaping**. They must go through the same escaping boundary.

## Implementation notes — API integration (gate 2)

* `POST …/invitation/preview`: `subject` + exactly one of `body` | `body_doc` (neither or both ⇒ 422).
  `body` became optional in the schema only to allow this; legacy `body`-only callers are unchanged.
* `POST …/send-invite`: unchanged shape plus optional `body_doc`; `body` + `body_doc` ⇒ 422; neither ⇒
  built-in default (as before). Schemas are `extra="forbid"`, so `onboarding_url`, `invite_url`,
  `token`, `html_body`, `mobile_url` are rejected.
* `OnboardingInvitationService.render` / `redacted_text` take `body_doc` and dispatch to
  `render_invitation_document` (re-checking mutual exclusion). Token service passes it through the
  existing dry-run → issue token → render → outbox → history → audit sequence; that sequence,
  idempotency and the outbox are untouched. History keeps the redacted plain-text projection.
* `email_templates.py`: the activated / changes-requested (live) and invite (no callers) builders now
  HTML-escape interpolated values. The invitation renderer does not protect them; they are a separate
  boundary.
