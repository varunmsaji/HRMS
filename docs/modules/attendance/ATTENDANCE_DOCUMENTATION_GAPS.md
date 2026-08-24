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
