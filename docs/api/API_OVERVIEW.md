# API overview & conventions

Audience: a mobile developer who has not worked on this backend. Every statement is taken from the code under `apps/api/src/hrms` or from a recorded exchange in [examples/](examples/). Where behaviour is inferred or not exercised, it says so.

## 1. Architecture in one paragraph
A single FastAPI service (`hrms.app.create_app`, title "HRMS API", `version="0.1.0"`) over PostgreSQL with row-level security per company, Redis (rate limiting, Celery broker), S3-compatible object storage (documents/photos), and Celery workers (employee import, scheduled attendance/leave jobs). **Multi-tenant**: every authenticated request is scoped to exactly one `company_id` carried inside the access token. There are 11 feature modules and **333 operations on 233 paths** ([ENDPOINT_INVENTORY.md](ENDPOINT_INVENTORY.md)): identity/auth 10, organisation 70, employee 41, employee-import 5, attendance 83, leave 34, payroll 43, onboarding 15, account-invite/users 6, platform console 23 (not for mobile), health 3.

## 2. Base URLs, versioning, environments
| Environment | Base URL | Source |
|---|---|---|
| Local / emulator | `http://localhost:8000`; Android emulator → `http://10.0.2.2:8000` | `apps/mobile/lib/core/api/api_client.dart` (`--dart-define=API_BASE_URL=…`, default `http://localhost:8000`) |
| Staging | **not defined anywhere in the repository** | grep of `infra/`, `docker-compose.prod.yml`, `docs/deployment` |
| Production | **not defined anywhere in the repository** | same |

* All business endpoints are under the **`/v1`** prefix. That is the only versioning mechanism: no header/media-type versioning, no deprecation headers, no `Sunset` policy. The OpenAPI `info.version` is the application version `0.1.0`, not an API contract version.
* Health probes are **unversioned**: `GET /health` (envelope), `GET /health/live` (`{"status":"ok"}` — *no envelope*), `GET /health/ready` (envelope; `503` when Postgres/Redis/storage are not ready). Use `/health/ready` for a connectivity check; never send credentials to them.
* **Swagger/ReDoc/OpenAPI are served only when `ENVIRONMENT=development`** (`/docs`, `/redoc`, `/v1/openapi.json`); in staging/production they are 404 by design (OPS-06). The committed [openapi.json](openapi.json) in this folder is therefore the only schema source for a mobile team targeting a deployed server.
* Deployed behind a reverse proxy: `X-Forwarded-For`/`-Proto` are honoured only from `trusted_proxy_hosts`. This matters for client-IP rate limiting and the `Secure` cookie flag.

## 3. Request conventions
| Item | Rule | Evidence |
|---|---|---|
| Content type | `application/json` for bodies; `multipart/form-data` for uploads (5 endpoints: face enrollment, face punch, employee document, onboarding document, employee import) | OpenAPI request bodies |
| Field naming | `snake_case` everywhere (requests, responses, query params) | schemas |
| IDs | UUID strings (v4 form) for every resource; opaque to clients | schemas |
| Auth header | `Authorization: Bearer <access_token>` ([AUTHENTICATION.md](AUTHENTICATION.md)) | `core/auth/dependencies.py` |
| `X-Company-Id` | **Optional.** If present it must equal the token's `company_id`, otherwise `404 NOT_FOUND "Resource not found"`. The token alone selects the tenant. | `core/tenancy/dependencies.py`; **[recorded]** |
| `X-Request-Id` | Optional client-supplied correlation id, pattern `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`; anything else is replaced by a server UUID. Always echoed in the response header and in `meta.request_id` / `error.request_id`. | `core/observability/request_context.py` |
| `If-Match` | **Optimistic concurrency** on versioned PATCH/PUT/DELETE/transition routes. Value = the integer `version` from the last read, bare (`3`) or ETag form (`"3"`, `W/"3"`). Missing header → `422 REQUEST_VALIDATION_ERROR`; non-integer → `422 INVALID_IF_MATCH`; stale → `409 STALE_RESOURCE` whose `details[0].context.current` contains the **current resource** so the client can merge. **[recorded]** | `shared/if_match.py` |
| `Idempotency-Key` | **Optional** header on `POST /employees` and `POST /onboarding-cases` (H-4 remediation; same semantics as below, `409 IDEMPOTENCY_KEY_CONFLICT` on a different body; a malformed key is a 422). **Required** header on 4 operations: `POST /leave-applications`, `POST /leave-ledger/adjustments`, `POST /leave-ledger/encashments`, `POST /payroll/adjustments`. 8–128 chars of `A-Za-z0-9._:-`. Same key + same body + same user → the stored response is replayed with status unchanged and header `Idempotent-Replayed: true`; same key + different body → `409 IDEMPOTENCY_KEY_CONFLICT`. A failed attempt does not consume the key. Scoped per company+operation. **[recorded: missing key → 422]** | `core/idempotency.py` |
| Face-punch idempotency | Separate mechanism: optional **form field** `idempotency_key` (16–64 of `[A-Za-z0-9_-]`) on `POST /attendance/face-punches/me`. Plain punch `POST /attendance/punches/me` accepts an optional **body** `idempotency_key` (≤100). Same key + same direction by the same employee **replays the original punch** (`201` with the original row); same key for a different employee (keys are unique per *company*) → `409 DUPLICATE_PUNCH_IDEMPOTENCY_KEY`; a different direction under the same key is refused by `_ensure_same_logical_punch`. Use a random UUID per tap, never a derived value. | `face_service.py:1148`, `attendance/exceptions.py` |
| CORS | Irrelevant to native apps; browser-only (`allow_credentials=true`, explicit origin list outside development). | `app.py` |

## 4. Response conventions
### 4.1 Success envelopes
```jsonc
// single resource / action result
{ "data": { … }, "meta": { "request_id": "…", "server_time": "2026-10-24T13:17:22.454984Z" } }
// collection
{ "data": [ … ], "pagination": { "page": 1, "per_page": 25, "total": 0, "total_pages": 0, "next_cursor": null } | null,
  "meta": { … } }
```
* `meta.server_time` is UTC ISO-8601 with `Z`; only some modules populate it identically, treat it as informational. It is **not** advertised as a clock-sync source.
* `next_cursor` is declared in the schema but **never populated** by any code path (grep of `src/`). Pagination is offset-based only.
* A handful of endpoints return a bare object instead of an envelope: `GET /health/live`; `204` responses have no body; CSV downloads (`GET /payroll/pay-runs/{id}/bank-advice`, `GET /employee-imports/template`) return `text/csv` with `Content-Disposition: attachment; filename="…"`; `GET /attendance/face-profiles/{id}/review-photo` returns raw image bytes with `Cache-Control: no-store, private`. All declare an empty (`{}`) JSON schema in OpenAPI — the real content type is only in the handler.
* **Org/employee master-data `DELETE` routes are soft-deactivations and return the updated resource (`200`, `is_active=false`)**; the following `DELETE` routes return `204` with no body: employee experience/education/dependents, face enrollment-window cancel, leave-combination-rules, statutory-leave-minimums, pay-runs, payroll adjustments. Check the inventory per route.

### 4.2 Error envelope (all errors, including framework 404/405/422)
```json
{ "error": { "code": "PERMISSION_DENIED", "message": "Permission ORG.COMPANY.MANAGE is required",
             "details": [ { "field": "body.name", "code": "missing", "message": "Field required", "context": null } ],
             "request_id": "70b4559e-…", "documentation_url": null } }
```
Details and the full catalogue: [ERROR_HANDLING.md](ERROR_HANDLING.md), [ERROR_CODES.md](ERROR_CODES.md).

### 4.3 Data types
| Kind | Wire format | Notes |
|---|---|---|
| Instant (`created_at`, `punch_time`, `submitted_at`, …) | ISO-8601 UTC string with `Z`, up to microseconds, e.g. `2026-10-24T13:17:22.407820Z` | In many Read models the OpenAPI type is plain `string` (no `date-time` format) because the server formats it manually (`_format_timestamp`). Parse as ISO-8601 with optional fraction. |
| Calendar date (`attendance_date`, `start_date`, `joining_date`) | `YYYY-MM-DD` | No timezone; interpreted in the company/shift business timezone. |
| Time of day (shift/policy times) | `HH:MM` | `_format_time`. |
| Business timezone | IANA name in `company_timezone` (`/auth/me`) and per-record `timezone` (e.g. `AttendanceDayRead.timezone`) | Registration currently only accepts `Asia/Kolkata` (`allowed_company_timezones`, see `GET /v1/companies/registration-config`). "Today" for attendance is the **company's** today, not the phone's; omit `date` where optional and let the server decide (e.g. `POST /attendance/days/calculate`). |
| Money | Integer **minor units** (paise) in `*_minor` fields (`gross_minor`, `net_minor`) plus ISO currency; `MoneyAmount{amount_minor,currency}` in shared schema | Never floats. Some payroll amounts are still decimal strings — see below. |
| Decimals (leave days, balances, similarity) | **JSON strings** such as `"1.50"` (schema `pattern` `^(?!^[-+.]*$)[+-]?0*\d*\.?\d*$`) | Parse with a decimal type, not `double`. A few fields (`paid_days`, `lop_days` on payslips) are plain `string` without the pattern. The Flutter app has `leave_decimal_parsing_test.dart` for this. |
| Booleans/enums | JSON booleans; enums as upper-case strings | OpenAPI declares many enums as plain `string`; allowed values are in [models/ENUMS.md](models/ENUMS.md). |
| Null vs omitted | Read models always include every key (nullable ones as `null`). Create/Update models: omitted = "no value / unchanged"; PATCH treats omitted as unchanged; explicit `null` clears nullable fields where the schema says nullable. *Not individually verified per field.* | `schemas.py` conventions |

### 4.4 Pagination, filtering, sorting
* Offset pagination via `page` (≥1, default 1) and `per_page` (1–100, default 25). Out-of-range → `422` (never clamped) **[recorded]**.
* **Standard paginated routes** (default 25, max 100): `/employees`, `/leave-applications`, `/leave-ledger`, `/onboarding-cases`, `/users`, `/policy-assignments`, `/shifts/{id}/versions`, `/holiday-calendars/{id}/holidays`, `/work-calendars/{id}/exceptions`, and platform `/platform/companies`, `/platform/audit-log`.
* **Bounded routes (H-1 remediation)** - `page` (≥1) and `per_page` (1-**500**, default **500**; 422 outside that range): `/attendance/punches`, `/attendance/days`, `/rosters`, `/regularizations`, `/overtime`, `/attendance-periods`, `/leave-projections`, `/attendance/face-profiles`, `/payroll/pay-runs`, `/payroll/pay-runs/{id}/employees`, `/payroll/adjustments`. They previously returned everything. The generous default keeps existing callers that send no paging parameters working (the web app does) while guaranteeing a response can never exceed 500 rows; `pagination` is always present so a client can detect a partial page (`page < total_pages`). Ordering is total (unique tie-breaker), so pages never overlap or skip rows. Send `per_page=100` (the Flutter client already does) for phone-sized pages.
* **Still unbounded** (small by nature or not yet reviewed; `"pagination": null`): org master data (`/branches`, `/departments`, `/designations`, `/grades`, `/shifts`, `/legal-entities`, calendars, weekly-off patterns), `/leave-types`, `/leave-policies`, `/me/payslips` (one row per finalised month), employee sub-resource lists, payroll setup lists, `/employee-imports/{id}/errors`. See [REMEDIATION_REPORT.md](REMEDIATION_REPORT.md) §H-1.
* **No sorting parameters exist** on any route (grep of OpenAPI: no `sort`/`order_by`). Order is whatever the repository returns (observed newest-first for punches). **No free-text search** on any tenant route (`q` exists only on the platform-console routes `/platform/companies` and `/platform/logs/entries`).
* `as_of=YYYY-MM-DD` returns the effective-dated row valid on that date (employee assignments/compensation/statutory/bank, policy versions).

## 5. Rate limits (all verified in code; Redis-backed, fixed window)
| Bucket | Limit | Key | Routes |
|---|---|---|---|
| `login` | 10 / 60 s | IP **and** IP+email (both must stay under) | `POST /auth/login` **[recorded: 11th attempt → 429]** |
| `token_refresh` | 10 / 60 s | IP | `POST /auth/token/refresh` |
| `auth` | 10 / 60 s | IP (shared bucket) | `POST /companies/register`, `/auth/password/forgot`, `/auth/password/reset`, `/public/account-invites/{token}/accept` |
| `email_verification` | 10 / 60 s | IP | `/auth/email/verify`, `/auth/email/resend-verification` |
| onboarding upload (middleware) | 30 / 60 s per IP, 10 / 60 s per onboarding token | IP / token | `/v1/public/onboarding/*` upload paths |
| `face_punch` | `face_punch_requests_per_minute_per_ip` = 600 / 60 s | tenant+IP | 2 face-punch routes |
| `face_enrollment` | 60 / 60 s | tenant+IP | face enrollment routes |
| `face_review_photo` | 120 / 60 s | tenant+IP | review-photo |
| Face failures | 5 failed punches / 10 min per employee → `429 FACE_ATTEMPTS_EXCEEDED`; 5 failed enrollments per window → `429 FACE_ENROLLMENT_ATTEMPTS_EXCEEDED` | employee | settings `face_punch_max_failed_attempts`, `face_enrollment_max_failed_attempts` |
| Everything else | **No rate limit** (`rate_limit_max=100` exists in settings but nothing reads it) | — | — |

Over-limit: `429 RATE_LIMITED` + `Retry-After: <seconds>`. Limiter unavailable: `503 RATE_LIMITER_UNAVAILABLE` + `Retry-After: 5` (fails closed).

## 6. Upload & download limits
| Endpoint | Field(s) | Max | Accepted types |
|---|---|---|---|
| `POST /attendance/face-enrollment/me` | `front,left,right,up,down` (5 files) + `consent_confirmed` (bool) | 5 MiB per image; request cap 5×5 MiB + 1 MiB (`413 PAYLOAD_TOO_LARGE`) | JPEG/PNG (content sniffed) |
| `POST /attendance/face-punches/me` | `frames[]` (exactly `frames_required` from the session; ≤5), `direction`, `liveness_session_id`, `idempotency_key?` | 1 MiB per frame; cap 5×1 MiB + 1 MiB | JPEG/PNG (sniffed) |
| `POST /employees/{id}/documents` | `document_type`, `file` | 10 MiB (cap +2 MiB) | PDF, JPEG, PNG by **magic bytes** — client `Content-Type`/filename are ignored |
| `POST /public/onboarding/{token}/documents` | `file` (+ metadata) | 10 MiB (cap +2 MiB) | same |
| `POST /employee-imports` | CSV/XLSX | 5 MiB (+1 MiB request cap) | see module doc |

* Oversize → `413 PAYLOAD_TOO_LARGE` with the standard envelope (built by middleware before parsing).
* **There is no endpoint that returns a download URL or bytes for an uploaded employee/onboarding document** — only list/upload/delete/review. `EmployeeDocumentRead` deliberately omits the storage key. Presigned URLs are not exposed anywhere in the API, so URL lifetime is N/A ([audit H-2](API_CONTRACT_AUDIT.md)).
* Payslips are JSON (`PayslipRead`); **no PDF rendering endpoint** exists.

## 7. Security headers & transport
Every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` (camera/mic/geo disabled — applies to web contexts only), a restrictive `Content-Security-Policy`, and `Strict-Transport-Security` when the request is HTTPS. Not relevant to native clients except that HSTS confirms the server expects TLS.

## 8. Asynchronous behaviour
Only a few operations are asynchronous, and none has a dedicated job-status endpoint — you poll the related resource:
| Operation | Response | How to observe completion |
|---|---|---|
| `POST /attendance/days/calculate-range` | `202` `AttendanceRangeCalculateQueued` | Period `POST …/validate` verdict / `GET /attendance/days` |
| `POST /employee-imports` | `201` batch | `GET /employee-imports/{batch_id}` (status), `/errors` |
| Email sends (invite, reset, verification) | request returns before delivery; delivery failure is swallowed | none — hence the "resend" endpoints |
| Face provider cleanup / retention | background | none |

## 9. Where to go next
[AUTHENTICATION.md](AUTHENTICATION.md) → [ERROR_HANDLING.md](ERROR_HANDLING.md) → [API_WORKFLOWS.md](API_WORKFLOWS.md) → [MOBILE_INTEGRATION_GUIDE.md](MOBILE_INTEGRATION_GUIDE.md) → module references under [modules/](modules/) → [API_CONTRACT_AUDIT.md](API_CONTRACT_AUDIT.md).
