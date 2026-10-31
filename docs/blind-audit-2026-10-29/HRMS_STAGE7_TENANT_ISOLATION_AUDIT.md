# HRMS Stage 7 — Remaining Tenant-Isolation Audit (audit only)

Date: 2026-10-29 · Builds on `HRMS_P1_VERIFICATION_REPORT.md` (V-1…V-6). No application code, migration, permission, test, CI file or database row was changed. Nothing was committed or pushed.

## 0. Method, evidence levels and limits

| Evidence tag | Meaning |
|---|---|
| **[DB]** | Read-only catalog or `SELECT` on the disposable DB `rls-h1` (alembic head `20261030090000`, 117 public tables, 16 companies, 0 employees). Roles checked: `hrms` = SUPERUSER+BYPASSRLS, `hrms_app` = neither. |
| **[REPRO]** | Behaviour reproduced against `rls-h1` as `hrms_app`, using only `SELECT`/`SET LOCAL ROLE` (no writes). |
| **[CODE]** | Read from source, with file:line. Not executed. |
| **[TEST]** | A test exists that, from its name and structure, asserts the behaviour. **I did not re-run any test in this stage** (running them writes fixtures to the DB; you asked for no DB data changes). |

Limits that matter:
* `rls-h1` has no employees, so any "0 rows" data check on it is a weak baseline, not proof of production consistency.
* The route map was produced by importing the app and walking FastAPI's dependency tree for each route (357 routes). Nothing was called over HTTP.
* The new runtime-role tests and the tenancy changes (`core/auth/dependencies.py`, `core/tenancy/*`) are **uncommitted** (git status: 7 modified, 10 untracked at start). The "existing protections" below only exist in the deployed code once those are committed.
* Cross-tenant FK exploitability is established per code path by reading the service. I did not insert foreign IDs.

## 1. Headline

* **No P0 and no confirmed cross-tenant data exposure.** Every one of the 357 routes either carries a verified tenant context, is intentionally public (token-keyed), or is platform-admin.
* **One confirmed defect (P2):** employee-import enqueue-failure path loses the RLS variable and fails with a uuid cast error, leaving the batch `PENDING` forever. It fails closed (no leak).
* **The dominant systemic risk (P1) is structural:** only 4 of 140 tenant-to-tenant foreign keys carry `company_id`, and FK checks bypass RLS. Isolation of writes rests on every service pre-validating each client-supplied ID. I reviewed the main paths and they do; one missed check anywhere is a silent cross-tenant link the database will accept.
* **Test gap:** the restricted-role suite covers auth, attendance, leave, payroll and the leave accrual task. Eight modules and most background tasks have never been run under `hrms_app`.

## 2. Entity and module coverage matrix

Legend — **RLS**: `tenant_isolation` policy, ENABLE+FORCE [DB]. **FK**: tenant→tenant FKs that include `company_id` / total from that module's tables [DB]. **RT test**: flows run under `hrms_app` [TEST].

| Module | Tenant tables (examples) | RLS | Composite-tenant FKs | RT test (restricted role) | Status |
|---|---|---|---|---|---|
| Identity / auth | `user_company`, `role`, `audit_log`, `idempotency_key`; **no RLS:** `session`, `refresh_token` | partial | n/a | login, refresh, RBAC scope, header/token tenant resolution, pooled-connection leak check (`test_rls_runtime_role`, `test_tenant_resolution_runtime_role`) | **Covered** (session/refresh tables are app-filtered only) |
| Attendance core | `punch`, `attendance_day`, `attendance_break`, `attendance_period*`, `overtime_*` | all | `attendance_day→employee` only | punch/calculate/read, cross-tenant read+write, header cases (`test_attendance_rls_runtime_role`); DB-level FK (`test_b13_attendance_tenant_fk`) | **Partly covered**: no regularization, periods, overtime, roster, policies |
| Geofence | `geofence_attempt`, `employee_workplace_authorization` | all | 3 of 3 composite | RLS + composite FK (`test_geofence_rls`) | **Covered** |
| Face / liveness | `employee_face_profile`, `face_embedding`, `face_*_attempt/window/session`, `face_external_deletion` | all | none | one RLS probe (`test_face_opensource_engine`) | **Untested** under runtime role (enrol, verify, cleanup, deletion tasks) |
| Leave | `leave_*` (13 tables), `policy_assignment` | all | none | lifecycle, cross-tenant read/mutate, accrual task (`test_leave_rls_runtime_role`, `test_leave_accrual_task_runtime_role`) | **Covered** for apply/approve/ledger/accrual. **Untested:** comp-off credit/expiry sweeps, year-end sweep, encashment, policy CRUD |
| Payroll | `pay_run*`, `pay_adjustment`, `salary_*`, `employee_salary`, `payroll_setting`, `statutory_rate` | all | none | pay-run lifecycle, cross-tenant read/mutate, finalised immutability (`test_payroll_rls_runtime_role`, `test_b05_db_immutability`) | **Partly covered**: salary structures, components, assignments, statutory rates, adjustments, payslip, bank advice, `/me/payslips` not run under the role |
| Employee | `employee`, `employment`, `employee_assignment`, `employee_bank/compensation/statutory`, `employee_document`, dependents/education/experience | all | none | CRUD, termination, banking, statutory (`test_rls_runtime_role`) | **Partly covered**: documents/S3, assignments, dependents, confirmation, termination sweep task not covered |
| Organisation masters | `legal_entity`, `branch`, `department`, `designation`, `grade`, `shift*`, `holiday*`, `work_calendar*`, `weekly_off_*`, `calendar_exception`, `company_feature_flag`, `subscription`, `number_series` | all | none | registration only. Cross-tenant tests (`test_cross_tenant_isolation`) run as `hrms` (RLS bypassed), so they prove app-layer scoping only | **Untested** under runtime role |
| Onboarding | `onboarding_case/document/message/section_review`; **no RLS:** `onboarding_token` | all but token | none | one RLS check in `test_invitation_compose` | **Untested** (public token flow, uploads, activation) |
| Employee import | `employee_import_batch`, `employee_import_row_error` | all | none | none | **Untested**, and contains confirmed defect F-02 |
| Account invite | **no RLS:** `account_invite`; writes `user_company`, `user_role` | partial | n/a | none (`test_account_invite_onboarding_token_isolation` runs as `hrms`) | **Untested** |
| Platform console | `company`, `user`, `plan*`, `platform_*` (global); **no RLS:** `platform_audit_log`, `email_log` | n/a | n/a | none | **Untested**; sets GUC per inspected company by design |
| Email outbox | **no RLS:** `email_outbox` (cross-tenant sweep worker) | none | n/a | `test_b13_email_outbox` runs as `hrms` | **Untested** under runtime role |
| Ops (`import_backlog`, `job_health`) | read-only reconciliation | n/a | n/a | none | **Untested** |
| Global tables | `permission`, `role_permission`, `user_role`, `plan`, `encryption_keys`, `password_reset_token`, `email_verification_token` | none | n/a | indirect via login/RBAC | `user_role`/`role_permission` carry no tenant column (F-04) |

Totals [DB]: 117 tables; 97 carry RLS; **7 have `company_id` and no RLS** (`account_invite`, `email_log`, `email_outbox`, `onboarding_token`, `platform_audit_log`, `refresh_token`, `session`); 13 are global with no `company_id`; **136 non-composite and 4 composite** tenant→tenant FKs.

## 3. Endpoints and background tasks reviewed

### 3.1 HTTP routes [CODE, introspected]
357 routes (dependency tree resolved at runtime, not regex):

| Class | Count | Tenant control |
|---|---|---|
| `get_tenant_context` (token + membership + header match, sets GUC) | 305 (attendance 89, org 75, payroll 43, employee 41, leave 34, onboarding-admin 13, import 4, invite 4, identity 2) | `core/tenancy/dependencies.py:26-64` |
| Onboarding public, token-keyed (6) | `get_onboarding_case_from_token` resolves token hash then sets GUC | `modules/onboarding/dependencies.py:55-68`, service `onboarding/service.py:762` |
| Account-invite public (2) | token hash lookup, GUC set from the invite row | `account_invite/service.py:269,311` |
| Platform admin (25) | `get_current_platform_admin`; per-company GUC only for usage counts | `platform/service.py:231,327,384` |
| Pre-auth identity (6) + register (2) | login/refresh/reset/verify/register: `login_lookup_user_companies()` SECURITY DEFINER | `core/db/repositories/identity.py:49` |
| User-only, no DB tenant data (3) | logout, `users-check`, import template | n/a |
| Health/metrics/docs (8) | `/metrics` needs bearer token (`metrics_router.py:29-34`) | n/a |

No route reads tenant tables without either a tenant context or a token that resolves one.

### 3.2 Celery / background [CODE]
| Task | Company context | Runtime-role test |
|---|---|---|
| `leave.run_monthly_accrual` → `accrue_company` | per-company `session_scope(company_id=…)` | **Yes** |
| `leave.run_comp_off_credit_sweep`, `…expiry_sweep`, `run_year_end_sweep` (+ per-company) | same pattern, `leave/tasks.py:97-183` | No |
| `attendance.run_daily_calculation` → `calculate_company` / `calculate_range` | per-company, per-employee-date transactions, `attendance/tasks.py:94-280` | No |
| `attendance.run_incomplete_reminders`, `run_face_cleanup`, `run_face_deletions` | per-company | No |
| `employee.run_termination_access_sweep` | per-company | No |
| `employee_import.process_batch` | per-company, mid-run commits restore GUC (`_commit_and_restore_rls`) | No |
| `email_outbox.deliver_message` / `sweep` | **none** — raw SQL on non-RLS `email_outbox`, global by design (`email_outbox.py:222-330`) | No |
| Fan-out listing companies | `session_scope()` with no GUC reads `company` (no RLS) | **Yes** (leave) |
| `health.ping`, `scheduler_heartbeat` | no DB tenant data | n/a |
| `ops/import_backlog.py` | per-company read-only | No |

### 3.3 Raw SQL, joins, files, caches [CODE]
* `text(` use: 9 sites touch tenant data. All bind parameters; no user input is interpolated. The two f-string SQL sites (`core/db/timeouts.py:32`, `attendance/face_cleanup.py:106`) interpolate internal constants only. `platform/repository.py:185-195` runs `employee`/`user_company` counts after the GUC is set to the inspected company.
* Storage keys always embed the company (`employee-imports/{company_id}/…`, `face-review/{company_id}/…`) and are read back from RLS-filtered rows, never from client input (`employee_import/service.py:150`, `face_service.py:610`). Onboarding and employee documents use presigned GET URLs minted from RLS-visible rows.
* Redis holds only rate-limit counters (`ratelimit:*`), per-IP/email/token, no tenant data. Advisory-lock keys include `company_id` (`core/db/locks.py`).
* Exports: payroll bank advice and payslips are generated from `pay_run` rows read under the tenant context. Not run under the runtime role.

## 4. Existing protections and supporting evidence

| Protection | Evidence |
|---|---|
| `hrms_app` is neither SUPERUSER nor BYPASSRLS; no DDL/TRUNCATE | [DB] `pg_roles`; [TEST] `test_rls_harness`, `test_runtime_role_grants` |
| 97 tenant tables: ENABLE+FORCE RLS, single `tenant_isolation` policy on `company_id = current_setting('app.company_id', true)::uuid` | [DB] `pg_class`/`pg_policy` |
| Fails closed: no GUC → 0 rows; GUC cleared by commit → uuid cast error, not a leak | [REPRO] (`SELECT count(*) FROM employee` as `hrms_app` with no GUC → 0 rows) |
| Tenant derived from signed token, confirmed against membership, header must match, raw header never reaches the tenant var | [CODE] `core/auth/dependencies.py:40-46`, `core/tenancy/dependencies.py:26-64`, `middleware.py`; [TEST] `test_tenant_resolution_runtime_role`, `test_tenancy_middleware` (all **uncommitted**) |
| Cross-tenant read/write blocked, alternating tenants over pooled connections do not leak the GUC | [TEST] attendance, leave, payroll, tenant-resolution runtime-role files |
| Accrual task isolation, redelivery, concurrency, rollback | [TEST] `test_leave_accrual_task_runtime_role` |
| Service-layer ownership checks before writing client-supplied FK IDs | [CODE] employee (`employee/service.py:976,1046,1244,1720-1782,1935-1940`), payroll employee salary (`payroll/service.py:1087-1090`), leave approver reassignment (`leave/service.py:2923-2933`), policy assignments (`organisation/service.py:4352-4374`), onboarding branch (`onboarding/service.py:403`) |
| DB-level composite tenant FKs | [DB] 4 only: `attendance_day→employee`, `employee_workplace_authorization→branch/employee`, `geofence_attempt→employee`; [TEST] `test_b13_attendance_tenant_fk`, `test_geofence_rls` |
| Tokens are hash-only and globally unique; public routes rate-limited where state-changing | [TEST] `test_account_invite_onboarding_token_isolation`; [CODE] `account_invite/public_router.py:28` |
| Login/refresh company lookup via SECURITY DEFINER function, executable by `hrms`/`hrms_app` only | [DB] `proacl` of `login_lookup_user_companies` |
| Baseline FK-consistency scan | [DB] 136 non-composite tenant FKs checked, 0 cross-tenant rows (weak: 0 employees; detector in Appendix A) |

## 5. Confirmed cross-tenant vulnerabilities

**None confirmed.** There is no endpoint or task I could show reading or writing another tenant's rows under `hrms_app`. The confirmed defect below is availability/correctness and fails closed.

## 6. Findings (risk-ranked)

### P0
None.

### P1

**F-01 · Tenant-to-tenant FKs are not tenant-consistent (systemic) — Confirmed gap, exploit unproven**
* [DB] 136 of 140 FKs between tenant tables omit `company_id`. FK validation runs as the table owner and ignores RLS, so Postgres will accept a child row in tenant A pointing at a parent in tenant B whenever the service does not first check ownership.
* [CODE] The reviewed paths do check (employee, payroll salary, leave reassignment, policy assignment, onboarding), so no exploit is shown. But protection is purely per-call-site and unenforced by the database; `user_role→role` (F-04) and `policy_assignment.policy_id/scope_id` (no FK at all, `organisation/models.py:583-584`) are the same shape.
* Not reviewed line-by-line: attendance regularization/roster/OT inputs, payroll adjustments/`attendance_period_id`/`previous_pay_run_id`, `shift_roster`, `leave_*` ledger inputs, onboarding case master-data fields beyond branch, face tables.
* Impact if one check is missing: silent cross-tenant link; later admin/report joins that run without RLS could expose parent data. A pre-existence oracle for foreign UUIDs is also possible.

### P2

**F-02 · Employee-import enqueue failure loses the RLS variable — Confirmed (mechanism reproduced), fails closed; remediated in Stage 7B (see below)**
* [CODE] `employee_import/service.py:177` commits the batch, then `:190-197` (inside `except` after `process_batch.delay` fails) runs `update_batch_progress` and commits again with no `set_rls_company_id`. The helper that restores it (`_commit_and_restore_rls`, `:611-620`) is not used here.
* [REPRO] As `hrms_app`: after a transaction that did `set_config('app.company_id', …, true)` commits, the next transaction reports `current_setting('app.company_id', true)` = `''` and any RLS table query fails with `invalid input syntax for type uuid: ""`.
* Result as originally written: broker outage → `DataError` (reported as HTTP 500) instead of `ImportQueueUnavailableError`; the batch stays `PENDING` forever, which is exactly what the code comment says it prevents.
* **Correction (Stage 8):** the observed response is **HTTP 422 `INVALID_VALUE`**, not 500. The PostgreSQL `invalid input syntax for type uuid: ""` error is a data error, which `core/errors/handlers.py:210-215` maps to 422. That error is raised by the `FAILED` update and prevented the intended `ImportQueueUnavailableError` (503) handling from running. The storage-failure path at `:347-354` runs after `_commit_and_restore_rls` and was not affected.
* **Remediation and verification (Stage 7B, separate from the finding above):** fixed by committing with `_commit_and_restore_rls(company_id)` at `employee_import/service.py:177`. Regression test `tests/integration/modules/employee_import/test_import_enqueue_failure_runtime_role.py` sends the upload as `hrms_app`. Before the fix it failed with 422 `INVALID_VALUE`. After the fix: HTTP 503 `IMPORT_QUEUE_UNAVAILABLE`, one batch row `FAILED` with `completed_at` populated; the whole `employee_import` directory passed (18). The fix and test are uncommitted. No other finding in this report has been remediated.
* Not covered by any test; the import suite runs as `hrms`.

**F-03 · Seven tenant-bearing tables have no RLS** — Confirmed by design, partly deliberate
* [DB] `account_invite`, `email_log`, `email_outbox`, `onboarding_token`, `platform_audit_log`, `refresh_token`, `session`. `hrms_app` holds full DML (`DELETE/INSERT/SELECT/UPDATE`) on all but `email_log` and `platform_audit_log` (INSERT/SELECT).
* Reasons are legitimate (pre-auth token lookup, cross-tenant worker, platform console), and `onboarding_token` RLS was explicitly removed in `20260906090000_onboarding_o2.py:31-32`; `account_invite` states "No RLS" at `20260921090000_account_invite.py:61`.
* Risk: isolation of these rows depends only on app queries. `email_outbox` holds unsent HTML bodies containing invite/onboarding links for every tenant until delivery (`email_outbox.py:222-330`). A single injection or an unfiltered future query on these tables bypasses the database layer entirely.
* No unscoped query by an authenticated tenant user was found: `account_invite` repository is keyed by token hash, `employee_id` that was first loaded under RLS, or `(company_id, email)` (`account_invite/repository.py:60-96`).

**F-04 · `user_role` / `role_permission` carry no tenant column** — Confirmed (V-4d), exploit unproven
* [DB] no `company_id`; FKs `user_role→user_company` and `user_role→role` are separate, so a role of tenant B can be attached to a membership of tenant A. RLS on `user_company`/`role` hides rows but does not constrain the link.
* [CODE] Only writers: `account_invite/repository.py:127-129` (role resolved via `get_role_by_code(company_id=…)`, `:100`), `organisation/repository.py:174,181` (registration), `seed/bootstrap.py`. All resolve the role inside the same company, so not currently reachable. A mis-linked role would grant its permissions, so this is a privilege-escalation shape.

**F-05 · Eight modules and most background tasks never run under the restricted role** — Confirmed (see §2, §7)

### P3

**F-06 · `get_current_user` does not bind the DB session to the token's user/company** — Theoretical
`core/auth/dependencies.py:56` loads `Session` by id only; it never compares `db_session.user_id`/`company_id` to the claims (`get_session_by_id`, `identity/repository.py:70-72`). Requires a validly signed token with mismatched claims, so it needs key compromise or a minting bug. Cheap defense-in-depth.

**F-07 · Polymorphic references without FKs** — `policy_assignment.policy_id` and `scope_id` (`organisation/models.py:583-584`) are validated in `_validate_policy_scope` only; no DB backstop. Same class as F-01.

**F-08 · Platform console sets the RLS variable from a path parameter** (`platform/service.py:231,327,384`). Intended (platform operators are cross-tenant), gated by `get_current_platform_admin`; listed so it is not mistaken for tenant-user input. Untested under the runtime role.

**F-09 · Existing protections are uncommitted** — The fixes that make `hrms_app` usable and the header non-authoritative live in modified, uncommitted files. Not a vulnerability in the repository state; a delivery risk.

## 7. Modules still untested under the restricted role

Priority order by data sensitivity and write surface:
1. Employee import (route + `process_batch` task) — also hosts F-02
2. Account invite and role assignment (writes `user_company`, `user_role`)
3. Onboarding (public token flow, document upload, activation → creates employee)
4. Organisation masters and policy assignments (feed every FK in F-01)
5. Employee: assignments, documents (S3), dependents/education/experience, termination sweep
6. Payroll: salary structures/components/assignments, statutory rates, adjustments, payslip/bank advice, `/me/payslips`
7. Attendance: regularization, periods, overtime, roster, policies, face enrol/verify/cleanup/deletion tasks, reminders, daily-calculation fan-out
8. Leave: comp-off and year-end sweeps, encashment, policy/type CRUD
9. Platform console and `email_outbox` sweep (cross-tenant by design; needs a "can only see what it should" test, not a cross-tenant-denied test)

## 8. Recommended remediation order

| Stage | Audit | Implementation | Verification |
|---|---|---|---|
| **1. F-02 import GUC** | Done here (repro). Also check `:347-354` | Restore the RLS variable (or run the failure update in a fresh `session_scope`) after the enqueue-failure commit | Runtime-role test: broker raises → `ImportQueueUnavailableError`, batch `FAILED`, no 500 |
| **2. Runtime-role coverage, highest risk first** (import, invite, onboarding, org masters) | Per module: list routes+tasks, FK inputs | Reuse `rls_support.app_as_runtime_role`; one test file per module, same pattern as the leave/payroll files | Each: own-tenant works, other-tenant read/write denied, no-GUC returns nothing, pooled alternation |
| **3. F-01 tenant FK consistency** | Finish the unreviewed input list (§6 F-01); run Appendix A on a production-shaped copy | Alembic migrations adding `(company_id, id)` unique keys and composite FKs, child tables first by risk (payroll, leave, attendance, onboarding). Backfill-check before each | Appendix A returns 0; migration up/down on disposable stack; negative tests that a foreign ID is rejected by the DB with the service check bypassed |
| **4. F-03/F-04** | Decide per table: RLS, or documented exception | Add `company_id` to `user_role` and a composite FK; add RLS to `session`/`refresh_token` only if the pre-auth lookup path can be kept (security-definer function) | Login/refresh/invite-accept suites under the runtime role |
| **5. F-06/F-07/F-09** | None | Bind session to claims; commit the uncommitted tenancy work; DB check for polymorphic refs | Unit + runtime-role tests |

## 9. Recommendation: single highest-priority next fix

**F-01, starting with a verification pass rather than a migration:** the only structural weakness that could produce a real cross-tenant breach, and one the existing tests cannot see because every fixture runs as a BYPASSRLS role. But it needs the unreviewed input list closed first.

If you want a smaller, fully-confirmed fix to take first, that is **F-02** (a few lines, reproduced, but fails closed and has no cross-tenant impact).

My recommendation is to fix **F-02 first as a quick win, then spend the next stage on F-01's remaining audit plus the import/invite/onboarding runtime-role tests**, since those tests are what will expose F-01-style gaps. I have not implemented anything and will wait for your approval.

## Stage 8 addendum — tenant write-path audit (2026-10-29)

Scope: attendance regularization and roster, payroll mutations, and the remaining client-supplied foreign-key IDs listed under F-01. Audit only; no application code, migration, permission, CI or database change. Evidence tags as in §0.

### S8.1 Reviewed write paths

Every path below is authenticated (`get_current_user`), tenant-scoped (`get_tenant_context`, GUC set) and permission-gated; the question is whether each client-supplied ID is proven to belong to the company before it is stored. The database cannot answer it (the FKs are not composite, see F-01).

| Path | Client-supplied IDs | Ownership check | Evidence |
|---|---|---|---|
| `POST /rosters`, `/rosters/bulk`, `PATCH /rosters/{id}` (`attendance/service.py:2202-2450`) | `employee_id`, **`shift_id`** | `employee_id` yes (`_ensure_employee_visible`). **`shift_id` no** (not read in create, bulk, update or publish) | [CODE] + [REPRO] F-10 |
| `POST /regularizations` and approval (`service.py:4389,4967-5030`) | `employee_id`, `attendance_date`, **`requested_shift_id`**, requested punches | `employee_id` yes. **`requested_shift_id` no**; stored at `:4567`, then written into a PUBLISHED roster row on approval at `:4984-5027`. Day, policy version and period are server-derived | [CODE] + [REPRO] F-10 |
| `POST /attendance-periods` (`service.py:5645`) | `legal_entity_id` | yes (`get_legal_entity`) | [CODE] |
| Payroll adjustments `POST/DELETE /payroll/adjustments` (`payroll/service.py:3748-3840`) | `source_pay_run_id`, `employee_id` | run loaded with `company_id`; employee must have paid days in that run; `legal_entity_id` taken from the run, not the client | [CODE] |
| Pay-run create/update (`payroll/service.py:1787`, `~1720-1740`) | `legal_entity_id` | yes (`get_legal_entity`); `attendance_period_id` and `previous_pay_run_id` are server-derived (`:2511,:2657`) | [CODE] |
| Salary structure lines (`payroll/service.py:547-580`) | `salary_component_id`, `base_salary_component_id` | yes (`get_many` by company; unknown/inactive refused) | [CODE] |
| Employee salary assign / bulk assign (`:1087-1090`, `:1262`) | `salary_structure_id`, `employee_ids` | structure by company; bulk candidates must be employed per company-scoped spans | [CODE] |
| Org: department parent/head, designation grade, weekly-off pattern, holiday calendars (`organisation/service.py:1564-1600,1766,2718,3849`) | parent/head/grade/pattern/calendar IDs | yes | [CODE] |
| Leave: policy/ledger adjustment/encashment/application/combination rule (`leave/service.py:310,655,1311,1387`, repo lookups by `company_id`) | `leave_type_id`, `employee_id` | yes | [CODE] |
| Onboarding case create (`onboarding/service.py:~397-403`) | branch, department, designation | yes | [CODE] |
| Employee dependents / education / experience (`employee/service.py:2935,3119,3362`) | `document_id` | **none, and no FK**; value is stored and returned, never dereferenced | [CODE] |

### S8.2 Findings

**F-10 · Roster `shift_id` and regularization `requested_shift_id` are not checked against the company (P2, confirmed)**
* **Reproduction [REPRO], 2026-10-29, `rls-h1`:** two provisioned tenants A and B; the API calls ran as `hrms_app` (`app_as_runtime_role`), setup and assertions as the admin role. Using tenant B's real shift ID in tenant A's session:
  * `POST /v1/rosters` → **201**; `shift_roster` row owned by A pointing at B's shift. Admin check: 1 row with `shift_roster.company_id <> shift.company_id`.
  * `POST /v1/regularizations` (`WRONG_SHIFT`, `requested_shift_id` = B's shift) → **201**; 1 row with `attendance_regularization_request.company_id <> shift.company_id`.
  * An unknown (non-existent) shift ID on the roster route → 409 `SHIFT_ROSTER_DATE_CONFLICT`: the FK error is caught by the date-conflict handler (`service.py:2279-2282`) and reported misleadingly. A foreign ID is therefore distinguishable from an unknown one (201 vs 409), a weak existence oracle for 122-bit random IDs.
* **Who can trigger it:** roster needs `ATTENDANCE_ROSTER_MANAGE`; regularization submit is available to an employee for themselves, so the weakest caller is an ordinary employee. They need the foreign shift's UUID, which is not guessable and not exposed by the API.
* **What is not shown:** no disclosure. The responses echo only the ID the caller supplied, and the reads are RLS-filtered. I did **not** reproduce the effect on approval or on attendance calculation. By code, approval would write a PUBLISHED roster row carrying the foreign ID (`:4984-5027`), and the calculation then asks for the shift's version through the company-scoped organisation service (`:3670-3675`), which only catches `ShiftVersionNotFoundForDateError`, so a not-found shift may fail that employee-date. **Unverified.**
* **Possible cross-tenant side effect (unverified):** a row in A referencing B's shift will make B's DELETE of that shift fail on the FK if B ever hard-deletes it.
* Class: instance of F-01 with a concrete, reproduced code path.
* **Test coverage:** none. `test_shift_roster.py`, `test_regularization.py` and `test_b12_cross_tenant_and_scope.py` never submit another tenant's shift; the runtime-role attendance file covers punches and days only.

**F-11 · Opaque `document_id` on dependents, education, experience (P3, theoretical)**
No FK, no ownership check (`employee/service.py:2935,3119,3362`). The value is not used to fetch anything in the paths reviewed, so no exposure was found; it would become an issue if a future endpoint resolved it without a company filter.

**Reviewed and found protected (no finding):** payroll adjustments, pay-run create/update, salary structure lines, salary assignment and bulk assignment, attendance period create, org parent/head/grade/pattern/calendar references, leave type/employee references, onboarding case references. These are [CODE] conclusions; none has a cross-tenant runtime-role test.

### S8.3 Missing coverage (not vulnerabilities)

| Gap | Test needed (runtime role, `app_as_runtime_role`) |
|---|---|
| Roster create/bulk/update/publish/delete and list/get across tenants | new `tests/integration/modules/attendance/test_roster_regularization_rls_runtime_role.py` |
| Regularization submit/approve/reject/cancel under `hrms_app` | same file |
| Payroll adjustments, pay-run create, salary-structure lines, bulk assign with a foreign ID | new `tests/integration/modules/payroll/test_payroll_write_paths_runtime_role.py` |
| Organisation master-data references | `tests/integration/modules/organisation/test_org_references_runtime_role.py` |

**Fixture conventions for these tests (reviewed):** reuse the two-tenant `tenants` pattern of `test_attendance_rls_runtime_role.py` (provision both tenants on the admin engine, run only the operations under test inside `app_as_runtime_role()`, assert state with `admin_engine`, teardown in `finally`). **The existing attendance teardown (`_cleanup_attendance_day`) does not delete roster or regularization rows**, so any new test creating them must also delete those tables first, or use `tests/integration/tenant_wipe.py::wipe_tenant`. Without that, the tenant cleanup fails with an FK error, which is exactly what happened during this audit's probe.

### S8.4 Recommended next implementation stage (needs approval)

1. In `attendance/service.py`: before the insert in `ShiftRosterService._insert` (`:2260`) and in the roster update path, and in `RegularizationRequestService.submit` (`:4567`), load the shift with `company_id` through the organisation service and raise the existing not-found/validation error when it is missing or inactive; also stop mapping every `IntegrityError` to `ShiftRosterDateConflictError` (`:2279-2282`) so only the unique-date violation maps to it.
2. Add the test file above covering: foreign shift → 404/422 and no row written; unknown shift → same error as foreign (no oracle); own shift still works; roster/regularization cross-tenant read, patch, publish, delete denied; no-GUC returns nothing.
3. Optional follow-up (separate stage, migration): composite FKs `(company_id, shift_id)` for `shift_roster` and `attendance_regularization_request` (F-01).

### S8.5 Evidence handling and side effects

* A transient probe test and a transient cleanup test were created under `tests/integration/modules/attendance/`, run once each on `rls-h1`, and **deleted**; `git status` shows neither.
* The probe's own teardown failed (FK error, see S8.3), leaving the two companies it created (`fe8c8bf5-…`, `9529a53a-…`) and their rows. I removed only those two tenants with the repo's `wipe_tenant` helper. `rls-h1` counts afterwards match the pre-probe counts: 16 companies, 16 users, and 0 rows in `employee`, `shift`, `shift_roster`, `attendance_regularization_request`. No reset, recreate or broad cleanup was performed.

## Appendix A — read-only cross-tenant FK detector

Runs on any database; changes nothing. Checks all tenant-to-tenant FKs that do not already include `company_id`. Baseline on `rls-h1` was `checked=136 with_cross_tenant_rows=0` (0 employees, so weak).

```sql
DO $$
DECLARE r record; n bigint; checked int := 0; bad int := 0; cond text;
BEGIN
  FOR r IN
    SELECT c.conname, c.conrelid::regclass AS t, c.confrelid::regclass AS rt, c.conkey, c.confkey, c.conrelid, c.confrelid
    FROM pg_constraint c
    WHERE c.contype='f'
      AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid=c.conrelid  AND a.attname='company_id' AND NOT a.attisdropped)
      AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid=c.confrelid AND a.attname='company_id' AND NOT a.attisdropped)
      AND NOT ((SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='company_id') = ANY(c.conkey))
  LOOP
    SELECT string_agg(format('c.%I = p.%I', ca.attname, pa.attname), ' AND ')
      INTO cond
      FROM unnest(r.conkey, r.confkey) AS k(ck, pk)
      JOIN pg_attribute ca ON ca.attrelid=r.conrelid  AND ca.attnum=k.ck
      JOIN pg_attribute pa ON pa.attrelid=r.confrelid AND pa.attnum=k.pk;
    EXECUTE format('SELECT count(*) FROM %s c JOIN %s p ON %s WHERE c.company_id <> p.company_id', r.t, r.rt, cond) INTO n;
    checked := checked + 1;
    IF n > 0 THEN bad := bad + 1; RAISE NOTICE 'MISMATCH % (%): % rows', r.conname, r.t, n; END IF;
  END LOOP;
  RAISE NOTICE 'non-composite tenant FKs checked=% with_cross_tenant_rows=%', checked, bad;
END $$;
```

Run it as the owner role (it must see all tenants), and never against a production DB without approval.

## Appendix B — what I did not do
* Did not re-execute the existing tests, did not run the app, did not insert any row, did not touch `hrms_dev`, or reset/recreate any QA stack.
* Did not review the web/mobile clients.
* Role-permission correctness (RBAC scope within a tenant) is out of scope; only tenant boundaries were assessed.
