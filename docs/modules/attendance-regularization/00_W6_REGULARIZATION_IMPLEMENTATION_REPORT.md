# W6 — Attendance Regularization Workflow: Implementation Report

**Date:** 2026-08-19
**Companion documents:** `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §13/§14,
decision log `docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md` **WD-28** (new entry
added by this slice).

---

## 1. Status

**W6 is implemented, tested, and live-verified end to end.** Backend (models, migration,
repository, service, router, permissions, exceptions), frontend (list, detail, create/review
dialogs, nav entry, attendance-day integration), and tests (24 new backend integration tests, 23
new frontend tests) are all in place and passing. A full manual browser walkthrough — submit →
approve → attendance recalculated — was performed against a real Postgres instance and is
documented in §18.

**W6 is production-ready for the scope actually specified in the task brief**, with the explicit
exclusions in §20 and the one pre-existing, out-of-scope production defect in §19.1 (not
introduced by this work, confirmed unfixed).

---

## 2. Audit Findings

Before writing any code, the existing W1–W5 codebase was read directly (not trusted from prior
reports): `WORKFORCE_ATTENDANCE_ARCHITECTURE.md` (full, all ~1860 lines), the decision log
(WD-01–WD-27), and the actual `attendance` module source — `models.py`, `service.py` (2880
lines), `repository.py`, `router.py`, `schemas.py`, `calculation.py`, `exceptions.py`,
`permissions.py`, `dependencies.py` — plus the `employee` and `organisation` modules' relevant
seams. Two focused background audits (service/repository/router conventions;
RBAC/audit/employee-linkage/frontend/migration conventions) cross-checked the exact call
signatures and patterns before any code was written.

Key findings that shaped the design:

- **No `AttendanceRegularization*` entity existed anywhere** (grep across `models.py` and every
  Alembic migration returned nothing) — W6 is greenfield for the workflow itself.
- **`RegularizationPolicy`/`RegularizationPolicyVersion`/`RegularizationPolicyAllowedType`
  already shipped in W3** with exactly the fields architecture §13.1 specifies
  (`allow_employee_request`/`allow_manager_request`/`allow_hr_request`, `max_backdated_days`,
  `max_requests_per_month`, `reason_required`, `attachment_required`, `approval_chain`,
  `auto_approve_within_minutes`, `blocked_when_locked`, and a typed `allowed_types` child table)
  — the policy really is the pre-built source of truth the task brief asked to defer to.
- **`AttendanceDay` already carries the hooks W6 needs**: `regularization_policy_version_id`,
  `is_regularized`, `is_pending_approval` all exist on the W4 model with no writer yet (dead
  columns waiting for this slice, exactly like `is_locked`/`locked_at` wait for W8).
- **`Punch.source` was already documented** (module docstring, `models.py`) as intended to accept
  `'REGULARIZATION'`/`'ADMIN'` for corrections, even though the DB `CHECK` constraint and the
  Pydantic enum tuple hadn't been widened yet — W3/W4's authors had already anticipated this
  slice's mechanism.
- **`ShiftRoster` (W5) already gives `WRONG_SHIFT` a ready-made application path**: a `PUBLISHED`
  roster row for an employee-date already outranks `EmployeeAssignment.shift_id` in the
  calculation engine's shift resolution — no new resolution step needed.
- **`AttendanceDayService.calculate()` (W4) is already the single recompute entrypoint**,
  get-or-create by `(employee_id, date)`, already refuses a locked day
  (`AttendanceDayLockedError`), already fully replaces derived fields (WD-10). Nothing about it
  needed to change.
- **The calculation engine (`calculation.py`) has zero regularization awareness** — its own
  module docstring says leave/regularization overlays are "no-op seams in W4." No `WFH`/`ON_DUTY`
  status branch is actually implemented in `evaluate_day` despite those values existing in the
  `attendance_status` enum. This directly shaped WD-28 decision 1/2 (see §6).
- **The flagged `POST /v1/auth/login` bug is real, and much larger in blast radius than
  documented** — see §19.1. Root-caused precisely via raw `psql`, reproduced live against a
  freshly restarted server process, and found to affect a large fraction of this repo's own
  pre-existing test helper infrastructure across modules unrelated to attendance.
- **`Employee.user_id` / JWT linkage remains intact** — `IdentityService._resolve_employee_id`
  → `EmployeeService.resolve_employee_id_for_user` → JWT `employee_id` claim →
  `AuthenticatedUser.employee_id` chain was traced end to end and used unmodified by every W6
  self-service code path (exactly like `PunchService.record_punch` already does).

No architectural contradiction was found. No W1–W5 code was redesigned. The one real,
close-call decision point — how a punch-driven calculation engine can honor `WRONG_STATUS`/
excess-break requests that don't reduce to a punch or shift correction — is resolved as an
explicit, documented **OPEN (PD-REG-1)** decision (WD-28), not invented.

---

## 3. Existing Contracts Reused

| Contract | Reused exactly as-is |
|---|---|
| `RegularizationPolicy` / `RegularizationPolicyVersion` / `RegularizationPolicyAllowedType` (W3) | Source of truth for allowed types, caps, windows, approval chain — read via `RegularizationPolicyRepository`, resolved via the existing `PolicyResolutionService.resolve(..., "REGULARIZATION_POLICY", ...)` (W3, unmodified) |
| `AttendanceDayService.calculate()` (W4) | The only recompute path an approved request ever calls |
| `PunchRepository.insert` (W4) | The only way a correction ever creates a punch — an ordinary immutable row, `source='REGULARIZATION'` |
| `ShiftRosterRepository.get_for_date` / `.insert` / `.update` (W5) | The only way a `WRONG_SHIFT` correction is applied — a `PUBLISHED` roster row, same mechanism W5 already built |
| `EmployeeService.resolve_visible_employee_ids` / `_ensure_employee_visible` / `_resolve_visible_employee_ids` (attendance `service.py` private helpers, W4) | Every DataScope check in W6, verbatim copy of the exact pattern fixed for `PUNCH_ON_BEHALF` in commit `fecb740` |
| `EmployeeAssignmentService.get_assignment_as_of` (Employee module) | Resolves `reporting_manager_id` as-of the attendance date for the `MANAGER` approval stage (PD-APR-1's stated default) |
| `AuditService.record` (core) | Every lifecycle transition, same call shape as every other attendance mutation |
| `require_permission` / `rbac.resolve_data_scope` (core RBAC) | Both the static-permission and the body-dependent (self vs. on-behalf) gating patterns, mirroring `create_punch` exactly |
| `DataEnvelope` / `ListEnvelope` / `ErrorEnvelope`, `If-Match` conditional-update convention | Unchanged, same shape as every other attendance endpoint |
| `hrms_app` RLS role, `company_id` + `FORCE ROW LEVEL SECURITY` + `tenant_isolation` policy | Applied to all three new tables, identical clause to every existing table |

**Nothing new was built that already existed.** No second policy-resolution mechanism, no second
audit system (beyond the append-only per-stage timeline justified in WD-28 decision 7), no new
DataScope levels, no generic workflow engine.

---

## 4. Database Changes

One new migration, `20260822090000_regularization_request.py`, `down_revision` chained onto W5's
`20260821090000_shift_roster`. Verified `upgrade → downgrade → upgrade` on a real Postgres 16
instance (§17).

Three new tables, each with `company_id` + `ENABLE`/`FORCE ROW LEVEL SECURITY` +
`tenant_isolation` policy identical to every other tenant table in this codebase:

- **`attendance_regularization_request`** — the request identity/state row. FKs to `company`,
  `employee`, nullable `attendance_day`, nullable `shift` (`requested_shift_id`),
  `regularization_policy_version` (snapshot), nullable `employee` again
  (`resolved_approver_manager_id`), and three nullable `user` FKs (submitted/reviewed/cancelled
  by). `CHECK` constraints on `status`, `approval_chain`, `approval_stage`, `request_type`. A
  partial unique index `(company_id, employee_id, attendance_date) WHERE status='SUBMITTED'`
  enforces "no duplicate active request" at the database level, not just in the service.
- **`attendance_regularization_requested_punch`** — typed child table, one row per requested
  IN/OUT instant (WD-12/WD-20: typed, not JSON). `CASCADE` on request deletion (there is no
  request-delete path today, but the FK is still correctly shaped).
- **`attendance_regularization_action`** — append-only per-stage timeline (architecture
  §13.2/§33.4 names `RegularizationAction` explicitly). `CHECK` on `action`/`stage`.

**Also in this migration**: widened the `punch_source_check` `CHECK` constraint to admit
`'REGULARIZATION'`, via `ALTER TABLE ... DROP/ADD CONSTRAINT` — the same "ALTER existing table in
place" posture DEC-021/WD-25 already established, not a new table. Reverted correctly on
downgrade.

**No W1–W5 migration was modified.**

---

## 5. Domain Model

```text
attendance_regularization_request
  id, company_id, employee_id, attendance_day_id (nullable), attendance_date
  request_type, reason, requested_shift_id (nullable), attachment_reference (nullable)
  status (SUBMITTED|APPROVED|REJECTED|CANCELLED)
  approval_chain (snapshotted at submit), approval_stage (MANAGER|HR|NULL)
  regularization_policy_version_id (snapshotted), resolved_approver_manager_id (snapshotted)
  submitted_by_user_id, submitted_at
  reviewed_by_user_id, reviewed_at, reviewer_comment, rejection_reason
  applied_at, cancelled_at, cancelled_by_user_id
  version (optimistic concurrency)

attendance_regularization_requested_punch
  id, company_id, request_id, direction (IN|OUT), requested_time, sort_order

attendance_regularization_action   (append-only)
  id, company_id, request_id, action, actor_user_id, actor_employee_id, stage, comment, created_at
```

`request_type` reuses the exact 8-value `_REGULARIZATION_TYPES` tuple W3 already defined in
`schemas.py` (`MISSING_PUNCH`, `WRONG_PUNCH`, `WRONG_SHIFT`, `WRONG_STATUS`, `WFH`, `ON_DUTY`,
`EXCESS_BREAK`, `FULL_DAY`) — never hardcoded a second list. What the *policy* actually allows
(`RegularizationPolicyAllowedType`) is looked up per request, not assumed.

The original request is **never mutated** after submission except through the typed lifecycle
transitions (approve/reject/cancel/apply) — `reason`, `requested_punches`,
`requested_shift_id` are set once at submit time and read-only thereafter.

---

## 6. Policy Behavior

Every field on `RegularizationPolicyVersion` is honored at submission:

| Field | Enforcement |
|---|---|
| `allowed_types` | Resolved version's allowed-type rows checked against `request_type`; empty or non-matching → `REGULARIZATION_TYPE_NOT_ALLOWED` (fail-closed, WD-21 — an *empty* configured set is never read as "allow everything") |
| `allow_employee_request` / `allow_manager_request` / `allow_hr_request` | Self-submit requires `allow_employee_request`; on-behalf requires `allow_manager_request OR allow_hr_request` (the policy model doesn't distinguish manager from HR submitters more finely than this) |
| `max_backdated_days` | `(today − attendance_date).days > max_backdated_days` → `REGULARIZATION_WINDOW_EXCEEDED` |
| `max_requests_per_month` | Counts non-cancelled requests submitted since the start of the current calendar month → `REGULARIZATION_REQUEST_LIMIT_EXCEEDED` |
| `reason_required` / `attachment_required` | Missing → `REGULARIZATION_REASON_REQUIRED` / `REGULARIZATION_ATTACHMENT_REQUIRED` |
| `approval_chain` | Drives the whole lifecycle — see §7 |
| `blocked_when_locked` | Combined with the target `AttendanceDay.is_locked` (if a day already exists) → `REGULARIZATION_BLOCKED_BY_LOCK` |
| No policy resolves at all | `REGULARIZATION_POLICY_NOT_RESOLVED` (WD-21 fail-closed — never silently permitted) |

**Known, documented gap**: `auto_approve_within_minutes` (a small-clock-error auto-approval
tolerance *orthogonal* to `approval_chain=AUTO`) is **not enforced**. Neither the architecture nor
the task brief specifies how it interacts with the four-chain state machine, and inventing that
interaction risked contradicting a future decision — left unenforced and recorded as a known
limitation (WD-28), not silently ignored.

---

## 7. Request Lifecycle

```text
SUBMITTED ──approve (final stage)──▶ APPROVED ──▶ (correction applied, same transaction)
    │
    ├──reject (any stage)──▶ REJECTED   (terminal, no correction applied)
    │
    └──cancel (submitter only)──▶ CANCELLED   (terminal, no correction applied)
```

No `DRAFT` state — architecture §13.2 lists `DRAFT` among possible statuses, but nothing in this
slice's requirements needs staging-before-submit (unlike `ShiftRoster`'s genuine
DRAFT→PUBLISHED gate on the calculation engine). Create always submits immediately. Recorded as
a deliberate, reasoned omission in WD-28, not a silent scope cut.

`MANAGER_THEN_HR` is the one non-trivial transition: a manager's approval does **not** set
`status=APPROVED` — it only moves `approval_stage` from `MANAGER` to `HR` and records a
`STAGE_APPROVED` action. Only the HR stage's approval is final. A rejection at *either* stage is
immediately terminal — there's no "manager rejects, forwards to HR for a second opinion" path,
matching the plain reading of "a rejected request cannot be treated as approved."

Every transition is guarded by `If-Match`/optimistic concurrency (§14). A stale write anywhere in
the lifecycle returns `409 STALE_RESOURCE` with the current server state attached, same shape as
every other stale-resource error in this codebase.

---

## 8. Approval Behavior

Implements architecture §14's four-chain model exactly, with WD-28's decision 4 recording the
one genuinely new implementation choice (an `approval_stage` field rather than a second status
enum) and decision 5 (self-approval is always blocked):

- **`AUTO`** — approved on submit, in the same call, by the submitting actor. No manual review
  step ever exists for this chain.
- **`HR`** — a single stage; any caller holding `ATTENDANCE.REGULARIZATION_APPROVE` at **COMPANY**
  scope (per §14: "any user with … `_APPROVE` at COMPANY").
- **`MANAGER`** — a single stage; the caller must literally *be* the snapshotted
  `resolved_approver_manager_id` (identity match, not merely holding the permission at some
  scope). Resolution failure (no manager as-of the attendance date) routes straight to `HR` and
  records an `APPROVER_UNRESOLVED` action — **never auto-approves on failure**, per §14's explicit
  instruction.
- **`MANAGER_THEN_HR`** — manager stage first (with the same resolution-failure→HR routing),
  then HR.

**Self-approval is unconditionally blocked** (`REGULARIZATION_SELF_APPROVAL_NOT_ALLOWED`, 403) —
including for a caller who happens to hold `ATTENDANCE.REGULARIZATION_APPROVE`. Neither the
architecture nor `RegularizationPolicyVersion` defines a field that would "explicitly permit"
self-approval, so the only policy-consistent reading is deny-by-default (WD-28 decision 5).

**PD-APR-1** (manager as-of the attendance date vs. current manager) was already an **explicitly
open** architecture decision with a **stated default** ("as-of the attendance date") — W6 ships
with that named default, snapshotting `resolved_approver_manager_id` at submit time via
`EmployeeAssignmentService.get_assignment_as_of(employee_id, attendance_date)`, and does not
silently guess a different answer.

---

## 9. Attendance Recalculation Behavior

**This is the part of the task brief that most needed a considered decision, and is fully
documented in decision log WD-28.**

An approved request is applied through **only the two mechanisms that already exist** — no new
calculation-engine logic anywhere:

1. **Punch-based correction** (`MISSING_PUNCH`, `WRONG_PUNCH`, `FULL_DAY`, and `WFH`/`ON_DUTY`
   when the request carries punch times): each `AttendanceRegularizationRequestedPunch` row
   becomes a new, ordinary, immutable `Punch` row (`source='REGULARIZATION'`,
   `reference='regularization:{id}'`). The original punches, if any, are **never** touched or
   deleted — corrections are always additive, matching WD-11's "punches immutable" invariant.
2. **Shift-based correction** (`WRONG_SHIFT`): upserts a `PUBLISHED` `ShiftRoster` row for the
   employee-date via the existing W5 repository — the calculation engine already reads roster
   ahead of the default assignment shift, so no new resolution step was needed.

Both paths, in either order, are followed by a single call to the existing
`AttendanceDayService.calculate()` — the same get-or-create, full-derived-field-replace pipeline
W4 already built. `AttendanceDay.is_regularized`/`is_pending_approval` are set by a small,
additional, narrowly-scoped repository method (`mark_regularized`/`set_pending_approval`)
**outside** `evaluate_day`'s pure calculation — `evaluate_day` still has zero knowledge that
regularization exists, exactly mirroring how `is_locked`/`locked_at` already sit unused on
`AttendanceDay` waiting for W8.

**Explicit, documented boundary (WD-28 decision 2 / OPEN PD-REG-1)**: every request — regardless
of `request_type` — must carry at least one requested punch or a `requested_shift_id` (enforced
by a Pydantic `model_validator` at submission, a real 422 before the service layer even runs). A
pure "reclassify this day without changing any punch or shift" correction (a `WRONG_STATUS`
request, or an `EXCESS_BREAK` request that only wants an already-punched excess break excused)
has no representation the current calculation engine can apply — it has no forced-status or
excused-break input. Building one would mean extending `calculation.py`'s core pipeline, which
the task brief explicitly asked not to do ("Do not create a second attendance calculation
engine," "do not redesign W1–W5 unless an actual blocking defect is discovered" — this is a real
gap, not a defect). The policy can still be configured to allow `WRONG_STATUS`/`EXCESS_BREAK`
as *request types* (the type taxonomy is policy-driven, per Phase 1), but such a request must
still supply a punch or shift correction to be submittable.

**Idempotent, race-safe apply**: the whole apply sequence (punch inserts, roster upsert,
`calculate()`, `mark_regularized`, `mark_applied`) runs inside the same database transaction that
already uniquely won the version-guarded `status='APPROVED'` write. If `calculate()` refuses a
locked day, the entire transaction — including the status transition — rolls back, so a request
is never left `APPROVED` without its correction having actually been applied.

---

## 10. Security / DataScope

Every DataScope requirement from Phase 4 was implemented and is covered by a dedicated test
(§15):

- **Submit** — `_ensure_employee_visible(employee_id, scope, caller_employee_id)` runs **first**,
  before any policy read, exactly mirroring the `fecb740` fix for `PUNCH_ON_BEHALF`: a caller
  holding *some* grant of `REGULARIZATION_REQUEST_ON_BEHALF` cannot use it to submit for an
  employee outside their resolved visible set — the router resolving a non-empty `DataScope`
  only proves *some* grant exists, not that this specific target is in scope.
- **List/Get** — `_resolve_visible_employee_ids`/the equivalent single-target check, same
  DEC-028 "cross-tenant/out-of-scope → 404, never 403" shape as every other attendance read.
- **Approve/Reject** — the `MANAGER` stage requires *identity* match against the snapshotted
  approver (stronger than any DataScope level could express); the `HR` stage requires literal
  COMPANY scope. Neither path needs (or duplicates) `_ensure_employee_visible`, since identity
  match is already the tighter constraint architecture §14 specifies.
- **Cancel** — restricted to the original submitter (`submitted_by_user_id` match), independent
  of DataScope, per the task brief's own "Employee: … Cancel eligible request" wording (no
  manager/HR cancel path specified).
- **Forged IDs** — a forged `employee_id` on submit, or a forged/cross-tenant request id on any
  read/action route, all resolve to `404`/`403` through the exact same seams every other
  attendance route already uses; nothing new was invented.

No new `DataScopeLevel` was added — `SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY` only.

---

## 11. Permissions

Three new codes (`attendance/permissions.py`, generically registered to `COMPANY_ADMIN` at
registration exactly like every other `ATTENDANCE_PERMISSIONS` entry — no per-code wiring
needed):

| Code | Typical scope | Purpose |
|---|---|---|
| `ATTENDANCE.REGULARIZATION_REQUEST` | SELF | Submit a request for one's own attendance |
| `ATTENDANCE.REGULARIZATION_REQUEST_ON_BEHALF` | COMPANY | Submit on behalf of another employee (mirrors `ATTENDANCE.PUNCH_ON_BEHALF` exactly) |
| `ATTENDANCE.REGULARIZATION_APPROVE` | REPORTEES/COMPANY (role-authored) | Approve/reject at any stage |

**Reads reuse the existing `ATTENDANCE.VIEW`** — no fourth code — mirroring WD-27 decision 4's
"roster viewing reuses `ATTENDANCE.VIEW`."

**Spelling note (WD-28 decision 6)**: architecture §23.2's table spells these
`ATTENDANCE.REGULARISE_APPROVE`/`REGULARISE_REQUEST` (British spelling) — the one inconsistent
instance in that document. This codebase's own `RegularizationPolicy`/`regularization_policy`
table already spells the word with a `z` throughout; W6 keeps that established spelling rather
than introducing the one differently-spelled code family. Recorded, not silently diverged.

---

## 12. API Endpoints

All under `/v1`, following the exact envelope/If-Match/`?as_of=`-free conventions already
established:

```text
POST   /regularizations                       create + submit (self or on-behalf via body.employee_id)
GET    /regularizations                        list, DataScope-filtered, filters: employee_id/date_from/date_to/request_status/request_type
GET    /regularizations/{id}                    detail
POST   /regularizations/{id}/cancel             submitter only, requires If-Match
POST   /regularizations/{id}/approve            requires If-Match, body: {reviewer_comment}
POST   /regularizations/{id}/reject             requires If-Match, body: {reviewer_comment, rejection_reason}
```

Path chosen (`/regularizations`) matches architecture §25's own named endpoint list verbatim
("`/regularizations` POST/GET/approve/reject") — not an invented namespace.

`create_regularization_request`'s self-vs-on-behalf permission gating mirrors `create_punch`
exactly (direct `rbac.resolve_data_scope()` call, not a static `Depends(require_permission(...))`
— the gating code depends on the request body). `cancel`'s gating accepts either submission
permission (self or on-behalf), since the service's `submitted_by_user_id` check is the actual
authorization gate.

---

## 13. Frontend Screens

`apps/web/src/app/app/regularizations/page.tsx` — list + filters (date range, status, type,
employee) with a **My requests / Team requests** toggle over the same permission-scoped
`GET /regularizations` read, mirroring the Attendance dashboard's own posture. "New request"
opens `RegularizationRequestDialog`.

`apps/web/src/app/app/regularizations/[id]/page.tsx` — detail: request fields, requested
correction (punch table or shift), review fields, and the full action timeline (mapped from
`AttendanceRegularizationAction` rows to human labels). Approve/Reject/Cancel buttons are gated
by the same client-side permission/state checks the backend independently enforces (backend
remains authoritative — a 403/409 from the API is still handled, not assumed away).

`apps/web/src/components/regularization/regularization-request-dialog.tsx` — create form. Every
`request_type` in the policy's reusable universe is offered (the frontend cannot read
`allowed_types` without `ATTENDANCE.POLICY_MANAGE`, so it doesn't guess — server 422s surface
policy-driven rejections as field errors, same pattern `RosterEntryDialog` already uses for
`shift_id`). Supports a `mode: "SELF" | "ON_BEHALF"` prop: `SELF` never shows an employee field;
`ON_BEHALF` shows either a locked field (pre-scoped, e.g. opened from an attendance day) or an
editable employee picker (opened from the unfiltered "Team requests" list) — **this picker was
added after live UI testing (§18) surfaced its absence as a real gap**, not designed up front.

`apps/web/src/components/regularization/regularization-review-dialog.tsx` — approve/reject
dialog, surfaces the backend's `REGULARIZATION_SELF_APPROVAL_NOT_ALLOWED`/
`REGULARIZATION_APPROVER_MISMATCH`/stale-version errors as specific messages rather than a
generic failure.

`apps/web/src/components/regularization/regularization-status-badge.tsx` — status badge,
mirrors `AttendanceStatusBadge`.

**Attendance day detail page** (`apps/web/src/app/app/attendance/[id]/page.tsx`) now has a
"Regularize" action (gated by `ATTENDANCE.REGULARIZATION_REQUEST_ON_BEHALF`) that opens the same
create dialog pre-filled with that day's `employee_id`/`attendance_date` — the requested
"attendance day → raise a regularization" integration point.

**Nav**: `Regularizations` entry added to `nav-items.ts` (unfiltered static list, matching this
codebase's existing "items the role/build can't access yet are absent, not disabled" convention
— gating happens per-action inside the page, not at the nav level).

---

## 14. Audit Events

`AuditService.record` is called once per state transition, `entity_type=
"attendance_regularization_request"` (plus `"punch"`/`"shift_roster"` entries for the
correction side-effects, reusing those entities' own existing action names for consistency with
their own audit trails):

`REGULARIZATION_SUBMITTED`, `REGULARIZATION_STAGE_APPROVED` (the `MANAGER_THEN_HR`
intermediate step — beyond the task's stated minimum, since it's a real, distinct state
transition), `REGULARIZATION_APPROVED`, `REGULARIZATION_REJECTED`, `REGULARIZATION_CANCELLED`,
`REGULARIZATION_APPLIED`, plus `PUNCH_CREATED`/`SHIFT_ROSTER_CREATED`/`SHIFT_ROSTER_UPDATED` for
the applied correction itself.

**In addition** — not instead of — the append-only `AttendanceRegularizationAction` table
(§5/WD-28 decision 7) gives the frontend timeline a request-scoped read model it can query
directly without `audit_log` read permission, and is the only place a `MANAGER_THEN_HR` chain's
two distinct reviewer/timestamp pairs can both be recorded (the parent row's single
`reviewed_by_user_id`/`reviewed_at` would otherwise be overwritten by the second stage). This is
not a second audit system — it's the entity architecture §13.2/§33.4 already names.

---

## 15. Concurrency Behavior

Every mutating endpoint requires `If-Match: <version>`; the repository's conditional
`UPDATE ... WHERE version = :expected_version` pattern (identical to every other attendance
mutation) is the sole source of truth for "did this write actually win." A losing write gets
`404` (row now missing) or `409 STALE_RESOURCE` (row present, version mismatched, current state
attached) — never silently ignored, never double-applied.

Verified explicitly by test (`test_stale_if_match_on_approve_rejected`,
`test_simultaneous_approve_and_reject_only_one_wins`): two competing terminal transitions
(`approve` and `reject`) against the same `expected_version` — exactly one succeeds (`200`), the
other fails (`409`), and the final persisted state matches whichever one actually won — never a
mixed or double-applied result.

`mark_applied`'s final follow-up write is deliberately **not** version-guarded — by the point it
runs, the version-guarded write that set `status='APPROVED'` has already uniquely succeeded, so
no other transition can legally race that specific column.

---

## 16. Tests

**Backend** — `apps/api/tests/integration/modules/attendance/test_regularization.py`, **24
tests, all passing** against a real Postgres 16 instance (real RLS, real `hrms_app` role, real
HTTP through the ASGI app):

- Creation & validation (7): happy path with `resolved_approver_manager_id` resolution, disallowed
  type, missing policy (fail-closed), backdating window, monthly limit, duplicate active request,
  missing correction payload, reason-required.
- DataScope/security (3): on-behalf without the on-behalf permission (403), forged employee id
  outside REPORTEES scope (404), cross-tenant request access (404).
- Lifecycle (9): manager-approval-applies-correction-and-recomputes (full assertion of resulting
  `AttendanceDay`/punches), reject-leaves-attendance-unchanged + replay-after-reject blocked,
  cancel-own-pending + non-submitter-cannot-cancel, self-approval-blocked, wrong-manager-cannot-
  approve, `MANAGER_THEN_HR` two-stage chain (including "manager can't also clear the HR stage"),
  `AUTO`-chain immediate approval, no-manager-resolved routes to HR (`APPROVER_UNRESOLVED`
  audited), `WRONG_SHIFT` applies via roster (asserts the actual `ShiftRoster` row), locked-day
  blocks new request.
- Concurrency (2): stale If-Match rejected, simultaneous approve/reject race resolved to exactly
  one winner.

Also ran the **full pre-existing attendance module suite** (`test_regularization.py` +
`test_shift_roster.py` + `test_attendance_day.py` + `test_attendance_security.py` +
`test_overtime_regularization_policy.py` + unit tests) together: **114 passed**, plus the 2
pre-existing failures documented in §19.1 (confirmed identical whether or not W6 code is
present), plus teardown-only `ERROR`s from the pre-existing test-infrastructure cascade also
documented in §19.

**Frontend** — 23 new tests, **all passing**, full suite **303/303**:

- `lib/regularization/validate-regularization.test.ts` (9): required-field validation,
  punch-or-shift requirement, payload building (punches vs. shift, on-behalf `employee_id`
  inclusion, reason trimming).
- `app/app/regularizations/page.test.tsx` (6): loading/empty/error/permission-denied states,
  rendering loaded rows, opening the create dialog, switching My/Team views.
- `app/app/regularizations/[id]/page.test.tsx` (8): loading/not-found states, rendering fields,
  self-approval and terminal-state button suppression (client-side UX, backend remains
  authoritative), full approve flow with toast + payload assertion, backend self-approval error
  surfaced, cancel-button visibility gated to the original submitter.

**mypy**: `success: no issues found in 11 source files` (attendance module). **ruff**: all
checks passed on every `.py` file touched (migration SQL-string line lengths follow the same
pre-existing pattern already present in committed W3 migrations). **import-linter**: contract
kept (0 broken). **tsc --noEmit**: exit 0. **`next build`**: compiles successfully, both new
routes (`/app/regularizations`, `/app/regularizations/[id]`) present in the route manifest.

---

## 17. Migration Verification

`20260822090000_regularization_request.py` verified on a real Postgres 16 instance:

```text
upgrade 20260821090000 -> 20260822090000   OK
downgrade 20260822090000 -> 20260821090000  OK  (punch_source_check correctly reverted, all three new tables dropped)
upgrade 20260821090000 -> 20260822090000   OK  (re-applied cleanly)
```

Also ran **every** migration from an empty database (`DROP DATABASE`/`CREATE DATABASE`, extension
and `hrms_app` role bootstrap re-applied, `alembic upgrade head`) to confirm the whole chain,
including this new revision, applies cleanly end to end with zero pre-existing data — this is
also how the "clean baseline" backend test run in §16/§19 was obtained.

---

## 18. Live Verification

Both servers were started for real (`uvicorn entrypoints.api:app`, `next dev`) against the real
Postgres/Redis dev stack, and driven with a headless-Chromium Playwright script (`chromium-cli`
was unavailable in this environment; the skill's documented fallback — a Playwright REPL driver —
was used instead), **not** just the test suite:

1. Registered a real company via the live API, built the full org/employee/shift/calendar/
   attendance-policy/regularization-policy graph via real HTTP calls (same shape as the test
   helpers, but through the running server, not `TestClient`).
2. Logged a real browser session in (session injection was used only because the *login endpoint
   itself* hit the pre-existing, out-of-scope §19.1 bug reproducibly during this exact
   verification — see that section for the live reproduction detail; every other screen was
   driven as an ordinary authenticated user from that point on).
3. `/app/regularizations` list page: loading → empty state → "New request" (found via live
   testing that the dialog needed an employee picker for the unfiltered on-behalf case — fixed
   immediately, see §13, then re-verified).
4. Submitted a real `MISSING_PUNCH` request through the actual form (date picker, request-type
   select, correction-kind select, time inputs, reason, attachment reference) — real 201,
   real toast.
5. Opened the created request's detail page — all fields rendered correctly, including the
   not-yet-calculated attendance-day state.
6. Approved it through the real review dialog — real `200`, toast, status transitioned to
   `Approved`, "View attendance day" link appeared (attendance-day backfill confirmed working).
7. Confirmed via direct API calls against the same running server: the request's `actions` array
   was exactly `["SUBMITTED", "APPROVED", "APPLIED"]`; the resulting `AttendanceDay` had
   `attendance_status="PRESENT"`, `worked_minutes=540`, `is_regularized=true`,
   `is_pending_approval=false` — the full correction → recompute pipeline verified live, not
   just through `TestClient`.

Zero browser console errors at any point in the flow. Screenshots were captured at each step.

**Bug found and fixed during this live pass** (not caught by unit/integration tests, because
they never exercised the "no employee pre-selected" on-behalf path): the create dialog had no
employee field at all when opened from the unfiltered "Team requests" view, making on-behalf
submission silently impossible from that entry point. Fixed by adding a `mode: "SELF" |
"ON_BEHALF"` prop and an employee picker (matching `RosterEntryDialog`'s established pattern),
re-verified live, and a corresponding frontend test gap was not left unaddressed — the existing
page test suite continues to pass 303/303 with the new prop wired through.

**Second issue found and fixed during this live pass**: the punch-time inputs' UTC conversion
(`toUtcIso`) treated the entered clock time as a literal UTC instant (`new Date(...:00Z)`),
inconsistent with the existing `PunchEntryDialog`'s convention of treating a `datetime-local`
input as **browser-local** time and converting via `.toISOString()`. Fixed to match the
established convention; the corresponding unit test was made timezone-agnostic rather than
hardcoding a UTC-literal expectation.

---

## 19. Known Limitations

### 19.1 Pre-existing production bug: `current_setting('app.company_id', true)` reverts to `''`, not `NULL`

**Confirmed real, root-caused precisely, and reproduced live** — and **substantially larger in
scope than the task brief's description** ("`POST /v1/auth/login` can return HTTP 500 on a fresh
server process").

**Root cause** (proven directly via raw `psql`, not inferred): on a single pooled Postgres
connection, once `SELECT set_config('app.company_id', '<uuid>', true)` (`SET LOCAL` semantics)
has been called inside any transaction and that transaction ends, `current_setting('app.company_id',
true)` on that **same connection**, in any **later** transaction that never re-sets it, returns
an **empty string** — never reverts to true `NULL`. This is documented, deterministic PostgreSQL
behavior for undeclared custom GUCs, not application flakiness:

```sql
BEGIN; SELECT set_config('app.company_id', '<uuid>', true); COMMIT;
BEGIN; SELECT current_setting('app.company_id', true);  -- returns '' here, not NULL
```

Every RLS policy in this codebase's tenant tables uses
`company_id = current_setting('app.company_id', true)::uuid`. Casting `''::uuid` raises
`InvalidTextRepresentationError: invalid input syntax for type uuid: ""` — a hard `500`, not a
graceful RLS denial.

**Blast radius, confirmed live**: any request whose session **skips** setting RLS —
`get_session()` only calls `set_rls_company_id` when `current_tenant_company_id()` is truthy,
which is false for every public/unauthenticated route (`/v1/auth/login`,
`/v1/companies/register`) — crashes with this exact 500 once it lands on a connection pool
member that any *earlier* authenticated request already touched. Reproduced live against a
freshly restarted server process: `POST /v1/companies/register` (first request on the process)
succeeded; a **second** `/v1/companies/register`/`/v1/auth/login` call moments later, on the same
process, failed with exactly this error. In a real deployment, once the pool has served even one
authenticated request, this becomes the **steady-state** behavior for every subsequent
unauthenticated request that reuses that connection — not a rare edge case.

**The same defect independently breaks a large fraction of this repo's own pre-existing test
infrastructure**, unrelated to attendance/regularization: `_create_permission_scoped_user`
(`test_attendance_security.py`) and its sibling in `test_employee_assignment.py` both use a raw
`get_session_factory()` session without setting RLS, and both crash identically once any earlier
authenticated call in the same test has touched the pool — confirmed by running the
already-committed `test_attendance_security.py` in isolation (11 of 13 tests failed) *before this
session made any code changes*, and again after a full `DROP DATABASE`/recreate (byte-identical
failure count, ruling out stale data as the cause — this is deterministic given test execution
order, not flaky). Tellingly, `test_registration_flow.py::_cleanup` **already** carries an
explicit code comment describing this exact bug and works around it with
`set_rls_company_id(session, ...)` before its own raw cleanup query — proof the original authors
already knew about this defect class; the workaround simply wasn't applied everywhere it needed
to be.

**What this session did about it**, per the task's own explicit instruction ("fix it only if the
fix is small, isolated, and clearly unrelated to W6; otherwise leave it untouched and report it
separately"):

- **Did not touch it in production code.** The correct fix — `NULLIF(current_setting(...), '')::uuid`
  in every `tenant_isolation` policy — spans the RLS clause duplicated across ~15+ pre-existing
  migration files, none of them attendance/regularization migrations. That is neither small nor
  isolated by the task's own stated bar, so it was left alone.
- **Did** apply the identical, already-established, one-line, test-only workaround
  (`set_rls_company_id(session, str(company_id))` before the raw query) to
  `_create_permission_scoped_user` in `test_attendance_security.py` specifically — the one
  pre-existing helper this slice's own new security tests depend on — since without it, this
  session could not have obtained a trustworthy pass/fail signal for its own DataScope tests at
  all. This is test-infrastructure-only, mirrors a pattern the codebase's own authors already
  established elsewhere in the same file family, and changes no production code path.
- W6's own new `attendance_regularization_request`/`_requested_punch`/`_action` tables use the
  exact same (vulnerable) RLS clause as every other table in this codebase, by design — WD-28
  notes this explicitly and says to use the corrected clause once/if the production fix lands,
  rather than have the new tables diverge from the established pattern unilaterally.

**Employee.user_id / JWT linkage was separately verified intact** (§2) and is unaffected by this
defect — it only manifests for sessions that skip RLS setup entirely, not for the
employee-linkage resolution path itself.

### 19.2 `WRONG_STATUS`/pure excess-break corrections cannot be mechanically applied

See §9 and decision log **OPEN PD-REG-1**. Every request needs a punch or shift correction to be
submittable; a true non-punch status/break override needs a calculation-engine extension this
slice deliberately did not build.

### 19.3 `auto_approve_within_minutes` is not enforced

See §6. A documented gap, not a silent one.

### 19.4 `AttendanceLock`/`AttendanceAdjustment` do not exist yet

`AttendanceDay.is_locked` is checked (both at submit time and via `AttendanceDayService.calculate()`'s
own existing guard at apply time) and never bypassed, but the period-lock entity itself (`W8`) and
the HR-direct-override-while-locked `APPROVED_PENDING_ARREARS` path (which needs
`AttendanceAdjustment`, a distinct entity from `AttendanceRegularizationRequest` per WD-18) are
out of this slice's stated scope. A regularization against a locked day is simply rejected.

### 19.5 Demo data left in the dev database

Live verification (§18) created three demo companies (`Acme UI Demo`, `Acme UI Demo 2`, `Acme UI
Demo 3`) in the shared dev Postgres instance. Not cleaned up (a cleanup script attempt hit an
unrelated import-path issue and was not chased further given time budget) — harmless test-scoped
data (RLS-isolated per company), but flagged for whoever next resets that database.

---

## 20. Explicitly Excluded Work

Per the task brief's own scope boundary, none of the following were touched:

- **`AttendanceAdjustment`** (HR/manager direct correction without a request, `ATTENDANCE.OVERRIDE`) — a
  distinct entity per WD-18, architecturally part of the same "corrections" family but not asked
  for by this task's 18 phases (which are entirely request-and-approve shaped).
- W7 Overtime approval/workflow, W8 Attendance locks/period closing, W9 Leave, W10
  Device/biometric integration, W11 rotation, W12 production hardening, Payroll, Salary
  structure, any generic workflow engine.
- The production RLS bug fix (§19.1) — reported, root-caused, not fixed, per the task's own
  smallness criterion.

---

## 21. Unresolved Architecture/Product Decisions

Recorded formally as **decision log WD-28** (`docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md`),
following this codebase's own established practice (WD-24 through WD-27) of writing down every
implementation choice not already covered by an existing decision, rather than silently deciding
in code. Summary:

| ID | Decision | Status |
|---|---|---|
| WD-28 decision 1 | Correction applied only via existing punch/roster mechanisms, never a new calc-engine branch | LOCKED |
| WD-28 decision 2 | Every request needs a punch-or-shift payload | LOCKED |
| WD-28 decision 3 | `is_regularized`/`is_pending_approval` set outside `evaluate_day` | LOCKED |
| WD-28 decision 4 | `approval_stage` field, not a second status enum, for `MANAGER_THEN_HR` | LOCKED |
| WD-28 decision 5 | Self-approval always blocked | LOCKED |
| WD-28 decision 6 | Permission-code spelling follows codebase convention over architecture §23.2's one inconsistent instance | LOCKED |
| WD-28 decision 7 | `AttendanceRegularizationAction` is a real child table, not derived from `audit_log` | LOCKED |
| WD-28 decision 8 | `AttendanceLock`/`AttendanceAdjustment` out of scope; locked-day requests simply rejected | LOCKED |
| **PD-REG-1 (new, OPEN)** | Whether `WRONG_STATUS`/excess-break-without-punch-change should ever be representable without a calc-engine extension | Not guessed — default recorded: unsupported until scoped |

`PD-APR-1` (manager as-of vs. current) was already open with a stated default in the architecture
document; W6 ships with that default, does not re-decide it.

---

## 22. Recommended Next Step

**W7 (Overtime detection + approval + caps + comp-off facts) can safely begin.** W6 does not
touch, block, or leave in an inconsistent state anything W7 would depend on — `OvertimePolicy`/
`OvertimePolicyVersion` (W3) and the OT-detection fields already on `AttendanceDay` (W4) are
untouched by this slice.

Before W7 or any later slice, two things are worth flagging to the team (not blocking, but real):

1. **§19.1's RLS bug** is a genuine production defect, already reproducing on a fresh server
   process, that will affect real users hitting `/v1/auth/login` after the server has served any
   authenticated traffic. It is out of W6's scope to fix, but it is not attendance-specific and
   should be triaged as its own ticket — the fix (`NULLIF(current_setting(...), '')::uuid` in
   every `tenant_isolation` policy) is well-understood and mechanical, just wide (~15+ files).
2. **PD-REG-1** (§21) is a real product question, not an engineering one: does any launch
   customer need to regularize a day *without* changing a punch or shift (e.g., "excuse this
   excess break," "mark this WFH day present with no corrected times")? If yes, that needs a
   calculation-engine extension (a WFH/on-duty/excused-break overlay) scoped as its own slice —
   not invented here.

---

### Test counts (exact)

- Backend: **24/24** new (`test_regularization.py`), **114 passed** across the full attendance
  module suite run together (new + pre-existing), 2 pre-existing failures unrelated to W6
  (§19.1), teardown-only errors from a separately-diagnosed, pre-existing, unrelated test-infra
  cascade (also not a W6 regression — confirmed identical on a from-scratch database).
- Frontend: **23/23** new, **303/303** full suite.
- mypy: 0 issues (11 attendance source files). ruff: 0 issues. import-linter: 1 contract kept, 0
  broken. tsc: 0 errors. `next build`: succeeds.
- Migration: upgrade/downgrade/upgrade verified; full from-scratch chain verified.
- Live verification: full submit→approve→recompute cycle confirmed against a real running
  server, real Postgres, real browser, zero console errors, two real UI bugs found and fixed
  during the pass.
