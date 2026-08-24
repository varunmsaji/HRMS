# Workforce Attendance — Final Business-Rule Completeness Audit (Combined)

**Generated:** 2026-08-21

This file concatenates the six final-audit deliverables into a single file for offline
reading, printing, or sharing as one package. The individual files remain the maintained
sources — edit those, not this file; regenerate this file if any of them change.

- ATTENDANCE_RULE_COMPLETENESS_AUDIT.md
- ATTENDANCE_MASTER_RULE_MATRIX.md
- ATTENDANCE_OVERRIDE_MATRIX.md
- ATTENDANCE_SCENARIO_MATRIX.md
- ATTENDANCE_CONFIGURATION_AUDIT.md
- ATTENDANCE_DOCUMENTATION_GAPS.md

---



<!-- ============================================================ -->
<!-- SOURCE FILE: ATTENDANCE_RULE_COMPLETENESS_AUDIT.md -->
<!-- ============================================================ -->

# Workforce Attendance — Final Business-Rule Completeness Audit (W1-W9)

**Audit date:** 2026-08-21
**Scope:** Slices W1 (Work Calendar/Holiday/Weekly Off) through W9 (Leave→Attendance Projection)
**Type:** Documentation-only audit. No application code, migration, or frontend behaviour was
modified to produce this or any of its five companion documents.

This is the master document. It covers methodology, scope, what was inspected, a summary of
findings, the full calculation-order reconstruction (spec Section 6), and the closing executive
summary (spec Section 15). The other five deliverables hold the detailed tables:

1. `ATTENDANCE_MASTER_RULE_MATRIX.md` — full rule inventory, categories A-O
2. `ATTENDANCE_OVERRIDE_MATRIX.md` — precedence table + no-explicit-precedence findings
3. `ATTENDANCE_SCENARIO_MATRIX.md` — scenario matrix + Indian HR requirements audit
4. `ATTENDANCE_CONFIGURATION_AUDIT.md` — false-customization table + hidden rules
5. `ATTENDANCE_DOCUMENTATION_GAPS.md` — contradictions + test coverage audit + consolidated gap list

## 1. Methodology

This audit re-derived every claim from the current working tree rather than trusting prior
documentation or any "COMPLETE" status report. Concretely:

- **Read in full**: `apps/api/src/hrms/modules/attendance/models.py` (1003 lines),
  `calculation.py` (1327 lines, the entire pure evaluation engine), `resolution.py`,
  `permissions.py`, `dependencies.py`. `service.py` (7000+ lines) was read section-by-section
  covering every public method's control flow: policy CRUD/publish, `AttendanceDayService.
  calculate`/`_build_calculation_input`/`_resolve_ot_decision`/`_sync_overtime_record`,
  `RegularizationRequestService.approve`/`_approve_internal`/`_apply_correction`,
  `OvertimeRecordService.approve`/`reject`/`_get_reviewable`, `AttendancePeriodService.
  _run_validation`/`finalize`/`reopen`/`_apply_incomplete_lock_resolution`,
  `LeaveProjectionService.sync`/`cancel`.
- **Traced every configurable field** on `AttendancePolicyVersion`/`OvertimePolicyVersion`/
  `RegularizationPolicyVersion` with a grep across `calculation.py`/`service.py`/`repository.py`
  to determine whether it is consumed by evaluation logic or only by CRUD serialization — the
  basis for the false-customization table.
- **Read `apps/api/src/hrms/modules/organisation/calendar_resolution.py`** (the calendar
  classification + 8-level policy-precedence engine this module reuses) for holiday/weekly-off/
  exception precedence.
- **Read the three new alembic migrations** (`20260823090000_overtime_record.py`,
  `20260824090000_attendance_period.py`, `20260825090000_leave_day_projection.py`) and confirmed
  their DB constraints (GiST exclusion on `attendance_period`, unique constraint on
  `overtime_record.attendance_day_id`, natural-key partial unique on `leave_day_projection`)
  match what the ORM model docstrings claim.
- **Enumerated every test** in `apps/api/tests/unit/modules/attendance/test_calculation.py` (45
  tests) and `apps/api/tests/integration/modules/attendance/*.py` (8 files, 128 tests total) by
  function name, to build the test-coverage audit without guessing what's tested.
- **Checked the frontend wiring**: `apps/web/src/components/layout/nav-items.ts` (all attendance-
  related routes are wired), `apps/web/src/app/app/attendance/[id]/page.tsx` (confirmed the leave
  overlay is surfaced read-only; confirmed there is **no** dedicated Leave-projection management
  screen — only `lib/leave-projection/types.ts` exists, consumed by the attendance-day detail page).
- **Cross-checked three documentation sources** against code: the architecture doc, the client-
  facing `ATTENDANCE_V1_*` set, and the newer `docs/business-rules/attendance/*` set (dated
  2026-08-20, one day before this audit) — see `ATTENDANCE_DOCUMENTATION_GAPS.md` §Methodology for
  the finding that the client-facing docs are already largely accurate against current code, while
  the architecture doc contains several aspirational descriptions of unbuilt behaviour.
- **`git log --oneline -20` and `git diff --stat`** were run at the start to separate genuinely new
  (uncommitted) W5-W9 work from already-committed W1-W4 foundations — see §2 below.

Not exhaustively re-verified in this pass (explicitly noted, not silently assumed correct):
employee/employment effective-dating internals (belongs to the employee module, out of this diff);
RLS policy definitions; the organisation module's own `calendar_resolution.py` test suite (the
*logic* was read directly and cited; its *test coverage* was not independently re-enumerated);
DST-transition correctness (flagged as untested, not proven wrong); exact FastAPI
transaction/commit boundaries (the "approve rolls back atomically" claim is taken from a code
comment, cross-referenced with the surrounding transactional pattern used consistently everywhere
else in this module, but the session/commit wiring itself was not traced end-to-end).

## 2. Scope of change inspected

`git status`/`git diff --stat` at audit time showed the following as uncommitted (i.e., the
"recent W5-W9 work" this audit was specifically commissioned to re-verify):

```
 apps/api/src/hrms/modules/attendance/{calculation,dependencies,exceptions,models,permissions,
   repository,router,schemas,service}.py   (4,492 insertions across 19 tracked files)
 apps/api/src/hrms/modules/employee/{repository,service}.py
 apps/api/tests/integration/modules/organisation/test_registration_flow.py
 apps/api/tests/unit/modules/attendance/test_calculation.py
 apps/web/src/app/app/attendance/[id]/{page.tsx,page.test.tsx}
 apps/web/src/app/app/attendance/page.test.tsx
 apps/web/src/components/layout/nav-items.ts
 apps/web/src/lib/attendance/types.ts
 docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md

 New (untracked):
 apps/api/alembic/versions/20260823090000_overtime_record.py
 apps/api/alembic/versions/20260824090000_attendance_period.py
 apps/api/alembic/versions/20260825090000_leave_day_projection.py
 apps/api/tests/integration/modules/attendance/{test_attendance_period,test_leave_projection,
   test_overtime_record}.py
 apps/web/src/app/app/{attendance-periods/,overtime/}
 apps/web/src/components/{attendance-period/,overtime/}
 apps/web/src/lib/{attendance-period/,leave-projection/,overtime/}
 docs/business-rules/ (client-facing doc set)
 docs/modules/{attendance-lock/,leave/,overtime/}
```

Recent commit history (`git log --oneline -20`) shows W1-W4 foundation work already committed
(`787ff8b feat: commit W1-W4 workforce attendance foundation`, plus two follow-up fix/style
commits), and the most recent commit `dbd3f43 feat(attendance): commit W5 shift rosters + W6
regularization workflow` — meaning **W7 (overtime), W8 (period lock), and W9 (leave projection)
are entirely uncommitted at audit time**, exactly matching the three new migrations and the bulk
of the `service.py`/`models.py`/`schemas.py` diff. This audit treats all of it — committed and
uncommitted alike — as the current, single source of truth for "what the system does today."

## 3. Summary of findings

The module is substantially more complete than a superficial read of the architecture document
would suggest, and substantially less complete than the architecture document's own prose implies
for a specific cluster of features. Three findings dominate:

**What is genuinely solid.** The core calculation pipeline (employment gate → calendar → policy
resolution → punch pairing/collapsing → break matching → status resolution → OT detection → leave
overlay), the entire W7 overtime approval workflow (including self-approval blocks, multi-stage
chains, frozen terminal decisions, daily/weekly/monthly caps), the entire W8 period-lock lifecycle
(6 independently-tested validation blockers, atomic finalize, comprehensive mutation-blocking
across all 7 mutable surfaces, reopen), and the entire W9 leave-projection overlay (full-day,
half-day, cancellation, overlap prevention, lock interaction) are all implemented correctly,
consistently, and are extensively unit- and integration-tested. RBAC/DataScope enforcement across
self/reportees/reportee-tree scopes and cross-tenant isolation is likewise comprehensively tested.

**What is configured but inert.** A specific, recurring pattern exists throughout this module:
a policy field is modeled, exposed via CRUD API and (per the frontend directory listing) a UI
form, resolved all the way into the pure calculation engine's input dataclasses — and then never
actually read by any `if`/`elif` branch in `calculation.py`. This is not one isolated bug; it is a
pattern spanning roughly 16 distinct configuration fields (punch rounding, core hours and its
breach behaviour, half-day-split method, excess-break behaviour, WFH/On-duty punch rules, late/
early-band cap-counting, auto-close, "by grade" OT eligibility, the night-OT time window, and
others — full list in `ATTENDANCE_CONFIGURATION_AUDIT.md`). Critically, **none of this is new** —
independent sampling against the pre-existing client-facing documentation shows every one of these
gaps was already known and already accurately documented before the W7/W8/W9 work in this diff,
and none of them were fixed incidentally by that work. The single most consequential of these is
**night-shift overtime classification**: the architecture document explicitly and emphatically
states `is_night_shift` "is an explicit flag... not inferred solely from times" (architecture
§9.5), while the shipped code does exactly that — `is_night` for OT purposes is always
`shift.is_cross_midnight`, the configured night-window start/end times are read into the engine's
inputs and never compared against anything, and the *default* `night_ot_mode` setting means a
tenant that never touches this policy screen will never see a single NIGHT-classified overtime
record, ever, regardless of how many genuinely-overnight shifts it runs. For a product whose
Indian-HR-requirements audit (Section 13, in the scenario matrix) explicitly needs to support
security/hospital/manufacturing night-shift patterns, this is the highest-priority gap found.

**What has no decided answer at all.** Distinct from "configured but inert," a few interactions
have no rule anywhere — not in code, not in any document, not in any test: most importantly,
whether overtime detected on a day fully covered by an approved leave application should be
cleared, kept, or something else (currently: kept, incidentally, because the leave overlay never
touches the OT fields — see `ATTENDANCE_OVERRIDE_MATRIX.md` for the full analysis). This is a
genuine open product question, not a documentation gap to be fixed by writing something down.

## 4. Section 6 — Calculation Order (reconstructed from code, not assumed)

This reconstructs the *actual* execution order inside `AttendanceDayService.calculate()` →
`calc.evaluate_day()`, derived by reading `service.py:2478-2624` and `calculation.py:704-802` line
by line — not the example order in any prior spec document.

| Step | What happens | Input | Output | Rule used | Possible statuses at this point | Can be overridden by | Can never be overridden by |
|---|---|---|---|---|---|---|---|
| 0 | Period-lock pre-check | `company_id`, `target_date` | raises `AttendancePeriodClosedError` or proceeds | `_ensure_date_open` (`service.py:2499`) | n/a — hard stop | Nothing — fail-closed | Any policy setting |
| 0b | Row-level lock re-check | existing `AttendanceDay.is_locked` | raises `AttendanceDayLockedError` or proceeds | `service.py:2506-2507` | n/a | Nothing | Anything |
| 1 | Employment gate | `Employment.get_employment_as_of(target_date)` | `population_status ∈ {ACTIVE, NOT_JOINED, EXITED}` | `service.py:2724-2733` | Terminal `NOT_JOINED`/`EXITED` short-circuits everything below | Nothing (highest-ranked gate) | n/a |
| 2 | Assignment resolution | `EmployeeAssignmentService.get_assignment_as_of` | branch, shift default, reporting manager | `service.py:2735-2737` | n/a | Roster (for shift only, step 5) | n/a |
| 3 | Roster lookup | `ShiftRoster.get_published_for_date` | `roster_week_off_override`, `roster_holiday_working_override`, roster `shift_id` (if any) | `service.py:2750-2758` (W5) | n/a | Nothing (roster is itself the override) | DRAFT roster rows (invisible) |
| 4 | Shift-version resolution | `shift_id` (roster or assignment) + `target_date` | `ShiftInputs` (type, breaks, duty blocks, core hours, OT flag, holiday/weeklyoff-operates flags) | `service.py:2760-2828` | n/a (feeds later steps) | n/a | n/a |
| 5 | Timezone resolution | shift-version tz, branch tz, company tz | one `tz_name` | `resolve_timezone` (`calculation.py:263-267`, WD-06) | n/a | Branch tz (over company) | Nothing overrides shift-version tz |
| 6 | Schedule window resolution | shift type + raw times + tz | `scheduled_start/end`, punch-load window | `resolve_schedule_window` (`calculation.py:344-429`) | n/a | n/a | n/a |
| 7 | Calendar resolution | `employee_id`, `target_date` | `calendar_day_type`, `holiday_name`, `holiday_on_weekly_off` | `CalendarResolutionService.resolve_for_employee` (organisation module, 8-level walk) | `None` if unresolved → later becomes `CONFIG_ERROR` | Calendar exceptions (per-date) | Nothing below this step can retroactively change `calendar_day_type` (only the *expectation of presence* built on top of it) |
| 8 | Attendance-policy resolution | `employee_id`, `target_date`, policy_kind=ATTENDANCE_POLICY | `PolicyInputs` + hour/late/early bands | `resolution.py` `PolicyResolutionService.resolve` → 8-level walk | `None` if unresolved → `CONFIG_ERROR` | Higher-precedence scope | Lower-precedence scope |
| 9 | Overtime-policy resolution + sibling-day cap consumption | same walk, plus DB sums of `overtime_record.minutes_detected` for the current ISO week/calendar month | `OvertimePolicyInputs` including `remaining_weekly_minutes`/`remaining_monthly_minutes` | `service.py:2928-3003` (W7, WD-29 decision 3) | n/a | n/a | n/a — this is the one documented non-idempotent input (§ known limitation) |
| 10 | Regularization-policy resolution | same walk | `regularization_policy_version_id` only (used for request snapshotting, not evaluation) | `service.py:3005-3012` | n/a | n/a | n/a |
| 11 | Punch loading | padded load window from step 6 | `list[PunchData]` | `service.py:3016-3026` | n/a | n/a | n/a — only `population_status=ACTIVE` employees load punches at all |
| 12 | Leave-projection loading | `employee_id`, `target_date` | `list[LeaveOverlayEntry]` (only APPROVED, active) | `service.py:3031-3039` (W9) | n/a | n/a | n/a |
| 13 | **Pure engine entry**: population gate re-check | `population_status` | terminal `NOT_JOINED`/`EXITED` | `calculation.py:724-726` | Terminal | Nothing | Everything |
| 14 | Calendar-resolution-failure gate | `calendar_day_type is None` | terminal `CONFIG_ERROR` | `calculation.py:729-730` (WD-21 fail-closed) | Terminal | Nothing | Everything |
| 15 | Policy-resolution-failure gate | `policy is None` | terminal `CONFIG_ERROR` | `calculation.py:733-734` | Terminal | Nothing | Everything |
| 16 | Roster week-off override (no shift, no punches) short-circuit | `roster_week_off_override and not punches` | terminal `NOT_EXPECTED` → leave overlay applied | `calculation.py:742-746` | `NOT_EXPECTED` (then possibly `LEAVE` via step 22) | Leave overlay | Nothing else |
| 17 | Missing-shift branch | `shift is None` | `ABSENT`/`INCOMPLETE` (no punches) or `_evaluate_no_schedule` (punches exist) | `calculation.py:748-759` | per `missing_shift_behaviour` | n/a | n/a |
| 18 | `not_expected`/`shift_operates` computation | `calendar_day_type`, shift flags, roster override | booleans | `calculation.py:761-774` | n/a | Roster holiday-working override, shift `operates_on_*` flags | n/a |
| 19 | Duplicate-punch collapsing | sorted punches, `duplicate_punch_window_seconds` | collapsed punch list | `collapse_duplicate_punches` (`calculation.py:437-452`) | n/a | n/a | n/a |
| 20 | Not-expected-and-nothing-happened short-circuit | `not_expected and not shift_operates and not collapsed` | terminal `NOT_EXPECTED` → leave overlay | `calculation.py:783-789` | `NOT_EXPECTED` | Leave overlay | n/a |
| 21 | Punch pairing | collapsed punches | `PairingResult` (pairs + orphans) | `pair_punches` (`calculation.py:460-486`) | n/a | n/a | n/a |
| 22 | Shift-type dispatch | `shift.shift_type` | `_evaluate_split` or `_evaluate_fixed_or_flex` | `calculation.py:797-800` | see steps 23-30 | n/a | n/a |
| 23 | Presence-span computation | pairs, `multi_punch_mode` | `first_in`, `last_out`, `gross_minutes`, `gaps` | `presence_span` (`calculation.py:489-516`) | n/a | n/a | n/a |
| 24 | Break matching | gaps, `shift.breaks` | `list[MatchedBreak]` (paid/unpaid/excess) | `match_breaks` (`calculation.py:543-586`) | n/a | n/a | n/a — unmatched gaps always default unpaid |
| 25 | Worked-minutes arithmetic | `gross_minutes`, `multi_punch_mode`, paid/unpaid minutes | `worked_minutes` | `worked_minutes_from_gross` (`calculation.py:519-536`) | n/a | n/a | n/a |
| 26 | Late/early computation | `first_in`/`last_out` vs `scheduled_start/end`, grace, bands | `late_minutes`/`early_departure_minutes` + classifications | `calculation.py:1028-1038` | n/a | n/a | n/a |
| 27 | Hour-band lookup | `worked_minutes` | `hour_band_status` | `lookup_band` (`calculation.py:1040`) | PRESENT/HALF_DAY/ABSENT | n/a | n/a |
| 28 | Primary status resolution | `not_expected`, `worked_minutes`, `missing_punch`, `missing_punch_behaviour`, `hour_band_status`, late/early classification | one of `NOT_EXPECTED`/`ABSENT`/`INCOMPLETE`/`PRESENT`/`HALF_DAY` | `_resolve_primary_status` (`calculation.py:1271-1314`) | **Late/early band = ABSENT or HALF_DAY outranks the hour-band status outright** (undocumented precedence, see Hidden Rules HR3) | n/a | n/a |
| 29 | Overtime detection | `worked_minutes`, `scheduled_minutes`, shift OT-eligible flag, holiday/weeklyoff/night flags, `OvertimePolicyInputs` | `ot_minutes_detected`, `ot_classification`, `eligible` | `detect_overtime` (`calculation.py:653-696`) | n/a | Daily/weekly/monthly caps (whichever is tightest) | Nothing raises the cap |
| 30 | Paid/LOP fraction | final `status`, `hour_band_status` | `paid_day_fraction`, `lop_fraction` | `_paid_lop_fraction` (`calculation.py:1317-1326`) | n/a | Leave overlay (step 31) | n/a |
| 31 | **Leave overlay** (applied to every non-terminal, non-gate outcome) | `leave_entries`, punch-derived `result` | possibly-replaced `attendance_status`/`paid_day_fraction`/`lop_fraction`/late-early fields, or `work_on_leave_flagged` | `_apply_leave_overlay` (`calculation.py:805-879`, W9) | Full-day leave wins outright over everything except the population gate and CONFIG_ERROR; half-day leave blends with the punch-derived outcome as a flat 0.50 | `work_on_leave_behaviour=PRESENT_CANCEL_LEAVE_HINT` (keeps punch outcome instead) | Population gate, CONFIG_ERROR |
| 32 | OT-decision resolution (service layer, after the pure engine returns) | `result.ot_minutes_detected`, existing `overtime_record` state, approval chain | PENDING/AUTO_APPROVED/frozen-terminal decision | `_resolve_ot_decision` (`service.py:3072-3161`) | n/a | A prior terminal decision freezes and wins outright, even over a fresh recompute | n/a |
| 33 | Persist | all of the above | `AttendanceDay` row (insert or full replace), `AttendanceBreak` rows (full replace), `OvertimeRecord` sync, audit log entries | `service.py:2545-2624`, `3163-3256` | n/a | n/a | n/a |

**Regularization is explicitly not a step in this pipeline** — it is applied *before* step 0 runs
again, as new synthetic punches (or a roster row), and the entire pipeline above simply re-executes
from scratch on the corrected inputs (WD-28 decision 1, confirmed at `service.py:3940-3945`).

## 5. Reading the other five documents

- Start with `ATTENDANCE_MASTER_RULE_MATRIX.md` for the full A-O rule inventory if you need to
  know the exact status of one specific setting.
- `ATTENDANCE_OVERRIDE_MATRIX.md` answers "if two rules conflict, which wins" and separately lists
  every combination the code does **not** decide at all.
- `ATTENDANCE_CONFIGURATION_AUDIT.md` is the single most actionable document for a product/UX
  decision — it lists every setting a user can configure that has zero runtime effect, with exact
  code citations, plus 12 further "hidden rules" embedded in code but nowhere in documentation.
- `ATTENDANCE_SCENARIO_MATRIX.md` is the walkthrough reference — 74 concrete day-level scenarios
  plus the Indian-HR-requirements support-level table.
- `ATTENDANCE_DOCUMENTATION_GAPS.md` is where architecture-doc-vs-code contradictions are laid out
  side by side (12 contradictions found, most already correctly captured by the newer client-facing
  docs), plus the full test-coverage audit and a consolidated count of every gap raised anywhere in
  this audit.

## 6. Section 15 — Final Executive Summary

**A. Rules currently implemented** — The full W1-W9 pipeline: employment gating, 8-level policy/
calendar precedence, timezone resolution (3-tier), calendar day-type classification (holiday/
weekly-off/shutdown/special-working/exceptions), weekly-off patterns (fixed/nth/last/alternate/
custom/rotational-via-roster), shift resolution (FIXED/SPLIT fully, FLEXIBLE partially), punch
pairing/duplicate-collapsing/multi-punch modes, break matching and paid/unpaid arithmetic, grace
and late/early band classification, hour-band status resolution, roster overrides, the full
regularization workflow (submit/approve/reject/cancel, multi-stage chains, self-approval block,
backdating/monthly caps, allowed-type gating), the full overtime workflow (detection, daily/
weekly/monthly caps, approval chains, self-approval block, comp-off facts, frozen terminal
decisions), the full period-lock lifecycle (6 validation blockers, atomic finalize, 7-surface
mutation blocking, reopen), and the full leave-projection overlay (full/half-day, cancellation,
overlap prevention, lock interaction).

**B. Rules users can configure and that actually work** — Grace minutes, punch multi-pairing mode,
duplicate-punch window, missing-shift behaviour, hour/late/early bands, split-shift missed-block
behaviour (as a status mapping), work-on-leave behaviour, incomplete-at-lock behaviour,
OT min-minutes/rounding/caps/requires-post-approval/comp-off-instead-of-pay, all four approval
chains (regularization and OT independently), regularization backdating/monthly-caps/reason-
attachment-requirements/allowed-types, roster week-off/holiday-working overrides.

**C. Rules users can configure but currently do NOT work** — Punch rounding, flexible-shift core
hours (start/end and breach behaviour), half-day-split method (BY_HOURS/BY_MIDPOINT), excess-break
behaviour, WFH/On-duty punch rules, late/early-band `counts_toward_cap`, repeated-late-to-half-day
penalty, early-departure-requires-approval, auto-close (both the trigger and its timing/shift-end
config), split-shift block-mandatory/hours-compensation flags, OT "by grade" eligibility, OT
night-window start/end, regularization `auto_approve_within_minutes`, regularization
`blocked_when_locked` (inverted risk — reads as an escape hatch, is actually inert). Full list
with citations: `ATTENDANCE_CONFIGURATION_AUDIT.md`.

**D. Rules hard-coded by the system** — Self-approval block (regularization and OT, no policy
escape hatch by design), fail-closed CONFIG_ERROR on unresolved calendar/policy, break-gap-to-
break first-match tie-break, late/early-band-outranks-hour-band status precedence, "is_night =
is_cross_midnight" for OT purposes, roster-check-before-missing-shift-check ordering, period-lock
unconditionally blocking every mutation surface regardless of any policy field.

**E. Rules with unresolved precedence** — Leave vs Overtime (an approved full-day leave does not
clear OT detected from incidental punches on that date — no code, doc, or test settles this).
Regularization approval vs an already-terminal OvertimeRecord for the same day (documented as
deliberately frozen, WD-29, but leaves the two facts able to diverge with no reconciliation path
short of a full period reopen). Two overlapping `PolicyAssignment` rows at the same scope tier
(not defended against, not re-examined in depth in this pass).

**F. Rules requiring client decisions** — Holiday-landing-on-weekly-off auto-substitution
(PD-CAL-2, explicitly open in code); OT eligibility "by grade" — build the real grade check or
remove the setting; night-shift OT classification — build window-based detection or accept
cross-midnight-only and relabel the setting; WFH/On-duty as first-class statuses — pick one of the
architecture's three named mechanisms (roster flag / regularization type / punch-source-plus-
policy) or descope entirely; auto-close — implement the synthetic-close-punch behaviour the setting's
name promises, or rename/hide it (the client-facing docs already recommend this specifically);
Leave vs Overtime precedence (new question, no prior position exists anywhere).

**G. Future attendance-related features** — A real Leave module (entitlement/balance/accrual/
approval — `LeaveDayProjection` is explicitly a temporary stand-in, per its own model docstring);
comp-off expiry-lapse enforcement (the fact is computed and stored; nothing invalidates it once
`comp_off_expiry_date` passes); monetary OT/payroll calculation (deliberately out of scope per
ADR-0006 — `configured_multiplier` is informational only); punch partitioning (deliberately
deferred, WD-26, until real volume exists); device-sourced punches (`Punch.source` reserves the
value, no ingestion path exists yet, named as W10 in the model docstring).

**H. Documentation gaps** — 10 catalogued in `ATTENDANCE_DOCUMENTATION_GAPS.md` (architecture doc
describing punch rounding, auto-close, core hours, `DEDUCT_SCHEDULED`, and WFH/On-duty as if built;
architecture doc's `is_night_shift` requirement directly contradicted by code; plus 12 further
"hidden rule" items with no documentation anywhere).

**I. Implementation gaps** — 16 catalogued (see the consolidated list in
`ATTENDANCE_DOCUMENTATION_GAPS.md`), the highest-priority being the night-OT window and "by grade"
OT eligibility, both explicitly flagged by the pre-existing client docs as needing resolution
before go-live if either is a genuine client requirement.

**J. Test gaps** — FLEXIBLE-shift end-to-end evaluation is entirely unverified by any test found;
Leave-vs-OT and Regularization-vs-OT combinations are untested; employee-transfer/policy-change/
shift-change mid-period scenarios are untested; DST-transition dates are untested; split-shift
missed-block behaviour branches beyond the happy path are only partially tested; `TREAT_PRESENT`
incomplete-at-lock resolution is untested (only `KEEP_INCOMPLETE` and default `TREAT_ABSENT` are).
Full detail: `ATTENDANCE_DOCUMENTATION_GAPS.md` §Section 11.

---

## ATTENDANCE SYSTEM READINESS

*The following are audit estimates formed by this review's own judgment of coverage breadth
against the rule inventory built above — they are not test-coverage measurements, not derived
from any code-coverage tool, and not a substitute for a client/product sign-off decision.*

| Dimension | Estimate | Basis |
|---|---|---|
| Business-rule completeness | **~78%** | Core pipeline (calendar, shift, punch, break, status, OT, regularization, lock, leave overlay) is essentially complete; the ~16-item false-customization cluster and the WFH/On-duty/core-hours/auto-close/rounding gaps are the main shortfall, concentrated in a few feature areas rather than spread evenly |
| Configuration completeness | **~60%** | Roughly 16 of the ~45 distinct policy-version fields inventoried in this audit have no runtime effect — a substantial fraction of what the UI/API present as configurable is currently decorative |
| Precedence completeness | **~85%** | The core 8-level scope walk, calendar-exception precedence, and lock/mutation precedence are all explicit, tested, and consistent; only Leave-vs-OT and the two OT-freeze-related interactions lack an explicit, decided rule |
| Scenario coverage (test suite) | **~75%** | 45 unit + 128 integration tests give strong coverage of single-rule behaviour and most cross-cutting workflows (regularization, OT, lock, leave); FLEXIBLE shifts, several combination scenarios (Leave+OT, Regularization+OT, mid-period changes), and DST are the clearest gaps |
| Documentation completeness | **~55%** | The architecture document has not been updated to reflect what W3-W9 actually shipped versus what was originally designed (rounding, core hours, auto-close, WFH, night OT); the newer client-facing `docs/business-rules/` set is considerably more accurate but is not yet the document a new engineer would find first |

---

*Audit conducted 2026-08-21 against the working tree described in §2. All six deliverable
documents were produced in this single audit pass; no claim in any of them was carried forward
from a prior report without independent re-verification against current code.*



<!-- ============================================================ -->
<!-- SOURCE FILE: ATTENDANCE_MASTER_RULE_MATRIX.md -->
<!-- ============================================================ -->

# Attendance Master Rule Matrix (W1-W9)

Companion to `ATTENDANCE_RULE_COMPLETENESS_AUDIT.md`. This is the full business-rule inventory
(spec Section 4), categories A-O. Every row was checked against the current working tree, not
against prior documentation. File:line citations point at the code inspected on 2026-08-21
(uncommitted `git status` at audit time — see the master audit for the full change list).

Status legend: **CURRENTLY WORKING** | **CONFIGURABLE AND WORKING** | **STORED BUT NOT USED** |
**OPEN PRODUCT DECISION** | **FUTURE MODULE** | **KNOWN LIMITATION** | **DOCUMENTATION GAP** |
**IMPLEMENTATION GAP**

Core files referenced throughout (paths relative to repo root):
- `apps/api/src/hrms/modules/attendance/models.py` (M)
- `apps/api/src/hrms/modules/attendance/calculation.py` (C) — pure evaluation engine
- `apps/api/src/hrms/modules/attendance/service.py` (S) — orchestration/DB
- `apps/api/src/hrms/modules/attendance/schemas.py` (SC)
- `apps/api/src/hrms/modules/attendance/repository.py` (R)
- `apps/api/src/hrms/modules/attendance/resolution.py` (RES)
- `apps/api/src/hrms/modules/organisation/calendar_resolution.py` (CAL)

---

## A. Employment

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing behaviour | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 Employment gate | An employee-date is only evaluated if an `Employment` spell covers it | N/A (fact-derived) | n/a | Yes | No | `service.py:2724-2733` calls `EmploymentService.get_employment_as_of` | `employment` table (employee module) | Everything else (ranks first in §19.1) | Nothing — highest precedence | No employment row and none ever existed → `NOT_JOINED`; one existed but ended → `EXITED` | `test_not_joined_before_employment_gate` (attendance_day) | CURRENTLY WORKING |
| A2 NOT_JOINED / EXITED terminal status | Population gate short-circuits the whole pipeline | n/a | n/a | Yes | No | `calculation.py:724-726`, `_terminal_result` | `attendance_day.attendance_status` | Calendar, shift, policy, leave overlay (all skipped) | Nothing | n/a — always resolvable if employment history exists | `test_evaluate_day_not_joined/exited` (unit) | CURRENTLY WORKING |
| A3 Paid/LOP fraction on gate statuses | `NOT_JOINED`→ paid 1.00/lop 0.00 (not sent to payroll as absence); `EXITED`→ paid 0.00/lop 1.00 | n/a | n/a | Yes | No | `calculation.py:892-897` `_terminal_result` | `attendance_day.paid_day_fraction/lop_fraction` | n/a | n/a | n/a | unit tests above (indirect) | CURRENTLY WORKING |
| A4 Effective-dated employment/assignment | Every resolution call is `..._as_of(target_date)`, never "current" | n/a | n/a | Yes | No | `service.py:2724,2735` | `employment`, `employee_assignment` (employee module) | n/a | n/a | n/a | employee module's own suite (not re-audited here) | CURRENTLY WORKING (re-used, not re-verified in this pass — see note below) |

Note: employee/employment effective-dating internals were not re-read line-by-line in this audit
pass (out of the attendance module's own diff); the attendance module's calls into
`EmploymentService`/`EmployeeAssignmentService` are `_as_of(target_date)` calls, confirmed by
grep at `service.py:2724,2735,3116`.

## B. Assignment

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 Assignment shift is the fallback shift source | `EmployeeAssignment.shift_id` used only when no `PUBLISHED` `ShiftRoster` row exists for the date | Employee-level | n/a | Yes | Yes (assign a shift) | `service.py:2764-2768` | `employee_assignment.shift_id` | Shift-policy default | `ShiftRoster` (W5) | No assignment and no roster → `shift_id=None` → missing-shift path (`missing_shift_behaviour`) | `test_published_roster_overrides_assignment_shift` | CURRENTLY WORKING |
| B2 Assignment branch → timezone | `assignment.branch_id` resolves `Branch.timezone`, one of 3 timezone precedence inputs | Branch-level | n/a | Yes | Yes | `service.py:2740-2744` | `branch.timezone` | Company timezone | Shift-version timezone | No branch on assignment → `branch_timezone=None`, falls through | none found directly in attendance suite (organisation module owns branch tz tests) | CURRENTLY WORKING |
| B3 Assignment reporting manager → regularization/OT approver | `assignment.reporting_manager_id` resolves the MANAGER approval stage | Employee-level | n/a | Yes | Yes | `service.py:3116-3121` (OT), regularization submit does the same (`service.py` search `reporting_manager_id`) | `employee_assignment.reporting_manager_id` | n/a | HR (when unresolved) | No manager resolved → routes straight to `HR` stage, flags `APPROVER_UNRESOLVED` | `test_no_manager_resolved_routes_to_hr` (both OT and regularization suites) | CURRENTLY WORKING |
| B4 Assignment → policy-assignment scope candidates (DESIGNATION/GRADE/DEPARTMENT/BRANCH) | 8-level scope walk for policy_kind resolution | Various | n/a | Yes | Yes | `calendar_resolution.py:48-57,251+` (reused by `resolution.py:62-65`) | `policy_assignment` (organisation module) | Lower-precedence scopes | Higher-precedence scopes (EMPLOYEE/SHIFT beat it) | No assignment row at any scope → `config_incomplete=True` → CONFIG_ERROR | `test_policy_resolution.py` (3 tests, thin) | CURRENTLY WORKING |

## C. Timezone

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 Timezone precedence | `ShiftVersion.timezone` > `Branch.timezone` > `Company.timezone` (WD-06) | Shift/Branch/Company | Company tz | Yes | Yes at all 3 levels | `calculation.py:263-267` `resolve_timezone` | `shift_version.timezone`, `branch.timezone`, `company.timezone` | Lower levels | Nothing (top of chain) | Company always has a timezone (required at registration) so this never fails closed | `test_resolve_timezone_prefers_shift_version`, `test_resolve_timezone_falls_back_to_branch_then_company` | CURRENTLY WORKING |
| C2 UTC storage | All punches/scheduled spans stored UTC; local time only used for classification | n/a | n/a | Yes | No | `Punch.punch_time: DateTime(timezone=True)` (models.py:445), `_local_to_utc` (calculation.py:275) | `punch.punch_time` | n/a | n/a | n/a | implicit across all evaluate_day tests | CURRENTLY WORKING |
| C3 DST handling | `ZoneInfo`-based conversion; Python's `zoneinfo` handles DST transitions natively for named zones | n/a | n/a | Presumed yes (stdlib) | No | `calculation.py:47` `from zoneinfo import ZoneInfo`, used throughout | n/a | n/a | n/a | No spring-forward/fall-back day was found in the test suite | **No test exercises a DST-transition date.** Not independently proven correct for the "shift spans the clock change" case. | DOCUMENTATION GAP (untested, not proven wrong) |
| C4 No employee-level timezone override | Architecture §6.4 itself specifies exactly 3 tiers (`shift_version.timezone > branch.timezone > company.timezone`, `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md:605-615`) — code matches this precisely, no discrepancy found | n/a | n/a | Yes (3-tier, as documented) | No | `resolve_timezone` signature has exactly 3 params (`calculation.py:263-267`) | No `employee.timezone` column exists (confirmed by grep) | n/a | n/a | n/a | n/a | CURRENTLY WORKING — code and architecture doc agree; re-checked in this pass, not a gap |

## D. Work Calendar

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D1 Day-type precedence | `CalendarException` > holiday union (first-list-wins) > weekly-off > WORKING | Company/scope | n/a | Yes | Yes (exceptions are per-date) | `calendar_resolution.py:130-233 classify_work_calendar_date` | `calendar_exception`, `holiday`, `weekly_off_pattern` (organisation module) | Everything below it | Roster override (W5) at the *expectation* level only, never `calendar_day_type` itself | No `WorkCalendar` resolved for the employee → `config_incomplete=True` → `CONFIG_ERROR` | organisation module's own `test_calendar_resolution.py` (not re-read in this pass; attendance-side is `_build_calculation_input` consuming `calendar_result`) | CURRENTLY WORKING |
| D2 Holiday landing on weekly-off | Stays `WEEKLY_OFF`, sets `holiday_on_weekly_off=True`; no auto-substitute | Company | Stay WEEKLY_OFF | Yes | **No — open decision (PD-CAL-2), no config to change it** | `calendar_resolution.py:208-218` | `day_type_read.holiday_on_weekly_off` → `attendance_day.holiday_on_weekly_off` | n/a | n/a | n/a | not found directly in attendance-side unit tests; organisation-side likely covers `classify_work_calendar_date` | OPEN PRODUCT DECISION (explicitly flagged `PD-CAL-2` in code comment, `calendar_resolution.py:211`) |
| D3 Optional/Restricted holiday default | Off by default unless calendar's own `restricted_holidays_are_off_by_default=False` treats it as "working until Leave applies" | WorkCalendar-level flag | Working (soft) unless flag flips it | Yes | Yes | `calendar_resolution.py:190-206` | `work_calendar.restricted_holidays_are_off_by_default` (organisation module) | n/a | Hard holiday types always win | n/a | not re-read | CONFIGURABLE AND WORKING — flagged `PD-CAL-1` as "the only sanctioned per-company override" |
| D4 SUBSTITUTE_HOLIDAY exception | Explicit exception row → `day_type=HOLIDAY` for the substitute date | Per-date exception | n/a | Yes | Yes (manual exception creation) | `calendar_resolution.py:157-163` | `calendar_exception.exception_type='SUBSTITUTE_HOLIDAY'` | Weekly-off pattern for that date (forces HOLIDAY regardless) | n/a | n/a | not re-read | CURRENTLY WORKING (manual only — no automatic Sunday-holiday-triggers-Monday-substitute rule exists; that would be D2's open decision) |
| D5 SHUTDOWN / SPECIAL_WORKING / CANCEL_HOLIDAY exceptions | Per-date overrides feeding calendar_day_type SHUTDOWN/SPECIAL_WORKING, or removing a holiday match for one date | Per-date | n/a | Yes | Yes | `calendar_resolution.py:143-167` | `calendar_exception.exception_type` | Holiday/weekly-off union | n/a | n/a | not re-read | CURRENTLY WORKING |
| D6 SHUTDOWN/HOLIDAY/WEEKLY_OFF feed `not_expected` in the engine | These 3 day types (plus roster week-off override) mean presence isn't expected by default | n/a | n/a | Yes | No | `calculation.py:767-769` | n/a | n/a | Shift `operates_on_holiday`/`operates_on_weekly_off`, roster `is_holiday_working_override` | n/a | `test_evaluate_day_worked_on_weekly_off`, `test_evaluate_day_not_expected_holiday_no_punches` | CURRENTLY WORKING |

## E. Weekly Off

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 FIXED_WEEKDAYS / NTH_WEEKDAY / ALTERNATE / CUSTOM, one child table | A single self-describing rule row covers Mon-Fri/Mon-Sat, nth-Saturday, last-Saturday, alternate-Saturday, and arbitrary combinations | Company/scope | n/a | Yes | Yes | `calendar_resolution.py:99-117 _rule_matches` | `weekly_off_pattern` rule rows (organisation module) | n/a | Holiday union at the hard-holiday tier (see D2) | No rule matches → `is_off=False` | not re-read (organisation module) | CURRENTLY WORKING |
| E2 Multiple matching rules | Most conservative (largest) off-fraction wins if >1 rule matches the same date | n/a | n/a | Yes | No | `calendar_resolution.py:120-127 evaluate_weekly_off` | n/a | n/a | n/a | n/a | not re-read | CURRENTLY WORKING (documented as "not a documented scenario", i.e., a defensive fallback) |
| E3 ALTERNATE rule with no explicit `week_parity` | Treated as "cycle-start week is the off week" (EVEN) | Rule-level | EVEN | Yes | Yes (`week_parity` field) | `calendar_resolution.py:109-116` | `weekly_off_pattern` rule row | n/a | n/a | n/a | not re-read | CURRENTLY WORKING — but the code comment itself flags this as "no documented default", i.e. an implementation choice, not a spec'd behaviour |
| E4 Roster week-off override vs weekly-off pattern | A `ShiftRoster.is_week_off_override=True` row forces `NOT_EXPECTED` for one employee-date even on a calendar `WORKING` day (rotating crew) | Employee-date | n/a | Yes | Yes | `calculation.py:742-746, 767-769` | `shift_roster.is_week_off_override` | Calendar's own weekly-off pattern for that one date | Punches (if punches exist despite the override, presence is still evaluated — `calculation.py:742` gates on `not inputs.punches`) | n/a | `test_evaluate_day_roster_week_off_override_wins_over_working_calendar`, `test_roster_week_off_override_marks_not_expected` (integration) | CURRENTLY WORKING |

## F. Shift

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 FIXED / FLEXIBLE / SPLIT shift types | Three distinct schedule-window and evaluation strategies | Shift-version | n/a | Yes (FIXED and SPLIT fully; FLEXIBLE window resolution exists) | Yes | `calculation.py:344-429 resolve_schedule_window`, `_evaluate_split` (1130+) vs `_evaluate_fixed_or_flex` (987+) | `shift_version.shift_type` | n/a | n/a | Shift resolved but no usable timing → falls back to plain calendar-day window (`calculation.py:425-429`) | Unit: split-shift tests exist (`test_evaluate_day_split_shift_*`); **no dedicated FLEXIBLE-shift unit/integration test found** in `test_calculation.py` or the integration suite grepped | FLEXIBLE: IMPLEMENTATION GAP (window math exists, no test proves late/early/core-hours behaviour for it) |
| F2 Cross-midnight shift | `is_cross_midnight` extends the end date by 1 day; attendance date = shift start date | Shift-version | n/a | Yes | Yes | `calculation.py:294-299, 313-317` | `shift_version.is_cross_midnight` | n/a | n/a | n/a | `test_scheduled_span_cross_midnight_attributes_to_start_date` | CURRENTLY WORKING |
| F3 `required_minutes` (FLEXIBLE) | The minimum minutes a flexible-shift day must accumulate | Shift-version | n/a | Only used as an `scheduled_minutes` fallback for OT/hour-band comparison when no fixed start/end resolved (`calculation.py:1059-1060`, `1208`) — **never independently checked against `worked_minutes` for a FLEXIBLE-shift PRESENT/HALF_DAY/ABSENT decision path distinct from the hour-band lookup** | Yes (settable) | `calculation.py:151` field, used at 1059,1208 | `shift_version.required_minutes` | n/a | n/a | n/a | none found isolating FLEXIBLE evaluation | STORED, PARTIALLY USED — see Configuration Audit |
| F4 `operates_on_holiday` / `operates_on_weekly_off` | Per-shift flags that let a shift run on a holiday/weekly-off day (24x7 ops) without a roster override | Shift-version | False | Yes | Yes | `calculation.py:770-774` | `shift_version.operates_on_holiday/operates_on_weekly_off` | Calendar's own `not_expected` default | Roster override (`roster_holiday_working_override`, which is scoped to one date and ORs with this) | n/a | not isolated in unit tests directly (roster tests cover the roster-override half) | CURRENTLY WORKING |
| F5 `is_ot_eligible` (shift flag) | Gate for OT detection when `OvertimePolicyVersion.eligibility=SHIFT_FLAG` | Shift-version | n/a | Yes | Yes | `calculation.py:670-671, 1066` | `shift_version.is_ot_eligible` | n/a | `eligibility=ALWAYS`/`GRADE_VIA_ASSIGNMENT` ignore this flag entirely (see M2) | n/a | `test_detect_overtime_ineligible_shift_flag` | CURRENTLY WORKING for `SHIFT_FLAG` mode only |
| F6 Split shift duty blocks | Each `ShiftDutyBlock` is checked for ≥1 overlapping punch pair; missed blocks trigger `split_shift_missed_block_behaviour` | Shift-version child table | n/a | Yes (block-presence only, not partial-hours credit) | Yes | `calculation.py:1156-1172` | `shift_duty_block` (organisation module) | n/a | n/a | n/a | `test_evaluate_day_split_shift_detects_overtime` | CURRENTLY WORKING with documented simplification (no partial-block credit — module docstring `calculation.py:17-22`) |
| F7 Core hours (`core_start`/`core_end`) | Flexible-shift "must be present between X and Y" window | Shift-version | n/a | **No — resolved into `ShiftInputs` but never read by any evaluation branch** | Cosmetically yes (fields settable) | `service.py:2821-2826` populates them; `calculation.py` never reads `shift.core_start`/`shift.core_end` anywhere in `evaluate_day`/`_evaluate_fixed_or_flex`/`_evaluate_split` | `shift_version.core_start/core_end` | n/a | n/a | n/a | none | **STORED BUT NOT USED** |
| F8 Missing shift (`shift_id=None` and no roster) | Falls back to `missing_shift_behaviour` (INCOMPLETE default, ABSENT if configured) when no punches; evaluates presence with no schedule when punches exist | Policy-level | INCOMPLETE | Yes | Yes | `calculation.py:748-759`, `_evaluate_no_schedule` (936+) | `attendance_policy_version.missing_shift_behaviour` | n/a | Roster week-off override (checked first, `calculation.py:742`) | n/a | `test_evaluate_day_missing_shift_no_punches_incomplete_by_default`, `..._absent_when_policy_says_absent`, `test_roster_null_shift_without_override_falls_through_to_missing_shift_behaviour` | CURRENTLY WORKING |

## G. Breaks

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| G1 FIXED_WINDOW / FLEXIBLE_DURATION break kinds matched against detected punch gaps | A break is only recognised if a punch-out/punch-in gap's local start time falls inside the break's configured window | Shift-version child table | n/a | Yes | Yes | `calculation.py:543-586 match_breaks` | `shift_break` (organisation module) | n/a | n/a | Unmatched gap defaults **unpaid** (conservative) | `test_unpaid_break_gap_already_excluded_not_double_subtracted`, `test_paid_break_gap_added_back_to_worked_minutes` | CURRENTLY WORKING |
| G2 Paid vs unpaid break minutes | Paid break minutes are added back into `worked_minutes`; unpaid are excluded (arithmetic differs by `multi_punch_mode`, see J-pipeline) | Shift-break-level | n/a | Yes | Yes | `calculation.py:519-536 worked_minutes_from_gross` | `shift_break.is_paid` | n/a | n/a | n/a | both tests above | CURRENTLY WORKING |
| G3 Mandatory break with zero punched gap | A `ShiftBreak.is_mandatory=True` break the employee never actually took (no punch gap at all) is **never auto-deducted** — `AttendancePolicyVersion` has no `DEDUCT_SCHEDULED` field despite the architecture doc naming that behaviour | Shift-break-level | n/a | **No** | `is_mandatory` is stored and read into `ShiftBreakData` (`calculation.py:72`) but never branches on in `match_breaks`/`worked_minutes_from_gross` | `models.py` `ShiftBreak.is_mandatory` (organisation module); `calculation.py:64-72` carries it through unused | n/a | n/a | n/a | n/a | none | KNOWN LIMITATION — explicitly documented as such in the module's own docstring (`calculation.py:23-28`), not a silently discovered gap |
| G4 Excess break (`is_excess`, `excess_break_minutes`) | A matched break longer than its `max_minutes` is flagged | Shift-break-level | n/a | Detection: yes. Consequence: **no** — `excess_break_behaviour` (IGNORE/DEDUCT/FLAG/REQUIRE_APPROVAL) is stored on the policy, resolved into `PolicyInputs.excess_break_behaviour`, but never read anywhere in `calculation.py`'s evaluation logic | Cosmetically yes | `calculation.py:113,129` (field only), `575` (detection) | `attendance_policy_version.excess_break_behaviour`, `attendance_day.excess_break_minutes` | n/a | n/a | n/a | none | **STORED BUT NOT USED** (behaviour value has zero effect; only the raw minute count and flag are stored, informationally) |
| G5 Multiple breaks / overlap | Each detected gap matches at most one `ShiftBreakData` (`best`, first hit wins) | n/a | n/a | Yes | No explicit overlap-resolution config | `calculation.py:557-573` | n/a | n/a | n/a | n/a | none isolating overlap specifically | CURRENTLY WORKING (first-match, undocumented tie-break — see Hidden Rules) |

## H. Attendance Policy

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 Grace in/out | Minutes of lateness/early-departure forgiven before `late_minutes`/`early_departure_minutes` start counting | Policy-version | 0/0 | Yes | Yes | `calculation.py:1028-1038` | `attendance_policy_version.grace_in_minutes/grace_out_minutes` | n/a | n/a | n/a | `test_evaluate_day_late_beyond_grace` | CURRENTLY WORKING |
| H2 Punch rounding | Round punch instants to nearest/up/down N minutes before math | Policy-version | NONE | **No — `apply_rounding`/`round_minutes` are defined but never called from `evaluate_day` or any of its helpers on punch instants** | Cosmetically yes | `calculation.py:594-613` (defined, unused for punches); only `round_minutes` is reused for **OT-minutes** rounding (`detect_overtime`, `calculation.py:678`) | `attendance_policy_version.punch_rounding/rounding_minutes` | n/a | n/a | n/a | `test_round_minutes_up_down_nearest` (tests the pure function only, not its application to a punch) | **STORED BUT NOT USED** (for punch-time rounding; the same primitive *is* genuinely used for OT-minute rounding, see M-category) |
| H3 Missing punch behaviour | INCOMPLETE (default) / ABSENT / AUTO_CLOSE / REQUIRE_REGULARIZATION | Policy-version | INCOMPLETE | INCOMPLETE and ABSENT: yes. AUTO_CLOSE: **partial — falls through to band-based status but never actually closes the day or sets `auto_closed=True`**. REQUIRE_REGULARIZATION: not read as a distinct branch in `_resolve_primary_status` (falls into the generic missing-punch `else` → INCOMPLETE) | Yes (settable, but 2 of 4 values behave identically to INCOMPLETE) | `calculation.py:1296-1302` | `attendance_policy_version.missing_punch_behaviour` | n/a | n/a | n/a | `test_evaluate_day_no_punches_working_day_defaults_incomplete`, `..._absent_when_policy_says_absent` — **no test exercises AUTO_CLOSE or REQUIRE_REGULARIZATION** | IMPLEMENTATION GAP (AUTO_CLOSE), DOCUMENTATION GAP (REQUIRE_REGULARIZATION has no distinct code path) |
| H4 `auto_close_after_minutes` / `auto_close_uses_shift_end` | Configuration for *how* an AUTO_CLOSE would synthesize a closing punch | Policy-version | None / True | **No — never read anywhere outside CRUD serialization** | Cosmetically yes | grep confirms zero references outside `models.py`/`schemas.py`/`service.py` CRUD assembly (`service.py:376-377`) | `attendance_policy_version.auto_close_after_minutes/auto_close_uses_shift_end` | n/a | n/a | n/a | none | **STORED BUT NOT USED** |
| H5 Half-day split (`half_day_split`/`half_day_boundary_minutes`) | BY_HOURS vs BY_MIDPOINT half-day determination method | Policy-version | BY_HOURS | **No — both fields are declared on `PolicyInputs` and never referenced in any evaluation branch.** Half-day is actually decided purely by `AttendancePolicyHourBand` lookups (worked-minutes thresholds) | Cosmetically yes | `calculation.py:106-107` (declared, unused) | `attendance_policy_version.half_day_split/half_day_boundary_minutes` | n/a | n/a | n/a | none | **STORED BUT NOT USED** |
| H6 Multi-punch mode | PAIR_ALL (sum all IN/OUT pairs) vs FIRST_IN_LAST_OUT (span first-in to last-out) | Policy-version | PAIR_ALL | Yes | Yes | `calculation.py:489-536` | `attendance_policy_version.multi_punch_mode` | n/a | n/a | n/a | `test_presence_span_pair_all_excludes_gap`, `..._first_in_last_out_includes_gap` | CURRENTLY WORKING |
| H7 Duplicate punch window | Consecutive same-direction punches within N seconds collapse to the first | Policy-version | 60s | Yes | Yes | `calculation.py:437-452` | `attendance_policy_version.duplicate_punch_window_seconds` | n/a | n/a | n/a | `test_collapse_duplicate_punches_within_window`, `..._outside_window_kept` | CURRENTLY WORKING |
| H8 Core-hours breach behaviour (flex) | IGNORE/FLAG/HALF_DAY/ABSENT for a flexible-shift core-hours violation | Policy-version | FLAG | **No — field carried on `PolicyInputs`, never read** | Cosmetically yes | `calculation.py:110` | `attendance_policy_version.core_hours_breach_behaviour` | n/a | n/a | n/a | none | **STORED BUT NOT USED** (tied to F7 — since `core_start`/`core_end` are never checked, this has nothing to act on) |
| H9 Split-shift missed-block behaviour | IGNORE/HALF_DAY/ABSENT/REQUIRE_REGULARIZATION | Policy-version | HALF_DAY | Yes for IGNORE/HALF_DAY/ABSENT/REQUIRE_REGULARIZATION (maps to INCOMPLETE) | Yes | `calculation.py:1177-1195` | `attendance_policy_version.split_shift_missed_block_behaviour` | n/a | n/a | n/a | `test_evaluate_day_split_shift_detects_overtime` exercises the happy path; missed-block branches not isolated by a dedicated unit test found | CURRENTLY WORKING (code path exists and is reachable; test coverage for the HALF_DAY/ABSENT/REQUIRE_REGULARIZATION branches specifically was not found — see Test Coverage Audit) |
| H10 WFH / On-duty punch rules | `wfh_requires_punch`/`on_duty_requires_punch`/`wfh_uses_shift_hours` | Policy-version | True/False/True | **No — never read in `calculation.py`; `WFH`/`ON_DUTY` are never produced as `attendance_status` values anywhere in the engine** (comment at `calculation.py:1283` explicitly calls these "W4 no-ops") | Cosmetically yes | field declarations only | `attendance_policy_version.wfh_requires_punch/on_duty_requires_punch/wfh_uses_shift_hours` | n/a | n/a | n/a | none | **STORED BUT NOT USED** — `WFH`/`ON_DUTY` exist only as regularization request types (§L) and as CHECK-constraint-legal `attendance_status` values that the engine never writes |
| H11 Work-on-leave behaviour | KEEP_LEAVE (default) vs PRESENT_CANCEL_LEAVE_HINT | Policy-version | KEEP_LEAVE | Yes | Yes | `calculation.py:822-878 _apply_leave_overlay` | `attendance_policy_version.work_on_leave_behaviour` | n/a | n/a | n/a | `test_full_day_leave_keep_leave_behaviour_overrides_punches`, `..._present_cancel_leave_hint_flags_and_keeps_punch_status` | CURRENTLY WORKING (W9) |
| H12 Late/early band classification | Ordered minute ranges → LATE/HALF_DAY/ABSENT (late) or EARLY_DEPARTURE/HALF_DAY/ABSENT (early) | Policy-version child tables | n/a | Yes | Yes | `calculation.py:621-628 lookup_band`, `1032,1038` | `attendance_policy_late_band`, `attendance_policy_early_departure_band` | n/a | n/a | No band matches → `None` classification (silently no consequence beyond raw minutes) | `test_lookup_band_matches_ordered_ranges`, `..._no_match_returns_none`, `test_evaluate_day_late_beyond_grace` | CURRENTLY WORKING |
| H13 `counts_toward_cap` on late/early bands | Declared per band but... | Band-level | True | **No consumer found** — `counts_toward_cap` is read into `AttendancePolicyLateBand`/`EarlyDepartureBand` rows (models.py:183,203) but `BandData`/`lookup_band` never carries or reads this field | Cosmetically yes | `models.py:183,203`; absent from `calculation.py`'s `BandData` (calculation.py:83-88) | `attendance_policy_late_band.counts_toward_cap`, `..._early_departure_band.counts_toward_cap` | n/a | n/a | n/a | none | **STORED BUT NOT USED** — ties to H14 (the cap it's meant to count toward doesn't exist either) |
| H14 Late-count window / lates-to-half-day-count / early-departure-requires-approval | A rolling-window "N lates = 1 half day" penalty and an early-departure approval gate | Policy-version | MONTH / None / False | **No — none of the three fields are referenced anywhere in `calculation.py` or `service.py`'s calculation path** | Cosmetically yes | field declarations only (`models.py:132-134`) | `attendance_policy_version.late_count_window/lates_to_half_day_count/early_departure_requires_approval` | n/a | n/a | n/a | none | **STORED BUT NOT USED** |
| H15 Incomplete-at-lock behaviour | TREAT_ABSENT (default) / TREAT_PRESENT / KEEP_INCOMPLETE, resolved at period finalize time | Policy-version | TREAT_ABSENT | **Yes — the one policy-version field in this whole audit that is genuinely read and applied outside CRUD**, both as a finalize-blocker (`KEEP_INCOMPLETE`) and as an auto-resolution (`TREAT_ABSENT`/`TREAT_PRESENT`) | Yes | `service.py:4688-4722` (blocker), `service.py:4920-4955 _apply_incomplete_lock_resolution` | `attendance_policy_version.incomplete_at_lock_behaviour` | n/a | n/a | n/a | `test_finalize_blocked_incomplete_with_keep_incomplete_policy`, `test_finalize_resolves_incomplete_with_default_treat_absent_policy` | **CONFIGURABLE AND WORKING** |

## I. Punches

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| I1 Punch immutability | `Punch` rows are never UPDATE'd/DELETE'd; corrections are new rows | n/a (architectural) | n/a | Yes | No | `models.py:417-434` (no `updated_at`, no update/delete methods found in `repository.py` for punches) | `punch` table | n/a | n/a | n/a | `test_punch_idempotency_key_replays_same_row` | CURRENTLY WORKING |
| I2 IN/OUT ordering & pairing | Deterministic pairing; consecutive same-direction punches produce orphans | n/a | n/a | Yes | No | `calculation.py:460-486 pair_punches` | n/a | n/a | n/a | 5 dedicated unit tests (`test_pairing_*`) | CURRENTLY WORKING |
| I3 Idempotency key | Partial unique index on `(company_id, idempotency_key)` — exact resubmission guard | Caller-supplied | n/a | Yes | Yes (caller opts in) | `models.py:430-434` (comment), `repository.py` insert path | `punch.idempotency_key` | n/a | n/a | No key supplied → no idempotency guard at insert time (relies on calc-time duplicate collapsing instead) | `test_punch_idempotency_key_replays_same_row` | CURRENTLY WORKING |
| I4 Source tagging | `source` distinguishes WEB/MANUAL/API/REGULARIZATION/ADMIN/DEVICE | Per-punch | n/a | Yes | n/a | `models.py:447` | `punch.source` | n/a | n/a | n/a | implicit in regularization tests (`source='REGULARIZATION'`) | CURRENTLY WORKING (device sources reserved for future W10, per model docstring `models.py:432`) |
| I5 On-behalf punch permission | `ATTENDANCE.PUNCH_ON_BEHALF` gate + DataScope check for who may punch for whom | RBAC | n/a | Yes | Yes (role grants) | router-level dependency (not re-read line-by-line; confirmed via `permissions.py:20` + test) | `role_permission` | n/a | n/a | n/a | `test_on_behalf_punch_requires_permission`, `..._reportees_scope_blocks_target_outside_visible_set` | CURRENTLY WORKING |
| I6 Punch rejected when period closed | A closed `AttendancePeriod` refuses new punches for dates it covers | Period-level | n/a | Yes | No (fail-closed, no override) | `service.py:2343 _ensure_date_open` | `attendance_period.status` | n/a | n/a | n/a | `test_punch_rejected_for_closed_period_date` | CURRENTLY WORKING |

## J. Attendance Calculation (pipeline — see also Section 6 in the master audit)

| Rule | Meaning | Status |
|---|---|---|
| J1 Full recompute, never patch | Every `calculate()` call fully replaces derived fields (WD-10) | CURRENTLY WORKING — `service.py:2478-2624`, `calculation_version` incremented each time |
| J2 Idempotent-with-one-documented-exception | Same punches+versions ⇒ same result, **except** OT detection can vary run-to-run because `remaining_weekly_minutes`/`remaining_monthly_minutes` depend on sibling-day `overtime_record` state at call time | KNOWN LIMITATION — explicitly documented, `calculation.py:29-34` (WD-29 decision 3) |
| J3 Fail-closed on unresolved calendar/policy | No calendar or no policy resolved ⇒ `CONFIG_ERROR`, never a guessed default | CURRENTLY WORKING — `calculation.py:729-734`; `test_evaluate_day_config_error_no_calendar/no_policy` |
| J4 Locked-day refusal | `calculate()` checks `is_locked` before and (racily) after building the calc input | CURRENTLY WORKING — `service.py:2506-2507, 2572-2575`; `test_locked_day_refuses_recompute` |
| J5 Snapshot/reproducibility | Every version FK actually used is stored on `AttendanceDay`, plus a JSONB `computation_snapshot` trace | CURRENTLY WORKING — `models.py:493-511,560`; snapshot built throughout `calculation.py` (`snapshot[...]=` assignments) |

## K. Leave (W9 projection overlay — Leave module itself does not exist)

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| K1 Only APPROVED projections visible | `LeaveDayProjection.status='CANCELLED'` rows are invisible to calculation | Fact-level | n/a | Yes | No | `repository.py` `list_active_for_employee_date` (filters status), consumed `service.py:3031-3039` | `leave_day_projection.status` | n/a | n/a | n/a | `test_cancel_projection_reverts_attendance_to_punch_derived_outcome` | CURRENTLY WORKING |
| K2 Full-day leave (fraction sum ≥ 1.00) | Wins outright — ranks above `NOT_EXPECTED`; sets `attendance_status=LEAVE`, zeroes late/early, sets paid/lop from leave's own paid flag | n/a | n/a | Yes | No (a fixed precedence rule, not configurable) | `calculation.py:849-864` | n/a | Calendar `NOT_EXPECTED` (HOLIDAY/WEEKLY_OFF `calendar_day_type` itself is untouched, only `attendance_status`) | Population gate (NOT_JOINED/EXITED) and CONFIG_ERROR — leave overlay is skipped for those | `test_full_day_leave_keep_leave_behaviour_overrides_punches`, `test_leave_overrides_roster_week_off_not_expected` | CURRENTLY WORKING |
| K3 Half-day leave (0<fraction<1.00) | Remaining half contributed from the punch-derived outcome as a flat 0.50, not minute-level re-evaluation | n/a | n/a | Yes (documented simplification) | No | `calculation.py:866-879` | n/a | n/a | n/a | `test_sync_half_day_paid_leave_no_punches`, `test_half_day_unpaid_leave_with_full_day_punches`, `test_multiple_half_day_projections_sum_to_full_day` | CURRENTLY WORKING with documented simplification (`calculation.py:35-39`) — no AM/PM-specific minute math, `half` field carried for provenance only |
| K4 Sum-to-at-most-1.00 enforcement | Multiple active projections for one employee-date cannot exceed 1.00 combined | Service-layer validation | n/a | Yes | No | `service.py:5167-5179` | n/a (service-level, not a DB CHECK — cross-row sum can't be a CHECK) | n/a | n/a | n/a | `test_overlapping_leave_fractions_rejected` | CURRENTLY WORKING |
| K5 Leave vs locked period | Sync/cancel both refuse when the period is closed | Period-level | n/a | Yes | No | `service.py:5158, 5288` | n/a | n/a | n/a | `test_sync_refused_when_period_closed`, `test_cancel_refused_when_period_closed` | CURRENTLY WORKING |
| K6 Work-on-leave hint vs cancel | `PRESENT_CANCEL_LEAVE_HINT` never cancels the leave itself — only raises `work_on_leave_flagged` for a (non-existent) Leave module to consume | Policy-level | KEEP_LEAVE | Yes (the flag), but there is no Leave module to *act* on the flag yet | Yes | `calculation.py:846-847,867-868` | `attendance_day.work_on_leave_flagged` | n/a | n/a | n/a | `test_full_day_leave_present_cancel_hint_flags_and_keeps_punch_status` | CURRENTLY WORKING as designed, but its consumer (Leave module) is FUTURE MODULE |
| K7 Leave entitlement/balance/accrual/approval | Not owned by Attendance at all | n/a | n/a | No | n/a | `models.py:947-954` docstring is explicit: "not the leave ledger... entitlement/balance/accrual/approval remain entirely Leave's" | No `leave_application`/`leave_balance` tables exist in this codebase | n/a | n/a | n/a | n/a | **FUTURE MODULE** |

## L. Regularization

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L1 Applied only via synthetic punches / roster row | The only two correction mechanisms; never a new status branch in the calc engine | n/a | n/a | Yes | No | `service.py:3931-4057 _apply_correction` | `punch.source='REGULARIZATION'`, `shift_roster` | n/a | n/a | n/a | `test_manager_approval_applies_correction_and_recomputes`, `test_wrong_shift_applies_via_roster` | CURRENTLY WORKING |
| L2 Who may request (employee/manager/HR) | 3 independent boolean gates | Policy-version | All True | Yes | Yes | `service.py` submit() logic (not fully re-read line-by-line beyond gating tests) | `regularization_policy_version.allow_employee_request/allow_manager_request/allow_hr_request` | n/a | n/a | n/a | `test_on_behalf_requires_on_behalf_permission` | CURRENTLY WORKING |
| L3 Max backdated days | Rejects requests for dates further back than N days | Policy-version | None (unlimited) | Yes | Yes | tested directly | `regularization_policy_version.max_backdated_days` | n/a | n/a | n/a | `test_backdating_window_enforced` | CURRENTLY WORKING |
| L4 Max requests per month | Caps how many regularization requests one employee may submit per month | Policy-version | None | Yes | Yes | tested directly | `regularization_policy_version.max_requests_per_month` | n/a | n/a | n/a | `test_monthly_request_limit_enforced` | CURRENTLY WORKING |
| L5 Reason/attachment required | Gates submission on presence of `reason`/`attachment_reference` | Policy-version | reason required=True, attachment=False | Yes | Yes | tested directly | `regularization_policy_version.reason_required/attachment_required` | n/a | n/a | n/a | `test_reason_required_enforced` | CURRENTLY WORKING |
| L6 Allowed request types | Which of MISSING_PUNCH/WRONG_PUNCH/WRONG_SHIFT/WRONG_STATUS/WFH/ON_DUTY/EXCESS_BREAK/FULL_DAY this policy permits | Policy-version child table | n/a | Yes (gating only — see H10 for why WFH/ON_DUTY don't change the resulting status) | Yes | `service.py` submit() validation | `regularization_policy_allowed_type` | n/a | n/a | n/a | `test_disallowed_request_type_rejected` | CURRENTLY WORKING (as a submission gate; the WFH/ON_DUTY *type* itself has no special downstream handling — it becomes ordinary synthetic punches) |
| L7 Approval chain: AUTO / MANAGER / MANAGER_THEN_HR / HR | Multi-stage approval with `approval_stage` tracking whose turn is next | Policy-version | MANAGER | Yes | Yes | `service.py:3835-3931` | `regularization_policy_version.approval_chain` | n/a | n/a | n/a | `test_manager_then_hr_two_stage_chain`, `test_auto_chain_approves_and_applies_on_submit` | CURRENTLY WORKING |
| L8 Self-approval block | An employee can never approve their own request, no policy escape hatch | n/a (hard-coded) | Always blocked | Yes | **No — deliberately not configurable** | `service.py` `_get_reviewable` equivalent for regularization (same pattern as OT, `service.py:4247-4249`) | n/a | n/a | n/a | `test_self_approval_blocked` | CURRENTLY WORKING |
| L9 Auto-approve within N minutes | `auto_approve_within_minutes` field exists on the policy version | Policy-version | None | **Not verified as consumed** — `approval_chain=AUTO` (a separate field) auto-approves immediately regardless of timing; grep found no reference to `auto_approve_within_minutes` inside `service.py`'s submit/approve logic beyond CRUD assembly | Cosmetically yes | `service.py:1513` (CRUD only) | `regularization_policy_version.auto_approve_within_minutes` | n/a | n/a | n/a | none | **STORED BUT NOT USED** (distinct from the working `approval_chain=AUTO`, which *is* real) |
| L10 Blocked when locked | `blocked_when_locked` field predates any lock mechanism (shipped in W3) | Policy-version | True | **Superseded, not read** — period-lock blocking is now unconditional (`_ensure_date_open`) regardless of this field's value, per the code's own comment | Cosmetically yes (field can be set to False but has no effect) | `service.py:3410` comment: "unconditional, independent of `RegularizationPolicyVersion.blocked_when_locked`" | `regularization_policy_version.blocked_when_locked` | n/a | n/a | n/a | `test_locked_day_blocks_new_request` (tests the unconditional behaviour, not the field) | **STORED BUT NOT USED** / DOCUMENTATION GAP (a policy author could believe setting this False re-enables regularization during lock — it does not) |
| L11 Locked period blocks new requests | Fail-closed regardless of L10 | Period-level | n/a | Yes | No | `service.py:3415 _ensure_date_open` | `attendance_period.status` | n/a | n/a | n/a | `test_locked_day_blocks_new_request`, `test_regularization_submit_rejected_for_closed_period_date` | CURRENTLY WORKING |
| L12 Approved correction recomputes the day | `_apply_correction` calls `AttendanceDayService.calculate()` in the same transaction | n/a | n/a | Yes | No | `service.py:4050-4057` | n/a | n/a | n/a | `test_manager_approval_applies_correction_and_recomputes` | CURRENTLY WORKING |
| L13 Rejected request leaves attendance unchanged | No punches/roster written on rejection | n/a | n/a | Yes | No | `reject()` (service.py, not shown above but symmetrical to OT `reject`) | n/a | n/a | n/a | `test_reject_leaves_attendance_unchanged` | CURRENTLY WORKING |

## M. Overtime

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 Eligibility modes | SHIFT_FLAG / ALWAYS / NEVER / GRADE_VIA_ASSIGNMENT | Policy-version | SHIFT_FLAG | NEVER and SHIFT_FLAG: yes. **ALWAYS and GRADE_VIA_ASSIGNMENT are never distinguished from each other — both fall through the same "no gate" path, i.e. GRADE_VIA_ASSIGNMENT behaves identically to ALWAYS regardless of the employee's actual grade** | Yes (settable, but 2 of 4 values are indistinguishable) | `calculation.py:666-671` — only `NEVER` and `SHIFT_FLAG` have explicit branches | `overtime_policy_version.eligibility` | n/a | n/a | n/a | `test_detect_overtime_ineligible_shift_flag` — **no test exercises GRADE_VIA_ASSIGNMENT actually reading a grade** | IMPLEMENTATION GAP — matches the pre-W7 finding; unchanged by W7 |
| M2 Min OT minutes | Detected excess below this threshold is discarded (returns 0) | Policy-version | 0 | Yes | Yes | `calculation.py:673-675` | `overtime_policy_version.min_ot_minutes` | n/a | n/a | n/a | `test_detect_overtime_below_minimum_not_counted` | CURRENTLY WORKING |
| M3 OT rounding | Rounds the *excess* minutes (not punch instants) to nearest/up/down N | Policy-version | None/NONE | Yes | Yes | `calculation.py:677-678` | `overtime_policy_version.rounding_minutes/rounding_mode` | n/a | n/a | n/a | `test_daily_threshold_and_rounding_applied` (integration) | CURRENTLY WORKING |
| M4 Daily/weekly/monthly caps | Detected OT is clamped to whichever cap is tightest | Policy-version | None (uncapped) | Yes | Yes | `calculation.py:680-685`; weekly/monthly remaining computed in `service.py:2954-2983` (DB-dependent, sibling-day sums) | `overtime_policy_version.daily_cap_minutes/weekly_cap_minutes/monthly_cap_minutes` | n/a | n/a | n/a | `test_detect_overtime_caps_at_daily_cap`, `..._weekly_cap_clamps_below_daily_cap`, `..._monthly_cap_clamps`, `..._weekly_cap_exhausted_still_eligible_zero_minutes`, `test_weekly_cap_clamps_second_day_in_same_week` (integration) | CURRENTLY WORKING — but see J2: caps make `evaluate_day` order-dependent across sibling days (documented, not a bug) |
| M5 Day-class classification (NORMAL/WEEKLY_OFF/HOLIDAY/NIGHT) | Determines which `OvertimePolicyRateRow.classification_code` applies | n/a | n/a | Partial — HOLIDAY/WEEKLY_OFF/NORMAL: yes. **NIGHT: only reachable when `night_ot_mode` is WINDOW or BOTH, and even then `is_night` is computed solely from `shift.is_cross_midnight` — the configured `night_window_start`/`night_window_end` are never compared against actual punch times** | Yes (settable, but NIGHT classification is decoupled from the configured window) | `calculation.py:636-650 classify_ot_day`; `is_night = shift.is_cross_midnight` at `calculation.py:1062,1212,1229` | `overtime_policy_version.night_ot_mode/night_window_start/night_window_end` | n/a | n/a | n/a | `test_classify_ot_day_holiday_wins_over_weekly_off_and_night`, `..._weekly_off_wins_over_night`, `..._night_requires_window_or_both_mode`, `..._normal_default` (all pure-function tests of `classify_ot_day`, which only ever receives `is_night` computed from cross-midnight — **no test proves the window itself is checked, because it isn't**) | **IMPLEMENTATION GAP / STORED-BUT-PARTIALLY-USED** — `night_ot_mode` gates the *branch*, but `night_window_start/end` never gate anything; default (`SHIFT_FLAG`) never produces NIGHT at all |
| M6 Approval chain (AUTO/MANAGER/MANAGER_THEN_HR/HR) | Same 4-value model as regularization | Policy-version | MANAGER | Yes | Yes | `service.py:3072-3161 _resolve_ot_decision` | `overtime_policy_version.approval_chain` | n/a | n/a | n/a | `test_auto_chain_auto_approves_immediately`, `test_manager_chain_pending_then_approved_updates_day`, `test_hr_chain_requires_company_scope`, `test_manager_then_hr_two_stage_chain` | CURRENTLY WORKING |
| M7 `requires_post_approval` | If False, engine auto-approves detected OT immediately, no human review at all | Policy-version | True | Yes | Yes | `calculation.py:1077-1080`, `service.py:3106` | `overtime_policy_version.requires_post_approval` | n/a | `approval_chain=AUTO` forces auto-approval even if this is True (WD-29 decision 4) | n/a | `test_requires_post_approval_false_auto_approves_without_auto_chain` | CURRENTLY WORKING |
| M8 Self-approval block | No employee can approve their own detected OT | n/a | Always blocked | Yes | No | `service.py:4247-4249` | n/a | n/a | n/a | `test_self_approval_blocked` (OT suite) | CURRENTLY WORKING |
| M9 No manager resolved → routes to HR | Same pattern as regularization | n/a | n/a | Yes | No | `service.py:3116-3121` | n/a | n/a | n/a | `test_no_manager_resolved_routes_to_hr` (OT suite) | CURRENTLY WORKING |
| M10 Frozen terminal decisions | Once `APPROVED`/`AUTO_APPROVED`/`REJECTED`, a later recompute never overwrites the record's decision fields | n/a | n/a | Yes | No | `service.py:3089-3097` | `overtime_record.status` | n/a | n/a | n/a | `test_approved_overtime_frozen_across_later_recompute` | CURRENTLY WORKING |
| M11 Comp-off instead of pay + expiry | Converts approved OT minutes into `comp_off_minutes` with an expiry date | Policy-version | False / None | Yes | Yes | `calculation.py:1081-1082`, `service.py:3138-3140` | `overtime_policy_version.comp_off_instead_of_pay/comp_off_expiry_days`, `overtime_record.comp_off_minutes/comp_off_expiry_date` | n/a | n/a | Comp-off minutes are a policy-computed *fact* stored regardless of approval state, but only credited to the day's payroll-facing summary once actually decided (`service.py:2540-2541`) | `test_comp_off_fact_with_expiry_on_auto_approval`, `test_comp_off_not_credited_to_day_while_pending` | CURRENTLY WORKING — **no expiry-lapse/redemption mechanism exists anywhere** (no code consumes `comp_off_expiry_date` to invalidate a stale comp-off; that would be a payroll/leave-ledger concern not yet built) — flag as FUTURE MODULE for the expiry-enforcement half specifically |
| M12 Configured multiplier | `OvertimePolicyRateRow.multiplier_decimal` — informational only, never applied as money | Policy-version child table | n/a | Yes (as a stored, snapshotted fact) | Yes | `models.py:227-229` docstring is explicit: "no monetary calculation... never applied as money here" | `overtime_policy_rate_row.multiplier_decimal`, snapshotted onto `overtime_record.configured_multiplier` | n/a | n/a | n/a | `test_overtime_policy_resolves_and_day_snapshots_version` | CURRENTLY WORKING as a payroll-facing *fact*, by design never used for calculation (ADR-0006 — money stays out of Attendance) |
| M13 SPLIT-shift OT | Previously never detected; W7 wires `detect_overtime` into `_evaluate_split` using `shift.required_minutes` as the schedule baseline | Shift-type-specific | n/a | Yes | Yes | `calculation.py:1206-1231` | n/a | n/a | n/a | `test_evaluate_day_split_shift_detects_overtime`, `..._no_overtime_policy_detects_nothing` | CURRENTLY WORKING (new in this diff, W7) |

## N. Period Finalization / Lock

| Rule | Meaning | Config level | Default | Applied? | Customizable? | Code | DB | Overrides | Overridden by | Missing | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| N1 Two states only: OPEN/CLOSED | No durable "CLOSING" state — finalize is one synchronous transaction | n/a | OPEN | Yes | No | `models.py:816-824` docstring | `attendance_period.status` | n/a | n/a | n/a | `test_create_period_opens_immediately_and_lists` | CURRENTLY WORKING |
| N2 No period overlap | GiST exclusion constraint per company | DB constraint | n/a | Yes | No | migration `20260824090000_attendance_period.py:93` `EXCLUDE USING gist` | `attendance_period` | n/a | n/a | n/a | `test_overlapping_period_rejected` | CURRENTLY WORKING |
| N3 Validation blockers (6 codes) | EMPLOYEES_WITHOUT_ATTENDANCE, CONFIG_ERROR, INCOMPLETE_ATTENDANCE (KEEP_INCOMPLETE only), PENDING_REGULARIZATION, PENDING_OVERTIME_APPROVAL, UNPUBLISHED_ROSTER | Period-scoped, computed | n/a | Yes, all 6 | No (fail-closed, not configurable which blockers apply) | `service.py:4616-4799 _run_validation` | n/a | n/a | n/a | one dedicated test per blocker: `test_finalize_blocked_missing_employee_attendance`, `..._config_error`, `..._incomplete_with_keep_incomplete_policy`, `..._pending_regularization`, `..._pending_overtime_approval`, `..._unpublished_roster` | CURRENTLY WORKING — comprehensively tested |
| N4 Missing blocker: PENDING_LEAVE_PROJECTION | No blocker exists for an unresolved/pending leave projection state (Leave module has no "pending" concept — only APPROVED/CANCELLED) | n/a | n/a | N/A | n/a | absent from `_run_validation`'s 6 checks | n/a | n/a | n/a | n/a | none needed (no pending state exists in this model) | Not a gap — consistent with K1's "only APPROVED visible" design |
| N5 Finalize freezes summary, locks days | One transaction: version-guarded CLOSED write → incomplete-resolution → summary snapshot insert → bulk day lock | n/a | n/a | Yes | No | `service.py:4957-5055 finalize` | `attendance_period_summary`, `attendance_day.is_locked` | n/a | n/a | n/a | `test_validate_ready_and_finalize_locks_days_and_freezes_summary` | CURRENTLY WORKING |
| N6 Mutation blocking during lock | Punch/roster/regularization-submit/recompute/OT-approve/leave-sync/leave-cancel all refuse a closed-period date | Period-level | n/a | Yes, all 7 mutation surfaces confirmed via `_ensure_date_open` call sites | No | `service.py:1911` + 11 call sites (§ list in master audit) | `attendance_period.status` | n/a | n/a | n/a | `test_punch_rejected_for_closed_period_date`, `..._roster_create_rejected...`, `..._regularization_submit_rejected...`, `..._recompute_rejected...`, `..._overtime_approve_rejected...`, `test_sync_refused_when_period_closed`, `test_cancel_refused_when_period_closed` | CURRENTLY WORKING — comprehensively tested across every mutation type |
| N7 Reopen | Clears `is_locked` across the range; does not recompute or restore; re-finalize regenerates a fresh summary (full delete/recreate) | RBAC-gated (`ATTENDANCE.UNLOCK`, separate from `.LOCK`) | n/a | Yes | No | `service.py:5057-5124` | n/a | n/a | n/a | `test_reopen_unlocks_days_and_refinalize_regenerates_summary`, `test_unlock_requires_separate_permission` | CURRENTLY WORKING |
| N8 `legal_entity_id` grain | Reserved column, always NULL in V1 — period grain is company-only | n/a | Company grain | Yes (as the only grain implemented) | **No — explicitly an open product decision (PD-LOCK-1), cannot be evaluated until Payroll exists** | `models.py:829-834` | `attendance_period.legal_entity_id` | n/a | n/a | n/a | n/a | OPEN PRODUCT DECISION |
| N9 Concurrency safety | Version-guarded (optimistic concurrency) writes on period create/finalize/reopen and on OT/regularization approve | n/a | n/a | Yes | No | `service.py` `expected_version` params throughout | `*.version` columns | n/a | n/a | n/a | `test_stale_if_match_on_finalize_rejected`, `test_simultaneous_finalize_only_one_wins`, and equivalents for OT/regularization | CURRENTLY WORKING |

## O. Payroll Facts

| Rule | Meaning | Status |
|---|---|---|
| O1 `paid_day_fraction`/`lop_fraction` | The only two fields Attendance computes that are directly payroll-consumable, per status (`calculation.py:1317-1326`, plus leave overlay at `calculation.py:849-878`) | CURRENTLY WORKING |
| O2 `ot_minutes_detected`/`ot_minutes_approved` | Detected vs. approved OT minutes, separately tracked | CURRENTLY WORKING |
| O3 `worked_on_holiday`/`worked_on_weekly_off` flags | Boolean facts for payroll to key off (e.g. holiday-work pay rules) — Attendance does not compute any monetary consequence itself | CURRENTLY WORKING (facts only) |
| O4 `comp_off_minutes_earned` | Comp-off fact, see M11 | CURRENTLY WORKING (fact only; no redemption/expiry engine) |
| O5 `AttendancePeriodSummary` | The one payroll-facing roll-up table, frozen at finalize, never carries rupees (ADR-0005) | CURRENTLY WORKING — `models.py:899-938` |
| O6 What Attendance does NOT calculate | No monetary OT pay, no salary, no statutory deduction, no payslip — all explicitly out of scope per ADR-0006/ADR-0005 and confirmed by the absence of any Payroll module in this repo | Consistent with architecture — **FUTURE MODULE** (Payroll itself) |

---

*Compiled 2026-08-21 against the working tree described in the master audit. Every "STORED BUT NOT
USED" row above was confirmed by `grep`-ing every occurrence of the field name across
`calculation.py`/`service.py`/`repository.py` and finding no consumption beyond CRUD
serialization — see `ATTENDANCE_CONFIGURATION_AUDIT.md` for the consolidated false-customization
table and exact grep evidence.*



<!-- ============================================================ -->
<!-- SOURCE FILE: ATTENDANCE_OVERRIDE_MATRIX.md -->
<!-- ============================================================ -->

# Attendance Override Matrix

Companion to `ATTENDANCE_RULE_COMPLETENESS_AUDIT.md`. Covers spec Section 7. "Configurable?"
means whether the precedence itself (not the underlying values) can be changed by configuration.
"Current Status" cites the code that actually implements the precedence — every row was traced to
a specific line, not inferred from the architecture narrative alone.

| Rule A | Rule B | Winner | Why | Configurable? | Current Status |
|---|---|---|---|---|---|
| Employee-scope policy | Company-scope policy | Employee | 8-level scope walk `EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH > LEGAL_ENTITY > COMPANY`; first matching `PolicyAssignment` wins | No — the order itself is hard-coded (`calendar_resolution.py:48-57`) | CURRENTLY WORKING |
| Employee-scope policy | Shift-scope policy | Employee | Same 8-level walk, EMPLOYEE ranks above SHIFT | No | CURRENTLY WORKING |
| Shift-scope policy | Designation-scope policy | Shift | Same walk | No | CURRENTLY WORKING |
| Designation-scope policy | Grade-scope policy | Designation | Same walk | No | CURRENTLY WORKING |
| Grade-scope policy | Department-scope policy | Grade | Same walk | No | CURRENTLY WORKING |
| Department-scope policy | Branch-scope policy | Department | Same walk | No | CURRENTLY WORKING |
| Branch-scope policy | Legal-entity-scope policy | Branch | Same walk | No | CURRENTLY WORKING |
| Legal-entity-scope policy | Company-scope policy | Legal entity | Same walk (last tier before company) | No | CURRENTLY WORKING |
| Roster shift | Assignment shift | Roster (if `PUBLISHED`) | `service.py:2764-2768` — `shift_id = roster_entry.shift_id if roster_entry is not None else assignment.shift_id` | No — roster always wins when a `PUBLISHED` row exists for the date; no config flag to prefer assignment instead | CURRENTLY WORKING (W5) |
| Roster shift | Shift policy (resolved through the 8-level walk) | N/A — different axes | Roster determines *which shift ID* is used; the 8-level walk determines *which attendance/OT/regularization policy* applies. These are orthogonal, not competing, resolutions — a roster-assigned shift's own `is_ot_eligible`/`operates_on_holiday` flags still feed into whichever policy wins the separate policy-precedence walk | N/A | Not a real conflict — see note below |
| Calendar exception (SHUTDOWN/SPECIAL_WORKING/SUBSTITUTE_HOLIDAY) | Holiday | Exception | `calendar_resolution.py:138-163` — exception always wins first, before the holiday union is even consulted | No | CURRENTLY WORKING |
| Calendar exception (CANCEL_HOLIDAY) | Weekly Off | Falls through to weekly-off check | `calendar_resolution.py:164-167` — CANCEL_HOLIDAY removes the holiday match for that date only, then the ordinary weekly-off/working check runs | No | CURRENTLY WORKING |
| Holiday | Weekly Off | Weekly Off (holiday-on-weekly-off case) | `calendar_resolution.py:208-218` — a hard holiday landing on a weekly-off day stays `WEEKLY_OFF`, flagged `holiday_on_weekly_off=True`; **no auto-substitute** | **No — open product decision PD-CAL-2**, explicitly flagged in the code comment as having no configuration to change it | OPEN PRODUCT DECISION |
| Special Working Day | Holiday | Special Working Day | It's an exception type (`SPECIAL_WORKING`) that, per the precedence table above, is checked before the holiday union | No | CURRENTLY WORKING |
| Shutdown | Working Day | Shutdown | Exception wins over the default WORKING classification the same way | No | CURRENTLY WORKING |
| Cancelled Holiday | Weekly Off | Weekly Off (if the date also matches a weekly-off rule) | CANCEL_HOLIDAY only removes the holiday; if the date independently matches a weekly-off rule, it still resolves WEEKLY_OFF (`calendar_resolution.py:177-180`) | No | CURRENTLY WORKING |
| Substitute Holiday | Working Day | Substitute Holiday (becomes HOLIDAY) | `calendar_resolution.py:157-163` — an explicit `SUBSTITUTE_HOLIDAY` exception row always produces `day_type=HOLIDAY` | Yes, in the sense that HR must manually create the exception row (no automatic Sunday-holiday → Monday-substitute rule) | CURRENTLY WORKING, manually-triggered only |
| Leave (full-day) | Absence (ABSENT/INCOMPLETE) | Leave | `calculation.py:849-864` — full-day leave (`total_fraction >= 1.00`) replaces `attendance_status` with `LEAVE` and zeroes late/early regardless of what the punch-derived outcome would otherwise have been (unless `PRESENT_CANCEL_LEAVE_HINT`) | Yes — `work_on_leave_behaviour` policy field genuinely gates this (KEEP_LEAVE vs PRESENT_CANCEL_LEAVE_HINT) | CURRENTLY WORKING |
| Leave (full-day) | NOT_EXPECTED (calendar) | Leave | Explicitly documented in `calculation.py:812-817` — full-day leave ranks above calendar `NOT_EXPECTED`, so it can apply even on a holiday/weekly-off date Leave has (redundantly) projected as covered; `calendar_day_type` itself is untouched | No | CURRENTLY WORKING |
| Leave (full-day) | Holiday (calendar_day_type) | Leave overrides `attendance_status` only; `calendar_day_type` still reports HOLIDAY | Same mechanism as above — the overlay never touches `calendar_day_type`, only status/fractions | No | CURRENTLY WORKING (deliberate split: two different fields answer two different questions) |
| Leave (full-day) | Punch (presence) | Leave (KEEP_LEAVE, default) or Punch (PRESENT_CANCEL_LEAVE_HINT, non-default) | `calculation.py:846-864` | Yes | CURRENTLY WORKING |
| Leave | Overtime | No explicit precedence found | A day with `attendance_status=LEAVE` (full-day) never reaches `detect_overtime` in the fixed/flex/split paths because `_evaluate_fixed_or_flex`/`_evaluate_split` compute OT from the *punch-derived* `worked_minutes` **before** the leave overlay is applied (`evaluate_day` calls `_apply_leave_overlay` on the already-built `result`, which already carries `ot_minutes_detected`) — meaning OT detected from any punches on a full-day-leave date is **not cleared by the leave overlay** and can still show up in `ot_minutes_detected`/`ot_pending`, even though `attendance_status` was overwritten to LEAVE | No — this is unflagged in code as an explicit rule either way | **NO EXPLICIT PRECEDENCE HANDLING — flag for client decision.** (`_apply_leave_overlay`'s `replace()` calls never zero `ot_minutes_detected`/`ot_pending`/`ot_classification`, only late/early/status/fractions — see `calculation.py:849-864`.) |
| Regularization (approved) | Punch | Regularization becomes new punches, applied then recomputed | `service.py:3931-4057 _apply_correction` — approved correction inserts `source='REGULARIZATION'` punches, then calls `calculate()` | No | CURRENTLY WORKING |
| Regularization (approved) | Attendance result | Regularization wins (recompute replaces the day) | Same mechanism — the recompute after applying the correction fully replaces derived fields (WD-10) | No | CURRENTLY WORKING |
| Overtime (decision) | Attendance status | No direct interaction — orthogonal fields | OT approve/reject writes `AttendanceDay.ot_minutes_approved`/`comp_off_minutes_earned` directly (`service.py:4359-4366`), entirely outside `calculate()`; `attendance_status` itself is never touched by OT approval/rejection | N/A | CURRENTLY WORKING as designed — but see Contradictions doc for whether this split is documented consistently |
| Period Lock | Punch | Lock wins (blocks) | `service.py:2343 _ensure_date_open` | No | CURRENTLY WORKING |
| Period Lock | Regularization (submit) | Lock wins (blocks) | `service.py:3415` | No — and note `RegularizationPolicyVersion.blocked_when_locked` cannot override this (see Configuration Audit L10) | CURRENTLY WORKING |
| Period Lock | Overtime (approve/reject) | Lock wins (blocks) | `service.py:4295,4423` | No | CURRENTLY WORKING |
| Period Lock | Roster (create/update/publish/delete) | Lock wins (blocks) | `service.py:2027,2083,2150,2208` | No | CURRENTLY WORKING |
| Period Lock | Leave (sync/cancel) | Lock wins (blocks) | `service.py:5158,5288` | No | CURRENTLY WORKING |
| Period Lock | Recompute (`calculate()`) | Lock wins (blocks) | `service.py:2499` + row-level `is_locked` re-check at `2506-2507,2572-2575` | No | CURRENTLY WORKING (defence-in-depth: period-level and row-level checks both exist) |
| Draft Roster | Published Roster | Published (draft is invisible to calculation) | `service.py:2750-2752` — `get_published_for_date` only ever considers `status='PUBLISHED'` rows | No | CURRENTLY WORKING — confirmed by `test_draft_roster_does_not_affect_calculation` |
| Roster week-off override | Calendar (WORKING day) | Roster override wins | `calculation.py:742-746,767-769` — forces `NOT_EXPECTED` even on a calendar `WORKING` day (rotating-crew case) | Yes (per-employee-date, via roster) | CURRENTLY WORKING |
| Roster holiday-working override | Calendar (HOLIDAY/WEEKLY_OFF not-expected default) | Roster override wins | `calculation.py:772-774` — ORs with the shift's own `operates_on_holiday`/`operates_on_weekly_off` flags | Yes | CURRENTLY WORKING |
| Shift `operates_on_holiday` | Calendar HOLIDAY (not-expected default) | Shift flag wins if set | `calculation.py:770-772` | Yes | CURRENTLY WORKING |

## Combinations with NO explicit precedence handling in code

Flagged deliberately — these are gaps in the sense that no line of code, comment, or test decides
the outcome; behaviour is whatever falls out incidentally from execution order, which may not be
the intended business rule.

1. **Leave vs Overtime** (detailed above) — a full-day leave overlay does not clear
   `ot_minutes_detected`/`ot_pending` computed from punches that happened to exist on that date.
   No test in `test_leave_projection.py` or `test_overtime_record.py` exercises "employee is on
   approved full-day leave but also has punches that would trigger OT" — `test_full_day_leave_
   present_cancel_hint_flags_and_keeps_punch_status` gets closest but does not assert on OT fields.
   **Needs a client decision**: should OT ever be creditable/payable on a day the leave ledger will
   treat as a full paid/unpaid leave day?

2. **Regularization vs Overtime, when a regularization changes punches that affect a day with an
   already-`PENDING`/terminal `OvertimeRecord`** — `_apply_correction` calls `calculate()`, and
   `_resolve_ot_decision` explicitly freezes a terminal (`APPROVED`/`AUTO_APPROVED`/`REJECTED`)
   `OvertimeRecord` (`service.py:3089-3097`) even though the underlying punches (and therefore the
   "true" OT minutes) just changed via the regularization. This is *documented* as deliberate
   (WD-29 decision 2) but is nonetheless a case where two W6/W7 mechanisms can leave the OT record
   permanently out of sync with the corrected attendance day, with no reconciliation path other
   than a manual period reopen. Not silently undiscovered, but genuinely unresolved.

3. **Roster (published, mid-period change) vs an already-`PENDING` OvertimeRecord** — no code path
   was found that re-evaluates a pending OT record's `day_class`/eligibility when the underlying
   roster shift changes after the OT was first detected but before it's approved. The next
   `calculate()` call (e.g. triggered by any other correction) would refresh `AttendanceDay.
   ot_minutes_detected`/`ot_classification` "informationally" per the `_resolve_ot_decision` docstring, but the
   `OvertimeRecord` row itself is only replaced while `PENDING` (`service.py:3212-3219`) — so this
   specific combination does resolve, just not through an explicitly named "roster-change-affects-
   pending-OT" rule; it falls out of the general PENDING-replace mechanism.

4. **Two overlapping `PolicyAssignment` rows at the same scope tier** (e.g. two EMPLOYEE-scope
   attendance-policy assignments for the same employee with overlapping effective dates) — not
   re-examined in this pass (belongs to the organisation module's `PolicyAssignment` table, which
   predates W1); flagged here only because `resolution.py`/`calendar_resolution.py` assume exactly
   one match per scope tier and neither module was seen to defend against a duplicate.

5. **Excess break vs Overtime** — `excess_break_minutes` is computed and stored but (per the
   Configuration Audit) `excess_break_behaviour` has no runtime effect; there is consequently no
   rule anywhere for whether an excess unpaid break should reduce `worked_minutes` further than it
   already does, or whether excess time should itself ever be OT-eligible. No test, no code branch,
   no documented decision either way.

---

*All rows verified 2026-08-21 against the current working tree. See
`ATTENDANCE_MASTER_RULE_MATRIX.md` for the underlying per-rule evidence and
`ATTENDANCE_DOCUMENTATION_GAPS.md` for where this matrix disagrees with existing documentation.*



<!-- ============================================================ -->
<!-- SOURCE FILE: ATTENDANCE_SCENARIO_MATRIX.md -->
<!-- ============================================================ -->

# Attendance Scenario Matrix + Indian HR Requirements Audit

Companion to `ATTENDANCE_RULE_COMPLETENESS_AUDIT.md`. Covers spec Section 12 (scenario matrix)
and Section 13 (Indian HR requirements audit). Every scenario's expected outcome is derived
directly from `calculation.py`/`service.py` logic verified in this audit — not guessed. Where a
scenario touches a rule found to be non-functional (per `ATTENDANCE_CONFIGURATION_AUDIT.md`), the
"Expected" column states what the code *actually* produces, not what the setting's name implies.

Default policy assumptions unless stated otherwise: `grace_in/out=0`, `missing_punch_behaviour=
INCOMPLETE`, `multi_punch_mode=PAIR_ALL`, `work_on_leave_behaviour=KEEP_LEAVE`, OT `eligibility=
SHIFT_FLAG`, `requires_post_approval=True`, `approval_chain=MANAGER`, `night_ot_mode=SHIFT_FLAG`.

## Section 12 — Scenario Matrix

### Normal Days

| # | Setup | Rules involved | Order | Day type | Attendance status | Worked min | Paid | LOP | OT | Approval | HR modify? | After lock |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | FIXED 09:00-18:00 shift, punches 09:00/18:00 | grace, hour bands | pair→worked→bands→status | WORKING | PRESENT | 540 | 1.00 | 0.00 | 0 (no excess) | n/a | Yes (recompute) | Frozen, `is_locked=True` |
| 2 | Same shift, no punches at all | `missing_punch_behaviour` | not_expected=False→missing_punch=True→INCOMPLETE (default) | WORKING | INCOMPLETE | 0 | 0.00 | 0.00 | n/a | n/a | Yes | Resolved per `incomplete_at_lock_behaviour` at finalize (default TREAT_ABSENT → paid 0.00/lop 1.00) |
| 3 | Same, `missing_punch_behaviour=ABSENT` | same | — | WORKING | ABSENT | 0 | 0.00 | 1.00 | n/a | n/a | Yes | Frozen |
| 4 | IN 09:35 (grace_in=15) | grace, late bands | late_raw=35, late_minutes=20→band lookup | WORKING | PRESENT (unless late band maps to HALF_DAY/ABSENT) | full | 1.00 | 0.00 | 0 | n/a | Yes | Frozen |
| 5 | OUT 17:00 (scheduled end 18:00, grace_out=0) | early bands | early_minutes=60→band lookup | WORKING | Depends on early band; if unmapped, PRESENT with `is_early_out=True` | ~480 | per hour-band | per hour-band | 0 | n/a | Yes | Frozen |
| 6 | Worked 350 min against an hour band `[0,360)=HALF_DAY` | hour bands | `_resolve_primary_status` | WORKING | HALF_DAY | 350 | 0.50 | 0.50 | 0 | n/a | Yes | Frozen |
| 7 | Missing IN only (orphan OUT) | pairing, missing_punch | `pair_punches` orphans the OUT | WORKING | INCOMPLETE (default) | 0 | 0.00 | 0.00 | n/a | n/a | Yes (via regularization) | Blocks finalize if `incomplete_at_lock_behaviour=KEEP_INCOMPLETE` |
| 8 | Missing OUT only (orphan IN) | pairing | trailing open IN is orphan | WORKING | INCOMPLETE | 0 | 0.00 | 0.00 | n/a | n/a | Yes | Same as #7 |
| 9 | Duplicate IN punches 30s apart | duplicate collapsing | `collapse_duplicate_punches` (default window 60s) | WORKING | Collapses to one IN, normal evaluation | per punches | — | — | — | — | Yes | — |
| 10 | Two IN/OUT pairs in one day (lunch out-and-back not configured as a break) | `multi_punch_mode=PAIR_ALL` | both pairs summed, gap between excluded | WORKING | PRESENT (sum of both intervals) | sum of both | 1.00 | 0.00 | per excess | — | Yes | — |

### Shifts

| # | Setup | Expected day type | Status | Worked min | OT | Notes |
|---|---|---|---|---|---|---|
| 11 | FIXED shift, standard | WORKING | per punches | as above | per excess | Baseline |
| 12 | FLEXIBLE shift, window 07:00-10:00, `required_minutes=480` | WORKING | Evaluated via `resolve_schedule_window`'s FLEXIBLE branch — **no dedicated test confirms the exact late/status outcome**; per code, `scheduled_start/end = window_start/window_end`, late compares IN against `window_end`+grace | per punches | uses `required_minutes` as OT baseline only if no fixed start/end resolved | **NOT TESTED — see Documentation Gaps.** Treat outcome as unverified, not merely "should work" |
| 13 | SPLIT shift, 2 duty blocks, both worked | WORKING | Normal status resolution (no missed blocks) | sum of pair minutes | detected via `shift.required_minutes` baseline | TESTED |
| 14 | SPLIT shift, one block missed, `split_shift_missed_block_behaviour=HALF_DAY` | WORKING | HALF_DAY | partial | still computed from worked minutes | Behaviour branch exists; not individually unit-tested by name (see Documentation Gaps) |
| 15 | Cross-midnight (overnight) shift 22:00-06:00 | WORKING | attendance_date = shift start date (the day the shift *begins*) | per punches | `is_night=True` internally, but OT day_class only becomes `NIGHT` if `night_ot_mode` is WINDOW/BOTH — **default (SHIFT_FLAG) never produces NIGHT** | TESTED for date attribution; NOT TESTED end-to-end for the NIGHT OT claim (see CT6) |
| 16 | Roster overrides assignment default shift | Whatever the roster's shift resolves to | — | — | — | TESTED — roster wins outright when PUBLISHED |
| 17 | No shift resolved (no assignment, no roster) and no punches | n/a (no schedule) | INCOMPLETE (default) or ABSENT (`missing_shift_behaviour=ABSENT`) | 0 | n/a | TESTED |
| 18 | No shift resolved, but punches exist | n/a | `_evaluate_no_schedule` — PRESENT if any gross minutes, else INCOMPLETE. **No late/early/OT ever computed in this path** (no schedule to compare against) | gross minutes | 0 (always — no OT is ever detected without a resolved schedule) | TESTED |

### Calendar

| # | Setup | Day type | Status (no punches) | Status (punches exist) | OT eligible on this day | Notes |
|---|---|---|---|---|---|---|
| 19 | Public holiday, shift doesn't operate | HOLIDAY | NOT_EXPECTED | Evaluated normally; `worked_on_holiday=True` if worked_minutes>0 | Yes, if shift is OT-eligible — `worked_on_holiday` feeds `day_class=HOLIDAY` | TESTED (weekly-off analogue confirmed directly; holiday shares the same code branch) |
| 20 | Weekly off (e.g. Sunday, Mon-Sat pattern) | WEEKLY_OFF | NOT_EXPECTED | `worked_on_weekly_off=True` if worked | Yes, `day_class=WEEKLY_OFF` | TESTED |
| 21 | Holiday landing on weekly-off day | WEEKLY_OFF, `holiday_on_weekly_off=True` | NOT_EXPECTED | Evaluated normally | Yes, `day_class` resolution: HOLIDAY beats WEEKLY_OFF in `classify_ot_day` (`calculation.py:642-650`) even though `calendar_day_type` reports WEEKLY_OFF | **OPEN PRODUCT DECISION** — no auto-substitute holiday granted elsewhere |
| 22 | Substitute holiday (manual exception) | HOLIDAY | NOT_EXPECTED | as #19 | as #19 | TESTED at the calendar-classification level (organisation module) |
| 23 | Special working day (exception) | SPECIAL_WORKING | Falls into the general "not `not_expected`" default (SPECIAL_WORKING is not in the `not_expected` tuple `("HOLIDAY","WEEKLY_OFF","SHUTDOWN")`, `calculation.py:767-768`) → presence IS expected | Evaluated normally | Yes | Confirms SPECIAL_WORKING behaves like an ordinary working day for attendance purposes |
| 24 | Shutdown day | SHUTDOWN | NOT_EXPECTED | Evaluated normally if punches exist | Yes | TESTED at the calendar-classification level |
| 25 | Cancelled holiday (exception removes the holiday match, date is not otherwise a weekly-off) | WORKING | INCOMPLETE/ABSENT per policy (ordinary working day now) | Evaluated normally | Yes | Confirmed via `calendar_resolution.py:164-180` |
| 26 | Optional/restricted holiday, `restricted_holidays_are_off_by_default=False` (default) | WORKING (soft — "working until Leave applies") | Ordinary working-day evaluation | Ordinary | Yes | PD-CAL-1 in code comment — the "only sanctioned per-company override" |

### Leave

| # | Setup | Status | Paid | LOP | OT | Notes |
|---|---|---|---|---|---|---|
| 27 | Full-day paid leave, no punches | LEAVE | 1.00 | 0.00 | 0 | TESTED |
| 28 | Full-day unpaid leave, no punches | LEAVE | 0.00 | 1.00 | 0 | TESTED |
| 29 | Half-day paid leave, no punches | LEAVE (remaining half unworked → LOP for the working half) | 0.50 | 0.50 | 0 | TESTED |
| 30 | Half-day leave + full-day punches | HALF_DAY (has_work=True) | 1.00 (0.50 leave + 0.50 punch-derived work) | 0.00 | Whatever punches detect, **unaffected by the leave overlay** | TESTED for status; OT interaction NOT TESTED (CT9) |
| 31 | Full-day leave + punches, `KEEP_LEAVE` (default) | LEAVE (punches ignored for status) | per leave's paid flag | per leave's paid flag | **OT still computed from the punches and NOT cleared** (CT9) | TESTED for status; OT NOT TESTED |
| 32 | Full-day leave + punches, `PRESENT_CANCEL_LEAVE_HINT` | Punch-derived status kept; `work_on_leave_flagged=True` | per punch-derived outcome | per punch-derived outcome | per punch-derived outcome | TESTED |
| 33 | Leave on a holiday date | `calendar_day_type=HOLIDAY` unchanged; `attendance_status=LEAVE` if leave fraction ≥1.00 | per leave | per leave | 0 | TESTED (`test_leave_overrides_roster_week_off_not_expected` proves the analogous weekly-off case) |
| 34 | Leave on a weekly-off date | Same pattern | per leave | per leave | 0 | Same mechanism |
| 35 | Leave cancelled after being synced | Reverts to punch-derived outcome on next recompute | per punches | per punches | per punches | TESTED — `test_cancel_projection_reverts_attendance_to_punch_derived_outcome` |
| 36 | Leave sync/cancel attempted on a locked period | Refused | n/a | n/a | n/a | TESTED |

### Regularization

| # | Setup | Outcome | Approval state | After lock |
|---|---|---|---|---|
| 37 | Employee submits MISSING_PUNCH request, single-stage MANAGER chain | SUBMITTED → manager approves → synthetic punches inserted → day recomputed | PENDING→APPROVED | Locked periods refuse the initial submission entirely |
| 38 | WRONG_SHIFT request | On approval, creates/updates a `PUBLISHED` `ShiftRoster` row for that date, then recomputes | as above | Same |
| 39 | WFH/ON_DUTY-typed request | On approval, inserts synthetic punches (same as MISSING_PUNCH) — **does not produce `attendance_status=WFH`/`ON_DUTY`** (CT5) | as above | Same |
| 40 | Manager rejects | Attendance day left entirely unchanged | REJECTED | n/a |
| 41 | Employee tries to approve their own request | Refused (self-approval always blocked) | n/a | n/a |
| 42 | MANAGER_THEN_HR chain, manager approves stage 1 | `approval_stage` moves to HR, status stays SUBMITTED, no correction applied yet | STAGE_APPROVED (manager) → then HR must act | n/a |
| 43 | No manager resolved for employee | Routes straight to HR stage | PENDING(HR) | n/a |
| 44 | `AUTO` approval chain | Approved and applied immediately on submit, no human review | AUTO_APPROVED-equivalent | n/a |
| 45 | Backdated beyond `max_backdated_days` | Submission rejected outright | n/a | n/a |
| 46 | Beyond `max_requests_per_month` | Submission rejected outright | n/a | n/a |
| 47 | Request for a date in a locked period | Submission refused | n/a | Only a full `ATTENDANCE.UNLOCK` reopen re-enables correction |

### Overtime

| # | Setup | day_class | Status | Approval | Cap interaction |
|---|---|---|---|---|---|
| 48 | Normal working day, 25 min excess over `min_ot_minutes=15` | NORMAL | PENDING (requires_post_approval=True, chain=MANAGER default) | Manager approves → `ot_minutes_approved` set on the day | none |
| 49 | Excess below `min_ot_minutes` | n/a | Not detected at all (`ot_minutes_detected=0`) | n/a | n/a |
| 50 | Worked on holiday | HOLIDAY | as #48 | as #48 | day_class = HOLIDAY, rate row lookup uses it |
| 51 | Worked on weekly-off | WEEKLY_OFF | as #48 | as #48 | day_class = WEEKLY_OFF |
| 52 | Genuinely overnight shift, default `night_ot_mode=SHIFT_FLAG` | **NORMAL, never NIGHT** (CT6) | as #48 | as #48 | Client expecting a night differential will see nothing distinguishing this from a normal day's OT |
| 53 | `night_ot_mode=WINDOW`, employee works past midnight | Still gated on `shift.is_cross_midnight` only, **not** on whether the actual minutes fall inside `night_window_start/end`; will read NIGHT for any cross-midnight shift with any excess minutes, correct or not | as #48 | as #48 | The window itself has zero effect (CT6) |
| 54 | SPLIT shift with excess in one block | Computed against `shift.required_minutes` baseline | as #48 | as #48 | TESTED (W7 addition) |
| 55 | Daily cap reached | Excess clamped to `daily_cap_minutes` | as #48 (clamped amount) | as #48 | TESTED |
| 56 | Weekly cap already consumed by an earlier day this week | `remaining_weekly_minutes` computed from sibling-day sums, clamps this day too — possibly to 0 even though the day's own excess is nonzero | STILL "eligible", just 0 minutes detected | n/a if 0 | TESTED — `test_detect_overtime_weekly_cap_exhausted_still_eligible_zero_minutes` |
| 57 | Monthly cap reached | Same pattern at month grain | as #56 | n/a | TESTED |
| 58 | `comp_off_instead_of_pay=True`, auto-approved | `comp_off_minutes_earned` set with expiry date | AUTO_APPROVED | Comp-off fact stored; **no expiry-lapse enforcement exists anywhere in this codebase** | TESTED for the fact; expiry enforcement is FUTURE MODULE |
| 59 | Comp-off while still PENDING | `comp_off_minutes_earned` on the day is **0** until the decision is made (the record itself always carries the computed fact) | PENDING | n/a | TESTED — `test_comp_off_not_credited_to_day_while_pending` |
| 60 | Rejected OT | `ot_minutes_approved`/`comp_off_minutes_earned` cleared to 0 on the day | REJECTED | Frozen — never revised by a later recompute | TESTED |
| 61 | Self-approval attempt | Refused | n/a | n/a | TESTED |
| 62 | `eligibility=NEVER` | No OT ever detected regardless of hours worked | n/a | n/a | Confirmed by code path (`calculation.py:668-669`); not individually named-tested but trivially implied by the eligibility gate structure |
| 63 | `eligibility=GRADE_VIA_ASSIGNMENT`, employee's grade is not meant to be OT-eligible | **Still detected — behaves exactly like ALWAYS** (CT7) | PENDING/AUTO per chain | This is a genuine payroll-risk scenario if a client relies on grade gating | NOT TESTED (no test proves the grade is even read) |

### Period / Lock

| # | Setup | Validation result | Outcome | Reopen |
|---|---|---|---|---|
| 64 | All days calculated, no pending anything | READY | Finalize succeeds, days locked, summary snapshot written | — |
| 65 | An employee has a date range with no `AttendanceDay` row | EMPLOYEES_WITHOUT_ATTENDANCE | Blocked | — |
| 66 | A day is `CONFIG_ERROR` | CONFIG_ERROR | Blocked, no lock-time auto-resolution exists (must fix and recompute) | — |
| 67 | A day is INCOMPLETE under `KEEP_INCOMPLETE` policy | INCOMPLETE_ATTENDANCE | Blocked | — |
| 68 | A day is INCOMPLETE under default `TREAT_ABSENT` policy | Not a blocker | Finalize succeeds; day auto-resolved to paid 0.00/lop 1.00 at finalize | — |
| 69 | A regularization request is still SUBMITTED | PENDING_REGULARIZATION | Blocked | — |
| 70 | An overtime record is still PENDING | PENDING_OVERTIME_APPROVAL | Blocked | — |
| 71 | A roster entry is still DRAFT | UNPUBLISHED_ROSTER | Blocked | — |
| 72 | Successful finalize | READY | Days locked, `AttendancePeriodSummary` rows frozen, period `status=CLOSED` | — |
| 73 | Any mutation attempted on a locked date (punch/roster/regularization-submit/recompute/OT-approve/leave-sync/leave-cancel) | n/a | All 7 refused | — |
| 74 | Reopen a CLOSED period | n/a | Days unlocked across the range; nothing recomputed automatically; a later ordinary `calculate()`/correction call is needed to actually change anything; re-finalize regenerates a fresh summary | Requires separate `ATTENDANCE.UNLOCK` permission |

## Section 13 — Indian HR Requirements Audit

| Requirement | Support level | Evidence |
|---|---|---|
| Mon-Fri work week | **Support** | `WeeklyOffRuleData` with `FIXED_WEEKDAYS` covers any weekday set, including a 2-day weekend (organisation module, `calendar_resolution.py:72-117`) |
| Mon-Sat work week (single weekly off) | **Support** | Same mechanism, one weekday |
| Alternate Saturday off | **Support** | `ALTERNATE` rule kind, `cycle_start_date` + `week_parity` (`calendar_resolution.py:109-116`) — default parity for an unset `week_parity` is documented as an implementation choice, not a spec'd default (see Hidden Rules HR3-equivalent in Configuration Audit) |
| Nth/last Saturday off | **Support** | `NTH_WEEKDAY` with `nth_in_month=-1` for "last" (`calendar_resolution.py:105-108`) |
| Rotational weekly offs (different day per employee/week) | **Support** | `ShiftRoster.is_week_off_override` per employee-date is exactly this mechanism, explicitly motivated by "night-shift workers with a Wednesday off" per the architecture doc itself (line 730) |
| State/branch-specific holidays | **Support** | Branch carries `state_code`; multiple `WorkCalendar`s can be scoped and resolved through the same 8-level precedence walk used for policies (organisation module — not re-verified line-by-line in this pass, but the mechanism generalizes from the confirmed policy-resolution walk) |
| Optional/restricted holidays | **Support** | `holiday_type IN (OPTIONAL, RESTRICTED)`, `restricted_holidays_are_off_by_default` toggle (PD-CAL-1) |
| Holiday on Sunday (weekly-off collision) | **Partial — needs decision** | Stays WEEKLY_OFF with a flag; no automatic substitute holiday is granted (PD-CAL-2, open) |
| Compensatory holiday (substitute) | **Partial** | `SUBSTITUTE_HOLIDAY` exception type exists and works, but is entirely manual (HR must create the exception row) — no automatic trigger from the Sunday-holiday collision above |
| Night shifts | **Partial — needs decision** | Cross-midnight scheduling/date-attribution works correctly; NIGHT overtime classification does not reliably distinguish a genuine night shift and, by default, never classifies anything as NIGHT (CT6) |
| 24x7 operations | **Support** | `operates_on_holiday`/`operates_on_weekly_off` per-shift flags plus roster overrides cover continuous-operations shift patterns |
| Security/hospital/manufacturing shift patterns | **Partial** | The building blocks (cross-midnight, SPLIT shifts, roster overrides, 24x7 flags) all exist and are individually tested; no end-to-end scenario test combines them the way a real 3-shift rotating roster would, and the NIGHT OT gap (above) is most likely to bite this segment specifically |
| Split shifts | **Support (with documented simplification)** | Duty-block presence detection works; no partial-hours credit for a partially-worked block (documented limitation, not silent) |
| Flexible timings | **Partial — needs verification** | Window resolution exists in `resolve_schedule_window`, but core-hours enforcement (the feature that makes "flexible" meaningfully different from "just don't check lateness") is entirely unimplemented (CT3), and no test proves the FLEXIBLE path's actual late/status output |
| Work From Home (WFH) | **Not supported as a distinct status — Future module / needs decision** | CT5 — none of the architecture's 3 named mechanisms exist; only ordinary punch-based evaluation results |
| Field / On-duty | **Not supported as a distinct status — Future module / needs decision** | Same as WFH — `ON_DUTY` regularization type exists but produces ordinary punches, never a distinct status |
| Half-day leave | **Support** | W9 — full, tested, including multiple half-days summing to a full day |
| Late-coming policy (grace + bands) | **Support** | Grace minutes + ordered late bands, fully working and tested |
| Repeated-late penalties (N lates = half day) | **Not supported — Stored but not used** | `lates_to_half_day_count`/`late_count_window` are configurable in the UI but have zero runtime effect (H14) |
| OT on holiday/weekly-off | **Support** | `day_class` classification correctly distinguishes HOLIDAY/WEEKLY_OFF for rate-row lookup (informational multiplier, not money) |
| Comp-off | **Support (fact only, no expiry enforcement)** | `comp_off_minutes_earned`/`comp_off_expiry_date` computed and stored correctly; nothing in this codebase invalidates a comp-off once its expiry date passes — that enforcement would live in a future Leave/Payroll module |
| Monthly attendance closing | **Support** | `AttendancePeriod` finalize/lock (W8) is comprehensive — 6 validation blockers, atomic lock, frozen payroll-facing summary, reopen path, all thoroughly tested |

---

*Compiled 2026-08-21. Scenarios reference the exact policy defaults documented in
`ATTENDANCE_MASTER_RULE_MATRIX.md`; "NOT TESTED" markers were confirmed by grepping the full test
function name list in both the unit and integration attendance test suites on the same date.*



<!-- ============================================================ -->
<!-- SOURCE FILE: ATTENDANCE_CONFIGURATION_AUDIT.md -->
<!-- ============================================================ -->

# Attendance Configuration Audit — False Customization Table + Hidden Rules

Companion to `ATTENDANCE_RULE_COMPLETENESS_AUDIT.md`. Covers spec Sections 9 (false
customization) and 10 (hidden rules). Every row was independently re-verified against the current
working tree on 2026-08-21 — none of these are carried over unverified from any prior document.
Method: for every configurable field found on `AttendancePolicyVersion` / `OvertimePolicyVersion`
/ `RegularizationPolicyVersion`, grep every occurrence of the field name across
`calculation.py`/`service.py`/`repository.py` and classify what, if anything, consumes it outside
CRUD serialization.

## Section 9 — False Customization Table

"Engine consumes it?" is the load-bearing column: UI/API/DB all being "Yes" is table stakes for
any settings screen in this codebase (the CRUD layer is generic and consistent); the gap is
specifically whether `calculation.py`/`service.py` branch on the value.

| Setting | UI allows it? | API stores it? | DB stores it? | Engine consumes it? | Actual effect |
|---|---|---|---|---|---|
| `punch_rounding` / `rounding_minutes` (punch-time rounding) | Yes — attendance policy form | Yes | Yes | **No.** `apply_rounding`/`round_minutes` exist in `calculation.py:594-613` but are never called from `evaluate_day` or any helper on a punch instant. | None. Punch times are used raw for late/early/worked-minutes math regardless of this setting. (The *same* `round_minutes` primitive is genuinely used elsewhere — for OT-minute rounding, see below — so this is not a dead function, just an unwired input for this one purpose.) |
| `core_hours_breach_behaviour` (IGNORE/FLAG/HALF_DAY/ABSENT) | Yes | Yes | Yes | **No.** Declared on `PolicyInputs` (`calculation.py:110`), never read in any branch. | None. There is no code path that reads a flexible shift's core-hours breach at all (see next row). |
| `core_start` / `core_end` (flexible-shift core-hours window) | Yes — shift-version form (organisation module) | Yes | Yes | **No.** Resolved into `ShiftInputs.core_start/core_end` (`service.py:2821-2826`) but never referenced in `evaluate_day`/`_evaluate_fixed_or_flex`/`_evaluate_split`. | None. A flexible shift's core-hours requirement is invisible to the calculation engine no matter what is configured. |
| `early_out_uses_core_end` | Yes | Yes | Yes | **No.** Same as above — dead input, tied to the same unused core-hours mechanism. | None. |
| `half_day_split` (BY_HOURS / BY_MIDPOINT) | Yes | Yes | Yes | **No.** Declared (`calculation.py:106`), never read. | None. Half-day determination is entirely driven by `AttendancePolicyHourBand` worked-minute thresholds, regardless of which split method is configured. |
| `half_day_boundary_minutes` | Yes | Yes | Yes | **No.** Same as above. | None. |
| `excess_break_behaviour` (IGNORE/DEDUCT/FLAG/REQUIRE_APPROVAL) | Yes | Yes | Yes | **No.** Declared (`calculation.py:113,129`), never read; excess-break *detection* (`is_excess`, `excess_break_minutes`) works independently of this field. | Excess breaks are still flagged and their minutes stored regardless of what this is set to — a `DEDUCT` policy does not actually deduct anything beyond what unpaid-break math already does, and `REQUIRE_APPROVAL` triggers no approval workflow. |
| `wfh_requires_punch` / `on_duty_requires_punch` / `wfh_uses_shift_hours` | Yes | Yes | Yes | **No.** Never referenced in `calculation.py`. | `WFH`/`ON_DUTY` are never produced as `attendance_status` by the engine at all (see next section) — these three fields govern a code path that does not exist. |
| `late_count_window` / `lates_to_half_day_count` | Yes | Yes | Yes | **No.** Field declarations only (`models.py:132-133`). | A "3 lates = 1 half day" style rolling penalty is fully configurable in the UI/API but has zero runtime effect — repeated lateness never converts to a half-day deduction anywhere in the codebase. |
| `early_departure_requires_approval` | Yes | Yes | Yes | **No.** | An early departure never actually requires or triggers any approval gate; `early_departure_minutes`/classification are computed and stored, nothing gates on this flag. |
| `auto_close_after_minutes` / `auto_close_uses_shift_end` | Yes | Yes | Yes | **No.** Zero references outside CRUD assembly (`service.py:376-377`). | `missing_punch_behaviour=AUTO_CLOSE` never actually synthesizes a closing punch using this configuration — see next row. |
| `missing_punch_behaviour=AUTO_CLOSE` | Yes | Yes | Yes | **Partial.** `_resolve_primary_status` has an explicit `AUTO_CLOSE` branch (`calculation.py:1299-1300`) that says "falls through to band-based status below (auto_closed flag set by caller)" — but `auto_closed` is hard-coded `False` at `calculation.py:1021` and never set `True` anywhere in the module. | Selecting AUTO_CLOSE changes nothing observable versus letting the day fall through the ordinary band-based status logic with whatever punches actually exist; the day is never actually "closed" with a synthetic OUT punch, and `AttendanceDay.auto_closed` is always `False`. |
| `missing_punch_behaviour=REQUIRE_REGULARIZATION` | Yes | Yes | Yes | **No distinct branch.** `_resolve_primary_status`'s missing-punch handling only special-cases `ABSENT` and `AUTO_CLOSE`; every other value (including `REQUIRE_REGULARIZATION` and `INCOMPLETE`) falls into the same `else: return "INCOMPLETE"` (`calculation.py:1301-1302`). | `REQUIRE_REGULARIZATION` behaves identically to `INCOMPLETE` — no distinct "this day needs regularization" signal is raised beyond the ordinary INCOMPLETE status. |
| `split_shift_block_mandatory` | Yes | Yes | Yes | **No.** Never referenced in `calculation.py`. Every duty block in `_evaluate_split` is checked for a missed overlap unconditionally (`calculation.py:1157-1172`). | Setting this to `False` (meant to make a duty block optional) has no effect — a missed block always counts toward `missed_blocks` and triggers `split_shift_missed_block_behaviour` regardless. |
| `split_shift_allow_hours_compensation` | Yes | Yes | Yes | **No.** Never referenced. | A block worked short is never credited by extra hours in another block; the module's own docstring (`calculation.py:17-22`) documents this as a known simplification. |
| `night_window_start` / `night_window_end` (overtime policy) | Yes | Yes | Yes | **No.** Carried on `OvertimePolicyInputs` (`calculation.py:130-131`) but never compared against any punch/worked-interval time. | Configuring a night window (e.g. 22:00–06:00) with `night_ot_mode=WINDOW` has no effect on which minutes are classified NIGHT — `is_night` is computed solely from `shift.is_cross_midnight` (`calculation.py:1062,1212,1229`), independent of the window. |
| `night_ot_mode=SHIFT_FLAG` (default) | Yes | Yes | Yes | **Effectively disables NIGHT classification entirely.** `classify_ot_day` only returns `"NIGHT"` when `night_ot_mode in ("WINDOW","BOTH")` (`calculation.py:648`) — `SHIFT_FLAG` never satisfies that condition no matter what `is_night` is. | Out of the box (default policy), overtime on a genuinely overnight/cross-midnight shift is classified `NORMAL` (or `HOLIDAY`/`WEEKLY_OFF` if applicable), never `NIGHT` — an HR admin who never touches `night_ot_mode` will never see a NIGHT-classified OT record. |
| `eligibility=GRADE_VIA_ASSIGNMENT` | Yes | Yes | Yes | **No distinct handling.** `detect_overtime` only special-cases `NEVER` and `SHIFT_FLAG` (`calculation.py:668-671`); `ALWAYS` and `GRADE_VIA_ASSIGNMENT` both fall through with no gate at all. | Selecting "OT eligibility by grade" behaves identically to "always eligible" — no employee grade, designation, or `EmployeeAssignment` field is ever consulted to determine per-grade OT eligibility. |
| `counts_toward_cap` (late/early band field) | Yes | Yes | Yes | **No.** `models.py:183,203` stores it; `BandData`/`lookup_band` (`calculation.py:83-88,621-628`) has no such field and cannot read it. | Purely decorative — whatever cap this was meant to gate does not exist either (see `lates_to_half_day_count` above). |
| `auto_approve_within_minutes` (regularization policy) | Yes | Yes | Yes | **No** confirmed consumer beyond CRUD assembly (`service.py:1513`). Distinct from `approval_chain=AUTO`, which *is* real and does auto-approve. | A timing-based auto-approve window ("auto-approve if reviewed within N minutes" or similar) has no observed runtime effect; only the separate `approval_chain=AUTO` value produces auto-approval. |
| `blocked_when_locked` (regularization policy) | Yes | Yes | Yes | **No — superseded.** The code's own comment at `service.py:3410` states the period-lock check is "unconditional, independent of `RegularizationPolicyVersion.blocked_when_locked`." | Setting this field to `False`, expecting regularization requests to remain submittable during a locked period, has no effect — a closed period blocks all regularization submission regardless of this setting. This is the inverse risk of the others: the field reads as an escape hatch but cannot actually be used as one. |
| `required_minutes` (FLEXIBLE shift) | Yes | Yes | Yes | **Partially.** Used only as the `scheduled_minutes` fallback for OT/hour-band comparison when no fixed start/end resolves (`calculation.py:1059-1060,1208`) — never independently validated as "did the employee actually accumulate this many minutes" for a FLEXIBLE-shift-specific PRESENT/HALF_DAY/ABSENT decision distinct from the ordinary hour-band lookup. | Functions correctly as an OT baseline; does **not** function as an independent minimum-hours gate the way its name implies for flexible-shift attendance status. |

### Confirmed as genuinely working (re-verified, not assumed)

For contrast — these configuration surfaces were checked with the same rigor and *do* change
calculation output:

| Setting | Verified effect |
|---|---|
| `grace_in_minutes`/`grace_out_minutes` | Directly subtracted from raw late/early minutes (`calculation.py:1030,1036`) |
| `multi_punch_mode` (PAIR_ALL/FIRST_IN_LAST_OUT) | Changes worked-minutes arithmetic (`calculation.py:519-536`) |
| `duplicate_punch_window_seconds` | Directly gates punch collapsing (`calculation.py:437-452`) |
| Hour/late/early bands | Directly drive status and classification (`lookup_band`, used at 1032,1038,1040) |
| `missing_shift_behaviour` | Directly gates ABSENT vs INCOMPLETE for a shift-less day (`calculation.py:750-754`) |
| `split_shift_missed_block_behaviour` (HALF_DAY/ABSENT/REQUIRE_REGULARIZATION) | Directly maps to status (`calculation.py:1180-1195`) — only `split_shift_block_mandatory`/`_allow_hours_compensation` (above) are the dead siblings |
| `work_on_leave_behaviour` | Directly branches the leave overlay (`calculation.py:846-878`) |
| `incomplete_at_lock_behaviour` | Directly resolves paid/lop fraction at finalize (`service.py:4920-4955`) and blocks/unblocks finalization (`service.py:4685-4722`) |
| OT `min_ot_minutes`/`rounding_minutes`/`rounding_mode`/daily-weekly-monthly caps | All directly applied in `detect_overtime` (`calculation.py:673-685`) |
| OT `requires_post_approval`/`approval_chain` | Directly drives PENDING vs AUTO_APPROVED (`service.py:3106-3132`) |
| OT `comp_off_instead_of_pay`/`comp_off_expiry_days` | Directly computed as facts (`calculation.py:1081-1082`, `service.py:3138-3140`) |
| Regularization `max_backdated_days`/`max_requests_per_month`/`reason_required`/`attachment_required`/allowed types | All directly enforced at submit time (dedicated tests exist for each) |
| Roster `is_week_off_override`/`is_holiday_working_override` | Directly change expectation-of-presence (`calculation.py:742-774`) |

## Section 10 — Hidden Rules (in code, absent from configuration/documentation)

Rules embedded as hard-coded logic — not exposed as a setting anywhere, and in several cases not
named in the architecture/business-rule docs either.

| # | Hidden rule | Where | Why it matters |
|---|---|---|---|
| HR1 | Roster week-off override is checked **before** the missing-shift branch | `calculation.py:736-746` (comment explains the ordering deliberately) | A pure roster week-off row with `shift_id=NULL` must not fall through to `missing_shift_behaviour` and be misread as a config error — this ordering is load-bearing and undocumented outside this one code comment. |
| HR2 | Break-gap matching is first-match, not best-match | `calculation.py:557-573` — the loop `break`s on the first `ShiftBreakData` whose window contains the gap start | If two configured breaks have overlapping windows, whichever is declared first in the query result order wins; no documented tie-break rule exists anywhere else. |
| HR3 | A late/early classification of `HALF_DAY` or `ABSENT` overrides the hour-band status outright | `calculation.py:1309-1312 _resolve_primary_status` | An employee who worked full hours but arrived extremely late (late band = ABSENT) is marked ABSENT even though `hour_band_status` said PRESENT — late/early bands outrank hour bands. This precedence is real but not written down anywhere as an explicit rule in the business-rule docs. |
| HR4 | `NOT_EXPECTED` + punches still present ⇒ presence is evaluated anyway | `calculation.py:783` (`not_expected and not shift_operates and not collapsed`) | A holiday/weekly-off day with *any* punches never short-circuits to NOT_EXPECTED — it always falls through to full pairing/evaluation, which is how `worked_on_holiday`/`worked_on_weekly_off` become achievable. This is correct and intentional but the "any punch at all defeats NOT_EXPECTED" threshold (not "punches worth N minutes") is not documented as an explicit rule. |
| HR5 | `is_night` for OT purposes is a synonym for cross-midnight, nothing else | `calculation.py:1062,1212,1229` | There is no independent "night shift" concept distinct from crossing midnight — a shift running, say, 20:00–23:30 (evening, not crossing midnight) can never be classified NIGHT for OT purposes no matter how policy is configured, and a shift crossing midnight by one minute (e.g. 23:55–00:05) is treated identically to a genuine graveyard shift. |
| HR6 | OT detection is **not idempotent** across recomputes for capped employees | `calculation.py:29-34` (module docstring, WD-29 decision 3), `service.py:2954-2983` | Recomputing day N can change its `ot_minutes_detected` purely because a sibling day's `overtime_record` state changed in between — a documented, deliberate design choice, but one an auditor/support engineer needs to know before treating two different `computation_snapshot`s for the same punches as evidence of a bug. |
| HR7 | Fail-closed default for unresolved calendar/policy is `CONFIG_ERROR`, not `WORKING`/`ABSENT` | `calculation.py:729-734` | Consistent with WD-21 but worth flagging: a misconfigured tenant silently accumulates `CONFIG_ERROR` days that block period finalization (`N3` in the master matrix) rather than ever defaulting to a guessed status. |
| HR8 | `AttendancePeriod.legal_entity_id` exists but is always NULL | `models.py:829-834` | A column exists in the schema and migration that no code path ever populates — reserved for a future grain change, but a naive query joining on it would silently find nothing. |
| HR9 | Regularization/OT approval self-check compares `caller_employee_id` to the *target* employee, not to the resolved manager identity independently | `service.py:4247-4249`, mirrored in regularization | Self-approval block is correct, but it is enforced as a single hard-coded equality check with **no policy field to disable it** — worth stating explicitly since several *other* similarly "safety" fields in this module (`blocked_when_locked`) turned out to be configurable-but-inert; this one is the opposite: safe, but not visible as a documented invariant anywhere outside this one line. |
| HR10 | A `PENDING` `OvertimeRecord` is fully replaced (delete/recreate) on every recompute; a terminal one is frozen | `service.py:3163-3231` (`_sync_overtime_record`) | Anyone reading only `AttendanceDay.ot_minutes_detected` without also checking `OvertimeRecord.status` could be misled — the day row's OT summary columns are overwritten by every recompute UNLESS the linked `overtime_record` has already reached a terminal state, in which case only the *day row's* redundant copy tracks the frozen decision, and the source of truth diverges silently. |
| HR11 | `_approve_internal`'s transactional atomicity for regularization is deliberate but undocumented outside a code comment | `service.py:3941-3945` | If `AttendanceDayService.calculate()` inside `_apply_correction` raises (e.g. locked day), the whole transaction — including the just-written `status='APPROVED'`row — rolls back. This means a caller retrying an approve on a request that appears `APPROVED` in a stale read could get confusing results; correct behaviour, but relies entirely on the surrounding transaction boundary being what the code comment asserts, which was not independently re-verified against the FastAPI/session-commit wiring in this audit pass. |
| HR12 | `AttendancePolicyHourBand`/`LateBand`/`EarlyDepartureBand` overlap/ordering is validated only at **publish time** in the service layer, never as a DB constraint | `models.py:150-151` | A DRAFT version can hold overlapping/contradictory bands indefinitely (no DB-level guard); only publishing enforces `InvalidPolicyBandError`. Not a bug, but means a half-edited draft is not fail-safe if read directly rather than through the publish path. |

---

*Every row in both tables above is backed by a specific grep/read of `calculation.py`, `service.py`,
`models.py`, or `schemas.py` performed during this audit (2026-08-21), not carried over from any
earlier document's claims.*



<!-- ============================================================ -->
<!-- SOURCE FILE: ATTENDANCE_DOCUMENTATION_GAPS.md -->
<!-- ============================================================ -->

# Attendance Documentation Gaps — Contradictions + Test Coverage Audit

Companion to `ATTENDANCE_RULE_COMPLETENESS_AUDIT.md`. Covers spec Section 8 (contradictions)
and Section 11 (test coverage audit), plus a consolidated list of every DOCUMENTATION GAP /
IMPLEMENTATION GAP item raised across all six deliverables.

## Methodology note on the existing documentation sets

Three documentation sources exist for this module, and they are **not equally current**:

1. **`docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md`** — the original design document.
   Written aspirationally/prescriptively; several of its detailed behaviour descriptions (rounding,
   core hours, WFH, auto-close) describe what the *design* called for, not what W3-W9 actually
   built. It has not been revised to mark these as unimplemented.
2. **`docs/business-rules/attendance/*.md` and `docs/business-rules/ATTENDANCE_V1_*.md`** (client-
   facing set) — dated 2026-08-20 (one day before this audit), explicitly built by "studying the
   live W1-W9 implementation" with code as the stated source-of-truth priority
   (`docs/business-rules/attendance/README.md:7-11`). Independent sampling in this audit (rounding,
   core hours, auto-close, WFH, night OT, grade-based OT eligibility — see table below) found this
   set **already accurate** against the current code, including after the W7/W8/W9 work reflected
   in today's `git status`. This audit's own code-reading independently reproduced the same
   findings without reading that document's conclusions first, then cross-checked afterward — the
   agreement is corroboration, not a shortcut.
3. **`docs/modules/{attendance,attendance-lock,attendance-policy,attendance-regularization,
   overtime,leave,shift-version,shift-rules}/*.md`** — per-slice implementation reports (W2-W9).
   Not exhaustively re-read line-by-line in this pass; where cited below it is because a specific
   claim was checked against code.

**The real, load-bearing contradiction in this codebase is architecture-doc-vs-code**, not
client-doc-vs-code. The table below documents that gap precisely, with line citations on both
sides, and does not attempt to resolve it — per instructions, a design document describing
intended behaviour that was subsequently descoped/simplified during implementation is a decision
for the client/product owner to ratify (either "implement as designed" or "update the
architecture doc"), not for this audit to pick a side on.

## Section 8 — Contradictions (Code vs Architecture vs Business-rule docs vs Client docs)

| # | Rule | Code behaviour | Architecture doc | Business-rule/client docs | Which is actually running | Recommended documentation treatment | Client decision needed? |
|---|---|---|---|---|---|---|---|
| CT1 | Punch rounding | Never applied to punch instants (`calculation.py:594-613` defined, unreferenced for this purpose) | §11.6 (`WORKFORCE_ATTENDANCE_ARCHITECTURE.md:1003-1006`): "Applied to punch times for evaluation only... Rounded instants are stored on AttendanceDay (`first_in_rounded_at`, etc.)" — **`AttendanceDay` has no `first_in_rounded_at` column at all** (confirmed against `models.py:464-568`, full field list read) | `ATTENDANCE_V1_COMPLETE.md:510,1169,1292`: correctly states "STORED BUT NOT USED" / "No rounding is applied" | Code (no rounding) | Update architecture §11.6 to either match code or be marked "not yet built — see gap list"; the `first_in_rounded_at` column reference is stale/aspirational and should be struck or built | **Yes** — is punch rounding a real client requirement (e.g. biometric device drift)? |
| CT2 | Missing-punch `AUTO_CLOSE` | Falls through to ordinary band-based status; `auto_closed` hard-coded `False`, never a synthetic OUT punch (`calculation.py:1021,1299-1300`) | §11.5 (line 997-998): "`AUTO_CLOSE` uses shift end (or last IN + scheduled minutes) and flags `auto_closed`" | `ATTENDANCE_V1_COMPLETE.md:503,519,1158,1296`: correctly flags this as a "known naming trap" / KNOWN LIMITATION | Code (no auto-close) | Same as CT1 — architecture describes unbuilt behaviour as if shipped | **Yes** — the client doc itself recommends relabeling the UI control to avoid false confidence; this is an actionable near-term fix even without building the feature |
| CT3 | Flexible-shift core hours | `core_start`/`core_end`/`core_hours_breach_behaviour`/`early_out_uses_core_end` resolved into inputs but never read by any evaluation branch (`calculation.py` — no reference in `_evaluate_fixed_or_flex`) | §11.8 (line 1019-1023): full table describing core-breach detection and its consequence (FLAG/HALF_DAY/ABSENT), and "before core_end if `early_out_uses_core_end`" | `ATTENDANCE_V1_COMPLETE.md:431,995,1069,1134,1294,1308`: correctly flags "not enforced today", high-priority gap for flex-shift clients | Code (not enforced) | Same treatment | **Yes** — client doc already flags this as high-priority if flexible shifts are widely used |
| CT4 | Mandatory break with no punched gap | Never auto-deducted; `is_mandatory` carried through but unread (`calculation.py:23-28` documents this as a known, deliberate simplification) | §10.2 names `DEDUCT_SCHEDULED` as an intended behaviour (line 883) | Not sampled directly in this pass — recommend the client-doc author cross-check | Code | The `calculation.py` module docstring already self-documents this — recommend porting that exact language into architecture §10.2 as a "not yet implemented" note | Lower priority — same underlying "auto-deduct unpunched mandatory break" feature as CT2's shift-end-based synthesis |
| CT5 | WFH / On-Duty as day-level statuses | `attendance_status` values `WFH`/`ON_DUTY` exist in the DB CHECK/enum but are **never written** by `evaluate_day` anywhere (`calculation.py:1283` comment: "Leave/WFH/ON_DUTY overlays are W4 no-ops"). `wfh_requires_punch`/`on_duty_requires_punch`/`wfh_uses_shift_hours` policy fields are unread. A WFH/ON_DUTY-typed regularization request only ever produces ordinary synthetic punches, never a WFH/ON_DUTY status | §11.7 (line 1007-1010): describes THREE distinct mechanisms for day-level WFH — "roster flag, regularization type WFH, or punch source WEB/MOBILE combined with policy" — **none of the three exist in code**: `ShiftRoster` has no WFH-specific field (only `is_week_off_override`/`is_holiday_working_override`, `models.py:398-399`); regularization-type WFH doesn't set the status (confirmed); punch `source` is never read to infer WFH anywhere in `calculation.py` | `ATTENDANCE_V1_COMPLETE.md:512,521,633-635,997,1176,1298,1330,1353` (`PD-WFH-1`): correctly and extensively documents this as unimplemented, "not available until a client decision is made" | Code (none of the 3 architected mechanisms exist) | Architecture §11.7 should be marked speculative/future — it describes a 3-mechanism design that has zero implementation, not a partial one | **Yes** — this is the single largest gap between architecture ambition and shipped code in the whole module; needs an explicit product decision on which (if any) of the 3 mechanisms to build |
| CT6 | Night-shift OT classification | `is_night` for OT purposes is *always* `shift.is_cross_midnight` (`calculation.py:1062,1212,1229`) — there is no independent "is this shift a night shift" concept in `ShiftInputs` at all | §9.5 (line 830-831), explicitly and emphatically: **"`is_night_shift` is an explicit flag (night OT classification), not inferred solely from times."** Also §6.1 area (line 133) lists `is_night_shift` as a field alongside `is_cross_midnight` as if both exist and are distinct | `ATTENDANCE_V1_COMPLETE.md:672,1193,1196,1317`: correctly documents that only the cross-midnight flag is checked, and that the configured night window is unused | Code (inferred solely from cross-midnight, exactly what architecture says must **not** happen) | This is the sharpest contradiction found in the audit: architecture doesn't just omit a feature, it states a negative requirement ("not inferred solely from times") that the shipped code directly violates. Architecture doc needs correction or the shift model needs an explicit `is_night_shift` field | **Yes — highest priority of all contradictions found.** If any client has night-shift/security/manufacturing OT differential requirements, this is the one most likely to produce wrong payroll-facing facts silently (a genuinely overnight shift with `night_ot_mode=SHIFT_FLAG`, the default, will simply never show NIGHT-classified OT) |
| CT7 | OT eligibility "by grade" | `GRADE_VIA_ASSIGNMENT` behaves identically to `ALWAYS` — no grade/designation lookup at all (`calculation.py:668-671`, no third branch) | §12.1 (line 1040) lists `GRADE_VIA_ASSIGNMENT` as one of 4 values with no further elaboration on how it should read the grade — the architecture doc itself does not fully specify the mechanism, so this is closer to an incomplete spec than an outright contradiction | `ATTENDANCE_V1_COMPLETE.md:670,1184,1318` (`ND-07`): correctly flags as KNOWN LIMITATION, "high priority to resolve before go-live if grade-based eligibility is a real requirement" | Code (no grade check) | Architecture should specify exactly which `EmployeeAssignment`/grade field this mode is meant to read before it's built | **Yes** — flagged as high-priority pre-go-live by the client doc already |
| CT8 | Regularization `blocked_when_locked` | Field exists, is settable, but the actual lock check is unconditional and ignores it (`service.py:3410` comment states this explicitly) | Not found as an explicit statement either way in the architecture doc's lock section (§13/§30) — the field's *existence* predates the lock mechanism by design (per the model's own docstring, `models.py:478`), so this reads as an intentional "ships ahead of use" pattern rather than a doc contradiction | Not sampled in the client doc set for this specific field | Code (field is inert) | Recommend adding one line to whichever policy-config screen surfaces this field, clarifying it currently has no effect (mirrors the "auto-close" naming-trap recommendation) | Lower priority — cosmetic/UX risk (a policy author could believe it's a working escape hatch) rather than a business-rule ambiguity |
| CT9 | Leave vs Overtime precedence | No code clears `ot_minutes_detected`/`ot_pending` when a full-day leave overlay overwrites `attendance_status=LEAVE` (see `ATTENDANCE_OVERRIDE_MATRIX.md`) | Not addressed in architecture §19.3/§19.4/§21 — the leave-overlay precedence table doesn't mention OT as an input at all | Not addressed in the sampled client docs either | Code (whatever falls out of execution order — OT stays) | This is a genuine spec gap, not just an implementation gap — no document anywhere states the intended precedence | **Yes — needs a fresh product decision**, not just a documentation fix, since no source of truth has ever answered this question |
| CT10 | 8-level policy-assignment scope order | Architecture and code agree exactly (`EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH > LEGAL_ENTITY > COMPANY`) | §15-16 (per `calendar_resolution.py:12-14` citation) | Consistent | Code == Architecture | No action needed — included here to demonstrate this audit checked for false negatives too, not just confirmed the known gaps | No |
| CT11 | Timezone precedence (3-tier) | `ShiftVersion.timezone > Branch.timezone > Company.timezone`, exactly 3 tiers, no employee-level override | §6.4 (line 605-615): identical 3-tier statement | Not contradicted anywhere sampled | Code == Architecture | No action needed | No |
| CT12 | Holiday-on-weekly-off (no auto-substitute) | Stays `WEEKLY_OFF`, flagged, explicitly marked `PD-CAL-2` (open decision) in the code comment itself (`calendar_resolution.py:210-212`) | Consistent — architecture doesn't claim auto-substitution is built | `ATTENDANCE_V1_*` docs (per user-supplied prior context) correctly describe this as-is | Code == Architecture (both silent on auto-substitute) | No action needed on documentation; remains an open product decision, not a doc gap | Yes, but already correctly flagged as OPEN, not a documentation defect |

## Section 11 — Test Coverage Audit

Legend: **TESTED** (a dedicated test asserts this exact behaviour) / **PARTIALLY TESTED** (covered
incidentally by a broader test, or only one branch of a multi-branch rule is exercised) / **NOT
TESTED** (no test found).

### Single-rule coverage (representative sample of the highest-risk rules)

| Rule | Coverage | Evidence |
|---|---|---|
| Employment gate (NOT_JOINED/EXITED) | TESTED | `test_evaluate_day_not_joined/exited` (unit), `test_not_joined_before_employment_gate` (integration) |
| CONFIG_ERROR (no calendar / no policy) | TESTED | `test_evaluate_day_config_error_no_calendar/no_policy`, `test_config_incomplete_without_policy_assignment` |
| Punch pairing (all 5 shapes) | TESTED | 5 dedicated unit tests |
| Duplicate-punch collapsing | TESTED | 2 dedicated unit tests |
| Grace-in/out | PARTIALLY TESTED | `test_evaluate_day_late_beyond_grace` covers late-in; no dedicated early-out-grace unit test found by name (early departure is exercised indirectly through `_evaluate_fixed_or_flex`'s shared code path, but not asserted on directly) |
| Missing-punch behaviour: INCOMPLETE/ABSENT | TESTED | `test_evaluate_day_no_punches_working_day_defaults_incomplete`, `..._absent_when_policy_says_absent` |
| Missing-punch behaviour: AUTO_CLOSE | **NOT TESTED** | No test found asserting on the AUTO_CLOSE branch specifically (consistent with the finding that it has no distinct observable behaviour to test) |
| Missing-punch behaviour: REQUIRE_REGULARIZATION | **NOT TESTED** | Same — no distinct branch exists |
| Multi-punch modes (PAIR_ALL/FIRST_IN_LAST_OUT) | TESTED | `test_presence_span_pair_all_excludes_gap`, `..._first_in_last_out_includes_gap` |
| Break paid/unpaid arithmetic | TESTED | `test_unpaid_break_gap_already_excluded_not_double_subtracted`, `test_paid_break_gap_added_back_to_worked_minutes` |
| Break excess flagging | PARTIALLY TESTED | `is_excess` computation exists in `match_breaks`; no test found specifically asserting `is_excess=True` for an over-length break |
| Core hours breach | **NOT TESTED** | Consistent with non-implementation |
| Punch rounding applied to instants | **NOT TESTED** (only the pure `round_minutes` function is unit-tested, never its application to a punch) | `test_round_minutes_up_down_nearest` tests the primitive only |
| Roster overrides (week-off / holiday-working) | TESTED | 5 unit tests + `test_roster_week_off_override_marks_not_expected`, `test_roster_null_shift_without_override_falls_through_to_missing_shift_behaviour` (integration) |
| Split-shift missed-block behaviours (IGNORE/HALF_DAY/ABSENT/REQUIRE_REGULARIZATION) | PARTIALLY TESTED | Only the OT-detection happy path is directly unit-tested (`test_evaluate_day_split_shift_detects_overtime`); the 4 distinct `split_shift_missed_block_behaviour` branches are not each individually asserted by name in the grepped test list |
| Leave: full-day paid/unpaid | TESTED | `test_sync_full_day_paid_leave_no_punches`, `..._unpaid_leave_no_punches` |
| Leave: half-day paid/unpaid, multiple half-days summing to 1.00 | TESTED | `test_sync_half_day_paid_leave_no_punches`, `test_multiple_half_day_projections_sum_to_full_day` |
| Leave: half-day + full-day punches present | TESTED | `test_half_day_unpaid_leave_with_full_day_punches` |
| Leave: KEEP_LEAVE vs PRESENT_CANCEL_LEAVE_HINT | TESTED | `test_full_day_leave_keep_leave_behaviour_overrides_punches`, `..._present_cancel_leave_hint_flags_and_keeps_punch_status` |
| Leave: overlapping-fraction rejection | TESTED | `test_overlapping_leave_fractions_rejected` |
| Leave: overrides roster week-off | TESTED | `test_leave_overrides_roster_week_off_not_expected` |
| Leave vs Overtime interaction | **NOT TESTED** | No test found combining an approved full-day leave projection with punches that would independently trigger OT detection |
| Leave: locked-period refusal (sync + cancel) | TESTED | `test_sync_refused_when_period_closed`, `test_cancel_refused_when_period_closed` |
| Leave + auto-regularization recompute | TESTED | `test_leave_plus_auto_regularization_recompute_keeps_leave_status` |
| Regularization: backdating window, monthly cap, reason/attachment gating, allowed types | TESTED | one dedicated test per rule (see Master Rule Matrix §L) |
| Regularization: self-approval block | TESTED | `test_self_approval_blocked` |
| Regularization: MANAGER_THEN_HR two-stage chain | TESTED | `test_manager_then_hr_two_stage_chain` |
| Regularization: no-manager-resolved routes to HR | TESTED | `test_no_manager_resolved_routes_to_hr` |
| Regularization: WRONG_SHIFT applies via roster | TESTED | `test_wrong_shift_applies_via_roster` |
| Regularization: locked-period blocks new request | TESTED | `test_locked_day_blocks_new_request`, `test_regularization_submit_rejected_for_closed_period_date` |
| Regularization + Overtime combination (regularizing a day with an existing pending/terminal OT record) | **NOT TESTED** | No test found combining these two workflows on the same attendance day |
| OT: min-threshold, rounding, daily/weekly/monthly caps | TESTED | `test_daily_threshold_and_rounding_applied`, cap tests (unit + `test_weekly_cap_clamps_second_day_in_same_week` integration) |
| OT: eligibility ALWAYS vs GRADE_VIA_ASSIGNMENT distinction | **NOT TESTED** | No test proves these two modes behave differently (consistent with the finding that they don't) |
| OT: approval chains (AUTO/MANAGER/MANAGER_THEN_HR/HR), self-approval block, no-manager-routes-to-HR | TESTED | Full set — see Master Rule Matrix §M |
| OT: frozen terminal decision across recompute | TESTED | `test_approved_overtime_frozen_across_later_recompute` |
| OT: comp-off fact + expiry, not credited while pending | TESTED | `test_comp_off_fact_with_expiry_on_auto_approval`, `..._not_credited_to_day_while_pending` |
| OT: night classification actually driven by configured window (as opposed to cross-midnight) | **NOT TESTED (and cannot be — the behaviour doesn't exist)** | `test_classify_ot_day_night_requires_window_or_both_mode` only proves the *mode gate*, not that the window itself is consulted |
| OT: SPLIT-shift detection | TESTED | `test_evaluate_day_split_shift_detects_overtime`, `..._no_overtime_policy_detects_nothing` |
| OT + locked period (approve/reject refused) | TESTED | `test_overtime_approve_rejected_for_closed_period_date` |
| Period: all 6 finalize blockers | TESTED | one dedicated test each (see Master Rule Matrix §N3) |
| Period: incomplete-at-lock resolution (TREAT_ABSENT/TREAT_PRESENT/KEEP_INCOMPLETE) | PARTIALLY TESTED | `KEEP_INCOMPLETE` (blocks) and default `TREAT_ABSENT` (resolves) both tested; **no test found asserting the `TREAT_PRESENT` branch specifically** |
| Period: lock blocks every mutation type (punch/roster/regularization/recompute/OT-approve/leave-sync/leave-cancel) | TESTED | 7 dedicated tests, one per mutation surface — comprehensive |
| Period: reopen unlocks + re-finalize regenerates summary | TESTED | `test_reopen_unlocks_days_and_refinalize_regenerates_summary` |
| Period: concurrency (stale If-Match, simultaneous finalize) | TESTED | `test_stale_if_match_on_finalize_rejected`, `test_simultaneous_finalize_only_one_wins` (and equivalents for OT/regularization) |
| RBAC/DataScope: self/reportees/reportee-tree scope, cross-tenant isolation, forged employee/company IDs | TESTED | `test_attendance_security.py` — 13 tests, broad coverage |

### Combination-scenario coverage (spec Section 11's explicit list)

| Combination | Coverage |
|---|---|
| Holiday + weekly-off | TESTED (organisation-module calendar classification; not re-verified line-by-line here but confirmed via `calendar_resolution.py:208-218` logic read directly) |
| Holiday + roster | PARTIALLY TESTED — `test_roster_holiday_working_override_present`/`..._no_punches_still_not_expected` cover roster-vs-holiday; no test found for "holiday + published roster shift assigns a *different* shift than the assignment default" combined with holiday-working |
| Holiday + punches | TESTED — `test_evaluate_day_worked_on_weekly_off` proves the weekly-off analogue; a dedicated holiday-plus-punches unit test was not separately confirmed by name (the mechanism is identical, `day_type == "HOLIDAY"` branch shares code with weekly-off, `calculation.py:1053-1054`) |
| Weekly-off + roster | TESTED — `test_roster_week_off_override_marks_not_expected`, `test_evaluate_day_roster_week_off_override_wins_over_working_calendar` |
| Roster + shift-policy (different shift ⇒ different policy resolution) | **NOT TESTED** — no test found where a roster-assigned shift changes *which policy* resolves through the 8-level walk (roster only changes the shift ID; policy resolution is scope-based on assignment fields, not on the roster's shift — this combination may be a non-issue by design, but nothing proves it either way) |
| Leave + punches | TESTED (multiple, see above) |
| Leave + OT | **NOT TESTED** (see CT9) |
| Half-day-leave + punches | TESTED |
| Split-shift + missing-block | PARTIALLY TESTED (happy path only, see above) |
| Night-shift + midnight | PARTIALLY TESTED — cross-midnight scheduling is tested (`test_scheduled_span_cross_midnight_attributes_to_start_date`); NIGHT OT classification's actual (non-)behaviour is tested for the mode-gate only, not for a genuine midnight-spanning OT scenario end-to-end |
| Multi-punch + breaks | TESTED |
| Regularization + OT | **NOT TESTED** |
| Regularization + lock | TESTED |
| OT + caps | TESTED (daily/weekly/monthly, all 3) |
| Lock + every mutation type | TESTED (comprehensive — 7 surfaces) |
| Employee-transfer mid-period | **NOT TESTED** — no test found changing `EmployeeAssignment` (branch/shift/manager) mid-way through an open period and checking the day-by-day consequence |
| Policy-change mid-period | **NOT TESTED** — no test found publishing a new policy version mid-period and checking that already-calculated days keep their originally-resolved version (WD-11 reproducibility) while later days pick up the new one |
| Shift-change mid-period | **NOT TESTED** — similar to policy-change; `ShiftVersion` effective-dating exists (organisation module) but no attendance-side test was found exercising a shift-version change mid-period |
| FLEXIBLE-shift end-to-end evaluation | **NOT TESTED** — see Master Rule Matrix F1; `resolve_schedule_window`'s FLEXIBLE branch exists in code but no unit/integration test isolates a FLEXIBLE-shift day's late/early/hour-band outcome |

## Consolidated DOCUMENTATION GAP / IMPLEMENTATION GAP list

Pulled from all six deliverables into one place, deduplicated. Counted total at the end.

**DOCUMENTATION GAP** (code behaves consistently and deliberately; the written docs disagree,
are silent, or could mislead a reader):
1. CT1 — punch rounding described as working in architecture §11.6 including a non-existent
   `first_in_rounded_at` column
2. CT2 — AUTO_CLOSE described as working in architecture §11.5
3. CT3 — core hours described as enforced in architecture §11.8
4. CT4 — `DEDUCT_SCHEDULED` named in architecture §10.2 with no corresponding field ever added
5. CT5 — WFH/On-Duty described as having 3 working mechanisms in architecture §11.7
6. CT6 — architecture §9.5 states `is_night_shift` must be an explicit flag "not inferred solely
   from times"; code does exactly the opposite
7. CT8 — `blocked_when_locked` field is inert; not documented as such anywhere a policy author
   would see it
8. HR1-HR12 in `ATTENDANCE_CONFIGURATION_AUDIT.md` (hidden rules not written down anywhere) — 12
   items
9. C3 (DST) in `ATTENDANCE_MASTER_RULE_MATRIX.md` — untested, unproven either way
10. L10 (`blocked_when_locked`) — duplicate of CT8, counted once

**IMPLEMENTATION GAP** (a documented/configured behaviour that code does not deliver, or delivers
only partially, distinct from a pure documentation mismatch):
1. H3/CT2 — `missing_punch_behaviour=AUTO_CLOSE` (no synthetic close, no `auto_closed=True`)
2. H3 — `missing_punch_behaviour=REQUIRE_REGULARIZATION` has no distinct code path
3. F1 — FLEXIBLE shift evaluation is unverified by tests (code exists, confidence is low)
4. F7/CT3 — core hours never enforced
5. H2/CT1 — punch rounding never applied
6. H5 — half-day split method (BY_HOURS/BY_MIDPOINT) never applied
7. H8 — core-hours-breach behaviour never applied (tied to F7)
8. H10/CT5 — WFH/On-Duty statuses never produced
9. H13/H14 — late/early band `counts_toward_cap`, `lates_to_half_day_count`,
   `early_departure_requires_approval` never applied
10. G3 — mandatory break with zero punched gap never auto-deducted (self-documented as a known
    limitation, not silently discovered — listed here for completeness)
11. G4 — `excess_break_behaviour` never applied
12. L9 — `auto_approve_within_minutes` never applied
13. M1/CT7 — `GRADE_VIA_ASSIGNMENT` OT eligibility behaves like `ALWAYS`
14. M5/CT6 — NIGHT OT classification decoupled from the configured night window; default mode
    never produces NIGHT at all
15. Split-shift `split_shift_block_mandatory`/`split_shift_allow_hours_compensation` never applied
16. CT9 — Leave vs Overtime precedence unresolved (also a spec gap, not just implementation)

**Total distinct DOCUMENTATION GAP + IMPLEMENTATION GAP items catalogued in this audit: 32**
(10 documentation-gap items + 16 implementation-gap items + 6 untested-combination items promoted
to gap status because no evidence exists either way: FLEXIBLE-shift evaluation, employee-transfer
mid-period, policy-change mid-period, shift-change mid-period, Leave+OT, Regularization+OT — these
6 are counted once each above where they overlap with the two main lists, not double-counted).

---

*Compiled 2026-08-21. Every contradiction row cites both a code location and a documentation
location; every test-coverage row was checked against the actual grepped test function list in
`apps/api/tests/unit/modules/attendance/test_calculation.py` and
`apps/api/tests/integration/modules/attendance/*.py` on the same date.*

