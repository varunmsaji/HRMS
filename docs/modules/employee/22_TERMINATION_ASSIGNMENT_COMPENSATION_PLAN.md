# Termination → Assignment/Compensation Closure — Verification & Implementation Plan

**Status: architecture verification and implementation planning only. No application code,
migrations, schema, or tests were created or modified to produce this document. Nothing was
committed.**

**Date:** 2026-08-15

**Implementation addendum (2026-08-15):** this plan has since been implemented — see
`docs/modules/employee/23_TERMINATION_LIFECYCLE_IMPLEMENTATION_REPORT.md`. OD-1 (§8/§19: the
current assignment/compensation row's `effective_from` after the new `last_working_day`) was
resolved for that implementation by the task owner as **"leave the row open, termination still
succeeds"** — plan §8's option 2, not the plan's own (non-locked) recommendation of option 1
("reject"). This addendum records the decision at the point it was made; the rest of this
document is left as originally written, including §8/§19's framing of the question as open at
plan-writing time.

**Filename note:** the task that requested this document asked for
`docs/modules/employee/21_TERMINATION_ASSIGNMENT_COMPENSATION_PLAN.md`. `21_` is already taken by
`21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` (E-07's plan, pre-existing). To avoid silently
overwriting or renumbering an unrelated document, this plan is filed as `22_...` instead — a
deviation from the literal instruction, written down rather than silently resolved, per this
task's own "the conflict must be written down" rule.

**Legend**, used consistently throughout, matching `HRMS_SYSTEM_DESIGN_BASELINE.md`:
- **FACT** — observed directly in code, schema, migrations, or tests.
- **DOC** — stated in an authoritative document; not yet built, or not independently verified in
  code.
- **DISCREPANCY** — DOC and FACT disagree.
- **OPEN** — genuinely unresolved; not invented here.
- **RECOMMENDATION** — a proposed next action, not a locked rule.

---

## 1. Executive Summary

`EmploymentService.terminate_employment` (`apps/api/src/hrms/modules/employee/service.py:463-532`)
transitions `employment.status` from `ACTIVE` to `TERMINATED` and sets `last_working_day`. It does
**not** touch `employee_assignment` or `employee_compensation` — **FACT**, confirmed by direct
code read and by the current code's own comments and tests. This is the exact CRITICAL-1 defect
`HRMS_SYSTEM_DESIGN_BASELINE.md §18` and `HRMS_ARCHITECTURE_DECISION_LOG.md`'s cross-reference
both name as the single highest-priority fix before Attendance/Leave/Payroll are built.

The consequence, proven by existing test assertions (not merely inferred): during the gap between
termination and any later rehire, `employee_assignment`/`employee_compensation`'s "current" row
(`effective_to IS NULL`) for that employee **stays open**, so any `as_of` query landing in the gap
returns the terminated employee's **stale pre-exit** placement and pay — not "no data," which is
what the architecture's own idealized model (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D)
requires. If the employee is never rehired, this row stays open **forever**.

The fix is narrow, additive, and does not require a migration, a new repository method, a new
permission, or an API contract change. `EmployeeAssignmentRepository.close_assignment` and
`EmployeeCompensationRepository.close_compensation` — built in E-04/E-06 for the "close current,
insert new" pattern — already do exactly what termination needs: close a row by `effective_to`,
guarded by optimistic-concurrency `version`. `EmploymentService.terminate_employment` needs to call
them, inside the same transaction, using `employment.last_working_day` as the closing boundary,
mirroring the boundary the architecture's own Part D worked example already specifies verbatim.

One genuine **OPEN** product question blocks a fully specified implementation: what should happen
when the employee's *currently open* assignment or compensation row has an `effective_from` **after**
the new `last_working_day`（i.e., a future-dated transfer/raise was already entered before an
unexpected early resignation). No source document addresses this, and the system today has no
mechanism to retract an insert-only effective-dated row. This is flagged, not resolved, in §8 and
§19.

**Verdict: READY WITH ONE OPEN DECISION.** The core fix (closing the ordinary case) is fully
specified and requires no product input. The future-dated edge case needs an explicit decision
before that one code path is implemented — it should not silently default to either "leave it
open" (today's bug, recurring) or "reject termination" without that being a conscious choice.

---

## 2. Current terminate_employment Behavior

**FACT**, from `apps/api/src/hrms/modules/employee/service.py:463-532`:

1. Confirms the employee exists (`_assert_employee_exists`, 404 otherwise).
2. Fetches the `Employment` row by `(company_id, employee_id, employment_id)` (404 if not found).
3. Rejects if `employment.status != "ACTIVE"` (`EmploymentNotActiveError`, 409 — "This employment
   is already terminated").
4. Rejects if `body.last_working_day < employment.joining_date` (`InvalidLastWorkingDayError`,
   422). **No upper-bound check exists** — a future `last_working_day` is accepted (this is how
   DEC-025's "on notice, derived not stored" state becomes representable: `status` flips to
   `TERMINATED` immediately, but `last_working_day` can be in the future).
5. `EmploymentRepository.update_employment` performs `UPDATE employment SET status='TERMINATED',
   last_working_day=:val, version=version+1, updated_at=:now WHERE id=... AND version=:expected`,
   returning the updated row or `None` on a version mismatch.
6. On `None`, re-fetches and raises `StaleResourceError` (409) with the current row's snapshot.
7. On success, records one audit entry, `action="EMPLOYMENT_TERMINATED"`, `before`/`after` =
   `employment_to_audit_dict` snapshots of the same row pre/post update.
8. Returns the updated `EmploymentRead`.

**Nothing in this method reads or writes `employee_assignment` or `employee_compensation`.**
Confirmed by direct code read (no import, no repository reference, no reachable call path) and by
`grep` across the module (§4 of the E-04 implementation report performed and recorded the same
grep independently, finding no executable-code reference).

---

## 3. Evidence From Source Documents

**DOC**, `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D (the rehire walkthrough, the closest thing
this codebase has to an authoritative idealized model for this exact scenario):

> `2030-09-30 | Resigns | employment #1.exit_date = 2030-09-30, status → TERMINATED/EXITED.
> employee_assignment #3.effective_to = 2030-09-30 (closed — no open assignment row remains).
> employee_compensation #2.effective_to = 2030-09-30 (closed — no open compensation row
> remains).`

This is explicit: the idealized model closes both child rows **at the exit date**, not at some
later date, not left open. This is the closest artifact to a specification for what "close" means
— treated in this plan as the authoritative target shape (§7), even though no `DEC-NNN` entry in
`HRMS_ARCHITECTURE_DECISION_LOG.md` names it verbatim (the log's `DEC-016` locks rehire mechanics
generally, citing Part D, but does not itself restate this specific sub-behavior).

**FACT**, `docs/modules/employee/12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md §12/§17 item 1`
and `20_EMPLOYEE_COMPENSATION_IMPLEMENTATION_REPORT.md §17 item 1` (E-04's and E-06's own closeout
reports) both independently document this exact gap as a **known limitation**, explicitly naming
`EmploymentService.terminate_employment` as the method that would need to change, and explicitly
stating it was deliberately not done in those slices ("the instruction not to modify completed
modules unnecessarily"). `16_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_REPORT.md §17 item 4`
repeats the same note for E-05. **No document claims this is already fixed anywhere** — three
independent implementation reports and the architecture baseline all agree it is not.

**FACT**, integration tests already encode and assert the *current* (broken) behavior explicitly,
not merely by omission:
- `test_rehire_first_assignment_after_gap`
  (`apps/api/tests/integration/modules/employee/test_employee_assignment.py:750-826`) — docstring:
  "terminating `employment #1` does **not** automatically close the still-open
  `employee_assignment` row... The pre-exit assignment therefore remains open until the rehire's
  own `create_assignment` call closes it — at the rehire's `effective_from - 1 day`, not the
  original exit date." Assertion at line 816: `pre_exit_after.json()["data"]["effective_to"] ==
  "2034-01-31"` (the day before the *rehire's* `effective_from`, 2034-02-01) — **not**
  `"2030-09-30"` (the actual `last_working_day` used in the same test at line 785).
- `test_rehire_first_compensation_after_gap`
  (`apps/api/tests/integration/modules/employee/test_employee_compensation.py:594-666`) — same
  shape, same assertion pattern, `effective_to == "2034-01-31"` instead of `"2030-09-30"`.

This is stronger evidence than a code read alone: the test suite does not merely fail to cover the
fix, it **positively documents and locks in the current buggy boundary date** as expected
behavior. Any implementation of this plan must update both tests (§14, §17).

---

## 4. Actual Current Code Path

```
POST /v1/employees/{employee_id}/employments/{employment_id}/terminate
  → router.terminate_employment (router.py:245-267)
      Depends(get_tenant_context)               — tenant resolution (verified path, per
                                                    baseline §1.5 item 2)
      Depends(require_permission(EMPLOYEE_TERMINATE))
      Depends(get_employment_service)            — constructs EmploymentService(session, settings)
  → EmploymentService.terminate_employment (service.py:463-532)
      1. _assert_employee_exists
      2. EmploymentRepository.get_employment
      3. status/date validation
      4. EmploymentRepository.update_employment  (UPDATE ... WHERE version=expected RETURNING)
      5. AuditService.record(action="EMPLOYMENT_TERMINATED")
      6. return EmploymentRead
  → get_session() dependency commits the request-scoped transaction on clean return,
    rolls back on any exception (core/db/session.py:71-83)
```

One session, one implicit transaction, per request — **FACT**. There is no explicit
`BEGIN`/`COMMIT` anywhere in the service layer; every mutation in this codebase relies on the
`get_session` FastAPI dependency's own commit-on-success / rollback-on-exception wrapper. This is
the same mechanism every other write path in this module already depends on (`create_employment`,
`create_assignment`, `create_compensation` all follow the identical pattern) — so any additive
change inside `terminate_employment` automatically inherits atomicity with the rest of the method,
with no new transaction-management code required.

Answers to Phase 2's twenty questions, condensed (each backed by the evidence above):

| # | Question | Answer |
|---|---|---|
| 1 | Columns changed on `employment` | `status`, `last_working_day`, `version`, `updated_at` |
| 2 | `employee_assignment` effect | None — untouched |
| 3 | `employee_compensation` effect | None — untouched |
| 4 | Auto-closed? | No |
| 5 | Future-dated Assignment rows affected? | No — not read, not written |
| 6 | Future-dated Compensation rows affected? | No — not read, not written |
| 7 | Multiple historical Assignment rows | Unaffected; only the one open (`effective_to IS NULL`) row is impacted by the gap (it stays open) |
| 8 | Multiple historical Compensation rows | Same as above |
| 9 | Termination after a rehire | Same code path, no special-casing; works correctly for `employment.status` itself since GiST guarantees at most one `ACTIVE` row |
| 10 | One DB transaction? | Yes — request-scoped session, commit/rollback wrapper |
| 11 | Assignment close while Compensation fails? | N/A today — neither is touched |
| 12 | Compensation close while Employment fails? | N/A today |
| 13 | Concurrent requests | `employment.version` + `If-Match` protects the employment row only; no assignment/compensation interaction exists to race on |
| 14 | Retried termination | Second call hits the `status != ACTIVE` guard → 409, no side effects |
| 15 | Audit events | `EMPLOYMENT_TERMINATED` only |
| 16 | Idempotent? | Yes, by the `ACTIVE`-only guard (second call is a clean no-op-with-error, not a silent no-op) |
| 17 | No current Assignment | N/A — never checked |
| 18 | No current Compensation | N/A — never checked |
| 19 | Future-dated changes on the employee | Not read or considered at all |
| 20 | Already-terminated employee | 409, no mutation attempted |

---

## 5. Assignment Lifecycle Behavior (today, without the fix)

`EmployeeAssignmentRepository.get_current_assignment` resolves "current" as `WHERE employee_id=:id
AND effective_to IS NULL` — **employee-scoped, not employment-scoped** (repository.py:230-239).
This is deliberate and correct for its own designed purpose (DEC-016), but it means:

- Immediately after termination, this query still returns the pre-exit row (`effective_to` still
  `NULL`) — **FACT**, unchanged by anything terminate does today.
- `get_assignment_as_of(employee_id, some_date_in_the_gap)` also returns the pre-exit row, because
  `effective_from <= as_of AND (effective_to IS NULL OR effective_to >= as_of)` is satisfied by an
  open-ended row for *any* `as_of` on or after `effective_from`, including dates after the
  employee's actual last working day.
- The row is only ever closed by a **later** `create_assignment` call (i.e., a rehire's first
  assignment), and when that happens, it closes at `rehire.effective_from - 1 day` — a date with no
  relationship to the actual exit date, confirmed by `test_rehire_first_assignment_after_gap`
  (§3).
- If the employee is never rehired, this row is **never** closed.

---

## 6. Compensation Lifecycle Behavior (today, without the fix)

Structurally identical to §5 — `EmployeeCompensationRepository.get_current_compensation`/
`get_compensation_as_of` are employee-scoped in exactly the same way, with exactly the same
consequence, confirmed by `test_rehire_first_compensation_after_gap` (§3). No divergence between
the two tables' behavior was found anywhere in the code.

---

## 7. Effective-Dating Analysis

The canonical pattern (`HRMS_SYSTEM_DESIGN_BASELINE.md §5`, `ADR-0003`, `DEC-003`): any
time-varying attribute lives in a child table keyed on the owning identity, with
`effective_from`/`effective_to`, a GiST exclusion constraint, and a close-then-insert write
pattern — **never an update to a closed row's business columns**. Termination's fix must respect
this exactly: the only field ever touched on an existing `employee_assignment`/
`employee_compensation` row is `effective_to` (plus `version`/`updated_at`) — precisely what
`close_assignment`/`close_compensation` already do and nothing more. No new write path, no new
mutable column, no exception to the "insert-never-update" rule is introduced by this fix — it
reuses the **existing** one allowed mutation (closing) at a moment (termination) where it
currently never fires.

**LOCKED** (this plan does not reopen it): the effective-dating pattern itself, the GiST exclusion
mechanism, and "closing" meaning "set `effective_to`, nothing else" are all already established
and confirmed live (§7 of `HRMS_ARCHITECTURE_DECISION_LOG.md` `DEC-003`).

**RECOMMENDATION**, closely tracking Part D (§3 above): on successful termination, if a current
(`effective_to IS NULL`) `employee_assignment` row exists for the employee **and its
`effective_from <= last_working_day`**, close it with `effective_to = last_working_day`. Same rule,
independently, for `employee_compensation`. This is the ordinary case and is fully specified by
existing documentation plus the existing repository contract — no invention required.

---

## 8. Future-Dated Record Analysis

Because `get_current_assignment`/`get_current_compensation` resolve "current" as "the one row with
`effective_to IS NULL`," and the GiST exclusion constraint guarantees **at most one** such row per
employee at any time, "future-dated" in this schema does not mean "a queue of upcoming rows" — it
means exactly one thing: **the single open row's `effective_from` is later than today** (e.g., a
promotion or raise entered in advance, effective next quarter). There is no other future-dated
state representable today.

**Ordinary future-dated case — not actually ambiguous.** If the open row's `effective_from <=
last_working_day` (the common case — a raise effective last month, employee resigns next month),
closing it at `effective_to = last_working_day` is correct and unambiguous, exactly per §7. A row
that is "future-dated" only relative to *today* but still starts before the exit date needs no
special handling.

**The genuinely open case.** If the open row's `effective_from > last_working_day` — a transfer or
raise was already scheduled to start *after* the employee's new last working day (e.g., a
promotion entered for 2031-01-01, then the employee unexpectedly resigns with `last_working_day =
2030-09-30`) — setting `effective_to = last_working_day` on that row would produce
`effective_from > effective_to`, an invalid range that Postgres's `daterange()` constructor
rejects outright (`ERROR: range lower bound must be less than or equal to range upper bound`). This
is not a theoretical edge case avoidable by "just choosing a sensible default" — it is a genuine
gap with no clean answer available in the current data model, for a reason worth stating plainly:
**there is no mechanism anywhere in this system to retract, cancel, or delete an
already-inserted effective-dated Assignment or Compensation row.** `EmployeeAssignmentRepository`/
`EmployeeCompensationRepository` expose no delete method; the insert-never-update principle (§7)
was never designed with a "the future event this row represents will no longer happen" scenario in
mind.

**OPEN — no source document addresses this.** Not resolved here. Three non-exclusive options exist,
none adopted by this plan:
1. Reject the terminate call with a new validation error until the future-dated row is
   dealt with some other way (a way that does not yet exist).
2. Terminate anyway and leave that one row open — recreating today's bug in miniature, but bounded
   to this one uncommon scenario instead of every termination.
3. Introduce a genuinely new capability (a "retract/cancel a not-yet-effective row" operation) —
   which is schema and API surface this plan is not authorized to design, and which the "insert-
   never-update" principle was not written to anticipate.

**RECOMMENDATION** (not a decision this plan locks): option 1 is the least-bad default — it fails
loudly and safely (a 409/422 the caller must act on) rather than silently reproducing the exact bug
this plan exists to fix, or silently inventing a new mutation capability. This should be confirmed
by product/architecture sign-off before this one code path is implemented; the ordinary-case fix in
§7 does not need to wait for that sign-off.

---

## 9. Rehire Analysis

Traced against the required scenario (Employment #1 ACTIVE → Assignment #1 → Compensation #1 →
Employment #1 TERMINATED → gap → Employment #2 REHIRED → Assignment #2 → Compensation #2):

- `employee.id`/`employee_code` — untouched by anything in this fix; `terminate_employment` never
  reads or writes the `employee` table. **Preserved.**
- `employee_assignment`/`employee_compensation` are keyed on `employee_id`, **never**
  `employment_id` (`DEC-016`, confirmed FACT in `models.py:123,178`). The fix operates purely in
  terms of "the employee's current open row, if any" — it has no concept of `employment_id` at all,
  matching every other method on `EmployeeAssignmentRepository`/`EmployeeCompensationRepository`.
- **Why the fix cannot accidentally reach into Employment #2's rows:** the fix runs synchronously,
  inside `terminate_employment`, which by construction can only be called while `employment.status
  == 'ACTIVE'` for Employment #1 (§2 step 3). Employment #2 does not exist yet at that moment — it
  is created later, by a separate `create_employment` call, which by the `employment_no_overlap`
  GiST constraint cannot even be inserted until Employment #1 is already `TERMINATED`. There is no
  interleaving under which the fix's "close the employee's current open row" logic could observe or
  touch a row belonging to a not-yet-created employment episode. This is a structural guarantee, not
  a runtime check this plan needs to add.
- **What actually changes for the rehire path, as a consequence of the fix, without touching
  `EmployeeAssignmentService`/`EmployeeCompensationService` at all:** today, `create_assignment`'s
  "close current" branch (service.py:728-751) is what closes the stale pre-exit row, at the wrong
  date, when the rehire's first assignment is created (§3, §5). After this fix,
  `terminate_employment` will have already closed that row correctly at `last_working_day`, so
  `get_current_assignment` will return `None` at the time of the rehire's first `create_assignment`
  call — meaning that call takes the **"no current row" branch** (service.py:656-672), exactly the
  branch E-04's own report (§12) says a rehire's first assignment is "mechanically identical to any
  employee's first assignment" through. This fix does not just close the gap correctly — it makes
  the *existing*, already-tested rehire code path in `EmployeeAssignmentService`/
  `EmployeeCompensationService` behave exactly as `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D's
  idealized model already describes, with zero changes to either of those two services.
- `as_of` queries: before the fix, a query for a date in the gap (2030-10-01 through 2034-01-31 in
  Part D's own example) incorrectly returns the pre-exit row. After the fix, the same query
  correctly returns nothing for that range, matching Part D exactly ("nothing to assign or pay
  during a period with no active spell").
- Historical rows on both sides of the gap remain immutable and correctly ordered — the fix adds
  exactly one `UPDATE ... SET effective_to` per table, at termination time; nothing about how
  `create_assignment`/`create_compensation` insert new rows changes.

**Conclusion: rehire correctness is not at risk from this fix — it is actively improved by it, with
no changes required outside `EmploymentService.terminate_employment` itself.**

---

## 10. Transaction Boundary

**RECOMMENDATION**, matching the existing per-request session pattern (§4) rather than introducing
a new one:

```
(inside the existing request-scoped session/transaction — no explicit BEGIN/COMMIT needed)

1. Validate: employee exists, employment found, employment.status == ACTIVE,
   last_working_day >= joining_date                                    (existing, unchanged)
2. Read the employee's current employee_assignment row, if any
3. Read the employee's current employee_compensation row, if any
4. If a current assignment exists:
     if its effective_from > last_working_day → OPEN case (§8) — surfaced as an error,
       nothing committed
     else → close_assignment(effective_to=last_working_day, expected_version=<row's own
       current version>) — StaleResourceError propagates uncaught on a concurrent-modification
       race, aborting everything
5. Same for compensation (step 4's shape, independently)
6. update_employment(status=TERMINATED, last_working_day=...)            (existing, unchanged)
7. Audit record(s)                                                       (§13)
8. Return EmploymentRead                                                  (existing, unchanged)

(request completes cleanly → get_session commits everything together;
 any exception at any step → get_session rolls back everything together)
```

This is not a new transaction-management design — it is the same implicit-transaction-per-request
pattern every other write in this module already relies on, extended with two more repository
calls before the existing `update_employment` call.

**Locking strategy:** none beyond what `close_assignment`/`close_compensation`/`update_employment`
already provide — each is a single `UPDATE ... WHERE version = :expected RETURNING`, which takes a
row-level lock implicitly for the duration of the statement and is validated against the version
read moments earlier in the same transaction. No `SELECT ... FOR UPDATE` is used anywhere in this
module today, and this fix does not need to introduce one — the version-checked `UPDATE` is
already the concurrency primitive.

**GiST exclusion interaction, checked specifically:** closing a row (narrowing its date range) can
only ever make it *less* likely to overlap with anything, never more — `employee_assignment_no_
overlap`/`employee_compensation_no_overlap`/`employment_no_overlap` cannot be violated by a close
operation. The only way this fix's writes interact with a GiST constraint is exactly the way every
other close-then-insert write already does: the constraint is inert against a pure narrowing
`UPDATE`.

---

## 11. Concurrency Strategy

**Optimistic concurrency, server-fetched, not client-supplied — RECOMMENDATION, with rationale.**
The terminate endpoint's request body (`EmploymentTerminate`) and its `If-Match` header both
concern `employment` only; the caller terminating an employment has no reason to know the
assignment/compensation rows' current `version` values, and requiring them would be a real API
contract change this plan recommends against (§12). Instead: read the current assignment/
compensation row(s) inside the same transaction, use the `version` value read at that moment as
`expected_version` for the close call. Because this all happens within one request's session
before that session commits, this is standard optimistic-concurrency usage, identical in shape to
how `create_assignment`/`create_compensation` already use a `current` row's version internally —
the only difference is *where* the expected version comes from (server-read here vs.
client-supplied `If-Match` there), which is appropriate because here the client isn't operating on
that sub-resource directly.

**Concurrent termination (two requests terminating the same employment):** unchanged from today —
the second request's `update_employment` call (or, if it loses the race earlier, its own
`get_employment` re-check) hits the `status != ACTIVE` guard or the `version` mismatch on
`employment` itself; existing `StaleResourceError`/`EmploymentNotActiveError` handling is
sufficient, no new code needed for this case.

**Concurrent transfer/compensation-revision during termination (the genuinely new race this fix
introduces):** e.g., a `POST .../assignments` (transfer) request and a `POST
.../employments/{id}/terminate` request racing for the same employee. Whichever transaction commits
first wins; the second one's `close_assignment` (if racing behind a transfer) or `create_assignment`
(if racing behind a termination's close) will see a `version` mismatch and get `None` back,
propagating `StaleResourceError` (409) and rolling back its **entire** transaction — the whole
termination fails, or the whole transfer fails, never a partial result. This is the safe default
recommended here: **fail the whole operation and let the client retry**, rather than attempting to
silently reconcile two conflicting business events. No new locking primitive is required to achieve
this — it falls out of the existing `version`-checked `UPDATE` pattern for free.

---

## 12. Idempotency

**Unchanged and still correct.** The existing `status != ACTIVE` guard (§2 step 3) already makes
repeated termination calls safe: the first call performs all writes (employment + the two new
closes); every subsequent call is rejected with `EmploymentNotActiveError` (409) **before** reaching
any of the new closing logic, so there is no risk of double-closing an already-closed row or
attempting to close a row using a now-stale `version` captured from a prior, already-committed
call. A request that fails partway through due to a concurrency conflict (§11) commits nothing
(§10), so retrying the identical request is always safe — this is the same retry semantics every
`If-Match`-guarded write in this codebase already has.

---

## 13. Permission Analysis

**RECOMMENDATION: `EMPLOYEE.TERMINATE` remains sufficient; no new permission code is introduced.**
No source document names or requires a separate permission for this cascade, and inventing one
would contradict this task's own "do not invent a new permission unless authoritative documentation
requires it" instruction. Precedent: `EMPLOYEE.CREATE` already gates the creation of the *first*
`employment` row without requiring a separate permission for anything it might imply — the same
"one HR-sensitive action, one permission, covering its direct, expected consequences" reasoning
applies here. `EMPLOYEE.TERMINATE` was itself already reasoned, at E-03's own implementation time,
to be "irreversible and at least as HR-sensitive as `EMPLOYEE.DEACTIVATE`" (`permissions.py:17-19`)
— closing the employee's org placement and pay record as a direct, structural consequence of ending
their employment is well within that same sensitivity band, not a separate action requiring
`EMPLOYEE.TRANSFER`/`EMPLOYEE.UPDATE_COMPENSATION` (those gate a **user-initiated** transfer/
revision; this is a **system-triggered** closure with no new values being set, only an end-date).

This is flagged as a recommendation, not asserted as a locked decision — no `DEC-NNN` entry
addresses it, and a future product review could disagree.

---

## 14. Audit Behavior

**RECOMMENDATION: reuse the two existing action names, do not invent new ones**, per this task's
own "do not invent new audit event names" instruction:

| Action | Fired when | Before / After |
|---|---|---|
| `ASSIGNMENT_CHANGED` | A current `employee_assignment` row is closed by termination | `before` = the open row's snapshot; `after` = the same row's snapshot post-close (`effective_to` now set) |
| `COMPENSATION_REVISED` | A current `employee_compensation` row is closed by termination | Same shape as above, for `employee_compensation` |
| `EMPLOYMENT_TERMINATED` | Always, on success (existing, unchanged) | `before`/`after` = `employment` row pre/post update |

Both `ASSIGNMENT_CHANGED` and `COMPENSATION_REVISED` are the same action names their respective
services already use for a "close current row" event (§ code review of `create_assignment`/
`create_compensation`, service.py:785-796, 953-964) — reusing them for a closure with no
accompanying new row keeps one action name meaning "this row's boundary changed" consistently,
rather than adding a third, narrower name for what is structurally the same kind of event (a
close). This mirrors how `EMPLOYMENT_TERMINATED` itself already records a before/after pair for a
single row transition, not a "before is null" shape.

**Ordering — RECOMMENDATION, not load-bearing for correctness (audit ordering does not affect
transaction atomicity, §10):** close assignment → record `ASSIGNMENT_CHANGED`; close compensation →
record `COMPENSATION_REVISED`; update employment → record `EMPLOYMENT_TERMINATED` (existing, last).
This interleaves each write with its own audit call, matching
`HRMS_SYSTEM_DESIGN_BASELINE.md §20` invariant 8 ("every state-changing write is audited, same
transaction") read literally as "immediately after that write," rather than batching all three
audit calls at the very end. Either ordering is transactionally equivalent since all commit
together; this is a readability/convention choice, not a correctness one.

**If no current assignment (or no current compensation) exists** (§17 Missing-data cases): no
`ASSIGNMENT_CHANGED`/`COMPENSATION_REVISED` record is written for that sub-resource — nothing was
closed, so nothing changed. `EMPLOYMENT_TERMINATED` still fires as normal.

---

## 15. API Impact

**RECOMMENDATION: no API contract change.** Per this task's own "prefer NO API change if the
lifecycle fix can remain an internal service-layer behavior" instruction, and confirmed achievable:

- **Request shape:** unchanged — `EmploymentTerminate{last_working_day: date}`,
  `extra="forbid"` (schemas.py:185-189).
- **Response shape:** unchanged — `DataEnvelope[EmploymentRead]`, the same `Employment`-only
  payload as today. Clients that want to see the now-closed assignment/compensation rows use the
  existing `GET .../assignments`/`GET .../compensation` endpoints (already support `?as_of=`),
  exactly as they would for any other historical read.
- **`If-Match`:** unchanged — still refers to `employment.version` only. The assignment/
  compensation `version` values used internally (§11) are never exposed to or required from the
  caller of this endpoint.
- **Error behavior:** the three existing errors (`404`, `409 EMPLOYMENT_NOT_ACTIVE`, `422
  INVALID_LAST_WORKING_DAY`, `409` stale-`employment`-version) are unchanged. One **new** error
  surface is introduced: a `409` if the assignment or compensation row was concurrently modified
  during the request (§11) — recommend reusing the existing generic `StaleResourceError` shape
  (already a `ConflictError`, already returns a `current` snapshot in its payload) parameterized
  with which sub-resource conflicted, rather than adding a new exception **class**. If §8's OPEN
  future-dated case is resolved toward "reject," that also surfaces as a new `422`-class error —
  its exact shape depends on how §8 is resolved and is not specified further here.
- **Repeated termination:** unchanged, `409 EMPLOYMENT_NOT_ACTIVE` (§12).
- **Concurrency conflicts:** unchanged in kind (still `409`s the client can retry against), new in
  breadth (can now also originate from the assignment/compensation close, not just the employment
  update itself) — §11.

---

## 16. Database Constraints

No migration is required for the ordinary case (§7). The fix uses exactly the columns and
constraints that already exist:

- `employee_assignment.effective_to`, `employee_assignment.version`,
  `employee_assignment_no_overlap` (GiST, live since `001_init_schema.sql`) — unchanged, only
  narrowed by the close (§10).
- `employee_compensation.effective_to`, `employee_compensation.version`,
  `employee_compensation_no_overlap` (GiST, live since `001_init_schema.sql`) — same.
- `employment.status`/`last_working_day`/`version`, `employment_no_overlap` (GiST, live since
  `20260814090000_employment_lifecycle.py`), `employment_status_last_working_day_check`,
  `employment_last_working_day_after_joining_check` — unchanged, already enforce everything they
  enforce today.

If §8's OPEN question is resolved in a direction that requires new state (e.g., a way to mark a
future-dated row as "will not take effect"), that would be new schema and is explicitly out of this
plan's scope (§21 non-goals).

---

## 17. Test Matrix

Labeled per this task's own instruction: **LOCKED** (behavior this plan specifies and a test
should enforce), **OPEN** (behavior not decided — the test's *expected value* cannot be written
yet), **RECOMMENDATION** (a sensible default, not yet a locked rule).

### Basic — LOCKED
- Terminate an active employment with one open assignment and one open compensation → both close
  at `effective_to = last_working_day`; `employment.status = TERMINATED`.
- `ASSIGNMENT_CHANGED`, `COMPENSATION_REVISED`, `EMPLOYMENT_TERMINATED` audit rows all exist,
  correct before/after snapshots.
- Whole operation commits as one transaction (verified indirectly: all three effects visible after
  the request, or none are, under an injected failure — §17 Concurrency).

### Missing data — LOCKED
- No current assignment exists (e.g., a hire with only `employment` and no `create_assignment`
  call yet) → termination still succeeds; no `ASSIGNMENT_CHANGED` audit row is written; no error.
- No current compensation exists → same shape.
- Both missing → termination succeeds with only `EMPLOYMENT_TERMINATED` recorded.

### Historical data — LOCKED
- Multiple **closed** historical assignment rows exist (from prior transfers) plus one open row →
  only the open row is affected; closed rows' `effective_to` values are untouched (byte-for-byte
  identical before/after).
- Same for compensation.

### Future-dated — mixed
- Open assignment/compensation row with `effective_from` in the future but **≤ `last_working_day`**
  → **LOCKED** per §8: closes normally at `last_working_day`.
- Open assignment/compensation row with `effective_from` **>** `last_working_day` → **OPEN** (§8) —
  do not write this test's expected assertion until §8 is resolved; write the test scaffold now,
  mark it `xfail`/skipped with a comment citing this document, per the instruction not to invent
  the behavior.

### Rehire — LOCKED
- Terminate Employment #1 (with an open assignment + compensation) → create Employment #2 → create
  Assignment #2 / Compensation #2 → assert:
  - Employment #1's closed assignment/compensation rows show `effective_to =
    employment_1.last_working_day` (not `rehire.effective_from - 1`, replacing the two existing
    tests' current assertions, §3).
  - `get_current_assignment`/`get_current_compensation` return `None` for the employee in the gap
    (a new assertion the current tests don't make, since today it's never `None`).
  - Assignment #2/Compensation #2 insert via the **"no current row"** branch (verifiable indirectly:
    no `AssignmentVersionRequiredError`/`CompensationVersionRequiredError` is raised even when no
    `If-Match`/`expected_version` is supplied — today's rehire tests already supply
    `if_match=str(pre_exit["version"])`, §9's "current" tests must be updated to *not* supply one,
    since after the fix there is no current row for the rehire's first insert to conflict with).
  - Employment #1's rows remain permanently queryable, unchanged in every other field.

### Concurrency — LOCKED (behavior), RECOMMENDATION (exact error shape, §15)
- Stale `If-Match` on the terminate call itself → unchanged existing `409` behavior.
- Concurrent `POST .../assignments` (transfer) racing a `POST .../terminate` for the same employee
  → whichever commits first wins; the loser's transaction rolls back entirely (assert: no partial
  state — either the transfer's new row exists and termination did *not* close anything, or
  termination closed the pre-transfer row and the transfer request itself failed with a version
  conflict against the employment/assignment it read).
- Repeated termination → unchanged `409 EMPLOYMENT_NOT_ACTIVE`, no new assignment/compensation
  writes attempted (assert audit row counts don't grow on the second call).
- Injected failure on the compensation close (e.g., a forced stale version) after the assignment
  close already succeeded, before commit → assert the **whole** request rolls back: re-fetching
  after the failed request shows the assignment still open, `employment.status` still `ACTIVE`.
  This is the concrete test for §10/§11's "rollback undoes everything" claim — do not skip it.

### Tenant isolation — LOCKED
- Cross-tenant employee id on the terminate call → unchanged `404` (existing coverage, re-run
  unmodified — this fix does not touch tenant-scoping code).
- The new assignment/compensation repository calls the fix adds use the same `(company_id,
  employee_id)`-filtered queries every other method on those repositories already uses — no new
  cross-tenant surface is introduced; a dedicated new test is low-value here but may be added for
  completeness.

### Audit — LOCKED
- All three audit rows (or fewer, per Missing-data) reference the correct `entity_id` for their own
  table (`employment.id`, `employee_assignment.id`, `employee_compensation.id` respectively — not
  all three pointing at the employment id).
- `before`/`after` snapshots on `ASSIGNMENT_CHANGED`/`COMPENSATION_REVISED` show only `effective_to`
  (and `version`/`updated_at`) differing — every business column identical before and after,
  verifying the "close never touches business columns" invariant (§7) at the audit-log level, not
  just the DB level.

---

## 18. Failure Scenarios

| Scenario | Current (unfixed) behavior | Behavior after this fix |
|---|---|---|
| Terminate, never rehired | Assignment/compensation stay open forever; any `as_of` query, including one issued by a future Attendance/Payroll module, sees a terminated employee as still placed and still paid | Rows close at `last_working_day`; `as_of` queries after that date return nothing for this employee, matching an exited employee correctly |
| Terminate, rehire later | Stale row closes at the wrong date on rehire's first write, corrupting the historical boundary permanently (§3) | Stale row already closed correctly before rehire; rehire's first write takes the clean "no current row" path (§9) |
| Terminate with a future-dated open row starting after the new exit date | Row stays open with a now-meaningless future date (subset of the "never rehired" row above) | **OPEN** (§8) — not specified by this plan |
| Concurrent transfer + terminate | No interaction today (transfer touches assignment, terminate touches only employment — no shared row) | New interaction: whichever commits first wins; loser's whole transaction rolls back (§11) — a new failure mode this fix **introduces**, but a safe one (fail-and-retry, never silent corruption) |
| Partial failure (assignment closes, compensation close then fails) | N/A — no closes attempted today | Whole transaction rolls back; nothing committed (§10) — must be verified by a test that injects exactly this failure (§17 Concurrency), not merely assumed from the architecture |

---

## 19. Open Product Decisions

Only genuine, unresolved questions — not items already answered by existing documentation:

**OD-1. What happens when the employee's current assignment/compensation row is future-dated
*beyond* the new `last_working_day`?** (§8) No source document addresses this; the system has no
mechanism to retract an already-inserted effective-dated row at all. This plan recommends
rejecting the terminate call in that specific case (§8, §15) as the least-bad default, but does not
lock that recommendation — a product/architecture decision is needed before that one code path is
implemented. **This does not block implementing the ordinary case (§7).**

**OD-2. Should `ASSIGNMENT_CHANGED`/`COMPENSATION_REVISED` audit ordering be interleaved with each
close, or batched at the end alongside `EMPLOYMENT_TERMINATED`?** (§14) Not correctness-bearing
(transaction atomicity is unaffected either way), but worth a conscious choice for audit-log
readability consistency across the module. Low stakes — either answer is implementable without
revisiting this plan.

**OD-3. Does the retroactive-correctness gap need a data backfill for already-terminated
employments?** (§20 risk) This fix only changes behavior for *future* calls to
`terminate_employment`; any employment already terminated under the current bug (in any environment
where real termination calls have already happened — dev/staging test data included) will still
have a stale open assignment/compensation row unless separately backfilled. This plan is explicitly
not authorized to write a migration or backfill script (task scope), but the decision of whether
one is needed, and for which environments, is a genuine open item for whoever implements this plan.

---

## 20. Locked Decisions

Restated for this plan's own scope, cross-referencing `HRMS_ARCHITECTURE_DECISION_LOG.md` where a
`DEC-NNN` exists, and this plan's own §-references where the "lock" is this plan's synthesis of
existing documentation rather than a numbered log entry:

- Effective-dating pattern, GiST-enforced no-overlap, close-then-insert, insert-never-update —
  `DEC-003`. Unchanged, unextended in kind by this fix (§7).
- `employee_assignment`/`employee_compensation` keyed on `employee_id`, never `employment_id` —
  `DEC-016`. Load-bearing for why this fix cannot corrupt a rehire (§9).
- Ordinary-case closing boundary is `effective_to = last_working_day` — sourced from
  `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D (§3, §7); not itself a `DEC-NNN` entry, but the
  only documented target shape and adopted as this plan's specification.
- One request = one transaction, commit-on-success/rollback-on-exception via `get_session` — FACT,
  `core/db/session.py:71-83`, unmodified by this fix (§4, §10).
- Cross-tenant access is always `404` — `DEC-028`. Unaffected by this fix; no new cross-tenant
  surface introduced.
- Effective-dated sub-resources are insert-only via `POST`, never `PATCH`/`DELETE` on an individual
  row — `DEC-029`. This is precisely why OD-1 (§19) has no existing mechanism to lean on — a
  "retract" operation would be a new kind of write this decision doesn't currently accommodate.

---

## 21. Recommended Implementation Design

**Service-layer only, no schema change, no new repository method, no new permission, no API
contract change** (for the ordinary case, §7; OD-1 in §19 is explicitly excluded from this
recommendation and must be separately resolved before its own code path is written).

`EmploymentService.__init__` gains two new dependencies:
```python
self._assignment_repo = EmployeeAssignmentRepository()
self._compensation_repo = EmployeeCompensationRepository()
```
(Both classes already exist, already imported elsewhere in this same module — `service.py`'s
existing `EmployeeAssignmentService`/`EmployeeCompensationService` already instantiate them
identically. This is an intra-module dependency, not a new cross-module import — `Employment`,
`EmployeeAssignment`, and `EmployeeCompensation` all live inside `modules/employee/`, so Module
Standard §2's cross-*module* boundary rule does not apply here; this stays within one module's own
service layer reaching into that same module's own pure-query repositories, mirroring the
docstring's own description of a repository as "no business rules" reusable plumbing.)

`terminate_employment` gains, between the existing validation (§2 steps 1-4) and the existing
`update_employment` call (§2 step 5):
1. `current_assignment = await self._assignment_repo.get_current_assignment(...)`
2. If present: validate against OD-1's eventual resolution (§8/§19); if the ordinary case, call
   `close_assignment(effective_to=body.last_working_day, expected_version=current_assignment.version,
   ...)`; handle `None` → `StaleResourceError`, same shape as every other close-site in this module.
3. Same two steps for `current_compensation`/`close_compensation`.
4. Existing `update_employment` call, unchanged.
5. Audit calls per §14 (two new, one existing, all inside the same method, same transaction).

No change to `EmployeeAssignmentRepository`/`EmployeeCompensationRepository` — `close_assignment`/
`close_compensation` already have exactly the right signature and contract for this use (§1).

---

## 22. Exact Files Expected to Change

(when this plan is later implemented — nothing below was touched to produce this plan)

- `apps/api/src/hrms/modules/employee/service.py` — `EmploymentService.__init__` and
  `terminate_employment` (§21). The only file with new business logic.
- `apps/api/tests/unit/modules/employee/test_employment_service.py` — new unit tests (§17 Basic/
  Missing-data/Historical), mocked repository behavior for the two new close calls.
- `apps/api/tests/integration/modules/employee/test_employment.py` — new integration tests (§17
  Basic/Concurrency/Audit), exercising real closes against the live GiST-constrained tables.
- `apps/api/tests/integration/modules/employee/test_employee_assignment.py` —
  `test_rehire_first_assignment_after_gap` **must be updated**, not left passing against the old
  boundary date (§3, §17 Rehire) — its docstring and assertion both describe the *current bug* as
  expected behavior and will be factually wrong once this fix ships.
- `apps/api/tests/integration/modules/employee/test_employee_compensation.py` —
  `test_rehire_first_compensation_after_gap`, same update, same reason.
- **Not expected to change:** `router.py` (§15), `permissions.py` (§13), `repository.py` (§21 —
  reuses existing methods verbatim), `models.py` (§16 — no new column), `schemas.py` (§15 — no
  request/response shape change), any Alembic migration (§16), `exceptions.py` (§15 — recommend
  reusing `StaleResourceError` rather than adding a class; revisit only if OD-1's resolution needs a
  new error).

---

## 23. Explicit Non-Goals

- No migration, no schema change, no new column, no new table.
- No new permission code.
- No API request/response contract change.
- No change to `EmployeeAssignmentService`/`EmployeeCompensationService`'s own write paths
  (`create_assignment`/`create_compensation`) — they are correct as built; the bug is entirely
  `EmploymentService`'s omission, not anything wrong with how those two services close/insert rows
  themselves (§9).
- No resolution of OD-1 (§19) — the future-dated-beyond-exit edge case is explicitly out of this
  plan's scope to decide, only to surface.
- No data backfill script for already-terminated employments (OD-3, §19) — flagged, not designed.
- No change to `employee.status`'s own lifecycle (FR-EMP-014's broader state machine) — out of
  scope, unrelated to this specific defect.
- No attempt to build the BR-14 shift-override chain, Attendance, Leave, or Payroll — this plan
  exists specifically because those modules depend on this fix landing first, not because this plan
  builds any part of them.

---

## 24. Implementation Sequence

1. Resolve OD-1 (§19) — or explicitly scope the first implementation PR to the ordinary case only
   (§7) and land OD-1's future-dated handling as a fast-follow once decided, per this plan's own
   framing that OD-1 does not block the ordinary-case fix.
2. Implement `EmploymentService.terminate_employment`'s two new close steps (§21).
3. Update the two existing rehire integration tests whose assertions currently encode the bug (§3,
   §17 Rehire, §22).
4. Add the new test coverage in §17 (Basic, Missing-data, Historical, Concurrency, Audit — and
   Future-dated once OD-1 is resolved).
5. Run the full backend suite (`uv run pytest` from `apps/api/`) to confirm no regression in
   `organisation`/`identity`/`health` or the rest of `employee` — matching every prior slice's own
   validation discipline (E-03/E-04/E-06 reports all report full-suite green before closeout).
6. Decide OD-3 (§19) — whether any already-terminated employment in a shared dev/staging database
   needs a one-off data fix, separately from this code change.
7. Only after this lands: resume the roadmap's next step,
   `HRMS_SYSTEM_DESIGN_BASELINE.md §21` item 2 (RBAC data-scope enforcement), then E-07 Statutory.

---

## 25. Risks and Rollback Strategy

**Risks:**
- **Retroactive gap (OD-3).** This fix is forward-only; any pre-existing terminated employment with
  a still-open assignment/compensation row stays wrong until separately backfilled. Real risk in any
  environment where termination has already been exercised against non-empty data — not a risk in a
  genuinely empty database, but should not be assumed empty without checking (`001_init_schema.sql`
  had zero rows for `employment` when E-03 shipped; that fact is now a historical snapshot, not a
  current guarantee, per this task's own instruction not to trust a memory/snapshot claim without
  re-verifying current state at implementation time).
- **New concurrency failure surface (§11, §18).** Terminating an employee now has two more ways to
  fail (409) than before, if a transfer or compensation revision races it. This is a deliberate,
  safe trade — fail-and-retry over silent corruption — but it is user-visible new behavior
  (a termination that would have silently "succeeded" against stale data before could now correctly
  409 instead) and should be called out in whatever release notes accompany this change.
- **Multiple-open-rows assumption.** The fix assumes at most one open `employee_assignment`/
  `employee_compensation` row per employee, which `scalar_one_or_none()` on `get_current_assignment`
  /`get_current_compensation` will raise `MultipleResultsFound` against if ever violated. This is an
  existing assumption inherited from E-04/E-06, not new to this fix, and is itself protected by the
  GiST exclusion constraints — noted here only so a future debugger doesn't mistake a
  `MultipleResultsFound` exception for something this fix introduced.
- **Downstream modules built before this fix lands.** If Attendance/Payroll are ever built against
  `get_assignment_as_of`/`get_compensation_as_of` before this fix ships, they will inherit the wrong
  assumption into their own logic and require their own re-validation once this fix lands — this is
  exactly the reason `HRMS_SYSTEM_DESIGN_BASELINE.md` sequences this fix first (§21 item 1 of that
  document). Not a risk of *this* plan; a risk of *not* implementing it before those modules start.

**Rollback strategy:** the fix is additive service-layer logic with no schema change, so rollback is
a plain code revert — no migration downgrade is needed. The only state a rollback would need to
reason about is: any assignment/compensation rows closed by the fix while it was live remain closed
after a code revert (closing is a normal, valid write within the existing effective-dating pattern,
not something a revert needs to undo) — a reverted deploy simply stops closing *new* terminations'
rows, reintroducing the original bug going forward, without corrupting anything the fix already
correctly closed.
