# Production Readiness Checklist

| Field | Value |
|---|---|
| Audit date | 2026-09-10 |
| Commit | `e33fcdb` |
| Parent document | [`PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md`](./PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md) |

Status key: ✅ Done · ⚠️ Partial · ❌ Missing · ⚪ Not applicable yet

**No item is marked ✅ without evidence.**

---

## 1. Architecture & code

| # | Item | Status | Evidence / gap |
|---|---|---|---|
| 1.1 | Clear module boundaries | ✅ | `modules/<name>/{models,schemas,repository,service,router,permissions,exceptions}.py` uniformly |
| 1.2 | Business logic isolated from controllers | ✅ | Routers resolve permissions and delegate; no logic |
| 1.3 | Pure, testable calculation core | ✅ | `attendance/calculation.py` — no DB imports; 362 unit tests in 1.5 s |
| 1.4 | Layering enforced automatically | ⚠️ | `.importlinter` enforces `modules > shared > core` only; module→module edges unconstrained (ARC-002) |
| 1.5 | No circular dependencies | ⚠️ | `leave ↔ attendance` cycle exists, broken only by function-scoped imports |
| 1.6 | No god services | ❌ | `attendance/service.py` 5 480 lines / 9 classes (ARC-001) |
| 1.7 | Single source of truth per concept | ⚠️ | `leave_day_projection` duplicates `leave_application_day` (ARC-003) |
| 1.8 | Lint passing | ✅ | `ruff check` in CI (E, F, I, N, B, UP, BLE, TRY) |
| 1.9 | Format enforced | ✅ | `ruff format --check` in CI |
| 1.10 | Static typing enforced | ✅ | `mypy --strict` on `src/hrms` in CI |
| 1.11 | No dead code | ❌ | `apply_rounding`, `ingestion/routes.py`, `PaginationMeta`, `MoneyAmount`, `get_logger`, `gunicorn` (DEAD-1) |
| 1.12 | **No dead configuration** | ❌ | ~15 policy fields stored, validated, exposed, never read (ATT-001…007, PAY-011) |

## 2. Database

| # | Item | Status | Evidence / gap |
|---|---|---|---|
| 2.1 | All migrations reversible | ⚠️ | Most implement `downgrade()`; the initial revision raises `NotImplementedError` |
| 2.2 | Migrations linear and ordered | ✅ | 61 revisions, unbroken `down_revision` chain |
| 2.3 | Foreign keys present | ✅ | Verified across all audited tables |
| 2.4 | Unique constraints on natural keys | ⚠️ | Present for punch, projection, attendance day, roster, comp-off type — **missing for accrual cycles** (DAT-001) |
| 2.5 | Check constraints encode invariants | ✅ | Employment status/exit-date pairing, non-zero ledger amounts, mutually exclusive roster overrides |
| 2.6 | Overlap prevention on effective-dated rows | ✅ | GiST exclusions on employment, policy assignment, policy versions, attendance period |
| 2.7 | Indexes on tenant + lookup columns | ✅ | `company_id` indexed on every tenant table |
| 2.8 | Safe cascade behaviour | ✅ | No `ON DELETE CASCADE` on any HR fact; `SET NULL` on every `user.id` FK |
| 2.9 | Correct nullability | ✅ | No incorrectly-nullable column identified |
| 2.10 | Timestamps are timezone-aware | ✅ | Every `DateTime(timezone=True)`; no naive column found |
| 2.11 | Money as integer minor units | ✅ | `annual_ctc_minor` `BigInteger` (ADR-0006) |
| 2.12 | Numeric precision adequate | ✅ | `Numeric(6,2)` days, `Numeric(5,4)` multipliers, `Numeric(3,2)` fractions |
| 2.13 | Soft deletion where required | ✅ | `deleted_at` on config entities |
| 2.14 | Append-only facts genuinely immutable | ✅ | 7 tables with no update path and no `updated_at` |
| 2.15 | Audit fields present | ✅ | `created_by`/`updated_by`/`version` on mutable entities |

## 3. Security

| # | Item | Status | Evidence / gap |
|---|---|---|---|
| 3.1 | Passwords hashed with a modern KDF | ✅ | argon2 (`core/auth/passwords.py`) |
| 3.2 | Password policy enforced | ⚠️ | ≥8 chars + letter + digit; no breach check, rotation, or history |
| 3.3 | Refresh-token rotation | ✅ | Every refresh revokes and reissues |
| 3.4 | Refresh reuse detection | ✅ | Replay revokes the entire token family |
| 3.5 | Session revocation honoured per request | ✅ | `core/auth/dependencies.py:34-36` |
| 3.6 | Account lockout | ✅ | 5 failures → 15 minutes |
| 3.7 | No user enumeration | ✅ | Identical message for every failure mode |
| 3.8 | **Rate limiting on auth endpoints** | ❌ | Applied to `/companies/register` only (SEC-002) |
| 3.9 | **CORS correctly configured** | ❌ | Production resolves to zero origins (SEC-001) |
| 3.10 | **Security headers** | ❌ | No HSTS, CSP, nosniff, frame-options (SEC-004) |
| 3.11 | Trusted host validation | ❌ | No `TrustedHostMiddleware` |
| 3.12 | Proxy headers handled | ❌ | Rate limiter keys on the load balancer's IP behind a proxy |
| 3.13 | No SQL injection | ✅ | Parameter binding throughout |
| 3.14 | No XSS in the application | ✅ | React escaping; no `dangerouslySetInnerHTML` |
| 3.15 | File upload validated | ⚠️ | Size and document-type checked; no MIME allow-list, magic bytes, or filename sanitisation (SEC-005) |
| 3.16 | Secrets not committed | ✅ | Verified — only `*.example` templates tracked |
| 3.17 | Secrets managed externally | ❌ | Plain environment variables; no vault or KMS |
| 3.18 | Production guardrail on default secrets | ❌ | Nothing prevents booting with `change-me-…` (PROD-1) |
| 3.19 | No sensitive data in logs | ✅ | No password or token logging found |
| 3.20 | PII encrypted at rest | ❌ | PAN, Aadhaar, UAN, PF, bank details plaintext |
| 3.21 | API docs restricted in production | ❌ | `/docs`, `/redoc`, `/openapi.json` always enabled |
| 3.22 | Dependency vulnerability scanning | ❌ | None (SEC-011) |
| 3.23 | Secret scanning in CI | ❌ | None |
| 3.24 | Container image scanning | ❌ | None |

## 4. Authorization & tenancy

| # | Item | Status | Evidence / gap |
|---|---|---|---|
| 4.1 | Every route authenticated (except intended public ones) | ✅ | 5 intentionally public routes, each with its own boundary |
| 4.2 | Every route permission-gated | ✅ | `require_permission` or an explicit combined-scope resolver |
| 4.3 | Data scope enforced server-side | ✅ | `DataScope` → concrete visible-employee set |
| 4.4 | **Object-level authorization (anti-IDOR)** | ✅ | `_ensure_employee_visible` on the target id, consistently |
| 4.5 | Fail-closed on missing grant | ✅ | Empty scope → `PermissionDeniedError` |
| 4.6 | Out-of-scope indistinguishable from nonexistent | ✅ | Identical 404 |
| 4.7 | Privileged operations separately gated | ✅ | `ATTENDANCE.UNLOCK` distinct from `PERIOD_MANAGE` |
| 4.8 | RLS enabled on tenant tables | ✅ | 70 of 79 |
| 4.9 | Application connects as a non-superuser role | ✅ | `hrms_app` `NOBYPASSRLS` |
| 4.10 | Migration credential separate from runtime | ✅ | `MIGRATIONS_DATABASE_URL`; `Settings` has no field for it |
| 4.11 | Client-supplied tenant id never trusted | ✅ | `X-Company-Id` must match the JWT claim |
| 4.12 | **RLS verified under the runtime role in tests** | ⚠️ | One test file; the rest run as a BYPASSRLS superuser (TEN-002) |
| 4.13 | Background jobs tenant-scoped | ✅ | `session_scope(company_id=…)` per task |

## 5. API

| # | Item | Status | Evidence / gap |
|---|---|---|---|
| 5.1 | Consistent response envelope | ✅ | `DataEnvelope` / `ListEnvelope` + `ResponseMeta` |
| 5.2 | Consistent error envelope with codes | ✅ | `ErrorEnvelope` with `code`, `message`, `details`, `request_id` |
| 5.3 | Request id propagated | ✅ | `X-Request-Id` in and out |
| 5.4 | Input validated | ✅ | Pydantic v2 on every body |
| 5.5 | **Pagination** | ❌ | None anywhere (DAT-002) |
| 5.6 | Filtering | ✅ | Consistent across list endpoints |
| 5.7 | Sorting | ❌ | Not exposed |
| 5.8 | Correct status codes | ✅ | 200/201/204/403/404/409/422/429 |
| 5.9 | Idempotency keys where needed | ⚠️ | Punch only |
| 5.10 | Optimistic concurrency on mutations | ✅ | `expected_version` throughout |
| 5.11 | No sensitive data over-exposure | ✅ | `/auth/me` returns own permissions only |
| 5.12 | No duplicate or orphan endpoints | ⚠️ | `GET /v1/ingestion/health` stub |
| 5.13 | Bulk operations transactional | ✅ | `POST /v1/rosters/bulk` |
| 5.14 | **Batch attendance generation endpoint** | ❌ | Does not exist (PAY-001) |

## 6. Business correctness

| # | Item | Status | Evidence / gap |
|---|---|---|---|
| 6.1 | Policy precedence deterministic | ✅ | One 8-level walk, reused for all six policy kinds |
| 6.2 | Missing configuration fails closed | ✅ | `CONFIG_ERROR` blocks finalization (WD-21) |
| 6.3 | Effective-dated resolution everywhere | ✅ | Employment, assignment, compensation, shift, policy |
| 6.4 | Published policy versions immutable | ✅ | Publish freezes; new version required |
| 6.5 | Version FKs snapshotted on results | ✅ | Six FKs on `attendance_day` |
| 6.6 | **Configured policy is applied policy** | ❌ | ~15 fields never read (ATT-001…007, PAY-011) |
| 6.7 | **Paid-day fraction correct for every status** | ❌ | PAY-004, PAY-006 |
| 6.8 | **LOP fraction correct for every status** | ❌ | PAY-005, PAY-006 |
| 6.9 | Attendance↔Leave precedence defined | ✅ | Every scenario resolves deterministically |
| 6.10 | Leave balance cannot go negative | ❌ | PAY-010 |
| 6.11 | Accrual idempotent under concurrency | ❌ | DAT-001 |
| 6.12 | Corrections never mutate facts | ✅ | Punches, ledger entries, timelines all append-only |
| 6.13 | **Historical results reproducible** | ❌ | PAY-008; also PAY-013 (unguarded timezone change) |
| 6.14 | **Every employee has a compensation record** | ❌ | PAY-014 — never created via onboarding activation |

## 7. Period & lock

| # | Item | Status | Evidence / gap |
|---|---|---|---|
| 7.1 | Period entity with non-overlap guarantee | ✅ | GiST exclusion per company |
| 7.2 | Finalization validates before locking | ✅ | Six blocking reason codes, fail-closed |
| 7.3 | Finalization atomic | ✅ | Version-guarded write first; one transaction |
| 7.4 | Locked days immutable | ✅ | `is_locked` + `_ensure_date_open` — two independent guards |
| 7.5 | Every mutation path respects the lock | ✅ | Punch, roster, regularization, OT, leave sync **and** cancel |
| 7.6 | Reopen separately permissioned | ✅ | `ATTENDANCE.UNLOCK` |
| 7.7 | Reopen requires a reason and is audited | ✅ | `reopen_reason` + action + audit row |
| 7.8 | **Frozen summary is a complete payroll input** | ❌ | PAY-002, PAY-003 |
| 7.9 | **Period finalizable in practice** | ❌ | PAY-001 |
| 7.10 | Leave has a closable period | ❌ | Does not exist (PD-3 open) |

## 8. Testing

| # | Item | Status | Evidence / gap |
|---|---|---|---|
| 8.1 | Unit tests | ✅ | 362, run in 1.5 s |
| 8.2 | Integration tests against a real DB | ✅ | 783 |
| 8.3 | Full suite passes | ✅ | **Verified this audit: `1145 passed in 239.79s`** |
| 8.4 | Permission tests | ✅ | `test_permission_matrix.py`, `test_employee_data_scope.py` |
| 8.5 | Tenant-isolation tests | ⚠️ | Present, but run with RLS bypassed (TEN-002) |
| 8.6 | RLS-under-runtime-role test | ✅ | `tests/security/test_rls_runtime_role.py` |
| 8.7 | Boundary tests | ✅ | Cross-midnight, month-end, leap day |
| 8.8 | **Concurrency tests** | ❌ | None (TST-004) |
| 8.9 | End-to-end tests | ❌ | None |
| 8.10 | Frontend unit tests | ✅ | **Executed: 342 passed in 45 files**; `tsc --noEmit` clean |
| 8.11 | **CI runs the integration suite** | ❌ | No DB service in CI (TST-001) |
| 8.12 | **CI runs the frontend** | ❌ | No frontend job (TST-002) |
| 8.13 | Coverage measured | ❌ | No `pytest-cov`, no threshold (TST-003) |
| 8.14 | Test for the lock-time paid/LOP resolution | ❌ | Missing (PAY-007) |

## 9. Operations

| # | Item | Status | Evidence / gap |
|---|---|---|---|
| 9.1 | CI pipeline | ⚠️ | Exists; incomplete (TST-001, TST-002) |
| 9.2 | **CD pipeline** | ❌ | None (OPS-001) |
| 9.3 | Production container image (API) | ⚠️ | Exists; runs as root, single process, no `HEALTHCHECK` |
| 9.4 | Production container image (web) | ❌ | None |
| 9.5 | Production orchestration manifest | ❌ | None |
| 9.6 | Migration step in the pipeline | ❌ | Never invoked |
| 9.7 | Rollback procedure | ❌ | None |
| 9.8 | Liveness / readiness probes | ❌ | One `/health` with no dependency check |
| 9.9 | Zero/low-downtime deployment | ❌ | Not addressed |
| 9.10 | **Database backups** | ❌ | None (OPS-002) |
| 9.11 | **Restore tested** | ❌ | None |
| 9.12 | RPO / RTO defined | ❌ | None |
| 9.13 | Object-storage backup | ❌ | None |
| 9.14 | **Error tracking** | ❌ | Sentry is a comment; exceptions not even logged (OPS-003) |
| 9.15 | Structured logging in use | ❌ | Configured; `get_logger` has no call sites |
| 9.16 | Request/response logging | ❌ | None |
| 9.17 | Metrics | ❌ | None |
| 9.18 | Alerting | ❌ | None |
| 9.19 | Background-job monitoring | ❌ | None |
| 9.20 | Background-job retries | ❌ | No task has a retry policy |
| 9.25 | Bulk-import job safe against broker redelivery | ❌ | IMP-001 — no re-entry guard |
| 9.21 | Beat single-instance guarantee | ❌ | No leader election (OPS-006) |
| 9.22 | Runbooks | ❌ | None |
| 9.23 | Production seed safety | ❌ | Demo seed has no environment guard (SEED-1) |
| 9.24 | Load / performance testing | ❌ | **PERFORMANCE NOT VERIFIED** |

## 10. Documentation

| # | Item | Status | Evidence / gap |
|---|---|---|---|
| 10.1 | Architecture documentation | ✅ | 16 documents |
| 10.2 | Architecture decision records | ✅ | 15 ADRs |
| 10.3 | Module decision logs | ✅ | WD-01…WD-33, LD-01…LD-23 — numbered, dated, with reasoning |
| 10.4 | Business rules documentation | ✅ | Precedence matrices, scenario catalogues, conflict analyses |
| 10.5 | In-code rationale | ✅ | Unusually strong — most modules explain why, and what was deliberately not built |
| 10.6 | API reference | ⚠️ | Generated OpenAPI only |
| 10.7 | **Documentation matches implementation** | ❌ | Configuration catalogues describe unimplemented behaviour (DOC-001) |
| 10.8 | Deployment documentation | ❌ | None |
| 10.9 | Security documentation | ⚠️ | RLS migration plan only; no threat model |
| 10.10 | Operational runbooks | ❌ | None |
| 10.11 | All documentation tracked in git | ❌ | `docs/business-rules/policies/` untracked (DOC-002) |

---

## Roll-up

| Section | ✅ | ⚠️ | ❌ |
|---|---|---|---|
| 1. Architecture & code | 6 | 4 | 2 |
| 2. Database | 12 | 2 | 0 |
| 3. Security | 9 | 3 | 12 |
| 4. Authorization & tenancy | 11 | 1 | 0 |
| 5. API | 8 | 3 | 3 |
| 6. Business correctness | 7 | 0 | 7 |
| 7. Period & lock | 7 | 0 | 3 |
| 8. Testing | 7 | 1 | 6 |
| 9. Operations | 0 | 2 | 23 |
| 10. Documentation | 5 | 2 | 4 |
| **Total** | **72** | **18** | **60** |

---

## The shape of the result

The distribution is not uniform, and that is the most useful thing in this checklist.

**Database (12/14), authorization and tenancy (11/12), and API contract discipline are close to
production-grade.** These are the areas that are hardest to retrofit, and they were done well.

**Operations is 0 of 24.** Not weak — absent. There is no deployment pipeline, no backup, no monitoring,
no alerting, no runbook. This is the single largest block of work standing between the current state and
a production system, and none of it is technically difficult; it simply has not been started.

**Business correctness is 7 of 14.** Six failures are in the paid-days / LOP / policy-application chain —
precisely the chain Payroll exists to consume. The seventh, found on a dedicated onboarding review, is
that employees hired through the wizard never receive a compensation record at all.

**Security is 9 ✅ / 12 ❌**, but the split matters: everything *structural* (hashing, token rotation,
reuse detection, lockout, RLS, object-level authorization, injection resistance) passes. Everything
*missing* is a hardening layer that can be added without touching the application's logic.

**Priority order is therefore: business correctness (P0) → CI (P0) → operations (P2) → security hardening
(P2) → the rest.**

---

*No application code, schema, migration, test, or configuration was modified during this audit.*
