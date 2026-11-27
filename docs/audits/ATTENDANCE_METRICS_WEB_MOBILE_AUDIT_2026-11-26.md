# Attendance reports and metrics: web vs mobile audit (2026-11-26)

Question: the attendance reports and other metrics now show on both the web app and the mobile app. Do
they agree, and where can they differ?

Short answer: **the headline figures agree, because both apps read them from the same API endpoint. The
differences are in what each app computes itself, how much data it loads, and what it tells the user when
the data is partial.** Nothing in the code was changed. This file is the only thing written.

Scope: `apps/web`, `apps/mobile` and `apps/api` on `test` at `c4044b6`. Static reading only: neither app
was run, no figure was compared on a real company's data, and the API was not called. "Same" below means
the code reads the same and gives the same result for the same input, not that it was observed.

## 1. How the numbers are produced

| Layer | What it does | Where |
|---|---|---|
| API, summary | Counts stored `attendance_day` rows into buckets, KPIs, rate, daily trend, punctuality, weekday absence, department and branch breakdown | `attendance/summary.py`, `day_classification.py` |
| API, exports | Builds the muster register and five reports as CSV, Excel or PDF from the same population and bucket rules | `muster_export.py`, `report_export.py` |
| Web | Reads `/attendance/summary` for totals; reads `/attendance/days` itself for lists, heatmap and the on-screen reports | `lib/attendance/summary.ts`, `dashboard.ts` |
| Mobile | Same split: totals from `/attendance/summary`, lists and reports from `/attendance/days` | `domain/attendance_totals.dart`, `attendance_reports.dart` |

So there are **three places that classify a day**: the API (for totals and exports), and each app (for lists
and on-screen reports). The API's rule is the reference: one bucket per day, "expected" is every bucket except
not employed, holiday, weekly off and non-working; rate is weighted present over expected, with present,
remote and on duty at 1, half day at 0.5 and everything else at 0.

## 2. What matches (checked line by line)

- **Day to bucket mapping.** `attendanceBucketOf` (mobile) and `bucketOf` (web) are the same function: use the
  API's `display.code` when present, else map the status the same way (`NOT_EXPECTED` split by calendar day
  type, unknown to non-working).
- **Dashboard totals.** Both apps show the API's focus-day KPIs, compare day, rate, daily series,
  punctuality, weekday absence and department/branch groups without re-adding rows. Mobile's model parses the
  same fields web does that the screens use.
- **KPI tiles.** Same tiles, same wording and the same denominators: "% of workforce" over total employees,
  Late over checked-in, Remote over present, Remote hidden until the engine produces remote days.
- **Trend.** Present, absent, leave, late and remote percent and average hours use the same numerators and
  denominators. A weekly point adds its days' counts and does not average daily rates, on both.
- **Per-employee month figures.** `monthStats` (mobile) and `monthStats` (web `employee-analytics.ts`) have
  the same steps: half day counts 0.5 worked day, punctuality is on-time over worked days rounded to a whole
  number, average hours is over days with a first punch.
- **Report definitions and wording.** The five on-screen reports plus payroll attendance have the same rows,
  columns (labels differ slightly), filters and the same one-sentence basis text.
- **Punctuality on mobile** is recomputed from the API's `checked_in` and `late` with plain division. The API
  does not round, so it matches the API's own `late_rate` and `on_time_rate`.
- **Period summary totals** (`sumPeriodSummary` mobile, the same on web) sum the same fields and keep "unknown"
  distinct from zero.

## 3. Findings

Severity is about the risk of a user reading a wrong or contradictory number, not about how hard the fix is.

### F1. Mobile loads fewer days than web and does not say when it is partial. High

- Mobile: 100 rows a page, at most 50 pages, **5,000 days** (`attendance_repository.dart`, `listAttendanceDays`).
  Its comment says the cap is "so day-level summaries are not truncated", but nothing tells the user when it
  is hit.
- Web: 500 rows a page, at most 20 pages, **10,000 days**, and when it truncates it shows a note: "Totals and
  charts count every attendance record, but the employee lists and heatmap show the most recent N of M"
  (`use-dashboard-data.ts`, `attendance/page.tsx`). The web comment says 10,000 is "the same ceiling the
  mobile app uses"; it is not, mobile's is half that.
- Effect: totals come from the server and are complete; lists, the heatmap, Needs attention, Absence and
  leave, Work hours and the on-screen reports come from the loaded days. A company with about 170 or more
  employees and a 30-day range passes 5,000 rows. On mobile those panels then understate, with no warning,
  while the tiles above them are right. The list is newest first, so the oldest days are the ones dropped.
- Same for names: mobile loads employee names through the choices loader and falls back to `Employee abc123`;
  web warns when it loaded only part of the directory. Mobile's cap for that was not checked.

### F2. Mobile has no "last calculated" freshness line. Medium

Web reads `calculated_at` from the summary and shows "Last calculated at HH:MM". Mobile's model does not
parse it. A user cannot tell whether today's figures are fresh. This matters most on the day itself, when the
rate is moving.

### F3. Mobile has no dashboard filters; web has five. Medium

Web filters the summary, the lists, patterns and exports by employee, shift, status, department and branch.
Mobile Insights has only a date range. Totals on a phone are always for everyone the caller may see, and so
are the new exports. Not a wrong number, but the same question gives different answers on the two apps unless
web is left unfiltered. Mobile does have a department and branch comparison card, which covers part of it.

### F4. On-screen reports and exports are different calculations in the same app. Medium

On both apps the five reports shown on screen are built in the client from the loaded days, while the new
export button asks the server to build the file. They can disagree:

- Present and absent: on screen shows present, half day, absent, leave. The server's tally also holds off,
  holiday and incomplete (`report_export.py`, `_Tally`), so the file can carry columns the screen does not.
- The on-screen version is capped by F1 (5,000 rows on mobile, 10,000 on web); the file has no such cap (up
  to 200,000 rows).
- Web's report headers say "(min)" while the values are shown as hours and minutes ("Worked (min)" next to
  "8h 30m"). Mobile's headers have no unit. Labels only.

Not verified: whether each of the five server reports has exactly the same columns and order as the screen.

### F5. Two different "late %" figures, and a "Present %" that is not the "Attendance rate". Medium (wording)

Same on both apps, so not a parity gap, but it will draw questions:

- Late tile: late over `checked_in` on the focus day, where checked in means any first punch, including a day
  still open. Punctuality card: late over days with both an in and an out punch. Same day, two percentages.
- Trend "Present %" counts full days only (present, remote, on duty) over expected. The headline "Attendance
  rate" weights a half day at 0.5. With half days in the window the two disagree for the same day.

### F6. Mobile is inconsistent about what "late" means. Low, needs one check

Mobile reports use `isLate`: the `is_late` flag, else late minutes above zero. The Team attendance list that a
Late tile opens uses `isLateDay`: late minutes above zero **or** the flag. Web uses the flag only. If a day can
have late minutes above zero with the flag false, the tile count (server) and the list (mobile) can differ.
Whether that case occurs depends on the calculation engine's grace handling (`calculation.py`), which was not
traced.

### F7. Payroll attendance report is offered to everyone on mobile. Low

Web hides that report unless the user is in the organisation view (`showPayroll`). Mobile shows the tab to
anyone who can open Reports and relies on the API's 403, which it words as "You do not have permission to view
the period summary." No data leaks, but a manager sees a tab that cannot work.

### F8. Smaller differences. Low

- The Reports tab on mobile has no Found / Approved / Pending overtime totals line; web has it above the
  overtime report. Mobile has those figures on the Trends tab.
- Mobile's summary model drops fields the API sends and web parses: `half_day` on each day and on each group,
  `not_in_yet`, `expected` and `rate` on the KPIs, `is_today`, `row_count`, the weekday `index`, and the
  `NOT_CHECKED_IN` distribution bucket. None of them is used on the screens today on either app, so no
  visible gap yet; they would be needed for a half-day trend or a "not yet due" count.
- Web folds the API's `NOT_CHECKED_IN` bucket into Absent in its distribution chart. Mobile does not draw the
  server's distribution.

## 4. Tests

- Both apps test their own maths with hand-written fixtures (`totals_fixture.dart`, `__fixtures__/summary.ts`).
  Mobile also has contract fixtures that check API response shapes.
- **No test feeds the same input to both apps and expects the same figure**, and none compares either app's
  on-screen report with the API's export of the same period. That is why F4, F5 and F6 can exist unnoticed.
- No test covers the 5,000-row cap on mobile (F1).

## 5. Recommended order

1. **F1:** raise mobile's page size to 500 (the API allows it; web does it), match web's 10,000 ceiling, and
   show the same "showing the most recent N of M" note. This is the one that can put a wrong number on a
   screen.
2. **F4:** decide what on-screen reports are for. Either label them as the loaded range and keep them, or
   make them read the server's report so screen and file always agree.
3. **F2:** read `calculated_at` and show the freshness line.
4. **F6:** trace `is_late` against `late_minutes` in the engine; then make mobile use one definition, the
   flag, as web does.
5. **F5:** reword the Late tile or the punctuality card so the two percentages say what they divide by.
6. **F7, F8, F3:** gate the payroll tab, add the overtime totals line, decide whether mobile needs filters.
7. Add one shared fixture: a JSON summary and day list that both apps' tests load and must give the same
   tiles, trend and report rows from.

## 6. Not verified

Run on a device or in a browser; compared real figures for one company; the trend chart rendering, the heatmap,
Needs attention counts and payroll readiness beyond the points above; the team-view (manager) mode on web
against mobile; digest emails; how the API's `is_late` is set (F6); the five server reports' exact columns
against the screen (F4).

## Confidence

High: section 2 matches, F1 (both caps read from code), F2, F7, F8. Medium: F4 and F5 (read from code, not
run). Low until traced: F6.
