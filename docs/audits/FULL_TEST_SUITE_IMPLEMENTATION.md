# Full Test Suite — Implementation Report (Phase 1)

Date: 2026-09-27

## Scope of this phase

The full request (see conversation) describes a multi-week program covering unit through
failure-injection and backup/restore testing. This phase delivers the foundation that every later
phase builds on: **one command that runs everything CI already knows how to run, on demand,
against a genuinely isolated database, with unified human- and machine-readable reporting** — and
that a developer or CI can trust not to touch `hrms_dev`. Later phases (multi-tenant IDOR sweep,
full RBAC matrix, Docker/deployment tests, failure injection, backup/restore, coverage-driven gap
filling) are deliberately not attempted here; see "Known gaps" below and in
`docs/testing/FULL_TEST_SUITE.md`.

## 1. Existing test coverage (found, not built)

- **Backend**: 154 `test_*.py` files under `apps/api/tests/{unit,integration,security}` — no
  pytest markers, purely directory-based. `tests/security` already proves RLS at the database
  layer (`test_rls_runtime_role.py`), credential provisioning (`test_db01_credential_provisioning.py`),
  org-level tenancy (`test_organisation_security.py`), and API docs exposure.
- **Frontend**: ~50 vitest files under `apps/web/src` (399 test cases) covering nearly every admin
  route, auth flows, and a large set of pure validation functions. This was more coverage than
  initially visible from a naive glob (a broad `*.test.*` search over `apps/web` without
  `apps/web/src` scoping returned nothing — a reminder to search more specifically).
- **CI** (`.github/workflows/ci.yml`) already runs: ruff check/format, mypy, import-linter,
  DB init scripts, `alembic upgrade head`, an explicit RLS-role assertion, `pytest tests/unit`,
  `pytest tests/integration tests/security`, `tsc --noEmit`, `npm test` — against `hrms_dev` on
  ephemeral GitHub Actions runners (safe there only because those runners are thrown away after
  each run).
- **What was missing**: no single local command ran all of this; no isolation from the developer's
  real `hrms_dev` database when run locally (confirmed by memory of a prior incident: running the
  suite locally without care previously truncated real seeded dev data); no unified JSON/JUnit
  report; no flaky-test detection.

## 2. New test coverage

None — per the project's own instruction, this phase is test *infrastructure*, not new test
authorship. No application test files were added, changed, or weakened.

## 3. Test architecture

`run_full_tests.py` at the repo root. Single file, no new backend/frontend dependencies. Stages:
prerequisites → infra health → isolated DB create/migrate → static checks → unit → integration +
security → frontend typecheck/test/build → report → cleanup. Full design rationale, the isolation
model, and two real traps discovered while building it are documented in
`docs/testing/FULL_TEST_SUITE.md` (read that file for the "why", not repeated here).

## 4. One-command execution

```bash
python run_full_tests.py
```

Verified twice from a clean state (`hrms_test` dropped before each run):

| Run | Static | Unit | Integration+Security | Frontend | Total stages | Exit code | Wall time |
|---|---|---|---|---|---|---|---|
| 1 | 3 FAIL / 1 PASS | PASS (699 tests) | PASS (1039 tests) | PASS (399 tests) | 10 PASS / 3 FAIL | 1 | 6m12s |
| 2 | 3 FAIL / 1 PASS | PASS (699 tests) | PASS (1039 tests) | PASS (399 tests) | 10 PASS / 3 FAIL | 1 | ~6m0s |

Identical results both times — no nondeterminism observed. The 3 static failures are **real,
pre-existing** ruff/mypy findings in the current working tree (not introduced by this work, not
touched, not silenced — see "Known gaps"). `python run_full_tests.py --quick` (unit tests only,
still isolated) completes in ~10s; `--static` alone in <1s; `--frontend` alone in ~25s;
`--integration --security` alone in ~5.5 minutes (the dominant cost of the whole suite).

## 5. Infrastructure isolation

- Postgres: dedicated database `hrms_test` on the existing dev Postgres server (not a separate
  container — see rationale in the testing doc), created fresh, migrated to head, dropped in a
  `finally` block. `hrms_dev` is never read or written by this runner.
- Redis: logical DB index `1`, separate from dev's index `0`.
- `assert_safe_target()` refuses to run if the test DB name doesn't contain "test", matches the
  dev DB name, the Postgres host isn't local, or an ambient `DATABASE_URL`/`MIGRATIONS_DATABASE_URL`
  looks like a staging/production URL.
- Cleanup was verified after both a fully-passing stage sequence and a stage that fails outright
  (`--static`): `hrms_test` did not survive either case. `docker ps` before and after a full run
  shows the same three containers, no extras created or left running.

Two real, non-obvious traps were found and fixed during this work, both documented in detail in
the testing doc:
1. `apps/api/alembic/env.py` prefers a `MIGRATIONS_DATABASE_URL` read directly out of
   `apps/api/.env` over the `DATABASE_URL` passed as a real process environment variable — and this
   repo's own `.env` points that at `hrms_dev`. The runner must set `MIGRATIONS_DATABASE_URL`
   explicitly, not just `DATABASE_URL`, or migrations silently target the wrong database.
2. `uv run pytest` / `uv run alembic` resolve to a broken interpreter in this development
   environment; the runner invokes `apps/api/.venv/bin/python -m pytest`/`-m alembic` directly.

## 6. Security coverage

Unchanged from what already existed (`tests/security/`, 5 files) — this phase makes it runnable
on demand and isolated, it does not add to it. The multi-tenant IDOR sweep, full RBAC matrix, and
broader auth-matrix testing described in the original request are not yet built (see gaps).

## 7. Business workflow coverage

Unchanged — existing integration coverage (attendance, leave, payroll, onboarding, organisation,
employee, employee_import, account_invite) now runs as one gated stage instead of an ad hoc
manual `pytest` invocation.

## 8. Frontend coverage

Unchanged test content; newly wired into the one-command runner: `tsc --noEmit`, `vitest run
--reporter=junit`, and `npm run build` (production build check) all execute and their results are
captured in the unified report.

## 9. Docker coverage

Not built this phase. The runner reuses the existing dev `docker-compose.yml` containers (starting
them if not already running, verifying health) but does not exercise `docker-compose.prod.yml`,
Nginx, certbot, or the worker/beat containers. See gaps.

## 10. Failure injection

Not built this phase.

## 11. Backup/restore

Not built this phase.

## 12. Coverage measurements

Not measured — `pytest-cov` is not currently a dependency of `apps/api`, and adding a coverage
threshold was explicitly out of scope ("do not set an arbitrary threshold simply to create a green
number"). Adding `pytest-cov` and reporting actual line/branch coverage without a pass/fail gate is
a reasonable next increment.

## 13. Known gaps

- Multi-tenant IDOR sweep beyond the existing RLS/org-security tests.
- Full RBAC matrix (role × endpoint).
- Docker/deployment tests against `docker-compose.prod.yml`.
- Failure-injection tests (Postgres/Redis/MinIO/SMTP down mid-request).
- Backup/restore drill.
- Coverage measurement and gap analysis.
- Dedicated disposable MinIO bucket per run (currently reuses the dev bucket — documented
  limitation, not a defect against any currently existing test).
- Concurrency-specific test additions beyond what `tests/integration/modules/attendance/
  test_attendance_concurrency.py` and similar existing files already cover.

## 14. Flaky tests

None observed in two full runs. The runner's flaky-detection mechanism (rerun failed tests once
via `pytest --lf`, report `FLAKY` rather than silently passing) was implemented and exercised
during development (triggered correctly when a stage failed for an environment reason before the
DB/migration fixes above were made) but no genuinely flaky application test was found once the
environment issues were corrected.

## 15. Environment-blocked tests

None — no test in the existing suite requires real external SMTP or real Let's Encrypt
credentials; `EMAIL_PROVIDER=logging` (the existing no-op provider) is used throughout, matching
what local dev and CI already do.

## 16. Exact final command

```bash
python run_full_tests.py
```

## 17. Exact final result (as of 2026-09-27, this working tree)

```
TOTAL STAGES: FAIL=3, PASS=10
RESULT: FAIL
```

The 3 failures are pre-existing `ruff check`, `ruff format --check`, and `mypy` findings in the
current uncommitted working tree — real defects the runner correctly surfaces, not something this
work introduced or should silently fix. Every test-execution stage (unit: 699 tests, integration +
security: 1039 tests, frontend vitest: 399 tests, plus typecheck and production build) passes.
