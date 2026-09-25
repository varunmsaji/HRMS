# Release Hardening — Phase 2: Security Remediation

Date: 2026-09-25

## Executive summary

```text
Phase 2:
Authentication and production exposure hardening
```

This phase closed exactly four findings from `docs/audits/PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.md`: **SEC-08** (invite acceptance authenticating an existing account without its
password), **SEC-07** (password reset not revoking existing sessions), **SEC-05** (no security
headers on either app), and **OPS-06** (unconditional production API-docs exposure). Every fix
reuses an existing mechanism already in the codebase — `IdentityService.login`'s own
`verify_password`/lockout logic for SEC-08, `get_current_user`'s existing `Session.revoked_at`
check for SEC-07, FastAPI's own `docs_url=None` idiom for OPS-06 — rather than inventing new
infrastructure. No database migration was required (see §Migration). SEC-09, SEC-06, DEP-01,
SEC-10, SEC-11, KMS, email, Docker, Nginx, HTTPS, backups, Sentry, metrics, audit logging, and
all payroll/leave/comp-off business rules were untouched, exactly as scoped.

```text
Production status: NOT READY FOR PUBLIC RELEASE
```

Closing these four findings is a security-hardening milestone, not a production-readiness
signal — the findings listed above remain fully open.

## SEC-08 — invite authentication

**Original vulnerability** (`account_invite/service.py`, existing-user branch): when an invite
targeted an email address that already had an account, `accept()` added a new company membership
and immediately issued that account a real session via `issue_tokens_for` — without ever checking
the submitted `password` against the account's actual password hash. The `password` field was
read only in the *new*-account branch (to hash and store it); in the *existing*-account branch it
was accepted by the endpoint and then silently ignored. Anyone who obtained a valid, unexpired,
unaccepted invite link for someone else's email — a forwarded email, a leaked link, a guessed
token — could log in as that person without ever knowing their password. The resolve response
also implicitly told the frontend nothing about which flow applied, so the UI always showed a
"create a new password" form even for accounts that already had one.

**Attack scenario**: an admin invites `alice@company.com`, who already has an HRMS account from a
different company. Alice's inbox is compromised, forwarded, or the link otherwise leaks (browser
history, a shared support ticket, an intercepted email). The attacker opens the link, types *any*
password into the "create a password" form, and is logged straight in as Alice — with a real
access/refresh token pair for her account — never having supplied Alice's actual password.

**Implementation** (`account_invite/service.py`):
- `accept()` now looks up the invite's email *before* deciding how to validate the submitted
  password. When an existing `User` row is found: the account-lockout check
  (`locked_until`), the real `verify_password(existing_user.password_hash, password)` check, and
  the failed-attempt counter (`increment_failed_login`/`reset_failed_login`) are the exact same
  calls `IdentityService.login` already makes — reused, not reimplemented. A mismatch raises the
  same `InvalidCredentialsError` (401) or `AccountLockedError` (423) login itself raises, and
  critically **never calls `mark_accepted`** — the invite stays live and re-attemptable, exactly
  like a normal failed login doesn't burn your account.
- The password-*strength* check (`is_password_strong_enough`) moved into the new-account branch
  only — for an existing account, `password` is a login credential being verified, not a new one
  being chosen, so the strength rule no longer applies to it.
- `PublicAccountInviteRead` (the pre-accept `GET` response) gained `existing_account: bool`, so
  the frontend can render "log in to accept" instead of "create a password" *before* the user
  submits anything. This isn't an enumeration risk: the invitee's own email is already known to
  them (it's the address the invite was sent to) and to the inviter (who typed it in); the invite
  token itself is the only secret in this flow, and it's unchanged.

**Frontend** (`apps/web/src/app/accept-invite/[token]/page.tsx`): the form now branches on
`existing_account`. For an existing account: no first/last name fields (irrelevant — the account
already has one), no confirm-password field (this isn't setting a password), the password field's
description changes to "Your existing account password," `autoComplete` switches from
`new-password` to `current-password`, and the submit button reads "Accept invitation" instead of
"Create account." A 401 response shows "Incorrect password" on the password field (not a generic
banner); a 423 shows "This account is temporarily locked" — the identical wording and status-code
handling `login/page.tsx` already uses, kept consistent rather than inventing new copy.

**Tests** (`tests/integration/modules/account_invite/test_account_invite.py`, all passing):
- `test_invite_existing_account_resolve_flags_existing_account` — the public resolve response
  correctly reports `existing_account: true`/`false`.
- `test_invite_existing_account_invite_alone_cannot_authenticate` — the core regression: a wrong
  password against an existing account's invite returns 401 `INVALID_CREDENTIALS`, grants no
  session, grants no membership/role, and leaves the invite acceptable on retry.
- `test_invite_existing_account_correct_password_accepts` — the *correct* password still accepts
  normally: a new membership is granted in a second company and a real session issues.
- `test_invite_existing_account_wrong_password_does_not_leak_other_companies` — a failed attempt's
  response contains nothing beyond the generic auth failure (no `companies` list, no tokens).
- Every pre-existing account-invite test (13) still passes unmodified in behavior — several
  already happened to reuse the same password across two accepts for the same email (by
  coincidence, for a different reason), which is exactly the "correct password" path this fix
  preserves.
- Frontend: 6 new tests in `apps/web/src/app/accept-invite/[token]/page.test.tsx` cover both form
  variants, the wrong-password rejection, the correct-password success, and the locked-account
  message.

**Residual risk**: the existing-account branch is protected by the same coarse, IP-only "auth"
rate limiter (10/min) the whole public accept endpoint already had, plus the per-account lockout
(5 failed attempts / 15 min) reused from login — not login's own dedicated, email+IP-keyed
limiter (`SEC-11`/`SEC-02`'s own finding tracks that coarseness for the "auth" bucket generally;
this phase did not extend a new bucket to a fourth endpoint, per its own scope). This is a
brute-force *cost* consideration, not a bypass of the fix itself — every attempt still requires
the real password.

## SEC-07 — password-reset session invalidation

**Original vulnerability** (`identity/service.py:314-341`, pre-fix): `reset_password` updated the
`password_hash` and marked the reset token used, and did nothing else. Every already-issued
access token remained valid until its own expiry (15 minutes, `jwt_access_ttl_minutes`), and every
refresh token remained valid for up to 30 days (`jwt_refresh_ttl_days`), continuing to mint new
access tokens indefinitely — completely unaffected by the password change that was supposed to be
the recovery action.

**Session architecture** (traced from `identity/service.py` + `core/auth/dependencies.py` +
`core/db/models/identity.py`): access tokens are JWTs carrying a `session_id`, but they are **not**
purely stateless — `get_current_user` (the dependency every protected route depends on) re-checks
`Session.revoked_at` against the database on *every single request*, not only at refresh time.
Refresh tokens are separately hash-stored, TTL-bound `RefreshToken` rows, each linked to a
`session_id` and a `token_family_id` (already used elsewhere for reuse-detection). Both `Session`
and `RefreshToken` carry a plain `user_id` column with no RLS (mirroring `PasswordResetToken`'s
own precedent — a password reset has no single tenant to scope to, since one `User` can belong to
several companies).

**Implementation**:
- `IdentityRepository.revoke_all_sessions_for_user` (`core/db/repositories/identity.py`, new) —
  two `UPDATE`s: every non-revoked `Session` row for the user gets `revoked_at = now()`, every
  non-revoked `RefreshToken` row gets `revoked_at = now()` / `revoked_reason = reason`. Scoped by
  `user_id` alone — every company, every device, not just one family (contrast with the existing
  `revoke_refresh_family`, which is deliberately narrower and used elsewhere for a different
  purpose: refresh-token-reuse detection on a single family).
  `reset_password` calls it with `reason="PASSWORD_RESET"` right after updating the password hash.
- Because `get_current_user` already re-checks `Session.revoked_at` on every request, this takes
  effect **immediately** for already-issued access tokens — no separate access-token blocklist,
  no change to `create_access_token`/`decode_access_token`, no new column, no migration.

**Tests** (`tests/integration/auth/test_password_reset.py`, all passing):
- `test_reset_password_invalidates_existing_access_and_refresh_token` — logs in, confirms the
  access token works (`GET /v1/auth/me` → 200), resets the password, and confirms the *same*
  access token now gets 401 `INVALID_TOKEN` and the *same* refresh token gets 401 on
  `POST /v1/auth/token/refresh`.
- `test_reset_password_invalidates_every_session_not_only_one` — two independent logins (standing
  in for two devices/browsers), one password reset, both access tokens rejected afterward — not
  only the one that happened to be attached to the reset request (this endpoint has no session
  context at all; it acts purely on the token's target `user_id`).
- Existing tests (unmodified): new password successfully logs in; old password is rejected; the
  reset token is single-use.

**Residual risk**: no audit-log entry is written for a password reset (matching the pre-existing,
deliberate posture already documented in both `forgot_password` and `reset_password`'s own
docstrings — `AuditLog.company_id` is a real tenant FK, and a password reset has no single tenant
to attach one to). Session revocation on password *change while already logged in* (as opposed to
the public forgot/reset flow) doesn't exist as a feature in this codebase at all yet — out of
scope, since no such endpoint exists to revoke sessions for.

## SEC-05 — security headers

**Headers implemented** (backend: `core/security_headers.py`, new `SecurityHeadersMiddleware`;
frontend: `apps/web/src/middleware.ts`, new):

| Header | Backend | Frontend |
| --- | --- | --- |
| `X-Content-Type-Options` | `nosniff` | `nosniff` |
| `X-Frame-Options` | `DENY` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(), usb=()` | same |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'; base-uri 'none'` (all routes except `/docs`/`/redoc`) | see below |
| `Strict-Transport-Security` | only when `request.url.scheme == "https"` | only when `x-forwarded-proto: https` |

**Backend CSP**: the API is a pure JSON service — the only HTML it ever serves is Swagger
UI/ReDoc, and OPS-06 (below) already removes both outside development — so `default-src 'none'`
with no exceptions is correct everywhere else; a JSON response has no scripts/styles/images/fonts
of its own to permit. `/docs`/`/redoc` are exempted from that one CSP line (Swagger/ReDoc load
their own JS/CSS bundle from a CDN) but still get every other header.

**Frontend CSP**: built from what the codebase actually contains, checked before writing any
directive — no WebSocket usage, no inline `<script>` tags, no external script or font CDN (fonts
are self-hosted via `next/font`), no `next/image` remote origin, and no `<img>` element anywhere
in `src/` (all confirmed by search). `script-src` uses a per-request nonce plus `'strict-dynamic'`
— Next.js's own documented App Router pattern: `middleware.ts` sets the nonce on the
`Content-Security-Policy` response header, and Next automatically threads that same nonce onto its
own inline hydration/bootstrap scripts, with **no `'unsafe-inline'`/`'unsafe-eval'` needed for
scripts at all**. Verified empirically, not just by reading the docs: with the dev server running,
every `<script>` tag in the rendered `/login` page carried the matching `nonce="…"` attribute and
none lacked one. `style-src` keeps `'unsafe-inline'` — Tailwind's compiled stylesheet is a
same-origin `<link>` already covered by `'self'`, but CSP's `style-src` also governs the raw
`style=""` HTML attribute, which nonces cannot cover (CSP3 §6.2), and this codebase has exactly
one component using it (`components/ui/progress.tsx`'s dynamic width bar) — the same narrow
exception Next.js's own strict-CSP guide documents for React apps. `connect-src` includes the
configured API origin (`NEXT_PUBLIC_API_URL`), since this is a client fetching a separate-origin
JSON API. `upgrade-insecure-requests` is gated to `NODE_ENV === "production"` only — in dev
(always plain HTTP) it would try to upgrade the dev API origin to `https:` and break every
request.

**HSTS**: deliberately conditional, not tied to `environment`/`NODE_ENV` alone. Docker/Nginx/HTTPS
termination is explicitly a separate, not-yet-started phase — this codebase has no TLS in front of
it anywhere yet. Sending `Strict-Transport-Security` on a host not actually reachable over HTTPS
would make browsers refuse *all* future plain-HTTP connections to it, which is a lockout, not a
protection. Backend: `request.url.scheme` already reflects `ProxyHeadersMiddleware`'s (OPS-02)
trusted-proxy-resolved `X-Forwarded-Proto` — so HSTS activates automatically, with zero further
code changes, the day a trusted reverse proxy actually terminates TLS in front of this app, and
not one moment before. Frontend: same rule, checked against the `x-forwarded-proto` request
header directly (inert today, since none is configured).

**Tests** (`tests/security/test_security_headers.py`, backend, all passing): headers present on a
normal 200 response and on an `AppError`-driven 401 response; no HSTS header over plain HTTP; HSTS
header present once the request is confirmed HTTPS. The frontend middleware has no dedicated
Vitest test (it needs a live HTTP request cycle Vitest's DOM environment doesn't provide) — it was
instead verified against a running `next dev` server: response headers inspected directly with
`curl`, and the rendered page's HTML confirmed to have zero `<script>` tags without the matching
nonce.

## OPS-06 — production API documentation

**Previous exposure** (`app.py:30-32`, pre-fix): `docs_url="/docs"`, `redoc_url="/redoc"`, and
`openapi_url="/v1/openapi.json"` were hardcoded, unconditional FastAPI constructor arguments —
reachable, unauthenticated, in every environment including production, publishing the entire
route surface and every request/response schema to any caller.

**New production behavior**: `create_app` now accepts an optional `settings` parameter (defaulting
to `get_settings()`, same pattern already used throughout this codebase — e.g.
`IdentityService.__init__`). All three URLs are set to the literal string only when
`settings.is_development` is true, and to `None` otherwise — FastAPI's own documented mechanism
for disabling them entirely: none of the three routes get registered at all, so a request to any
of them in a non-development environment is an ordinary 404, not a custom auth check that has to
be separately maintained and could itself have a bug. `is_development` is the exact same boundary
`Settings._guard_non_development_config` already draws for every other production-safety guard in
this codebase (secrets, CORS, S3, KMS) — staging gets treated identically to production here, not
a third posture invented for this one finding.

**Tests** (`tests/security/test_api_docs_exposure.py`, all passing): `/docs`, `/redoc`, and
`/v1/openapi.json` all return 200 with `Settings()`'s development default; all three return 404
under both `environment="production"` and `environment="staging"` (constructed with the minimum
fields `_guard_non_development_config` itself requires); and — proving schema generation for
development/testing was not broken — the development-mode OpenAPI document is fetched and its
shape asserted (`info.title == "HRMS API"`, `/v1/auth/login` present in `paths`).

## Files changed

**SEC-08** (invite authentication):
- `apps/api/src/hrms/modules/account_invite/service.py`
- `apps/api/src/hrms/modules/account_invite/schemas.py`
- `apps/api/tests/integration/modules/account_invite/test_account_invite.py`
- `apps/web/src/app/accept-invite/[token]/page.tsx`
- `apps/web/src/app/accept-invite/[token]/page.test.tsx` (new)

**SEC-07** (password-reset session invalidation):
- `apps/api/src/hrms/modules/identity/service.py`
- `apps/api/src/hrms/core/db/repositories/identity.py`
- `apps/api/tests/integration/auth/test_password_reset.py`

**SEC-05** (security headers):
- `apps/api/src/hrms/core/security_headers.py` (new)
- `apps/api/src/hrms/app.py` (middleware registration)
- `apps/api/tests/security/test_security_headers.py` (new)
- `apps/web/src/middleware.ts` (new)

**OPS-06** (production API docs):
- `apps/api/src/hrms/app.py` (shared with SEC-05's middleware registration, above)
- `apps/api/tests/security/test_api_docs_exposure.py` (new)

**Carried over, untouched by this phase, still present from Phase 1** (Ruff/mypy/formatting
remediation — see `RELEASE_HARDENING_PHASE_1_CI_REMEDIATION.md`; listed here only because they
remain in the same uncommitted working tree, per this phase's own "do not commit" instruction):
all files listed in that report's own "Files changed" section, plus the `branches/page.test.tsx`
frontend fix from that phase.

## Migration

```text
No migration required.
```

SEC-07 and SEC-08 both reuse columns that already exist (`Session.revoked_at`,
`RefreshToken.revoked_at`/`revoked_reason`, `User.password_hash`/`locked_until`/
`failed_login_count`) — nothing new was added to the schema. SEC-05 and OPS-06 are
middleware/app-configuration only. Alembic head is unchanged: `20261004110000` (confirmed via
`alembic heads` against a fresh migrated database, both before and after this phase's changes).

## Test results

All figures below are from a full run against a genuinely fresh, isolated `postgres:16-alpine`
container (mirroring `.github/workflows/ci.yml` exactly: same init scripts, same
`alembic upgrade head`, same `hrms_app` role verification) — not the shared local `hrms_dev`
database, which (as documented in Phase 1 §7) still carries unrelated pre-existing manual-testing
data that blocks some fixtures locally but does not exist in CI's own fresh container. This phase
independently re-confirmed that distinction is still accurate: a permission check blocked this
session from cleaning further local-only rows discovered while validating SEC-07, so the isolated
fresh-database path — already established and proven correct in Phase 1 — was used again instead.

| Check | Phase 1 baseline | After Phase 2 | Status |
| --- | ---: | ---: | ------ |
| Backend tests (fresh DB) | 1,683 passed / 0 failed / 0 errors | **1,697 passed / 0 failed / 0 errors** | PASS |
| Frontend tests (Vitest) | 388 passed / 0 failed | **394 passed / 0 failed** | PASS |
| Frontend TypeScript | pass | pass | PASS |
| Frontend production build | pass | pass (middleware confirmed compiled: `ƒ Middleware 26.9 kB`) | PASS |
| Ruff check | pass | pass | PASS |
| Ruff format | pass | pass | PASS |
| mypy | pass | pass | PASS |
| Import lint | 1 kept, 0 broken | 1 kept, 0 broken | PASS |

The +14 backend tests and +6 frontend tests are exactly this phase's new coverage (SEC-08: 4
backend + 6 frontend; SEC-07: 2 backend; SEC-05: 4 backend; OPS-06: 4 backend). No pre-existing
test was weakened; one assertion was strengthened (none — Phase 1's invite-permission assertion
was the only such change, and it is unrelated to this phase). No new failure was found or waved
off as "pre-existing" — every number above is a full, not partial, run.

## Regression check

`git diff --check`: clean. `git status --short` / `git diff --stat`: every file touched maps to
one of the four workstreams above, Phase 1's already-reviewed carryover, or a brand-new test file.
No leave/payroll/comp-off business logic was touched. No lint rule was disabled, no
`# type: ignore` was added, no `Any` was introduced, no CSP directive was weakened to make a test
pass (the CSP a passing test asserts is the same strict CSP the app actually serves), no test
assertion was weakened.

## Remaining security findings

```text
SEC-09 — email verification — not addressed
SEC-06 — refresh token in localStorage — not addressed
DEP-01 — python-jose — not addressed
SEC-10 — password/MFA policy — not addressed
SEC-11 — Redis failure policy (and the "auth" bucket's own coarseness, noted in SEC-08's
         residual risk above) — not addressed
KMS credentials — not addressed
Email provider (real SES, currently logging-only) — not addressed
Docker — not addressed
Nginx / HTTPS termination — not addressed (this is also why HSTS stays inert in both apps —
         see SEC-05 above)
Backups — not addressed
Sentry / observability — not addressed
Audit logging (password reset/forgot still write no audit record, by the same pre-existing,
         documented design this phase did not change) — not addressed
Payroll statutory rates / legal / compliance — not addressed
Local dev-DB hygiene beyond Phase 1's own cleanup (a further stale `legal_entity` →
         `branch`/`employment` chain under the demo company was discovered while validating
         SEC-07 locally; a cleanup attempt was blocked by this session's own permission system,
         has zero effect on CI — verified via the fresh-DB run above — and was left for the user)
```

## Commit recommendation

Working tree is clean, scoped, and passing on every check — no commits were made, per instruction
("Do NOT commit"). Suggest committing by workstream when ready: (1) Phase 1's CI remediation
(unrelated to this phase, already reviewed in its own report), (2) SEC-08, (3) SEC-07, (4)
SEC-05 + OPS-06 (share `app.py`'s middleware-registration block, natural to commit together), (5)
docs.

Final status:

```text
NOT READY FOR PUBLIC RELEASE
```
