# Security Readiness Audit

| Field | Value |
|---|---|
| Audit date | 2026-09-10 |
| Commit | `e33fcdb` |
| Method | Static source review + safe validation. **No exploitation was attempted.** |
| Parent document | [`PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md`](./PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md) |
| Verdict | 🟠 **NEEDS FIX BEFORE PRODUCTION** — no breach vector found; hardening and deployability gaps |

---

## Executive position

**No cross-tenant data leakage, IDOR/BOLA vulnerability, SQL injection, or authentication bypass was
identified.** The three things that most often go wrong in a multi-tenant HRMS — tenant isolation,
object-level authorization, and credential handling — are all done well here, and in the case of tenant
isolation, unusually well.

The security findings are of three kinds:

1. **A deployability defect** — production CORS resolves to an empty origin list, which would break the
   application on its first deployment (SEC-001).
2. **Missing hardening layers** — rate limiting on one endpoint, no security headers, no proxy-header
   handling, no dependency scanning.
3. **A verification gap** — the RLS backstop is designed correctly but the test suite runs as a
   BYPASSRLS superuser, so it is largely unexercised (TEN-002).

---

## 1. Authentication

| Control | Implementation | Evidence | Status |
|---|---|---|---|
| Password hashing | argon2 via `argon2-cffi`, library defaults | `core/auth/passwords.py:4-17` | 🟢 |
| Password policy | ≥8 chars, at least one letter and one digit | `is_password_strong_enough:20-31` | 🟡 Weak; no breach-list check, no rotation, no history |
| Access token | JWT HS256, 15-minute TTL, `type: "access"` claim checked on decode | `core/auth/jwt.py:15-46` | 🟢 |
| Refresh token | 48-byte `secrets.token_urlsafe`, stored as SHA-256 only | `core/auth/tokens.py` | 🟢 |
| **Refresh rotation** | Every refresh revokes the presented token (`ROTATED`) and issues a new one in the same family | `identity/service.py:114` | 🟢 |
| **Reuse detection** | Presenting an already-revoked refresh token revokes the **entire family** (`REUSE_DETECTED`) | `identity/service.py:101-106` | 🟢 **Excellent** |
| Session revocation | `get_current_user` verifies `session.revoked_at IS NULL` on **every** request | `core/auth/dependencies.py:34-36` | 🟢 |
| Logout | Revokes the session row → all access tokens for it become invalid immediately | `identity/service.py:141-150` | 🟢 |
| Account lockout | 5 consecutive failures → 15-minute lock; reset on success | `core/db/repositories/identity.py:164-176` | 🟢 |
| User enumeration | Identical `"Invalid email or password"` for unknown user, bad password, and no membership | `identity/service.py:46, 54, 60, 75` | 🟢 |
| Membership validation | Every request re-validates `user_company.status = 'ACTIVE'` | `core/auth/dependencies.py:38-40` | 🟢 |
| Password reset | ❌ Not implemented | — | 🟡 |
| Email verification | ❌ Not implemented | — | 🟡 |
| MFA | ❌ Not implemented | — | 🔵 |

**SEC-A1 🟠 — no brute-force protection at the request layer.** Per-account lockout is the only control.
Password spraying across many accounts is unthrottled, and the lockout itself is an account-denial
primitive an attacker can trigger for any known email. See SEC-002.

---

## 2. Authorization

| Control | Implementation | Status |
|---|---|---|
| Permission model | Module-owned code constants seeded into `permission`; `role_permission` carries a `data_scope` | 🟢 |
| Permission check | `require_permission(code)` → `resolve_data_scope` → **empty scope fails closed** | 🟢 `core/rbac/dependencies.py:28-33` |
| Data scope levels | `SELF` · `REPORTEES` · `REPORTEE_TREE` · `COMPANY` | 🟢 |
| Scope union semantics | Multiple roles union their levels; `COMPANY` short-circuits; empty never implies `COMPANY` | 🟢 `employee/service.py:119-141` |
| **Object-level check** | Every write additionally verifies the **target** employee id, not merely that the caller holds the permission | 🟢 `_ensure_employee_visible` |
| Error shape | Out-of-scope and nonexistent both return an identical 404 | 🟢 `attendance/service.py:1904-1906` |
| Privileged separation | Reopening a locked period requires `ATTENDANCE.UNLOCK`, distinct from `PERIOD_MANAGE` | 🟢 |
| Self-approval | Blocked — an employee who heads their own department is treated as "no HOD resolved" and falls through to HR | 🟢 `leave/service.py:2061` |

### IDOR / BOLA assessment

**No vulnerability identified.** The pattern that prevents it is applied consistently, and the commit
history shows it was a deliberate hardening pass rather than an accident:

- `fecb740` — *"fix(identity,attendance): resolve employee_id in real JWTs and enforce punch DataScope"*
- `7a8ff30` — *"feat(employee): close RBAC data-scope enforcement gaps end-to-end (F4/F8/F9)"*

The `PunchService.record_punch` docstring names the exact bug class the pattern defends against
(`attendance/service.py:2323-2331`): *"a `REPORTEES`/`REPORTEE_TREE`/`SELF`-scoped `PUNCH_ON_BEHALF`
grant could be used to punch an employee entirely outside the caller's visible set."*

**Residual gaps.** 🟡 Leave cancellation is identity-based (submitter only), not permission-based, so HR
has no cancellation path — this is a business gap rather than a security one. 🟡 There is no audit-log
read API, so the security trail is reachable only by direct SQL.

---

## 3. Multi-tenant isolation

**This is the strongest area of the codebase.**

| Layer | Control | Evidence |
|---|---|---|
| Database | `ENABLE` + `FORCE ROW LEVEL SECURITY` + a `tenant_isolation` policy on **70 of 79 tables** | `scripts/sql/002_row_level_security.sql` + a block in nearly every migration |
| Policy shape | `USING (company_id = current_setting('app.company_id', true)::uuid)` — Postgres applies this as `WITH CHECK` for INSERT/UPDATE too, so writes are constrained as well as reads | — |
| Fail-closed | An unset GUC makes `current_setting(..., true)` return NULL → `company_id = NULL` → no rows | — |
| Runtime role | `hrms_app`: `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`, owns nothing, so `FORCE` cannot be bypassed | `infra/docker/postgres/init/002_app_role.sql:16-23` |
| Migration role | Separate `MIGRATIONS_DATABASE_URL`; `Settings` deliberately has **no field** for it, so the app process never loads the admin credential | `alembic/env.py:16-29` |
| GUC timing | Set at session open, then **re-set from the verified company id** after the membership check | `core/tenancy/dependencies.py:31-37` |
| Header trust | `X-Company-Id` must equal the JWT claim, else 404 | `core/tenancy/dependencies.py:19-20` |
| Application layer | Every repository query filters `company_id` explicitly **in addition to** RLS | Sampled across all repositories |
| Background jobs | `session_scope(company_id=...)` sets the GUC per task | `leave/tasks.py:34, 59, 83, 108` |
| Public onboarding | GUC set from the **token's own server-authored** `company_id`; no public route accepts a client `company_id` or `case_id` | `onboarding/service.py:450-455`; `public_router.py:9-10` |
| File storage | S3 keys namespaced `onboarding/{company_id}/{case_id}/…`, reachable only via a presigned URL minted after a tenant-scoped DB read | `onboarding/service.py:571` |

### Tables without RLS — assessed, not overlooked

`company` · `permission` · `plan` · `plan_feature` · `refresh_token` · `session` · `user` ·
`role_permission` · `user_role`

- `permission`, `plan`, `plan_feature` — global catalogues shared by all tenants. Correct.
- `user`, `session`, `refresh_token` — cross-tenant by nature (a user may belong to several companies).
  Access is always keyed by an authenticated `user_id`.
- `role_permission`, `user_role` — no `company_id` column exists to key on. Reached only through the
  RLS-protected `user_company` join, which the RBAC query **also** filters explicitly
  (`core/rbac/service.py:18-31`). Documented as intentional (`002_row_level_security.sql:31-33`).
- **`company`** — 🟡 **SEC-007.** `ALTER TABLE company FORCE ROW LEVEL SECURITY` is issued
  (`002_row_level_security.sql:10`) but RLS is never `ENABLE`d and no policy is created. `FORCE` without
  `ENABLE` is a no-op, so `company` rows have no RLS backstop at all. The application always filters
  explicitly and `IdentityService.get_company` checks `company_id != viewer_company_id` → 404
  (`identity/service.py:169-173`), so no leak path was found — but the intended backstop is absent.

### TEN-002 🟠 — designed well, verified weakly

`tests/conftest.py:9` and `.github/workflows/ci.yml:47` both point `DATABASE_URL` at the **superuser
`hrms`** role, which has `BYPASSRLS`. Only `tests/security/test_rls_runtime_role.py` temporarily
repoints the engine at `hrms_app` (`:64`, `:73`).

Every other test — including
`tests/integration/modules/organisation/test_cross_tenant_isolation.py` — therefore validates
application-layer filtering with RLS effectively switched off underneath.

That one security test file is genuinely good: it asserts `current_user = 'hrms_app'`, exercises real
cross-tenant reads, and even records a regression where login failed under the restricted role
(`:366`, fixed in commit `0c17787`). It should be the default, not the exception.

**Fix:** run the whole suite as `hrms_app`; keep an `hrms`-role fixture only for seeding.

---

## 4. Injection and input handling

| Vector | Assessment | Evidence |
|---|---|---|
| SQL injection | 🟢 **Not present.** All queries use SQLAlchemy Core/ORM parameter binding. `set_config('app.company_id', :company_id, true)` is parameterised (`core/db/session.py:46-49`). Migrations use static DDL. | — |
| ORM injection | 🟢 No dynamic attribute or column names from user input | — |
| XSS (reflected/stored in app) | 🟢 React escapes by default; no `dangerouslySetInnerHTML` found | — |
| **Stored XSS via upload** | 🟡 **SEC-005.** Client-supplied `content_type` is stored verbatim and echoed by the presigned GET | `onboarding/service.py:583` |
| CSRF | ⚪ Not applicable — bearer tokens in an `Authorization` header, no cookie authentication | — |
| SSRF | ⚪ No user-controlled outbound URL fetch exists | — |
| Command injection | ⚪ No shell invocation from request data | — |
| Path traversal | 🟡 `s3_key = f"onboarding/{company_id}/{case_id}/{document_id}/{filename}"` interpolates the raw client filename (`onboarding/service.py:571`). S3 keys are flat, so this is key-pollution and content-disposition weirdness rather than filesystem traversal — but it is unsanitised input in a storage path. | — |
| Deserialization | 🟢 Celery is JSON-only (`task_serializer="json"`, `accept_content=["json"]`) | `core/celery_app.py:15-17` |
| Mass assignment | 🟢 Pydantic schemas define exactly which fields are writable | — |

### File upload — SEC-005 🟡 / SEC-006 🟡

`apps/api/src/hrms/modules/onboarding/service.py:545-591`

| Check | Present? |
|---|---|
| Size limit | ✅ `ONBOARDING_DOCUMENT_MAX_SIZE_BYTES` |
| Document-type allow-list | ✅ `ONBOARDING_DOCUMENT_TYPES` |
| Case status gate | ✅ writable statuses only |
| **MIME allow-list** | ❌ any `content_type` accepted and stored |
| **Magic-byte verification** | ❌ |
| **Filename sanitisation** | ❌ raw filename in the S3 key |
| **Streaming size check** | ❌ `await file.read()` buffers the whole body before the limit is applied (`public_router.py:94`) |
| Malware scanning | ❌ |

**Recommended:** allow-list `application/pdf`, `image/jpeg`, `image/png`; verify magic bytes; slugify the
filename; enforce the size limit from `Content-Length` before reading; set
`ContentDisposition: attachment` on the presigned GET.

---

## 5. Transport, headers, and CORS

### SEC-001 🟠 CRITICAL — production CORS is unusable

`apps/api/src/hrms/app.py:36-42`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- **Production** (`environment in ("staging", "production")`) → `allow_origins = []`. **Zero** origins
  are permitted, so the deployed frontend cannot call the API at all. This would surface on the first
  deployment as a total outage.
- **Development** → `["*"]` combined with `allow_credentials=True` is a combination browsers reject
  outright per the CORS specification.

**Fix:** add a `cors_allowed_origins: list[str]` setting; fail boot if production resolves to an empty
list; drop `allow_credentials` (the app uses bearer tokens, not cookies).

### SEC-004 🟠 — no security headers, no host validation, no proxy awareness

| Header / control | Present? |
|---|---|
| `Strict-Transport-Security` | ❌ |
| `Content-Security-Policy` | ❌ |
| `X-Content-Type-Options: nosniff` | ❌ |
| `X-Frame-Options` / `frame-ancestors` | ❌ |
| `Referrer-Policy` | ❌ |
| `Permissions-Policy` | ❌ |
| `TrustedHostMiddleware` | ❌ |
| Proxy-header handling (`X-Forwarded-For`/`-Proto`) | ❌ |
| HTTPS redirect | ❌ |

The proxy gap has a direct consequence: `rate_limit` keys on `request.client.host`
(`shared/rate_limit.py:49`), which behind a load balancer is the **balancer's** address — turning a
per-client limit into a global one.

Only one header is set today: `X-Request-Id`, echoed by `TenancyMiddleware` (`middleware.py:33`).

### 🟡 API documentation exposed in every environment

`app.py:30-32` enables `/docs`, `/redoc`, and `/v1/openapi.json` unconditionally. Not a vulnerability in
itself — the endpoints are still authenticated — but it publishes the complete API surface to
unauthenticated visitors in production.

---

## 6. Rate limiting — SEC-002 🟠

A Redis-backed sliding-window limiter exists and is correctly implemented
(`shared/rate_limit.py`). It is applied to **exactly one endpoint**:

```
$ grep -rn "rate_limit(" src/
src/hrms/shared/rate_limit.py:43:  def rate_limit(...)
src/hrms/modules/organisation/router.py:88: _registration_rate_limit = rate_limit("auth", limit=10, window_seconds=60)
```

Unprotected, unauthenticated, and high-value:

| Endpoint | Exposure |
|---|---|
| `POST /v1/auth/login` | Password spraying; account-lockout DoS |
| `POST /v1/auth/token/refresh` | Token brute force |
| `GET /v1/public/onboarding/{token}` | Token enumeration |
| `PATCH /v1/public/onboarding/{token}/sections/{section}` | Unauthenticated write attempts |
| `POST /v1/public/onboarding/{token}/documents` | Unauthenticated upload attempts |

*Mitigating factor for the onboarding surface:* tokens are 32 random bytes
(`secrets.token_urlsafe(32)`, `onboarding/service.py:414`), stored as SHA-256 only, and every failure
mode returns an identical 404 so enumeration cannot distinguish "never existed" from "expired"
(`resolve_and_touch:434-448`). The entropy makes guessing infeasible; the missing limit is about resource
exhaustion, not token discovery.

Also note: `settings.rate_limit_window_ms` and `rate_limit_max` are defined and **never read** — the one
call site hard-codes `limit=10, window_seconds=60`.

---

## 7. Secrets and configuration

| Check | Finding | Status |
|---|---|---|
| Secrets in git | **None.** `git ls-files` returns only `*.example` templates; a scan for `AKIA` and private-key headers found nothing. | 🟢 |
| `.gitignore` | Covers `.env`, `.env.local`, `.env.*.local`, and `apps/api/env/.env.*` with an explicit `!*.example` negation and a comment explaining why | 🟢 |
| Environment separation | Four committed templates: dev / qa / staging / production | 🟢 |
| Boot validation | `pydantic-settings` validates at import; `jwt_*_secret` enforce `min_length=16` | 🟢 |
| Credential separation | Runtime (`hrms_app`) and migration (`hrms`) roles are separate URLs; the app never loads the migration credential | 🟢 **Excellent** |
| Email provider flag | `email_provider` is an explicit setting rather than inferred from credential presence, with the reasoning documented at `settings.py:40-47` | 🟢 Thoughtful |
| Secret manager | ❌ None — secrets are plain environment variables | 🟡 |
| **Production guardrails** | ❌ Nothing prevents booting production with `jwt_access_secret = "change-me-local-dev-only-min-16"` | 🟠 |
| Encryption at rest | ❌ No column-level encryption for PAN, Aadhaar, UAN, PF, or bank details | 🟡 |
| Key rotation | ❌ No JWT-secret rotation mechanism (no `kid` claim, no multi-key verification) | 🟡 |

### SEED-1 🟠 — the demo seed has no environment guard

`apps/api/scripts/seed.py` creates `admin@example.com` with password `DemoPass123!`, a
`COMPANY_ADMIN` role holding **every permission in the catalogue** at `COMPANY` data scope. The
credentials are documented in `docs/development/DEMO_SEED_CREDENTIALS.md`. Nothing in the script checks
`settings.environment`.

**Fix:** guard the demo seed with an environment assertion, and split the permission-catalogue seed
(which *must* run in production) from the demo-user seed (which must never).

---

## 8. Sensitive data

| Concern | Finding | Status |
|---|---|---|
| Passwords in logs | 🟢 None found | 🟢 |
| Tokens in logs | 🟢 None found | 🟢 |
| Tokens in URLs | 🟡 The onboarding token is a **path parameter** (`/public/onboarding/{token}`) — it will appear in access logs, proxy logs, and `Referer` headers | 🟡 |
| PII in error responses | 🟢 Generic messages; the catch-all returns no detail | 🟢 |
| PII at rest | 🟡 PAN, Aadhaar, UAN, PF, ESI, and bank details are plaintext columns | 🟡 |
| PII in the audit log | 🟡 `before_json` / `after_json` capture full entity state, including statutory identifiers, with no redaction and no retention policy | 🟡 |
| Client-side token storage | 🟠 Access **and refresh** tokens in `localStorage` — readable by any XSS. Documented as a deliberate trade-off at `web/src/lib/auth/token-storage.ts:3-13`, because the backend sets no `Set-Cookie`. | 🟠 SEC-003 |

---

## 9. Dependency and supply chain

| Check | Finding |
|---|---|
| Lockfiles | ✅ `uv.lock` (494 KB), `package-lock`/`node_modules` for web |
| Docker base pinning | ⚠️ `python:3.12-slim` — tag-pinned, not digest-pinned |
| **Vulnerability scanning** | ❌ No `pip-audit`, `safety`, `npm audit`, Dependabot, or Renovate anywhere |
| SAST | ❌ None (`ruff` lints style and simple bug patterns, not security) |
| Secret scanning | ❌ No gitleaks or TruffleHog in CI |
| SBOM | ❌ None |
| Container scanning | ❌ No Trivy or Grype |

**SEC-011 🟡.** A modern HRMS handling statutory identifiers and bank details should not ship without at
least dependency scanning and secret scanning on every pull request. Both are low-effort CI additions.

---

## 10. Findings summary

| ID | Finding | Severity | Fix effort |
|---|---|---|---|
| SEC-001 | Production CORS resolves to an empty origin list; dev uses `*` with credentials | 🟠 CRITICAL | Low |
| SEC-002 | Rate limiting applied to 1 of ~150 endpoints; login and public onboarding unlimited | 🟠 CRITICAL | Low |
| SEC-004 | No security headers, no `TrustedHostMiddleware`, no proxy-header handling | 🟠 CRITICAL | Low |
| SEED-1 | Demo seed has no environment guard; creates a known-credential super-admin | 🟠 CRITICAL | Low |
| SEC-A1 | No request-layer brute-force protection (per-account lockout only) | 🟠 CRITICAL | Low |
| TEN-002 | Test suite runs as a BYPASSRLS superuser; RLS largely unverified | 🟠 CRITICAL | Medium |
| SEC-003 | Access and refresh tokens in `localStorage` | 🟠 HIGH | Medium |
| SEC-005 | Upload: no MIME allow-list, no magic-byte check, unsanitised filename in the S3 key | 🟡 HIGH | Low |
| SEC-006 | Upload body fully buffered before the size check | 🟡 HIGH | Low |
| SEC-007 | `company` has `FORCE` RLS but RLS is never `ENABLE`d and no policy exists | 🟡 HIGH | Low |
| SEC-011 | No dependency, secret, container, or static analysis scanning in CI | 🟡 HIGH | Low |
| PROD-1 | No production guardrail against default JWT secrets | 🟡 HIGH | Low |
| DOCS-1 | `/docs`, `/redoc`, `/openapi.json` exposed in every environment | 🟡 MEDIUM | Low |
| PII-1 | Statutory identifiers and bank details stored unencrypted | 🟡 MEDIUM | High |
| PII-2 | Audit log captures full PII with no redaction or retention policy | 🟡 MEDIUM | Medium |
| TOK-1 | Onboarding token travels as a URL path parameter | 🟡 MEDIUM | Medium |
| SEC-010 | No password reset, email verification, or MFA; weak password policy | 🟡 MEDIUM | Medium |
| KEY-1 | No JWT key rotation mechanism | 🔵 LOW | Medium |
| RL-1 | `rate_limit_window_ms` / `rate_limit_max` settings are never read | 🔵 LOW | Trivial |

---

## 11. What is genuinely strong — do not rebuild

1. **The RLS role separation.** A dedicated non-superuser runtime role, a separate migration credential
   the app process cannot load, and a plan document explaining why
   (`docs/architecture/POSTGRES_RLS_ROLE_MIGRATION_PLAN.md`). This is better than most production HRMS
   deployments.
2. **Refresh-token family reuse detection.** Presenting a revoked token revokes the whole family. This is
   the correct design and it is implemented correctly.
3. **Object-level authorization.** Checking the *target* id rather than merely permission possession is
   the control that actually prevents IDOR, and it is applied consistently — with commit history showing
   it was a deliberate hardening pass.
4. **Fail-closed everywhere.** Empty `DataScope` → deny. Unset RLS GUC → zero rows. Missing policy →
   `CONFIG_ERROR` → period cannot close. Unknown onboarding token → 404 identical to expired.
5. **The identical-404 discipline.** Out-of-scope, cross-tenant, and nonexistent all return the same
   response, so no probe distinguishes them.

---

## 12. Recommended security work before production

**Before Payroll development starts (P0):**
- SEC-001 — CORS configuration + boot assertion.

**Before any production deployment (P1/P2):**
- SEC-002 — rate-limit login, refresh, and the public onboarding surface.
- SEC-004 — security-headers middleware, `TrustedHostMiddleware`, proxy-header handling, `/docs` off in
  production.
- SEED-1 — environment guard on the demo seed; split catalogue from demo.
- TEN-002 — run the test suite as `hrms_app`.
- PROD-1 — refuse to boot production with default secrets.
- SEC-011 — dependency and secret scanning in CI.
- SEC-005/006 — upload hardening.
- SEC-007 — `ENABLE ROW LEVEL SECURITY` on `company` with a policy, or document that it is intentionally
  a global table.

**Before handling real employee data at scale (P3):**
- PII-1 — column-level encryption for statutory identifiers and bank details.
- PII-2 — audit-log redaction and retention policy.
- SEC-003 — migrate the refresh token to an HttpOnly cookie.
- SEC-010 — password reset, email verification, and a stronger password policy.

---

*No application code, schema, migration, test, or configuration was modified during this audit. No
exploitation was performed.*
