# Release Hardening — Phase 5A: Non-AWS Transactional Email

Date: 2026-09-25

## Executive Summary

```text
FINAL STATUS: COMPLETE — REAL SMTP DELIVERY ENVIRONMENT-BLOCKED
```

Phase 4 (`docs/audits/RELEASE_HARDENING_PHASE_4_PILOT_READINESS_GATE.md`, §8, §20 item 1)
identified one genuine application-level pilot blocker: the only real email transport in the
codebase was `SesEmailSender`, a literal AWS SES client, directly contradicting this deployment's
stated no-AWS-managed-services architecture. The default `LoggingEmailSender` never delivers
anything.

This phase replaced `SesEmailSender` with `SmtpEmailSender` — a provider-agnostic, authenticated
SMTP transport (via `aiosmtplib`) behind the same `EmailSender` protocol every caller already
depended on. No AWS SDK, credential, or service was introduced anywhere in this change; the only
remaining `aioboto3` consumer in the codebase is the pre-existing, unrelated self-hosted MinIO S3
client (`core/storage.py`), confirmed still genuinely needed and left untouched.

Production/staging now refuse to boot with `EMAIL_PROVIDER=logging` — a pilot deployment can no
longer silently believe email is being delivered when it is only being logged. A half-configured
SMTP transport (missing host/from-address, mismatched username/password, or no TLS mode enabled)
also fails to boot, in every environment, the moment `EMAIL_PROVIDER=smtp` is selected.

No real SMTP credentials were available in this environment, so a real end-to-end delivery test
could not be performed — marked `ENVIRONMENT-BLOCKED`, not faked, per this phase's own instruction.
Everything else was verified: the full regression suite (backend 1,741/0/0 — the 1,720 baseline
plus 21 new tests; frontend 399/0), Ruff, Ruff format, mypy, import-linter, and a real frozen
Docker image build confirming the new dependency actually installs and imports correctly.

## Previous State

- `apps/api/src/hrms/modules/onboarding/email_sender.py` defined `EmailSender` (a `Protocol`),
  `LoggingEmailSender` (the default — logs instead of sending), and `SesEmailSender` (the only
  real-delivery implementation, using `aioboto3`'s `ses` client against real AWS SES credentials).
- `Settings.email_provider: Literal["logging", "ses"] = "logging"` — no boot-time requirement that
  production actually select `"ses"`; a production deployment could run indefinitely on the
  logging-only sender without any startup failure.
- Five call sites used the shared `get_email_sender(settings).send(...)` abstraction:
  `identity/service.py` (password reset, email verification), `account_invite/service.py`
  (invite), `onboarding/service.py` (three call sites — send-invite, changes-requested-adjacent,
  activation-adjacent email hooks), `attendance/tasks.py`/`attendance/reminders.py` (incomplete-day
  reminders — unrelated to auth, shares the same abstraction).
- No test file exercised `get_email_sender`'s provider-selection logic or `SesEmailSender` at all
  — every existing integration test monkeypatches `LoggingEmailSender.send` directly (the default,
  test-time provider), so nothing in the existing suite depended on which real sender existed.
- No `SMTP_*`/`EMAIL_PROVIDER` variable appeared in any `.env.example` file anywhere in the repo.

## Email Architecture

Unchanged by this phase, confirmed by re-reading every caller before making any change:

- The `EmailSender` `Protocol` (`async def send(self, *, to, subject, html_body, text_body) ->
  None`) is the only surface any caller depends on.
- Message content (subject, HTML body, plain-text body, the token/URL embedded in it) is built
  entirely by the caller (`identity/service.py`, `account_invite/service.py`,
  `onboarding/service.py`, using `email_templates.py`'s template functions) — the sender receives
  an already-composed message and never generates or inspects a token itself.
- `get_email_sender(settings)` is the single selection point every caller already used and
  continues to use unmodified.

This phase touched **only** `email_sender.py`'s implementation classes and `Settings`' own
provider/SMTP configuration fields — zero lines changed in `identity/service.py`,
`account_invite/service.py`, `onboarding/service.py`, `email_templates.py`, or any router.

## Provider Selection

`Settings.email_provider: Literal["logging", "smtp"] = "logging"` — `"ses"` was removed outright
(no deprecated/dual-support period: no real production ciphertext or live deployment of this
setting existed anywhere, per the same reasoning Phase 3A used for the KMS→master-key migration).
An invalid value (e.g. the old `"ses"`) is rejected by pydantic's `Literal` type at `Settings`
construction — verified by `test_invalid_provider_rejected_at_settings_construction`.

`get_email_sender`:
```python
def get_email_sender(settings: Settings) -> EmailSender:
    if settings.email_provider == "smtp":
        return SmtpEmailSender(settings)
    return LoggingEmailSender()
```

## SMTP Implementation

`SmtpEmailSender` (`apps/api/src/hrms/modules/onboarding/email_sender.py`):

- Builds a standard `email.message.EmailMessage` (stdlib) with a plain-text part and an HTML
  alternative part (`message.add_alternative(html_body, subtype="html")`) — no change to what
  content is sent, only how it is packaged for SMTP.
- Sends via `aiosmtplib.send(...)`, a pure-Python, no-vendor-tie async SMTP client — new dependency
  (`aiosmtplib>=3.0.0`, resolved to `5.1.3`), added to `apps/api/pyproject.toml` and locked via
  `uv lock`.
- Every connection parameter (`hostname`, `port`, `username`, `password`, `start_tls`, `use_tls`)
  comes from `Settings`; nothing is hardcoded, and no specific commercial provider is named
  anywhere in the code — any standard authenticated SMTP endpoint works (a transactional-email
  vendor's SMTP relay, a self-hosted MTA, etc.).
- `username`/`password` are passed as `None` (not empty strings) when both are unset, correctly
  driving `aiosmtplib`'s own unauthenticated-submission path for an internal relay that doesn't
  require auth — verified by
  `test_smtp_sender_unauthenticated_relay_passes_none_credentials`.
- On any `aiosmtplib.SMTPException`, raises a new `EmailDeliveryError` (message contains no
  settings values) chained from the original exception (`from exc`, preserved for local
  traceback/debugging only, never serialized into a log or response) — every existing call site
  already wraps `get_email_sender(...).send(...)` in a bare `except Exception: pass`
  ("delivery failure must not fail the request/caller", `identity/service.py`,
  `account_invite/service.py`), so this new exception type is caught by that pre-existing,
  unmodified handling exactly like a `SesEmailSender` failure was before.

`core/storage.py`'s own comment (which referenced `email_sender.SesEmailSender` as a second
`aioboto3` consumer) was updated to state `aioboto3` now has exactly one consumer — the MinIO S3
client — confirmed by grep across the whole source tree.

## Configuration

New `Settings` fields (`apps/api/src/hrms/core/config/settings.py`):

```text
EMAIL_PROVIDER          logging | smtp        (default: logging)
SMTP_HOST                str                  (default: "")
SMTP_PORT                int                  (default: 587)
SMTP_USERNAME             str                  (default: "")
SMTP_PASSWORD             str                  (default: "")
SMTP_FROM_EMAIL           str                  (default: "")
SMTP_FROM_NAME            str                  (default: "Staff Spectrum HRMS")
SMTP_USE_TLS              bool                 (default: true — STARTTLS)
SMTP_USE_SSL              bool                 (default: false — implicit TLS)
```

Two `model_validator`s in `Settings`:

1. **`_guard_smtp_config`** — runs in every environment, whenever `email_provider == "smtp"`:
   requires `smtp_host` and `smtp_from_email` non-empty, `smtp_port` a valid TCP port,
   `smtp_username`/`smtp_password` either both set or both empty (a lone one is always a mistake),
   and exactly one of `smtp_use_tls`/`smtp_use_ssl` true (never both, never neither). Does nothing
   at all when `email_provider == "logging"` — no SMTP field is required or read.
2. **`_guard_non_development_config`** (existing, extended) — outside `development`, now also
   requires `email_provider == "smtp"` explicitly. A staging/production process with
   `EMAIL_PROVIDER=logging` (or unset) fails to boot with a clear `ValueError`, the same
   fail-closed pattern already used for JWT secrets, CORS origins, and the MinIO/S3 settings.

All four `apps/api/env/.env.{dev,staging,qa,production}.example` files were updated with a
required `EMAIL_PROVIDER=smtp` block and `__SET_IN_REAL_FILE__` placeholders for the SMTP
credentials (matching this repo's existing placeholder convention for every other real secret).
The local-developer-machine `apps/api/.env.example` keeps `EMAIL_PROVIDER=logging` as the active
default (unchanged developer experience) with the SMTP block present but commented out, for anyone
who wants to test real delivery locally.

## Security

- `SMTP_PASSWORD` is read only from `Settings` (env-injected, gitignored files, never committed —
  same posture as `JWT_ACCESS_SECRET`/`PII_MASTER_KEY`) and passed directly to `aiosmtplib.send`;
  it is never interpolated into a log line, an f-string, or an exception message anywhere in
  `email_sender.py` — verified directly, not just by inspection:
  `test_smtp_password_never_appears_in_the_failure_log` forces a real `aiosmtplib.SMTPException`
  and asserts the marker password string appears in neither the raised `EmailDeliveryError`'s
  message nor any structured log line captured via `structlog.testing.capture_logs()`.
- The SMTP-failure log line (`onboarding_email_smtp_send_failed`) logs only `to`, `subject`, and
  `error_type` (the exception's class name) — deliberately `logger.error`, not `logger.exception`,
  specifically so the full exception `str()`/traceback (not a security-reviewed contract of
  `aiosmtplib`'s own error formatting) never reaches a log record; a `# noqa: TRY400` with an
  inline justification documents this as a deliberate choice, not an oversight (Ruff's own
  `TRY400` rule recommends `logger.exception` by default).
- `test_smtp_send_failure_does_not_log_the_email_body` independently confirms the **message body**
  (which, for a real verification/reset/invite email, contains the token URL) is never logged on
  failure either — only the non-sensitive `to`/`subject`/`error_type` metadata.
- Health endpoints were re-checked: `/health`, `/health/live`, `/health/ready` never touch email
  configuration and continue to return no credential/connection-string values (unchanged from
  Phase 3B's own dedicated test for this).
- API responses: `SmtpEmailSender.send` never returns anything to its caller beyond `None` (a
  success) or the caller's own pre-existing swallow-and-continue handling (a failure) — no
  exception detail, credential, or token from this module reaches any HTTP response.

## Email Verification

Unchanged code path (`identity/service.py`'s `send_verification_email`/`verify_email`/
`resend_verification_email`): still calls `get_email_sender(self._settings).send(...)` with the
same `build_email_verification_email(...)`-produced subject/HTML/text. Only the transport selected
by `get_email_sender` changed. All 10 existing tests in
`tests/integration/auth/test_email_verification.py` re-run unmodified and pass (token
unpredictability, expiry, single-use, replay-fails, invalid-token-fails, no account-info leakage,
resend rate-limiting/anti-enumeration, registration-session-unaffected, login-blocked-until-
verified, invited-accounts-pre-verified).

## Invitations

Unchanged code paths in `account_invite/service.py` (existing-account and new-account invite
email) and `onboarding/service.py` (send-invite). All existing invite tests
(`test_account_invite.py`, `test_onboarding_invite.py`) re-run unmodified and pass.

## Password Reset

Unchanged code path (`identity/service.py`'s `forgot_password`/`reset_password`). All existing
tests in `tests/integration/auth/test_password_reset.py` re-run unmodified and pass (session
invalidation across access and refresh tokens, across multiple sessions, single-use reset token).

## Tests

**New** — `apps/api/tests/unit/modules/onboarding/test_email_sender.py` (21 tests, SMTP transport
fully mocked via `unittest.mock.AsyncMock` patched over `aiosmtplib.send`; no real SMTP server
contacted):

| Area | Tests |
| --- | --- |
| Provider selection | logging selected by default; smtp selected when configured; invalid provider (`Literal` violation) rejected |
| SMTP config validation | missing host/from-email rejected; invalid port rejected; lone username/password rejected (both cases); unauthenticated (both-empty) relay accepted as valid; plaintext (`tls=false, ssl=false`) rejected; both-TLS-modes-at-once rejected; valid config accepted; logging provider requires no SMTP fields; production rejects `logging`; production accepts `smtp` |
| Email sending | correct `To`/`From`/`Subject`/body envelope; STARTTLS parameters (`start_tls=True, use_tls=False`); implicit-TLS parameters (port 465, `start_tls=False, use_tls=True`); unauthenticated relay passes `None`/`None` credentials, not empty strings; `LoggingEmailSender` never calls `aiosmtplib.send` at all |
| Security | SMTP password absent from both the raised exception and every captured log line on failure; email body (token URL) absent from the failure log line; failure log carries only `to`/`subject`/`error_type` |

**Updated** (pre-existing test files that construct a non-development `Settings()` and needed a
valid SMTP shape added to their existing kwargs, since `_guard_non_development_config` now also
requires `email_provider="smtp"` — no test logic, assertion, or existing test case was changed,
only the fixture data each already used to build a valid non-development `Settings`):
`tests/unit/core/test_settings.py` (`_non_dev_settings` helper), `tests/unit/core/
test_crypto_keys.py` (`_prod_settings` helper), `tests/unit/core/test_cors_middleware.py`
(`_TEST_S3_KWARGS`), `tests/security/test_api_docs_exposure.py` (`_NON_DEV_KWARGS`).

**Existing flows, re-run unmodified**: every email-verification, invitation, and password-reset
test (§ above) — zero assertions weakened, zero tests deleted, zero tests skipped.

## Real SMTP Delivery Test

```text
REAL SMTP DELIVERY: ENVIRONMENT-BLOCKED
```

No real SMTP credentials (host, username, password, or a controlled test mailbox) were available
in this environment — confirmed by checking the environment for any `SMTP_*`/vendor-named
credential variable before starting this phase; none were found. Per this phase's own instruction,
this was not faked.

**Exact production configuration steps to actually perform this test** (an operator action against
real infrastructure this environment does not have):

1. Choose a non-AWS SMTP provider (any authenticated SMTP endpoint works — a transactional-email
   vendor, or a self-hosted MTA already under the operator's control).
2. Obtain `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and a verified/authorized
   `SMTP_FROM_EMAIL` from that provider.
3. Set `EMAIL_PROVIDER=smtp` and the five `SMTP_*` values in `apps/api/env/.env.production` (or
   `.staging`/`.qa`/`.dev` for a lower tier), choosing exactly one of `SMTP_USE_TLS=true` (port
   587, STARTTLS) or `SMTP_USE_SSL=true` (port 465, implicit TLS).
4. Restart the `api` (and `worker`, since password-reset/verification email is also sent from
   request-handling code, not a background task) containers:
   `docker compose -f docker-compose.prod.yml restart api worker`.
5. Trigger a real flow against a controlled test mailbox: `POST /v1/auth/forgot-password` (or
   register a new company, which sends a verification email) with the test mailbox's address.
6. Confirm: the message arrives, `From` matches `SMTP_FROM_NAME <SMTP_FROM_EMAIL>`, the
   verification/reset link points at the correct `WEB_APP_BASE_URL`-based frontend route, and
   clicking it completes the flow (`GET /v1/auth/email/verify`/the reset-password page).

This is the same class of gap Phase 4 already correctly marked `ENVIRONMENT-BLOCKED` for real
Let's Encrypt issuance — a real public/production credential this development environment
genuinely cannot possess, not a code gap.

## Docker / Production Configuration

`docker-compose.prod.yml` required **no change** — the `api`/`worker`/`beat`/`migrate` services
already load the entire `apps/api/env/.env.production` file via `env_file:`, so the new `SMTP_*`
variables reach every container that needs them (identity/account-invite/onboarding services all
run inside `api`; the attendance-reminder email path runs inside `worker`/`beat`) automatically,
the same way `PII_MASTER_KEY`/`JWT_ACCESS_SECRET` already do. No credential was added to any
Dockerfile, Compose file, or committed file — confirmed by `git diff --stat` (§Files Changed):
`docker-compose.prod.yml` itself does not appear in this phase's changes at all.

`docs/deployment/PRODUCTION_DEPLOYMENT.md` was updated in two places: §4 (Secret Generation) now
explains `SMTP_USERNAME`/`SMTP_PASSWORD` come from the chosen provider, not `openssl rand`; §17
(Common Failure Cases) gained two new entries for the two boot-failure messages this phase's own
validators can raise, so an operator hitting either recognizes it immediately rather than
re-debugging it.

A real, frozen production Docker build was performed this session to prove the new dependency
actually installs and imports in the exact image the runbook builds — not merely resolved by
`uv lock`:

```text
docker build -t hrms-api:phase5a-check apps/api  ->  Successfully built
docker run --rm hrms-api:phase5a-check python -c "import aiosmtplib; print(...)"
  -> aiosmtplib 5.1.3 OK
docker run --rm hrms-api:phase5a-check python -c "from hrms.modules.onboarding.email_sender import ..."
  -> email_sender module imports OK
```
(Image removed after the check — not left behind.)

## Files Changed

**New:**
- `apps/api/tests/unit/modules/onboarding/test_email_sender.py`
- `docs/audits/RELEASE_HARDENING_PHASE_5A_EMAIL.md` (this report)

**Modified:**
- `apps/api/pyproject.toml` — added `aiosmtplib>=3.0.0`
- `apps/api/uv.lock` — regenerated (`uv lock`)
- `apps/api/src/hrms/modules/onboarding/email_sender.py` — `SesEmailSender` replaced by
  `SmtpEmailSender`; new `EmailDeliveryError`; `get_email_sender` now selects `"smtp"`
- `apps/api/src/hrms/core/config/settings.py` — `email_provider` literal changed
  (`"ses"`→`"smtp"`); new `smtp_*` fields; new `_guard_smtp_config` validator; `_guard_non_
  development_config` extended to require `email_provider="smtp"` outside development
- `apps/api/src/hrms/core/storage.py` — comment-only update (stale `SesEmailSender` reference)
- `apps/api/.env.example`, `apps/api/env/.env.dev.example`,
  `apps/api/env/.env.staging.example`, `apps/api/env/.env.qa.example`,
  `apps/api/env/.env.production.example` — added `EMAIL_PROVIDER`/`SMTP_*` documentation/values
- `apps/api/tests/unit/core/test_settings.py`, `tests/unit/core/test_crypto_keys.py`,
  `tests/unit/core/test_cors_middleware.py`, `tests/security/test_api_docs_exposure.py` — existing
  non-development `Settings()` test fixtures extended with a valid SMTP shape (no test logic
  changed)
- `docs/deployment/PRODUCTION_DEPLOYMENT.md` — §4 and §17 updated for SMTP

**Explicitly not touched by this phase** (pre-existing, already-uncommitted change from an earlier
phase's own Ruff formatting pass, confirmed by its content being a pure mechanical line-collapse
unrelated to email): `apps/api/tests/unit/core/test_storage.py`.

**Files this phase deliberately did NOT change**: `identity/service.py`, `account_invite/
service.py`, `onboarding/service.py`, `email_templates.py`, any router, any auth/JWT/refresh-token/
encryption/RLS/MinIO/attendance/leave/payroll/RBAC code, `docker-compose.prod.yml`, any Nginx
config, any HTTPS/certbot config.

## Migrations

```text
No migration was added or required by this phase.
```

Nothing about the database schema changed — `email_provider`/`smtp_*` are `Settings` fields only,
never persisted. Alembic head unchanged: `20261004112000`.

## Test Results

| Check | Phase 4 baseline | This phase | Status |
| --- | ---: | ---: | --- |
| Backend unit tests | 687 passed / 0 / 0 | **708 passed / 0 / 0** (687 + 21 new) | PASS, no regression |
| Backend integration + security | 1,033 passed / 0 / 0 | **1,033 passed / 0 / 0** | PASS, exact match |
| Backend total | 1,720 / 0 / 0 | **1,741 / 0 / 0** (1,720 + 21 new) | PASS, no regression |
| Ruff check | pass | **pass** | PASS |
| Ruff format | pass | **pass** (1 new file formatted on write, then verified clean) | PASS |
| mypy | pass (167 files) | **pass (167 files)** | PASS |
| import-linter | 1 kept, 0 broken | **1 kept, 0 broken** (140 files, 343 deps analyzed) | PASS |
| Frontend TypeScript | pass | **pass** (untouched by this phase) | PASS |
| Frontend Vitest | 399 / 0 | **399 / 0** | PASS, exact match |
| Frontend production build | pass | **pass** | PASS |
| Docker `hrms-api` image build | builds | **rebuilt from scratch, builds; `aiosmtplib` confirmed installed and importable inside the frozen image** | PASS |

Both freshly-run test suites (unit and integration+security) were executed against a genuinely
fresh, isolated `postgres:16-alpine` + `redis:7-alpine` pair, migrated from scratch via
`MIGRATIONS_DATABASE_URL` (not the shared persistent `hrms_dev` database) — the same CI-equivalent
methodology every prior phase used, torn down afterward.

## Remaining Risks

- **Real SMTP delivery has not been exercised against a live provider or mailbox** — the transport
  is mocked in all automated tests and proven to construct correct envelopes/TLS parameters, but
  an actual message reaching an actual inbox has not been observed (§Real SMTP Delivery Test).
- **The `auth` rate-limit bucket's existing coarseness** (registration/forgot-password/reset/
  invite-accept sharing one IP counter, tracked since SEC-11/Phase 3A) is unchanged and equally
  applies to whatever real email volume a real SMTP provider now enables — not a new risk, but
  worth remembering now that email delivery is closer to production-real.
- **No per-provider deliverability guidance** (SPF/DKIM/DMARC records for `SMTP_FROM_EMAIL`'s
  domain) is documented — a real provider will typically require these for inbox placement, and
  this is a DNS/domain-ownership action the operator must perform for their chosen domain,
  independent of this application's code.
- **Existing call sites still swallow every send failure silently** (`except Exception: pass`) —
  unchanged, pre-existing behavior this phase deliberately did not redesign; a real SMTP outage
  today produces no error to the caller and no alert, only the new `onboarding_email_smtp_send_
  failed` log line (§Security). This was already true under `SesEmailSender` and is out of this
  phase's own narrow scope.

## Environment-Blocked Items

```text
REAL SMTP DELIVERY TEST — no real, non-AWS SMTP credentials or controlled test mailbox were
available in this development environment. Exact manual production steps are documented above
(§Real SMTP Delivery Test).
```

## Pilot Impact

Phase 4's pilot blocker #1 ("configure a real, working delivery path... before the first real
user registers or is invited") is now **code-complete and non-AWS**: the moment a real operator
puts real SMTP credentials into `apps/api/env/.env.production` and restarts, verification/invite/
password-reset emails will be sent for real — no further code change is needed. The remaining gap
is purely the operator action of obtaining those credentials and confirming delivery
(§Real SMTP Delivery Test), which is now a same-shape action as Phase 4's own remaining Let's
Encrypt and off-VPS-backup conditions: a real-infrastructure step this environment cannot perform
on the operator's behalf, not a missing capability.

## Final Status

```text
COMPLETE — REAL SMTP DELIVERY ENVIRONMENT-BLOCKED
```

## Git / Change Control

- Branch: `main`. `HEAD`: `fb94e25` (unchanged — this phase added no commits).
- 25 commits ahead of `origin/main` (unchanged from Phase 0's own safety-snapshot baseline).
- `git status --short`: 134 modified/untracked paths (130 at the end of Phase 4). The only two
  new untracked paths this phase added are `apps/api/tests/unit/modules/onboarding/
  test_email_sender.py` and this report; the remainder of the delta is this phase's edits landing
  on already-tracked files (`pyproject.toml`, `uv.lock`, `settings.py`, `email_sender.py`,
  `storage.py`, the five `.env*.example` files, four existing test files,
  `PRODUCTION_DEPLOYMENT.md`) — each newly `M`odified, not newly created.
- Exact files changed/added: listed in full in §Files Changed above.
- Migrations: none (§Migrations).
- Tests: backend 1,741 passed / 0 failed / 0 errors; frontend 399 passed / 0 failed (§Test
  Results).
- Real SMTP delivery result: `ENVIRONMENT-BLOCKED` — not faked (§Real SMTP Delivery Test).
- **No credentials of any kind were committed.** The two gitignored `.env`/`apps/api/env/.env.*`
  files this phase might have used for local verification were not created as part of this
  phase's own testing (unit tests mock the SMTP transport entirely; no live SMTP server was
  contacted) — no real or placeholder SMTP secret touched any file this phase wrote to disk.
- **Nothing was committed. Nothing was pushed.** No `git reset`, `git rebase`, or deletion of any
  unrelated file was performed. `mavericks-kit.zip`, `shirt.png`, `shorts.png`, `work done/`
  remain untouched, consistent with every prior phase.
