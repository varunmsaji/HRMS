# B11 — Onboarding and employee lifecycle QA: scope, gap analysis, test matrix (2026-10-26)

Status: PLAN written **before** any execution. QA only: no application code is changed in B11. Defects found go to
`QA_DEFECT_REGISTER.md` Part F (additive) with a separate fix plan.

## 1. Repository state at start (preserved, nothing reset/cleaned/stashed)

* Branch `main`; `git status --short` = **221** paths at B11 start (the 202 pre-existing paths + the HR_ADMIN implementation
  work + docs); the saved reference list has 223 lines because it was written after this plan and the evidence directory were created. Reference list saved to `docs/testing/qa_evidence_b11/git_status_start.txt`. 136 tracked files modified.
* HEAD `436a2e5`. No commit/push/merge/deploy in B11.

## 2. Safety gates and resources

| Gate | Value at plan time | Rule |
|---|---|---|
| Root free disk | 4.4 GiB | start >= 3 GiB, stop < 2 GiB (`stack.sh` also enforces 2 GiB per runner) |
| Memory available | ~8.7 GB, swap 2 MB used | monitored before every batch |
| Shared stack | `hrms-postgres/redis/minio` running | **never touched**; the disposable stack has `--network none` holder namespace |
| Stack | fresh `b11-20261026a` via `docs/testing/qa_harness/stack.sh` | `ISOLATION PROVED` required before every run (printed by `stack.sh guard` and re-verified by `entry.py`) |
| Forbidden | `002_app_role.sh` rerun, `usage-probe-install` (DDL trigger probe), GRANT changes, real email/payments/webhooks | not invoked |

Harness change (QA tooling only): one extra read-only mount `b11` in `stack.sh` (same pattern B10 used for `b10`).

## 3. Evidence reviewed (what is already covered)

Sources: `HR_ADMIN_IMPLEMENTATION_PLAN.md` §7, `QA_DEFECT_REGISTER.md` Part A/B/E, `QA_BASELINE_RESULTS.md` §39-42, retained
`qa_runs/hradm-20261026a/artifacts/*` (B10-*.jsonl, role_grants.json, preflight_isolation.json), the B10 harness and the
product tests listed below. The `hradm` run reports 487 (org + invite + onboarding) and 391 (employee) product tests passed
as the table-owner role `hrms` (OBS-TEST-ROLE-01: RLS/grants not exercised there).

| Area | Already covered (regression value) | Gap for B11 |
|---|---|---|
| Onboarding create/list/get/activate | `test_onboarding_case.py` (dup active blocked, cross-tenant, no-permission), `test_onboarding_activation.py` (graph, not verified, no LE, twice, cross-tenant), `test_onboarding_review.py`, `test_onboarding_invite.py` | principal matrix for HR_ADMIN, REPORTING_MANAGER, BRANCH_MANAGER, EMPLOYEE, custom, anonymous, other tenant on **every** operation; run as `hrms_app`; denied-write side effects (audit/idempotency); concurrent activation; repeated `send-invite`; stale/replayed review; CANCEL status |
| Employee lifecycle | `test_employment.py` (terminate/rehire/rollback), `test_employee_lifecycle_and_concurrency.py` (parallel create, version race, deactivate, seat limit), `test_employee_data_scope.py` (SELF/REPORTEES/BRANCH/TREE), `test_optional_idempotency.py` | linked attendance/leave/payroll/document rows after terminate/deactivate; audit events per transition; out-of-order transitions; denied-path DB state; forged `X-Company-Id`; run as `hrms_app` |
| HR_ADMIN policy | `test_hr_admin_policy_grants.py`, `test_hr_admin_separation.py`, B10 `ESCALATION`/`ONBOARDING` | regression only |
| New/existing tenant seeding | `test_hr_admin_policy_grants.py` (new tenant, migration additive/idempotent/scope-preserving), `test_scope_guard_live_grants.py` | cross-role snapshot (other roles unchanged), VIEW vs VIEW_ALL distinctness, re-seed idempotence on a fresh tenant |
| OBS-HRA-01 (5 handlers) | `scope_guard_exceptions.toml` pins them; B10-04 touched `calculate` only (route then 200 for SELF) | all five handlers, restricted scopes SELF/REPORTEES/BRANCH/REPORTEE_TREE, direct object, ID manipulation, side effects, cross-tenant |
| Failure injection | `test_terminate_employment_rolls_back_on_compensation_close_failure`, `test_activation_failure_isolation.py` | audit-write failure during onboarding review/activation and employee terminate (in-process hook, no shared-service change) |

## 4. The five OBS-HRA-01 exceptions (static findings, to be proven dynamically)

| # | Route | Permission | Reads scope? | Exposes / mutates |
|---|---|---|---|---|
| 1 | `POST /v1/attendance/days/calculate?employee_id&date` | `ATTENDANCE.VIEW_ALL` | no (`_scope`) | **mutates** (creates/replaces the target's attendance day), returns the day |
| 2 | `POST /v1/attendance/days/{id}/recompute` | `ATTENDANCE.RECOMPUTE` | no | **mutates** target day by id |
| 3 | `POST /v1/attendance/days/calculate-range` | `ATTENDANCE.RECOMPUTE` | no | queues recalculation for employees in range (body-driven) |
| 4 | `POST /v1/attendance/days/{id}/work-on-leave/keep-leave` | `ATTENDANCE.RECOMPUTE` | no | **mutates** day (clears finalize blocker) |
| 5 | `POST /v1/employees/{id}/invite` | `EMPLOYEE.INVITE` | no | **mutates**: creates an invite token/row and (provider `logging`) an email record for any employee in the company |

Each is run with synthetic custom roles holding the permission at SELF / REPORTEES / BRANCH (owner = real employee), against in-scope, out-of-scope, unknown and other-tenant targets, under `hrms_app`, comparing company table counts before/after (denied calls must change nothing). Verdict per handler is one of: (1) enforcement proven, (2) genuine defect confirmed, (3) demonstrably safe, (4) inconclusive/blocked. Critical exposure -> stop and report.

## 5. ONBOARDING.CANCEL

Static: `ONBOARDING.CANCEL` is defined (`onboarding/permissions.py`) and granted to HR_ADMIN/COMPANY_ADMIN; status `CANCELLED` is a recognised terminal value; no router dependency, no service and no repository write ever sets `status = CANCELLED`. Dynamic test B11-ONB-CANCEL asserts: no route in the live route inventory requires the permission, no onboarding path (including `PATCH`/`DELETE`/`POST .../cancel`) exists (404/405), and no case ever reaches CANCELLED after the whole lifecycle. Result recorded as "genuinely absent / stale grant" with a recommendation; nothing is implemented.

## 6. Test matrix

`R` = regression (existing test, re-run), `N` = new B11 coverage (harness `docs/testing/qa_harness/b11/`, runs as `hrms_app` unless noted).

| QA case | Feature / route | Principal and scope | Expected | File / command | Type |
|---|---|---|---|---|---|
| B11-SG-01..05 | the five OBS-HRA-01 handlers | custom roles SELF/REPORTEES/BRANCH; COMPANY control; other tenant | out-of-scope target refused (404/403) with zero DB effect; in-scope allowed | `b11/test_b11_01_scope_exceptions.py` | N |
| B11-ONB-MATRIX | 9 onboarding operations | COMPANY_ADMIN, HR_ADMIN, REPORTING_MANAGER, BRANCH_MANAGER, EMPLOYEE, custom (VIEW only, REVIEW only), anonymous, other-tenant admin | permitted: success; denied: 401/403/404, no table changes (incl. audit_log, idempotency_key) | `b11/test_b11_02_onboarding.py::test_matrix` | N |
| B11-ONB-LIFE | create -> invite -> submit -> review -> activate | HR_ADMIN (acting), anonymous candidate token | state, DB rows and audit rows per transition; repeat/invalid transitions rejected with no partial change | `test_b11_02_onboarding.py::test_lifecycle_*` | N |
| B11-ONB-DUP | duplicate active case, duplicate email vs existing employee | HR_ADMIN | 409; one row | `test_b11_02_onboarding.py::test_duplicates` | N |
| B11-ONB-CONC | 8 parallel activations of one VERIFIED case; 8 parallel creates of the same candidate | HR_ADMIN | exactly 1 employee / 1 case; losers 409/422 | `test_b11_02_onboarding.py::test_concurrent_*` | N |
| B11-ONB-FAIL | audit-write failure during review / activate (in-process hook) | HR_ADMIN | request fails closed; case status and employee tables unchanged | `test_b11_02_onboarding.py::test_audit_failure_*` | N |
| B11-ONB-CANCEL | `ONBOARDING.CANCEL` | all | grant exists, no route/service uses it | `test_b11_02_onboarding.py::test_cancel_*` | N |
| B11-ONB-TENANT | every onboarding id route with other tenant's case id + forged `X-Company-Id` | other-tenant admin, HR_ADMIN | 404/401, no effect | `test_b11_02_onboarding.py::test_tenant_*` | N |
| B11-ONB-REG | existing onboarding module tests | COMPANY_ADMIN (owner role) | pass | `pytest tests/integration/modules/onboarding` | R |
| B11-EMP-LIFE | create, patch, assignments (branch/dept/designation/manager change = transfer), confirm, deactivate/reactivate, terminate, rehire | HR_ADMIN; denied: BRANCH_MANAGER/REPORTING_MANAGER out of scope, EMPLOYEE | success + denied; post-state read from DB; audit row per transition | `b11/test_b11_03_employee.py` | N |
| B11-EMP-LINK | terminate / deactivate with attendance, leave, payroll compensation/bank, documents rows | HR_ADMIN | historical rows untouched, counts equal, assignment/compensation closed as designed | `test_b11_03_employee.py::test_linked_*` | N |
| B11-EMP-ORDER | out-of-order: terminate twice, update terminated, confirm non-probation, deactivate twice, stale version | HR_ADMIN | 409/422, no change | `test_b11_03_employee.py::test_out_of_order` | N |
| B11-EMP-ISO | other employee / other branch / other tenant ids, list vs direct, `?employee_id=` smuggling, forged company header | BRANCH_MANAGER, REPORTING_MANAGER, EMPLOYEE, other tenant | 404 for out-of-scope; list filtered | `test_b11_03_employee.py::test_isolation` | N |
| B11-EMP-REG | existing employee lifecycle/scope/employment tests | owner role | pass | `pytest` the 5 named files | R |
| B11-SEED | new-tenant HR_ADMIN grants, migration add/idempotent/scope-preserving, guard live grants | system roles | as designed | `test_hr_admin_policy_grants.py`, `test_scope_guard_live_grants.py`, `test_scope_enforcement_guard.py` | R |
| B11-SEED-N | other roles unchanged, VIEW vs VIEW_ALL distinct, re-seed no duplicates | all 7 system roles on a fresh tenant | grant sets equal the pinned baseline | `b11/test_b11_04_seeding.py` | N |
| B11-PERM-HR | HR_ADMIN boundaries: attendance read, no user/role admin, no COMPANY_ADMIN invite/assign, payroll approve/finalise/pay/bank-advice denied, statutory self-verify denied | HR_ADMIN | allowed/denied as approved | `test_b11_03_employee.py::test_hr_admin_ceiling` + R: `test_hr_admin_separation.py` | N+R |

Batches (run separately, `ISOLATION PROVED` + resource check before each): **A** regression (onboarding dir), **B** regression (employee files + org/invite/seed/guard files), **C** B11-SG, **D** B11-ONB, **E** B11-EMP + PERM, **F** B11-SEED-N. Not run: full suite, web, mobile, B5b payroll calculation (CL-05/CL-06).

## 7. Fixtures
Synthetic only: the B10 `world.py` (2 branches, manager/branch-manager/employees, custom roles, second tenant, random ids, `@example.com`), plus onboarding cases built through the API and public candidate token. Email provider `logging`; no external calls. The disposable database is dropped with the stack.
