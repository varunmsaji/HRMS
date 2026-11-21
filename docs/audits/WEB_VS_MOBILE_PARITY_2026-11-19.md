# Web vs mobile parity report (2026-11-19)

Question asked: is the web app up to date with the mobile app?
Short answer: **mostly yes, with three real gaps and a handful of things I could not confirm by reading code.**
Web is the leader. Mobile has followed it closely. The few places where mobile is ahead are about the
phone's hardware (camera, GPS), and the web does not handle those users well.

Scope: `apps/web` (Next.js) and `apps/mobile` (Flutter) on branch `test`, commit `d58ae7f`.
No code was changed. This is the only file written.

## How this was done, and what it can't tell you

- Read the route tables, nav menus, screen lists and API calls on both sides, and read the code of the
  specific features below.
- Compared git history for 2026-11-01 to 2026-11-18 (web: 109 commits touching `apps/web` since
  2026-10-29; mobile: 84).
- **Neither app was run.** Everything here is static reading. Where a statement is a guess it says so.
- Endpoint-by-endpoint diffing by string search was too noisy to trust (test fixtures, path building).
  I used it only as a lead and confirmed each claim by reading the file.
- The older `MOBILE_FEATURE_PARITY_AUDIT.md` (2026-10-03) is out of date; this report replaces it for
  the web-vs-mobile question.

## Size

| | Web | Mobile |
|---|---|---|
| Pages / screens | 102 `page.tsx` routes | 228 Dart files, 64 screen files, about 75 routes |
| Tests | 161 test files | 111 test files |

## 1. Where the two apps match

Both sides cover these, checked against route lists or code:

- **Auth:** login (including company code and employee ID), register, forgot and reset password, verify email,
  accept invite, public onboarding link.
- **People:** employee directory (summary, filters, CSV export on both), employee record with employments,
  assignments, bank, compensation, statutory IDs, identity, education, experience, dependents, documents
  (upload, verify, reject), manager-change impact, invite, deactivate and reactivate.
- **Onboarding:** cases, case detail, invitation composer, verify all, public candidate wizard.
- **Org setup:** company profile, legal entities, branches, departments, designations, grades, holiday
  calendars, weekly-off patterns, work calendars (including exceptions), setup progress, users and roles.
- **Attendance:** self attendance, day detail with timeline, mismatch fixes, mark-day bulk entry for HR,
  regularizations, overtime, rosters (board, grid, calendar), shift swaps, shifts with versions and guarded
  delete, attendance and overtime and correction policies (one-step `/setup` create on both), policy
  assignments and resolution, geofences, attendance periods with monthly summary, employee attendance
  analytics, HR face-enrollment review (all five photos).
- **Leave:** applications, decision center, balances, ledger, encashment, adjustments, types, policies,
  combination rules, statutory minimums, leave year.
- **Payroll:** pay runs (full lifecycle), per-employee detail, variance acknowledge, salary components,
  structures with versions, bulk assign, statutory rates, my payslips, bank advice CSV.
- **Notifications:** bell, list, and an in-app message when a new one arrives. Web shows a toast, mobile a banner.

Recent commits show mobile deliberately catching up to web every few days ("matching the web",
"follows the web redesign", "close the 12 Nov parity gaps"). Nothing I found suggests drift is being ignored.

## 2. Gaps where mobile can do something the web cannot

### G1. Face punch and GPS punch exist only on mobile, and the web's own punch path fails for those users (highest priority)

What I verified:
- The web has no camera code and no geolocation code anywhere under `apps/web/src`.
- The web's "Record punch" dialog (`components/attendance/punch-entry-dialog.tsx`) posts only
  `{direction, reference}` to `POST /attendance/punches/me`. It never sends a location.
- The API treats the web source (`WEB`) as geofenced: `GEOFENCED_SOURCES = {"WEB", "FACE"}` in
  `geofence_service.py:46`. When a policy's geofence mode is `REQUIRED`, a punch with no location is refused
  (`LOCATION_REQUIRED`).
- Separately, `service.py` (around line 3470) refuses a plain `WEB` punch for any employee whose face profile
  is `ENROLLED`, with `FACE_VERIFICATION_REQUIRED`.
- The web dialog has no special handling for either refusal. It shows the generic API error text
  (`describeApiError`).

What I did not verify: the exact wording the employee sees, and whether the web hides the self-punch button
for these employees elsewhere. Worth a quick manual try with a face-enrolled test user.

Why it matters: in a company that turns on geofencing or face attendance, an employee who opens the web app
gets a punch button that cannot work and an error that does not tell them to use the mobile app. This is a
design choice (capture needs a phone), but the web should say so.

Note the web already does this right for enrollment: `app/app/attendance/face-setup/page.tsx` tells the user to
open the mobile app.

### G2. Dedicated approvals inbox is mobile-only

Mobile has `/app/approvals` (`ApprovalsScreen`): every request the user may decide (leave, corrections,
overtime, onboarding review) in one list, with a count on Home and Dashboard. The web has a
`pending-approvals` card on the dashboard and separate decision centers for leave and regularizations, but no
single approvals page. Low risk: the web has the data, it is a convenience gap.

### G3. Native-only features, not expected on web

Camera face enrollment and active liveness checks, GPS capture with an accuracy check, sharing a payslip PDF
through the phone's share sheet. Web has a print dialog for the payslip (`window.print()`). These are correct
to leave off the web.

## 3. Gaps where the web can do something mobile cannot

| Area | Detail | Severity |
|---|---|---|
| Platform admin console | `/platform/*`: companies, admins, audit, emails, logs, login. Web only. | Expected; staff tool, not for phones |
| Settings guide | `/app/settings/guide` help content and a per-area Settings layout (`/app/settings/[module]`). Mobile has a flat "More" hub with a search box. | Low |
| Roster Schedule views | **Checked 2026-11-19: every view exists on mobile; only the navigation differs.** Web (2026-11-18) has one Shift Rosters nav: Coverage, plus Schedule with Week, Month, Day and List. Mobile has all of them as separate screens: Week = Workforce roster, Month = Roster calendar, Day = Shift board, List = Shift Rosters, Coverage = Schedule coverage, plus Shift swaps. Filters match (7/14/31 days, search, date, status), as do copy-to-next-day and publish. Mobile reaches them through three app-bar icons on the Shift Rosters list and separate menu entries, not one switcher. | Low, navigation only |
| HR attendance page rework | **Checked 2026-11-19: mobile has the same data and fixes but not the 18 Nov layout.** Web `e632fcb` split the page into Today, Trends and Reports tabs, put the rate beside five clickable tiles, cut Trends from 9 cards to 6, replaced the employee dropdown with a type-to-find box, made Muster a List/Grid switch, and (with `8b6999c`) moved the period panels under Payroll. Mobile's Insights screen still follows the earlier single long page and still shows Period status and Monthly summary on it. Mobile already has the mismatch banner with "Show only these" and the on-row fixes (`f3fe353`), bulk Mark attendance, and a separate Reports screen. | Low to medium, layout only |
| Attendance periods placement | Web `8b6999c` moved Attendance Periods under Payroll and added a monthly summary. Mobile still lists it as its own route (`/app/attendance-periods`); it does call the `/summary` endpoint. Menu placement differs. | Low |
| Shift version resolve | Web calls `/shifts/{id}/versions/resolve`. I found no mobile call. | Low, **unverified** |
| Salary setup preview | Web calls `/employees/{id}/salary/setup/preview`. Mobile has a structure-version preview but I found no call to this endpoint. | Low, **unverified** |
| Employee bulk import | API has `/employee-imports` (upload, template, reference data, status). **Neither web nor mobile has a screen for it.** | Not a web-vs-mobile gap, but a feature the backend offers that nobody can use |

## 4. Things that look like gaps but are not

- Policy creation: mobile has no `form-context` call, but it uses the same `/setup` endpoint through
  `PolicySetupScreen`. Parity.
- Bank advice CSV: both sides have it (mobile `pay_run_detail_screen.dart`).
- Shift swaps: the web puts them under Shift Rosters > Coverage (`/app/rosters/coverage`), employees' menu says
  "Shift Swaps". Mobile has `/app/shift-swaps`. Parity.
- Breaks on shifts: web has a shift breaks editor; mobile's shift form includes `breaks` as a field. Probably
  parity, but I did not open the mobile editor.

## 5. Known work already queued on mobile

From `MOBILE_UX_NEXT_STEPS.md` (not committed, local notes): none of UX phases 1 to 4 has been tried on a real
phone; split the 28-field new-employee form; per-day lists instead of grids on phones; quick chips on Team
attendance; push notifications (needs Firebase), offline banner (needs a new package) and biometric unlock are
all not built. These are mobile improvements, not web parity gaps.

## 6. Recommendations, in order

1. **Web: handle the geofence and face refusals** (G1). When the server returns `LOCATION_REQUIRED` or
   `FACE_VERIFICATION_REQUIRED`, show "Use the Krewoxa mobile app to punch." Better still, hide the self-punch
   button when the employee's policy needs location or face. Small change, avoids a confusing dead end.
2. **Manually check the two Medium rows** in section 3: Roster Schedule views and the HR attendance rework.
   They are the only recent web-first features I could not confirm mobile has.
3. Decide whether a web approvals page (G2) is worth it. Probably only if HR asks.
4. Decide what to do with employee import. The API is built and tested but has no screen.
5. Fix the tracking gap: add the check proposed in the October audit (a script that diffs the backend route list
   against what each client calls), so this report does not need to be done by hand again.

## 7. Confidence

- High: sections 1, G1, G3, and the web-only platform console. Each was confirmed by reading the code.
- Medium: G2 and the roster and attendance-page rows. Confirmed one side, inferred the other.
- Low: the two "unverified" rows. Based on a missing string, not on reading the whole feature.
