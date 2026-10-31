# Test and QA results

All commands were run on 2026-10-30 against the working tree. Nothing was pointed at a production database. The shared development database `hrms_dev` on port 5433 and Redis on port 6380 were left untouched. `tests/isolation_guard.py` refuses that combination unless `HRMS_TEST_ALLOW_SHARED_DEV=1`. That override was not set.

The API virtualenv’s `pytest` script has a broken shebang (`/media/varun/varun11/...`). Tests were run with `apps/api/.venv/bin/python -m pytest`.

## Backend

### Executed

```text
cd apps/api
.venv/bin/python -m pytest \
  tests/unit/modules/attendance/test_calculation.py \
  tests/unit/modules/attendance/test_night_ot.py \
  tests/unit/modules/attendance/test_geofence.py \
  tests/unit/modules/attendance/test_pay_basis.py \
  tests/unit/modules/attendance/test_evaluation_summary.py \
  tests/unit/modules/attendance/test_policy_validation.py \
  tests/unit/modules/attendance/test_period_summary.py \
  tests/unit/modules/attendance/test_engine_version.py \
  tests/unit/core/test_tenancy_middleware.py \
  --noconftest -q --tb=line
```

Result: **180 passed**, 1 warning (Starlette `TestClient` / httpx deprecation), 1.31s.

`--noconftest` was required so the suite would not open the shared dev database or delete `ratelimit:*` keys on the shared Redis.

Second batch, same interpreter and `--noconftest`:

```text
.venv/bin/python -m pytest tests/unit/modules/attendance tests/unit/core/test_tenancy_middleware.py tests/unit/shared --noconftest -q --tb=line
```

Result: **407 passed, 13 skipped, 11 failed**, 3.78s.

Failures that are environment, not product defects:

| Failure | Cause |
|---|---|
| `test_liveness.py` (2) and `test_opensource_face_evaluation.py` (1) | `ModuleNotFoundError: cv2`. OpenCV is not installed in this venv. Liveness extra is absent. |
| `test_onboarding_upload_rate_limit_middleware.py` (2) and `test_rate_limit_dual_bucket.py` (6) | Redis connection refused at `localhost:6380` from the sandbox. Those tests need a Redis. They were not re-run against the shared dev Redis, because the root conftest deletes rate-limit keys there. |

The 180-test calculation and tenancy batch does not overlap those failures. Attendance calculation, geofence decision, night overtime, pay-basis fractions, period summary, and the header-does-not-set-tenant unit tests passed.

### Not executed

| Suite | Why |
|---|---|
| `tests/integration/**` | Would use `hrms_dev` and issue deletes. Refused. |
| `tests/security/test_rls_*.py` and attendance RLS runtime-role tests | Same database. Not run. Their assertions were read. |
| `tests/integration/modules/attendance/test_company_attendance_overview.py` | Not run. |
| Alembic upgrade / downgrade | Forbidden for this audit. |
| Celery beat firing | No worker was started. |
| Load at 50–5,000 employees | No isolated dataset was built. No timings exist. |

## Web

### Typecheck

```text
cd apps/web && ./node_modules/.bin/tsc --noEmit --pretty false
```

Exit code **0**. No diagnostics.

### Vitest, full suite, under parallel load

```text
cd apps/web && ./node_modules/.bin/vitest run --reporter=dot
```

**689 passed, 10 failed**, 94 files (85 passed, 9 failed), 42.95s.

The 10 failures were `Test timed out in 5000ms` (login, register, punch dialog, accept-invite, company profile, leave balances, grade detail, my calendar, roster grid). One punch-dialog case also reported the submit mock was not called after the timeout started. Worker shutdown then hit `kill EACCES` inside the sandbox. These ran while Flutter tests and pytest were also running.

### Vitest, the failed files plus CSP unit tests, alone

```text
./node_modules/.bin/vitest run --testTimeout 20000 --maxWorkers 2 \
  src/app/login/page.test.tsx src/app/register/page.test.tsx \
  src/components/attendance/punch-entry-dialog.test.tsx \
  src/app/accept-invite/[token]/page.test.tsx \
  src/app/app/company/page.test.tsx src/app/app/leave-balances/page.test.tsx \
  src/app/app/grades/[id]/page.test.tsx src/app/app/me/calendar/page.test.tsx \
  src/app/app/rosters/grid/page.test.tsx \
  src/lib/security/csp.test.ts src/middleware.test.ts
```

**11 files, 77 tests, all passed**, 6.30s. Worker `kill EACCES` appeared again during pool shutdown and did not fail the tests.

Conclusion: no confirmed web product test failure. The full-suite timeouts were load. CSP header unit tests passed in the rerun.

### CSP production browser suite

First attempt (sandbox, no Chromium binary): 8 HTTP nonce/cache tests passed, 7 browser tests failed in 1ms with `Executable doesn't exist` for Playwright’s headless shell, 3 nginx tests skipped. That run does not count as a CSP failure.

Second attempt:

```text
cd apps/web
CSP_E2E_CHROMIUM=/usr/bin/google-chrome \
  ./node_modules/.bin/playwright test -c playwright.csp.config.ts
```

**15 passed, 3 skipped**, 26.9s. Exit code 0.

Passed in Chrome against `next build` + `next start` on `127.0.0.1:13011`, with `NEXT_PUBLIC_API_URL=https://api.hrms.test` and CSP enforced (Playwright was not set to bypass CSP):

- Negative controls: foreign `fetch`, inline `onclick`, and `eval` blocked.
- `/login`, `/register`, `/app/dashboard`, `/verify-email/abc123`: scripts load, React hydrates, no CSP violations.
- Login submit handler runs. Register form is interactive. The API host is a fake origin, so login does not reach a real API. The suite expects that DNS failure.
- Every `<script>` on `/login`, `/register`, `/app/dashboard`, `/verify-email/abc123`, `/`, and a missing route carries that response’s nonce. A second request gets a different nonce. `cache-control` is `no-store`. No `x-nextjs-prerender`.
- CSP header is `script-src 'self' 'nonce-…' 'strict-dynamic'` with no `unsafe-inline` or `unsafe-eval` on scripts, `connect-src` includes the API origin, `frame-ancestors 'none'`, `upgrade-insecure-requests`. HSTS is present because the test sends `X-Forwarded-Proto: https`.
- `/_next/static` chunks are immutable, one-year cache.

Skipped, because `CSP_E2E_BASE_URL` was not set:

- TLS terminated by Nginx.
- HSTS from the proxy rather than a client-supplied header.
- Nonces through the proxy.

The web server logged: `next start` does not work with `output: "standalone"`. Use `node .next/standalone/server.js`. Docker’s runtime command is `node server.js` from the standalone bundle (`apps/web/Dockerfile` 51–52). **That process was not the one Playwright hit.** Hydration is proven for `next start` of this build, not for the container entrypoint, and not behind Nginx.

A Next.js warning says the `middleware` file convention is deprecated in favor of `proxy`. The current middleware still produced a passing CSP.

## Flutter

```text
/home/varun/flutter/bin/flutter analyze --no-fatal-infos
```

**No issues found** (2.4s). Flutter then printed an upgrade notice. The SDK was not upgraded.

```text
/home/varun/flutter/bin/flutter test --reporter compact
```

**All tests passed. 557 passed, 1 skipped.** About 33s.

Not executed: `flutter build apk --release`, an emulator, a device, and `live/live_contract_test.dart` against a real API.

## End-to-end scenarios

| Scenario | Result |
|---|---|
| A. Employee login, check-in, check-out, hours, history | **Unverified.** No live API session. |
| B. Admin dashboard, present/absent/leave, pending request, approve | **Unverified.** Overview code and pending-approval code were read. |
| C. Flutter check-in visible on web, web check-out visible on Flutter | **Unverified.** |
| D. Duplicate punch, check-out without check-in, concurrent check-in, cross-tenant, network failure | **Partial code inspection only.** See documents 02, 04, and 05. No concurrent HTTP test was run. |

## Baseline `git status --short` (start of audit)

Branch `main`, HEAD `f6340eb7c1679e449ecd87079cb6de01cb5cafec`, ahead of `origin/main` by 1.

Modified (tracked): `.github/workflows/ci.yml`; API auth, tenancy, attendance router/service, employee import, organisation module, several tests, web pages listed in the conversation git status (dashboard, attendance geofences, employees, leave, rosters, shifts, layout, middleware, API client, and others), `docs/deployment/PRODUCTION_DEPLOYMENT.md`.

Untracked at start (not created by this audit): shift-tenant migration `20261031090000_shift_tenant_fk.py`, `attendance/overview.py`, `overview_schemas.py`, RLS and overview tests, web dashboard components, CSP e2e, security lib, employee directory hooks, and the pre-existing docs under `docs/audits`, `docs/blind-audit-2026-10-29`, `docs/operations`, `docs/production-readiness`, `docs/ui-performance`.

## Closing comparison

HEAD is still `f6340eb7c1679e449ecd87079cb6de01cb5cafec`. The branch is still `main`, one commit ahead of `origin/main`.

Tracked files that differ from HEAD are the same set that was already dirty at the start of the audit (62 paths). The CSP production build appended `.next-csp-e2e` include paths to `apps/web/tsconfig.json`. That accidental edit was restored with `git checkout -- apps/web/tsconfig.json` so the audit would not leave an application-source change. The build directory `apps/web/.next-csp-e2e` was removed after the suite. It is not source.

The only files this audit added are the eleven documents in `docs/audits/attendance-only-production-readiness/`. No commit was made.

## Repository protection

This audit created only `docs/audits/attendance-only-production-readiness/`. It did not commit, push, migrate, or edit application source. The CSP suite writes a Next build directory (`.next-csp-e2e` or `.next`, depending on `NEXT_DIST_DIR`). That output is a build artifact, not a source change. If it is present after the audit, it should not be committed.
