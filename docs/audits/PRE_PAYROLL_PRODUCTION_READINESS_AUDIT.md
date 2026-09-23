# Pre-Payroll Production Readiness Audit

| Field | Value |
|---|---|
| Audit date | 2026-09-10 |
| Repository | `staff-spectrum/HRMS` |
| Commit at audit | `e33fcdb` — `feat(employee): confirmation workflow (PROBATION -> ACTIVE)` |
| Branch | `main` |
| Scope | Everything merged before Payroll development begins |
| Method | Direct source inspection + full local test-suite execution. No code was modified. |
| Verdict | 🟠 **NOT READY — FOUNDATION FIXES REQUIRED** |

**Evidence rule applied throughout:** no status is asserted without a file/line, a command output, or an
executed test result. Where behaviour could not be verified, it is recorded as *not verified* rather than
assumed.

---

## Audit coverage

Every module completed before Payroll was inspected. Depth varied by payroll relevance, and is
stated here so no area is silently assumed.

| Area | Depth | What was read |
|---|---|---|
| Attendance — calculation engine | **Full** | `calculation.py` (1 520 lines) read end to end |
| Attendance — orchestration, period, lock, OT, regularization, projection | **Full** | `service.py` (5 480 lines) — all payroll-relevant paths; `models.py`, `repository.py` key methods |
| Leave — models, applications, approval, accrual, comp-off, tasks | **Full** | `models.py`, `service.py` critical paths, `tasks.py`, `year.py` |
| Core — auth, RBAC, tenancy, session, audit, errors, config, rate limit | **Full** | Every file read |
| Calendar & policy precedence | **Full** | `calendar_resolution.py` (456 lines) read end to end; `resolution.py` |
| Employee — employment, assignment, data scope | **Full** | As-of contracts, `resolve_visible_employee_ids`, models |
| Organisation — CRUD services | **Full** (second pass) | `service.py` (3 895 lines) — registration, profile, shift publish validation, policy-assignment validation, branch/department/designation/grade/calendar paths |
| Employee import | **Full** (second pass) | `service.py`, `tasks.py`, `router.py`, `schemas.py` |
| Onboarding | **Full** (second pass) | Token service, public router, document upload, review loop, activation (O7) |
| Database — 79 tables, 61 migrations, RLS | **Full** | Coverage computed programmatically |
| Frontend | **Full** (second pass) | Structure, auth layer, API client; **suite executed**, `tsc --noEmit` executed |
| CI/CD, deployment, infra | **Full** | Every file read |

**Executed during this audit:**

```
apps/api $ .venv/bin/python -m pytest tests -q
1145 passed in 239.79s

apps/web $ npx vitest run
Test Files  45 passed (45)      Tests  342 passed (342)      Duration 8.85s

apps/web $ npx tsc --noEmit
(clean — exit 0)
```

The second pass added six findings not visible from the payroll-critical path alone: **PAY-013**
(unguarded timezone change), **PAY-014** (onboarding creates no compensation record), and **IMP-001…004**
(bulk-import job safety). It also produced direct corroboration for **PAY-007**.

---

## Table of contents

1. [Repository map](#part-1--repository-map)
2. [Module inventory](#part-2--module-inventory)
3. [Production readiness scorecard](#part-3--production-readiness-scorecard)
4. [Architecture review](#part-4--architecture-review)
5. [Payroll foundation audit](#part-5--payroll-foundation-audit)
6. [Attendance audit](#part-6--attendance-audit)
7. [Attendance reproducibility](#part-7--attendance-calculation-reproducibility)
8. [Leave audit](#part-8--leave-audit)
9. [Attendance ↔ Leave audit](#part-9--attendance--leave-audit)
10. [Policy precedence audit](#part-10--policy-precedence-audit)
11. [Database audit](#part-11--database-audit)
12. [Multi-tenant isolation](#part-12--multi-tenant-isolation)
13. [Authorization audit](#part-13--authorization-audit)
14. [API audit](#part-14--api-audit)
15. [Frontend audit](#part-15--frontend-audit)
16. [Transaction & concurrency](#part-16--transaction--concurrency-audit)
17. [Idempotency](#part-17--idempotency-audit)
18. [Money / numeric safety](#part-18--money--numeric-safety)
19. [Timezone and date audit](#part-19--timezone-and-date-audit)
20. [Audit logging](#part-20--audit-logging)
21. [Historical data integrity](#part-21--historical-data-integrity)
22. [Period finalization and locking](#part-22--period-finalization-and-locking)
23. [Test audit](#part-23--test-audit)
24. [Testing the tests](#part-24--test-the-tests)
25. [Error handling](#part-25--error-handling)
26. [Background jobs](#part-26--background-jobs)
27. [Performance](#part-27--performance-audit)
28. [Security](#part-28--security-audit)
29. [Secrets & configuration](#part-29--secrets--configuration)
30. [Deployment](#part-30--deployment-audit)
31. [Backup & disaster recovery](#part-31--backup--disaster-recovery)
32. [Observability](#part-32--observability)
33. [Data migration & seeding](#part-33--data-migration--seeding)
34. [Documentation](#part-34--documentation-audit)
35. [Code quality](#part-35--code-quality-review)
36. [Technical debt](#part-36--technical-debt)
37. [Payroll blocker analysis](#part-37--payroll-blocker-analysis)
38. [Production readiness gates](#part-38--production-readiness-gates)
39. [Final recommendation](#part-39--final-recommendation)
40. [Remediation plan](#part-40--prioritized-remediation-plan)
41. [Payroll readiness contract](#part-41--payroll-readiness-contract)
42. [What Payroll must not assume](#part-42--what-payroll-should-not-assume)
43. [Final audit questions](#final-audit-questions)

---

## PART 1 — Repository map

```
HRMS/
├── apps/
│   ├── api/                       FastAPI modular monolith (Python 3.12)
│   │   ├── src/hrms/
│   │   │   ├── core/              auth · rbac · tenancy · db · audit · errors · config · observability
│   │   │   ├── shared/            pagination envelopes · rate_limit · value_objects
│   │   │   ├── modules/           identity · organisation · employee · employee_import
│   │   │   │                      attendance · leave · onboarding · health
│   │   │   ├── ingestion/         stub (health route only)
│   │   │   └── seed/              permission catalogue + demo bootstrap
│   │   ├── alembic/versions/      61 migrations
│   │   ├── scripts/sql/           001_init_schema · 002_row_level_security · 003_effective_dating
│   │   ├── entrypoints/           api · worker · beat · ingestion
│   │   └── tests/                 unit (25) · integration (60) · security (2)
│   └── web/                       Next.js 14 App Router + Tailwind + Radix (278 ts/tsx, 45 vitest files)
├── docs/                          211 markdown documents (adr · architecture · business-rules · modules)
├── infra/docker/postgres/init/    extensions + dedicated hrms_app runtime role
├── .github/workflows/ci.yml       single job: API lint/typecheck/boundaries/test
├── docker-compose.yml             postgres:16 · redis:7 · minio (local dev only)
└── scripts/dev.py, dev.sh         local stack launcher
```

**Measured size** — `find src -name "*.py" | xargs wc -l` → **43 174** lines across 120 files;
tests → **39 434** lines across 112 files.

| Concern | Present? | Evidence |
|---|---|---|
| Backend | ✅ | `apps/api/src/hrms` |
| Frontend | ✅ | `apps/web/src` |
| Database | ✅ | PostgreSQL 16, `docker-compose.yml:4-23` |
| Migrations | ✅ | 61 Alembic revisions, `apps/api/alembic/versions/` |
| Tests | ✅ | 1 145 tests, all passing locally (verified this audit) |
| Config / env handling | ✅ | `core/config/settings.py` (pydantic-settings, boot-validated) |
| Background jobs | ⚠️ Partial | Celery + Beat; **only Leave and employee-import have real tasks** |
| Scheduled tasks | ⚠️ Partial | 4 Beat entries, all Leave (`core/celery_app.py:29-50`) |
| Queues | ✅ | Redis broker, `default` + `reports_exports` queues |
| External integrations | ⚠️ Minimal | S3/MinIO (`core/storage.py`), SES (defaults to logging-only sender) |
| Authentication | ✅ | JWT HS256 + rotating refresh family, argon2 (`core/auth/`) |
| Authorization | ✅ | Permission codes + `DataScope` levels (`core/rbac/`) |
| File storage | ✅ | `core/storage.py` (aioboto3) |
| Notifications | ❌ | No notification module. Email sender is logging-only by default. |
| Logging | ✅ | structlog JSON to stdout (`core/observability/logging.py`) |
| Monitoring | ❌ | None. Sentry is a code comment (`core/errors/handlers.py:79`) |
| Deployment | ❌ | One API Dockerfile only. No CD, no web image, no prod compose. |
| Docker | ⚠️ Dev only | `docker-compose.yml` is a local dev stack |
| CI/CD | ⚠️ CI only, incomplete | See [TST-001](#part-23--test-audit) |
| Documentation | ✅ Extensive | 211 markdown files |

---

## PART 2 — Module inventory

Status key: **Complete** = feature-complete for its stated slice · **Partial** = shipped but with
documented or discovered gaps · **Contract only** = schema/API exist, no engine reads them.

| Module | Purpose | Implementation status | Test coverage | Production risk | Payroll dependency |
|---|---|---|---|---|---|
| Authentication | Login, refresh rotation, logout, lockout | Complete | Integration + `tests/security/` | 🟡 no rate limit on login (SEC-002) | Indirect |
| User Management | Users, sessions, memberships | Complete | Integration | 🟡 no password reset / MFA | Indirect |
| Roles & Permissions | Permission codes + 4 `DataScope` levels | Complete | `test_permission_matrix.py`, `test_employee_data_scope.py` | 🟢 | Indirect |
| Organization (Company) | Profile, setup progress, plans, feature flags | Complete | Integration | 🟢 | 🔴 Company timezone |
| Legal Entity | Statutory employer entity | Complete | Integration | 🟢 | 🔴 PF/ESI/TDS entity grain |
| Branch / Location | Branch + **timezone** | Complete | Integration | 🟢 | 🟠 Timezone resolution |
| Department | Hierarchy + `head_employee_id` | Complete | Integration | 🟢 | 🟡 Cost allocation |
| Designation | Effective-dated, `next_designation_id` | Complete | Integration | 🟢 | 🟡 |
| Grade | Bands | Complete | Integration | 🟢 | 🟠 Grade-based pay bands |
| Employee Management | Identity, statutory, bank, compensation | Complete | 8 integration files | 🟢 | 🔴 All identity inputs |
| Employment | Spells, joining/exit, GiST no-overlap | Complete | `test_employment.py` | 🟢 | 🔴 Paid-day window |
| Employee Assignment | Branch/dept/desig/grade/shift/manager over time | Complete | `test_employee_assignment.py` | 🟢 | 🔴 Policy resolution basis |
| Employee Import | CSV bulk import via Celery | **Partial** (IMP-001…004) | Integration | 🟠 no re-entry guard on an at-least-once queue | Indirect |
| Onboarding | Case → token → wizard → review → activation | **Partial** (PAY-014) | 7 integration files | 🟠 **activation creates no compensation record** | 🔴 **CTC missing for onboarded staff** |
| Holiday Calendar | Calendars, holidays, types | Complete | Integration | 🟢 | 🟠 Holiday pay |
| Weekly Off Pattern | Fixed / nth / alternate / custom rules | **Partial** — `off_fraction` discarded (PAY-012) | Unit + integration | 🟠 | 🟠 Half-day weekly off |
| Work Calendar | Composition + exceptions + precedence | Complete | Unit + integration | 🟢 | 🔴 Day classification |
| Shift / Shift Version | FIXED · FLEXIBLE · SPLIT, breaks, duty blocks | Complete | Unit + integration | 🟢 | 🔴 Scheduled minutes |
| Roster | Per-employee-per-date override, DRAFT/PUBLISHED | Complete | `test_shift_roster.py` | 🟢 | 🟠 |
| Attendance Policy | Versioned rule config | **Partial — see below** | Integration | 🟠 **many fields inert** | 🔴 |
| Attendance (calculation) | Punch → AttendanceDay | **Partial** (ATT-001…013) | Unit + integration | 🟠 | 🔴 paid days / LOP |
| Overtime | Detection + approval + comp-off | **Partial** (ATT-005) | `test_overtime_record.py` | 🟠 | 🔴 OT minutes |
| Regularization | Request → approve → synthetic punches | Complete | `test_regularization.py` | 🟢 | 🟠 |
| Period Lock | Create · validate · finalize · reopen | **Partial** (PAY-002/003/007) | `test_attendance_period.py` | 🔴 | 🔴 Frozen input |
| Leave Types / Policies | Versioned, statutory-minimum check | Complete | Integration | 🟢 | 🟠 |
| Leave Ledger | Append-only balance | Complete | `test_leave_ledger.py` | 🟢 | 🔴 Balance |
| Leave Accrual | Monthly + yearly + carry-forward cap | **Partial** (DAT-001) | `test_leave_accrual.py`, `test_leave_year.py` | 🟠 | 🟠 |
| Leave Application | Submit → multi-stage approval → projection | **Partial** (PAY-010) | 4 integration files | 🟠 | 🔴 Paid/unpaid leave days |
| Comp-off | Credit + expiry sweeps | Complete | `test_leave_comp_off.py` | 🟡 | 🟠 |
| Encashment | Policy-validated ledger debit | Complete | `test_leave_encashment.py` | 🟡 | 🟠 Encashment payout |
| Audit Logs | `audit_log` write path | **Contract only for reads** — no read API/UI | Indirect | 🟡 | 🟠 Evidence |
| Notifications | — | ❌ **Not built** | — | 🟠 | Indirect |
| Documents | Onboarding docs only | Partial | Integration | 🟡 | Indirect |
| Reports | ❌ Not built | — | — | 🟡 | 🟠 |
| Settings | Per-module config screens | Complete | Frontend | 🟢 | Indirect |
| Payroll | — | ❌ Not started (this gate) | — | — | — |

---

## PART 3 — Production readiness scorecard

🟢 READY · 🟡 READY WITH CONDITIONS · 🟠 NEEDS FIX BEFORE PAYROLL · 🔴 BLOCKER · ⚪ N/A

| # | Area | Status | Risk | Evidence | Required action |
|---|---|---|---|---|---|
| 1 | Architecture | 🟡 | Low | Pure engine split (`attendance/calculation.py`) from orchestration (`service.py`); import-linter layers contract (`.importlinter`) | Constrain module→module edges (ARC-002) |
| 2 | Code quality | 🟡 | Med | `attendance/service.py` 5 480 lines / 9 classes; ruff + mypy `strict` pass in CI | Split god-service; no rewrite |
| 3 | Database | 🟢 | Low | 61 migrations, GiST exclusions, CHECK constraints, partial unique indexes | — |
| 4 | Data integrity | 🟠 | High | Append-only ledger/punch ✅; but accrual check-then-insert has no unique index (DAT-001) | Add uniqueness |
| 5 | Business rules | 🟠 | High | ~15 configurable policy fields stored/validated/exposed but **never read** (ATT-001…007) | Implement or remove + document |
| 6 | Attendance | 🟠 | High | See [Part 6](#part-6--attendance-audit) | Fix paid/LOP semantics, bulk generation |
| 7 | Leave | 🟠 | High | Balance checked at submit only (PAY-010); accrual race (DAT-001) | Re-check at approve; add constraint |
| 8 | Security | 🟠 | High | CORS unusable in prod (SEC-001); rate limit on 1 of ~150 endpoints (SEC-002) | Fix before any deploy |
| 9 | Authorization | 🟢 | Low | `require_permission` + `DataScope` + `_ensure_employee_visible` on target IDs, consistently | — |
| 10 | Tenant isolation | 🟡 | Med | 70/79 tables RLS-enforced; non-superuser `hrms_app` role; header verified against JWT | Run the suite as `hrms_app` (TEN-002) |
| 11 | API correctness | 🟠 | Med | Consistent envelopes + error handler; **zero pagination** (DAT-002) | Add pagination before volume |
| 12 | Frontend correctness | 🟡 | Med | 45 vitest files, permission-aware UI; tokens in `localStorage` (SEC-003) | Not payroll-blocking |
| 13 | Testing | 🔴 | **Critical** | **CI runs no integration/security tests** (TST-001) | Add DB service to CI |
| 14 | Error handling | 🟢 | Low | Global handlers, typed `AppError`, request-id in every envelope | — |
| 15 | Transactions | 🟢 | Low | Request-scoped session, commit-on-success / rollback-on-exception (`core/db/session.py:63-68`) | — |
| 16 | Concurrency | 🟡 | Med | `expected_version` optimistic locking on every workflow entity; no row locks, no concurrency tests | Add tests (TST-004) |
| 17 | Idempotency | 🟠 | High | Punch idempotency key ✅; accrual/comp-off idempotent by check ⚠️; `calculate()` **not** idempotent (PAY-008) | See Part 17 |
| 18 | Logging | 🟡 | Med | structlog JSON, no request/response middleware logging, no log shipping | — |
| 19 | Auditability | 🟡 | Med | `AuditService.record` at every mutation + per-entity action timelines; **no read API/UI** | Expose audit read |
| 20 | Monitoring | 🔴 | Critical | None (OPS-003) | Required before production |
| 21 | Backups | 🔴 | Critical | Nothing in repo (OPS-002) | Required before production |
| 22 | Recovery | 🔴 | Critical | No restore test, no RPO/RTO | Required before production |
| 23 | Deployment | 🔴 | Critical | No CD, no prod image for web, no migration step (OPS-001) | Required before production |
| 24 | CI/CD | 🔴 | Critical | Single incomplete CI job (TST-001, TST-002) | Fix CI |
| 25 | Configuration | 🟢 | Low | pydantic-settings, boot-validated, 4 per-env `.env.*.example` templates | — |
| 26 | Secrets | 🟢 | Low | `.gitignore` excludes `.env*`; no secrets tracked (verified by `git ls-files` scan) | Rotate dev defaults for prod |
| 27 | Performance | 🟠 | High | No benchmarks. **PERFORMANCE NOT VERIFIED.** N+1s + unbounded lists (DAT-002/003) | Load-test before payroll volume |
| 28 | Scalability | 🟠 | High | Per-employee-per-date synchronous calculation, no batch path (PAY-001) | Build batch engine |
| 29 | Documentation | 🟡 | Med | 211 docs, but configuration catalogues describe inert fields (DOC-001) | Reconcile |
| 30 | Operational readiness | 🔴 | Critical | No runbooks, no on-call, no alerting, no health/readiness split | Required before production |

---

## PART 4 — Architecture review

**Determinations**

| Question | Answer | Evidence |
|---|---|---|
| Is module separation clear? | Yes | `src/hrms/modules/<name>/{models,schemas,repository,service,router,permissions,exceptions}.py` uniformly |
| Are business rules isolated? | **Partially** | `attendance/calculation.py` is pure and DB-free ✅; `organisation/calendar_resolution.py` splits pure classification from DB walk ✅; Leave rules live inline in `leave/service.py` ❌ |
| Are domain boundaries clear? | Yes, by convention | Cross-module access is via `other_module.service`, never repositories |
| Excessive coupling? | Yes, in one direction | `attendance.service` imports `employee.service`, `organisation.service`, `organisation.calendar_resolution`; `leave.service` imports `attendance.service` **and** `attendance.schemas` |
| Business logic in controllers? | No | Routers are thin; permission resolution + delegation only |
| Duplicated business logic? | Yes, deliberately | Approval state machines are "mirrored not shared" across Regularization / Overtime / Leave (LD-05) — 3 near-identical implementations |
| Circular dependencies? | Runtime-avoided | `leave.service` ↔ `attendance.service` is a genuine cycle, broken only by function-scoped imports |
| Attendance and Leave separated? | Yes | Leave never writes `attendance_day`; Attendance never writes `leave_ledger` |
| Can Payroll consume cleanly? | **No, not yet** | `AttendancePeriodSummary` lacks paid days (PAY-002) and mis-aggregates (PAY-003) |
| Multiple calculation engines? | No | One `evaluate_day` |
| Duplicated models? | Yes, one | `LeaveDayProjection` (attendance) duplicates `LeaveApplicationDay` (leave) |
| Duplicated status definitions? | Yes | `FIRST_HALF/SECOND_HALF` (leave) vs `FIRST/SECOND` (attendance), translated at the boundary (`leave/service.py:2423`) |

### Architecture findings

| ID | Finding | Severity | Evidence | Payroll impact | Recommendation |
|---|---|---|---|---|---|
| ARC-001 | God service | 🟡 HIGH | `attendance/service.py` = 5 480 lines, 9 service classes; `organisation/service.py` = 3 895 | Slows Payroll integration; raises regression risk | Split by aggregate (policy / roster / day / regularization / overtime / period / projection). Do **not** rewrite logic. |
| ARC-002 | Unconstrained module→module edges | 🟡 HIGH | `.importlinter` declares only `hrms.modules > hrms.shared > hrms.core`; nothing restricts sibling imports. Function-scoped imports hide the cycle from static tooling | Payroll will import 4 modules with no contract | Add `independence` or `forbidden` contracts naming allowed seams |
| ARC-003 | Duplicate source of truth for approved leave | 🟡 HIGH | `LeaveDayProjection` (`attendance/models.py:976`) vs `LeaveApplicationDay` (`leave/models.py:314`); kept in sync only by `_apply_approval`/`_reverse_approval` | Payroll could read either and get different answers | Declare `LeaveDayProjection` the Payroll-facing read model; add a reconciliation check |
| ARC-004 | Synchronous cross-module recompute | 🔵 MEDIUM | `LeaveProjectionService.sync` → `AttendanceDayService.calculate` per day (`attendance/service.py:5349`); ADR-0012 outbox unimplemented | A 30-day leave approval = 30 full recomputes in one HTTP request | Acceptable now; move to outbox before volume |
| ARC-005 | Pure-engine split | 🟢 STRENGTH | `calculation.py` is import-free of SQLAlchemy; 362 unit tests run in 1.5 s | Makes Payroll's own engine testable the same way | Reuse this pattern for Payroll |

---

## PART 5 — Payroll foundation audit

Definitions: **Authoritative** = one unambiguous source · **Immutable after finalization** = cannot change
once the period is `CLOSED` · **Auditable** = who/what/when recoverable · **Historical-safe** = re-reading
the same period tomorrow yields the same value.

### Payroll input readiness matrix

| Payroll input | Source module | Source of truth | Finalized? | Auditable? | Historical safe? | Payroll ready? |
|---|---|---|---|---|---|---|
| Employee identity | employee | `employee` | n/a | ✅ `audit_log` | ✅ | 🟢 Yes |
| Employment status | employee | `employment.status` (`ACTIVE`/`TERMINATED`, CHECK) | n/a | ✅ | ✅ | 🟢 Yes |
| Joining date | employee | `employment.joining_date` + GiST no-overlap | n/a | ✅ | ✅ | 🟢 Yes |
| Exit date | employee | `employment.last_working_day` (CHECK-tied to status) | n/a | ✅ | ✅ | 🟢 Yes |
| Employment type | employee | `employee.status` (`PROBATION`/`ACTIVE`/…) | n/a | ✅ | ⚠️ current value only, not as-of | 🟡 Conditional |
| Department / Designation / Grade / Branch | employee | `employee_assignment` effective-dated | n/a | ✅ | ✅ `get_assignment_as_of` | 🟢 Yes |
| Shift | employee + attendance | `shift_roster` (PUBLISHED) > `employee_assignment.shift_id` | ✅ via `attendance_day.shift_version_id` | ✅ | ✅ | 🟢 Yes |
| Attendance status | attendance | `attendance_day.attendance_status` | ✅ `is_locked` | ✅ snapshot + `audit_log` | 🟠 see PAY-008 | 🟠 Conditional |
| **Paid days** | attendance | `attendance_day.paid_day_fraction` | ✅ locked | ✅ | 🟠 | 🔴 **No** — not in the frozen summary (PAY-002); wrong for NOT_JOINED (PAY-004) |
| **LOP** | attendance | `attendance_day.lop_fraction` → `summary.lop_days` | ✅ | ✅ | 🟠 | 🔴 **No** — wrong for EXITED (PAY-005), INCOMPLETE unresolved until lock (PAY-006) |
| Leave (days consumed) | leave + attendance | `leave_day_projection` (Payroll-facing) / `leave_application_day` | ✅ lock-guarded (`_ensure_date_open`) | ✅ | ✅ | 🟡 Conditional — pick one source (ARC-003) |
| Leave balance | leave | `SUM(leave_ledger.amount)` | ❌ never frozen | ✅ append-only | ⚠️ derived live, changes with any new row | 🟠 Conditional |
| Overtime minutes | attendance | `overtime_record.minutes_approved` → `summary.ot_minutes_*` | ✅ frozen at close | ✅ `overtime_action` timeline | ⚠️ night classification wrong (ATT-005) | 🟠 Conditional |
| OT rate multiplier | attendance | `overtime_record.configured_multiplier` | ✅ snapshotted | ✅ | ✅ | 🟢 Yes — **informational only** (ADR-0006) |
| Comp-off earned | attendance + leave | `overtime_record.comp_off_minutes` → `leave_ledger` `COMP_OFF_CREDIT` | ✅ | ✅ | ✅ | 🟡 Conditional — requires `comp_off_day_length_minutes` set |
| Holiday | organisation | `work_calendar` composition → `attendance_day.calendar_day_type` | ✅ | ✅ | ✅ | 🟢 Yes |
| Weekly off | organisation | `weekly_off_pattern` rules | ✅ | ✅ | ⚠️ `off_fraction` discarded (PAY-012) | 🟡 Conditional |
| Regularization | attendance | Synthetic `punch` rows + `attendance_regularization_action` | ✅ lock-guarded | ✅ | ✅ | 🟢 Yes |
| Period lock | attendance | `attendance_period.status='CLOSED'` + `attendance_day.is_locked` | ✅ | ✅ `attendance_period_action` | ✅ | 🟢 Yes — mechanism is sound |
| Approval state | attendance + leave | per-entity `status`/`approval_stage` + action timelines | ✅ | ✅ | ✅ | 🟢 Yes |
| CTC / compensation | employee | `employee_compensation.annual_ctc_minor` (BigInteger, ADR-0006) | effective-dated | ✅ | ✅ | 🟠 **Conditional — never created for employees activated through onboarding (PAY-014)** |
| Company / branch timezone | organisation | `company.timezone`, `branch.timezone` | ❌ **mutable, unguarded** | ✅ audited | ❌ **a change alters unlocked historical attendance** | 🟠 **PAY-013** |

**Nine-point assessment of the critical inputs**

| Input | Authoritative | Immutable post-final | Auditable | Recalculable | Historically reproducible | Effective-dated | Policy change can corrupt history | Normalized | Duplicate sources |
|---|---|---|---|---|---|---|---|---|---|
| Paid days | ⚠️ two candidates | ✅ | ✅ | ✅ | ❌ | ✅ | ⚠️ only via backdated version publish | ✅ | ⚠️ day rows vs summary |
| LOP | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ⚠️ same | ✅ | ⚠️ same |
| Leave balance | ✅ | ❌ never frozen | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| OT approved | ✅ | ✅ | ✅ | ⚠️ frozen once terminal | ✅ | ✅ | ❌ | ✅ | ❌ |
| Leave days | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ two tables |

---

## PART 6 — Attendance audit

Verified against the implementation, not the documentation.

| Rule | Where implemented | Verified behaviour | Status |
|---|---|---|---|
| Attendance generation | `AttendanceDayService.calculate` (`service.py:2483`) | One employee, one date, one HTTP call. **No batch, no job.** | 🔴 PAY-001 |
| Date generation | Caller-supplied `target_date` | No date-range generator exists | 🔴 PAY-001 |
| Employee eligibility | `_build_calculation_input:2732-2741` | `get_employment_as_of` → ACTIVE; else `get_latest_employment_on_or_before` → EXITED/NOT_JOINED | 🟢 |
| Employment period | Same | Correct three-way gate | 🟢 |
| Calendar | `CalendarResolutionService.resolve_for_employee` | 8-level precedence, fails closed to `config_incomplete` | 🟢 |
| Holiday | `classify_work_calendar_date:130-233` | Exception > holiday union (first-list-wins) > weekly-off > WORKING | 🟢 |
| Weekly off | `evaluate_weekly_off:120-127` | Fixed/nth/last/alternate; **`off_fraction` returned then discarded at line 140** | 🟠 PAY-012 |
| Shift | `_build_calculation_input:2777-2836` | `resolve_shift_version_as_of` by date; version id snapshotted | 🟢 |
| Roster | `:2758-2766` | PUBLISHED only; DRAFT invisible to calculation | 🟢 |
| Punch ingestion | `PunchService.record_punch:2300` | Append-only; `_ensure_employee_visible` on target; period-lock checked | 🟢 |
| Punch validation | `schemas.py` + DB CHECK | Direction IN/OUT, source enum | 🟢 |
| Punch dedup | `collapse_duplicate_punches:468` | Same-direction within `duplicate_punch_window_seconds` collapses to first | 🟢 |
| IN/OUT pairing | `pair_punches:491` | Deterministic; consecutive INs orphan the earlier; trailing IN orphans | 🟢 |
| Cross-midnight | `punch_window_utc:310` / `scheduled_span_utc:333` | ±2 h padding; end rolled +1 day when `is_cross_midnight` | 🟢 |
| Worked minutes | `presence_span:520` + `worked_minutes_from_gross:550` | `PAIR_ALL` sums pairs then **adds back** paid breaks; `FIRST_IN_LAST_OUT` subtracts unpaid. Arithmetic is correct and documented. | 🟢 |
| Break calculation | `match_breaks:574` | Matches **gap start** local time-of-day against break windows only | 🟡 ATT-009 |
| Scheduled break with no punched gap | — | **Never deducted** (documented limitation, `calculation.py:23-28`) | 🟡 ATT-008 |
| Late | `_evaluate_fixed_or_flex:1146-1150` | `first_in - scheduled_start - grace_in`, banded | 🟢 |
| Early departure | `:1152-1166` | `scheduled_end - last_out - grace_out`, banded; unapproved forced to harshest configured band | 🟢 |
| Grace | `PolicyInputs.grace_in/out_minutes` | Applied | 🟢 |
| Punch rounding | `apply_rounding:637` | **Function has zero call sites.** Config is inert. | 🟠 ATT-001 |
| Status calculation | `_resolve_primary_status:1447` | worked==0 → NOT_EXPECTED / INCOMPLETE / ABSENT; then bands; then overrides | 🟢 |
| Half-day split | `half_day_split`, `half_day_boundary_minutes` | Passed into `PolicyInputs`, **never read**. Half-day comes only from hour bands. | 🟠 ATT-003 |
| Paid day | `_paid_lop_fraction:1510` | PRESENT 1.00 · HALF_DAY 0.50 · ABSENT 0.00 · NOT_EXPECTED 1.00 · INCOMPLETE 0.00 | 🟠 see PAY-004/006 |
| LOP | Same | ABSENT 1.00 · EXITED 1.00 · INCOMPLETE 0.00 | 🟠 PAY-005/006 |
| Overtime detection | `detect_overtime:696` | `worked - scheduled`, min threshold, rounding, daily/weekly/monthly caps | 🟢 |
| OT classification | `classify_ot_day:679` | HOLIDAY > WEEKLY_OFF > NIGHT > NORMAL | 🟡 |
| Night OT | `:1237`, `:1388` | `is_night = shift.is_cross_midnight` **only**. `night_window_start/end` never evaluated. | 🟠 ATT-005 |
| OT approval | `OvertimeRecordService` + `_sync_overtime_record:3244` | PENDING replaced on recompute; terminal frozen (WD-29) | 🟢 |
| Regularization | `_apply_correction:4016` | Synthetic punches / roster row, then recompute. Never a status branch. | 🟢 |
| Leave projection | `_apply_leave_overlay:861` | Full-day wins; half-day contributes 0.50; KEEP_LEAVE vs PRESENT_CANCEL_LEAVE_HINT | 🟢 |
| Recalculation | `calculate()` = full replacement (`replace_derived_fields:1087`) | Never a partial patch | 🟢 |
| Period finalization | `finalize:5053` | Fresh re-validation, version-guarded write, single transaction | 🟢 |
| Period lock | `bulk_lock:1222` + `_ensure_date_open:1915` | Two independent guards | 🟢 |
| Reopen | `reopen:5153` | Requires reason, audited, bulk-unlock | 🟢 |
| Missing-punch AUTO_CLOSE | `_resolve_primary_status:1483` | Falls through to bands; **`auto_closed` hard-coded `False`**; `auto_close_after_minutes` has zero references | 🟠 ATT-002 |
| Excess break behaviour | `excess_break_behaviour` | Passed into `PolicyInputs`, **never read** | 🟠 ATT-004 |
| SPLIT shift | `_evaluate_split:1306` | Block-overlap only; **late/early always 0**; no core-hours or cumulative overrides | 🟡 ATT-010 |

---

## PART 7 — Attendance calculation reproducibility

> *"Why did this employee receive this attendance result on this date?"*

`AttendanceDay` stores version FKs for shift, shift version, work calendar, attendance policy version,
overtime policy version, regularization policy version, on-duty regularization — plus a JSONB
`computation_snapshot`. Published policy versions are immutable. That is a genuinely strong design.

| Element | Reconstructable? | Evidence |
|---|---|---|
| Employee, date, timezone | ✅ | Columns on the row |
| Calendar | ✅ | `work_calendar_id` FK |
| Shift / shift version | ✅ | `shift_id`, `shift_version_id` FKs |
| Roster | ⚠️ **Indirect** | Not stored on the row; must be re-read from `shift_roster` (a mutable master — a later edit changes what you'd re-derive) |
| Attendance / OT / Regularization policy | ✅ | Version FKs; versions immutable once PUBLISHED |
| Punches | ✅ | `snapshot.inputs.punch_ids` + `snapshot.collapsed_punch_ids` + `snapshot.pairing` |
| Leave | ⚠️ **Indirect** | Overlay entries **not** in the snapshot; must be re-read from `leave_day_projection` |
| Regularization | ✅ | Applied as immutable punches |
| Worked minutes / breaks | ✅ | `snapshot.presence` |
| Late / early | ⚠️ | Final values stored; the bands used are recoverable via the version FK |
| Status | ✅ | Column |
| Paid fraction / LOP | ✅ | Columns — **but silently overwritten at lock time** (`set_lock_time_incomplete_resolution:1199`) with no before/after audit row |
| OT | ✅ | Columns + `overtime_record` |
| Approval | ✅ | Action timelines |
| **Calculation version** | ❌ | `calculation_version` is a per-row recompute counter (`service.py:2569`), **not** an engine/algorithm identifier |
| **Policy version** | ✅ | FKs |
| **Sibling-day inputs** | ❌ | `prior_late_days_in_window`, `prior_excess_break_days_in_window` (`service.py:2959-2981`), `remaining_weekly_minutes`, `remaining_monthly_minutes` (`service.py:3009-3038`) are **not written to the snapshot** |

### Verdict

🔴 **PAYROLL FOUNDATION RISK — historical attendance is not exactly reproducible.**

Two independent causes, both already documented in the decision log as accepted trade-offs (WD-29
decision 3, WD-32 decisions 2/3) but never assessed against a Payroll consumer:

1. **Sibling-day dependency.** Recomputing an unchanged day can produce a different
   `ot_minutes_detected` or a different status, because the weekly/monthly OT budget and the
   late/excess-break day counters are read live from sibling days at compute time. The inputs are not
   preserved, so you cannot tell after the fact what budget was applied.
2. **No engine-version stamp.** If `calculation.py` changes — as it will while ATT-001…ATT-005 are
   fixed — there is no way to distinguish rows produced by the old algorithm from rows produced by the
   new one.

**Fix (P0):** persist the derived sibling-day inputs into `computation_snapshot`, and add a module-level
`ENGINE_VERSION` constant written to a new `attendance_day.engine_version` column.

---

## PART 8 — Leave audit

| Concern | Business rule | Implementation | Data model | Transaction integrity | Tests | Auditability | Status |
|---|---|---|---|---|---|---|---|
| Leave type | Code/name/paid-default/balance-required/comp-off/statutory-category | `LeaveTypeService` | `leave_type` | Single tx | ✅ | ✅ | 🟢 |
| Leave policy | Versioned, publish-immutable, bound to one leave type (LD-10) | `LeavePolicyService` | `leave_policy` + `_version` | ✅ | ✅ | ✅ | 🟢 |
| Eligibility | `allow_employee_request` / on-behalf / probation | `submit:1962-1974`, `:1955-1960` | Policy fields | ✅ | `test_leave_probation_rules.py` | ✅ | 🟢 |
| Entitlement | Not modelled as an entitlement figure — it emerges from accrual | — | — | — | — | — | 🟡 **BUSINESS DECISION REQUIRED** |
| Accrual | Monthly (prev. month, prorated) + Yearly (leave-year start) | `run_for_company:1339`, `run_year_end_for_company:1439` | `leave_ledger` `ACCRUAL` | ⚠️ check-then-insert | `test_leave_accrual.py` | ✅ system rows | 🟠 DAT-001 |
| Allocation | Ledger credit | `LeaveLedgerRepository.insert` | Append-only | ✅ | ✅ | ✅ | 🟢 |
| Balance | `SUM(leave_ledger.amount)` — never a stored column | `get_balances:1267` | ADR-0004 honoured | ✅ | `test_leave_ledger.py` | ✅ | 🟢 |
| Carry forward | Excess over `max_carry_forward_days` forfeited at leave-year start | `:1506-1537` | `CARRY_FORWARD` negative entry | ⚠️ same race | `test_leave_year.py` | ✅ | 🟡 |
| Expiry / lapse | **Only** comp-off has expiry (`expire_company:1643`). Ordinary leave never expires beyond the carry-forward cap. | — | — | — | `test_leave_comp_off.py` | ✅ | 🟡 **BUSINESS DECISION REQUIRED** |
| Encashment | Policy-validated (`max_encashment_days`, `min_balance_after_encashment`) | `create_encashment:1152` | `ENCASHMENT` debit | ✅ | `test_leave_encashment.py` | ✅ | 🟢 (payout is Payroll's) |
| Negative balance | Hard-blocked at submit; **`allow_negative_balance` never read** | `:2023-2024` | Field inert | — | — | — | 🟠 PAY-011 |
| Advance leave | Not implemented | — | — | — | — | — | 🟡 **BUSINESS DECISION REQUIRED** |
| Full-day | `fraction = 1.00` | `_compute_day_breakdown:1860` | `leave_application_day` | ✅ | ✅ | ✅ | 🟢 |
| Half-day | Only when `start_date == end_date` (`:1862`) | Multi-day applications cannot have a half start or end | 🟡 documented gap |
| Overlap | Cross-type blocked by `LeaveCombinationRule`; **same-type overlap not blocked at submit** | `:1911-1927` | Caught late by `LeaveProjectionOverlapError` at approve | 🟡 DAT-006 |
| Holiday / weekly off | Non-consuming unless bracketed | `:1843-1853` | ✅ | ✅ | ✅ | ✅ | 🟢 |
| Sandwich | Interior non-working day between two consuming days becomes consuming; **within one application only** | `:1847-1853` | Default ON (`sandwich_rule_enabled=True`) | ✅ | ✅ | ✅ | 🟢 documented |
| Approval | AUTO / HR / MANAGER / MANAGER_THEN_HR / MANAGER_THEN_HOD_THEN_HR; approvers snapshotted at submit | `submit:2026-2071`, `_approve_internal:2296` | `approval_stage` | ✅ optimistic-locked | `test_leave_approval_hod.py` | ✅ `leave_application_action` | 🟢 |
| Rejection | Terminal, reason captured | `reject:2237` | ✅ | ✅ | ✅ | ✅ | 🟢 |
| Cancellation | SUBMITTED or APPROVED; **submitter only** | `cancel:2488-2513` | Reverses ledger + projections | ✅ single tx | ✅ | ✅ | 🟡 **BUSINESS DECISION REQUIRED** (HR cannot cancel) |
| Withdrawal | Same as cancellation — no separate concept | — | — | — | — | — | 🟡 |
| Backdating | `max_backdated_days` vs `date.today()` | `:1978-1981` | Server-local date | ✅ | ✅ | ✅ | 🟡 DAT-005 |
| Policy changes | `leave_policy_version_id` snapshotted at submit | `:2079` | In-flight applications protected | ✅ | ✅ | ✅ | 🟢 |
| Historical records | Ledger append-only; corrections are offsetting entries | ADR-0004 | ✅ | ✅ | ✅ | ✅ | 🟢 |
| Attendance interaction | See Part 9 | | | | | | 🟢 |

### 🔴 The single most important Leave finding

**PAY-010 — balance is verified at submit and never again.**

`submit` (`leave/service.py:2002-2024`) checks `current_balance >= total_days`.
`_apply_approval` (`leave/service.py:2465-2480`) then inserts the `APPLICATION` debit
**unconditionally** — no re-check, no lock, no constraint.

Concretely: an employee with 5 days of balance submits two 5-day applications on Monday. Both pass the
submit check (unless `reserve_balance_on_submission` is enabled, which defaults to `False`). A manager
approves both on Tuesday. Result: balance −5, and `allow_negative_balance` — the field that exists
precisely to govern this — is never consulted anywhere in the codebase.

---

## PART 9 — Attendance ↔ Leave audit

| Scenario | Current behaviour | Intended (per architecture §19.3/§19.4) | Precedence | Payroll impact | Status |
|---|---|---|---|---|---|
| Full-day leave + punches, `KEEP_LEAVE` (default) | Status `LEAVE`, late/early zeroed, paid = leave's paid fraction | Same | Leave > punches | Correct | 🟢 |
| Full-day leave + punches, `PRESENT_CANCEL_LEAVE_HINT` | Punch outcome kept; `work_on_leave_flagged=true`; Attendance never cancels the leave | Same | Punches > leave, Leave notified | Employee is paid as present **and** the leave day is still debited from the ledger until HR acts | 🟡 **BUSINESS DECISION REQUIRED** |
| Leave + no punches | Status `LEAVE`, paid from leave, LOP from unpaid portion | Same | Leave | Correct | 🟢 |
| Half-day leave + work | Status `HALF_DAY`, **paid 1.00** (`calculation.py:929-935`) | Half leave + half work = full pay | Leave overlay after punch evaluation | ⚠️ status says HALF_DAY, fraction says full day — a Payroll rule keyed on **status** would underpay | 🟡 ATT-013 |
| Half-day leave + no work | Status `LEAVE`, paid 0.50, LOP 0.50 | Same | Leave | Correct | 🟢 |
| Leave + late | Late zeroed on full-day leave; **retained on half-day leave** | §19.3: "full-day leave: late/early not computed" | Leave | Correct as documented | 🟢 |
| Leave + early departure | Same as late | Same | Leave | Correct | 🟢 |
| Leave + OT | OT detection runs **before** the leave overlay; a full-day-leave day can still carry `ot_minutes_detected > 0` | Not specified | Undefined | 🟠 OT on a leave day flows to `summary.ot_minutes_*` | 🟠 **BUSINESS DECISION REQUIRED** |
| Leave + holiday | Full-day leave outranks `NOT_EXPECTED`; `calendar_day_type` still reports HOLIDAY | Architecture's own contract table | Leave > calendar | Leave is consumed on a holiday if Leave projected it — but `_compute_day_breakdown` won't project one unless the sandwich rule brackets it | 🟢 |
| Leave + weekly off | Same | Same | Leave > calendar | Same | 🟢 |
| Leave + regularization | Independent — regularization writes punches, leave overlays afterwards | Same | Leave last | Correct | 🟢 |
| Leave cancellation → attendance | `LeaveProjectionService.cancel` → synchronous recompute of that day | §21 | — | Correct | 🟢 |
| Leave approved after attendance already calculated | `sync()` recomputes the affected day in the same transaction | §21 | — | Correct | 🟢 |
| Leave changed after **finalization/lock** | **Refused.** `sync` and `cancel` both call `_ensure_date_open` (`:5254`, `:5384`) and raise `AttendancePeriodClosedError`; the whole approval transaction rolls back | §21 "default refuse" | Lock wins | Correct — this is the strongest guarantee in the system | 🟢 |
| Leave approval spanning a closed period boundary | Entire application fails; no partial approval | LD-12 | Lock wins | Correct, but operationally awkward — no arrears path | 🟡 **BUSINESS DECISION REQUIRED** |
| ON_DUTY + leave | Leave overlay applied **after** on-duty overlay, so leave wins | WD-32 decision 6 | Leave > ON_DUTY | Correct | 🟢 |

---

## PART 10 — Policy precedence audit

The 8-level scope walk is implemented once, generically, in
`CalendarResolutionService.resolve_policy_assignment` (`organisation/calendar_resolution.py:288-315`)
and reused verbatim for every policy kind:

```
EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH > LEGAL_ENTITY > COMPANY
```

Most specific wins; first match stops the walk; no match → `config_incomplete = True` (fail closed,
WD-21). This is applied to `WORK_CALENDAR`, `WEEKLY_OFF`, `ATTENDANCE_POLICY`, `OVERTIME_POLICY`,
`REGULARIZATION_POLICY`, and `LEAVE_POLICY` (the last additionally keyed by `leave_type_id`, LD-11).

### Master policy precedence matrix

| ID | Policy A | Policy B | Winner | Why | Explicitly defined? | Payroll impact |
|---|---|---|---|---|---|---|
| P-01 | EMPLOYEE assignment | COMPANY assignment | A | Most specific (`_PRECEDENCE_SCOPES:48-57`) | ✅ WD-09 | Policy set per employee |
| P-02 | SHIFT assignment | DEPARTMENT assignment | A | Shift ranks 2nd | ✅ WD-09 | ✅ |
| P-03 | BRANCH | LEGAL_ENTITY | A | Branch ranks 6th, LE 7th | ✅ | ✅ |
| P-04 | `CalendarException` | Holiday list | A | `classify_work_calendar_date:142-167` | ✅ §6.3 | Day type |
| P-05 | Holiday list | Weekly-off pattern | A | `:177-219` | ✅ §6.3 | Holiday vs WO pay |
| P-06 | Holiday **on** a weekly off | — | WEEKLY_OFF + `holiday_on_weekly_off` flag | WD-05; no auto-substitution | ✅ PD-CAL-2 open | 🟡 No compensatory day |
| P-07 | Two holiday calendars listing the same date | First list in link order | `:171-175` | ✅ | Deterministic | 🟢 |
| P-08 | Two weekly-off rules matching the same date | **Largest** `off_fraction` | `evaluate_weekly_off:127` — most conservative | ✅ | Fraction is then discarded anyway (PAY-012) | 🟠 |
| P-09 | `WEEKLY_OFF` PolicyAssignment | `WorkCalendar.weekly_off_pattern_id` | A | `resolve_for_employee:428-435` | ✅ | ✅ |
| P-10 | PUBLISHED `ShiftRoster` | `EmployeeAssignment.shift_id` | A | `_build_calculation_input:2772-2776` | ✅ §9.7/WD-27 | Scheduled minutes |
| P-11 | DRAFT `ShiftRoster` | Anything | **Ignored entirely** | `get_published_for_date` | ✅ WD-27 | 🟢 |
| P-12 | Roster week-off override | `calendar_day_type = WORKING` | A → `NOT_EXPECTED` | `evaluate_day:785-794` | ✅ | Paid 1.00 |
| P-13 | Population gate (NOT_JOINED/EXITED) | Everything | A | `evaluate_day:767-769` — checked first | ✅ §19.4 | 🔴 PAY-004/005 |
| P-14 | CONFIG_ERROR | Everything except the gate | A | `:771-777` | ✅ WD-21 | Blocks finalize |
| P-15 | Full-day leave | Punch-derived status | A (unless `PRESENT_CANCEL_LEAVE_HINT`) | `_apply_leave_overlay:905-920` | ✅ §19.4 | Paid days |
| P-16 | Leave overlay | ON_DUTY overlay | Leave | `evaluate_day:858` — on-duty applied first, leave wraps it | ✅ WD-32 | ✅ |
| P-17 | Late band `ABSENT` | Hour band `PRESENT` | ABSENT | `_resolve_primary_status:1493-1498` | ✅ | Full LOP |
| P-18 | Core-hours override | Hour band | Override | `:1493-1505` | ✅ WD-32 d1 | ✅ |
| P-19 | Cumulative late-days override | Hour band | Override (HALF_DAY) | `:1499-1505` | ✅ WD-32 d2 | ✅ |
| P-20 | Late override vs cumulative override | **Neither suppresses the other** — ABSENT tier evaluated before HALF_DAY tier | `:1493-1505` | ✅ documented | ✅ |
| P-21 | SPLIT missed-block behaviour | Hour band | Missed-block behaviour | `_evaluate_split:1357-1360` | ✅ | ✅ |
| P-22 | Period lock | Every mutation | **Lock** | `_ensure_date_open:1915` on punch / roster / regularization / OT / leave projection | ✅ WD-30 | 🟢 Strongest guarantee |
| P-23 | Period lock | Regularization policy `blocked_when_locked` | Lock, unconditionally | `service.py:3491` comment | ✅ | 🟢 |
| P-24 | Manual correction | Calculated result | Correction, **but only via punches/roster** — never a direct status write | WD-28 d1 | ✅ | 🟢 Excellent |
| P-25 | Leave combination rule | Absence of a rule | Absence = allowed | `submit:1919-1927` | ✅ LD-16 | 🟡 Fail-open by design |
| P-26 | Statutory leave minimum | Policy `accrual_rate_per_cycle` | Minimum blocks publish; compared against **MAX** across all states | `_enforce_statutory_minimum:899` | ✅ LD-22 | 🟡 Fail-safe, not scope-precise |

**No undefined precedence conflicts were found in the code paths that Payroll depends on.** Every
conflict above resolves deterministically. This is a genuine strength.

---

## PART 11 — Database audit

**Strengths — verified, not assumed:**

- **79 tables**, 61 Alembic revisions. Every attendance/leave table carries `company_id` with an index.
- **GiST exclusion constraints** prevent overlapping effective-dated rows: `employment_no_overlap`,
  `PolicyAssignment`, published policy versions, `AttendancePeriod`.
- **CHECK constraints** encode invariants at the DB level, e.g. `employment.last_working_day` set *iff*
  `status='TERMINATED'`; `leave_ledger.amount <> 0`.
- **Partial unique indexes** for natural keys: `punch(company_id, idempotency_key)`,
  `leave_day_projection(company_id, employee_id, attendance_date, leave_application_id)`,
  `leave_combination_rule` over `LEAST/GREATEST` of the pair, one active comp-off type per company.
- **Append-only tables** with no `updated_at` and no update path: `punch`, `leave_ledger`, `audit_log`,
  and all four `*_action` timelines.
- **`ON DELETE SET NULL`** on every `user.id` FK — a deleted user never cascades away an HR fact.
- **Money as integer minor units** — `employee_compensation.annual_ctc_minor` is `BigInteger` (ADR-0006).

**Findings:**

| ID | Finding | Severity | Evidence |
|---|---|---|---|
| DAT-001 | No unique constraint backing accrual idempotency | 🟠 | `exists_for_cycle` → `insert` (`leave/service.py:1400-1435`) with no unique index on `(company_id, employee_id, leave_type_id, entry_type, effective_date)` |
| DAT-007 | Numeric typing inconsistency | 🔵 | `EmployeeStatutory.vpf_percentage: Mapped[float \| None]` over a `Numeric(9,4)` column (`employee/models.py:228`) — the annotation is wrong; the runtime value is `Decimal` |
| DAT-009 | `paid_day_fraction`/`lop_fraction` are `Numeric(3,2)` | 🔵 | `attendance/models.py:580-581` — sufficient for 0.00–1.00, but leaves no headroom for quarter-day or 1.5× constructs |
| DAT-010 | No FK from `leave_day_projection.leave_application_id` to `leave_application.id` | 🟡 | `attendance/models.py:1012-1014` — deliberate (built before Leave existed), now an unenforced cross-module reference |
| DAT-011 | `attendance_period.legal_entity_id` reserved, always NULL | 🟡 | `attendance/models.py:872` — period grain is company-wide; PD-LOCK-1 open |
| SEC-007 | `company` has `FORCE ROW LEVEL SECURITY` but RLS is never `ENABLE`d and no policy exists | 🟡 | `scripts/sql/002_row_level_security.sql:10-11` — `FORCE` without `ENABLE` is a no-op |
| DAT-012 | No table partitioning on `punch` or `attendance_day` | 🔵 | Documented deferral (WD-26). Fine at current volume. |

**Timestamps:** every `DateTime` column in the audited modules is `DateTime(timezone=True)` →
`TIMESTAMPTZ`. No naive timestamp columns were found. Business dates (`attendance_date`,
`effective_date`, `joining_date`) are `DATE`, which is correct.

**Cascades:** no `ON DELETE CASCADE` was found on any HR-fact table. Deletion is soft
(`deleted_at`) throughout. No unsafe delete path was identified.

---

## PART 12 — Multi-tenant isolation

This is the strongest area of the codebase, and it has been deliberately hardened.

| Layer | Control | Evidence | Status |
|---|---|---|---|
| Database | RLS `ENABLE` + `FORCE` + `tenant_isolation` policy keyed on `current_setting('app.company_id', true)::uuid` on **70 of 79 tables** | `scripts/sql/002_row_level_security.sql`, plus a block in nearly every migration | 🟢 |
| Database role | `hrms_app`: `NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`, owns nothing | `infra/docker/postgres/init/002_app_role.sql:16-23` | 🟢 |
| Migration role | Separate `MIGRATIONS_DATABASE_URL`; `Settings` has **no field** for it, so the app process never loads the admin credential | `alembic/env.py:16-29` | 🟢 Excellent |
| Session | GUC set at session open from the tenant contextvar, then **re-set from the verified company id** after membership check | `core/db/session.py:42-49`, `core/tenancy/dependencies.py:31-37` | 🟢 |
| API | `X-Company-Id` header must equal the JWT's `company_id`, else 404 | `core/tenancy/dependencies.py:19-20` | 🟢 Client-supplied tenant id is never trusted |
| Repository | Every query filters `company_id` explicitly *in addition to* RLS | Sampled across all repositories | 🟢 Defence in depth |
| Service | `_ensure_employee_visible` on the **target** id, not just permission possession | `attendance/service.py:1894-1912`, `leave/service.py:1748` | 🟢 |
| Background jobs | `session_scope(company_id=...)` sets the GUC per task | `leave/tasks.py:34, 59, 83, 108` | 🟢 |
| Public onboarding | GUC set from the **token's own server-authored** `company_id`; no route accepts a client `company_id` | `onboarding/service.py:450-455`, `public_router.py:9-10` | 🟢 |
| Reports / exports / search | Not built | — | ⚪ |
| Notifications | Not built | — | ⚪ |
| File access | S3 keys namespaced `onboarding/{company_id}/{case_id}/...` and only reachable via a presigned URL minted after a tenant-scoped DB read | `onboarding/service.py:571` | 🟡 Not cryptographically bound to the tenant |

### Tables without RLS

`company`, `permission`, `plan`, `plan_feature`, `refresh_token`, `session`, `user`, `role_permission`,
`user_role`. The first four are global catalogues or the tenant root; the identity tables are
cross-tenant by nature; `role_permission`/`user_role` have no `company_id` column and are reached only
through the RLS-protected `user_company` join (`core/rbac/service.py:18-31`, which additionally filters
`company_id` explicitly). Documented as intentional in `002_row_level_security.sql:31-33`.

### TEN-002 🟠 — the isolation is designed well but tested weakly

`tests/conftest.py:9` and `.github/workflows/ci.yml:47` both point `DATABASE_URL` at the **superuser
`hrms`** role, which has `BYPASSRLS`. Only `tests/security/test_rls_runtime_role.py` temporarily
repoints the engine at `hrms_app` (`:64, :73`). Every other test — including
`tests/integration/modules/organisation/test_cross_tenant_isolation.py` — therefore proves only that
the *application-layer* `WHERE company_id` filters work, with RLS effectively disabled underneath.

**No credible cross-tenant leakage path was found.** The design is sound. But the verification is
thinner than the design, and that gap should be closed before Payroll adds a new set of tenant tables.

---

## PART 13 — Authorization audit

Permissions are module-owned code constants (`modules/*/permissions.py`), seeded into the `permission`
table (`seed/bootstrap.py:58-63`). Every permission grant carries a `data_scope` on `role_permission`
(migration `20260815120000`), resolved into a `DataScope` of levels
`SELF | REPORTEES | REPORTEE_TREE | COMPANY` and then into a concrete visible-employee set by
`EmployeeService.resolve_visible_employee_ids` (`employee/service.py:94-141`).

| Operation | Gate | Scope narrowing | Evidence |
|---|---|---|---|
| View attendance day | `ATTENDANCE.VIEW` / `.VIEW_ALL` | `_resolve_visible_employee_ids`; out-of-scope → **404, not 403** | `attendance/service.py:2442-2446` |
| Record punch | `ATTENDANCE.PUNCH` / `.PUNCH_ON_BEHALF` | `_ensure_employee_visible` on the target, **before** the idempotency lookup | `attendance/service.py:2325-2337` |
| Calculate / recompute | `ATTENDANCE.*` + period lock | `_ensure_date_open` | `:2504` |
| Manage roster | `ATTENDANCE.ROSTER_MANAGE` | Target-employee check on every mutation | `ShiftRosterService` docstring `:1940-1944` |
| Submit regularization | `ATTENDANCE.REGULARIZE` / `_ON_BEHALF` | Body-dependent permission choice | `attendance/router.py:1068` |
| Approve / reject regularization | `ATTENDANCE.REGULARIZE_APPROVE` | Stage + resolved approver identity checked | `_get_reviewable:3877` |
| Cancel regularization | Two permissions unioned | `attendance/router.py:1150` | |
| Approve / reject OT | `ATTENDANCE.OVERTIME_APPROVE` | `_get_reviewable:4330` | |
| Finalize period | `ATTENDANCE.PERIOD_MANAGE` | Company-scoped | `router.py:1413` |
| Reopen period | `ATTENDANCE.UNLOCK` | **Separate, stronger permission than finalize** | `router.py:1436` 🟢 |
| Leave balance / ledger read | `LEAVE.BALANCE_VIEW` ∪ `LEAVE.BALANCE_VIEW_ALL` | `_combined_balance_scope:445-457` — raises if the union is empty | 🟢 |
| Adjust / encash balance | `LEAVE.BALANCE_ADJUST` | Company-scoped HR admin | `router.py:465, 484` |
| Submit leave | `LEAVE.APPLICATION_SUBMIT` / `_ON_BEHALF` | Body-dependent | `router.py:547-565` |
| Approve leave | `LEAVE.APPLICATION_APPROVE` | Stage + snapshotted approver; **self-approval blocked** | `leave/service.py:2061` |
| Cancel leave | Submitter only | Not permission-based | `leave/service.py:2512-2513` 🟡 |
| Manage any policy | `*.POLICY_MANAGE` | Company-scoped | Consistent |
| Export | Not built | — | ⚪ |

**IDOR / BOLA assessment.** The pattern that prevents it is applied consistently: a non-empty
`DataScope` proves only that the caller holds *some* grant, so every service additionally checks the
**target** id (`_ensure_employee_visible`). The commit history shows this was a deliberate hardening
pass (`fecb740` — *"enforce punch DataScope"*, `7a8ff30` — *"close RBAC data-scope enforcement gaps
end-to-end"*). Out-of-scope and nonexistent ids both return the identical 404, so responses do not
distinguish the two (`attendance/service.py:1904-1906`).

**No IDOR/BOLA vulnerability was identified in the audited surface.** 🟢

**Gaps:** 🟡 no audit-log read API or UI; 🟡 no permission-change audit trail beyond generic `audit_log`;
🟡 leave cancellation is identity-based rather than permission-based, so HR has no cancellation path.

---

## PART 14 — API audit

~150 endpoints across 8 routers, all under `/v1`.

| Concern | Finding | Status |
|---|---|---|
| Authentication | Every route except `/health`, `/auth/login`, `/auth/token/refresh`, `/companies/register`, and `/public/onboarding/*` requires a bearer token | 🟢 |
| Authorization | `require_permission(...)` or an explicit combined-scope resolver on every authenticated route | 🟢 |
| Validation | Pydantic v2 schemas on every body; enum allow-lists in `schemas.py` | 🟢 |
| Input sanitization | SQLAlchemy Core/ORM parameter binding throughout — **no string-concatenated SQL was found** | 🟢 |
| Output validation | Typed `DataEnvelope[T]` / `ListEnvelope[T]` response models | 🟢 |
| **Pagination** | **None.** `PaginationMeta` is defined (`shared/pagination.py:14`) but `pagination=` is never passed anywhere, and no list repository issues a `LIMIT` | 🟠 DAT-002 |
| Filtering | Present and consistent (`employee_id`, `date_from`, `date_to`, `status`) | 🟢 |
| Sorting | Not exposed | 🔵 |
| Error handling | Global handlers, typed codes, `request_id` in every envelope; unhandled exceptions → generic 500 with no leakage | 🟢 |
| Status codes | Consistent 200/201/204/404/403/409/422/429 | 🟢 |
| Idempotency | Only `POST /attendance/punches` supports an idempotency key | 🟡 |
| Transactions | One request = one session = one transaction | 🟢 |
| Race conditions | `expected_version` (If-Match style) on every workflow mutation | 🟢 |
| **Rate limiting** | Applied to **one** endpoint (`/companies/register`) | 🟠 SEC-002 |
| Sensitive data exposure | `/auth/me` returns the caller's own permission codes only; no password hashes or tokens in any response | 🟢 |
| Tenant isolation | See Part 12 | 🟢 |
| Audit logging | Every mutation calls `AuditService.record` | 🟢 |
| Duplicate endpoints | None found | 🟢 |
| Dead endpoints | `GET /v1/ingestion/health` (stub, `ingestion/routes.py`) | 🔵 |
| Response format consistency | Uniform envelopes | 🟢 |
| Business logic in controllers | None | 🟢 |
| Unsafe bulk operations | `POST /v1/rosters/bulk` is the only bulk write; it is transactional and scope-checked | 🟢 |
| **Missing endpoint** | **No batch attendance calculation endpoint** | 🔴 PAY-001 |

---

## PART 15 — Frontend audit

Next.js 14 App Router, 278 `.ts`/`.tsx` files, 45 vitest test files.

**Executed during this audit:**

```
$ npx vitest run
Test Files  45 passed (45)      Tests  342 passed (342)      Duration 8.85s

$ npx tsc --noEmit
(clean — exit 0)
```

The frontend is in better shape than its absence from CI suggests: 342 tests pass and the codebase
type-checks cleanly under the project's own `tsconfig`. The gap is that **nothing enforces this on a
pull request** (TST-002).

| Concern | Finding | Status |
|---|---|---|
| Authentication | `AuthProvider` + `apiClient` with automatic refresh; `SESSION_EXPIRED_EVENT` decouples the plain-module client from React | 🟢 |
| Token storage | Both access **and refresh** tokens in `localStorage` — the trade-off is explicitly documented at `lib/auth/token-storage.ts:3-13` because the backend sets no `Set-Cookie` | 🟠 SEC-003 |
| Route protection | Auth-gated layout under `src/app/app/` with a tested layout guard (`layout.test.tsx`) | 🟢 |
| Permission enforcement | Permission codes from `/auth/me` drive navigation and action visibility | 🟢 UI-level |
| **Backend enforcement verified separately** | Yes — see Part 13. Frontend hiding is **not** the control. | 🟢 |
| Form validation | Per-domain pure validators with unit tests (`lib/*/validate-*.test.ts`) | 🟢 |
| Error handling | Envelope-aware error surfacing | 🟢 |
| Loading / empty states | Present in list and detail screens | 🟢 |
| Duplicate submissions | Not systematically guarded — no disable-on-submit convention found | 🟡 |
| Unsaved changes | No navigation guard | 🔵 |
| Pagination | No UI pagination — mirrors the API gap (DAT-002). A large tenant will render every row. | 🟠 |
| Date/time & timezone | Dates rendered from ISO strings; **no company-timezone renderer** despite ADR-0010 ("UTC storage, company timezone render") | 🟡 |
| Accessibility | Radix primitives give keyboard/ARIA baseline; no axe or a11y test in the suite | 🔵 |
| Responsive | Tailwind responsive utilities used | 🟢 |
| **CI** | **The frontend is not built, linted, type-checked or tested by CI at all** | 🟠 TST-002 |

---

## PART 16 — Transaction & concurrency audit

**Transaction boundary.** One request = one `AsyncSession` = one transaction, committed on success and
rolled back on any exception (`core/db/session.py:63-68, 78-83`). Celery tasks use the same
`session_scope`. This is correct and consistently applied.

| Risk | Control | Verified | Status |
|---|---|---|---|
| Double approval (regularization / OT / leave) | `expected_version` optimistic lock on the status write; loser gets a stale-version error | ✅ code + tests | 🟢 |
| Double submission | No idempotency key on submit endpoints | ❌ | 🟡 |
| Duplicate leave requests, same type, same dates | Not blocked at submit; caught at approve by `LeaveProjectionOverlapError` | ✅ code | 🟡 DAT-006 |
| Duplicate punches | Partial unique index on `(company_id, idempotency_key)`; `IntegrityError` → typed error; plus calculation-time collapsing | ✅ | 🟢 |
| Concurrent attendance recalculation | `replace_derived_fields` is a single `UPDATE ... WHERE is_locked = false RETURNING` — last writer wins, but both compute the same result from the same inputs | ✅ | 🟡 |
| Concurrent regularization apply | Version-guarded | ✅ | 🟢 |
| Concurrent OT approval | Version-guarded | ✅ | 🟢 |
| Concurrent period finalization | Version-guarded `status='CLOSED'` write happens **before** any day is touched, so the loser aborts cheaply; whole thing is one transaction | ✅ `finalize:5088-5097` | 🟢 Excellent |
| **Concurrent leave balance updates** | **None.** No row lock, no unique constraint, no re-check at approve | ❌ | 🟠 PAY-010 |
| **Concurrent accrual runs** | Check-then-insert with no unique index | ❌ | 🟠 DAT-001 |
| Celery Beat duplicate firing | No leader election or single-instance guard | ❌ | 🟠 OPS-006 |

**Test coverage for concurrency: none.** No test in the suite executes two operations in parallel. The
optimistic-locking paths are tested by passing a deliberately stale `expected_version`, which proves the
guard exists but not that it wins a real race. 🟡 TST-004

---

## PART 17 — Idempotency audit

| Operation | Run twice → correct? | Mechanism | Status |
|---|---|---|---|
| Attendance calculation | ⚠️ **Usually, not always** | Full replacement of derived fields; but sibling-day inputs can differ between runs (PAY-008) | 🟠 |
| Leave monthly accrual | ✅ Sequentially / ❌ Concurrently | `exists_for_cycle` on `(employee, type, ACCRUAL, period_end)`; no DB constraint | 🟠 DAT-001 |
| Leave year-end (carry-forward + yearly accrual) | ✅ / ❌ | Same mechanism, same gap | 🟠 |
| Leave balance update | ✅ | Append-only ledger; balance is always `SUM()` | 🟢 |
| Leave approval | ✅ | Version-guarded; second attempt gets a stale-version error | 🟢 |
| OT generation | ✅ | PENDING replaced on recompute; terminal frozen (WD-29 d2) | 🟢 |
| Regularization apply | ✅ | Version-guarded; punches carry distinct ids | 🟢 |
| Period finalization | ✅ | Version-guarded; `replace_for_period` is a full delete/recreate | 🟢 |
| Period reopen | ✅ | Version-guarded | 🟢 |
| Comp-off credit sweep | ✅ | Idempotent per `overtime_record_id` | 🟢 |
| Comp-off expiry sweep | ✅ | Date-gated | 🟢 |
| Punch ingestion | ✅ when a key is supplied | Partial unique index; replays the original row | 🟢 |
| Leave projection sync | ✅ | Natural-key upsert, bumps `source_version` | 🟢 |
| Notifications | ⚪ | Not built | ⚪ |
| Payroll input export | ⚪ | Not built | ⚪ |

**Non-idempotent operations requiring a fix before Payroll:** attendance calculation (PAY-008), leave
accrual under concurrency (DAT-001).

---

## PART 18 — Money / numeric safety

| Check | Finding | Status |
|---|---|---|
| Decimal vs float in money | **No float anywhere in a money path.** `annual_ctc_minor` is `BigInteger` minor units per ADR-0006 | 🟢 |
| Decimal vs float in fractions | `paid_day_fraction`/`lop_fraction` are `Numeric(3,2)` and manipulated as `Decimal` throughout (`calculation.py:893-935`) | 🟢 |
| Precision / scale | `Numeric(6,2)` for ledger amounts and summary day counts; `Numeric(5,4)` for OT multipliers; `Numeric(3,2)` for fractions | 🟢 |
| Rounding — accrual | `Decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` (`leave/service.py:1319`) — explicit and deterministic | 🟢 |
| Rounding — OT minutes | `round_minutes` NEAREST uses Python's built-in `round()` → **banker's rounding** (`calculation.py:634`). `round(7.5) == 8` but `round(2.5) == 2`. | 🟡 ATT-011 |
| Currency | `MoneyAmount` value object carries an explicit 3-letter currency (`shared/pagination.py:33-37`) | 🟢 |
| Currency precision | Minor units only — no sub-paise representation | 🟢 |
| Negative values | Ledger amounts are signed with a `CHECK amount <> 0`; negative balances are structurally possible (PAY-010) | 🟠 |
| Percentage calculations | `vpf_percentage` is `Numeric(9,4)` but annotated `float` (DAT-007). Nothing computes with it yet. | 🔵 |
| Multipliers | `configured_multiplier` is `Numeric(5,4)`, snapshotted onto `overtime_record`, and **never applied as money** (ADR-0006, WD-03 §12.1) | 🟢 Correct boundary |
| Minutes → hours | No conversion happens in the audited code — everything stays in integer minutes until Payroll | 🟢 Excellent |
| Hours → monetary rate | Does not exist yet. This is Payroll's job. | 🟢 |

**Verdict: money and numeric handling is one of the strongest areas.** The discipline of keeping
Attendance in integer minutes and Decimal fractions, and refusing to apply the OT multiplier, is exactly
the right foundation for Payroll. The one real defect is banker's rounding in OT minute rounding.

---

## PART 19 — Timezone and date audit

| Check | Finding | Status |
|---|---|---|
| UTC storage | Every timestamp column is `DateTime(timezone=True)`. No naive datetime column found. | 🟢 |
| Timezone resolution | `resolve_timezone` = `ShiftVersion.timezone` > `Branch.timezone` > `Company.timezone` (`calculation.py:294-298`, WD-06) | 🟢 |
| Company timezone | `app_timezone_default = "Asia/Kolkata"`, per-company override | 🟢 |
| Branch timezone | Real column, resolved per assignment | 🟢 |
| Employee timezone | Not modelled (branch is the grain) | 🟢 Intentional |
| Shift timezone | `ShiftVersion.timezone` — highest precedence | 🟢 |
| Date boundaries | `_local_to_utc` via `zoneinfo`; the attendance date is the **shift start date** (FR-ATT-005) | 🟢 |
| Cross-midnight shifts | `is_cross_midnight` rolls the end date +1 and pads the load window ±2 h | 🟢 |
| DST | `zoneinfo` handles offsets correctly. **No test covers a DST transition**, and India has no DST, so this is untested for any future non-IST tenant. | 🟡 |
| Month boundaries | Explicit last-day computation (`service.py:2953-2957`) — correct including December | 🟢 |
| Payroll period boundaries | `[period_start, period_end]` inclusive-inclusive, GiST-enforced non-overlapping | 🟢 |
| Naive datetimes in logic | `datetime.now(UTC)` used consistently — **except** two places | 🟡 |
| **`date.today()` misuse** | `leave/service.py:1979` (backdating check) and `leave/service.py:2597` (reversal `effective_date`) use the **server's local date**, not the company timezone | 🟡 DAT-004/005 |
| Punch period-lock check | Uses the punch's **UTC** date, a documented approximation at period boundaries for overnight shifts (`service.py:2352-2360`) — backstopped by `calculate()` refusing a locked day | 🟢 Documented |

---

## PART 20 — Audit logging

`AuditService.record` (`core/audit/service.py`) writes a row capturing:
**who** (`actor_user_id`), **what** (`action`, `entity_type`, `entity_id`), **when** (`occurred_at`),
**before** (`before_json`), **after** (`after_json`), **source** (`ip`, `user_agent`), and a
**correlation id** (`request_id`, pulled from the tenancy contextvar).

| Event | Audited? | Before/after? | Reason captured? | Evidence |
|---|---|---|---|---|
| Employee changes | ✅ | ✅ | — | `employee/service.py` |
| Attendance calculated / recomputed | ✅ | after only | — | `attendance/service.py:2618-2628` |
| Punch created | ✅ | after only (immutable) | — | `:2374` |
| Regularization submit/approve/reject/cancel | ✅ | ✅ | ✅ reviewer comment + rejection reason | + `attendance_regularization_action` timeline |
| OT approve / reject | ✅ | ✅ | ✅ | + `overtime_action` timeline |
| Leave submit/approve/reject/cancel | ✅ | ✅ | ✅ | + `leave_application_action` timeline |
| Leave ledger adjustment / encashment | ✅ | ✅ | ✅ `reason` column | `leave/service.py:1098, 1152` |
| Policy version publish | ✅ | ✅ | ✅ `publish_reason` + `published_by` + `published_at` | All policy services |
| Roster write | ✅ | ✅ | ✅ `reason` | `ShiftRosterService` |
| Period finalize | ✅ | ✅ | — | `:5139-5150` + `attendance_period_action` |
| Period reopen | ✅ | ✅ | ✅ **reason mandatory** | `:5208-5219` |
| Leave projection sync / cancel | ✅ | ✅ | ✅ | `:5334, :5400` |
| Login / logout / token refresh | ✅ | — | — | `identity/service.py:242-251` |
| **Lock-time INCOMPLETE resolution** | ❌ | ❌ | ❌ | `set_lock_time_incomplete_resolution:1216-1220` silently rewrites `paid_day_fraction`/`lop_fraction` with no audit row |
| **Accrual / carry-forward / comp-off credits** | ❌ no `audit_log` row | — | ✅ `reason` on the ledger entry | `leave/service.py:1421-1435` — the append-only ledger *is* the trail, but there is no `audit_log` entry |
| Permission / role changes | ⚠️ | — | — | Not verified — no role-management API exists yet |
| Configuration changes | ✅ | ✅ | — | Policy services |

**Findings:** 🟠 the lock-time paid/LOP rewrite — the single most payroll-consequential silent mutation
in the system — is not audited. 🟡 there is **no audit-log read API and no UI**, so the trail exists but
is only reachable by direct SQL. 🟡 no retention or tamper-evidence policy.

---

## PART 21 — Historical data integrity

> *If Payroll processes August today, can the same August attendance change tomorrow?*

**Answer: yes, in four identified ways — three controlled, one not.**

| Change | Can it alter a **closed** period? | Can it alter an **open** historical period? | Control |
|---|---|---|---|
| Editing an attendance/OT/regularization policy | ❌ | ❌ | Published versions are immutable; a new version needs a new `effective_from`, and resolution is always by date |
| **Back-dated policy version publish** | ❌ (day is locked) | ✅ **Yes** | Only `*.POLICY_MANAGE` holders; audited via `published_by`/`publish_reason`. Documented in `attendance/models.py:483-486` |
| Editing a shift | ❌ | ❌ | `ShiftVersion` is versioned and resolved by date |
| **Editing a roster row** | ❌ | ✅ **Yes** | `ShiftRoster` is a **mutable master**, not an insert-new history (`attendance/models.py:388-394`). Mutations are audited, but the previous value is only in `audit_log` — the row itself is overwritten. |
| Editing an employee assignment | ❌ | ❌ | Effective-dated, `get_assignment_as_of` |
| Editing a leave policy | ❌ | ❌ for in-flight applications (`leave_policy_version_id` snapshotted) | Accrual re-resolves by date, so a back-dated leave version **can** change a future accrual run |
| Calendar / holiday edit | ❌ | ✅ **Yes** | `holiday`/`work_calendar` are mutable masters with no versioning |
| **Company or branch timezone change** | ❌ | ✅ **Yes** | **PAY-013** — see below |
| Leave approval / cancellation | ❌ refused | ✅ Yes, with recompute | `_ensure_date_open` |
| Punch insertion | ❌ refused | ✅ Yes | `_ensure_date_open` |
| **Recomputing an unchanged day** | ❌ | ⚠️ **Can change the result** | PAY-008 — sibling-day dependency |

**Mechanisms present:** ✅ policy versions · ✅ effective dates · ✅ version-FK snapshots on
`AttendanceDay` · ✅ immutable finalized records (`is_locked`) · ✅ frozen `AttendancePeriodSummary` ·
⚠️ partial calculation snapshot.

**Mechanisms missing:** ❌ no snapshot of the *roster* or *calendar* facts used · ❌ no snapshot of
sibling-day inputs · ❌ no engine-version stamp · ❌ leave **balance** is never frozen at period close.

### PAY-013 🟠 — timezone changes are unguarded, and the guard that was written for this is a no-op

`organisation/service.py:601-608`:

```python
def _assert_timezone_change_allowed(self, company_id, current_timezone, new_timezone) -> None:
    """Documented no-op hook until Payroll/Attendance modules exist (Domain Model §5.5)."""
    _ = (company_id, current_timezone, new_timezone)
```

The hook is called from `update_company_profile` (`:598-599`) whenever the timezone changes. It was
written deliberately, as a placeholder, for the moment Attendance existed. **Attendance now exists, and
the hook was never wired up.** `grep` confirms it is the only such placeholder left in the codebase.

`update_branch` (`:1005-1087`) has no equivalent hook at all — `branch.timezone` can be changed freely.

**Why this matters.** Timezone resolution is `ShiftVersion.timezone > Branch.timezone > Company.timezone`
(`calculation.py:294-298`). Most shifts and branches leave it unset, so the company value is load-bearing.
Every date-boundary computation depends on it: `_local_to_utc` for the scheduled span, the punch-load
window, break-window matching (which compares *local* time-of-day, `calculation.py:585`), and core-hours
evaluation.

**Failure scenario.** A company corrects its timezone from `Asia/Kolkata` to `Asia/Dubai`. Every unlocked
historical day, on its next recompute, resolves a scheduled start 90 minutes earlier in UTC — changing
late minutes, potentially crossing a late band, potentially changing status and therefore paid days.

**Partial mitigation.** `attendance_day.timezone` *is* stored (`models.py:502`), so the value used is
recoverable. But recompute re-resolves the timezone live rather than reading the stored one, so the
stored value silently changes too.

**Fix.** Implement the hook: refuse a timezone change when any `CLOSED` period or calculated
`AttendanceDay` exists, or require an explicit acknowledgement. Add the same guard to `update_branch`.

### PAY-014 🟠 — onboarding activation creates no compensation record

`OnboardingActivationService.activate_case` (`onboarding/service.py:864-1017`) writes:
Employee → Employment → Assignment → (optional) Bank → (optional) Statutory. **It never writes
`employee_compensation`.**

```
$ grep -n "ompensation" src/hrms/modules/onboarding/*.py
src/hrms/modules/onboarding/schemas.py:17:  ...(§8.6/O7 only writes Employee/Employment/Assignment/
                                              Compensation/Statutory/Bank)...
```

The single mention is a docstring **claiming compensation is written**. It is not.
**DOCUMENTATION / IMPLEMENTATION CONFLICT.**

By contrast, the bulk-import path *does* create compensation
(`employee_import/service.py:_create_employee_row` → `compensation_service.create_compensation`).
So an employee hired through the digital onboarding flow has no CTC, while an identical employee
loaded from a spreadsheet does.

Nothing currently detects this, because compensation has no consumer until Payroll exists. **Payroll
will encounter employees with no salary record and no indication that anything is missing.**

**Fix.** Either collect compensation during onboarding and write it at activation, or make activation
require an explicit compensation input. Correct the docstring either way.

### Verdict

🟠 **Historical integrity is strong once a period is CLOSED, and weak while it is OPEN.**

The lock is the real guarantee, and it works. The risk is entirely in the window between calculation and
finalization — which is exactly the window Payroll will operate in if it reads unlocked data.
**Payroll must read only CLOSED periods.** That constraint should be enforced, not merely documented.

---

## PART 22 — Period finalization and locking

| Question | Answer | Evidence |
|---|---|---|
| Attendance period | `AttendancePeriod`, `[start, end]` inclusive, GiST non-overlap per company, two states `OPEN`/`CLOSED` | `attendance/models.py:846-903` |
| Leave period | **Does not exist.** Leave has a *leave year* (`LeaveYearSetting`) for accrual, but no closable period. | 🟠 |
| Finalization | Re-validates fresh (never trusts the cached verdict) → version-guarded `CLOSED` write → resolve INCOMPLETE → write frozen summary → bulk-lock days. One transaction. | `finalize:5053-5151` |
| Validation gates | `EMPLOYEES_WITHOUT_ATTENDANCE`, `CONFIG_ERROR`, `INCOMPLETE_ATTENDANCE` (only under `KEEP_INCOMPLETE`), `PENDING_REGULARIZATION`, `PENDING_OVERTIME_APPROVAL`, `UNPUBLISHED_ROSTER` | `_run_validation:4712-4895` |
| **What is frozen** | `attendance_day.is_locked = true` for every row in range; `attendance_period_summary` rows written once | `bulk_lock:1222`, `replace_for_period` |
| **What is not frozen** | Leave **balances**; `leave_ledger` (new entries can still be added with any `effective_date`); the roster; the calendar; policy versions (immutable anyway) | 🟠 |
| Who can reopen | `ATTENDANCE.UNLOCK` — a **separate, stronger permission** than `PERIOD_MANAGE` | `router.py:1436` 🟢 |
| Is reopening audited | ✅ Yes, and the **reason is mandatory** — `audit_log` + `attendance_period_action` | `reopen:5153-5220` 🟢 |
| Does reopening affect payroll inputs | ✅ Yes — days become mutable again, and re-finalizing regenerates a **completely new** frozen summary (full delete/recreate) | `reopen` docstring `:5164-5169` |
| Can a new policy version alter locked data | ❌ No — `calculate()` refuses a locked day, and `_ensure_date_open` refuses every mutation into a closed period | 🟢 |

**Findings.**

- 🟢 The lock mechanism itself is well built: two independent guards (period-level `_ensure_date_open`
  and row-level `is_locked`), fail-closed validation, atomic finalization, audited reopen behind its own
  permission.
- 🔴 **PAY-001** — the `EMPLOYEES_WITHOUT_ATTENDANCE` gate requires an `AttendanceDay` row for **every**
  employment-day in the period, and the only way to create one is a single-employee-single-date HTTP
  call. A 100-employee company closing a 30-day month needs ~3 000 individual API calls. **In practice,
  a period cannot be finalized.**
- 🔴 **PAY-002/003** — the frozen summary that finalization produces is not a sufficient Payroll input
  (no paid days; double-counted and under-covered buckets).
- 🟠 **PAY-007** — `_apply_incomplete_lock_resolution` (`:5016`) issues a Core `UPDATE`, then
  `_aggregate_day_rows` (`:5101`) reads the same in-memory ORM objects. Whether the aggregate sees the
  resolved fractions depends on SQLAlchemy's implicit `synchronize_session="auto"` behaviour. **No test
  asserts the frozen summary's `lop_days` after an INCOMPLETE resolution.** This must be made explicit
  and tested, not left to ORM defaults.

  **Corroborated on the second pass.** This codebase *understands* the identity-map
  auto-synchronization behaviour and works around it explicitly in at least two other places:

  > *"Captured before `update_setup_progress` runs below: that bulk UPDATE auto-synchronizes the
  > session's identity map, mutating this same already-loaded `progress` instance in place — reading
  > `.status` off it afterwards would silently observe the new value, not the prior one."*
  > — `organisation/service.py:660-664`

  > *"…that `UPDATE ... RETURNING` auto-synchronizes the session's identity map, mutating this same
  > already-loaded `branch` instance in place (same gotcha documented on `update_legal_entity`)…"*
  > — `organisation/service.py:1026-1029`

  Elsewhere the team defends against this deliberately. In `finalize` — the one place where the
  behaviour determines a number Payroll pays — the reliance is implicit and untested. That
  inconsistency is the finding, not a misreading of the ORM.
- 🟠 Leave has no period concept, so leave balances can move freely across a closed attendance period.

---

## PART 23 — Test audit

**Executed during this audit:**

```
$ .venv/bin/python -m pytest tests -q
1145 passed in 239.79s (0:03:59)
```

362 unit tests complete in 1.5 s (the pure-engine split paying off); the remaining 783 are integration
tests against a real PostgreSQL 16.

| Category | Present | Files | Assessment |
|---|---|---|---|
| Unit | ✅ | 25 | Strong — calculation engine, calendar resolution, validators |
| Integration | ✅ | 60 | Strong — real DB, real HTTP through ASGI, real seeds |
| API | ✅ | (within integration) | Full request/response cycle |
| Database | ✅ | e.g. `test_company_feature_flag_constraint.py` | Constraint behaviour tested directly |
| Permission | ✅ | `test_permission_matrix.py`, `test_employee_data_scope.py` | Genuinely good |
| Tenant isolation | ⚠️ | `test_cross_tenant_isolation.py`, `tests/security/test_rls_runtime_role.py` | The RLS test is excellent; everything else runs as a BYPASSRLS superuser (TEN-002) |
| Scenario | ✅ | `test_attendance_day.py`, `test_leave_application.py` | Multi-step business scenarios present |
| Regression | ✅ | Named tests referencing fixed bugs | Good practice |
| **Concurrency** | ❌ | 0 | No parallel-execution test anywhere |
| Failure | ⚠️ | Some | Error paths tested; infrastructure-failure paths not |
| Boundary | ✅ | Cross-midnight, month-end, leap-day (`_safe_date`) | Good |
| End-to-end | ❌ | 0 | No Playwright/Cypress; frontend and backend never tested together |

### Business rule test coverage matrix

| Rule | Implemented | Tested | Edge cases | Conflicts tested | Payroll critical | Status |
|---|---|---|---|---|---|---|
| Population gate (NOT_JOINED/EXITED/ACTIVE) | ✅ | ✅ | ✅ | ✅ | 🔴 | 🟢 |
| Calendar day classification | ✅ | ✅ unit + integration | ✅ | ✅ | 🔴 | 🟢 |
| 8-level policy precedence | ✅ | ✅ `test_policy_resolution.py` | ✅ | ✅ | 🔴 | 🟢 |
| Punch dedup + pairing | ✅ | ✅ unit | ✅ | n/a | 🔴 | 🟢 |
| Cross-midnight attribution | ✅ | ✅ | ✅ | n/a | 🔴 | 🟢 |
| Worked-minutes arithmetic (both modes) | ✅ | ✅ unit | ✅ | n/a | 🔴 | 🟢 |
| Late / early banding | ✅ | ✅ | ✅ | ✅ | 🟠 | 🟢 |
| Hour bands → status | ✅ | ✅ | ✅ | ✅ | 🔴 | 🟢 |
| **Punch rounding** | ❌ **not implemented** | ❌ | — | — | 🟠 | 🔴 ATT-001 |
| **AUTO_CLOSE missing punch** | ❌ **not implemented** | ❌ | — | — | 🟠 | 🔴 ATT-002 |
| **Half-day split policy** | ❌ **not implemented** | ❌ | — | — | 🟠 | 🔴 ATT-003 |
| **Excess-break behaviour** | ❌ **not implemented** | ❌ | — | — | 🟡 | 🔴 ATT-004 |
| **Night-window OT** | ❌ **not implemented** | ❌ | — | — | 🟠 | 🔴 ATT-005 |
| OT detection + caps | ✅ | ✅ | ✅ | ✅ | 🔴 | 🟢 |
| OT approval freeze | ✅ | ✅ | ✅ | ✅ | 🔴 | 🟢 |
| Regularization → punch → recompute | ✅ | ✅ | ✅ | ✅ | 🟠 | 🟢 |
| Leave overlay precedence | ✅ | ✅ | ✅ | ✅ | 🔴 | 🟢 |
| Sandwich rule | ✅ | ✅ | ✅ | ✅ | 🟠 | 🟢 |
| Leave balance sufficiency at submit | ✅ | ✅ | ✅ | — | 🔴 | 🟡 |
| **Leave balance at approve** | ❌ **not implemented** | ❌ | — | — | 🔴 | 🔴 PAY-010 |
| Monthly accrual + proration | ✅ | ✅ | ✅ | — | 🔴 | 🟡 no concurrency test |
| Carry-forward cap | ✅ | ✅ | ✅ | — | 🟠 | 🟡 |
| Comp-off credit + expiry | ✅ | ✅ | ✅ | — | 🟠 | 🟢 |
| Period validation gates | ✅ | ✅ | ✅ | ✅ | 🔴 | 🟢 |
| **Lock-time INCOMPLETE → summary** | ✅ | ❌ **no test** | ❌ | ❌ | 🔴 | 🔴 PAY-007 |
| Period lock refuses mutations | ✅ | ✅ | ✅ | ✅ | 🔴 | 🟢 |
| Reopen | ✅ | ✅ | ✅ | — | 🟠 | 🟢 |
| RLS under the runtime role | ✅ | ✅ (1 file) | ✅ | ✅ | 🔴 | 🟡 |

### TST-001 🔴 — CI does not run the integration or security suites

`.github/workflows/ci.yml` has **no `services:` block** and no docker-compose step, yet sets
`DATABASE_URL: postgresql://hrms:...@localhost:5433/hrms_dev` (line 47) and runs `uv run pytest`
(line 51) over `testpaths = ["tests"]`. **62 of 87 test files require a live PostgreSQL.**

Two additional problems in the same six lines:

- The CI database URL uses the **superuser `hrms`** role — the role that
  `infra/docker/postgres/init/002_app_role.sql:3-6` explicitly says "must never again be the role the
  application authenticates as", because it has `BYPASSRLS`.
- CI's JWT secrets are set, but no Redis is provisioned either, so the one rate-limited endpoint's tests
  cannot pass.

**Whatever the current CI status is, the effect is the same: the 783 integration tests that verify
business rules, authorization, and tenant isolation are not a merge gate.** This is the single highest
-leverage fix in this audit — it costs about fifteen lines of YAML.

---

## PART 24 — Test the tests

Where could the suite give false confidence?

| Risk | Assessment | Evidence |
|---|---|---|
| Happy-path only | ❌ Not a problem | Error paths, permission denials, stale versions, blocked finalization all tested |
| Mock-heavy | ❌ Not a problem on the backend | Integration tests use a real DB, real seeds, real HTTP. (The frontend suite does mock `apiClient` — appropriate for unit tests.) |
| Doesn't verify DB state | ❌ Not a problem | Tests read back through the API and assert values |
| Doesn't verify authorization | ❌ Not a problem | Dedicated permission-matrix and data-scope suites |
| **Doesn't verify tenant isolation at the DB layer** | ✅ **Real problem** | TEN-002 — all but one file runs as a BYPASSRLS superuser |
| Asserts 200 without checking the result | ❌ Not a problem on the sampled files | Assertions check payload values |
| Bypasses business logic | ❌ Not a problem | Tests go through routers and services |
| Weak assertions | ⚠️ Isolated | Some tests assert only the status field of a large result |
| Order-dependent | ⚠️ Possible | Shared seed fixtures (`clear_b1_seed`) with a history of teardown bugs (commits `cb3e2ba`, `4a31258`); no `pytest-randomly` |
| Flaky | ❌ Not observed | Full suite passed cleanly on the first run |
| **Tests for unimplemented config** | ✅ **Real problem** | ATT-001…005: because the fields are never read, no test can fail. Green CI does not mean the configured policy is applied. |
| **Coverage measurement** | ✅ **Absent** | No `pytest-cov`, no threshold, no report |

**The most dangerous false confidence in this codebase:** a screen exists to configure punch rounding,
the value validates, persists, appears in the policy version, is snapshotted onto every AttendanceDay,
and has tests confirming all of that — and the number is never used in any calculation. A user would
have no way to discover this.

---

## PART 25 — Error handling

| Concern | Finding | Status |
|---|---|---|
| Exception handling | Four global handlers: typed `AppError`, `RequestValidationError` (422), Starlette HTTP, catch-all 500 | 🟢 |
| Error taxonomy | Per-module `exceptions.py` — 643 lines in attendance, 811 in organisation. Every error has a stable code and status. | 🟢 |
| Validation errors | Field-level detail list with codes | 🟢 |
| Database errors | `IntegrityError` caught and mapped where a constraint is the intended control (e.g. `DuplicatePunchIdempotencyKeyError`) | 🟢 |
| Transaction rollback | Automatic on any exception (`core/db/session.py:66-68`) | 🟢 |
| Information leakage | Catch-all returns a generic message; the exception is discarded (`handlers.py:80`) | 🟡 **the exception is not logged either** |
| Background job failures | No retry policy, no `autoretry_for`, no dead-letter handling on any Celery task | 🟠 |
| External integration failures | S3 and SES exceptions are unhandled — they propagate to the 500 handler | 🟡 |
| Retry behaviour | None configured | 🟠 |
| User-facing errors | Consistent envelope with `request_id` | 🟢 |

### The worked example: leave approval

> Step 1 approve leave → Step 2 update balance → Step 3 project into attendance. If step 3 fails, what happens?

**Verified answer: the entire transaction rolls back, including the approval.**

`_apply_approval` (`leave/service.py:2401-2482`) runs inside the same request transaction as the
`status='APPROVED'` write. `LeaveProjectionService.sync` raises `AttendancePeriodClosedError` if any day
falls in a closed period; the exception propagates through `get_session`'s `except` branch
(`core/db/session.py:80-83`), which rolls back. There is no partially-approved, partially-synced state.
The ordering is deliberate — projections first, ledger debit last — and is documented at `:2410-2415`.

🟢 **This is correct and well-designed.** The same posture is applied in
`AttendanceRegularizationRequestService._apply_correction` and in `AttendancePeriodService.finalize`.

**The residual risk is not in HTTP requests but in Celery tasks**, where a failure mid-fan-out leaves
some companies accrued and others not, with no retry and no alert (OPS-006, OPS-003).

---

## PART 26 — Background jobs

| Task | Trigger | Frequency | Retry | Idempotent | Failure handling | Logging | Monitoring | Locking | Duplicate protection |
|---|---|---|---|---|---|---|---|---|---|
| `health.ping` | Manual | — | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | n/a |
| `employee_import.process_batch` | API-triggered | On demand | ❌ deliberate | ❌ **no re-entry guard** | Per-row error rows; batch status | ❌ | ❌ | ❌ | ❌ IMP-001 |
| `leave.run_monthly_accrual` | Beat | `0 1 1 * *` | ❌ | ✅ fan-out only | ❌ | ❌ | ❌ | ❌ | ❌ |
| `leave.accrue_company` | Fan-out | Per company | ❌ | ⚠️ **check-then-insert** | ❌ | ❌ | ❌ | ❌ | ❌ DAT-001 |
| `leave.run_comp_off_credit_sweep` | Beat | **Hourly** | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | Per `overtime_record_id` |
| `leave.credit_comp_off` | Fan-out | Per company | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| `leave.run_comp_off_expiry_sweep` | Beat | `30 1 * * *` | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| `leave.run_year_end_sweep` | Beat | `0 2 * * *` | ❌ | ⚠️ same as accrual | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Attendance generation** | — | — | — | — | — | — | — | — | ❌ **Does not exist** |
| **Notifications** | — | — | — | — | — | — | — | — | ❌ Does not exist |
| **Reports** | — | — | — | — | — | — | — | — | ❌ Does not exist |
| **Outbox sweep** | — | — | — | — | — | — | — | — | ❌ ADR-0012 unimplemented |

**Findings.**

- 🔴 **PAY-001** — no attendance generation job. This is the largest functional gap in the system.
- 🟠 **OPS-006** — Celery Beat has no leader election. Two beat replicas double-fire every schedule.
  Combined with DAT-001, that means double leave accrual.
- 🟠 **No task has a retry policy.** A transient DB blip during the monthly accrual silently skips a
  tenant until the following month.
- 🟠 **No task logs anything.** They return an integer count that goes to the Celery result backend and
  nowhere else.
- 🟡 The `asyncio.run` bridge in each task (`leave/tasks.py:42` etc.) creates a fresh event loop and
  engine per task invocation — correct but connection-inefficient at the hourly comp-off cadence.

### Bulk employee import — job-safety findings

`employee_import` is the only task triggered from a request rather than a schedule, and it is the only
one that creates employees. It deserves separate treatment.

**What is done well.** Each row runs inside `session.begin_nested()` (a savepoint), so one bad row
cannot abort the batch (`service.py:303-330`). Failures are captured per row with the raw CSV content and
a typed error code. The pipeline drives the employee module's own validated services rather than writing
to repositories directly, so an imported employee is validated identically to an interactively created
one. And `_commit_and_restore_rls` (`service.py:522-529`) fixes a genuinely subtle bug — `set_config`
with `is_local=true` is transaction-scoped, so committing mid-run would silently blank the RLS GUC.
Finding and documenting that is good work.

| ID | Finding | Severity | Evidence |
|---|---|---|---|
| **IMP-001** | **No re-entry guard.** `process_batch` does not check whether the batch is already `PROCESSING` or `COMPLETED` before starting (`service.py:443-448` — it only checks the row exists). Celery brokers deliver at-least-once; a redelivery after a worker crash or visibility-timeout expiry reruns the batch from row 1. Combined with mid-run commits, rows already created stay created. `employee_code` is `UNIQUE (company_id, employee_code)`, so explicitly-coded rows would collide and error — but **auto-generated codes would not**, producing silent duplicate employees. | 🟡 HIGH | `service.py:443`, `tasks.py:10-13` |
| **IMP-002** | `create_batch` commits mid-request (`service.py:161`) before calling `.delay()`. Deliberate and documented — the task needs the row visible. But if the enqueue then fails (Redis unavailable), the batch is permanently committed as `PENDING` with no retry, no timeout, and nothing that detects it. | 🟡 HIGH | `service.py:157-166` |
| **IMP-003** | `process_batch` commits mid-run at every 25-row progress flush. A crash leaves a partially-imported batch stuck at `PROCESSING` forever, with some employees created. The documented recovery is "re-submit the remaining rows as a fresh, smaller import" — but nothing records *which* rows succeeded beyond aggregate counters, so the operator must reconcile manually. | 🔵 MEDIUM | `service.py:331-334`, `tasks.py:10-13` |
| **IMP-004** | The whole CSV is buffered in memory at upload (`await file.read()`, `router.py:28`), and `MAX_IMPORT_ROWS = 1000` is enforced only *after* parsing the entire file (`service.py:181-182`). No `Content-Length` pre-check. | 🔵 MEDIUM | `router.py:28`, `schemas.py:52` |

**The deliberate no-retry decision is correct**, and its reasoning is sound (`tasks.py:10-13`: a blind
retry after partial failure risks duplicates). But it defends against Celery's *automatic* retry while
leaving *broker redelivery* — which is not optional — unguarded. A status check at the top of
`process_batch` closes IMP-001 in three lines.

---

## PART 27 — Performance audit

> **PERFORMANCE NOT VERIFIED.** No benchmark, load test, profiling result, or `EXPLAIN` plan exists
> anywhere in the repository. Everything below is a static read of the query patterns, not a measurement.

### Measured query cost of one `AttendanceDayService.calculate()` call

Counted from `_build_calculation_input` (`service.py:2711-3151`):

| Stage | Queries |
|---|---|
| Employment as-of (+ latest, on the failure path) | 1–2 |
| Assignment as-of | 1 |
| Company profile | 1 |
| Branch (if assigned) | 1 |
| Roster for date | 1 |
| Shift version as-of + breaks + duty blocks | 3 |
| Calendar resolution (8-scope walk + calendar + holiday links + holidays + weekly-off rules + exceptions) | up to 14 |
| Weekly-off PolicyAssignment walk | up to 8 |
| Attendance policy walk + version + 3 band tables | up to 12 |
| Overtime policy walk + version + rate rows + weekly/monthly sums | up to 12 |
| Regularization policy walk | up to 8 |
| Prior late-days / excess-break-days counters | 0–2 |
| Punches | 1 |
| Leave projections | 1 |
| Early-departure + on-duty regularization lookups | 2 |
| Writes: day row, OT record, breaks replace, audit | 4+ |
| **Total** | **~50–70 queries per employee-day** |

| Population | Employee-days / month | Estimated queries for a full month | Assessment |
|---|---|---|---|
| 100 | 3 000 | ~180 000 | Feasible but slow; requires 3 000 HTTP calls (PAY-001) |
| 1 000 | 30 000 | ~1.8 M | Not feasible through the current API |
| 10 000 | 300 000 | ~18 M | Not feasible |
| 50 000 | 1.5 M | ~90 M | Not feasible |
| 100 000 | 3 M | ~180 M | Not feasible |

### Other identified bottlenecks

| ID | Issue | Evidence |
|---|---|---|
| DAT-002 | **Zero pagination.** `GET /v1/attendance/days` with a month range returns every row for every visible employee. No `LIMIT` exists in any list repository. | `shared/pagination.py:14` defined but never used; no `.limit(` in any list query |
| DAT-003a | N+1 on attendance day listing — one break query per row | `attendance/service.py:2477` |
| DAT-003b | N+1 in the policy precedence walk — one query per scope level per policy kind | `calendar_resolution.py:301-314` |
| DAT-003c | N+1 in leave accrual — employees × leave types × (assignment walk + version + exists check) | `leave/service.py:1365-1409`. 1 000 employees × 5 types ≈ 50 000+ queries in one task |
| DAT-003d | N+1 in login — one company query per membership | `identity/service.py:63-68` |
| PERF-1 | Leave approval over a 30-day range triggers 30 synchronous full recomputes inside one HTTP request | `leave/service.py:2437-2455` → `attendance/service.py:5349` |
| PERF-2 | No caching of company profile, policy versions, or resolved assignments — all re-read per employee-day | — |
| PERF-3 | `computation_snapshot` JSONB is written on every recompute with no size bound | `attendance/models.py:590` |

**Required before Payroll volume:** a batch calculation path that resolves policies **once per
(policy-scope, date-range)** rather than once per employee-day, plus pagination on every list endpoint.

---

## PART 28 — Security audit

Static and safe validation only. No exploitation was attempted.

| Area | Finding | Severity |
|---|---|---|
| Authentication | JWT HS256, 15-min access TTL, 30-day refresh; session revocation checked on **every** request (`core/auth/dependencies.py:34-36`) | 🟢 |
| Password handling | argon2 via `argon2-cffi` with library defaults; min 8 chars + letter + digit | 🟡 policy is weak; no breach-list check, no rotation, no history |
| Sessions / tokens | **Refresh-token rotation with family-wide reuse detection** — a replayed token revokes the whole family (`identity/service.py:101-106`) | 🟢 Excellent |
| Account lockout | 5 failed attempts → 15-minute lock (`core/db/repositories/identity.py:169-170`) | 🟢 |
| Authorization / RBAC | See Part 13 | 🟢 |
| IDOR / BOLA | None identified; target-id checks are applied consistently | 🟢 |
| Tenant isolation | See Part 12 | 🟢 |
| SQL injection | No string-concatenated SQL in the application. Migrations use static DDL. | 🟢 |
| XSS | React escapes by default; no `dangerouslySetInnerHTML` found | 🟢 |
| Stored XSS via upload | Client-supplied `content_type` stored verbatim and echoed by the presigned GET | 🟡 SEC-005 |
| CSRF | Bearer tokens in an `Authorization` header, no cookie auth → not applicable | ⚪ |
| SSRF | No user-controlled outbound URL fetch | ⚪ |
| File upload | Size limit ✅ (`ONBOARDING_DOCUMENT_MAX_SIZE_BYTES`); **no MIME allow-list, no magic-byte check, no filename sanitisation** | 🟡 SEC-005 |
| Path traversal | `s3_key = f"onboarding/{company_id}/{case_id}/{document_id}/{filename}"` interpolates the raw client filename (`onboarding/service.py:571`). S3 keys are flat, so this is key-pollution rather than filesystem traversal — but it is unsanitised input in a storage path. | 🟡 |
| Secrets | None committed (verified); `.gitignore` covers `.env*` and `apps/api/env/.env.*` | 🟢 |
| Sensitive logging | No password/token logging found | 🟢 |
| PII exposure | Statutory ids (PAN/Aadhaar/PF/UAN) and bank details stored in plaintext columns — **no column-level encryption** | 🟡 |
| API exposure | `/docs`, `/redoc`, `/v1/openapi.json` are **unconditionally enabled in every environment** (`app.py:30-32`) | 🟡 |
| **CORS** | `allow_origins=["*"] if settings.is_development else []` (`app.py:38`). Production gets **zero** allowed origins → the deployed frontend cannot call the API. Development gets `*` with `allow_credentials=True`, an invalid combination browsers reject. | 🟠 **SEC-001** |
| Security headers | **None.** No HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`, or `Referrer-Policy`. No `TrustedHostMiddleware`. | 🟠 SEC-004 |
| Proxy headers | Not handled. `rate_limit` keys on `request.client.host` (`shared/rate_limit.py:49`), which behind a load balancer is the balancer — making the limiter global rather than per-client. | 🟠 SEC-004 |
| **Rate limiting** | Applied to exactly **one** endpoint — `/companies/register` (`organisation/router.py:88`). `/auth/login`, `/auth/token/refresh`, and the entire public onboarding token surface are unlimited. | 🟠 **SEC-002** |
| Brute-force protection | Per-account lockout only. No IP throttling, so password spraying across many accounts is unthrottled; and the lockout itself is an account-DoS primitive. | 🟠 |
| Token storage (client) | Access **and refresh** tokens in `localStorage` — documented trade-off, no HttpOnly cookie path exists | 🟠 SEC-003 |
| Dependency vulnerabilities | **Never scanned.** No `pip-audit`, `safety`, Dependabot, or `npm audit` in CI. | 🟡 SEC-011 |
| Password reset | ❌ Not implemented | 🟡 |
| Email verification | ❌ Not implemented | 🟡 |
| MFA | ❌ Not implemented | 🔵 |

---

## PART 29 — Secrets & configuration

| Check | Finding | Status |
|---|---|---|
| `.env` handling | `pydantic-settings` with `env_file=".env"`, validated at boot, fail-fast | 🟢 |
| Secrets in git | **None.** `git ls-files` finds only `*.example` templates; a scan for `AKIA`/private-key headers found nothing. | 🟢 |
| `.gitignore` | Covers `.env`, `.env.local`, `.env.*.local`, and `apps/api/env/.env.*` with a `!*.example` negation | 🟢 |
| Environment separation | Four committed templates: `.env.dev.example`, `.env.qa.example`, `.env.staging.example`, `.env.production.example` | 🟢 |
| Secrets management | **No vault, KMS, or secret-manager integration.** Secrets are plain environment variables. | 🟡 |
| JWT secrets | Minimum length 16 enforced by a pydantic validator; dev defaults are literal `change-me-...` strings | 🟡 — nothing *prevents* the dev default in production |
| DB credentials | Runtime role (`hrms_app`) and migration role (`hrms`) are **separate URLs**, and `Settings` deliberately has no field for the migration URL so the app process never loads it | 🟢 Excellent |
| Encryption keys | Not applicable — no column-level encryption exists | ⚪ |
| Third-party credentials | S3/SES credentials via env; `email_provider` is an explicit flag rather than inferred from credential presence (`settings.py:40-47`) | 🟢 Thoughtful |
| Production guardrails | **None.** No startup assertion that `environment == "production"` implies non-default secrets, TLS-required DSNs, or disabled `/docs`. | 🟠 |

---

## PART 30 — Deployment audit

**Actual deployment path today:**

```
Code → GitHub → CI (lint · format · mypy · import-linter · pytest[unit only, integration fails])
     → ??? nothing further exists ???
```

| Element | Present | Evidence |
|---|---|---|
| Dockerfile (API) | ✅ | `apps/api/Dockerfile` — multi-stage, uv, `uvicorn` |
| Dockerfile (web) | ❌ | None |
| Production compose / Helm / Terraform / ECS task def | ❌ | None |
| CI | ⚠️ Incomplete | `.github/workflows/ci.yml` — one job, no DB service, no frontend |
| CD | ❌ | No deploy workflow exists |
| Migration step in any pipeline | ❌ | Never invoked |
| Startup sequence | ⚠️ | `lifespan` creates the engine; **does not verify DB connectivity or migration version** |
| Health check | ⚠️ | `/health` exists but does not check DB or Redis; no liveness/readiness split; no `HEALTHCHECK` in the Dockerfile |
| Rollback | ❌ | No procedure; `20260803124757.downgrade()` raises `NotImplementedError` |
| Zero/low downtime | ❌ | Not addressed |
| Environment configuration | ✅ | Four env templates |
| Database backups | ❌ | See Part 31 |
| Logs | ⚠️ | stdout only, no shipping |
| Monitoring | ❌ | See Part 32 |

**Additional container findings.** The image runs as **root** (no `USER` directive). It runs a single
`uvicorn` process with default settings, although `gunicorn>=23.0.0` is a declared dependency and is
never used — so there is no worker management, no graceful-restart story, and no CPU utilisation beyond
one core. There is no `.dockerignore`, so build context includes the local `.venv`.

**OPS-001 🔴 — there is no production deployment path.** This is not a hardening gap; the capability does
not exist.

---

## PART 31 — Backup & disaster recovery

| Question | Answer |
|---|---|
| Database backup frequency | **Not defined.** Nothing in the repository configures, schedules, or documents a backup. |
| Retention | Not defined |
| Backup verification | Not defined |
| Restore testing | **Never performed** — no procedure exists to perform |
| File (S3) backup | Not defined. No versioning or lifecycle policy on the documents bucket. |
| Disaster recovery plan | Does not exist |
| RPO | Undefined |
| RTO | Undefined |

The only persistence configuration in the repo is a Docker named volume for local development
(`docker-compose.yml:61-64`).

🔴 **OPS-002.** Per the audit brief's own rule — *do not claim backups are reliable unless restore
testing exists* — this area is a blocker for **production**, though not for beginning Payroll
*development*. It must be closed before any tenant's payroll data exists.

---

## PART 32 — Observability

| Capability | Present | Evidence |
|---|---|---|
| Application logs | ⚠️ Configured, barely used | `structlog` JSON to stdout (`core/observability/logging.py`). `get_logger` has **no call sites in any module**. |
| Request/response logging | ❌ | `TenancyMiddleware` sets a request id and echoes it in the response header, but logs nothing |
| Error tracking | ❌ | Sentry is a comment: `# Sentry hook lands here in a later sprint` (`core/errors/handlers.py:79`). The unhandled exception is discarded (`_ = exc`) — **not even logged.** |
| Metrics | ❌ | No Prometheus, StatsD, or OpenTelemetry |
| Health checks | ⚠️ | `/health` with no dependency probing |
| Database monitoring | ❌ | None |
| Background-job monitoring | ❌ | No Flower, no task result inspection, no failure alerting |
| Alerting | ❌ | None |

### The brief's three questions, answered honestly

> **If Attendance calculation starts failing in production, how would we know?**
> A user would report it. The 500 response contains a `request_id` that appears in no log anywhere.

> **If Leave balance calculation fails for 500 employees, how would we know?**
> We would not. `leave.accrue_company` returns an integer to the Celery result backend and logs nothing.
> A tenant would simply have no accrual that month, and would discover it when an employee's balance
> looked wrong.

> **If database errors increase, how would we know?**
> We would not. Nothing measures database health, connection-pool saturation, or error rates.

🔴 **OPS-003.** Observability is the area with the largest gap between what the architecture documents
describe and what exists.

---

## PART 33 — Data migration & seeding

| Concern | Finding | Status |
|---|---|---|
| Initial data | `seed_b1_foundation` seeds the permission catalogue from module-owned constants (`seed/bootstrap.py:58-63`) | 🟢 Well factored |
| Seed scripts | `scripts/seed.py`, `scripts/seed_plans.py` | 🟢 |
| Demo data | Two demo companies, `admin@example.com` / `viewer@example.com`, password `DemoPass123!` — documented in `docs/development/DEMO_SEED_CREDENTIALS.md` | 🟡 |
| **Production seed safety** | 🔴 **`seed.py` has no environment guard.** Nothing prevents it running against a production database and creating a known-credential admin account with every permission. | 🟠 |
| Migration ordering | Linear `down_revision` chain, timestamp-named, 61 revisions | 🟢 |
| Migration rollback | Most revisions implement `downgrade()`; the **initial** one raises `NotImplementedError` | 🟡 |
| Data repair scripts | None | 🔵 |
| Idempotency of seeds | `_ensure_*` helpers make the seed re-runnable | 🟢 |

**Required:** add `if settings.environment != "development": raise SystemExit(...)` to the demo seed, and
separate the permission-catalogue seed (which **must** run in production) from the demo-user seed (which
must never).

---

## PART 34 — Documentation audit

211 markdown documents. Genuinely unusual depth: 15 ADRs, module-level decision logs
(`WORKFORCE_ATTENDANCE_DECISION_LOG.md`, `LEAVE_DECISION_LOG.md`) with numbered, dated decisions, a
business-rules corpus with precedence matrices and scenario catalogues, and client sign-off records.

The in-code documentation is equally strong — most modules carry a docstring explaining *why* a design
was chosen, which decision it implements, and what was deliberately **not** built.

| Category | Present | Assessment |
|---|---|---|
| Architecture | ✅ Extensive | `docs/architecture/` — 16 documents |
| ADRs | ✅ | 15, covering multitenancy, effective dating, ledger, money, outbox |
| API documentation | ⚠️ | Generated OpenAPI only; no published reference or examples |
| Business rules | ✅ Extensive | `docs/business-rules/` — precedence, scenarios, conflicts, gaps |
| Attendance | ✅ Extensive | Business rules, config catalogue, precedence, client sign-off |
| Leave | ✅ | `LEAVE_DECISION_LOG.md` LD-01…LD-23 |
| Database | ⚠️ | `docs/database/Database_Architecture.md` — not regenerated per migration |
| Deployment | ❌ | None |
| Security | ⚠️ | RLS role migration plan only; no threat model, no security policy |
| Configuration | ✅ | `ATTENDANCE_V1_CONFIGURATION_CATALOG.md` — **but see DOC-001** |
| Runbooks | ❌ | None |

| ID | Finding | Severity |
|---|---|---|
| DOC-001 | **DOCUMENTATION / IMPLEMENTATION CONFLICT.** The configuration catalogues document the behaviour of punch rounding, AUTO_CLOSE, half-day split, excess-break behaviour, and night-window OT. The engine implements none of them (ATT-001…005). | 🟠 |
| DOC-002 | `docs/business-rules/policies/` is **untracked in git** (`git status` → `?? docs/business-rules/policies/`), including `MASTER_POLICY_PRECEDENCE_MATRIX.md` and `HRMS_POLICY_DECISIONS_CLIENT_REVIEW.md` | 🟡 |
| DOC-003 | No deployment, security, or operational documentation | 🟡 |
| DOC-004 | Untracked non-project artifacts at the repo root: `mavericks-kit.zip` (3.9 MB), `mavericks-kit/`, `jersouy/`, `mavericks-kit-preview.jpg` | 🔵 |
| DOC-005 | `docs/archive/superseded-v1-nestjs/` (15 documents) describes a superseded NestJS architecture and sits alongside current docs | 🔵 |

---

## PART 35 — Code quality review

**Strengths.** Uniform module shape. `ruff` (E, F, I, N, B, UP, BLE, TRY) and `mypy --strict` both pass
in CI. Import-linter enforces the core/shared/modules layering. Consistent naming. Errors are typed with
stable codes. Comments explain rationale, not mechanics — and reference the decision that produced them.

| Issue | Finding | Severity |
|---|---|---|
| Duplication | Three near-identical approval state machines (regularization, overtime, leave) — a conscious "mirrored not shared" decision (LD-05), but ~600 lines of parallel logic that must now be fixed three times | 🟡 |
| Complexity | `_evaluate_fixed_or_flex` is ~200 lines with 6 override sources; `submit` (leave) is ~290 lines with 14 sequential validations | 🟡 |
| Long functions | `LeaveApplicationService.submit` (1880–2169), `_build_calculation_input` (2711–3151) | 🟡 |
| Large classes / god services | `attendance/service.py` 5 480 lines / 9 classes; `organisation/service.py` 3 895 | 🟡 ARC-001 |
| Circular dependencies | `leave.service` ↔ `attendance.service`, resolved only by function-scoped imports | 🟡 ARC-002 |
| **Dead code** | `apply_rounding` (zero call sites); `ingestion/routes.py` (stub); `PaginationMeta` (never constructed); `MoneyAmount` (never used); `get_logger` (never called); `gunicorn` (unused dependency) | 🟠 |
| **Dead configuration** | ~15 policy fields stored, validated, exposed, and never read (ATT-001…007, PAY-011) | 🟠 |
| Magic numbers | ±2 h punch-window padding, +12 h flex lookahead (`calculation.py:418, 431`); 5 failed logins / 15-minute lock (`identity.py:169-170`) | 🔵 |
| Hard-coded policy | `late_count_window` is stored but the window is hard-coded to the calendar month (`service.py:2952`) | 🟡 |
| Inconsistent naming | `FIRST_HALF`/`SECOND_HALF` vs `FIRST`/`SECOND`; `attendance_date` vs `calendar_date` vs `roster_date` for the same concept | 🔵 |
| Poor error handling | Catch-all handler discards the exception without logging (`handlers.py:80`) | 🟠 |
| Unsafe defaults | `allow_origins=["*"]` in development with `allow_credentials=True` | 🟡 |
| Missing validation | No MIME allow-list on upload (SEC-005) | 🟡 |
| Separation of concerns | Excellent between calculation and orchestration; weaker within Leave, where rules live inline in the service | 🟡 |

---

## PART 36 — Technical debt

See [`TECHNICAL_DEBT_REGISTER.md`](./TECHNICAL_DEBT_REGISTER.md) for the full register.

Summary by timing:

| Classification | Count | Representative items |
|---|---|---|
| **Must fix before Payroll** | 11 | PAY-001…008, PAY-010, TST-001, SEC-001 |
| **Should fix before production** | 14 | SEC-002/003/004, OPS-001/002/003, DAT-001/002, TST-002/003 |
| **Can fix during Payroll** | 12 | ATT-006…013, ARC-001/002, DAT-004…007 |
| **Can defer** | 8 | DAT-012 (partitioning), DOC-004/005, ATT-012, SEC-010, ARC-004 |

---

## PART 37 — Payroll blocker analysis

See [`PAYROLL_BLOCKER_REGISTER.md`](./PAYROLL_BLOCKER_REGISTER.md) for the full register with evidence
and fixes. The headline:

| ID | Blocker | Severity |
|---|---|---|
| PAY-001 | No batch attendance generation → periods cannot be finalized at scale | 🔴 |
| PAY-002 | `AttendancePeriodSummary` has no paid-days figure | 🔴 |
| PAY-003 | Summary buckets double-count holidays and omit five statuses | 🔴 |
| PAY-004 | Pre-joining days are paid at 1.00 | 🔴 |
| TST-001 | CI does not run the tests that verify any of this | 🔴 |
| PAY-005 | Post-exit days carry LOP 1.00 | 🟠 |
| PAY-006 | INCOMPLETE days have neither paid nor LOP until lock | 🟠 |
| PAY-007 | Lock-time paid/LOP rewrite is unaudited and untested | 🟠 |
| PAY-008 | Attendance results are not exactly reproducible | 🟠 |
| PAY-010 | Leave balance is never re-checked at approval | 🟠 |
| **PAY-013** | **Timezone change is unguarded; the guard written for this case is a no-op** | 🟠 |
| **PAY-014** | **Onboarding activation creates no compensation record — onboarded staff have no CTC** | 🟠 |

---

## PART 38 — Production readiness gates

| # | Gate | Verdict | Evidence |
|---|---|---|---|
| 1 | Architecture | ⚠️ **PASS with conditions** | Clean module shape, pure-engine split, enforced core layering. Conditions: ARC-001 (god service), ARC-002 (unconstrained module edges) |
| 2 | Data integrity | ❌ **FAIL** | Strong constraints and append-only tables, but DAT-001 (unconstrained accrual idempotency) and PAY-010 (no balance guard at approval) allow incorrect financial data |
| 3 | Attendance | ❌ **FAIL** | PAY-001 (no batch generation), PAY-004/005/006 (paid/LOP semantics), ATT-001…005 (configured policy not applied) |
| 4 | Leave | ❌ **FAIL** | PAY-010, DAT-001. Everything else in Leave is sound. |
| 5 | Security | ❌ **FAIL** | SEC-001 (production CORS unusable), SEC-002 (rate limiting on 1 endpoint), SEC-004 (no security headers). No breach vector found — these are hardening and deployability failures. |
| 6 | Authorization | ✅ **PASS** | `require_permission` + `DataScope` + target-id checks applied consistently; no IDOR found; dedicated permission and data-scope suites |
| 7 | Tenant isolation | ⚠️ **PASS with conditions** | 70/79 tables RLS-enforced, non-superuser runtime role, client tenant id never trusted. Condition: TEN-002 — the suite runs as a BYPASSRLS superuser, so the backstop is largely unverified |
| 8 | Testing | ❌ **FAIL** | 1 145 tests pass locally, but **CI runs none of the 783 integration tests** (TST-001). No frontend CI (TST-002), no coverage (TST-003), no concurrency tests (TST-004) |
| 9 | Historical integrity | ❌ **FAIL** | Locked periods are genuinely immutable ✅, but PAY-008 means an unlocked day is not reproducible, and there is no engine-version stamp |
| 10 | Auditability | ⚠️ **PASS with conditions** | Comprehensive write-side audit + per-entity timelines. Conditions: the lock-time paid/LOP rewrite is unaudited; there is no audit read API |
| 11 | Deployment | ❌ **FAIL** | OPS-001 — no CD, no web image, no migration step, no rollback, root container |
| 12 | Backup & recovery | ❌ **FAIL** | OPS-002 — nothing exists |
| 13 | Monitoring | ❌ **FAIL** | OPS-003 — nothing exists; unhandled exceptions are not even logged |
| 14 | Payroll input readiness | ❌ **FAIL** | PAY-002/003 — the frozen summary is not a sufficient Payroll input |

**Result: 2 PASS · 3 PASS-with-conditions · 9 FAIL.**

---

## PART 39 — Final recommendation

# 🟠 NOT READY — FOUNDATION FIXES REQUIRED

### Why not 🔴 BLOCKED

No cross-tenant data leakage was found. No IDOR or BOLA was found. No SQL injection was found. No
floating-point money arithmetic exists. No data-corruption path was found in normal operation. The
tenant-isolation architecture is genuinely well built, the authorization model is applied consistently
and correctly, the period-lock mechanism does what it claims, and 1 145 tests pass against a real
database. There is no emergency here.

### Why not 🟢 or 🟡

Payroll's job is to turn attendance and leave into money. Today it cannot, for four independent reasons:

1. **The input cannot be produced.** Closing a period requires an `AttendanceDay` row for every
   employment-day, and the only way to create one is a single-employee-single-date HTTP call. There is no
   batch endpoint and no job. A 100-employee month needs ~3 000 calls; a 1 000-employee month cannot be
   done at all.
2. **The input, once produced, is incomplete and internally inconsistent.** The frozen
   `AttendancePeriodSummary` — the artifact explicitly designed as Payroll's contract — contains no
   paid-days figure, double-counts a worked holiday as both `present_days` and `holiday_days`, and
   assigns no bucket at all to INCOMPLETE, NOT_EXPECTED, ON_DUTY, CONFIG_ERROR, NOT_JOINED, or EXITED
   days.
3. **Some of the input is wrong.** A day before joining carries `paid_day_fraction = 1.00`. A day after
   exit carries `lop_fraction = 1.00`. A leave approval can drive a balance negative with no guard,
   because the balance is checked at submission and never again.
4. **Roughly fifteen policy settings that HR can configure are never read by the engine.** Punch
   rounding, AUTO_CLOSE, half-day split, excess-break behaviour, night-window OT — each has a screen, a
   validator, a database column, a snapshot on every AttendanceDay, and passing tests. None of them
   changes any result. Building Payroll on top of this means building on rules that appear to exist.

And a fifth reason that makes the other four dangerous: **CI does not run the tests that would catch any
of it.** The workflow provisions no database, so the 783 integration tests are not a merge gate.

### The honest framing

This is a well-engineered codebase with a missing operational layer and a set of specific, bounded
correctness defects — not a codebase that needs rework. Every finding above is a targeted fix, and none
requires redesigning anything that works. The pure-engine split, the version-snapshot pattern, the
append-only ledger, the RLS role separation, and the period-lock design are all exactly what Payroll
needs underneath it. They should not be touched.

**Estimated remediation for the P0 set: 3–4 focused engineering weeks.** Payroll *design* — data model,
the input contract, ADRs — can and should proceed in parallel starting now, using
[`PAYROLL_FOUNDATION_CONTRACT.md`](./PAYROLL_FOUNDATION_CONTRACT.md) as the specification. Payroll
*implementation* should wait for P0 to land.

---

## PART 40 — Prioritized remediation plan

Owners are left blank where not already known, per the audit brief.

### Priority 0 — BLOCKERS (must land before Payroll implementation starts)

| Priority | Finding | Module | Required action | Owner | Verification | Status |
|---|---|---|---|---|---|---|
| P0 | TST-001 | CI | Add `services: postgres/redis` to `ci.yml`; run migrations; point `DATABASE_URL` at **`hrms_app`**, not `hrms` | — | CI runs all 1 145 tests green | Open |
| P0 | PAY-001 | attendance | Build a batch calculation path: `POST /v1/attendance/days/calculate-batch` (employee set × date range) **and** a Celery task, resolving policies once per (scope, range) | — | 1 000-employee month completes in one call; period finalizes | Open |
| P0 | PAY-002 | attendance | Add `paid_days` and `payable_days` to `attendance_period_summary` | — | Migration + frozen-summary test | Open |
| P0 | PAY-003 | attendance | Rewrite `_aggregate_day_rows`: mutually exclusive status buckets; stop double-counting worked holidays; add a reconciliation assertion that buckets sum to the period's employment days | — | Property test over generated day sets | Open |
| P0 | PAY-004 | attendance | `NOT_JOINED` → `paid_day_fraction = 0.00` | — | Unit test on `_terminal_result` | Open |
| P0 | PAY-005 | attendance | `EXITED` → `lop_fraction = 0.00` (out-of-employment ≠ loss of pay) | — | Unit test | Open |
| P0 | PAY-010 | leave | Re-check balance inside `_apply_approval` under `SELECT ... FOR UPDATE` on the employee's ledger; honour `allow_negative_balance` | — | Concurrency test: two approvals, one succeeds | Open |
| P0 | SEC-001 | core | Drive CORS from a `cors_allowed_origins` setting; fail boot if production has an empty list | — | Integration test per environment | Open |
| P0 | DAT-001 | leave | Add `UNIQUE (company_id, employee_id, leave_type_id, entry_type, effective_date)` where `entry_type IN ('ACCRUAL','CARRY_FORWARD')`; catch `IntegrityError` | — | Concurrency test | Open |
| P0 | PAY-008 | attendance | Persist sibling-day inputs into `computation_snapshot`; add `ENGINE_VERSION` + an `attendance_day.engine_version` column | — | Recompute test asserting snapshot completeness | Open |
| P0 | PAY-007 | attendance | Make the lock-time resolution explicit (re-read rows after update, or resolve in Python before aggregating); write an `audit_log` row for it | — | Test asserting frozen `lop_days` after INCOMPLETE resolution | Open |
| P0 | **PAY-014** | onboarding | Create `employee_compensation` at activation, or require compensation input before a case can be activated. Correct the docstring at `onboarding/schemas.py:17`. | — | Integration test asserting an activated employee has a compensation row | Open |
| P0 | **PAY-013** | organisation | Implement `_assert_timezone_change_allowed` — refuse when a CLOSED period or any calculated `AttendanceDay` exists. Add the same guard to `update_branch`. | — | Test asserting the change is refused | Open |

### Priority 1 — CRITICAL (before the Payroll architecture is finalized)

| Priority | Finding | Module | Required action | Owner | Verification | Status |
|---|---|---|---|---|---|---|
| P1 | ATT-001 | attendance | Implement `punch_rounding`, **or** remove the fields and the UI and document the removal | — | Unit test per mode | Open |
| P1 | ATT-002 | attendance | Implement `AUTO_CLOSE` (synthetic OUT + `auto_closed=true`), or remove | — | Unit test | Open |
| P1 | ATT-003 | attendance | Implement `half_day_split`, or remove | — | Unit test | Open |
| P1 | ATT-005 | attendance | Implement night-window OT evaluation, or remove `night_window_*` | — | Unit test | Open |
| P1 | PAY-011 | leave | Implement `allow_negative_balance`, or remove it | — | Unit test | Open |
| P1 | PAY-006 | attendance | Decide and implement INCOMPLETE's pre-lock paid/LOP semantics | — | Test | Open |
| P1 | PAY-012 | organisation | Carry `off_fraction` through to a half-day weekly off, or remove the column | — | Unit test | Open |
| P1 | TEN-002 | tests | Run the whole suite as `hrms_app`; keep one `hrms`-role fixture for seeding only | — | Suite green under RLS | Open |
| P1 | DAT-002 | api | Add cursor or offset pagination to every list endpoint, with a hard max page size | — | Test asserting a bounded response | Open |
| P1 | ARC-003 | attendance/leave | Declare `leave_day_projection` the Payroll-facing read model; add a reconciliation check against `leave_application_day` | — | Reconciliation test | Open |

### Priority 2 — HIGH (before production, in parallel with Payroll)

| Priority | Finding | Module | Required action | Owner | Verification | Status |
|---|---|---|---|---|---|---|
| P2 | OPS-003 | core | Sentry (or equivalent) + structured request logging + actually log the caught exception in `handlers.py:80` | — | Induced error appears in the tracker | Open |
| P2 | OPS-001 | infra | CD pipeline, web image, migration step, rollback runbook, non-root container, gunicorn workers | — | Staging deploy + rollback rehearsal | Open |
| P2 | OPS-002 | infra | Automated backups + a **rehearsed restore** with documented RPO/RTO | — | Restore drill signed off | Open |
| P2 | SEC-002 | api | Rate-limit `/auth/login`, `/auth/token/refresh`, and `/public/onboarding/*` | — | Test asserting 429 | Open |
| P2 | SEC-004 | core | Security-headers middleware, `TrustedHostMiddleware`, proxy-header handling, `/docs` off in production | — | Header assertions | Open |
| P2 | OPS-006 | infra | Single Beat instance or a distributed lock per scheduled task | — | Deployment constraint documented | Open |
| P2 | OPS-004 | core | Split `/health/live` and `/health/ready` (readiness probes DB + Redis); add `HEALTHCHECK` | — | Probe test | Open |
| P2 | TST-002 | CI | Frontend job: `tsc --noEmit`, `next lint`, `vitest run`, `next build` | — | CI green | Open |
| P2 | TST-003 | CI | `pytest-cov` with a ratchet threshold | — | Coverage report published | Open |
| P2 | TST-004 | tests | Concurrency tests for approval, accrual, and finalization | — | Tests pass | Open |
| P2 | OPS-010 | leave | Celery retry policies + failure logging on every task | — | Induced failure retries and alerts | Open |
| P2 | Seed | seed | Environment guard on the demo seed; split catalogue seed from demo seed | — | Attempt against non-dev exits non-zero | Open |
| P2 | Audit | core | Audit-log read API + UI, gated by a new permission | — | Endpoint test | Open |
| P2 | **IMP-001** | employee_import | Refuse `process_batch` when the batch is not `PENDING` — closes broker-redelivery duplication | — | Test invoking the task twice | Open |
| P2 | **IMP-002** | employee_import | Detect and surface batches stuck at `PENDING`/`PROCESSING` beyond a threshold | — | Monitoring check | Open |

### Priority 3 — MEDIUM (during Payroll)

ATT-004 · ATT-006 · ATT-007 · ATT-009 · ATT-010 · ATT-011 · ATT-013 · DAT-004 · DAT-005 · DAT-006 ·
SEC-005 · SEC-006 · SEC-011 · ARC-001 · ARC-002 · DOC-001 · DOC-002 · DAT-010 · SEC-007

### Priority 4 — LOW (deferrable)

ATT-008 · ATT-012 · DAT-007 · DAT-009 · DAT-012 · SEC-003 · SEC-010 · ARC-004 · DOC-004 · DOC-005 ·
frontend a11y · DST test coverage · dead-code removal

---

## PART 41 — Payroll readiness contract

**Only assumptions verified during this audit appear here.** See
[`PAYROLL_FOUNDATION_CONTRACT.md`](./PAYROLL_FOUNDATION_CONTRACT.md) for the full contract.

| Payroll assumption | Verified? | Evidence | Risk if false |
|---|---|---|---|
| A CLOSED period's `AttendanceDay` rows are immutable | ✅ **Yes** | `bulk_lock:1222` sets `is_locked`; `replace_derived_fields:1104` filters `is_locked = false`; `_ensure_date_open:1915` refuses every mutation | Retroactive change to already-paid figures |
| No punch, roster, regularization, OT decision, or leave projection can enter a CLOSED period | ✅ **Yes** | `_ensure_date_open` called from `record_punch`, roster writes, regularization submit, OT approve/reject, `LeaveProjectionService.sync`/`cancel` | Same |
| Reopening a period is permission-gated, reason-required, and audited | ✅ **Yes** | `ATTENDANCE.UNLOCK` (`router.py:1436`), `reopen:5176-5219` | Silent unlock |
| Employment dates are authoritative and non-overlapping | ✅ **Yes** | `employment_no_overlap` GiST + CHECK tying `last_working_day` to `TERMINATED` | Wrong pro-rata window |
| Effective-dated org data is resolvable as-of any date | ✅ **Yes** | `get_assignment_as_of`, `resolve_shift_version_as_of`, `find_effective_as_of` | Wrong policy applied |
| Published policy versions are immutable | ✅ **Yes** | Publish freezes the row; edits require a new version; GiST prevents overlap | Retroactive rule change |
| Every AttendanceDay records the exact policy/shift/calendar versions used | ✅ **Yes** | Six version FKs on `attendance_day` | Unexplainable results |
| The OT multiplier is informational, never applied as money | ✅ **Yes** | `configured_multiplier` snapshotted on `overtime_record`; no monetary code in Attendance (ADR-0006, WD-03 §12.1) | Double-applied rate |
| All durations are integer minutes; no float touches them | ✅ **Yes** | Every minute field is `Integer`; fractions are `Decimal` | Rounding drift |
| The leave ledger is append-only; balance is always `SUM(amount)` | ✅ **Yes** | No update path; ADR-0004 | Silent balance rewrite |
| Approvals are recoverable stage-by-stage | ✅ **Yes** | Four `*_action` timelines + `audit_log` | No evidence trail |
| Tenant data is isolated at the database layer | ⚠️ **Designed, weakly verified** | 70/79 tables RLS+FORCE, non-superuser role — but tests run as a BYPASSRLS superuser (TEN-002) | Cross-tenant payroll |
| `AttendancePeriodSummary` is a complete payroll input | ❌ **NO** | No paid-days column; buckets double-count and under-cover (PAY-002/003) | **Wrong salary** |
| `paid_day_fraction` is correct for every status | ❌ **NO** | NOT_JOINED = 1.00 (PAY-004); INCOMPLETE = 0.00 until lock (PAY-006) | **Wrong salary** |
| `lop_fraction` is correct for every status | ❌ **NO** | EXITED = 1.00 (PAY-005) | **Wrong deduction** |
| Attendance can be reproduced exactly | ❌ **NO** | Sibling-day inputs unsnapshotted; no engine version (PAY-008) | Cannot defend a payslip |
| Leave balances cannot go negative | ❌ **NO** | Not re-checked at approval (PAY-010) | Negative-balance payout |
| Configured attendance policy is the applied policy | ❌ **NO** | ~15 fields never read (ATT-001…007) | Payroll built on phantom rules |
| Leave balances are frozen at period close | ❌ **NO** | No leave period exists; the ledger accepts any `effective_date` | Balance moves after payroll |
| A period can be finalized in practice | ❌ **NO** | PAY-001 | No payroll input at all |

---

## PART 42 — What Payroll should not assume

See [`PAYROLL_FOUNDATION_CONTRACT.md`](./PAYROLL_FOUNDATION_CONTRACT.md) §"Must not assume". Each rule
below is supported by a finding in this audit.

**Payroll must NOT assume:**

1. **That current configuration equals historical configuration.** A back-dated policy version publish
   can change an *unlocked* historical day. Only the lock stops it. (Part 21)
2. **That current policy applies to historical records.** Always resolve by date. The engine already
   does; Payroll must too. (Part 10)
3. **That attendance can always be recalculated to the same answer.** Recomputing an unchanged day can
   yield different OT and status because of sibling-day dependencies. (PAY-008)
4. **That approved leave can never change.** It can — until the period closes. After that it cannot.
   (Part 9)
5. **That OT classification implies a monetary amount.** `configured_multiplier` is a snapshot for
   Payroll to interpret, deliberately never applied. (ADR-0006)
6. **That a database field existing means the policy is implemented.** Fifteen configurable fields are
   stored, validated, exposed, snapshotted — and never read. (ATT-001…007, PAY-011)
7. **That frontend restrictions guarantee authorization.** They do not. Backend enforcement is separate
   and, in this codebase, correct — but it is the only control. (Part 13, Part 15)
8. **That a successful API response means the transaction completed correctly.** It does here, because
   one request is one transaction — but Payroll must preserve that property in its own writes.
   (Part 16)
9. **That `AttendancePeriodSummary` buckets sum to the period length.** They do not. Five statuses land
   in no bucket, and a worked holiday lands in two. (PAY-003)
10. **That `present_days + half_days` yields payable days.** There is no paid-days figure in the frozen
    summary at all. (PAY-002)
11. **That a leave balance is non-negative.** Nothing enforces it at approval. (PAY-010)
12. **That a leave balance read today equals the one read at period close.** Leave has no period
    concept; the ledger accepts entries with any effective date. (Part 22)
13. **That an unlocked period is safe to read.** It is not. Payroll must read only `CLOSED` periods, and
    that should be enforced in code, not documentation. (Part 21)
14. **That background jobs ran.** Nothing monitors, retries, or alerts on them. A tenant can silently
    miss a month of accrual. (Part 26, Part 32)
15. **That the tests passing means the rules are right.** CI runs none of the integration tests.
    (TST-001)

---

## Final audit questions

Each answered explicitly, as required.

**1. Can we trust Attendance paid-day calculations?**
**No, not yet.** The arithmetic for PRESENT/HALF_DAY/ABSENT is correct and tested. But NOT_JOINED days
are paid at 1.00 (PAY-004), INCOMPLETE days are neither paid nor LOP until lock (PAY-006), and the
frozen summary Payroll is meant to read carries no paid-days figure at all (PAY-002).

**2. Can we trust Attendance LOP calculations?**
**No, not yet.** EXITED days carry LOP 1.00 (PAY-005). The lock-time INCOMPLETE resolution that produces
final LOP is unaudited and untested (PAY-007). `summary.lop_days` itself is computed correctly from
`lop_fraction` — the fractions feeding it are the problem.

**3. Can we trust Leave balances?**
**Partially.** The append-only ledger with `SUM(amount)` as the only balance is exactly right, and the
accrual proration is deterministic. But the balance can be driven negative by concurrent approvals
(PAY-010), double-credited by concurrent accrual runs (DAT-001), and is never frozen at period close.

**4. Can we trust approved OT records?**
**Mostly yes.** Approval freezes the record (WD-29 d2), the multiplier is snapshotted, the action
timeline is complete, and caps are applied. The two caveats: night classification is wrong when
`night_ot_mode=WINDOW` (ATT-005), and detected minutes depend on sibling-day state (PAY-008).

**5. Can historical Attendance/Leave results be reproduced?**
**No — not exactly.** Version FKs and `computation_snapshot` recover most of the picture, but sibling-day
inputs are not persisted and there is no engine-version stamp (PAY-008). Leave is reproducible: the
ledger is append-only.

**6. Can historical records change unexpectedly?**
**In a CLOSED period: no** — verified across every mutation path. **In an OPEN period: yes** — via
back-dated policy publish, roster edit, calendar edit, or leave approval. Each is permission-gated and
audited, but each is possible.

**7. Are policy versions/effective dates handled safely?**
**Yes.** This is one of the strongest areas: identity + immutable published version, GiST no-overlap,
resolution strictly by date, version FK snapshotted onto every result row.

**8. Is period locking sufficient for Payroll?**
**The mechanism is — the workflow is not.** Two independent guards, atomic finalization, permission-gated
audited reopen: all correct. But a period cannot be finalized in practice (PAY-001), and what
finalization produces is not a sufficient input (PAY-002/003).

**9. Are Attendance and Leave cross-module rules deterministic?**
**Yes.** Every scenario in Part 9 resolves deterministically, and the lock-refusal behaviour on both
sync and cancel is correct and transactional. Two open business questions remain (OT on a leave day;
`PRESENT_CANCEL_LEAVE_HINT` double-counting).

**10. Are all important precedence rules defined?**
**Yes.** Twenty-six conflicts were traced (Part 10) and every one resolves deterministically in code. No
undefined precedence was found on any Payroll-relevant path.

**11. Are tenant boundaries secure?**
**By design, yes — by verification, not sufficiently.** No leakage path was found; 70/79 tables carry
RLS under a non-superuser role, and client-supplied tenant ids are rejected. But the test suite runs as a
BYPASSRLS superuser (TEN-002), so the backstop is largely unexercised.

**12. Are permissions enforced server-side?**
**Yes.** Consistently, including the target-object check that prevents IDOR. This is a genuine strength.

**13. Are sensitive operations audited?**
**Almost all of them.** One material exception: the lock-time paid/LOP rewrite. And the trail has no read
API.

**14. Are database transactions safe?**
**Yes.** One request = one transaction, rollback on any exception, verified end-to-end on the leave
approval → balance → projection path.

**15. Are operations idempotent?**
**Mostly.** Punch ingestion, projection sync, OT sync, finalization, and reopen are all idempotent.
Attendance calculation is not exactly (PAY-008); leave accrual is not under concurrency (DAT-001).

**16. Are concurrency risks controlled?**
**Partially.** Optimistic locking is applied consistently to workflow entities. But the leave balance has
no concurrency control at all (PAY-010), accrual has none (DAT-001), and no test exercises any real race
(TST-004).

**17. Are date/time calculations timezone-safe?**
**Yes, with two exceptions.** UTC storage, `zoneinfo`, three-tier timezone resolution, correct
cross-midnight and month-boundary handling. The exceptions are two `date.today()` calls in Leave
(DAT-004/005) and the absence of any DST test.

**18. Are monetary/numeric calculations safe?**
**Yes.** No float in any money path, integer minor units per ADR-0006, explicit `ROUND_HALF_UP` in
accrual, and — most importantly — Attendance refuses to compute money at all. The one defect is banker's
rounding in OT minute rounding (ATT-011).

**19. Are tests sufficient for payroll-critical rules?**
**No.** 1 145 tests pass locally and the business-rule coverage is genuinely good. But CI runs none of
the integration tests (TST-001), there are no concurrency tests, no coverage measurement, and — most
insidiously — the unimplemented policy fields cannot be caught by any test, because nothing reads them.

**20. Is production deployment reversible?**
**No.** There is no deployment pipeline to reverse, no rollback procedure, and the initial migration's
`downgrade()` raises `NotImplementedError`.

**21. Are backups tested?**
**No. Backups do not exist.**

**22. Is monitoring sufficient?**
**No. Monitoring does not exist.** Unhandled exceptions are not even written to a log.

**23. Can Payroll safely consume current data?**
**No.** Employment dates, org assignments, shift versions, policy versions, OT multipliers, and the lock
mechanism are all safe to consume. Paid days, LOP, and the period summary are not.

**24. What must be fixed before Payroll?**
The thirteen P0 items in Part 40: batch generation (PAY-001), summary completeness and correctness
(PAY-002/003), paid/LOP semantics for NOT_JOINED and EXITED (PAY-004/005), the leave balance guard
(PAY-010), accrual uniqueness (DAT-001), reproducibility (PAY-008), the lock-time resolution
(PAY-007), production CORS (SEC-001), and CI actually running the tests (TST-001).

**25. What can safely be deferred?**
Everything in Priority 3 and 4 (Part 40): the remaining inert policy fields once documented as
unimplemented, service-file decomposition, table partitioning, frontend accessibility work,
`localStorage` token migration, MFA, and documentation tidying. None of these can cause incorrect money.

---

*End of audit. No application code, schema, migration, test, or configuration was modified.*
