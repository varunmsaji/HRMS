# Leave module audit (hardening phase)

Scope: PRA-07 accrual reliability, PRA-14 dates and timezones, PRA-15 concurrency and overlap,
PRA-16 history immutability, and Leave's interaction with the employee lifecycle, comp-off and
period locks. Payroll and the Attendance follow-ups are out of scope.

## Flows

| Flow | Path |
|---|---|
| Apply | `POST /leave-applications` -> period-open check -> **per-employee date lock** -> combination rules -> policy resolve -> day breakdown (sandwich/half day) -> **same-type per-date total <= 1** -> balance check (advisory, re-checked at approval) -> insert; AUTO chain approves immediately. |
| Approve | `If-Match` version bump -> stage chain -> final stage: **per-employee date lock** -> per-(employee,type) balance lock + re-check -> attendance projection sync per date -> `APPLICATION` ledger debit. All in one transaction. |
| Cancel | submitted: withdraw. approved: employee before start, HR any time with a reason -> period-open check -> version bump -> offsetting `ADJUSTMENT` credit (company-local date) + projections cancelled. |
| Accrual | Beat daily 01:00 IST -> per company -> acts only in the first `leave_accrual_run_window_days` company-local days -> previous calendar month, prorated by days employed (all spells) -> `ACCRUAL` row keyed by cycle (unique index). |
| Year end | Beat daily 02:00 IST -> per employee whose leave year starts on the company-local date -> lapse / carry-forward cap / encash, then yearly accrual. |
| Comp-off | approved overtime -> hourly credit sweep (keyed by overtime record) -> daily expiry sweep (keyed by credit id, under the balance lock). |

## Locks and where they are taken

| Resource | Lock | Taken by |
|---|---|---|
| One application's state | optimistic `version` / `If-Match` | approve, reject, cancel (loser gets 409) |
| One employee x leave type balance | `pg_advisory_xact_lock("leave-balance:...")` | approval re-check, comp-off expiry |
| One employee's leave dates (new) | `pg_advisory_xact_lock("leave-dates:...")` | submit, final approval |
| Ledger cycle rows | partial unique indexes + `ON CONFLICT DO NOTHING` | accrual, year end, comp-off credit |
| One attendance day row | `FOR UPDATE` | `AttendanceDayService.calculate` |

## Findings

| ID | Severity | Finding | Status |
|---|---|---|---|
| L1 | P1 | A `SECOND_HALF` leave application could never be saved: `leave_application_day.half` was `VARCHAR(10)` and the value is 11 characters. The insert failed and surfaced as a generic "value out of range" 422. | **Fixed** (migration `20261009091000`, model widened). |
| L2 | P1 | PRA-15: two concurrent approvals of overlapping leave of different types both succeeded (both 200), double-booking the day. The per-type balance lock does not order them and the projection check is read-then-insert. | **Fixed**: per-employee date lock at final approval; the loser gets 409 `LEAVE_PROJECTION_OVERLAP`. |
| L3 | P2 | PRA-15: two applications of the same type for the same date both submitted (also a retried or double-clicked submit). | **Fixed**: 409 `LEAVE_APPLICATION_OVERLAP` when same-type active leave on a date would exceed one day (two half days still fit). Submission takes the per-employee date lock, so concurrent submits create one. |
| L4 | P2 | PRA-14: backdating window used `date.today()` (UTC server date). | **Fixed**: company-local business date. |
| L5 | P2 | PRA-14: `max_requests_per_month` counted from the UTC month start. | **Fixed**: company-local month start. |
| L6 | P2 | PRA-14: the cancellation reversal's `effective_date` used `date.today()`, booking the credit in the previous period just after midnight IST at a month/year boundary. | **Fixed**. |
| L7 | P1 | PRA-07: one employee's exception rolled back and aborted the whole company's accrual and year-end run; nothing was logged. | **Fixed**: one savepoint per employee, failures logged (`leave_accrual_employee_failed`, `leave_accrual_incomplete`, same for year end); a re-run completes the rest idempotently. |
| L8 | P1 | PRA-07: a missed day-1 Beat firing silently lost a month. | **Fixed (bounded)**: the task is scheduled daily and acts only in the first `leave_accrual_run_window_days` (default 5) company-local days; extra runs are no-ops. A longer outage still needs a manual run (see remaining). |
| L9 | P2 | Accrual for an employee rehired within the same month used only the first spell's days (second spell skipped by the cycle key). | **Fixed**: days employed are summed across all spells. |
| L10 | P1 | PRA-16: the runtime role `hrms_app` could UPDATE/DELETE/TRUNCATE `leave_ledger`, `leave_application_action` and `audit_log`, although the ledger is documented append-only. | **Fixed** (migration `20261009090000`): those privileges are revoked from `hrms_app`; the app never used them. Owner role unchanged. |
| L11 | P2, DECISION | Leave can be applied for, auto-approved and debited for dates **before the joining date, after the last working day, and inside a rehire gap**. Attendance rejects punches there (A2). | **Fixed** (D0-D3/D5/D6, below) — `EmploymentService.check_employment_coverage` (`employee/coverage.py`) now gates submit, approval, adjustments and encashments; see `tests/integration/modules/leave/test_leave_employment_validity.py`. |
| L12 | P2, DECISION | A leave balance belongs to the employee, not to an employment, so an old employment's balance is available after a rehire. | **Decided and implemented** (D7/D8, below): the balance stays employee-level by design and survives termination/rehire with no reset — see the same test file's "D7/D8 rehire balance" section. |
| L13 | P3 | Approval versus attendance period finalization is check-then-act with no shared lock; a narrow window exists. | Open, informational. |

## Product decisions — resolved (FINDING-05 remediation, 2026-10-05)

**L11 - leave dated outside employment. Decided: (a).** Every leave date must fall inside one
employment spell, consistent with A2 for punches — pre-joining, after the last working day (with
no further employment), and inside a rehire gap are all rejected (`LEAVE_DATE_OUTSIDE_EMPLOYMENT`
on submit/adjustment/encashment, `LEAVE_APPROVAL_OUTSIDE_EMPLOYMENT` if employment moved underneath
a pending approval). The last working day itself remains valid employment, as before. Implemented
via the shared `EmploymentService.check_employment_coverage` (`employee/coverage.py`'s
`evaluate_employment_coverage`), consumed by Leave submit/approve/adjust/encash exactly the way
Attendance and the termination guard already consumed it (D0-D6 below).

**L12 - balances across a rehire. Decided: (a), carry the balance over.** The ledger stays
employee-level (never employment-scoped); a rehire does not reset, lapse, or require an HR
adjustment to restore it — the pre-existing balance is simply spendable again once a new spell
opens (D7/D8 below).

**D0-D8, as implemented and tested** (`tests/integration/modules/leave/test_leave_employment_validity.py`):
D0-D3 (submission validity for the whole range, not just consuming days), D4 (an employment change
that would strand submitted/approved leave is refused, 409, no side effects), D5 (adjustments and
encashments need an effective date inside employment), D6 (legacy leave from before this pass stays
exactly as it was — readable, still cancellable, never retroactively invalidated), D7/D8 (balance
is employee-level, survives termination and rehire, the gap itself accrues nothing).

## Remaining (not changed)

- A Beat outage longer than the run window needs a manual `LeaveAccrualService.run_for_company` run;
  there is no HTTP/admin trigger (PRA-07 remainder).
- The sweeps now retry connection-level failures, acknowledge late and have time limits (decision 16/LM-11 pass, below); there is still no alerting - failures are logged as `leave_task_failed`.
- Comp-off expiry still skips a partly spent credit (documented LD-14 rule, preserved).

## Hardening pass: product decisions 11-20 (implemented)

Decisions 11-20 of the Leave market-readiness audit were approved and the engineering consequences
that are objectively defined were implemented. L11/L12 were decided and implemented in the
FINDING-05 remediation pass (2026-10-05) — see "Product decisions — resolved" above, not "Not
done" below (both items have been removed from that list accordingly).

| Decision | Result |
|---|---|
| 11 leave-type semantics | Done. `requires_balance`, `is_comp_off`, `is_paid_default` cannot change once any application or ledger entry refers to the type (409 `LEAVE_TYPE_IN_USE`). Cancel-reversal now credits what the ledger shows the application debited (LM-04), never what the type's current flags imply. |
| 12 default role grants | Done (new companies and, by migration `20261010090000`, existing ones). EMPLOYEE: submit own leave, own balances/history. REPORTING_MANAGER / BRANCH_MANAGER: approve (already) plus view reportees'/branch leave. HR_ADMIN: approve, cancel approved, company-wide view, adjust/encash, submit on behalf, reassign approver. No role below COMPANY_ADMIN manages leave types, policies, year setting, combination rules or statutory minimums. LM-05: `GET /leave-types` is readable by anyone who can submit (active types only). |
| 13 stuck approval | Done. `POST /leave-applications/{id}/reassign-approver` (`LEAVE.APPLICATION_REASSIGN`, company scope, `If-Match`, mandatory reason). Allowed only while a MANAGER/HOD stage's current approver is not employed today, has no login, or lacks the approve grant; the new approver must satisfy the same rules and cannot be the applicant. Timeline entry `APPROVER_REASSIGNED`, audit entry `LEAVE_APPLICATION_APPROVER_REASSIGNED`; dates, balance and ledger untouched. |
| 14 closed/finalised periods | Done on the Leave side. Manual adjustments and encashments dated in a closed attendance period of the employee's legal entity are refused (409 `LEAVE_LEDGER_PERIOD_CLOSED`); if a pay run for that period is FINALISED/PAID the code is `LEAVE_LEDGER_PAYROLL_FINALISED`. A correction is a new entry dated in an open period. No arrears engine. |
| 15 request limits | Done. Schema caps a request at 90 calendar days (422 before any per-day work). New `leave_policy_version.max_consecutive_days` (default 30, 1..90), enforced as `LEAVE_APPLICATION_MAX_CONSECUTIVE_EXCEEDED`. |
| 16 year-end catch-up | Done. `leave_year_end_catchup_days` (default 5). A year start is processed once per employee (`leave_year_end_run`), using the balance at execution time, ledger rows dated on the year start. Operator path: `celery -A entrypoints.worker call leave.run_year_end_for_company --args '["<company-uuid>", "<YYYY-MM-DD>"]'`. |
| 17 notifications | **Deferred.** No transactional outbox or notification abstraction exists in the repository (`onboarding/email_sender.py` is a direct SMTP sender; `celery_app.py` lists the outbox as planned-only). Required follow-up: a shared outbox table written in the business transaction, a delivery worker with retry and de-duplication key, then the six events listed in the decision. Until then job failures are logged (`leave_task_failed`, `leave_task_dispatch_failed`, `leave_year_end_incomplete`, `leave_accrual_incomplete`). |
| 18 reports/exports | **Deferred (remaining P2).** No reporting infrastructure exists. The data is report-ready without reading mutable state: `leave_ledger` (append-only, signed, dated, referenced), `leave_application` + `_day` + `_action`, `leave_year_end_run`. |
| 19 audit/privacy | Done for new writes. Application audit entries use an explicit allow-list (`LEAVE_APPLICATION_AUDIT_FIELDS`); ledger audit entries omit `reason`. |
| 20 unpaid leave and accrual | Documented as intentional (comment in `_accrue_employee_month`): LOP days do not reduce accrual. |

### Historical audit exposure (not changed)

Before this pass `audit_log` rows for leave applications held the whole application, including the
free-text `reason`, `attachment_reference`, `expected_delivery_date`, the reviewer comment and the
rejection/cancellation reasons, and ledger audit rows held the entry `reason`. `audit_log` is
append-only for the runtime role, so those rows remain. Nothing was deleted. Scoping query (read-only):
`SELECT count(*) FROM audit_log WHERE entity_type = 'leave_application' AND (after_json ? 'reason' OR before_json ? 'reason');`.
Any erasure/redaction needs a separate, owner-role retention decision. The application row and the
`leave_application_action` timeline still hold the text (it is business data, not audit).

### Additional defects found and fixed while writing the tests

- **Approve x attendance finalisation (LM-18) was a real defect.** A leave approval parked between its
  recalculation and its commit while a period finalised produced approved leave, a ledger debit, and a
  frozen summary counting 0 leave days. Finalisation now takes an exclusive, and every leave
  approval/reversal a shared, advisory lock on `attendance-period-close:{company}` (`core/db/locks.py`),
  always acquired after the per-employee date lock.
- `LeaveYearSettingService.get_effective` raised a unique violation when two first readers raced (now
  `ON CONFLICT DO NOTHING`).
- The audit `before` state for reject and cancel was read after the update and showed the post-update
  row; it is now captured first.
- A whitespace-only reassign reason was accepted; it is now rejected.
- Leave advisory locks waited indefinitely; they now give up after `leave_lock_wait_ms` (default 5 s)
  with 503 `DATABASE_BUSY` (retryable).

### Not done / remaining

- **LM-02 for plain adjustments is ordering hygiene, not an overdraw fix.** A manual debit is
  unconditional, so with or without its lock the final balance equals a legal serial order; the real
  overdraw fix is the encashment lock (a test fails without it).
- **Max consecutive days is per application.** Two adjacent applications are not chained. Chaining
  across applications (and across leave types) is a policy decision.
- **A 90-day request cap sits below statutory maternity leave (26 weeks).** A longer absence must be
  split into several applications. Product should confirm this is intended.
- `max_consecutive_days` has no field in the web policy form yet (API only).
- Year-end holds its per-balance locks until the company run commits (one transaction per company); an
  approval for an employee being processed waits (bounded) and is retried by the client.
- The ledger's employee foreign key is still on `employee.id` alone; the service now rejects a foreign
  id, but a composite `(company_id, employee_id)` foreign key would enforce it in the database.
- A leave type can still be first used between the "is it used?" check and a flag change
  (check-then-act with no lock on the type row).
- The integration suite connects as the table owner, so RLS is not exercised by it; whether the
  production runtime role is `NOBYPASSRLS` remains unverified.

## LM-03 - idempotency keys (adjustment, encashment, leave application)

`POST /leave-ledger/adjustments`, `POST /leave-ledger/encashments` and `POST /leave-applications`
require an `Idempotency-Key` header (8-128 characters of `A-Z a-z 0-9 . _ : -`; a UUID is fine). A
missing or malformed key is a 422 (`IDEMPOTENCY_KEY_REQUIRED` / `IDEMPOTENCY_KEY_INVALID`).

**Mechanism** (`core/idempotency.py`, table `idempotency_key`, migration `20261011090000`):

1. Inside the request's own transaction, `INSERT ... ON CONFLICT DO NOTHING` claims
   `(company_id, operation, key)`. A concurrent request with the same key blocks on the unique index
   until the first transaction ends (bounded by `idempotency_wait_ms`, then a retryable 503).
2. The business mutation runs. On any failure the transaction rolls back and the claim goes with it,
   so a failed attempt never poisons a key.
3. The response is stored on the same row, so mutation, audit entry and stored response commit
   together. A committed row therefore always carries its response.
4. A request that finds a committed row compares fingerprints: equal replays the stored response
   (same status, same `data`, `Idempotent-Replayed: true` header, fresh `meta.request_id`) without
   running anything; different is 409 `IDEMPOTENCY_KEY_CONFLICT`.

**Scope**: company + operation (`leave.ledger.adjustment`, `leave.ledger.encashment`,
`leave.application.submit`) + key. Another company, or another operation, may reuse a key.

**Fingerprint** (SHA-256 of canonical JSON): the operation; the acting user id; every field of the
request body (`employee_id`, `leave_type_id`, amount or days, dates, reason, half-day and attachment
fields as applicable); for a submission also the resolved target employee. Excluded: headers, IP,
user agent, request id. Only the digest and the response are stored, never the raw request. The
actor is part of the fingerprint, so another user presenting someone's key gets a 409, not their
result.

**Authorisation** still runs first: permission and data-scope checks sit in route dependencies and
the handler, before the key lookup, so a caller without the permission gets 403 whether or not the
key exists. Service-level checks are not repeated on replay (the replay returns what this same user
already received).

**Not stored**: business refusals (422/409 from the operation) roll back, so the same key can be
re-sent after the cause is fixed.

**Clients**: the shared test client adds a unique key to these three POSTs when a test did not pass
one. Web (`newIdempotencyKey`, kept across network-failure retries in the apply and encash forms)
and mobile (`ApiClient.newIdempotencyKey`, a fresh key per call unless the caller passes one) send
the header. The mobile change could not be compiled or analysed here (no Flutter SDK).

**Open follow-ups**: rows are never purged (a retention job, e.g. 30 days, is a small follow-up);
approve / reject / cancel are guarded by `If-Match` versions, not keys; the other mutating modules
have no keys.
