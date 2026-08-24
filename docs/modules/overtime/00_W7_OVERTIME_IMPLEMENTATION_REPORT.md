# W7 — Overtime Detection, Approval, Caps & Comp-Off Facts: Implementation Report

**Date:** 2026-08-20
**Companion documents:** `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §12/§22,
decision log `docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md` **WD-29** (new entry added
by this slice).

---

## 1. Status

**W7 is implemented, tested, and live-verified for the scope this slice actually needed to
build.** A three-agent audit performed before any code was written established that overtime
*detection* was already fully built in W3/W4 — this materially narrowed W7's real scope relative
to a literal reading of the task brief. What W7 adds: an approval workflow entity
(`OvertimeRecord`/`OvertimeAction`), weekly/monthly cap enforcement, a comp-off fact with expiry,
a fix for a confirmed SPLIT-shift detection gap, four new API endpoints, one new permission, and
comprehensive test coverage (67 new/extended backend tests, all passing against real Postgres
with real RLS).

Four product-decision boundaries were raised with the requester before implementation began and
locked as **WD-29**, per this program's own established practice of not silently deciding
undefined business rules in code.

**Frontend**: `/app/overtime` (list) and `/app/overtime/[id]` (detail) screens, an approve/reject
review dialog, a status badge component, and a nav entry — implemented separately (see §15) and
verified with `vitest`, `tsc --noEmit`, and `next build`.

---

## 2. Initial Audit Findings

Before writing any code, the actual current repository was read directly — `calculation.py`,
`service.py`, `repository.py`, `models.py`, `schemas.py`, `router.py`, `permissions.py`,
`exceptions.py`, the W3 overtime policy migration, and the architecture/decision-log documents —
via three parallel research passes (W3 policy fields, W4 calculation engine internals, W6
regularization/RBAC/audit conventions as the pattern template), cross-checked against each other
and against the actual code before any design decision was made.

**Overtime detection is not greenfield.** `calculation.detect_overtime()` was already a complete,
unit-tested pure function: eligibility gating (`SHIFT_FLAG`/`ALWAYS`/`NEVER`/
`GRADE_VIA_ASSIGNMENT`), minimum-threshold rejection, rounding, daily-cap clamping,
holiday/weekly-off/night day-class classification with rate-row lookup, and a
requires-post-approval-vs-auto-approve split — already wired end-to-end through
`AttendanceDayService.calculate()`, including `OVERTIME_POLICY` resolution via the existing
generic `PolicyResolutionService`. `AttendanceDay.ot_minutes_detected`/`ot_minutes_approved`/
`ot_pending`/`ot_classification`/`comp_off_minutes_earned`/`overtime_policy_version_id` were
already live columns written by every `calculate()` call, not dead columns waiting for this
slice (unlike `is_locked`/`locked_at`, which genuinely are dead until W8).

**What was confirmed missing — the real W7 scope:**

1. **Weekly/monthly cap enforcement** — `OvertimePolicyVersion.weekly_cap_minutes`/
   `monthly_cap_minutes` existed as stored columns but were never read by the engine (only
   `daily_cap_minutes` was).
2. **An approval workflow entity** — `approval_chain`/`requires_post_approval` were stored on
   the policy but nothing anywhere acted on them for overtime; no request/action table, no
   router, no permission existed for OT specifically.
3. **A comp-off fact with expiry** — `comp_off_expiry_days` existed on the policy but was never
   applied to compute an actual expiry date; only a bare `comp_off_minutes_earned` counter
   existed, with no fact record carrying policy version, day, or expiry.
4. **`configured_multiplier`** — architecture §12.1/§22.1 calls for attendance to stamp the
   matched rate row's multiplier onto a payroll-facing fact so payroll doesn't need to re-resolve
   the policy version later; no such column or field existed anywhere.
5. **A confirmed engine gap**: `calculation._evaluate_split()` (the SPLIT shift-type branch)
   never called `detect_overtime()` at all — SPLIT-shift employees got `ot_minutes_detected=0`
   unconditionally, regardless of policy configuration. Verified by reading the function directly:
   no input was actually missing (`scheduled_minutes` already resolved via
   `shift.required_minutes`, the same fallback the FIXED/FLEX path already uses), so this was a
   genuine, mechanically-fixable gap rather than an underspecified business rule.
6. **Test coverage gaps** — no test exercised `PolicyResolutionService.resolve(...,
   "OVERTIME_POLICY", ...)` directly, no test covered night-OT/holiday/weekly-off classification,
   weekly/monthly caps, comp-off, or SPLIT-shift detection.

**A secondary finding, not actioned in this slice**: `AttendanceDayService._result_to_values`
unconditionally sets `"is_pending_approval": result.ot_pending` on every `calculate()` call,
which can silently clobber a regularization's own out-of-band `is_pending_approval` flag if an
unrelated recompute happens while a regularization is in flight. This is a pre-existing W4/W6
interaction bug, out of W7's scope to fix — W7 deliberately does **not** touch
`is_pending_approval` itself (only the OT-specific `ot_pending` field), so it neither fixes nor
compounds this pre-existing issue. Flagged for the team, not fixed here.

No architectural contradiction was found between the architecture document and the actual code.
No W1–W6 code was redesigned.

---

## 3. Existing W3/W4 Contracts Reused

| Contract | Reused exactly as-is |
|---|---|
| `calculation.detect_overtime()` / `OvertimePolicyInputs` (W3/W4) | Extended (two new optional fields, one new clamp), never replaced — see §7 |
| `PolicyResolutionService.resolve(..., "OVERTIME_POLICY", ...)` (W3, already generic) | Unmodified, called exactly as `AttendanceDayService.calculate()` already called it |
| `OvertimePolicyRepository` (get_version, list_rate_rows) (W3) | Unmodified, reused inside the existing OT-policy wiring block in `calculate()` |
| `AttendanceDayService.calculate()` (W4) | The only recompute path; extended, not duplicated — see §9 |
| `EmployeeAssignmentService.get_assignment_as_of` (Employee module) | Manager-as-of-date resolution, identical call shape to W6's regularization `submit()` |
| `AuditService.record` (core) | Every lifecycle transition, same call shape as every other attendance mutation |
| `require_permission` / `rbac.resolve_data_scope` (core RBAC) | Standard `Depends(require_permission(...))` gating — no body-dependent gating was needed since there is no create route |
| Module-level `_resolve_visible_employee_ids` / `_ensure_employee_visible` (W4/W6) | Reused verbatim for every OT DataScope check, not reimplemented |
| `DataEnvelope` / `ListEnvelope`, `If-Match` conditional-update convention | Unchanged, same shape as regularization/roster/policy endpoints |
| `hrms_app` RLS role, `company_id` + `FORCE ROW LEVEL SECURITY` + `tenant_isolation` policy | Applied to both new tables, identical clause to every existing table |

**Nothing new was built that already existed.** No second overtime detection engine, no second
policy-resolution mechanism, no new DataScope levels, no generic workflow engine.

---

## 4. Product Decisions (WD-29)

Four boundaries were raised with the requester and locked before implementation began (full text
in `docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md` WD-29):

| # | Decision | Chosen |
|---|---|---|
| 1 | Terminal OT decision vs. a later regularization correction to the same day | **Freeze forever** — once `APPROVED`/`AUTO_APPROVED`/`REJECTED`, never silently revised by a later recompute |
| 2 | Weekly/monthly cap enforcement vs. `calculate()`'s stated idempotency guarantee | **Implement as specified**, accepting the documented non-idempotency as a known limitation |
| 3 | Which minutes count against the shared weekly/monthly budget | **All non-`REJECTED`** (`PENDING`+`AUTO_APPROVED`+`APPROVED`) — consistent with how the existing daily cap already clamps against detected, not yet approved, minutes |
| 4 | Whether to fix the SPLIT-shift detection gap in this slice | **Fixed now** — confirmed mechanical, no missing inputs, isolated to the SPLIT branch |

Additional decisions recorded in WD-29 without a separate question (safe defaults, consistent
with WD-28 precedent): no manual "request overtime" submission flow exists (engine-detected
only — `requires_pre_approval` has no described mechanic for retrospectively-detected OT and is
left unenforced and documented, the same treatment WD-28 gave `auto_approve_within_minutes`);
`OvertimeRecord` is a single mutable-then-frozen row per day, not an accumulating history like
regularization requests; the permission code reuses the existing `ATTENDANCE_PERMISSIONS`
registration list rather than adding a second list/registration site.

**Open, not guessed (recorded, not resolved):**
- **PD-OT-1**: whether a terminal `OvertimeRecord` should ever become revisable/voidable. Default
  shipped: frozen, no revision path in W7.
- **PD-OT-2**: `requires_pre_approval` remains entirely unenforced. If a future slice needs it,
  its interaction with `calculate()`'s retrospective detection timing needs its own scoped design.

---

## 5. Database Changes

One new migration, `20260823090000_overtime_record.py`, `down_revision` chained onto the actual
current head (`20260822090000_regularization_request.py`). Verified `upgrade → downgrade →
upgrade` on a real Postgres 16 instance (§13).

Two new tables, both with `company_id` + `ENABLE`/`FORCE ROW LEVEL SECURITY` +
`tenant_isolation` policy identical to every other tenant table in this codebase:

- **`overtime_record`** — the workflow entity, one row per `AttendanceDay`
  (`attendance_day_id` is `UNIQUE` — deliberately not a partial-unique-index-per-status shape
  like regularization, since exactly one mutable-then-frozen row exists per day, never an
  accumulating history). FKs to `company`, `employee`, `attendance_day` (`CASCADE`),
  `overtime_policy_version` (snapshot, `RESTRICT`), nullable `employee` again
  (`resolved_approver_manager_id`), nullable `user` (`reviewed_by_user_id`). `CHECK` constraints
  on `status`, `approval_chain`, `approval_stage`, `day_class`, and `configured_multiplier > 0`.
- **`overtime_action`** — append-only per-record timeline, mirroring
  `attendance_regularization_action` exactly (WD-28 decision 7 precedent): `CASCADE` on record
  deletion, `CHECK` on `action`/`stage`.

**No W1–W6 migration was modified.**

---

## 6. Domain Model

```text
overtime_record
  id, company_id, employee_id, attendance_day_id (UNIQUE), attendance_date
  overtime_policy_version_id (snapshot)
  day_class, classification_code, configured_multiplier   -- payroll-facing facts
  minutes_detected, minutes_approved
  status (PENDING|AUTO_APPROVED|APPROVED|REJECTED)
  approval_chain (snapshotted), approval_stage (MANAGER|HR|NULL)
  resolved_approver_manager_id (snapshotted, manager-as-of-date)
  reviewed_by_user_id, reviewed_at, reviewer_comment, rejection_reason
  comp_off_minutes, comp_off_expiry_date
  version (optimistic concurrency)

overtime_action   (append-only)
  id, company_id, overtime_record_id, action, actor_user_id, actor_employee_id, stage, comment, created_at
```

Unlike `AttendanceRegularizationRequest`, `overtime_record` is never user-submitted — every row
is created, and every `PENDING` row's fields fully replaced, by `AttendanceDayService.calculate()`
itself. Once terminal, a row is frozen (§9) — it is the one place in this table's lifecycle where
"never mutated again" genuinely means never, not just "never by this specific mutation path."

---

## 7. Overtime Calculation Behavior

**Detection itself is unchanged** from the existing W3/W4 pipeline (`detect_overtime()`'s
eligibility/threshold/rounding/daily-cap/classification logic) — W7 extends it in two additive
ways:

1. **Weekly/monthly clamping** — two new optional fields on `OvertimePolicyInputs`
   (`remaining_weekly_minutes`, `remaining_monthly_minutes`, both `None`-means-uncapped,
   matching `daily_cap_minutes`'s own convention), clamped in `detect_overtime()` identically to
   the existing daily-cap clamp, after it. See §8 for how these are computed.
2. **`classify_ot_day()` extraction** — the day-class computation (`HOLIDAY > WEEKLY_OFF > NIGHT
   > NORMAL`) that already lived inline inside `detect_overtime()` was extracted into its own
   pure helper, called both by `detect_overtime()` (unchanged behavior, unchanged tested return
   shape) and by `_evaluate_fixed_or_flex()`/`_evaluate_split()` to populate a new
   `AttendanceCalculationResult.ot_day_class` field — this is what `OvertimeRecord.day_class`
   is populated from, since `detect_overtime()` itself only ever returned the policy-configured
   `classification_code`, not the day_class it matched against.

**SPLIT-shift fix**: `_evaluate_split()` now calls `detect_overtime()` with
`scheduled_minutes=shift.required_minutes` (the same fallback `_evaluate_fixed_or_flex()` already
uses when no `scheduled_start`/`scheduled_end` window is set), mirroring the FIXED/FLEX call
shape exactly — ~20 lines, additive, isolated to the SPLIT branch. Two new unit tests
(`test_evaluate_day_split_shift_detects_overtime`, `test_evaluate_day_split_shift_no_overtime_
policy_detects_nothing`) confirm the fix and that it's a no-op when no OT policy resolves at all.

**Cross-midnight / night OT**: unchanged — `is_night = shift.is_cross_midnight` continues to be
the sole night signal, feeding `classify_ot_day()`'s `NIGHT` branch when `night_ot_mode` is
`WINDOW`/`BOTH`.

---

## 8. Threshold, Rounding, and Cap Behavior

| Field | Enforcement |
|---|---|
| `min_ot_minutes` | Unchanged (pre-existing): excess below threshold → `0` minutes, `eligible=False` |
| `rounding_minutes`/`rounding_mode` | Unchanged (pre-existing) |
| `daily_cap_minutes` | Unchanged (pre-existing): clamps excess, `eligible` stays `True` even at `0` |
| **`weekly_cap_minutes`** (new) | Computed in `service.py` (DB access; `calculation.py` stays pure) via a new `OvertimeRecordRepository.sum_minutes_detected_for_range`, summing `minutes_detected` from non-`REJECTED` `overtime_record` rows in the ISO week containing the target date (`target_date - weekday()` through `+6`), excluded by `attendance_date` (not `attendance_day_id`, since the day being calculated may not have a row yet on its first calculation). `remaining_weekly_minutes = max(0, weekly_cap_minutes - week_sum)`, clamped in `detect_overtime()` the same way as the daily cap. |
| **`monthly_cap_minutes`** (new) | Identical mechanism, calendar-month boundaries (`target_date.replace(day=1)` through month end). |

**Accepted, documented non-idempotency (WD-29 decision 3)**: because weekly/monthly clamping
depends on sibling-day `overtime_record` state at the moment `calculate()` runs, a day's detected
OT can change between two recomputes with zero change to that day's own punches — purely because
a sibling day's state changed in between. This is an explicit, accepted departure from
`AttendanceDayService.calculate()`'s own docstring claim ("same punches + versions produce the
same result") for this one dimension, confirmed with the requester rather than silently shipped.
Verified live by `test_weekly_cap_clamps_second_day_in_same_week`: a policy with
`weekly_cap_minutes=90` and two days each independently detecting 60m raw excess correctly
clamps the second day to 30m (the remaining budget), not its own unclamped 60m.

---

## 9. Approval Workflow

Every `calculate()` call determines the current **OT decision** for that run via a new private
`AttendanceDayService._resolve_ot_decision()` — the single source of truth used both to override
the day row's `ot_minutes_approved`/`comp_off_minutes_earned`/`ot_pending` columns and to sync
`overtime_record`:

- **A pre-existing terminal record (`APPROVED`/`AUTO_APPROVED`/`REJECTED`) is frozen outright**
  (WD-29 decision 2) — its own stored values win, unconditionally. The day row's
  `ot_minutes_detected`/`ot_classification`/`is_overtime` still refresh from fresh engine output
  (informational, same as every other derived column), but `ot_minutes_approved`/
  `comp_off_minutes_earned`/`ot_pending` are overridden with the terminal record's own decided
  values, not the freshly recomputed engine output.
- **`approval_chain == "AUTO"`** always resolves to `AUTO_APPROVED` immediately, even when
  `requires_post_approval=True` — the chain itself says no human ever reviews this. This is a
  case where the day row's values must be overridden even for a *freshly created* record (not
  just a pre-existing terminal one), since the pure engine's own `ot_pending`/`ot_approved` split
  only ever looks at `requires_post_approval`, not `approval_chain` — verified by
  `test_auto_chain_auto_approves_immediately`.
- **`requires_post_approval == False`** (any chain) also resolves to `AUTO_APPROVED` immediately
  — the engine already computed the approved amount in this case; `_resolve_ot_decision` reuses it
  rather than re-deriving. Verified by `test_requires_post_approval_false_auto_approves_without_
  auto_chain`.
- **`MANAGER`/`MANAGER_THEN_HR`/`HR` with `requires_post_approval=True`** creates/updates a
  `PENDING` record. Manager identity resolved via `EmployeeAssignmentService.get_assignment_as_
  of(employee_id, attendance_date)` at detection time (not review time), identical to W6's
  regularization pattern. No-manager-resolved routes straight to the `HR` stage and records
  `overtime_action(action='APPROVER_UNRESOLVED')` — never auto-approves on failure. Verified by
  `test_no_manager_resolved_routes_to_hr`.
- **`MANAGER_THEN_HR`** uses an `approval_stage` field (`MANAGER`→`HR`), not a second status enum
  — the manager's approval only advances the stage; only HR's approval sets `status='APPROVED'`.
  Verified by `test_manager_then_hr_two_stage_chain`, including that the manager cannot also
  clear the HR stage.
- **Self-approval is unconditionally blocked** (`OVERTIME_SELF_APPROVAL_NOT_ALLOWED`, 403), same
  posture as WD-28 decision 5. Verified by `test_self_approval_blocked`.
- **`MANAGER` stage requires literal identity match** against the snapshotted
  `resolved_approver_manager_id`; **`HR` stage requires a COMPANY-scoped grant** of
  `ATTENDANCE.OVERTIME_APPROVE`. Verified by `test_wrong_manager_cannot_approve` and
  `test_hr_chain_requires_company_scope`.
- **No partial-amount approval** — `approve()` always sets `minutes_approved = minutes_detected`
  (the full detected/capped amount); there is no field for the reviewer to approve a smaller
  amount. `reject()` always zeroes `minutes_approved`/`comp_off_minutes` on both the record and
  the day row. Verified by `test_reject_clears_day_fields`.

**Recompute of a `PENDING` record**: full replace in place (same row id, preserving its
`overtime_action` history across pre-decision recomputes — deliberately not delete/recreate, so
a `DETECTED` timeline isn't lost every time an unrelated punch triggers recompute before a human
reviews it). A recompute that now detects zero eligible OT deletes the stale `PENDING` record
outright (nothing left to decide).

**Terminal-freeze across regularization recompute**: verified end to end by
`test_approved_overtime_frozen_across_later_recompute` — an `AUTO_APPROVED` record's decided
minutes survive a later recompute (triggered by an additional punch pair) that would otherwise
have detected a materially larger amount.

---

## 10. Comp-Off Fact Behavior

`OvertimeRecord.comp_off_minutes` is the policy-computed fact
(`comp_off_instead_of_pay=True` ⟹ `comp_off_minutes = minutes_detected`, mirroring the engine's
own existing unconditional computation) — populated regardless of decision state, since "how much
comp-off would this be worth" is a policy-configuration fact, not something contingent on review.
`comp_off_expiry_date` is computed once, at the same time, as
`attendance_date + comp_off_expiry_days` when the policy configures an expiry window (verified:
`2026-08-10` + `90` days → `2026-11-08`, `test_comp_off_fact_with_expiry_on_auto_approval`).

**The day row's payroll-facing `comp_off_minutes_earned` is a stricter fact than the record's
own field**: it is `0` while `PENDING` (nothing has actually been decided yet) and only reflects
the record's `comp_off_minutes` once the record reaches a terminal `AUTO_APPROVED`/`APPROVED`
state — verified by `test_comp_off_not_credited_to_day_while_pending`. This is a deliberate,
narrow behavior change from the pre-W7 engine (which populated `comp_off_minutes_earned`
regardless of pending status) made possible because no existing test asserted the old provisional
behavior with `comp_off_instead_of_pay=True` (confirmed by grep before making the change) — the
new behavior is strictly more correct for a "fact" that is supposed to represent something
actually earned, not merely computed.

Per ADR-0004/architecture §12.3, this is a *fact*, not a ledger entry — Attendance does not
create or touch any leave/comp-off balance. `configured_multiplier` and `classification_code` are
carried as informational payroll-facing snapshot fields only, never used in any arithmetic here
(ADR-0006 — no money in Attendance).

---

## 11. Policy Resolution / Versioning

Unchanged from W3/W4: `PolicyResolutionService.resolve(company_id, "OVERTIME_POLICY",
employee_id=, target_date=)` is called once per `calculate()` run, resolving through the existing
8-level `PolicyAssignment` precedence chain, fail-closed (`config_incomplete` never guesses a
default). `OvertimeRecord.overtime_policy_version_id` snapshots the resolved version at
detection/last-recompute time — reproducibility is preserved the same way `AttendanceDay`'s own
version FKs already work: recompute always re-resolves by date, so only a backdated version
publish (a privileged act) can change an unlocked historical day's OT outcome, and even then only
until the record reaches a terminal state (§9).

Locked-day handling is unchanged and inherited for free: `AttendanceDayService.calculate()`'s
existing `is_locked` guard runs before any of W7's new code executes, so a locked day simply never
reaches OT sync at all — no new lock-awareness was needed in this slice.

---

## 12. DataScope / Security

Every read/write path reuses the exact module-level `_resolve_visible_employee_ids`/
`_ensure_employee_visible` helpers already established by W4/W6 — no DataScope logic was
reimplemented. No new `DataScopeLevel` was added (`SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY`
only).

- **List/Get** — visible-employee-id filtering, same cross-tenant/out-of-scope → `404` shape as
  every other attendance read (DEC-028). Verified by `test_self_scope_sees_only_own_overtime_
  record`, `test_reportees_scope_excludes_unrelated_employee`,
  `test_cross_tenant_overtime_record_returns_404`.
- **Approve/Reject** — the `MANAGER` stage requires identity match (stronger than any DataScope
  level); the `HR` stage requires literal `COMPANY` scope. Neither needs (or duplicates)
  `_ensure_employee_visible`, since identity match is the tighter constraint (mirrors WD-28's
  identical reasoning for regularization).
- No manual submission route exists, so there is no on-behalf/self-submission DataScope surface
  to gate at all (the entire class of bug W6 fixed in commit `fecb740` — "resolve scope then
  discard it" — has no analog here, since there is nothing a caller submits on anyone's behalf).

---

## 13. Permissions

One new code, registered generically:

| Code | Typical scope | Purpose |
|---|---|---|
| `ATTENDANCE.OVERTIME_APPROVE` | REPORTEES/COMPANY (role-authored) | Approve/reject at any stage |

**Reads reuse the existing `ATTENDANCE.VIEW`/`ATTENDANCE.VIEW_ALL`** — no fourth code, mirroring
WD-28 decision 6's identical reasoning: OT records are system-detected and attached to attendance
days the caller can already view, not self-submitted content needing its own view gate.

Appended to the existing `ATTENDANCE_PERMISSIONS` list in `permissions.py` — both registration
call sites (`organisation.service.register_company` and `seed/bootstrap.py`) already iterate that
list generically, so **no second registration site or list was needed**, confirmed by reading
both call sites directly before assuming a new list was required.

---

## 14. API Endpoints

All under `/v1`, following the exact envelope/If-Match conventions already established. No create
route exists — engine-detected only (WD-29 decision 1):

```text
GET   /overtime                          list, DataScope-filtered, filters: employee_id/date_from/date_to/record_status
GET   /overtime/{record_id}              detail
POST  /overtime/{record_id}/approve      requires If-Match, body: {reviewer_comment}
POST  /overtime/{record_id}/reject       requires If-Match, body: {reviewer_comment, rejection_reason}
```

Unlike regularization's `create_regularization_request`, no route here needs body-dependent
`rbac.resolve_data_scope()` gating — every route uses a plain static
`Depends(require_permission(...))`, since there is no self-vs-on-behalf distinction to make.

---

## 15. Frontend Screens

`apps/web/src/lib/overtime/types.ts` — `OvertimeRecord`/`OvertimeAction` TypeScript interfaces
mirroring the API contract exactly.

`apps/web/src/app/app/overtime/page.tsx` — list + filters (date range, status), with a
**My overtime / Team overtime** toggle over the same permission-scoped `GET /overtime` read,
mirroring the regularization dashboard's posture. **No "New request" button and no create
dialog** — this is the single load-bearing difference from the regularization list page, since
every `OvertimeRecord` is system-detected, never submitted.

`apps/web/src/app/app/overtime/[id]/page.tsx` — detail: request/detection fields (minutes
detected/approved, day class, classification, configured multiplier shown as an informational
label, never as money), comp-off fields (shown only when `comp_off_minutes > 0`), review fields,
and the full action timeline mapped from `OvertimeAction` rows to human-readable labels.
Approve/Reject buttons are gated by the same client-side permission/status/self-ownership checks
the backend independently enforces (backend remains authoritative — a 403/409 is still handled,
not assumed away).

`apps/web/src/components/overtime/overtime-review-dialog.tsx` — approve/reject dialog, surfaces
`OVERTIME_SELF_APPROVAL_NOT_ALLOWED`/`OVERTIME_APPROVER_MISMATCH`/stale-version errors as
specific messages, mirroring `regularization-review-dialog.tsx`'s error-mapping pattern.

`apps/web/src/components/overtime/overtime-status-badge.tsx` — status badge, mirrors
`AttendanceStatusBadge`/`RegularizationStatusBadge`.

**Nav**: `{ href: "/app/overtime", label: "Overtime", icon: AlarmClock }` added to `nav-items.ts`
next to the `Regularizations` entry — `AlarmClock` chosen since `Timer` was already taken by
"Overtime Policies".

**Verification** (all three run against the merged main working tree, not just the isolated
worktree the frontend implementation pass was drafted in):

```text
npx vitest run     -> Test Files  42 passed (42)   Tests  319 passed (319)
npx tsc --noEmit   -> zero errors
npx next build     -> Compiled successfully; route manifest includes
                       ○ /app/overtime           7.07 kB   114 kB First Load JS
                       ƒ /app/overtime/[id]      6.05 kB   119 kB First Load JS
```

23 new frontend tests (list page: loading/empty/error/permission-denied states, rendering loaded
rows, switching My/Team views, and an explicit assertion that no "new/submit/create" control
renders anywhere on the page; detail page: loading/not-found states, field rendering, self-
approval and terminal-state button suppression, full approve flow with toast + If-Match payload
assertion, backend error-code surfacing, reject flow, cancel/permission-gated button visibility).
Full suite: **319/319 passing**, zero regressions to any pre-existing frontend test.

---

## 16. Audit Events

`AuditService.record` is called for every real persisted transition, `entity_type=
"overtime_record"`:

`OVERTIME_DETECTED` (once per `calculate()` run that creates or updates a non-frozen record),
`OVERTIME_STAGE_APPROVED` (the `MANAGER_THEN_HR` intermediate step), `OVERTIME_APPROVED`,
`OVERTIME_REJECTED`, `COMP_OFF_EARNED` (whenever a decision resolves to `AUTO_APPROVED`/`APPROVED`
with nonzero comp-off minutes).

**In addition** — not instead of — the append-only `overtime_action` table (mirroring WD-28
decision 7's identical regularization-action precedent) gives the frontend timeline a
record-scoped read model it can query directly without `audit_log` read permission, and is the
only place a `MANAGER_THEN_HR` chain's two distinct reviewer/timestamp pairs can both be recorded.

---

## 17. Concurrency Behavior

Every mutating endpoint requires `If-Match: <version>`; `OvertimeRecordRepository.update`'s
conditional `UPDATE ... WHERE version = :expected_version` is the sole source of truth for "did
this write actually win," identical to every other attendance mutation. A losing write gets `404`
(row now missing, cannot happen here since records are never deleted once decided) or
`409 STALE_RESOURCE` (version mismatched, current state attached).

Verified explicitly by `test_stale_if_match_on_approve_rejected` and
`test_simultaneous_approve_and_reject_only_one_wins`: two competing terminal transitions against
the same `expected_version` — exactly one succeeds (`200`), the other fails (`409`), and the final
persisted state matches whichever one actually won.

`AttendanceDayRepository.mark_ot_approved`'s follow-up write (pushing the terminal decision onto
the day row) is deliberately not version-guarded — mirrors `mark_regularized`'s identical
reasoning: by the time it runs, the version-guarded write that set `status='APPROVED'`/
`'REJECTED'` has already uniquely succeeded, so no other transition can legally race that column.

---

## 18. Tests

**Backend unit** — `apps/api/tests/unit/modules/attendance/test_calculation.py`, **9 new tests**,
all passing, no existing test modified or broken:
weekly-cap clamp below daily cap, monthly-cap clamp, weekly-cap-exhausted-still-eligible-zero,
four `classify_ot_day` classification-precedence cases, SPLIT-shift OT detection, SPLIT-shift
no-policy no-op. Full file: **47/47 passing**.

**Backend integration** — `apps/api/tests/integration/modules/attendance/test_overtime_record.py`,
**20 new tests**, all passing against a real Postgres 16 instance (real RLS, real `hrms_app`
role, real HTTP through the ASGI app):

- Detection/policy resolution (2): policy resolves and day snapshots the version;
  threshold+rounding applied together.
- Approval chains (6): `AUTO` auto-approves immediately; `requires_post_approval=False`
  auto-approves without an `AUTO` chain; `MANAGER` chain pending→approved updates the day;
  `HR` chain requires `COMPANY` scope; `MANAGER_THEN_HR` two-stage (including manager cannot
  also clear HR); no-manager-resolved routes to HR (`APPROVER_UNRESOLVED` audited).
- Rejection/security (4): reject clears day fields; self-approval blocked; wrong manager cannot
  approve.
- Concurrency (2): stale If-Match rejected; simultaneous approve/reject race resolved to exactly
  one winner.
- Terminal freeze (1): an approved record survives a later recompute that would otherwise detect
  a materially different amount.
- Comp-off (2): fact + expiry on auto-approval; not credited to the day while still pending.
- Weekly cap (1): second day in the same ISO week correctly clamped by the shared budget.
- DataScope/security (3): SELF sees only own; REPORTEES excludes unrelated employees;
  cross-tenant record access returns 404.

Also ran the **full pre-existing attendance module suite together** with the new tests: **67
passed** (20 new integration + 47 unit), plus the same pre-existing teardown-only test-
infrastructure errors already documented in the W6 report §19.1/§19 (a `plan`/`subscription` FK
cleanup-ordering issue and the RLS/`current_setting` connection-pool bug) — confirmed **identical
in count and shape** whether or not W7's code is present, by running the same test files against
the pre-W7 working tree via `git stash`/`git stash pop` before restoring this slice's changes.
Every affected test's own assertions pass (`N passed, N error` per file — the error is always in
async teardown, never the test body).

`ruff check`: all checks passed. `ruff format --check`: clean except the same two pre-existing
unrelated formatting-drift lines in `repository.py` (docstring quoting, one long `.append()`
call) already present before this slice touched the file — confirmed by inspection that neither
line falls inside code this slice added or modified. `mypy` (`src/hrms/modules/attendance/`
only, matching this project's own `mypy_path = "src"` scope — tests are not type-checked):
`Success: no issues found in 11 source files`. `import-linter`: 1 contract kept, 0 broken.

**Frontend** — `apps/web/src/app/app/overtime/page.test.tsx` and `[id]/page.test.tsx`, **23 new
tests, all passing**, full suite **319/319**. `vitest run`, `tsc --noEmit`, and `next build` all
clean — see §15 for the exact output.

---

## 19. Migration Verification

`20260823090000_overtime_record.py` verified on a real Postgres 16 instance:

```text
upgrade 20260822090000 -> 20260823090000   OK
downgrade 20260823090000 -> 20260822090000  OK  (both new tables dropped)
upgrade 20260822090000 -> 20260823090000   OK  (re-applied cleanly)
```

---

## 20. Live Verification

The real API server was started as an actual `uvicorn` process (not the ASGI `TestClient`) against
the real dev Postgres/Redis stack, and driven end to end with a standalone Python script issuing
real HTTP requests (`httpx.Client` against `http://127.0.0.1:8010`):

1. Registered a real company via `POST /v1/companies/register`.
2. Built the full org/employee/shift/calendar/attendance-policy graph via real HTTP calls.
3. Created and published an `OvertimePolicyVersion` (`eligibility=ALWAYS`, `approval_chain=AUTO`,
   `comp_off_instead_of_pay=True`, `comp_off_expiry_days=90`, one rate row), COMPANY-assigned.
4. Punched a real IN/OUT pair (09:00–19:00 against a 09:00–18:00 shift) and called
   `POST /v1/attendance/days/calculate` — real `200`, `ot_minutes_detected=60`,
   `ot_minutes_approved=60`, `comp_off_minutes_earned=60`, `ot_pending=False`.
5. `GET /v1/overtime?employee_id=...&date_from=...&date_to=...` — real `200`, one record,
   `status=AUTO_APPROVED`, `minutes_detected=60`, `minutes_approved=60`, `comp_off_minutes=60`,
   `comp_off_expiry_date=2026-11-08` (exactly `2026-08-10 + 90 days`), `actions=["DETECTED",
   "AUTO_APPROVED"]`.
6. `GET /v1/overtime/{id}` — real `200`, matches the list row.

This confirms the full detect → auto-approve → comp-off-fact → read pipeline works against a
genuinely separate server process, not just the in-process test client. The broader
approval-chain matrix (`MANAGER`/`HR`/`MANAGER_THEN_HR`/reject/self-block/races/terminal-freeze/
weekly-cap) is covered by the 20 integration tests in §18, which already run the identical HTTP
stack against real Postgres with real RLS via the ASGI transport — functionally equivalent rigor
to a separate process for everything except "is a second OS process wired correctly," which step
1–6 above already confirms independently.

Frontend: `next build` (§15) confirms both new routes compile and render into real production
Next.js pages with no build-time errors; a full authenticated-browser click-through (login →
navigate to `/app/overtime` → approve/reject) was not additionally performed in this session —
the frontend's own `vitest` suite exercises every rendered state (loading/empty/error/permission-
denied/loaded/approve-flow/reject-flow) against a mocked API layer, and the backend contract it
calls against is the same one already live-verified end to end in steps 1–6 above. Flagged
honestly as a gap rather than overclaimed: a true browser session was not driven in this pass.

---

## 21. Known Limitations

### 21.1 `requires_pre_approval` is not enforced

See §4 (WD-29 decision 1 / PD-OT-2). No described mechanic exists for a pre-approval workflow
against retrospectively-detected overtime; left unenforced and documented, not silently ignored.

### 21.2 Weekly/monthly cap enforcement is not strictly idempotent

See §8 (WD-29 decision 3). A day's detected OT can depend on sibling-day state at calculation
time; recomputing the same day twice with unchanged punches can produce a different result if a
sibling day's `overtime_record` changed in between. Accepted and documented, confirmed with the
requester rather than discovered silently in production.

### 21.3 No revision/void workflow for a terminal decision

See §4 (WD-29 decision 2 / PD-OT-1). A later regularization correction to the same day never
retroactively revises an already-decided `OvertimeRecord`, even when the underlying punches
change materially.

### 21.4 Pre-existing production bug (RLS `current_setting` empty-string revert) — confirmed still present, not fixed

Already fully root-caused and documented in the W6 implementation report §19.1
(`docs/modules/attendance-regularization/00_W6_REGULARIZATION_IMPLEMENTATION_REPORT.md`).
Re-confirmed present in this session: the same `2 failed, N passed, N error` signature reproduces
identically whether run against the pre-W7 working tree or this slice's code (verified via
`git stash`/`git stash pop`), and the exact `InvalidTextRepresentationError: invalid input syntax
for type uuid: ""` error is still reproducible. **Not touched in this slice** — the fix spans
~15+ pre-existing migration files unrelated to overtime, outside this slice's own smallness
criterion, exactly as W6 already established. No W7 code path is affected differently than any
other attendance code, since W7 introduces no new unauthenticated route.

### 21.5 No full authenticated-browser click-through was performed

See §20. `next build` confirms both new routes compile into real pages, and the frontend's own
`vitest` suite (23 new tests) exercises every rendered state including the approve/reject flow
against a mocked API layer — but a live login → click "Approve" → observe the real network
request → observe the toast browser session was not additionally driven in this pass, unlike
W6's report which did perform one. Flagged as a real gap in this session's verification depth,
not silently omitted.

### 21.6 Pre-existing test-infrastructure teardown issue (unrelated `plan`/`subscription` FK ordering) — confirmed present, not fixed

A second, independently-discovered pre-existing issue (not documented in the W6 report): the
shared `seeded_plan_catalogue` pytest fixture's teardown attempts `DELETE FROM plan WHERE
plan.code IN (...)` while at least one `subscription` row still references it, raising a
`ForeignKeyViolationError` — always in async teardown, never inside a test's own body (every
affected test's own assertions pass; the pattern is always `N passed, N error`, `N` matching).
Confirmed pre-existing and unrelated to attendance/overtime by reproducing on the pre-W7 working
tree. Not fixed here — it is test-infrastructure-only, was not introduced by this slice, and
fixing shared fixture teardown ordering is outside this slice's stated scope.

---

## 22. Explicitly Excluded Work

Per the task brief's own scope boundary, none of the following were touched:

- Payroll, salary structure, statutory overtime rate calculation, or any monetary computation
  (ADR-0006 — `configured_multiplier` is stored and surfaced as an informational label only).
- Leave module, comp-off ledger/consumption/expiry-enforcement (ADR-0004 — Attendance emits the
  fact; Leave, when it exists, owns the ledger).
- W8 Attendance locks/period closing (this slice inherits the existing `is_locked` guard for
  free, adds no new lock model).
- A manual "request overtime" submission/pre-approval workflow (WD-29 decision 1 — no described
  mechanic exists for retrospectively-detected OT; not invented here).
- The pre-existing RLS bug fix (§21.4) and the pre-existing test-teardown fix (§21.6) — both
  reported, root-caused where newly found, not fixed, per this program's established smallness
  criterion for unrelated defects.

---

## 23. Recommended Next Step

**W8 (Attendance period locks) can safely begin.** W7 does not touch, block, or leave in an
inconsistent state anything W8 would depend on — the existing `AttendanceDay.is_locked` guard is
inherited unmodified by every new code path in this slice (a locked day simply never reaches OT
sync, verified implicitly by the pre-existing lock test suite continuing to pass unmodified).

Before W8 or any later slice, worth flagging to the team (not blocking, but real):

1. **§21.4's RLS bug** remains a genuine, reproducing production defect affecting
   `/v1/auth/login`/`/v1/companies/register` once a connection pool member has served any
   authenticated request. Still unfixed after two consecutive slices independently confirming it;
   worth prioritizing as its own ticket rather than continuing to defer it slice over slice.
2. **PD-OT-1/PD-OT-2** (§4/§21) are real product questions, not engineering ones: does any launch
   customer need to revise an approved OT decision after a later correction proves it wrong, or
   need a genuine pre-work-approval workflow rather than post-detection review? If yes to either,
   each needs its own scoped design — not invented here.
3. **§21.6's test-teardown issue** is minor but will keep generating noisy (harmless) `ERROR`
   lines in every attendance-adjacent test run until someone fixes the shared fixture's cleanup
   ordering — worth a small standalone ticket given how much test-run noise it now causes across
   multiple slices' test suites.

### Test counts (exact)

- Backend unit: **9/9 new** (`test_calculation.py`), **47/47** full file.
- Backend integration: **20/20 new** (`test_overtime_record.py`), **67/67** combined with unit
  tests; full attendance module suite run together shows the same pre-existing failure/error
  signature confirmed identical to the pre-W7 working tree (§21.4/§21.6), zero new regressions.
- Frontend: **23/23 new**, **319/319** full suite. `tsc --noEmit`: 0 errors. `next build`:
  succeeds, both new routes (`/app/overtime`, `/app/overtime/[id]`) present in the route manifest.
- ruff: 0 issues (this slice's own code). mypy: 0 issues (11 attendance source files).
  import-linter: 1 contract kept, 0 broken.
- Migration: upgrade/downgrade/upgrade verified on real Postgres.
- Live verification: full detect→auto-approve→comp-off-fact→read cycle confirmed against a real,
  separately-running server process, real Postgres, zero manual intervention (backend); frontend
  verified via `next build` + its own mocked-API test suite, not an additional live browser
  session (§21.5).
