# API contract & mobile-readiness audit

Scope: whether the backend as implemented today (`apps/api`, working tree on branch `main`, API version `0.1.0`) can support a production mobile client. **Observed defects** and **suggested improvements** are kept in separate sections. Evidence tags: **[live]** = reproduced against a running API on an isolated test database ([examples/](examples/)); **[code]** = read in the source (path:line given); **[doc-gen]** = from the generated inventory/OpenAPI ([ENDPOINT_INVENTORY.md](ENDPOINT_INVENTORY.md)).

Severity: **Critical** blocks secure/correct integration · **High** major functionality or reliability risk · **Medium** friction/inconsistency · **Low** documentation/maintainability.

## 0. Verdict
The backend is **mature and consistent in its core contract** (uniform envelope, strict validation, per-request revocation, optimistic concurrency, idempotency where it matters, defensive error handling) and a Flutter client already exists. It is **not mobile-ready for ordinary employees' attendance** out of the box (C-1), several list endpoints are unbounded (H-1), and key mobile journeys depend on things the API does not offer (documents, payslip PDF, push, deep links — H-2, H-3, H-7). None of the problems require redesign; most are small additive changes.

## 0.1 Status after remediation (2026-10-24)
The findings below are the **baseline** as first written. Their current status, with evidence, is tracked here and in full in [REMEDIATION_REPORT.md](REMEDIATION_REPORT.md).

| ID | Status | Evidence |
|---|---|---|
| C-1 | **Fixed and tested** | `organisation/service.py` grants the `EMPLOYEE` role SELF-scoped `ATTENDANCE.PUNCH/VIEW/REGULARIZATION_REQUEST`; migration `20261020090000` backfills existing tenants; `tests/integration/modules/attendance/test_employee_default_role_attendance.py` |
| H-1 | **Fixed and tested** for the 11 high-volume collections; small master-data lists intentionally unchanged | `shared/pagination.py` (`bounded_pagination_params`, `fetch_page`), `test_bounded_list_pagination.py` |
| H-2 | **Deferred - product decision** (verified absent; not required by the current mobile release) | REMEDIATION_REPORT §H-2/H-7 |
| H-3 | **Partly fixed, deployment-dependent** - optional `hrms://app/...` link added to the four token emails; HTTPS App/Universal Links not implemented | `core/links.py`, `test_mobile_email_links.py` |
| H-4 | **Fixed for the identified gaps; rest classified** - opt-in `Idempotency-Key` on `POST /employees` and `POST /onboarding-cases`; every other write is state-machine protected | `test_optional_idempotency.py` |
| H-5 | **Documented decision, no code change** - online-only is the approved behaviour (`DEC-TZ-01`); mobile-source label cannot be server-validated without attestation | OFFLINE_ATTENDANCE_DESIGN.md |
| H-6 | **Verified fail-closed; intentionally left disabled** | `tests/unit/core/test_face_feature_gates.py`, `test_face_attendance_stays_fail_closed_by_default` |
| H-7 | **Deferred - product decision** | REMEDIATION_REPORT §H-2/H-7 |
| M-7 (test coverage) | **Improved** - reusable contract helpers and a cross-cutting contract suite added | `tests/integration/contract_helpers.py`, `test_api_contract_core.py` |
| Others (M-1…M-13, L-1…L-8) | Open, unchanged | see §1 |

## 1. Observed defects & gaps

### Critical
**C-1 — The default `EMPLOYEE` role cannot punch, read attendance, or file regularizations, and the API offers no way to grant it.**
* Evidence **[live]**: a freshly registered company → create employee → invite → accept; `GET /auth/me` lists only `EMPLOYEE.VIEW*`, `LEAVE.APPLICATION_SUBMIT`, `LEAVE.BALANCE_VIEW`, `PAYROLL.PAYSLIP_VIEW_OWN`; `POST /v1/attendance/punches/me` → `403 PERMISSION_DENIED "Permission ATTENDANCE.PUNCH is required"` ([examples/employee-self-service.md](examples/employee-self-service.md)). **[code]** `organisation/service.py:756-805` grants the `EMPLOYEE` role no `ATTENDANCE.*` code (`BRANCH_MANAGER` gets `ATTENDANCE.VIEW` at BRANCH scope, managers/HR get the `*_APPROVE` codes, nobody but `COMPANY_ADMIN` gets `ATTENDANCE.PUNCH`, and `COMPANY_ADMIN` has no employee record by default). The only role-related write endpoint is `PATCH /users/{id}/roles` (assign existing role codes); there is no create-role/edit-permissions route **[doc-gen]**.
* Affected: `POST /attendance/punches/me`, all `/attendance/face-*/me`, `GET /attendance/{days,punches}`, `POST /regularizations`, `GET /overtime`, `GET /rosters` for employees.
* Impact: the headline mobile feature (self punch, face punch, own attendance) returns 403 for every ordinary employee unless the permission rows are inserted out-of-band. After inserting `ATTENDANCE.PUNCH/VIEW/REGULARIZATION_REQUEST` (SELF) for the role directly in the test DB, the whole flow worked **[live]**.
* Recommendation: grant `ATTENDANCE.PUNCH`, `ATTENDANCE.VIEW`, `ATTENDANCE.REGULARIZATION_REQUEST` (SELF) to the system `EMPLOYEE` role at registration and via a data migration for existing companies; add a role-permission management endpoint. Confirm intended behaviour with the backend team first — this may be a deliberate "attendance module not yet enabled" gate that the docs do not mention.

### High
**H-1 — Most list endpoints are unbounded.** Only 11 routes accept `page`/`per_page`; `/attendance/days`, `/attendance/punches`, `/regularizations`, `/overtime`, `/rosters`, `/payroll/pay-runs`, `/attendance-periods`, `/leave-types`, org master-data lists etc. return everything and `pagination: null`. **[live]** `/branches?page=2&per_page=5` ignores both; **[code]** `attendance/router.py:898-922` has no page params and the attendance repository applies no `LIMIT` to those queries (only `.limit(1)` existence checks and one capped query at `repository.py:2447`). All date/employee filters are optional, so a COMPANY- or REPORTEE_TREE-scoped caller can request years of data in one response. Impact: memory/latency spikes on phones and server. Fix: add `page/per_page` (or require a bounded date range) to those routes; keep `pagination: null` only where the set is inherently small. *Not load-tested.*

**H-2 — Missing capabilities for common mobile features.** No download/preview of uploaded documents (list/upload/delete/review only; `EmployeeDocumentRead` omits the storage key) **[code: employee/schemas.py]**, no payslip PDF (`PayslipRead` JSON only) **[code]**, no leave-attachment upload (`attachment_reference` is a free ≤500-char string), no profile-photo upload (`photo_url` free string), no document/payslip share. Impact: these screens can only be built as native renderings of JSON or deferred. Fix: add authenticated, short-lived download endpoints (stream or presigned URL with documented TTL) and a payslip PDF endpoint.

**H-3 — Email links cannot open the mobile app.** Password-reset, email-verification, account-invite and onboarding emails contain `{web_app_base_url}/reset-password|verify-email|accept-invite|onboarding/<token>` **[code: identity/service.py:449,530; account_invite/service.py:180; onboarding/service.py:745]**. The Android manifest registers only the custom scheme `hrms://app` and no https App Links or iOS associated domains were found **[code: apps/mobile/android/app/src/main/AndroidManifest.xml:27-32]**; the Flutter router has matching `/reset-password/:token` etc. routes. Impact: a user tapping the email on a phone with the app installed lands in a browser; the token is single-use and short-lived (reset 2 h, verification 24 h). Fix: host `assetlinks.json`/`apple-app-site-association` on `web_app_base_url` and register the https links, or add a mobile-specific link template.

**H-4 — Idempotency covers only 4 operations plus punches.** `Idempotency-Key` is mandatory for leave application, leave adjustments/encashments, payroll adjustments **[code]**; manual/face punches have their own optional keys. Every other write (employee create, approvals, rejects, pay-run transitions, publish, role changes, imports, onboarding submit) has none. Mitigation present: `If-Match`/state-machine checks usually turn a duplicate into `409`. Impact: after a timeout the client cannot know whether the write landed and must reconcile by reading. Fix: extend `Idempotency-Key` to approval/creation endpoints.

**H-5 — Punch time is always the server's receipt time; no offline-capture path, and the source label is wrong for mobile.** `PunchCreateSelf` has no time field (`attendance/schemas.py:1277`), **[live]** `source: "WEB"` is returned for the app's own call; a duplicate `IN` is accepted **[live]**. Impact: queued offline punches would be stamped at replay; analytics/HR cannot distinguish mobile punches; the app must route missed punches through regularization. Fix: accept an optional client capture time with bounded skew (flagged `OFFLINE`) or document regularization as the sanctioned path; add a `source`/client-type value for mobile.

**H-6 — Face attendance is disabled by default and its liveness thresholds are declared uncalibrated.** `face_verification_provider` and `face_liveness_engine` default to `disabled`, in which case all face routes answer `503 FACE_VERIFICATION_UNAVAILABLE/FACE_LIVENESS_UNAVAILABLE`; the settings comment says the thresholds are "UNCALIBRATED engineering defaults … do not enable for production attendance until device/attack calibration has been done" **[code: core/config/settings.py:228-262]**. Face failure `429`s carry no `Retry-After`. The face flow was **not executed** in this audit. Impact: cannot be relied on for launch without a deployment decision and calibration.

**H-7 — No push notification or in-app notification surface.** No device-token registration, notification list, or webhooks; approvals/reminders are email only **[doc-gen; grep of src/]**. Impact: approvers learn of leave/regularization requests only by polling or email.

### Medium
* **M-1 — Login throttling is IP-wide and enables lockout abuse.** The `login` bucket enforces 10/60 s per IP **and** per IP+email, so every email from one NAT shares the IP budget **[live: 11th attempt → 429; earlier run tripped after only 4 attempts because 6 other logins from the same IP had counted]**. Separately, 5 wrong passwords lock *any* account for 15 min (lock checked before the password **[live]**), so a third party who knows an address can lock it. Impact: shared-office devices are throttled together; targeted lockout nuisance. Fix: per-device/ per-account progressive delays, CAPTCHA/attestation, or an unlock flow.
* **M-2 — No sorting, no search, no sparse fields on any tenant list** (**[doc-gen]** no `sort`/`q` params). Mobile must sort client-side and cannot search employees.
* **M-3 — OpenAPI under-describes the contract.** FastAPI's generated spec marks `Idempotency-Key` optional (enforced as required), declares the 422 body as FastAPI's `HTTPValidationError` instead of the real `ErrorEnvelope`, lists no 401/403/409/429 responses, types timestamps as bare strings (159 of 174 `*_at` fields), enum-like fields as `string`, and declares CSV/image responses as `{}` **[doc-gen]**; field `description`s are almost entirely empty and only 76 of 333 handlers have docstrings. The enriched [openapi.json](openapi.json) fixes the mechanical items; a generated client from the *raw* spec will be wrong.
* **M-4 — Error shapes are consistent in envelope but inconsistent in vocabulary.** Three validation conventions (`REQUEST_VALIDATION_ERROR` with prefixed fields, `VALIDATION_ERROR`, per-module 422 codes; [ERROR_HANDLING.md §2](ERROR_HANDLING.md)); `documentation_url` always `null`; no machine-readable `retryable`; `Retry-After` only on rate-limit/DB-busy; 291 distinct codes with no per-endpoint map.
* **M-5 — No session management for users.** No change-password, no list/revoke devices, no switch-company-without-password (re-login with `company_id`) **[doc-gen]**. A user in several companies cannot move between them in-app without re-entering credentials.
* **M-6 — No per-endpoint error matrix and thin descriptions** (see M-3): domain codes are discoverable per module only ([modules/*.md](modules/)). Contract tests per endpoint would close this.
* **M-7 — Authorization truth-table test covers only three modules.** `tests/integration/test_route_authorization_matrix.py` introspects `organisation`, `employee`, `employee_import` (`_MODULES`); attendance, leave, payroll, onboarding, account-invite and platform rely on module tests. Textual cross-reference of method+path in `tests/`: 186 direct, 117 path-only, 30 none (platform-console and several sub-resource GET/PATCH/DELETE routes; matcher is heuristic and misses helper-wrapped calls — list in Appendix B).
* **M-8 — Silent filtering of out-of-scope data.** `GET /attendance/days?employee_id=<other>` returns `200 []` **[live]**, indistinguishable from "no data". Fine for security, ambiguous for UX; document or return `403`.
* **M-9 — Pagination envelope is polymorphic** (`pagination` object vs `null`) and `next_cursor` is dead schema **[code]**.
* **M-10 — Staging and production base URLs, CORS origins, `web_app_base_url`, and email provider are not defined in the repository** ([API_OVERVIEW §2](API_OVERVIEW.md)); Swagger is dev-only. Impact: environment configuration must come from DevOps; keep this repo's `openapi.json` in CI to avoid drift.
* **M-11 — Refresh token only as a cookie.** Correct for browsers (SEC-06), but native clients must run a persistent cookie jar or parse `Set-Cookie`; there is no body/header alternative in responses (the request side accepts `refresh_token` in the body). A lost/cleared jar = forced re-login; some HTTP stacks (React Native `fetch`) handle cookies poorly. Fix: opt-in token-in-body for native clients (e.g. a `X-Client-Type: mobile` header) or a documented token-exchange.
* **M-12 — Company starts read-only by default** (`company_approval_required=true`): freshly registered tenants see `PENDING_APPROVAL` until a platform admin acts; mobile must handle it as a first-class state ([AUTHENTICATION §6](AUTHENTICATION.md)).
* **M-13 — Employees cannot self-edit profile data or see a directory** with default roles (no `EMPLOYEE.UPDATE*`, no `EMPLOYEE.VIEW_ALL`); attendance days show `CONFIG_ERROR` when the company has not configured calendars/policies **[live]** — configuration prerequisites are not discoverable from the API (see `/companies/current/setup-progress`, admin only).

### Low
* **L-1** — Duplicate Pydantic class names (`CompanyDetail` in identity and platform) produce mangled OpenAPI names (`hrms__modules__identity__schemas__CompanyDetail`, `DataEnvelope_CompanyDetail___1`) that hurt code generators **[doc-gen]**.
* **L-2** — `GET /health/live` returns a bare object while `GET /health` and `/health/ready` use the envelope.
* **L-3** — `POST /companies/register` returns `409 CONFLICT "An account with this email already exists"` **[code: organisation/service.py:311]**, an account-existence oracle that other flows (login, forgot, resend) deliberately avoid.
* **L-4** — Access-token lifetime is exposed as `expires_in_minutes` (not seconds / absolute time) and `meta.server_time` is the only clock hint besides the HTTP `Date` header.
* **L-5** — Tenant and platform JWTs are signed with the same HS256 secret (`jwt_access_secret`) and separated only by `type`/`aud` claims **[code: platform/security.py, core/auth/jwt.py]**; `session.expires_at` is not consulted by `get_current_user` (only `revoked_at`) **[code]**.
* **L-6** — `GET /v1/auth/admin/users-check` is a permission-probe utility (`SETTINGS.USER.MANAGE`, returns `{"status":"ok"}`); not a product endpoint (marked internal below).
* **L-7** — `Content-Type` of CSV/image downloads is only discoverable in handlers.
* **L-8** — Per-field descriptions are almost absent from schemas, so the generated dictionaries show `-` for most descriptions; the information lives in source comments/docs under `docs/`.

## 2. Improvements (suggested, not defects)
1. Fix C-1; add role/permission administration endpoints and a "required setup" API (company readiness) so clients can explain `CONFIG_ERROR` states.
2. Introduce bounded/paged variants for H-1 routes; add `sort` and `q` where lists are user-facing.
3. Add document download + payslip PDF + attachment upload; define signed-URL TTL if presigned.
4. Publish `openapi.json` from CI, with the enrichments in `docs/api/tools/build_api_docs.py` moved into the app (response models for errors, required idempotency header, enums as real `Enum`s, `format: date-time` types).
5. Unify validation errors under one code and a documented `details[].field` convention; populate `documentation_url`; add `retryable` and `Retry-After` for face 429.
6. Provide a mobile-friendly session option (token in body for native clients), a change-password endpoint, device list/revoke, and company switch via refresh.
7. Add push-token registration and a notifications feed; add universal-link support.
8. Extend `Idempotency-Key` to create/approve/transition endpoints.
9. Add contract tests asserting each endpoint's declared error set (turns M-6 into a CI gate).
10. Rate-limit design: separate IP and account budgets, return remaining budget headers (`RateLimit-*`).

## 3. Internal, deprecated or unsuitable endpoints
| Endpoint(s) | Classification |
|---|---|
| `/v1/platform/*` (23 ops: platform login/logout/me, companies, audit log, plans, admins, logs) | Platform super-admin console — separate token, **not for the tenant mobile app** |
| `GET /v1/auth/admin/users-check` | Internal probe |
| `GET /health`, `/health/live`, `/health/ready` | Infrastructure |
| `POST /v1/leave-projections*`, `POST /v1/attendance/days/{id}/recompute`, `/days/calculate-range`, period `finalize/reopen/validate` | Back-office/integration seams (COMPANY-scoped, privileged) |
| `/v1/payroll/*` setup & run lifecycle, `/v1/attendance-policies|overtime-policies|regularization-policies*`, `/v1/employee-imports*` | Admin configuration (tier C) — buildable in mobile (the Flutter app does) but not typical |
No endpoint is marked deprecated in code; there is no deprecation mechanism.

## 4. Validation performed (actual results)
| Check | Command / method | Result |
|---|---|---|
| Route inventory vs OpenAPI | `docs/api/tools/build_api_docs.py` asserts introspected routes == `app.openapi()` operations | **333 operations / 233 paths**, no discrepancy (script would abort otherwise) |
| Existing backend tests (auth + routing) | `pytest tests/integration/auth tests/integration/test_route_authorization_matrix.py tests/integration/test_route_robustness.py` on isolated DB `hrms_test` (migrated to head first; the DB was one migration behind) | **70 passed, 0 failed** (84 s). The suite refuses to run against `hrms_dev`. |
| Live contract recording | `docs/api/tools/record_examples.py` against a local server (`ENVIRONMENT=development`, `hrms_test`, Redis db 1, email provider `logging`, `COMPANY_APPROVAL_REQUIRED=false`) | 73 real calls recorded: registration, verification, login, refresh rotation + reuse detection, logout/revocation, lockout (5→423), rate limit (11th→429), `If-Match`/`STALE_RESOURCE`, pagination cap, `Idempotency-Key` required, invite→accept, employee `/me`, punches, attendance days, leave/payslip empty states, permission denials |
| OpenAPI document validity | see the final report (structure validated with FastAPI's `OpenAPI` model) | |
| Not executed | face enrollment/punch (provider and liveness disabled), leave application submit/approve (needs policy setup), payroll run lifecycle, onboarding portal, employee import, regularization/overtime workflows, any load or concurrency test | **Documented from code only** — marked `[source]` in [API_WORKFLOWS.md](API_WORKFLOWS.md) |
Side effects of validation: test rows were created in the isolated `hrms_test` database (companies named "Docs Example…", "Docs Lock…") and three `role_permission` rows were inserted there by hand for the recorded punch flow. Nothing touched `hrms_dev`.

## Appendix A — Breaking-change risks & undocumented dependencies
* API `info.version` is static `0.1.0`; `/v1` has had no documented breaking-change policy. The Flutter client mirrors the web client's TypeScript types (`apps/web/src/lib/api/types.ts`), so field renames would break both.
* Behaviour that depends on **server configuration**, not code: `company_approval_required`, `allowed_company_timezones`, `jwt_*_ttl`, face provider/liveness engine, rate-limit sizes (hard-coded in routers: 10/min), email provider, `web_app_base_url`, trusted proxy hosts (affects client-IP limiting and `Secure` cookie). Confirm deployed values.
* Third-party dependencies visible in code: Face++ (face provider), MiniFASNet (local liveness model), SMTP/Mailtrap/Hostinger providers (email), S3-compatible storage, Redis, Celery. **No payment gateway, OAuth/Google/Apple, SMS or push provider exists.**
* Timezone: one allowed zone today (`Asia/Kolkata`); the schema carries `timezone` per record, so multi-zone clients must not hard-code IST.

## Appendix B — Endpoints with no textual test reference (heuristic)
Overtime/regularization policy version sub-routes (GET resolve, GET/PATCH/DELETE `{version_id}`), employee education/experience `GET {id}` and `DELETE`, payroll `salary-structures/{id}` GET/PATCH, and the 16 platform-console routes listed in the inventory with `none`. The matcher recognises `client.<verb>("/path")` calls; platform tests likely wrap calls in helpers, so treat this list as "needs a human look", not "untested".
