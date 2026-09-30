# Continuous Integration — Staff Spectrum HRMS

What `.github/workflows/ci.yml` actually does, why, and how to reproduce every check locally. This
document describes only what is implemented today — see
`docs/devops/CI_CD_DEVOPS_IMPLEMENTATION_PLAN.md` for what's planned but not yet built (Docker CI,
compose-boot validation, deployment, backups, monitoring — all explicitly out of scope for this
phase).

## Triggers

`push` and `pull_request` against `main` and `develop`. No path filters, no manual dispatch, no
schedule.

## Jobs

Four jobs, all running in parallel (no `needs:` between any of them):

| Job | What it checks |
|---|---|
| `api` | Ruff, Ruff-format, mypy, import-linter, unit tests, integration+security tests |
| `web` | ESLint (non-blocking), TypeScript, Vitest, production build |
| `security-scan` | Gitleaks secret scanning (blocking) |
| `dependency-scan` | pip-audit + npm audit (both non-blocking, see policy below) |

**Why `api` and `web` are each one job, not split into `-quality`/`-tests` pairs** (the example
split in the original brief): splitting would double `uv sync`/`npm ci` cost and re-pay the
Postgres/Redis/MinIO service-container startup cost twice per job, for a sub-30-second wall-clock
saving. On a free-tier Actions-minutes budget, that trade isn't worth it. The parallelism that
matters — backend vs. frontend vs. security vs. dependency-scanning never blocking each other — is
already there at the job level.

## Backend CI (`api` job)

Real `postgres:16-alpine` + `redis:7-alpine` service containers, fresh every run. Order of
operations: apply `infra/docker/postgres/init/*.sql`/`*.sh` (GH Actions service containers don't
run `docker-entrypoint-initdb.d`, so this is done by hand) → `alembic upgrade head` against the
now-empty database → assert `hrms_app` is `NOSUPERUSER`/`NOBYPASSRLS` → unit tests → start a
disposable MinIO + provision its bucket → integration + security tests (the only step that needs
MinIO).

**Database.** `DATABASE_URL` points at `hrms` (the schema owner), not `hrms_app`, for the
integration+security run — deliberately. Most integration fixtures do raw cross-tenant
DELETE/INSERT relying on bypass privileges; `tests/security/test_rls_runtime_role.py` independently
re-points itself at `hrms_app` and opens its own raw `hrms_app` engine, so RLS is still proven by
the database, not by application code, regardless of what the default session uses.

**Redis.** One service container, port 6380. Fail-closed rate-limiter behavior
(`tests/unit/shared/test_rate_limit_redis_failure.py` and similar) is tested at the unit level with
a broken/unreachable URL — it does not need the real service to fail.

**MinIO — new in this phase.** Several `tests/integration` files
(`core/test_storage.py`, `modules/employee_import/test_employee_import*.py`,
`modules/onboarding/test_onboarding_documents.py` and its upload-bounds/rate-limit siblings) talk to
a real MinIO over the S3 API, no mocking — the same convention already used for Postgres/Redis.
Until this phase, CI never provided one, so `S3_ENDPOINT_URL` stayed unset and any test that
actually opened the S3 client would either error or try to resolve real AWS S3. The `api` job now
starts a disposable `pgsty/silo` container (same credentials and bucket name as `docker-compose.yml`'s
`minio`/`minio-init` services — no CI-only path), waits for `/minio/health/live`, provisions the
`hrms-documents` bucket via `pgsty/mc`, and only then runs the MinIO-dependent tests. All 29
previously-unverified-in-CI tests pass against this setup (verified locally against an equivalent
disposable container — see `docs/devops/PHASE_A_CI_IMPLEMENTATION.md`).

`pgsty/silo`/`pgsty/mc` replaced `minio/minio`/`quay.io/minio/mc` repo-wide (dev, CI, and
production) after `docs/devops/MINIO_IMAGE_REPLACEMENT_AUDIT.md` found MinIO Inc. had archived the
original images with no open-source successor. CI pins the same image digest
`docker-compose.prod.yml` does, so a green CI run means something about the exact bits production
runs, not just an equivalent-looking fork.

One MinIO-dependent test (`test_object_survives_a_minio_container_restart`) additionally shells out
to `docker restart` on a container named `hrms-minio` and self-skips if that exact name isn't
reachable. In this job the container is named `ci-minio`, so this one test correctly skips in CI —
it's written that way on purpose for exactly this situation, per its own docstring.

**SMTP.** No CI changes needed. `EMAIL_PROVIDER` defaults to `logging` under
`ENVIRONMENT=development` (what CI sets), and every SMTP-transport test
(`tests/unit/modules/onboarding/test_email_sender.py`) mocks `aiosmtplib.send` directly — no real or
fake SMTP server is contacted by anything in this suite.

## Frontend CI (`web` job)

`TZ=America/New_York` (deliberately non-IST — the Phase 6 timezone tests assert an attendance
instant renders as IST regardless of viewer timezone; running the job in UTC would let a
host-timezone-fallback regression slip through on values that happen to look close enough).

**ESLint — new in this phase, non-blocking.** `apps/web` had no ESLint dependency or config at
all; `next lint` / `npm run lint` would hang on an interactive setup prompt in a non-interactive
shell. `.eslintrc.json` (new, extends `next/core-web-vitals`) plus `eslint`+`eslint-config-next`
(pinned to this repo's exact Next version, 14.2.28) fix that — `next lint` is now genuinely
non-interactive. Turning it on for the first time surfaced 7 pre-existing violations across 6
files (6 `react/no-unescaped-entities`, 1 `react-hooks/exhaustive-deps`), none of which this phase
touches. The step runs with `continue-on-error: true` and is explicitly, visibly labeled
non-blocking rather than silently skipped — its output still appears in every run. Promote to
blocking once that backlog is cleared in a follow-up PR.

**Why `next build` doesn't fail over the same 7 violations:** by default, once an ESLint config
exists, `next build` folds linting into the build step and fails the whole build on any lint error
— which would have made "ESLint has 7 pre-existing findings" look like "the production build is
broken." `next.config.mjs` now sets `eslint.ignoreDuringBuilds: true` so the two stay decoupled:
build failure means the bundle doesn't compile; lint failure is reported separately and
non-blockingly, for now.

**Production build — new in this phase.** CI never ran `next build` before; only the local
`run_full_tests.py` did. It's a real, blocking step now.

## Secret scanning (`security-scan` job)

Gitleaks, run via `docker run zricethezav/gitleaks:latest detect --no-git`, against
`.gitleaks.toml` (new, repo root). **Blocking** — no `continue-on-error`, per the explicit
instruction that a genuine committed secret must fail CI.

`--no-git` is deliberate: `gitleaks detect` on a git checkout defaults to re-scanning the *entire*
commit history on every single run, which both gets slower as the repo grows and re-flags history
that's already been reviewed instead of answering the question this gate actually needs to answer
— "is there a secret in the code as it would be if this PR merges." The one-time, full-history scan
(69 commits) was run by hand as part of the Phase 0 pre-push audit before anything was pushed to
`origin/main`; this job covers the ongoing, per-PR case going forward.

`.gitleaks.toml` excludes build/tool-cache paths (`.next/`, `.mypy_cache/`, `.ruff_cache/`,
`.pytest_cache/`, `node_modules/`, `.venv/`, `test-results/` — never actually present in this job's
checkout, since it never builds or installs anything, but excluded anyway so a developer running
the identical command locally gets the identical result) and one hand-verified false positive: the
`generic-api-key` rule matches a plain-English sentence in
`docs/product/25_Project_Plan_Estimation_and_Team.md:220` describing the stack in the developer's
own job-responsibilities table cell, on token shape, not content (deliberately not quoted verbatim
here — doing so previously made this very paragraph trip the same rule against itself). Verified by
reading the actual line — it contains no credential. The allowlist entry is scoped to that one file, not a blanket
rule-disable.

## Dependency scanning (`dependency-scan` job)

**Python:** `pip-audit`, run via `uvx pip-audit` (ephemeral — deliberately not added to
`uv.lock`/`pyproject.toml`, so a CI-only tool never becomes a project dependency) against
`uv export --no-hashes --no-emit-project`. Checked at implementation time: **0 known
vulnerabilities.**

**Frontend:** `npm audit --audit-level=high`. Checked at implementation time: **8 real advisories
against the pinned Next.js 14.2.28** — 1 critical, 5 high, 2 moderate (cache poisoning, SSRF, DoS,
and a Remote Code Execution in the Image Optimization API among them). Remediation is a Next.js
major-version upgrade (14 → 16), which is a breaking change requiring its own dedicated,
separately-tested effort — explicitly out of scope for "CI foundation." See
`docs/devops/PHASE_A_CI_IMPLEMENTATION.md` §5 for the full finding and the human decision it raises.

**Initial policy — both non-blocking.** Failing every PR over every historical advisory
(especially one requiring a major version bump to fix) the moment dependency scanning is switched
on would make the gate something to route around, not something anyone trusts. Findings are fully
visible in every run's log and job summary; promoting either check to blocking (and on what
severity threshold) is one of this phase's open decisions, not something this phase decided
unilaterally.

## Test reporting

Backend (`unit`, `integration+security`) and frontend (`vitest`) all produce JUnit XML
(`apps/api/test-results/*.xml`, `apps/web/test-results/*.xml`), uploaded as GitHub Actions
artifacts (`backend-test-reports`, `frontend-test-reports`, 14-day retention) on every run,
including failed ones (`if: always()`). Nothing secret is written to any report — these are test
pass/fail/timing records only.

## Failure behavior

Ruff, Ruff-format, mypy, import-linter, unit tests, integration+security tests, TypeScript,
Vitest, production build, and Gitleaks all fail the run on any failure — no
`continue-on-error`. ESLint and both dependency-scan steps are the only steps that don't block, and
that's a stated, visible policy (see above), not a hidden one.

## Local ⇄ CI parity

`python run_full_tests.py` (repo root) mirrors this workflow's backend static/unit/integration
gates and the frontend typecheck/vitest/build gates against the same commands, plus an isolated
`hrms_test` database instead of CI's ephemeral service container — functionally equivalent, safe to
run against a developer's already-running dev stack. As of this phase, the one remaining
asymmetry is ESLint, which CI now runs (non-blocking) and `run_full_tests.py` does not — worth
adding there too as a fast follow, tracked in Phase B readiness notes.

## Troubleshooting

- **A local `uv run <tool>` command reports errors that `python -m <tool>` doesn't (or vice
  versa):** check the console script's shebang (`head -1 .venv/bin/<tool>`) — if it points at a
  path other than this checkout's own `.venv`, the venv was carried over from a different path and
  needs rebuilding (`rm -rf apps/api/.venv && uv sync --all-groups`). This is a known local-machine
  quirk, not a CI issue — CI always creates its venv fresh on a clean runner.
- **MinIO-dependent integration tests fail locally but the rest of `tests/integration` passes:**
  confirm a MinIO container is actually running and reachable at whatever `S3_ENDPOINT_URL` you're
  using, and that its bucket exists (`mc mb`) — CI does both automatically; a local run via
  `run_full_tests.py` or `docker compose up` needs the same dev MinIO container up first.
- **Gitleaks flags something you're sure isn't a secret:** don't disable the rule — add a narrowly
  scoped `paths` entry to `.gitleaks.toml` for that specific file, with a comment explaining what
  was checked and why it's safe, matching the existing entries there.
