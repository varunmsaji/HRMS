# Release Hardening — Phase 6A: DB-01 Remediation & REPO-01 Closure

**DATE:** 2026-09-25
**SCOPE:** Narrow, targeted remediation of the two blockers Phase 6
(`docs/audits/RELEASE_HARDENING_PHASE_6_DEPLOYMENT_READINESS.md`) identified as blocking —
**REPO-01** (entire release-hardening body of work uncommitted) and **DB-01** (production Postgres
role provisioning hardcoded a repo-visible password). No broad re-audit was performed, no
redesign, no unrelated hardening or improvements. This report documents only that remediation and
its verification.

**COMMIT:** `6f899d394dfaa29e655502c1d072cfd63803f2f3` (branch `main`, 26 commits ahead of
`origin/main`, **not pushed** — see §"REPO-01" below).

## Executive Result

| Item | Status |
| --- | --- |
| **DB-01** | **FIXED and verified live** — `hrms_app`'s password now comes from a required, no-default `HRMS_APP_PASSWORD` environment variable; production fails closed if it's unset |
| **REPO-01** | **FIXED** — the full working tree (142 files, the DB-01 fix included) is committed to `main` in one commit; **not pushed**, per standing project rule (push only on explicit request) |
| Backend tests | 1,746 passed, 1 failed (confirmed pre-existing flake, passes in isolation) — see delta explanation below |
| Backend static analysis | ruff check, ruff format --check, mypy, import-linter — all clean |
| Frontend tests | 399 passed, 0 failed (unchanged from Phase 6 baseline) |
| Frontend typecheck / build | `tsc --noEmit` clean; `next build` succeeds, 48 pages |
| Docker | All 8 services (postgres, redis, minio, api, worker, beat, web, nginx + certbot) built and booted healthy; verified end-to-end via HTTPS through nginx |
| Git | Clean working tree except 4 pre-existing, unrelated untracked files (Finding REPO-02, unchanged, explicitly not touched) |

**Final classification:** **REMEDIATION COMPLETE — READY FOR FINAL GO-LIVE GATE** (for the two
named blockers only — see "Remaining Deployment Blockers" below for everything Phase 6 already
correctly scoped out of this gate).

---

## DB-01

### Root cause

`infra/docker/postgres/init/002_app_role.sql` (a Postgres `docker-entrypoint-initdb.d` script,
mounted identically into every environment's Postgres container by both `docker-compose.yml` and
`docker-compose.prod.yml`) provisioned the application's own runtime role like this:

```sql
CREATE ROLE hrms_app LOGIN PASSWORD 'hrms_app_dev_password' ...
```

The password was a fixed, repository-visible literal, entirely independent of whatever the
operator generated and put in `apps/api/env/.env.production`'s `DATABASE_URL`. Following the
documented runbook exactly (generate secrets with `openssl rand`) produced a database
authentication failure and a crash-looping `api` container on first boot; using the SQL file's own
literal password instead (the most plausible workaround a first-time operator would find) produced
a working deployment whose actual application database role authenticated with a password
published in the git repository.

### Files changed

- **`infra/docker/postgres/init/002_app_role.sql` → `002_app_role.sh`** (renamed, executable):
  same idempotent `CREATE ROLE ... IF NOT EXISTS` / `GRANT` / `ALTER DEFAULT PRIVILEGES` logic,
  now reading the password from `$HRMS_APP_PASSWORD` (`: "${HRMS_APP_PASSWORD:?...}"` — fails
  immediately, with a clear message, if unset) instead of a literal. No SQL schema change, no RLS
  change, no change to what the role is granted.
- **`docker-compose.prod.yml`**: `postgres` service now requires
  `HRMS_APP_PASSWORD: ${HRMS_APP_PASSWORD:?HRMS_APP_PASSWORD is required}` — no default, so the
  stack refuses to start at all if it's missing (verified — see below).
- **`docker-compose.yml`** (dev): `postgres` service sets
  `HRMS_APP_PASSWORD: hrms_app_dev_password` — the same fixed, repo-visible value as before,
  intentionally kept for local dev (matches `tests/security/test_rls_runtime_role.py`'s hardcoded
  connection string; not a secret, nothing but a throwaway local container ever uses it).
- **`.github/workflows/ci.yml`**: the step that manually applies
  `infra/docker/postgres/init/*.sql` (CI service containers don't run
  `docker-entrypoint-initdb.d`) now also applies `*.sh` scripts, with `HRMS_APP_PASSWORD` and
  `PGHOST`/`PGPORT`/`PGPASSWORD` set in the step's environment (the script calls `psql` itself
  without `-h`/`-p`).
- **`.env.prod.example`** and **`apps/api/env/.env.production.example`**: added
  `HRMS_APP_PASSWORD` (compose-level) and rewrote the previously-misleading comment on
  `DATABASE_URL` — it was written as if the password segment should match `POSTGRES_PASSWORD`,
  which is a different role's password entirely. Now explicit: `POSTGRES_PASSWORD` (role `hrms`,
  `MIGRATIONS_DATABASE_URL`) and `HRMS_APP_PASSWORD` (role `hrms_app`, `DATABASE_URL`) are two
  separate values.
- **`docs/deployment/PRODUCTION_DEPLOYMENT.md`**: §3/§4 updated for the new variable; new §6
  subsection "Rotating the `hrms_app` database password" (existing-volume operator procedure,
  see below); new §17 failure-case entry documenting the exact `InvalidPasswordError` symptom and
  its fix.
- **`apps/api/tests/security/test_db01_credential_provisioning.py`** (new, 6 tests): regression
  coverage — asserts `docker-compose.prod.yml` requires `HRMS_APP_PASSWORD` with no default and no
  hardcoded literal, asserts the dev compose keeps its fixed value, asserts the init script
  contains no hardcoded password and does contain the fail-closed shell idiom, asserts the old
  `.sql` file is gone, asserts CI applies `.sh` init scripts. All file/config assertions — no
  database needed, so they run in every CI invocation, including the ones that never build Docker
  images.

### New credential flow

```
operator generates two separate values (openssl rand -base64 32)
  → HRMS_APP_PASSWORD in repo-root .env (docker-compose.prod.yml)
  → same value in apps/api/env/.env.production's DATABASE_URL
        ↓                                              ↓
  postgres container init (fresh volume only):    api/worker/beat/migrate containers:
  002_app_role.sh creates hrms_app with            connect as hrms_app using DATABASE_URL
  this password, fails closed if unset             (or as hrms via MIGRATIONS_DATABASE_URL,
                                                     using the separate POSTGRES_PASSWORD)
```

`POSTGRES_PASSWORD` (schema-owner `hrms`) and `HRMS_APP_PASSWORD` (runtime role `hrms_app`) are
two independent values for two roles with different privileges — the fix does not conflate them,
and the runbook now says so explicitly (a request requirement: "PostgreSQL and API must use the
same configured credential" — satisfied for the `hrms_app`/`DATABASE_URL` pair specifically, which
is the pair DB-01 was actually about).

### Fresh-volume verification (live, this session)

A disposable, non-default production-config stack was built and run, then fully torn down
(containers, volumes, scratch `.env`/`.env.production` files) — nothing committed or left running.
Two independent passes:

**Pass 1 — DB-01-focused (postgres/redis/minio/api/worker/beat only):**
1. Generated fresh, deliberately non-default secrets for `POSTGRES_PASSWORD`, `HRMS_APP_PASSWORD`,
   `MINIO_ROOT_PASSWORD`, JWT secrets, `PII_MASTER_KEY` (`openssl rand`).
2. `docker-compose -f docker-compose.prod.yml build api web migrate worker beat` — succeeded.
3. Started `postgres`/`redis`/`minio`/`minio-init` against a **brand-new** named volume — all
   `healthy`. Postgres init log confirms `running /docker-entrypoint-initdb.d/002_app_role.sh`
   followed by `DO` / `GRANT` / `GRANT` / `GRANT` / `ALTER DEFAULT PRIVILEGES`, no errors, **no
   password anywhere in the log output**.
4. `docker-compose --profile tools run --rm migrate` — clean, reached head
   (`20261004112000`), authenticating as `hrms` via `MIGRATIONS_DATABASE_URL`.
5. `provision_encryption_key.py` — succeeded, authenticating as `hrms_app` via `DATABASE_URL`
   (the exact connection Finding DB-01 originally broke).
6. Started `api`/`worker`/`beat` — all reported `healthy`. `/health/ready` (queried from inside the
   `api` container): `{"ready":true,"database":"ok","redis":"ok","storage_configured":true}`.
7. **Authenticated, DB-writing API request**: `POST /v1/companies/register` → `201 Created`,
   returned a real `company_id` — a genuine write through `hrms_app` across `company`/`user`/
   `user_company`/`employee` tables, not just a read.
8. **Restarted `api`** — came back `healthy`, reconnected with the same credentials.
9. **Restarted `postgres`** — came back `healthy` (existing volume, so `002_app_role.sh` correctly
   did **not** re-run — see "Existing-volume semantics" below).
10. **Verified persistence**: `/health/ready` still `ok` after both restarts; `POST /v1/auth/login`
    for the account created in step 7 returned `403 EMAIL_NOT_VERIFIED` (the correct,
    pre-existing gate — not a DB error) — proving the row written before both restarts was read
    back correctly by `hrms_app`, i.e. both the role and the data survived intact.
11. **Negative control**: with `HRMS_APP_PASSWORD` unset, `docker-compose -f docker-compose.prod.yml
    config` fails immediately with `required variable HRMS_APP_PASSWORD is missing a value:
    HRMS_APP_PASSWORD is required` (exit code 1) — confirms the "fail clearly if missing"
    requirement, before any container even starts.
12. Full teardown: `docker-compose down -v`, scratch `.env`/`.env.production` deleted.

**Pass 2 — full 8-service stack (Docker verification for Part 3, below)** — repeated steps 1–6
above with a second, independently-generated set of non-default secrets, then additionally started
`web`, and `nginx`/`certbot` fronted by a self-signed certificate (no public domain is available in
this environment — real Let's Encrypt issuance remains `ENVIRONMENT-BLOCKED`, unchanged from
Phase 6 §14; this is the same "self-signed substitute" approach Phase 3B used). `curl` through
nginx over HTTPS: `GET /health/live` (Host: api domain) → `200 {"status":"ok"}`; `GET /` (Host: web
domain) → `200`; plain HTTP → `301` redirect to HTTPS. Full teardown afterward, including the
scratch self-signed-cert volume.

Both passes ran against the **current working tree as committed** (see REPO-01 below), not a
hand-picked subset.

### Existing-volume semantics (not implied to auto-rotate)

`002_app_role.sh`, like every `docker-entrypoint-initdb.d` script, only executes on a **fresh**
data volume (first-ever start against an empty `$PGDATA`). Changing `HRMS_APP_PASSWORD` in `.env`
later and restarting `postgres` does **nothing** to an already-initialized volume — this was
verified implicitly by step 9 above (the restart did not re-run the init script; the pre-existing
password kept working). `docs/deployment/PRODUCTION_DEPLOYMENT.md` now documents this explicitly
in §6, plus a separate, explicit operator procedure ("Rotating the `hrms_app` database password")
for changing the password on an existing production database: generate the new value, apply it to
the live role with `ALTER ROLE hrms_app PASSWORD '...'` authenticated as the schema-owner `hrms`,
then update `apps/api/env/.env.production` and recreate `api`/`worker`/`beat`. The runbook
explicitly warns never to recreate the `postgres_data` volume to "apply" a rotation — that
discards the production database. This procedure was documented, not live-executed against a real
production dataset this session (there is no real production data to rotate against); the
mechanism itself (`ALTER ROLE ... PASSWORD`) is standard, unconditional Postgres behavior, not new
code this fix introduces.

### Security implications

No hardcoded password remains in the repository for any environment that matters (dev's fixed
value is not a secret — see above, and is asserted as intentional by
`test_dev_compose_still_sets_the_fixed_dev_only_password`). No fallback default exists in
production's compose file — a missing value is a hard failure, not a silent weak default. No
secret is embedded in SQL source — the SQL file itself is gone; the shell script never writes the
password to a file, only pipes it to `psql` via a heredoc in the same process. No change was made
to RLS policies, tenant isolation, application authorization, or the database schema — this is
purely a credential-provisioning fix, confirmed by the diff touching only
`infra/docker/postgres/init/`, the two compose files' `postgres`/environment blocks, env-file
examples, CI, docs, and the new test file.

---

## REPO-01

### Previous repository state

Per Phase 6 (§3): `main` at `fb94e255b629e3dbf55f3404871ba899919fe322`, 25 commits ahead of
`origin/main`, with a 99-file / ~2,200-line uncommitted working-tree diff plus ~30 untracked new
files — including the entire crypto/master-key rewrite, `SecurityHeadersMiddleware`, SMTP email
sending, email verification, all production Docker/Nginx/backup infrastructure, and all six prior
phase audit reports. None of it existed on `origin/main`.

### Files included

All of the above, **plus** this session's DB-01 fix (`infra/docker/postgres/init/002_app_role.sh`,
both compose files, `ci.yml`, the two env-example files, the deployment runbook, the new regression
test file) — 142 files total, committed as a single commit
(`6f899d394dfaa29e655502c1d072cfd63803f2f3`, `feat(release-hardening): phases 0-6A — security,
production infra, DB-01 fix`). Full file list is in the commit itself (`git show --stat`).

### Files intentionally excluded

Per Phase 6 Finding REPO-02 and this session's own re-verification (`git status --porcelain -uall`
before staging, secret-pattern grep across the full staged diff after staging — no real secrets
found, only test fixtures, placeholder text, and a shell-variable name in this report's own new
doc text):

- `mavericks-kit.zip`, `shirt.png`, `shorts.png` — unrelated personal files, repo root, not
  gitignored, not staged.
- `work done/PRODUCTION_HARDENING_IMPLEMENTATION_STATUS_2026-09-21_09-00-27.md` — an older,
  duplicate status report unrelated to this repository's own tracked docs.
- No `.env`, credentials, private keys, certificates, database dumps, or generated artifacts were
  present as untracked files at all (confirmed via `git status --porcelain --ignored -uall`); the
  real `apps/api/.env` is confirmed gitignored and was never staged.

These four items remain untracked and unmodified after the commit — confirmed by
`git status --porcelain -uall` showing only them, post-commit.

### Commit hash

`6f899d394dfaa29e655502c1d072cfd63803f2f3` on `main`.

### origin/main state / push status

`git rev-list --left-right --count origin/main...HEAD` → `0  26`: **0 commits behind, 26 commits
ahead** (the 25 pre-existing unpushed commits plus this session's one release-hardening commit).
**Nothing was pushed** — per the standing project rule (push only on explicit request) and this
task's own explicit instruction. `origin/main` is unchanged from before this session.

---

## Tests / Static Analysis

### Backend

Full suite run against a **genuinely fresh, single-purpose scratch Postgres container** (isolated
from the shared dev database and from the user's running dev stack — a separate, temporary
container on a separate port, migrated from empty to head via the current, committed
`002_app_role.sh`, then deleted afterward; the long-running dev `hrms-postgres`/`hrms-redis`/
`hrms-minio` containers were never stopped or touched):

```
1,746 passed, 1 failed in 339.81s
```

The one failure, `tests/unit/modules/onboarding/test_email_sender.py::
test_smtp_send_failure_does_not_log_the_email_body`, is the **exact same flake Phase 6 itself
already documented and root-caused** — a structlog test-capture-fixture timing issue specific to
full-suite execution order, not a real defect. This session's own full-suite run shows the same
signature: the captured stdout in the full run contains the correct, properly-redacted log line
(`{"to": "alice@example.com", ..., "event": "onboarding_email_smtp_send_failed", ...}`, no token
leak), but the test's own log-capture assertion saw zero entries. Re-run in isolation immediately
after: **1 passed**. The actual security property under test (no token/body leak into logs) held
in both runs.

**Delta from Phase 6's own stated fresh-DB baseline** (1,740 passed, 1 failed = 1,741 total; this
task's brief separately states "approximately 1,741 passed" as the expected baseline): this
session's total is 1,747 (1,746 + 1 flake), **+6** over baseline. The delta is fully accounted for
by the 6 new, legitimate DB-01 regression tests added in
`tests/security/test_db01_credential_provisioning.py` (all 6 passed in every run). No other test
was added, removed, or changed in a way that affects the count. **Net conclusion: zero regressions
— every prior test that passed on Phase 6's baseline still passes; the only change is 6 new tests
covering DB-01's own fix.**

Static analysis, run against the full `apps/api` tree as committed:

| Check | Result |
| --- | --- |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 465 files already formatted |
| `mypy src/hrms` | Success: no issues found in 167 source files |
| `lint-imports` | Analyzed 140 files, 343 dependencies — 1 kept, 0 broken |

(Note: this session used `apps/api/.venv/bin/python -m ...` directly rather than `uv run ...` —
`uv run` resolves to an unrelated, broken interpreter in this specific environment, a pre-existing
local quirk unrelated to this task; CI itself uses `uv run` inside a clean CI runner, where this
does not apply.)

### Frontend

| Check | Result |
| --- | --- |
| `npx tsc --noEmit` | 0 errors |
| `npm test -- --run` (vitest) | **399 passed**, 0 failed, 56 test files — unchanged from Phase 6 |
| `npm run build` (`next build`) | Succeeds, 48 pages compiled/prerendered |
| `npm run lint` | Still hangs on the interactive ESLint-setup prompt (Finding FE-01/CI-01, pre-existing, out of this task's scope — not touched) |

No frontend source file was changed by this session's work (DB-01 is a backend/infra/docs fix
only); the frontend numbers are Phase 6's own, re-confirmed unchanged.

---

## Docker

All production images build from the current, committed working tree; the full 8-service stack
(`postgres`, `redis`, `minio`, `api`, `worker`, `beat`, `web`, `nginx` + `certbot`) was started
together (Pass 2 above) against a fresh, non-default-credentialed volume set and verified healthy,
including a real HTTPS round-trip through nginx to both the API and the web app. Everything was
torn down afterward (`docker-compose down -v` plus the scratch self-signed-cert volume) — nothing
was left running beyond the user's own pre-existing dev stack, which this session never stopped or
modified.

Real Let's Encrypt certificate issuance remains `ENVIRONMENT-BLOCKED` (no public domain available
in this environment) — unchanged from Phase 6 §14; this session used a self-signed certificate
only to prove nginx's routing/proxy configuration itself works, consistent with Phase 3B's own
prior precedent for the same constraint.

---

## Regression Checks (areas potentially affected by DB-01)

All exercised via the full backend suite (1,746/1,747 passed, see above) run against a database
provisioned entirely through the fixed `002_app_role.sh`, plus the live Docker verification above:

| Area | Result |
| --- | --- |
| Database initialization | `VERIFIED` live — fresh-volume boot, both passes, clean init logs, no errors, no leaked password |
| Database connection | `VERIFIED` — `hrms_app`/`DATABASE_URL` and `hrms`/`MIGRATIONS_DATABASE_URL` both connect correctly; full test suite (which exercises both roles) passes |
| Migrations | `VERIFIED` — clean to head, twice (once per live pass), plus the scratch DB used for the full test run |
| Authentication | `VERIFIED` — `tests/integration/auth/*` all pass; live `POST /v1/companies/register` (201) and `POST /v1/auth/login` (correct 403 `EMAIL_NOT_VERIFIED`) both exercised against the fixed stack |
| Company creation | `VERIFIED` — `tests/integration/modules/organisation/test_registration_flow.py` passes; live registration succeeded |
| Tenant isolation / RLS | `VERIFIED` — `tests/security/test_rls_runtime_role.py` passes unchanged (this file's own cross-tenant DB-level assertions are exactly what would break first if `hrms_app`'s grants/role attributes had regressed) |
| Employee creation | `VERIFIED` — `tests/integration/modules/employee/*` pass |
| Attendance | `VERIFIED` — `tests/integration/modules/attendance/*` pass |
| Leave | `VERIFIED` — `tests/integration/modules/leave/*` pass |
| Payroll | `VERIFIED` — payroll-related unit/integration tests within the full suite pass (no payroll code was touched by this fix) |
| Document storage | `VERIFIED` — `tests/unit/core/test_storage.py`, `tests/integration/modules/onboarding/test_onboarding_documents.py` pass; live stack's `minio`/`minio-init` healthy in both passes |
| Worker | `VERIFIED` live — `worker` container healthy in both passes (`celery inspect ping`) |
| Beat | `VERIFIED` live — `beat` container up, no crash, in both passes |
| Backup/restore | **Not re-executed live** — `infra/backup/{pg,minio}_{backup,restore}.sh` reference only `POSTGRES_USER`/`POSTGRES_PASSWORD` (the `hrms` schema-owner role); confirmed by grep that neither script references `hrms_app` or `HRMS_APP_PASSWORD` at all — **zero code-path overlap** with the DB-01 fix, so no regression risk exists here for this specific change. Not re-run live this session (matches Phase 6's own decision on this item, for an unrelated reason there — session time budget). |

**Conclusion**: no regression found in any area with actual code-path overlap with the DB-01 fix.

---

## Remaining Deployment Blockers

Compared directly against Phase 6 §25 — no new blockers invented, none of Phase 6's non-REPO-01/
non-DB-01 items were touched or re-litigated:

**MUST FIX BEFORE DEPLOYMENT** (Phase 6's list): REPO-01 ✅ closed; DB-01 ✅ closed;
**CI-02** (add a CI job that builds Docker images and boots the compose stack) — **still open**,
unchanged, correctly out of this task's narrow scope (this session did that verification by hand,
exactly the manual work CI-02 would automate, but did not add the CI job itself, since that would
be new hardening work beyond "fix DB-01 → verify → commit").

**MUST COMPLETE BEFORE REAL EMPLOYEE/PII DATA** — all four items unchanged, still open
(`PII_MASTER_KEY` off-VPS custody, off-VPS backup destination, privacy notice, statutory rate
verification) — none are code gaps, all correctly deferred as Phase 4/6 already classified them.

**ENVIRONMENT-BLOCKED** — unchanged: real Let's Encrypt issuance (no public domain), real SMTP
delivery (no live mailbox).

**POST-PILOT / PUBLIC RELEASE** — unchanged (MFA, malware scanning, rate-limit topology, payroll
5.7, full DPDP compliance program, recruitment module, frontend lint gate / VPS hardening docs).

---

## Final Classification

**REMEDIATION COMPLETE — READY FOR FINAL GO-LIVE GATE**

Both blockers named in this task (REPO-01, DB-01) are fixed, live-verified against a fresh
production-config Docker stack (twice, independently), and safely committed to `main` without
being pushed. The system's own prior classification from Phase 6 (§27) — **PILOT READY WITH
CONDITIONS**, once REPO-01 and DB-01 close — is now accurate again, subject to the unchanged,
correctly-scoped-out items above (Phase 6's own "MUST COMPLETE BEFORE REAL EMPLOYEE/PII DATA" and
"ENVIRONMENT-BLOCKED" lists), none of which are code gaps and none of which this task was asked to
close.
