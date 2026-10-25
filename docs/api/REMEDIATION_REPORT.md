# Remediation report - critical/high API findings (2026-10-24)

Scope: verify the findings in [API_CONTRACT_AUDIT.md](API_CONTRACT_AUDIT.md) against the code, fix the confirmed defects that are inside existing product scope, and record everything that needs an owner's decision. Nothing was committed, pushed, merged or deployed. All pre-existing uncommitted work (including `apps/mobile/*` and `apps/api/src/hrms/seed/bootstrap.py`) was left as found, and the whole `docs/api/` package is preserved (untracked).

## 1. Summary

| ID | Finding | Verdict | Status |
|---|---|---|---|
| C-1 | Default `EMPLOYEE` role cannot punch / read attendance / request regularization | **Genuine defect** (also recorded in the project's own product doc as gap A-1) | **Fixed and tested** |
| H-1 | Unbounded collections | **Genuine defect** for the high-volume lists | **Fixed and tested** (11 collections); small master-data lists deliberately unchanged |
| H-2 | No document download / payslip PDF / attachments / photo upload | Capability absent (verified); not required by the current mobile release | **Deferred - product decision** |
| H-3 | Email links cannot open the app | Real gap, partly infrastructural | **Implemented (optional custom-scheme link), tested; HTTPS App Links blocked on deployment** |
| H-4 | Idempotency gaps | Partly genuine (create endpoints), partly already protected by state machines | **Fixed for the genuine gaps; rest classified** |
| H-5 | Mobile source label / offline attendance | **Not a defect**: online-only is the approved behaviour (`DEC-TZ-01`); label cannot be server-validated without attestation | **Documented decision, no code change** |
| H-6 | Face attendance readiness | Disabled by design, fail-closed verified | **Verified; intentionally left disabled** |
| H-7 | No push / in-app notifications | Capability absent; no mobile dependency exists | **Deferred - product decision** |

## 2. Baseline and safety
* Branch `main`; pre-existing changes: 21 modified/untracked mobile files, `bootstrap.py` (a guard that refuses `TRUNCATE` on `hrms_dev`), untracked `docs/api/`. Their diffs are unchanged.
* **Databases.** `hrms_dev` and production were never touched. `hrms_test` (already dirty from the original documentation run: throwaway "Docs …" companies and three hand-inserted `role_permission` rows) was treated as shared state: I applied `alembic upgrade head` to it once (which also exercised the new migration - it backfilled all 11 `EMPLOYEE` roles there) and ran a handful of targeted tests, but did not delete or reset anything. One pre-existing test (`payroll/test_b01_session_commit`) assumes a clean database and failed there because of that leftover data; it is not related to the changes.
* **Full-suite runs used a disposable database** `hrms_remed_20261024` created with the same steps as `run_full_tests.py` (extensions, `hrms_app` role grants, `alembic upgrade head` through the new migration), Redis DB 3, Celery DB 14. It is left in place for inspection and can be dropped with `DROP DATABASE hrms_remed_20261024`.
* Email: `EMAIL_PROVIDER=logging` / capturing senders only. Face: `FACE_VERIFICATION_PROVIDER=disabled`; no Face++ request was made. No payments exist.

## 3. Per-finding detail

### C-1 - employee attendance authorization (fixed)
* **Verified independently** in two ways: a live call (403 for a freshly accepted employee) and code (`organisation/service.py` grants the `EMPLOYEE` role only employee/leave/payslip codes). The self-service routes (`/attendance/punches/me`, `/attendance/face-*/me`, self `POST /regularizations`) are explicitly designed as `SELF`-scoped (router docstrings, product doc §2.2/A-1); leave and payslip self-service already follow the same grant pattern for the same role (Decision 12 / Payroll 5.4). That is why this was treated as an established intent rather than a guess.
* **Fix** (narrowest): grant `ATTENDANCE.PUNCH`, `ATTENDANCE.VIEW`, `ATTENDANCE.REGULARIZATION_REQUEST` at `SELF` to the system `EMPLOYEE` role in `OrganisationService.register_company`, plus migration `20261020090000_employee_role_self_attendance.py` that backfills existing tenants (system `EMPLOYEE` role only, `ON CONFLICT DO NOTHING`, so a customised wider scope is preserved; downgrade removes only SELF grants of those three codes). Precedent: `20261005090000_face_attendance` backfilled a permission the same way. Not granted: `PUNCH_ON_BEHALF`, `VIEW_ALL`, `REGULARIZATION_REQUEST_ON_BEHALF`, any approve/manage/lock/face-manage code. **Production permissions were not modified**; the migration must be reviewed and run through the normal release process.
* **Tests** (`tests/integration/modules/attendance/test_employee_default_role_attendance.py`, 7 tests): registration grants exactly the three SELF codes and no other role gains `PUNCH`; a real invited employee punches IN/OUT and reads only their own punches/days; on-behalf punch, on-behalf regularization and nine HR-only routes (policies, calculate, periods, face admin, rosters, approvals) return 403; cross-tenant (`X-Company-Id` mismatch → 404, foreign employee id → empty) and unauthenticated (401) stay denied; HR_ADMIN / REPORTING_MANAGER / BRANCH_MANAGER still get 403 on self-punch; the backfill SQL restores missing grants, is idempotent and does not overwrite a wider customised scope; face routes stay 503 with the shipped defaults. Existing exact-set assertion in `test_account_invite.py` was updated deliberately.
* **Open decision (not blocked, but unresolved):** the product doc (A-1) also notes `HR_ADMIN` has no attendance view/roster/policy/lock/face-management codes by default. That is a wider policy question I did **not** change; see §6.

### H-1 - bounded list responses (fixed for high-volume collections)
* **Audit of every list route** (inventory + OpenAPI): 11 already paginated (25/100). Unbounded and high-volume - now bounded: `/attendance/punches`, `/attendance/days`, `/rosters`, `/regularizations`, `/overtime`, `/attendance-periods`, `/leave-projections`, `/attendance/face-profiles`, `/payroll/pay-runs`, `/payroll/pay-runs/{id}/employees`, `/payroll/adjustments`. Already paginated and left alone: employees, leave applications/ledger, onboarding cases (the candidate collection), users.
* **Compatibility decision.** The web app calls several of these with no paging parameters, so a 25-row default would silently truncate its screens. The Flutter client already loops `page`/`per_page: 100` until `pagination == null`. I therefore used a dedicated contract: `page ≥ 1`, `per_page` 1-**500**, default **500**, `pagination` always present, out-of-range → 422 (never clamped). A response can never exceed 500 rows; clients that page get the smaller pages they already ask for. Lowering the default is a follow-up once the web screens page.
* Implementation: `shared/pagination.py` (`bounded_pagination_params`, `fetch_page` = count + `LIMIT/OFFSET`), `page_filtered` repository methods built from the same filter statements the unbounded methods use (so filters, scope narrowing and tenant predicates are identical), unique tie-breaker (`id`) appended to every ordering, and the per-day break N+1 in `/attendance/days` replaced by one query. Internal callers of the unbounded repository methods (period validation, calculation) are untouched.
* Tests: `test_bounded_list_pagination.py` - contract on all 11 routes (shape, 422 matrix, 401), and a data test (9 punches incl. an identical-instant pair: partial last page, page past the end, repeatability, filter + paging, tenant isolation, day paging order).
* **Not changed on purpose:** org master-data lists, `/leave-types`, `/leave-policies`, `/me/payslips` (one row per finalised month), employee sub-resource lists and `/employee-imports/{id}/errors`. They are bounded by the nature of the data or by import limits (`MAX_IMPORT_ROWS`); bounding them is cheap later but changes more clients.

### H-3 - email links and mobile navigation
* **Traced end-to-end.** Backend emails embed `{web_app_base_url}/reset-password|verify-email|accept-invite|onboarding/<token>` (4 flows; attendance reminders contain no token). The app registers `hrms://app` on both platforms (`AndroidManifest.xml:31`, `Info.plist` `CFBundleURLSchemes`) and its router resolves `hrms://app/<path>/<token>` (`test/deep_link_test.dart`).
* **Implemented:** `MOBILE_APP_LINK_BASE` setting (empty by default; validated `scheme://host`), `core/links.py`, and a second line in the four emails carrying the *same* token. Default emails are byte-for-byte unchanged.
* **Tests** (`test_mobile_email_links.py`, 5): no app link by default; with the setting, app token == web token for verification, invite and reset, the app token works, is single-use, and a replay is `401 INVALID_TOKEN`; invalid/expired tokens are uniformly rejected (`401` / `404` for invites); setting validation; log redaction covers `hrms://app/<path>/<token>`. A capturing sender replaced the mailer - no email was sent. Token redaction in structured logs already existed (LOG-08) and is covered.
* **Not verified / blocked (deployment):** (a) *App installed* behaviour needs a device/emulator; the router test proves URI resolution only. (b) *Not installed:* a custom scheme does nothing, and some mail clients will not linkify it - the web link is the fallback. (c) **HTTPS App Links / Universal Links** require `/.well-known/assetlinks.json` and `apple-app-site-association` hosted on the web domain, signing fingerprints/Team ID, Android `autoVerify` intent filters and the iOS Associated Domains entitlement. None of that exists in the repo; I did not claim or fake it. Because `apps/mobile` has uncommitted work in progress, I did not edit its manifest.

### H-4 - idempotency and safe retries
Classification of state-changing endpoints:
| Group | Endpoints | Protection |
|---|---|---|
| Already idempotent (DB-backed, atomic claim, fingerprint) | leave application submit, leave adjustments/encashments, payroll adjustments (header required); manual and face punches (own keys) | existing; concurrency covered by existing suites |
| **Genuine gap - duplicate rows on retry** | `POST /employees`, `POST /onboarding-cases` | **now opt-in `Idempotency-Key`** |
| Naturally idempotent via state machine / unique index | approve, reject, cancel, publish, lock-inputs/compute/approve/finalise/mark-paid/rollback (a repeat is a 409 transition error), pay-run create (`PAY_RUN_ALREADY_EXISTS`), roster create (unique employee/date), regularization (one active per date), account invite (revokes prior live invite), registration (409 on existing email) | no change |
| Not addressed | `POST /employee-imports` (a retry creates a second batch; duplicate employees then fail row validation), overtime/period operations | documented; needs a decision on import de-duplication (§6) |
* The existing mechanism (`core/idempotency.py`) provides: atomic claim via unique `(company, operation, key)` insert, concurrent duplicates serialised on the unique index, replay with `Idempotent-Replayed: true`, SHA-256 fingerprint over body + actor, failed attempts roll back the claim so a key is never poisoned, state lives in PostgreSQL so it survives restarts. I reused it unchanged and added `optional_idempotency_key` (absent → old behaviour; malformed → 422).
* Tests (`test_optional_idempotency.py`, 3): no header unchanged; sequential replay returns the identical employee; **6 concurrent identical requests create exactly one row** (5 replays); different body → `409 IDEMPOTENCY_KEY_CONFLICT`; malformed → 422; same key in another tenant independent; failed (422) request does not consume the key; same for onboarding cases.
* **Gap I did not close: retention.** `idempotency_key` rows are never purged, so a key replays forever and the table grows. A retention window is a product/ops decision (§6).

### H-5 - source identification and offline
* `punch.source` is informational: no permission, calculation or policy branches on it (only `_ensure_same_logical_punch` compares it on key replay). The DB constraint already allows `MOBILE`, but any server-side "is this the mobile app" signal would be client-asserted (User-Agent, header) and therefore not trustworthy; real attribution needs app attestation or per-app client credentials. I made **no** code change and did not add a client-supplied source field.
* Offline: `DEC-TZ-01` (server clock authoritative, device time never trusted) is an approved decision, so online-only is the intended behaviour. Documented the client behaviour and a full secure design for the case the owner wants offline capture: [OFFLINE_ATTENDANCE_DESIGN.md](OFFLINE_ATTENDANCE_DESIGN.md). Nothing implemented.

### H-2 / H-7 - missing capabilities (verified absent; not implemented)
| Capability | Verified | Current mobile need | Decision |
|---|---|---|---|
| Document download | No route; `EmployeeDocumentRead` omits storage key; no presign API | App has an employee-documents panel (list/upload/review), no viewer | **Product decision**: define who may view which document, URL lifetime, audit |
| Payslip PDF | `PayslipRead` JSON only | `my_payslips_screen.dart` renders JSON; no PDF dependency in `pubspec.yaml` | **Product decision** (template, legal wording, signing) |
| Leave attachment upload | `attachment_reference` free string | no upload UI | **Product decision** |
| Profile photo upload | `photo_url` free string | none | **Product decision** (storage/moderation) |
| Push / in-app notifications | no device-token or notification model; email only; no FCM/APNs dependency in the app | none | **Product + infrastructure decision** (provider, consent/preferences, retries/dedup) |
No file-handling or notification code was added because requirements, storage policy and external services are not established; the safe-implementation requirements you listed (size/type validation, tenant isolation, no unsafe URLs; retries, dedup, preferences, device registration) are the acceptance criteria to apply when they are.

### H-6 - face attendance
`face_verification_provider` and `face_liveness_engine` default to `disabled`; boot guards refuse to start with the provider enabled without credentials, liveness without model assets, or thresholds that could label a frame both live and spoof. Tests added (`test_face_feature_gates.py`, 4; plus an integration test that an employee who *can* now reach the face routes still gets `503 FACE_*_UNAVAILABLE`). The thresholds remain "uncalibrated engineering defaults" per the settings comment. **Remaining gates before enabling** (not done, not claimed): real-device capture tests (low light, glasses, camera quality), presentation-attack/spoof testing, threshold calibration, privacy/consent and retention review (retention periods are intentionally unset), Face++ account/region and cost, rate/alert monitoring, and a staged rollout. The OpenCV `liveness` extra is not installed in this environment (2 unit tests that need it fail - §5).

## 4. Phase 9/11/12 - contract tests, isolation, documentation
* New reusable helpers `tests/integration/contract_helpers.py` (`assert_error`, `assert_data`, `assert_page`) and `tests/integration/test_api_contract_core.py` (4 tests): request-id echo / validation / replacement (incl. on error bodies), framework 404/405/422 use the same envelope, 401/403/404-tenant/`If-Match` 422 + stale 409 with `context.current` / required-and-malformed idempotency key (using a plain client because the shared test `client` auto-injects keys on those paths), login 429 with `Retry-After`.
* Workflow coverage: registration, verification, login, refresh, logout (`tests/integration/auth`, 60 passed); employee self-punch (new); leave, onboarding, employee import, payroll (module suites below); background-enqueue failure (`IMPORT_QUEUE_UNAVAILABLE`) and document handling are exercised by existing suites. These are **newly executed in this run** (the original audit executed only the auth/route subset and the live recording); they were written by the project, not by this remediation.
* Examples re-recorded against a controlled local server (disposable DB, mocked email, face disabled): 78 calls, regenerated `examples/*.md` - the employee punch now succeeds with no out-of-band SQL; new recorded exchanges: forbidden on-behalf punch, bounded list paging, idempotent employee create / replay / conflict. Source-derived examples in `modules/` remain clearly labelled as not executed.
* Generated artifacts rebuilt (`tools/build_api_docs.py`): 333 operations on 233 paths, route table == `app.openapi()` (the script asserts it). Docs updated: AUTHENTICATION, API_OVERVIEW, API_WORKFLOWS, MOBILE_INTEGRATION_GUIDE, API_CONTRACT_AUDIT (§0.1 status table), README; added this report and OFFLINE_ATTENDANCE_DESIGN.md.

## 5. Exact commands, environment and results
Environment: Python 3.12 venv `apps/api/.venv`, Postgres 16 container `hrms-postgres:5433`, Redis container `:6380`, `ENVIRONMENT=development`, `TZ=UTC`, `EMAIL_PROVIDER=logging`, `FACE_VERIFICATION_PROVIDER=disabled` (forced by `tests/conftest.py`).
```bash
# disposable DB (same steps as run_full_tests.py db-setup)
PGHOST=localhost PGPORT=5433 PGUSER=hrms PGPASSWORD=<dev> psql -d postgres -c "CREATE DATABASE hrms_remed_20261024 OWNER hrms"
psql -d hrms_remed_20261024 -f infra/docker/postgres/init/001_extensions.sql
POSTGRES_USER=hrms POSTGRES_DB=hrms_remed_20261024 HRMS_APP_PASSWORD=<dev> sh infra/docker/postgres/init/002_app_role.sh
export ENVIRONMENT=development DATABASE_URL=postgresql://hrms:<dev>@localhost:5433/hrms_remed_20261024 \
       MIGRATIONS_DATABASE_URL=$DATABASE_URL REDIS_URL=redis://localhost:6380/3 HRMS_TEST_CELERY_DB=14 \
       JWT_ACCESS_SECRET=<test> JWT_REFRESH_SECRET=<test> TZ=UTC
cd apps/api && .venv/bin/python -m alembic upgrade head          # ... -> 20261020090000
.venv/bin/python -m pytest tests/unit tests/security tests/integration/auth tests/integration/core \
    tests/integration/test_*.py tests/integration/modules/<module>   # one invocation per chunk
.venv/bin/ruff check src tests ; .venv/bin/ruff format --check ...
.venv/bin/python -I ../../docs/api/tools/build_api_docs.py        # from repo root
```
Results (actual, final run on the disposable DB, after all code changes):
| Chunk | Result |
|---|---|
| `tests/unit` | 1211 passed, 5 skipped, **2 failed** (`test_liveness.py::test_boot_refuses_enabled_liveness_with_missing_assets`, `::test_boot_with_enabled_liveness_and_verified_assets`) - both need OpenCV (`ModuleNotFoundError: cv2`, the optional `liveness` extra, not installed here); unrelated to these changes |
| `tests/security` | 38 passed |
| `tests/integration/auth` | 60 passed |
| `tests/integration/core` | 92 passed |
| `tests/integration/test_*.py` (incl. route-authorization matrix, robustness, new contract suite) | 31 passed |
| modules: account_invite 90 · employee 387 · employee_import 14 · leave 252 · onboarding 99 · organisation 294 · platform 27 · payroll 68 · attendance 359 | all passed |
| New tests in those totals | 7 (C-1) + 2 (H-1) + 5 (H-3) + 3 (H-4) + 4 (contract) + 4 unit (H-6) + 1 integration (H-6, in C-1 file) |
Static checks: `ruff check src tests` clean and `ruff format --check` clean (497 files); `mypy src/hrms` reports 3 errors, none in files changed by this work: missing optional stubs `cv2`/`numpy` (`liveness.py`) and a type error at `seed/bootstrap.py:135` inside the user's pre-existing uncommitted change (`session.get_bind().url` on `Engine | Connection`) - left untouched. `lint-imports` could not run (its entry-point interpreter path is stale in this checkout); module-dependency rules were respected by keeping shared email helpers in `core/` rather than importing across modules - **import-linter was not executed**.
Earlier (before the disposable DB existed), on `hrms_test`: auth/matrix/robustness 70 passed; attendance+payroll chunk passed until the unrelated dirty-data failure noted in §2.

## 6. Decisions that need an owner
1. **HR_ADMIN attendance scope** (product doc A-1): should `HR_ADMIN` get `ATTENDANCE.VIEW_ALL`, `POLICY_MANAGE`, `ROSTER_MANAGE`, `LOCK`, `FACE_ENROLLMENT_MANAGE` etc. by default? I changed only the employee SELF grants. Also whether `REPORTING_MANAGER` should hold `ATTENDANCE.VIEW` for their reportees.
2. **Existing-tenant backfill release plan** for migration `20261020090000` (it widens permissions for every existing company's `EMPLOYEE` role).
3. **List defaults:** keep default/max 500 on the bounded collections, or schedule a change to 25/100 once the web app pages (breaking for callers that send no parameters).
4. **Idempotency:** retention window for `idempotency_key` rows; whether `POST /employee-imports` needs a client batch key / content-hash de-duplication; whether to make the key mandatory on employee/onboarding creation after clients adopt it.
5. **App/Universal Links:** approve hosting association files on the web domain and obtain signing fingerprints/Team ID; then the Android manifest and iOS entitlements (in `apps/mobile`, which has uncommitted work) can be changed. Decide whether to enable `MOBILE_APP_LINK_BASE=hrms://app` in each environment.
6. **Mobile attendance source / offline:** confirm online-only for the current release; if mobile attribution matters, decide on attestation or a declared-but-untrusted `client_type`. Offline decisions are listed in OFFLINE_ATTENDANCE_DESIGN.md §4.
7. **Documents, payslip PDF, attachments, photos, notifications:** requirement, ownership and provider decisions (§H-2/H-7).
8. **Face attendance:** go/no-go criteria, calibration owner, privacy review, retention periods, provider contract.
9. **Environment values (cannot be invented):** approved staging/production base URLs and `web_app_base_url`; `COMPANY_APPROVAL_REQUIRED` for each environment. See §7.

## 7. Configuration reference (Phase 10)
| Setting | Required? | Default | Behaviour / risk |
|---|---|---|---|
| Staging / production base URL | Needed by the mobile build; **not defined in the repository** | - | Obtain from DevOps; do not hard-code in docs. |
| `WEB_APP_BASE_URL` | **Required outside development** (boot refuses loopback / non-https) | `http://localhost:3000` | Embedded in every token email. Unsafe if wrong (links to the wrong site). |
| `MOBILE_APP_LINK_BASE` (new) | Optional | empty (off) | `hrms://app` today; https only after association files exist. Malformed value → boot error. |
| `COMPANY_APPROVAL_REQUIRED` | Optional | `true` | `true`: new companies are `PENDING_APPROVAL` (read-only) until a platform admin approves - the safe production default; `false` gives an immediate 14-day trial (what the tests use). |
| `FACE_VERIFICATION_PROVIDER`, `FACE_LIVENESS_ENGINE` | Optional | `disabled` | Enabling requires credentials / model assets (boot guards) and the readiness gates in §H-6. Unsafe to enable before calibration. |
| `ALLOWED_COMPANY_TIMEZONES` | Optional | `Asia/Kolkata` | Registration rejects other zones. |
| Accepted regularization `request_type` | n/a | resolved | `MISSING_PUNCH, WRONG_PUNCH, WRONG_SHIFT, WRONG_STATUS, WFH, ON_DUTY, EXCESS_BREAK, FULL_DAY, EARLY_DEPARTURE_APPROVAL` (`attendance/schemas.py:_REGULARIZATION_TYPES`); each company's regularization policy may allow a subset. |

## 8. Final mobile-readiness assessment
| Class | Items |
|---|---|
| **Verified ready** (executed, passing) | Registration → verification → login → refresh (rotation + reuse detection) → logout; account lockout and login rate limit; request-id propagation; error envelope for framework and domain errors; `If-Match` concurrency; required-idempotency enforcement; tenant isolation (header mismatch, cross-tenant lists); invite → accept; employee `/auth/me`; leave, onboarding, employee-import and payroll flows as covered by the project's suites (all passing on a clean DB) |
| **Fixed and tested** | C-1 employee self-service attendance authorization (+ backfill); H-1 bounded lists for 11 collections; H-4 opt-in idempotency for employee/onboarding creation; H-3 optional mobile link in token emails (server side); H-6 face gates stay fail-closed |
| **Implemented but not fully verified** | H-3 deep link end-to-end on a real device (only URI resolution and server output are tested); H-1 behaviour under production-scale data (no load test run); migration `20261020090000` on production-like data volume |
| **Blocked by product / infrastructure decisions** | HTTPS App/Universal Links (hosting + signing); mobile source attribution (needs attestation); offline attendance (needs approval of the design); HR_ADMIN attendance defaults; staging/production URLs; idempotency retention; import de-duplication |
| **Deferred capabilities** | Document download, payslip PDF, leave attachments, profile photo, push and in-app notifications, face attendance enablement, change-password / device-session management / company switch (M-5), sorting & search on lists (M-2) |

**Overall:** the backend is now ready for a mobile client to implement sign-in, session handling, employee self-punch (manual), attendance and leave self-service, payslips (JSON), onboarding links and manager approvals against a deployment that has the migration applied and a real `WEB_APP_BASE_URL`. It is **not** declared production-ready: face attendance, offline punching, document/PDF viewing, push notifications and HTTPS app links remain unbuilt or unverified, no load or device testing was performed, and the items in §6 need owner sign-off.

## 9. Files changed
Source: `core/{idempotency,links,config/settings}.py`, `shared/pagination.py`, `modules/attendance/{repository,service,router,face_service}.py`, `modules/payroll/{repository,service,router}.py`, `modules/employee/router.py`, `modules/onboarding/{router,service,email_templates}.py`, `modules/identity/{service,email_templates}.py`, `modules/account_invite/{service,email_templates}.py`, `modules/organisation/service.py`, migration `alembic/versions/20261020090000_employee_role_self_attendance.py`.
Tests: `tests/integration/contract_helpers.py`, `tests/integration/test_api_contract_core.py`, `modules/attendance/{test_employee_default_role_attendance,test_bounded_list_pagination}.py`, `modules/account_invite/test_mobile_email_links.py`, `modules/employee/test_optional_idempotency.py`, `tests/unit/core/test_face_feature_gates.py`, and one updated assertion in `modules/account_invite/test_account_invite.py`.
Docs: `docs/api/**` (regenerated and extended; still untracked).
