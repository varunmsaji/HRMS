# DevOps Phase A — CI Foundation Implementation Report

**Scope:** Phase 0 (repository release baseline) + Phase A (CI foundation) only, per
`docs/devops/CI_CD_DEVOPS_IMPLEMENTATION_PLAN.md`. Docker image CI, compose-boot validation, GHCR,
VPS provisioning, deployment, backups, monitoring, and staging are explicitly Phase B+ and are not
touched here.

**Git state:** nothing has been committed or pushed. Every change described below exists only in
the working tree, pending review.

---

## 1. Initial CI State

- `.github/workflows/ci.yml`: two jobs (`api`, `web`), triggered on `push`/`pull_request` to
  `main`/`develop`. No Docker build, no secret scanning, no dependency scanning, no frontend lint,
  no frontend production build, no test-report artifacts.
- GitHub Actions had executed **twice** in this repository's entire history (2026-08-25,
  2026-09-03), both failures, nothing since — because `origin/main` was 27 commits behind local
  `main` (confirmed in Phase 0 below). CI had validated none of the payroll, TDS, onboarding, or
  release-hardening work done since early September.
- Local backend static analysis was initially reported as failing (mypy: 10 errors) due to a
  stale `.venv` shebang pointing at a decoy path from a different checkout location — not a real
  code defect. Rebuilding the venv (`rm -rf apps/api/.venv && uv sync --all-groups`) resolved it;
  see §13.
- Confirmed-clean backend baseline, once the venv was fixed: **1,747 tests passed, 0 failed, 0
  errors** (708 unit + 1,039 integration+security), mypy/import-linter/ruff clean on all 27
  committed commits (the only static-analysis failures found were in one already-uncommitted,
  in-progress file, `apps/api/src/hrms/seed/bootstrap.py`, untouched by this phase).
- Frontend: TypeScript clean, Vitest 399/399 passed, `next build` succeeded — but had never been
  run in CI, only via the local `run_full_tests.py`. No ESLint existed anywhere in `apps/web`.

## 2. Files Changed

| File | Change |
|---|---|
| `.github/workflows/ci.yml` | MinIO service steps + env vars in `api` job; ESLint + build steps in `web` job; two new jobs (`security-scan`, `dependency-scan`); JUnit report generation + artifact upload; job summaries |
| `.gitleaks.toml` (new) | Secret-scanning config: narrow path allowlist for build/cache dirs + one hand-verified doc false positive |
| `apps/web/.eslintrc.json` (new) | `{"extends": "next/core-web-vitals"}` — the first ESLint config this app has ever had |
| `apps/web/next.config.mjs` | Added `eslint.ignoreDuringBuilds: true`, with a comment explaining why (see §5) |
| `apps/web/package.json`, `apps/web/package-lock.json` | Added `eslint@8.57.1`, `eslint-config-next@14.2.28` as exact-pinned devDependencies |
| `docs/devops/CI.md` (new) | CI reference documentation (A16) |
| `docs/devops/PHASE_A_CI_IMPLEMENTATION.md` (new) | This report |

No backend application code, no frontend application code (beyond the two config files above),
and no test files were modified. `pyproject.toml`/`uv.lock` were deliberately left untouched — an
earlier attempt to add `pip-audit` as a project dev-dependency via `uv add` was reverted in favor
of running it ephemerally via `uvx` in CI only (see §11).

## 3. Workflow Architecture

Four jobs, all parallel, no `needs:` between any of them: `api`, `web`, `security-scan`,
`dependency-scan`. See `docs/devops/CI.md` for the full reference and the reasoning for keeping
`api`/`web` each as one job rather than splitting into quality/test pairs.

## 4. Backend CI

Unchanged in its core sequence (Ruff → Ruff-format → mypy → import-linter → init scripts → Alembic
→ RLS role check → unit tests). Added: MinIO startup + bucket provisioning between the unit and
integration+security steps, S3 env vars added to the integration+security step only, JUnit output
for both pytest steps, artifact upload. See §6–§9 below and `docs/devops/CI.md` for the detail.

## 5. Frontend CI

Added ESLint (non-blocking — see §13), `next build` (blocking, new), JUnit output for Vitest,
artifact upload. The interaction that needed resolving: adding an ESLint config makes `next build`
fold linting into the build step by default, which turned "7 pre-existing lint findings" into
"the production build is broken." Fixed via `eslint.ignoreDuringBuilds: true` in
`next.config.mjs`, which decouples the two — this is the "legitimate repository change" flagged
and documented per the A6 instruction before making it, not an unrelated code change.

## 6. Database Setup

No changes needed beyond what already existed — verified, not assumed. `HRMS_APP_PASSWORD`,
`DATABASE_URL`, `MIGRATIONS_DATABASE_URL`, the RLS runtime role, and the migration role were all
already correctly wired in `ci.yml` from the DB-01 remediation (Phase 6A), and all passed cleanly
in local verification (§9, §13). No hardcoded production credential exists anywhere in CI — every
value used is the same repo-visible, dev-only placeholder already documented in
`apps/api/.env.example` and `docker-compose.yml`.

## 7. Redis Setup

No changes needed. One service container (port 6380) already existed and is sufficient; the
fail-closed rate-limiter behavior is tested at the unit level against a broken/unreachable URL, so
it doesn't need the real service to actually fail.

## 8. MinIO Setup

**New.** Confirmed via direct inspection that `tests/integration/core/test_storage.py` and four
other integration files talk to a real MinIO over the S3 API with no mocking, and that CI
previously provided none — meaning `S3_ENDPOINT_URL` was unset in every real CI run to date, and
any test opening the S3 client would either error or attempt to resolve real AWS S3. This is a
plausible contributing factor in the two historical CI failures, though not confirmed as the sole
cause (the runs predate the DB-01 fix that also could have broken things at that time).

Added: a disposable `minio/minio:latest` container (test-only credentials matching
`docker-compose.yml`'s `minio` service, not real secrets), a health-check wait loop against
`/minio/health/live`, and bucket provisioning via `quay.io/minio/mc` matching
`docker-compose.yml`'s `minio-init` service exactly. Never exposed beyond the ephemeral runner;
torn down unconditionally (`if: always()`) at the end of the job.

**Verified locally** (§13): ran the 4 real MinIO-dependent integration test files (29 tests) against
an equivalent disposable container on an isolated port — all 29 passed, including the one test
that self-skips when the specifically-named restart-target container isn't reachable (which it
correctly will, in real CI, since no container there is named `hrms-minio`).

## 9. SMTP Test Strategy

**No changes made — verified, not needed.** `EMAIL_PROVIDER` defaults to `logging` under
`ENVIRONMENT=development` (what CI already sets), and every SMTP-transport test mocks
`aiosmtplib.send` directly. No real or fake SMTP server is contacted by anything in the existing
test suite. Confirmed by reading `tests/unit/modules/onboarding/test_email_sender.py` directly.

## 10. Secret Scanning

Gitleaks, run via Docker (`zricethezav/gitleaks:latest`), blocking (no `continue-on-error`) — a
genuine detected secret must fail CI, per instruction.

**Real issue found and fixed before finalizing this job:** the first version of this step used
`gitleaks detect` with default git-history mode, which (a) re-scans the entire commit history on
every future run rather than just the code as it would exist after merge, and (b) flagged 9
"leaks" — 8 were local-only Next.js build artifacts (`.next/prerender-manifest.json` etc.,
generated by my own local `next build` runs, gitignored, never present in a real CI checkout) and 1
was a genuine, persistent false positive: `docs/product/25_Project_Plan_Estimation_and_Team.md:220`
matches the `generic-api-key` rule on token shape in an ordinary English sentence about the
developer's job responsibilities. Verified by reading the line directly — no credential of any
kind. Fixed by switching to `--no-git` mode (checks the checked-out tree, not history) and adding
`.gitleaks.toml` with a narrow path-based allowlist for that one file plus common build/cache
directories (never present in this job's checkout anyway). No secret was ever added to any
allowlist — every entry is a confirmed non-secret, documented with why.

Re-verified against a simulated clean checkout (working tree minus `.git`/`node_modules`/`.venv`/
build+cache dirs, representing what CI will see once this is committed): **no leaks found.**

## 11. Dependency Scanning

**Python:** `pip-audit` via `uvx` (ephemeral — not added to `uv.lock`; an earlier attempt to add it
via `uv add --dev` was deliberately reverted, see §2) against `uv export`. Result: **0 known
vulnerabilities.**

**Frontend:** `npm audit --audit-level=high`. Result: **8 real advisories against the pinned
Next.js 14.2.28 — 1 critical, 5 high, 2 moderate**, including cache poisoning, SSRF, DoS, and a
Remote Code Execution in the Image Optimization API (one advisory, an RCE on Windows-hosted
servers, doesn't apply to this Linux-only Docker deployment; the others are not
platform-restricted). Fixing this requires a Next.js 14→16 major-version upgrade — a breaking
change requiring its own dedicated, separately-tested effort, explicitly out of scope for "CI
foundation" and outside the instruction not to modify unrelated frontend code.

**Policy (both non-blocking for this rollout):** failing every PR immediately over findings that
require a major-version bump to fix — one of them the day dependency scanning is switched on —
would make the gate something to route around rather than trust. Both findings are fully visible in
every CI run's log and job summary. This is the sensible-initial-policy instruction applied
honestly to a real, non-trivial finding, not used to bury it — see §16 for why this is flagged as
a human decision rather than something resolved silently here.

## 12. Test Reporting

JUnit XML for backend unit, backend integration+security, and frontend Vitest, uploaded as
`backend-test-reports` / `frontend-test-reports` artifacts (14-day retention, uploaded even on
failure via `if: always()`). Each job also writes a short markdown line to
`$GITHUB_STEP_SUMMARY` so a PR's Actions tab shows Backend / Frontend / Security /
Dependency-scan status at a glance without opening full logs. No secrets or application data are
written to any report — pass/fail/timing only.

## 13. CI Failures Encountered (and Root-Caused Locally)

1. **Stale `.venv` shebang → false mypy failures.** `uv run mypy src/hrms` reported 10 errors,
   including "cannot find stub for structlog/aiosmtplib" despite both packages being installed
   with `py.typed` markers present. Root cause: `.venv/bin/mypy`'s shebang pointed at a `varun8`
   path (a stale venv, likely carried over from a different checkout location), not the actual
   `varun9` checkout — `uv run <console-script>` executes the script directly via its own shebang
   rather than uv re-resolving the interpreter, so the wrong Python ran mypy against the wrong
   site-packages. `uv run python -m mypy` (module invocation, unaffected by the stale shebang)
   returned clean immediately, confirming the code was never actually broken. Fixed by rebuilding
   the venv from scratch (`rm -rf .venv && uv sync --all-groups`); re-verified clean after.
2. **`next build` failing after adding ESLint.** Covered in §5.
3. **`gitleaks detect` default mode flagging 9 false positives.** Covered in §10.
4. **`quay.io/minio/mc` entrypoint.** First attempt (`docker run ... quay.io/minio/mc:latest /bin/sh
   -c "..."`) failed with `mc: <ERROR> /bin/sh is not a recognized command` — the image's default
   ENTRYPOINT is `mc` itself, so `/bin/sh` was parsed as an mc subcommand. Fixed with
   `--entrypoint /bin/sh ... -c "..."` to actually override the entrypoint, matching how
   `docker-compose.yml`'s `minio-init` service does it via its own `entrypoint:` key.
5. **Port collision during local MinIO validation.** The developer's own dev-stack MinIO was
   already running on 9000/9001; my first disposable-container test tried to bind the same ports
   and failed. Re-ran against an unused port (19000) for a valid, isolated test. No production or
   dev-stack impact.
6. **Incidental restart of the dev MinIO container.** During local validation of the
   MinIO-dependent integration tests, `test_object_survives_a_minio_container_restart` found a
   container literally named `hrms-minio` (the developer's persistent dev container, not my
   disposable test one) and restarted it, since its skip-check matches by that exact name. Verified
   afterward that the dev container came back up healthy with no lasting effect. This cannot happen
   in real CI (no container there is ever named `hrms-minio`), only in a local test run where both
   happened to coexist — noted here for transparency, not because it's a workflow bug.

None of these were hidden, worked around with `continue-on-error`, or left for someone else to
discover — each was root-caused and fixed (or, for #6, explicitly noted as a local-only artifact
of how I validated the change, with no code or config implication).

## 14. Fixes Made

- Rebuilt `apps/api/.venv` from scratch (no file changes — a local environment fix, not a code
  change).
- Added `eslint.ignoreDuringBuilds: true` to `apps/web/next.config.mjs`.
- Switched the Gitleaks step to `--no-git` mode with a narrow, documented `.gitleaks.toml`
  allowlist.
- Corrected the MinIO bucket-provisioning command to use `--entrypoint /bin/sh`.
- Reverted an initial `uv add --dev pip-audit` in favor of ephemeral `uvx pip-audit` in CI only.

No fix expanded scope beyond what Phase A asked for. No pre-existing application code (backend or
frontend) was modified.

## 15. Final Local Verification Result

Everything below was run directly, for real, against a corrected local environment — not assumed:

| Check | Result |
|---|---|
| Ruff check / Ruff format | FAIL — confined entirely to `apps/api/src/hrms/seed/bootstrap.py`, a pre-existing uncommitted file untouched by this phase |
| mypy (`src/hrms`) | **PASS** — 0 errors, 167 files |
| import-linter | **PASS** — 1 contract kept, 0 broken |
| Backend unit tests | **PASS** — 708 passed, 0 failed, 0 errors |
| Backend integration+security tests | **PASS** — 1,039 passed, 0 failed, 0 errors (includes the 29 MinIO-dependent tests, verified against a disposable container matching the new CI setup) |
| TypeScript (`tsc --noEmit`) | **PASS** |
| Vitest | **PASS** — 399 passed, 56 files |
| Production build (`next build`) | **PASS** (with `eslint.ignoreDuringBuilds: true`) |
| ESLint | **7 findings** (6 errors, 1 warning), non-blocking by documented policy |
| Gitleaks (`--no-git`, final config) | **PASS** — 0 leaks, verified against a simulated clean checkout |
| pip-audit | **PASS** — 0 known vulnerabilities |
| npm audit (`--audit-level=high`) | **8 findings** against Next.js 14.2.28 (1 critical, 5 high, 2 moderate), non-blocking by documented policy — see §11 |

**GitHub Actions itself: not yet run against these changes.** Nothing has been pushed or opened as
a PR — per the explicit instruction not to commit, push, merge, reset, squash, or rewrite history
without being asked, and the earlier instruction not to push without explicit sign-off. Every check
above was run locally against services (Postgres, Redis, a disposable MinIO, Docker-based Gitleaks)
configured to match the workflow's exact commands and credentials as closely as a local environment
allows, which is the strongest verification available without pushing. Actually exercising the
workflow on GitHub Actions requires either pushing this branch or opening a PR from it — this is a
decision for you, not something I did unilaterally (see §16).

## 16. Remaining CI Gaps

- **Not yet run on GitHub Actions itself** (§15) — the one thing this report cannot claim.
- ESLint backlog (7 findings) not fixed — by design, out of scope for this phase.
- Next.js dependency vulnerabilities (8 findings, 1 critical) not fixed — by design, out of scope;
  needs a dedicated major-version-upgrade effort.
- `run_full_tests.py` still doesn't run ESLint, so local/CI parity has one remaining asymmetry
  (CI now checks something local doesn't) — worth closing as a fast follow.
- Docker/Compose validation (CI-02, the highest-priority item in the overall plan) is still
  entirely untouched — that's Phase B/C by design, not an oversight here.
- No CodeQL/SAST — deferred per the original plan's cost/team-size reasoning, not part of this
  phase's ask.

## 17. Phase B Readiness

**Mechanically ready:** the CI foundation (backend static+test gates, frontend static+test+build
gates, secret scanning, dependency scanning, artifacts, reporting) now exists, is internally
consistent, and has been verified as thoroughly as possible without a push.

**Not yet ready, and blocking in practice:** the workflow has never executed on GitHub Actions
itself. Before Phase B (Docker image CI, which builds directly on top of this same workflow file)
starts, this file should actually run there at least once — which needs either (a) the 27-commit
Phase-0 push to go ahead, or (b) a separate feature branch pushed and a PR opened just to exercise
CI, without touching `main`. Both require your explicit go-ahead, not mine.

---

```text
PHASE A STATUS

CI:
NOT YET RUN ON GITHUB ACTIONS (verified locally instead — see §15)

Backend:
PASS (1,747 tests: 708 unit + 1,039 integration+security, 0 failed, 0 errors; mypy/import-linter/ruff
clean on all committed code — ruff findings exist only in one pre-existing uncommitted file)

Frontend:
PASS (TypeScript clean; Vitest 399/399; production build succeeds)

Static analysis:
PASS

Security scanning:
PASS (Gitleaks, 0 leaks, verified against a simulated clean checkout)

Dependency scanning:
FINDINGS, NON-BLOCKING BY POLICY (Python: 0 vulnerabilities. Frontend: 8 vulnerabilities against
Next.js 14.2.28 — 1 critical, 5 high, 2 moderate — remediation is a major-version upgrade, flagged
as a human decision, not fixed in this phase)

GitHub Actions:
NOT YET RUN — nothing has been pushed; requires your explicit go-ahead per the git rules for this
task

Known flaky tests:
Not reproduced this run (the previously-known "structlog capture" flake did not appear; flagged as
"not reproduced," not "fixed," since nothing was changed to specifically address it)

Remaining issues:
(1) CI has never actually executed on GitHub Actions — needs a push or a throwaway branch/PR to
verify for real, pending your decision. (2) ESLint backlog: 7 pre-existing findings, not fixed, by
design. (3) Next.js has 8 known vulnerabilities (1 critical) — needs a dedicated major-version
upgrade, out of this phase's scope. (4) `run_full_tests.py` doesn't yet run ESLint (new local/CI
asymmetry). (5) Docker/compose validation (CI-02) remains completely untouched, as intended for
this phase.

Phase B readiness:
NOT READY — mechanically complete, but gated on actually seeing this workflow run successfully on
GitHub Actions at least once, which requires a push or PR that only you can authorize.
```
