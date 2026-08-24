# Workforce & Attendance Decision Log

**Status:** Architecture decision record. No application code, schema, migrations, frontend
code, or tests were created or modified to produce this document.

**Date:** 2026-08-17

**Companion:** `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md`

**How to use this log:** implementation tasks may treat every **LOCKED** entry as settled.
Changing one requires a new entry that supersedes it — never a silent divergence in code.
**OPEN** entries must not be guessed in implementation; they are listed again in the
architecture document §32.

**Numbering:** `WD-NN` (Workforce Decision) so these do not collide with `DEC-NNN` in
`HRMS_ARCHITECTURE_DECISION_LOG.md`. Existing DEC/ADR entries remain in force unless a WD
entry explicitly records a divergence.

**Legend:** LOCKED · DIVERGENCE (from a prior DOC, with rationale) · OPEN

---

## Relationship to existing locked decisions

The following remain fully in force for Attendance:

| ID | Applies how |
|---|---|
| ADR-0001 / DEC-001 | Attendance is a module inside the monolith, not a service |
| ADR-0002 / DEC-002 | `company_id` + RLS + `hrms_app` on every new table |
| ADR-0003 / DEC-003 / DEC-029 | Effective-dated assignments are insert-new; GiST overlap prevention |
| ADR-0004 / DEC-004 | Leave ledger is Leave's problem; Attendance only emits comp-off *facts* |
| ADR-0005 / DEC-005 | Payroll snapshots attendance facts; locked days are not rewritten |
| ADR-0006 / DEC-006 | No money in Attendance |
| ADR-0007 / DEC-007 | Device ingestion is a later deployable; punches still immutable |
| ADR-0008 / DEC-008 | Generic workflow engine is the **long-term** approval home — see WD-08 for V1 |
| ADR-0010 / DEC-010 | UTC storage; IANA timezone for day boundaries — see WD-06 |
| ADR-0011 / DEC-011 | No hardcoded statutory OT rates |
| DEC-016 / DEC-025 / DEC-026 | Rehire, employment status, population gate = `get_employment_as_of` |
| DEC-018 | `NULL` shift is legitimate; no default-shift cascade |
| DEC-019 | Resource/action permission catalogue for operational Attendance APIs |
| DEC-021 | ALTER stubs in place; never drop-and-recreate `holiday_calendar`/`holiday`/`shift` |
| DEC-023 | `modules/attendance/` is its own package |
| DEC-028 | Cross-tenant → 404 |
| RBAC Decision C | No new data-scope levels (`DEPARTMENT`/`BRANCH`/…) |

---

## WD-01 — WorkCalendar and HolidayCalendar are separate concepts

**Status:** LOCKED

**Decision:** A **HolidayCalendar** is a reusable catalogue of named holiday dates (national,
regional, company). A **WorkCalendar** is the assignment-facing composition: which holiday
calendars apply, which weekly-off pattern applies, and which dated exceptions (shutdown,
special working, substitution) apply. Employees are assigned a WorkCalendar (explicitly or
via branch/company default), never a raw HolidayCalendar.

**Why not one table:** many work groups share "Karnataka 2026" holidays but differ on weekly
offs, shutdowns, or optional-holiday treatment. Collapsing them forces holiday-row duplication
or department FKs on Holiday.

**Why not three concepts (Calendar + HolidayCalendar + WorkCalendar):** WorkCalendar *is* the
calendar. A third name adds nothing.

**Rejected:** attaching only `holiday_calendar_id` on Branch (the original Sprint 3 stub
intent) as the whole model — insufficient for exceptions, composition, and employee overrides.

---

## WD-02 — Shift is schedule; Attendance Policy is evaluation

**Status:** LOCKED · **DIVERGENCE** from FR-ATT-001 and `HRMS_SYSTEM_DESIGN_BASELINE.md` §6.6

**Decision:** Shift/ShiftVersion own *what the employee is scheduled to work* (times, type,
breaks, timezone, cross-midnight, optional weekly-off, OT-eligibility *flag*,
operates-on-holiday/WO). Attendance Policy versions own *how compliance is judged* (grace,
rounding, hour bands, late/early conversion, missing punch, excess break, flex evaluation,
WFH/on-duty punch rules).

**Existing FACT this changes:** `shift.grace_in_minutes`, `grace_out_minutes`,
`half_day_threshold_hours`, `min_hours_full_day` are evaluation fields. They will be copied
into a default Attendance Policy at implementation time and **stop being inputs to the
engine**. Columns remain until a later cleanup (DEC-021).

**Why diverge:** the product requirement is different grace/thresholds for different groups
on the same shift (company default vs night shift vs one employee). That is impossible if
grace lives on Shift. The baseline placed these on Shift because Attendance Policy did not
exist as a concept when Shift Rules shipped (Sprint 3 D5).

**Rejected:** a JSON rules engine on either entity. **Rejected:** duplicating grace on both
Shift and Policy "for convenience" (PD-POL-2 default is No).

---

## WD-03 — Overtime Policy and Regularization Policy are separate from Attendance Policy

**Status:** LOCKED

**Decision:** Three versioned policy identities: Attendance, Overtime, Regularization. They
are assigned independently (a grade may be OT-ineligible while sharing the department's
attendance policy).

**Rejected:** one mega-policy document. **Rejected:** OT multipliers as code constants
("statutory 2× for factory workers"). Multipliers are typed rows of configuration; statutory
interpretation is Payroll's future job (ADR-0011).

---

## WD-04 — How an employee gets a WorkCalendar

**Status:** LOCKED

**Decision:** Combination, not pure inheritance and not pure explicit assignment.

Resolution: explicit PolicyAssignment for the employee → Shift → designation → grade →
department → Branch (via BRANCH PolicyAssignment) → COMPANY PolicyAssignment → fail closed
(`CONFIG_ERROR` / `INCOMPLETE`, never silently WORKING).

Department-specific holidays are modelled as a different WorkCalendar assigned at DEPARTMENT
scope, not as `holiday.department_id`.

---

## WD-05 — Holiday vs weekly-off conflict

**Status:** LOCKED, with OPEN substitution product question (PD-CAL-2)

**Decision:** A CalendarException on the WorkCalendar always wins. Otherwise a holiday landing
on a weekly-off keeps `calendar_day_type = WEEKLY_OFF` with flag `holiday_on_weekly_off`. The
holiday is still visible to OT/comp-off and to Leave sandwich rules. Auto-moving the holiday
to the next working day is **not** default behaviour; it requires an explicit
`SUBSTITUTE_HOLIDAY` + `SPECIAL_WORKING` pair.

**OPEN PD-CAL-2:** whether any launch customer needs automatic substitution as a WorkCalendar
flag. Do not implement auto-substitute until answered.

---

## WD-06 — Attendance timezone resolution extends ADR-0010

**Status:** LOCKED · compatible extension of ADR-0010 / DEC-010

**Decision:** Punch storage remains UTC. The civil-day boundary for an employee-date uses, in
order: `ShiftVersion.timezone` if set, else `Branch.timezone` if set, else `Company.timezone`.

**Why:** ADR-0010 named company timezone as the single source of truth before Branch timezone
existed as a live nullable column (FACT). Multi-branch tenants (construction, multi-state)
will mis-attribute night punches if every branch is forced onto HQ midnight.

**Rejected:** storing punches in local time. **Rejected:** using UTC midnight as the
attendance date.

---

## WD-07 — Two stored status dimensions; Late/OT/Regularized are flags

**Status:** LOCKED · **DIVERGENCE** from FR-ATT-006's single enum as the stored model

**Decision:** Store `calendar_day_type` and `attendance_status` separately, plus combinable
flags (`is_late`, `is_early_out`, `is_overtime`, `is_regularized`, `is_pending_approval`,
`worked_on_holiday`, `worked_on_weekly_off`, `missing_punch`, `is_locked`). UI "Late" /
"Holiday OT" is a display function.

**Why:** a person can be PRESENT + LATE + OT on a WORKING day, or PRESENT on a HOLIDAY
(`worked_on_holiday`). A single enum cannot do this without exploding.

**COMP_OFF** is a Leave type, not an attendance primary status.

**OPEN PD-POL-1:** FR-ATT-006 says precedence is configurable. V1 locks engine overlay order
(architecture §19.4). Display labels may be configured. Full tenant-reorder of the engine is
deferred.

---

## WD-08 — Attendance V1 uses a local four-chain approval; does not build the workflow engine

**Status:** LOCKED · **defers implementation of** ADR-0008 / DEC-008 without repealing it

**Decision:** Regularization and OT approval in V1 support only
`AUTO | MANAGER | MANAGER_THEN_HR | HR`. Implemented inside `attendance/` as a small state
machine with append-only `RegularizationAction` rows. Approver resolution failure routes to
HR and audits; it never auto-approves.

Schema includes nullable `approval_request_id` so these flows can become workflow-engine
instances when `workflow/` is built (expected with Leave).

**Why not build ADR-0008 now:** the engine does not exist; Doc 20 estimates a large generic
subsystem; this programme forbids generic frameworks before a second consumer. Attendance
would otherwise be blocked on an unrelated platform slice.

**Why not ignore ADR-0008:** it remains the correct long-term shape. V1 must not grow a
private SLA/escalation/expression engine that cannot migrate.

**Rejected:** per-module bespoke graphs with condition languages. **Rejected:** implementing
Doc 20 node types inside Attendance.

**OPEN PD-APR-1:** manager as-of the attendance date (default) vs current manager.

---

## WD-09 — Policy assignment precedence

**Status:** LOCKED

**Decision:** For each policy kind independently:

```
EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH > LEGAL_ENTITY > COMPANY
```

No match → fail closed. No Employee Group dimension in V1. Same scope + overlapping
effective dates is structurally forbidden (GiST), mirroring EmployeeAssignment.

Shift *schedule* assignment is **not** done through this table; it stays on
`EmployeeAssignment.shift_id` + future `ShiftRoster` (DEC-018). Shift appears here only as a
**scope** (e.g. "Night Shift uses Attendance Policy B").

PolicyAssignment stores `policy_id` (identity), not `policy_version_id`. Version is resolved
by attendance date at evaluation time.

---

## WD-10 — Calculation pipeline order

**Status:** LOCKED

**Decision:** Architecture §19.1 steps 1–20. Employment gate first. Calendar type before
punches. Leave overlay before late/absent conversion. OT after presence math. Derived
AttendanceDay is fully recomputed, never incrementally patched. Recompute of locked days is
refused except via UNLOCK or an arrears-flagged override.

Overnight attribution: whole duty to shift **start date** (FR-ATT-005, unchanged).

---

## WD-11 — Historical reproducibility = version FKs + snapshot; punches immutable

**Status:** LOCKED

**Decision:**

- Punches are append-only. Corrections are new punches (`source=REGULARIZATION|MANUAL`) or
  regularization/adjustment rows. Never UPDATE/DELETE a punch.
- Published AttendancePolicyVersion / OvertimePolicyVersion / RegularizationPolicyVersion /
  ShiftVersion are immutable. Edits publish a new version with a new `effective_from`.
- Each AttendanceDay stores the version IDs actually used plus a `computation_snapshot`.
- Payroll copies **facts**, not versions (ADR-0005).
- Unlocked days may be recomputed (including after a backdated version publish, which is a
  privileged `ATTENDANCE.RECOMPUTE` act). Locked days never change their facts.

This is the attendance analogue of Employee's insert-new effective dating, adapted for
*shared* masters (many employees per policy) where inserting a new assignment row per
employee on every grace change would be unusable.

---

## WD-12 — No undocumented statutory or company-specific attendance behaviour in code

**Status:** LOCKED

**Decision:** Late-to-half-day, 8/6-hour bands, 10 vs 15 minute grace, OT 2×, sandwich
rules, RH off-by-default — all are **data** (or Leave/Payroll). Engine code implements
mechanisms (bands, caps, enums), not a particular company's handbook. If a behaviour cannot
be expressed with the typed fields in this design, that is an OPEN product decision to
extend the typed model — not a reason to add a JSON expression or a `if company_id =` branch.

---

## WD-13 — Module ownership

**Status:** LOCKED

**Decision:**

- **organisation/** keeps and extends Shift; owns WorkCalendar, HolidayCalendar, Holiday,
  WeeklyOffPattern, CalendarException. Matches FR-ORG-008, live Shift ownership, and the
  Organisation settings UI.
- **attendance/** owns policies, PolicyAssignment, roster, punches, days, calculation,
  regularization, OT requests, locks, summaries.
- No new `workforce/` Python package.
- Leave and Payroll remain unbuilt future packages; contracts only.

**Resolves** baseline D-3 ("holiday/week-off ownership") in favour of Organisation for the
catalogue, Attendance for consumption.

---

## WD-14 — Weekly-off is typed rules, not arbitrary JSON

**Status:** LOCKED

**Decision:** `WeeklyOffPattern.pattern_kind` + `WeeklyOffRule` rows (weekday, nth-of-month,
alternate parity, half/full). CUSTOM is still that table, not a script. ShiftVersion may
point at a pattern (shift-specific offs). Interaction with holiday/leave/OT as in
architecture §8.2.

**Rejected:** `pattern JSONB` as specified in `08_Database_Architecture.md` §5 `week_off_pattern`.

---

## WD-15 — Breaks are first-class children of ShiftVersion

**Status:** LOCKED

**Decision:** `ShiftBreak` rows (fixed window or flexible duration, paid/unpaid,
mandatory/optional, min/max, split, midnight). Actuals are `AttendanceBreak` on the day.
Unpaid breaks reduce worked minutes; paid breaks do not. Excess-break outcome is Attendance
Policy, not Shift.

Integer `break_minutes_paid/unpaid` on `shift` become derived/deprecated after backfill.

---

## WD-16 — Flexible / split / rotational

**Status:** LOCKED

**Decision:** `shift_type` = `FIXED | FLEXIBLE | SPLIT` on ShiftVersion with typed columns /
`ShiftDutyBlock` children — not JSONB windows (`08_Database_Architecture.md` §6.1
DIVERGENCE). ROTATIONAL is not a type; it is a later generator (`ShiftRotationPattern`) that
writes `ShiftRoster`. Roster is required for FR-ATT-002 date overrides; the generator is
sequence W11.

Flex evaluation: present by required minutes; late only after start window + grace; core
hours optional with a policy outcome. Architecture §11.8.

---

## WD-17 — WFH / On Duty are day-level overlays, not assignment location

**Status:** LOCKED · OPEN nuance PD-WFH-1

**Decision:** `EmployeeAssignment.work_location_type` (`OFFICE/WFH/HYBRID/FIELD`, FACT) is
not copied onto AttendanceDay as status. Day-level WFH/ON_DUTY comes from roster flag,
approved regularization, or policy-defined punch sources. Default PD-WFH-1: WFH location
type does **not** auto-present the employee without punches.

---

## WD-18 — Regularization vs adjustment vs punch mutation

**Status:** LOCKED

**Decision:** Employee/manager *requests* use `AttendanceRegularization` and consume
RegularizationPolicy caps/windows. HR/manager *direct* corrections use
`AttendanceAdjustment` + `ATTENDANCE.OVERRIDE` and do not consume employee monthly caps.
Neither mutates historical punches.

After payroll lock: default reject; HR may record `APPROVED_PENDING_ARREARS` without
rewriting locked facts (ADR-0005).

---

## WD-19 — Permission codes

**Status:** LOCKED · **DIVERGENCE** from product matrix naming of `VIEW_OWN`/`VIEW_TEAM` and
`ATTENDANCE.SHIFT_MANAGE`

**Decision:** Operational codes follow Employee: `ATTENDANCE.VIEW` + data-scope, plus
`ATTENDANCE.VIEW_ALL`. Shift remains `ORG.SHIFT.MANAGE`. New `ORG.HOLIDAY.MANAGE` and
`ORG.CALENDAR.MANAGE`. Policy config is `ATTENDANCE.POLICY_MANAGE` at COMPANY scope. Device /
geofence codes wait for those features.

Do not introduce new DataScopeLevel values.

---

## WD-20 — JSONB policy

**Status:** LOCKED

**Decision:** JSONB is allowed only for `computation_snapshot`, punch `raw_payload`, and
nothing else in V1 without a new WD entry. Policy rules are columns and child tables.

---

## WD-21 — Fail closed on missing configuration

**Status:** LOCKED

**Decision:** Missing employment → `NOT_JOINED`/`EXITED`. Missing shift → policy
`missing_shift_behaviour` (default `INCOMPLETE`). Missing calendar or attendance policy →
`CONFIG_ERROR` / `INCOMPLETE`, never Present, never Absent-as-LOP. Missing approver → HR,
never auto-approve (WD-08).

---

## WD-22 — Leave and Payroll are contracts, not this programme

**Status:** LOCKED

**Decision:** Do not implement leave calculation, sandwich rules, leave types, pay-days
26/30, OT rupees, or statutory OT. Implement the read/event contracts in architecture
§21–§22 so those modules can land later without rewriting AttendanceDay.

---

## WD-23 — First implementation slice

**Status:** LOCKED (recommendation)

**Decision:** After explicit architecture approval, implement **W1** first: Organisation
WorkCalendar + HolidayCalendar/Holiday expansion + WeeklyOffPattern + exceptions +
permissions + settings UI. No punches, no engine, no policies.

**Why:** baseline H-4 / D-3 — a status engine without day-type is structurally incomplete;
stubs already exist; the Organisation CRUD pattern is proven; it unblocks every later slice.

---

## WD-24 — `PolicyAssignment` pulled forward into W1, restricted to `WORK_CALENDAR`/`WEEKLY_OFF`

**Status:** LOCKED · **supersedes WD-23's "no policies" wording for this narrow case only**

**Decision:** WD-23 and architecture §30 place `PolicyAssignment` in W3, alongside
AttendancePolicy/OvertimePolicy/RegularizationPolicy. During W1 implementation this created a
genuine contradiction rather than a wording nuance: W1's own requirements (§6.2/§16 — calendar
assignment below COMPANY scope; §15.3 — explicitly rejecting a `branch.work_calendar_id`
shortcut *in favour of* `PolicyAssignment`) are unsatisfiable without an assignment mechanism.
Without it, W1 could only ever support one WorkCalendar per company, with no way to give
different branches/departments/employees different calendars — contradicting the architecture
document's own motivating examples ("Kerala Office Holidays" vs "Mumbai Office Holidays",
§5) and §10's employee+date→resolved-calendar contract.

`policy_assignment` is created in W1 (migration `20260818130000_policy_assignment`), but its
`policy_kind` column carries a DB-level `CHECK` constraint restricted to `('WORK_CALENDAR',
'WEEKLY_OFF')`. `ATTENDANCE_POLICY` / `OVERTIME_POLICY` / `REGULARIZATION_POLICY` are **not**
supported — creating a `PolicyAssignment` with one of those kinds is rejected at the service
layer (`PolicyKindNotSupportedError`) ahead of the raw constraint. W3 widens the `CHECK`
(`ALTER TABLE ... DROP CONSTRAINT ... ADD CONSTRAINT`) rather than building a second table —
this is the same "ALTER in place" posture DEC-021 already established for `holiday_calendar`/
`holiday`, applied to a table that didn't exist yet at W1 start.

**Why not build the full WD-09 precedence machinery without persisting it:** the precedence
*algorithm* (EMPLOYEE > SHIFT > ... > COMPANY) is meaningless without rows to walk against —
implementing the walk but refusing to let anyone create an assignment would be design theatre,
not a narrower scope.

**Why not wait for W3:** W1's own explicit deliverables (§10 "Calendar resolution", §11
"Calendar assignment") reference this exact mechanism by name. Deferring it would silently
narrow W1 to something the architecture document itself does not describe, which is the kind
of divergence §2.3/WD-12 forbid coding around silently — hence this entry instead of a quiet
scope cut.

**Rejected:** a `branch.work_calendar_id` convenience column (already rejected by §15.3 for
unrelated reasons — two sources of truth). **Rejected:** building the full 5-kind
`PolicyAssignment` table with no CHECK restriction — would let a caller create an
`ATTENDANCE_POLICY` assignment pointing at a `policy_id` for a table (`attendance_policy`)
that does not exist yet, an unvalidatable dangling reference.

---

## WD-25 — W3 implementation decisions

**Status:** LOCKED (recorded post-implementation, per this document's own rule that every
implementation choice not already covered by an existing WD gets written down rather than
silently decided in code)

**Decision:**

1. **`AttendancePolicy`/`OvertimePolicy`/`RegularizationPolicy` live in a new `hrms.modules.
   attendance` package (DEC-023), `PolicyAssignment` stays in `organisation`.** WD-13 named
   `attendance/` as PolicyAssignment's eventual owner, but WD-24 already pulled the table into
   `organisation` at W1 for a documented reason (no `attendance/` package existed yet, and the
   calendar-assignment requirement couldn't wait). Moving the table now would be an unrequested,
   unjustified refactor of working, tested code. W3 widens its CHECK constraint in place instead
   (`ALTER TABLE ... DROP/ADD CONSTRAINT`, migration `20260819090000`) — exactly what WD-24's own
   migration comment said W3 would do.

2. **Cross-module existence validation uses a local, function-scoped import in both
   directions.** `organisation.service._validate_policy_reference` needs to confirm an
   `ATTENDANCE_POLICY`/`OVERTIME_POLICY`/`REGULARIZATION_POLICY` `policy_id` exists;
   `attendance.resolution.PolicyResolutionService` needs `organisation.calendar_resolution.
   CalendarResolutionService`'s precedence walk. Both directions use the identical
   function-scoped-import idiom this codebase already established twice before W3
   (`calendar_resolution.py` importing `employee.service`; `employee/service.py` importing
   `organisation.service`). The import-linter `layers` contract only constrains
   `hrms.core`/`hrms.shared`, never sibling `hrms.modules` packages, so this is not a new
   exception — it is the existing convention applied a third and fourth time.

3. **Policy resolution (`resolve_attendance_policy`/OT/regularization) does not duplicate the
   WD-09 precedence walk.** `CalendarResolutionService.resolve_policy_assignment` (built in W1)
   was already generic over `policy_kind` — only the `policy_assignment.policy_kind` CHECK
   constraint, not the resolution code, restricted it to `WORK_CALENDAR`/`WEEKLY_OFF`. W3's
   `attendance.resolution.PolicyResolutionService` calls it directly with the three new kinds
   rather than re-implementing the 8-level scope walk.

4. **`/policy-assignments` (GET/POST) is one shared endpoint across all five `policy_kind`
   values, with permission dispatched by `policy_kind` at the router layer** (`ORG.CALENDAR.
   MANAGE` for `WORK_CALENDAR`/`WEEKLY_OFF`, `ATTENDANCE.POLICY_MANAGE` for the three W3 kinds;
   listing with no `policy_kind` filter requires both). Rejected: a second, duplicate
   `/attendance/policy-assignments` route set — architecture §18 already says "do not create
   another assignment table if the architecture already provides a reusable mechanism," which
   extends naturally to not duplicating its CRUD surface either.

5. **New permission `ATTENDANCE.POLICY_MANAGE` (WD-19), one code covering all three W3 policy
   families' config + their assignments** — not `ATTENDANCE.ATTENDANCE_POLICY_MANAGE` /
   `ATTENDANCE.OT_POLICY_MANAGE` / `ATTENDANCE.REGULARIZATION_POLICY_MANAGE` separately. WD-19
   already named `ATTENDANCE.POLICY_MANAGE` (singular) for "Attendance/OT/regularization
   policies + assignments" — this locks that reading rather than splitting it three ways, since
   no product requirement asks for independently grantable access to the three families.

6. **No auto-created initial DRAFT version on `POST /attendance-policies` (unlike
   `POST /shifts`, which auto-creates one).** A `Shift` with zero schedule is meaningless
   downstream (nothing can ever be assigned); an `AttendancePolicy` identity with zero versions
   is a normal, harmless interim state — nothing reads it until a `PolicyAssignment` resolves to
   it, and resolution already fails closed (`CONFIG_INCOMPLETE`) when no published version
   exists. Auto-creating a draft here would be convenience without a correctness reason.

7. **Deactivating a policy does not check for active `PolicyAssignment` references** (unlike
   `WorkCalendarDeactivationBlockedError`, which blocks deactivation while assignments exist).
   Documented as a known limitation (see the W3 implementation report), not a silent gap — adding
   the check requires the same cross-module query pattern as decision 2 above and was deferred to
   keep the identity-CRUD surface symmetric with `Shift`'s own unblocked deactivate/reactivate.

**Rejected:** duplicating `WD-09`'s precedence algorithm inside `attendance/`; a second
policy-assignment table scoped to `attendance/`; per-family permission codes; auto-draft-on-create
for policies.

---

## Open product decisions (not locked)

Copied for the log. Full text in architecture §32.

| ID | Topic | Default if forced |
|---|---|---|
| PD-CAL-1 | Optional/RH off-by-default vs working-until-applied | Working until Leave applies |
| PD-CAL-2 | Auto-substitute holiday on WO | No auto-substitute |
| PD-APR-1 | Approver as-of attendance date vs current | As-of attendance date |
| PD-POL-1 | Configurable engine precedence in V1 | Engine order locked |
| PD-POL-2 | Keep grace on Shift as well | No |
| PD-SHIFT-1 | Intra-day shift change | Not supported |
| PD-LOCK-1 | Lock grain LE vs company | Legal entity if payroll is LE-scoped; else company |
| PD-WFH-1 | Auto WFH from assignment location | No |
| PD-OT-1 | OT post-approval default | Required |
| PD-SCOPE-1 | Branch HR without BRANCH scope | COMPANY for HR roles |
| PD-BR14-SHIFT | Default-shift cascade (DEC-018) | Still deferred |

---

## WD-26 — W4 `punch`/`attendance_day` ship as ordinary (non-partitioned) tables

**Status:** LOCKED (recorded post-implementation, per this document's own rule) · **DIVERGENCE**
from architecture §27 ("`punch` and `attendance_day` PARTITION BY RANGE on local month... required
before volume, acceptable to ship first migration already partitioned")

**Decision:** `punch` and `attendance_day` (migrations `20260820090000`/`20260820100000`) are
created as ordinary RLS'd tenant tables — `company_id` FK, `ENABLE`/`FORCE ROW LEVEL SECURITY`,
`tenant_isolation` policy — identical in shape to every other table in this codebase. Neither is
declaratively partitioned.

**Why:** confirmed with the user before implementation (W4 plan, decision 1). Zero rows exist in
either table anywhere at the time of this decision — this is a greenfield slice, not a retrofit.
No table in this codebase has ever been partitioned; introducing the pattern for the first time
here would add composite-PK/child-FK complexity (`AttendanceBreak.attendance_day_id` would need
to carry `attendance_date` too) and first-of-its-kind migration/test surface, for a performance
concern the architecture's own §28 explicitly defers: "Partition maintenance (monthly) is an ops
task before 150k-employee scale; V1 tenants will not notice." §27 itself phrases partitioning as
"acceptable to ship... already partitioned," not mandatory for the first migration.

**Why this is safe to defer, not silently drop:** partitioning by RANGE is a purely additive
migration once real punch volume exists (convert-to-partitioned is a well-understood Postgres
operation on an empty or lightly-loaded table) — nothing in W4's schema or query shape forecloses
it. This entry exists so a future slice doesn't have to rediscover the reasoning or mistake the
omission for an oversight.

**Rejected:** implementing partitioning now as a first-of-its-kind pattern in this codebase,
justified only by literal §27 compliance rather than an actual near-term volume need.

**Follow-up:** revisit before onboarding a tenant near the scale §28 names (150k employees) or
once real punch volume makes unpartitioned scans/indexes a measured problem — not on a fixed
calendar date.

---

## WD-27 — W5 `ShiftRoster`: no rotation-pattern generator; DRAFT/PUBLISHED status; roster
overrides never touch `calendar_day_type`

**Status:** LOCKED (recorded post-implementation, per this document's own rule)

**Decision:**

1. **`ShiftRotationPattern` (an automatic rotating/weekly/monthly generator that would write
   `ShiftRoster` rows) is not built in W5.** Architecture §4.2 already calls it "Deferred past
   V1 core... not required to ship punches + status resolution" and §30 lists it as **W11,
   Optional** — this is not a new scope cut, it is holding the line the architecture document
   already drew. The generic W5 task brief that triggered this slice asked for "Fixed/
   Rotating/Weekly/Monthly roster types," which is broader than what §30 actually scopes into
   W5; per WD-24/WD-25's own precedent (follow the architecture doc, record the conflict, don't
   silently expand scope), this entry is that record. Operationally, `POST /rosters/bulk`
   (architecture §25's named endpoint) accepts an explicit per-date `(date, shift_id,
   overrides)` list — a fixed roster is that list with one repeated shift, a monthly roster is
   that list with one row per date, a rotating pattern is that list pre-expanded by the caller
   (typically the frontend) before submission. The backend never persists or interprets a
   *pattern*, only dated facts (WD-12).

2. **`ShiftRoster.status` (`DRAFT`|`PUBLISHED`) is new — not literally named in architecture
   §4.2's `ShiftRoster` field list, but not prohibited by it either.** Only a `PUBLISHED` row
   is visible to the calculation engine (`ShiftRosterRepository.get_published_for_date`); a
   `DRAFT` row can never change a live attendance calculation. This satisfies the task brief's
   audit/staging requirement ("Published rosters cannot silently change history") cheaply,
   without inventing a second table: every mutation (create/update/publish/delete) is recorded
   via `AuditService.record` — the same mechanism architecture §24 already names ("Roster
   write" is explicitly listed as an audited action) — rather than a separate revision/history
   table. `ShiftRoster` itself stays a mutable master keyed on `(company_id, employee_id,
   roster_date)` (§17: "the roster_date is the effective date"), mirroring `Shift`'s own
   audited-mutable-row shape, not `ShiftVersion`'s insert-new-immutable one — a roster row has
   no multi-date range to preserve history *within*, so there is nothing for an insert-new
   pattern to buy here.

3. **Roster overrides (`is_week_off_override`/`is_holiday_working_override`, §9.7) extend
   `AttendanceCalculationInput`/`evaluate_day`'s existing `not_expected`/`shift_operates`
   variables (`calculation.py`) rather than writing a parallel code path.**
   `is_holiday_working_override` is OR'd into `shift_operates` — functionally identical to what
   a per-shift `operates_on_holiday`/`operates_on_weekly_off` flag already does, just scoped to
   one employee-date instead of the whole shift, including that mechanism's existing (pre-W5)
   quirk that a zero-punch "operates" day still resolves to `NOT_EXPECTED` via
   `_resolve_primary_status`'s `not_expected`-only check — W5 does not fix or change that
   quirk, only reuses the same variable consistently. `is_week_off_override` is checked ahead
   of the "missing shift" branch so a pure day-off roster row (`shift_id=NULL`) is read as a
   deliberate schedule fact, not a config error. Neither override ever writes
   `calendar_day_type` (WD-04/WD-07 — calendar type stays Calendar's concern).

4. **`ATTENDANCE.ROSTER_MANAGE`** (already named at COMPANY scope in architecture §23.2) gates
   all roster mutation routes; roster *viewing* reuses `ATTENDANCE.VIEW` + the existing four
   `DataScope` levels — no new scope levels (WD-19). Every mutation route re-checks the target
   `employee_id`'s visibility via `EmployeeService.get_employee(scope=...)`
   (`_ensure_employee_visible`), the same fix commit `fecb740` applied to
   `ATTENDANCE.PUNCH_ON_BEHALF` — a COMPANY-scoped grant is the expected common case, but
   nothing in the roster service assumes it.

**Rejected:** building `ShiftRotationPattern` now (contradicts §30's own W11 placement);
a `RosterRevision`/history table for the audit-trail requirement (redundant with `audit_log`,
which architecture §24 already designates for this); a `roster.day_type` enum duplicating
`calendar_day_type` (the brief's generic template used one; architecture's own boolean-flag
design in §9.7 is more precise about what roster can and cannot override).

---

## WD-28 — W6 `RegularizationRequest`: correction applied only through existing punch/roster
mechanisms; uniform punch-or-shift payload; append-only `RegularizationAction` timeline

**Status:** LOCKED (recorded before implementation, per this document's own rule that every
implementation choice not already covered by an existing WD gets written down rather than
silently decided in code)

**Decision:**

1. **A regularization is never applied by teaching the calculation engine a new overlay.**
   Architecture §13.2 already names the mechanism: "On approve: write any synthetic punches
   with `source=REGULARIZATION` (still immutable punches)... recompute." W6 does exactly this
   and nothing else — an approved request either (a) inserts one or more new `Punch` rows
   (`source='REGULARIZATION'`) via the existing `PunchRepository.insert`, or (b) for
   `WRONG_SHIFT`, upserts a `PUBLISHED` `ShiftRoster` row for that employee-date via the
   existing `ShiftRosterRepository` (§9.7's roster-outranks-assignment resolution already
   exists; W6 adds no new resolution step) — then calls the existing
   `AttendanceDayService.calculate()` (WD-10's full-recompute path, unchanged). No new status
   branch, overlay, or "excused break"/"forced status" input is added to `calculation.py`.

2. **Every `RegularizationRequest`, regardless of `request_type`, must carry at least one
   requested punch (`AttendanceRegularizationRequestedPunch`) or a `requested_shift_id`.**
   `request_type` (reusing `_REGULARIZATION_TYPES` from W3's schema module verbatim — WD-12,
   don't hardcode a second list) is a classification/reason the policy's `allowed_types` gates,
   not a distinct application mechanism. This works cleanly for `MISSING_PUNCH`, `WRONG_PUNCH`,
   `FULL_DAY`, `WRONG_SHIFT`, and `WFH`/`ON_DUTY` requests that supply punch times (WD-17: "Day
   -level WFH... comes from roster flag, approved regularization, or policy-defined punch
   sources" — the approved-regularization case *is* a punch source, not a new WFH status
   branch). It does **not** cover `WRONG_STATUS`, or an `EXCESS_BREAK`/`WFH`/`ON_DUTY` request
   that changes no punch and asks only to reclassify an already-punched day (e.g. "excuse this
   excess break without changing any punch time") — W4's `evaluate_day` has no excused-break or
   forced-status input to apply such a request to (confirmed: its module docstring calls
   leave/regularization overlays "no-op seams in W4"). Requiring a punch-or-shift payload
   uniformly means "apply" always has a well-defined, already-supported effect; a pure
   non-punch status/break override is left **OPEN** (see below) rather than invented.

3. **`is_regularized`/`is_pending_approval` (`AttendanceDay`, shipped empty in W4) are set by
   the regularization service via a narrow, additional `AttendanceDayRepository` update
   immediately after `calculate()` returns, not threaded through `evaluate_day`'s pure
   calculation.** `evaluate_day` has no knowledge of `attendance_regularization_request` (and
   per decision 1, must not gain any) — mirrors how `is_locked`/`locked_at` already exist on
   `AttendanceDay` with no W4 writer, waiting for W8. `is_pending_approval` is set `true` while
   a request is `SUBMITTED` for that employee-date and cleared on any terminal transition
   (`APPROVED`/`REJECTED`/`CANCELLED`).

4. **Approval chain (`AUTO`/`MANAGER`/`MANAGER_THEN_HR`/`HR`, WD-08) is implemented as a
   `RegularizationRequest.approval_stage` field (`MANAGER`|`HR`|`NULL`) rather than a second
   status enum.** `MANAGER_THEN_HR` transitions `approval_stage` from `MANAGER` to `HR` on the
   manager's approval without changing `status` off `SUBMITTED`; only the final stage's approval
   sets `status=APPROVED` and triggers decision 1's apply step. A rejection at *either* stage is
   terminal (`status=REJECTED`) — architecture never describes a rejected manager stage
   forwarding to HR for a second opinion, and Phase 5's "a rejected request cannot be treated as
   approved" reads most naturally as: rejection ends the workflow, it does not advance it.
   Approver identity for the `MANAGER` stage is snapshotted at submit time
   (`resolved_approver_manager_id`, via `EmployeeService.get_assignment_as_of(employee_id,
   attendance_date).reporting_manager_id`) per PD-APR-1's stated default ("as-of the attendance
   date") — this is an already-open product decision in §32 that the architecture explicitly
   says ships with a default if forced; W6 ships with that named default, not a new guess.
   Resolution failure (no manager as-of that date) routes directly to `HR` stage and records a
   `RegularizationAction(action='APPROVER_UNRESOLVED')`, exactly as §14 specifies — never
   auto-approves on failure.

5. **Self-approval is always blocked** (`request.employee_id == acting caller's employee_id` ⇒
   rejected with a dedicated 403), **including for a caller who happens to hold
   `ATTENDANCE.REGULARIZATION_APPROVE`.** Neither `RegularizationPolicyVersion` (W3) nor the
   architecture defines a flag that would "explicitly permit" self-approval (Phase 6's own
   conditional — "unless the existing policy explicitly permits it" — has no field to point at),
   so the only policy-consistent reading is: no such permission exists yet, therefore it is
   denied. `AUTO`-chain requests never reach a manual approve call at all (decision 4), so this
   is not in tension with "approved on submit."

6. **Permission codes are `ATTENDANCE.REGULARIZATION_REQUEST` (SELF),
   `ATTENDANCE.REGULARIZATION_REQUEST_ON_BEHALF` (COMPANY, mirrors `ATTENDANCE.PUNCH_ON_BEHALF`
   exactly — same router-level "gate depends on request body" shape as `create_punch`), and
   `ATTENDANCE.REGULARIZATION_APPROVE`** (WD-19 spelling: this codebase's `RegularizationPolicy`/
   `regularization_policy` table already spells the word with a `z` throughout; architecture
   §23.2's `ATTENDANCE.REGULARISE_APPROVE`/`REGULARISE_REQUEST` is the one inconsistent
   British-spelled instance in that document and is treated as a typo against the codebase's own
   established spelling, not a divergence requiring sign-off). **Reads reuse the existing
   `ATTENDANCE.VIEW`** rather than a fourth new code — mirrors WD-27 decision 4's "roster
   *viewing* reuses `ATTENDANCE.VIEW`... no new scope levels."

7. **`AttendanceRegularizationAction` (named in architecture §13.2/§33.4) is a real child
   table, not derived from `audit_log`.** Unlike `ShiftRoster` (WD-27 decision 2, which found
   `audit_log` sufficient because every mutation is a single-actor event), a
   `MANAGER_THEN_HR` request has two distinct reviewer/timestamp pairs in sequence that
   `RegularizationRequest`'s own columns (one `reviewed_by_user_id`/`reviewed_at`) cannot hold
   without overwriting the manager stage's record when HR acts — the action table is the
   per-stage history the architecture doc already names, not a duplicate/generic audit system.
   `AuditService.record` is called in addition, once per state transition
   (`REGULARIZATION_SUBMITTED`/`_APPROVED`/`_REJECTED`/`_CANCELLED`/`_APPLIED`), exactly as
   Phase 10 requires and identically to how every other attendance mutation is audited — the two
   mechanisms are not redundant: `audit_log` is the company-wide platform sink, the action table
   is a request-scoped read model the frontend timeline queries directly without needing
   audit-log-read permission.

8. **`AttendanceLock` (W8) does not exist, so "locked" is only ever the pre-existing,
   currently-dead `AttendanceDay.is_locked` flag** (WD-11, no W4/W5 code path sets it). W6 still
   checks it at both submit time and apply time (`AttendanceDayService.calculate()` already
   raises `AttendanceDayLockedError` at apply time unmodified) and refuses to bypass it — but
   §13.4's `APPROVED_PENDING_ARREARS` HR-override-while-locked path requires
   `ATTENDANCE.OVERRIDE`, which is `AttendanceAdjustment`'s mechanism (WD-18), a distinct entity
   this task brief explicitly does not ask W6 to build. A regularization request against a
   locked day is therefore simply rejected with a clear error in W6; the arrears path is
   deferred to whenever `AttendanceAdjustment`/W8 lands.

**Rejected:** a new calculation-engine overlay/status branch for `WRONG_STATUS`/excused-break
requests (decision 2 — would duplicate/extend the calculation engine, against the task's own
instruction); a second generic audit/workflow system (decision 7); auto-approving on approver
-resolution failure (decision 4, §14 forbids it explicitly); allowing self-approval by default
(decision 5); building `AttendanceAdjustment`/`ATTENDANCE.OVERRIDE` or `AttendanceLock` in this
slice (decision 8 — out of the stated W6 scope); enforcing
`RegularizationPolicyVersion.auto_approve_within_minutes`'s clock-error tolerance window (a
finer nuance orthogonal to `approval_chain=AUTO` that neither the architecture nor the task
brief specifies the interaction for — left unenforced and documented as a known gap rather than
guessed).

**OPEN (new, PD-REG-1):** whether `WRONG_STATUS`/excess-break-without-a-punch-change requests
should be representable at all without a calculation-engine extension (decision 2). Default if
forced: not supported until such an extension is scoped — request creation still succeeds for
these `request_type`s (policy remains the source of truth for `allowed_types`), but approval
requires a punch or shift payload before it can transition past `SUBMITTED`.

---

## Divergences index (quick reference)

| Prior source | This log |
|---|---|
| FR-ATT-001 grace/thresholds on Shift | WD-02 |
| Baseline §6.6 "Attendance reads Shift grace, never redefines" | WD-02 |
| FR-ATT-006 single stored status enum | WD-07 |
| ADR-0008 build generic engine first | WD-08 (deferred, not repealed) |
| `08_Database_Architecture.md` JSONB shift windows / week_off JSONB | WD-14, WD-16 |
| Product matrix `ATTENDANCE.SHIFT_MANAGE`, `VIEW_OWN`/`VIEW_TEAM` | WD-19 |
| Baseline D-3 holiday ownership unresolved | WD-13 |
| ADR-0010 company timezone only | WD-06 |
| §27 `punch`/`attendance_day` partitioned from first migration | WD-26 (deferred, not repealed) |
| Generic W5 brief: rotation-pattern generator, `day_type` enum | WD-27 (deferred to W11, not repealed) |
| Architecture §23.2 `ATTENDANCE.REGULARISE_*` spelling | WD-28 decision 6 (codebase spelling kept) |

---

## WD-29 — W7 `OvertimeRecord`: engine-detected only, single mutable-then-frozen record per
day, weekly/monthly caps computed pre-engine, terminal decisions frozen against recompute

**Status:** LOCKED (recorded before implementation, per this document's own rule; product
decisions confirmed with the requester before coding began)

**Context:** unlike W6, overtime *detection* is not greenfield. W3/W4 already implemented
`calculation.detect_overtime()`, wired end-to-end through `AttendanceDayService.calculate()`,
with policy resolution, daily-cap clamping, min-threshold, rounding, night/holiday/weekly-off
classification, and 1:1 comp-off crediting already live (`AttendanceDay.ot_minutes_detected`/
`ot_minutes_approved`/`ot_pending`/`ot_classification`/`comp_off_minutes_earned` are not dead
columns — they are written by every `calculate()` call). W7's actual scope is: weekly/monthly
cap enforcement, an approval **workflow entity** (nothing today acts on `approval_chain`/
`requires_post_approval` for OT), a comp-off fact with expiry, and a confirmed engine gap
(`_evaluate_split` never calls `detect_overtime` at all).

**Decision:**

1. **There is no manual "request overtime" submission flow.** Architecture §12.2 only
   describes detect-then-post-approve; `requires_pre_approval` (`OvertimePolicyVersion`) has no
   described mechanic for OT that is only knowable retrospectively via `calculate()`. W7 leaves
   it unenforced and documented, the same treatment WD-28 gave
   `auto_approve_within_minutes`. API surface is `GET /overtime`, `GET /overtime/{id}`,
   `POST /overtime/{id}/approve`, `POST /overtime/{id}/reject` only — no create route.

2. **`OvertimeRecord` is a single mutable-then-frozen row per `AttendanceDay`
   (`attendance_day_id` is `UNIQUE`), not an accumulating history** like
   `AttendanceRegularizationRequest`. A `PENDING` record is fully replaced on every recompute of
   its day (mirrors `AttendanceBreak`'s delete/recreate posture — nothing has been decided yet).
   A recompute that now detects zero eligible OT deletes a prior `PENDING` record outright (there
   is nothing left to decide). Once a record reaches a terminal status (`AUTO_APPROVED`,
   `APPROVED`, `REJECTED`), it is **frozen**: `AttendanceDayService.calculate()` still refreshes
   `AttendanceDay.ot_minutes_detected`/`ot_classification`/`is_overtime` in the day row
   (informational, same as every other derived column), but overrides
   `ot_minutes_approved`/`comp_off_minutes_earned`/`ot_pending` in that same write with the
   terminal record's own values, not the freshly recomputed engine output. No revision/void
   action exists in W7 — a terminal decision survives any later recompute, including one driven
   by an approved regularization correction to the same day (confirmed with the requester:
   "freeze forever" over "block the regularization instead" or leaving this undefined).

3. **Weekly/monthly cap enforcement runs in `service.py`, before the pure engine, exactly like
   the existing daily cap runs inside it.** A new `OvertimeRecordRepository
   .sum_minutes_detected_for_range` sums `minutes_detected` across non-`REJECTED`
   `overtime_record` rows (`PENDING` + `AUTO_APPROVED` + `APPROVED` all reserve budget as soon as
   detected — confirmed with the requester, consistent with how the existing daily cap already
   clamps against detected, not yet approved, minutes) in the ISO week / calendar month
   containing the target date (excluding the day being recomputed), producing
   `remaining_weekly_minutes`/`remaining_monthly_minutes` passed into `OvertimePolicyInputs` and
   clamped in `detect_overtime()` identically to `daily_cap_minutes`. **Confirmed and accepted
   with the requester**: this makes a day's detected OT depend on sibling-day state, which is
   explicitly **not idempotent** in the sense `AttendanceDayService.calculate()`'s own docstring
   claims ("same punches + versions produce the same result") — a day's detected OT can change
   between two recomputes with zero change to that day's own punches, purely because a sibling
   day's `overtime_record` state changed in between. Accepted as a known, documented limitation
   of period-cumulative caps computed this way; no cascading recompute across days is triggered.

4. **Approval workflow mirrors WD-28 decisions 4/5/6 exactly**, substituting `overtime_record`
   for `attendance_regularization_request`: `approval_chain` snapshotted from the resolved
   `OvertimePolicyVersion` at detection time; `AUTO` chain sets `AUTO_APPROVED` immediately with
   no manual step ever; `MANAGER`/`MANAGER_THEN_HR`/`HR` create a `PENDING` record only when
   `requires_post_approval` is true (otherwise `AUTO_APPROVED` with no review step, matching how
   the engine already auto-approves when `requires_post_approval=False`); manager identity
   resolved via `EmployeeAssignmentService.get_assignment_as_of(employee_id, attendance_date)` at
   detection time, not review time; no-manager-resolved routes straight to `HR` stage and records
   `overtime_action(action='APPROVER_UNRESOLVED')` — never auto-approves on failure.
   `MANAGER_THEN_HR` uses an `approval_stage` field, not a second status enum. Self-approval is
   always blocked, including for a caller who holds `ATTENDANCE.OVERTIME_APPROVE`.

5. **SPLIT-shift overtime detection gap (`calculation.py` `_evaluate_split`) is fixed in this
   slice, not deferred.** Unlike a genuinely underspecified gap, this one has no missing input:
   `scheduled_minutes` already resolves to `shift.required_minutes` for SPLIT shifts (the same
   fallback the FIXED/FLEX path already uses when no `scheduled_start`/`scheduled_end` is set),
   so `detect_overtime()` is wired in identically to the FIXED/FLEX path. Confirmed with the
   requester as in-scope for W7 rather than a separately-reported pre-existing defect (unlike
   W6's RLS bug, this sits inside the pure engine module W7 already owns for this slice).

6. **Permission: `ATTENDANCE.OVERTIME_APPROVE` only, appended to the existing
   `ATTENDANCE_PERMISSIONS` list** (not a new list/registration site — both registration call
   sites, `organisation.service.register_company` and `seed/bootstrap.py`, already iterate that
   list generically). Reads reuse `ATTENDANCE.VIEW`/`ATTENDANCE.VIEW_ALL` (no fourth code,
   mirrors WD-28 decision 6) — OT records are system-detected and attached to attendance days the
   caller can already view, not self-submitted content needing its own view gate.

**Rejected:** a manual pre-approval submission flow (decision 1 — no described mechanic exists);
an accumulating multiple-records-per-day history table (decision 2 — one row per day is
sufficient since nothing is ever re-detected concurrently); silently overwriting a terminal
record's approved/comp-off minutes on every recompute (decision 2 — would let an unrelated
regularization correction silently revise a rendered approval decision); scoping weekly/monthly
caps out of W7 to preserve strict idempotency (decision 3 — the task brief explicitly asks for
all three cap levels; the non-idempotency is accepted instead); only counting
`APPROVED`/`AUTO_APPROVED` minutes toward the weekly/monthly budget (decision 3 — would let a
day's cap-clamped amount retroactively shrink once an earlier `PENDING` day is later approved);
deferring the SPLIT-shift fix as a separately-reported defect (decision 5 — it is mechanical and
sits inside this slice's own engine surface); a fourth view permission (decision 6).

**OPEN (new, PD-OT-1):** whether a terminal `overtime_record` should ever become
revisable/voidable — e.g. an HR-initiated correction after a later regularization proves the
underlying punches were wrong. Default shipped: frozen, no revision path in W7 (decision 2).

**OPEN (new, PD-OT-2):** `requires_pre_approval` remains entirely unenforced (decision 1) — if a
future slice needs it, its interaction with `calculate()`'s retrospective detection timing needs
its own scoped design, not a guess bolted onto this one.

---

## WD-30 — W8 `AttendancePeriod`: two-state lock (`OPEN`/`CLOSED`), company grain,
period is the authoritative lock check, `incomplete_at_lock_behaviour` resolved at finalize

**Status:** LOCKED (recorded before implementation, per this document's own rule; product
decisions confirmed via the task brief's own explicit defaults where architecture left a
question genuinely open)

**Context:** architecture §4.2 names `AttendanceLock` (period lock) and `AttendancePeriodSummary`
(payroll-facing roll-up) as W8's two new entities. Neither had any writer before this slice —
`AttendanceDay.is_locked`/`locked_at`/`locked_by` (W4), `RegularizationPolicyVersion.
blocked_when_locked` (W3), and `AttendancePolicyVersion.incomplete_at_lock_behaviour` (W3) all
shipped as dead/unused columns explicitly reserved for this slice, confirmed by direct audit of
`models.py`'s own docstrings and `calculation.py` (`incomplete_at_lock_behaviour` declared on
`PolicyInputs` but never read anywhere in the engine). `AttendanceDayService.calculate()` and
`RegularizationRequestService.submit()` already had a locked-day refusal wired (`WD-11`/W6), but
nothing could ever set the flag; `PunchService.record_punch`, `ShiftRosterService`'s four mutating
methods, and `OvertimeRecordService.approve`/`reject` (which writes `AttendanceDay.
ot_minutes_approved`/`comp_off_minutes_earned` directly, bypassing `calculate()` entirely) had no
lock awareness at all — confirmed by direct read of `service.py`, not assumed.

**Decision:**

1. **Two persisted states only: `OPEN`/`CLOSED`.** `CLOSED` *is* locked — architecture's own
   `AttendanceLock` never describes a closed-but-unlocked state, and finalization is synchronous
   (no Celery fan-out, matching every W1-W7 mutation in this module), so a durable `CLOSING` state
   has no code path that would ever observe it. Create always opens immediately (no separate
   "open" action), mirroring WD-28's no-DRAFT-state precedent.

2. **The period, not `AttendanceDay.is_locked`, is the authoritative lock source of truth.**
   `AttendanceDay.is_locked`/`locked_at`/`locked_by` remain a synchronized denormalization set
   atomically by finalize/reopen (`AttendanceDayRepository.bulk_lock`/`bulk_unlock`), read by
   `AttendanceDayService.calculate()`'s pre-existing check for the already-computed-row case. A
   new shared `_ensure_date_open()` helper, consulted by `PunchService.record_punch`,
   `ShiftRosterService`'s four mutating methods, `RegularizationRequestService.submit`, and
   `OvertimeRecordService.approve`/`reject`, queries the period directly — the only way to refuse
   a mutation against a date that has no `AttendanceDay` row yet at all (a backdated request into
   an already-closed period, for an employee whose day was never computed). `ATTENDANCE_PERIOD_
   CLOSED` (409) is this new, period-level refusal; the pre-existing `ATTENDANCE_DAY_LOCKED` stays
   as the narrower, already-computed-row-specific error `calculate()` raises. Two independent,
   defence-in-depth guards, not one — they should never disagree since finalize/reopen sets both
   together.

3. **Lock grain: company only in V1** (PD-LOCK-1, architecture §32, genuinely open). The
   architecture's own stated default — legal-entity grain *only if* Payroll will be LE-scoped —
   cannot be evaluated because Payroll does not exist yet; V1 ships the other half of that same
   documented default (company grain) with a reserved, unused `legal_entity_id` column on
   `attendance_period` for a future slice, mirroring how `is_locked`/`locked_at` themselves
   shipped unused ahead of this one.

4. **`incomplete_at_lock_behaviour` (architecture §11.4) is resolved as part of `finalize`,
   not treated as a blanket blocker.** A still-`INCOMPLETE` day's own snapshotted
   `AttendancePolicyVersion.incomplete_at_lock_behaviour` governs: `KEEP_INCOMPLETE` blocks
   finalization (`INCOMPLETE_ATTENDANCE` reason); `TREAT_ABSENT` (the shipped default) or
   `TREAT_PRESENT` is auto-resolved by `finalize` itself, immediately before locking —
   `paid_day_fraction`/`lop_fraction` are set to the ABSENT/PRESENT mapping architecture §11.4
   already defines, `attendance_status` itself is left `INCOMPLETE` (the architecture table
   names only the two fraction columns, not a status rewrite). Verified live, end to end, against
   a real running server: a day that became `INCOMPLETE` from an approved regularization's
   additive punches was correctly *not* blocked (default policy), correctly resolved to
   `paid_day_fraction=0.00`/`lop_fraction=1.00` at finalize, and correctly locked.

5. **Finalization validation is fail-closed across six typed reason codes**:
   `EMPLOYEES_WITHOUT_ATTENDANCE` (an employment spell's day count vs. `AttendanceDay` row count
   in range — computed via `EmploymentService.list_spans_overlapping`, a new, minimal, primitive-
   tuple-returning method added to the *employee* module and consumed through `.service`, never
   `.repository`/`.models`, per Module Standard §2), `CONFIG_ERROR` (unconditional — no lock-time
   resolution mechanism exists for this, unlike `INCOMPLETE_ATTENDANCE`), `INCOMPLETE_ATTENDANCE`
   (only the `KEEP_INCOMPLETE` subset, decision 4), `PENDING_REGULARIZATION` (any `SUBMITTED`
   request in range), `PENDING_OVERTIME_APPROVAL` (any `PENDING` record in range), and
   `UNPUBLISHED_ROSTER` (any `DRAFT` roster row in range). `finalize` always re-validates fresh
   inside its own version-guarded transaction — it never trusts the cached `last_validation_
   status` a prior `POST .../validate` call wrote.

6. **`AttendancePeriodSummary` is a full delete/recreate snapshot, written exactly once per
   successful `finalize` call, inside the same transaction as the lock.** "Regenerated only while
   unlocked" (architecture §4.2) is implemented as a live, unpersisted, per-request aggregation
   (`GET .../summary` while `OPEN`) rather than a second persisted-and-continuously-updated table —
   there is no described requirement for the `OPEN`-state numbers to survive a server restart, and
   persisting a table nobody reads until finalize would be exactly the kind of "generic
   config/cache nobody asked for" this codebase's own review gate (architecture §31 "generic JSON
   creeping in") warns against for a different column shape. A period finalized more than once
   across its lifetime (finalize → reopen-for-correction → finalize again) gets a fresh, correct
   frozen snapshot each time, never a stale leftover from an earlier close.

7. **`ATTENDANCE.LOCK` covers create/validate/finalize; `ATTENDANCE.UNLOCK` is separate**
   (architecture §23.2 names exactly these two codes). No third "view periods" code — reads reuse
   `ATTENDANCE.VIEW`/`ATTENDANCE.VIEW_ALL`, mirroring WD-28 decision 6 / WD-29 decision 6's
   identical "no fourth/third read code" reasoning. Both are COMPANY-scoped only — a period has no
   `employee_id` to resolve a narrower `DataScope` against.

8. **No `AttendanceAdjustment` / `APPROVED_PENDING_ARREARS` path in this slice** (Phase 7 of the
   task brief: verify whether W8 must introduce it, and stop rather than build an uncontrolled
   override if the answer is unclear). Architecture §13.4 itself states the default plainly:
   "reject with a clear error; pending-arrears is an explicit HR action" — the reject-by-default
   half is exactly what `_ensure_date_open`/`ATTENDANCE_PERIOD_CLOSED` already gives every
   mutating service. The arrears half needs `AttendanceAdjustment`, a distinct entity WD-18
   already named but which no W1-W8 slice has built, and architecture never assigns it to a
   specific W-numbered slice. Building it here would be inventing an unresolved business rule
   (which post-lock correction paths get arrears vs. flat rejection, what "explicit HR action"
   concretely means) rather than reading one off the architecture. The only sanctioned path back
   to mutability in V1 is `ATTENDANCE.UNLOCK` reopening the whole period.

**Rejected:** a persisted `CLOSING` state (decision 1 — no code path would ever observe it given
synchronous finalization); relying on `AttendanceDay.is_locked` alone for lock enforcement
(decision 2 — cannot refuse a mutation for a date with no day row yet); legal-entity lock grain
(decision 3 — architecture's own stated condition for it, LE-scoped Payroll, does not exist yet);
treating every `INCOMPLETE` day as an unconditional finalization blocker (decision 4 — architecture
names an explicit lock-time resolution policy field for exactly this, TREAT_ABSENT/TREAT_PRESENT
would then never be exercised); a persisted, continuously-regenerated summary table for the `OPEN`
state (decision 6 — no described requirement survives a restart, and it would be a second
"generic cache" the architecture's own review gate warns against); a fourth/third read permission
code (decision 7); an `AttendanceAdjustment`/arrears mechanism invented without an architecturally
assigned owner or defined rule set (decision 8).

**OPEN (unresolved, PD-LOCK-1 remains open):** whether a future slice should switch lock grain to
legal-entity once Payroll is LE-scoped. The reserved `legal_entity_id` column exists for exactly
that; V1 does not read or write it.

**OPEN (new, PD-LOCK-2):** whether `AttendanceAdjustment` / an `APPROVED_PENDING_ARREARS` path
should ever be built for controlled post-lock correction without a full period reopen. Default
shipped: reject with `ATTENDANCE_PERIOD_CLOSED`; the only correction path is `ATTENDANCE.UNLOCK`
reopening the whole period (decision 8).

**Observed during live verification, not a W8 defect (recorded for W6/W9 awareness):** approving
a regularization request whose proposed punches duplicate an already-fully-punched day (e.g. a
`MISSING_PUNCH` request approved against a day that was never actually missing a punch) can
produce two near-identical `IN`/`OUT` pairs on the same `AttendanceDay`, and `calculation.py`'s
existing punch-pairing can turn a previously-`PRESENT` day `INCOMPLETE` as a result — reproduced
live against a real server (§18 of the implementation report). This is pre-existing W4/W6
punch-pairing-under-duplicate-punches behavior (WD-28's "corrections are always additive" already
establishes that original punches are never touched or deduplicated against a new correction),
not something W8 introduced or should silently work around; W8's own `incomplete_at_lock_
behaviour` resolution (decision 4) handled the resulting `INCOMPLETE` day correctly. Flagged here,
not fixed, per this slice's own scope boundary.

---

## WD-31 — W9 `LeaveDayProjection`: attendance-owned mirror of Leave's read model, real
leave overlay in `evaluate_day`, refuse-only lock interaction

**Status:** LOCKED (recorded before implementation, per this document's own rule; two genuinely
open design points — projection backing store, ingestion API surface — were put to the user
before any code was written, per the task brief's own "stop and ask, don't silently choose" rule;
both were resolved with an explicit answer, recorded below)

**Context:** architecture §21 fully specifies the `LeaveDayProjection` contract (fields, precedence,
fraction/LOP mapping) and §30 names W9's scope exactly: "Leave projection adapter (mocked until
Leave exists) + recompute-on-event." No Leave module, package, table, or service exists anywhere in
this codebase (confirmed by full-repo grep, not assumed from prior reports). `calculation.py`'s own
docstrings state, verbatim, that the leave overlay is a "no-op seam" — `work_on_leave_behaviour`
(W3, `AttendancePolicyVersion`), the `LEAVE`/`ON_DUTY`/`WFH` `attendance_status` enum values, and
`AttendancePeriodSummary.leave_days` (W8) all shipped as dead/unused surface explicitly reserved for
this slice, mirroring how `AttendanceLock`'s columns shipped dead ahead of W8. `AttendancePeriodSummary`'s
`leave_days` aggregation code (`service.py`) already existed but had never once fired, since nothing
ever produced `attendance_status="LEAVE"`.

**Decision:**

1. **`leave_day_projection` is a real, attendance-owned table — a temporary mirror of the
   contract, not the leave ledger.** Architecture §21 describes the projection as "a read model
   published by Leave (service method, not table sharing)," but no Leave module exists to publish
   it. Put to the user as an explicit choice (minimal owned table vs. a pure interface with no
   persistence): the owned-table option was chosen, matching the precedent §12.3 already
   established for comp-off ("store the fact on `AttendanceDay`... so nothing is lost" until Leave
   exists to own the real ledger). `leave_day_projection` is explicitly documented (model
   docstring, this entry) as replaceable wholesale once a real Leave module ships — nothing else in
   this module depends on its storage shape, only on the typed `LeaveOverlayEntry` values resolved
   from active rows. It is never described or treated as the leave ledger; ADR-0004 stays untouched.

2. **A narrow internal HTTP endpoint (`POST /leave-projections`, `POST /leave-projections/{id}/cancel`,
   reads via `GET`), not a Python-only service method.** Also put to the user explicitly: architecture
   §25 sanctions "in-process service calls... acceptable... as a temporary seam" (no real
   event/outbox infra exists yet, ADR-0012), which would have permitted a service-method-only
   design. The HTTP option was chosen so Phase 11's live-verification requirement (inject a real
   projection through the intended contract, via real HTTP) is actually exercisable, and so a
   future Leave module — or an ops tool, meanwhile — has a real integration point. This is the
   adapter's own narrow surface (sync/cancel/list/get for one entity), not a Leave CRUD API: no
   leave type, balance, application-workflow, or approval endpoint exists anywhere.

3. **The leave overlay is real in `evaluate_day` as of this slice — `_apply_leave_overlay`,
   applied once the punch-derived outcome is known, for every branch except the population gate
   (`NOT_JOINED`/`EXITED`, which ranks above `LEAVE` in §19.4) and `CONFIG_ERROR` (nothing
   well-defined to overlay onto).** Full-day leave (active fractions summing to >= 1.00) wins
   outright per §19.4's literal precedence order — which places `LEAVE` *above* calendar
   `NOT_EXPECTED` — without ever touching `calendar_day_type` itself (still Calendar's concern,
   WD-04/WD-07); `calendar_day_type` continues to report HOLIDAY/WEEKLY_OFF/WORKING/SHUTDOWN
   unchanged regardless of what the overlay does to `attendance_status`. `work_on_leave_behaviour`
   (W3, dead until now) is consulted for the one case §19.3 names explicitly — punches exist
   despite full-day leave: `KEEP_LEAVE` (default) keeps `attendance_status=LEAVE` and zeroes
   late/early; `PRESENT_CANCEL_LEAVE_HINT` keeps the punch-derived outcome and raises a new
   `work_on_leave_flagged` column (additive migration) for Leave to see — Attendance never cancels
   the leave application itself, matching §19.3's "Attendance never writes the leave ledger."

4. **Half-day leave (0 < fraction < 1.00) treats the remaining half of the day as a flat 0.50
   contribution from whatever the punch-derived outcome already computed** — not a minute-by-minute
   re-evaluation scoped to one half of the shift. This is a documented simplification, not a silent
   gap, and directly mirrors the precedent `_evaluate_split` already set for SPLIT shift duty
   blocks ("checked for at least one overlapping pair... not further sub-analysed"). It reproduces
   architecture §19.4's own worked example exactly: half-day unpaid leave + a fully-punched other
   half → `paid_day_fraction=0.50`/`lop_fraction=0.50`; half-day *paid* leave with no other work
   correctly falls through to `attendance_status=HALF_DAY`/`LEAVE` with the fraction math §11.4
   already specifies. Verified live against a real server, not just unit tests.

5. **Multiple leave projections may cover the same employee-date** (§21 explicitly permits this —
   the half-day-AM-plus-half-day-PM case). Active (`APPROVED`) fractions are summed; a sync that
   would push the total above 1.00 is rejected fail-closed (`LEAVE_PROJECTION_OVERLAP`, 409) before
   any row is written — Phase 2's "fail closed if the projection is ambiguous or invalid,"
   implemented as a service-layer cross-row check (no DB constraint can express a cross-row sum),
   mirroring `InvalidPolicyBandError`'s identical validate-in-service posture.

6. **Cancellation is `status='CANCELLED'`, never a delete** — provenance/audit is preserved,
   mirroring WD-11's never-mutate-the-fact posture. A resync of the same `(employee_id,
   attendance_date, leave_application_id)` natural key updates the existing row in place (bumping
   `source_version`), reviving a previously-cancelled row rather than accumulating duplicates —
   idempotent republish, matching how a corrected projection is expected to arrive.

7. **Both `sync` and `cancel` consult `_ensure_date_open` (the exact W8 seam, unmodified) and
   refuse with the pre-existing `ATTENDANCE_PERIOD_CLOSED` (409) against a locked period — no new
   lock mechanism, and no `AttendanceAdjustment`/arrears path.** Architecture §21's own contract row
   ("Leave approved after payroll lock... default refuse; HR exception creates arrears, not a
   rewrite") has no implementable target for its "arrears" half: `AttendanceAdjustment` does not
   exist through W8 (PD-LOCK-2, still OPEN). W9 implements only the "refuse" half, exactly
   consistent with how W8 itself scoped the identical problem for regularization/overtime — the
   only correction path for a locked date remains a full `ATTENDANCE.UNLOCK` period reopen.

8. **Recompute-on-event (architecture §30's own naming) is a synchronous, in-process call to the
   existing `AttendanceDayService.calculate()`** — not a new recompute code path, and not a real
   event bus (§25 sanctions this explicitly as a temporary seam given no ADR-0012 infra exists
   yet). `sync`/`cancel` each trigger exactly one `calculate()` call for the affected employee-date,
   inside the same request, after the projection write is committed.

9. **`ATTENDANCE.LEAVE_PROJECTION_SYNC` is one new COMPANY-scoped code covering both `sync` and
   `cancel`** (mirrors `ATTENDANCE_LOCK`'s static-gate posture — this is an internal integration
   seam, not self-service). Reads (`list`/`get`) reuse `ATTENDANCE.VIEW`/`ATTENDANCE.VIEW_ALL` — no
   third code, mirroring every other read-reuse precedent in this module (WD-28 decision 6 / WD-29
   decision 6 / WD-30 decision 7's identical reasoning).

**Rejected:** a pure interface/Protocol with no persistence (decision 1 — would make Phase 10/11's
recompute, locking, and payroll-fact tests, and live verification, unexercisable with real data); a
Python-only service method with no HTTP route (decision 2 — technically sanctioned by §25 but makes
real live verification impossible); building `AttendanceAdjustment`/an arrears mechanism for
leave-approved-after-lock (decision 7 — same reasoning as WD-30 decision 8: no architecturally
assigned owner or defined rule set exists yet, PD-LOCK-2 stays open); a minute-by-minute half-day
split evaluation (decision 4 — no finer contract specified, and the SPLIT-shift precedent already
established that block/half-level granularity is this codebase's accepted simplification tier);
treating LEAVE as ranking below calendar `NOT_EXPECTED` (rejected as a misreading of §19.4's own
literal precedence list, which places LEAVE above NOT_EXPECTED); a fourth/third read permission code
(decision 9); a generic JSON leave-rules engine (WD-22 forbids this outright).

**OPEN (unchanged, PD-LOCK-2):** whether `AttendanceAdjustment`/an `APPROVED_PENDING_ARREARS` path
should ever be built — W9's leave-cancellation-after-lock case hits the exact same open question W8
already recorded; no new information resolves it here.

**OPEN (new, PD-LEAVE-1):** the real Leave module, when built, must decide whether it *replaces*
`leave_day_projection` wholesale (dropping this table, switching Attendance's read to a real
in-process service call per §21's own literal wording) or *becomes* the writer of this same table
(keeping the schema, changing only who populates it). Architecture doesn't specify which — flagged
for whoever builds Leave, not resolved here.

---

## Divergences index (quick reference) — continued

| Prior source | This log |
|---|---|
| W7 task brief's literal read of "build overtime detection" | WD-29 (already built in W3/W4; W7 scope narrowed to approval/caps/comp-off-fact/SPLIT-fix after audit) |
| W8 task brief's implicit assumption of a richer `OPEN → CLOSING → CLOSED/LOCKED` lifecycle | WD-30 decision 1 (collapsed to two persisted states; `CLOSING` has no observable code path under synchronous finalization) |
| Architecture §21's literal "service method, not table sharing" | WD-31 decision 1 (an owned mirror table, since no Leave module exists to expose that service method — explicitly a temporary, replaceable stand-in) |

---

**STOP.** Implementation does not start until the architecture and this log are reviewed and
explicitly approved.
