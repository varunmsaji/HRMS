# Employee mobile: final redesign specification

Status: **approved baseline pending sign-off** · 2026-10-30 · Documentation only. Do not start implementation without explicit approval.

Companions: [Final audit](EMPLOYEE_MOBILE_FINAL_AUDIT.md) (issues `EA-n`, decisions `D-n`, open items `O-n`) · [API and permission matrix](EMPLOYEE_MOBILE_FINAL_API_AND_PERMISSION_MATRIX.md) (`H-n` Home widgets, §5.3 attendance states, `F-n` findings) · [Design system](EMPLOYEE_MOBILE_FINAL_DESIGN_SYSTEM.md) (tokens, components) · [Implementation plan](EMPLOYEE_MOBILE_FINAL_IMPLEMENTATION_PLAN.md) (`T-n` tasks).

Quoted strings are the copy to ship. Everything else is layout. **No screen may call an endpoint that is not in the API matrix, add an action the API does not support, or remove a permission-gated control.**

---

## 1. Principles

1. One primary action per screen, visibly the primary one.
2. The workday first: status, then action, then history.
3. Never invent data. Missing data is absent, not a placeholder; an unknown status is "unavailable", not a guess (API matrix §5.3).
4. Company timezone for every clock and date (`lib/core/time.dart`), never the device's.
5. Server error messages are shown as returned (`describeApiError`).
6. Hiding is not security. Every control is also enforced by the API; the client mirrors it to avoid dead ends.
7. Employee-specific visuals come from the employee theme (D-04); permission branches on shared screens are preserved exactly (D-13).

---

## 2. Surface model

| Session | Predicate | Theme | Tabs | Landing |
|---|---|---|---|---|
| Employee surface | `employeeId != null` and no `DASHBOARD.COMPANY.VIEW` | employee, light only | Home (employee) · Attendance · Leave · Profile | `/app/home` |
| Administrator | holds `DASHBOARD.COMPANY.VIEW` | unchanged (system light/dark) | Home (dashboard) · Attendance · Leave · Profile | `/app/dashboard` |
| No employee record, no dashboard | neither | unchanged | Home (existing explanatory page) · Attendance · Leave · Profile | `/app/dashboard` |
| Not signed in / public token | none | unchanged system (D-14); public onboarding forced light | none | `/login` |

Managers (`REPORTING_MANAGER`, `BRANCH_MANAGER`) are employee-surface sessions with extra permissions; their Team and approve controls remain on the shared screens.

---

## 3. Navigation specification

### 3.1 Router structure (verified against `app_router.dart`)

* Public routes, unchanged: `/splash`, `/login`, `/register`, `/forgot-password`, `/reset-password/:token`, `/verify-email/:token`, `/accept-invite/:token`, `/onboarding/:token`.
* One `StatefulShellRoute.indexedStack` with four branches. **Branch 0 gains a second route** (D-02):

```
branch 0: /app/dashboard  (DashboardScreen)      /app/home  (EmployeeHomeScreen)
branch 1: /app/attendance                         branch 2: /app/leave-applications
branch 3: /app/me
```

* All other `/app/*` routes remain top-level, outside the shell (pushed, no bottom bar). They are reached with `context.push` so Back returns to the originating tab. No admin route is removed or renamed.

### 3.2 Redirect rules (additions in bold)

1. Public paths pass.
2. Loading → `/splash`. Unauthenticated → `/login` unless auth-only path.
3. Authenticated on `/splash` or auth-only → `landingPathFor(user)` (D-01).
4. **`/app/dashboard` and `/app/home` cross-redirect:** employee surface at `/app/dashboard` → `/app/home`; non-employee at `/app/home` → `/app/dashboard`.
5. **Permission guard (D-09):** if the location starts with a guarded prefix (§3.5) and the user holds none of its permissions → `landingPathFor(user)`. Never applied to shell tab paths or `/app/more`.

### 3.3 Tab visibility

| User | Branches shown | Rule |
|---|---|---|
| Employee surface | 0,1,2,3 | `visibleShellBranches`: Home now included whenever `showHomeTab` (employee id **or** dashboard permission **or** none) |
| Administrator | 0,1,2,3 | unchanged |
| Profile not loaded (null) | 0,1,2,3 | unchanged |

`showHomeTab` becomes: always true (the Home tab always has something to show: Home, dashboard, or the explanatory page). `shell_tabs_test.dart` case "employee without dashboard does not get Home" is replaced by "employee gets four tabs and `/app/home`" (T1-02).

Labels and icons: Home `home_outlined/home_rounded` on the employee surface; the administrator keeps `space_dashboard_*`. Attendance `fingerprint_rounded`; Leave `event_available_*`; Profile `person_*`.

### 3.4 More menu: permission navigation matrix

Data-driven (D-08): `NavEntry(label, route, anyOf: [permissions], employeeDefault: bool)`. An entry is shown when the user holds **at least one** of `anyOf` (or `anyOf` is empty). Search filters only visible entries. Groups with no visible entry are not shown. Sign out is not an entry, it is a fixed row.

Verification: ✔ = the API gate confirmed in source this pass; ◐ = mirror of the screen's own checks / inventory, confirmed against each router in T3-01 (acceptance requires it).

**Employee-visible entries (these four plus Sign out are the entire employee menu):**

| Label | Destination | Required permission (any of) | Employee | Administrator |
|---|---|---|---|---|
| Leave balances | `/app/leave-balances` | `LEAVE.BALANCE_VIEW`, `LEAVE.BALANCE_VIEW_ALL` ✔ | Shown | Shown (holds) |
| Attendance corrections | `/app/regularizations` | `ATTENDANCE.VIEW` ✔ | Shown | Shown |
| Overtime | `/app/overtime` | `ATTENDANCE.VIEW` ✔ | Shown | Shown |
| Payslips | `/app/me/payslips` | `PAYROLL.PAYSLIP_VIEW_OWN` ✔ | Shown | Shown if held |
| Sign out | confirm dialog | none | Shown | Shown |

**Administrator and manager entries (hidden from a default employee):**

| Label | Destination | Required permission (any of) | Employee | Administrator |
|---|---|---|---|---|
| Employees | `/app/employees` | `EMPLOYEE.VIEW_ALL` ✔ | Hidden | Shown |
| Onboarding | `/app/onboarding` | `ONBOARDING.VIEW` ✔, `.CREATE`, `.REVIEW`, `.ACTIVATE` | Hidden | Shown |
| Team attendance | `/app/team-attendance` | `ATTENDANCE.VIEW_ALL`, `EMPLOYEE.VIEW_ALL` ◐ | Hidden | Shown |
| Attendance insights | `/app/attendance-insights` | `ATTENDANCE.VIEW_ALL` ◐ | Hidden | Shown |
| Shift rosters / Roster calendar | `/app/rosters`, `/app/roster-calendar` | `ATTENDANCE.ROSTER_MANAGE` ◐ | Hidden | Shown |
| Attendance periods | `/app/attendance-periods` | `ATTENDANCE.LOCK`, `.UNLOCK`, `.VIEW_ALL` ◐ | Hidden | Shown |
| Payroll (pay runs) | `/app/payroll/pay-runs` | `PAYROLL.RUN_VIEW` ✔, `PAYROLL.RUN_PROCESS` | Hidden | Shown |
| Company | `/app/company` | `ORG.COMPANY.MANAGE` ◐ | Hidden | Shown |
| Branches | `/app/branches` | `ORG.BRANCH.MANAGE` ✔ | Hidden | Shown |
| Departments | `/app/departments` | `ORG.DEPARTMENT.MANAGE` ✔ | Hidden | Shown |
| Designations | `/app/designations` | `ORG.DESIGNATION.MANAGE` ✔ | Hidden | Shown |
| Grades | `/app/grades` | `ORG.GRADE.MANAGE` ◐ | Hidden | Shown |
| Legal entities | `/app/legal-entities` | `ORG.LEGAL_ENTITY.MANAGE` ◐ | Hidden | Shown |
| Shifts | `/app/shifts` | `ORG.SHIFT.MANAGE` ✔ | Hidden | Shown |
| Work calendars, Weekly-off patterns | `/app/work-calendars`, `/app/weekly-off-patterns` | `ORG.CALENDAR.MANAGE` ◐ | Hidden | Shown |
| Holiday calendars | `/app/holiday-calendars` | `ORG.HOLIDAY.MANAGE` ◐ | Hidden | Shown |
| Attendance / Overtime / Regularization policies | `/app/attendance-policies`, `/app/overtime-policies`, `/app/regularization-policies` | `ATTENDANCE.POLICY_MANAGE` ◐ | Hidden | Shown |
| Policy assignments, Policy resolution | `/app/policy-assignments`, `/app/policy-resolution` | `ORG.CALENDAR.MANAGE` or `ATTENDANCE.POLICY_MANAGE` ✔ (by policy kind) | Hidden | Shown |
| Leave types | `/app/leave-types` | `LEAVE.TYPE_MANAGE` ◐ | Hidden | Shown |
| Leave policies / Combination rules / Leave year / Statutory minimums | `/app/leave-policies`, `/app/leave-combination-rules`, `/app/leave-year-setting`, `/app/statutory-leave-minimums` | `LEAVE.POLICY_MANAGE` / `LEAVE.COMBINATION_RULE_MANAGE` / `LEAVE.YEAR_SETTING_MANAGE` / `LEAVE.STATUTORY_MINIMUM_MANAGE` ✔ | Hidden | Shown |
| Salary components, Salary structures | `/app/payroll/salary-components`, `/app/payroll/salary-structures` | `PAYROLL.SETUP_MANAGE` ✔ | Hidden | Shown |
| Statutory rates | `/app/payroll/statutory-rates` | `PAYROLL.STATUTORY_MANAGE` ✔ | Hidden | Shown |
| Setup | `/app/setup` | `ORG.COMPANY.MANAGE` ✔ (`GET /companies/current/setup-progress`) | Hidden | Shown |
| Users | `/app/users` | `SETTINGS.USER.MANAGE`, `SETTINGS.ROLE.MANAGE` ✔ (screen checks both) | Hidden | Shown |

**Implementation note (T3-01, 2026-10-30):** the gates above were checked against the API routers; those marked ✔ are confirmed. `Shift rosters` and `Attendance periods` have API gate `ATTENDANCE.VIEW` (which employees hold), so their menu gate is the team/admin permissions `ATTENDANCE.ROSTER_MANAGE`/`LOCK`/`UNLOCK`, `ATTENDANCE.VIEW_ALL` or `EMPLOYEE.VIEW_ALL` (branch managers keep them). An employee-surface user with team permissions sees "Your work" first, then the administrator-style groups for what they hold. The table lives in `lib/core/nav/nav_entries.dart`.

Rule: if an entry's gate cannot be confirmed, the safe default is the broader "any of" list, never a hard hide that would remove a manager's existing access. A manager must still see Team attendance and Team leave exactly as today.

The administrator More keeps today's two-level structure (Quick links grid, grouped settings). The employee More is one flat group, "Your work", with rows only (no two-column grid).

### 3.5 Route guard map (D-09)

`/app/employees`, `/app/onboarding`, `/app/team-attendance`, `/app/attendance-insights`, `/app/rosters`, `/app/roster-calendar`, `/app/attendance-periods`, `/app/payroll/*` (except `/app/me/payslips`), `/app/company`, `/app/branches`, `/app/departments`, `/app/designations`, `/app/grades`, `/app/legal-entities`, `/app/shifts`, `/app/work-calendars`, `/app/weekly-off-patterns`, `/app/holiday-calendars`, `/app/attendance-policies`, `/app/overtime-policies`, `/app/regularization-policies`, `/app/policy-*`, `/app/leave-types`, `/app/leave-policies`, `/app/leave-combination-rules`, `/app/leave-year-setting`, `/app/statutory-leave-minimums`, `/app/setup`, `/app/users` map to the `anyOf` of their §3.4 row. Unguarded: `/app/home`, `/app/dashboard` (own rule), `/app/attendance`, `/app/leave-applications`, `/app/me`, `/app/more`, `/app/leave-balances`, `/app/regularizations`, `/app/overtime`, `/app/me/payslips` (their data calls enforce the permission and the screen shows the existing error). The guard is a single table in `core/router/route_guard.dart`, shared with the menu so they cannot disagree. A deep link to a guarded route as an employee ends on Home with no admin screen built. **The API remains the authority**; a test confirms the API 403 handling still renders if the guard is bypassed.

### 3.6 State preservation, back, deep links, sign-out

* **State:** `indexedStack` keeps each branch alive. Re-tapping the active tab resets that branch to its root (`initialLocation: true`), as today. Home data uses `autoDispose` Riverpod providers keyed by `employeeId`; they refresh on tab re-entry only via pull-to-refresh and on explicit events (after punch, after cancel). Nothing is cached across sessions: sign-out must leave no previous user's data reachable (providers keyed by `employeeId`; a test logs out A, logs in B, asserts no A data).
* **Back (Android):** pushed screens pop. On the root of Attendance, Leave or Profile, Back goes to Home first; on Home, Back exits the app. (Small behaviour addition via `PopScope`, T1-02. Administrators get the same, since it only changes which tab is selected.)
* **Deep links:** `hrms://app/<path>` resolves to go_router `<path>`. The four public token routes are unchanged. Any other `/app/*` link: unauthenticated → `/login` (no return-to; matches today); authenticated → guard (§3.2). `hrms://app/app/home` is valid for employees.
* **Sign-out:** More row and Profile text button both call the shared confirm dialog (S34). Confirm → `AuthController.logout()` (never throws) → unauthenticated → router redirects to `/login`; the stack is replaced.
* **Shared screens:** `LeaveApplicationsScreen`, `LeaveApplicationDetailScreen`, `LeaveBalancesScreen`, `RequestListScreen/DetailScreen`, `EmployeeDetailScreen` (+ panels), `AttendanceDayDetailScreen`, `PayslipScreen`, `AuthScaffold` screens, `CompanyReadOnlyBanner`: see §5.

---

## 4. Screen specifications

### 4.0 Defaults inherited by every screen below

* **R (responsive):** content scrolls vertically; side padding 16 (20 at ≥390); at width ≥ 600 content is centred, max 600; 320 px must not overflow; text scale up to 2.0 wraps or scrolls, never clips; landscape not a target but must not throw.
* **A (accessibility):** 48 × 48 targets; labels per the design system §9; visual order = reading order; status = word + colour; focus visible; snackbars announced.
* **L (loading):** skeleton shaped like the content; a primary control is never replaced by a spinner.
* **E (error):** `StateMessage` with server message from `describeApiError` and "Try again" when the call is a read; writes show a snackbar and leave the form intact.
* **D (disabled):** busy controls show the phase sentence and are disabled; disabled-by-permission controls are **absent**, not greyed.
* **S (success):** snackbar with the existing copy, then refresh.
* Each screen lists only deviations. "Preserve" lists behaviour that must not change and the tests that guard it.

### Authentication and public

#### S01 Splash
**Purpose** Hold the UI while session restore and `GET /auth/me` resolve. **Entry** App start. **Header** None; light status icons. **Layout** Full-screen `#102A43`; column centred: mark 72, 16, white wordmark 26, 8, tagline "Your people, organized." (white 70 %, 14), 28, white spinner 26. **Info** None. **Primary/Secondary** None. **Navigation** Router leaves `/splash` when auth leaves `loading` (`landingPathFor` or `/login`); no timeout UI. **API** session restore, `GET /auth/me`. **States** Loading only; failed `/auth/me` is handled by `AuthController` (lands on login). **R** column capped 440 at ≥600. **Preserve** redirect rules and public-path bypass. **Acceptance** Cold start with a valid employee session opens `/app/home` without showing Profile; admin opens dashboard; no session opens login. Closes EA-23.

#### S02 Login
**Purpose** Sign in with work email and password. **Entry** Unauthenticated redirect. **Header** `AuthScaffold` navy band (mark 40, wordmark 22), no back. **Layout** Sheet (top radius 16, padding 24): "Sign in", "Use your work email.", Email, Password (show/hide 48 px), error line, unverified block (when `EMAIL_NOT_VERIFIED`: inset, "Verify your email before signing in.", text button "Resend verification email", then "Email sent."), primary "Sign in", text "Forgot password?", footer "Setting up a company? Create an account". **Primary** "Sign in" ("Signing in…" while busy, disabled). **Secondary** Forgot password → `/forgot-password`; Create an account → `/register` (company sign-up, unchanged). **API** `POST /auth/login`, `POST /auth/email/resend-verification`. **States** Validation "Email is required.", "Enter a valid email address.", "Password is required."; 401 "Invalid email or password."; 423 lock copy; 429 "Too many attempts. Please wait a moment and try again."; otherwise `error.message`. **R** band shrinks to 120 + inset below 640 height; sheet scrolls; drag dismisses keyboard (kept). **Preserve** `login()` arguments, error mapping, no password logging. **Acceptance** Employee success → `/app/home`; admin → `/app/dashboard`; wrong password stays with the 401 string; widget tests still find Email, Password, Sign in.

#### S03 Forgot password
**Purpose** Request a reset email. **Header** Scaffold, 48 px back to `/login`. **Layout** "Reset password", "We will email a link if an account exists for that address.", Email, "Send link", "Back to sign in". **API** `POST /auth/password/forgot`. **States** invalid email makes no call; submitting; success replaces the form with "Check your email" + typed address + "Back to sign in" (icon `mail_outlined`, `inkSecondary`); error shows API message. Does not reveal whether the account exists. **Preserve** repository method and non-enumerating success. **Acceptance** Invalid email never calls API; success hides the field.

#### S04 Reset password
**Purpose** Set a new password from the email token. **Entry** Public deep link (works with a live session). **Layout** "Choose a new password", New password, Confirm password, "Update password". **API** `POST /auth/password/reset`. **States** mismatch "Passwords do not match." (no call); expired token shows the server message and stays; success confirmation + "Sign in" (no auto-login; the repository returns none). Hint only if `validation.dart` enforces a rule, shown with its own message. **Preserve** token parameter, validator. **Acceptance** Mismatch never calls API.

#### S05 Verify email
**Purpose** Consume the verification token. **Entry** Public deep link. **Layout** Centred result: loading "Verifying…", success `check_circle_outline` (success glyph, 28, no circle) "Email verified" / "You can sign in.", failure `error_outline` + server message; "Sign in" on both. **API** `POST /auth/email/verify` (started in `initState`). **Acceptance** Valid shows success; invalid shows the API message and Sign in.

#### S06 Accept invite
**Purpose** Invited employee sets name and password and enters the app. **Entry** Public deep link. **Layout** "Accept invitation"; read-only invite email/company as `caption` only if `getInvite` returns them; the **existing** fields (match `accept_invite_screen.dart`; none dropped); existing submit label as primary. **API** `GET /public/account-invites/{token}`, `POST /public/account-invites/{token}/accept`. **States** loading; invalid/expired token → `StateMessage` and **no form**; submitting; API error under the button. **Navigation** Success → `landingPathFor` (`/app/home` for employee). **Preserve** token handling, JSON keys. **Acceptance** Expired token shows no form; valid submit with an employee profile opens Home.

#### S07 Public onboarding
**Purpose** Candidate completes HR-requested sections and submits. Not the signed-in profile. **Entry** Public deep link; no session; no bottom nav. **Header** Light scaffold (forced employee theme, D-14), app bar = step name ("Welcome", each section label, "Documents", "Review"), back goes to previous step (hidden on step 0), 4 px `ProgressTrack`, caption "Step n of m". **Layout** Step 0: welcome using identity fields the repository returns, else "Complete your details for HR."; steps: one column, labels above fields, repeatable sections keep add/remove, empty repeatable "Nothing added — you can skip this step if it does not apply."; Documents: type, filename, size, status, rejection reason, upload; Review: one row per section with its summary and chevron back to the step. **Primary** Bottom bar: "Get started" / "Save & continue" / "Submit" ("Saving…" / "Submitting…", both buttons disabled). **Secondary** "Back". **API** `/public/onboarding/{token}`: load, PATCH section, upload, submit. **States** skeleton; bad link "Link not available"; already activated terminal; field errors under fields; upload failure shows API message; success terminal with existing copy. **R** bar stacks above text scale 1.3. **Preserve** section order (Personal Info, Address, Emergency Contact, Bank Details, Statutory Details, Compensation, Previous Employment, Education, Nominees & Family, Documents, Review), PATCH-on-continue, submit; `public_onboarding_screen_test`, `onboarding_form_spec_test`. **Acceptance** Moving back loses nothing saved; bad token never shows fields; no employee nav. Closes EA-20.

### Shell

#### S08 App shell and navigation
Per §3. **Purpose** Move between four tabs keeping state. **Layout** Column: optional banner (S09), `Expanded(navigationShell)`, bottom bar (design system §7). **Primary** Selected tab. **Interaction** `goBranch`, haptic selection click, re-tap resets branch. **States** none of its own. **Preserve** `StatefulShellRoute` per-branch state, banner above body. **Acceptance** Employee: four tabs, lands on Home. Admin: dashboard on Home. Switching tabs never reloads another tab's form state. `shell_tabs_test` updated only for the new employee expectation.

#### S09 Company read-only banner
**Purpose** Say changes are blocked. **Layout** Full-width bar, icon 18 + 10 + text, padding 16/10, background from theme (`#FFFBEB` employee, existing for admin). **Copy** Pending: "Your company is awaiting approval. You can view data, but changes are disabled." Suspended: "Your company is suspended. You can view data, but changes are disabled." Hidden for any other status. **Preserve** statuses, copy, and that the API enforces the block; `company_read_only_banner_test`.

### Core employee experience

#### S10 Employee Home (closes EA-01, EA-03, EA-16)
**Purpose** The workday and the next action. **Entry** Login landing, Home tab. **Header** App bar "Home", no back, trailing text button "More" → `/app/more`. **Layout (top to bottom, each part omitted if its permission is missing, H-n in API matrix §6):**
1. Identity (H-01): `label` company-zone date "Friday, 30 Oct"; `title` first name (employee record, else omitted; never "there"); `caption` employee code.
2. `TodayStatusPanel` (H-02) in one of the 12 states of API matrix §5.3.
3. `CheckInAction` (H-03/H-04) inline (not sticky) when `ATTENDANCE.PUNCH`; same controller as Attendance.
4. `LeaveBalanceStrip` (H-05): ≤3 largest balances, "n reserved" when ≠ 0, "All balances" → `/app/leave-balances`.
5. "Needs attention" (H-06): `SUBMITTED` corrections and leave applications as `RequestRow`s; whole section omitted when none (no "all caught up" card).
6. "Leave" (H-07): ≤3 latest, "See all" → Leave tab.
7. "Recent days" (H-09): ≤3 previous days, status chip + worked time, tap → S12.
8. "Payslip" (H-08): one row, month + net, tap → S32.

**Primary** CheckInAction. **Secondary** More, All balances, See all, alternate punch. **Navigation** Tab root; rows push existing detail screens. **API** API matrix §6, all in parallel; none blocks another. **States** Loading: panel/strip/row skeletons. Partial failure: only the failed widget shows its message + "Try again" (attendance failure never hides leave). No employee id: "No employee record" + no punch. Empty optional sections: omitted. Disabled: punch control disabled until face status is known and while busy. Success: same punch snackbars as S11, then refresh H-02. **R** strip scrolls horizontally below 360; panel stacks times in a column when they do not fit. **A** panel announces its state sentence; punch button labels include direction. **Preserve** punch idempotency, geofence, face-required behaviour (one shared controller, T1-03); no `/dashboards/*` or holiday call from Home. **Acceptance** Employee login opens Home; today status obeys §5.3 for each state with a faked response; a punch from Home updates S11 and vice versa; a user with `DASHBOARD.COMPANY.VIEW` never builds this widget; zero requests to `/dashboards/*`, `/holiday-calendars`, or `/employees` (list).

#### S11 Attendance (closes EA-03, EA-04, EA-09)
**Purpose** Punch, see today, review the month and 14 days. **Entry** Tab. **Header** "Attendance", no back, no More icon on the employee surface (D-15); pull-to-refresh, no refresh button. **Layout** (1) `TodayStatusPanel` (same state table); (2) face block: required/enrolled/pending/rejected/window-open keep the existing `FacePunchCard` sentences as a flat inset (no icon badge), **not set up and not required** is one caption "Face attendance is not set up." and nothing else; (3) "This month" + month card; (4) "Last 14 days" in one grouped list: date block (kept), title = status word, caption = time range and worked minutes, chevron; (5) sticky `CheckInAction` bar at the bottom of the body above the tab bar, list bottom padding = bar height. **Month card** Monday-first "Mo Tu We Th Fr Sa Su"; cell ≥ 40, radius 8; fill = subtle tone, glyph 10 px, today ring 1.5 `action`; no-record days plain `inkTertiary` numerals, not tappable; legend of buckets present; summary "Present n · Absent n · Leave n" via `attendanceBucketOf`; semantics "15 October, Present". **Primary** Filled likely action: "Punch in" / "Punch out" (face required: "Face punch in" / "Face punch out"). **Secondary** Text button for the other direction ("Punch out instead" / "Punch in instead"); month prev/next; day tap. **API** days (14), punches (D-06), face enrollment, geofence policy, `punches/me`, face endpoints. **States** No employee record: warning message, no bar. History loading: skeleton rows, bar active. History error: `StateMessage` + Try again, bar active. Empty: "No attendance yet" / "Your punches will show up here." Face status loading: "Loading…" and bar disabled (a plain punch must not be offered then refused). Punch busy: "Checking location…", "Preparing face check…", "Verifying…" on the button. Failure: existing geofence/camera dialogs and snackbars. **R** below 340 the alternate action is a full-width text button under the primary; 7 columns without scroll. **Preserve** `punchMe`/`facePunchMe` payloads, per-direction idempotency, geofence modes, face-required hiding of plain punch, window `businessDayOffset(-13)…today`, descending sort, snackbar copy "Punched in." / "Punched out.", `attendance_self_mandatory_face_test`, `face_punch_card_test`, `punch_location_flow_test`, `punch_idempotency_test`. **Acceptance** Face not required: filled button visible at 360×640 without scrolling; face required: no plain buttons; punches request failure shows two equal buttons and no "clocked in" claim; today never says "Absent" before a lock (state 3); month colours match the bucket; no HR control (calculate today, punch on behalf) appears.

#### S12 Attendance day (closes EA-07)
**Purpose** Read one calculated day. **Entry** Row/cell tap, record Attendance tab, Home recent days. **Header** Title = formatted date in `day.timezone`; back. **Layout** (1) status header: `EmployeeStatusHeader` (3 px left border in tone), chip, First in / Last out, `heading` worked time; (2) flag chips (late, early out, overtime, regularized, pending approval, worked on holiday/weekly off, missing punch, work-on-leave phrases, core hours, on duty, locked); (3) Schedule; (4) Actual + one row per break "09:30–09:45 · 15m · paid"; (5) Overtime and pay; (6) leave overlay with its provenance sentence when projections loaded; (7) "Calculation details" expansion, collapsed for everyone, holding versions and timestamps. Empty/"—" rows omitted. **Primary** None. **Secondary** Recompute and Keep leave **only** with `ATTENDANCE.RECOMPUTE` (not locked; keep-leave only when flagged and unresolved), above the sections. **API** `GET /attendance/days/{id}`, leave projections (silent on failure). **States** skeleton from `initial`; 404 "This attendance day was not found, or you don't have access to it."; other errors Retry. **R** time columns stack under 340. **Preserve** `getAttendanceDay`, flags, keep-leave reason dialog, day timezone. **Acceptance** Employee never sees Recompute; HR with permission does; collapsed tile still contains the calculation version after expand; worked time equals `formatMinutes`.

#### S13 Face enrollment
**Purpose** Capture five poses in an HR-opened window. **Entry** "Set up face attendance" (only when the window is open). **Layout** Four stages, order kept: consent (explanation + required checkbox + "Continue"), capturing (full-bleed preview, pose name, `FacePoseTracker` hint), review (five thumbnails, "Submit"; retake only if it exists today), submitting ("Submitting…" + linear progress). **Header** App bar "Set up face attendance" on consent/review; transparent close over the camera; closing with ≥1 pose stored asks "Leave setup? Photos already taken will be discarded." **API** `POST /attendance/face-enrollment/me`. **States** denied → existing settings sentence; camera failure → existing message; submit error → API message, stay on review; starting → "Starting camera…". **Navigation** Pop `true` on success so the card shows "Face submitted. HR will review it before face punching is switched on." **Preserve** pose order, auto-capture rules, encoding, front camera, audio off, ML Kit options, frame disposal, `consentConfirmed: true`; `face_pose_tracker_test`. **Acceptance** Same photo map and consent sent; denial does not crash; cancelling after a capture discards images and pops `false`.

#### S14 Face liveness capture
**Purpose** Capture frames for the server's challenge; the phone never decides liveness. **Entry** Face punch (pushed `fullscreenDialog`). **Layout** Black preview, white instruction from the session, optional thin progress only if the session exposes counts, close. **Interaction** Capture automatic. **Outcomes** Close → `FaceCaptureCancelled` (no `facePunchMe`). Messages stay in `face_punch_card.dart`. **Preserve** outcome types in `face_liveness_capture.dart`, frames cleared in `finally`, server messages verbatim; `face_liveness_capture_test`.

#### S15 Location and geofence dialogs
**Purpose** Explain a location failure; retry or cancel before a punch is sent. **Layout** Standard dialog (employee chrome: radius 16, title `heading`, body `secondary`, max 400, margin 24): existing titles and server text unchanged; retry/settings action; Cancel aborts (`PunchLocationPlan.abort`). **Rules** DISABLED: no dialog. OPTIONAL: failure sent as `locationError`, punch proceeds. REQUIRED: no punch until a fix exists or cancel. Policy lookup failure: proceed without location. **Preserve** `planPunchLocation`, one foreground fix, no background collection; `punch_location_flow_test`, `location_capture_test`. **Acceptance** REQUIRED + denied permission never calls `punchMe`; OPTIONAL still does.

### Leave

#### S16 Leave applications (closes EA-12, EA-13, EA-16)
**Purpose** See own applications and start a new one; reviewers also see Team. **Entry** Tab. **Header** "Leave", no back; text button "Apply" when `canCreate` ("Apply on behalf" for on-behalf holders). **Layout** Mine/Team segmented control **only** with `LEAVE.APPLICATION_APPROVE` or `_SUBMIT_ON_BEHALF`; `LeaveBalanceStrip` first (Mine only, hidden on Team); caption of active filter "All dates · All statuses" + "Filter" text button; grouped `RequestRow`s: leave type, "1 Apr – 3 Apr · 3 days", status chip; "Load more" when `hasMore`. **Primary** "Apply" (app bar) and, when empty, button "Apply for leave". **Secondary** Filter sheet: From, To, Clear dates, status chips. **API** `GET /leave-applications` (`employee_id` forced to self unless Team), `GET /leave-balances`, `GET /leave-types`. **States** skeleton; error "Couldn't load leave" + Try again; empty "No leave applications" / "Applications you submit will show up here."; success "Leave application submitted." then reload. **Preserve** query (`application_status`, `date_from`, `date_to`), pagination, choice loading, on-behalf flag; `leave_applications_test`. **Acceptance** Employee: no Team, no on-behalf; no FAB; first data row visible at 360×640; Apply posts the same body.

#### S17 Apply for leave
**Purpose** Submit one application for self. **Entry** Apply. **Header** Full-screen form (not a dialog), title "Apply for leave", close/back confirms "Discard this application?" only if dirty. **Layout** Caption of loaded balances ("Casual · 8.5 available"; omitted if they failed; never blocks submit); fields in `leaveApplicationSpec` order: Leave type, Start date, End date, Half day ("Only for a single-day application"), Reason, Attachment reference, Expected delivery date ("Maternity leave only"); employee picker only when `onBehalf`. **Primary** Sticky "Submit" ("Submitting…"). **API** `POST /leave-applications` (idempotency key in repository). **States** choices loading skeleton fields; choice error + Retry; validation under fields; server 422/overlap/balance messages verbatim under the button. **Interaction** Done key on last field focuses Submit. **Preserve** payload keys; `extraValidate` (end before start, half day on a range); no `employee_id` for self. **Acceptance** Self body has no `employee_id`; half day on a range shows the existing error and does not POST.

#### S18 Leave application detail (closes EA-07)
**Purpose** Understand one application; withdraw when rules allow. **Entry** Row tap. **Header** Title = leave type (else "Leave"); back. **Layout** `EmployeeStatusHeader` (chip, date range, `heading` total days); Approve/Reject row **only when `canReview`** (never for the applicant); sections omitting empty values: Reason, Attachment reference, Expected delivery, Approval chain, Approval stage, Submitted at; when not `SUBMITTED`: Reviewed at, Reviewer comment, Rejection reason, Cancelled at, Cancellation reason; Days; History. **Primary** Bottom bar "Cancel application" (destructive text, full width) only when `canCancel`. **API** `GET /leave-applications/{id}`, cancel, review. **States** skeleton; 404 "Not found" with the access sentence; other errors Retry; busy disables actions. **R** Approve/Reject wrap under 360. **Preserve** `isOwn`, `hasStarted` in company zone, cancel-approved permission, reason-required rule, `If-Match`, excess-as-LOP in review dialog. **Acceptance** Employee cancels a `SUBMITTED` application; cannot cancel an approved one on/after start; a manager still sees Approve/Reject on someone else's pending row.

#### S19 Cancel leave dialog
Title "Cancel this application?". Body: approved → "The leave balance and attendance are reversed."; otherwise "The application is withdrawn." Reason field with helper "Required — the leave has already started." or "Optional". Actions "Keep it" and **filled error** "Cancel application". Validation "A reason is required." only when required. **Preserve** reason payload and `If-Match`. **Acceptance** Optional reason can be blank for submitted; required cannot; body equals today's.

#### S20 Leave balances (closes EA-16)
**Purpose** Read remaining leave and the ledger behind it. **Entry** Home strip, Leave strip, More. **Header** "Leave balances", back, no apply. **Layout** One grouped list: type name `bodyStrong`, code `caption`, balance `heading` tabular trailing, "n reserved" `micro` when ≠ 0; section "Ledger": `humanize(entryType)` + type, caption date and reason, trailing signed amount (negative in danger text); "Load more" when `hasMore`. **Secondary** Employee dropdown only with `LEAVE.BALANCE_VIEW_ALL` and >1 employee; Encash/Adjust only with `LEAVE.BALANCE_ADJUST`. **API** `GET /leave-balances?employee_id=`, `GET /leave-ledger?employee_id=&page=` (verified contract). **States** skeleton; error "Couldn't load balances" + Retry; empty "No balances yet" / "No balance-backed leave types configured yet."; ledger empty "No ledger activity yet."; no employee id: no call, "No employee record is linked to your account." **R** at scale ≥1.4 the figure moves under the name. **Preserve** decimal strings exactly (`leave_decimal_parsing_test`), ledger paging, adjust/encash dialogs. **Acceptance** Employee sees types and no Encash; holder of adjust still does.

### Profile

#### S21 Profile (closes EA-11, EA-15, EA-21)
**Purpose** Who I am at work; reach the longer record. **Entry** Tab. **Header** "Profile", no back, no More icon (employee surface). **Layout** Identity block (56 avatar on `actionSubtle`, name `title`, code `caption`, status chip, extra "Inactive" chip if `isActive` is false); "Work" (only values readable from `/employments` and `/assignments`: joining date, pay basis, work location type — D-10; id-only fields omitted; section omitted if both calls fail/403); "Personal" (DOB, gender, marital status, blood group, nationality); "Contact" (personal email, mobile, emergency name/relationship/phone); address paragraph only if any present-address field is set; row "Employment records" with caption "Statutory, bank, documents, and history." → S22; text button "Sign out" (danger) → S34. **Rule** every empty value omitted; no "Not set". **API** `GET /employees/{id}`, `/employments`, `/assignments`. **States** skeleton; error "Couldn't load profile" + Try again; no employee id: existing warning copy; Work failure = silent omission. **R** one column always; name wraps. **Preserve** `getEmployee`; edit/deactivate/invite/confirm stay on S22 for permitted roles. **Acceptance** A populated email shows; a null gender shows nothing; sign-out asks to confirm; an admin with an employee id opens the same layout.

#### S22 Employment and records
**Purpose** Read the rest of the file; HR keeps writes. **Entry** S21 row, employee directory. **Header** Employee name; back; scrollable tabs: Overview, record sections the user may view (Employment, Assignment, Compensation, Statutory, Banking, Identity, Experience, Education, Dependents), Salary (`EMPLOYEE.VIEW_COMPENSATION`), Documents, Attendance (`ATTENDANCE.VIEW`); tab label 13/600, indicator `action`. **Layout** Overview uses the S21 blocks when viewing the signed-in employee and keeps the HR action row (Edit, Confirm, Invite, Deactivate) for permitted users; Assignment tab: the six id fields show **"Recorded by HR"** instead of a UUID when no label is loaded (display only, D-10), rows for null values omitted; other tabs keep `EmployeeRecordPanel` content and `humanize`/`prettyEnum`. **API** per-tab `GET /employees/{id}/...`. **States** per-tab loading, empty "Nothing here yet", error + Retry (403 renders the existing error). **Preserve** every route, `If-Match`, every `RecordAction`; `employee_record_sections_test`, `employee_record_actions_test`. **Acceptance** EMPLOYEE sees no Edit/Upload/Assign/Terminate; HR still does; substitution applies to the six id fields only and never alters the payload; tabs keep state.

#### S23 Documents (tab)
Rows: title = document type humanized; caption = filename and size; trailing "Open" only when `downloadUrl` exists; no chevron without a URL (visible, not tappable). Upload/verify/reject/delete only with `EMPLOYEE.UPDATE_SENSITIVE`. API `GET /employees/{id}/documents`. States: loading, empty "No documents yet", error + retry. Preserve URL handling and HR flows. Acceptance: employee opens a row with a URL and sees no Upload.

#### S24 Salary (tab)
First block: breakup (tabular, `formatInr`), as-of date control (refetches `/salary/breakup?as_of=`), history rows (effective range, revision type). Assign only with `PAYROLL.SETUP_MANAGE`. No icon badges. No client maths. States: loading, error, empty history with current messages. Acceptance: EMPLOYEE sees figures and no Assign.

#### S25 Attendance (record tab)
Existing list of own days from `GET /attendance/days` for a from/to range; Calculate today and punch-on-behalf only with their permissions (both absent for employee); face-enrollment admin card HR-only. Visual: S11 day rows. Acceptance: no HR control for employee; rows open S12.

### Requests

#### S26 Attendance corrections list (closes EA-09, EA-12, EA-13)
Route stays `/app/regularizations`. **Header** "Attendance corrections", back; text button "Request" when `canCreate`. **Layout** Mine/Team only with approve or on-behalf permission; caption of the default window (last 30 business days in company zone) + status; "Filter" sheet (from, to, status, type); rows: type label + date as title (`regularizationTypeLabels`), reason as caption if set, status chip via `StatusMap`; no initials avatar. **API** `GET /regularizations` with `employee_id` on Mine and `statusParam` = `request_status`. **States** skeleton; error + retry; empty "No corrections" / "Requests you submit will show up here." + "Request" button. **Preserve** query parameters, `buildRegularizationBody`, `request_screens_test`. **Acceptance** No Team for an employee; status colours match leave for Submitted/Approved/Rejected/Cancelled.

#### S27 Correction detail
Header = type label; `EmployeeStatusHeader` (chip + attendance date); sections Request, Requested punches, Outcome (when not submitted), History; omit "—" rows; bottom "Cancel request" only when submitter and `SUBMITTED`; Approve/Reject for reviewers unchanged; punch lines in company zone; API `GET /regularizations/{id}`, cancel. Preserve self-approval and approver-mismatch codes as returned by the API.

#### S28 Correction form (closes F-1)
Full-screen form; title "Attendance correction"; discard confirm when dirty. Fields: Attendance date, Request type, toggle "Correct the assigned shift instead of punch times", then shift choice **or** check-in/out time, Reason, Attachment reference; helper "Times use your company timezone."; time fields stacked. **Choice loading (D-12)**: choices load per key; the `shifts` source loads only when the toggle is switched on; a 403 shows "Shift correction isn't available for your account." under the toggle and turns the toggle off; **no** "Could not load the options" banner for an employee, and a time-based request submits. API `POST /regularizations` (`ATTENDANCE.REGULARIZATION_REQUEST`). Preserve `buildRegularizationBody`, `wallTimeToUtcIso` (company zone), no `correct_shift` key, on-behalf employee field only in that mode. Acceptance: time-only request sends `requested_punches` and no `requested_shift_id`; shift correction does the opposite; opening as EMPLOYEE shows no error.

#### S29 Overtime
Header "Overtime", back, "Filter". Rows: attendance date title, caption "detected / approved minutes" (approved shown when > 0), status chip (PENDING, AUTO_APPROVED "Auto-approved" success, APPROVED, REJECTED). Default last 30 business days; Mine sends `employee_id`. No create, no FAB. Team and employee filter only with `ATTENDANCE.OVERTIME_APPROVE`. Empty "No overtime" / "Overtime appears here when it is recorded on your attendance." API `GET /overtime`. Acceptance: no create/approve for an employee.

#### S30 Overtime detail
Header = attendance date; status header; "Overtime" (day class, classification, multiplier, detected, approved, comp-off and expiry where the builder includes them); "Approval"; History. Minutes via `formatMinutes`. Approve/Reject for reviewers unchanged; codes `OVERTIME_SELF_APPROVAL_NOT_ALLOWED` and mismatch surfaced as returned.

### Payslips

#### S31 My payslips
Header "Payslips", back. One grouped list: `formatPayMonth` title, caption "Paid {payDate}" or "Paid —", trailing net (`bodyStrong`, tabular) + "Net pay" `micro`. Pull to refresh (add to `AsyncListScreen` only if absent; fetch unchanged). Empty "No payslips yet — they appear once a pay run is finalised." API `GET /me/payslips` only. Tap loads `getMyPayslip`. Acceptance: HR pay-run endpoints never called.

#### S32 Payslip (closes EA-07, EA-24)
Header "Payslip · {month}", back, actions Share PDF and Print (icons with tooltips; disabled while sharing). Layout: preview banner if `!isFinal` (kept for HR); net block (3 px `ink` top border, no gradient): entity name `caption`, "Net pay" `label`, `display` amount `formatInr`, `netInWords`, Gross and Deductions `heading`; address line; facts (employee, code, designation, department, joining date, masked PAN, UAN, ESI IP, paid by, days in month, paid days, LOP, pay date; nulls omitted); Earnings, Deductions, "Employer contributions (not part of net pay)" with notes, full-month amount when different, totals; leave balances chips; footer "This is a computer-generated payslip and does not need a signature." `display` falls to 24 if it would wrap. Failures: snackbar with the error string. Preserve both loaders (`getMyPayslip`, `getPayRunPayslip`), PDF filename, `Printing.sharePdf`/`layoutPdf`, all money fields; `payroll_test`. Acceptance: figures equal `formatInr` of API minor units; no gradient; HR pay-run payslip still opens.

### System

#### S33 More (closes EA-02, EA-05, EA-25)
Header "More", back (pushed). Employee: search + group "Your work" with the four §3.4 rows (title only, chevron, min 52) and the Sign out row (danger text, `logout_rounded`). Administrator: today's structure, filtered by §3.4. Search is case-insensitive over visible entries only; empty "No matches" / "Try a different word." No loading state. Preserve routes; do not delete administrator routes. Acceptance: employee session shows no Users/Payroll/Departments, and searching "Users" returns no matches; `SETTINGS.USER.MANAGE` holder still sees Users.

#### S34 Sign-out dialog
Title "Sign out?"; body "You will need to sign in again to use the app."; Cancel and text "Sign out" in danger. Used from More and Profile. Confirm → `logout()` (cannot throw) → `/login`. Acceptance: Cancel keeps the session on both entries. (Builds on the uncommitted More implementation, F-5.)

---

## 5. Shared screens: employee change vs administrator behaviour that must not change

| Shared screen | Employee-specific change | Administrator behaviour preserved |
|---|---|---|
| Attendance tab (S11) | Today panel, sticky punch, conditional face block, month glyphs; no More icon | Same layout in their theme (O-01); More icon stays on dashboard/admin app bars; punch-on-behalf lives elsewhere |
| Leave list (S16) | App-bar Apply, filter sheet, balance strip | Team segment, employee filter, "Apply on behalf", approve on detail |
| Leave detail (S18) | Status header, bottom cancel | Approve, Reject, cancel-approved |
| Leave balances (S20) | Flat rows | Employee dropdown, Encash, Adjust |
| Request list/detail (S26–S30) | Filter sheet, no avatar, shared chip | Team, on-behalf create, approve/reject |
| Records (S22–S25) | Profile blocks on Overview, id label rule | Edit, terminate, transfer, promote, confirm, invite, deactivate, documents/salary writes |
| Day detail (S12) | Flat header, collapsed audit | Recompute, Keep leave |
| Payslip (S32) | Flat net block | HR pay-run payslip route and preview banner |
| Auth screens (S02–S06) | Radius/labels only | Register stays company sign-up; copy and error branches unchanged |
| Banner (S09) | Recolour via theme | Same copy and statuses |
| Dashboard | not touched | unchanged |

---

## 6. Non-goals

No notification centre, announcement feed, task list, holiday browser, or team directory for the employee role. No break punch. No offline queue. No dark-mode toggle. No change to attendance, leave or payslip maths. No dashboard redesign. No new endpoint.
