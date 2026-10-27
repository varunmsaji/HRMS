# B13 - Reliability and migration readiness: plan (2026-10-26)

Scope: durable e-mail outbox, onboarding e-mail uniqueness migration, attendance tenant composite FK, confirm-vs-terminate
race, seat-limit concurrency, B12 regression re-verification. No commit/push/merge/deploy, no full regression, no web/mobile
suites, no B5b payroll, no grant changes, no `002_app_role.sh`, no DDL trigger probe. B11/B12 evidence is untouched.
This document does **not** claim production readiness.

## 1. Preflight (recorded before any edit)

| Item | Value |
|---|---|
| Branch / HEAD | `main` / `436a2e5` |
| `git status --short` | 238 paths (the count B12 ended with); full snapshot saved to `qa_evidence_b13/git_status_start.txt`, `git_diff_stat_start.txt`, `tracked_diff_start.patch` |
| Root free disk | 3.09 GiB (gate: >= 3 GiB to start, stop < 2 GiB). Margin is thin (B12 started at 4.4 GiB); re-checked before every run by `b13_run.sh` |
| Memory | 15 GiB total, ~8.3 GiB available, swap 338 MiB / 2 GiB used |
| Docker | shared `hrms-postgres/redis/minio` running (never touched); no `qa-*` containers exist; images for the harness are present locally |
| Stack | fresh disposable `b13-20261026a` via `qa_harness/stack.sh` (holder container with `--network none`; QA data on the 193 GiB `varun12` volume, not on `/`) |

## 2. Findings from inspection that shape the work

* **Outbox**: B12 `core/db/post_commit.py` runs delivery in-process after commit (at-most-once). `email_sent` has had three
  meanings: pre-B12 "provider accepted", B12 "queued" (it can only be `False` if *enqueue code* raised), and now - see §4.
  Four callers: activation e-mail, account invite, case invite, changes-requested. `email_log` is an append-only, tenant-free,
  trigger-protected ledger (one row per delivery attempt) written by the sender; it stays the delivery ledger.
* **Seat limit**: already serialised per company by `pg_advisory_xact_lock('employee-seats:<company>')` inside
  `EmployeeService._check_seat_limit`, reached by activation through `create_employee`. Counting rule: non-deleted AND `is_active`.
  Termination does **not** clear `is_active` ("nothing is deleted or deactivated"), so a terminated employee keeps a seat until HR
  deactivates them - that is the implemented contract and will be asserted, not changed. E is therefore verification-first.
* **Confirm vs terminate**: `terminate_employment` already takes `lock_employee_leave_dates` (per-employee advisory xact lock) as its
  first statement. `confirm_employee` takes no lock and reads employments, so it can commit `ACTIVE` after a concurrent termination.
  Smallest fix: `confirm_employee` takes the same lock first (it is first in the documented lock order, and confirm takes no other lock).
* **Onboarding uniqueness**: rule is established in code and docs: *per company, case-insensitive on `personal_email`, among non-deleted
  cases whose status is not terminal (`ACTIVATED`, `EXPIRED`, `CANCELLED`)* (plan §13 Q5 / `DUPLICATE_ACTIVE_ONBOARDING_CASE`).
  No new policy needed. The index must use exactly this predicate.
* **Attendance**: `attendance_day.employee_id -> employee.id` and `company_id -> company.id` are independent FKs; `employee` has no
  `UNIQUE (company_id, id)`.

## 3. Work plan

### A. Durable transactional outbox
* Migration `20261027090000_email_outbox`: table `email_outbox` (id, `message_id` UNIQUE = stable logical-message key, company_id,
  kind, recipient, subject, text/html body, status `PENDING|SENDING|SENT|FAILED`, attempts, max_attempts, next_attempt_at,
  locked_until, locked_by, last_failure_class, last_error_type, created/updated/sent_at, failed_at). Tenant-free like `email_log`
  (the worker has no tenant), no RLS, default privileges give `hrms_app` DML - **no grant change**.
* Producer: `queue_email_after_commit` (same signature) now `INSERT ... ON CONFLICT (message_id) DO NOTHING` in the **business
  transaction** (rolls back with it and with its SAVEPOINTs), then registers a post-commit *dispatch* (not delivery).
* Consumer: Celery tasks `email_outbox.deliver_message` and `email_outbox.sweep` (Beat, every minute) in the existing worker.
  Claim = short transaction `FOR UPDATE SKIP LOCKED` + lease (`locked_until`), commit, **then** send with no transaction open, then a
  guarded `UPDATE ... WHERE status='SENDING' AND locked_by=:me`. Transient failure -> `PENDING` with exponential backoff (30 s * 2^n,
  cap 1 h, 6 attempts); permanent failure or attempts exhausted -> `FAILED`. Lease expiry recovers a crashed worker. Bodies are blanked
  on `SENT`/`FAILED` (they contain single-use links).
* `EMAIL_OUTBOX_DISPATCH=celery|inline|none` setting (default `celery`); the test conftest uses `inline` so the existing suites keep
  observing `email_log`; new tests use `none` to hold the crash window open.
* Guarantee: durable **at-least-once** with duplicate-logical-message protection (`message_id`); a crash between provider acceptance and
  `SENT` can resend. Not exactly-once.
* API: keep `email_sent` (documented as "queued", unchanged since B12), add `email_queued` and `email_delivery_status`
  (`QUEUED` at response time). No web/mobile edit; required client copy changes are documented for approval.
* Tests: commit+outbox, rollback, crash after commit, worker restart, transient/permanent failures, duplicate task delivery,
  repeated activation/invite, concurrent workers (threads on separate connections **and** separate OS processes), outbox/business
  consistency after failures. Synthetic senders only.

### B. Onboarding e-mail uniqueness migration
Migration `20261027091000_onboarding_case_email_unique`: pre-flight `DO` block lists conflicting groups (company, normalised e-mail, case ids,
statuses) and raises - nothing is deleted or merged - then `CREATE UNIQUE INDEX ... (company_id, lower(personal_email)) WHERE deleted_at IS NULL
AND status NOT IN ('ACTIVATED','EXPIRED','CANCELLED')`. App maps the index violation to the existing 409. Tested on scratch databases inside the
disposable Postgres: clean upgrade, exact-case / case-variant / legacy / terminal-vs-active data, fail-safe with diagnostics, downgrade.

### C. Attendance tenant composite FK
Migration `20261027092000_attendance_day_tenant_fk`: `UNIQUE (company_id, id)` on `employee`; diagnostic `DO` block; `FOREIGN KEY (company_id, employee_id)
REFERENCES employee (company_id, id) ON DELETE RESTRICT` added `NOT VALID` then `VALIDATE`. Fails with diagnostics when stray rows exist; never rewrites.
Tests: valid insert/update, cross-tenant, unknown, update of company_id/employee_id (also of `employee.company_id`), pre-existing violators, up/down; all
attendance writers enumerated.

### D. Confirm vs terminate
Lock fix above; tests with separate connections and OS processes; final employment status, employee status and audit-event counts asserted.

### E. Seat limit
Tests only unless a defect appears: capacity available, exact limit, N cases for the last seat (connections + OS processes), reject-then-retry,
active/inactive/terminated treatment.

### F. B12 regression re-run + negative controls
Re-run the six B12 target groups; negative controls via the existing in-memory plugin (`b12/negctl.py`) plus a new `b13/negctl.py`; no source edits.

## 4. Run mechanics
`qa_harness/stack.sh` gets one extra read-only `/qa/b13` mount (same pattern as B12). `qa_harness/b13_run.sh <batch> <pytest args>` enforces the disk
gates, requires the exact line `ISOLATION PROVED` and writes `qa_evidence_b13/<batch>.{isolation,resources}.txt` + `.log`. One attributable batch per
workstream. Teardown removes only containers labelled `qa.run=b13-20261026a`.

## 5. Stop conditions
Free root disk < 2 GiB; isolation not proved; a required change to grants, to plan/seat semantics or to the uniqueness rule; client (web/mobile)
changes needed for correctness (documented and stopped at).
