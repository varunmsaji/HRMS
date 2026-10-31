# HRMS Production Readiness Programme — Progress

Started 2026-10-29. No commits, pushes, deployments or production changes are made by this programme.

## Stage 0 — Baseline (status: in progress; test results pending)

### Repository state (recorded before any edit)
- Branch `main`, HEAD `f6340eb7c1679e449ecd87079cb6de01cb5cafec`.
- Staged: none.
- Unstaged (9): `.github/workflows/ci.yml`, `core/auth/dependencies.py`, `core/tenancy/dependencies.py`, `core/tenancy/middleware.py`, `modules/attendance/service.py`, `modules/employee_import/service.py`, `tests/conftest.py`, `test_attendance_day.py`, `test_leave_application_pagination.py` (135 insertions, 33 deletions).
- Untracked (18): migration `20261031090000_shift_tenant_fk.py`, 11 test files (`rls_support.py`, runtime-role and migration tests), 4 audit/design docs, `docs/operations/SHIFT_TENANT_FK_MIGRATION.md`.
- This progress file and `docs/production-readiness/` are new and untracked.

### Reconciliation with the stated project state
| Claim | Verified |
|---|---|
| Single Alembic head `20261031090000` | Yes: 128 revisions, one head (static scan) and `alembic current` = head on `s11-shiftfk-1` and `pr-base-1` |
| Migration is untracked | Yes (not in git) |
| `hrms_app` is restricted | Yes: `rolsuper=f`, `rolbypassrls=f`; owner `hrms` is superuser+BYPASSRLS |
| Import enqueue fix and Stage 9 shift ownership fix present | Present as uncommitted diffs (`employee_import/service.py`, `attendance/service.py`) |
| `s11-shiftfk-1` running | Yes; isolation guard PASS (ISOLATION PROVED) |
| `rls-h1` preserved | Yes, running, untouched |

### Environments
| Stack | Role | Use |
|---|---|---|
| `rls-h1` | QA residual data | **Do not touch** |
| `s11-shiftfk-1` | Stage 9/10 FK migration verification | read-only reference |
| `pr-base-1` (db `hrms_qa_pr_base_1`) | new, this programme | baseline suite; created by `stack.sh up`, guard passed, migrated to head |
| `hrms-postgres/redis/minio` (5433/6380/9000) | shared dev | **Never used.** The test guard refused a host-side pytest collect, as designed |

### Baseline checks
- `ruff check src tests`: pass. `ruff format --check`: pass (600 files).
- `mypy`: **7 errors in 4 files**. None are in regions changed by the uncommitted diff (the changed regions of `attendance/service.py` are all above line 4600; errors are at 6219-6220):
  - `attendance/service.py:6219,6220` — `_PeriodScope` vs `DataScope` assignment/arg type
  - `onboarding/router.py:318` — `UUID | None` passed as `UUID`
  - `attendance/opensource_face/embedding_service.py` — missing `numpy` stubs (and others)
- Full pytest on `pr-base-1`: pending (see below).

### Outstanding / next
- Record the full-suite result here, then Stage 1 (runtime-role coverage for import, invite, onboarding, org masters).

## Stage 1 — Tenant-isolation coverage (status: in progress)

Environment: `s11-shiftfk-1` (disposable, guard passed, db `hrms_qa_s11_shiftfk_1`). API runs as `hrms_app` (verified non-super, non-BYPASSRLS by `assert_role_is_unprivileged`); setup, assertions and teardown use the admin role and only touch rows each test created.

| Module | Result | Evidence |
|---|---|---|
| Employee import | **No defect found.** Foreign-tenant batch and errors return 404 identical to an unknown id (no existence oracle); reference-data is tenant-scoped; a CSV in tenant B naming tenant A's org entities creates 0 employees in either tenant and no cross-tenant assignment | new `tests/integration/modules/employee_import/test_import_rls_runtime_role.py`: 2 passed; whole import dir 20 passed |
| Account invite / role assignment | **No defect found.** Code review: `assign_roles` resolves membership by `(user_id, company_id)` and roles by `company_id`; foreign user gives 404. Cross-tenant list, role assignment, invite, token pivot and token replay all refused under `hrms_app`; target's roles unchanged | new `tests/integration/modules/account_invite/test_account_invite_rls_runtime_role.py`: 1 passed |

These are coverage additions, not fixes. They have not been mutation-checked against a deliberately broken service. They do not cover public invite-token acceptance abuse, `email_outbox`, or `session`/`refresh_token` (no RLS).

Still to do in Stage 1: onboarding (public token flow, uploads, activation), organisation masters, employee assignments/documents, remaining payroll and attendance background tasks. Lint on new files passes (`ruff check`, `ruff format`).

## Baseline full-suite run (pr-base-1) — complete
Command: `stack.sh pytest pr-base-1 tests -q` (isolation guard passed; DB `hrms_qa_pr_base_1`, migrated to head `20261031090000`). Run before the new Stage 1 tests were added.

**Result: 3853 passed, 54 skipped, 4 failed (18m49s).** Note: this run is the existing suite, most of which runs as the BYPASSRLS owner, so a pass here is not evidence of tenant isolation.

| Failure | Cause | Disposition |
|---|---|---|
| `test_scope_enforcement_guard::test_every_scope_ignoring_route_is_a_reviewed_exception` | `POST /onboarding-cases/{id}/cancel` (`ONBOARDING.CANCEL`) had no reviewed exception entry, unlike its four sibling `ONBOARDING.*` codes. Not a scope bypass: all `ONBOARDING.*` are seeded at COMPANY scope only (`organisation/service.py`) and cases pre-date any employee | **Fixed**: added the reviewed entry to `tests/unit/core/scope_guard_exceptions.toml`. Guard file now 16 passed. Pre-existing at HEAD (router unmodified) |
| `test_liveness.py` x2, `test_opensource_face_evaluation.py` x1 | `cv2` (and numpy stubs) not installed in the QA runner; they belong to the optional `liveness` extra | **Unresolved, environmental.** Tests fail rather than skip when the extra is missing. Open question for Stage 7: CI runs `uv sync --all-groups` (no extra), so check whether CI hits the same failures |

Remaining unverified: whether these 3 pass with the `liveness` extra installed.

## PAUSED — 2026-10-29 (resume checkpoint)

**Status:** Stage 0 complete. Stage 1 in progress (import and account-invite covered; rest not started). Stages 2-8 not started. No work is running. See `checkpoints/2026-10-29-pause.md` for resume/verification commands.

### Completed
- Baseline full suite on `pr-base-1` (before new tests): **3853 passed, 54 skipped, 4 failed** (18m49s).
- Fixed 1 failure: scope-guard exception for `ONBOARDING.CANCEL` (`tests/unit/core/scope_guard_exceptions.toml`); guard file 16 passed.
- 3 failures unresolved: `test_liveness.py` x2 and `test_opensource_face_evaluation.py` x1, `cv2` missing in the runner (optional `liveness` extra). Not yet checked with the extra installed or in CI.
- New runtime-role tests: `employee_import/test_import_rls_runtime_role.py` (2 passed; import dir 20 passed) and `account_invite/test_account_invite_rls_runtime_role.py` (1 passed). Both on `s11-shiftfk-1`. No defects found. Not mutation-checked.
- Not re-run after the scope-guard fix: the full suite. Only the guard file was re-run.

### Working tree at pause (all preserved, nothing committed)
Branch `main`, HEAD `f6340eb`. Modified (10): `.github/workflows/ci.yml`, `core/auth/dependencies.py`, `core/tenancy/dependencies.py`, `core/tenancy/middleware.py`, `attendance/service.py`, `employee_import/service.py`, `tests/conftest.py`, `test_attendance_day.py`, `test_leave_application_pagination.py`, `scope_guard_exceptions.toml` (the last is from this programme).
Untracked: migration `20261031090000_shift_tenant_fk.py`; tests: `test_shift_tenant_fk_migrations.py`, `test_account_invite_rls_runtime_role.py` (new), `test_import_rls_runtime_role.py` (new), `test_attendance_rls_runtime_role.py`, `test_roster_regularization_rls_runtime_role.py`, `test_shift_tenant_fk_runtime_role.py`, `test_import_enqueue_failure_runtime_role.py`, `test_leave_accrual_task_runtime_role.py`, `test_leave_rls_runtime_role.py`, `test_payroll_rls_runtime_role.py`, `tests/rls_support.py`, `test_rls_harness.py`, `test_tenant_resolution_runtime_role.py`, `test_tenancy_middleware.py`, `test_rls_support.py`; docs: 3 blind-audit reports, `SHIFT_TENANT_FK_MIGRATION.md`, `docs/production-readiness/`.

### Stacks (all still running)
`rls-h1` (alembic `20261030090000`, preserve untouched); `s11-shiftfk-1` (`20261031090000`, FK verification and Stage 1 tests); `pr-base-1` (`20261031090000`, baseline). Shared dev stack (5433/6380/9000) never used. No DB reset or cleanup done; tests cleaned only their own rows.

### Next task
Finish Stage 1 coverage (onboarding, org masters, employee assignments/documents, background tasks), then read-only pre-flight checks for `shift_version.shift_id`, `attendance_day.shift_id`, `employee_assignment.shift_id`.

### Recheck on resume
- Working tree matches the sha256 manifest; HEAD still `f6340eb`.
- Stacks still up and guard passes; `pr-base-1` now holds baseline-run leftovers and is not clean.
- Run the full suite again after the scope-guard edit and new tests.
- Whether the 3 `cv2` failures also occur in CI.
- `mypy` 7 pre-existing errors untouched.
- Migration `20261031090000` is still untracked and unverified on production-shaped data.
