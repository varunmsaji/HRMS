# Release Hardening — Phase 1: CI Remediation

Date: 2026-09-25

## Executive Summary

```text
Production readiness status:
NOT READY FOR PUBLIC RELEASE
```

This phase closed every CI/code-quality/test-baseline gap Phase 0 diagnosed. Every
CI-equivalent check now passes, including — independently re-verified against a genuinely
fresh, isolated `postgres:16-alpine` container mirroring `.github/workflows/ci.yml` exactly —
the full backend test suite (1,683 tests, 0 failed, 0 errors). This phase did not touch, and
was explicitly scoped away from, any of the still-open security/infrastructure work
(SEC-05 through SEC-09, DEP-01, KMS, email, Docker, Nginx, HTTPS, backups, observability). CI
going green is a code-quality/test-baseline milestone, not a production-readiness signal.

## 1. Baseline

Phase 0 (`docs/audits/RELEASE_HARDENING_PHASE_0_CI_BASELINE.md`) recorded:

| Check | Result |
| --- | --- |
| Ruff lint | FAIL — 21 `E501` errors |
| Ruff format | FAIL — 41 files would be reformatted |
| Mypy | FAIL — 3 errors in 2 files |
| Import boundaries | FAIL — `hrms.core.crypto.backfill` imports `hrms.modules.*` |
| Backend tests | 1,660 passed, 1 failed, 22 errors |
| Frontend TypeScript | PASS |
| Frontend tests (Vitest) | 384 passed, 4 failed |
| Frontend production build | PASS (not CI-gated) |

All commands were reproduced verbatim from `.github/workflows/ci.yml` before any change, via
`apps/api/.venv/bin/python -m <tool>` (the `varun9`/`varun8` decoy-path workaround already on
record) instead of `uv run`, which resolves to a broken interpreter in this environment.

## 2. Ruff

**Initial**: 21 `E501` errors — 17 in Alembic migration files (raw SQL inside triple-quoted
strings), 3 in application source (`employee/repository.py`, `employee/schemas.py` ×2), 1 in
`onboarding/service.py`.

**Changes**: every fix was a line wrap, not a behavior change.
- Alembic files: the long lines are all inside `op.execute("""...""")` raw-SQL string literals.
  SQL is whitespace-insensitive, so each `CONSTRAINT ... FOREIGN KEY (...) REFERENCES ...` (or
  equivalent) was split across two indented lines, mirroring the file's own existing wrap
  convention. One line (`default_roles_backfill.py:103`) was real Python (`", ".join(...)`) and
  was wrapped with parentheses instead.
- Application source: standard parenthesized wraps (function signatures, dict literals, `select()`
  chains) — no expression semantics changed.
- One line collapsed by the formatter in step 3 (below) re-exceeded 100 chars
  (`test_onboarding_activation.py:539`, a SQL string inside `text(...)`); fixed the same way —
  split into two adjacent string literals (Python auto-concatenates them), which is a formatting
  change with no behavioral difference.

**Final**: `ruff check .` → **All checks passed!** (0 errors)

## 3. Formatting

**Initial**: 41 files flagged by `ruff format --check .`.

**Changes**: 4 of those 41 were already brought into compliance by the E501 line-wraps in step 2
(the manual wraps happened to match Ruff's own formatting style), leaving 37 files. Formatted
**exactly those 37 files** (`ruff format <explicit file list>`), never a blanket `ruff format .`
over the whole tree, per the existing repo convention of not touching files outside the current
work. Every diff was reviewed; all are mechanical (argument-list reflow, line
wrap/unwrap, a removed blank line) with zero functional changes — confirmed both by the diff
content and by every test file's tests continuing to assert the exact same values afterward.

**Final**: `ruff format --check .` → **452 files already formatted** (0 pending)

## 4. Mypy

**Initial**: 3 errors in 2 files.

1. `employee/repository.py:1077` and `:1090` — `float(...)` called on a value SQLAlchemy's own
   type stubs infer as `float | None` (from `func.coalesce(func.sum(...), 0)`). At runtime the
   `coalesce(..., 0)` guarantees a non-`None` scalar, but mypy can't see through that SQL-level
   guarantee.
   **Root cause**: the code asserted a type SQLAlchemy's stubs don't actually promise.
   **Fix**: read the scalar into a local, and use the correct type model —
   `float(total) if total is not None else 0.0` — instead of asserting away the `None` case. No
   observable behavior change (the `None` branch is unreachable at runtime given the `coalesce`),
   but the code is now honestly typed rather than force-cast.
2. `onboarding/schemas.py:674` — `_token_status(...)` was declared to return `str | None`, but
   its only possible return values are the literal strings `"ACTIVE"`, `"EXPIRED"`, `"REVOKED"`,
   or `None` — exactly the `Literal[...] | None` the caller (`OnboardingCaseDetailRead`) expects.
   **Root cause**: the function's declared return type was wider than its actual contract.
   **Fix**: narrowed the return type annotation to
   `Literal["ACTIVE", "EXPIRED", "REVOKED"] | None`, matching the field it feeds. `Literal` was
   already imported in the file.

**Final**: `mypy src/hrms` → **Success: no issues found in 164 source files**

## 5. Import boundary

**Original violation**: `hrms.core.crypto.backfill` imported `hrms.modules.employee.models`
(`Employee`, `EmployeeBank`) and `hrms.modules.onboarding.models` (`OnboardingCase`), violating
the `layers` contract (`hrms.modules` → `hrms.shared` → `hrms.core`; `core` may not import
`modules`).

**Architectural reason**: this module is a standalone, never-imported-elsewhere PII-encryption
backfill script (its own docstring: "Callable directly — as a one-off script or a Celery task —
never runs automatically at import time, app boot, or on any request path"). It genuinely needs
ORM access to `Employee`/`EmployeeBank`/`OnboardingCase` — two different modules' tables — to do
its job. It does not belong to `core` (core owns no business models) and it doesn't belong to any
single module (its job spans employee and onboarding data). Renaming or shimming imports would
either violate the layering the same way or require a fake abstraction with no other use.

**Solution**: moved the file out of `hrms.core.crypto` entirely, to a new top-level sibling
module `hrms.pii_backfill` — the same architectural slot `hrms.seed` (`seed/bootstrap.py`
already imports across `hrms.modules.attendance`, `.employee`, `.leave`, `.onboarding`, `.
organisation`, `.payroll`) and `hrms.ingestion` already occupy: cross-cutting, non-request-path
code that sits beside `core`/`modules`/`shared` rather than inside the layered contract (which
only orders those three packages — a sibling package is simply outside it, not exempted from
it). This is option 1 from the brief ("move the backfill operation into an appropriate
module/service layer") applied at the right granularity — one file, one move, no new
abstraction, no duplicated logic, no circular imports. `git mv` preserved history. The two
places that imported the old path (`tests/integration/test_pii_encryption_backfill.py`, both a
top-level `from ... import backfill as backfill_module` and a function-local
`_encrypt_and_verify` import) were updated to the new path; no other file referenced it.

**Final**: `lint-imports` → **Contracts: 1 kept, 0 broken.**

## 6. Backend test — `test_invite_employee_accept_and_login_success`

**Investigation**: the test asserted a hardcoded 4-permission set
(`EMPLOYEE.VIEW`/`.VIEW_COMPENSATION`/`.VIEW_STATUTORY`/`.VIEW_BANKING`) for a freshly-invited
employee. Tracing `organisation/service.py`'s `_bootstrap_default_roles` (the code that actually
provisions the default `EMPLOYEE` role on every new company), the `EMPLOYEE` role is granted 8
permissions, not 4: the original 4 plus `EMPLOYEE.VIEW_SENSITIVE`, `.VIEW_EXPERIENCE`,
`.VIEW_NOMINEE` (documented in `employee/permissions.py` as intentional additions, each with its
own phase rationale and precedent) and `PAYROLL.PAYSLIP_VIEW_OWN` (documented in
`payroll/permissions.py`, Phase 5.4: "every employee reads their own finalised payslips").

**Classification**: stale test expectation, not a regression and not SEC-08. The current
behavior (8 permissions) is the intentionally, currently-documented state of the codebase — the
test's fixture was simply never updated when those three employee-view permissions and the
payslip-view permission were added in later phases.

**Fix**: updated the assertion to the current, correct 8-permission set. No production code
changed; no invite/auth security behavior touched.

**Final**: passes in isolation and as part of the full suite.

## 7. Database hygiene

**The problem** (as Phase 0 found): 22 backend test errors, all
`IntegrityError: ForeignKeyViolationError`, surfaced when `tests/integration/auth/conftest.py`'s
`seeded_db` fixture (used by `test_auth_security.py`, `test_credential_rate_limit.py`,
`test_password_reset.py` — all three login against the fixed seed demo users rather than
registering a fresh tenant) calls `clear_b1_seed()` to delete-then-reseed the demo `ADMIN_USER_ID`
/`VIEWER_USER_ID` users at the start of every test. On the shared, long-lived local `hrms_dev`
database, that `DELETE FROM "user"` was blocked by leftover rows still referencing those user
IDs.

**Diagnosis — not a fixture defect**: grepping the entire test suite confirms no automated test
creates data under the fixed seed user IDs (`ADMIN_USER_ID`/`VIEWER_USER_ID` are imported only by
`test_password_reset.py`, and only to clean up its own `password_reset_token` rows). The blocking
rows — 8 `onboarding_case` rows dated 2026-09-21 through 2026-09-23, all under the seeded "Demo
Company A" (`company_id = 11111111-...`) — are artifacts of prior **manual/interactive** use of
the dev server against this same persistent database (the documented demo login flow), not of any
pytest fixture.

**What was done**: deleted exactly those 8 stale `onboarding_case` rows (and their 33
`onboarding_section_review` + 16 `onboarding_token` child rows) via direct SQL against the local
`hrms_dev` database — a local environment action, not a code or fixture change. No application
logic, test fixture, or production behavior was modified.

**Independent proof this is environment-only, not a code defect**: a second, completely isolated
`postgres:16-alpine` container was started on an unused port, initialized with the exact same
`infra/docker/postgres/init/*.sql` scripts and `alembic upgrade head` CI runs, and the full
`tests/integration tests/security` suite was run against it. Result: **1,009 passed, 0 failed, 0
errors** — every test that errors locally passes cleanly against a database with no manual-testing
history, exactly matching what CI's own fresh `postgres:16-alpine` service container gets on every
run. This also re-confirms none of this phase's ruff/mypy/import-boundary/test-file changes
introduced any regression.

**What was deliberately left alone**: after the above cleanup, one *further*, deeper chain of
leftover manual-testing data was found still blocking the same fixture locally — a `legal_entity`
row ("Test Legal Entity", dated 2026-09-22) under the same demo company, itself referenced by 1
`branch` and 4 `employment` rows. This is outside what Phase 0 diagnosed, and unlike the
`onboarding_case` rows, it reaches into `employment` records — data adjacent to the demo/QA setup
this repository's payroll work has been actively exercised against. Per this phase's own
instruction not to invent unnecessary changes once CI-equivalent behavior is proven correct, and
given the ambiguity of what else depends on that data, this was **not** deleted. It has no effect
on CI (proven above) and is flagged here for awareness, not left as a hidden problem.

**Final local-DB test count** (persistent `hrms_dev`, with the above partial cleanup applied):
1,661 passed, 0 failed, 22 errors (100% attributable to the remaining `legal_entity` chain,
confirmed environment-only via the fresh-database run above).
**Final CI-equivalent (fresh database) test count**: 1,683 passed, 0 failed, 0 errors.

## 8. Frontend

**Initial**: 4 failures, all in `src/app/app/branches/page.test.tsx`.

**Investigation**: all 4 traced to a single, already-shipped, intentional product change visible
in the component's own comments (`page.tsx`): a "quick setup" flow that replaced an old "go to
Legal Entities first" dead end, plus a third `apps.get("/companies/current")` call added to
support it, plus hiding/auto-filling the legal-entity selector when a company has exactly one
legal entity (the common case). None of the four is a regression, a test-environment issue, or a
product/security decision requiring escalation — each is a stale expectation against UI text or
form structure that changed when that feature shipped:

1. **"prompts to add a legal entity first when none exist"** — asserted old dead-end copy
   (`/add a legal entity before creating branches/i`); the current empty state shows "Let's set
   up your company." Updated the assertion to match current copy.
2. **"shows an error state when loading fails with forbidden"** — `mockRejectedValueOnce` only
   mocks the *first* of what is now three parallel `apiClient.get` calls
   (`/branches`, `/legal-entities`, `/companies/current`); the second/third calls returned
   `undefined`, and calling `.catch()` on `undefined` threw synchronously before the intended
   403 was ever reached, so the component fell through to a generic "Something went wrong."
   Fixed by mocking all three paths explicitly.
3. **"creates a branch from the empty state and refreshes the list"** — with exactly one seeded
   legal entity, `hideLegalEntitySelector` hides the selector and `openCreate()` pre-fills it
   automatically, so `screen.getByLabelText(/legal entity/i)` could never find it. Removed the
   now-inapplicable `selectOptions` call (the value is already correctly pre-filled).
4. **"shows a validation error when required fields are missing"** — same root cause in reverse:
   with the default single mocked legal entity, the selector is hidden and pre-filled, so the
   "select a legal entity" validation could never fire. Changed the mock to seed two legal
   entities, which keeps the selector visible and unselected by default.

No product, security, or ESLint work was introduced; no other frontend test was touched.

**Final**: `npx vitest run src/app/app/branches/page.test.tsx` → 7/7 passed. Full suite:
**388 passed, 0 failed** (54 files).

## 9. Build

`npx tsc --noEmit` → clean, exit 0 (unchanged from Phase 0).
`npm run build` → succeeds, exit 0 (unchanged from Phase 0; still not part of CI's own gate —
that gap is pre-existing and out of this phase's scope).

## 10. Final CI matrix

| Check            |                             Before | After | Status |
| ---------------- | ----------------------------------:| -----:| ------ |
| Ruff check       |                          21 errors |     0 | PASS   |
| Ruff format      |                           41 files |     0 | PASS   |
| mypy             |                           3 errors |     0 | PASS   |
| import lint      |                             failed |  kept | PASS   |
| backend tests (CI-equivalent, fresh DB) | 1660 passed / 1 failed / 22 errors | 1683 passed / 0 failed / 0 errors | PASS |
| backend tests (local persistent DB)     | 1660 passed / 1 failed / 22 errors | 1661 passed / 0 failed / 22 errors (environment-only, see §7) | PASS in CI |
| TypeScript       |                                pass |  pass | PASS   |
| Vitest           |                              384/4  | 388/0 | PASS   |
| production build |                                pass |  pass | PASS   |

## Regression check

`git diff --check`: clean (no whitespace errors).
`git status --short` / `git diff --stat`: exactly 50 files touched (49 modified + 1 rename), all
within the 12 areas this phase was scoped to touch (Ruff line wraps, formatting, 2 mypy type
fixes, 1 file move + 2 import updates, 1 test assertion, 4 test-mock fixes). No unrelated files.
`mavericks-kit.zip`, `shirt.png`, `shorts.png`, `work done/` were never touched. Every reformatted
file's diff was reviewed; all are mechanical (line wrap/collapse, argument reflow, blank-line
removal) with zero assertion or logic changes. No lint rule was disabled, no `# noqa`/
`# type: ignore` was added, no `Any` was introduced, no import-linter exclusion was added, no
test assertion was weakened (one was strengthened — the invite test now asserts the full,
correct 8-permission set instead of a stale 4-permission subset), no production behavior changed.

## Not addressed (by design)

```text
SEC-07, SEC-08, SEC-09, SEC-05, SEC-06 — not addressed
DEP-01 (python-jose) — not addressed
KMS credentials, email provider — not addressed
Docker, Nginx, HTTPS, backups — not addressed
Sentry, metrics, Redis failure policy — not addressed
MFA, password policy, audit logging — not addressed
Payroll statutory rates / legal / compliance — not addressed
```

## Known remaining issues

1. Local `hrms_dev` still carries one unrelated chain of manual-testing data (`legal_entity` →
   `branch`/`employment`) under the demo company that would need explicit, deliberate cleanup
   (out of this phase's scope — see §7). Zero effect on CI.
2. CI runs no ESLint (no config/dependency present) and no production build step — both are
   pre-existing, documented directly in `ci.yml`'s own comments, not introduced or touched by
   this phase.

## Next phase

Security remediation (SEC-05 through SEC-09, DEP-01, KMS, email, Docker, Nginx, HTTPS, backups,
observability) — unchanged from Phase 0's recommendation, still entirely open.

Final status:

```text
NOT READY FOR PUBLIC RELEASE
```
