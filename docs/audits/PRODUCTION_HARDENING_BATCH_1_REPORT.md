# Production Hardening Batch 1

## Scope

```text
OPS-01  Production CORS allows no origins
SEC-01  JWT signing secrets have working defaults and no production guard
SEC-02  Login and token refresh are not rate-limited
OPS-02  Client IPs are not correctly resolved behind a trusted proxy
```

Source audit: `docs/audits/PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.md`.

## Baseline

```text
Commit:       c3b8cec9c1d24dbd4892f92a649b9c4c98e3533f (fix(rbac): grant approval authority to
              HR_ADMIN, REPORTING_MANAGER, and BRANCH_MANAGER)
Branch:       main
Working tree: clean of tracked changes; several pre-existing untracked docs/media files present
              (docs/audits/, docs/business-rules/attendance/…, docs/business-rules/policies/,
              docs/modules/employee/41_…, jersouy/, mavericks-kit*). None touched by this task.
```

## Findings Before Implementation

- **OPS-01** — `app.py:38`: `allow_origins=["*"] if settings.is_development else []`. Outside
  development, empty — every browser request blocked. In development, `["*"]` combined with
  `allow_credentials=True` is an invalid, browser-rejected combination.
- **SEC-01** — `settings.py:27,29` (pre-change line numbers): `jwt_access_secret`/
  `jwt_refresh_secret` default to `"change-me-local-dev-only-min-16"` /
  `"change-me-local-dev-too-min-16"`, both 16+ chars (clears the existing `Field(min_length=16)`
  check), and nothing rejected them outside development.
- **SEC-02** — `identity/router.py`: `login` and `refresh_token` took no rate-limit dependency at
  all. `forgot_password`/`reset_password` already used `_password_rate_limit = rate_limit("auth",
  limit=10, window_seconds=60)`, as did registration and invite-accept (all sharing one "auth"
  bucket — a pre-existing coarseness tracked separately as SEC-11, not touched here).
- **OPS-02** — `shared/rate_limit.py:49`: `request.client.host`, with no `ProxyHeadersMiddleware`
  or trusted-proxy configuration anywhere in `app.py`. Behind any reverse proxy/load balancer this
  resolves to the proxy's own address for every caller, collapsing every IP-keyed bucket (and
  every logged `ip_address` on sessions/audit rows — the same read site is used in the audit
  logging call in every module router) into one shared value.

## Changes Made

### OPS-01 CORS

- `Settings.cors_allowed_origins: tuple[str, ...] = ()` (new) — comma-separated string or list
  accepted (`CORS_ALLOWED_ORIGINS=https://a.example.com,https://b.example.com`), parsed by a
  `field_validator`.
- `Settings.effective_cors_origins` (new property) — returns `cors_allowed_origins` verbatim when
  set; in `development` only, falls back to `[web_app_base_url, "http://localhost:3000"]`
  (deduplicated) — never `["*"]`, so `allow_credentials=True` stays a valid combination in every
  environment, fixing the development-mode defect the audit also called out.
- `app.py` now passes `allow_origins=settings.effective_cors_origins` to `CORSMiddleware` instead
  of the `["*"] if is_development else []` conditional.
- Boot-time guard (see SEC-01 below) refuses to start `staging`/`production` with an empty
  `cors_allowed_origins`.

### SEC-01 JWT Secrets

- New `Settings.model_validator(mode="after")` — `_guard_non_development_config` — runs on every
  `Settings()` construction (including `get_settings()`), and for `environment != "development"`:
  - rejects a missing/empty secret;
  - rejects a secret **equal to the known repository default** (explicit string comparison, not
    inferred from length — a deliberately-strong-looking secret that happened to still be the
    default would still be caught);
  - rejects a secret shorter than 32 characters **or** with fewer than 8 distinct characters (an
    entropy floor well above the existing 16-char `Field(min_length=...)` sanity check, which the
    known default already clears — so that check alone could never have been the thing standing
    between a forgotten secret and a booted production API).
  - Applies independently to `jwt_access_secret` and `jwt_refresh_secret`.
- Error messages name the field and environment only — never the secret value (verified by a
  dedicated test, `test_rejection_error_never_echoes_the_rejected_secret_value`).
- `development` is exempted entirely (`is_development` short-circuits the validator) — local
  workflow with the repository defaults is unchanged.

### SEC-02 Login Rate Limiting

- New `rate_limit_by_ip_and_email(bucket, *, limit, window_seconds)` in `shared/rate_limit.py` —
  reuses the exact same Redis `INCR`/`EXPIRE` sliding-window primitive as the existing
  `rate_limit()`, applied twice per request: once keyed on client IP, once on the request body's
  `email` field (read via `request.json()`, which Starlette caches on the `Request` object — no
  double consumption of the body against the endpoint's own `LoginRequest` parameter). Blocks if
  **either** counter exceeds `limit`. No second limiter, no new Redis client, no new dependency
  mechanism — this is the same `rate_limit` architecture, parameterised.
- `identity/router.py`: `_login_rate_limit = rate_limit_by_ip_and_email("login", limit=10,
  window_seconds=60)`, attached to `POST /auth/login`.
- **Design decision — separate bucket, not the shared "auth" bucket**: the audit's fix text reads
  "apply the existing `rate_limit("auth", …)` dependency ... keyed on email as well as IP." I
  interpreted this as "reuse the existing `rate_limit` mechanism" (which the code does) rather
  than "share the literal `"auth"` Redis key namespace" with registration/forgot-password/
  reset-password/invite-accept. Sharing that bucket would mean a burst of legitimate login
  attempts could exhaust the counter registration relies on and vice versa — deliberately not
  widening the coarseness that finding **SEC-11** already tracks separately for that bucket. This
  is a judgment call, called out explicitly rather than silently deviating from the audit's
  literal wording.
- Account lockout (`IdentityRepository.increment_failed_login`, unchanged) remains a fully
  separate control — see **Known Limitations** below for a pre-existing gap discovered while
  testing it, not introduced by this batch.
- The response for an unknown email and for a known email with the wrong password remain
  identical (`401 INVALID_CREDENTIALS`) — anti-enumeration posture unchanged, and covered by a new
  test.

### SEC-02 Refresh Rate Limiting

- `_refresh_rate_limit = rate_limit("token_refresh", limit=10, window_seconds=60)`, attached to
  `POST /auth/token/refresh`. IP-only — the refresh body carries a token, not an email, so there
  is no second dimension to key on; its own bucket name keeps a stolen-refresh-token replay burst
  from also exhausting that IP's login attempts (and vice versa).
- Refresh rotation and reuse/replay detection (`revoke_refresh_family` on reuse) are unchanged and
  covered by regression tests under the new limiter.

### OPS-02 Trusted Proxy IP

- `Settings.trusted_proxy_hosts: tuple[str, ...] = ()` (new) — comma-separated host/CIDR list,
  same parsing convention as `cors_allowed_origins`. Empty by default (nothing trusted).
- `app.py` wires `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware` (already a transitive
  dependency via `uvicorn[standard]` — no new package) as the **last** middleware added via
  `app.add_middleware`. Starlette builds its middleware stack in reverse add-order, so the
  last-added middleware is outermost and runs first — meaning it resolves `scope["client"]`
  before `CORSMiddleware`, `TenancyMiddleware`, the rate limiter, or any route handler's
  `request.client.host` read (audit logging in every module router included) ever sees the
  request.
- Deliberately **not** a hand-rolled `X-Forwarded-For` parser: `ProxyHeadersMiddleware` only
  trusts a forwarded value when the immediate socket peer is itself in the configured
  `trusted_hosts` (IP, CIDR, or `"*"`), and walks a multi-hop `X-Forwarded-For` chain in reverse,
  stopping at the first entry outside the trusted set — so neither "take the first" nor "take the
  last" comma-separated value is used, and a chain of two trusted proxies is still resolved
  correctly. This is the framework's own, separately-maintained implementation rather than new
  code written for this batch.

## Configuration Changes

New settings, all documented in every `env/.env.*.example` file and the local `.env.example`
(placeholders only — no real secrets committed):

```text
CORS_ALLOWED_ORIGINS    comma-separated origin list. Empty/unset in development (dev fallback
                        origin used); REQUIRED (boot fails otherwise) in staging/production.
TRUSTED_PROXY_HOSTS     comma-separated host/CIDR list of the immediate reverse proxy(ies)
                        allowed to set X-Forwarded-For/X-Forwarded-Proto. Empty/unset = nothing
                        trusted, forwarded headers always ignored (safe default).
```

Also added the previously-**missing** `ENVIRONMENT=` line to `env/.env.dev.example`,
`env/.env.qa.example`, `env/.env.staging.example`, and `env/.env.production.example` — these files
only ever set `NODE_ENV` (the web app's own variable), which does not gate
`hrms.core.config.settings.Settings.environment` at all. Without this, the new SEC-01/OPS-01 boot
guard would never actually engage in a real deployment of any of these tiers, silently defeating
the fix. `env/.env.qa.example`'s "production-shaped" tier is mapped to `ENVIRONMENT=staging`
(`Settings.environment` only models `development`/`staging`/`production`).

## Tests Added

50 new tests across 6 files (all passing):

```text
tests/unit/core/test_settings.py              18 tests — SEC-01 (dev/staging/prod × missing/
                                                default/weak/strong secret, no-leak-on-error) and
                                                OPS-01 (dev fallback, staging/prod required,
                                                comma-parsing, wildcard-never-appears) + trusted-
                                                proxy-hosts parsing
tests/unit/core/test_cors_middleware.py        4 tests — real CORSMiddleware preflight/simple-
                                                request behaviour per environment, untrusted
                                                origin rejected (400, no allow-origin header)
tests/unit/core/test_proxy_headers.py          7 tests — direct ProxyHeadersMiddleware behaviour:
                                                Cases A-D, multi-hop chain, CIDR support, empty-
                                                trusted-hosts-never-trusts
tests/unit/shared/test_rate_limit_dual_bucket.py
                                                7 tests — IP-bucket-catches-spray, email-bucket-
                                                catches-distributed-attack, independent per-email
                                                counters (Case E), window recovery (dual-bucket
                                                and plain), malformed-body fallback
tests/integration/test_proxy_aware_rate_limiting.py
                                                5 tests — Cases A-D end-to-end through a probe app
                                                wired identically to app.py (CORS → Tenancy →
                                                ProxyHeaders, in that add-order), plus the
                                                negative control showing the pre-fix bug
tests/integration/auth/test_credential_rate_limit.py
                                                10 tests — real /auth/login and /auth/token/
                                                refresh: normal login, IP-bucket trip, email-
                                                bucket trip, distributed-IP attack, non-cross-
                                                blocking, anti-enumeration, refresh rate limit,
                                                refresh rotation + replay detection under the
                                                limit, and the account-lockout finding below
```

Existing coverage exercised as regression: `tests/integration/auth/` (30 tests, unchanged),
`tests/integration/modules/organisation/test_registration_rate_limit.py` (unchanged bucket/key
format preserved deliberately — see below).

**Compatibility note**: the pre-existing `rate_limit()` function's Redis key format
(`ratelimit:{bucket}:{ip}`) was **not** changed, specifically so `tests/integration/auth/
conftest.py`'s `_REGISTRATION_RATE_LIMIT_KEY` and the organisation module's own rate-limit test
keep working unmodified. Only the new `rate_limit_by_ip_and_email` uses a different key shape
(`ratelimit:{bucket}:ip:{ip}` / `ratelimit:{bucket}:email:{email}`), under its own new bucket
names (`"login"`, `"token_refresh"`) that don't collide with the existing `"auth"` bucket.

Added an autouse fixture (`tests/conftest.py::_reset_credential_rate_limits`) that `SCAN`s and
deletes every `ratelimit:login:*`/`ratelimit:token_refresh:*` key before and after **every** test
in the suite — necessary because login is now exercised (via `admin_tokens`/`viewer_tokens`-style
fixtures) from dozens of unrelated test files sharing one ASGITransport client IP and a small set
of reused seed emails; without this, the new 10/min buckets would trip well before any test
intends to exercise the limit itself.

## Test Results

```text
Targeted (new) tests:            50 passed
Full backend suite:              1303 passed, 1 failed (pre-existing, unrelated — see below)
mypy (strict, packages=["hrms"]): Success: no issues found in 142 source files
ruff check (files touched by
this batch):                     All checks passed
```

**The one full-suite failure** —
`tests/integration/modules/organisation/test_registration_flow.py::
test_registration_success_full_row_graph` — asserts an exact RBAC permission-code set for a
freshly registered `COMPANY_ADMIN` and is missing `SETTINGS.ROLE.MANAGE`, `SETTINGS.USER.MANAGE`,
and `EMPLOYEE.INVITE` from its expected set. **Confirmed pre-existing**: reproduced identically
after `git stash`-ing every change in this batch, run against the unmodified baseline commit
`c3b8cec`. Unrelated to CORS/JWT/rate-limiting/proxy work (an RBAC/permission-seeding drift), not
touched or fixed here per the scope lock (`Do not modify RBAC permissions`).

`ruff check .` over the **whole repository** (not just this batch's files) separately reports 6
pre-existing `E501` line-length findings in `alembic/versions/*.py` migration files — confirmed
unrelated (untouched by this diff, pre-existing formatting in historical migrations).

## Regression Results

| Capability | Result |
|---|---|
| Login | ✅ normal login still 200s under the new limit |
| Refresh | ✅ rotation still works; ✅ replay/reuse still detected and revokes the family |
| Logout/revocation | ✅ untouched (no dependency added, not in this batch's diff) |
| Session validation | ✅ untouched (`tests/integration/auth/test_auth_security.py` — 4 tests, unchanged, all pass) |
| Account lockout | ⚠️ **Pre-existing bug found, not caused by this batch** — see Known Limitations |
| Tenant isolation / RLS / cross-tenant denial | ✅ untouched — `tests/security/`, tenancy-scoped integration suites all pass |
| Registration / IP throttling / tenant bootstrap | ✅ unchanged bucket, all pre-existing tests pass |
| Password reset / anti-enumeration | ✅ `tests/integration/auth/test_password_reset.py` unchanged, passes |
| Invitations / role assignment / anti-enumeration | ✅ `tests/integration/modules/account_invite/` unchanged, passes |

## Security Review

Searched the full API source (`src/hrms/`) for each pattern in scope:

- `allow_origins=["*"]` — **zero occurrences** (previously one, in `app.py`; now
  `settings.effective_cors_origins`, which the SEC-01/OPS-01 guard guarantees is never `["*"]` in
  any environment).
- `X-Forwarded-For` — only referenced in comments explaining the `ProxyHeadersMiddleware` wiring;
  no application code reads the header directly.
- `request.client.host` — present at every existing audit-logging call site (unchanged call
  sites, ~90 occurrences across `attendance`, `employee`, `leave`, `onboarding`, `organisation`,
  `account_invite` routers) plus `shared/rate_limit.py`. All of them now transparently benefit
  from the `ProxyHeadersMiddleware` fix (it mutates `scope["client"]` before any of these run) —
  this also happens to correct the audit's OPS-02 note that logged session/audit-row IPs were
  wrong behind a proxy, without touching any of those call sites individually.
- `jwt_access_secret` / `jwt_refresh_secret` — only in `settings.py` (definition + guard) and
  `core/auth/jwt.py` (signing/verification, unchanged). No hardcoded secret value outside the
  named development-default constants, which are now explicitly rejected outside `development`.
- No rate-limit bypass found: the dual-bucket dependency runs before the route body is ever acted
  on; a Redis-outage failure mode is unchanged (see below).
- No email-enumeration regression: login's 401 response is identical for an unknown email and a
  known email with a wrong password (tested).
- No authentication weakening: password verification, token issuance, and refresh-family
  revocation logic are byte-for-byte unchanged (`identity/service.py` is not in this diff).

## Scope Compliance

Confirmed **not** implemented, touched, or refactored in this batch: `DATA-01`, `API-01`,
`SEC-03`–`SEC-10` (except the SEC-02 items explicitly in scope), `SEC-11` (see below), `DEP-01`,
`OBS-01`, `OBS-02`, `OPS-03`, `OPS-04`, `OPS-05`, `OPS-06`, `QA-01`, `AUD-01`. No RBAC permission
changes. No attendance/timezone logic changes. No tenancy/RLS changes. No frontend changes.

**Files modified** (10):

```text
apps/api/.env.example
apps/api/env/.env.dev.example
apps/api/env/.env.production.example
apps/api/env/.env.qa.example
apps/api/env/.env.staging.example
apps/api/src/hrms/app.py
apps/api/src/hrms/core/config/settings.py
apps/api/src/hrms/modules/identity/router.py
apps/api/src/hrms/shared/rate_limit.py
apps/api/tests/conftest.py
```

**Files added** (6, all tests):

```text
apps/api/tests/integration/auth/test_credential_rate_limit.py
apps/api/tests/integration/test_proxy_aware_rate_limiting.py
apps/api/tests/unit/core/test_cors_middleware.py
apps/api/tests/unit/core/test_proxy_headers.py
apps/api/tests/unit/core/test_settings.py
apps/api/tests/unit/shared/test_rate_limit_dual_bucket.py
```

**Migration files**: none required (no schema/model changes).

No other tracked file was modified. The pre-existing untracked files present at session start
(`docs/audits/` contents other than this report, `docs/business-rules/attendance/…`,
`docs/business-rules/policies/`, `docs/modules/employee/41_…`, `jersouy/`, `mavericks-kit*`) were
left exactly as found. Nothing was committed — this is left for the user to review and commit.

## SEC-11 (rate-limiter failure policy) — remains separate

Verified, did not change: `_get_client()`/`client.incr(...)` in `shared/rate_limit.py` still
raises on a Redis outage (a `redis.exceptions.ConnectionError`-family exception), which is not an
`AppError` subclass, so it falls through to the generic `unhandled_exception_handler` and the
endpoint 500s — for the two newly-limited endpoints exactly as it already did for
registration/forgot-password/reset-password/invite-accept. This is unavoidable collateral of
adding a limiter that uses the existing architecture (a limiter that "fails closed" per-endpoint
would itself be a SEC-11-shaped design decision), and changing it was not necessary to safely
implement this batch. **SEC-11 remains open and separate.**

## Known Limitations

1. **Account lockout does not currently persist (pre-existing, discovered during this batch's
   regression testing, not caused by it).** `hrms.core.db.session.get_session` rolls back its
   entire transaction on any exception raised during request handling; `IdentityService.login`
   calls `IdentityRepository.increment_failed_login` (which only `flush()`s, never commits) and
   then raises `InvalidCredentialsError` on the same request. That raise triggers the rollback,
   silently discarding the `failed_login_count` increment. Confirmed by direct DB inspection: six
   consecutive wrong-password attempts against a seeded user leave `failed_login_count` at `0` and
   `locked_until` at `NULL` in the database, and every response is `401 INVALID_CREDENTIALS` —
   never the `423 ACCOUNT_LOCKED` the code path is written to produce. None of the three files
   involved (`core/db/session.py`, `modules/identity/service.py`,
   `core/db/repositories/identity.py`) are touched by this diff — confirmed via `git diff --stat`
   against the baseline commit. **Not fixed here**: it is not one of OPS-01/SEC-01/SEC-02/OPS-02,
   fixing it would mean changing session/transaction-commit semantics in `identity/service.py`
   (explicitly out of scope — "do not refactor unrelated authentication code"), and the new rate
   limiter is a fully independent control that still works correctly regardless (verified: the
   login rate limit trips at the configured threshold whether or not lockout is engaged). This
   should be raised as its own follow-up finding before production sign-off — the audit's
   Login & session row currently credits lockout as a working mitigant, and it is not one today.
2. Both new buckets ("login", "token_refresh") use the same 10/min policy as the existing "auth"
   bucket by convention, since neither the audit nor an existing spec defines a different value
   for these specific endpoints. If the client wants a tighter policy specifically for credential
   endpoints, that's a one-line change to the two `rate_limit(...)`/`rate_limit_by_ip_and_email(
   ...)` call sites in `identity/router.py`.
3. CORS/proxy end-to-end tests use small probe apps that mirror `app.py`'s exact middleware
   wiring rather than importing the full `create_app()` app — the full app needs a live Postgres/
   Redis connection at *import* time with one fixed `Settings()` instance, which cannot vary
   `trusted_proxy_hosts`/`cors_allowed_origins` per test within one process. The probe apps
   register the same `CORSMiddleware`/`TenancyMiddleware`/`ProxyHeadersMiddleware` in the same
   add-order and the same real `register_exception_handlers`/`rate_limit` — the only thing not
   reused is the database-backed route handlers, which the CORS/proxy/rate-limit mechanics under
   test don't depend on.

## Final Status

```text
BATCH 1 PASS
```

All four findings (OPS-01, SEC-01, SEC-02, OPS-02) are implemented, enforced at boot/request time
(not only documented), and covered by passing tests. The one full-suite test failure and the
account-lockout persistence gap are both confirmed pre-existing and out of this batch's scope; SEC-11
is confirmed unchanged and remains open. This closes only OPS-01/SEC-01/SEC-02/OPS-02 — the
platform is **not** being declared production-ready; the remaining P0 (`DATA-01`, `API-01`) and all
P1/P2 findings in `PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.md` remain open until separately
remediated and verified.
