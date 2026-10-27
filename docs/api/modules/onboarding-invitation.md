# Onboarding invitation email (HR-editable)

HR composes, previews and confirms the pre-joining invitation from the onboarding case page
(`Compose Invitation -> Preview -> Confirm & send -> status in "Invitation emails"`). It is a
welcome / onboarding invitation, **not** an offer letter. Delivery reuses the existing transactional
outbox (`email_outbox`) and sender; there is no second transport.

## Endpoints (all under `/v1`, tenant from the authenticated context only)

| Method & path | Permission | Notes |
| --- | --- | --- |
| `GET /onboarding-cases/{id}/invitation/compose` | `ONBOARDING.CREATE` | Defaults, recipient, resolved case facts (designation/department may be `null`), `invitable`, `has_active_link` (+expiry), placeholder catalogue, length limits. |
| `POST /onboarding-cases/{id}/invitation/preview` | `ONBOARDING.CREATE` | Body `{subject, body}`. Same renderer as send, **inert link** (`PREVIEW-LINK-NOT-ACTIVE`). No token, outbox row, history row or audit entry. 422 `INVITATION_TEMPLATE_INVALID` for bad content. |
| `POST /onboarding-cases/{id}/send-invite` | `ONBOARDING.CREATE` | Backward compatible: no body = built-in default invitation. Optional `{subject, body, send_request_id}`; unknown fields (e.g. `company_id`) are rejected (422). |
| `GET /onboarding-cases/{id}/messages` | `ONBOARDING.VIEW` | Invitation history for the case with live delivery status. |

`send-invite` response additions: `email_queued`, `email_delivery_status` (`QUEUED`/`NOT_QUEUED`),
`message_id`, `message_status`, `replayed`, `invitation_expires_at`; `invite_url` is `null` only for a
replay. `email_sent` is a **deprecated alias of `email_queued`**: it means "queued", never "delivered".

## Content rules

* Body is **plain text** (blank line = paragraph). All text and values are HTML-escaped when the HTML
  part is built, so markup typed by HR or present in data is shown as text; the only link in the HTML
  is the server-built one (http/https). No client-side sanitiser is relied on.
* Placeholders `{{name}}` from one allowlist (`invitation_compose.PLACEHOLDERS`): `candidate_first_name`,
  `candidate_last_name`\*, `candidate_name`, `company_name`, `designation`\*, `department`\*,
  `joining_date`, `invitation_expiry`, `onboarding_url` (\* optional). Unknown/empty/malformed names are
  rejected. Values are resolved server-side from the case's own tenant records.
* Missing optional value: in the **body** the paragraph containing it is omitted; in the **subject** it
  is a validation error. A required value that is missing is an error, never an empty string.
* Body must contain `{{onboarding_url}}`; the subject must not. Subject: 1 line, <= 150 chars, no control
  characters (CR/LF rejected, not stripped). Body <= 5000 chars.
* Dates: `15 January 2027`; expiry `22 January 2027 (UTC)`. Date-only values need no timezone conversion.
* Plain-text and HTML parts are both produced; the text part carries the link.

## Send, retry, resend, duplicates

* One transaction: lock case row (`FOR UPDATE`) -> validate/render with inert link (nothing written on
  failure) -> issue token (revokes the previous live token) -> render with real link -> outbox row ->
  history row -> audit. A worker delivers after commit. A rollback leaves no token, outbox row or history.
* If the outbox write fails the token stays valid (HR can copy the link) and the response says
  `NOT_QUEUED`; the history row is `NOT_QUEUED`.
* **Delivery retry** is automatic and handled by the outbox (same row, same body, same token); history
  shows `RETRYING`. There is deliberately **no manual "retry" for a `FAILED` message**: the outbox blanks
  bodies when a message is final and the raw token is never stored, so the same link cannot be re-sent.
* **Resend** = a new `send-invite`: new token, new message, previous link revoked (the UI says so).
* **Duplicate HTTP requests**: the same `send_request_id` returns the first result (`replayed: true`,
  `invite_url: null`) without a new token. Without it, simultaneous sends are serialised by the row lock
  and each is an intentional resend; exactly one live token remains.

## History and retention (`onboarding_message`)

Stores the approved subject, recipient, actor, timestamps, `outbox_message_key` and a plain-text body in
which the credential link is replaced by `[secure onboarding link - not retained]` (HTML is not kept: it
is derivable and carries the link). No raw token anywhere durable (history, audit, logs). Status is **not**
stored: it is read from the linked `email_outbox` row, so they cannot diverge:
`NOT_QUEUED | QUEUED | RETRYING | SENDING | PROVIDER_ACCEPTED | FAILED | UNKNOWN`.
`PROVIDER_ACCEPTED` means the mail provider accepted it - **not** inbox delivery (no delivery/bounce
events are processed). Only a coarse `failure_class` is exposed, never provider error text.
Retention: rows live as long as the case (cases are soft-deleted); no purge job exists - add one with the
platform data-retention policy if a shorter window is required. Tenant isolation: `company_id` + forced RLS
(`tenant_isolation`), plus company filters in every query; the platform email-log API is not exposed to HR.

## Migration

`20261028090000_onboarding_message` (down: `20261027092000`). Additive: one table, indexes, RLS, no data
migration, no new DB grants (default privileges cover `hrms_app`). Downgrade drops the table (loses the
invitation history only; tokens and outbox rows untouched). Tested up -> down -> up on a disposable
Postgres 16. **Not** applied to any shared database: run `alembic upgrade head` as the schema owner.
