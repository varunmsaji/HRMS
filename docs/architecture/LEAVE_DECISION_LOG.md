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

## LD-12 — L4 approval: a closed attendance period fails the whole approval, not just that day

**Status:** LOCKED.

**Context:** `LeaveProjectionService.sync()` (`attendance/service.py:5210`, LD-01's existing
contract) already refuses to publish a `LeaveDayProjection` for a date whose `AttendancePeriod`
is closed, raising `AttendancePeriodClosedError`. A multi-day `leave_application` approval calls
`sync()` once per `leave_application_day` row — Regularization has no precedent for this, since
it never wrote a downstream projection at all.

**Decision (client answer, 2026-08-31):** if any single day's sync fails because its period is
closed, the entire approval is refused — no partial approval, no partially-synced application.
The approver is told which date failed. Keeps `leave_application.status`, the `leave_ledger`
`APPLICATION` entry, and every `LeaveDayProjection` row for that application in lockstep: either
all exist or none do, never a subset.

**Rejected:** partial sync (approve the application, silently skip locked days). Would leave an
"APPROVED" application with some days invisible to Attendance's calculation — a worse, silent
version of exactly the inconsistency ADR-0004/WD-11's "never guess, never partially apply"
posture exists to prevent.

---

## LD-13 — Post-approval cancellation is a first-class action, not an HR-manual correction

**Status:** LOCKED.

**Context:** Regularization's `cancel` (`attendance/service.py:3703-3754`) only permits
cancellation while `status == "SUBMITTED"` — it never needed a post-approval path, since
Regularization touches no balance and publishes no downstream projection. Leave does both, so
this is new design, not a mirror of anything.

**Decision (client answer, 2026-08-31):** an `APPROVED` `leave_application` can still be
cancelled. Doing so writes an offsetting `ADJUSTMENT` ledger entry (credits back `total_days` —
the original `APPLICATION` debit is never mutated or deleted, per ADR-0004) and calls
`LeaveProjectionService.cancel()` for every `leave_application_day` that was synced. Self-service,
no HR intervention required to correct a leave that was approved and then no longer needed.

**Rejected:** requiring HR to manually correct via L2's `POST /leave-ledger/adjustments` +
manual projection cancellation. Workable but pushes routine corrections (employee's plans
changed) onto HR for something the system can safely automate — same reversal shape either way,
just gated behind a person instead of a button.

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

## LD-14 — Comp-off credit engine: four gaps LD-07 locked the shape of but not the mechanism

**Status:** LOCKED.

**Context:** implementing L5 against LD-07 surfaced four real, unanswered questions — the same
"found while implementing" pattern LD-10/LD-11/LD-12 already established for this module. None
of these were guessed; each was confirmed before writing code.

**Decision 1 — which `LeaveType` receives the credit:** `OvertimeRecord` (attendance module) has
no `leave_type_id` of its own. Added `leave_type.is_comp_off: bool` (mirrors the existing
`is_paid_default`/`requires_balance` flags), with a DB partial unique index allowing at most one
active `is_comp_off=true` row per company. A company with none configured is a valid, non-error
state — the credit/expiry engine silently skips crediting for it, same posture
`LeaveAccrualService` already uses for an unconfigured `accrual_rate_per_cycle`.

**Decision 2 — minutes-to-days conversion:** `OvertimeRecord.comp_off_minutes` is minutes;
`leave_ledger.amount` is days, and nothing in the schema expressed a "minutes per day" basis.
Added `overtime_policy_version.comp_off_day_length_minutes` (nullable, HR-configured per policy
version, e.g. `480` for an 8-hour day) — not derived from `Shift` duration, which can vary and
change over time independently of the overtime policy. A policy version with no value set is
skipped, never defaulted to a guessed constant.

**Decision 3 — expiry against a pooled balance:** `leave_ledger`'s balance is always `SUM(amount)`
(LD-03) with no per-entry "remaining" tracking, so "expire the unconsumed remainder of this
specific credit" has no direct implementation without new FIFO lot-tracking infrastructure (no
precedent anywhere in this codebase). **Decision: no FIFO.** The expiry sweep
(`LeaveCompOffService.expire_company`) writes a full offsetting `ADJUSTMENT` for an expired
credit only if the employee's *current* comp-off balance still covers that credit's original
amount; if it doesn't (some of it was already spent, possibly a newer credit drawn down first),
nothing is expired for that credit. Simpler and safe (never drives a balance negative), at the
cost of being slightly generous to the employee in the specific edge case where an older,
now-expired credit was preserved by spending a newer one first.

**Rejected:** strict FIFO reconstruction. Correct to the day, but new algorithmic infrastructure
in money-adjacent logic with no precedent — real risk of a subtle bug, for a scenario (multiple
comp-off credits with different expiry dates, partially drawn down) narrow enough that the
simpler heuristic's edge case is an acceptable tradeoff.

**Decision 4 — trigger direction:** every existing cross-module call in this codebase goes
*Leave → Attendance* (e.g. `_apply_approval`'s call into `LeaveProjectionService.sync()`).
Crediting comp-off synchronously inside Attendance's `OvertimeRecordService.approve()` would
invert that direction — nothing else here has Attendance call into Leave. **Decision:** a polling
Celery sweep instead, mirroring L3's `accrue_company`/`run_monthly_accrual` shape exactly:
`OvertimeRecordService.list_comp_off_facts()` (new, attendance/service.py) is the one read-only
seam Leave calls through — Leave never queries `overtime_record` directly. Credit runs hourly
(`leave.run_comp_off_credit_sweep`) since comp-off is earned continuously, not on a fixed cycle;
expiry runs daily (`leave.run_comp_off_expiry_sweep`) since a validity window can lapse on any
calendar day. Both are idempotent (credit keyed on `reference_id=overtime_record_id`, expiry
keyed on `reference_id=credit.id`), so a missed or repeated run is harmless — credit simply lands
up to one sweep interval after approval rather than instantly.

**Known scaling boundary (not addressed here):** `list_credits_for_expiry` scans every
`COMP_OFF_CREDIT` entry ever written for a leave type on every daily sweep, not an incremental
window — acceptable under ADR-0004's existing "leave-ledger volume is low" assumption for a first
cut, same tradeoff LD-03 already accepted for balance computation itself. Revisit if profiling
ever shows otherwise.

---

## LD-15 — Reserved/Pending Balance: derived live from open applications, no new ledger entry

**Status:** LOCKED.

**Context:** client spec §8 (Leave Balance Calculation) wants Available Balance and Reserved/
Pending Balance shown separately, and says "pending leave should NOT reduce the available
balance permanently unless the company policy requires reservation of balance" — i.e. the
current LD-06 behavior (pending applications never affect the ledger-derived balance) is the
correct *default*, but must be a per-policy toggle, not the only behavior.

**Decision 1 — no new ledger entry type, no stored figure.** "Reserved balance" for
`(employee, leave_type)` is always `SUM(total_days)` over that employee's currently `SUBMITTED`
`leave_application` rows for that type — computed live, exactly the same derived-not-cached
posture LD-03 already established for the ledger balance itself. Nothing is written anywhere
when an application is submitted; the figure simply changes as `leave_application.status`
changes (submitted → reserved goes up; approved/rejected/cancelled → reserved goes down,
automatically, since the query only counts `SUBMITTED` rows).

**Decision 2 — `LeaveBalanceRead.reserved_balance` is always shown, regardless of the toggle.**
Matches the client's "preferably show" framing — HR/employee sees both Available and
Reserved/Pending for every leave type, even for a type where reservation isn't enforced (in
which case it's purely informational: "these applications are pending, but haven't reduced what
you can still apply for").

**Decision 3 — enforcement is a new `LeavePolicyVersion.reserve_balance_on_submission` flag,
default `False`.** When `False` (every existing policy version, unchanged), `submit()`'s
balance-sufficiency check is exactly LD-06's original: only the ledger-derived `balance` is
checked. When `True`, `submit()` additionally subtracts `sum_pending_for_type()` (other
already-`SUBMITTED` applications for that type) before comparing against the new application's
`total_days` — so two pending applications that together exceed the balance can no longer both
be submitted, only however many the balance actually covers.

**Rejected:** a `PENDING_HOLD`-style ledger entry written on submission and reversed on
resolution. Would work, but duplicates information `leave_application.status` already holds
exactly, violates ADR-0004's "the ledger is the append-only record of *resolved* balance
events" framing by writing a ledger row for something not yet decided, and would need its own
reversal-on-every-terminal-transition logic (reject/cancel/approve) that the derived-query
approach gets for free.

---

## LD-16 — Leave combination rules: default-allowed, unordered pair, submit-time only

**Status:** LOCKED.

**Context:** client spec §7 wants configurable pairwise exclusivity between leave types (e.g.
"CL + SL = Not Allowed", "AL + CL = Allowed"). Nothing in this module touched cross-leave-type
interaction before this — every existing check (balance, sandwich rule, reservation) is scoped
to a single leave type.

**Decision 1 — new `leave_combination_rule` table, absence of a row means allowed.** Matches
today's behavior exactly (nothing currently blocks any combination), so introducing this feature
changes nothing for a leave type until HR explicitly adds a `allowed=False` rule for it against
another type.

**Decision 2 — the pair is unordered, enforced by a DB expression index over
`LEAST`/`GREATEST(leave_type_id_a, leave_type_id_b)`**, not by canonicalizing storage order at
the application layer. A rule for (CL, SL) and one for (SL, CL) are the same rule; the unique
index rejects the second insert regardless of which order either was given in.

**Decision 3 — flat identity rows, no draft/publish lifecycle.** Unlike `LeavePolicyVersion`,
a combination rule is a single boolean with no meaningful "draft" state — HR changes a rule by
deleting and recreating it, not by publishing a new version. No `version` column, no optimistic
concurrency — this is deliberately the simplest shape that works, consistent with this
resource's low contention (company-wide config, HR-only).

**Decision 4 — "combination" means two different leave types with active applications
overlapping the same date(s)**, not two leave types within a single application (a
`LeaveApplication` only ever names one `leave_type_id`) and not a leave type spanning a
Weekly-Off/Public-Holiday calendar day (that's already governed by the existing sandwich-rule
day-type classification, LD-06, and needs no new rule — the client's own "AL + Weekly Off =
Allowed" / "AL + Public Holiday = Allowed" examples describe exactly the behavior this codebase
already has). "Active" means `SUBMITTED` or `APPROVED` — a `REJECTED`/`CANCELLED` application
never blocks a new submission, mirroring LD-15's identical definition of "active" for reserved
balance.

**Decision 5 — enforced once, at `submit()`, not re-checked later.** If application A (type X)
is submitted, then application B (type Y, X+Y disallowed) is submitted and rejected for
combination, then A is later cancelled — B was never created, so there's nothing to
retroactively un-reject. If A is instead *approved* while B (a different, already-submitted
type-Y application on the same dates) is still pending, B's own approval attempt would still
succeed today, since this check only runs at submission time — mirrors this module's existing
balance-sufficiency check, which is also submit-time-only (LD-06), not re-verified at approval.
Revisit only if this proves to be a real gap in practice.

---

## LD-17 — Maternity fields: informational only, no new day-counting logic

**Status:** LOCKED.

**Context:** client spec §F lists eligibility, minimum service, entitlement, application
process, supporting documents, start date, expected delivery date, pre-delivery leave,
post-delivery leave, extension, payroll treatment, and approval workflow as things HR must be
able to configure for maternity leave, "not one universal number of days."

**Decision 1 — everything except two items is already covered by the generic engine.**
Eligibility, entitlement, supporting documents, payroll treatment (`is_paid_default`), and
approval workflow are already fully configurable per leave type via the existing `LeaveType`/
`LeavePolicyVersion` machinery — maternity needs no special-casing there, consistent with this
module's "no hardcoded per-leave-type logic" design.

**Decision 2 — `expected_delivery_date` is a generic, optional field on `LeaveApplication`.**
Harmless and simply unused for every non-maternity leave type, the same posture as the existing
generic `attachment_reference`/`half_day` fields. It is never read by day-counting, balance, or
approval logic — purely informational, for HR/coverage planning.

**Decision 3 — "pre-delivery leave"/"post-delivery leave" are policy-level entitlement-split
documentation, not day-counting inputs.** Added `pre_delivery_days`/`post_delivery_days` to
`LeavePolicyVersion` (nullable, e.g. "6 weeks pre + 20 weeks post") — purely informational
config, same treatment as `max_carry_forward_days`. An application's actual day count still
comes from `start_date`/`end_date` exactly like every other leave type; this module makes no
attempt to verify a given application falls within the configured pre/post split against the
(possibly still-unknown, since delivery hasn't happened yet) actual delivery date.

**Decision 4 — "extension" needs no new code.** Nothing in the existing submission flow prevents
an employee from submitting a second application of the same leave type starting the day after
an approved one ends (subject to the normal balance/combination checks, which already apply
generically) — this already satisfies "extension" without inventing a new
amend-an-approved-application feature, which doesn't exist for any leave type today and would be
a materially larger, separate feature if actually needed later.

**Rejected:** an `actual_delivery_date` field with its own update endpoint, and validating
applications against the configured pre/post split. Both are real possible follow-ups, but add
either new-fact-capture-after-the-original-decision machinery or enforcement logic this client
spec didn't actually ask for ("preferably show" language elsewhere in this spec is the closest
precedent for how much enforcement this codebase adds unprompted — none, until asked).

---

## LD-18 — Probation rules: read `Employee.status` directly, no new Employee-module schema

**Status:** LOCKED.

**Context:** client spec §9 wants HR to configure, per leave type: whether a probation employee
may apply at all, whether accrual runs during probation, and (already handled generically by
existing per-leave-type policy assignment, no new work needed) pro-rata entitlement and max
balance during probation. Example: "Probation Employee → CL Allowed → SL Allowed → AL Accrual
Starts After Confirmation."

**Decision — `Employee.status` already carries this fact.** The Employee module's FR-EMP-014
lifecycle enum (`PRE_JOINING, PROBATION, ACTIVE, ...`) already includes `PROBATION` as an
explicit, first-class value — not something Leave needs to derive from `joining_date` +
`Grade.probation_days` (which has no confirmation-event override anyway, e.g. early confirmation
or extended probation, and would make Leave the first, ad-hoc consumer of a probation-duration
concept that doesn't otherwise exist as a computed fact anywhere in this codebase). Leave reads
it read-only via `EmployeeService.get_employee()` — the same "call the owning module's service,
never its repository" seam every other cross-module read in this log already uses (LD-07's
`OvertimeRecordService`, LD-06's `EmploymentService`/`CalendarResolutionService`).

**Two independent flags on `LeavePolicyVersion`, both default `True`:**
1. `allowed_during_probation` — checked in `submit()`, right after policy resolution. `False` +
   `Employee.status == "PROBATION"` blocks the submission (`LeaveApplicationNotAllowedDuring
   ProbationError`). `True` (default) preserves the prior behavior exactly — `submit()` has
   never looked at employee status before this.
2. `accrue_during_probation` — checked in `LeaveAccrualService.run_for_company()`'s existing
   per-employee/per-leave-type loop, fetching each employee's status once per employee (not once
   per leave type) and skipping that employee's accrual for a leave type whose version has this
   `False`. `True` (default) preserves the prior behavior exactly — accrual has never looked at
   employee status before this either.

Both default `True` for the same reason every other flag in this log defaults to "preserve
current behavior" — no existing policy version changes behavior until HR explicitly opts a
specific leave type out for probation employees.

---

## LD-19 — Encashment detail: dedicated validated path, revisiting LD-06 decision 3

**Status:** LOCKED.

**Context:** LD-06 decision 3 originally said encashment is "always HR-initiated... uses the same
manual-entry shape as L2's `ADJUSTMENT`" — i.e. no dedicated write path, HR just posts a signed
adjustment. Client spec §12 asks for real config (max encashable days, minimum balance required,
frequency, calculation basis) that a bare `encashment_allowed: bool` can't express or enforce.

**Decision 1 — a dedicated `POST /leave-ledger/encashments` endpoint, writing the already-
reserved `ENCASHMENT` entry_type.** `ENCASHMENT` has been a valid value in `leave_ledger`'s
`entry_type` CHECK constraint since L2's very first migration — nothing needed to change in the
ledger schema itself, only that something finally writes it. This revisits LD-06 decision 3's "no
dedicated endpoint" call, but additively: `POST /leave-ledger/adjustments` is untouched and still
exists for genuine corrections; encashment gets its own auditable, validated path instead of
being indistinguishable from a plain signed adjustment. Still HR-initiated (`LEAVE.BALANCE_
ADJUST`, same permission as adjustments) — no automatic sweep, matching LD-06's original intent
on that point.

**Decision 2 — `max_encashment_days`/`min_balance_after_encashment` are enforced; `encashment_
frequency`/`encashment_calculation_basis` are informational only.** The first two need nothing
beyond the single request being validated (requested days ≤ configured max; balance after the
debit ≥ configured minimum) — both straightforward per-request checks. The other two would need
things this codebase doesn't have yet: enforcing "frequency" (e.g. once per year) needs a
leave-year concept — the same open item already blocking `YEARLY` accrual (LD-06/LD-09) — and
"calculation basis" (e.g. basic-pay-per-day) is inherently a Payroll computation; Payroll doesn't
exist as a module yet (confirmed absent when this was scoped). Both fields are stored as
HR-documented config for a future Payroll module to read, not something Leave computes or
enforces — same "informational until the prerequisite exists" posture LD-17 already used for
maternity's pre/post-delivery day split.

**Rejected:** an automatic year-end encashment sweep. Would need the same leave-year anchor
already blocking two other items in this log — not invented here, and not what the client's
"HR/Admin" framing in §12 asked for anyway (encashment reads as an HR-triggered action throughout
the spec, never automatic).

---

## LD-20 — Leave year configuration: singleton per company, client answer locks the default

**Status:** LOCKED.

**Context:** client spec §10 wants HR to select Calendar/Financial/Anniversary/Custom leave
year. This was the fiscal-year anchor LD-06/LD-09 explicitly left open, blocking `YEARLY`
accrual and carry-forward-cap enforcement (both stubbed since L3).

**Client answers (2026-09-06):**
1. **Default leave year: `CALENDAR`** (1 Jan – 31 Dec) for this client. The mechanism still
   supports all four options the spec lists — a future company under this platform may need a
   different one — but nothing is pre-populated beyond the `CALENDAR` default every company
   effectively already has until told otherwise.
2. Financial year, if configured, is **India's Apr 1 – Mar 31** (this client answered India-only
   scope for the separate legal-compliance-floor decision the same day, 2026-09-06).

**Decision 1 — new `leave_year_setting` table, singleton per company** (unique index on
`company_id`, not a versioned/CRUD collection like `LeavePolicyVersion` — a leave-year choice has
no meaningful "draft" state). `LeaveYearSettingService.get_effective` lazily materializes the
`CALENDAR` default on first read, so a company doesn't need an explicit row before this setting
"exists" for it.

**Decision 2 — `CALENDAR`/`FINANCIAL` start dates are hardcoded in application code
(`leave/year.py`), not stored.** They aren't configurable values, just named choices — Jan 1 and
Apr 1 respectively are fixed by what the words mean. Only `CUSTOM` stores `start_month`/
`start_day` (required together when `leave_year_type=CUSTOM`, rejected otherwise). `ANNIVERSARY`
stores nothing at all — each employee's own `Employment.joining_date` month/day is the anchor,
computed per employee, never company-wide.

**Decision 3 — pure boundary-computation functions, isolated in `leave/year.py`.**
`leave_year_start_for`/`is_leave_year_start` take a plain-data `LeaveYearSettingData` and an
optional `joining_date`, no session/ORM dependency — unit-testable without a database, and the
one place a Feb-29-anchor edge case (an `ANNIVERSARY` or `CUSTOM` employee/setting anchored to a
leap day) is handled once (`_safe_date` clamps to the last valid day of the month in a non-leap
year) rather than at every call site.

---

## LD-21 — Yearly accrual + carry-forward cap: one daily sweep, gated on LD-20's boundary

**Status:** LOCKED.

**Decision 1 — `LeaveAccrualService.run_year_end_for_company`, not a separate service class.**
Mirrors `run_for_company`'s exact shape (resolve spans overlapping `as_of`, resolve each
employee's policy per leave type, write idempotent ledger rows) closely enough that a new class
would just duplicate structure — the only real difference is the trigger condition
(`is_leave_year_start` per employee instead of "every employee, every month").

**Decision 2 — carry-forward forfeiture finally uses the reserved `CARRY_FORWARD` entry_type**,
not a generic `ADJUSTMENT`. `CARRY_FORWARD` has sat in `leave_ledger`'s CHECK constraint unused
since L2's first migration; using it here (rather than `ADJUSTMENT`, which is also HR's own
manual-correction entry type) means the idempotency check
(`exists_for_cycle(..., entry_type="CARRY_FORWARD", effective_date=as_of)`) can never collide
with an unrelated manual adjustment HR happens to make on the same day.

**Decision 3 — no proration for `YEARLY` accrual.** The client's own Method 2 example ("12 days
credited at the beginning of the leave year") is a flat credit, not prorated by days-worked the
way `MONTHLY`/proration already is (LD-06). A joiner mid-cycle under `CALENDAR`/`FINANCIAL`/
`CUSTOM` simply receives no `YEARLY` credit until the next company-wide leave-year start; under
`ANNIVERSARY`, their first "leave year start" is their own joining date, so they're credited
immediately and then every anniversary thereafter — no special-casing needed, this falls out of
`is_leave_year_start` naturally.

**Decision 4 — carry-forward is checked before the new year's accrual is written**, both against
a balance fetched once per employee at the top of the loop (before either write) — the cap
enforcement reflects the old year's ending balance, never double-counting today's fresh credit.

**Decision 5 — daily Beat schedule, not annual.** Under `ANNIVERSARY`, different employees' leave
years start on different calendar days; a single annual cron can't cover that. Daily is
idempotent and cheap (`exists_for_cycle` short-circuits every non-matching employee/day), the
same tradeoff already accepted for the comp-off expiry sweep (LD-14).

---

## LD-22 — Legal compliance floor: no hardcoded figures, publish-time block against the strictest configured minimum

**Status:** LOCKED.

**Context:** client spec §16 wants HR blocked from publishing a leave policy whose entitlement
falls below the legally required minimum. India's Shops & Establishments Acts (and the Factories
Act) set these minimums, but they vary by state and, in some states, by establishment type — this
is exactly the kind of business-rule detail this log's own discipline says must not be guessed
(no prior LD entry, nor the client conversation, supplied actual figures for any state).

**Client answers (2026-09-06):** India-only scope (this platform doesn't need a global compliance
framework for this client); **block publishing** below the minimum, not just warn.

**Decision 1 — zero legal figures hardcoded anywhere in this codebase.** Same "engine reads
whatever is configured" posture LD-06 already established for accrual: a new `statutory_leave_
minimum` table (company-scoped, RLS) holds HR/compliance-entered floors — `state_code`/
`establishment_type` (both optional, free-text, matching the existing `Branch.state_code`
convention rather than a hardcoded enum) narrow *which* minimum a row represents, purely for
HR's own record-keeping. Flat identity row, no versioning — editing a minimum is delete-and-
recreate, same posture as `LeaveCombinationRule` (LD-16).

**Decision 2 — `LeaveType.statutory_category` classifies a company's free-form leave type**
against a small fixed taxonomy (`EARNED`, `SICK`, `CASUAL`, `MATERNITY`, `PATERNITY`) so
"Privilege Leave" at one company and "Earned Leave" at another both compare against the same
floor. `NULL` (default) means "not a statutorily-governed leave type" (LOP, comp-off,
bereavement, ...) — never checked, same "not configured yet is a valid, non-error state" posture
every other optional field in this module already uses.

**Decision 3 — enforcement point is `LeavePolicyVersion.publish_version`, per the client's literal
instruction, checked against the *strictest* (`MAX`) `min_days_per_year` configured for the leave
type's category — not resolved against any specific state/branch.** A `LeavePolicyVersion` at
publish time has no `PolicyAssignment` yet (or may later be assigned to several scopes in
different states), so there is no single state to check against. Comparing against the toughest
configured floor for the category is fail-safe (a policy can never publish below what *any*
configured minimum requires) rather than scope-precise. A company with no `statutory_leave_
minimum` rows configured for a category has nothing to enforce — publishing behaves exactly as it
did before this feature existed.

**Decision 4 — annual entitlement is computed from the same two fields the accrual engine already
reads**, no new field: `accrual_rate_per_cycle * 12` for `MONTHLY`, `accrual_rate_per_cycle` as-is
for `YEARLY`, `0` for `NONE` (nothing to compare, never trips the floor).

**Rejected:** adding `establishment_type`/jurisdiction fields to `Branch`/`LegalEntity` and doing
scope-aware enforcement at `PolicyAssignment` time instead of publish time. Would require
resolving which branches/states a policy ends up covering — real work, and `Branch` has no
`establishment_type` field today either — for no functional gain this client asked for; the client
specifically said "block publishing", not "block assignment". Revisit only if a future company
needs per-branch precision (e.g. one leave policy legitimately valid in a lenient state but not a
stricter one).

**Rejected:** hardcoding actual Indian statutory figures (e.g. "12 earned leave days/year") as
seed data in the migration. Real legal minimums vary by state, change over time, and are exactly
the kind of detail this log's own STOP-and-ask discipline exists to protect against guessing —
HR/compliance populates them via the new admin CRUD surface instead.

---

## LD-23 — Department Head assignment + Leave's third approval level (`MANAGER_THEN_HOD_THEN_HR`)

**Status:** LOCKED.

**Context:** this log's own STOP note (below) has said since L4 shipped that the third approval
level was blocked on `Department.head_employee_id` — a real DB-level FK (`employee.id`, `ON
DELETE SET NULL`, migration 20260813140000) that was never exposed by Organisation's own
schema/service/router because, at the time that slice shipped, no `Employee` ORM model existed
yet to validate against (Sprint 3 Scope Decision D10). `Employee` exists today; nothing
structural still blocks this.

**Decision 1 — `head_employee_id` becomes a real ORM-level `ForeignKey`, exposed on
`DepartmentCreate`/`Update`/`Read`, validated via a new `OrganisationService.
_assert_department_head_reference`** (repo-level existence check, same shape as
`_assert_manager_reference` in the Employee module) and reuses the existing `ORG.DEPARTMENT.
MANAGE` permission — no new permission, matching this module's explicit no-field-level-split
convention. No migration needed to store this: the DB constraint already existed.

**Decision 2 — new `approval_chain` value `MANAGER_THEN_HOD_THEN_HR`**, a three-stage chain
(Manager → Head of Department → HR), added alongside the existing `AUTO`/`MANAGER`/
`MANAGER_THEN_HR`/`HR` values HR already configures per policy version. `leave_application` gets
a new `resolved_department_head_id` column, snapshotted at submit time exactly like
`resolved_approver_manager_id` (resolved via `EmployeeAssignmentService.get_assignment_as_of`'s
`department_id` → `Department.head_employee_id`) — never re-resolved against current org-chart
state once an application is in flight, same immutability posture as the manager snapshot.
`approval_stage`'s new `"HOD"` value fits the existing `VARCHAR(10)` column unwidened.

**Decision 3 — the old hardcoded `is_final_stage` boolean check
(`approval_chain == "MANAGER_THEN_HR" and approval_stage == "MANAGER"`) is generalized into a
proper stage-sequence resolver** (`leave/approval_chain.py`, pure functions, unit-tested in
isolation): each chain has a nominal stage list (`MANAGER_THEN_HOD_THEN_HR` → `(MANAGER, HOD,
HR)`), and *this specific application's* effective sequence drops any stage whose identity
didn't resolve at submit time — falling back to a single `HR` stage if nothing resolved at all.
This is not a new behavior, just a generalization: it reproduces LD-05's original "resolution
failure routes to HR, never blocks, never auto-approves" rule exactly for the two pre-existing
chains (verified by the full existing test suite passing unchanged), and extends the same rule
to `HOD`. Concretely: manager unresolved but department head resolved → sequence is `(HOD, HR)`,
skipping straight to HOD; both unresolved → sequence is `(HR,)`, HR is the sole and final
reviewer. `_approve_internal` now looks up the next stage from this same resolver (recomputed
from the row's own snapshotted identities, deterministic) instead of a hardcoded chain-specific
boolean.

**Decision 4 — an employee who is their own department's head is treated as "no department head
resolved" for their own application**, not routed to themselves. Self-approval is already
unconditionally blocked (`LeaveApplicationSelfApprovalNotAllowedError`, no policy escape hatch,
LD-05) — without this guard, an application from the department head themself would reach the
`HOD` stage and then get permanently stuck, since nobody else is authorized to act at that stage.
Falling through to HR instead (same mechanism as any other unresolved stage) avoids a stuck
application without adding a new exception path — it reuses the existing "unresolved" branch.

**Rejected:** letting Department Head resolution block leave submission (e.g. requiring every
department to have a head before `MANAGER_THEN_HOD_THEN_HR` can be used). Mirrors LD-05's
existing manager-resolution posture exactly — an HR-configured chain must never prevent an
employee from submitting leave just because an org-chart field happens to be unset; it degrades
toward HR instead.

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
| **L3 — DONE** | Monthly accrual engine (`LeaveAccrualService.run_for_company`, `leave.run_monthly_accrual`/`leave.accrue_company` Celery tasks, Beat-scheduled) + **year-end sweep** (`run_year_end_for_company`, `leave.run_year_end_sweep`, LD-20/LD-21) covering `YEARLY` accrual and carry-forward-cap enforcement | L2 + LD-06's items answered. Shipped: found and fixed two real gaps along the way — LD-10 (`LeavePolicy` had no `LeaveType` binding) and LD-11 (`PolicyAssignment`'s exclusion constraint didn't allow multiple simultaneous `LEAVE_POLICY` assignments at one scope, which every leave type needs). `YEARLY` accrual and carry-forward-cap enforcement were originally deferred for lack of a fiscal-year anchor — resolved 2026-09-06 by LD-20 (client chose `CALENDAR` as the default, mechanism supports all four spec options). |
| **L4 — DONE** | `leave_application`/`leave_application_day`/`leave_application_action` + approval workflow, writes `LeaveDayProjection` via the existing sync contract on approval | L2, LD-01, LD-05. Shipped: two new decisions along the way — LD-12 (closed-attendance-period fails the *whole* approval, not just that day) and LD-13 (post-approval cancellation is self-service, reversing both the ledger and every synced projection — no Regularization precedent, since Regularization touches no balance/projection). Also caught a real cross-module vocabulary mismatch in testing: `leave_application_day.half` (`FIRST_HALF`/`SECOND_HALF`) vs. `LeaveProjectionSync.half` (`FIRST`/`SECOND`) — translated at the module boundary, not unified. |
| **L5 — DONE** | Comp-off credit + expiry sweep (`LeaveCompOffService`, `leave.credit_comp_off`/`leave.run_comp_off_credit_sweep`/`leave.sweep_comp_off_expiry`/`leave.run_comp_off_expiry_sweep` Celery tasks) | L2, LD-07 (now LOCKED). Shipped: found and fixed four real gaps in LD-07 itself along the way, each its own LD-14 decision below (leave-type resolution, minutes-to-days conversion, expiry-against-a-pooled-balance semantics, and trigger direction) — the same "found while implementing" pattern LD-10/LD-11/LD-12 already established for this module. Redemption needed no new code: an employee applies for leave against the `is_comp_off=true` `LeaveType` exactly like any other `requires_balance` type. |
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

**STOP.** L1 through L5 are done, including L3's `YEARLY`/carry-forward follow-up (LD-20/LD-21),
the legal-compliance floor (LD-22), and the third approval level (LD-23, which also closed the
Department Head assignment gap in Organisation this log had been reading but couldn't yet
exercise). L6 (a full, standalone frontend module) was never built as a separate slice —
instead, each config surface (leave types, policies, combination rules, leave year setting,
balances/encashment, statutory minimums) got its own page as it shipped, application submission
got its own dialog, and no gap in UI coverage remains for anything built through LD-23. The one
remaining open item is outside this module's own scope: the Employee confirmation/probation
transition workflow (blocks `allowed_during_probation`/`accrue_during_probation`, LD-18, from
ever actually triggering).
