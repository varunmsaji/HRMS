# Release Hardening — Phase 3A: Targeted Security Remediation

Date: 2026-09-25

## 1. Executive Summary

```text
Production status: NOT READY FOR PUBLIC RELEASE
```

This phase audited the six findings Phase 2 explicitly left open (SEC-09, SEC-06, DEP-01,
SEC-10, SEC-11, and the KMS/encryption question) against the **current** codebase before changing
anything, per this phase's own brief. All six were genuinely still open — none had been silently
fixed by later work — so all six were remediated, plus one real architectural conflict the
original brief's own KMS section had not anticipated (see §9).

Summary of outcome:

| Finding | Action |
| --- | --- |
| SEC-09 — email verification | **CLOSED**. Token-based verification built from scratch; registration unchanged, subsequent logins blocked until verified. |
| SEC-06 — refresh token in `localStorage` | **CLOSED**. Refresh tokens now travel only as an HttpOnly, `SameSite=Lax` cookie; the JSON response no longer contains one. |
| DEP-01 — `python-jose` | **CLOSED**. Migrated to `PyJWT`; identical claims, algorithm pinning, and error handling. |
| SEC-10 — password policy / MFA | **PARTIALLY CLOSED**. Added an offline common-password blocklist. MFA formally **DEFERRED** — it is functionally absent and out of this phase's scope by its own instructions. |
| SEC-11 — Redis failure policy | **CLOSED** for the `Depends()`-based limiters (`auth`, `login`, `token_refresh`); they now fail closed with a clean `503`, matching the onboarding-upload middleware's existing policy. |
| KMS / PII encryption | **CLOSED**, with a scope change from the original brief. AWS KMS was found to be a **hard, enforced** boot dependency in non-development environments — not unused/vestigial as the brief's own framing assumed. Per an explicit product decision (recorded below), it was replaced with a self-hosted application master key. |

Two decisions were escalated to the product owner before implementation, per this phase's own
"do not guess" instruction for the KMS question and the brief's expectation that an unverified-
account access policy is already "intended," not something to invent:

1. **KMS resolution** — approved: migrate PII-DEK wrapping from AWS KMS to an application-supplied
   master key, in every environment, aligning with the stated no-AWS-managed-services
   architecture. No data migration was required (no real production ciphertext existed yet).
2. **Unverified-account login policy** — approved: the registration flow is unchanged (the
   registrant's first session issues immediately); only a *subsequent* login is blocked until the
   address is verified.

No AWS service was added. No leave/attendance/payroll/RBAC/upload-validation code was touched.
Nothing was committed or pushed (§14/§18).

## 2. Phase 2 Baseline

Reproduced from `docs/audits/RELEASE_HARDENING_PHASE_2_SECURITY_REMEDIATION.md` and independently
re-verified against current source before any change (§3 below):

| Check | Phase 2 result |
| --- | ---: |
| Backend tests (fresh DB) | 1,697 passed / 0 failed / 0 errors |
| Frontend tests (Vitest) | 394 passed / 0 failed |
| Frontend TypeScript | pass |
| Frontend production build | pass |
| Ruff check / format | pass |
| mypy | pass |
| Import lint | 1 kept, 0 broken |

Phase 2 closed SEC-08, SEC-07, SEC-05, and OPS-06. It explicitly left SEC-09, SEC-06, DEP-01,
SEC-10, SEC-11, and KMS untouched — this phase's exact scope.

## 3. Current-State Audit

Every finding below was re-verified against the live source tree (not assumed from the old audit
or Phase 2's own "not addressed" list) before any change was made.

| Finding | Original status (2026-09-17) | Current implementation (found) | Phase 3A action | Final status |
| --- | --- | --- | --- | --- |
| SEC-09 | Registration signs the creator in with no email verification. | Unchanged — no verification concept existed anywhere in the codebase (no column, table, endpoint, or frontend page). | Built email verification end-to-end (§4). | **CLOSED** |
| SEC-06 | 30-day refresh token in `localStorage`. | Unchanged — `TokenResponseData.refresh_token` still returned in the JSON body; `apps/web/lib/auth/token-storage.ts` still wrote it to `localStorage`; the backend had a dead cookie-read fallback (`request.cookies.get("hrms_refresh")`) with nothing ever writing that cookie. | Wired the write side: HttpOnly cookie set by every token-issuing endpoint; JSON body no longer carries the refresh token (§5). | **CLOSED** |
| DEP-01 | `python-jose` in `pyproject.toml`, imported in `core/auth/jwt.py`. | Unchanged — `python-jose[cryptography]>=3.3.0` still declared; `jwt.py` still did `from jose import JWTError, jwt`. | Replaced with `PyJWT`; deleted the dependency (§6). | **CLOSED** |
| SEC-10 (password) | 8 chars + letter/digit, no breach-list. | Unchanged. | Added an offline common-password blocklist (§7). | **PARTIALLY CLOSED** |
| SEC-10 (MFA) | Absent. | A single unused `User.mfa_enabled` boolean column — no enrollment, challenge, verification, or UI anywhere. | None — documented as deferred per this phase's own instruction not to build a half-finished MFA system (§7). | **DEFERRED** |
| SEC-11 | No failure policy; a Redis outage 500s. | The three `Depends()`-based buckets (`auth`, `login`, `token_refresh`) still had no `try/except` around the Redis calls — an unhandled `RedisError` fell through to the generic `500 INTERNAL_ERROR` handler. The onboarding-upload *middleware* limiter (added since the original audit) already had a correct, explicit `503` failure policy. | Wrapped the three `Depends()` limiters in the same fail-closed-clean pattern; added a Redis socket/connect timeout (§8). | **CLOSED** |
| KMS / PII encryption | PAN/Aadhaar/bank stored in plaintext. | **Already fixed by an earlier phase**, and solidly built: AES-256-GCM envelope encryption, versioned ciphertext, DEK cache, key registry. AWS KMS wrapped the DEK and was a **hard boot-time requirement** in staging/production (`Settings._guard_non_development_config`, `app.py`'s `lifespan()`) — contradicting the stated no-AWS architecture. | Product-approved migration of DEK wrapping from AWS KMS to a self-hosted application master key, in every environment (§9). | **CLOSED** (with an approved scope change) |

## 4. SEC-09 — Email Verification

**What was built** (smallest addition consistent with the existing account/session architecture,
reusing every pattern `forgot_password`/`reset_password` already established):

- `user.email_verified_at` (nullable timestamp; `NULL` = unverified) and a new
  `email_verification_token` table — identical hash-only-storage, single-use, TTL-bound shape to
  `password_reset_token`. Migration: `20261004112000_email_verification.py`.
- `IdentityService.send_verification_email` — issues a `secrets.token_urlsafe(32)` token (SHA-256
  hashed at rest, 24-hour TTL), emails it via the *existing* `EmailSender` abstraction
  (`onboarding.email_sender.get_email_sender` — already cross-module-imported by
  `IdentityService.forgot_password`, so this introduces no new import-boundary exception). No new
  email provider was introduced: the default is still the logging-only sender: a real provider is
  a separate, later configuration decision, matching the brief's own instruction.
- `IdentityService.verify_email` — single-use, TTL-bound; an invalid/expired/already-used token and
  a never-issued one all raise the identical `401 INVALID_TOKEN`.
- `IdentityService.resend_verification_email` — same anti-enumeration posture as `forgot_password`
  (always returns success; only actually sends if the account exists, is active, and is still
  unverified).
- `IdentityService.login` now raises `403 EMAIL_NOT_VERIFIED` when `email_verified_at is None`,
  checked *after* the password is confirmed correct (never doubles as an account-existence oracle)
  and *before* any token issuance.
- New routes: `POST /auth/email/verify`, `POST /auth/email/resend-verification` — both public,
  rate-limited on their own new bucket (`email_verification`, 10/min/IP) rather than joining the
  already-flagged-as-overly-shared `auth` bucket (SEC-11's own tracked coarseness).
- Frontend: `/verify-email/[token]` page (auto-submits on load, handles success/expired/invalid);
  the login page now recognizes `EMAIL_NOT_VERIFIED` and shows a "resend verification email"
  action instead of the generic invalid-credentials message.

**The registration-vs-login split (the approved product decision).** Registration
(`organisation/service.register_company`) is unchanged: it still issues the registrant's first
session immediately via `issue_tokens_for` (never through `login()`), then sends the verification
email best-effort afterward. Only a *subsequent* call to `POST /auth/login` is blocked while
unverified. This keeps the blast radius to exactly what the original 2026-09-17 finding
described (an unverified address permanently bound to a live tenant) without touching the
company-bootstrap transaction at all.

**Invited accounts are exempt, deliberately.** `account_invite.service.accept`'s new-account
branch marks `email_verified_at` at creation time — accepting a token that was emailed to that
exact address is itself proof of receipt, and this keeps the existing-account/new-account
invite flows (SEC-08, Phase 2) working unchanged. The existing-account branch was already
unaffected: it never calls `login()`.

**A real SQLAlchemy pitfall found and fixed along the way**: `User.email_verified_at` has a
Python-side column default (`datetime.now(UTC)`) so every pre-existing direct `User(...)`
construction across ~12 test/seed files — none of which know this column exists — keeps
defaulting to "verified," not suddenly locking out every fixture-created user. SQLAlchemy's
client-side `default=` fires whenever the value being inserted is `None`, indistinguishable from
never having been set at all — so `organisation.repository.insert_user` cannot force a real `NULL`
for the *one* path (self-service registration) that needs it by passing `email_verified_at=None`
to the constructor; that silently gets overridden back to "verified now." The fix: insert with
the default first, then an explicit `UPDATE ... SET email_verified_at = :value` (not subject to
INSERT-time defaults) sets the exact value the caller asked for. Caught by this phase's own new
integration tests, not by inspection — see §14/§15.

**Verified**: token unpredictable (32 bytes via `secrets.token_urlsafe`), expires (24h), single-use
(`used_at`), never logged (only the hashed value and metadata ever touch a log line or the DB),
replay fails (`401 INVALID_TOKEN`), invalid token fails identically, verification leaks no account
information, resend is rate-limited and anti-enumerating, verified accounts log in normally,
unverified accounts are rejected with a clear, actionable, non-generic error.

## 5. SEC-06 — Refresh Token Storage

**Full trace done first** (per this phase's own instruction), confirming: access tokens are
returned in the JSON body and kept client-side (short 15-minute TTL, unchanged — this phase did
not move access tokens, only refresh tokens); refresh tokens were returned in the same JSON body
and written to `localStorage`; the backend already had a dead read-only fallback
(`request.cookies.get("hrms_refresh")`) that nothing ever populated; CORS already had
`allow_credentials=True` (unused until now); the frontend API client had no
`credentials: "include"` anywhere.

**What changed:**

- `hrms.core.auth.refresh_cookie` (new) — `set_refresh_cookie`/`clear_refresh_cookie`. Cookie
  shape: `HttpOnly` always; `Secure` conditional on `request.url.scheme == "https"` — the exact
  same conditional pattern SEC-05's HSTS header already established (this deployment has no TLS
  termination anywhere yet; a hardcoded `Secure=True` would make the cookie silently never send
  today and activates automatically the day a reverse proxy terminates TLS); `SameSite=Lax`;
  `Path=/v1/auth` (scoped to the routes that actually consume it, not sent on every API request).
- `TokenResponseData` (service-layer, unchanged) is no longer returned directly from any HTTP
  route. A new `PublicTokenResponseData` (identical, minus `refresh_token`) is what every
  token-issuing endpoint actually serializes: `POST /auth/login`, `POST /auth/token/refresh`,
  `POST /companies/register`, `POST /public/account-invites/{token}/accept`. Each sets the cookie
  from the service-layer value first, then returns the public shape.
- `POST /auth/token/refresh`'s `body` parameter is now `RefreshRequest | None = None` — a browser
  client sends no body at all (the cookie carries the token); the JSON-body path is preserved for
  any caller that needs to supply a specific token explicitly (kept working correctly for
  reuse-detection tests that must replay an intentionally stale token after the cookie has already
  rotated past it).
- `POST /auth/logout` now also clears the cookie.
- Frontend: `StoredSession`/`TokenResponseData` no longer carry a refresh token at all;
  `lib/api/client.ts` sends `credentials: "include"` on every request (safe — the cookie is
  path-scoped server-side) and no longer reads/writes a refresh token anywhere.

**CSRF**: deliberately not given a separate double-submit token. `SameSite=Lax` cookies are not
attached to cross-site `fetch`/XHR requests of any method — only to a cross-site top-level *GET*
navigation — so a malicious page cannot trigger a cross-site `POST /v1/auth/token/refresh` with
this cookie attached. A separate CSRF token would be redundant defense for this one endpoint given
that property; adding one was judged to be over-engineering for the smallest safe change.

**Not done, and why**: no `logout-all` endpoint was added (none existed before; out of this
finding's scope) and no cookie `domain=` attribute was set (this deployment's production domain
topology is decided in the not-yet-started Docker/Nginx phase — see §16).

## 6. DEP-01 — python-jose

Confirmed still present exactly as the original audit described: `pyproject.toml` declared
`python-jose[cryptography]>=3.3.0` (resolved to 3.5.0); `core/auth/jwt.py` did
`from jose import JWTError, jwt`. Migrated to `PyJWT>=2.9.0` (2.15.0 resolved):

- `jwt.encode`/`jwt.decode` calls are drop-in compatible; `JWTError` → `jwt.PyJWTError`.
- Every claim preserved exactly: `sub`, `company_id`, `session_id`, `employee_id`, `exp`, `iat`,
  `type`. Algorithm still pinned both directions (`HS256` only, both encode and decode) — no
  algorithm-confusion surface introduced or removed, since the application-level pinning (not the
  library) was already what closed that vector.
- `python-jose` uninstalled from the venv; `pyproject.toml`'s mypy override list no longer
  needs a `jose.*` entry (PyJWT ships its own type stubs).
- One incidental fix: PyJWT emits `InsecureKeyLengthWarning` for the repository-visible 31-char
  dev secrets (intentionally short; production secrets are separately guarded by
  `_guard_non_development_config`'s 32+-char entropy floor) — added to `pytest`'s
  `filterwarnings` so the warning doesn't spam every auth-touching test.

## 7. SEC-10 — Password Policy / MFA

**Password policy.** Audited first: 8-character minimum, mandatory letter+digit, no breach-list,
no history, no rotation. Verdict was NEEDS-IMPROVEMENT specifically because of the missing
breach-list check — the one control NIST 800-63B actually calls for (the mandatory-composition
rule the codebase already enforces is, if anything, mildly at odds with modern guidance, but
removing it wasn't asked for and isn't a security regression to leave alone).

Added `hrms.core.auth.common_passwords` — a small, bundled, offline list of the most commonly
breached/guessed passwords, checked case-insensitively. Deliberately **not** a live
Have-I-Been-Pwned-style API call: this deployment's architecture avoids new external network
dependencies for a control that must not become a single point of failure for every signup, and a
live call would also leak partial password material off this server on every registration. This is
the smallest safe improvement over "no breach-list check at all," not a claim of completeness.

Password rotation and forced history were deliberately left unimplemented — NIST 800-63B
recommends against both, so their absence is an intentional non-fix, correctly reflected as
`NOT APPLICABLE` rather than a residual gap.

**MFA.** Confirmed functionally absent: `User.mfa_enabled` is a single boolean column, set nowhere,
read nowhere, with no enrollment/challenge/verification endpoint or frontend surface at all — not
"partially built," despite the column's existence. Per this phase's own explicit instruction
("do not build a half-finished MFA system just to mark the finding closed" / "document as deferred
unless the repository already contains most of the required infrastructure"), and since it does
not, **MFA is formally deferred**, not attempted. It needs a real design pass (TOTP vs WebAuthn,
enrollment UX, recovery-code flow, session-elevation semantics) that is out of scope for a
targeted remediation phase.

## 8. SEC-11 — Redis Failure Policy

Audited every rate limiter, not assumed from the old finding:

- `rate_limit`/`rate_limit_by_ip_and_email` (`shared/rate_limit.py`) — the `auth`, `login`, and
  `token_refresh` buckets all go through these. Before this phase: no `try/except` around
  `client.incr`/`client.expire` at all; a `RedisError` propagated unhandled to the generic
  `Exception` handler, producing a bare `INTERNAL_ERROR` 500 — a real crash-shaped failure, not a
  designed one, and indistinguishable from an actual application bug.
- `OnboardingUploadRateLimitMiddleware` — **already correct**, added since the original 2026-09-17
  audit: explicit `try/except RedisError` returning a clean `503 RATE_LIMITER_UNAVAILABLE`. Left
  untouched; this phase's fix makes the other three buckets match its existing policy, not the
  other way around.

**Fix**: wrapped the Redis calls in both `Depends()` dependencies in `try/except RedisError`,
raising a new `RateLimiterUnavailableError` (`503 RATE_LIMITER_UNAVAILABLE`) — fails closed (no
request gets through when the limiter itself can't be consulted) with a purpose-built response
instead of a generic crash. Also added a 2-second `socket_timeout`/`socket_connect_timeout` to the
Redis client (previously unset, meaning a hung — not just down — Redis could block a request
indefinitely rather than failing fast).

**Left open, deliberately, as a carried-forward residual risk**: the `auth` bucket (registration,
password forgot/reset, invite-accept) remains one shared, IP-only counter across four unrelated
endpoints — the exact coarseness the original SEC-11 finding and Phase 2's own SEC-08 residual-risk
note both already flagged. Splitting it is a bucket-topology redesign, not a failure-mode fix, and
was out of this specific finding's scope (this phase added exactly one new, separate bucket for
its own new endpoints — `email_verification` — rather than compounding the existing coarse one).

## 9. Encryption / KMS

This section required the most caution, per the brief's own "VERY IMPORTANT" framing, and the
audit's actual finding differs from what the brief assumed.

**What already existed, confirmed solid and untouched in its cryptography**: AES-256-GCM envelope
encryption (`core/crypto/field.py`), a versioned ciphertext format
(`v1:<key_version>:<nonce>:<ciphertext>`), a DEK cache with TTL-bounded resolution
(`core/crypto/keys.py`), and a key registry (`core/crypto/registry.py`, `encryption_keys` table)
supporting rotation. PAN, Aadhaar, bank account number, and employee-dependent Aadhaar are all
encrypted at the field level; nothing about *how* fields are encrypted or decrypted was changed by
this phase.

**What the brief assumed vs. what was actually found**: the brief's framing suggested KMS might be
unused/vestigial configuration safe to leave undocumented. It was not — `Settings.
_guard_non_development_config` refused to boot staging/production without a real `kms_cmk_arn`,
and `app.py`'s `lifespan()` refused to boot without a KMS-unwrappable active key. This is a hard,
enforced dependency, directly contradicting the deployment's own stated architecture (self-hosted
Hostinger VPS, explicitly no AWS-managed services). Per the brief's own decision tree, this needed
a human decision, not a guess — escalated (§1) and approved: migrate the DEK-wrapping mechanism
off AWS KMS entirely.

**What changed**:

- `hrms.core.crypto.kms` (the AWS KMS client wrapper) — **deleted**.
- `hrms.core.crypto.master_key` (new) — mirrors the old `KmsKeyService`'s exact call shape
  (`generate_data_key`/`decrypt_wrapped_dek`) so `DekCache`/`provisioning.py` needed only their
  call sites updated, not their control flow. The DEK is wrapped by encrypting it — AES-256-GCM,
  the same primitive `field.py` already uses, with a fixed non-secret AAD so a wrapped DEK can
  never be silently accepted under a different master key — under a key derived (SHA-256, the same
  derivation the development-only path already used) from a new required setting,
  `Settings.pii_master_key`.
- `pii_master_key` is guarded exactly like the JWT signing secrets: required, must not equal the
  repository-visible development default, must meet the same 32+-char/8+-distinct-character
  entropy floor, enforced in the same `_guard_non_development_config` validator (the previous
  KMS-specific ARN/placeholder check was removed — this setting reuses the JWT-secret guard loop
  directly rather than inventing a parallel mechanism).
- `encryption_keys.kms_key_arn` → renamed `wrapping_key_id` (migration
  `20261004111000_encryption_key_local_wrapping.py`, pure column rename, no data transformation):
  it now stores a non-secret SHA-256 fingerprint of the master key that wrapped that row's DEK
  (for record-keeping/future master-key-rotation-detection), never a KMS ARN.
- `aioboto3` remains a dependency — it is still genuinely needed for the self-hosted MinIO S3
  client (`core/storage.py`) and SES email (`onboarding/email_sender.py`), both unrelated,
  unchanged concerns. Confirmed cleanly separate from the removed KMS usage: MinIO/SES credentials
  (`aws_access_key_id`/`aws_secret_access_key`) were never the same setting as `kms_cmk_arn`/
  `pii_master_key`.

**Why this was safe to do now, and would not have been safe later**: no real production ciphertext
existed anywhere at the time of this change (confirmed — this application's own status is `NOT
READY FOR PUBLIC RELEASE`, and `provision_initial_key`/`rotate_key` are operator-invoked, never
automatic; no environment had ever provisioned a real KMS-backed key outside test fixtures). The
DEK-wrapping mechanism changing does not touch a single existing PII field's ciphertext — the
field-level AES-256-GCM format and every already-encrypted value are completely unaffected. Doing
this migration before any real key had ever been provisioned in a live environment is what made it
a zero-data-migration change; doing it after would have required a real key-rewrap operation
against live ciphertext.

**Key handling verified**: production requires an explicit `pii_master_key` (boot fails otherwise);
not in source control (env-injected, same as JWT secrets); not in the database (only a one-way
fingerprint of it is, in `wrapping_key_id`); not logged (grepped every router/schema file — zero
hits); restarting with the same key still decrypts (existing `test_key_rotation_old_version_still_
decrypts`, `test_current_key_resolves_and_caches_across_calls`); no silent new-key generation in
production (`provision_initial_key`/`rotate_key` are never called automatically; `app.py`'s boot
guard still requires exactly one `ACTIVE` `encryption_keys` row).

## 10. Cost-Constrained Architecture

No AWS-managed service was added by this phase. One was **removed**: AWS KMS. The application no
longer has any dependency, hard or soft, on AWS KMS in any environment. `aioboto3` remains solely
for the two already-approved, pre-existing uses (self-hosted MinIO's S3-compatible API; SES email,
still defaulted off in favor of the logging-only sender). This phase's net effect on the
cost/architecture goal is a strict improvement over the state Phase 3A started in.

## 11. Files Changed

Only Phase 3A's own changes are listed here. Every other file `git status` shows modified predates
this phase (Phase 1's ruff/format remediation and Phase 2's SEC-05/07/08/OPS-06 work, both already
reviewed in their own reports) and was **not touched** by this phase — see §16 for the explicit
carry-forward list.

**DEP-01:**
- `apps/api/pyproject.toml`
- `apps/api/src/hrms/core/auth/jwt.py`

**SEC-11:**
- `apps/api/src/hrms/shared/rate_limit.py`
- `apps/api/tests/unit/shared/test_rate_limit_redis_failure.py` (new)

**KMS / encryption:**
- `apps/api/src/hrms/core/crypto/master_key.py` (new)
- `apps/api/src/hrms/core/crypto/kms.py` (deleted)
- `apps/api/src/hrms/core/crypto/keys.py`
- `apps/api/src/hrms/core/crypto/provisioning.py`
- `apps/api/src/hrms/core/crypto/registry.py`
- `apps/api/src/hrms/core/crypto/models.py`
- `apps/api/src/hrms/core/config/settings.py`
- `apps/api/src/hrms/app.py` (comment only)
- `apps/api/alembic/versions/20261004111000_encryption_key_local_wrapping.py` (new)
- `apps/api/.env.example`, `apps/api/env/.env.{dev,staging,qa,production}.example`
- `apps/api/tests/unit/core/test_crypto_keys.py`
- `apps/api/tests/unit/core/test_settings.py`
- `apps/api/tests/unit/core/test_cors_middleware.py`
- `apps/api/tests/security/test_api_docs_exposure.py`

**SEC-06 (refresh-token cookie):**
- `apps/api/src/hrms/core/auth/refresh_cookie.py` (new)
- `apps/api/src/hrms/modules/identity/router.py`
- `apps/api/src/hrms/modules/identity/schemas.py`
- `apps/api/src/hrms/modules/organisation/router.py`
- `apps/api/src/hrms/modules/account_invite/public_router.py`
- `apps/api/tests/integration/auth/test_auth_security.py`
- `apps/api/tests/integration/auth/test_credential_rate_limit.py`
- `apps/api/tests/integration/auth/test_employee_jwt_linkage.py`
- `apps/api/tests/integration/auth/test_password_reset.py`
- `apps/api/tests/integration/modules/organisation/test_registration_flow.py`
- `apps/api/tests/security/test_rls_runtime_role.py`
- `apps/web/src/lib/auth/token-storage.ts`
- `apps/web/src/lib/auth/types.ts`
- `apps/web/src/lib/api/client.ts`
- `apps/web/src/lib/api/client.test.ts`
- `apps/web/src/app/login/page.tsx` *(shared with SEC-09 below — one edit pass)*
- `apps/web/src/app/register/page.test.tsx`
- `apps/web/src/app/accept-invite/[token]/page.test.tsx` *(one line — removed a now-nonexistent mock field)*
- `apps/web/src/lib/auth/auth-context.test.tsx`

**SEC-09 (email verification):**
- `apps/api/alembic/versions/20261004112000_email_verification.py` (new)
- `apps/api/src/hrms/core/db/models/identity.py`
- `apps/api/src/hrms/core/db/repositories/identity.py`
- `apps/api/src/hrms/core/errors/auth.py`
- `apps/api/src/hrms/modules/identity/service.py`
- `apps/api/src/hrms/modules/identity/email_templates.py`
- `apps/api/src/hrms/modules/organisation/service.py`
- `apps/api/src/hrms/modules/organisation/repository.py`
- `apps/api/src/hrms/modules/account_invite/service.py`
- `apps/api/tests/integration/auth/test_email_verification.py` (new)
- `apps/web/src/app/login/page.tsx`
- `apps/web/src/app/login/page.test.tsx`
- `apps/web/src/app/verify-email/[token]/page.tsx` (new)
- `apps/web/src/app/verify-email/[token]/page.test.tsx` (new)

**SEC-10 (password policy):**
- `apps/api/src/hrms/core/auth/common_passwords.py` (new)
- `apps/api/src/hrms/core/auth/passwords.py`
- `apps/api/tests/unit/core/test_passwords.py` (new)

## 12. Database Migration

Two new migrations, both applied and verified against a fresh database in this phase:

1. `20261004111000_encryption_key_local_wrapping.py` — renames `encryption_keys.kms_key_arn` to
   `wrapping_key_id`. Pure rename, no data transformation, no ciphertext affected.
2. `20261004112000_email_verification.py` — adds `user.email_verified_at`, creates
   `email_verification_token` (FK to `user.id`, `ON DELETE CASCADE` — deliberately unlike
   `password_reset_token`'s `RESTRICT`, since a verification token has no retention requirement of
   its own and should not block deleting a user). Existing rows are backfilled to "verified now"
   in the same migration (see the migration's own docstring for why: this finding is about *new*
   self-service signups, not about retroactively challenging accounts that already exist).

Alembic head after this phase: `20261004112000`. Both migrations were applied against the
persistent local dev database and, separately, against a from-scratch isolated container as part
of the fresh-DB verification run (§14).

## 13. Configuration Changes

- **Removed**: `KMS_CMK_ARN` (every environment).
- **Added**: `PII_MASTER_KEY` — required in staging/production (boot fails without it, same guard
  shape as `JWT_ACCESS_SECRET`/`JWT_REFRESH_SECRET`); optional in development (falls back to the
  existing `DEV_ENCRYPTION_KEY` derivation, unchanged). No secret *values* are recorded anywhere in
  this report or in source control; `.env.example` and `env/.env.{dev,staging,qa,production}.
  example` were updated with the setting name and a placeholder only.
- No other environment variable was added, renamed, or removed.

## 14. Tests

All figures reproduced against a genuinely fresh, isolated `postgres:16-alpine` container (a
second instance on an unused port, migrated from scratch with the same
`infra/docker/postgres/init/*.sql` scripts and `alembic upgrade head` CI uses) — not the
persistent local `hrms_dev` database, which (as Phase 1/2 already documented, and as this phase's
own extensive iteration reconfirmed) accumulates unrelated manual/repeated-test-run data over time
and is not by itself trustworthy evidence of a clean state.

| Check | Phase 2 baseline | After Phase 3A | Status |
| --- | ---: | ---: | --- |
| Backend tests (fresh DB) | 1,697 passed / 0 failed / 0 errors | **1,716 passed / 0 failed / 0 errors** | PASS |
| Frontend tests (Vitest) | 394 passed / 0 failed | **399 passed / 0 failed** | PASS |
| Frontend TypeScript | pass | pass | PASS |
| Frontend production build | pass | pass (`/verify-email/[token]` route compiled) | PASS |
| Ruff check | pass | pass | PASS |
| Ruff format | pass | pass (462 files already formatted) | PASS |
| mypy | pass | pass (167 source files) | PASS |
| Import lint | 1 kept, 0 broken | 1 kept, 0 broken | PASS |

The +19 backend tests are exactly this phase's own new coverage: 10 in
`test_email_verification.py`, 7 in `test_passwords.py`, 2 in `test_rate_limit_redis_failure.py`.
The +5 frontend tests: 1 in `client.test.ts` (asserts `credentials: "include"`), 1 in
`login/page.test.tsx` (the resend-verification flow), 3 in the new `verify-email/[token]/page.
test.tsx`. `tests/security/test_rls_runtime_role.py` (hard-coded to port 5433 by its own design,
per its own file header — so it cannot run against the second, differently-ported fresh container)
was run separately against the persistent database and passed 4/4 clean; its 4 tests are included
in the 1,716 total above.

**A note on process, in the interest of full disclosure**: mid-phase, a first attempt at the SEC-09
`email_verified_at` default introduced a real regression (a new `RESTRICT`-style FK violation on
user cleanup, and separately a SQLAlchemy default-substitution bug that silently marked every
self-registered account "verified" regardless of intent) — both caught by this phase's own new
integration tests and by re-running the broader auth/organisation/account-invite suite after each
change, and fixed before this report was written. Neither reached the final state described above;
both are described in §4/§9 as part of the record of what was actually built, not left as hidden
problems.

## 15. Security-Specific Tests

- **SEC-09**: token unpredictability (32-byte `secrets.token_urlsafe`), expiry, single-use,
  never-logged, replay-fails, invalid-token-fails, no account-info leakage, resend rate-limiting
  and anti-enumeration, registration-session-unaffected, login-blocked-until-verified, invited
  accounts pre-verified — all in `tests/integration/auth/test_email_verification.py`.
- **SEC-06**: `credentials: "include"` asserted on every fetch (`client.test.ts`); refresh-token
  absence from every JSON response body, presence in the `Set-Cookie` header, rotation, and reuse
  detection re-verified against the new cookie-only flow (`test_auth_security.py`,
  `test_credential_rate_limit.py`, `test_password_reset.py`, `test_employee_jwt_linkage.py`,
  `test_rls_runtime_role.py`).
- **DEP-01**: existing JWT/session tests (employee-JWT-linkage, RLS, auth-security suites) all
  re-verified passing unmodified in behavior against the new PyJWT-backed encode/decode.
- **SEC-10**: common-password rejection (case-insensitive), and an explicit regression guard
  proving this project's own seeded demo password (`DemoPass123!`) does not accidentally collide
  with the blocklist (`test_passwords.py`).
- **SEC-11**: both `Depends()`-based limiters proven to raise a clean `503
  RATE_LIMITER_UNAVAILABLE` (not a generic `500`, not a silent pass-through) when the Redis client
  itself errors (`test_rate_limit_redis_failure.py`).
- **KMS/encryption**: `test_crypto_keys.py`'s full suite re-verified against the new
  `MasterKeyService` fake (development-mode isolation, no-active-key fail-closed, unknown-version
  fail-closed, TTL caching bounding "unwrap" calls to one per version per window, rotation
  preserving old-version decryptability, master-key-unavailable fail-closed on both read and
  write paths) — every property the original DATA-01 test matrix required, now proven against the
  new wrapping mechanism instead of the old KMS one.

## 16. Residual Risks

- **`auth` bucket coarseness** (SEC-11, carried forward) — registration, password forgot/reset,
  and invite-accept still share one IP-only counter. Tracked, not fixed, by design (§8).
- **No cookie `domain=` scoping** (SEC-06) — the refresh cookie is host-only (no explicit
  `Domain` attribute). This is correct for today's architecture (no subdomain split exists yet)
  but will need a decision once the Docker/Nginx/HTTPS deployment phase picks a real domain
  topology (e.g. `api.` vs `app.` subdomains).
- **Password policy is still base-level** (SEC-10) — an offline blocklist is not equivalent to a
  live breach-corpus check; a determined attacker's non-common-but-still-weak password is not
  caught. This is the smallest safe improvement, not a claim of completeness (§7).
- **MFA is fully absent** (SEC-10) — formally deferred, not attempted (§7).
- **Local dev-database hygiene**: this phase's own iterative development (registering many test
  companies while debugging, some runs failing mid-way before a fix landed) left additional
  test-fixture rows in the shared, persistent `hrms_dev` database, in the same already-documented
  category Phase 1's own report flagged (stale companies/users from manual and repeated test runs,
  zero effect on CI — proven by this phase's own from-scratch fresh-container run, §14). Not
  cleaned up, consistent with Phase 1's own precedent of flagging rather than unilaterally deleting
  shared dev-DB state.
- **`kms_cmk_arn` → `pii_master_key` is a breaking config-name change** for any environment that
  had already set the old variable. No real environment exists yet (this application has never
  been deployed outside development/CI), so this has zero actual blast radius today, but it must
  be reflected in whatever deployment runbook is written for the still-not-started Docker/Nginx
  phase.

## 17. Deferred Findings

```text
MFA — deferred (SEC-10, §7): functionally absent; needs a real design pass, not a targeted fix.
"auth" bucket coarseness — deferred (SEC-11, §8): a bucket-topology redesign, not a failure-mode fix.
Cookie domain scoping — deferred (SEC-06, §16): depends on a not-yet-decided production domain topology.
Live breach-corpus password check — deferred (SEC-10, §7): would introduce an external network
    dependency this architecture avoids; the offline blocklist is the interim control.
Docker, Nginx, HTTPS termination, backups, Sentry/observability, audit-log gaps, payroll
    statutory-rate compliance sign-off — unchanged from Phase 2's own "not addressed" list; still
    entirely out of this phase's scope, per its own instructions (§11 of the brief).
```

## 18. Production Readiness

```text
NOT READY FOR PUBLIC RELEASE
```

This phase closed five of Phase 2's six remaining findings outright (SEC-09, SEC-06, DEP-01,
SEC-11, KMS) and made a real, measured improvement to the sixth (SEC-10's password policy, with
MFA correctly left as a deferred, separately-scoped decision). Closing these is a security-hardening
milestone, exactly as Phase 2's own report put it for its findings — not a production-readiness
signal by itself. Docker, Nginx, HTTPS termination, backups, observability, and the payroll
statutory-rate compliance sign-off remain entirely untouched and unresolved.

**Git state**: branch `main`, HEAD unchanged at `fb94e25` (this phase added no commits). Working
tree contains this phase's changes plus every already-reviewed, still-uncommitted change from
Phase 1 and Phase 2 (ruff/format remediation; SEC-05/07/08/OPS-06). `git status --short` shows no
file outside those three phases' own scopes; `mavericks-kit.zip`, `shirt.png`, `shorts.png`, and
`work done/` remain untouched, as in every prior phase. Nothing was committed. Nothing was pushed.

Suggested commit grouping when the user is ready: (1) Phase 1's CI remediation, (2) Phase 2's
SEC-08/SEC-07/SEC-05+OPS-06, (3) this phase's DEP-01, (4) this phase's SEC-11, (5) this phase's
KMS→application-master-key migration, (6) this phase's SEC-06 cookie migration
(backend+frontend together — they are not independently deployable), (7) this phase's SEC-09
email verification (backend+frontend together, same reason), (8) this phase's SEC-10 password
blocklist, (9) this doc.
