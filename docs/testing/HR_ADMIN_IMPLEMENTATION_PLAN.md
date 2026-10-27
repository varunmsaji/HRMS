# HR_ADMIN policy implementation — inspection findings and plan (2026-10-26)

Status: PLAN ONLY. No application code has been changed. Working tree has 202 pre-existing
changed/untracked paths (branch `main`); all must be preserved. Root disk at inspection: 4.4 GiB free
(gate: >= 3 GiB to start, stop < 2 GiB).

## 1. Architecture as found

* Grants: `OrganisationService.register_company` (`modules/organisation/service.py` ~L600-700) inserts
  system roles and `role_permission(role_id, permission_id, data_scope)` rows for new tenants. Existing
  tenants get grants only via alembic data backfills (precedent: `20261020090000_employee_role_self_attendance.py`,
  `ON CONFLICT DO NOTHING`). These are row inserts, not DB `GRANT`s; `002_app_role.sh` is not involved.
* Runtime: `require_permission(code)` (`core/rbac/dependencies.py`) returns a `DataScope` (set of
  `SELF/REPORTEES/REPORTEE_TREE/BRANCH/COMPANY`); it never filters anything itself. Handlers must
  convert scope to visible ids (`attendance.service._resolve_visible_employee_ids`,
  `_ensure_employee_visible`) using `user.employee_id`.
* Both defects are the same pattern: the router binds the scope to an unused `_scope` parameter.

## 2. Current HR_ADMIN grants vs approved policy

| Area | Today (code) | Gap |
|---|---|---|
| Employee | all `EMPLOYEE.*` at COMPANY (incl. `EMPLOYEE.INVITE`) | must verify HR_ADMIN cannot invite/assign COMPANY_ADMIN (`account_invite/service.py`) - test only if already enforced |
| Onboarding | none | add `ONBOARDING.CREATE/VIEW/REVIEW/ACTIVATE/CANCEL` @COMPANY (needs migration backfill) |
| Attendance read | approve regularization/overtime only; **no `ATTENDANCE.VIEW`/`VIEW_ALL`** | add `ATTENDANCE.VIEW` + `ATTENDANCE.VIEW_ALL` @COMPANY (migration backfill). Policies/shifts/rosters/lock stay COMPANY_ADMIN unless you approve more |
| Leave | view_all, adjust, approve, cancel-approved, submit/reassign on behalf | none; policy/type management stays COMPANY_ADMIN (existing Decision 12) |
| Payroll | `SETUP_MANAGE, RUN_VIEW, RUN_PROCESS, STATUTORY_MANAGE`; `RUN_APPROVE`, `BANK_ADVICE_DOWNLOAD` COMPANY_ADMIN only | policy already matches; add negative tests (approve/finalise/paid/bank advice) |
| Statutory | `STATUTORY_MANAGE` covers create, edit **and verify**; `verify()` records `verified_by_user_id` but the row has no last-editor column | see blocker B-1 |

## 3. Defect fixes (code only, no migration)

* DEF-B6-02: `attendance-periods/{id}/summary` takes the `DataScope` and `user.employee_id`; service
  `get_summary` filters rows (live preview and frozen CLOSED rows) to visible ids; empty visible set -> empty list.
  Period list/detail carry only period metadata - left as is, recorded in the guard exceptions file with rationale.
  Because HR_ADMIN currently lacks `ATTENDANCE.VIEW`, the grant in section 2 goes in the same change.
  Note `ATTENDANCE.VIEW_ALL` is a separate code; summary will honour `VIEW` scope only unless you want VIEW_ALL treated as COMPANY (decision D-2).
* DEF-B10-01: `create_adjustment` (and sibling `encashments`, same gate and same pattern) resolve visible ids
  from the scope **before** any lock/insert; out-of-scope target -> 404 (same as peer routes, hides existence).
  The existing docstring "No scope narrowing - deliberately" is replaced. Idempotency wrapper unchanged, so a
  denied call stores no idempotency record only if the check runs inside `execute` -> check placed before `run_idempotent`.

## 4. Expected files (exact list may shrink)

Code: `attendance/router.py`, `attendance/service.py`, `leave/router.py`, `leave/service.py`,
`organisation/service.py` (new-tenant grants), new alembic revision `2026102x_hr_admin_attendance_onboarding_grants.py`.
Tests: new `tests/integration/modules/attendance/test_period_summary_scope.py`,
`tests/integration/modules/leave/test_adjustment_scope.py`, `tests/integration/modules/payroll/test_hr_admin_separation.py`,
extend existing grant/seed tests that encode the old HR_ADMIN set. Guard: `tests/unit/core/test_scope_enforcement_guard.py`
+ `tests/unit/core/scope_guard_exceptions.toml`. QA docs (additive): `QA_DEFECT_REGISTER.md`, `QA_BASELINE_RESULTS.md`,
`QA_TEST_CASES.csv`; strict-xfail harness tests in `docs/testing/qa_harness/b10/` get their xfail removed **only after**
an independent pass (history of the failed run is kept in the register).

## 5. Blockers / decisions needing you

* B-1 Statutory self-verification: `statutory_rate` has no `updated_by`; the editor is only in the audit log
  (`PAYROLL_STATUTORY_RATE_*` events). Options: (a) derive "last editor" from the audit log inside `verify()` and refuse when
  equal to the verifier - no schema change, but couples payroll to audit reads; (b) add `last_modified_by_user_id` column +
  migration (the schema change you told me to stop at). Recommendation: (a) if the audit repository is cleanly reachable, else report as blocked.
* D-1 Onboarding/attendance grant backfill migration: confirm it may be authored (it is only executed on the disposable DB).
* D-2 Whether `ATTENDANCE.VIEW_ALL` should widen the summary to COMPANY.
* D-3 Disposable stack: `stack.sh up` needs ~ some GB; with 4.4 GiB free the 2 GiB stop-gate is close. Confirm I may create it
  (and I will stop if free space < 2 GiB).

## 6. Guard design (sketch)

AST pass over `modules/*/router.py`: for each handler param `Depends(require_permission(X))` named `_scope`/`scope`, flag
if the name is unused in the body and X is not in the reviewed-exceptions file; exceptions require a `reason` and a
`company_only_grant: true` assertion cross-checked against `register_company` grants. Imperative `rbac.resolve_data_scope`
calls whose result is unused are flagged too. 199 current unused-scope routes mean the exceptions list will be large
but explicit; the guard fails on any new one.

---

## 7. Outcome (2026-10-26) - what was implemented versus this plan

* Implemented as planned: DEF-B6-02 (service-layer scope on the period summary), DEF-B10-01 + encashment sibling, HR_ADMIN grants
  (seed + migration `20261026090000`), statutory maker-checker via `audit_log` (fails closed), scope-enforcement guard.
* Scope changes against section 4: **added** `payroll/exceptions.py`, `payroll/repository.py` (read-only `StatutoryAuditReader`),
  `tests/integration/modules/payroll/test_p1_hardening.py` (old edit-and-verify expectation), the harness `b10/*` assertions and
  `scope_guard.py` (helper). **Not needed:** no frontend change (web/mobile gate on `/auth/me` permissions), no `account_invite` change
  (HR_ADMIN already cannot invite/assign COMPANY_ADMIN - proven by test).
* D-2 as approved: `ATTENDANCE.VIEW_ALL` is a separate permission; each of VIEW and VIEW_ALL is honoured at the scope it was granted,
  and the union is used. Held at COMPANY (both shipped holders) it is company-wide; a restricted custom VIEW_ALL grant stays restricted.

## 8. Design proposal (not implemented): fail-closed `company_only` permissions

196 routes still ignore scope (reviewed exceptions). To make a future sub-company custom grant safe without touching each handler,
add `require_company_permission(code)` in `core/rbac/dependencies.py`: it behaves like `require_permission` but returns 403
`SCOPE_NOT_SUPPORTED` when the caller's grant for `code` is anything other than COMPANY. Migrate the 32 `company_level` permission
exceptions to it (mechanical, one import per router), then delete them from the exceptions file; the 5 `known_gap` handlers
(OBS-HRA-01) need real scope enforcement or the same dependency. No schema or data change; behaviour for shipped roles is identical.

## 9. Statutory-rate editor - schema option (not implemented, needs approval)
`statutory_rate` has no `last_modified_by_user_id`. Adding it (migration + backfill from `audit_log`) would remove the dependency on
audit completeness (OBS-HRA-04) and make the check a single-row comparison. Current implementation needs no migration.
