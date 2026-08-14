# Shift Rules Module — Pre-Implementation Audit

Status: **Audit only — no code changed.** Follows the same audit-then-build discipline used
for Legal Entity, Branch, Department, Designation, and Grade
(`docs/modules/grade/00_GRADE_AUDIT.md`). This document inspects the current DB, the
completed Grade slice (the closest pattern to replicate — a standalone, company-scoped
resource with no parent hierarchy), and every Shift reference across product docs, the
Sprint 3 plan, and the Attendance/Employee-Assignment docs that consume Shift, then states
exactly what this slice builds, what it explicitly defers, and why — before writing code.

---

## 1. Current state

**Shift has zero application code and zero database presence.** Confirmed by a repo-wide
case-insensitive search: no `apps/api/src/**` file references "shift" anywhere today, and no
`shift`/`shift_rule`/`shift_roster` table exists in `apps/api/scripts/sql/001_init_schema.sql`
or any Alembic migration. This is a stronger "nothing exists" starting point than every prior
organisation-module slice — Grade, Department, Designation, and Branch all began from a
Prisma-era DB stub table; Shift has no stub at all. It is a genuinely new table, not a
column-expansion migration.

The only things that exist today:

- **Frontend**: an empty `apps/web/src/lib/shift/` directory with no files in it — an
  artifact of scaffolding, not real code. No Shift screen, component, or type file exists.
  Two incidental case-insensitive "shift" matches elsewhere in the frontend
  (`layout.tsx`'s font-loading comment, `Array.prototype.shift()` in
  `validate-department.ts`) are unrelated false positives.
- **Documentation**: no `docs/modules/shift-rules/` directory existed before this audit.
  Shift is discussed extensively across `docs/product/17_SRS_Phase1_Core_Modules.md` (FR-ATT-
  001–005), `docs/product/08_Database_Architecture.md` §6, `docs/sprints/
  SPRINT_3_COMPANY_FOUNDATION.md` (Decision D5, Feature 4.2), `docs/product/
  19_RBAC_and_Permission_Matrix.md`, `docs/product/09_API_Standards.md`, and
  `docs/product/24_UIUX_Screen_Inventory_and_Design_System.md` — none of it previously
  consolidated into an implementation-ready spec.
- **A precedent-setting Sprint decision (D5)** that scopes this exact task down to a *shift
  master* only — no assignment, no roster, no rotation-pattern generator — because those
  require Employee, which doesn't exist yet. This matches, almost word for word, this task's
  own instruction not to touch Employee/Employee Assignment/Attendance.
- **A dependency the Sprint plan itself declares (`week_off_pattern`, Task 3.1.1's own
  sequencing) that was never built** — Branch's own slice deliberately deferred
  `branch.week_off_pattern_id` "to Task 3.1.3" (`organisation/models.py::Branch` docstring),
  and no later slice built Task 3.1.3. This is the central open dependency question this
  audit resolves in §3.

**The good news**: the Grade slice, which shipped most recently, is the closest structural
template — a standalone resource scoped only by `company_id`, no parent FK, no hierarchy, a
single `ORG.<ENTITY>.MANAGE` permission, full CRUD + soft-deactivate + optimistic
concurrency + audit. Shift follows that shape exactly, differing only in its field set (time-
of-day values instead of money) and one genuinely new server-side validation rule (cross-
midnight time-ordering) in place of Grade's CTC-range rule.

---

## 2. Database state

### 2.1 What exists today

Nothing. No `shift` table, no stub, no partial column set.

### 2.2 What the spec requires — two different answers

Two documents describe the `shift` table, at two different scopes, and this audit treats
them as **build-time spec vs. long-term target spec**, not as a contradiction to silently
pick one side of:

**A. The long-term full-featured target** — `docs/product/08_Database_Architecture.md:273-279`
(§6.1 `shift`):

```
id, company_id, code, name, shift_type (FIXED/FLEXIBLE/SPLIT/ROTATIONAL), start_time, end_time,
is_night_shift, crosses_midnight, total_hours, break_minutes, is_break_paid,
break_windows JSONB, grace_in_minutes, grace_out_minutes, min_hours_full_day,
min_hours_half_day, max_hours_per_day, is_ot_eligible, ot_starts_after_minutes,
week_off_pattern_id, flexible_core_start, flexible_core_end, flexible_window_start,
flexible_window_end, second_block_start, second_block_end (split shift)
```

Plus two companion tables at `08_Database_Architecture.md:281-285` — `shift_rotation_pattern`
and `shift_roster` — which model assignment/rostering, not the master definition.

**B. The Sprint 3 build-time scope** — `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` Decision
D5 (line 21) and Task 4.2.1 (line 596):

> D5: "Shift in this sprint is the shift master only (`docs/product/17` FR-ATT-001) — name,
> timings, breaks, grace, OT eligibility flag. No shift **assignment**, no roster, no
> rotation-pattern generator (FR-ATT-002). Assignment requires employees to assign shifts to,
> which don't exist until Sprint 4."

Task 4.2.1's actual column list (narrower than §6.1 above):

```
id, company_id, name VARCHAR(100), code VARCHAR(30), start_time TIME, end_time TIME,
break_minutes_paid INTEGER DEFAULT 0, break_minutes_unpaid INTEGER DEFAULT 0,
grace_in_minutes INTEGER DEFAULT 0, grace_out_minutes INTEGER DEFAULT 0,
half_day_threshold_hours NUMERIC(4,2), min_hours_full_day NUMERIC(4,2),
is_night_shift BOOLEAN DEFAULT false, is_cross_midnight BOOLEAN DEFAULT false,
week_off_pattern_id UUID NULL FK, is_ot_eligible BOOLEAN DEFAULT false,
is_active BOOLEAN DEFAULT true, deleted_at, version
```

Task 4.2.1's own Acceptance Criteria is explicit that the gap between A and B is
**intentional, not an oversight**: *"No roster/assignment table or endpoint exists this
sprint — confirmed absent, not just unbuilt (i.e., don't accidentally create `shift_roster`
as a side effect of following the DB architecture doc too literally; that table is explicitly
Sprint 7 per D5)."*

**Resolution, consistent with this task's own instructions** ("do not implement Employee,
Employee Assignment, Attendance… or any other module yet"): this slice builds column set **B**
— the Sprint 3 master-only scope. Set A's `shift_type`, `total_hours`, `break_windows` JSONB,
`max_hours_per_day`, `ot_starts_after_minutes`, and all flexible/split-shift columns
(`flexible_core_start/end`, `flexible_window_start/end`, `second_block_start/end`) are **not
implemented** — they belong to FR-ATT-003 (Flexible shift) and FR-ATT-004 (Split shift), which
the Sprint doc's own D5 does not scope into this build, and which have no CRUD/validation
behavior defined anywhere else. Flagged as a known limitation (§9), not silently dropped.

### 2.3 `shift_roster`/`shift_rotation_pattern` — explicitly out of scope

Per D5 and Task 4.2.1's own Acceptance Criteria (quoted above), confirmed absent this slice.
`docs/product/VERSION_1_ROADMAP.md:313` places roster/assignment tables under "5. Attendance"
as a separate future roadmap block, consistent with this task's explicit instruction not to
build Attendance.

### 2.4 `week_off_pattern_id` — the dependency gap

Task 4.2.1 declares its own dependency: *"Dependencies: 3.1.1 (shift references
`week_off_pattern`)"* (line 595) — actually Task 3.1.3, which is the task that builds
`week_off_pattern` (line 438-446). **Task 3.1.3 was never implemented.** Confirmed by:

- `organisation/models.py` has no `WeekOffPattern` class.
- `Branch`'s own docstring (`organisation/models.py:104-106`): *"`holiday_calendar_id`/
  `week_off_pattern_id` are intentionally absent — deferred to Feature 4.1 and Task 3.1.3
  respectively (see the Branch module audit)."*
- No later slice (Department, Designation, Grade) built it either — none of their audits
  mention `week_off_pattern`.

This mirrors exactly the situation Designation faced with `grade_id` before Grade existed:
a documented FK to a table that doesn't exist yet. The established precedent across every
prior slice in this series (Branch deferring its own `week_off_pattern_id`/
`holiday_calendar_id`; Designation deferring `grade_id` until the Grade slice) is: **exclude
the column entirely until its target table is built, add it via a follow-up migration when
that table ships** — never a passive/inert column pointing at nothing, and never inventing
the target table as a side effect of unblocking the current slice (that would be building
`week_off_pattern`, a different table, under cover of "Shift Rules").

**Consequence for this task**: `week_off_pattern_id` is **not added** to `shift` this slice.
`is_night_shift`/`is_cross_midnight`/`is_ot_eligible` and every other column with no
cross-table dependency are unaffected and ship normally. This is flagged as a known
limitation (§9) and an explicit deferred item (§11), exactly as `designation.grade_id` was
during the Designation slice.

### 2.5 `code` uniqueness — no constraint documented, none invented

Unlike Grade (which had a real, pre-existing `UNIQUE (company_id, code)` DB constraint),
Shift has no DB table at all yet, so there is no pre-existing constraint to preserve. Neither
Database Architecture §6.1 nor Task 4.2.1 states a uniqueness rule for `shift.code`. Following
the Branch/Department/Designation precedent (not Grade's — Grade's uniqueness was preserved
because it already existed at the DB level, not because every organisation resource needs
one), this slice does **not** invent a uniqueness constraint on `shift.code` or `shift.name`.

### 2.6 Required columns vs. optional — reading the spec literally

Task 4.2.1's column list marks some columns `NULL` explicitly (`half_day_threshold_hours`,
`min_hours_full_day`, `week_off_pattern_id`) and gives others a `DEFAULT` (the four
break/grace integers, the three booleans). `start_time`/`end_time`/`name` carry neither
marker — read as required (`NOT NULL`), consistent with FR-ATT-001 naming "start/end time" as
the shift's own defining identity, and with `name` following the same "name is always
required" convention every prior organisation resource used. `code` also carries no `NULL`
marker in the column list, but — mirroring Branch/Department/Designation's own resolution for
an ungoverned `code` field (not Grade's, which had a real pre-existing `NOT NULL` at the DB
level) — this audit treats `code` as **optional**, since no document states it is required and
no uniqueness constraint forces it to be meaningful. This keeps Shift consistent with three of
the four prior precedents; Grade's `code` was the outlier, and it was an outlier for a
documented DB reason (§6.2 of the Grade audit), which Shift doesn't share.

---

## 3. Relationship with other entities

**Shift is a standalone aggregate**, exactly like Grade: it references only `company_id`, has
no FK to Legal Entity, Branch, Department, Designation, or Grade, and none of those resources
gain a `shift_id`/`default_shift_id` column this slice (see §3.1 below for why, despite BR-14
naming "shift default" in an override chain).

### 3.1 BR-14 / FR-EMP-018's override chain — named, not built, this slice

`docs/product/02_PRD.md:213` (BR-14): *"Notice period, probation period, leave entitlement
and shift default at Company level, are overridable at Branch → Department → Grade →
Employee level; the most specific setting wins."* `docs/product/17_SRS_Phase1_Core_
Modules.md:155` (FR-EMP-018) states the same chain in Employee terms: *"Employee → Grade →
Designation → Department → Branch → Company (most specific wins)."*

Grade's own slice implemented the notice-period/probation legs of this chain
(`grade.notice_period_days`, `grade.probation_days`) but **not** the shift leg — Grade's own
audit is silent on why, and no `shift_id`/`default_shift_id` column exists on `branch`,
`department`, `designation`, or `grade` today.

**This audit does not retroactively add one.** Two independent reasons:

1. **Scope discipline** — this task's own instructions are explicit: "Do not modify unrelated
   modules." Adding `default_shift_id` to Branch/Department/Grade would mean editing three
   already-shipped modules' models/schemas/migrations/service/router/frontend, which is a
   materially larger and different change than "build the Shift Rules vertical slice."
2. **No buildable spec exists for the override *mechanism*** — BR-14/FR-EMP-018 name the
   *chain*, but no document specifies which table(s) carry the override column, what happens
   when an employee has no shift resolved anywhere in the chain (Testing Strategy
   `15_Testing_Strategy.md:148` only says "falls back to company default; warning raised" —
   itself contingent on Employee existing), or how resolution order interacts with the
   Company-level `business_hours_start`/`business_hours_end` fields that already exist on
   `Company` (`identity.py:69-70`) and are documented as a *separate*, company-wide default
   that Shift "may override" (`docs/modules/company/02_Domain_Model.md:124`) — i.e., Company
   already has its own informal default-hours mechanism, and how it reconciles with a future
   `default_shift_id` chain is genuinely undefined.

**Consequence**: flagged as an unresolved product decision (§10) and known limitation (§9),
exactly the same posture Grade's own audit took toward `leave_policy_id`. This slice ships
the Shift *master* only; the override chain is Employee/Employee-Assignment-era work.

### 3.2 Company's `business_hours_start`/`business_hours_end` — a pre-existing, informal shift-like field

`Company` already carries `business_hours_start`/`business_hours_end` (`TIME`, nullable) at
the DB and schema level (`identity.py:69-70`; `organisation/schemas.py`'s
`BusinessHoursSchema`, `"%H:%M"` string on the wire). `docs/modules/company/
02_Domain_Model.md:124,127,163` documents this explicitly as informal and superseded once
Shift exists: *"company-wide default; Shift (separate sub-domain) is the actual scheduling
unit and may override"* and *"no overnight-spanning company-wide default; Shift-level
overrides may model overnight shifts — that's the Shift sub-domain's concern, not Company's."*

**No code change to `Company` is implied or made by this slice** — `business_hours_*` remains
exactly as-is (a simple, non-overnight-aware pair of `TIME` fields on the company profile).
This audit only confirms the two coexist without conflict: `business_hours_*` is Company's own
generic default (still useful before any `Shift` exists), and `Shift` is the real, richer
scheduling primitive Company's own docs anticipate. Confirmed as the established, safe
`_format_time`/`_parse_time` (`"%H:%M"` string) convention for `TIME` columns, which this
slice reuses verbatim for `shift.start_time`/`shift.end_time` (§4.3).

### 3.3 Employee Assignment's `shift_id` — confirmed out of scope, referenced only as a forward pointer

`docs/product/08_Database_Architecture.md:95,232,234` and `docs/product/17_SRS_Phase1_Core_
Modules.md:123` document `employee_assignment.shift_id` and a `SHIFT_CHANGE` change-type
enum value. `employee_assignment` does not exist (Employee is out of scope this task). This
slice creates the `shift` table that a future Employee Assignment slice will reference by id
— an intentionally one-directional, forward-compatible relationship, the same posture Grade
took toward `employee_assignment.grade_id`.

### 3.4 Attendance — the primary future consumer, confirmed out of scope

FR-ATT-001 through FR-ATT-007 and `attendance_day.shift_id`/`roster_source`
(`08_Database_Architecture.md:314`) describe how Attendance will consume Shift: grace-minute
late-marking, cross-midnight day attribution (FR-ATT-005, AC-ATT-005.1), weekly-off status
resolution, and OT eligibility gating. None of this is implemented or referenced by this
slice — Shift ships as pure master data with no Attendance-side behavior. Flagged in §9/§12 so
the eventual Attendance slice has a clear list of fields it will need to consume
(`grace_in_minutes`, `grace_out_minutes`, `is_cross_midnight`, `is_ot_eligible`,
`half_day_threshold_hours`, `min_hours_full_day`).

---

## 4. Required data model

### 4.1 ORM model — `organisation/models.py::Shift`

Same file as `LegalEntity`/`Branch`/`Department`/`Grade`/`Designation`. Modelled directly on
`Grade` (standalone, `company_id`-only aggregate) rather than `Branch`/`Department` (which
have parent FKs Shift doesn't need).

```python
class Shift(Base, TimestampMixin):
    """A shift master definition (FR-ATT-001; docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md
    Decision D5, Task 4.2.1) — timings, breaks, grace, and OT-eligibility only. No
    assignment/roster/rotation-pattern data (D5 — that's an Attendance-module concern,
    Sprint 7). `week_off_pattern_id` is intentionally absent — `week_off_pattern` itself was
    never built (deferred by the Branch slice's own Task 3.1.3, never picked up since); see
    docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md §2.4."""

    __tablename__ = "shift"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    break_minutes_paid: Mapped[int] = mapped_column(Integer, default=0)
    break_minutes_unpaid: Mapped[int] = mapped_column(Integer, default=0)
    grace_in_minutes: Mapped[int] = mapped_column(Integer, default=0)
    grace_out_minutes: Mapped[int] = mapped_column(Integer, default=0)
    half_day_threshold_hours: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    min_hours_full_day: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    is_night_shift: Mapped[bool] = mapped_column(Boolean, default=False)
    is_cross_midnight: Mapped[bool] = mapped_column(Boolean, default=False)
    is_ot_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
```

`week_off_pattern_id` intentionally absent per §2.4. No money columns — Shift carries no
compensation data, so ADR-0006 doesn't apply here. `Time` (SQLAlchemy) / `time` (Python
stdlib) already has a live precedent in this codebase: `Company.business_hours_start/end`
(`hrms/core/db/models/identity.py:69-70`) — same type, same nullability posture (Company's
version is nullable since business hours are optional; Shift's `start_time`/`end_time` are
required per §2.6).

### 4.2 Migration

New file, `apps/api/alembic/versions/20260813170000_shift_rules.py`
(`down_revision = "20260813160000"`, chained after the Grade migration — current head).
Unlike every prior organisation-module migration, this one is a **`CREATE TABLE`**, not an
`ALTER TABLE` expansion — there is no stub to build on (§2.1).

```sql
CREATE TABLE shift (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES company(id) ON DELETE RESTRICT ON UPDATE CASCADE,
  name VARCHAR(100) NOT NULL,
  code VARCHAR(30),
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  break_minutes_paid INTEGER NOT NULL DEFAULT 0,
  break_minutes_unpaid INTEGER NOT NULL DEFAULT 0,
  grace_in_minutes INTEGER NOT NULL DEFAULT 0,
  grace_out_minutes INTEGER NOT NULL DEFAULT 0,
  half_day_threshold_hours NUMERIC(4,2),
  min_hours_full_day NUMERIC(4,2),
  is_night_shift BOOLEAN NOT NULL DEFAULT false,
  is_cross_midnight BOOLEAN NOT NULL DEFAULT false,
  is_ot_eligible BOOLEAN NOT NULL DEFAULT false,
  is_active BOOLEAN NOT NULL DEFAULT true,
  deleted_at TIMESTAMPTZ,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX shift_company_id_idx ON shift (company_id);
CREATE INDEX shift_company_active_idx
  ON shift (company_id, is_active) WHERE deleted_at IS NULL;

ALTER TABLE shift ENABLE ROW LEVEL SECURITY;
ALTER TABLE shift FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON shift
  USING (company_id = current_setting('app.company_id', true)::uuid);
```

No `UNIQUE (company_id, code)` constraint (§2.5). RLS asserted directly in this migration
(not merely idempotently re-asserted, since the table is brand new) — same posture as every
prior slice's own migration; the standalone `scripts/sql/002_row_level_security.sql` is
confirmed not to list `shift` in its static array either, consistent with every prior audit's
finding that this file is not the live RLS registry for any environment.

### 4.3 Schemas (`organisation/schemas.py`)

Add `ShiftCreate`, `ShiftUpdate`, `ShiftRead`, `shift_to_read`, `shift_to_audit_dict`,
`build_shift_update_values` — same five/six-function shape as `Grade*`. Reuses the
module-level `_format_time`/`_parse_time` helpers already defined for `Company.business_hours_*`
(`schemas.py:269-284`) rather than duplicating a second time-formatting helper — `"%H:%M"` on
the wire, matching `BusinessHoursSchema`'s own field pattern (`^\d{2}:\d{2}$`).

- `name: str` — required, 1–100 chars.
- `code: str | None` — optional, ≤30 chars (§2.6).
- `start_time: str`, `end_time: str` — required, `"HH:MM"` pattern-validated
  (`^\d{2}:\d{2}$`, mirroring `BusinessHoursSchema`).
- `break_minutes_paid`, `break_minutes_unpaid`, `grace_in_minutes`, `grace_out_minutes: int`
  — default `0`, `ge=0`.
- `half_day_threshold_hours`, `min_hours_full_day: Decimal | None` — optional, `ge=0`.
- `is_night_shift`, `is_cross_midnight`, `is_ot_eligible: bool` — default `False`.
- `is_active` server-controlled on create, client-settable via PATCH only — same rule as
  every other organisation-module resource.

`ShiftUpdate` mirrors `GradeUpdate`'s shape (all fields optional, `extra="forbid"`, plus
`is_active`).

---

## 5. API requirements

Matching `docs/product/09_API_Standards.md` §5.3 (referenced at Task 4.2.1, line 599) and the
exact envelope/error conventions every prior organisation-module resource used:

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/shifts` | `ORG.SHIFT.MANAGE` | List, company-scoped, unfiltered (same low-cardinality assumption every prior list endpoint made) |
| POST | `/v1/shifts` | `ORG.SHIFT.MANAGE` | Create; `is_active` always `true` |
| GET | `/v1/shifts/{shift_id}` | `ORG.SHIFT.MANAGE` | 404 (never 403) cross-tenant or not-found |
| PATCH | `/v1/shifts/{shift_id}` | `ORG.SHIFT.MANAGE` | `If-Match: <version>`; partial update |
| DELETE | `/v1/shifts/{shift_id}` | `ORG.SHIFT.MANAGE` | Soft deactivation only; `If-Match`; `200 DataEnvelope<ShiftRead>`, not `204` |

---

## 6. Business rules

### 6.1 Company ownership

Identical mechanism to every other organisation-module resource — `company_id` filtering,
belt-and-suspenders in the repository, RLS as backstop.

### 6.2 Cross-midnight time-ordering — documented, implemented

Task 4.2.1's own Backend Work note states the rule explicitly: *"`end_time` before
`start_time` is **valid** (represents a cross-midnight shift) only if `is_cross_midnight=true`,
otherwise rejected as `422`."* Implemented as a service-layer check: if `end_time <=
start_time` and `is_cross_midnight` is not `true`, raise `422 INVALID_SHIFT_TIME_RANGE` (or
equivalent). If `is_cross_midnight=true`, `end_time <= start_time` is expected and accepted
(that is what "crosses midnight" means); `end_time > start_time` while
`is_cross_midnight=true` is not rejected either — no document states a same-day shift can't
also carry the flag, so this audit does not invent a rejection for that combination.

### 6.3 Half-day threshold vs. min-hours-full-day — documented, implemented

Task 4.2.1's own Testing Requirements name a second rule: *"half-day threshold must be less
than min-hours-full-day when both present."* Implemented as a service-layer check, structured
identically to Grade's `min_ctc <= max_ctc` rule: when both `half_day_threshold_hours` and
`min_hours_full_day` are provided, reject (`422 INVALID_SHIFT_HOURS_RANGE` or equivalent) if
`half_day_threshold_hours >= min_hours_full_day`. Not required when either is absent (both
nullable). Re-validated on update against the *effective* range (patch value where present,
otherwise the existing stored value) — same posture as Grade's CTC-range re-validation.

### 6.4 No documented deactivation-blocking rule

FR-ORG-014's literal text blocks deactivation of an org unit "only if no active employee is
assigned" — Employee doesn't exist, so this can't be checked, identical to every prior module.
No document names any other resource as a blocker on Shift deactivation (Shift has no
downstream resource referencing it yet — Employee Assignment, the eventual referencer, is out
of scope). **This slice ships Shift deactivation/reactivation with no dependency-blocking
check.**

### 6.5 Optimistic concurrency

`version` + `If-Match`, identical mechanism to every other organisation-module resource.

### 6.6 Soft deactivation only

`DELETE` never hard-deletes; flips `is_active` to `false` via the same code path as `PATCH
{is_active: false}`.

### 6.7 No invented rules

Per this task's own explicit instructions, the following are **not** implemented, because no
document specifies them or they require out-of-scope modules: `shift_type`
(FIXED/FLEXIBLE/SPLIT/ROTATIONAL) and any split/flexible-shift field or validation (§2.2), OT
computation itself (`is_ot_eligible` is a stored flag only — no OT calculation logic exists
anywhere in this codebase), weekly-off resolution (`week_off_pattern_id` deferred, §2.4),
holiday interaction, roster/assignment of any kind, the BR-14 override-chain mechanism (§3.1),
and any Attendance-side consumption logic (grace-period math, late-marking, cross-midnight day
attribution — FR-ATT-005/007, §3.4).

---

## 7. Permission requirements

**Two inconsistent documented codes exist** — this audit resolves the conflict rather than
silently picking one:

- `docs/product/19_RBAC_and_Permission_Matrix.md:56-58` places shift management inside the
  `ATTENDANCE` domain's permission list: `ATTENDANCE.SHIFT_MANAGE`.
- `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:1416` (and used throughout Feature 4.2, e.g.
  line 596/599-602) defines and uses `ORG.SHIFT.MANAGE` — in the `ORG` domain, matching where
  the table actually lives this slice (`organisation` module, per Task 4.2.1's own text: "this
  module owns it as org-setup config; the future `attendance` module will own roster/
  assignment and reference `shift` by id").

**Resolution**: `ORG.SHIFT.MANAGE`, following the exact precedent this series already
established for Legal Entity (`docs/modules/grade/00_GRADE_AUDIT.md`'s sibling audit chose the
Sprint doc over the RBAC matrix for the same reason): *the Sprint doc is the more recent,
module-scoped, implementation-precise source, and it is what the code that actually ships this
table will use.* `ATTENDANCE.SHIFT_MANAGE` is reserved, unused terminology for if/when a real
Attendance-module-owned shift-*assignment* permission is introduced later (a different
capability — assigning a shift to a person — from managing the shift master itself).

```python
ORG_SHIFT_MANAGE = "ORG.SHIFT.MANAGE"
```

Added to `ORGANISATION_PERMISSIONS` and granted to the `COMPANY_ADMIN` system role at company
registration time, the same `get_or_create_permission` → `insert_role_permission` pattern used
for every prior organisation-module permission.

---

## 8. Tenant / RLS / audit requirements

Identical mechanism to every other organisation-module resource — `TenancyMiddleware` +
`get_tenant_context`, belt-and-suspenders `company_id` filtering in every repository method,
RLS asserted directly in the migration (§4.2, new table — not merely re-asserted). Cross-
tenant access, including a guessed `shift_id`, must return `404`, never leak.

Audit events via the existing `AuditService`, mirroring Grade's four: `SHIFT_CREATED`,
`SHIFT_UPDATED`, `SHIFT_DEACTIVATED`, `SHIFT_REACTIVATED`, `entity_type = "shift"`,
before/after `ShiftRead` snapshots. No `RESTRICTED`-classified fields — timing/break/grace
configuration is organisational policy data, not personal or compensation data.

---

## 9. Known limitations (flagged now, not silently discovered later)

1. **No `week_off_pattern_id`** (§2.4) — `week_off_pattern` itself was never built (deferred
   by Branch's own Task 3.1.3, never picked up since). Shift ships without this FK; a future
   slice adds it once `week_off_pattern` exists, mirroring exactly how `designation.grade_id`
   was added once Grade existed.
2. **No `shift_type`/flexible/split-shift support** (§2.2, §2.6) — FR-ATT-003/004 are not
   implemented; only the fixed-shift shape (§6.7's list) ships this slice, per Sprint 3's own
   Decision D5 scope-down.
3. **No BR-14/FR-EMP-018 override-chain mechanism** (§3.1) — no `default_shift_id` column
   added to Branch/Department/Grade/Designation this slice; the chain is named in the PRD/SRS
   but has no buildable spec for *how* it's stored, and building it would mean editing four
   already-shipped, unrelated modules.
4. **No Attendance-side consumption** (§3.4) — grace-period math, late-marking, cross-midnight
   day attribution, OT computation, and weekly-off/holiday status resolution are all
   Attendance-module concerns, explicitly out of scope this task.
5. **No default "General Shift" seed on registration** — Task 4.2.2 (`docs/sprints/
   SPRINT_3_COMPANY_FOUNDATION.md:604-613`) specifies seeding one default shift
   (09:00–18:00) at company registration. **Not implemented this slice** — no prior
   organisation-module slice (Legal Entity, Branch, Department, Designation, Grade)
   established a registration-time default-row-seeding precedent to reuse (`register_company`
   today only seeds permissions/role/setup-progress/subscription rows, never a default
   business-data row for any resource), so building one now would be introducing a new
   mechanism rather than reusing an established pattern — contrary to this task's explicit
   instruction to reuse exact existing patterns. Flagged as a deferred item (§11), not
   silently dropped.
6. **No query-param filtering** on `GET /shifts` — consistent with every prior
   organisation-module list endpoint.
7. **No uniqueness constraint** on `shift.code` or `shift.name` (§2.5) — no document specifies
   one, and unlike Grade, there is no pre-existing DB constraint to preserve.

---

## 10. Decisions made in this audit (stated explicitly, per this task's instructions)

1. **Column scope**: build Sprint 3 Task 4.2.1's master-only column set (§2.2, option B), not
   the full `docs/product/08` §6.1 target shape. **Rationale**: D5 explicitly scopes this
   sprint down for the same reason this task's own instructions scope this slice down —
   Employee doesn't exist, so assignment/roster/flexible/split-shift fields have no consumer
   and no fully-specified validation behavior anywhere in the docs.
2. **`week_off_pattern_id`**: excluded entirely, not added as a passive/inert column (§2.4).
   **Rationale**: the target table doesn't exist; every prior slice in this series resolved
   an identical situation (Branch/`week_off_pattern_id`, Designation/`grade_id`) the same way.
3. **RBAC permission code**: `ORG.SHIFT.MANAGE`, not `ATTENDANCE.SHIFT_MANAGE` (§7).
   **Rationale**: matches this series' own precedent for resolving a Sprint-doc-vs-RBAC-matrix
   naming conflict (Legal Entity), and matches which module actually owns the table.
4. **`code` optionality**: optional, no uniqueness (§2.5, §2.6). **Rationale**: no document
   states either constraint for Shift, unlike Grade's pre-existing DB-level constraint;
   Branch/Department/Designation's own "no constraint documented, none invented" resolution
   is the closer precedent.
5. **Default shift seed (Task 4.2.2)**: not implemented this slice (§9.5). **Rationale**: no
   established codebase precedent for registration-time default-data seeding exists to reuse;
   introducing one is a new mechanism, which conflicts with this task's "reuse exact existing
   patterns" instruction more than it satisfies the Sprint doc's narrower ask.
6. **Cross-midnight and half-day/min-hours validation** (§6.2, §6.3): implemented as
   service-layer checks, structured identically to Grade's `min_ctc <= max_ctc` rule.
   **Rationale**: both are explicitly named, buildable rules in Task 4.2.1's own text — the
   same category of "genuinely documented, buildable business rule" Grade's own audit
   identified for the CTC-range check.

---

## 11. Explicit out-of-scope items

Per this task's instructions and this audit's findings, **not** part of this slice:
`week_off_pattern`/`week_off_pattern_id`, `shift_type`/flexible/split-shift fields and
validation, `shift_roster`/`shift_rotation_pattern` (shift assignment/rostering — explicitly
Sprint 7 per D5), the BR-14/FR-EMP-018 override-chain mechanism on Branch/Department/Grade/
Designation, default-shift registration seeding (Task 4.2.2), Employee, Employee Assignment,
Attendance (including all grace-period/late-marking/cross-midnight-day-attribution/OT
computation logic), Leave, Payroll, Recruitment, ESS, Performance, Workflow automation, and
any change to `Company.business_hours_start/end` (§3.2, left exactly as-is).
