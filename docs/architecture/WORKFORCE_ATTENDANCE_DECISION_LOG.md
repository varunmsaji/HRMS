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

**STOP.** Implementation does not start until the architecture and this log are reviewed and
explicitly approved.
