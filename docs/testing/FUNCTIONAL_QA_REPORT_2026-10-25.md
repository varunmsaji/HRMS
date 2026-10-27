# HRMS End-to-End Functional QA Report — 2026-10-25

Scope: functional verification of the existing HRMS (FastAPI API, Celery workers, Next.js web, Flutter mobile).
Nothing was committed, pushed, merged or deployed. No production or shared development data was used;
all synthetic data lived in disposable resources that have since been removed.

Evidence: [`qa_live_2026-10-25/`](qa_live_2026-10-25/) holds every script used and `register.csv`
(216 live checks, one row per check). Coverage is not proof of correctness; see section 10.

---

## 1. Feature inventory and coverage matrix

335 API operations (OpenAPI) · 22 Celery tasks, 10 Beat entries · 82 web pages · Flutter app.

| Feature | API (ops) | Web | Mobile | Live E2E (this pass) | Existing automated tests | Verdict |
|---|---|---|---|---|---|---|
| Auth, sessions, password reset, email verify | `auth/*` (10) | yes | yes | 32/32 | yes | **PASS** |
| Tenant isolation / RLS | all | n/a | n/a | 10 API + 7 DB-level | yes | **PASS** |
| RBAC | all | partly | partly | 16 | yes | **PASS** |
| Employees (CRUD, ETag/If-Match, pagination, idempotency) | 45 | yes | yes | 13 | 436 | **PASS** |
| Employee bulk import (CSV → Celery) | 5 | **no UI** | **no UI** | 12 (real worker) | 30 | **PASS after fix** (DEF-02/03) |
| Attendance punches | `attendance/*` (21) | yes | yes | 14 | 620 | PASS; 1 known gap (K-1) |
| Regularization | 6 | yes | yes | 15 | yes | **PASS** |
| Shifts, rosters, policies, periods, overtime | ~70 | yes | partly | sweep only | yes | NOT deep-tested live |
| Leave (types, policies, applications, ledger, balances) | ~45 | yes | yes | 41 | 252 | **PASS** |
| Payroll (structures, runs, payslips, adjustments) | 38 | yes | yes | 26 (guards/authz/tenant) | 126 (hand-computed expectations) | PASS; calculation not re-derived by me |
| Onboarding + documents | 17 | yes | yes | 9 (doc validation) | 163 | PASS |
| Platform console | 25 | yes | no | tenant-admin denial only | 24 | partly tested |
| Subscription | 1 (read-only plan/feature summary) | yes | — | not exercised | partial | payment/usage billing **NOT IMPLEMENTED** |
| Face attendance (Face++ / open-source) | ~12 | yes | yes | **excluded by instruction** | yes | NOT RUN |
| Recruitment, job postings, applications, candidate search | — | — | — | — | — | **NOT IMPLEMENTED** |
| Resume processing / AI features | — | — | — | — | — | **NOT IMPLEMENTED** |
| Notifications beyond transactional email; reports/exports | 1 dashboard endpoint | — | — | — | — | **NOT IMPLEMENTED** (no export endpoints) |

## 2. Environment and dependency health

* Postgres 16, Redis 7, MinIO healthy. Migrations (121 revisions) apply cleanly from empty to head
  `20261022090000` on a disposable database.
* **Blocker found:** the host root partition is **100 % full (5 GB free of 560 GB)**, and the dev MinIO
  volume lives on it. MinIO rejected writes (`XMinioStorageFull`), which caused **38 of the 38 integration
  failures in the baseline run**. All 38 pass on healthy storage. Free disk space on `/`.
* Isolation used: private Postgres DB, Redis DBs 2/14, a private MinIO (data on the other drive) and
  email = logging sender, Face++ disabled. Verified the dev DB was untouched afterwards.
* **Process lapse (mine):** `tests/integration/core/test_storage.py::test_object_survives_a_minio_container_restart`
  runs `docker restart hrms-minio` (the shared dev container). I did not read the test before running it and it
  restarted that container once. It came back healthy with data intact. I deselected it afterwards. Consider
  guarding that test behind an opt-in flag.
* `uv run lint-imports` / the runner's static stage fail because `.venv` scripts have a stale shebang
  (`/media/varun/varun11/...`); the code itself is fine (import contract KEPT when invoked via python).

## 3. Test results

| Suite | Result |
|---|---|
| Baseline backend (runner, before changes) | unit 1063 PASS; integration+security 1801 pass / **38 fail (all disk-full)** |
| Backend full regression **after fixes**, private DB + MinIO | **3198 passed, 0 failed** (1 deselected: the shared-container restart test) |
| Web `tsc --noEmit` | clean |
| Web vitest | 64 files / **522 passed** |
| Web ESLint | **110 errors** (97× `react-hooks/set-state-in-effect`, rest style rules) — lint debt, no functional failure observed |
| ruff / mypy | ruff: 6 E501 before, 5 after (all in already-applied migrations, left alone); mypy: 1 error before, clean after |
| Flutter analyze/test | **BLOCKED** — Flutter SDK is not installed on this host |
| Live black-box (new) | 216 checks: 214 PASS, 1 INFO, 1 FAIL (known K-1) |

## 4. End-to-end workflows verified live (real HTTP, real Celery worker)

register → email-verify → login → refresh/rotate → logout · invite user → accept → login ·
employee create/update with optimistic concurrency · employee invite → linked login ·
leave: policy → balance → apply → approve/reject/cancel (ledger checked in DB) ·
attendance punch (idempotent, parallel) → regularization request → approve → punches written once ·
payroll run creation, duplicate/stale/invalid-transition guards, authorization ·
CSV import via broker → worker → rows → errors; worker killed → job survives → restart → completes once ·
document upload/validation/download via presigned URL · dependency failure behaviour.

## 5. Defects found and fixes made

| ID | Sev | Finding | Status |
|---|---|---|---|
| **DEF-02** | **High** | Every DB-touching Celery task (leave accrual, attendance calc, termination sweep, employee import) ran under its own `asyncio.run()` against a process-global asyncpg pool. The 2nd task in a worker process failed with *"attached to a different loop"*, depending on what ran before it. Reproduced deterministically (`leave.accrue_company` call 2 and `attendance.calculate_company` call 1 failed), and as a stuck `PENDING` import batch with a real worker. Existing tests call the coroutine directly, so none crossed a loop. | **Fixed**: `run_task()` in `core/db/session.py` disposes the engine inside the task's loop; 4 task modules use it. Regression: `tests/integration/core/test_celery_task_event_loop.py` (fails 3/3 when the dispose is removed). |
| DEF-03 | Medium | Binary / non-UTF-8 bytes uploaded as `.csv` to `/v1/employee-imports` raised an unhandled `UnicodeDecodeError` → HTTP 500 + error log. | **Fixed**: 422 `IMPORT_FILE_UNREADABLE` before anything reaches S3/queue. 3 regression cases added. |
| DEF-04 | Low | `mypy` error in the dev-DB wipe guard (`seed/bootstrap.py:135`); one E501 in `opensource_face/store.py`. | **Fixed**, behaviour unchanged. |
| K-1 | Medium (known) | `hrms_app` can UPDATE/DELETE `punch` (and, per the repo's own note, `attendance_regularization_action`, `attendance_period_action`) although the model says "never UPDATE'd or DELETE'd". The repo's `test_runtime_role_grants.py` documents this as **decision D11, not yet approved**. | **Not changed** — needs your approval. Live check `ATT-15` reports it. |

## 6. Security and tenant isolation

PASS: unauthenticated access to all 335 operations is denied except documented public routes; forged,
expired, `alg=none`, wrong-secret and tampered tokens → 401; refresh-token reuse revokes the family; logout
kills the access token immediately; login/forgot-password give no user enumeration; login brute force → 429;
cross-tenant read/write/transition denied on employees, leave, regularization, pay runs, imports, documents,
punches; RLS verified as the real runtime role (no context ⇒ 0 rows; no cross-tenant read/insert/update);
`audit_log` and `leave_ledger` are INSERT/SELECT-only; no stack traces, SQL or driver text in any of ~650
sweep responses; injection-shaped input handled; oversize body → 4xx.

Observations (not defects): login **fails closed (503)** when Redis is down while authenticated reads keep
working; employee-create and onboarding-case creation accept but do not require `Idempotency-Key`, so a
double-submit at the API level creates two employees (the four money-affecting endpoints do enforce it).

## 7. Data integrity

Verified in the database: leave balance == `sum(leave_ledger)`; approve/cancel/double-approve/double-cancel
never double-debit or double-restore; parallel applications never push a balance negative (5 of 6 approved,
balance exactly 0); 6 parallel identical-date requests → exactly one accepted; 10 parallel identical
idempotency keys → one punch row; regularization approval writes exactly the requested punches once;
rejected/refused operations leave no rows; failed storage writes leave no document or batch row.

## 8. Web / mobile integration

* Static contract check: web **220** distinct calls → **0** mismatches; mobile **117** → **0** real mismatches
  (4 scanner artefacts verified by hand). Limitation: only literal call sites are visible to the scan.
* Mobile sends `Idempotency-Key` on all four required endpoints; web does for leave application, encashment
  and payroll adjustment.
* No dead in-app links (82 routes checked).
* **Backend features with no usable UI:** employee CSV import (neither client), leave `reassign-approver`
  (neither), `rosters/bulk` (neither), manual leave-ledger adjustment (web only; mobile has it).
* **Not done:** I did not drive the web UI or mobile screens (no browser session; Flutter missing), so
  loading/empty/error states are covered only by the existing 522 web unit tests.

## 9. Background jobs and dependencies

All 10 Beat entries map to registered tasks. Real worker on both queues. Verified: import round-trip,
worker killed → message retained → completes exactly once after restart. Dependency failures:
storage unreachable → clean 500 envelope, no partial rows; Redis killed → readiness reports not-ready,
liveness stays 200, login 503, reads continue. Observation: storage failure surfaces as generic
`500 INTERNAL_ERROR` rather than a retryable 503, and `/health/ready` reports `storage_configured`, not
reachability. Beat itself was deliberately not run (no real scheduled accrual/payroll).

## 10. Blocked or untested

Face attendance (excluded by instruction) · Flutter tests (SDK absent) · browser/UI journeys · web `next build`
(not run) · payroll statutory/TDS calculations (relied on the project's hand-computed tests; I did not
re-derive them, and statutory-rate verification status is a business input) · full payroll run to PAID live
(needs closed attendance periods; covered only by the project's own test) · shifts/rosters/overtime/policies
beyond the sweep · platform-admin flows · Beat firing · load/concurrency beyond the cases above ·
real email delivery.

## 11. Remaining critical risks

1. Root disk 100 % — production-like failure mode (uploads fail) already present on this host.
2. K-1 immutable-history tables still mutable by the runtime role (pending D11).
3. Any deployment that ran the previous code had unreliable Celery DB tasks (DEF-02) — check that leave
   accrual and attendance calculation actually ran in your environments.
4. Payroll statutory correctness not independently re-verified.

## 12. Prioritised remediation plan

1. Free disk space; move the MinIO/Postgres volumes off `/`.
2. Review and keep the DEF-02/03/04 changes; deploy workers with the fix.
3. Decide D11 and migrate `punch` and the two action tables (then move them into `APPEND_ONLY` in the grants test).
4. Guard the MinIO-restart test behind an opt-in; recreate `.venv` so `lint-imports` works.
5. Add UI for employee import (and decide on `reassign-approver`, `rosters/bulk`).
6. Map storage outages to a 503; make `/health/ready` probe storage.
7. Fix web ESLint errors; install Flutter and run the mobile suite in CI.

## 13. Verdict

**Conditionally ready for the features that exist.** The backend is functionally solid on everything exercised
(3198 automated + 214 live checks passing, strong auth/tenant/data-integrity results), after fixing one
high-severity background-job defect and one input-handling defect. It is **not** verified end to end for
UI behaviour on web/mobile, face attendance, or payroll statutory maths, and recruitment/AI/billing do not
exist. Do not treat this as proof of complete correctness.

### Files changed (all uncommitted)

`core/db/session.py` (+`run_task`), `modules/{leave,attendance,employee,employee_import}/tasks.py`,
`modules/employee_import/{service,exceptions}.py`, `seed/bootstrap.py` (type fix),
`modules/attendance/opensource_face/store.py` (docstring wrap); new tests
`tests/integration/core/test_celery_task_event_loop.py` and three cases in
`test_employee_import_upload_bounds.py`; this report and `qa_live_2026-10-25/`.
Some of those files already had your uncommitted edits (`session.py`, `bootstrap.py`, `store.py`); mine are
additive.
