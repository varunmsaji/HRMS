# Platform Production Readiness & Security Audit

| Field | Value |
|---|---|
| Audit date | 2026-09-17 |
| Commit | `c3b8cec` (branch `main`) |
| Scope | `apps/api` (45.7k LoC) · `apps/web` (44.9k LoC) · 68 migrations · 228 routes |
| Areas | Login · registration · user invites · employee onboarding · attendance · leave · RBAC/tenancy · database · operations |
| Method | Static source review. **No exploitation was attempted**, no running system was tested. |
| Verdict | 🔴 **NOT PRODUCTION-READY** — 5 P0 blockers, 9 P1, 10 P2 |
| Rendered version | [`PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.html`](./PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.html) |

**Relationship to prior audits.** This is a fresh source-level pass, not a re-read of the
2026-09-10 set ([`SECURITY_READINESS_AUDIT.md`](./SECURITY_READINESS_AUDIT.md),
[`PRODUCTION_READINESS_CHECKLIST.md`](./PRODUCTION_READINESS_CHECKLIST.md)). Those covered commit
`e33fcdb`; password reset, account invites, the `BRANCH_MANAGER` role and the DEC-TZ-01
remediation have all landed since. Findings carried forward from that set are re-verified against
current source and marked as such; everything else is new. Payroll-input business-rule
completeness remains tracked separately in
[`PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md`](./PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md).

---

## Executive position

**The domain is further along than the platform around it.**

The HR logic — tenant isolation, RBAC data scopes, attendance calculation, leave ledgers — is
built to a genuinely high standard, with a real Postgres RLS backstop under a non-privileged
runtime role and 1,220 tests behind it. That part is close to ready.

What is not finished is the layer that makes it deployable and defensible: the API cannot be
reached by a browser in production as configured, JWT signing secrets have working defaults with
no guard, the login endpoint is unthrottled, government ID and bank numbers are stored in
plaintext despite `_enc` column names, and no list endpoint in the entire API is paginated.

None of the five blockers is a deep architectural problem. All five are a focused week of work —
but all five must land before a paying tenant's data goes in.

| Severity | Count |
|---|---|
| P0 — blocker | 5 |
| P1 — high | 9 |
| P2 — medium | 10 |
| Tenant tables under `ENABLE` + `FORCE` RLS | 67 |

---

## 1. Readiness by area

Each area is judged on whether it could carry live customer data today — not on how much of it is
built. Several areas marked *blocked* are functionally complete and held back only by
platform-level gaps shared across the whole API.

| Area | State | What holds it back |
|---|---|---|
| Registration & tenant bootstrap | 🔴 Blocked | No email verification; one POST creates a live tenant plus an authenticated admin session. IP rate limit only. |
| Login & session | 🔴 Blocked | No request-layer throttle on `/auth/login` or `/auth/token/refresh`. Rotation, reuse detection and revocation are otherwise excellent. |
| Password reset | 🟠 Needs fix | Correct token handling and anti-enumeration, but a reset does not revoke live sessions or refresh families. |
| User invites & role assignment | 🟠 Needs fix | Accepting an invite for an email that already has an account issues that account a session with no password check. |
| Employee onboarding (public wizard) | 🟠 Needs fix | Unauthenticated upload buffers the whole file before the size check, stores a caller-chosen content type, and is unthrottled. |
| Attendance | 🟡 Ready with caveats | Punch instants now server-assigned; period locks enforced at 13 mutation sites. Limited by the API-wide pagination gap. |
| Leave | 🟡 Ready with caveats | Ledger, approval chain, self-approval block and scope checks sound. Same pagination gap; accrual cycles lack a natural-key unique constraint (DAT-001, carried forward). |
| Multi-tenancy & RBAC | 🟢 Ready | Strongest part of the system. One latent footgun: the RLS session variable is first set from an unverified request header. |
| Database & schema | 🟠 Needs fix | Well-modelled and constrained, but `_enc` PII columns hold plaintext and the base migration has no downgrade path. |
| Deploy & operations | 🔴 Blocked | Production CORS resolves to no origins, no security headers, no error tracking, no web container, root-user API image. |

---

## 2. Blockers (P0)

Each of these either prevents the product from functioning once deployed, or exposes customer data
in a way that is not defensible to a client or a regulator.

### OPS-01 🔴 Production CORS allows no origins at all

**Evidence:** `apps/api/src/hrms/app.py:38` — `allow_origins=["*"] if settings.is_development else []`

Outside development the allowed-origin list is empty and there is no environment variable to
populate it. The moment the API runs with `ENVIRONMENT=staging` or `production`, every browser
request from the Next.js app is blocked by the preflight. **The application is undeployable as
configured** — this fails on the first deploy, not later under load.

The development branch has its own defect: `allow_origins=["*"]` together with
`allow_credentials=True` is an invalid combination that browsers reject, so the wildcard provides
less than it appears to.

**Fix:** add a `cors_allowed_origins` setting, read it per environment, and fail boot if it is
empty outside development.

*(Carried forward from SEC-001, 2026-09-10 — re-verified unchanged at `c3b8cec`.)*

### SEC-01 🔴 JWT signing secrets have working defaults and no production guard

**Evidence:** `apps/api/src/hrms/core/config/settings.py:27-30`

Both signing secrets carry defaults that satisfy the 16-character minimum, so an environment that
forgets to inject them boots successfully and signs tokens with a value that is public in the
repository. Anyone with the source can then mint a valid access token for any
`user_id`/`company_id` pair — a **complete authentication bypass across every tenant**, with no log
trace, because such a token verifies normally.

Nothing in the settings model, the app factory or the lifespan hook asserts that production is not
running on defaults. `env/.env.production.example` correctly documents Secrets Manager injection,
but that is documentation, not enforcement.

**Fix:** a Pydantic model validator that raises when `environment != "development"` and either
secret matches the default or falls under a real entropy floor.

### SEC-02 🔴 No rate limit on login or token refresh

**Evidence:** `apps/api/src/hrms/modules/identity/router.py:34-60` — neither route takes the
`_password_rate_limit` dependency

Registration, forgot-password, reset-password and invite-acceptance all carry a 10-per-minute IP
bucket. Login and refresh — the two endpoints that actually validate credentials — carry none. The
only control is per-account lockout after five failures
(`core/db/repositories/identity.py:201-209`), which does not stop password spraying across many
accounts, and which an attacker can aim at any known email address as a denial-of-service
primitive against that user.

Refresh is also unthrottled, so a stolen refresh token can be exercised without friction.

**Fix:** apply the existing `rate_limit("auth", …)` dependency to both routes, keyed on email as
well as IP, and make the limiter fail closed if Redis is unreachable.

*(Carried forward from SEC-002 / SEC-A1, 2026-09-10 — re-verified unchanged.)*

### DATA-01 🔴 Aadhaar, PAN and bank account numbers are stored in plaintext

**Evidence:** `apps/api/src/hrms/modules/employee/models.py:61-63` (`pan_number_enc`,
`aadhaar_number_enc`), `:272` (`account_number_enc`)

The `_enc` suffix implies encryption at rest; the columns are plain `String`, and a search for any
encryption primitive across the API — Fernet, KMS, pgcrypto, application-level envelope encryption
— returns a single source comment acknowledging the gap. Government identifiers and salary-account
numbers for every employee of every tenant sit in cleartext in one table.

This is the finding most likely to end a client security review. Under India's DPDP Act these are
precisely the identifiers that attract the strictest handling expectations, and a database
snapshot, a replica, a backup file or a support export leaks all of them at once. It also blocks
payroll, where bank details become operationally necessary rather than optional.

**Fix:** envelope-encrypt these three columns with a KMS-managed data key, decrypt only in the
narrow service paths that need the value, and mask in every read schema. Backfill before the first
real tenant, not after.

### API-01 🔴 No list endpoint in the API is paginated

**Evidence:** `apps/api/src/hrms/shared/pagination.py:14` — `PaginationMeta` defined, **zero
usages**; `modules/employee/router.py:97` — `list_employees` takes no page parameters

Across 228 routes, not one list endpoint accepts a page, cursor or limit parameter; every one
serialises the tenant's full result set. `GET /employees` returns every employee, attendance-day
and punch listings return every row in range, and `GET /users` additionally runs one role query per
member (acknowledged as deliberate N+1 in `account_invite/service.py`).

At demo scale this is invisible. At a thousand-employee tenant with a year of attendance history it
is a slow-query and memory problem on every page load, and an authenticated amplification vector:
one cheap request forces an unbounded database read and JSON serialisation.

**Fix:** wire the already-defined `PaginationMeta` through `ListEnvelope`, add `page`/`per_page`
with a hard server-side ceiling, and bound the date ranges on attendance and leave queries.

---

## 3. High severity (P1)

Not launch-stopping on their own, but each materially widens the blast radius of an incident. Fix
before onboarding customers, not before the first internal deploy.

| ID | Finding | Evidence |
|---|---|---|
| SEC-03 | **Public document upload buffers the entire request before checking size.** The 10 MB ceiling is enforced only after the whole file is resident in process memory, on a route reachable by anyone holding an onboarding link and with no rate limit attached. | `onboarding/public_router.py:94` → `onboarding/service.py:566` |
| SEC-04 | **Uploaded content type is caller-controlled and replayed on download.** Only the document category is allow-listed; the MIME type comes from the client, is stored on the object, and is served to an HR reviewer through a presigned GET with no `Content-Disposition: attachment` — an uploaded `text/html` executes on the bucket origin. The raw filename is concatenated into the S3 key unsanitised. No malware scanning. | `onboarding/service.py:564-572` |
| SEC-05 | **No security headers on either application.** No CSP, HSTS, `X-Content-Type-Options`, frame-options or referrer policy anywhere. The missing CSP matters most because it is the layer that would contain SEC-06. | `app.py:36-43`; `apps/web/next.config.mjs` |
| SEC-06 | **Thirty-day refresh tokens live in `localStorage`.** Honest, well-isolated tradeoff — but combined with no CSP, any XSS yields a long-lived refresh token, and therefore account takeover that survives a password change (see SEC-07). | `apps/web/src/lib/auth/token-storage.ts:1-13` |
| SEC-07 | **Password reset leaves existing sessions alive.** The reset itself is well built (single-use hashed token, 2 h TTL, uniform errors), but the attacker's session and refresh family both survive it. No audit record for the credential change, by deliberate design. | `identity/service.py:314-341` |
| SEC-08 | **Invite acceptance authenticates an existing account without its password.** When an invite targets an address that already has an account, acceptance adds the membership and issues that user a session — the submitted password is never checked against the existing hash. The response also enumerates every other company that account belongs to. The code already declines to overwrite the password; it should likewise decline to grant a session. | `account_invite/service.py` (existing-user branch → `issue_tokens_for`) |
| OPS-02 | **Client IPs are not resolved behind a proxy.** Every bucket is keyed on the socket peer, which behind a load balancer is the balancer — all registration/reset/invite traffic collapses into one shared counter. Logged IPs on sessions and audit rows are wrong for the same reason. | `shared/rate_limit.py:49`; no `ProxyHeadersMiddleware` in `app.py` |
| SEC-09 | **Registration creates unverified tenants and signs the creator straight in.** No email verification exists anywhere. Any address — including one the registrant does not control — produces a live trial company with a `COMPANY_ADMIN` session, and is then permanently bound to that tenant under the global unique index on `user.email`, enabling address squatting. | `organisation/router.py:108` |
| DEP-01 | **JWT handling depends on an unmaintained library.** `python-jose` carries published algorithm-confusion and DoS advisories (CVE-2024-33663, CVE-2024-33664). Application usage is careful (HS256 pinned both ways, token type asserted), so this is supply-chain exposure rather than an exploitable bug today. No dependency scanning runs in CI. | `pyproject.toml`; `core/auth/jwt.py` |

---

## 4. Database & tenant isolation

68 linear migrations, 81 tables, timezone-aware timestamps throughout, money as integer minor units,
GiST exclusion constraints preventing overlapping effective-dated rows, and no destructive cascade
on any HR fact. **The modelling is strong.** The gaps are in coverage at the edges rather than in
the core design.

| Control | State | Detail |
|---|---|---|
| Runtime role | 🟢 Strong | The app connects as `hrms_app` — NOSUPERUSER, NOBYPASSRLS, owns nothing. CI asserts those attributes before the security suite runs, so the RLS tests cannot pass vacuously. |
| Policy coverage | 🟢 Strong | 67 tenant tables carry `ENABLE` + `FORCE ROW LEVEL SECURITY` with a `tenant_isolation` policy. An unset GUC yields zero rows — fails closed. |
| RLS on `company` | 🟡 No-op | `scripts/sql/001_init_schema.sql:464` issues `FORCE` without `ENABLE`, which does nothing in Postgres. The comment reasons it away as the tenant root; the practical effect is no backstop on company rows. |
| Identity tables | 🟡 Uncovered | `user`, `session`, `refresh_token`, `password_reset_token`, `user_role`, `role_permission`, `permission` have no policy. Cross-company by nature, so defensible — but application `WHERE` clauses are the only control. |
| Deliberate exemptions | 🟢 Documented | `onboarding_token` and `account_invite` are explicitly exempt so a pre-tenant-context lookup can resolve them; both are hash-keyed and set the GUC immediately after resolving. `login_lookup_user_companies` (migration `20260828090000`) is a correctly hardened `SECURITY DEFINER` escape hatch — `search_path` pinned, `EXECUTE` granted only to `hrms_app`, no company parameter. |
| Pre-auth GUC | 🟠 Footgun | `TenancyMiddleware` sets `app.company_id` from an unverified `X-Company-Id` header (`core/tenancy/middleware.py:21-26`); `get_tenant_context` re-sets it from the verified JWT. Correct for every route today, fail-open for any future route that forgets the dependency. |
| PII at rest | 🔴 Blocked | See DATA-01. |
| Migration rollback | 🟡 Partial | Chain is linear and unbroken with real `downgrade()` bodies, except the base revision, which raises `NotImplementedError`. No downgrade is exercised in CI. |
| Backup & restore | 🟠 Undefined | No documented backup cadence, retention, restore drill or RPO/RTO target anywhere in the repository. |

> **Worth stating plainly:** tenant isolation here is better than most multi-tenant products reach
> before their first customer. The database itself — not a forgotten `WHERE` clause — is what stops
> a cross-tenant read, and there is a test suite that opens its own restricted connection to prove
> it. That foundation is why the remaining findings are fixable in days rather than months.

---

## 5. Medium severity (P2)

| ID | Finding | Evidence |
|---|---|---|
| OBS-01 | Unhandled exceptions are swallowed — the 500 handler discards the exception with `_ = exc` and a comment deferring Sentry to "a later sprint." Production errors leave no trace. | `core/errors/handlers.py:74-81` |
| OBS-02 | No request access log, no metrics endpoint, no tracing. `structlog` is configured and `get_logger` is never called from a request path. | `core/observability/logging.py` |
| OPS-03 | Health check reports `redis: "skipped"` and there is no liveness/readiness split — an orchestrator cannot tell "starting" from "broken," and a Redis outage surfaces as 500s on every rate-limited route. | `modules/health/service.py` |
| OPS-04 | API image runs as root with no `USER`, no `HEALTHCHECK`, and a single-process uvicorn command — `gunicorn` is a declared dependency but never invoked. | `apps/api/Dockerfile` |
| OPS-05 | No Dockerfile, build step or deployment path exists for the web app at all; CI never runs `next build`, so a build-time failure reaches `main` undetected. | `apps/web`; `.github/workflows/ci.yml` |
| OPS-06 | Interactive API docs and the OpenAPI schema are served unconditionally in every environment, publishing the full route surface to unauthenticated callers. | `app.py:30-32` |
| QA-01 | The web app has no ESLint configuration or dependency; `npm run lint` would prompt interactively, so CI substitutes `tsc --noEmit`. No linting gate on 45k lines of TypeScript. | `ci.yml`; `apps/web/package.json` |
| SEC-10 | Password policy is 8 characters with one letter and one digit — no breach-list check, no history, no rotation. No MFA anywhere in the product. | `core/auth/passwords.py:20-31` |
| SEC-11 | The rate limiter has no failure policy: if Redis is down the dependency raises and the endpoint 500s, and one shared `auth` bucket covers registration, password reset and invite acceptance together. | `shared/rate_limit.py:48-56` |
| AUD-01 | Audit coverage is uneven — 44 records in attendance and 30 in organisation, but **zero** in `employee_import`, which mutates employee records in bulk, and none for credential changes. | `modules/*/service.py` |

---

## 6. What is already solid

Assessed with the same scrutiny as the findings. These are load-bearing and should not be disturbed
while fixing the rest.

- **Refresh-token rotation with family revocation** — every refresh revokes and reissues; replaying
  a spent token revokes the entire family and its sessions (`identity/service.py:103-149`).
- **Per-request session validation** — every authenticated request re-checks user status, session
  revocation and active company membership against the database, not just the token signature
  (`core/auth/dependencies.py:29-40`).
- **Fail-closed permission resolution** — an empty data scope raises rather than defaulting to
  company-wide (`core/rbac/dependencies.py:28-33`), and writes verify the *target* record's
  visibility, not merely that the caller holds the permission.
- **404 instead of 403 across tenants** — out-of-scope and nonexistent identifiers return identical
  responses, so the API cannot be used to probe for record existence.
- **Server-assigned punch instants** — `PunchCreateSelf` has no `punch_time`, `source` or
  `employee_id` field and uses `extra="forbid"` (`attendance/schemas.py:1260-1284`), closing
  DEC-TZ-01. `source` is server-assigned on every route.
- **Anti-enumeration throughout** — login, forgot-password, invite and onboarding token resolution
  all return one identical response for every failure mode.
- **Enforced engineering gates** — 1,220 tests, `mypy --strict`, ruff lint and format,
  import-linter module boundaries, and CI pinned to UTC so a host-clock regression fails the build.
- **Period locks on every write path** — closed attendance periods are checked at 13 separate
  mutation sites, with unlocking gated behind a permission distinct from period management.

---

## 7. Go-live sequence

Ordered by dependency and risk, not by effort. Steps 1–5 clear the blockers; 6–8 are the minimum
bar for handling a real customer's data; 9–10 are what make an incident survivable.

| # | Step | Closes |
|---|---|---|
| 1 | **Make the API reachable and its secrets mandatory.** Environment-driven CORS origins, plus boot-time validation that refuses to start on default JWT secrets outside development. | OPS-01, SEC-01 |
| 2 | **Throttle the credential endpoints.** Rate-limit login and refresh by IP and by email, and resolve the real client IP behind the proxy so every existing bucket starts working. | SEC-02, OPS-02 |
| 3 | **Encrypt the identifiers.** Envelope-encrypt PAN, Aadhaar and bank account columns; mask them in read schemas. Do this before the first tenant, while backfill is still cheap. | DATA-01 |
| 4 | **Paginate every list endpoint.** Wire the existing `PaginationMeta` through the list envelope with a server-side ceiling, and bound the attendance and leave date ranges. | API-01 |
| 5 | **Harden the two public write surfaces.** Size-check before buffering, allow-list MIME types, sanitise object keys, force attachment disposition, rate-limit the public onboarding router. | SEC-03, SEC-04 |
| 6 | **Close the session-lifecycle gaps.** Revoke sessions and token families on password reset; require real authentication before an invite attaches a membership to an existing account. | SEC-07, SEC-08 |
| 7 | **Add security headers and move the refresh token to a cookie.** CSP, HSTS and the rest on both apps; an HttpOnly refresh cookie the API already knows how to read. | SEC-05, SEC-06 |
| 8 | **Verify email before a tenant becomes real.** Hold new companies in a pending state until the admin address is confirmed. | SEC-09 |
| 9 | **Turn on the lights.** Error tracking in the 500 handler, request access logging with the existing request id, a Redis-aware readiness probe, a defined limiter failure policy. | OBS-01, OBS-02, OPS-03, SEC-11 |
| 10 | **Finish the delivery pipeline.** Non-root API image with a health check, a web container and build step, dependency and container scanning, a documented and rehearsed backup restore. | OPS-04, OPS-05, QA-01, DEP-01 |

---

*Static source review at commit `c3b8cec`, 17 September 2026. Every finding cites the file and line
it was read from; no exploitation was attempted and no running system was tested.*
