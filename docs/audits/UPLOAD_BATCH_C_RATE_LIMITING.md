# Upload Security Batch C — Onboarding Rate Limiting

## 1. Objective

Close SEC-03's still-open half — no rate limiting on the public, unauthenticated onboarding
document-upload endpoint — without redoing Batch A (self-hosted MinIO, private bucket, dual
internal/public endpoints) or Batch B (bounded upload handling, size enforcement, MIME/magic-byte
validation, safe object keys, filename sanitization, forced attachment downloads), and without
expanding into SEC-11's broader global rate-limiter failure policy, OPS-02's proxy architecture
(already resolved — see §6), login/refresh throttling, PII encryption, pagination, JWT secrets,
CORS, email verification, password reset, RBAC, attendance/timezone, or payroll.

## 2. Findings Addressed

| Finding | Description |
| --- | --- |
| SEC-03 (rate-limiting half) | `POST /public/onboarding/{token}/documents` is reachable without authentication and, even after Batch B's size caps, had no bound on request *volume* — an attacker could repeat valid-sized uploads indefinitely, consuming API worker/CPU/memory, MinIO storage and bandwidth, database rows, and network bandwidth. Batch B's own §15 named this explicitly as not closed by that batch. |
| SEC-11 (boundary only) | Not fixed globally — see §7. A new, explicit, *local* failure policy was added for this one new endpoint's limiter; the existing `rate_limit`/`rate_limit_by_ip_and_email` dependencies used by login/refresh/registration/invite-accept are untouched and remain subject to SEC-11 as originally described (Redis down → unhandled exception → 500). |
| OPS-02 | Not new work in this batch — `ProxyHeadersMiddleware` + `Settings.trusted_proxy_hosts` were already implemented and wired in `app.py` before this batch started (git history/working tree at the time this batch began). This batch's new middleware reuses the already-resolved `scope["client"]`; see §6. |

## 3. Existing Rate-Limit Architecture

`hrms/shared/rate_limit.py` provides two `Depends()` factories used across the identity,
account-invite, and organisation-registration routers, both `Depends()`-based per-endpoint
buckets keyed on client IP (and, for credential endpoints, an additional identity dimension):

| Endpoint | Auth | Limit | Key | Redis dependency | Failure behaviour |
| --- | --- | --- | --- | --- | --- |
| `POST /auth/login` | none | 10/60s | IP **and** email (dual bucket, either trips it) | yes | Redis down → unhandled `RedisError` propagates → generic 500 (SEC-11, unchanged) |
| `POST /auth/token/refresh` | refresh token in body/cookie | 10/60s | IP only | yes | same as above |
| `POST /auth/password/forgot` | none | 10/60s, **shared `"auth"` bucket** | IP only | yes | same as above |
| `POST /auth/password/reset` | none | 10/60s, shared `"auth"` bucket | IP only | yes | same as above |
| `POST /account-invite/.../accept` | invite token | 10/60s, shared `"auth"` bucket | IP only | yes | same as above |
| `POST /companies/register` | none | 10/60s, shared `"auth"` bucket | IP only | yes | same as above |
| `POST /public/onboarding/{token}/documents` | onboarding token (public) | **none, before this batch** | n/a | n/a | n/a |
| every other public onboarding route (`GET`/`PATCH .../sections`, `POST .../submit`, `GET`/`DELETE .../documents`) | onboarding token (public) | none | n/a | n/a | out of scope — not a resource-intensive write surface named by SEC-03 |
| every authenticated route | JWT + RBAC | none | n/a | n/a | out of scope |

Registration, password forgot/reset, and invite-acceptance intentionally share one `"auth"` Redis
bucket namespace (`ratelimit:auth:{ip}`) — a pre-existing, documented coarseness (SEC-11's own
finding text), unchanged by this batch. Login and refresh each have their own bucket instead,
per the SEC-02 rationale already in `identity/router.py`.

## 4. Selected Rate-Limit Policy

No source document (this repository's audits, the onboarding module plan, or the Batch A/B
reports) names a request-rate ceiling for the onboarding upload endpoint — Batch B's own §15
explicitly flagged this as open, not silently deferred. **This batch's own engineering decision,
requiring product/security sign-off before being treated as approved policy:**

- **30 requests / 60 seconds per client IP**
- **10 requests / 60 seconds per onboarding token**

Reasoning: `ONBOARDING_DOCUMENT_TYPES` enumerates 8 categories (`PHOTO`, `PAN`, `AADHAAR`,
`ADDRESS_PROOF`, `EDUCATION_CERTIFICATE`, `PREVIOUS_EMPLOYMENT_PROOF`, `BANK_PROOF`, `OTHER`); a
real candidate uploading all 8 with headroom for a couple of retries (wrong file picked, a
size/MIME rejection, a flaky mobile connection) comfortably fits under 10/minute for one case,
matching the existing project convention of "10/min" for other public, unauthenticated,
account-affecting endpoints (`identity/router.py`'s own `_password_rate_limit`/`_login_rate_limit`
comments). The IP bucket is set higher (30, not 10) specifically to avoid the failure mode named
in the task brief: several legitimate candidates completing onboarding concurrently from one
shared NAT/office network/mobile carrier must not collide into one exhausted counter — 30/min
gives headroom for roughly three concurrent onboarding sessions from one IP while still bounding
a single attacker's raw request rate regardless of how many tokens (real or guessed) it cycles
through.

`Settings.rate_limit_window_ms`/`Settings.rate_limit_max` (declared in `core/config/settings.py`)
were checked and confirmed dead — never read anywhere in the codebase — and were not repurposed
for this batch's own constants, to avoid quietly changing the meaning of an existing (if unused)
setting.

## 5. Rate-Limit Key

Dual bucket, same structural rationale as `rate_limit_by_ip_and_email` (SEC-02):

- **IP bucket** (`ratelimit:onboarding_upload:ip:{client_ip}`) — bounds one source hammering the
  endpoint regardless of which token it sends, including garbage/guessed tokens that never
  resolve to a real case.
- **Token bucket** (`ratelimit:onboarding_upload:token:{sha256(token)}`) — bounds the worst-case
  request volume against *one* onboarding case regardless of how many source IPs it's spread
  across (the botnet-against-one-known-link scenario). The raw token is never used as a Redis key
  or logged; only its SHA-256 hash is, because the token is itself a bearer credential for that
  case (`get_onboarding_case_from_token`'s own docstring).

Either bucket tripping rejects the request — same "OR" semantics as the login dual bucket.
Client-supplied identity headers (`X-Forwarded-For` etc.) are never trusted directly; the IP used
is whatever `scope["client"]` resolves to *after* `ProxyHeadersMiddleware` has already run (§6).

## 6. Trusted Client IP Handling

**Not new work in this batch.** `ProxyHeadersMiddleware` (from `uvicorn.middleware.proxy_headers`)
and `Settings.trusted_proxy_hosts` were already present in `app.py`/`settings.py` when this batch
started, added as OPS-02's own remediation, and already covered by
`tests/integration/test_proxy_aware_rate_limiting.py` (direct-untrusted-request,
trusted-proxy-uses-forwarded-ip, untrusted-proxy-ignored, two-clients-behind-one-proxy-get-
independent-buckets, and the OPS-02-bug negative control). `OnboardingUploadRateLimitMiddleware`
is registered so that it executes *after* `ProxyHeadersMiddleware` and `TenancyMiddleware` in the
actual request path (`app.user_middleware` order, confirmed by inspection:
`ProxyHeadersMiddleware → TenancyMiddleware → OnboardingUploadRateLimitMiddleware →
MaxUploadSizeMiddleware(import) → MaxUploadSizeMiddleware(onboarding) → CORSMiddleware → router`)
— it reads `scope["client"]` only once OPS-02's own resolution has already happened, the same
precondition `MaxUploadSizeMiddleware` and the existing `Depends()` limiters already rely on. No
proxy-architecture changes were made in this batch.

## 7. Redis Failure Policy

**Explicit, local decision — scoped to this one new endpoint only, not a SEC-11 fix.** SEC-11
itself (the existing `Depends()`-based limiters having no failure policy at all — an unhandled
`RedisError` reaching the generic 500 handler) remains open and unchanged; fixing it project-wide
was out of scope per the task brief's own instruction to stop and report rather than silently
redesign the shared limiter.

For `OnboardingUploadRateLimitMiddleware` specifically: a Redis outage **fails closed** —
`RedisError` raised while checking/incrementing either bucket is caught inside the middleware and
answered with a `503 RATE_LIMITER_UNAVAILABLE`, never a silent pass-through to unlimited uploads.
Rationale: the entire purpose of this control is DoS/abuse resistance on a public, unauthenticated,
resource-consuming endpoint; fail-open would silently remove that protection at exactly the moment
(a Redis outage, possibly attacker-induced) it matters most. The blast radius is deliberately
narrow — the failure is caught inside this one middleware, scoped by its own path/method match, so
a Redis outage makes only this one route unavailable; every other endpoint (including the rest of
the onboarding module — `GET`/`PATCH` sections, `submit`, document list/delete) is unaffected, and
the rest of the HRMS does not go down. The response body never includes the underlying Redis
exception text, connection details, or internal key names (`tests/unit/shared/
test_onboarding_upload_rate_limit_middleware.py::TestRedisFailurePolicy` asserts this directly).

## 8. Endpoint Changes

No route code changed. `hrms/modules/onboarding/public_router.py` is untouched — the limiter is
ASGI middleware, not a route dependency (§9 explains why), so it needed no wiring inside the
router itself. The only production code changes are:

- **New:** `OnboardingUploadRateLimitMiddleware` in `hrms/shared/rate_limit.py` (co-located with
  the existing Redis client/rate-limit primitives it reuses — `_get_client()` — rather than a new
  module).
- **Modified:** `hrms/app.py` — imports and registers the new middleware, positioned so it
  executes after `ProxyHeadersMiddleware`/`TenancyMiddleware` and before both
  `MaxUploadSizeMiddleware` registrations, CORS, and routing.

## 9. Request Processing Order

FastAPI's own `get_request_handler` (`fastapi/routing.py`, verified by reading the installed
`fastapi==0.115.6` source directly) calls `body = await request.form()` — fully parsing and
spooling the multipart body — **before** `solve_dependencies` runs at all. This means a
`Depends()`-based limiter, no matter where it appears in a route's parameter list, cannot reject a
request ahead of the multipart parse; it is exactly the constraint Batch B's own
`hrms/core/uploads.py` docstring already documents, which is why `MaxUploadSizeMiddleware` exists
as ASGI middleware rather than a dependency. The same constraint applies here, so
`OnboardingUploadRateLimitMiddleware` is likewise ASGI middleware, not a dependency — this is a
documented framework behaviour, not a design preference.

Actual order for a request to `POST /v1/public/onboarding/{token}/documents`:

```
HTTP request
    ↓
ProxyHeadersMiddleware       — resolves scope["client"] from X-Forwarded-For iff trusted (OPS-02)
    ↓
TenancyMiddleware            — sets X-Request-Id/company GUC (unrelated, pre-existing)
    ↓
OnboardingUploadRateLimitMiddleware   — path+method match, dual-bucket check, 429/503 if tripped
    ↓                                   (rejection here: zero bytes of the body have been read)
MaxUploadSizeMiddleware (onboarding)  — Content-Length/streaming size cap, 413 if tripped
    ↓
CORSMiddleware
    ↓
FastAPI routing + solve_dependencies  — this is where `await request.form()` actually runs
    ↓                                   (multipart body fully parsed/spooled here, bounded to the
    ↓                                   12MB MaxUploadSizeMiddleware ceiling regardless of the
    ↓                                   rate-limit or size outcome above)
get_onboarding_case_from_token dependency  — DB query resolving the token
    ↓
route handler → read_upload_bounded → magic-byte sniffing → MinIO put_object → DB insert
```

A rate-limited or Redis-unavailable request is rejected at the `OnboardingUploadRateLimitMiddleware`
step — before any bytes of the request body are read, before FastAPI routing/DI, before the token
is ever resolved against the database, before magic-byte sniffing, before any MinIO or database
call. It is *not* rejected before Starlette's own multipart parser would eventually run for a
request that got past this middleware (it never does, for a blocked one) — that parser is what
`MaxUploadSizeMiddleware` already bounds to a fixed ceiling regardless, so this batch introduces no
new unbounded-body risk.

## 10. Abuse Scenarios

All verified with real Redis (no mocking of the counters — mocking is used only for the Redis
*outage* case, §7):

- Below/exactly at/one request past both the IP and the token limit.
- Window expiration and recovery (integration test forces expiry by deleting the Redis keys
  rather than sleeping 60s; the unit-level dual-bucket window-recovery behaviour for the existing
  `rate_limit`/`rate_limit_by_ip_and_email` primitives was already covered pre-Batch-C).
- One IP spraying many different (never-resolved) garbage tokens — caught by the IP bucket alone.
- One token hammered from many different source IPs (simulated botnet) — caught by the token
  bucket alone.
- Different IPs get independent IP buckets; different tokens get independent token buckets.
- Two separate customers (different companies, different onboarding tokens, different simulated
  IPs) uploading concurrently do not share either bucket.
- 10 and 20 rapid requests, and repeated valid uploads, are all covered by the boundary tests
  above at the actual configured limits (10 token / 30 IP) rather than arbitrary smaller numbers,
  so the tests exercise the real production configuration.

## 11. MinIO Verification

`test_no_minio_object_or_document_row_created_for_the_rejected_upload` uploads to the token
limit (10, all succeed and each creates one object + one `onboarding_document` row), records the
object count under that case's S3 prefix, sends one more (rejected, 429), and asserts both the S3
object count and the document list (`GET .../documents`, still exactly 10) are unchanged. Combined
with Batch B's own unchanged size/MIME rejection-produces-no-object tests (re-run, still passing,
§13), the full expected matrix holds: allowed upload → exactly one object; 429 → no object; 413/422
(oversized/invalid-MIME) → no object, unchanged from Batch B.

## 12. Tests

**New (24 total):**

- `apps/api/tests/unit/shared/test_onboarding_upload_rate_limit_middleware.py` (8 tests) — path/
  method scoping (GET, DELETE, unrelated routes, non-HTTP scope all pass through untouched),
  Redis-outage fail-closed 503 with no leaked exception text and the standard error envelope
  shape, the raw token never appearing in a rejected response body, and a missing `scope["client"]`
  degrading to an `"unknown"` bucket rather than crashing.
- `apps/api/tests/integration/modules/onboarding/test_onboarding_upload_rate_limit.py` (8 tests)
  — real end-to-end behaviour against the real mounted route, real Redis, real MinIO: token-bucket
  boundary (10 succeed, 11th is 429 with a `Retry-After` header), the MinIO/DB side-effect check
  (§11), window-expiry recovery, one-token-many-IPs, one-IP-many-tokens, independent-IP-buckets,
  and the two-customer isolation scenario.

Both new files register an autouse fixture (`tests/integration/modules/onboarding/conftest.py`,
extended, not replaced) that clears `ratelimit:onboarding_upload:*` keys before and after every
test in that directory — the same convention already used there for the registration bucket
(`_reset_registration_rate_limit`) and at the top-level `conftest.py` for login/refresh — because
every test in the directory shares one `ASGITransport` client IP by default and would otherwise
exhaust the new bucket well before any test intends to exercise the limit itself.

## 13. Regression Results

```
apps/api $ .venv/bin/python -m pytest -q
1 failed, 1489 passed in 291.84s (0:04:51)
```

The one failure is the same one named in the Batch B baseline:
`tests/integration/modules/organisation/test_registration_flow.py::
test_registration_success_full_row_graph` — an RBAC default-permission-set seeding drift
(`SETTINGS.ROLE.MANAGE`, `SETTINGS.USER.MANAGE`, `EMPLOYEE.INVITE` present but not expected by the
test's hardcoded set). Not touched by any file in this batch (§8), not a rate-limiting or upload
test, and pre-existing per Batch B's own §14. **Classification: PRE-EXISTING, not a Batch C
regression.**

1489 = Batch B's baseline 1473 passed + this batch's 16 new tests (8 unit + 8 integration).

`ruff check` and `mypy` were run against every file this batch touched
(`hrms/shared/rate_limit.py`, `hrms/app.py`, both new test files, the extended onboarding
`conftest.py`) — both clean, zero errors/warnings.

All of Batch A's and Batch B's own tests were re-run as part of the full suite above and pass
unmodified — `tests/integration/core/test_storage.py` (MinIO restart/persistence),
`tests/integration/modules/onboarding/test_onboarding_documents.py` and
`test_onboarding_upload_bounds.py` (size/MIME/filename matrix, admin document access, cross-tenant
isolation), `tests/integration/modules/employee_import/*` (bulk import, its own upload bounds), and
the full SEC-02/OPS-02 suites (`tests/integration/auth/test_credential_rate_limit.py`,
`tests/integration/test_proxy_aware_rate_limiting.py`,
`tests/integration/modules/organisation/test_registration_rate_limit.py`) — none of which this
batch modified.

## 14. Remaining Findings

Explicitly **not** closed by this batch — reported, not silently fixed, per the task's own scope
discipline:

- **Finding:** SEC-11's global rate-limiter failure policy (the existing `Depends()`-based
  `rate_limit`/`rate_limit_by_ip_and_email` used by login, refresh, registration, password
  forgot/reset, and invite-acceptance still have no failure handling at all — a Redis outage
  raises an unhandled `RedisError` that reaches the generic 500 handler).
  **Why it matters:** an unhandled 500 is worse than either a clean fail-open or fail-closed
  decision — it's an unstructured error response and, if the resulting exception path has any
  side effects before the limiter's own increment, an unreviewed one.
  **Why it is outside Batch C:** this batch's brief explicitly scoped it to closing the
  onboarding-upload rate-limit gap and instructed stopping rather than redesigning the shared
  limiter; the fix here (a new, separate middleware with its own local policy) does not touch or
  require touching the existing dependency's behaviour.
  **Recommended next batch:** give `rate_limit`/`rate_limit_by_ip_and_email` an explicit,
  documented failure policy (this batch's fail-closed-with-503 pattern is a reasonable template)
  and decide whether the coarse shared `"auth"` bucket (registration/forgot/reset/invite-accept)
  should be split, as SEC-11's own text separately suggests.
- **Finding:** the onboarding upload rate limit (30 IP / 10 token per 60s) is this batch's own
  engineering decision, not a reviewed product/security policy.
  **Why it matters:** too tight breaks legitimate onboarding (retries, shared-NAT candidates);
  too loose doesn't meaningfully bound abuse.
  **Why it is outside Batch C:** setting business/security policy numbers is a product/security
  sign-off decision, not an engineering one — §4 states this explicitly rather than asserting the
  numbers are already approved.
  **Recommended next batch:** confirm or adjust these two numbers with product/security once real
  onboarding traffic patterns exist.
- **Finding:** no malware/AV scanning, no deep/structural file validation, no scoped (non-root)
  MinIO credentials, no backfill of pre-existing unsanitized filenames.
  **Why it matters:** unchanged from Batch B's own §15 — restated here only so this report doesn't
  imply they were closed.
  **Why it is outside Batch C:** this batch is rate-limiting only; none of these are rate-limiting
  concerns.
  **Recommended next batch:** Batch B's own §15 already names these as the next upload-hardening
  items.

## 15. Production Status

```
Public onboarding rate limiting: PASS
429 behaviour: PASS
Rate-limit key security: PASS
Trusted IP handling: PASS (reused, not new — OPS-02 already resolved)
Redis failure policy: PASS (local, fail-closed decision for this endpoint only — SEC-11's
                             global policy remains BLOCKED/open, unchanged, reported above)
MinIO side effects: PASS
Authorization regression: PASS

Batch A:  PASS (unchanged, re-verified)
Batch B:  PASS (unchanged, re-verified)
Batch C:  PASS

Overall upload security:  NOT READY FOR PRODUCTION

  - SEC-03 is now closed in full (size/content, Batch B; rate limiting, this batch).
  - SEC-11's global rate-limiter failure policy remains open (§14) — this batch closed it only
    for the one new endpoint it added, not for the pre-existing login/refresh/registration/
    invite-accept limiters.
  - No malware/AV scanning, no scoped (non-root) MinIO credentials, no backfill of pre-existing
    unsanitized filenames (Batch B §15, restated §14 above) remain open.
  - This batch does not claim, and this report does not assert, that the upload system — or the
    platform — is production-ready as a whole.
```
