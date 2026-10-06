# Pre-Payroll Production Readiness Final Audit

| Field | Value |
|---|---|
| Audit date | 2026-10-05 |
| Repository | `staff-spectrum/HRMS` |
| Branch | `main` |
| Commit at audit | `7ba4ce7` — `fix(attendance): refuse cross-employee punch idempotency key reuse` |
| Working tree | **Not clean** — 65 modified + 54 untracked files, spanning core, employee, leave, attendance, payroll, web and mobile (full list in §3). This is live, uncommitted work; it was read and exercised exactly as it sits on disk. |
| Method | Direct source inspection, live database probing (RLS, backup/restore), full local test execution, dependency/secret scanning. **No business code, schema, or production-like data was modified.** |
| Scope | Everything before Payroll. Payroll's own correctness is out of scope except as a *consumer* of Attendance/Leave/Employee outputs (§17). |

**Evidence rule applied throughout:** every PASS below cites a file/line, a command transcript, or a
reproduced test result. Where nothing could be executed in this environment, the item is marked
**UNVERIFIED**, never PASS. Two prior final-form audits exist in this repo
(`PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md`, commit `e33fcdb`, 2026-09-10, and
`PRODUCTION_READINESS_AUDIT_PRE_PAYROLL.md`) — they were read as historical input, not trusted;
every claim reused from them below was re-verified against the current repository.

> **2026-10-05, same day — superseded by remediation.** All five findings below (§7) were closed
> the same day in a remediation pass: see **"Final Remediation and Re-Audit"** near the end of
> this document for what changed (and, for FINDING-05, what turned out to already be true and
> only needed correcting in documentation) and the final verdict, **READY FOR PRODUCTION**. §1-§21
> below are kept exactly as originally written — the point-in-time record this audit produced
> before remediation — and should be read as history, not current status.

---

## 1. Executive Verdict

# 🟠 READY WITH CONDITIONS

The foundation is substantially stronger than the 2026-09-10 baseline: RLS is now proven (not just
present) under the real runtime role with a raw-connection, app-bypassing test; CI runs the full
integration + security suite against real Postgres/Redis/MinIO (closing the prior **TST-001
BLOCKER**); the leave balance race the prior audit called a concrete correctness hole is now closed
with advisory locks and a deterministic, monkeypatch-driven concurrency test; the attendance
engine now carries `engine_version`/`paid_days`/`payable_days` fields the payroll handoff needs
(closing prior **PAY-002**, **PAY-004**, **DAT-001/002**). This is real, independently-verified
progress, not re-asserted history.

It is **not** an unconditional pass. Five findings below are production blockers in their own
right (§7), independent of anything Payroll will ever read:

1. **Unhandled exceptions are never logged** — a crash anywhere in the API produces a clean `500`
   to the client and leaves **zero trace** in any log, metric, or alert (`FINDING-01`).
2. **Two list endpoints have no pagination or limit at all** (`GET /v1/account-invites/users`,
   `GET /v1/onboarding-cases`) — unbounded response size as tenants grow (`FINDING-03`).
3. **A critical-severity Next.js vulnerability** (GHSA — DoS/HTTP request smuggling) and a
   high-severity PostCSS vulnerability sit in the frontend's production dependency tree
   (`FINDING-02`).
4. **`account_invite` and `onboarding_token` carry `company_id` but have no Row-Level Security
   policy, and no documented reason for the gap** — unlike `refresh_token`/`session` (two other
   un-policied tables, but ones explicitly documented as a deliberate design decision), tenant
   isolation on these two rests entirely on an unreviewed application `WHERE` clause, with no
   database-level backstop (`FINDING-04`).
5. Two **product decisions already identified in this repository's own leave-hardening pass
   (L11/L12)** remain unresolved in code: leave can still be submitted, auto-approved and debited
   for dates before joining, after the last working day, or inside a rehire gap, and a leave
   balance survives a rehire as one continuous ledger. Both are now a coded gap, not an unknown.

None of the five requires a redesign. All are bounded, single-area fixes (§19). Once they are
closed and the open product decisions in §12 of `PAYROLL_BUSINESS_DECISIONS.md` (L11/L12) are
made, this platform is ready to carry Payroll on top of it.

**What "READY WITH CONDITIONS" means here, precisely:** the system **can** go to production for
everything before Payroll (registration, employee lifecycle, attendance, leave, RBAC, multi-tenant
isolation at the database level) once FINDING-01 through FINDING-04 are fixed. Payroll itself must
not be switched on — and no period should be relied on for payroll input — until L11/L12 are
decided and the handoff gaps in §17 are closed.

---

## 2. Scope

Everything merged or in the working tree **before** Payroll's own business correctness: auth, RBAC,
tenancy/RLS, company/legal-entity/branch/department, employee lifecycle, employment spells,
compensation, attendance, leave, overtime, regularization, comp-off, period closing, notifications,
object storage, audit logging, background jobs, infrastructure, CI/CD, migrations, and the
Attendance/Leave/Employee → Payroll handoff contract. Payroll's internal calculation correctness
(salary breakup, TDS, arrears) is explicitly **not** re-audited; it is touched only to ask "can
Payroll trust what it is handed."

## 3. Repository / Commit Audited

```
HEAD:   7ba4ce7e212a17946257e9792939a0b7c7805d01  (2026-10-03 18:42:23 +0530)
Branch: main
```

Working tree carried substantial uncommitted work at audit time (verified `git status`, `git diff
--stat`): 65 modified files + 54 untracked files, 4,331 insertions / 892 deletions in the tracked
set alone. This includes:

- **Core**: `auth/dependencies.py`, `celery_app.py`, `config/settings.py`, `errors/handlers.py`,
  `rbac/dependencies.py`, `tenancy/dependencies.py`, new `db/locks.py`, `db/timeouts.py`,
  `idempotency.py` + `idempotency_key` model/migration.
- **Employee**: `coverage.py` (new — single employment-coverage authority, see §9), lifecycle
  hardening across `repository.py`/`service.py`/`schemas.py`.
- **Leave**: the full hardening pass (decisions 11–20), 13 new integration test files.
- **Attendance**: cross-employee idempotency fix, `engine_version`/`paid_days` fields, 4 new test
  files (sweep concurrency, punch-after-LWD, regularization employment period, leave-projection
  integrity).
- **Payroll**: `breakup.py`, `engine.py`, `models.py`, `repository.py`, `router.py`, `service.py`,
  6 new migrations, 6 new test files (`test_b01`…`test_b05`, `test_p1_hardening`) — all read only
  as a consumer of the pre-Payroll surface, per scope.
- **Mobile/Web**: leave/payroll repository wiring, idempotency-key plumbing, attendance dashboard.

This audit read and exercised the tree **as it sits**, uncommitted. §22 lists every command that
touched any database, confirms nothing was committed, and discloses one unintended command (a
no-op) against the live dev database.

## 4. Environment Tested

| Component | Version / detail |
|---|---|
| OS | Linux 6.8.0-138-generic |
| PostgreSQL | 16 (docker `hrms-postgres`, healthy, port 5433) + a disposable `postgres:16-alpine` container for migration/backup verification |
| Redis | 7 (docker `hrms-redis`, healthy, port 6380) |
| Object storage | MinIO (docker `hrms-minio`, healthy, ports 9000-9001) |
| Python | 3.12, `.venv` managed by `uv` |
| Node | frontend `npm`/vitest/Next.js toolchain, installed |
| Flutter/Dart SDK | **not installed in this environment** — mobile analyzer/tests/build are UNVERIFIED here (code-level review only; CI status not re-derived) |
| Runtime DB role | `hrms_app` — confirmed `NOSUPERUSER`, `NOBYPASSRLS` live (`pg_roles` query, §6) |
| Migration/owner role | `hrms` — `SUPERUSER`, `BYPASSRLS` (by design, schema owner only) |

The dev Postgres instance is shared with the developer's own running stack (dev API server was
live on port 8000 throughout). All destructive/exploratory probing was done either read-only
against it, or against disposable containers created and destroyed for this audit (§22).

## 5. Test Statistics

**Backend** (`apps/api`, `.venv/bin/python -m pytest`):

| Metric | Value |
|---|---|
| Tests collected | **2,330** (`pytest --collect-only -q`, 0.57s) — up from 1,145 at the 2026-09-10 baseline |
| Test files | 198 (87 at the 2026-09-10 baseline) |
| Full run (`tests/`) | **2,330 passed, 0 failed, 0 errors, 4 warnings, in 643.57s (10:43)** |

A first execution attempt (`pytest tests -q`) was killed by an over-tight 580s harness timeout
before completion (exit 143) — the suite has grown well past the point a ~10 minute budget covers,
partly because several concurrency tests (§14) deliberately hold real multi-second `asyncio.sleep`
windows to force interleaving deterministically rather than relying on luck. It was re-launched
unbounded in the true background and **ran to completion**: every one of 2,330 collected tests
passed, zero failures, zero errors. The 4 warnings are pre-existing `pytest.mark.asyncio` lint
warnings on synchronous test functions in `test_route_authorization_matrix.py` (cosmetic, not
failures — see that file below).

Individually confirmed by direct reading (in addition to being part of the 2,330 that passed):

- `tests/security/test_rls_runtime_role.py` — read in full (636 lines); its assertions were
  independently reproduced live via `psql` as `hrms_app` (§6).
- `tests/security/test_security_headers.py`, `test_api_docs_exposure.py` — read in full, behavior
  cross-checked against `errors/handlers.py` and `app.py`.
- **`tests/integration/test_route_authorization_matrix.py`** — an auto-generated authorization
  truth table, not a hand-written one: it introspects every route in the organisation, employee and
  employee-import routers and asserts, per route, anonymous→401, authenticated-with-zero-permissions
  →403 (and that 403 wins over a 422 body-validation failure), holding exactly the required
  permission code → past the gate, holding a different code → 403, and `COMPANY_ADMIN` → past the
  gate. Routes that pick a permission imperatively inside the handler (one found:
  `POST /employees/{employee_id}/assignments`) are covered by dedicated assertions. Because routes
  are discovered by introspection rather than listed by hand, a newly added endpoint is covered the
  day it lands. This is materially stronger RBAC evidence than this audit initially credited in
  earlier drafts of §6 row B.
- Migration suite (111 Alembic revisions) — executed end-to-end on an empty database (§15).
- Backup/restore round trip — executed end-to-end on a disposable database (§16/AH).

**Frontend** (`apps/web`, `npx vitest run`):

```
Test Files  61 passed (61)
     Tests  505 passed (505)
  Duration  10.50s (environment 69.54s)
```

Executed to completion this audit. Up from 45 files / 342 tests at the 2026-09-10 baseline.

```
npx tsc --noEmit  → clean, exit 0
npx next build    → succeeds, 70 routes compiled, First Load JS shared 87.4 kB
```

Both re-run to completion this audit (not carried from a prior document).

**Mobile**: **UNVERIFIED** — no Flutter/Dart SDK in this environment. 28 `*_test.dart` files exist
(code inspection only); analyzer, widget tests, and release build could not be executed here.
Distinguish explicitly: **VERIFIED IN CODE ONLY**, never **VERIFIED ON DEVICE**.

**Security scans**:

```
pip-audit (backend venv):     3 known vulns, 1 package (urllib3 2.7.0 → fix 2.8.0)
npm audit --omit=dev (web):   3 vulns — 1 critical (next.js), 2 high (postcss, nanoid)
npm audit (web, incl. dev):   14 vulns — 1 critical, 11 high, 2 moderate
git history secret scan:      0 real findings (grep for AKIA/private-key headers; only doc placeholders and "AKIAEXAMPLE" matched)
```

**Database**:

```
Migration status:  111/111 revisions apply cleanly, empty DB → head, verified on a disposable container
RLS:                71 of ~100 public tables have RLS + FORCE RLS; cross-tenant SELECT/UPDATE/DELETE/INSERT
                    proven blocked at the database level (not just app code) under hrms_app, reproduced live
Backup/restore:     pg_dump (-Fc) from the live dev DB → pg_restore into a disposable container;
                    table count (104) and a sampled row count (company) matched source exactly
Integrity tests:    see §13 (data integrity) and §14 (concurrency) — specific files cited, not re-run in full here
```

### 5a. Full backend suite — final result

**Completed during this audit.** `cd apps/api && .venv/bin/python -m pytest tests -q
--junitxml=backend-full.xml`, launched unbounded in the background after the first, timeout-killed
attempt:

```
2330 passed, 4 warnings in 643.57s (0:10:43)
```

Zero failures, zero errors, across the entire collected suite (unit + integration + security) —
every file referenced elsewhere in this report as "read in full" or "exists, not re-run" was in
fact exercised and passed as part of this run, including `test_rls_runtime_role.py`,
`test_leave_balance_races.py`, `test_sweep_concurrency.py`, `test_route_authorization_matrix.py`,
`test_leave_rbac_matrix.py`, `test_auth_security.py`, and every new/uncommitted test file listed in
§3. This is the strongest single piece of evidence in this audit: a 2,330-test suite spanning auth,
RBAC, tenancy, employee lifecycle, attendance, leave, concurrency, idempotency, and security,
passing in full against real Postgres/Redis/MinIO, with no test skipped or xfailed. The 4 warnings
are cosmetic `pytest.mark.asyncio`-on-a-sync-function lint warnings in
`test_route_authorization_matrix.py`, not failures.

This does **not** change any finding in §7/§8 — all five were found by direct code/config/schema
reading, not by a failing test (none of them have a regression test yet, which is itself part of
§20's recommendation) — but it substantially raises confidence in the "READY" half of "READY WITH
CONDITIONS": nothing this audit exercised through the test suite contradicts the rest of this
report, and no latent regression was hiding in the 1,185 tests added since the 2026-09-10 baseline.

---

## 6. Production Readiness Scorecard

Legend: ✅ PASS (evidenced) · 🟡 PASS WITH FINDING · 🔴 FAIL/BLOCKER · ⚪ UNVERIFIED · N/A not applicable here.

| Gate | Status | Evidence |
|---|---|---|
| A. Authentication | ✅ | JWT HS256 + rotating refresh family; `test_auth_security.py` passed as part of the full suite run (§5a); login/expired/malformed/unauthenticated token paths covered by `test_organisation_security.py` (read in full, §9 extract). Specific scenarios not individually re-traced line-by-line this pass (brute-force lockout threshold, full refresh-reuse-detection matrix) — covered by passing tests, not independently re-derived from first principles. |
| B. Authorization / RBAC | ✅ | Role catalogue confirmed in code: `COMPANY_ADMIN`, `HR_ADMIN`, `REPORTING_MANAGER`, `BRANCH_MANAGER`, `EMPLOYEE` (`organisation/service.py:223-240`, with documented scope rationale per role). `test_leave_rbac_matrix.py` and the introspection-based `test_route_authorization_matrix.py` (§5a) both passed as part of the full suite run — the latter proves 401/403/scope behavior for every route in three modules automatically, not by hand-picked example. |
| C. Tenant isolation | ✅ | Proven live, both through the app and via a raw connection bypassing app code entirely (§6 detail below). |
| D. RLS | 🟡 | 71/~100 tables RLS+FORCE; 4 tables have no RLS (`refresh_token`/`session` — documented exceptions; `account_invite`/`onboarding_token` — undocumented, `FINDING-04`). `company` itself correctly has no isolation policy (it *is* the tenant root). |
| E. Company / legal entity | ✅ | GiST no-overlap on employment/policy/period; read in `DATA_INTEGRITY_AUDIT.md`, spot-checked current schema. |
| F. Branch/department/assignments | 🟡 | Department depth cap (5), `BRANCH_MANAGER` role scoped to `EmployeeAssignment.branch_id` — code read, not independently load-tested. |
| G. Employee lifecycle | 🟡 | `employee/coverage.py` (new, uncommitted) is now the single authority for joining/LWD/rehire-gap/cross-spell validity, consumed by Leave, Attendance projection and the termination guard (§9) — closes a design gap the leave audit flagged as open. Full lifecycle E2E not re-run this pass. |
| H. Employment spells | ✅ | `employment_no_overlap` GiST exclusion constraint — a database guarantee, not an app check (verified present in schema). |
| I. Compensation / master data | 🟡 | CTC strictly-positive DB check constraint (migration `20261007090000` present in `alembic upgrade head` output, §15). Not independently re-verified against live data. |
| J. Attendance | 🟡 | Engine-version stamping now present (`FINDING` closed vs. 2026-09-10); cross-employee punch-idempotency bug fixed this commit (`7ba4ce7`); `GET /attendance/days`/`/punches` still unbounded without a date range (documented, open, §11). |
| K. Leave | 🟡 | Balance concurrency now lock-protected (`pg_advisory_xact_lock`) with a deterministic test (§14); L11/L12 employment-boundary/rehire-balance decisions still open in code (§12). |
| L. Overtime | ⚪ | Code read; self-approval block and comp-off hand-off confirmed in docs; not independently re-executed this pass. |
| M. Regularization | 🟡 | R1 (requested punches not tied to date) — fixed per `ATTENDANCE_MODULE_AUDIT.md` pass 2, `test_regularization_employment_period.py` exists (uncommitted). |
| N. Comp-off | ⚪ | Credit/expiry idempotency documented and tested per `ATTENDANCE_MODULE_AUDIT.md` C1; not independently re-executed. |
| O. Period closing | 🟡 | PD-2/PD-3/PD-4 (Payroll must refuse non-CLOSED periods; leave locks on closed dates; input-change detection) read as implemented in `PAYROLL_BUSINESS_DECISIONS.md` cross-reference; live period-close race not independently re-executed this pass. |
| P. Notifications/email | 🔴 | **No outbox / notification abstraction exists** (confirmed: `leave/service.py` and `celery_app.py` comments explicitly call this "planned-only"). SMTP fails boot loudly if misconfigured in non-dev (`settings.py` model validators, §10) — that part is solid; the notification layer itself is not built. |
| Q. Files / object storage | ✅ | Presigned URLs, 300s default expiry (`core/storage.py:70,95`); upload-bounds and rate-limit tests exist (`test_onboarding_upload_bounds.py`, `test_employee_import_upload_bounds.py`). |
| R. Audit logging | ✅ | `audit_log` append-only for `hrms_app` (owner-only UPDATE/DELETE, migration `20261009090000`); confirmed present via RLS test (`test N` assertion). |
| S. API correctness | 🟡 | See §11 pagination findings. |
| T. Web UI | ✅ | 505/505 vitest pass; `tsc --noEmit` clean; `next build` succeeds (70 routes) — all three re-run to completion this audit. |
| U. Mobile app | ⚪ | UNVERIFIED — no toolchain (§5). |
| V. Background jobs | 🟡 | Celery Beat schedule read in full (§10) — reasonable, idempotent, well-reasoned; per-employee savepoint isolation in accrual (L7) confirmed from `LEAVE_MODULE_AUDIT.md`, not re-executed. |
| W. Celery Beat | ✅ | 6 scheduled tasks, all with documented idempotency/timezone reasoning (§10). |
| X. Redis | ✅ | Healthy, used for sessions/rate-limit buckets; confirmed live (`docker ps`). |
| Y. Database integrity | 🟡 | Strong constraint design (GiST exclusions, CHECK constraints, partial unique indexes, 7 append-only tables) — confirmed via schema read; known gap: `leave_ledger`'s employee FK is not composite with `company_id` (documented, open). |
| Z. Database concurrency | 🟡 | Leave-balance and leave-dates advisory locks, attendance sweep per-employee-date locking (not whole-company) — confirmed in code and via a deterministic test file read in full (§14). |
| AA. Idempotency | ✅ | `Idempotency-Key` mechanism (`core/idempotency.py`) — claim/commit/replay/fingerprint design read in full; migration present; punch idempotency cross-employee bug fixed this HEAD commit. |
| AB. Error handling | 🔴 | Clean, non-leaking error envelopes confirmed (no stack trace, no SQL text, no internal path in any handler) — **but the catch-all handler discards the exception with no logging at all** (`FINDING-01`). |
| AC. Observability | 🔴 | Direct consequence of AB: a production 500 leaves no log line, no metric, no alert. structlog is configured and used elsewhere, just not here. |
| AD. Security | 🟡 | Security headers, CSP, conditional HSTS, boot-time fail-safe config (CORS/SMTP/JWT/KMS) all confirmed live; `FINDING-04` (RLS gap on 4 tables) and `FINDING-02` (dependency CVEs) are the open items. |
| AE. Dependencies | 🔴 | 1 critical (Next.js) + 1 high (PostCSS) + 1 high (nanoid) in the frontend production tree; 1 package (urllib3) with 3 known CVEs in the backend (§8). |
| AF. CI/CD | ✅ | **Materially improved since 2026-09-10**: CI now provisions real Postgres+Redis+MinIO and runs `tests/integration` + `tests/security` (closes the prior TST-001 🔴 BLOCKER) — read in full (§7 detail). |
| AG. Migrations | ✅ | 111/111 apply cleanly on an empty database, reproduced independently this audit (§15). |
| AH. Backups/restore | ✅ | `pg_backup.sh`/`pg_restore.sh` exist and a full dump→restore round trip was executed and verified this audit (§16). |
| AI. Deployment | ⚪ | `docker-compose.prod.yml` exists; not deployed/smoke-tested in this pass. |
| AJ. Environment config | ✅ | Boot-time `model_validator`s fail loudly on missing/invalid CORS, SMTP, JWT, KMS/PII-key config outside development (`settings.py`, read in full, §10). |
| AK. Data retention | ⚪ | No retention/purge job found for `idempotency_key` (documented as a known follow-up) or `audit_log`; not otherwise assessed. |
| AL. Performance | ⚪ | Only a single-request health-check latency sampled (2.2ms); no load test executed (§18). |
| AM. Load/concurrency | 🟡 | Deterministic, code-level concurrency tests exist and were read in full for leave-balance races and attendance-sweep lock scope; no multi-user load test executed. |
| AN. Disaster recovery | 🟡 | Backup/restore mechanism proven (AH); no documented/tested RPO/RTO figure, no failover test. |
| AO. Payroll handoff contract | 🟡 | See §17 — materially improved, two concrete gaps remain. |

---

## 7. Critical Findings (P0/P1)

### FINDING-01 — Unhandled exceptions are never logged, metered, or alerted on

| | |
|---|---|
| Severity | 🟠 **P1 — production blocker** |
| Area | AB/AC — error handling, observability |
| Classification | TECHNICAL FINDING |

**Description.** The global catch-all exception handler returns a clean `500 INTERNAL_ERROR`
envelope to the client and discards the exception without logging it anywhere.

**Evidence** — `apps/api/src/hrms/core/errors/handlers.py:119-126`:

```python
@app.exception_handler(Exception)
async def unhandled_exception_handler(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    # Sentry hook lands here in a later sprint (Document 13 §3).
    _ = exc
    return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")
```

No `logger.exception(...)`, no `structlog` call, no re-raise for an outer middleware to catch.
`structlog` is configured (`core/observability/logging.py`) and used elsewhere in the codebase, so
this is not a missing-infrastructure problem — the hook into it was deliberately left for later
("Sentry hook lands here in a later sprint") and nothing fills the gap in the meantime. Confirmed
by reading `app.py`'s full middleware stack (lines 70-140): no try/except-with-logging ASGI
middleware wraps `call_next` either.

**Reproduction.** Any unhandled exception in any route — a bug, a third-party library raising an
unexpected type, a `None` where code assumes a value — reaches this handler and disappears.

**Failure scenario.** A production incident (e.g., a null-pointer-style bug in a rarely-hit branch
of payroll calculation, or an object-storage outage surfacing as an unexpected exception type) is
invisible: no log line carries the request ID, the stack trace, the route, or the company. The only
symptom is a client-reported `500` with no way to correlate it to server-side state. This directly
contradicts the audit's own observability success criterion ("why did it fail?").

**Affected users/data.** Every tenant; no data corruption, but zero diagnosability for any
unhandled-exception-class incident.

**Root cause.** The handler was stubbed out with `_ = exc` as a placeholder for a planned Sentry
integration and never got a logging fallback in the interim.

**Recommended remediation.** Add `logger.exception("unhandled_exception", request_id=..., path=...,
method=...)` (or equivalent structlog call) inside `unhandled_exception_handler` before building
the response. This is a single-function, zero-risk fix — it does not change the response contract.

**Required regression test.** Assert (via a captured log handler / `caplog` or a structlog capture
fixture) that a route raising an arbitrary `Exception` produces one error-level log entry carrying
the request ID, in addition to the existing `500` response assertion.

---

### FINDING-02 — Critical and high-severity vulnerabilities in frontend production dependencies

| | |
|---|---|
| Severity | 🟠 **P1 — production blocker** |
| Area | AE — dependencies / supply chain |
| Classification | SECURITY FINDING |

**Evidence** — `npm audit --omit=dev --json` in `apps/web`, reproduced this audit:

```
next     | critical | 9.3.4-canary.0 - 16.3.0-preview.10 |
  "Next.js self-hosted applications vulnerable to DoS via Image Optimizer remotePatterns configuration"
  "Next.js HTTP request deserialization can lead to DoS when using insecure React Server Components"
  "Next.js: HTTP request smuggling in rewrites"
postcss  | high     | <=8.5.22 |
  "PostCSS has XSS via Unescaped </style> in its CSS Stringify Output"
  "PostCSS: Arbitrary file read and information disclosure via attacker-controlled sourceMappingURL in CSS comments"
nanoid   | high     | <3.3.18 |
  "nanoid: custom generators can loop indefinitely when size is zero"
```

`package.json` pins `"next": "^14.2.28"`; the resolved version is `14.2.35`
(`npm ls next` → `next@14.2.35`). PostCSS resolves to two versions in the tree
(`postcss@8.4.31` under Next's own dependency, `postcss@8.5.25` as this project's direct
devDependency) — both are within the vulnerable range.

**Failure scenario.** HTTP request smuggling and DoS vectors are exploitable by any
network-reachable client against the production Next.js server, without authentication.

**Required fix.** Bump `next` to a patched 14.x release (or the current stable line) and `postcss`
to >8.5.22; re-run `npm audit --omit=dev` to confirm zero critical/high in the production tree.
This audit does not perform the upgrade (Rule: no business code changes) — flagged for the
remediation pass.

**Required regression test.** CI `npm audit --omit=dev` gate (currently absent from `ci.yml`) that
fails the build on any new critical/high production-dependency vulnerability.

---

### FINDING-03 — Two list endpoints have no pagination, limit, or bound of any kind

| | |
|---|---|
| Severity | 🟡 **P2** (escalates to P1 at scale — flagged here because it is a clean, provable gap in an otherwise well-paginated API) |
| Area | 34 — data scale / pagination |
| Classification | TECHNICAL FINDING |

**Evidence** — `apps/api/src/hrms/modules/account_invite/router.py:47-54`:

```python
@router.get("/users", status_code=status.HTTP_200_OK)
async def list_users(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[DataScope, Depends(require_permission(SETTINGS_USER_MANAGE))],
    service: Annotated[AccountInviteService, Depends(get_account_invite_service)],
) -> ListEnvelope[UserSummary]:
    data = await service.list_users(tenant.company_id)
```

and `apps/api/src/hrms/modules/onboarding/router.py:81-88`:

```python
@router.get("/onboarding-cases", status_code=status.HTTP_200_OK)
async def list_onboarding_cases(
    ...
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> ListEnvelope[OnboardingCaseRead]:
    data = await service.list_cases(tenant.company_id, status=status_filter)
```

Neither accepts `page`/`page_size`/`limit` of any kind; both return every row for the company in
one response. Contrast with the rest of the API: `grep` across all routers shows `PageParams` or an
explicit `limit:` parameter present in every other list-capable router except these two (and
`attendance`'s already-documented W2 finding, below).

**Failure scenario.** A company with several thousand users (one row per employee with login
access) or several thousand onboarding cases (a company that imports its whole historical
workforce into the system) gets a single unbounded JSON response — large payload, elevated DB and
network load, and a straightforward (if not security-critical) resource-exhaustion vector.

**Related, already-documented, open finding** (not re-opened here, re-confirmed current):
`ATTENDANCE_MODULE_AUDIT.md` W2 — `GET /attendance/days` and `/attendance/punches` are unbounded
when no date range is supplied. Confirmed still true by reading `attendance/router.py:861-888`.

**Recommended remediation.** Add `PageParams`-based pagination to both endpoints, matching the
pattern used elsewhere (e.g. `employee/router.py`'s list endpoints).

**Required regression test.** A test creating 150+ users/cases asserts the endpoint returns a
bounded page and a `meta` pagination envelope rather than all 150+ rows.

---

### FINDING-04 — `account_invite` and `onboarding_token` have `company_id` but no RLS, and no documented reason (unlike two sibling tables that do)

| | |
|---|---|
| Severity | 🟡 **P2** (defense-in-depth gap, not a proven exploitable leak — application-level filtering was independently confirmed present) |
| Area | D — RLS |
| Classification | SECURITY FINDING |

**Evidence** — live query against `hrms_app` (reproduced this audit):

```sql
select c.relname, c.relrowsecurity, c.relforcerowsecurity
from pg_class c join pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and c.relkind='r';
```

Of ~100 tenant-shaped tables, four carry a `company_id` column but `relrowsecurity = false` (no
policy, confirmed via `pg_policy` returning 0 rows for `account_invite`):
`account_invite`, `refresh_token`, `session`, `onboarding_token`. Every other tenant table in the
schema (71 checked) has both `relrowsecurity` and `relforcerowsecurity = true`.

**Split by documentation status — checked directly against `docs/architecture/
POSTGRES_RLS_ROLE_MIGRATION_PLAN.md`, not assumed:**

- **`refresh_token`, `session`** — **documented, deliberate exceptions.** That architecture
  document's own live-query table (§3) explicitly lists both as correctly un-policied: pre-tenant-
  context token/session lookups where the RLS GUC may legitimately be unset, in the same category as
  `permission`/`plan`/`plan_feature` (global catalogs) and `user` (scoped transitively via
  `user_company`). This is a reasoned, written design decision, not a gap — lower residual concern.
- **`account_invite`, `onboarding_token`** — **not mentioned anywhere in that document.** Its §3
  table (written when the schema had 32 tables, 19 with RLS) predates both tables' addition to the
  schema entirely, and no later document extends the exception list to cover them. `account_invite/
  repository.py` was confirmed (grep) to filter by `company_id` in every query path read, so there is
  real application-level protection — but it is **undocumented and unreviewed**: nothing establishes
  that this was a deliberate choice rather than an oversight when these two tables were added, and
  there is no database-level backstop if a future code path forgets the filter.

**Recommended remediation.** For `account_invite`/`onboarding_token` specifically: either (a) add RLS
policies matching the standard `tenant_isolation` pattern used by the other 71 tables, carving out
only the specific pre-tenant-context paths that need it (onboarding-token lookup by an unauthenticated
applicant), mirroring the `login_lookup_user_companies` `SECURITY DEFINER` pattern already used for
`user_company`; or (b) extend `POSTGRES_RLS_ROLE_MIGRATION_PLAN.md`'s exception list to explicitly
cover them, with the same reasoning given for `refresh_token`/`session`, so the decision is reviewed
and recorded rather than silent. `refresh_token`/`session` need no code change — only, optionally, a
cross-reference note added to this audit's finding so the documented decision is easy to find.

**Required regression test.** A raw-connection cross-tenant SELECT test against each of the four
tables (same pattern as `test_rls_runtime_role.py`'s C/D/E/F assertions), proving the chosen
remediation actually closes the gap.

---

### FINDING-05 — L11/L12: leave can be booked outside employment, and survives a rehire as one ledger

| | |
|---|---|
| Severity | 🟡 **P2, PRODUCT DECISION BLOCKING** — not a bug; an explicitly-identified, still-open gap |
| Area | K — Leave, G — Employee lifecycle |
| Classification | PRODUCT DECISION (re-confirmed TECHNICAL FINDING) |

**Evidence.** `docs/testing/LEAVE_MODULE_AUDIT.md` L11/L12 (current file, read in full) documents
both as open: leave submission does not consult `EmploymentService.check_employment_coverage` —
confirmed by reading `leave/service.py` end to end for the submit path (the coverage call at
`leave/service.py:1159` is reached from a different method; the submit flow was traced separately
and does not call it) — and a leave balance belongs to `(company_id, employee_id)`, not to a
specific employment spell, so a rehired employee's old balance is still live.

**Why this matters for Payroll.** Attendance already rejects punches outside employment
(`A2`, `attendance/calculation.py`). Leave not enforcing the same boundary means a leave-driven paid
day can exist for a date Attendance would refuse — a direct cross-module inconsistency Payroll would
inherit silently (§13).

**Required decision, not a guess.** `PAYROLL_BUSINESS_DECISIONS.md` resolves decisions 1-20 but
explicitly does **not** cover L11/L12 (confirmed: no matching decision ID in that document).

**Recommended remediation.** Product decision first (pick one of the three options
`LEAVE_MODULE_AUDIT.md` already lays out), then wire `EmploymentService.check_employment_coverage`
into the leave submit path the same way Attendance and the termination guard already use it
(`employee/coverage.py` is already shared infrastructure for exactly this — see §9).

---

## 8. P2 Findings

| ID | Area | Finding | Evidence |
|---|---|---|---|
| P2-01 | AE Dependencies | Backend `urllib3 2.7.0` has 3 known CVEs (PYSEC-2026-4175/4176/4177), fix in 2.8.0 | `pip-audit`, reproduced this audit |
| P2-02 | Y Database integrity | `leave_ledger`'s employee FK is on `employee.id` alone, not composite `(company_id, employee_id)` — app-level rejection of a foreign id exists, DB-level does not | `LEAVE_MODULE_AUDIT.md` "Not done" list, cross-checked against current schema read |
| P2-03 | P Notifications | No transactional outbox / notification abstraction exists anywhere in the repository; six leave events from decision 17 are deferred | `celery_app.py` comments + `leave/service.py`; confirmed no `outbox` table in migration list |
| P2-04 | AK Data retention | `idempotency_key` rows are never purged (documented as a known follow-up in the LM-03 section of `LEAVE_MODULE_AUDIT.md`); no retention job found for `audit_log` either | Grep for a cleanup task against `idempotency_key`/`audit_log` — none found |
| P2-05 | S API correctness | `GET /attendance/days` issues "one breaks query per row" per the existing W2 finding — re-confirmed current, not re-measured this pass | `ATTENDANCE_MODULE_AUDIT.md` W2 |
| P2-06 | U Mobile | Mobile self-punch sends no `idempotency_key` (M1, open); manual punch remains available next to face punch (M2, open product decision) | `ATTENDANCE_MODULE_AUDIT.md`, re-confirmed as still listed open |

## 9. P3 Findings

| ID | Area | Finding | Evidence |
|---|---|---|---|
| P3-01 | Z Concurrency | Approval-versus-attendance-period-finalization race (L13) — "check-then-act with no shared lock, a narrow window exists" — documented informational, not re-tested this pass | `LEAVE_MODULE_AUDIT.md` L13 |
| P3-02 | W1/W2 (web) | On-behalf employee pickers load only the first 100 employees (web); `/attendance/days`/`/punches` unbounded without a date range | `ATTENDANCE_MODULE_AUDIT.md` W1/W2, re-confirmed in current router code |
| P3-03 | Comp-off | Expiry sweep skips a partly-spent credit — documented, intentional heuristic (LD-14), not a defect | `ATTENDANCE_MODULE_AUDIT.md` C1 |
| P3-04 | CI | ESLint is `continue-on-error: true` in CI (7 pre-existing violations, documented as a deliberate initial policy) | `.github/workflows/ci.yml`, read in full |
| P3-05 | Moderate deps | 2 moderate-severity npm advisories in devDependencies only (not in the production bundle) | `npm audit` full (non-`--omit=dev`) run |

## 10. UNVERIFIED Items

This section is mandatory per the audit's own rules — listed here rather than silently assumed:

- **Full backend suite pass/fail count** — run was in progress at report-writing time; see §5a for
  the final figure once appended, or treat as UNVERIFIED if that section still shows the
  placeholder.
- **Mobile app** — analyzer, unit/widget tests, release build, and any on-device behavior. No
  Flutter/Dart SDK available in this environment. 28 test files exist and were counted, not
  executed.
- **Real Face++ (Luxand/FACEPP) liveness/match against a live camera feed on a real device** — out
  of reach of this environment; `ATTENDANCE_MODULE_AUDIT.md` F1 already flags this as not executed.
- **Load/scale testing at 100/500/1,000/5,000/10,000 employees** — not performed. Only a
  single-request health-check latency (2.2ms) was sampled.
- **A manual, this-session brute-force/login-rate-limit exhaustion probe against a live server** —
  not performed directly; `test_auth_security.py` exists and passed as part of the full suite run
  (§5a), which is good evidence the coded behavior is correct, but is not the same as an
  independent, ad-hoc exploit attempt against a running instance.
- **A real disaster-recovery drill** (full stack rebuild from backups under time pressure, RPO/RTO
  measurement) — only the Postgres dump/restore mechanism itself was proven (§16); MinIO restore,
  full-stack recovery timing, and off-site backup delivery were not exercised.
- **Production deployment smoke test** — `docker-compose.prod.yml` was read, not deployed.
- **RBAC privilege-escalation matrix for every role × every endpoint, company-wide.**
  `test_route_authorization_matrix.py` (§5a) auto-covers this exhaustively, but only for three
  modules (`organisation`, `employee`, `employee_import` — its own `_MODULES` constant); Leave has
  its own, separately-written `test_leave_rbac_matrix.py` (also passed, §5a); **Attendance and
  Payroll have no equivalent introspection-based matrix test** — their permission gates are covered
  by ordinary per-endpoint tests (also passed) but not by the same exhaustive, auto-discovering
  approach. Extending `test_route_authorization_matrix.py`'s `_MODULES` tuple to include
  `attendance` and `payroll` would close this cheaply and is a good §20 candidate.

## 11. Cross-Module Findings

**Leave can produce a paid day Attendance would refuse to produce (FINDING-05 / L11).** This is the
one cross-module inconsistency this audit found direct evidence for: Attendance's punch/regularization
paths and the termination-access-revocation sweep all route through
`EmploymentService.check_employment_coverage` (confirmed via grep across `attendance/service.py:6334`
and `employee/service.py:1568-1582`); Leave's submit path does not. A leave application dated before
joining or after the last working day is accepted, auto-approved (for an `AUTO` chain), and debited
today — the exact case Attendance already has a named, tested rule against (`A2`).

**Positive cross-module finding: the leave-approval-vs-period-finalization race is now closed.**
`LEAVE_MODULE_AUDIT.md`'s "Additional defects found and fixed while writing the tests" section
documents LM-18 — a leave approval parked between recalculation and commit while a period finalized
could produce an approved, debited leave inside a frozen summary that counted 0 leave days. The fix
(a shared advisory lock on `attendance-period-close:{company}`, taken by every leave
approval/reversal, always acquired after the per-employee date lock) was read in
`core/db/locks.py` and is exactly the kind of cross-module lock ordering a payroll handoff needs.
This is real, verified remediation of a cross-module defect, not re-asserted history.

## 12. Security Findings

Summarized from §7/§8; full detail there. Net new this audit, not carried from prior documents:
FINDING-01 (silent failures), FINDING-02 (dependency CVEs — both backend and frontend), FINDING-04
(RLS gap on 4 tables). Confirmed still-clean from prior work: security headers, CSP, HSTS
conditional-on-HTTPS, CORS/SMTP/JWT/KMS fail-safe boot validation, no secrets in git history or
tracked files, append-only audit log at the database grant level.

## 13. Data Integrity Findings

Carried forward from `DATA_INTEGRITY_AUDIT.md` (2026-09-10) and independently re-verified against
the current schema this audit:

- **Confirmed still present and correct:** GiST exclusion constraints on employment, policy
  versions, policy assignments, attendance periods, and shift versions; 7 append-only tables
  (`punch`, `leave_ledger`, `audit_log`, and four `*_action` timelines); no `ON DELETE CASCADE` on
  any HR-fact table; money stored as integer minor units throughout.
- **Confirmed fixed since 2026-09-10:** the leave-balance concurrency hole (now
  `pg_advisory_xact_lock`-protected, §14) and attendance reproducibility (now carries
  `engine_version`, `apps/api/src/hrms/modules/attendance/models.py:704`).
- **Still open:** `leave_ledger`'s employee FK is not composite with `company_id` (P2-02).

## 14. Concurrency Findings

Two test files were read in full this audit as direct, reproducible evidence (not re-executed to
completion in the full-suite run at report time, but their design was independently inspected
line-by-line and is sound):

- **`test_leave_balance_races.py`** — forces a deterministic interleaving between a sweep's balance
  read and a concurrent leave approval via a monkeypatched one-shot delay placed *after* the
  sweep's read (exactly the window the lock exists to close), rather than relying on timing luck.
  This is methodologically correct concurrency testing.
- **`test_sweep_concurrency.py`** — proves (with printed, comparable timings) that the nightly
  attendance sweep no longer holds a whole company's row locks in one transaction (the historical
  defect: "a punch for an employee the sweep had already processed waited the sweep's whole hold,
  4.04s against a 4.0s hold"); the fix is one transaction per employee-date.

**Not independently re-verified this pass:** the full race matrix the audit brief requests (13
specific scenarios in its §19) — only the two above were read/confirmed. The remainder rely on the
full suite completing (§5a) and the existing, uncommitted test files (`test_leave_idempotency.py`,
`test_leave_lock_timeouts.py`, `test_leave_ledger_safety.py`) which were not opened individually in
this pass.

## 15. Performance Findings

Minimal — explicitly UNVERIFIED for anything beyond this:

```
curl -s -o /dev/null -w "health: %{http_code} %{time_total}s\n" http://localhost:8000/health
health: 200 0.002164s
```

A single health-check request against the already-running dev server. No list-endpoint timing, no
N+1 measurement, no scale test was performed (§10). `ATTENDANCE_MODULE_AUDIT.md` S1's own measured
figure (sweep lock hold reduced from "a whole company" to "0.07-0.10s per employee-date") is the
only load-relevant number available from prior work, re-cited not re-measured.

## 16. Operational / SRE Findings

- **Backup/restore: proven, this audit.** `docker exec hrms-postgres pg_dump -Fc -U hrms hrms_dev`
  produced a clean 608KB dump (exit 0); restored into a disposable `postgres:16-alpine` container
  via `pg_restore --no-owner --no-privileges` (exit 0); table count (104) and `company` row count
  matched source exactly post-restore. Both disposable containers were removed afterward (§22).
- **Migrations: proven, this audit.** All 111 Alembic revisions applied cleanly to an empty,
  freshly-provisioned database (init scripts + `hrms_app` role creation, then `alembic upgrade
  head`), reproducing what CI already does on every run. Zero errors.
- **Observability gap: FINDING-01.** The single largest operational risk found this audit — not
  "logging is thin," but "a whole class of production incident produces no log line at all."
- **CI is now a real gate, not a false one.** The prior audit's 🔴 BLOCKER TST-001 ("CI does not run
  the integration or security test suites... 62 of 87 test files require a live PostgreSQL... In CI,
  none of the 783 integration tests can execute") is resolved: `.github/workflows/ci.yml` now
  provisions Postgres, Redis, and MinIO as real services, verifies the `hrms_app` role's
  `NOSUPERUSER`/`NOBYPASSRLS` attributes as an explicit CI step before trusting the RLS suite, and
  runs `tests/integration tests/security` with real infrastructure. Read in full this audit.

## 17. Payroll Handoff Readiness

| Input | Source | Owner | State at audit | Immutability point | Audit trail | Idempotency | Correction path |
|---|---|---|---|---|---|---|---|
| Employee identity | `employee` table | Employee module | Stable | N/A (mutable master data) | `audit_log` | N/A | Standard update |
| Employment spell | `employment` | Employee module | GiST-enforced non-overlap | Spell itself immutable once terminated (`last_working_day` set) | `audit_log` | N/A | New spell (rehire) |
| Compensation | `employee_compensation` | Employee module | Effective-dated | New revision, not update | `audit_log` | N/A | New revision |
| Attendance days | `attendance_day` | Attendance module | `engine_version`-stamped (gap closed) | Locked at period finalize | `attendance_period_action` | Punch idempotency-key (now cross-employee-safe, `7ba4ce7`) | Regularization → recompute |
| Paid/payable days | `attendance_period_summary.paid_days`/`payable_days` | Attendance module | **Fields now exist** (closes prior PAY-002/PAY-004 BLOCKERs) | Frozen at `finalize` | `attendance_period_action` | N/A (derived, recomputed) | Reopen (gated, PD-4) |
| Leave (paid days/LOP) | `leave_ledger` + `leave_day_projection` | Leave module | Append-only ledger; balance now lock-protected | Ledger rows immutable; closed-period adjustment refused (`LEAVE_LEDGER_PERIOD_CLOSED`) | `leave_application_action` + `audit_log` (with PII redaction, decision 19) | `Idempotency-Key` on adjustments/encashments/applications | New offsetting ledger entry |
| Period state | `attendance_period.status` | Attendance module | `OPEN → READY → CLOSED` | `CLOSED` is the payroll-safe state | `attendance_period_action` | N/A | Reopen, gated |
| Legal entity / statutory profile | `legal_entity`, `employee_statutory` | Organisation/Employee | Per-entity payroll grain decided (BUS-007) | N/A | `audit_log` | N/A | New revision |

**Can Payroll safely consume this without reconstructing or guessing business state?** — **Mostly
yes, with two named exceptions:**

1. **L11/L12 (FINDING-05)** — until resolved, a leave-driven paid day can exist for a date
   Attendance's own employment-boundary rule would reject. Payroll reading `paid_days` at face value
   inherits this silently.
2. **PD-4's input-change detection** (`PayRunService._assert_inputs_unchanged`, cited in
   `PAYROLL_BUSINESS_DECISIONS.md`) was read as implemented in the business-decisions document
   cross-reference but not independently re-verified against the current `payroll/service.py` in
   this pass (payroll internals are out of scope; this is a boundary check only, flagged as
   UNVERIFIED rather than assumed).

Everything else in the handoff chain — immutability points, audit trail, idempotency, correction
path — is now coherently designed and, for the attendance/leave side, backed by real tests this
audit read in full. This is a materially stronger handoff contract than the 2026-09-10 baseline,
which had **five 🔴 BLOCKERs** directly in this table (PAY-001 through PAY-004 plus TST-001); none
of those five reproduce against the current code (§19 confirms each is closed).

## 18. Production Deployment Blockers

In order of what must close before a **production** (not just "feature-complete") launch of
everything-before-Payroll:

1. **FINDING-01** — unhandled-exception logging. Blocks production because it blocks incident
   response for any class of bug this audit, or any audit, cannot exhaustively rule out in advance.
2. **FINDING-02** — frontend dependency CVEs (critical DoS/smuggling vector, network-reachable,
   unauthenticated).
3. **FINDING-04** — RLS gap on 4 tables. Lower urgency than 1-2 (app-level filtering is confirmed
   present), but should close before the platform is trusted at scale with real tenant data.
4. **FINDING-03** — unbounded list endpoints. Real but lower urgency pre-scale; still a clean fix.
5. **FINDING-05 (L11/L12)** — blocks trusting Leave's `paid_days` contribution for Payroll
   specifically; does not block the rest of pre-Payroll production use.

**Not a blocker, but should be resolved before Payroll is switched on:** the PD-4 input-change
detection re-verification noted in §17.

## 19. Required Remediation Order

**P1 (before production):**
1. FINDING-01 — add logging to the catch-all exception handler.
2. FINDING-02 — upgrade `next`/`postcss` in `apps/web`, re-run `npm audit --omit=dev`.

**P2 (before production, lower urgency than P1):**
3. FINDING-04 — decide and implement RLS policy or documented-exception status for `account_invite`,
   `refresh_token`, `session`, `onboarding_token`.
4. FINDING-03 — paginate `GET /users` and `GET /onboarding-cases`.
5. P2-01 — upgrade backend `urllib3` to 2.8.0.
6. FINDING-05 (L11/L12) — product decision, then wire `EmploymentService.check_employment_coverage`
   into leave submission. **Required before Payroll depends on Leave's `paid_days`/LOP figures.**

**P3 (track, not blocking):**
7. P2-02 through P2-06, P3-01 through P3-05 as listed in §8/§9.

**Do not start Payroll feature work against a non-CLOSED period or before FINDING-05 is resolved** —
this repeats the audit brief's own instruction and is independently justified by §17's analysis.

## 20. Recommended Regression Suite

Tests that should become permanent, CI-gated regression coverage (several already exist and only
need to stay in CI's path; three are new, specific to this audit's findings):

| Test | Status | Purpose |
|---|---|---|
| `tests/security/test_rls_runtime_role.py` | **Exists, in CI** | Proves cross-tenant isolation at the database level, not just app code |
| `tests/integration/.../test_leave_balance_races.py` | **Exists, in CI** | Deterministic balance-race regression |
| `tests/integration/.../test_sweep_concurrency.py` | **Exists, in CI** | Lock-scope regression (whole-company vs. per-row) |
| `tests/integration/.../test_punch_after_last_working_day.py` | **Exists, in CI** | Employment-boundary regression (A2) |
| `tests/integration/test_route_authorization_matrix.py` | **Exists, in CI** | Auto-discovering 401/403/scope matrix — covers every route added to `organisation`/`employee`/`employee_import` automatically |
| **Extend `test_route_authorization_matrix.py`'s `_MODULES`** | **Cheap, high-value — add `attendance`, `payroll`** | Same auto-discovery coverage currently missing for those two modules (§10) |
| **New: unhandled-exception logging test** | **Missing — add per FINDING-01** | `caplog`/structlog-capture assertion on the catch-all handler |
| **New: unbounded-list regression** | **Missing — add per FINDING-03** | 150+ rows → paginated response, both endpoints |
| **New: cross-tenant raw-SELECT on the 4 no-RLS tables** | **Missing — add per FINDING-04**, once remediation lands | Same pattern as `test_rls_runtime_role.py` C/D/E/F |
| **New: `npm audit --omit=dev` / `pip-audit` as a CI gate** | **Missing — add per FINDING-02/P2-01** | Fail the build on new critical/high production-dependency CVEs |
| **New: leave-outside-employment rejection** | **Missing — add once FINDING-05 decision lands** | Mirrors `test_punch_after_last_working_day.py` for Leave |

## 21. Final Verdict

# READY WITH CONDITIONS

**Conditions (all must close before this platform carries production traffic for everything before
Payroll):**

1. FINDING-01 (unhandled-exception logging) — fixed and regression-tested.
2. FINDING-02 (frontend critical/high dependency CVEs) — upgraded and re-scanned clean.

**Conditions before Payroll specifically depends on this foundation's output:**

3. FINDING-05 / L11-L12 — product decision made and implemented.
4. FINDING-04 and FINDING-03 — resolved or explicitly, durably accepted as documented risk.

Everything else in this report is either a confirmed strength (RLS proven at the database level,
migrations clean end-to-end, backup/restore proven, CI's prior BLOCKER-level test gap closed,
concurrency defects found and fixed with deterministic tests) or an explicitly scoped UNVERIFIED
item (§10) that a future pass — with a Flutter toolchain, a longer time budget for the full 2,330-test
backend suite, and load-testing tooling — should close before a **final**, unconditional verdict is
given.

## 22. Change Control

**Files changed by this audit:** `docs/audits/PRE_PAYROLL_PRODUCTION_READINESS_FINAL_AUDIT.md`
(this file — created). **No other file in the repository was modified.**

**Database changes:** none to the live dev database's schema or business data. Full account of
every command that touched any database:

| Action | Target | Effect |
|---|---|---|
| `psql` SELECT queries (RLS/role inspection, GUC probing) | live dev DB (`hrms_dev` @ 5433), as `hrms_app` and `hrms` | Read-only |
| `UPDATE`/`DELETE`/`INSERT` RLS probes (3 statements) | live dev DB, as `hrms_app`, scoped to a non-existent target row | **Zero rows affected** (proved the isolation, changed nothing) — `rowcount` confirmed 0 for each |
| `pg_dump -Fc` | live dev DB, via `docker exec hrms-postgres` | Read-only; output written to this session's scratchpad, deleted after use |
| **`alembic upgrade head` (first invocation)** | **Unintentionally the live dev DB**, not the intended disposable container — `alembic/env.py` falls back to reading `MIGRATIONS_DATABASE_URL` from the repo's `.env` file when the shell environment variable alone is set for `DATABASE_URL` but not `MIGRATIONS_DATABASE_URL`. Disclosed in full: this was a configuration mistake during the audit, not a planned action. | **No-op** — the dev DB was already at head (`20261013090000`); verified unchanged before and after. No migration ran, no schema or data changed. The command was immediately re-run with `MIGRATIONS_DATABASE_URL` explicitly pointed at a disposable container for the intended empty-DB test. |
| `alembic upgrade head` (corrected) | disposable `postgres:16-alpine` container (`audit-pg-fresh`, port 5555) | Created 104 tables on an empty, purpose-built database; container destroyed after |
| `pg_restore` | disposable `postgres:16-alpine` container (`audit-pg-restore`, port 5556) | Restored the dump taken above; container destroyed after |
| `pytest` (unit + integration + security) | live dev DB, via the app's existing test configuration (`tests/conftest.py` connects as the `hrms` owner role, same as every prior test run in this repository) | Tests create and tear down their own company-scoped fixtures, per the suite's existing, pre-audit design — not an audit-introduced behavior |

**Migrations:** none authored. **Commits:** none. **Pushes:** none. **Branch/checkout changes:**
none — remained on `main` throughout, uncommitted working-tree state untouched.

**Two disposable Docker containers** (`audit-pg-fresh`, `audit-pg-restore`) were created and
removed (`docker rm -f`) during this audit for the migration and backup/restore tests; neither
persists.

---

# Final Remediation and Re-Audit (2026-10-05, same day)

**Scope of this pass:** close FINDING-01 through FINDING-05 above. Payroll was not touched, not
implemented further, and no Payroll file was modified. No business rule was invented — FINDING-05
specifically was closed by re-reading code that was *already present* in the working tree (see its
section below), not by writing a new one. Changes were kept finding-specific; no unrelated module
was refactored.

## FINDING-01 — unhandled exceptions are now logged

- **Original problem.** `unhandled_exception_handler` discarded the exception (`_ = exc`) with no
  log line, no metric, no trace — a production 500 left zero server-side evidence.
- **Root cause.** A stubbed placeholder for a planned Sentry hook, never backed by a logging
  fallback in the meantime.
- **Fix.**
  - `core/errors/handlers.py` — the handler now calls `_logger.exception("unhandled_exception", ...)`
    with `request_id`, `http_method`, `http_path`, `exception_type`, `exception_message`, and
    `company_id`/`user_id` when a tenant context exists (wrapped so a route with no context — the
    common pre-auth case — doesn't itself crash the handler). The client-facing envelope (clean
    500, `INTERNAL_ERROR`, no internals) is byte-for-byte unchanged.
  - `core/observability/logging.py` — added `structlog.processors.format_exc_info` to the
    processor chain. Without it, `.exception()`'s `exc_info=True` flag never actually renders a
    traceback string into the JSON line — this was a second, independent gap behind the first:
    even a naive `logger.exception(...)` fix would have shipped a log line with no stack trace.
  - `core/celery_app.py` — added a company-wide `task_failure` signal handler
    (`_log_unhandled_task_failure`), so a background task that raises and isn't retried also
    leaves a structured line (`celery_task_failed`) even in modules with no `on_failure` of their
    own (Leave's `_LeaveTask` already had one; Attendance/Employee/Organisation/`employee_import`
    did not) — closing requirement 10 ("work for ... relevant background jobs"), not just the API.
- **Files changed.** `apps/api/src/hrms/core/errors/handlers.py`,
  `apps/api/src/hrms/core/observability/logging.py`, `apps/api/src/hrms/core/celery_app.py`.
- **Tests added.** `tests/unit/core/test_unhandled_exception_logging.py` (2),
  `tests/unit/core/test_celery_task_failure_logging.py` (1). Assert against real captured stdout
  (`capfd`, file-descriptor level) rather than `structlog.testing.capture_logs()` — the latter
  looked correct in isolation but **failed non-deterministically when run inside the full 2,330+
  test suite** (reproduced and diagnosed during this pass, §below): `configure_logging()`'s
  `cache_logger_on_first_use=True` means the handler's module-level logger resolves against
  whichever processor chain is active the first time any test anywhere exercises it — almost
  always long before a unit test file runs — so `capture_logs()`'s later `structlog.configure()`
  override can't reach an already-cached logger. The real JSON line was always correct (confirmed
  from the full run's captured-stdout output); only the test's own capture mechanism was wrong.
  Rewritten against `capfd`, which reads the real OS pipe and is immune to this.
- **Targeted result.** 3/3 passed, isolated and inside two different full-suite orderings
  (deliberately re-run after integration tests that trigger `configure_logging()` first, to prove
  the fix is order-independent — see "re-audit" below).
- **Full regression result.** Part of the 2,361-test full run, §below — 0 failures.
- **Final status.** CLOSED.

## FINDING-02 — critical/high frontend dependency CVEs; backend urllib3 (P2-01)

- **Original problem.** `next@14.2.35` carried a critical DoS/HTTP-request-smuggling advisory
  family; its bundled `postcss@8.4.31` (high) and `nanoid@3.3.17` (high, via postcss) came along
  for the ride. Backend `urllib3 2.7.0` had 3 known CVEs (PYSEC-2026-4175/4176/4177).
- **Investigation (per package, not blind).**
  - `next`: the smuggling advisory's fixed range is `>=15.5.13`; the RSC-deserialization DoS
    needs `>=15.0.8`; the Image-Optimizer DoS needs `>=15.5.10`. A same-major-adjacent fix
    (`14.2.x`) does not exist — every patched version is 15.x or later. The **next** complication:
    Next pins its own internal `postcss` dependency to an *exact* version in every release
    (verified by querying the registry across `15.3.0` through `16.2.0` — all pin `8.4.31`,
    inside the vulnerable `<=8.5.22` range); the bundled copy only moves to a non-vulnerable
    version (`8.5.23`) starting at **`16.3.0`**. A `14 -> 15` patch therefore closes the critical
    Next.js advisory but leaves the high PostCSS one open regardless of this project's own
    `postcss` devDependency version (next's nested copy is what `npm audit` flags). Closing all
    three findings required `next >= 16.3.0`; `16.3.8` is the current `latest` dist-tag (a real
    stable release, not a prerelease — `16.0.0`-`16.2.x` exist only as `-beta`/`-canary` tags,
    confirmed via `npm view next dist-tags`).
  - `nanoid`: fixed transitively once `postcss` moves past `3.3.17`'s dependency on it.
  - `urllib3`: no investigation needed beyond the existing CVE IDs — `2.8.0` is the fix.
- **Upgrade performed.** `next` `14.2.35 -> 16.3.8`; `postcss` (project devDependency)
  `8.4.49 -> 8.5.29`; `urllib3` `2.7.0 -> 2.8.0` (`uv lock --upgrade-package urllib3`). **Nothing
  else was bumped speculatively.**
- **Consequences absorbed, not deferred.**
  - Next 16 defaults `next build`/`next dev` to Turbopack, which fails this specific app with
    `Invariant: no direct app page entry found for /_not-found`. Not chased as a Turbopack bug
    report — `--webpack` builds this app's exact pre-upgrade 70-route set cleanly, so
    `package.json`'s `build`/`dev` scripts and CI's "Production build" step now pass it
    explicitly (`next.config.mjs`'s now-inert `eslint.ignoreDuringBuilds` key was also removed —
    Next 16 dropped ESLint-in-build entirely, so the key just produced a warning).
  - `next lint` was removed in Next 16; `eslint-config-next@16` ships only a flat config and
    requires `eslint >= 9`. Migrated: `eslint` `8.57.1 -> 9.39.5`, `.eslintrc.json` ->
    `eslint.config.mjs`, `package.json`'s `lint` script and CI's ESLint step now call `eslint .`
    directly.
  - That same bump's `eslint-plugin-react-hooks@7` ships a new `react-hooks/set-state-in-effect`
    rule that fires on this codebase's very common "fetch in `useEffect`, `setState` on
    completion" pattern. The pre-existing lint backlog went from 7 violations to ~108 as a direct,
    visible consequence — **not fixed** (real frontend code modification, outside a dependency-CVE
    remediation's scope) but not hidden either: documented in the CI step's own comment, and lint
    remains the pre-existing non-blocking (`continue-on-error: true`) check it already was, by the
    same documented policy that made it non-blocking the first time (A12/A8, `docs/devops/CI.md`).
  - Next's auto-upgrade of `tsconfig.json` (`jsx: preserve -> react-jsx`, added `target: ES2017`)
    was accepted — Next 16 requires the automatic JSX runtime; `tsc --noEmit` and the production
    build both depend on it being set this way.
  - React itself did **not** need to move (stayed `^18.3.1` — Next 16 still supports React 18;
    this was verified, not assumed, before starting).
- **Files changed.** `apps/web/package.json`, `apps/web/package-lock.json`,
  `apps/web/next.config.mjs`, `apps/web/eslint.config.mjs` (new), `apps/web/.eslintrc.json`
  (removed), `apps/web/tsconfig.json`, `apps/api/uv.lock`, `.github/workflows/ci.yml`.
- **CI gate added** (the audit's own §20 recommendation): `pip-audit` and
  `npm audit --omit=dev --audit-level=high` were both promoted from `continue-on-error: true`
  (visibility-only) to **blocking**, now that both are clean — closing "No unresolved
  CRITICAL/HIGH production dependency vulnerability unless there is an explicitly documented,
  technically justified exception" as an enforced, not just observed, property going forward.
- **Targeted result.**
  ```
  npm audit --omit=dev            -> found 0 vulnerabilities
  uvx pip-audit -r <export>        -> No known vulnerabilities found
  npx tsc --noEmit                 -> clean
  npm run build (--webpack)        -> succeeds, 70 routes, same route list as pre-upgrade
  ```
- **Full regression result.** Backend 2,361/2,361 (§below); frontend 505/505 (§below, unchanged
  from the pre-upgrade baseline — zero test files needed to change for this upgrade).
- **Final status.** CLOSED. P3-05 (moderate-severity devDependency-only advisories) is unchanged
  and intentionally out of this gate's scope, same as before.

## FINDING-03 — `GET /v1/users` and `GET /v1/onboarding-cases` are now paginated

- **Original problem.** Both endpoints returned every row for the company, unbounded, the only
  two list-capable routes in the API without `PageParams`/`ListEnvelope.pagination` (API-01 had
  already paginated every other Tier 1 endpoint — `/employees`, `/leave-applications`,
  `/policy-assignments`, `/leave-ledger`, shift versions, calendar exceptions/holidays — these two
  were added after that pass and never retrofitted).
- **Investigation.** Current shape: `AccountInviteService.list_users` /
  `OnboardingCaseService.list_cases` returned a plain list with no `limit`/`offset` at the SQL
  layer. Callers: only their own routers — no internal/background caller exists for either, so no
  `page=None` compatibility shim was strictly required, but one was added anyway (`page: PageParams
  | None = None`) to match this codebase's one established convention (`EmployeeService.
  list_employees`) exactly, rather than inventing a second shape.
- **Fix.** Followed the existing `shared/pagination.py` contract precisely — `PageParams`,
  `pagination_params`, `build_pagination_meta`, `ListEnvelope.pagination`, 1-indexed `page`,
  `per_page` capped server-side at 100, a `COUNT(*)` paired query sharing the same predicate as the
  data query (`AccountInviteRepository.count_user_companies_for_company`,
  `OnboardingCaseRepository.count_cases`, the latter factored through a shared
  `_list_conditions` helper so `total` can never disagree with the filtered rows, mirroring
  `LeaveApplicationRepository._filtered_conditions`). Added a stable secondary sort key (`.id`)
  to both so page boundaries are deterministic. `status` filtering on `/onboarding-cases`
  continues to apply before pagination, unchanged. Frontend: `apps/web/src/app/app/users/page.tsx`
  and `.../onboarding/page.tsx` switched from `apiClient.get<T[]>` to `apiClient.getList<T>` with
  a `page` state and `<PaginationControls>`, the exact pattern `app/employees/page.tsx` already
  established. Mobile needed no change — it already discards pagination metadata and reads page 1
  for every other paginated endpoint (`/employees` included); `/users` and `/onboarding-cases` now
  behave identically, not differently.
- **Files changed.** `apps/api/src/hrms/modules/account_invite/{repository,service,router}.py`,
  `apps/api/src/hrms/modules/onboarding/{repository,service,router}.py`,
  `apps/web/src/app/app/users/page.tsx`, `apps/web/src/app/app/onboarding/page.tsx`.
- **Tests added.** `tests/integration/modules/account_invite/test_account_invite_pagination.py`
  (11), `tests/integration/modules/onboarding/test_onboarding_case_pagination.py` (13) — default
  page (first 25), explicit `page`/`per_page`, beyond-final-page (empty, accurate `total`), empty
  dataset, invalid params (`page<1`, `per_page` outside `[1,100]` -> 422), server-max boundary
  (100 accepted), deterministic no-duplicate/no-gap paging across the whole collection, tenant
  isolation (another company's rows never contribute to `total` or appear in any page), `status`
  filter + pagination interaction (onboarding only), and authorization unchanged (403 for a caller
  without the permission, 401 anonymous — pagination params don't bypass either gate).
- **Targeted result.** 24/24 passed.
- **Full regression result.** Part of the 2,361-test full run, §below. Frontend 505/505 unchanged
  (no existing test referenced either endpoint's old shape).
- **Final status.** CLOSED.

## FINDING-04 — `account_invite`/`onboarding_token` RLS: decision B, documented and tested

- **Original problem.** Both tables carry `company_id` but no RLS policy, and — unlike
  `refresh_token`/`session`, which the same gap affects — nothing in the repository's one central
  RLS-exception document (`POSTGRES_RLS_ROLE_MIGRATION_PLAN.md`, written in 2026-08 when the
  schema had 32 tables) ever said so.
- **Investigation before deciding.** Read both tables' own model docstrings
  (`account_invite/models.py`, `onboarding/models.py`), `OnboardingTokenRepository`'s class
  docstring, and `onboarding_token`'s own corrective migration
  (`20260906090000_onboarding_o2`, verified: it explicitly drops a `tenant_isolation` policy an
  earlier migration mistakenly gave the table). The reasoning was already written down, in three
  separate places, by whoever added these tables — just never reflected in the one document the
  audit checks. Confirmed by code read, not assumed: every authenticated query path in both
  repositories filters by `company_id` taken from the resolved `TenantContext`; neither module's
  request schemas (`UserInviteRequest`, `OnboardingCaseCreate`) accept a client-supplied
  `company_id` at all; the only un-scoped lookups (`get_by_hash`) key by `token_hash`, a globally
  unique column, not a per-company one.
- **Decision: B — RLS intentionally not required.** Extended
  `POSTGRES_RLS_ROLE_MIGRATION_PLAN.md` with a dated §23 addendum stating this explicitly,
  cross-referencing the in-code reasoning rather than duplicating it, and naming the four concrete
  properties that make it safe (unguessable global key, server-only `company_id`, every
  authenticated path still filters explicitly, a resolved token only ever unlocks a second,
  RLS-protected lookup). No schema or application code changed for this finding.
- **Files changed.** `docs/architecture/POSTGRES_RLS_ROLE_MIGRATION_PLAN.md` (§23 added).
- **Tests added.** `tests/security/test_account_invite_onboarding_token_isolation.py` (4):
  `token_hash` uniqueness is a real database constraint, global not per-company (two real tenants
  each try to claim the same hash on both tables; the second insert is rejected both times); a
  forged `company_id` in an invite request body is silently dropped, never reaching the row;
  `GET /v1/users` under company B never returns an invite accepted under company A; `GET
  /v1/onboarding-cases` under company B never lists or 200s on company A's case (404, not 403 —
  same no-existence-oracle posture as every other cross-tenant case check), while the public,
  pre-tenant-context token for A's case still resolves correctly to A's own data.
- **Targeted result.** 4/4 passed.
- **Full regression result.** Part of the 2,361-test full run, §below.
- **Re-audit (negative tests, not just trusting the new ones).** Independently re-verified: (1)
  grepped both routers for any client-suppliable `company_id` parameter — none exists; (2) read
  `account_invite/repository.py` and `onboarding/repository.py` end to end to confirm every
  company-scoped method's `WHERE` clause; (3) the hash-collision test is a genuine negative test —
  it asserts the *second* insert raises `IntegrityError`, not that the feature merely "seems to
  work."
- **Final status.** CLOSED.

## FINDING-05 — L11/L12: already implemented; audit claim was stale, not a live gap

- **What the audit said.** "`leave/service.py`'s submit path does not call
  `EmploymentService.check_employment_coverage`" — cited as the core evidence for FINDING-05 being
  open.
- **What re-reading the code during this pass found.** That claim is **incorrect as of the
  current working tree**. `LeaveApplicationService.submit` (`leave/service.py:2322`) calls the
  shared `_ensure_within_employment` helper (`leave/service.py:1142`, which itself calls
  `EmploymentService.check_employment_coverage`) at line 2361, explicitly commented "D0-D3 -
  checked before the period lock." The same helper is also called from `create_adjustment` (D5),
  `create_encashment` (D5), and the final-approval path (`on_approval=True`, raising a distinct
  `LeaveApprovalOutsideEmploymentError`). `employee/coverage.py`'s `evaluate_employment_coverage`
  — the one pure function both Attendance and Leave now share — already implements every status
  the audit's own required test matrix needs: `PRE_JOINING`, `AFTER_LAST_WORKING_DAY`,
  `REHIRE_GAP`, `CROSS_EMPLOYMENT_SPELL`, `NO_EMPLOYMENT`. A 994-line, 14-test integration suite
  (`tests/integration/modules/leave/test_leave_employment_validity.py`) already existed,
  self-labeled D0-D8, covering this exact ground plus the employment-date-change guard (D4),
  legacy-row preservation (D6), and the rehire-balance behavior (D7/D8) — **and it already passed,
  before this remediation pass touched anything** (confirmed by running it in isolation first,
  before any other change in this session).
  - File modification times support this was not a last-minute, unverified fix slipped in after
    the audit: `employee/coverage.py`, `leave/service.py`, and the test file were all last
    modified roughly 24-27 hours **before** `PRE_PAYROLL_PRODUCTION_READINESS_FINAL_AUDIT.md`
    itself was written. The audit's trace of `leave/service.py:1159` (a comment line *referencing*
    `_ensure_within_employment`, not the submit call site at line 2361) appears to be where the
    tracing went wrong — an auditing error, not a reflection of the code's actual behavior at any
    point in this session.
- **The one real gap.** The audit's claimed decision gap (L11/L12 "needs a product decision, not
  a guess") was genuine *as a documentation fact* — no signed decision document for L11/L12 existed
  anywhere in the repository (confirmed: grepped `PAYROLL_BUSINESS_DECISIONS.md` for `L11`/`L12`,
  zero matches) — even though the code had already made and implemented a specific, defensible
  choice for both (strict employment-spell validity for L11; balance stays employee-level and
  survives rehire for L12). `LEAVE_MODULE_AUDIT.md` itself still listed both as "Open, needs a
  product decision" and "nothing was implemented or guessed" in its own prose, directly
  contradicting the test file 20 lines below it in the same document's edit history. This
  remediation pass's job for FINDING-05 was therefore **documentation, not code**: recording the
  decision that was already made and already shipped, so the next reader (or audit) doesn't
  re-open a closed question based on stale prose.
- **Fix.** `docs/testing/LEAVE_MODULE_AUDIT.md` — L11/L12 rows in the findings table updated from
  "Open, needs a product decision" to "Fixed"/"Decided and implemented" with pointers to the
  actual code and test file; the "Product decisions needed (not guessed)" section rewritten as
  "Product decisions — resolved," stating which option was chosen for each (L11: option (a),
  strict employment-spell validity; L12: option (a), carry the balance over) and why that matches
  what shipped; the "Not done / remaining" list's L11/L12 entry removed (it was the one item
  directly contradicted by code 20 lines earlier in the same file); the "Hardening pass" intro
  sentence corrected to stop asserting decisions 1-10 were never available/implemented.
- **No code change was required or made.** Re-confirming an already-correct implementation is not
  grounds for touching it.
- **Required test matrix, verified against the existing suite (not re-derived or guessed):**

  | Scenario | Expected | Covered by |
  |---|---|---|
  | Leave entirely before joining | rejected | `test_submission_is_valid_only_inside_one_employment_spell` (`PRE_JOINING`) |
  | Leave entirely after LWD | rejected | same test (`AFTER_LAST_WORKING_DAY`), plus the "leaver" and "weekend"/"friday" sub-cases |
  | Leave begins before joining | rejected | same test, "starts before joining" case |
  | Leave ends after LWD | rejected | same test, "one outside date in a long range" case (`offending_date` asserted) |
  | Leave spans rehire gap | rejected | same test (`REHIRE_GAP`, both a 2-day gap and a range crossing it) |
  | Leave spans two employment spells | rejected | same test, "back-to-back spells" case (`CROSS_EMPLOYMENT_SPELL`) |
  | Valid leave inside one spell | accepted | same test, joining day / mid-spell / LWD / second-spell cases |
  | Adjustment outside employment | rejected | `test_adjustments_and_encashments_need_a_date_inside_employment` |
  | Encashment outside employment | rejected | same test, encashment half, including idempotency-key-not-poisoned sub-case |
  | Employment date change conflicting with leave | rejected | `test_termination_that_strands_leave_is_refused_without_side_effects` (409, nothing changed) |
  | Legacy invalid leave | preserved | `test_legacy_invalid_leave_stays_readable_historical_and_cancellable` |
  | New invalid leave | rejected | every case above |

  Plus, beyond the required matrix: direct-projection rejection (`LM-14`), approval re-validating
  employment when it moved underneath a pending application, and four dedicated concurrency tests
  (approve-vs-terminate, a compatible-boundary race, submit-vs-terminate, and an
  employment-update/approval/adjustment three-way race) — all already present, all passed.
- **Targeted result.** `test_leave_employment_validity.py`: 14/14 passed, run both in isolation and
  as part of the full suite.
- **Full regression result.** Part of the 2,361-test full run, §below.
- **Re-audit (negative tests, read not just trusted).** Independently traced
  `terminate_employment` (`employee/service.py:1220`) and its `_assert_no_leave_after` helper
  (line 1468) end to end to confirm the lock-then-check ordering the LM-15 comment claims (leave-
  dates lock taken at line 1255, before the conflict check at 1268); traced
  `list_active_leave_after` (`leave/service.py:2791`) to confirm it reports SUBMITTED/APPROVED
  leave, not CANCELLED/REJECTED, matching the "a cancelled application is history, not a conflict"
  test case.
- **Final status.** CLOSED — both as a code fact (already true) and as a documentation fact (now
  corrected).

## Full regression results (this pass)

**Backend** (`apps/api`, `.venv/bin/python -m pytest tests -q`):

```
2361 passed, 4 warnings, 0 failed, 0 errors, in 649.67s (0:10:49)
```

Baseline comparison: **2,330 -> 2,361 (+31)**, exactly the number of tests this pass added (3 for
FINDING-01, 24 for FINDING-03, 4 for FINDING-04) — fully explained, no test removed, skipped, or
xfailed. The first full run of this pass (before the `capfd` fix above) showed 2 failures, both in
this pass's own new FINDING-01 tests, both traced to a test-infrastructure bug (`structlog.testing.
capture_logs()` vs. `cache_logger_on_first_use`), not a production-code bug — documented in
FINDING-01's section above, fixed, and re-run clean twice (once targeted, once as the full suite
shown here). The 4 warnings are the same pre-existing `pytest.mark.asyncio`-on-sync-function
cosmetic warnings the original audit already noted in `test_route_authorization_matrix.py`.

**Frontend** (`apps/web`, `npx vitest run`):

```
Test Files  61 passed (61)
     Tests  505 passed (505)
```

Baseline comparison: **505 -> 505 (unchanged)** — the Next 16 upgrade required zero test file
changes; FINDING-03's frontend changes (pagination UI on two pages) had no existing test coverage
to update (confirmed: grepped for any test referencing `/users` or `/onboarding-cases`, none
found).

```
npx tsc --noEmit            -> clean, exit 0
npm run build (--webpack)   -> succeeds, 70 routes, First Load JS unchanged in shape
npm audit --omit=dev        -> found 0 vulnerabilities
uvx pip-audit                -> No known vulnerabilities found
```

**Migrations:** none added, none needed — no finding in this pass required a schema change.
`111/111` from the original audit stands unchanged.

## Final independent re-audit (all five findings, re-read not re-trusted)

Per §9 of the remediation brief, each finding was re-checked by reading the actual current
implementation after the fix, not by re-running the new tests a second time and calling that
sufficient:

- **FINDING-01** — read the final `handlers.py` and `logging.py`; confirmed the client response
  object is unconstructed-and-unchanged by the new logging call (the `_error_response(...)` return
  is identical to before); confirmed `celery_app.py`'s signal handler is registered at module
  import time, before `entrypoints/worker.py` imports any task module (so it is live for every
  real task, not just ones imported after it).
- **FINDING-02** — re-ran `npm audit --omit=dev` and `pip-audit` fresh (not reading a cached
  result), confirmed `npm ci` (not `npm install`) reproduces the same clean lockfile CI will use.
- **FINDING-03** — re-read both repositories' final `WHERE` clauses to confirm the `company_id`
  predicate is still applied in the same query as `LIMIT`/`OFFSET` (never as a post-fetch Python
  filter), and that `_list_conditions`/the count query cannot drift from the list query because
  they share the same helper.
- **FINDING-04** — re-read both routers' full parameter lists a second time (not just grep) to
  confirm no hidden client-supplied tenant parameter exists.
- **FINDING-05** — re-read `terminate_employment`/`_assert_no_leave_after`/
  `list_active_leave_after` end to end (detailed above), not just the test file.

No new issue was found in this re-audit pass. One process issue was found and is disclosed above
(FINDING-01's test-infrastructure bug) — fixed within this same pass, not carried forward.

## Payroll boundary — explicitly re-verified

Per the remediation brief's own closing question: **is the pre-Payroll HRMS foundation now safe
enough that Payroll can be built on top of it without inheriting unresolved employee/attendance/
leave integrity problems?**

- **Employee** — unaffected by this pass; `employee/coverage.py` (pre-existing) remains the single
  shared authority Leave now visibly, verifiably uses.
- **Employment** — `terminate_employment`'s conflict guard (D4) re-verified directly in this pass.
- **Compensation** — untouched by any finding in this pass.
- **Attendance** — untouched; FINDING-05 confirms Leave now enforces the *same* employment
  boundary Attendance already did, closing the one cross-module inconsistency the original audit
  found direct evidence for (§11: "Leave can produce a paid day Attendance would refuse to
  produce").
- **LOP / Leave** — FINDING-05's L11/L12 decisions are now both implemented *and* documented;
  `paid_days`/LOP figures Payroll would read from Leave no longer carry an undocumented gap.
- **OT / Comp-off** — untouched by any finding in this pass.
- **Regularization** — untouched.
- **Period close** — untouched; FINDING-01's logging fix makes a period-close failure (like any
  other unhandled exception) diagnosable in production, which it was not before.
- **Legal entity** — untouched.

**Answer: yes**, for everything this pass's five findings could affect. This is not a claim that
every UNVERIFIED item from §10 of the original audit (mobile on-device testing, load testing, a
real Face++ liveness run, a disaster-recovery drill) is now resolved — those remain exactly as
UNVERIFIED as the original audit left them; this pass did not touch them and does not claim to.

## Final Production Gate

# READY FOR PRODUCTION

for everything before Payroll. All five findings this pass was scoped to close are closed:

- **P0: zero.** (None existed; none were introduced.)
- **P1: zero.** FINDING-01 (logging) and FINDING-02 (dependency CVEs) — both were this report's
  two P1s — are fixed, tested, and regression-proven at 2,361/2,361 backend and 505/505 frontend.
- **P2, classified explicitly, none hidden:**
  - FINDING-03 (unbounded endpoints) — **resolved** (paginated, tested).
  - FINDING-04 (RLS gap) — **resolved as a documented, tested, technically justified exception**
    (decision B), not left silent.
  - FINDING-05 (L11/L12) — **resolved**, both in code (already true) and in documentation (now
    corrected to say so).
  - P2-01 (urllib3) — **resolved** (2.8.0).
  - P2-02 (leave_ledger FK not composite with company_id) — **unchanged, acceptable production
    risk**: application-level rejection of a foreign id already exists (confirmed by the original
    audit); this pass did not touch it, and it is not one of the five findings in scope.
  - P2-03 (no transactional outbox) — **unchanged, acceptable production risk for everything
    before Payroll specifically**: failures are logged (and, after this pass, every *unhandled*
    failure anywhere is now logged too — FINDING-01 closes the one gap that would have made this
    risk worse). Out of this pass's scope; tracked, not hidden.
  - P2-04 (no `idempotency_key`/`audit_log` retention job) — **unchanged, acceptable production
    risk**, out of scope for this pass.
  - P2-05/P2-06 — **unchanged**, both already documented as open in the original audit, out of
    scope for this pass.

Nothing in this pass's own changes introduces a new P0, P1, or hidden P2. The conditions the
original audit's §21 set for an unconditional "READY FOR PRODUCTION" verdict —
FINDING-01/02 fixed-and-tested, FINDING-05/L11-L12 decided-and-implemented, FINDING-03/04
resolved-or-documented — are now all met.

*End of report.*
