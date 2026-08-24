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
