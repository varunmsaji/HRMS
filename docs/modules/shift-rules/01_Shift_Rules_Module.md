# Shift Rules Module

Status: **Implemented** — the Sprint 3 Feature 4.2 / Task 4.2.1 master-only scope (Decision
D5), not the full `docs/product/08_Database_Architecture.md` §6.1 target shape. This document
covers purpose, scope, data model, business rules, lifecycle, audit, tenant isolation,
permissions, relationships, and known limitations — mirroring the shape of
`docs/modules/grade/01_Grade_Module.md`, the closest structural precedent. The full endpoint
reference lives in the sibling `02_Shift_Rules_API.md`. The pre-implementation audit — the
source of truth for every scope decision below — is `00_SHIFT_RULES_AUDIT.md`.

## 1. Purpose

A **Shift** is a reusable master definition of a work schedule: start/end time, paid/unpaid
break allowances, in/out grace minutes, half-day/full-day hour thresholds, and three
descriptive flags (night shift, crosses-midnight, OT-eligible). It is company-wide master
data — not employee-specific, not an assignment, not a roster entry. A future
Employee-Assignment/Attendance module will reference a `shift_id` to determine an individual
employee's schedule and to compute attendance/lateness/OT outcomes; this slice ships only the
definition those future modules will consume.

## 2. Scope

**Built this slice** (Sprint 3 Task 4.2.1's column set — audit §2.2, option B):

- Full CRUD (create, list, get, update) + soft deactivate/reactivate on `/v1/shifts`
- Every field in §3 below
- Two service-layer validation rules: cross-midnight time-ordering, half-day/full-day hour
  ordering (§4)
- Optimistic concurrency (`version` + `If-Match`)
- Audit logging (`SHIFT_CREATED`/`SHIFT_UPDATED`/`SHIFT_DEACTIVATED`/`SHIFT_REACTIVATED`)
- Tenant isolation (RLS + belt-and-suspenders `company_id` filtering)
- Frontend list/detail pages, create/edit forms, deactivate/reactivate UI, stale-version
  handling, nav entry

**Not built this slice** (audit §6.7, §9, §11 — explicitly deferred, not silently dropped):

- `shift_type` (FIXED/FLEXIBLE/SPLIT/ROTATIONAL) and any flexible/split-shift fields
  (`flexible_core_start/end`, `flexible_window_start/end`, `second_block_start/end`)
- `week_off_pattern_id` — the target table (`week_off_pattern`) was never built by any prior
  slice
- `total_hours`, `break_windows` (JSONB), `max_hours_per_day`, `ot_starts_after_minutes`
- `shift_roster` / `shift_rotation_pattern` (assignment/rostering — explicitly Sprint 7)
- The BR-14/FR-EMP-018 override chain (`default_shift_id` on Branch/Department/Grade/
  Designation)
- Any Attendance-side consumption logic (grace-period math, late-marking, cross-midnight day
  attribution, OT computation, weekly-off/holiday resolution)
- A default "General Shift" seed at company registration (Task 4.2.2)
- Uniqueness constraint on `code` or `name`
- Query-param filtering on `GET /shifts`
- Employee, Employee Assignment, Attendance, Leave, Payroll, or any other module

## 3. Data model

**Aggregate boundary**: `Shift` is its own standalone aggregate, referencing only
`company_id` — no FK to Legal Entity, Branch, Department, Designation, or Grade, and none of
those resources gain a `shift_id`/`default_shift_id` column this slice (audit §3.1).

**Entity — `Shift`** (`organisation/models.py::Shift`, table `shift`)

| Field | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | no | — | PK |
| `company_id` | UUID | no | — | FK → `company.id`, indexed |
| `name` | string(100) | no | — | Required |
| `code` | string(30) | yes | — | Optional; **no uniqueness constraint** (§6.5 below) |
| `start_time` | TIME | no | — | Required, `"HH:MM"` on the wire |
| `end_time` | TIME | no | — | Required, `"HH:MM"` on the wire |
| `break_minutes_paid` | integer | no | `0` | `>= 0` |
| `break_minutes_unpaid` | integer | no | `0` | `>= 0` |
| `grace_in_minutes` | integer | no | `0` | `>= 0` |
| `grace_out_minutes` | integer | no | `0` | `>= 0` |
| `half_day_threshold_hours` | numeric(4,2) | yes | — | `>= 0`; see §4.2 |
| `min_hours_full_day` | numeric(4,2) | yes | — | `>= 0`; see §4.2 |
| `is_night_shift` | boolean | no | `false` | Descriptive flag only — no behavior attached |
| `is_cross_midnight` | boolean | no | `false` | Gates the time-ordering rule (§4.1) |
| `is_ot_eligible` | boolean | no | `false` | Stored flag only — no OT computation exists in this codebase |
| `is_active` | boolean | no | `true` | Lifecycle flag (§6) |
| `deleted_at` | timestamptz | yes | — | Reserved, unused — deactivation is not deletion |
| `version` | integer | no | `1` | Optimistic concurrency (§7) |
| `created_at` / `updated_at` | timestamptz | no | — | `TimestampMixin` |

`week_off_pattern_id` is intentionally absent — see §9.1.

## 4. Business rules

### 4.1 Cross-midnight time-ordering

`end_time <= start_time` is rejected (`422 INVALID_SHIFT_TIME_RANGE`) **unless**
`is_cross_midnight` is `true`. When `is_cross_midnight=true`, `end_time <= start_time` is the
expected shape of an overnight shift and is accepted; `end_time > start_time` while
`is_cross_midnight=true` is also accepted — no document forbids a same-day shift from also
carrying the flag, so this slice does not invent a rejection for that combination.

Implemented as a service-layer check (`_validate_shift_time_range`), structured identically
to Grade's `min_ctc <= max_ctc` rule. Re-validated on update against the *effective* range
(patch value where present, otherwise the existing stored value) — so a `PATCH` that only
changes `end_time` is still checked against the shift's current `start_time`/
`is_cross_midnight`, and vice versa.

### 4.2 Half-day threshold vs. minimum full-day hours

When both `half_day_threshold_hours` and `min_hours_full_day` are present, `
half_day_threshold_hours >= min_hours_full_day` is rejected (`422
INVALID_SHIFT_HOURS_RANGE`). Not enforced when either value is absent (both fields are
nullable). Re-validated on update against the effective range, same posture as §4.1.

### 4.3 Company ownership

Identical mechanism to every other organisation-module resource — `company_id` filtering,
belt-and-suspenders in the repository, RLS as backstop (§8).

### 4.4 No deactivation-blocking rule

FR-ORG-014's literal text blocks deactivation of an org unit "only if no active employee is
assigned" — Employee doesn't exist, so this can't be checked. No document names any other
resource as a blocker on Shift deactivation. **This slice ships Shift deactivation/
reactivation with no dependency-blocking check** — a Shift can be deactivated at any time
regardless of any future consumer.

### 4.5 Optimistic concurrency

`version` + `If-Match`, identical mechanism to every other organisation-module resource — see
§7.

### 4.6 Soft deactivation only

`DELETE` never hard-deletes; it flips `is_active` to `false` via the exact same
`update_shift` code path as `PATCH {is_active: false}` (the router's `deactivate_shift`
handler is a thin wrapper; the service's `deactivate_shift` method constructs a
`ShiftUpdate(is_active=False)` and delegates to `update_shift`).

### 4.7 No invented rules

The following are **not** implemented, per §2's deferred list: `shift_type` and any split/
flexible-shift validation, OT computation (`is_ot_eligible` is a stored flag only), weekly-off
resolution, holiday interaction, roster/assignment of any kind, the BR-14 override-chain
mechanism, and any Attendance-side consumption logic.

## 5. Time/shift semantics

- **Wire format**: `start_time`/`end_time` are `"HH:MM"` strings on the wire (pattern
  `^\d{2}:\d{2}$`), matching `Company.business_hours_*`'s own `BusinessHoursSchema`
  convention. They are parsed to/from Python's `datetime.time` at the schema boundary via the
  same `_parse_time`/`_format_time` helper shape already established for
  `Company.business_hours_start/end` (independently re-implemented in `service.py` for the
  service-layer validation checks — see the code review notes in
  `03_Shift_Rules_Implementation_Report.md`).
- **Cross-midnight behavior**: modeled purely as a boolean flag (`is_cross_midnight`) plus the
  §4.1 validation rule. There is no day-attribution logic — determining which calendar day an
  overnight shift's worked hours count against is explicitly an Attendance-module concern
  (FR-ATT-005), out of scope here.
- **Break configuration**: two independent integer fields, `break_minutes_paid` and
  `break_minutes_unpaid`, both defaulting to `0`. No `break_windows` (JSONB, start/end times
  per break) — that is the full-target-shape (`08_Database_Architecture.md` §6.1) field, not
  built this slice.
- **Grace configuration**: `grace_in_minutes`/`grace_out_minutes`, both integers defaulting to
  `0`. Stored only — no late-marking or grace-period math is implemented anywhere in this
  codebase; that logic belongs to the future Attendance module, which will read these two
  fields.
- **Full-day/half-day configuration**: `half_day_threshold_hours`/`min_hours_full_day`, both
  optional `numeric(4,2)`, validated against each other per §4.2. Stored only — no
  attendance-day classification logic consumes them yet.
- **OT eligibility**: `is_ot_eligible` is a boolean flag with no attached computation.
  Overtime calculation logic does not exist anywhere in this codebase.
- **Night-shift behavior**: `is_night_shift` is a purely descriptive boolean flag. It has no
  validation rule attached (unlike `is_cross_midnight`) and no computed behavior — a shift can
  be marked `is_night_shift=true` with any `start_time`/`end_time` combination.

## 6. Active/inactive lifecycle

- Created rows are always `is_active=true` — the client cannot set `is_active` on `POST`
  (`ShiftCreate` has no `is_active` field at all; sending one is rejected by
  `extra="forbid"`).
- `is_active` is toggled two ways, both requiring `If-Match`:
  - `DELETE /v1/shifts/{id}` — always deactivates (sets `is_active=false`)
  - `PATCH /v1/shifts/{id}` with `{"is_active": true}` or `{"is_active": false}` in the body
    — this is also how **reactivation** happens (there is no separate "reactivate" endpoint)
- No dependency-blocking check exists (§4.4) — a Shift can be freely deactivated and
  reactivated any number of times.
- `deleted_at` exists on the model but is never written by this slice — deactivation is
  represented entirely by `is_active`, not by soft-delete timestamping.

## 7. Optimistic locking

Identical mechanism to every other organisation-module resource: every mutating request
(`PATCH`, `DELETE`) requires an `If-Match: <version>` header. The repository's `update_shift`
issues `UPDATE ... WHERE id = :id AND company_id = :company_id AND version = :expected_version
AND deleted_at IS NULL RETURNING *`; a `NULL` result (row exists but version didn't match, or
row doesn't exist/belongs to another tenant) is disambiguated in the service layer: a
follow-up `get_shift` determines whether to raise `404 NOT_FOUND` or `409 STALE_RESOURCE`
(the latter includes the current row under `error.details[0].context.current` so the client
can offer "reload latest"). Every successful update increments `version` by exactly `1`.

## 8. Audit behavior

Uses the existing `AuditService`. Four events, mirroring Grade's:

- `SHIFT_CREATED`
- `SHIFT_UPDATED`
- `SHIFT_DEACTIVATED`
- `SHIFT_REACTIVATED`

Each with `before`/`after` snapshots of the `ShiftRead` DTO (`entity_type = "shift"`), IP
address, and user agent captured from the request. No `RESTRICTED`-classified fields —
timing/break/grace configuration is organisational policy data, not personal or compensation
data. On create, only `after` is recorded (no `before`, since the row didn't exist).

## 9. Tenant/RLS behavior

Identical mechanism to every other organisation-module resource:

- `TenancyMiddleware` + `get_tenant_context` resolve `company_id` from the request
  (`X-Company-Id` header + JWT) before any handler runs.
- Every repository method filters by `company_id` explicitly (belt-and-suspenders), not
  relying on RLS alone.
- RLS is enabled and forced at the database level (`ALTER TABLE shift ENABLE/FORCE ROW LEVEL
  SECURITY`), with a `tenant_isolation` policy comparing `company_id` against
  `current_setting('app.company_id', true)::uuid`. Asserted directly in the migration (new
  table, not an idempotent re-assertion).
- Cross-tenant access — including a guessed `shift_id` belonging to another company — returns
  `404`, never `403`, and never leaks row existence.

## 10. Permission

Single permission, matching the Company/Legal Entity/Branch/Department/Designation/Grade
precedent:

```
ORG.SHIFT.MANAGE
```

**Resolution of a documented naming conflict** (audit §7): `docs/product/
19_RBAC_and_Permission_Matrix.md:56-58` places shift management under
`ATTENDANCE.SHIFT_MANAGE`, while `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:1416` defines
and uses `ORG.SHIFT.MANAGE`. This slice uses `ORG.SHIFT.MANAGE`, following the same precedent
this series already established for the Legal Entity naming conflict: the Sprint doc is the
more recent, module-scoped, implementation-precise source, and it matches which module
actually owns the table (`organisation`, not a not-yet-built `attendance` module).
`ATTENDANCE.SHIFT_MANAGE` remains reserved, unused terminology for a possible future
shift-*assignment* permission — a different capability from managing the shift master.

Granted to the `COMPANY_ADMIN` system role at company registration time, via the same
`get_or_create_permission` → `insert_role_permission` pattern used for every prior
organisation-module permission.

## 11. Relationships

**Shift is a standalone aggregate** — no FK to any other organisation-module entity, and no
other entity references it yet. Two relationships are named in product docs but explicitly
not built this slice:

- **BR-14/FR-EMP-018 override chain** — "shift default" is named alongside notice
  period/probation/leave entitlement as overridable Company → Branch → Department → Grade →
  Employee. Grade's own slice implemented the notice-period/probation legs but not the shift
  leg; no `shift_id`/`default_shift_id` column exists on Branch/Department/Designation/Grade.
  Not added by this slice (audit §3.1) — doing so would mean editing four already-shipped,
  unrelated modules with no buildable spec for the override mechanism itself.
- **`employee_assignment.shift_id`** — documented in `08_Database_Architecture.md` as the
  future FK that will reference this table once Employee Assignment exists. This slice
  creates the `shift` table as a one-directional, forward-compatible target; no code in this
  slice references `employee_assignment` (which doesn't exist).

`Company.business_hours_start`/`business_hours_end` (pre-existing, informal TIME fields on
Company) coexist unmodified — Company's own docs describe Shift as the "real, richer
scheduling primitive" that may override `business_hours_*`, but this slice makes no code
change to `Company`.

## 12. Future Employee/Attendance integration

Fields a future Attendance slice will need to consume, so its own audit has a ready list
(audit §3.4):

- `grace_in_minutes` / `grace_out_minutes` — late-marking thresholds
- `is_cross_midnight` — cross-midnight day attribution (FR-ATT-005)
- `is_ot_eligible` — OT eligibility gating (computation itself is not implemented anywhere)
- `half_day_threshold_hours` / `min_hours_full_day` — attendance-day full/half classification

A future Employee Assignment slice will add `employee_assignment.shift_id` referencing this
table's `id`. No roster, rotation-pattern, or weekly-off resolution exists yet.

## 13. Known limitations

1. **No `week_off_pattern_id`** — `week_off_pattern` itself was never built by any prior
   slice (deferred by Branch's own Task 3.1.3, never picked up since). A future slice adds
   this FK once `week_off_pattern` exists.
2. **No `shift_type`/flexible/split-shift support** — only the fixed-shift shape ships this
   slice, per Sprint 3's own Decision D5 scope-down.
3. **No BR-14/FR-EMP-018 override-chain mechanism** — no `default_shift_id` column on any
   other organisation-module resource.
4. **No Attendance-side consumption** — grace-period math, late-marking, cross-midnight day
   attribution, OT computation, and weekly-off/holiday status resolution are all future
   Attendance-module concerns.
5. **No default "General Shift" seed on registration** (Task 4.2.2) — no prior
   organisation-module slice established a registration-time default-row-seeding precedent to
   reuse.
6. **No query-param filtering** on `GET /shifts` — consistent with every prior
   organisation-module list endpoint.
7. **No uniqueness constraint** on `shift.code` or `shift.name` — no document specifies one,
   and unlike Grade, there was no pre-existing DB constraint to preserve. Two shifts in the
   same company can share the same `code` or `name`.
8. **No deactivation-blocking rule** — a Shift can be deactivated even if a future consumer
   (once Employee Assignment exists) references it.

## 14. Explicitly deferred functionality

Per the audit's own out-of-scope list (§11), **not** part of this slice: `week_off_pattern`/
`week_off_pattern_id`, `shift_type`/flexible/split-shift fields and validation,
`shift_roster`/`shift_rotation_pattern` (explicitly Sprint 7), the BR-14/FR-EMP-018
override-chain mechanism on Branch/Department/Grade/Designation, default-shift registration
seeding (Task 4.2.2), Employee, Employee Assignment, Attendance (including all
grace-period/late-marking/cross-midnight-day-attribution/OT computation logic), Leave,
Payroll, Recruitment, ESS, Performance, Workflow automation, and any change to
`Company.business_hours_start/end`.
