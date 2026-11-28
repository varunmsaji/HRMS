# Web vs mobile parity audit (2026-11-26)

Question: is the mobile app up to date with the web app?
**Update, same day:** gaps 1 to 4 below are now closed in code (commits `7d426f9`, `9bdd58a`, `fac7130`,
`0d2fdd5`, on PR 81). Two remain: row 5 (decision needed) and row 6 (not compared). None of the closed work
has been tried on a phone or against a running API.

Short answer: **mostly, but not fully.** Since the 2026-11-22 audit mobile closed the two gaps it listed
(R-F02, R-D06) and added push, but web then shipped a batch of attendance features (2026-11-24/25) that mobile
does not have, and one API contract change (assigned branches) is missing from **both** clients.

Scope: `apps/web` and `apps/mobile` on `test` at `de83274`. Static reading only (commits, route tables,
identifier search, reading the relevant files). Neither app was run, nothing was tried on a phone or browser.
Builds on `WEB_VS_MOBILE_PARITY_2026-11-22.md`. Only this file was written; no code changed.

## 1. Gaps that exist now

| # | Status | Feature | Web | Mobile | Evidence | Severity |
|---|---|---|---|---|---|---|
| 1 | **Closed** (`7d426f9`) | **Assigned branches** (API `adeffaa`): HR admin and branch manager must be given at least one branch; `branch_ids` on invite, user read and role update; `PUT /users/{id}/branches` | Not done. `users/page.tsx` posts `/users/invite` and patches roles with no branches | Not done. `inviteUser` sends only `email` and `roleCode` | `BranchAccessRequiredError` in `account_invite/exceptions.py`; `_needs_branches` in `service.py`; zero `branch_ids` matches in `web/src` and `mobile/lib` (mobile only has regenerated test fixtures, `0281c15`) | **High, shared.** Inviting or re-roling an HR admin or branch manager is rejected on both clients. Not a mobile lag: plan it once for both |
| 2 | **Closed** (`9bdd58a`) | **Monthly attendance statement** download per employee (`GET /attendance/employees/{id}/statement`, `85df47e`) | Yes (`statement-download.tsx`, employee page and self view) | No. No `statement` match in `mobile/lib` | commit file lists | Medium. An employee on a phone cannot get their own statement |
| 3 | **Closed** (`fac7130`) | **Pattern alerts** (often late, often absent, missing punches, same weekday) (`GET /attendance/pattern-alerts`) | Yes (`pattern-alerts.tsx`, `patterns.ts`) | No | no `pattern-alerts` in `mobile/lib` | Medium for managers and HR |
| 4 | **Closed** (`0d2fdd5`) | **Exports** of the muster register and the five reports (CSV, Excel, PDF) (`/attendance/export/muster`, `/attendance/reports/{report}/export`) | Yes (`export.ts`, reports panel, muster heatmap) | No. Mobile has only the employee directory CSV (`core/export/csv_export.dart`) | no `export` call in attendance mobile code | Low to medium. Share-sheet export is natural on a phone |
| 5 | Open, decision | **Attendance digest settings** page (`/app/attendance-digests`, `GET/PUT /attendance/digest-settings`) | Yes | No (`digest` appears only in the work-calendar change-impact screen) | route lists | Low. Rare admin setting; acceptable as web-only if decided |
| 6 | Open, not compared | Web attendance page: click-through, manager view, chart drill-downs (`de201a9`) | Yes | **Not checked in depth**; mobile Insights has charts and a Team screen with quick chips but I did not compare drill-down behaviour | `de201a9` touches no mobile file | Unknown, treat as medium until compared on screen |

## 1a. How the closed gaps were closed

- **Row 1:** a branch picker on invite and on the roles dialog, on web (`users/page.tsx`) and mobile
  (`users_screen.dart`). Shown only for HR admin and branch manager without company admin; at least one branch
  required; `branch_ids` sent on invite and role update; users list shows each person's branches.
- **Row 2:** a "Download statement" menu (PDF, Excel, CSV) on the month card, which both the employee's own
  screen and the HR employee profile use; the file goes to the share sheet.
- **Row 3:** a "Patterns to look at" card on the Insights Today tab, left out when the caller may not see it.
  Web also shows it in team view; mobile's Team attendance is a one-day list, so it is not there.
- **Row 4:** "Export register" (heatmap card) and "Export period" (Reports tab), with web's limits. Mobile
  Insights has no department, branch or shift filters, so mobile exports cover the whole range for everyone the
  caller can see, where web passes its filters through.

## 2. Closed since 2026-11-22

- R-F02 period-close notices and R-D06 "not calculated" notice: mobile `036dc08`, with `not_calculated.dart` and
  period detail changes.
- Mobile push notifications with a no-Firebase fallback (`e9772d1`) against API `cf686c6`; web has no equivalent
  need.
- MOB-UX-029 (new-employee form sections), MOB-UX-045 (employee record on three tabs), MOB-UX-047 (Team
  attendance chips), swipe-to-decide cards (`ce3e44f`).
- Error references (`ERR-`) on every error screen and handled-error reporting: both clients, same day
  (`bdc9cb5`, `82eaf26`).

## 3. Level and intentional differences (unchanged)

- Route count: web 103 pages, mobile 62 routes. The difference is detail pages that mobile opens as sheets or
  tabs, plus web-only areas: `/platform/*` console, landing, Settings pages and guide, browser print of
  payslips, the digest settings page above.
- Mobile only, by design: face enrollment and liveness, GPS punch, payslip share sheet, single Approvals inbox,
  push.
- Shift swaps, policy versions, pay runs, onboarding, leave, regularization and overtime decision centers,
  salary: present on both (endpoint and screen search; not run).
- Neither has a screen: employee bulk import (`/employee-imports`).

## 4. Method and limits

- Compared `git log 30a9649..HEAD` (37 commits) by which app each touched, route tables of both apps, and
  identifier search for each new API route.
- A raw endpoint-string diff was too noisy (test fixtures, interpolated paths) to trust; every gap above was
  confirmed by the commit's file list plus an absence search, not by that diff.
- Not verified: behaviour on a device, screens beyond the listed searches, row 6 detail.

## 5. Recommended order

1. Done: assigned branches, statement, pattern alerts, exports (section 1a).
2. Compare row 6 on screen, side by side.
3. Decide whether digest settings stay web-only and record it in the intentional list.
4. Try it on a phone and a browser, against a real API: invite an HR admin and a branch manager and edit their
   branches; download a statement in each format; open the pattern alerts card; export a register and a report.
   Also the unreleased mobile work in `MOBILE_HANDOFF_2026-11-20.md`, section 3.1.

## Confidence

High: rows 1 to 5 were real gaps when found (commit contents plus absence searches, row 1 also read from service code); rows 1 to 4 are now closed by code and automated tests only. Low: row 6.
