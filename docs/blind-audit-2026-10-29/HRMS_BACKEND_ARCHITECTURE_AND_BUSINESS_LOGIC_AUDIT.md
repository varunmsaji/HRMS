# HRMS Backend Architecture & Business-Logic Audit

## 1. Architecture (confirmed)
Modular monolith: `core/` (config, db, auth, rbac, tenancy, crypto, observability, errors) → `shared/` → `modules/{identity, organisation, employee, attendance, leave, payroll, onboarding, employee_import, account_invite, platform, health}`. Routers → services → repositories, FastAPI `Depends` wiring, Celery workers/beat, S3-compatible storage (MinIO), Redis, SMTP outbox.

Boundary enforcement: `import-linter` with a single **layers** contract (`modules > shared > core`) (`apps/api/.importlinter`) run in CI.

### Size / coupling
| File | Lines |
|---|---|
| attendance/service.py | 6,874 |
| organisation/service.py | 4,509 |
| payroll/service.py | 3,857 |
| employee/service.py | 3,810 |
| leave/service.py | 3,542 |
| attendance/repository.py | 2,772 |

**F-15 (P2, confirmed):** services of 3.5–6.9k lines are hard to review and change safely – the exact condition under which AI-assisted edits regress neighbouring behaviour. The layers contract does **not** stop module↔module imports; the code uses function-local imports across modules (e.g. `identity/service.py` → `employee.service`, comment: "same cross-module-seam convention"). No `independence`/`forbidden` contracts exist, so cycles between feature modules are possible and unmonitored.

## 2. Request trace (representative)
`POST /v1/payroll/pay-runs/{id}/finalise` → router aliases (`_RunApprove` = `require_permission(PAYROLL_RUN_APPROVE)`, `_Tenant`) → `If-Match` parse → idempotency (`run_idempotent`) → `PayRunService.finalise` → advisory locks `payroll-finalise` then shared `attendance-period-close` → state checks → writes → commit in `get_session` → `run_post_commit`. DB trigger rejects later mutation of FINALISED rows. This is a well-layered path with defence in depth (app state machine + lock + trigger).

## 3. Business-rule consistency
| Concern | Observation | Status |
|---|---|---|
| Single source of truth for attendance calc | `attendance/calculation.py` (1,791 lines) with `engine_version` stored per `attendance_day` (migration `20261004095000`) → historical reproducibility | ✔ design; math **not** reviewed |
| Payroll compute | `payroll/engine.py` (701 lines), integer minor units, `rounding_minor` recorded, `attendance_period_version` snapshot on `pay_run` | ✔ design; math **not** reviewed |
| Historical vs current config | policy/shift/salary/leave-policy are **versioned**; day rows store version ids | ✔ |
| Leave ↔ attendance ↔ payroll ordering | `LeaveDayProjection`, shared advisory locks, period-close freeze | ✔ strong |
| State transitions | Explicit lifecycles (`DRAFT→INPUTS_LOCKED→COMPUTED→APPROVED→FINALISED→PAID`), DB trigger backing for final states | ✔ |
| Timezone | `app_timezone_default="Asia/Kolkata"` global; extensive `ATTENDANCE_TIMEZONE_*` docs exist; per-company tz source not verified | **unverified** (F-25, P2) |
| Duplicate logic | Permission gating is implemented three ways: `Depends(require_permission)`, in-handler `rbac.resolve_data_scope`, and aliased `Annotated` deps. All sampled uses are correct, but three idioms raise the chance of a future ungated route; mitigated by `tests/integration/test_route_authorization_matrix.py` and the scope-guard test. | P3 |
| Silent fallbacks | `NEXT_PUBLIC_API_URL ?? "http://localhost:8000"` in three web files (F-13b); `set_rls_company_id(None)` no-op (F-23). | |

## 4. Transactions
* Request = single transaction (good). ~20 explicit mid-request commits exist for legitimate reasons (persist lockout counter, persist reuse-detection revoke, commit-before-enqueue). Documented in comments, but they bypass the "GUC is transaction-local" assumption (**F-02**).
* S3/DB atomicity: `employee/service.py:3662-3663` deletes the S3 object, **then** the DB row and audit entry. If the DB step fails after S3 deletion, the row survives pointing at a missing object (**F-12, P2, confirmed**). Prefer: delete row + audit first, enqueue S3 deletion post-commit (`core/db/post_commit.py` already exists).

## 5. Per-request cost (F-07, P2, needs validation)
Per authenticated request, before business logic: `get_current_user` runs 4 sequential queries (user, session, membership, company); `get_tenant_context` re-fetches membership; `require_permission` runs 1–2 more. ≥6 round trips, and the membership read is duplicated. Safe and secure; measure p95 before optimising (candidate: single joined query or short-TTL cache keyed by session id **with** revocation invalidation).

## 6. Observability (confirmed present)
Structured logging (structlog), request-id context, redaction, security events (`tenant.rejected`, `access_token.rejected`, `authorization.denied`), Prometheus metrics (multiprocess), DB/Celery/storage dependency metrics, file sink, health live/ready. Audit log table with append-only privilege. Good.

## 7. Dead code / config
`ingestion/routes.py` (`GET /ingestion/health`) is unauthenticated and appears vestigial — **unverified purpose**. Repo-root `run_full_tests.py`, `__pycache__`, `mavericks-kit.zip`, `shirt.png` look unrelated to the product (F-17).
