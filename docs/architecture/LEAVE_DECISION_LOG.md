# Leave Module Decision Log

**Status:** Architecture decision record. No application code, schema, migrations, frontend
code, or tests were created or modified to produce this document.

**Date:** 2026-08-30

**Companion:** `docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md` (the module this one is
carved out of and must stay compatible with), `docs/adr/0004-leave-ledger.md`,
`docs/architecture/HRMS_ARCHITECTURE_DECISION_LOG.md` (DEC-004).

**Trigger:** client sign-off review, §M question 3 — *"i want to build the leaves module"*
(`docs/business-rules/ATTENDANCE_V1_CLIENT_SIGNOFF.md` §M, change requested, 2026-08-25). Flagged
at the time as its own initiative requiring a dedicated architecture pass, not a WD entry in the
Attendance log, since Leave is a new standalone module rather than a change to an existing one.

**How to use this log:** same discipline as the Attendance decision log — every **LOCKED** entry
is settled; every **OPEN** entry must not be guessed in implementation. Numbering: `LD-NN` (Leave
Decision), so these do not collide with `WD-NN` (Attendance) or `DEC-NNN` (core architecture).
Existing ADR/DEC entries remain in force unless an LD entry explicitly records a divergence.

**STOP.** Implementation does not start until this log is reviewed and explicitly approved —
several entries below are genuinely OPEN (accrual numbers, sandwich-leave rules, negative-balance
policy) and must not be guessed.

---

## LD-01 — Module boundary: Leave becomes the writer of `LeaveDayProjection`, not its replacement

**Status:** LOCKED (resolves `PD-LEAVE-1`, open since Attendance decision log WD-31).

**Context:** Attendance's W9 slice built `LeaveDayProjection` as an explicit, self-described
temporary stand-in — its own docstring calls it "Attendance's own temporary backing store...
not the leave ledger... replaceable wholesale once a real Leave module exists." WD-31 left open
whether the real Leave module should *replace* this table (Attendance switches to a real
in-process service call, table dropped) or *become its writer* (same table, same contract,
different owner).

**Decision:** become the writer. Leave module's application-approval flow calls the exact same
sync contract Attendance already exposes (`POST /leave-projections`, `LeaveProjectionSync`
schema: `employee_id, attendance_date, leave_application_id, leave_type_id, leave_type_code,
fraction, half, is_paid`) instead of writing to the table directly — reusing
`LeaveProjectionService.sync()`'s existing validation (overlap rejection, period-lock check,
recompute trigger) rather than duplicating it. Attendance's `calculation.py` (`_apply_leave_overlay`,
`AttendanceCalculationInput.leave_entries`) is **not touched at all** by this module.

**Rejected:** replacing `LeaveDayProjection` wholesale now. That requires touching
`calculation.py`'s leave-overlay funnel point and every attendance test that exercises leave —
real risk to a module that just shipped and was signed off, for zero functional gain today.
Revisit only if the mirror-table contract (a flat fraction/half pair per day) becomes a genuine
limitation for a Leave feature this plan doesn't yet anticipate.

---

## LD-02 — Data model: five new tables, `leave_ledger` append-only per ADR-0004

**Status:** LOCKED (shape) · field-level specifics OPEN where noted.

**Decision:**

```
leave_type              — identity: code, name, is_paid_default, requires_balance (LOP-style
                           types don't consume a balance), is_active, deleted_at, version.
                           Mirrors AttendancePolicy's identity-row-only pattern.

leave_policy             — identity row only (name, code, is_active), mirrors AttendancePolicy.
leave_policy_version     — the versioned config: status (DRAFT/PUBLISHED), version,
                           effective_from/effective_to, accrual_frequency, accrual_rate,
                           max_carry_forward, encashment_rules, sandwich_rule fields,
                           approval_chain, backdating_window_days, requests_per_month_cap.
                           Mirrors AttendancePolicyVersion's draft/publish/discard lifecycle
                           exactly (immutable once PUBLISHED).

leave_ledger             — APPEND-ONLY (ADR-0004/DEC-004, no exceptions). employee_id,
                           leave_type_id, entry_type (ACCRUAL / APPLICATION / ADJUSTMENT /
                           ENCASHMENT / CARRY_FORWARD / COMP_OFF_CREDIT), amount (signed
                           Decimal, days), reference (e.g. leave_application_id or
                           overtime_record_id for comp-off credits), effective_date, created_by,
                           created_at. No update, no delete, no soft-delete flag — corrections are
                           new ADJUSTMENT rows, same posture ADR-0005 already established for
                           payroll postings.

leave_application        — employee_id, leave_type_id, date range, per-day fractions, status
                           (SUBMITTED/APPROVED/REJECTED/CANCELLED), approval_chain,
                           approval_stage, resolved_approver_manager_id,
                           regularization-request-shaped fields throughout. Same shape as
                           AttendanceRegularizationRequest, not shared code (see LD-05).

leave_application_action — append-only approval history: id, request_id, action, actor_user_id,
                           actor_employee_id, stage, comment, created_at. Mirrors
                           AttendanceRegularizationAction exactly — needed for the same reason
                           (a single reviewed_by/reviewed_at pair can't hold a MANAGER_THEN_HR
                           chain's full history).
```

Balance for `(employee_id, leave_type_id)` is **always** `SUM(leave_ledger.amount WHERE ...)` —
never a stored counter. This is DEC-004, not a style preference; no code path may write a
`balance` column anywhere.

**OPEN — accrual/policy field specifics:** the field *shapes* above are locked, but their
*values* (accrual rate, frequency, max carry-forward, encashment percentage, requests-per-month
cap, backdating window) are HR-configurable policy fields, same as every Attendance policy field
— they need real client numbers before `leave_policy_version` rows can be published, exactly like
grace-minutes/half-day-thresholds did for Attendance. Not guessed here.

---

## LD-03 — Balance computation: derived sum, no cache in the first cut

**Status:** LOCKED.

**Decision:** balance queries run `SELECT SUM(amount) FROM leave_ledger WHERE employee_id = :eid
AND leave_type_id = :ltid` (or GROUP BY for a full balance summary), backed by a composite index
on `(company_id, employee_id, leave_type_id)`. No materialized/cached running-total column in the
first cut — leave-ledger volume is orders of magnitude below attendance-punch volume (ADR-0004's
own stated tradeoff), so a live sum is expected to be cheap enough. If a future profiling pass
shows otherwise, a cached total may be added *behind* the ledger (read-through cache, never a
second source of truth) — not decided here, flagged only as a possible future LD entry.

---

## LD-04 — Policy assignment: new `policy_kind="LEAVE_POLICY"`, reuse the existing precedence walk

**Status:** LOCKED.

**Decision:** `leave_policy_version` is assigned via the existing `PolicyAssignment` table, adding
`"LEAVE_POLICY"` to the `_POLICY_KINDS` allow-list (`organisation/schemas.py`, currently
`WORK_CALENDAR`/`WEEKLY_OFF`/`ATTENDANCE_POLICY`/`OVERTIME_POLICY`/`REGULARIZATION_POLICY`) —
naming matches the existing `_POLICY` suffix convention exactly. Resolution reuses
`resolve_policy_assignment()`'s existing 8-level "most specific wins" walk
(Employee → Shift → Designation → Grade → Department → Branch → Legal Entity → Company) verbatim
— no new precedence logic. No new `scope_type` values needed.

**Rejected:** a Leave-specific assignment/precedence mechanism. The existing one is generic
across policy kinds already (WD-09) and gains nothing from a parallel implementation.

---

## LD-05 — Approval workflow: mirror Regularization's chain logic, don't share code

**Status:** LOCKED.

**Decision:** `leave_application`'s approval chain reuses the exact `AUTO`/`MANAGER`/
`MANAGER_THEN_HR`/`HR` resolution shape already implemented (independently) in both
Regularization and Overtime services: chain type comes from the policy version;
`MANAGER`/`MANAGER_THEN_HR` resolve `resolved_approver_manager_id` via
`EmployeeAssignmentService.get_assignment_as_of(company_id, employee_id, target_date)`;
resolution failure (no manager on record) routes to HR and audits — never auto-approves on
failure. This is the third independent implementation of this exact pattern (after
Regularization and Overtime), which is consistent with this codebase's existing convention:
`core`/cross-module code sharing is restricted by the Module Standard's import-linter contract,
so each module owns its own copy rather than importing another module's `service.py` internals.

**Rejected:** extracting a shared `ApprovalChainResolver` into `hrms.core`. Tempting given three
near-identical implementations, but doing so now would mean refactoring two already-shipped,
already-tested modules (Regularization, Overtime) as a side effect of building a third one — out
of this plan's blast radius. Worth flagging as a real future refactor candidate once a fourth
consumer appears, not decided here.

---

## LD-06 — Accrual engine

**Status:** OPEN (mechanism partially designed below; values and several mechanism-level
questions are not decided).

**Context:** this is the one genuinely novel piece of infrastructure in this module — nothing
elsewhere in the codebase does periodic, proration-aware balance crediting.

**Proposed mechanism (not locked):** a scheduled job (reusing whatever job-running mechanism the
codebase settles on — none exists yet outside the trivial `health.ping` Celery task found during
the RLS audit) that, per published `leave_policy_version`'s `accrual_frequency`, inserts one
`leave_ledger` `ACCRUAL` row per eligible employee per cycle. Proration for an employee who joins
mid-cycle uses `Employment.joining_date`; accrual stops the cycle `Employment.last_working_day`
falls in.

**OPEN — must be answered before L3 starts, not guessed:**
1. Accrual rate(s) and frequency per leave type — client-specific numbers, not yet given.
2. Carry-forward cap and whether it varies by leave type.
3. Encashment: automatic at a fixed point (e.g. fiscal year-end) or always HR-initiated?
4. **Negative balance**: is an employee ever allowed to go negative (advance leave), or is every
   application hard-capped at current balance? No existing pattern in this codebase to infer from.
5. **Sandwich-leave rule**: if an employee takes leave either side of a weekend/holiday, does the
   weekend/holiday itself count as leave too? Flagged as a known open question in the existing
   Attendance audit docs, never answered by the client.

---

## LD-07 — Comp-off redemption + expiry enforcement

**Status:** LOCKED (mechanism) · one OPEN sub-question.

**Context:** Attendance already emits comp-off as a fact (`OvertimeRecord.comp_off_minutes` +
`comp_off_expiry_date`, `AttendanceDay.comp_off_minutes_earned`, `AttendancePeriodSummary`
roll-up) per its own architecture §12.3 contract: *"Attendance does not credit a leave ledger...
It emits an immutable fact... for Leave to append a ledger row when Leave exists."* Confirmed in
client sign-off §P as explicitly out of Attendance's scope. **Nothing today enforces
`comp_off_expiry_date`** — a real, currently-nowhere-implemented gap this module inherits.

**Decision:** Leave module reads `OvertimeRecord.comp_off_minutes`/`comp_off_expiry_date` as an
inbound fact (read-only — Leave never writes to Attendance tables) and appends a
`COMP_OFF_CREDIT` row to `leave_ledger` when an `OvertimeRecord` reaches its terminal
approved-with-comp-off state. Leave module owns expiry enforcement: a scheduled sweep that
appends an offsetting `ADJUSTMENT` row (never deletes/mutates the original credit — ADR-0004) for
any comp-off credit whose `expiry_date` has passed and remains unconsumed.

**OPEN:** exact redemption UX — does an employee explicitly "spend" comp-off against a specific
leave application, or is it just another balance that any leave application draws down
first-in-first-out alongside regular leave? Needs a decision before L5.

---

## LD-08 — RBAC: `LEAVE.*` permission codes, same convention as Attendance

**Status:** LOCKED.

**Decision:** new `LEAVE_PERMISSIONS` list, same two-part underscore-joined convention Attendance
uses (not the three-part dotted convention shown as an example in `02_Module_Standard.md`, which
the actual codebase has never followed): `LEAVE.APPLICATION_SUBMIT`,
`LEAVE.APPLICATION_SUBMIT_ON_BEHALF`, `LEAVE.APPLICATION_APPROVE`, `LEAVE.POLICY_MANAGE`,
`LEAVE.BALANCE_VIEW`, `LEAVE.BALANCE_VIEW_ALL`, `LEAVE.BALANCE_ADJUST`. Reads reuse `.VIEW`-style
codes rather than adding separate list/get codes, matching the explicit repeated convention
already stated in Attendance's own `permissions.py` comments (WD-28/29/30/31 decision 6/6/7/9).
Data-scope reuses the existing 4-level `DataScopeLevel` (`SELF`/`REPORTEES`/`REPORTEE_TREE`/
`COMPANY`) unchanged — no new scope level needed.

---

## LD-09 — Phasing

**Status:** LOCKED (sequence) · each slice's own field-level specifics gated by its OPEN items
above.

| Slice | Scope | Blocked on |
|---|---|---|
| **L1** | `leave_type`, `leave_policy`/`leave_policy_version` (identity+config, no evaluation), `PolicyAssignment` wired for `LEAVE_POLICY`, permission scaffolding | Nothing — pure reuse of existing patterns (LD-02 shape, LD-04, LD-08) |
| **L2** | `leave_ledger`, balance computation, manual adjustment entries (HR can view/adjust balances by hand) | L1 |
| **L3** | Accrual engine | L2 + LD-06's OPEN items answered |
| **L4** | `leave_application` + approval workflow, writes `LeaveDayProjection` via the existing sync contract on approval | L2, LD-01, LD-05 |
| **L5** | Comp-off redemption + expiry sweep | L2, LD-07's OPEN sub-question answered |
| **L6** | Frontend: balance display, application submission, approval review queue, policy config UI — mirrors existing Regularization/Attendance-Policy UI exactly | L4 |

L1–L2 alone already give HR a working, auditable balance ledger before accrual automation exists
— same "each slice independently shippable" discipline as Attendance's W1–W9.

---

## Divergences index (quick reference)

| Prior source | This log |
|---|---|
| WD-31's `PD-LEAVE-1` (open: replace `LeaveDayProjection` or become its writer?) | LD-01 (become the writer — resolved) |
| `02_Module_Standard.md`'s three-part dotted permission-code example (`LEAVE.APPLICATION.CREATE`) | LD-08 (actual codebase convention is two-part underscore-joined, matching what Attendance actually shipped, not the doc's illustrative example) |

---

**STOP.** L1 does not start until: (a) this log is reviewed and approved, and (b) at minimum
LD-06's five OPEN questions and LD-07's one OPEN question have real answers — the same discipline
that gated every WD entry in the Attendance log before its implementation began.
