# Attendance-only production readiness — executive summary

Audit date: 2026-10-30  
Auditor mode: read-only. No application source, schema, configuration, or environment file was changed by this audit.  
Candidate under test: the **working tree** on `main`, not the committed revision alone.

## Verdict

**DEPLOY AFTER SPECIFIED FIXES.**

The attendance engine, self-service punch API, company overview query, web screens, and Flutter attendance flow are real implementations, not stubs. An employee can check in and check out through the API, and both clients call that API. That is not the same as a releasable production build.

The committed revision still copies the untrusted `X-Company-Id` header into tenant context before authentication. The fix exists only as uncommitted work. The Android release build is signed with the debug key and defaults to `http://localhost:8000`. Backup restore has never been recorded as tested. One regularization type the API and mobile app accept cannot be stored. This audit did not execute the integration or row-level-security suite, because that suite is guarded against the shared development database.

Payroll does not have to be finished for attendance to run. The API imports the payroll package at startup, and that import succeeds in the current tree. Unfinished payroll screens are reachable from navigation and do not share attendance data loading.

## Overall score

**6.1 / 10** (unweighted mean of the scores below)

| Category | Score | Evidence | Critical gaps |
|---|---:|---|---|
| Backend attendance | 7 | Code trace of punch, day, roster, regularization, leave projection. 180 calculation and policy unit tests passed. | Idempotency is optional. Web does not send a key. Calculation failure after a punch is swallowed. |
| Attendance calculations | 7 | Single `evaluate_day` engine. Unit tests passed. | Punch rounding is never applied. `auto_closed` is never set. WFH does not change status. `is_regularized` is cleared on the next recompute. |
| Database integrity | 7 | Alembic constraints read from migration files. Head on disk is `20261031090000` (untracked). | `EARLY_DEPARTURE_APPROVAL` is allowed in Python and rejected by the check constraint. Shift composite foreign keys are not in git. |
| API contracts | 7 | Routes, schemas, and both clients compared. | Web attendance lists drop pagination and stop at 500 rows. Early-departure type will not persist. |
| Web employee attendance | 6 | Punch dialog, history, and calendar are wired to live routes. Web tests of that dialog passed on rerun. | No browser session against a real API. No geolocation. No idempotency key. |
| Web company dashboard | 6 | Working-tree dashboard calls `GET /v1/dashboards/company/attendance-overview`. | That endpoint and UI are uncommitted. The Attendance page still aggregates in the browser and can truncate at 500 rows. |
| Flutter attendance | 5 | Analyzer clean. `flutter test`: 557 passed, 1 skipped. Payload matches `PunchCreateSelf`. | Release signing is the debug key. Default API URL is localhost. No offline queue. |
| Cross-platform consistency | 6 | Both clients use server time for self punch and the same day fields. | Web omits location and idempotency. Company overview buckets and the Attendance page buckets do not match. |
| Authentication | 8 | Argon2, 15-minute access token, rotating refresh cookie, lockout, logout revokes the session. | Refresh cookie `Secure` depends on `TRUSTED_PROXY_HOSTS`. Not exercised live in this audit. |
| Authorization | 8 | Employee role is `SELF` for punch, view, and regularization request. Self-approval is refused on the review path. | A published `AUTO` chain skips that self-approval check. Not exercised live. |
| Tenant isolation | 5 | Working-tree middleware ignores `X-Company-Id`. RLS policies exist. Runtime-role tests exist and were **not run**. | Committed `HEAD` still trusts the header. Shipping `HEAD` is unsafe. |
| Timezone correctness | 7 | Business dates use the company zone. Companies are allow-listed to `Asia/Kolkata`. Celery beat is `Asia/Kolkata`. Calculation unit tests passed. | A few `datetime.now(UTC).date()` call sites remain. Overnight punches are attributed to the punch’s local date until the sweep. |
| Performance | 3 | Overview is one grouped SQL statement. No timings were taken. | No measurement at 50, 250, 500, 1,000, or 5,000 employees. |
| Logging and monitoring | 6 | JSON logs, `X-Request-Id`, `/health/live` and `/health/ready`, optional monitoring compose file. | No evidence of an alerting sink on the Hostinger host. Beat has no leader lock. |
| Automated testing | 6 | Backend unit subset, web Vitest, Flutter analyzer and tests, `tsc --noEmit` executed. | Integration, RLS, migration, and live end-to-end scenarios were not executed. |
| Deployment configuration | 6 | Compose, Nginx, and Dockerfiles are in the repo. Local production CSP suite: 15 passed, 3 Nginx checks skipped. | Hostinger runbook has not been executed. Docker standalone entrypoint and real TLS were not the process under test. `connect-src` is baked in at web build time. |
| Backup and recovery | 3 | `pg_backup.sh` / `pg_restore.sh` exist. Docs state restore has not been proven. | Same-VPS dumps. No recorded restore. No off-site copy in the repo. |

## Critical findings

| ID | Severity | What | Blocks deployment |
|---|---|---|---|
| ATT-SEC-001 | Critical | Committed `TenancyMiddleware` sets tenant context from `X-Company-Id` before authentication. The working tree stops doing that. | Yes, if the deployed code is `HEAD` or `origin/main`. |
| ATT-REL-001 | Critical | The attendance overview, tenancy fix, CSP middleware changes, and shift-tenant foreign key are uncommitted. There is no release commit to deploy. | Yes, until that tree is reviewed and packaged. |
| ATT-MOB-001 | Critical for mobile | Android release uses the debug signing config. `API_BASE_URL` defaults to `http://localhost:8000`. Release builds disallow cleartext. | Yes for any Flutter distribution. |
| ATT-REG-001 | High | `EARLY_DEPARTURE_APPROVAL` is in the API schema and the mobile form. The database check constraint does not allow it. | Yes if that request type stays in the product. |
| ATT-OPS-001 | High | Production boot requires `ENVIRONMENT`, real secrets, `TRUSTED_PROXY_HOSTS`, and a baked-in `NEXT_PUBLIC_API_URL`. Defaults are development. | Yes if those are left at defaults. |
| ATT-OPS-002 | High | Restore has not been tested. Backups documented as local to the VPS. | Yes before real employee data is stored. |
| ATT-QA-001 | High | Punch, authorization, and tenant-isolation behaviour were not executed against a database in this audit. | Yes as a release gate: the existing integration and RLS jobs must be green on an isolated database. |

## Deployment recommendation

Do not deploy the current git revision.

Do not wait for payroll, payslips, tax, PF, or ESI.

Deploy only after the items in `09_RELEASE_BLOCKERS_AND_ACTION_PLAN.md` section A are done, and only the working-tree security fixes (reviewed and included in the artifact), not `f6340eb` by itself.

## Answers required by the audit brief

1. **Backend attendance** is structurally production-capable for check-in, check-out, and day calculation. It is not releasable until the uncommitted tenancy fix is what actually ships, the early-departure type is aligned with the database, and the integration suite has been run.
2. **Web** is integrated with the current APIs and typechecks. It was not exercised in a logged-in browser against the API. The company overview is the right design and is uncommitted. The Attendance command centre can under-count past 500 rows.
3. **Flutter** attendance behaviour is implemented and its test suite passed. The Android release package is not store-ready or production-URL-ready.
4. **An employee can record attendance and see the result** when the API, a published attendance policy, and a client pointed at that API are running. This audit did not complete that click-path against a live server.
5. **An administrator can monitor company attendance** through the uncommitted overview endpoint, which groups stored `attendance_day` rows and does not mark a pre-shift day as absent. The separate Attendance page can disagree and can truncate.
6. **Web and mobile are consistent** on self-punch (server clock, no client timestamp) and on day fields. They are not consistent on location, idempotency, or on how “present” is bucketed in the two web views.
7. **Authentication and authorization look safe** in the working tree for an employee role. **Tenant isolation is not safe on committed `HEAD`.** The working-tree design is the correct one and was not proven here by running the RLS tests.
8. **Timezone handling in the calculation engine is the company zone, default `Asia/Kolkata`.** A few non-calculation call sites still use the UTC calendar date. Overnight attribution has a known one-day lag until the 09:30 sweep.
9. **Payroll does not have to be implemented** for attendance to start. Leave it installed so the process can import it. Hide or label payroll navigation so operators do not treat it as part of this release.
10. **Blockers** are listed above and in document 09. They are security packaging, mobile release configuration, one broken regularization type, untested recovery, and an unexecuted integration gate. They are not “build the rest of HRMS.”

## Evidence classes used in this audit

- **Executed:** a command in this audit produced the result.
- **Code inspection:** behaviour read from the working tree, with path and line.
- **Committed contrast:** `git show HEAD:` differs from the working tree.
- **Documented, not re-proven:** an existing doc states a fact this audit did not repeat.
- **Unverified:** no run and no complete code path.

## Baseline

| Item | Value |
|---|---|
| Branch | `main` (ahead of `origin/main` by 1 commit) |
| HEAD | `f6340eb7c1679e449ecd87079cb6de01cb5cafec` |
| HEAD subject | `feat(attendance): geofenced punches, mobile location capture, and web UI redesign` |
| Remote | `https://github.com/varunmsaji/HRMS.git` |
| Layout | `apps/api` (FastAPI), `apps/web` (Next.js), `apps/mobile` (Flutter), `infra/` (Compose, Nginx, backups) |

`git status --short` at the start of the audit is reproduced in `07_TEST_AND_QA_RESULTS.md`. The closing comparison is in that same file.
