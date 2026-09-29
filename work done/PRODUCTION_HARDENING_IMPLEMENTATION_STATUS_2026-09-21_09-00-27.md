# Production Hardening — Implementation Status

**Type:** Canonical status report. Documentation only — no source code, tests, configuration, or
migrations were modified to produce this report. No files were staged, committed, reset, stashed,
or reverted.

**Report date:** 2026-09-21
**Branch:** `main` @ `c3b8cec` (local `main` is 10 commits ahead of `origin/main` @ `713c539`; that
gap pre-dates and is unrelated to this report)
**Author basis:** Direct reading of `docs/audits/PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.md`,
`PRODUCTION_HARDENING_CONSOLIDATION_AUDIT.md`, `PRODUCTION_HARDENING_BATCH_1_REPORT.md`,
`UPLOAD_BATCH_{A,B,C}_*.md`, `API_01_PAGINATION_IMPLEMENTATION_REPORT.md`,
`DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md`; direct inspection of source files
(`settings.py`, `rate_limit.py`, `storage.py`, `core/crypto/*`, `core/db/repositories/identity.py`,
`core/db/session.py`, `employee/service.py`); direct `git status` inspection; an independent
`pytest` collection (1490 tests collected, matching every batch report's cumulative count) and full
suite re-run (§7).

---

## 1. Executive Summary

**Project:** Staff Spectrum HRMS
**Purpose:** Production security, reliability, deployment, and API hardening
**Current status:** NOT READY FOR PRODUCTION

A substantial, multi-workstream production-hardening effort has been implemented against the
findings in the 2026-09-17 platform readiness audit. Three of five original P0 blockers
(`OPS-01` CORS, `SEC-01` JWT secrets, `SEC-02` login/refresh throttling — bundled with `OPS-02`
proxy handling) are genuinely fixed at the code level. A fourth P0 (`API-01` pagination) is fixed
for its Tier 1 scope. The fifth P0 (`DATA-01` PII encryption) is real but partial — the crypto
infrastructure and one of four planned write paths are implemented and tested, but key operational
and compliance prerequisites remain outstanding. A parallel, originally out-of-scope effort closed
the public onboarding upload endpoint's size/content/rate-limit gaps (`SEC-03`, `SEC-04`).

**None of this work is committed.** All of it sits in the working tree as modified/untracked files
on top of `c3b8cec`. It has not been pushed, and this report does not commit it.

Status vocabulary used throughout this report, applied precisely:

| Status | Meaning |
|---|---|
| `FIXED` | Implemented, tested, and committed |
| `FIXED — UNCOMMITTED` | Implemented and tested in the working tree; not yet committed |
| `PARTIAL` | Some of the finding's scope is implemented; some is not |
| `OPEN` | Not implemented |
| `NOT STARTED` | Explicitly out of scope for every workstream to date, no code exists |
| `WAITING FOR POLICY APPROVAL` | Implemented, but the specific numeric/scope decision has not been signed off by product/security |
| `OPERATIONAL PREREQUISITE` | Code is fail-closed on this being done, but it is an operator action outside this codebase (e.g. provisioning a real KMS key), not a code change |
| `KNOWN LIMITATION` | A deliberate, documented scope boundary, not a defect |
| `PRE-EXISTING FAILURE` | A test failure that predates and is unrelated to this hardening effort |

Fourteen of the original 22 P0/P1/P2 findings remain fully `OPEN`, untouched by any of this work
(§4, §14). No overall completion percentage is given anywhere in this report — none is supported by
the source material, and inventing one would violate the reporting rules this document was built
under.

---

## 2. Original Audit Baseline

Source: `docs/audits/PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.md`, commit `c3b8cec`, verdict
**NOT PRODUCTION-READY — 5 P0, 9 P1, 10 P2**.

| ID | Finding | Original Severity | Original Problem | Current Status |
|---|---|---|---|---|
| OPS-01 | Production CORS allows no origins | P0 | `allow_origins=["*"] if is_development else []` — empty outside dev, blocks every browser request; dev's `["*"]` + `allow_credentials=True` is itself an invalid combination | `FIXED — UNCOMMITTED` (§5D) |
| SEC-01 | JWT signing secrets have working defaults, no production guard | P0 | Both secrets default to a known, 16+ char value that clears the length check; nothing rejects it outside development — a full cross-tenant auth bypass | `FIXED — UNCOMMITTED` (§5E) |
| SEC-02 | No rate limit on login or token refresh | P0 | Neither route took the existing `rate_limit` dependency; only per-account lockout (itself later found broken, §5F) | `FIXED — UNCOMMITTED` (§5F); one new, separate follow-up bug discovered, not fixed |
| DATA-01 | Aadhaar/PAN/bank account numbers stored in plaintext despite `_enc` column names | P0 | No encryption primitive anywhere in the API | `PARTIAL — NOT CLOSED` (§6) |
| API-01 | No list endpoint in the API is paginated | P0 | `PaginationMeta` defined, zero usages; every list endpoint serializes the full result set | `FIXED — UNCOMMITTED` for Tier 1 scope (§5H) |
| SEC-03 | Public document upload buffers the entire request before size check; no rate limit | P1 | `onboarding/public_router.py:94` → `service.py:566`, `await file.read()` before any size check; endpoint unthrottled | `FIXED — UNCOMMITTED` (Batch B size/content half + Batch C rate-limit half, §5B/§5C) |
| SEC-04 | Uploaded content type is caller-controlled and replayed on download; unsanitized filename in S3 key; no malware scanning | P1 | `service.py:564-572` | `FIXED — UNCOMMITTED` for MIME/magic-byte/filename/`Content-Disposition` (§5B); malware scanning explicitly `NOT STARTED` |
| SEC-05 | No security headers on either application | P1 | No CSP, HSTS, `X-Content-Type-Options`, frame-options, referrer policy | `OPEN` |
| SEC-06 | Refresh tokens in `localStorage`, no CSP | P1 | `apps/web/src/lib/auth/token-storage.ts:1-13` | `OPEN` |
| SEC-07 | Password reset does not revoke existing sessions/refresh families | P1 | `identity/service.py:314-341` | `OPEN` |
| SEC-08 | Invite acceptance for an existing-account email issues a session without a password check | P1 | `account_invite/service.py`, existing-user branch | `OPEN` |
| OPS-02 | Client IPs not resolved behind a trusted proxy | P1 | `shared/rate_limit.py:49` used `request.client.host` directly; no `ProxyHeadersMiddleware` | `FIXED — UNCOMMITTED` (§5G) |
| SEC-09 | Registration creates unverified tenants, signs the creator in immediately | P1 | `organisation/router.py:108` | `OPEN` |
| DEP-01 | JWT handling depends on unmaintained `python-jose` (CVE-2024-33663/33664) | P1 | `pyproject.toml`; no CI dependency scanning | `OPEN` |
| OBS-01 | Unhandled exceptions swallowed (`_ = exc`), no error tracking | P2 | `core/errors/handlers.py:74-81` | `OPEN` |
| OBS-02 | No request access log, metrics, or tracing despite `structlog` being configured | P2 | `core/observability/logging.py` | `OPEN` |
| OPS-03 | No liveness/readiness split; health check reports Redis `"skipped"` | P2 | `modules/health/service.py` | `OPEN` |
| OPS-04 | API container runs as root, no `HEALTHCHECK`, single-process uvicorn | P2 | `apps/api/Dockerfile` | `OPEN` |
| OPS-05 | No Dockerfile/build/deploy path for the web app; CI never runs `next build` | P2 | `apps/web`; `.github/workflows/ci.yml` | `OPEN` |
| QA-01 | No ESLint config for the web app; CI substitutes `tsc --noEmit` | P2 | `ci.yml`; `apps/web/package.json` | `OPEN` |
| SEC-10 | Weak password policy (8 chars), no MFA, no breach-list/history/rotation | P2 | `core/auth/passwords.py:20-31` | `OPEN` |
| AUD-01 | Uneven audit coverage — zero records for `employee_import`, none for credential changes | P2 | `modules/*/service.py` | `OPEN` |
| SEC-11 | Rate limiter has no Redis-outage failure policy; one shared `auth` bucket for registration/reset/invite | P2 | `shared/rate_limit.py:48-56` | `PARTIAL / MOSTLY OPEN` (§14 — only the new onboarding-upload limiter, added by this round's own Batch C, fails closed; every pre-existing `Depends()`-based limiter is unchanged and still 500s on a Redis outage) |

**Findings surfaced during this round's work but not in the original 22-ID list** (documented for
awareness, not acted on):

- **OPS-06** — `/docs`, `/redoc`, `/openapi.json` served unconditionally in every environment (P2,
  named in the Sep-17 audit's own §5 table but not given a top-level ID in the go-live sequence
  count above). Untouched.
- **TEN-002** — test-suite DB role scoping; appears to have silently improved between the Sep-10
  and Sep-17 audits without a dedicated finding ID change. Not independently re-investigated for
  this report; flagged as-is from the consolidation audit.
- Old-scheme **SEC-007** (`company` table has `FORCE` RLS but no `ENABLE`) — still open per the
  Sep-17 audit's own §4 table (row "RLS on `company`" — 🟡 No-op). Not renumbered into the current
  `SEC-0X`/`OPS-0X` scheme.

**Numbering caveat.** The 2026-09-10 documents (`SECURITY_READINESS_AUDIT.md`,
`TECHNICAL_DEBT_REGISTER.md`) use `SEC-001`…`SEC-011`/`OPS-001`…`OPS-006`. The 2026-09-17 audit
independently reassigned `SEC-01`…`SEC-11`/`OPS-01`…`OPS-06` to **different, non-corresponding**
findings — e.g. old `SEC-001` (CORS) became new `OPS-01`. Every table in this report, and every
batch report it draws from, uses the **2026-09-17 scheme**. Do not cross-reference an old-scheme ID
against this table without checking which finding it actually names.

---

## 3. Completed Workstreams

### A. Upload Batch A — Storage Architecture

**Status: `FIXED — UNCOMMITTED`** (storage backend/endpoint scope only)

- **Architecture**: self-hosted MinIO in every environment, never AWS S3. `DocumentStorageService`
  (`apps/api/src/hrms/core/storage.py`) now takes two independent endpoint settings —
  `S3_ENDPOINT_URL` (internal, used by `put_object`/`get_object`/`delete_object`) and the new,
  optional `S3_PUBLIC_ENDPOINT_URL` (used only by `presigned_get_url`, falling back to the internal
  endpoint when unset). This solves the real architectural problem that a SigV4 presigned URL's
  signature is computed over the exact host it will be requested against — an internal Docker
  hostname (`http://minio:9000`) can never be handed to a browser.
- **Boot guard**: `Settings._guard_non_development_config` now refuses to boot `staging`/
  `production` when `s3_endpoint_url`, `s3_bucket_documents`, `aws_access_key_id`, or
  `aws_secret_access_key` is falsy — closing the gap where an unset `S3_ENDPOINT_URL` would have
  silently resolved `aioboto3` against real `s3.amazonaws.com`. Verified present in
  `apps/api/src/hrms/core/config/settings.py` (line ~157, `_guard_non_development_config`).
- **MinIO initialization**: `docker-compose.yml` gained a `minio-init` one-shot service
  (`quay.io/minio/mc`) running `mc mb --ignore-existing` + `mc anonymous set none` on every
  `docker compose up` — the bucket previously existed only because a developer had created it by
  hand.
- **Employee-import storage-failure handling**: `EmployeeImportService.process_batch` previously
  called `self._storage.get_object(...)` with no failure handling — a MinIO outage mid-Celery-task
  would crash uncaught and leave the batch stuck at `PROCESSING` forever. Now wrapped in
  `try/except Exception`, marks the batch `FAILED`, commits, and re-raises.
- **Configuration**: `S3_ENDPOINT_URL`, `S3_BUCKET_DOCUMENTS`, `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY` now required outside `development`; `S3_PUBLIC_ENDPOINT_URL` optional
  everywhere. Documented in all five `.env*.example` templates, replacing a previously-wrong "ECS
  task role provides S3 access" comment (no ECS, no IAM role concept on the actual Hostinger VPS
  target).
- **Files changed**: `core/storage.py`, `core/config/settings.py`, `docker-compose.yml`, all five
  `.env*.example` files, `modules/employee_import/service.py`.
- **Tests added**: 8 config tests (`test_settings.py`), 7 storage unit tests (`test_storage.py`), 5
  storage integration tests against real local MinIO (`tests/integration/core/test_storage.py`),
  including a real `docker restart` persistence test (`skipif`-guarded on Docker-in-Docker access —
  degrades to skip, not failure, on a sandboxed runner).
- **Integration testing**: all new tests run against a real local MinIO container, not mocks.
- **Known limitations**: no scoped (non-root) MinIO credentials — still a static root-user key pair
  per environment (flagged as a Batch-B-or-later candidate, not delivered by any batch to date). No
  live Nginx config for the internal/public endpoint split exists in this repository — fully
  specified in the batch's own report but not shipped, since no `nginx.conf` or production compose
  file exists anywhere in the repo to edit. MinIO console (port 9001) exposure is documented but not
  addressed in code.
- **Current status**: `FIXED — UNCOMMITTED`. Verified present in the working tree by direct file
  inspection (`core/crypto/` is a separate workstream — the storage files listed above were
  confirmed to exist and contain the described logic).

### B. Upload Batch B — File Validation

**Status: `FIXED — UNCOMMITTED`**

- **Upload size enforcement**: two independent layers, because FastAPI's own
  `get_request_handler` calls `await request.form()` — fully parsing and spooling the multipart
  body — before any `Depends()` or the route handler itself runs, so an in-route check cannot
  prevent the framework from already having received the full body.
  1. `MaxUploadSizeMiddleware` (new, `hrms/core/uploads.py`) — ASGI-level, checks `Content-Length`
     early when present, and independently tracks bytes read from the ASGI `receive()` channel
     regardless of what the header claimed. On overflow, constructs and sends a `413` response
     directly at the ASGI layer (Starlette's exception-handler middleware sits *inside* user
     middleware, so a raised exception there would otherwise fall through to a generic,
     unstructured 500).
  2. `read_upload_bounded` (same module) — reads the already-admitted `UploadFile` in 1MB chunks,
     defense-in-depth against the application's own in-memory buffer.
  - Ceilings: 12MB (onboarding, = 10MB business limit + multipart overhead headroom), 6MB
    (employee-import, = new 5MB business limit + headroom). The 5MB import ceiling is this batch's
    own engineering decision — no source document named one.
- **This is why middleware, not a FastAPI dependency**: documented directly in the batch report and
  confirmed by reading the installed `fastapi==0.115.6` source — `solve_dependencies` runs only
  after the multipart body is already fully parsed; only ASGI middleware, positioned ahead of
  routing, can reject before that parse.
- **MIME allowlist**: PDF, JPEG, PNG only — **this batch's own engineering decision, not a reviewed
  product/security policy** (no source document names an allowed file-type list). See §13.
- **Magic-byte validation**: `sniff_document_content_type`
  (`hrms/modules/onboarding/document_validation.py`) checks the file's own byte prefix (`%PDF-`,
  `FF D8 FF`, `89 50 4E 47 0D 0A 1A 0A`) — the client's claimed `Content-Type` header is never
  trusted or persisted. A caller claiming one type for bytes that sniff to a different *supported*
  type is silently normalized; unsupported bytes are rejected (422). No `libmagic`/deep structural
  validation — a manual prefix check only.
- **Filename sanitization / safe object keys**: `sanitize_display_filename` and
  `safe_document_object_key` are two independent code paths that never share logic. The object key
  is never derived from the client filename at all (`onboarding/{company_id}/{case_id}/{document_id}/document{ext}`,
  all server-generated UUIDs plus a literal); the display filename (metadata only, stored and shown
  to the reviewer) strips directory components, non-printable characters (including CR/LF —
  closing a response-header-injection vector), and anything outside a small safe-ASCII allowlist.
- **`Content-Disposition: attachment`**: `presigned_get_url` gained an optional
  `response_content_disposition` parameter (S3's `ResponseContentDisposition` override);
  `OnboardingDocumentService.list_documents_with_urls` now forces it on every presigned URL —
  independent of whatever was set at upload time. Verified against real MinIO.
- **Employee-import upload protection**: pre-parse file-size check, fixed non-client-derived object
  key (`employee-imports/{company_id}/{batch_id}/import.csv`).
- **Authorization preservation**: no RBAC/tenant-scoping code touched — pre-existing cross-tenant
  isolation and permission-check tests pass unmodified (only their fixtures moved from fake bytes
  to real magic-byte-valid bytes).
- **Deliberate scope exclusion — explicitly stated, not implemented**:
  ```text
  No AV/malware scanning.
  ```
  Magic-byte validation proves a file's header matches a supported format; it does not scan for
  embedded exploits or malformed-but-signature-valid content. This was out of scope from the
  original audit onward and remains unaddressed by every batch to date.
- **Also not closed**: no structural/deep file validation past the header; no backfill of
  pre-existing unsanitized filenames already in the database (none exist in this repository's own
  data, since there is no production data yet).
- **Files changed**: `core/uploads.py` (new), `modules/onboarding/document_validation.py` (new),
  `app.py`, `core/storage.py`, `modules/onboarding/{service,public_router,exceptions}.py`,
  `modules/employee_import/{service,router,exceptions,schemas}.py`.
- **Tests added**: 34 new unit tests, 15 new integration tests, 10 existing integration tests
  updated (not weakened — fake bytes replaced with real magic-byte-valid fixtures) against real
  MinIO.
- **Current status**: `FIXED — UNCOMMITTED`.

### C. Upload Batch C — Onboarding Upload Rate Limiting

**Status: `FIXED — UNCOMMITTED`**

- **Endpoint protected**: `POST /public/onboarding/{token}/documents` only — the only
  resource-intensive, unauthenticated write surface on that router (other onboarding routes —
  `GET`/`PATCH` sections, `submit`, document list/delete — remain unlimited, out of scope for this
  batch).
- **Dual bucket**: IP bucket (`ratelimit:onboarding_upload:ip:{client_ip}`) and onboarding-token
  bucket (`ratelimit:onboarding_upload:token:{sha256(token)}`) — either tripping rejects the
  request. The raw token is never used as a Redis key or logged, only its SHA-256 hash, because the
  token is itself a bearer credential for that onboarding case.
- **Implemented values** (`app.py` call-site arguments, not settings fields):
  ```text
  30 requests/minute per IP
  10 requests/minute per onboarding token
  60-second window
  ```
  **WAITING FOR POLICY APPROVAL** — these are this batch's own engineering decision (§13). No
  source document names a ceiling for this endpoint. Not changed by this report.
- **Redis / fail-closed behavior**: `OnboardingUploadRateLimitMiddleware` reuses the existing
  Redis client (`_get_client()`) from `shared/rate_limit.py`. A `RedisError` while checking or
  incrementing either bucket is caught **inside the middleware** and answered with a `503
  RATE_LIMITER_UNAVAILABLE` — never a silent pass-through to unlimited uploads. This is a narrow,
  local decision scoped to this one new endpoint only — it does not fix `SEC-11` globally (§14).
  The response body never includes the underlying Redis exception text or connection details.
- **Middleware placement / interaction with trusted-proxy handling**: registered so it executes
  *after* `ProxyHeadersMiddleware` and `TenancyMiddleware` — confirmed order (`app.user_middleware`):
  `ProxyHeadersMiddleware → TenancyMiddleware → OnboardingUploadRateLimitMiddleware →
  MaxUploadSizeMiddleware(import) → MaxUploadSizeMiddleware(onboarding) → CORSMiddleware → router`.
  This is a **functional runtime dependency**, not a textual/diff dependency: the IP bucket reads
  `scope["client"]`, which is only the real client IP once `ProxyHeadersMiddleware` (OPS-02, §5G)
  has already run. Batch C must not be deployed ahead of OPS-02 (§9, §12, §15).
- **No route code changed** — the limiter is ASGI middleware, not a route dependency, for the same
  FastAPI-body-parsing-order reason as Batch B's `MaxUploadSizeMiddleware` (§B above).
- **Files changed**: `shared/rate_limit.py` (new `OnboardingUploadRateLimitMiddleware` class,
  co-located with the existing Redis primitives it reuses), `app.py` (registration),
  `tests/integration/modules/onboarding/conftest.py` (bucket-reset fixture, extended not replaced).
- **Tests added**: 8 unit tests (path/method scoping, Redis-outage fail-closed 503, no leaked
  exception text, missing `scope["client"]` degrades to `"unknown"` rather than crashing), 8
  integration tests against real Redis and real MinIO (token-bucket boundary at exactly 10/11th
  request, MinIO/DB side-effect verification — a rejected upload creates zero objects and zero DB
  rows, window-expiry recovery, one-token-many-IPs, one-IP-many-tokens, two-customer isolation).
- **Current status**: `FIXED — UNCOMMITTED`.

### D. OPS-01 — Production CORS

**Status: `FIXED — UNCOMMITTED`**

- **Previous behavior**: `allow_origins=["*"] if settings.is_development else []` — empty outside
  development (every browser request blocked); the development branch's `["*"]` combined with
  `allow_credentials=True` is itself an invalid, browser-rejected combination.
- **New behavior**: new `Settings.cors_allowed_origins: tuple[str, ...] = ()` field (comma-separated
  string or list, parsed by a `field_validator`), and a new `effective_cors_origins` property —
  returns `cors_allowed_origins` verbatim when set; in `development` only, falls back to
  `[web_app_base_url, "http://localhost:3000"]` — **never** `["*"]`, so `allow_credentials=True`
  stays valid in every environment. Verified present in `settings.py`
  (`cors_allowed_origins: tuple[str, ...] = ()` at line ~71).
- **`CORS_ALLOWED_ORIGINS`**: new environment variable, documented in all five `.env*.example`
  files.
- **Production boot guard**: `_guard_non_development_config` raises at `Settings()` construction —
  i.e. at process boot, before serving any request — if `cors_allowed_origins` is empty for
  `environment != "development"`. Confirmed present (`if not self.cors_allowed_origins:` at line
  ~188 of `settings.py`).
- **Development behavior**: unchanged local workflow — the dev fallback origin list still resolves
  without requiring the operator to set anything.
- **Tests**: `tests/unit/core/test_cors_middleware.py` (4 tests — real `CORSMiddleware`
  preflight/simple-request behavior per environment, untrusted origin rejected with no
  `Access-Control-Allow-Origin` header), plus CORS-specific cases inside `test_settings.py`.
- **Current status**: `FIXED — UNCOMMITTED`, code-level verified.

### E. SEC-01 — JWT Secret Enforcement

**Status: `FIXED — UNCOMMITTED`**

- **Previous default-secret problem**: both `jwt_access_secret`/`jwt_refresh_secret` defaulted to a
  known, repository-committed value that cleared the existing 16-character minimum-length check;
  nothing rejected the default outside development.
- **Production validation**: `_guard_non_development_config` (same function as OPS-01's guard —
  see §11 on the interleaving this causes), for `environment != "development"`:
  - rejects a missing/empty secret;
  - rejects a secret **equal to the known repository default** (explicit string comparison, not
    inferred from length alone);
  - rejects a secret shorter than 32 characters **or** with fewer than 8 distinct characters (an
    entropy floor above the pre-existing length-only check);
  - applies independently to both the access and refresh secrets.
- **Default/weak secret rejection**: confirmed by direct code read.
- **Error messages**: name the field and environment only, never the secret value — a dedicated
  test (`test_rejection_error_never_echoes_the_rejected_secret_value`) asserts this.
- **Development exception**: `development` is exempted entirely — `is_development` short-circuits
  the validator, local workflow with repository defaults is unchanged.
- **Tests**: 18 tests inside `test_settings.py` covering dev/staging/prod × missing/default/weak/
  strong secret combinations and the no-leak-on-error property.
- **No secret rotation/provisioning mechanism was implemented** — this workstream is boot-time
  validation only; it does not generate, store, or rotate a secret for any environment.
- **Current status**: `FIXED — UNCOMMITTED`.

### F. SEC-02 — Credential Rate Limiting

**Status: `FIXED — UNCOMMITTED`**, with one newly-discovered, unrelated bug left open

- **Login protection**: new `rate_limit_by_ip_and_email(bucket, *, limit, window_seconds)` in
  `shared/rate_limit.py` — reuses the same Redis `INCR`/`EXPIRE` sliding-window primitive as the
  pre-existing `rate_limit()`, applied twice per request (IP dimension and the request body's
  `email` field, read via Starlette's cached `request.json()` — no double body consumption).
  Blocks if **either** counter trips. `identity/router.py`: `_login_rate_limit =
  rate_limit_by_ip_and_email("login", limit=10, window_seconds=60)` on `POST /auth/login`.
- **Refresh protection**: `_refresh_rate_limit = rate_limit("token_refresh", limit=10,
  window_seconds=60)` on `POST /auth/token/refresh` — IP-only, since the refresh body carries a
  token, not an email.
- **IP bucket / credential bucket / key construction**: new key shape
  (`ratelimit:{bucket}:ip:{ip}` / `ratelimit:{bucket}:email:{email}`), under new bucket names
  (`"login"`, `"token_refresh"`) that deliberately do **not** share the pre-existing `"auth"` bucket
  used by registration/forgot-password/reset-password/invite-accept — a documented judgment call
  (sharing the bucket would let a burst of legitimate login attempts exhaust the counter
  registration relies on, and vice versa), explicitly flagged as a deviation from the audit's
  literal wording rather than silently made.
- **Redis dependency**: same client, same failure behavior as every pre-existing `rate_limit()`
  consumer (§14 — SEC-11 unchanged for this path).
- **Tests**: 10 integration tests (`test_credential_rate_limit.py` — normal login, IP-bucket trip,
  email-bucket trip, distributed-IP attack, non-cross-blocking, anti-enumeration preserved, refresh
  rate limit, refresh rotation/replay-detection under the limit), 7 unit tests
  (`test_rate_limit_dual_bucket.py`).
- **Newly discovered account-lockout persistence bug — NOT FIXED, follow-up item**:
  `hrms.core.db.session.get_session` rolls back its entire transaction on any exception raised
  during request handling (confirmed by direct read of `core/db/session.py`:
  `await session.commit()` / `except: await session.rollback()`).
  `IdentityRepository.increment_failed_login` (confirmed, `core/db/repositories/identity.py:201`)
  only `flush()`s, never commits, and `IdentityService.login` raises `InvalidCredentialsError` on
  the same request — triggering the rollback and silently discarding the `failed_login_count`
  increment. Six consecutive wrong-password attempts leave `failed_login_count` at `0` and
  `locked_until` at `NULL`; every response is `401`, never the `423 ACCOUNT_LOCKED` the code path is
  written to produce. **Discovered during this batch's regression testing, confirmed present by
  direct code read for this report, not caused by this batch** (none of the three files involved —
  `core/db/session.py`, `identity/service.py`, `core/db/repositories/identity.py` — are touched by
  this round's diff), **and not fixed** — flagged as its own follow-up finding, not folded into
  SEC-02's closure.
- **Current status**: `FIXED — UNCOMMITTED` for the rate-limiting scope of SEC-02; the account
  lockout persistence bug is a separate, `OPEN`, newly-surfaced finding.

### G. OPS-02 — Trusted Proxy Handling

**Status: `FIXED — UNCOMMITTED`**

- **`ProxyHeadersMiddleware`**: from `uvicorn.middleware.proxy_headers` (already a transitive
  dependency via `uvicorn[standard]` — no new package), wired in `app.py` as the **last**
  middleware added via `app.add_middleware`. Starlette builds its middleware stack in reverse
  add-order, so the last-added middleware is outermost and runs first — resolving `scope["client"]`
  before CORS, tenancy, rate limiting, or any route handler's IP read.
- **Trusted proxy configuration**: new `Settings.trusted_proxy_hosts: tuple[str, ...] = ()`
  (comma-separated host/CIDR list, empty by default = nothing trusted). Verified present in
  `settings.py` (`trusted_proxy_hosts: tuple[str, ...] = ()` at line ~78).
- **`TRUSTED_PROXY_HOSTS`**: documented in all five `.env*.example` files.
- **Client-IP resolution**: deliberately **not** a hand-rolled `X-Forwarded-For` parser —
  `ProxyHeadersMiddleware` only trusts a forwarded value when the immediate socket peer is itself
  trusted, and walks a multi-hop chain correctly (neither naive "take first" nor "take last"). This
  is the framework's own, separately-maintained implementation.
- **Interaction with rate limiting**: every IP-keyed bucket (SEC-02's login/refresh, Batch C's
  onboarding-upload) and every audit-logged `ip_address` now transparently benefits, since
  `ProxyHeadersMiddleware` mutates `scope["client"]` before any of those read sites run — no
  individual call site was touched.
- **Why this matters for IP-based security controls**: behind any reverse proxy/load balancer,
  every IP-keyed control (rate limits, audit trails) collapses into one shared value (the proxy's
  own address) without this fix — the exact failure mode the original audit named.
- **Tests**: `test_proxy_headers.py` (7 tests — Cases A-D, multi-hop chain, CIDR support,
  empty-trusted-hosts-never-trusts), `test_proxy_aware_rate_limiting.py` (5 integration tests
  through a probe app wired identically to `app.py`'s real middleware order).
- **Current status**: `FIXED — UNCOMMITTED`.

### H. API-01 — Pagination

**Status: `FIXED — UNCOMMITTED`** for Tier 1 scope

- **Pagination infrastructure**: `apps/api/src/hrms/shared/pagination.py` — `PageParams`,
  `pagination_params` (shared FastAPI `Depends`), `build_pagination_meta`. Every Tier 1 router uses
  the same three symbols.
- **`PaginationMeta` / `ListEnvelope`**: existing types, previously defined with zero usages (the
  original audit's own evidence line); now wired through every Tier 1 endpoint.
- **Contract**: `page` (1-indexed, default 1), `per_page` (`ge=1`, `le=100`, default 25) — invalid
  values 422 via FastAPI validation, never silently clamped. `total` is an exact `COUNT(*)` sharing
  the identical `WHERE` predicates as the data query (extracted into a shared conditions-builder per
  repository so the two can never drift).
- **Tier 1 endpoints** (7, SQL-level `.limit()`/`.offset()`, never a full-scan-then-slice): `GET
  /employees`, `/leave-applications` (+ N+1 fix, below), `/policy-assignments`, `/leave-ledger`,
  `/shifts/{id}/versions`, `/work-calendars/{id}/exceptions`, `/holiday-calendars/{id}/holidays`.
- **N+1 fix**: `LeaveApplicationService.list_applications` previously ran 2 extra queries per row
  (`1 + 2N` for N applications); now 2 flat batch queries (`WHERE leave_application_id IN (...)`)
  regardless of page size — proven, not just asserted, by
  `test_n_plus_one_removed_query_count_bounded`, which asserts a 3-row page and a 12-row page issue
  the identical number of SQL statements via a real `before_cursor_execute` listener.
- **Backend SQL pagination**: authorization (`DataScope`/tenant filtering) resolved **before**
  `LIMIT`/`OFFSET` is applied in every case — proven with a dedicated `BRANCH`-scope +
  pagination combination test (`test_branch_scope_pagination_narrows_before_paging`: an 8-of-13
  visible-employee actor pages through and the 5 outsiders never appear on any page).
- **Frontend changes**: `lib/api/types.ts` gained `PaginationMeta`/`ListEnvelope<T>`;
  `lib/api/client.ts` gained `apiClient.getList<T>()`; new
  `components/common/pagination-controls.tsx` (verified present in the working tree) shared across
  every updated page (`employees`, `leave-applications`, `policy-assignments`, `leave-balances`,
  `shifts/[id]`, `work-calendars/[id]`, `holiday-calendars/[id]`).
- **Integration tests**: `test_employee_pagination.py` (12), `test_leave_application_pagination.py`
  (7), `test_leave_ledger_pagination.py` (3), `test_shift_version_pagination.py` (3),
  `test_workforce_calendar_pagination.py` (6).
- **Unit tests**: `test_pagination.py` (9, the shared contract itself).
- **Explicit scope decision, documented, not silent**:
  ```text
  Tier 2/3 endpoints (branches, departments, designations, shifts-list, grades, holiday
  calendars, weekly-off patterns, leave types/policies/combination rules, statutory
  minimums, legal entities) use a documented safety-limit approach (hardcoded LIMIT 1000
  or left entirely untouched) rather than full pagination.
  ```
  This is stated as a scope decision in the pagination report itself (§2 of that report), reasoned
  as bounded org-config collections with no UI page controls — not an oversight.
- **Known limitation, documented in-code and here — not silently ignored**:
  ```text
  Every reference-data /employees dropdown (manager picker, department-head picker, team
  filter, etc.) now requests per_page=100, the server-enforced maximum, and will silently
  truncate the list for any company with more than 100 employees.
  ```
  A proper fix (a searchable/paginated employee-picker component) is out of scope for API-01 as
  delivered. See §13 for the policy-confirmation recommendation.
- **Current status**: `FIXED — UNCOMMITTED` for the stated Tier 1 scope. Tier 2/3 is not "fully
  paginated" and this report does not describe it that way.

---

## 4. DATA-01 — PII Encryption

**Status: `PARTIAL — NOT CLOSED`.** This finding is not being reported as fixed, closed, or
production-ready under any framing. Confirmed directly against `apps/api/src/hrms/core/crypto/`
(10 files present: `aad.py`, `backfill.py`, `errors.py`, `field.py`, `keys.py`, `kms.py`,
`models.py`, `provisioning.py`, `registry.py`, `service.py`), the migration file
(`alembic/versions/20260927090000_encryption_key_registry.py`), and
`employee/service.py` (confirmed `PiiCryptoService` import and `encrypt_column`/`decrypt_column`
calls at lines 14, 1974, 1980, 2084).

### Implemented

- **Crypto core** (`hrms/core/crypto/`): true envelope encryption — a KMS-wrapped, per-environment
  application data-encrypting key (DEK), AES-256-GCM performed locally against the cached plaintext
  DEK (KMS is called only once per key-version cache-miss, never per field operation).
- **Encryption/decryption services**: implemented as explicit, async service-layer calls
  (`PiiCryptoService.encrypt_column`/`decrypt_column`/`encrypt_jsonb_key`/`decrypt_jsonb_key`) — a
  deliberate, documented deviation from the plan's original `TypeDecorator`-based design (§0a of the
  plan document), made because a column-level `TypeDecorator` has no access to the owning row's
  primary key at bind time (needed for AAD, below) and because DEK resolution is inherently async
  (KMS calls via `aioboto3`) while SQLAlchemy's synchronous ORM hooks cannot `await`. Every decrypt
  call is a visible, grep-able call inside a permission-checked service method — never automatic on
  ORM load.
- **Key registry**: `encryption_keys` table (migration `20260927090000`) — `key_version`,
  `kms_key_arn`, `wrapped_dek` (base64 `CiphertextBlob`, never the plaintext DEK), `status`
  (`ACTIVE`/`RETIRED`), timestamps. Exactly one `ACTIVE` row expected at a time. Old keys are never
  deleted, so historical ciphertext stays decryptable across rotations.
- **Bank-account encryption write path**: `EmployeeBank.account_number_enc` — the one live,
  shipped write path. `EmployeeBankService` calls `encrypt_column` on write and
  `decrypt_account_number`-style helpers on read, always behind an `EMPLOYEE.VIEW_BANKING`-style
  permission check.
- **AAD handling**: mandatory on every encrypt/decrypt call, `table:column:record_id` convention
  (e.g. `employee_bank:account_number_enc:{employee_bank.id}`) — binds ciphertext to its own row so
  a copied/misplaced ciphertext value fails to decrypt under a different row's identity, closing a
  gap plain AEAD tamper-detection alone does not close.
- **Audit redaction**: `hrms/core/audit/redact.py` (`mask_sensitive()`, confirmed present) wired
  into `bank_to_audit_dict()` — audit-log writes for bank changes no longer receive an unredacted
  `BankRead.model_dump()`.
- **Onboarding → employee encryption handoff**: `OnboardingCaseService`/
  `OnboardingActivationService` decrypt the candidate-submitted `bank_info` and re-encrypt into the
  new `EmployeeBank` row under a fresh AAD at activation — verified by a dedicated test
  (`test_onboarding_activation.py`).
- **Tests**: 94 tests across crypto/keys/service/redact/backfill/banking/activation — independently
  re-runnable; not re-executed in full for this report (see §7 for the full-suite figures that
  include them).
- **Migration**: `20260927090000_encryption_key_registry.py` creates only the `encryption_keys`
  table; touches no PII columns. Confirmed single head (§9).
- **Configuration**: `kms_cmk_arn`, `dev_encryption_key`, `encryption_dek_cache_ttl_seconds` —
  confirmed present in `settings.py` (lines ~129, ~133, ~137).
- **Development mode**: a fixed, clearly-fake local key (`Settings.dev_encryption_key`) is used in
  `development` only — structurally incapable of running in staging/production per the same
  boot-guard pattern SEC-01 established for JWT secrets.

### Not completed

```text
KMS CMK has not been provisioned in a real environment.

Historical audit-log remediation has not been implemented.

Onboarding post-activation cleanup has not been implemented.

PAN/Aadhaar encryption has not been implemented.
```

- **KMS CMK provisioning** — `OPERATIONAL PREREQUISITE`. `provision_initial_key()`
  (`core/crypto/provisioning.py`) exists and is tested against a fake KMS (`_FakeKms`), but has
  never been run against real AWS KMS in any environment. The boot guard
  (`_guard_non_development_config`'s `kms_cmk_arn` check, confirmed at line ~222 of `settings.py`)
  refuses to start staging/production without it — correct fail-closed behavior, but it means this
  is a required pre-deploy operator action, not something "done" by landing this code.
- **Historical audit-log remediation** (plan §8) — `WAITING FOR POLICY APPROVAL`. Strategy is fully
  written in the plan document; no remediation script exists in the repository. Explicitly gated on
  product/compliance sign-off that has not happened.
- **Onboarding post-activation cleanup** (plan §9.1) — `WAITING FOR POLICY APPROVAL`. No
  clearing/pop logic exists in `onboarding/service.py`. The retention alternative (plan §9.2) is
  what actually runs today by default: **`onboarding_case.bank_info` and `employee_bank` both
  permanently retain encrypted copies of the same account number** — the same "never clear"
  behavior the original data-flow inventory described, except the retained copy is now encrypted
  rather than plaintext.
- **PAN/Aadhaar encryption** — `NOT STARTED`. `employee.pan_number_enc`/`.aadhaar_number_enc`
  remain unchanged `String` columns with **no service-layer write path** — confirmed by grep: zero
  references to either column name in `employee/service.py` or `employee/repository.py`. The
  encryption/decryption machinery is wired and tested against these two columns directly (unit
  level), but nothing in the application calls it for them. Explicitly out of scope for this batch
  per the plan, not an oversight — but it also means DATA-01 is far from fully closed as a finding.
- **Plan-document inconsistency, reported not corrected**: the implementation plan
  (`DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md`) states in its header:
  `IMPLEMENTATION BATCH 1 COMPLETE — READY FOR REVIEW`, and its "Final position" section (line
  ~1400) describes substantial completion — but its own §18 "Final implementation checklist"
  (lines 1362-1396, 22 items) is **100% unchecked** (`- [ ]` on every line), confirmed by direct
  read. This report does not silently correct that document. It is flagged here as a documented
  disagreement between prose and checklist state, left as-is per this task's own instruction not to
  rewrite history in another document.

### DATA-01 status

```text
PARTIAL — NOT CLOSED
```

Precisely because: (1) no real KMS key has been provisioned in any environment, so staging and
production cannot currently boot with this code active; (2) two compliance-sensitive remediation
decisions (historical audit-log redaction, onboarding-record cleanup vs. retention) are explicitly
unresolved and gated on sign-off that has not happened; (3) two of the four originally-scoped PII
fields (PAN, Aadhaar) have no write path at all; (4) the plan document's own closeout checklist is
unchecked. The crypto infrastructure and the one live write path it protects are real, tested, and
represent genuine progress — but none of the four conditions above can be resolved by more code
alone, and the finding cannot be marked closed while they stand.

---

## 5. Testing Evidence

### Documented baselines (as stated in each dated report)

| Milestone | Source doc | Documented result |
|---|---|---|
| Hardening Batch 1 (CORS/JWT/SEC-02/OPS-02) | `PRODUCTION_HARDENING_BATCH_1_REPORT.md` | Targeted: 50 passed. Full backend: **1303 passed, 1 failed** |
| DATA-01 (PII encryption) | `DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` | No full-suite figure stated; 94 targeted DATA-01 tests (crypto/keys/service/redact/backfill/banking/activation), not independently re-run in full for this report |
| API-01 (pagination) | `API_01_PAGINATION_IMPLEMENTATION_REPORT.md` | Targeted: 40/40 passed. Full backend: **1402 passed, 1 failed** (of 1403). Full frontend `vitest`: **364 passed, 4 failed** (of 368) |
| Upload Batch A | `UPLOAD_BATCH_A_STORAGE_ARCHITECTURE.md` | Unit tests only: **502 pre-existing + 15 new = 517**, all pass. No full-suite figure given in this doc. |
| Upload Batch B | `UPLOAD_BATCH_B_FILE_VALIDATION.md` | **1 failed, 1473 passed** |
| Upload Batch C | `UPLOAD_BATCH_C_RATE_LIMITING.md` | **1 failed, 1489 passed** (= 1473 + 16 new: 8 unit + 8 integration) |

These figures are preserved exactly as documented in each report — no number in this table was
invented or interpolated.

### Independent verification performed for this report

- **Test collection**: `apps/api/.venv/bin/python -m pytest --collect-only -q` (bypassing the
  broken console-script shebangs, §9) reported **1490 tests collected** — exactly matching the
  Batch C report's arithmetic (1489 passed + 1 known-failed = 1490).
- **Full suite re-run**: `apps/api/.venv/bin/python -m pytest -q` was executed independently for
  this report. [Result recorded in §5a below once the run completed — see that subsection for the
  actual pass/fail counts observed in this session, separate from the documented baselines above.]
- **Targeted code verification** (not test execution, direct source inspection): confirmed the
  existence and content of `Settings._guard_non_development_config`, `_parse_comma_separated`,
  `rate_limit()`/`rate_limit_by_ip_and_email()`/`OnboardingUploadRateLimitMiddleware` in
  `rate_limit.py`, all 10 files under `core/crypto/`, `core/uploads.py`, the encryption-key-registry
  migration, `cors_allowed_origins`/`trusted_proxy_hosts`/`kms_cmk_arn`/`dev_encryption_key`/
  `encryption_dek_cache_ttl_seconds`/`s3_public_endpoint_url` fields in `settings.py`, the
  account-lockout rollback path in `core/db/session.py` + `core/db/repositories/identity.py`, the
  absence of any PAN/Aadhaar reference in `employee/service.py`/`repository.py`, and the presence of
  `apps/web/src/components/common/pagination-controls.tsx`.

### 5a. Independent full-suite result (this report's own run)

An independently-triggered `apps/api/.venv/bin/python -m pytest -q` was run against the exact
working tree described throughout this report (bypassing the broken console-script shebangs, §7).
Result:

```text
1 failed, 1489 passed, 1 warning in 287.31s (0:04:47)
```

This is byte-for-byte the same pass/fail split documented in `UPLOAD_BATCH_C_RATE_LIMITING.md`
(§5 table above) and confirms no regression has been introduced beyond that point. The single
failure is, again, `test_registration_success_full_row_graph` — the assertion diff observed in
this run shows the identical three extra/unexpected permission codes named in every prior report:
`SETTINGS.USER.MANAGE`, `EMPLOYEE.INVITE`, `SETTINGS.ROLE.MANAGE` (§6). The one warning is a
pre-existing `StarletteDeprecationWarning` about `httpx`/`starlette.testclient`, unrelated to any
hardening workstream.

**Independent conclusion for this report**: the full backend suite, run fresh against the current
uncommitted working tree, matches every documented baseline exactly. No new failure was introduced
by any workstream described in §3/§4, and no previously-reported failure has changed shape.

---

## 6. Known Pre-Existing Test Failure

```text
test_registration_success_full_row_graph
```

- **Full path**: `tests/integration/modules/organisation/test_registration_flow.py::test_registration_success_full_row_graph`
- **Nature of the failure**: asserts an exact, hardcoded RBAC permission-code set for a freshly
  registered `COMPANY_ADMIN`. The actual seeded set now includes three additional codes
  (`SETTINGS.ROLE.MANAGE`, `SETTINGS.USER.MANAGE`, `EMPLOYEE.INVITE`) that the test's hardcoded
  expectation does not list.
- **Missing RBAC permission codes**: `SETTINGS.ROLE.MANAGE`, `SETTINGS.USER.MANAGE`,
  `EMPLOYEE.INVITE`.
- **Predates the current hardening work**: confirmed pre-existing by the Batch 1 report, which
  reproduced it identically after `git stash`-ing every change in that batch and running against
  the unmodified baseline commit `c3b8cec`.
- **Independently reproduced**: every batch report from Batch 1 onward (Batch A, B, C, API-01, the
  consolidation audit) re-ran the full suite and observed this exact single failure, with no
  variation in which test fails.
- **No new regressions identified**: the consolidation audit's own explicit conclusion, after
  reviewing all eight workstreams: "Confirmed: still exactly this one test, still unrelated to any
  of the 8 workstreams above. No new regressions were found anywhere in this audit."
- **Not fixed by this report or any prior workstream** — every batch's scope discipline explicitly
  excludes RBAC permission changes.

---

## 7. Migration Status

- **Current head**: `20260927090000` (the DATA-01 encryption-key-registry migration) — single head,
  no branching, no conflicts. Confirmed independently for this report: `alembic/versions/` contains
  no other file with `down_revision = None` besides the base revision (`20260803124757_init_schema.py`),
  and the encryption-key-registry migration file is present.
- **Migration history**: linear. Most recent entry before the DATA-01 migration:
  `20260926090000 -> 20260927090000`.
- **Multiple heads**: none found.
- **DATA-01 key-registry migration**: creates only the `encryption_keys` table (fields per §4
  above) and a partial unique index; touches no PII columns — consistent with the plan's Option A
  design (encrypt at the application layer, no column-type change).
- **Environment problem preventing `alembic current` verification**: confirmed independently for
  this report. `apps/api/.venv/bin/alembic` and `.venv/bin/pytest`'s shebang lines both read:
  ```text
  #!/media/varun/varun6/work/staff-spectrum/HRMS/apps/api/.venv/bin/python3
  ```
  — a stale absolute path from a previous mount point (`varun6`); the actual repository now lives
  under `/media/varun/varun8/...`. This makes every `.venv/bin/<console-script>` invocation fail
  outright in this sandbox. **This is a local development-environment problem, not a repository
  defect** — it is fixed by recreating the virtualenv (`uv sync` or equivalent) at its current path,
  not by changing any tracked file. It was worked around for this report by invoking
  `.venv/bin/python -m pytest`/`-m alembic` directly (the `python` binary itself is a valid symlink
  to a real CPython 3.12.12 interpreter, matching `pyproject.toml`'s `requires-python = ">=3.12"` —
  only the generated console-script wrapper files carry the stale path).
- **Distinction maintained**: the repository's migration state (single head, linear history, no
  conflicts) is sound and independently confirmed. The inability to run `alembic current` against a
  live database in this sandbox is a local tooling problem, addressed separately from, and not
  counted against, the repository's actual migration correctness.

---

## 8. Configuration Changes

| Configuration | Workstream | Purpose | Production Requirement | Current Status |
|---|---|---|---|---|
| `CORS_ALLOWED_ORIGINS` | OPS-01 | Comma-separated allowed browser origin list | **Required outside development** — boot fails if empty | Implemented, confirmed in `settings.py` |
| `TRUSTED_PROXY_HOSTS` | OPS-02 | Comma-separated host/CIDR list of the immediate reverse proxy(ies) allowed to set `X-Forwarded-For` | Optional; empty = nothing trusted (safe default) | Implemented, confirmed in `settings.py` |
| `S3_ENDPOINT_URL` | Upload Batch A | Internal MinIO endpoint | **Required outside development** — boot fails if unset | Implemented, pre-existing field now enforced |
| `S3_PUBLIC_ENDPOINT_URL` | Upload Batch A | Browser-facing hostname for presigned GET URLs; falls back to `S3_ENDPOINT_URL` when unset | Optional everywhere | Implemented (new field), confirmed in `storage.py` |
| `S3_BUCKET_DOCUMENTS` | Upload Batch A | Document storage bucket name | **Required outside development** — boot fails if unset | Implemented, pre-existing field now enforced |
| `AWS_ACCESS_KEY_ID` | Upload Batch A | MinIO/S3-compatible static credential | **Required outside development** — boot fails if unset | Implemented, pre-existing field now enforced |
| `AWS_SECRET_ACCESS_KEY` | Upload Batch A | MinIO/S3-compatible static credential | **Required outside development** — boot fails if unset | Implemented, pre-existing field now enforced |
| `KMS_CMK_ARN` | DATA-01 | ARN of the per-environment AWS KMS customer-managed key wrapping the application DEK | **Required outside development** — boot fails if unset or the documentation placeholder | Implemented in code; **no real value exists in any real environment** — operational prerequisite, §4/§13 |
| `DEV_ENCRYPTION_KEY` | DATA-01 | Fixed, obviously-fake local key used only in `development` | Not applicable outside development (structurally rejected by the same guard pattern as JWT secrets) | Implemented, confirmed in `settings.py` |
| `ENCRYPTION_DEK_CACHE_TTL_SECONDS` | DATA-01 | In-process TTL (default 3600s) for cached plaintext DEKs | Optional, has a default | Implemented, confirmed in `settings.py` |

Only settings independently verified present in `apps/api/src/hrms/core/config/settings.py` for
this report are listed above.

---

## 9. Files / Modules Changed

Workstream-based map — see the consolidation audit's §5 for the exhaustive per-file table; this is
a navigational summary, not a line-by-line diff.

```text
Upload A     apps/api/src/hrms/core/storage.py (endpoint-selection half)
             apps/api/src/hrms/modules/employee_import/service.py (storage-outage handling)
             docker-compose.yml (minio-init service)
             apps/api/{.,env/}.env*.example (S3/MinIO block)
             apps/api/tests/{unit,integration}/core/test_storage.py

Upload B     apps/api/src/hrms/core/uploads.py (new)
             apps/api/src/hrms/modules/onboarding/document_validation.py (new)
             apps/api/src/hrms/core/storage.py (response_content_disposition half)
             apps/api/src/hrms/app.py (MaxUploadSizeMiddleware registrations)
             apps/api/src/hrms/modules/onboarding/{service,public_router,exceptions}.py
             apps/api/src/hrms/modules/employee_import/{service,router,exceptions,schemas}.py
             apps/api/tests/unit/core/test_uploads.py, tests/unit/modules/onboarding/test_document_validation.py
             apps/api/tests/integration/modules/{onboarding,employee_import}/test_*_upload_bounds.py

Upload C     apps/api/src/hrms/shared/rate_limit.py (OnboardingUploadRateLimitMiddleware class)
             apps/api/src/hrms/app.py (middleware registration)
             apps/api/tests/integration/modules/onboarding/conftest.py (bucket-reset fixture)
             apps/api/tests/unit/shared/test_onboarding_upload_rate_limit_middleware.py
             apps/api/tests/integration/modules/onboarding/test_onboarding_upload_rate_limit.py

CORS/JWT     apps/api/src/hrms/app.py (CORS origin swap)
             apps/api/src/hrms/core/config/settings.py (cors_allowed_origins, JWT guard portions)
             apps/api/tests/unit/core/test_cors_middleware.py

Proxy/       apps/api/src/hrms/app.py (ProxyHeadersMiddleware registration)
rate limit   apps/api/src/hrms/core/config/settings.py (trusted_proxy_hosts portion)
             apps/api/src/hrms/modules/identity/router.py
             apps/api/src/hrms/shared/rate_limit.py (rate_limit_by_ip_and_email)
             apps/api/tests/conftest.py (login/refresh bucket-reset fixture)
             apps/api/tests/unit/core/test_proxy_headers.py
             apps/api/tests/integration/test_proxy_aware_rate_limiting.py
             apps/api/tests/integration/auth/test_credential_rate_limit.py
             apps/api/tests/unit/shared/test_rate_limit_dual_bucket.py

PII (DATA-01) apps/api/src/hrms/core/crypto/*.py (10 files, new)
             apps/api/src/hrms/core/audit/redact.py (new)
             apps/api/alembic/versions/20260927090000_encryption_key_registry.py (new)
             apps/api/src/hrms/modules/employee/{models,service,schemas}.py
             apps/api/src/hrms/modules/onboarding/{models,schemas,service}.py
             apps/api/src/hrms/core/config/settings.py (kms_cmk_arn/dev_encryption_key/... portion)
             apps/api/tests/integration/modules/employee/test_employee_banking.py
             apps/api/tests/unit/modules/employee/test_employee_bank_service.py
             apps/api/tests/integration/test_pii_encryption_backfill.py
             apps/api/tests/unit/core/test_{crypto_field,crypto_keys,pii_crypto_service,audit_redact}.py

Pagination   apps/api/src/hrms/shared/pagination.py
             apps/api/src/hrms/modules/employee/repository.py, modules/employee/router.py
             apps/api/src/hrms/modules/leave/{repository,router,service}.py
             apps/api/src/hrms/modules/organisation/{repository,router,service}.py
             apps/web/src/lib/api/{client.ts,types.ts}
             apps/web/src/components/common/pagination-controls.tsx (new)
             apps/web/src/app/app/{employees,leave-applications,leave-balances,
                policy-assignments,attendance,overtime,regularizations,rosters,...}/page.tsx
                (27 files total — see consolidation audit §5 for the full list)
             apps/api/tests/integration/modules/{employee,leave,organisation}/test_*_pagination.py
             apps/api/tests/unit/shared/test_pagination.py

Tests        See per-workstream lists above; also apps/api/tests/conftest.py (shared rate-limit
             bucket reset, spans SEC-02 + Batch C)

Documentation docs/audits/UPLOAD_BATCH_{A,B,C}_*.md, API_01_PAGINATION_IMPLEMENTATION_REPORT.md,
             DATA_01_PII_*.md (3 files), PRODUCTION_HARDENING_BATCH_1_REPORT.md,
             PRODUCTION_HARDENING_CONSOLIDATION_AUDIT.md,
             PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.{md,html}

Migrations   apps/api/alembic/versions/20260927090000_encryption_key_registry.py (only new one)
```

---

## 10. Cross-Workstream Dependencies

### Upload C → OPS-02

`OnboardingUploadRateLimitMiddleware`'s IP bucket keys on `scope["client"]`, which is only the real
client IP once `ProxyHeadersMiddleware` (OPS-02) has already resolved it from a trusted proxy's
forwarded headers. This is a **functional, runtime dependency invisible in a text diff** — the two
workstreams touch different files with no textual overlap, but Batch C is only correct at deploy
time if OPS-02 is active in front of it (in the actual middleware order confirmed in §3C, OPS-02's
`ProxyHeadersMiddleware` is already registered before Batch C's middleware). Deploying Batch C
without OPS-02 would key every IP bucket on the reverse proxy's own address, collapsing all
onboarding-upload traffic into one shared counter — the same failure mode OPS-02 itself was written
to fix for login/refresh.

### Upload A ↔ Upload B

Both touch `DocumentStorageService.presigned_get_url` (`apps/api/src/hrms/core/storage.py`) in the
same method body: Batch A added the internal/public endpoint split; Batch B added the
`response_content_disposition` parameter for forced-download headers. These are two independent
reasons for the same hunk to have changed — the file only compiles/type-checks correctly with both
halves present together.

### Settings interleaving

`Settings._guard_non_development_config` (`apps/api/src/hrms/core/config/settings.py`) is a single
function whose body runs, in sequence, unrelated checks for JWT secret strength (SEC-01),
`cors_allowed_origins` non-emptiness (OPS-01), S3/MinIO config completeness (Upload Batch A), and
`kms_cmk_arn` presence (DATA-01) — four workstreams' boot-time validation logic in one contiguous
function, added incrementally across separate work sessions. There is no clean hunk boundary
between these checks. `_parse_comma_separated` is a second, smaller shared function serving both
`cors_allowed_origins` (OPS-01) and `trusted_proxy_hosts` (OPS-02). **This is the one place in the
entire working tree where separating workstreams into independent commits requires manual
hand-editing, not a mechanical `git add -p` split** — confirmed by direct inspection of the function
body for this report.

### Rate limiting

`apps/api/src/hrms/shared/rate_limit.py` holds three genuinely independent implementations with no
shared code path: the pre-existing generic `rate_limit()`, the new `rate_limit_by_ip_and_email()`
(SEC-02), and the new `OnboardingUploadRateLimitMiddleware` class (Upload Batch C). They share a
Redis client (`_get_client()`) but not Redis key namespaces. Critically, **they have different
failure behaviors**: Batch C's middleware fails closed (503) on a Redis outage; every consumer of
the generic `rate_limit()`/`rate_limit_by_ip_and_email()` dependency (login, refresh, registration,
forgot-password, reset-password, invite-accept) has no failure handling at all and will 500 on a
Redis outage — this inconsistency is exactly what SEC-11 (§14) still tracks as open, except for the
one narrow exception Batch C introduced for itself.

---

## 11. Policy Decisions Required

### Upload Batch C

Approval required for:
```text
30 requests/minute per IP
10 requests/minute per onboarding token
```
This batch's own engineering decision (reasoned from the 8 onboarding document categories and a
"comfortably fits legitimate use, bounds abuse" heuristic — see §3C), not a reviewed product/
security policy. Not changed by this report.

### Upload Batch B

Approval required for:
```text
PDF/JPEG/PNG allowlist
```
No source document (plan, schema, or product spec) named an allowed file-type list for onboarding
documents before this batch implemented one. Widening it (HEIC, WebP, TIFF, …) is a product
decision, not an engineering one.

### DATA-01

Approval required for:
```text
Historical audit-log remediation (plan §8) — strategy written, not executed, no sign-off recorded.
Onboarding cleanup vs. retention (plan §9) — retention is what currently runs by default; no
  sign-off recorded authorizing either the cleanup alternative or the retention default itself.
PAN/Aadhaar encryption scope — whether and when a write path should be built at all is itself a
  business decision this report does not make.
```

### API-01

Confirmation recommended for:
```text
100-item employee dropdown ceiling — tenants with >100 employees see a silently truncated
  manager/department-head/team-filter picker. Lower risk than the three DATA-01 items above,
  but nothing in the documentation indicates product sign-off on this specific behavior as
  acceptable in production.
Tier 2/3 pagination scope — the decision to leave branches/departments/designations/shifts-list
  on a hardcoded safety-net LIMIT rather than true pagination is reasoned as a bounded-collection
  judgment call, not confirmed by product.
```

None of these four decisions are made by this report. This report documents that they are open, and
does not change any of the implemented numeric values pending that approval.

---

## 12. Commit Status

**Implemented but uncommitted** — every workstream in §3 and §4 above exists only in the working
tree on top of commit `c3b8cec`. `git status --short` (verified at the start and end of this
report's own work) shows 66 modified tracked files and ~40 untracked new files/directories directly
attributable to these workstreams, plus the pre-existing, unrelated items in §16.

**Recommended commit sequence** (from the consolidation audit's own dependency analysis, §10 above):

```text
1. Upload Batch A       (storage architecture)
2. Upload Batch B       (file validation — depends on Batch A's storage.py hunk)
3. Upload Batch C       (onboarding rate limiting — must not precede OPS-02, see below)
4. CORS + JWT secrets   (OPS-01 + SEC-01 — settings.py requires manual splitting)
5. Proxy handling + credential rate limiting (OPS-02 + SEC-02 — must land at or before Commit 3)
6. PII encryption       (DATA-01 — settings.py requires manual splitting; do not treat as closed
                          once committed, see §4)
7. Pagination           (API-01 — fully independent of 1-6)
```

**Upload Batch C must not precede OPS-02.** This is a runtime correctness requirement, not a
stylistic preference — see §10's cross-workstream dependency note. If Batch C is deployed to any
environment ahead of OPS-02's `ProxyHeadersMiddleware` being active, its IP-based rate limiting
bucket will key on the reverse proxy's address rather than the real client, defeating the control.

**No commit was created by this report.** No commit was created by any part of this documentation
task.

---

## 13. Files That Must Not Be Committed

```text
mavericks-kit.zip   (3,854,339 bytes, repo root, confirmed present, Zip archive)
shirt.png            (1,894,091 bytes, repo root, confirmed present, 1312x1199 PNG)
shorts.png           (1,949,691 bytes, repo root, confirmed present, 1536x1024 PNG)
```

Independently re-confirmed present at the repo root for this report (`ls -la`, `file`). None appear
in any `.gitignore` pattern — a broad `git add -A` would silently include all three. No reference to
any of them exists anywhere in code, tests, or documentation. **Recommendation: confirm with the
user whether these are intentional before any staging operation touches the repo root** — this
report does not stage, remove, or otherwise act on them.

**Additional documentation areas identified as unrelated to this hardening round**, present in the
working tree but out of scope for a "production hardening" commit sequence:

```text
docs/business-rules/policies/*
```
Pre-existing Attendance/Leave policy business-rules documentation (the canonical policy-baseline
doc referenced elsewhere in this project's records). Not touched by, or related to, any of the eight
hardening workstreams in §3/§4 — bundling it into a hardening commit would misrepresent what that
commit contains.

```text
docs/business-rules/attendance/ATTENDANCE_TIMEZONE_DECISION_REGISTER.md
docs/business-rules/attendance/ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md
docs/modules/employee/41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md
```
Documentation for already-committed baseline work (attendance/timezone remediation, RBAC/
account-provisioning plan) that landed in commits at or before `c3b8cec` but whose own docs were
never committed alongside them. Legitimate, but belongs with that already-landed work, not this
hardening sequence.

---

## 14. Not Yet Implemented

| Finding | Status | Why Still Open | Recommended Future Work |
|---|---|---|---|
| SEC-05 security headers | OPEN | Not touched by any workstream in this round | Add CSP, HSTS, `X-Content-Type-Options`, frame-options, referrer policy to both apps |
| SEC-06 refresh cookie | OPEN | Not touched | Move refresh token from `localStorage` to an HttpOnly cookie; depends on SEC-05's CSP for full benefit |
| SEC-07 password-reset session revocation | OPEN | Not touched | Revoke existing sessions/refresh families on password reset |
| SEC-08 invite authentication | OPEN | Not touched | Require a real password check before an invite acceptance attaches a session to an existing account |
| SEC-09 email verification | OPEN | Not touched | Hold new companies in a pending state until the admin address is confirmed |
| DEP-01 JWT dependency | OPEN | Not touched | Migrate off unmaintained `python-jose`; add CI dependency scanning |
| SEC-11 Redis failure policy | **PARTIAL / MOSTLY OPEN** | Only Batch C's own new onboarding-upload limiter fails closed (503); every pre-existing `Depends()`-based limiter (login, refresh, registration, forgot-password, reset-password, invite-accept) still has no failure policy at all and will 500 on a Redis outage | Define and implement a global Redis-failure policy for the shared `rate_limit()`/`rate_limit_by_ip_and_email()` primitives, using Batch C's fail-closed pattern as a template; decide whether the coarse shared `"auth"` bucket should be split |
| Account-lockout persistence bug (new, unnumbered) | OPEN | Discovered during SEC-02 regression testing; explicitly out of that batch's scope (would require changing session/transaction-commit semantics in `identity/service.py`) | Fix the rollback-discards-`failed_login_count` bug in `core/db/session.py`/`identity/service.py`/`core/db/repositories/identity.py` before crediting account lockout as a working mitigant |
| OBS-01 error tracking | OPEN | Not touched | Wire a real error-tracking service (e.g. Sentry) into the 500 handler |
| OBS-02 request logging | OPEN | Not touched | Emit structured request access logs using the already-configured `structlog` |
| OPS-03 readiness | OPEN | Not touched | Split liveness/readiness; make the health check Redis-aware instead of reporting `"skipped"` |
| OPS-04 API container | OPEN | Not touched | Non-root user, `HEALTHCHECK`, `gunicorn` (already a declared but unused dependency) |
| OPS-05 web container/build | OPEN | Not touched | Add a Dockerfile/build step for the web app; make CI run `next build` |
| QA-01 frontend lint | OPEN | Not touched | Add an ESLint configuration and wire it into CI in place of/alongside `tsc --noEmit` |
| SEC-10 password/MFA | OPEN | Not touched | Strengthen password policy, add breach-list/history/rotation checks, add MFA |
| AUD-01 audit coverage | OPEN | Not touched | Add audit records for `employee_import` bulk mutations and credential changes |
| PAN/Aadhaar encryption | NOT STARTED | See §4 — machinery exists, no write path | Build the service-layer write path once a product decision on scope/timing is made |
| Historical audit-log PII remediation | WAITING FOR POLICY APPROVAL | See §4/§11 | Execute the already-documented strategy once sign-off is obtained |
| Onboarding post-activation cleanup | WAITING FOR POLICY APPROVAL | See §4/§11 | Enable §9.1's clearing logic once sign-off is obtained, or formally ratify §9.2's retention default |
| KMS CMK provisioning | OPERATIONAL PREREQUISITE | See §4 | Provision one CMK per environment before any non-development boot is attempted |
| OPS-06 unconditional API docs exposure | OPEN (surfaced, not in original 22-ID list) | Not touched by any workstream | Gate `/docs`/`/redoc`/`/openapi.json` behind environment or auth |

---

## 15. Commit Status Recap

See §12 for the full recommended sequence and the hard OPS-02-before-Batch-C ordering constraint.
Nothing in this working tree has been committed as part of this report or any prior step described
in it.

---

## 16. Files That Must Not Be Committed (recap)

See §13 for the full list and reasoning: `mavericks-kit.zip`, `shirt.png`, `shorts.png` (unrelated,
unreferenced, root-level), plus `docs/business-rules/policies/*` and the two already-committed-
baseline documentation directories (legitimate but out of scope for a hardening-specific commit
sequence).

---

## 17. Production Readiness Gate

```text
PRODUCTION READINESS: NOT READY
```

### Security blockers

- `DATA-01` PII encryption is partial — no KMS key provisioned in any real environment; PAN/Aadhaar
  have no write path at all.
- `SEC-05` (no security headers), `SEC-06` (refresh token in `localStorage`, no CSP), `SEC-07`
  (password reset doesn't revoke sessions), `SEC-08` (invite acceptance skips password check for
  existing accounts), `SEC-09` (no email verification) are all fully `OPEN`.
- `SEC-11` (Redis rate-limiter failure policy) is mostly `OPEN` — most credential/account endpoints
  will 500, not fail closed or fail open by design, on a Redis outage.
- The newly-discovered account-lockout persistence bug means per-account lockout does not currently
  function as a mitigant, despite existing code that appears to implement it.
- `DEP-01` — JWT signing still depends on an unmaintained library with published CVEs.

### Data/privacy blockers

- Historical `audit_log` rows (if any exist in a real environment) remain plaintext pending a
  remediation decision that has not been made.
- `onboarding_case.bank_info` permanently retains an encrypted (not cleared) copy of bank account
  data post-activation, pending a retention-vs-cleanup policy decision.
- PAN and Aadhaar numbers have no encryption write path — if any real tenant has ever written to
  those columns, they remain plaintext today (inventory reports zero writers to date, but this has
  not been independently re-verified against a real production database, since none exists).

### Reliability/operations blockers

- `OBS-01` (exceptions swallowed, no error tracking), `OBS-02` (no request logging/metrics/tracing),
  `OPS-03` (no readiness/liveness split, Redis health "skipped") are all `OPEN`.

### Deployment blockers

- `OPS-04` (API container runs as root, no `HEALTHCHECK`) and `OPS-05` (no web container or build
  pipeline; CI never runs `next build`) are both `OPEN`.
- Upload Batch A's storage architecture requires a live Nginx configuration fronting MinIO's
  internal/public endpoint split that does not exist anywhere in this repository — documented and
  specified, not deployed.

### QA blockers

- `QA-01` — no ESLint configuration for the 45k-line web app; CI substitutes `tsc --noEmit` only.
- The pre-existing `test_registration_success_full_row_graph` failure (§6) should be resolved before
  any release process that gates on a fully-green suite, even though it is unrelated to this round's
  work.

### Policy/approval blockers

- All four items in §11 (Upload Batch C's rate-limit thresholds, Upload Batch B's MIME allowlist,
  DATA-01's two deferred remediation decisions plus PAN/Aadhaar scope, API-01's dropdown-truncation
  and Tier 2/3 scope) require an explicit product/security sign-off this report does not and cannot
  provide.

### Operational prerequisites

- KMS CMK provisioning, per environment, before DATA-01's boot guard will allow staging/production
  to start at all.
- A rehearsed application-level DEK rotation in a real (non-development) environment has never been
  performed.
- A staging rehearsal of the full DATA-01 backfill sequence against a real KMS CMK has never been
  performed (only `environment=development`'s local-key path and registry/rotation logic against a
  fake KMS have been exercised).

No overall score or "percent ready" figure is given. None of the above is minimized: several items
in each category are launch-blocking on their own.

---

## 18. Next Steps

Ordered roadmap, supported by findings documented above and in the source audits. Not performed by
this report.

```text
1.  Prepare clean commit boundaries for the eight workstreams currently sitting uncommitted
    in the working tree (§12).
2.  Resolve settings.py's interleaving — manually split _guard_non_development_config and
    _parse_comma_separated (§10) before attempting the CORS/JWT, proxy/credential-rate-limit,
    or PII-encryption commits, since this is the one file that resists a mechanical git add -p
    split.
3.  Commit the audited, completed workstreams in the dependency-respecting order in §12
    (Upload A → B → C-with-OPS-02 → CORS/JWT → Proxy/SEC-02 → DATA-01 → Pagination).
4.  Resolve DATA-01's operational and policy prerequisites: provision a real KMS CMK per
    environment; obtain sign-off on historical audit-log remediation and onboarding
    cleanup-vs-retention; decide PAN/Aadhaar encryption scope and timing (§4, §11).
5.  Implement the remaining P1 security findings not touched by this round: SEC-05 through
    SEC-09, DEP-01 (§14).
6.  Implement a global Redis failure policy for the shared rate-limiter primitives, closing
    SEC-11 for every endpoint, not just Upload Batch C's new one (§10, §14).
7.  Implement observability: OBS-01 (error tracking), OBS-02 (request logging/metrics/tracing).
8.  Harden containers, readiness probes, and deployment: OPS-03, OPS-04, OPS-05, plus the
    Nginx configuration Upload Batch A specified but did not deploy.
9.  Add frontend lint (QA-01) and close the CI build-verification gap it's part of.
10. Commission a final production readiness audit once the above land, re-verifying every
    finding in §2 against the then-current codebase rather than reusing this report's findings.
```

---

## 19. Reporting Rules Followed

This report used exact statuses throughout (`FIXED`, `FIXED — UNCOMMITTED`, `PARTIAL`, `OPEN`,
`NOT STARTED`, `WAITING FOR POLICY APPROVAL`, `OPERATIONAL PREREQUISITE`, `KNOWN LIMITATION`,
`PRE-EXISTING FAILURE`) and did not use vague completion language (no "mostly secure," "almost
production ready," or percentage claims) anywhere a specific source did not already state one. Where
documentation and code were found to disagree (DATA-01's plan-document checklist vs. its own prose,
§4), the disagreement is reported, not silently resolved. Every test-count figure in §5 is quoted
exactly as it appears in its source document; no number was invented or interpolated. No security
finding is described as closed on the basis of code existing alone — DATA-01, SEC-11, and the
account-lockout bug are the clearest examples of "code exists, finding is not closed."

---

## 20. Final Verification

```bash
git status --short   # confirmed clean of any change made by this report — this file is the
                      # only new path this task introduced
git diff --check      # not run against a diff this task did not create
```

This report is the sole artifact created by this task. No source file, test, configuration, or
migration was modified. No file was staged. No commit was created.

**Final status:**

```text
NOT READY FOR PRODUCTION
```
