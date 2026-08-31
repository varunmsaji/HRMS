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

**Status:** LOCKED.

**Context:** this is the one genuinely novel piece of infrastructure in this module — nothing
elsewhere in the codebase does periodic, proration-aware balance crediting.

**Mechanism:** a Celery Beat-scheduled task, `leave.run_monthly_accrual` — this exact name and
"monthly cron" schedule is already specified in `docs/architecture/04_Background_Job_Architecture.
md` §5, not invented here. Correction to this log's earlier note: Celery + Redis is not an open
question — it's the locked, ADR-0014-backed job system for this codebase (`entrypoints/worker.py`,
`entrypoints/beat.py` already scaffolded; only the trivial `health.ping` task exists today, but the
infrastructure and conventions — `company_id` first task argument, task naming
`module.verb_noun`, DB session + RLS set inside the task body — are already decided in §3 of that
doc). Per published `leave_policy_version`'s `accrual_frequency`, the task inserts one
`leave_ledger` `ACCRUAL` row per eligible employee per cycle. Proration for an employee who joins
mid-cycle uses `Employment.joining_date`; accrual stops the cycle `Employment.last_working_day`
falls in.

**Decisions (client answers, 2026-08-31):**
1. **Accrual rate/frequency per leave type**: HR-configurable, not hardcoded — set via
   `LeavePolicyVersion.accrual_frequency`/`accrual_rate_per_cycle`, one policy per leave type
   (see LD-10). No fixed numbers baked into code; the engine reads whatever the published version
   says.
2. **Carry-forward cap**: also HR-configurable, not hardcoded — `LeavePolicyVersion.
   max_carry_forward_days`, per policy (i.e. per leave type, via LD-10's binding). A leave type
   with no cap set carries forward unlimited; `0` means use-it-or-lose-it.
3. **Encashment**: always HR-initiated. `encashment_allowed` on the policy version gates whether
   it's allowed at all; no automatic fiscal-year-end sweep is built. HR creates the `ENCASHMENT`
   ledger entry explicitly (L5-adjacent, uses the same manual-entry shape as L2's `ADJUSTMENT`).
4. **Negative balance**: never allowed. Every leave application is hard-capped at the employee's
   current balance at time of application (enforced in L4). `allow_negative_balance` stays
   `False`-only for now — the column remains in the schema (LD-02 lock) but nothing sets it `True`
   until a future client asks for advance leave.
5. **Sandwich-leave rule**: applies. A weekend/holiday sandwiched between two leave days is
   itself counted and deducted as leave. `sandwich_rule_enabled` defaults `True` for newly
   created leave policy versions going forward (L3 scope: the day-counting logic that honors
   this flag when computing how many days an application/accrual period actually deducts).

---

## LD-10 — `LeavePolicy` must bind to exactly one `LeaveType`

**Status:** LOCKED.

**Context:** found while implementing HR-configurable accrual (LD-06 items 1–2). `LeavePolicy`/
`LeavePolicyVersion` (L1) carry accrual rate, carry-forward cap, etc., but the L1 schema never
linked a policy to *which* leave type those settings apply to — a real gap, not caught by L1's
tests because L1 never exercised accrual fields end-to-end. `leave_policy` has 0 rows in every
environment (dev included), so this is a clean schema fix, not a backfill.

**Decision:** add `leave_type_id: UUID` (FK → `leave_type.id`, `NOT NULL`) to the `LeavePolicy`
identity row (not `LeavePolicyVersion` — the binding doesn't change across a policy's versions,
mirrors why `code`/`name` live on the identity row too). Not unique: multiple `LeavePolicy` rows
may target the same `LeaveType` (e.g. "Casual Leave — HQ" vs "Casual Leave — Remote", assigned to
different scopes via the existing `PolicyAssignment` precedence mechanism, LD-04). HR creates one
`LeavePolicy` per (leave type × scope) combination that needs distinct rules.

---

## LD-11 — `PolicyAssignment` needs a `leave_type_id` dimension for `LEAVE_POLICY`

**Status:** LOCKED.

**Context:** found while building L3's employee→policy resolution. `policy_assignment_no_overlap`
(`20260818130000_policy_assignment.py`) excludes on `(company_id, policy_kind, scope_type,
scope_id, daterange)` — correct for every other `policy_kind`, where exactly one policy governs a
scope at a time (one work calendar, one attendance policy, etc.). Leave is structurally different:
a company legally needs *multiple simultaneous* leave policies at the same scope — one per leave
type (Casual, Earned, Sick each accrue differently). As shipped, LD-10's `leave_type_id` binding
on `LeavePolicy` is meaningless for resolution, because assigning a second `LEAVE_POLICY` (for a
different leave type) at the same scope and overlapping dates is rejected outright by the
exclusion constraint — there is no way today to have both a Casual Leave policy and an Earned
Leave policy active at COMPANY scope at once. `policy_assignment` has 0 rows in every environment,
so again a clean fix, not a backfill.

**Decision:** add `leave_type_id: UUID | None` to `policy_assignment` (FK → `leave_type.id` — a
real FK, unlike the polymorphic `policy_id`, since this column is never anything but a leave type
once populated). `NULL` for every existing `policy_kind`; `NOT NULL` iff `policy_kind =
'LEAVE_POLICY'` (CHECK, mirrors `scope_id_null_iff_company_check`'s pattern exactly). Widened
exclusion constraint adds `COALESCE(leave_type_id, '00000000-...'::uuid) WITH =` as a new
equality term — same sentinel-for-NULL trick already used for `scope_id`, so non-LEAVE_POLICY
rows (`leave_type_id` always NULL → always the same sentinel) keep today's exact behavior, while
LEAVE_POLICY rows now partition by leave type too. `get_current`/`find_effective`
(`organisation/repository.py`) and `resolve_policy_assignment`
(`organisation/calendar_resolution.py`) all gain an optional `leave_type_id` filter parameter,
threaded through from the router. `_validate_policy_reference`'s `LEAVE_POLICY` branch
additionally checks the referenced `LeavePolicy.leave_type_id` matches the assignment's
`leave_type_id` — rejects a request that names a Casual Leave policy but tags it as the Earned
Leave assignment.

---

## LD-07 — Comp-off redemption + expiry enforcement

**Status:** LOCKED.

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

**Redemption UX (client answer, 2026-08-31):** explicit spend — an employee must explicitly
choose to apply comp-off balance against a specific leave application, not an automatic
first-in-first-out draw-down alongside regular leave.

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
| **L1 — DONE** | `leave_type`, `leave_policy`/`leave_policy_version` (identity+config, no evaluation), `PolicyAssignment` wired for `LEAVE_POLICY`, permission scaffolding | Nothing — pure reuse of existing patterns (LD-02 shape, LD-04, LD-08). Shipped: also required widening the DB-level `policy_assignment_policy_kind_check` CHECK constraint, not just the Pydantic allow-list — a real gap LD-04 didn't anticipate, found by manually testing the assignment endpoint end-to-end. |
| **L2 — DONE** | `leave_ledger`, balance computation (`GET /leave-balances`), manual adjustment entries (`POST /leave-ledger/adjustments`, HR can view/adjust balances by hand), raw audit trail (`GET /leave-ledger`) | L1. Shipped: `LEAVE.BALANCE_VIEW`/`LEAVE.BALANCE_VIEW_ALL` read-gating uses the `cancel_regularization_request` combined-`DataScope` union shape (`attendance/router.py`) — the closest existing precedent for a route accepting either of two permission grants, confirmed via research before implementing rather than inventing a new pattern. |
| **L3 — DONE** | Monthly accrual engine (`LeaveAccrualService.run_for_company`, `leave.run_monthly_accrual`/`leave.accrue_company` Celery tasks, Beat-scheduled) | L2 + LD-06's items answered. Shipped: found and fixed two real gaps along the way — LD-10 (`LeavePolicy` had no `LeaveType` binding) and LD-11 (`PolicyAssignment`'s exclusion constraint didn't allow multiple simultaneous `LEAVE_POLICY` assignments at one scope, which every leave type needs). Scoped to `MONTHLY` frequency only; `YEARLY` accrual and carry-forward-cap enforcement deferred — no fiscal-year anchor has been decided yet. |
| **L4** | `leave_application` + approval workflow, writes `LeaveDayProjection` via the existing sync contract on approval | L2, LD-01, LD-05 |
| **L5** | Comp-off redemption + expiry sweep | L2, LD-07 (now LOCKED) |
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

**STOP.** L1, L2, and L3 are done. L4 (`leave_application` + approval workflow) is next and is
unblocked — nothing outstanding gates it. L5 is unblocked on decisions (LD-07 is now LOCKED) but
naturally follows L4, since comp-off redemption is redemption *against an application*. The one
remaining genuinely open item is L3's own deferred scope: a fiscal-year anchor for `YEARLY`
accrual and carry-forward-cap enforcement, needed whenever a client actually configures a
`YEARLY`-frequency policy — not required for L4/L5/L6 to proceed.
