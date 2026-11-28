# Web vs mobile parity review (2026-11-22)

Question: is the mobile app up to date with the web app?
Short answer: **yes for everything shipped up to 2026-11-20. Two small web features from 2026-11-21 are not
on mobile yet, and one backend change in progress (assigned branches) will need both clients.**

Scope: `apps/web` and `apps/mobile` on `test` at `30a9649`. Static reading only: neither app was run, and
nothing was tried on a phone or in a browser. This file is the only thing written; no code was changed.
It updates `WEB_VS_MOBILE_PARITY_2026-11-19.md` and the handoff `MOBILE_HANDOFF_2026-11-20.md`.

## 1. Gaps that exist now

| # | What web has | Mobile today | Evidence | Severity |
|---|---|---|---|---|
| 1 | **R-D06** "N employed people have no calculated day on this past date" notice on the HR Attendance page, with a button to queue the calculation (`not-calculated-notice.tsx`, commit `dee9943`) | Nothing. Mobile only calls `/attendance/days/calculate-range` from the period detail screen, and the insights screen has no such notice | `dee9943` touches no mobile file; no match for the notice text or call in `features/attendance/presentation/attendance_insights_screen.dart` | Medium. Missing people drop out of every figure, and at close an unresolved day becomes absent |
| 2 | **R-F02** Closing a period lists the incomplete days that will be counted absent or present (`ABSENT_AT_LOCK`, `PRESENT_AT_LOCK`, the `notices` array, commit `4164bc1`) | Does not read `notices`. Mobile's period detail shows only blocking reasons | `grep ABSENT_AT_LOCK\|PRESENT_AT_LOCK\|notices` in `apps/mobile/lib` finds nothing; the commit touched no mobile file | Medium. HR closing a period on a phone gets no warning the web gives |
| 3 | **Assigned branches** (uncommitted API work on `test`): `ASSIGNED_BRANCHES` data scope, `user_branch_access`, `PUT /users/{id}/branches`, `branch_ids` on invite create, user read and role update | Neither client mentions it (`branch_ids` / `branch_access` search over web and mobile finds nothing) | `git diff` of `core/rbac/types.py`, `account_invite/schemas.py` and `router.py` | High once released. Inviting or editing an HR admin or branch manager will fail validation (at least one branch is required), on web and mobile alike |
| 4 | Web: "Use the mobile app" message when a punch is refused for face or location (PR #64) | n/a, correct | Handoff and `punch-errors.ts` | Done |

Gap 3 is not a mobile lag. It is a new contract that both clients must follow, so plan it once for both.

## 2. Everything else checked and found level

Web items from 2026-11-14 onward, each confirmed in mobile by code or commit:

- Employee profile header and Overview redesign, edit from Overview with shift, attendance analytics and charts
  (`f893f41`, `1b5dd71`, `3109b3c`).
- HR Mark attendance, bulk day entry with review (`2516c2b`, `mark_day.dart` says it mirrors the web dialog).
- Shift Rosters single navigation with Coverage, Week, Month, Day and List (`2d5356a`).
- HR attendance page rework: Today, Trends, Reports tabs, mismatch fixes, find-an-employee, muster list/grid
  (`0155b04`, `f3fe353`, `117b53e`, `702e953`); periods and monthly summary under the periods screen.
- Attendance calendar status breakdown and per-person list (`571d4df`).
- Day explanation, R-D04 on web and R-E02 on mobile (`963c465`); month-summary endpoint and day display names
  (R-B01 to B05, `52b41bd`, `0dcb51f`, `dcb62ce`, `82f354f`, both clients).
- Report basis sentences and pending overtime minutes, R-F01 and R-F03 (`7a79305`, both clients).
- Salary tab card, save lines as a new structure (`046efeb`); all five enrollment photos for HR review (`f49542c`).
- Policy "Who follows this" with the coverage endpoint; dashboard branch filter and company insights
  (`bab554d`, `dashboard_screen.dart`); onboarding case redesign and Verify all (`9dcf4c7`); middle names.
- Auth, people, org setup, leave, payroll, notifications and onboarding: matched in the 2026-11-19 report and no
  web change since has reopened them. Mobile has 62 routes against web's 102 pages; the difference is detail
  pages that mobile opens as sheets or tabs, plus the items in section 3.

## 3. Intentional differences (not gaps)

- **Web only, by design:** platform admin console (`/platform/*`), landing page, Settings guide
  (`/app/settings/guide`) and the per-area Settings pages, browser print for payslips, password-less public
  routes' marketing copy. Mobile uses a searchable More hub and a setup screen instead.
- **Mobile only, by design:** face enrollment and liveness, GPS punch, share-sheet payslip PDF, and a single
  Approvals inbox (`/app/approvals`). Web has the pending-approvals card and the two decision centers.
- **Neither has a screen:** employee bulk import (`/employee-imports` exists in the API).
- **Mobile lacks, and is not on web either:** push notifications (needs Firebase), biometric unlock, offline
  banner, per-employee dark mode. Listed in `MOBILE_UX_NEXT_STEPS.md`.

## 4. Mobile's own open work (not parity)

From the handoff and the UX audit: MOB-UX-029 (split the 28-field new-employee form), MOB-UX-045 rest (the
13-tab employee record), MOB-UX-047 (quick chips on Team attendance), MOB-UX-046 (server-side `GET /employees`
status filter, needs an owner decision), MOB-UX-032 (offline, needs `connectivity_plus`), MOB-UX-041 (one
component kit). Employees with no attendance row are counted but not listed on mobile.

## 5. Recommended order

1. Decide the client work for assigned branches before the API change is released: a branch picker on invite and
   on the user edit screen, on both web and mobile, for `HR_ADMIN` and `BRANCH_MANAGER`.
2. Add R-F02 notices to mobile's period detail (small: read `notices`, show two labelled lines before close).
3. Add R-D06 to mobile's Insights Today tab (needs the list of employed people with no calculated day; the web
   gets it from the directory plus the summary, so check mobile has the employment dates first, which the handoff
   says it does not).
4. Try the 2026-11-19 mobile work on a phone using the checklist in the handoff section 3.1. Nothing from
   Phases 1 to 4 or the PAR work has been tried on a device.
5. Add the route-diff script suggested in the 2026-11-19 report. Endpoint string search was too noisy to trust
   again this time; every claim above was confirmed by reading code or commits.

## Confidence

High: gaps 1 and 2 (the commits touch no mobile file and the identifiers are absent), and gap 3 (read from the
working-tree diff). Medium: the "level" list, which rests on commit messages plus spot checks, not on running
the app or reading every screen.
