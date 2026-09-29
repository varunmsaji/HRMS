# Full Test Suite

One command that gives a trustworthy, repeatable health check of the backend, frontend, and
database schema, without ever touching the developer's persistent `hrms_dev` database.

```bash
python run_full_tests.py
```

Runs (in order): infra health check → isolated test-database creation + migrations → backend
static checks (ruff, mypy, import boundaries) → backend unit tests → backend integration +
security tests → frontend typecheck, tests, and production build. Prints a human-readable summary,
writes `test-results/{results.json,results.xml,summary.txt}`, and exits non-zero if anything failed.

## Prerequisites

- The dev infra containers from `docker-compose.yml` (`hrms-postgres`, `hrms-redis`, `hrms-minio`,
  `hrms-minio-init`) — the runner starts them via `docker compose`/`docker-compose up -d` if they
  aren't already running, and polls their healthchecks.
- `apps/api/.venv` already created (`uv sync --all-groups` in `apps/api`).
- `apps/web/node_modules` already installed (the runner runs `npm ci` itself if missing).
- `psql`, `docker`, `uv`, `npm`, `npx` on `PATH`.

## Environment isolation

| Resource | Dev uses | This runner uses |
|---|---|---|
| Postgres database | `hrms_dev` on `localhost:5433` | `hrms_test` on the same server |
| Redis logical DB | index `0` on `localhost:6380` | index `1` |
| MinIO bucket | `hrms-documents` | same bucket (known limitation, see below) |

`hrms_test` is created fresh, has `infra/docker/postgres/init/001_extensions.sql` and
`002_app_role.sh`'s grants applied, then fully migrated (`alembic upgrade head`) before any test
runs — then dropped again in a `finally` block, so a failure mid-run still cleans up. Pass
`--keep-services` to leave it in place for post-mortem debugging.

`assert_safe_target()` at the top of `run_full_tests.py` refuses to run at all if the configured
test database name doesn't contain "test", matches the dev database name, or if the Postgres host
isn't `localhost`/`127.0.0.1` — and refuses if an ambient `DATABASE_URL`/`MIGRATIONS_DATABASE_URL`
in the environment looks like a staging/production URL.

**Known limitation**: MinIO storage tests reuse the dev bucket (`hrms-documents`) rather than a
dedicated test bucket — creating and tearing down a disposable bucket per run is a reasonable
follow-up but wasn't necessary for the existing storage tests, which use randomized object keys and
clean up after themselves. Do not add tests that assume the bucket is empty at start.

## Why `hrms_test`, not a disposable container

`docker-compose.yml`'s Postgres container is also used by the developer's running `uvicorn`
server. Rather than spinning up a second, fully separate Postgres container (a second image,
volume, and network — more moving parts, more to go wrong, and unnecessary since Postgres
databases are already isolated catalogs), the runner creates a second **database** on the same
server. Data isolation is exactly as strong; only the process/container is shared, and the
process was already running and healthy in dev anyway.

## A real trap this design avoids

`apps/api/tests/conftest.py` defaults `DATABASE_URL` to `hrms_dev` when no override is set — so
running the raw pytest suite without this runner **truncates the developer's real dev data**
(confirmed by direct observation once during this project). The whole point of `hrms_test` +
explicit `DATABASE_URL`/`MIGRATIONS_DATABASE_URL` overrides is to make that impossible from this
runner.

A second, subtler trap found while building this: `apps/api/alembic/env.py` prefers
`MIGRATIONS_DATABASE_URL` read out of `apps/api/.env` over the `DATABASE_URL` passed as a real
environment variable, and this repo's own `.env` points `MIGRATIONS_DATABASE_URL` at `hrms_dev`.
Overriding `DATABASE_URL` alone is not enough — `MIGRATIONS_DATABASE_URL` must be set explicitly
too, or `alembic upgrade head` silently migrates `hrms_dev` (a no-op there, since it's already at
head) while `hrms_test` never gets its schema. `run_full_tests.py` sets both.

## A CI quirk this design also works around

`uv run pytest` / `uv run alembic` resolve to a broken interpreter in this development
environment (a conda Python leaks in ahead of the project's own `.venv`), which surfaces as
unrelated-looking errors (e.g. `AttributeError: module 'jwt.api_jws' has no attribute
'InsecureKeyLengthWarning'`). The runner invokes `apps/api/.venv/bin/python -m pytest` /
`-m alembic` directly instead. `uv run ruff` / `uv run mypy` / `uv run lint-imports` are
unaffected and keep using `uv run`. If this repo is run somewhere `uv run` works cleanly, the
direct `.venv/bin/python` invocation is still correct — it's just more explicit.

## Test categories and what "unit" actually means here

There are no pytest markers in this repo — `tests/unit`, `tests/integration`, `tests/security`
are directory-based splits, mirrored exactly by `.github/workflows/ci.yml`. CI's "unit tests (no
database)" step name is optimistic: several unit tests (`test_crypto_keys.py`, `modules/health`,
`modules/organisation/test_router.py`) boot the real app and open a real DB connection. CI gets
away with this because it always migrates `hrms_dev` before either pytest step runs. This runner
does the same — it migrates `hrms_test` before **any** backend tests, including `--unit` alone.

`--quick` still creates and migrates the test database for this reason; it is fast (a few
seconds), not free, but it is the only way `--unit` reports real results rather than spurious
`database does not exist` errors.

## Command-line options

```
python run_full_tests.py               # everything: static + unit + integration + security + frontend
python run_full_tests.py --quick       # unit tests only (still needs/creates the test DB)
python run_full_tests.py --static      # ruff / ruff format / mypy / import-linter only
python run_full_tests.py --unit
python run_full_tests.py --integration
python run_full_tests.py --security
python run_full_tests.py --backend     # static + unit + integration + security, no frontend
python run_full_tests.py --frontend    # typecheck + vitest + production build only
python run_full_tests.py --keep-services   # don't drop hrms_test at the end
python run_full_tests.py --verbose         # stream subprocess output instead of capturing it
```

## Flaky-test detection

If a pytest stage (`unit` or `integration-security`) fails, the runner reruns only the failed
tests once (`pytest --lf`). If the rerun passes, the stage is reported as `FLAKY` (not `PASS`) and
the specific flaky test IDs are listed in the summary and in `results.json`'s `flaky_tests` — the
run still exits non-zero. If the rerun also fails, the stage is reported as `FAIL`. A failure is
never silently converted into a passing result.

## Reports

- `test-results/summary.txt` — the same human-readable report printed to stdout.
- `test-results/results.xml` — every backend pytest testcase (unit + integration + security) and
  every frontend vitest testcase, merged into one JUnit XML document.
- `test-results/results.json` — machine-readable: per-stage status/duration, and a flat `tests`
  array (name, category, duration, status, error, timestamp) parsed from the merged JUnit XML.
- Per-stage JUnit files (`unit.xml`, `integration-security.xml`, `web-vitest.xml`, and `*.rerun.xml`
  when a rerun happened) are kept alongside the merged files for drill-down.

## Timeouts and cleanup

Every stage has a timeout (see `STAGE_TIMEOUTS` in `run_full_tests.py`); a hung subprocess is
killed and the stage is reported as a `FAIL` with a `TIMEOUT` detail rather than hanging forever.
The test database is dropped in a `finally` block, so it is cleaned up even when an earlier stage
fails or raises — verified by running the full suite to completion, and separately by running a
stage that fails outright (`--static`, which currently fails on pre-existing lint issues in the
tree) and confirming `hrms_test` does not survive the run.

## Known gaps (not yet built)

This is phase 1 of the project described in `docs/audits/FULL_TEST_SUITE_IMPLEMENTATION.md` —
it covers what CI already covers, on demand, isolated, with unified reporting. Not yet covered:

- **Multi-tenant cross-company IDOR sweep** beyond what `tests/security/test_organisation_security.py`
  and the RLS suite already assert.
- **Full RBAC matrix** (every role × every endpoint).
- **Docker/deployment tests** (`docker-compose.prod.yml`, Nginx, certbot, worker/beat containers).
- **Failure injection** (Postgres/Redis/MinIO/SMTP down mid-request).
- **Backup/restore** drill.
- **Coverage measurement** (`pytest-cov` is not currently a dependency).
- A dedicated disposable MinIO bucket per run (see limitation above).

## Troubleshooting

- **"expected venv interpreter not found"** — run `uv sync --all-groups` in `apps/api` first.
- **Containers never become healthy** — check `docker ps` / `docker logs hrms-postgres` etc.;
  the runner does not create these containers' images, only starts what `docker-compose.yml`
  defines.
- **`SAFETY ABORT` on startup** — do not weaken the checks in `assert_safe_target()`; they exist to
  keep this runner from ever touching a non-local or non-test database. Fix the environment
  instead.
