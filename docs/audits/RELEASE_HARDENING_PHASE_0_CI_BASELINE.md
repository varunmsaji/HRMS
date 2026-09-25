# Release Hardening — Phase 0: Safety Snapshot and CI Baseline

Date: 2026-09-25

## Executive Summary

```text
Current release status:
NOT READY FOR PUBLIC RELEASE
```

This phase is diagnostic only. No source code, tests, or CI configuration were
modified. A recoverable GitHub snapshot of the current `main` was created and
pushed. The actual CI-equivalent checks were reproduced locally and their
failures are recorded below, classified by cause.

No single document in `docs/audits/` was found containing the exact figures
quoted in this phase's brief (1,660/384 test counts, 21 ruff errors, 41
files needing formatting, the specific mypy line numbers). The closest
existing documents — `PRODUCTION_HARDENING_CONSOLIDATION_AUDIT.md` and
`PRODUCTION_HARDENING_IMPLEMENTATION_STATUS.md` — confirm SEC-07/SEC-08 as
`OPEN` but don't carry those counts. Per the brief's own instruction to
verify rather than trust cited numbers: **every count below was independently
reproduced against the current tree today**, and all of them match what the
brief described.

## Git State

| Item | Value |
| --- | --- |
| Branch | `main` |
| HEAD | `fb94e25` — `feat(payroll): income tax (TDS) — new regime only (phase 5.6)` |
| Remote | `origin` → `https://github.com/varunmsaji/HRMS.git` |
| Ahead / behind `origin/main` | 25 ahead / 0 behind |
| Uncommitted tracked changes | none |
| Untracked files | `mavericks-kit.zip`, `shirt.png`, `shorts.png`, `work done/` — unrelated to the repo, excluded from every operation this phase |

## Safety Snapshot

- Created local branch `release-readiness-baseline-2026-09-25` at `fb94e25` (current `main` HEAD).
- Pushed it to `origin` — **succeeded**, no credential prompt needed:
  `remotes/origin/release-readiness-baseline-2026-09-25` now exists on GitHub.
- `main` itself was **not** pushed and remains 25 commits ahead of `origin/main` — this phase only adds a new branch ref, it does not touch `origin/main`.
- No history rewritten, no force-push, no branch deleted.
- **Rollback reference:** `git reset --hard release-readiness-baseline-2026-09-25` (or `origin/release-readiness-baseline-2026-09-25`) recovers exactly this state from anywhere, including a fresh clone.

## CI Commands

Taken verbatim from `.github/workflows/ci.yml` (single workflow file, two jobs: `api`, `web`).

### Backend (`apps/api`, `TZ=UTC`)

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/hrms
uv run lint-imports
# services: postgres:16-alpine on 5433, redis:7-alpine on 6380
# apply infra/docker/postgres/init/*.sql, then:
uv run alembic upgrade head
uv run pytest tests/unit
uv run pytest tests/integration tests/security
```

Locally, `uv run` resolves to a broken interpreter in this environment (a
stale shebang pointing at a `varun8` path that doesn't exist here — see repo
memory), so every command was run via `apps/api/.venv/bin/python -m <tool>`
instead. This is a local execution-environment workaround, not a change to
what CI itself runs.

### Frontend (`apps/web`, `TZ=America/New_York`)

```bash
npx tsc --noEmit
npm test          # vitest run
```

CI deliberately does **not** run `next lint` (no ESLint config or dependency
installed — confirmed: `node_modules/.bin/eslint` absent, `next lint` would
hang on an interactive prompt) and does **not** run a production build. Both
are documented gaps in the workflow's own comments. Per this phase's brief
(which asks to verify "production build succeeds"), `npm run build` was run
locally as an out-of-band check beyond what CI actually gates.

## Results

| Check | Result | Failure Count | Classification |
| --- | --- | ---: | --- |
| Ruff lint (`ruff check .`) | FAIL | 21 | FORMAT/LINT FAILURE |
| Ruff format (`ruff format --check .`) | FAIL | 41 files | FORMAT/LINT FAILURE |
| Mypy (`mypy src/hrms`) | FAIL | 3 | TYPE FAILURE |
| Import boundaries (`lint-imports`) | FAIL | 1 contract | CODE FAILURE |
| Backend unit tests | PASS | 0 | — |
| Backend integration + security tests | FAIL | 1 failed + 22 errors | 1 TEST FAILURE (pre-existing), 22 STALE DATABASE STATE |
| Frontend typecheck (`tsc --noEmit`) | PASS | 0 | — |
| Frontend tests (`vitest`) | FAIL | 4 | TEST FAILURE (pre-existing) |
| Frontend production build (`npm run build`) | PASS | 0 | — |
| Frontend lint | N/A | — | CI CONFIGURATION GAP (no ESLint set up; not gated) |

## Backend Tests

- **Unit** (`pytest tests/unit`): **674 passed**, 0 failed.
- **Integration + security** (`pytest tests/integration tests/security`): **986 passed**, **1 failed**, **22 errors**, in 324s.
- **Combined passed total: 674 + 986 = 1,660** — matches the brief's cited figure exactly.

### The 1 failure

`tests/integration/modules/account_invite/test_account_invite.py::test_invite_employee_accept_and_login_success`

Fails on a hardcoded expected-permission-set assertion that is missing perms
added by later work (`EMPLOYEE.VIEW_EXPERIENCE`, `EMPLOYEE.VIEW_NOMINEE`,
`EMPLOYEE.VIEW_SENSITIVE`, `PAYROLL.PAYSLIP_VIEW_OWN`). This is a known,
pre-existing stale test expectation (tracked in repo memory since
2026-09-23, predates this phase and the payroll work). **Classification:
TEST FAILURE**, not a regression — the test's fixture set was never updated
when those view-permissions were introduced.

### The 22 errors

All 22 are `IntegrityError: ForeignKeyViolationError` on `DELETE FROM "user"`
during test teardown/fixture setup, blocked by leftover `onboarding_case`
rows still referencing the fixed test user id
`aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa`. Verified directly against the
database:

```sql
SELECT id, created_by_user_id, status, created_at FROM onboarding_case
WHERE created_by_user_id IN ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');
```

Returned 8 rows dated 2026-09-21 through 2026-09-23 — days before this
session — each an artifact of earlier test runs against the shared
`hrms_dev` database using a fixed, non-randomized test user UUID. **CI runs
against a fresh `postgres:16-alpine` container per run and would not
accumulate this state** — this is purely a symptom of tests sharing a
persistent local dev database across sessions. **Classification: STALE
DATABASE STATE / ENVIRONMENT FAILURE**, not a code defect. No application
behavior was changed to make these disappear, per instruction.

## Frontend Tests

- **Vitest**: **384 passed**, 4 failed, 1 test file failing — `src/app/app/branches/page.test.tsx` (a legal-entity-selection validation-message assertion timing out via `findByText`). Matches the pre-existing baseline already on record in repo memory (unchanged before this payroll work started). **Classification: TEST FAILURE (pre-existing, not a regression)**.
- **Typecheck**: clean, exit 0.
- **Production build**: succeeds, exit 0. Not part of CI's own gate (see CI Configuration Failure below).
- **Lint**: not applicable — no ESLint dependency or config present in `apps/web`.

## Database State

The dev database (`hrms_dev` on `localhost:5433`) is a long-lived, shared
instance reused across many prior sessions, not a fresh CI-style container.
The 22 test errors were confirmed by direct SQL query to originate from 8
`onboarding_case` rows created 2026-09-21 to 2026-09-23 by fixture code that
uses a fixed (non-random) test user UUID, which a fresh database would never
contain. CI's `postgres:16-alpine` service container starts empty on every
run, so **these 22 errors would not reproduce in actual CI** — they are an
artifact of this specific local dev database's accumulated history, not of
the code under test. No application logic was altered to hide or work around
this.

## Known Baseline Problems

1. **Ruff lint — 21 `E501` (line too long) errors.** 17 in Alembic migration files (`alembic/versions/*.py`), 4 in application source (`employee/repository.py:1071`, `employee/schemas.py:716,739`, `onboarding/service.py:506`). All are the same rule; no other lint categories present.
2. **Ruff format — 41 files would be reformatted**, 411 already compliant. Per existing repo guidance, these must never be bulk-reformatted (`ruff format .` on the whole tree would rewrite unrelated pre-existing files) — only files actually touched by future work should be reformatted.
3. **Mypy — 3 errors in 2 files:**
   - `src/hrms/modules/employee/repository.py:1077` — `float(...)` called on a `float | None`-typed value.
   - `src/hrms/modules/employee/repository.py:1090` — same pattern, second occurrence (matches the brief's cited line exactly).
   - `src/hrms/modules/onboarding/schemas.py:674` — `token_status: str | None` passed where `Literal["ACTIVE","EXPIRED","REVOKED"] | None` is expected (matches the brief's cited line exactly).
4. **Import boundary — 1 broken contract.** `hrms.core.crypto.backfill` imports `hrms.modules.employee.models` (line 34) and `hrms.modules.onboarding.models` (line 35), violating the "core depends on shared and core only" contract enforced by `lint-imports`.
5. **1 known-stale integration test** (`test_invite_employee_accept_and_login_success`) — hardcoded permission-set assertion not updated for perms added since 2026-09-23.
6. **22 dev-DB-only test errors** — stale `onboarding_case` rows in the shared local `hrms_dev` database; does not reproduce against a clean database / real CI.
7. **4 known-stale frontend tests** in `branches/page.test.tsx` — pre-existing baseline, unrelated to any work in this phase.
8. **CI configuration gap** — no ESLint is configured for `apps/web`, and CI runs no production build step at all. Both are pre-existing, documented directly in the workflow file's own comments, not something this phase introduced or is fixing.

## Not Addressed

```text
SEC-07 — not addressed
SEC-08 — not addressed
KMS credentials — not addressed
Email provider — not addressed
Docker — not addressed
Nginx/HTTPS — not addressed
Backups — not addressed
Observability — not addressed
Other release blockers — not addressed
```

## Next Phase

The next implementation phase should be:

```text
CI remediation
```

Recommended order within that phase (diagnostic findings only, not yet
scoped or approved): (1) fix the 21 `E501` lint errors and reformat only the
41 flagged files in isolated commits, (2) fix the 3 mypy errors, (3) resolve
the `crypto/backfill` → `modules` import-boundary violation (likely needs an
interface/protocol in `core` rather than importing concrete ORM models),
(4) update the stale `test_invite_employee_accept_and_login_success`
permission fixture, (5) separately decide how to keep the local dev database
clean for test runs (e.g., a teardown/reset script) — this should **not**
be conflated with a code fix. Security remediation (SEC-07, SEC-08, KMS,
etc.) should be scoped and executed as its own, later phase.

Final status:

```text
NOT READY FOR PUBLIC RELEASE
```
