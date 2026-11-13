# Comprehensive code audit — backend, web, mobile, infrastructure

**Date:** 13 Nov 2026 · **Branch:** `test` at `3cf857d`, working tree as found (8 modified and 3 untracked files that predate this audit were left untouched) · **Mode:** read-only; no code, data or configuration was changed.

This audit follows the 11 Nov beta-readiness audit (`BETA_PRODUCTION_READINESS_AUDIT_2026-11-11.md`), which covered infrastructure, configuration and database schema but did not read the backend line by line. This one traces code paths. Findings from the earlier audit are not repeated; section 9 records which of them were re-checked.

## 1. Executive summary

**Overall health: good engineering base, not yet ready for real employee data.** No authentication bypass, cross-tenant leak or SQL injection was found. Tenant isolation, scope enforcement, token rotation, idempotency, the e-mail outbox and the pay-run state machine are built carefully and defended by tests and a static guard. The problems found are narrower: one public endpoint that lets a candidate set their own salary, one public endpoint that can fill the server's disk, a web client that signs people out on transient errors, and a set of medium-severity gaps in lockout, rate limiting, attendance trust and job scalability.

**Counts from this audit:** 0 critical, 3 high, 11 medium, 12 low. The critical-class items remain the operational ones from 11 Nov (seed credentials on the live database, encryption-key escrow, backups and alerting), which this audit could not re-verify from the repository.

**Most serious risks, in order:**

1. A candidate can write their own annual CTC through the public onboarding link; HR never sees it, and it becomes the employee's compensation record at activation (H-1).
2. Any holder of an onboarding link can upload without limit, about 144 GB a day per link, onto the single VPS that also holds Postgres (H-2).
3. The web app signs the user out whenever a token refresh fails for any reason, including a 429 from the per-IP refresh limit that a shared office address will hit (H-3).
4. The operational blockers B-1 and B-3 from 11 Nov, if still open.

**Code quality:** high in discipline (typing, lint, import boundaries, audit trail, documented decisions), weakened by very large service files (`attendance/service.py` is 7,899 lines; four others exceed 4,000) and by comments that are longer than the code they describe.

### What this audit did and did not cover

| Area | Read and traced | Not covered |
|---|---|---|
| Backend core | Auth, JWT, refresh, tenancy, RBAC, sessions, rate limiter, storage, Celery app, e-mail outbox, log viewer | `core/crypto` internals, idempotency module line by line |
| Backend modules | Identity, account invite, onboarding (public and activation), leave submit/approve, pay-run transitions and bank advice, punch recording, employee import upload, platform login, notifications, all task files | Attendance calculation engine, leave accrual and year-end, payroll statutory and income-tax maths, organisation calendar code, geofence and face services beyond the punch gate |
| Web | API client, token storage, middleware/CSP, XSS-sink and redirect scan | Individual pages and forms |
| Mobile | API client, release configuration | Screens, state management; `flutter analyze`/`flutter test` not run |
| Infrastructure | Compose files, nginx templates, CI and auto-merge workflows | The live VPS |
| Tests | Structure and counts; the static scope scanner was run directly (346 routes, 0 unreviewed) | The test suites were **not run**: the repository's isolation guard refuses the shared dev database, and no disposable stack was started |

Each finding is labelled **Confirmed** (the behaviour follows directly from the code read), **Likely risk** (the code permits it; the trigger depends on load or environment) or **Needs verification**.

## 2. Architecture summary

```text
Browser (Next.js 16, client-rendered app)      Flutter app
        │  Bearer access token (15 min) + HttpOnly refresh cookie (30 days, rotating)
        ▼
nginx (TLS, 15 MB body cap) ──► FastAPI (gunicorn/uvicorn)
        │                         │ middleware: request id → proxy headers → security headers
        │                         │             → tenancy → upload limits → CORS
        │                         │ per route: get_current_user → require_permission → DataScope
        │                         ▼
        │                 module router → service → repository
        │                         │
        ├──► MinIO (presigned GET) │──► PostgreSQL 16 (RLS on 104 tables, hrms_app runtime role)
        │                         │──► Redis (rate limits, Celery broker and results)
        │                         │──► SMTP / face provider (httpx, timeouts set)
        ▼                         ▼
                          Celery worker + beat: daily attendance calculation, leave accrual,
                          comp-off sweeps, year-end, termination access sweep, face cleanup,
                          e-mail outbox sweep, employee CSV import
```

- **Tenancy:** the company comes only from the signed token. `get_current_user` sets the transaction-local `app.company_id` variable and re-checks user, session, membership and company status on every request.
- **Authorisation:** `require_permission(code)` returns the caller's `DataScope` (SELF, REPORTEES, REPORTEE_TREE, BRANCH, COMPANY). Services turn it into visible employee ids. A static AST guard fails CI when a route ignores its scope.
- **Modules:** identity, organisation, employee, employee import, attendance (punch, calculation, regularisation, overtime, periods, rosters, geofence, face), leave, payroll, onboarding, account invite, notification, platform console.
- **Unauthenticated surface:** login, refresh, password reset, e-mail verification, company registration, account-invite links, onboarding links, health.

## 3. Critical findings

None were confirmed in code by this audit.

Carried over from 11 Nov and **not re-verified** here because they concern the live server: B-1 (the live app may run on a database containing published seed credentials) and B-3 (encryption-key escrow, backup alerting). If either is still open it outranks everything below.

## 4. High-priority findings

### H-1. A candidate can set their own salary through the public onboarding link

**Severity:** High · **Category:** Security / Data integrity · **Status:** Confirmed

**Location**
- `apps/api/src/hrms/modules/onboarding/public_router.py:63`, `update_onboarding_section`
- `apps/api/src/hrms/modules/onboarding/schemas.py:445`, `SECTION_SCHEMAS`
- `apps/api/src/hrms/modules/onboarding/service.py:1630`, `OnboardingActivationService.activate_case`
- Path: `PATCH /v1/public/onboarding/{token}/sections/compensation_info` → `update_section` → `onboarding_case.compensation_info` → `create_compensation` at activation → `EmployeeSalaryService._annual_ctc`

**Problem.** The public router accepts any key of `SECTION_SCHEMAS`, and that map still contains `compensation_info`. The schema comment says candidates "no longer enter or get reviewed on CTC", and `compensation_info` was removed from `ONBOARDING_SECTION_NAMES`, so it is neither required for submission nor part of HR's section review. The write path was left open. At activation, any non-empty value becomes an `employee_compensation` row with `revision_type="JOINING"`.

**Why it matters.** The candidate chooses the figure. HR cannot see it: the web app's onboarding pages never render `compensation_info` (it appears only in a type definition and test fixtures). The salary setup screen and bulk structure assignment then read that CTC as the employee's annual pay.

**Reproduction.** With a valid onboarding link, send `PATCH …/sections/compensation_info` with `{"annual_ctc_minor": 900000000}` while the case is `INVITED`, `IN_PROGRESS` or `CHANGES_REQUESTED`. Complete and submit as normal. HR verifies the eight reviewed sections and activates. The employee now has a ₹90 lakh joining compensation. The integration test `test_onboarding_submit.py:60` writes this section through the public route, so the behaviour is exercised today.

**Root cause.** The section was withdrawn from the wizard and the review list but not from the public write allow-list.

**Recommended fix.** In the public router, accept only sections in `ONBOARDING_SECTION_NAMES`. If compensation at onboarding is still wanted, let HR enter it through an authenticated route. Add a test that the public route returns 404/422 for `compensation_info`. Check existing cases for a non-empty `compensation_info` that HR did not enter.

**Priority.** Fix before any real candidate receives a link. Money still needs a salary structure and an approved pay run to move, which is why this is high and not critical.

### H-2. Onboarding links allow unlimited uploads and can fill the server's disk

**Severity:** High · **Category:** Reliability / Security · **Status:** Confirmed (no cap in code); impact is a Likely risk

**Location**
- `apps/api/src/hrms/modules/onboarding/service.py:1001`, `OnboardingDocumentService.upload_document`
- `apps/api/src/hrms/app.py`, `OnboardingUploadRateLimitMiddleware(ip_limit=30, token_limit=10, window_seconds=60)`

**Problem.** Each upload is capped at 10 MB and each link at 10 uploads a minute, but nothing limits how many documents or bytes one case may hold. One link can store about 100 MB a minute, 144 GB a day, for the seven days the link lives.

**Why it matters.** MinIO, Postgres and Redis share one VPS disk with no quotas (`docker-compose.vps.yml`). A full disk stops Postgres for every tenant. The actor needs only an onboarding link, which any invited candidate has.

**Reproduction.** Loop `POST /v1/public/onboarding/{token}/documents` with a 10 MB file that starts with `%PDF-`, ten times a minute.

**Root cause.** Abuse protection was designed per request (size, rate), not per resource.

**Recommended fix.** Refuse an upload when the case already holds N documents (20 is generous) or M bytes in total. Add a MinIO bucket quota and a disk-usage alert. Apply the same count cap to employee documents.

**Priority.** Before external candidates are invited.

### H-3. The web app signs users out on any failed token refresh

**Severity:** High · **Category:** Reliability · **Status:** Confirmed in code; the mass sign-out scenario is a Likely risk

**Location**
- `apps/web/src/lib/api/client.ts:217`, `refreshSession` (`if (!res.ok) return false;` and `catch { return false; }`)
- `apps/web/src/lib/api/client.ts:279`, `apiRequest` (`clearSession(); notifySessionExpired();`)
- `apps/api/src/hrms/modules/identity/router.py:51`, refresh limit of 10 a minute per IP

**Problem.** `refreshSession` returns `false` for every non-2xx response and every network error, and the caller then clears the session. A 429, a 503 from the fail-closed rate limiter, a 502 during a deploy or a 30-second timeout is treated the same as "your session was revoked". The mobile client already separates the cases (`_isRefreshRejection`, three-valued result); the web client does not.

**Why it matters.** Access tokens last 15 minutes and the refresh limit is 10 a minute per IP. An office of about 150 active users behind one public address exceeds that in normal use (the 11 Nov audit's H-1). Every refresh that receives the 429 logs that user out. A Redis restart or an API redeploy does the same to everyone whose token expires in that window.

**Reproduction.** Sign in, wait for the access token to expire, block `/v1/auth/token/refresh` with a 503 once, and make any request. The session is removed from `localStorage` and the user lands on the login page, although the refresh cookie is still valid.

**Root cause.** A boolean result for a three-way outcome.

**Recommended fix.** Port the mobile logic: sign out only on 400/401/403 from the refresh endpoint; on anything else keep the session and surface a retryable error. Separately, key the refresh limit on the session or raise it well above office scale.

**Priority.** Before a beta with more than a handful of users per office.

## 5. Medium-priority findings

| # | Finding | Status | Location | Impact and scenario | Fix |
|---|---|---|---|---|---|
| M-1 | **Account lockout can be held open indefinitely.** `failed_login_count` is never reduced when a lock expires, and the lock check runs before the password check. After five wrong attempts, one wrong attempt every 15 minutes re-locks the account. | Confirmed | `core/db/repositories/identity.py:359`, `identity/service.py:77` | Anyone who knows an administrator's e-mail can keep them out, for example on payroll day. A password reset clears the counter, and five more requests restore the lock. The same pattern exists for platform admins. | Reset the counter when a lock expires; lock with increasing delays per source rather than a hard account lock; never refuse a correct password from a source that has not failed. |
| M-2 | **Rate-limit counters can lose their expiry.** `INCR` and `EXPIRE` are separate calls with a 2-second socket timeout. If `EXPIRE` fails after `INCR` created the key, the key never expires and the count only grows. | Likely risk | `shared/rate_limit.py:115-117`, `140-142`, and the two-key variants | That IP or e-mail is blocked from the endpoint until someone deletes the key by hand. | One atomic step: a Lua script, or `SET key 1 EX n NX` followed by `INCR`; or repair when `TTL` is -1. |
| M-3 | **Face verification is skipped by not enrolling, and never applies to punch-out.** The plain punch is refused only when the employee's face profile is `ENROLLED` and the direction is `IN`. | Confirmed (documented design) | `attendance/service.py:2980`, `3415` | An employee who never enrols, or whose profile is pending or rejected, can punch from any device that passes geofence. Anyone with the credentials can punch out. Liveness is also off by default (11 Nov H-5). Attendance feeds pay. | Owner decision: when the company's face policy requires enrolment, refuse plain punches after a grace period; decide whether punch-out needs verification. |
| M-4 | **The onboarding link returns full PAN, Aadhaar and bank account numbers for as long as it lives,** including after submission and after activation. | Confirmed | `onboarding/service.py:508`, `780` | A forwarded e-mail, shared computer or mailbox compromise exposes identity and bank data for up to seven days. The read routes have no rate limit. | Mask sensitive fields in the public read (last four digits); revoke the link on activation; shorten its life after submission. |
| M-5 | **The daily attendance sweep is serial and time-boxed.** Employees are processed one at a time, three dates each, one transaction per date, under a 30-minute hard limit. | Likely risk | `attendance/tasks.py:145`, `COMPANY_TASK_LIMITS` | At a few thousand employees the task is killed part-way. The list order is stable, so the same employees at the end are skipped every day and their days are never calculated until someone runs a range calculation. | Split per company into employee batches (one task per 200), or process with bounded concurrency; alert on `attendance_scheduled_calculate_incomplete`. |
| M-6 | **E-mail verification is not enforced after registration.** Registration issues a session immediately; neither `refresh` nor `get_current_user` checks `email_verified_at`. | Confirmed | `identity/service.py:116` (login only), `refresh` | With company approval switched off, a registrant using someone else's address keeps full administrator access for as long as they keep refreshing. The real owner of the address cannot register. | Check verification in `refresh` after a short grace period, or make unverified sessions read-only. |
| M-7 | **No guard against administrators changing their own records.** Self-approval is blocked for leave, regularisation, overtime and face enrolment, but an HR or company admin can set their own CTC and structure, adjust their own leave balance, edit their own bank account and enter back-dated punches for themselves. | Confirmed | `payroll/service.py` `save_setup`; `leave/service.py:1349`; `attendance/router.py:946` | Fraud by a single insider. The pay-run maker-checker limits the damage only if the approver reviews variances. | Refuse or require a second approver when the target employee is the caller, for compensation, bank, ledger adjustments and on-behalf punches. |
| M-8 | **A lost refresh response ends the session.** Reuse of a rotated token revokes the whole family with no grace period. | Likely risk | `identity/service.py` `refresh`, mobile `api_client.dart` `_refreshSession` | On a weak mobile connection the server rotates the token, the response is lost, and the next refresh with the old cookie is treated as theft. The employee is signed out, often at punch time. | Accept the immediately previous token for a short window (10–30 seconds) when it arrives from the same session, returning the already-issued successor. |
| M-9 | **Auto-merge protects too few paths.** Only `.github/`, `.gitleaks.toml`, `AGENTS.md`, `CLAUDE.md` and `apps/api/alembic/` wait for a person. | Confirmed | `.github/workflows/auto-merge.yml:62` | A change that deletes tests, adds an entry to `scope_guard_exceptions.toml`, edits `tests/conftest.py`, `pyproject.toml`, lockfiles, Dockerfiles, compose files or `infra/` merges to `main` with no human review. Each of these can weaken a check or change what ships. | Add those paths to the list. |
| M-10 | **Password-reset and verification e-mails bypass the outbox.** They are sent inline; a failure is logged and the caller still gets 202. The matched and unmatched branches also take visibly different time. | Confirmed | `identity/service.py:457`, `540` | A brief SMTP failure silently loses the message with no retry. Response time reveals whether an address has an account, which the code elsewhere works to hide. | Queue both through `enqueue_email`, as invites already are. |
| M-11 | **Storage and database writes are not coordinated, and S3 calls have no timeouts.** Upload stores the object before the row is committed; delete removes the object before the row's deletion commits. The S3 client uses botocore defaults (60 s connect and read, with retries) inside an open transaction. | Confirmed | `onboarding/service.py:1001`, `1097`; `core/storage.py` | Orphaned objects, or rows pointing at missing files. A hung MinIO ties up request workers and database connections. | Delete the object after commit (`defer_until_commit`); add a periodic orphan sweep; pass a `botocore.config.Config` with short timeouts. |

## 6. Low-priority findings

| # | Finding | Status | Location |
|---|---|---|---|
| L-1 | Registration answers "An account with this email already exists", which reveals accounts. Login also returns faster for unknown addresses (no hash is computed), and reports "locked" before checking the password. | Confirmed | `organisation/service.py:334`; `identity/service.py:68-79` |
| L-2 | Four business-date calculations still use `date.today()` (UTC on the server): the roster week default, the shift-swap past-date check, and three decision-centre fallbacks. Between 00:00 and 05:30 IST they are a day behind. | Confirmed | `attendance/schedule_router.py:56`, `schedule_service.py:553`, `leave/decision_center.py:114`, `attendance/regularization_decision_center.py:134`, `organisation/dashboard_insights.py:132` |
| L-3 | Bank-advice CSV neutralises a leading `= + - @` only. A leading tab or carriage return is not handled, and the account number and IFSC cells are not passed through the filter. Names can originate from a candidate. | Confirmed | `payroll/service.py:3868` |
| L-4 | `verify_password` catches only `VerifyMismatchError`; a malformed stored hash raises and becomes a 500. | Confirmed | `core/auth/passwords.py:20` |
| L-5 | The failed-login counter is read, incremented and written in the ORM, so parallel wrong attempts can under-count. | Likely risk | `core/db/repositories/identity.py:359` |
| L-6 | The self-punch order and gap check reads the latest punch and then inserts without a lock; two simultaneous requests both pass. Calculation later collapses duplicates. | Likely risk | `attendance/service.py:3366` |
| L-7 | Mobile `_refreshOnce` never completes if `_refreshSession` throws before its `try` (the secure-storage read), and every later request waits forever. | Likely risk | `apps/mobile/lib/core/api/api_client.dart:239` |
| L-8 | `session.expires_at` is written but never checked, and each refresh issues a new 30-day token, so a session has no absolute lifetime. | Confirmed | `core/auth/dependencies.py`, `identity/service.py` `issue_tokens_for` |
| L-9 | Accepting an invite as an existing user does not check that user's status or the company's status before issuing tokens. The per-request checks reject them afterwards. | Confirmed | `account_invite/service.py` `accept` |
| L-10 | `POST /users/invite` can grant `COMPANY_ADMIN` with `SETTINGS.USER.MANAGE`, while changing a role needs `SETTINGS.ROLE.MANAGE`. Only company admins hold both today. | Confirmed | `account_invite/router.py:74`, `92` |
| L-11 | nginx caps bodies at 15 MB, but face enrolment accepts up to 26 MB (five 5 MB images). An oversized enrolment gets nginx's HTML 413, not the API's error envelope. | Confirmed | `infra/nginx/nginx.conf:74`, `app.py` |
| L-12 | Uploaded files are identified by leading magic bytes only; there is no malware scan. A hostile PDF from an anonymous candidate reaches HR as a download. | Confirmed | `onboarding/document_validation.py` |

## 7. Other observations

**Database and performance.** Transaction scope in the jobs is deliberate and well reasoned (one row lock per calculation). Login and refresh load each company in a loop, which is harmless at one company per user. The 11 Nov index and timeout items (D-2, D-3) stand. No N+1 pattern was found in the paths read, but the large list endpoints were not profiled.

**API contracts.** Error envelopes, request ids, optimistic locking with `If-Match`, and idempotency keys are consistent across the routes read. The mobile contract fixtures are regenerated and compared in CI. The one mismatch found is behavioural, not structural: web and mobile handle refresh failures differently (H-3).

**Background jobs.** The outbox gives at-least-once delivery with duplicate protection at enqueue and states its limits honestly. Import batches are claimed atomically. Fan-out isolates tenants. Open points: M-5, and the 11 Nov items on `acks_late` and beat monitoring.

**Architecture and maintainability.** Module boundaries are enforced by import-linter and cross-module calls go through services. The risk is file size: `attendance/service.py` (7,899 lines), `organisation/service.py` (4,862), `leave/service.py` (4,392), `payroll/service.py` (4,275), `employee/service.py` (4,174). Comments routinely run longer than the code and cite decision ids without stating the rule, which slows review. H-1 is an example of what that hides: a comment recorded the decision while the code kept the old behaviour.

**Testing.** 361 backend test files, 147 web test files, 97 mobile test files, with real Postgres, Redis and MinIO in CI and a two-role RLS harness. Gaps: only two Playwright feature specs and none in CI; no device run for mobile; no test asserting which sections the public onboarding route accepts; no concurrency test for the punch order check; no test for web refresh failure modes other than rejection.

## 8. Top 10 fixes, in order

1. Restrict public onboarding writes to `ONBOARDING_SECTION_NAMES`; audit existing cases (H-1).
2. Cap documents and bytes per onboarding case; add a bucket quota and disk alert (H-2).
3. Close the 11 Nov operational blockers B-1 and B-3 if still open (clean production database, key escrow, backup alerts).
4. Web: sign out only on a rejected refresh; raise or re-key the refresh rate limit (H-3).
5. Rework lockout so it cannot be held open by a third party (M-1).
6. Mask PAN, Aadhaar and bank numbers in the public onboarding read; revoke the link on activation (M-4).
7. Decide and enforce the face-punch policy; switch liveness on for companies that use it (M-3).
8. Make the rate limiter atomic (M-2).
9. Batch the daily attendance sweep and alert when it is incomplete (M-5).
10. Widen the auto-merge "needs a person" list (M-9), then add self-change guards (M-7).

## 9. Status of the 11 Nov findings re-checked here

| 11 Nov item | Status on 13 Nov |
|---|---|
| B-2 salary setup ignores scope | **Fixed.** `save_setup` enforces the `EMPLOYEE.UPDATE_COMPENSATION` scope; the static scanner reports 346 routes and no unreviewed scope-ignoring route. |
| B-4 mobile release configuration | **Still open.** Release build signs with the debug key, the API base URL defaults to `http://localhost:8000`, `pubspec.yaml` still reads "A new Flutter project." |
| H-1 per-IP auth limits | **Still open** (10 a minute for login, refresh and the shared auth bucket), and made worse by H-3 above. |
| H-5 face liveness off by default | **Still open** (`face_liveness_engine` defaults to `disabled`). |
| H-9 Node 20 | **Still open** in CI (`node-version: "20"`). |
| All others | Not re-checked. |

## 10. Production readiness score

| Area | Score |
|---|---:|
| Architecture | 8/10 |
| Security | 7/10 |
| Reliability | 6/10 |
| Error handling | 8/10 |
| Performance | 6/10 |
| Scalability | 5/10 |
| Test coverage | 7/10 |
| Maintainability | 6/10 |
| Observability | 7/10 |
| **Overall production readiness** | **6/10** |

Performance and scalability scores rest on code reading, not load testing. Reliability and overall scores assume the 11 Nov operational blockers are still open.

## 11. Fix roadmap

### Phase 1 — before any real user
- H-1, H-2, H-3.
- 11 Nov B-1, B-3, B-4, B-5 (legal notices) and the per-IP limits.
- M-4 (mask onboarding PII) and M-1 (lockout).

### Phase 2 — first weeks of beta
- M-2 (atomic limiter), M-3 (face policy and liveness), M-6 (verification), M-8 (refresh grace), M-9 (auto-merge paths), M-10 (reset e-mails through the outbox), M-11 (storage coordination and timeouts).
- L-1, L-2, L-3, L-7.
- Tests: public onboarding section allow-list, web refresh failure modes, five or six Playwright smoke flows run against staging.

### Phase 3 — improvements
- M-5 (sweep batching) before any tenant passes about a thousand employees; M-7 (self-change guards).
- Split the five largest service files along their existing class boundaries.
- Remaining low items; error tracking and alerting from the 11 Nov list; a load test of punch, attendance calculation and pay-run compute.
