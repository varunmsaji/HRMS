# HRMS Testing & CI Audit

**Execution status: NO TESTS WERE RUN SUCCESSFULLY.** One attempt (`pytest tests/unit/core/test_passwords.py … test_scope_enforcement_guard.py -p no:cacheprovider`, bytecode writing disabled) aborted at collection: the root `tests/conftest.py` refused to run because `DATABASE_URL`/`REDIS_URL` pointed at the shared dev stack (`hrms_dev`, Redis 6380), which the conftest would modify (it deletes `ratelimit:*` keys). I did **not** set `HRMS_TEST_ALLOW_SHARED_DEV=1`. Statements below are about tests that **exist**, not tests that **pass**.

## 1. Layout (confirmed)
`apps/api/tests/{unit, integration, security}` plus Flutter (`apps/mobile/test`) and web (`vitest`, Playwright e2e in `apps/web/e2e`). Backend modules: unit tests under `tests/unit/{core,modules,ops,shared}`; DB-backed under `tests/integration/{auth,core,migrations,modules}`; `tests/security/*` (RLS runtime role, geofence RLS, credential provisioning, headers, API-docs exposure, organisation security, account-invite/onboarding token isolation).

## 2. Coverage assessment against the requested list
| Area | Exists? | Quality note |
|---|---|---|
| DB constraints | partly (integration per module) | runs as superuser; constraint behaviour is real, RLS is not |
| **Tenant isolation** | **yes, narrow** | `test_rls_runtime_role.py` (4 tests: role flags, cross-tenant CRUD under `hrms_app` via HTTP + raw SQL, login/refresh, RBAC scopes) and `test_geofence_rls.py`. Payroll/leave/attendance/org/onboarding **not** run as `hrms_app` (**F-01**) |
| Unauthorized access | yes | `tests/integration/test_route_authorization_matrix.py`, `test_scope_enforcement_guard.py` (+ toml ratchet) |
| Attendance/shift calc | yes (module integration/unit; not inspected) | |
| Leave balances/approvals | yes (hardening/ledger tests referenced by migrations) | |
| Payroll calc | yes (module tests; not inspected) | correctness of expected values not independently verified |
| Concurrency | some (advisory-lock/idempotency tests referenced in `b13_mp.py`, `b13_outbox_proc.py`) | |
| Idempotent retries | yes (`test_import_idempotency.py`, punch/leave) | |
| Auth lifecycle | yes (`integration/auth`, `unit/core/test_passwords.py`, `test_company_access.py`) | |
| **Migration consistency** | `tests/integration/migrations` exists | no model-vs-DB drift test found (F-11) |
| Background-job failures | yes (celery task failure/lifecycle/hardening unit tests) | |
| API error handling | yes (`test_error_contract.py`, `test_api_contract_core.py`, `test_route_robustness.py`) | |
| File access | `test_uploads.py`, `test_storage.py`; cross-tenant document download not specifically seen | |
| **Backup restore** | **no automated test found** | scripts only |
| Production configuration | yes (`test_settings.py`, `test_db01_credential_provisioning.py`, proxy header/CORS tests) | |

## 3. Findings
| ID | Sev | Conf. | Finding |
|---|---|---|---|
| F-01 | P1 | confirmed (design) | Suite default role = schema owner `hrms` (SUPERUSER+BYPASSRLS): `tests/security/test_rls_runtime_role.py:6-12`. Bugs that exist only when RLS is enforced (F-02 class) pass CI. Required: run the whole integration suite as `hrms_app` with a separate admin engine for fixtures/teardown. |
| F-14 | P2 | confirmed | The CI job labelled "Unit tests (no database)" cannot run locally without the disposable-stack environment, because the *root* conftest enforces infra isolation for every test. Developers (and AI agents) cannot get a fast unit signal without Docker. Move DB/Redis guard to the integration conftest. |
| F-31 | P2 | confirmed | CI has no `alembic check`/drift step, no `pip-audit`/`npm audit`/image scan, no coverage measurement, mypy runs on `src/hrms` only (tests excluded), ESLint is `continue-on-error`. |
| F-32 | P2 | confirmed | No automated restore test; backup scripts exist (`infra/backup/*`). |
| F-19 | P1-process | confirmed | 187 modified files + untracked head migration at audit time; CI can only validate committed state. |
| — | note | | Line coverage was not measured; high coverage would not establish tenant isolation or business-rule correctness. |

## 4. CI pipeline (confirmed, `.github/workflows/ci.yml`)
Jobs: API (ruff, ruff-format, mypy, import-linter, apply DB init scripts creating `hrms_app`, `alembic upgrade head`, assert `hrms_app` is NOSUPERUSER/NOBYPASSRLS, unit tests, MinIO container, integration+security), Web (npm ci, ESLint non-blocking, tsc, vitest, `next build`), Mobile (Flutter 3.29.2 analyze/test), gitleaks (`--no-git`, `:latest`). Positive: CI provisions the real runtime role and asserts it is restricted — the building block needed to fix F-01.

## 5. Missing tests worth adding (regression list)
1. Whole suite under `hrms_app`. 2. For every endpoint taking a foreign-entity id in body/path: "id from another tenant → 404, no write". 3. Commit-then-query RLS regression for each mid-request commit site. 4. Drift test (ORM constraints vs `pg_catalog`). 5. Restore drill in CI nightly. 6. Beat-missed-run catch-up test. 7. Concurrent finalise vs attendance reopen (documented lock order) with two real connections.
