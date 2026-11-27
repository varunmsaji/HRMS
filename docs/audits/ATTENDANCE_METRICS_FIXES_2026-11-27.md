# Attendance metrics: fixes for the web vs mobile audit (2026-11-27)

Follows [ATTENDANCE_METRICS_WEB_MOBILE_AUDIT_2026-11-26.md](ATTENDANCE_METRICS_WEB_MOBILE_AUDIT_2026-11-26.md).
Branch `test`, on top of `de31129`.

## Status by finding

| Finding | Status | What changed |
|---|---|---|
| F1. Mobile loads fewer days, no warning (high) | **Fixed** | Mobile reads 500 rows a page, up to 20 pages (10,000 days), the same as web. When it stops at the ceiling, Insights shows web's note on all three tabs. |
| F2. No "last calculated" line (medium) | **Fixed** | Mobile reads `calculated_at` from the summary. The Today card shows "Last calculated at HH:MM" for today, and the date and time for a past day. |
| F3. No dashboard filters on mobile (medium) | Not done, on purpose | `/attendance/summary` accepts department and branch, but `/attendance/days` does not. Mobile could filter the tiles but not the lists, which would recreate the kind of mismatch this audit found. It needs a days filter on the API first, or a directory lookup like web's. |
| F4. On-screen reports vs exports (medium) | **Fixed (round 2)** | On both apps, Present / absent on screen now has the server's Weekly off, Holiday and Incomplete columns. A note by the export button explains that the table covers the loaded days and the file covers every record. On web, the screen headers no longer say "(min)" next to "8h 30m", while CSV headers still do, because the file holds raw minutes. |
| F5. Two "late %" figures; "Present %" vs rate (medium) | **Fixed (wording)** | On both apps, the punctuality figures now read "of completed days" and a line explains how they differ from the Late tile. The trend metric is now "Present % (full days)". |
| F6. Mobile's two "late" definitions (low) | **Traced and aligned** | The engine sets `is_late = late_minutes > 0` (`calculation.py:3366`), and every other code path sets both to zero/false, so the two rules give the same answer on real rows. Team attendance (`isLateDay`) now uses the same rule as the reports: the flag, with late minutes only when the flag is missing. |
| F7. Payroll tab shown to everyone on mobile (low) | **Fixed** | The payroll attendance report is offered only with `ATTENDANCE.VIEW_ALL`, which matches web's `showPayroll={mode === "org"}`. |
| F8. Overtime totals line missing (low) | **Fixed** | The overtime report on mobile has the "Found · Approved · Pending" line above it, using the same sums as web's `overtimeTotals`. |
| F8. Unparsed summary fields (low) | Not done | Nothing on either app uses them yet. |

## Round 2 (same day): F4 and the shared fixture

- **Shared parity fixture** (audit section 5, item 7): `apps/api/tests/fixtures/attendance_metrics_parity.json` holds 14 day rows and 3 overtime records, with the buckets, per-employee tallies, late/early days and overtime totals they must produce. It follows the pattern of `day_display_table.json`. Three tests load it:
  - web: `src/lib/attendance/metrics-parity.test.ts`
  - mobile: `test/metrics_parity_test.dart`, which also checks that the reports' `isLate` and Team attendance's `isLateDay` agree
  - API: `tests/unit/modules/attendance/test_report_parity.py`, which runs the export's own `_tallies` and `_late_early`. Each API row is given the bucket the fixture expects, because the API decides buckets in SQL and that part is not tested here.
- Web's per-employee tally moved from inside `reports-panel.tsx` to `tallyByEmployee` in `src/lib/attendance/report-basis.ts`, so the parity test can call it.
- The report note has the same wording on both apps: web's `REPORT_SOURCE_NOTE` and mobile's `reportSourceNote`.

Round 2 results:
- Web: `tsc` was clean, and all 1,284 vitest tests passed.
- Mobile: `flutter analyze` was clean, and all 1,597 tests passed.
- API: all 1,793 attendance unit tests passed (18 skipped), and ruff was clean.
- The API tests ran with a throwaway Redis on port 6399 and a database URL that points nowhere. The suite refuses the shared dev stack, and that guard was not overridden. The local `.env` also needed `FACE_PROVIDER_COMPARISON_ENABLED=false`, for this run only.

## Files

Mobile:
- `lib/features/attendance/data/attendance_repository.dart`: adds `DaysCoverage` and `listAttendanceDaysCovered` (500 a page, 20 pages, plus a truncated flag). `listAttendanceDays` now delegates to it, so the per-employee screens also use 500-row pages.
- `lib/features/attendance/presentation/attendance_insights_screen.dart`: adds the partial-data note, the freshness line, the payroll gate and the punctuality wording.
- `lib/features/attendance/presentation/attendance_reports_screen.dart`: adds the `partialNote` and `showPayroll` parameters and the overtime totals line.
- `lib/features/attendance/domain/attendance_totals.dart`: adds `calculatedAt`.
- `lib/features/attendance/domain/attendance_reports.dart`: adds `overtimeTotals`.
- `lib/features/attendance/domain/attendance_insights.dart`: renames the trend metric label.
- `lib/features/attendance/presentation/attendance_summary.dart`: changes `isLateDay` to the reports' rule.

Web:
- `src/components/attendance/dashboard/insight-panels.tsx`: changes the punctuality wording and adds the explanatory line.
- `src/lib/attendance/dashboard.ts`: renames the trend metric label.

The comment in `use-dashboard-data.ts`, "the same ceiling the mobile app uses", is now true.

## Tests

- New mobile tests in `test/attendance_history_test.dart` cover the page size (500), stopping at 10,000 with `truncated` set, and exactly 10,000 not counting as truncated.
- New mobile tests in `test/attendance_insights_test.dart` cover the partial note shown and not shown, the freshness line shown and not shown, the payroll tab hidden and shown, and the overtime totals sums.
- Updated tests: the old "100 per page" test, the three test fakes (which now implement `listAttendanceDaysCovered`), and two web chart tests that look the chart up by its label.

Results on this machine:
- Mobile: `flutter analyze` found no issues, and `flutter test` passed all 1,593 tests. One earlier run had 8 other failures that did not recur. They look flaky rather than caused by these changes, but the cause was not traced.
- Web: `npx tsc --noEmit` was clean, and `npx vitest run` passed all 1,280 tests in 175 files.

## Not verified

- Neither app was run on a device or in a browser, so the new note, freshness line and overtime line have not been seen on screen.
- No figure was compared on a real company's data.
- Loading 500 rows a page has not been timed on a slow mobile connection.
- ESLint was not run (it does not block CI).

## Still open

1. F3: mobile filters. This needs a department/branch filter on `/attendance/days`, which is an API change, before mobile can filter the lists and the tiles together.
2. Extend the parity fixture to the summary (tiles, trend, rate) and to the API's SQL bucket rule.
3. The unused summary fields listed in F8.
