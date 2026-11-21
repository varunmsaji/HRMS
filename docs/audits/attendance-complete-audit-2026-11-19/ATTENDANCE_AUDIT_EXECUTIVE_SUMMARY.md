# Attendance audit: executive summary

19 November 2026. Read-only audit; nothing in the code, configuration, database or data was changed.

## Overall assessment

The calculation engine is careful and well documented, but it still has about ten reproduced rule defects that
affect pay, each waiting on an owner decision (16 Nov reports). The HR screens improved a lot this week. The
weakest part is **how a result is presented**:

- The same day is counted four different ways on different screens.
- An employee who is at work can be shown as "Incomplete" or "Absent".
- No screen explains why a day came out as half day or absent.
- An unfixed day quietly becomes unpaid at month close, and nobody is told.

**Not ready to show employees payroll-relevant figures yet. Fixable in about four weeks of focused work once
the decisions are made.**

## Most important findings

| # | Finding | Severity |
|---|---|---|
| 1 | The home dashboard and the Attendance page use two different backend calculations and disagree on Present, Incomplete and exceptions for the same morning (AUD-01) | High |
| 2 | A half day counts as 0 in the attendance rate, 0.5 in the HR calendar, 1 on the home dashboard (AUD-02) | High |
| 3 | A person who is working shows "Incomplete" (or "Absent") on the web, because the engine has no clock and the web does not correct for it. Mobile already does (AUD-03) | High |
| 4 | No "why" for any result: thresholds, grace and the deciding rule are recorded in the snapshot but shown only as raw JSON, and employees see policy version ids (AUD-06) | High |
| 5 | "Incomplete" days become absent and unpaid at lock by default, with no warning or deadline shown (AUD-07) | High |
| 6 | Month totals on the employee card and the HR calendar differ from what payroll uses (AUD-09) | Medium |
| 7 | A holiday is described as "Weekly off" on the web day page (AUD-04) | Medium (bug) |
| 8 | Past dates silently drop employees whose day was never calculated (AUD-08) | Medium |
| 9 | Overtime shown is what was found, overtime paid is what was approved; screens don't say so (AUD-14) | Medium |
| 10 | Tests never check that two screens agree; no HALF_DAY case in either dashboard test; no web e2e for attendance (AUD-17) | Medium |

Plus the carried engine defects: band gaps pay a full day (MA-01), part-time shifts get half days (MA-05),
late punches after close are lost (MA-06), schedule changes do not recalculate the neighbouring day (MA-07),
and others.

## Biggest UX weaknesses

1. Status is a bare word with no reason.
2. The live day is judged before it ends.
3. The calendar can show only one thing per day (late, missing punch and overtime are invisible on it).
4. Similar labels hide different arithmetic.

## Recommended priorities

1. **Decide:** half-day weight in rates (D-AUD-1/2), WFH (D-AUD-3), and Group A session 1 (H-01, H-02, H-03, H-04).
2. **Quick wins, no decision needed:** fix the holiday headline; stop showing a verdict while someone is working
   (web); show "calculated up to"; count missing rows on past dates; hide technical ids from employees; write
   the failing cross-screen consistency test.
3. **One source of truth:** one backend classifier for buckets, exceptions and "in progress", used by both
   dashboards and both apps; one month-summary function shared with payroll.
4. **Explain every result:** a backend `explanation` for each day (reason line, facts, pay effect, action and
   deadline), rendered the same on web and mobile.
5. **Then the calendar and HR close view,** built on 3 and 4.

## Proposed sequence

| Week | Work |
|---|---|
| 1 | Decisions; quick wins (R-D01, R-D02, R-B04, R-B06, R-C04); failing consistency test (R-G01) |
| 2 | One classifier (R-B01, R-B02); engine fixes R-A01..A04 |
| 3 | Explanation contract (R-C01..C03); shared month summary (R-B03); remaining engine fixes as decided |
| 4 | Web and mobile day "why" panels, calendar redesign, HR close view, reports basis, e2e and Flutter CI |

Details: `ATTENDANCE_COMPLETE_AUDIT_REPORT.md`, `ATTENDANCE_UI_UX_IMPROVEMENT_PLAN.md`,
`ATTENDANCE_IMPLEMENTATION_ROADMAP.md`, `ATTENDANCE_TEST_SCENARIO_MATRIX.md` (same folder).

## Limits of this audit

Everything was read, not run: no app, test or database query was executed, and Flutter is not available on this
machine. Two items need a runtime check before any fix: what an approved WFH request writes (S-27), and
duplicate punch submission (S-13). Engine rule findings are carried from the 16 Nov reports. The engine has not
changed since then.
