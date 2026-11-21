# Attendance test scenario matrix

19 November 2026. Planning only; nothing was run. "Current" is from reading the code (or carried from the 16 Nov
reports, marked *carried*). "Coverage" says whether an existing test covers the scenario as far as I could find by
search; "none found" means a gap to fill, not proof that none exists. Engine-level cases with probe ids (G1, IP2,
L7 …) are in `docs/audits/ATTENDANCE_CROSS_MODULE_SCENARIO_MATRIX.md`; this matrix adds the result-to-screen
columns.

Legend for Web / Mobile: ✓ shown correctly · ✗ shown wrongly · ~ partly · ? not checked.

## 1. Punch processing and live day

| ID | Scenario | Expected outcome | Current backend / DB | Web | Mobile | Payroll | Coverage |
|---|---|---|---|---|---|---|---|
| S-01 | Normal day, on time, IN and OUT | PRESENT, worked = paired minutes − unpaid break | PRESENT | ✓ | ✓ | paid 1 | engine unit tests |
| S-02 | Checked in, shift still running | "Working", no verdict | `INCOMPLETE` (or `ABSENT` under policy), `missing_punch` true | ✗ badge Incomplete / Absent (AUD-03) | ✓ provisional | none until lock | none found for display |
| S-03 | No punch yet, before shift start, today | "Not in yet" | Row only after 09:30 sweep; then `INCOMPLETE` | ✗ summary counts Incomplete; home dashboard ✓ Not checked in | ✓ provisional | — | overview test ✓; summary none |
| S-04 | Missing OUT, day over | INCOMPLETE with deadline and consequence | INCOMPLETE | ~ no consequence (AUD-07) | ~ same | LOP at lock under TREAT_ABSENT | finalize tests ✓; display none |
| S-05 | Missing IN (OUT only) | INCOMPLETE | INCOMPLETE | ~ | ~ | as S-04 | engine ✓ |
| S-06 | Multiple IN/OUT pairs | Sum of pairs | pairing in snapshot | ✓ timeline | ✓ | — | engine ✓ |
| S-07 | Duplicate punch (same instant) | Collapsed once | `collapsed_punch_ids` | ✓ | ✓ | — | engine ✓ |
| S-08 | Out-of-order punch (OUT and IN same instant) | OUT first | fixed `fdfa6b2` | ✓ | ✓ | — | engine ✓ |
| S-09 | Overnight shift 22:00–06:00 | Owned by start date | ownership window | ✓ | ✓ | — | engine ✓ (*carried*) |
| S-10 | Face-enrolled employee punches on web | Refused with "use mobile app" | `FACE_VERIFICATION_REQUIRED` | ✓ since `58cc67e` | n/a | — | web test ✓ |
| S-11 | Geofence required, web punch | Refused with guidance | `LOCATION_REQUIRED` | ✓ since `58cc67e` | ✓ GPS flow | — | ✓ |
| S-12 | Mobile punch with no network | Clear error, or queued if D-AUD-4 | no queue (AUD-16) | n/a | ~ error only | — | none |
| S-13 | Same punch submitted twice (retry) | One punch | ? idempotency not checked in this audit | ? | ? | — | **needs runtime check** |
| S-14 | Punch after period closed, owned by locked day | Reported / blocked | counted nowhere (MA-06, *carried*) | ✗ | ✗ | missed | reproduced 16 Nov |

## 2. Working hours, status and policy

| ID | Scenario | Expected | Current | Web | Mobile | Payroll | Coverage |
|---|---|---|---|---|---|---|---|
| S-15 | Late within grace | PRESENT, not late | per policy | ✓ | ✓ | paid 1 | engine ✓ |
| S-16 | Late beyond grace | PRESENT + late flag; reason shows grace and minutes | late flag | ~ no grace shown (AUD-06) | ~ | per bands | engine ✓; display none |
| S-17 | Late beyond mark ceiling → HALF_DAY | HALF_DAY with reason | HALF_DAY; ceiling includes grace (MA-09, *carried*) | ✗ no reason | ✗ | 0.5 LOP | engine ✓ |
| S-18 | Early departure | Early flag; reason | flag | ~ | ~ | per bands | engine ✓ |
| S-19 | Worked below half-day threshold | HALF_DAY / ABSENT with threshold in reason | band status | ✗ no threshold | ✗ | per band | engine ✓ |
| S-20 | Hour bands with a gap | CONFIG_ERROR (if H-01 decided) | PRESENT, full pay (MA-01) | ✗ | ✗ | overpaid | reproduced 16 Nov |
| S-21 | Excess break | flag + excess minutes | flag | ✓ table | ✓ | per policy | ✓ |
| S-22 | Unresolved (open) break | exception | flag | ~ counted on home dashboard only (AUD-10) | ~ | — | none for counts |
| S-23 | Overtime found, pending approval | "found X, waiting" | detected > 0, approved 0, `ot_pending` | ~ badge shows detected only (AUD-14) | ~ | pays approved only | display none |
| S-24 | Overtime partly approved | found / approved shown | | ✓ time summary; ✗ badge | ✓ | approved | display none |
| S-25 | Part-time shift, full attendance | PRESENT (if P-05) | HALF_DAY (MA-05) | ✗ | ✗ | 0.5 LOP | reproduced |
| S-26 | Approved ON_DUTY regularization | ON_DUTY | ON_DUTY overlay | ✓ | ✓ | paid | ✓ |
| S-27 | Approved WFH regularization | Per D-AUD-3 | WFH status never produced (AUD-13) | ? | ? | ? | **needs runtime check** |
| S-28 | Core-hours breach (flex) | flag or HALF_DAY per policy | per policy | ~ "Core hours breach" without times | ~ | per policy | engine ✓ |

## 3. Calendar overlays

| ID | Scenario | Expected | Current | Web | Mobile | Payroll | Coverage |
|---|---|---|---|---|---|---|---|
| S-29 | Holiday, no punches | "Holiday: <name>" | NOT_EXPECTED + HOLIDAY | ✗ day headline "Weekly off" (AUD-04); badge "Not expected"; calendar ✓ Holiday | ✓ Holiday | paid 1 | **none** for headline |
| S-30 | Worked on holiday | PRESENT + worked-on-holiday; OT class holiday | flags | ✓ | ✓ | OT holiday class | ✓ |
| S-31 | Weekly off, no punches | Weekly off | NOT_EXPECTED + WEEKLY_OFF | ✓ | ✓ | paid / per pattern | ✓ |
| S-32 | Roster week-off with shift-scoped policy | resolves | CONFIG_ERROR (MA-04) | ✗ | ✗ | blocks close | reproduced |
| S-33 | Full-day approved leave | On leave | LEAVE | ✓ | ✓ | leave 1 | ✓ |
| S-34 | Half-day leave + worked other half | split | PRESENT/HALF_DAY with `leave_fraction 0.5` | ~ month counts as whole present (AUD-09) | ~ | 0.5 / 0.5 | period summary ✓; client counts none |
| S-35 | Half-day leave + no punches | per H-07 | *carried* | ? | ? | per decision | reproduced |
| S-36 | Half-day leave on a day that became a day off | per H-08 | 0.50 LOP until HR reconciles (MA-08) | ✗ | ✗ | under-paid | reproduced |
| S-37 | Punched on approved leave | flagged; HR keeps leave or cancels | `work_on_leave_flagged` | ✓ fixes | ✓ fixes | per decision | ✓ |
| S-38 | Holiday added after leave approved | leave refunded / reconciled | (AC-03, *carried*) | ? | ? | ? | reproduced |

## 4. Changes, recalculation, concurrency

| ID | Scenario | Expected | Current | Coverage |
|---|---|---|---|---|
| S-39 | Shift reassigned for a past date | That date and neighbour recalc | own date only (MA-07) | reproduced |
| S-40 | Policy version published backdated | Affected unlocked days recalc | recalc queue (`recalc.py`) | ✓ |
| S-41 | Calendar edit | recalc | fixed in engine 16 (`6e15d07`) | ✓ |
| S-42 | Correction approved | Day recalculates; status updates on both apps | synthetic punches + recalc | ✓ API; display refresh ✓ web (18 Nov) |
| S-43 | Correction rejected | Day unchanged; request shows rejected with reason | | ? display |
| S-44 | Punch during the 09:30 sweep for the same row | Both succeed, row consistent | per-row transactions + `FOR UPDATE` (`tasks.py` docstring) | measured earlier per docstring; **runtime check** |
| S-45 | Beat fires twice / misses a day | Idempotent; trailing 3 days absorbs | full-row replace | ✓ by design |

## 5. Aggregation and cross-surface consistency (new, all untested)

| ID | Check | Expected | Current |
|---|---|---|---|
| X-01 | Same date, same filters: home dashboard vs Attendance page Present | equal | differ when any HALF_DAY, open punch or CONFIG_ERROR (AUD-01) |
| X-02 | Attendance rate vs HR calendar for a department with half days | consistent weighting | 0 vs 0.5 (AUD-02) |
| X-03 | Past date with a missing row: totals | employee shown as "Not calculated" | dropped from summary (AUD-08) |
| X-04 | Employee month card vs payroll period summary | equal paid / LOP / leave | differ with fractional days (AUD-09) |
| X-05 | "Needs attention" count vs mismatch banner vs KPI exceptions | equal | four definitions (AUD-10) |
| X-06 | Web label vs mobile label for each status | equal | differ for NOT_EXPECTED / WFH (AUD-11) |
| X-07 | OT on day screen vs OT in payroll input | labelled so they reconcile | detected vs approved (AUD-14) |
| X-08 | Month end in IST: day 31 at 23:30 IST punch | owned by 31st, in that month's period | per timezone remediation; **runtime check** with an IST-midnight fixture |
| X-09 | Year-end leave-year rollover and attendance period crossing 31 Dec | correct period | not checked here |

## 6. Gaps to fill first

1. X-01 to X-07 as one integration test (roadmap R-G01).
2. S-02, S-03, S-29 as web component tests and one Playwright flow (R-D01, R-D02, R-G02).
3. HALF_DAY cases in `test_attendance_summary.py` and `test_company_attendance_overview.py` (none today).
4. S-13 and S-44: confirm by a runtime probe before deciding whether a fix is needed.
