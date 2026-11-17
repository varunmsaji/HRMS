# Attendance engine 16 — pre-commit remediation of the independent review (R-1 … R-8)

**Date:** 16 November 2026 · **Branch:** `test` at `dd71571`, working tree only · **Nothing staged,
committed or pushed.** · Source: `ATTENDANCE_ENGINE_16_PRE_COMMIT_REVIEW_2026-11-16.md`.
Payroll code was not touched. No historical recalculation was run. `MOBILE_UX_NEXT_STEPS.md` was not
touched and must stay out of the commit. The already-reviewed engine 16 behaviour is unchanged except
where a finding required it (R-2); the 14 → 16 engine numbering stands (engine 15 never shipped).

## 1. Result in one paragraph

All eight findings are fixed in code and, except R-8's wording, covered by tests that pass. The three
blockers (R-1 leave restoration, R-2 late-mark credit, R-3 drift resolution) are closed in code. **Two
things still need the owner before historical recalculation:** the R-2 ceiling (built as a default of
59 minutes per end) and the policy-A question behind R-3. **One thing could not be verified here:**
the Flutter app (no Flutter on this machine; CI runs it). The three new migrations must be applied
before the code is deployed, and because the change touches `alembic/` the pull request will not
auto-merge.

## 2. How to read the status words

| Word | Meaning here |
|---|---|
| **Fixed** | The code change is in the working tree. |
| **Tested** | A test written or kept for this finding exercises the behaviour and passed in the final runs of section 5. |
| **Code-reviewed** | The change was read against the finding by the author only. This is **not** an independent review; the independent reviewer should re-read R-1 to R-8. |
| **Not tested** | No automated test covers it. |
| **Outstanding** | Work or a decision still open. |

## 3. Finding-by-finding results

| ID | What was fixed | Fixed | Tested | Code-reviewed | Not tested | Outstanding |
|---|---|---|---|---|---|---|
| **R-1** leave never re-charged after every day was released | The half of a half-day leave now lives on `leave_application.half_day` (migration `20261116110000`, backfilled), and `_application_discrepancies` no longer returns early when there are no day rows. A fully released leave is re-derived from its own range and half and re-debited, projected or turned into a shortfall exactly like any other. | Yes | Yes. 5 integration tests (`test_leave_full_release_restoration.py`): single full day, single half day (same half restored), multi-day with all days released and restored one at a time, repeated release/restore cycles then cancellation, cancel while fully released. Each asserts balance, append-only ledger, active projections and the absence of `LEAVE_CALENDAR_MISMATCH`. The 6 existing reconciliation tests still pass. Migration upgraded, downgraded 3 and re-upgraded on a restore of the dev data; the legacy half value `FIRST` is copied | Yes | Concurrent restoration of the same application is covered only through R-3's concurrent-apply test, not as a separate R-1 test. Applications whose days were **already** all released before this fix have lost their half-day marker (see Outstanding) | Existing broken rows are not repaired by the migration; `attendance_integrity_report.sql` §7 lists them (the dev database has none). A released LOP day comes back as a normal debit, not LOP (documented) |
| **R-2** late mark credited unworked time | Late/early mark credit to the hour-band lookup is bounded by `MARK_CREDIT_CEILING_MINUTES` = 59 per end (or the policy's grace if larger). The mark itself (`late_minutes`, `is_late`, classification) is unchanged. Published policy versions are not edited. Snapshot gains `capped` and `ceiling`. | Yes | Yes. 180 unit tests (`test_late_mark_credit_ceiling.py`, 168 run + 12 intentionally skipped grid cells): the review's reproduction (13:00 in, `LATE` 31-240 → `HALF_DAY`, not `PRESENT`), the early-departure mirror, 59 vs 60 vs 90 minutes late, an open-ended `NONE` band, each end capped separately, a marks-within-ceiling case that still behaves as D-01 intended, larger grace still fully forgiven, snapshot fields, and a grid invariant. All existing attendance unit tests pass (946) after one snapshot-shape update | Yes | A policy with **no** late/early bands still has the one-minute cliff (unchanged, documented). Split-shift path has no mark credit (unchanged). No integration test for R-2 | **Owner decision:** keep 59, choose "no credit", or per-policy. **Impact report must be run** (`scripts/sql/late_mark_band_impact_report.sql`) before recalculating; dev result in §6 |
| **R-3** no resolution path for leave drift | New `POST /v1/leave-reconciliation/preview` and `/apply` (company scope, `LEAVE.BALANCE_ADJUST`). Preview is read-only with per-date outcome and a digest; apply re-derives under the locks, refuses a stale digest (409, nothing written), requires reason and `Idempotency-Key`, runs in one transaction, is a no-op when nothing is left, writes a per-application timeline entry, audit rows and one run-level audit row, never touches a closed period, and never converts a shortfall to LOP. | Yes | Yes. 8 integration tests (`test_leave_reconciliation_operation.py`): weekly-off change (preview read-only, wrong digest refused, apply, replay, repeat is a no-op, history append-only, audit rows, timeline carries the reason, close blocker clears); shortfall stays an exception and `lop_days` stays 0; roster week-off after approval; shift that operates on the weekly off after approval; stale preview; closed-period protection; **two simultaneous applies change the leave once**; permissions (no permission, company-less scope) and the window bound | Yes | No UI (API only). Work-calendar assignment drift and pending (`SUBMITTED`) leave are not covered (pending leave is not reconciled by design). No load test | **Owner:** the policy-A conflict (should a pattern change be reported at close at all, or applied by default?). Optional: a screen, and a scheduled run |
| **R-4** cap cascade stopped at the month boundary | The sibling-day pass now runs to the end of the second month when the week spans two months and a monthly cap exists, and to the week's last day for a weekly cap alone. | Yes | Yes. 2 integration tests across 31 Aug – 8 Sep 2026: weekly 90 + monthly 100 (the 7th and 8th of September are re-allocated after a correction on 31 Aug) and weekly-cap-only (September days of the week) | Yes | Year boundary (Dec → Jan) not tested (the date helper handles it); monthly cap alone with no weekly cap is covered only by the first test's combined policy | None |
| **R-5** HR approve / reject did not re-allocate caps | `reallocate_caps_after_decision` runs in the reviewer's transaction after a final approval with fewer minutes than detected, and after a rejection, when the governing policy has a cap. A full approval triggers nothing. | Yes | Yes. 3 integration tests: partial approval (30 of 60 → the next day takes 60), rejection (→ 60 and 30), full approval (next days not recalculated: `calculated_at` unchanged) | Yes | Stage approval (`MANAGER_THEN_HR`), concurrent approval with a recalculation, and a locked later day after a decision (the locked-day rule is the shared pass and is tested for corrections) | None |
| **R-6** sibling pass ran with no cap | `_calculate` reads the day's cap contribution and runs the pass only if the overtime policy has a weekly or monthly cap; late/excess-break counter changes still trigger the month pass as before. | Yes | Yes. 2 integration tests: no cap → later days' `calculated_at` unchanged after a correction; weekly cap → they are recalculated (control) | Yes | A policy changed from capped to uncapped between two calculations (policy publish queues its own recalculation) | None |
| **R-7** `CAPPED` label for a policy version change | `outcome` is now `CAPPED` (approved minutes cut), `POLICY_VERSION_CHANGED` (version moved), or `DETECTION_UPDATED` (only the detected figure moved). | Yes | Yes. 2 integration tests: republish with identical minutes → `POLICY_VERSION_CHANGED`; correction cutting the approval → `CAPPED` | Yes | `DETECTION_UPDATED` has no dedicated test | Anything that filters audit rows on `outcome = 'CAPPED'` should be checked (none found in the code) |
| **R-8** contradictory text | `calendar_impact.py` warning split by change type: dated changes say leave is adjusted automatically (new code `LEAVE_ADJUSTED_AUTOMATICALLY`), others say it is not and name HR reconciliation (`LEAVE_NOT_RECALCULATED`); web and mobile work-calendar activation text corrected; reconciliation doc trigger section; trigger matrix (dated vs undated, sibling caps, AR-09 rows); overtime plan/results banners (engine 14 → 16, caps fixed, "not rerun" superseded); AR document header and registers; SQL comment path; `ENGINE_VERSION` comment. | Yes | Yes for the warning (2 tests: a holiday says "adjusted automatically", a pattern edit says "not changed automatically" + reconciliation; 25 calendar-impact tests pass). Documents are read, not tested | Yes | The web and mobile dialog wording is a string change only: web covered by typecheck and the full suite, **mobile not run** | A second reader should check the documents against the code; `LEAVE_NOT_RECALCULATED` code changed meaning for dated changes (an existing test was updated) |

Existing tests changed in this work: `test_calendar_impact.py::test_leave_impact_is_reported_and_leave_records_stay_untouched`
(now asserts the new code and wording, because it pinned the contradictory text) and
`test_grace_band_credit.py::test_a_missing_punch_day_gets_no_credit_and_stays_incomplete` (the
snapshot gained two keys). Nothing else was edited to make a test pass.

## 4. What the old implementation did against the new tests

Only these claims are made, and only because the tests were run before the fix **against the
unmodified working tree this review examined** (not against `dd71571`, which has none of the engine
16 work):

| Finding | Observed before the fix |
|---|---|
| R-1 | 4 of the 5 new tests failed, at the restoration step (e.g. total days 0.00 instead of 1.00; balance 20.00 instead of 19.00). The fifth (cancel after a full release) passed: that path was already correct. |
| R-2 | The review's reproduction returned `PRESENT` instead of `HALF_DAY`. Of the 180 tests, 4 failed on behaviour (the reproduction, 60 and 90 minutes late, the open-ended `NONE` band); the rest failed because the new constant or snapshot keys did not exist yet, which proves nothing about behaviour. The early-departure mirror test was found *not* to exercise the credit (its band stopped short of the miss); it was corrected afterwards and shown to fail with the ceiling raised to 10,000 (an emulation of the uncapped logic, not the old code). |
| R-4, R-5, R-6, R-7 | The five tests that assert the new behaviour failed (R-4 across the month, R-5 partial and rejection, R-6 no-cap recalculation, R-7 label); the control tests (weekly-cap-only R-4, full approval, capped R-6 control, real `CAPPED`) passed. |
| R-3 | Nothing to compare: the operation did not exist. |
| R-8 | Not applicable. |

## 5. Verification run

Every run below was on a database created for this work and migrated from scratch to head
`20261116110000` (`hrms_r_int`, `hrms_r_sec`; Redis indexes 6/7 and Celery 13/14), with the API
code unchanged from the moment the runs started (checked by file timestamps).
`FACE_PROVIDER_COMPARISON_ENABLED=false` was set in the process because the local `apps/api/.env`
enables it (as noted in the review).

| Check | Result |
|---|---|
| `pytest tests/integration` (clean DB) | **2,525 passed, 40 skipped, 1 expected failure, 0 failed**, 24 min 34 s. `test_punch_after_last_working_day` (time-of-day dependent) passed |
| `pytest tests/security` (clean DB) | **70 passed** |
| `pytest tests/unit` | **2,301 passed, 12 skipped, 1 failed**: `test_settings.py::test_development_has_no_explicit_origins_but_a_valid_fallback`, the known failure caused by `CORS_ALLOWED_ORIGINS` in the local `.env`. Re-run with that variable overridden to empty: all 28 settings tests pass. (After this run only one constant in the new unit test file was corrected; that file was re-run: 168 passed, 12 skipped.) |
| `ruff check .`, `ruff format --check .` | clean (891 files) |
| `mypy src/hrms` | no issues (287 files) |
| `lint-imports` | 1 contract kept, 0 broken |
| Mobile contract fixtures (CI step) | The new response schemas **changed the fixtures**: regenerated (10 new files + `_required.json`). They are inert for the Dart tests (explicit model map). They must be committed or CI's fixture check fails |
| Migrations | Fresh DBs reach head. A restore of the dev data (taken with a read-only dump; the dev database was not written) upgraded 14 Nov → head; `downgrade -3` and re-upgrade round-trip; the backfill copied the one existing half-day marker |
| Web `tsc --noEmit` | clean |
| Web `vitest run` (whole suite) | **151 files, 1,045 tests passed** |
| ESLint on the four changed web files | 1 error in `work-calendars/setup/page.tsx` (`react-hooks/set-state-in-effect`, line 97). **Pre-existing:** the same error is in the file at `HEAD`; this change edited only a dialog string |
| Concurrency | Two simultaneous reconciliation applies (R-3) and the existing concurrent-calculation test passed |
| Roster / shift / weekly-off / locked period | R-3 tests: weekly-off pattern change, published roster week-off, shift operating on the weekly off, closed attendance period (protected). `LOCKED` attendance *days* inside an open period are covered by the existing locked-day test for cap cascades |

**Not run**

* **Flutter** (`flutter analyze`, `flutter test`): no Flutter on this machine. CI runs it with Flutter
  3.29.2 (`.github/workflows/ci.yml`). Mobile files changed in the tree: `attendance_setup_configs.dart`,
  `day_timeline.dart`, `day_timeline_test.dart`, `work_calendar_setup_screen.dart` (a string), and the
  contract fixtures. **Mobile is unverified until CI runs.**
* Web `next build` and repository-wide ESLint.
* Any run against a production-like data set, and any load or timing test.
* `alembic check` (large drift that predates this change; CI does not run it).

## 6. Impact report evidence (R-2), development database only (test data)

`scripts/sql/late_mark_band_impact_report.sql` (read-only) on `hrms_dev`:

* 20 broad-band rows across 10 policy versions in 2 companies (`LATE`/`EARLY_DEPARTURE` 11-120,
  31-240, 6-60), 8 of them published and 2 drafts. Company `b84168b0` has 280 unlocked and 3,923
  locked days on them; company `16723927` has none unlocked.
* One unlocked day the uncapped credit would have paid in full that the ceiling keeps at half a day
  (late 85 minutes, `LATE` 11-120).
* Six unlocked half-days whose mark is inside the ceiling: these are the days expected to move to
  present (D-01) when recalculated.
* No published policy version lacks late and early bands.

The leave drift (`LeaveCalendarReconciliationService.preview`, run through a script against the
restored copy, rolled back): company `b84168b0` has the **5** differences the review counted, and
all 5 are `PROTECTED` (inside closed attendance periods), so they do not block anything and the
operation would not change them. Company `16723927` has none.

Production data does not exist yet (`project-test-data-only`): these figures say nothing about real pay.

## 7. What remains

1. **Owner decisions:** R-2 (59 minutes, none, or per policy); policy A vs `LEAVE_CALENDAR_MISMATCH`
   (R-3); the earlier unconfirmed defaults listed in `ATTENDANCE_RULES_REMEDIATION_2026-11-16.md`.
2. **Flutter in CI** — the only unverified layer.
3. **Independent re-read** of R-1 to R-8 by someone other than the author.
4. **Before any historical recalculation:** run `attendance_integrity_report.sql` (now with the R-1
   check), `late_mark_band_impact_report.sql`, and take `attendance_pre_recalc_snapshot.sql` per
   company and period before and after; hold companies with broad bands until R-2 is decided.
5. **No UI for the reconciliation operation** (API only).
6. Applications fully released before the R-1 fix (none in dev) lost their half-day marker.
7. Carried over, not touched here: P-01, P-04, P-05, P-10, P-11, P-12, P-14, P-D, D-07, LV-01 to
   LV-13 except LV-04; AR-03's text-matched lock withdrawal; AR-01 `SHIFT_FLAG` with no shift
   (no snapshot note); AR-06 SPLIT edge case.

## 8. Commit guidance (nothing was staged)

* Stage **by file name**. Exclude `MOBILE_UX_NEXT_STEPS.md`.
* Include the three migrations: `20261116090000`, `20261116100000`, `20261116110000`. Apply them
  **before** the code is deployed (new code on the old schema fails at the first supersede and at
  period validation). A downgrade after the engine 16 recalculation deletes supersede history and
  open shortfalls.
* Include the regenerated contract fixtures under `apps/mobile/test/fixtures/contract/`.
* The pull request touches `apps/api/alembic/`, so it will **not** auto-merge: merge it manually
  (`gh pr merge --merge`).

## 9. Files changed by this remediation

New: `alembic/versions/20261116110000_leave_application_half_day.py`;
`tests/integration/modules/leave/test_leave_full_release_restoration.py`,
`.../test_leave_reconciliation_operation.py`; `tests/integration/modules/attendance/test_overtime_cap_reallocation.py`;
`tests/unit/modules/attendance/test_late_mark_credit_ceiling.py`;
`scripts/sql/late_mark_band_impact_report.sql`, `scripts/sql/attendance_pre_recalc_snapshot.sql`;
10 mobile contract fixtures; this document.
Modified: `leave/models.py`, `leave/service.py` (one line: store `half_day` at submit),
`leave/reconciliation.py`, `leave/exceptions.py`, `leave/schemas.py`, `leave/router.py`,
`leave/dependencies.py`, `attendance/calculation.py`, `attendance/service.py`,
`organisation/calendar_impact.py`; tests `test_calendar_impact.py`, `test_grace_band_credit.py`;
web `work-calendars/setup/page.tsx`; mobile `work_calendar_setup_screen.dart`,
`fixtures/contract/_required.json`; `attendance_integrity_report.sql` (path fix, R-1 query);
documents: the reconciliation, trigger-matrix, overtime plan/results, policy-decisions and AR
documents.
