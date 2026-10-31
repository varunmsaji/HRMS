> **Superseded (2026-10-30).** This combined file is the *first-pass* audit. It contains errors that were corrected after verification against source (leave-balance endpoint, punch-direction rule, missing-attendance handling, theme isolation, issue counts, auth endpoint paths). The authoritative baseline is:
> [Final audit](EMPLOYEE_MOBILE_FINAL_AUDIT.md) · [Final redesign specification](EMPLOYEE_MOBILE_FINAL_REDESIGN_SPECIFICATION.md) · [Final implementation plan](EMPLOYEE_MOBILE_FINAL_IMPLEMENTATION_PLAN.md) · [Final design system](EMPLOYEE_MOBILE_FINAL_DESIGN_SYSTEM.md) · [Final API and permission matrix](EMPLOYEE_MOBILE_FINAL_API_AND_PERMISSION_MATRIX.md).
> Kept for history; do not implement from this file.

# Employee mobile UI/UX audit and redesign

Audit date: 2026-10-30. Read-only planning document for the employee surfaces in `apps/mobile`. No application source was modified to produce this plan.

This file combines the screen inventory, UI audit, design system, screen-by-screen redesign specification, and implementation plan.

## Contents

1. [Screen inventory](#screen-inventory)
2. [UI/UX audit](#ui-audit)
3. [Design system](#design-system)
4. [Redesign specification](#redesign-specification)
5. [Implementation plan](#implementation-plan)

---

<a id="screen-inventory"></a>

## Employee mobile screen inventory

Audit date: 2026-10-30. Source of truth is `apps/mobile`, not route names alone.

This inventory covers the Flutter client at `apps/mobile` (`hrms_mobile` 0.1.0). It is one application for every company role. There is no separate employee binary. “Employee-facing” means a screen the system `EMPLOYEE` role can complete with its default grants, including auth and candidate onboarding. Administrator configuration screens are listed at the end because the More hub currently links to them; they are not employee product surfaces.

Related documents:

- [UI audit](#ui-audit)
- [Redesign specification](#redesign-specification)
- [Design system](#design-system)
- [Implementation plan](#implementation-plan)

### 1. Stack (discovered)

| Concern | Implementation |
|---|---|
| Framework | Flutter, Dart SDK `^3.7.2`, Material 3 (`useMaterial3: true`) |
| Navigation | `go_router` 14. `StatefulShellRoute.indexedStack` for four tabs. Pushed screens use `Navigator.push` / `MaterialPageRoute` and have **no** go_router path. |
| State | `flutter_riverpod` 2. `authControllerProvider` holds session and `UserProfile`. Feature screens are mostly `ConsumerStatefulWidget` with local loading flags, not a global cache. |
| HTTP | `dio` via `ApiClient`. Cookie jar for refresh token. Access token in `flutter_secure_storage`. Base URL from `--dart-define=API_BASE_URL`. |
| Styling | `AppTheme.light` / `AppTheme.dark` in `lib/core/theme/app_theme.dart`. `MaterialApp.router` sets both and does not set `themeMode`, so Flutter’s default `ThemeMode.system` applies. Font: Inter via `google_fonts`. Shared widgets: `lib/core/widgets/ui.dart`. |
| Forms | Generic `FormSpec` + `openSpecForm` (`lib/core/forms/`). |
| Lists that share one screen | `RequestListScreen` / `RequestDetailScreen` (`lib/core/requests/request_screens.dart`) for regularizations and overtime. `ResourceListScreen` for administrator masters. |

Entry: `lib/main.dart` → `HrmsApp`. Router: `lib/core/router/app_router.dart`.

### 2. System EMPLOYEE grants

Seeded in `apps/api/src/hrms/modules/organisation/service.py` for role code `EMPLOYEE`, all `SELF` scope:

| Permission | What the mobile UI does with it |
|---|---|
| `EMPLOYEE.VIEW` | Load own employee on Profile and Employment & records. |
| `EMPLOYEE.VIEW_COMPENSATION` | Compensation tab and Salary tab are visible. Assign salary stays hidden (`PAYROLL.SETUP_MANAGE` is absent). |
| `EMPLOYEE.VIEW_STATUTORY` | Statutory tab, read-only. |
| `EMPLOYEE.VIEW_BANKING` | Banking tab, read-only. |
| `EMPLOYEE.VIEW_SENSITIVE` | Identity tab (PAN, Aadhaar, UAN), read-only. |
| `EMPLOYEE.VIEW_EXPERIENCE` | Experience and Education tabs, read-only. |
| `EMPLOYEE.VIEW_NOMINEE` | Dependents tab, read-only. |
| `EMPLOYEE.VIEW_DOCUMENTS` | Documents tab. Upload, verify, reject, and delete need `EMPLOYEE.UPDATE_SENSITIVE`, which EMPLOYEE does not have. Download uses the presigned URL when present. |
| `LEAVE.APPLICATION_SUBMIT` | Apply, list own applications, cancel own submitted application, cancel own approved application only before the start date (company timezone). |
| `LEAVE.BALANCE_VIEW` | Own balances and ledger. Encash and adjust need `LEAVE.BALANCE_ADJUST`. |
| `ATTENDANCE.PUNCH` | Plain punch and face punch for self. |
| `ATTENDANCE.VIEW` | Own attendance days, own regularizations, own overtime records (`GET /overtime` is gated by `ATTENDANCE.VIEW`, not by the approve permission). |
| `ATTENDANCE.REGULARIZATION_REQUEST` | Create and cancel own submitted regularization. |
| `PAYROLL.PAYSLIP_VIEW_OWN` | `GET /me/payslips` and `GET /me/payslips/{run_id}`. |

Not granted, and the UI must keep hiding the matching actions: punch on behalf, attendance recompute, keep-leave, regularization approve, overtime approve, leave approve, leave submit on behalf, leave balance adjust, employee edit, document manage, payroll process, organisation manage, dashboard company view.

Landing today (`landingPathFor` in `lib/features/auth/state/auth_state.dart`): users with `DASHBOARD.COMPANY.VIEW` go to `/app/dashboard`. Everyone else with an `employeeId` goes to `/app/me`. The Home tab is hidden when `showHomeTab` is false (`lib/features/shell/app_shell.dart`), which is the normal employee case. Employees therefore have three tabs: Attendance, Leave, Profile.

### 3. Employee-facing surfaces

Routes are go_router paths. “Pushed” means `Navigator.push` with no URL.

#### 3.1 Authentication and onboarding

| Screen | Route | File | Purpose | APIs | Entry |
|---|---|---|---|---|---|
| Splash | `/splash` | `lib/features/splash/splash_screen.dart` | Hold the UI while the stored session and `/auth/me` resolve. | Session restore, `GET /auth/me` via `AuthController`. | App start. Redirects to login or `landingPathFor`. |
| Login | `/login` | `lib/features/auth/presentation/login_screen.dart` | Email and password sign-in. Shared with administrators. | `POST /auth/login`. Resend verification on `EMAIL_NOT_VERIFIED`. | Unauthenticated redirect. Links to forgot password and register. |
| Forgot password | `/forgot-password` | `lib/features/auth/presentation/forgot_password_screen.dart` | Request a reset email. | `POST /auth/forgot-password`. | Login footer. |
| Reset password | `/reset-password/:token` | `lib/features/auth/presentation/reset_password_screen.dart` | Set a new password from an email link. Public even if a session exists. | `POST /auth/reset-password`. | Deep link. |
| Verify email | `/verify-email/:token` | `lib/features/auth/presentation/verify_email_screen.dart` | Consume an email verification token. Public. | `POST /auth/verify-email`. | Deep link. |
| Accept invite | `/accept-invite/:token` | `lib/features/auth/presentation/accept_invite_screen.dart` | Employee sets name and password from an invite. Public. | `POST /auth/accept-invite` (confirm in `auth_repository.dart` before changing copy). | Deep link. On success, `landingPathFor`. |
| Public onboarding | `/onboarding/:token` | `lib/features/onboarding/presentation/public_onboarding_screen.dart` | Candidate wizard before an account exists. Not the signed-in profile. | Public onboarding repository: load case, PATCH sections, upload documents, submit. | Deep link. |

Register (`/register`, `register_screen.dart`) creates a **company**, not an employee account. It is out of the employee redesign. Keep the login link.

Onboarding sections, in order, from `onboarding_form_spec.dart`: Personal Info, Address, Emergency Contact, Bank Details, Statutory Details, Compensation, Previous Employment, Education, Nominees & Family, then Documents, then Review.

Chrome: `AuthScaffold` (`lib/features/auth/presentation/widgets/auth_scaffold.dart`) — navy header, white sheet, radius 28.

#### 3.2 Shell

| Screen | Route | File | Purpose | Notes |
|---|---|---|---|---|
| App shell | wraps `/app/dashboard`, `/app/attendance`, `/app/leave-applications`, `/app/me` | `lib/features/shell/app_shell.dart` | Bottom navigation and optional company banner. | Tabs filtered by `visibleShellBranches`. Haptic on tab change. |
| Company read-only banner | overlay | same file, `CompanyReadOnlyBanner` | Shown when `companyStatus` is `PENDING_APPROVAL` or `SUSPENDED`. | Copy is fixed. API still blocks writes. |

#### 3.3 Attendance

| Screen | Route | File | Purpose | APIs | Entry |
|---|---|---|---|---|---|
| My attendance | `/app/attendance` | `attendance_self_screen.dart` | Punch and review own days. | `GET /attendance/days` for the last 14 business days in the company zone. | Bottom tab. More action in the app bar. |
| Face attendance card | embedded | `face_punch_card.dart` | Enrollment status and face punch. | `GET` own face enrollment; `POST` liveness session; `POST` face punch; geofence policy. | Top of My attendance. |
| Face enrollment | pushed, fullscreen flow | `face_enrollment_screen.dart` | Consent, five poses, review, submit. | `submitFaceEnrollment`. Camera + on-device ML Kit pose gate only. | “Set up face attendance” when a window is open. |
| Face liveness capture | pushed, `fullscreenDialog` | `face_liveness_capture_screen.dart` | Capture the server challenge frames. | Frames posted by the punch card, not by this screen. | Face punch in/out. |
| Location dialogs | dialogs | `punch_location_flow.dart` | REQUIRED vs OPTIONAL geofence. One foreground fix per punch. | `GET` own geofence policy. | Before plain punch and around face punch. |
| Month grid | embedded | `attendance_month_card.dart` | Month of own days. | `GET /attendance/days` for the visible month. | “This month” on My attendance. |
| Attendance day | pushed | `attendance_day_detail_screen.dart` | One computed day. Shared with HR. | `GET /attendance/days/{id}`, leave projections (best effort). Recompute and keep-leave only with `ATTENDANCE.RECOMPUTE`. | Tap a day in the list or the month grid. |

There is no separate break-start screen. Breaks are computed intervals on the day (`breaks[]`, paid, unpaid, excess). Punch directions implemented in the UI are `IN` and `OUT` only.

Plain punch calls `punchMe` and is recorded with the server’s source value (the client does not send a mobile-specific source). Idempotency: a punch with no HTTP response reuses its key for the same direction.

#### 3.4 Leave

| Screen | Route | File | Purpose | APIs | Entry |
|---|---|---|---|---|---|
| Leave applications | `/app/leave-applications` | `leave_applications_screen.dart` | Own applications. Team segment only if `LEAVE.APPLICATION_APPROVE` or submit-on-behalf. | `GET /leave-applications` paged, filtered to own `employeeId`. Choices: `leave_types`. | Bottom tab. |
| Apply for leave | modal form | `spec_form_screen.dart` + `leave_application_form.dart` | Create one application. | `POST /leave-applications` with idempotency key inside the repository. | FAB “Apply for leave”. |
| Leave application | pushed | `leave_application_detail_screen.dart` | Detail, days, history, cancel. Approve/reject only for a reviewer who is not the applicant. | `GET /leave-applications/{id}`, cancel, and review endpoints. | Tap a row. |
| Cancel application dialog | dialog | same file | Withdraw or cancel. Reason required when approved leave has already started and the caller is allowed to cancel it. Employees cannot cancel an approved leave that has started. | `POST .../cancel` with `If-Match`. | Detail actions. |
| Leave balances | `/app/leave-balances` | `leave_balances_screen.dart` | Own balances and ledger. Employee picker and encash/adjust only with the matching admin permissions. | `GET /employees/{id}/leave-balances`, ledger page. | More → Leave Balances. Not linked from the Leave tab. |

#### 3.5 Profile, records, documents, salary

| Screen | Route | File | Purpose | APIs | Entry |
|---|---|---|---|---|---|
| My profile | `/app/me` | `profile_screen.dart` | Own overview. **Current employee landing.** | `GET /employees/{employeeId}`. | Tab, and post-login redirect. |
| Overview body | embedded | `employee_overview.dart` | Identity, personal contact, present address, emergency contact. Shared with the manager record. | Fields on the employee payload. No department, designation, or manager on this payload. | Profile body. |
| Employment & records | pushed | `employees_screen.dart` `EmployeeDetailScreen` | Tabbed own record. Same widget as an HR employee file. | Per-tab `GET /employees/{id}/...`. | “Employment & records” on the profile. |
| Record tabs | tabs inside the detail screen | `employee_record_sections.dart` | Employment, Assignment, Compensation, Statutory, Banking, Identity, Experience, Education, Dependents. | Paths in that file. Write actions are permission-gated and do not appear for EMPLOYEE. | Horizontal `TabBar`. |
| Documents | tab | `employee_documents_panel.dart` | List and open own documents. | `GET /employees/{id}/documents`, open `download_url`. | Records tab. |
| Salary | tab | `employee_salary_panel.dart` | Compensation history and breakup. Assign button hidden. | `GET /employees/{id}/salary`, `.../salary/breakup?as_of=`. | Records tab, because `VIEW_COMPENSATION` is granted. |
| Attendance inside the record | tab | `employee_attendance_panel.dart` | Another own-day list. Calculate today and punch-on-behalf hidden. | `GET /attendance/days` for a from/to range. | Records tab, because `ATTENDANCE.VIEW` is granted. |

Assignment rows display raw ids (`branch_id`, `department_id`, `reporting_manager_id`, `shift_id`). The mobile record panel does not resolve those ids to names for the employee.

Profile sign-out calls `logout()` immediately, with no confirm. More hub sign-out confirms first.

#### 3.6 Requests the employee can raise or read

| Screen | Route | File | Purpose | APIs | Entry |
|---|---|---|---|---|---|
| Regularizations | `/app/regularizations` | `request_screens.dart` + `regularizationConfig` | Own requests, default last 30 business days. | `GET /regularizations` (`ATTENDANCE.VIEW`). | More hub. |
| Regularization detail | pushed `RequestDetailScreen` | same | Sections: Request, Requested punches, Outcome, History. Cancel if status is `SUBMITTED` and `submitted_by_user_id` is the caller. | `GET /regularizations/{id}`, cancel. Approve hidden. | Row tap. |
| New regularization | modal `FormSpec` | `request_resources.dart` `regularizationSpec` | Date, type, shift correction or punch times, reason, attachment reference. | `POST /regularizations`. Times converted with company timezone (`wallTimeToUtcIso`). | FAB. |
| Overtime | `/app/overtime` | `RequestListScreen` + `overtimeConfig` | Own detected overtime. No create form (`createSpec` is null). | `GET /overtime` requires `ATTENDANCE.VIEW`. | More hub. |
| Overtime detail | pushed | `RequestDetailScreen` | Day class, minutes, multiplier, comp-off, approval, history. | `GET /overtime/{id}` (approve routes need `ATTENDANCE.OVERTIME_APPROVE`). | Row tap. |

Regularization types: Missing punch, Wrong punch time, Wrong shift, Wrong status, Work from home, On duty, Excess break, Full day correction, Early departure pre-approval.

#### 3.7 Payslips

| Screen | Route | File | Purpose | APIs | Entry |
|---|---|---|---|---|---|
| My payslips | `/app/me/payslips` | `my_payslips_screen.dart` | Finalised payslips for the signed-in employee. | `GET /me/payslips`. | More hub only. |
| Payslip | pushed | `payslip_screen.dart` | Net pay, facts, earnings, deductions, employer contributions, leave balances on the slip, PDF share and print. Shared with HR’s pay-run payslip. | `GET /me/payslips/{payRunId}` for self. | Row tap. PDF built on device (`payslip_pdf.dart`). |

#### 3.8 More hub

| Screen | Route | File | Purpose |
|---|---|---|---|
| More | `/app/more` | `settings_hub_screen.dart` | Searchable list of quick links and every settings group. **Not filtered by permission.** |
| Sign out dialog | dialog | same | Confirm, then `logout()`. |

Reached from `MoreAction` (`Icons.apps_outlined`) on Attendance, Leave, Profile, and request lists. Not on payslips (`AsyncListScreen` app bar has no More action).

### 4. What does not exist

Confirmed absent from `apps/mobile` dependencies and `lib/`:

- Push notifications, local notifications, and an in-app notification centre.
- Announcements.
- Tasks or work management.
- A holiday list for the employee. Holiday calendars are an administrator resource (`/app/holiday-calendars`). A day’s `holiday_name` appears only on an attendance day that has already been calculated.
- A dedicated “my team” screen for the EMPLOYEE role. Team attendance, employee directory, and leave “Team” mode require other permissions.
- Break in/out as its own punch action.
- Offline database or a queued punch.
- Biometric app lock and company switching.
- Help or support screen.
- An employee dashboard. The company dashboard exists and employees are redirected away from it.

### 5. Shared with administrators

These widgets render for EMPLOYEE and for HR. The redesign must keep the permission branches.

| Widget | Employee behaviour | Extra behaviour to preserve |
|---|---|---|
| `LeaveApplicationsScreen` | Mine, apply, date and status filters. | Team segment, employee filter, “Apply on behalf”, approve on the detail. |
| `LeaveApplicationDetailScreen` | Read and cancel under the rules above. | Approve, reject, cancel-approved for holders of those permissions. |
| `LeaveBalancesScreen` | Own cards and ledger. | Employee dropdown (`LEAVE.BALANCE_VIEW_ALL`), Encash and Adjust (`LEAVE.BALANCE_ADJUST`). |
| `RequestListScreen` / `RequestDetailScreen` | Mine, create regularization, read overtime. | Team segment, on-behalf create, approve and reject. |
| `EmployeeDetailScreen` and record sections | Read own tabs. | Edit, terminate, transfer, promote, confirm, invite, deactivate when permitted. |
| `EmployeeDocumentsPanel` | Open download URL. | Upload, verify, reject, delete. |
| `EmployeeSalaryPanel` | History and breakup. | Assign. |
| `EmployeeAttendancePanel` | Own days. | Calculate today, punch on behalf, face-enrollment admin card. |
| `AttendanceDayDetailScreen` | Read schedule, actuals, breaks, OT facts, leave overlay, audit. | Recompute, Keep leave. |
| `PayslipScreen` | Own slip via `/me/payslips/{id}`. | HR slip via pay-run employee route. |
| `AuthScaffold` screens | Employees use them. | Register remains the company-signup flow. |
| `CompanyReadOnlyBanner` | Same copy for every role. | Do not imply the client can override the API block. |

### 6. Administrator routes currently linked from More

Do not redesign these as employee screens. Filter them out of the employee hub. Keep the routes for roles that hold the permission. Each uses `ResourceListScreen`, `RequestListScreen`, or a dedicated screen and returns an API error (often 403) when the caller cannot access it. The mobile shell does not pre-check.

| Route | Screen | Typical permission (API; mobile often does not check first) |
|---|---|---|
| `/app/dashboard` | `DashboardScreen` | `DASHBOARD.COMPANY.VIEW`. Employees are redirected to `/app/me`. |
| `/app/employees` | `EmployeesScreen` | `EMPLOYEE.VIEW_ALL` to list. |
| `/app/onboarding` | `OnboardingCasesScreen` | Onboarding review/create permissions. |
| `/app/team-attendance` | `TeamAttendanceScreen` | `ATTENDANCE.VIEW_ALL` for the broad list; punch on behalf is separate. |
| `/app/attendance-insights` | `AttendanceInsightsScreen` | Company attendance read beyond self. |
| `/app/rosters`, `/app/roster-calendar` | Roster screens | `ATTENDANCE.ROSTER_MANAGE` for writes. |
| `/app/attendance-periods` | Periods and detail | Lock, unlock, recompute. |
| `/app/policy-assignments`, `/app/policy-resolution` | Policy screens | Policy manage / resolution. |
| `/app/company` and organisation masters | Company, branches, departments, designations, grades, legal entities | `ORG.*.MANAGE`. |
| `/app/shifts` and calendar masters | Shifts, work calendars, holiday calendars, weekly-off patterns | `ORG.SHIFT.MANAGE`, `ORG.CALENDAR.MANAGE`, `ORG.HOLIDAY.MANAGE`. |
| `/app/attendance-policies`, overtime policies, regularization policies | Resource lists | `ATTENDANCE.POLICY_MANAGE`. |
| `/app/leave-types`, leave policies, combination rules, leave year, statutory minimums | Leave administration | `LEAVE.TYPE_MANAGE`, `LEAVE.POLICY_MANAGE`, and related. |
| `/app/payroll/pay-runs` and payroll setup | Pay runs, components, structures, statutory rates | Payroll process, setup, statutory manage. |
| `/app/setup`, `/app/users` | Setup and users | `SETTINGS.USER.MANAGE`, `SETTINGS.ROLE.MANAGE`. |

`DashboardScreen` (`dashboard_screen.dart`, about 887 lines) is the company operations dashboard. It is not an employee home. This programme does not reskin it.

### 7. Data the employee home is allowed to use

A new Home screen may only compose calls that already succeed for EMPLOYEE:

- `GET /auth/me` fields already on `UserProfile` (name, email, `employeeId`, company timezone, company status, permissions).
- `GET /employees/{id}` for display name and employee code.
- `GET /attendance/days` for today and the recent window (company timezone via `businessToday`).
- Face enrollment status used by `FacePunchCard`.
- `GET /leave-balances` for that employee.
- `GET /leave-applications` for the latest own rows.
- `GET /regularizations` for own pending rows.
- `GET /me/payslips` for the latest slip.
- `GET /overtime` for own rows, optional and secondary.

Do not add announcements, a task inbox, a team roster, or an upcoming-holiday feed. No employee-scoped holiday endpoint was found; holiday administration is `/holiday-calendars`.

---

<a id="ui-audit"></a>

## Employee mobile UI/UX audit

Audit date: 2026-10-30. Read-only. No application source was modified.

Scope: employee self-service in `apps/mobile`. The same binary contains the administrator product. Findings below are about the employee path. Administrator master-data screens are out of scope except where the employee can open them.

Inventory and file references: [EMPLOYEE_MOBILE_SCREEN_INVENTORY.md](#screen-inventory).

### 1. How the employee app actually works

Flutter, Riverpod, go_router, Dio. Light and dark themes both exist; the app follows the phone theme. Four shell branches exist in the router. For a normal `EMPLOYEE` user the Home branch is removed, and login lands on `/app/me` (My Profile). Attendance, Leave, and Profile are the tabs. Everything else is behind an unfiltered More menu that mirrors the web settings nav.

The employee can punch (plain and face), see their days, apply for leave, read balances, request a regularization, read overtime the system detected, read their record and documents, and open payslips. They cannot edit the record, upload documents, approve anything, or see the company dashboard.

Breaks are calculated facts on an attendance day, not a button. Holidays appear as a name on a calculated day, not as a calendar the employee browses. There is no notification centre, announcement feed, task list, team screen, or help screen.

### 2. Audit method

Each employee surface was read in `apps/mobile/lib`, including dialogs and pushed routes that have no URL. Permissions were checked against the `EMPLOYEE` grants in `organisation/service.py` and against the `if (permissions.contains(...))` branches in the widgets. API paths were taken from the repositories, not inferred from screen titles.

Severity:

- Critical: the employee cannot see the thing they opened the app to do, or the navigation actively sends them into the wrong product.
- High: the task is possible, but the screen looks or behaves like an admin tool and will be misread.
- Medium: inconsistency that makes the product feel unfinished.
- Low: polish that does not block the task.

### 3. Screen findings

#### 3.1 Splash, login, and account recovery

Splash is the strongest branded moment: navy field, Krewoxa mark, wordmark, tagline “Your people, organized.” Login, forgot password, reset, verify, and accept-invite share `AuthScaffold`: navy header, 28px white sheet, 52px controls. That sheet is more considered than the in-app screens. Problems are smaller: register (company signup) sits next to employee sign-in with equal weight; error text is a single string under the form; there is no employee-specific reassurance about which company they are joining on the invite screen beyond what the API returns. Public onboarding is a generic step wizard (`LinearProgressIndicator`, default `AppBar`, `FormSpec` fields) and does not use `AuthScaffold`, so the candidate’s first real task looks like a different product from login.

States that do exist: invalid email, empty password, 401, 423 lock, 429, unverified email with resend, token errors on reset and verify. Keyboard dismiss-on-drag is implemented on the auth sheet.

#### 3.2 Shell

Bottom navigation is appropriate. Four destinations are the right number. The labels Home / Attendance / Leave / Profile match the product, but Home is hidden for employees, so the bar’s first mental model is a lie: the code comment still calls the bar Dashboard / Attendance / Leave / Profile.

`MoreAction` (`apps` grid icon, tooltip “More”) is on the tab app bars and on request lists. It opens the entire administrator catalogue. An employee can search “Payroll” or “Users” and land on a 403 or an empty error. That is the most damaging navigation bug in the employee experience.

The company banner uses an orange `tertiaryContainer` that reads as a failure. The copy itself is clear and must stay.

Touch targets on the bar are adequate (height 68). Safe area is handled by `NavigationBar`. There is no gesture back customisation beyond Material/Cupertino transitions.

#### 3.3 Attendance

`AttendanceSelfScreen` is a `ListView` of: face card, two punch buttons, “This month” calendar card, “Last 14 days” of `AttendanceDayTile` cards. Pull to refresh reloads the 14-day list. The punch buttons and the month card load on their own, which is the right priority and must be kept.

What is missing on the screen the employee uses every day:

- No statement of today’s status before the buttons. The 14-day list may contain today, as one more card.
- Punch in and punch out are equal. The employee must know which one they need.
- When face verification is required, the plain buttons disappear and the face card’s sentence changes. When it is not required, the face card still occupies the top with “not set up yet” even if the company never uses face attendance. That empty instruction is the first thing on the screen.
- The month grid uses stock `Colors.green` / `red` / `purple` at 22% alpha, two-letter weekday collisions (T, T, S, S), no legend, and cells that are hard to hit on a 320px-wide phone. Counts under the grid (“Present n · Absent n · Leave n”) are the only summary, in 12px grey.
- Day tiles are the same card pattern as leave rows and settings rows. The date block is the best piece of hierarchy on the screen and should survive.
- Location and geofence failures are dialogs and snackbars. They are functionally careful (REQUIRED blocks, OPTIONAL continues, idempotency on unknown outcome). They are visually default `AlertDialog`s. That is acceptable if the dialog copy stays; it is not a visual system.
- Face enrollment and liveness are full-screen camera flows. They are task UIs, not cards. Their problem is inconsistency with the rest of the app (default app bar, default progress), not lack of decoration. Do not restyle the camera stage into a card.

`AttendanceDayDetailScreen` leads with a navy gradient `HeroCard`, then a wrap of chips, then five `DetailSection` cards (Schedule, Actual, Overtime & pay facts, Leave overlay, Calculation & audit). For an employee, the audit block (policy version ids, calculation version) is noise above the fold. The useful content is status, first in, last out, worked time, late/early flags, and breaks. HR recompute and keep-leave are correctly hidden without `ATTENDANCE.RECOMPUTE`.

There is no pull-to-refresh on the month card independent of the parent. Changing month shows a spinner inside the card. Empty month and error month exist.

#### 3.4 Leave

The Leave tab is an administrator list that happens to be filtered to one employee. Above the list: date buttons “From” / “To”, a horizontal chip row of All / Submitted / Approved / Rejected / Cancelled, then cards. The apply action is an extended FAB, so the primary task floats over the list and is absent from the empty state except as a separate message. Balances are not on this screen. An employee cannot see “how many days do I have” without opening More → Leave Balances.

Filters default to open, not collapsed, so the first screenful can be controls. There is no Mine/Team control for a pure employee, which is correct. Pagination is “load more”, not an infinite scroll. Pull to refresh exists when the list is showing. Loading uses `ListSkeleton`. Error and empty states exist.

The apply form is `FormSpec`: leave type, start, end, half day, reason, attachment reference, expected delivery date. Validation for end-before-start and half-day-on-a-range exists in `leave_application_form.dart` and must stay. The form looks like every other spec form (stacked fields, generic submit).

Detail repeats the gradient hero (type, status, dates, total days), then action buttons, then key-value sections for request, outcome, days, and history. Cancel rules are implemented and must not be simplified. Reviewer comment and rejection reason are present when the status is not `SUBMITTED`.

Leave balances are another card list: icon badge, type name, code, a 22px number, reserved caption, then a ledger of more cards. For an employee the number is the point and the ledger should be secondary. Encash and Adjust are hidden, correctly. Empty copy “No balance-backed leave types configured yet” is honest and should stay.

#### 3.5 Profile and records

Profile is a navy gradient header (initials, name, employee code, status pill) and then four identical cards: Identity, Personal contact, Present address, Emergency contact. Every field renders, and empty fields say “Not set” in a two-column wrap. On a phone that wrap makes “Date of birth / Not set” sit beside “Gender / Not set”. The employee’s job — department, designation, manager, joining date — is not on this screen. It is behind “Employment & records”, which pushes `EmployeeDetailScreen`, the HR file: a scrollable tab bar of Overview, Employment, Assignment, Compensation, Statutory, Banking, Identity, Experience, Education, Dependents, Salary, Documents, Attendance.

That is the wrong information architecture for someone checking their own designation. It is the right data, in an HR container. Assignment values are raw UUIDs. Salary and the second attendance list duplicate the Attendance tab and the payslip. Sign out on the profile is a text button with no confirmation, while More confirms. Documents are a manage-shaped list even when the only action is open.

Loading skeleton, error with retry, pull to refresh, and the no-employee-record message all exist on the profile.

#### 3.6 Regularizations and overtime

Both are `RequestListScreen`: a column of date buttons, status dropdown, type dropdown, then `ListRowCard`s with an initials avatar of the word “Regularization request”, and an extended FAB. The employee’s own name is not shown (Mine view passes an empty name). Default range is the last 30 business days, which is correct and easy to miss because the buttons read “From 2026-10-01”.

Status chips here use raw green, red, and orange and a 4px radius, while the rest of the app uses `StatusChip`. That is a concrete inconsistency, not a taste note.

Detail is section title plus key-value rows. Approve and reject stay hidden. Cancel stays for the submitter while `SUBMITTED`. Overtime has no FAB, which is correct. An employee who opens Overtime from More sees a filter-heavy list of system records. The data is theirs; the chrome is an approval inbox.

#### 3.7 Payslips

`MyPayslipsScreen` is the closest thing to a clear employee list: month, pay date, net amount, tap through. It uses `ListRowCard` and `IconBadge` again, but the trailing net figure is the right hierarchy. It is only in More, not in the tab bar and not on Home. The payslip itself is strong on content (net, gross, deductions, earnings lines, employer contributions, masked PAN, paid days, LOP, PDF share and print) and weak on chrome (another navy-to-blue gradient, then more cards). Preview banner for non-final slips exists; own payslips are finalised by API contract, but the banner must remain because the same widget renders HR previews.

#### 3.8 Public onboarding

A linear wizard with progress, back, and “Save & continue”. Sections match the web spec. Documents can be skipped when empty if the section is repeatable. Terminal states exist for a bad link and for an already activated case. Visually it is a default scaffold. That is a medium issue: candidates see it once, but it is the product’s first impression after the invite email.

### 4. Why it looks generic

The theme file already aims at a Stitch “technobeala” system and a Krewoxa navy. The employee screens still look generic because the composition never changes, not because there are no tokens.

| # | Issue | Screens | Current implementation | Why it is a problem | Improvement | Benefit | Priority |
|---|---|---|---|---|---|---|---|
| G1 | One card recipe | Attendance days, leave rows, balances, profile sections, More groups, payslip lines, request rows | `AppCard` or `ListRowCard` plus `IconBadge` plus title plus subtitle plus chip | Every task has the same silhouette, so nothing looks more important than anything else. | Open sections and flat rows. One bordered panel per screen for the primary status. | The employee can find today’s punch and the leave balance without scanning decorations. | P0 |
| G2 | Gradient heroes | Profile, attendance day, leave detail, payslip | `HeroCard` / `LinearGradient` from `AppBrand.navy` to navy-deep or `#1E3A8A` | The gradient is the same decoration on unrelated tasks. It also fights the “no dark default” requirement by painting a dark header on a light app. | Flat sheet, navy text, a 3px `ink` rule or a status chip. | Identity stays in the wordmark and the action colour, not in a repeated banner. | P1 |
| G3 | No employee home | Post-login | `landingPathFor` sends employees to profile. Home tab hidden. | The first screen is a personal-data form, not the workday. | Home composed only of existing attendance, leave, regularization, and payslip calls. | Punch, balance, and pending requests are visible in one place. | P0 |
| G4 | Admin navigation leaked | More hub | `_quickLinks` and `_settingsGroups` are constant lists. | Employees meet payroll setup, users, and legal entities. Failures look like a broken app. | Hub items gated by permission. Employee menu is four links plus sign out. | The product matches the role. | P0 |
| G5 | Equal punch buttons | Attendance, face card | `Row` of `FilledButton` Punch in and `OutlinedButton` Punch out. | The screen does not say whether the employee is in or out. | One filled button for the likely direction, text button for the other. Face path unchanged when required. | Fewer wrong-direction punches. Both directions remain available, so server behaviour is unchanged. | P0 |
| G6 | Type scale is desktop-small | All in-app screens | Body 13–14, labels 11–12 (`AppTheme._textTheme`). | On a phone, secondary text falls under a comfortable reading size, and titles are not actually larger than card titles. | Employee scale in the design system: 16 body, 18 section, 22 screen, 28 for one figure. | Hierarchy becomes visible without new colours. | P1 |
| G7 | Status colour drift | Month grid, request chips | `Colors.green`, `Colors.red`, `Colors.orange`, 4px chips. | The same “approved” is a green chip on leave and an orange box on regularizations. The month grid ignores `AppStatusColors`. | Route all statuses through `StatusChip` and the existing status palette. Add a glyph on the month cell. | Colour means one thing. | P1 |
| G8 | Empty fields as content | Profile overview | Every field paints “Not set”. | The screen looks unfinished and hides the few values that exist. | Omit empty rows. Lead with code, status, and the assignment fields that have display names. | The profile looks like a record, not a sparse form. | P1 |
| G9 | Primary actions are FABs | Leave, regularizations | `FloatingActionButton.extended`. | The action is easy to cover with the thumb and is disconnected from the empty state. | App-bar action plus empty-state button. | Apply and request sit where the employee looks for a command. | P1 |
| G10 | Filters before content | Leave, regularizations, overtime | Date buttons and dropdowns always expanded. | The list is below the fold on small phones. | One “Filter” text button opening a sheet. Show the active range as a caption. | The first row of real data is visible immediately. | P1 |
| G11 | Lavender canvas | All scaffolds | `scaffoldBackgroundColor` is `#F3F3FE`. | Combined with white 16px cards it is the default Material 3 look. | Canvas `#F4F6F8`, sheet `#FFFFFF`, hairline `#E4E7EB`. | The app stops looking like an untouched Material sample. | P1 |
| G12 | Radius and shape mix | Theme vs widgets | Tokens say 2–12; cards are 16; dialogs 24; sheets 28; month cells 10; request chips 4. | Nothing feels cut from one system. | Employee radii 8 / 10 / 16 only. | Controls and surfaces match. | P2 |
| G13 | System dark theme | `HrmsApp` | `theme` and `darkTheme` set, `themeMode` omitted. | A phone in dark mode gets the dark scheme the product brief does not want as the employee default. | `themeMode: ThemeMode.light` for this app until a setting exists. | The designed light UI is what ships. | P1 |
| G14 | Face card always first | Attendance | `FacePunchCard` is unconditional. | Companies that have not opened enrollment still see a setup essay above the punch buttons. | When status is “not set up” and face is not required, move the card below the today panel as a single text row, or hide it. Keep it dominant when enrollment is open, pending, rejected, or required. | Punch is first when punch is the task. | P0 |
| G15 | Second attendance and salary buried in HR tabs | Profile record | 13 tabs, UUIDs on assignment. | Employees will not find designation or a document. | A short profile: identity, work (joining, designation, department, manager, shift when the API provides a name), contact, then “Records” for statutory, bank, documents. | The common questions are answered without a tab safari. | P1 |

### 5. Quality checklist

#### Visual

Professional appearance is uneven: auth and splash are branded; in-app screens are a component demo. Hierarchy is flat because of G1 and G6. Colour is inconsistent (G7, G11). Iconography is consistent only in the sense that it is always a Material icon in a circle. Spacing is a uniform 16, which is tidy and also why sections do not group. Buttons and inputs follow Material defaults with a 12px radius. Information density is low on profile (empty fields) and high on the attendance day (audit ids).

#### Experience

Common tasks and steps today:

| Task | Steps |
|---|---|
| Punch in | Login lands on Profile → Attendance tab → choose Punch in → location dialog if required. |
| See if I am in | Attendance tab → scan the 14-day cards. |
| Apply for leave | Leave tab → FAB → form. Balance is not in the flow. |
| See balance | Any tab → More → Leave Balances. |
| Correct a missed punch | More → Regularizations → FAB → form. |
| Payslip | More → My Payslips → row. |
| Who is my manager | Profile → Employment & records → Assignment tab → raw id. |

Discoverability of balances, payslips, and corrections is poor. Feedback is a snackbar, which is fine. Consistency fails across status chips and heroes. Touch targets on the month grid and on filter chips are the weak spots. There is no reduced-motion path and no text-scale test evident in the widget tests.

#### Mobile behaviour

- Small screens: filter stacks and the two-column profile wrap will overflow or crowd at 320px. The month grid’s `childAspectRatio: 1.1` makes cells short.
- Safe area: auth sheet and the bottom bar handle it. Sticky content does not exist yet; the FAB pads the list (`bottom: 88` on request lists).
- Keyboard: auth scroll dismisses on drag. Spec forms need the same; confirm during implementation rather than assuming every form has it.
- Scroll: attendance, leave, profile, balances, and requests scroll. The shell does not.
- Pull to refresh: attendance, leave list, profile, balances, request lists, day detail, leave detail. Not on splash or auth. Month card refreshes on month change and when the parent reloads only if the parent rebuilds it; the month card keeps its own state.
- Offline: `ApiError` with status 0 becomes a message. Punch idempotency is implemented. There is no offline queue and this redesign must not add one.
- Loading: skeletons on profile, leave, balances, payslips. Attendance history uses a centred spinner. Face card uses the word “Loading…”.

#### Enterprise quality

Compared with a serious employee app (the bar is “I can punch, request leave, and read my slip without learning the HR console”):

- Information architecture matches the web settings tree, not the employee’s week.
- Status language exists in the API and is only partly translated into a consistent chip.
- There is no chart that would help, and none should be added for its own sake. The month grid is the right visualization once it uses the status system.
- Forms work and validate. They look like internal tools.
- Empty states exist and are plain, which is better than illustration kits. Keep them plain.
- Notifications do not exist. Do not design a bell icon that opens an empty screen.

### 6. Counts

| Item | Count |
|---|---|
| Employee-facing surfaces audited (screens, embedded task UIs, and the dialogs that carry a decision) | 35, listed in the inventory §§3.1–3.8 |
| Proposed surface that does not exist yet | 1, Employee Home, composition of existing APIs only |
| Administrator routes discovered and excluded from redesign | 30+ More destinations, inventory §6 |
| Critical issues | 5 (G3, G4, G5, G14, and the missing today-status which is part of G5’s screen) |
| High-priority improvements | 11 (G1, G2, G6, G7, G8, G9, G10, G11, G13, G15, and leave balances absent from the Leave tab) |
| Medium | G12, onboarding visual gap, unconfirmed profile sign-out, assignment UUIDs, overtime presented as an approval inbox |
| Low | Splash tagline size, More search empty state (already decent), payslip footer disclaimer |

Critical set, named:

1. Employees land on a profile instead of the workday.
2. More exposes the administrator product.
3. Attendance does not lead with today’s status and a single likely punch.
4. The face-enrollment placeholder outranks punching when face punching is not in play.
5. Leave balances are disconnected from the leave task. Counted as high, not critical, because the balances screen works once found. The critical attendance and navigation issues are the five if balances are kept high. **Critical: 4. High: 12.**

Precise count used by the summary:

- Critical: 4 (no home, admin More, punch hierarchy including missing today-status, face card outranking punch).
- High: 12 (G1, G2, G6, G7, G8, G9, G10, G11, G13, G15, balances not on Leave, assignment ids unreadable).

### 7. Functionality that must not change

- Permission branches in §5 of the inventory.
- Punch idempotency and “outcome unknown” copy.
- Face frames cleared after the attempt. ML Kit stays a pose gate, not a liveness decision.
- Geofence DISABLED / OPTIONAL / REQUIRED behaviour.
- Company-timezone formatting.
- Leave date validation, half-day rule, cancel rules, `If-Match`.
- Regularization body shape and timezone conversion.
- Payslip PDF share and print.
- Public onboarding section order and submit.
- Company read-only banner when status is pending or suspended.
- Server error messages shown as returned (`describeApiError`).

### 8. Uncertainties

- Display names for branch, department, designation, and manager are not on the employee overview payload. The assignment payload stores ids. Whether list-choice endpoints return those names to an EMPLOYEE caller was not verified. The redesign says: show a name only if a field or an already-authorized choice list returns one; otherwise show nothing rather than a UUID, and record the gap. Do not add an API.
- `GET /overtime` is permitted with `ATTENDANCE.VIEW`. Whether SELF scope returns only the caller’s rows when `employee_id` is omitted was not re-tested here. The mobile app already sends `employee_id` in the Mine view. Keep that filter.
- iOS permission strings were not re-verified in this audit. Camera denial copy already exists in the face flows.
- Spec-form keyboard avoidance was not exercised on a device in this pass.

---

<a id="design-system"></a>

## Krewoxa employee mobile design system

Audit date: 2026-10-30. This is the visual contract for the employee surfaces in `apps/mobile`. It does not replace `docs/design/01_Design_System.md`, which is written for the dense HR desktop product. Employee mobile is the second posture that document already calls for: sparse, one primary action, opened briefly.

Implement these tokens in new employee widgets first (`lib/core/theme/` plus `lib/core/widgets/employee/`). Do not silently restyle `AppCard` for administrator resource screens in the same pass. Shared widgets may gain an employee variant; they should not change density for HR lists until that work is scheduled.

### 1. Direction

The employee app should feel like a calm operations tool with a Krewoxa identity: deep navy ink, one blue for the action the employee is here to take, paper-white sheets, and hairline structure. It should not feel like a stack of identical rounded cards, a gradient marketing page, or a colourful analytics dashboard.

Use the colours already in the product:

- Navy ink `#102A43` is `AppBrand.navy` (landing page and splash).
- Action blue `#004AC6` is the current light `ColorScheme.primary`.
- Status hues stay the existing `AppStatusColors.light` values so attendance and leave mean the same thing as on the web.

Avoid:

- Gradient heroes. Today they appear on the profile header, attendance-day hero, and payslip net-pay block. Replace them with a flat surface and a 3px navy rule or a single status colour.
- A card wrapper around every section. Use open sections separated by 24px and a hairline, and reserve a bordered surface for a tappable row or a true summary.
- Decorative icon badges (tinted circle + icon) on every row. `IconBadge` is the main reason screens look generated from one template.
- Dark theme as the default. `HrmsApp` currently follows the device (`ThemeMode.system`). Employee shell uses light only. Keep `AppTheme.dark` in the codebase; do not delete it. Do not add a theme picker in this programme (none exists today).
- Extra motion. Keep the existing page transition. No staggered card entrances.

### 2. Colour

#### 2.1 Brand and ink

| Token | Hex | Use |
|---|---|---|
| `ink` | `#102A43` | Titles, primary text, navy rule, splash background. |
| `inkSecondary` | `#52606D` | Supporting text, timestamps, section labels. |
| `inkTertiary` | `#7B8794` | Hints, empty-field values, disabled icons. |
| `action` | `#004AC6` | The single primary button, selected tab, text links, focus ring. |
| `actionPressed` | `#003A9E` | Pressed primary. |
| `actionSubtle` | `#E8F0FE` | Selected chip, current-day cell, focus wash. Not a large background. |

`onAction` is `#FFFFFF`.

#### 2.2 Surfaces

| Token | Hex | Use |
|---|---|---|
| `canvas` | `#F4F6F8` | Scaffold behind content. Replaces `surfaceContainerLow` (`#F3F3FE`), which reads as a lavender Material tint. |
| `sheet` | `#FFFFFF` | App bars, bottom navigation, tappable rows, forms. |
| `inset` | `#F7F8FA` | Read-only fact groups inside a section (address block, payslip facts). |
| `line` | `#E4E7EB` | Row dividers, input borders, bottom-nav top border. |
| `lineStrong` | `#CBD2D9` | Disabled outlines. |

No drop shadow on cards. The sticky punch bar may use a 1px `line` along its top edge only.

#### 2.3 Status

Keep `AppStatusColors.light`. Pair every status colour with a word and, on the month grid, a shape. Colour alone is not the status.

| Meaning | Hex | Subtle | Glyph |
|---|---|---|---|
| Success, present, approved | `#16A34A` | `#F0FDF4` | Check |
| Warning, pending, half day, late | `#F59E0B` | `#FFFBEB` | Clock |
| Danger, absent, rejected | `#EF4444` | `#FEE2E2` | Cross |
| Info, on duty | `#0EA5E9` | `#E0F2FE` | Briefcase |
| On leave | `#8B5CF6` | `#F5F3FF` | Calendar-off |
| Holiday, weekly off | `#64748B` | `#F1F5F9` | Dot |
| Work from home | `#0D9488` | `#F0FDFA` | House |

Month cells today use `Colors.green`, `Colors.red`, `Colors.purple`, and similar. Replace those with this table. Map buckets the same way `attendance_month_card.dart` already maps them: PRESENT, REMOTE, ON_DUTY, HALF_DAY, ABSENT, LEAVE, INCOMPLETE, CONFIG_ERROR, HOLIDAY, WEEKLY_OFF.

Do not use raw `Colors.green` / `Colors.orange` / `Colors.red` for `RequestStatusChip`. Map status strings through `toneForStatus`.

#### 2.4 Company banner

Pending approval and suspended stay a full-width bar, not a card. Use warning subtle `#FFFBEB` with ink text `#102A43` and a warning icon. The current bar uses `tertiaryContainer` (`#BC4800` family), which looks like an error stripe. The meaning is “you can look, you cannot change.”

### 3. Typography

Family: Inter, already loaded. Enable tabular figures for times, day counts, and money (`FontFeature.tabularFigures()`).

The desktop design system uses 14px body because HR tables are dense. Employee mobile is not that surface. Use this scale. Do not add a second display family.

| Token | Size / line / weight | Use |
|---|---|---|
| `display` | 28 / 34 / 600 | One number per screen: hours worked, net pay, leave days left. |
| `title` | 22 / 28 / 600 | Screen title in the app bar when it is the employee’s name or “Today”. |
| `heading` | 18 / 24 / 600 | Section title (“This month”, “Balances”). |
| `body` | 16 / 22 / 400 | Paragraphs, input text, row title. |
| `bodyStrong` | 16 / 22 / 600 | Row title that is a name or a leave type. |
| `label` | 13 / 18 / 600 | Section eyebrow, field label, uppercase tracking 0.4. |
| `caption` | 13 / 18 / 400 | Secondary row text. Colour `inkSecondary`. |
| `micro` | 12 / 16 / 500 | Status chips, weekday letters. Never below 12. |

App bar title uses `heading` (18), not the current `headlineMedium` at 20 with weight 700 on every screen. The employee’s name is the title only on Profile.

Letter-spacing: titles `-0.2`. Labels `0.4`. Body `0`.

### 4. Spacing, radius, elevation

Spacing scale, in logical pixels: 4, 8, 12, 16, 20, 24, 32, 40.

| Use | Space |
|---|---|
| Screen horizontal padding | 16. Increase to 20 when width ≥ 390. |
| Between sections | 24 |
| Between a label and its value | 2 |
| Between stacked rows | 0, with a `line` divider inset 16 |
| Sticky action bar padding | 16, plus the safe-area bottom inset |

Radius:

| Token | Value | Use |
|---|---|---|
| `radiusControl` | 8 | Buttons, inputs, chips that are not pills. |
| `radiusSurface` | 10 | The rare bordered summary (today panel, payslip net block). |
| `radiusSheet` | 16 | Dialogs and the top of bottom sheets. |
| `radiusPill` | 999 | Status chips, filter chips. |

Current radii conflict: `AppRadii` documents 2–12, then sets input 12, card 16, dialogs 24, sheets 28. Employee UI uses the table above only.

Elevation: 0. Inputs are filled `#FFFFFF` with a 1px `line` border. Focused input: 1.5px `action`. Error: 1.5px `#EF4444`.

Minimum touch target: 44 × 44. Primary buttons are 48 tall and full width when they are the screen’s main action. Icon buttons keep a 44 hit area even if the glyph is 22.

### 5. Iconography

Material Symbols rounded, the set already imported as `Icons.*_rounded` / `*_outlined`.

Rules:

- Outlined glyph when idle, filled glyph when selected (already done on the bottom nav).
- Size 22 in rows, 24 in the bottom nav, 20 beside a chip.
- Colour `inkSecondary` unless the icon is the status itself.
- One metaphor per object: fingerprint for attendance, calendar for leave, person for profile, receipt for payslips. Do not use `beach_access` for leave; it reads as leisure, not an HR request. Use `event_available_outlined` for leave applications and `account_balance_wallet_outlined` only on the balance figure.
- Do not put an icon in a coloured circle unless the circle is the person’s initials.

Initials avatar: 40px in a list, 56px on the profile header. Circle, `actionSubtle` background, `action` text, weight 600. No white ring on a gradient.

### 6. Components

#### 6.1 EmployeeHeader

Not a second app bar. The system app bar stays: sheet background, no shadow, title left, back chevron when the route is pushed, no centred title.

On Home and Profile the first content block under the app bar is the identity line: “Good morning” is not used. Use the calendar date in the company zone plus the employee’s first name: “Friday, 30 Oct” as `label`, then the first name as `title`. No illustration.

#### 6.2 SectionHeader

Existing `SectionHeader` is a starting point. Employee version: `label` style, `inkSecondary`, no icon, 24px above, 8px below. A text button may sit on the trailing edge (“See month”, “Balances”).

#### 6.3 TodayStatusPanel

One bordered surface (`radiusSurface`, 1px `line`, sheet fill) at the top of Home and Attendance.

Contents, in order:

1. Status word from today’s `attendanceStatus`, using `StatusChip`. If today’s row does not exist yet, the word is “Not punched in”.
2. First in and last out as `display`-sized time on the left and a caption on the right, or a single “First in 09:12” line when there is no out punch.
3. Worked duration from `workedMinutes` via the existing `formatMinutes`. Do not recompute hours on the client.
4. Shift window only when `scheduled_start` and `scheduled_end` are present on today’s day payload. If they are absent, omit the row. Do not invent a shift name.
5. One sentence for face or location state, `caption` colour.

This panel is not wrapped in `IconBadge`.

#### 6.4 CheckInAction

The primary action is one button, not two equal buttons.

- If the latest punch direction known from today’s punches is missing or `OUT`, the button label is “Punch in”.
- If the latest direction is `IN`, the label is “Punch out”.
- The client does not decide the direction from the clock. It uses the attendance day’s `actualFirstIn` / `actualLastOut` and, when both exist, offers the explicit secondary action “Punch in again” only as a text button. The server accepts either direction; hiding a direction would be a behaviour change. So both directions remain available: the likely one is the filled button, the other is a text button under it labelled “Punch out instead” or “Punch in instead”.
- When `faceVerificationRequired` is true, both buttons start the existing face flow and the plain `punchMe` buttons are not shown. That rule stays.
- Busy label replaces the button text: “Checking location…”, “Preparing face check…”, “Verifying…”. Disable the button. Do not add a second progress card.

Sticky placement: bottom of the Attendance screen, above the navigation bar, sheet background, 16px padding, safe area. Home shows the same control only when the employee has `ATTENDANCE.PUNCH`.

#### 6.5 WorkDurationIndicator

Not a chart. A single line under the times: “6h 40m worked” in `bodyStrong`, tabular figures. If `workedMinutes` is null, show “Worked time appears after the day is calculated.” Do not sum punches on the device.

#### 6.6 LeaveBalanceStrip

Horizontal row of up to three leave types, then “All balances”. Each cell is not a card. It is a column: type name `caption`, balance `heading` tabular. Reserved balance as `micro` “2 reserved” when `reservedBalance != 0`. Data from the existing balance endpoint. If there are more than three types, show the three with the largest `balance` and a count. Do not drop types from the full balances screen.

#### 6.7 LeaveRequestItem

A row, not a card: date range as title, leave type name as caption, `StatusChip` trailing, chevron. Divider `line`. Minimum height 64.

#### 6.8 StatusChip

Use the existing `StatusChip` API (`label`, `tone`, optional `dot`). Height 24, pill, `micro` text, subtle background, foreground text. Always include the word. On the month grid, the dot or glyph is enough inside the cell and the word is in the legend.

#### 6.9 Buttons

| Variant | Spec |
|---|---|
| Primary | Filled `action`, white label `bodyStrong`, height 48, radius 8, full width in sticky bars and forms. |
| Secondary | Outlined, 1px `lineStrong`, ink label, height 48, radius 8. |
| Text | `action` label, no fill. Use for the alternate punch and “Cancel”. |
| Destructive | Text or outlined `#EF4444`. Confirm in a dialog before logout, cancel leave, or cancel regularization. |

Do not use an extended FAB for “Apply for leave” or “Regularization request”. Put the primary button in the app bar as a text button “Apply”, and repeat it in the empty state.

#### 6.10 Inputs

Height 48, radius 8, fill `sheet`, border `line`, label above the field (not floating), `label` style. Error text `caption` in `#EF4444` under the field. `FormSpec` screens should pick up this decoration from the employee theme so leave and regularization forms match without a second form engine.

#### 6.11 List row

`sheet` background, padding 16 vertical 12, title `bodyStrong`, subtitle `caption`, trailing status or value, chevron `inkTertiary`. No shadow, no per-row radius. The list sits on `canvas` as one `sheet` group with `radiusSurface` on the group, not on each row.

#### 6.12 EmptyState

Existing `StateMessage` is the right structure. Employee visual: no oversized icon circle. A 28px `inkTertiary` icon, `heading` title, `caption` message, one primary or text button. Vertical padding 32.

Copy stays specific. Do not replace server messages.

#### 6.13 Loading

Prefer the existing `ListSkeleton` for lists. For the today panel, a skeleton of two lines and a button-shaped block. Do not use a centred spinner for the whole attendance screen while the punch button waits on the 14-day list. The punch card already loads independently; keep that.

#### 6.14 Dialogs and sheets

Dialog: `sheet` fill, radius 16, title `heading`, body `body`, actions right-aligned. Destructive confirm is the right-hand button in `#EF4444` text, not a filled red button, except cancel-leave which already uses a filled error button. Keep that filled error button for irreversible leave cancellation so it stays visually heavier than “Keep it”.

Sheets: top radius 16, drag handle, `canvas` body. Use a sheet for date filters on Leave and Regularizations instead of stacking dropdowns above the list.

### 7. Navigation

Specified in the redesign document. Visual rules:

- Bottom bar height 64 plus the safe-area inset. Background `sheet`. Top border 1px `line`. No shadow blur.
- Four destinations for an employee with a record: Home, Attendance, Leave, Profile.
- Selected: `action` icon and label weight 600. Unselected: `inkSecondary`, weight 500.
- Labels always visible.
- More is not a fifth tab. It is a text button “More” on Home only, opening a short employee menu. Administrator destinations stay on their routes for other roles.

### 8. Writing

- Sentence case for buttons and titles. “Punch in”, not “PUNCH IN”.
- Use the company timezone for every clock (`formatClockTime`, `formatDateTime`, `businessToday`). Never the device zone. This rule already exists and stays.
- Status labels go through `humanize` or the existing status maps. Do not show raw `FIRST_HALF` or `MISSING_PUNCH`.
- Money uses `formatInr`. Leave days use the API decimal string as today (`balance` is already a display string). Do not reformat in a way that changes precision (`leave_decimal_parsing_test.dart`).
- Empty values: omit the row when the value is null. Do not print a grid of “Not set”. The profile overview currently does that for every field.

### 9. Accessibility

- Contrast: `ink` on `sheet` and `action` on white both clear WCAG AA for normal text. `inkTertiary` is for hints only, not for essential status.
- Status is text plus colour.
- TalkBack labels on punch buttons include the direction: “Punch in”, “Punch out”.
- Month cells expose “15 October, Present” as the semantics label.
- Respect the device text scale up to 1.4. The today panel stacks the two times vertically when the scaled width overflows; do not clip the punch button.
- Focus order follows visual order. Sticky punch bar is last in the scroll, not an overlay that covers the last list row: add bottom padding equal to the bar height.

### 10. What stays in code

| Existing | Decision |
|---|---|
| `AppBrand.navy`, `AppBrand.blue` | Keep. Employee tokens alias navy and `#004AC6`. |
| `AppStatusColors` | Keep the light set. Employee theme reads it. |
| `AppRadii` | Leave for administrator screens. Employee widgets use the radius tokens in §4. |
| `AppCard`, `IconBadge`, `HeroCard` | Keep for HR screens. Employee screens stop using `HeroCard` and stop using `IconBadge` on every row. |
| Inter | Keep. |
| Material 3 | Keep. Employee `ThemeData` is a light `ColorScheme` built from §2, with component themes matching §6. |

---

<a id="redesign-specification"></a>

## Employee mobile redesign specification

Audit date: 2026-10-30. This is the build contract for employee surfaces in `apps/mobile`. Tokens are defined in [EMPLOYEE_MOBILE_DESIGN_SYSTEM.md](#design-system). File paths and APIs are in [EMPLOYEE_MOBILE_SCREEN_INVENTORY.md](#screen-inventory).

Rules for every screen:

- Do not add endpoints, fields, or actions that are not already implemented.
- Do not remove a permission-gated action. If this spec describes the EMPLOYEE role, the same widget must still show the administrator branch when the permission is present.
- Clock times use the company timezone helpers in `lib/core/time.dart`.
- Light theme only (`ThemeMode.light`) for the app until a user setting exists. Do not add that setting.
- Copy in quotation marks is the copy to ship. Everything else is layout.

Proposed navigation (does not delete routes):

| Tab | Employee | User with `DASHBOARD.COMPANY.VIEW` |
|---|---|---|
| Home | New `EmployeeHomeScreen` | Existing `DashboardScreen`, unchanged by this programme |
| Attendance | `AttendanceSelfScreen` | Same |
| Leave | `LeaveApplicationsScreen` | Same, including Team when permitted |
| Profile | `ProfileScreen` | Same |

`landingPathFor`: dashboard permission → `/app/dashboard`; else if `employeeId` → `/app/home`; else `/app/dashboard` (current no-access case for an account with no employee row).

Employee More, opened from Home only: Leave balances, Attendance corrections, Overtime, Payslips, Sign out. Any other current hub row is visible only when the signed-in user holds the permission that screen already checks, or, where the screen does not check, the permission listed in inventory §6. Searching must not reveal hidden rows.

---

### Screen: Splash

**1. Screen objective.** Show the Krewoxa mark while the session resolves. The employee does nothing here.

**2. Overall layout.** Full-screen `ink` `#102A43`. Content centred as a column: mark 72px, 16px gap, white wordmark height 26, 8px gap, tagline, 28px gap, 26px white spinner. Keep the existing assets `assets/brand/krewoxa-mark.png` and `krewoxa-wordmark-white.png`.

**3. Header.** None. Status bar light icons on navy (`SystemUiOverlayStyle.light`).

**4. Main content.** Tagline “Your people, organized.” in white at 70% opacity, 14px. No card, no progress text.

**5. Primary actions.** None.

**6. Secondary actions.** None.

**7. Navigation.** Router sends the user to `/login` or `landingPathFor` when auth leaves `loading`. Do not add a timeout UI.

**8. Interaction.** None.

**9. UI states.** Only the loading state exists. A failed `/auth/me` is handled by the auth controller, which lands on login. Do not add an error layout on the splash itself.

**10. Responsive.** Stay centred from 320px to tablet width. On width ≥ 600, cap the column at 440 and keep the navy full bleed.

**11. Visual.** Background `ink`. No gradient animation. Spinner stroke 2.5, white.

**12. Preserve.** Redirect rules in `app_router.dart`, including public paths that skip the redirect.

**13. Acceptance.** Cold start with a valid session opens Home (employee) or the company dashboard (admin) without a flash of the profile tab. Cold start without a session opens login. The mark and wordmark remain the current assets.

---

### Screen: Login

**1. Screen objective.** Sign in with work email and password.

**2. Overall layout.** Keep `AuthScaffold`: navy top band with mark and wordmark, white sheet with top radius 16 (was 28). Sheet padding 24. Title, 6px, description, 24px, fields, 16px, error, 16px, button, footer.

**3. Header.** Inside the navy band, the same images as splash at a smaller size (mark 40, wordmark 22), top safe area plus 24px. No back button.

**4. Main content.** Title “Sign in”. Description “Use your work email.” Fields, labels above: Email, Password. Password has a show/hide icon button with a 44px target. Unverified-email block, when `EMAIL_NOT_VERIFIED`: inset surface, caption “Verify your email before signing in.”, text button “Resend verification email”, then “Email sent.” after success.

**5. Primary actions.** Full-width primary “Sign in”. Disabled and labelled “Signing in…” while the request runs.

**6. Secondary actions.** Text button “Forgot password?”. Footer line “Setting up a company? Create an account” with “Create an account” as the link to `/register`. Register stays a company signup. Do not rename it to look like employee registration.

**7. Navigation.** Success → `landingPathFor`. Forgot password → `/forgot-password`. Already authenticated users never see this route.

**8. Interaction.** Submit on the keyboard done key. Inline errors replace the previous error. Drag dismisses the keyboard, already implemented.

**9. UI states.** Initial empty. Validation: “Email is required.”, “Enter a valid email address.”, “Password is required.” API: “Invalid email or password.” on 401, lock copy on 423, “Too many attempts. Please wait a moment and try again.” on 429, otherwise `error.message`. Disabled while submitting. No permission state.

**10. Responsive.** Sheet content max width 440, already in the scaffold. On height under 640 the band shrinks to 120px plus safe area so the button stays on screen without covering fields. Sheet scrolls.

**11. Visual.** Navy band `ink`. Sheet `sheet`. Inputs per design system §6.10. Primary button `action`. Error text `#EF4444` caption. No extra illustration.

**12. Preserve.** `login()` arguments, resend verification call, and the error codes above. Do not log the password.

**13. Acceptance.** Wrong password shows the 401 string and does not navigate. Unverified email shows resend and does not navigate. Valid employee session opens `/app/home`. Valid admin session opens `/app/dashboard`. Widget tests that pump `LoginScreen` still find Email, Password, and Sign in.

---

### Screen: Forgot password

**1. Screen objective.** Ask for a reset email.

**2. Overall layout.** `AuthScaffold`. Back chevron at the top of the sheet, 44px, aligned start.

**3. Header.** Title “Reset password”. Description “We will email a link if an account exists for that address.”

**4. Main content.** One email field.

**5. Primary actions.** “Send link”.

**6. Secondary actions.** “Back to sign in”.

**7. Navigation.** Back returns to `/login`. Success stays on this screen and replaces the form with a confirmation.

**8. Interaction.** Same validation as login email.

**9. UI states.** Initial, invalid email, submitting, success: title “Check your email” and the address they typed, text button “Back to sign in”. Error uses the API message. Do not reveal whether the email is registered if the API does not.

**10. Responsive.** Same sheet rules as login.

**11. Visual.** Same auth sheet. Success uses `StateMessage` without a coloured circle: icon `mail_outlined` in `inkSecondary`.

**12. Preserve.** The repository method and the success behaviour that does not depend on the account existing.

**13. Acceptance.** Invalid email does not call the API. A successful response shows the confirmation and no longer shows the field.

---

### Screen: Reset password

**1. Screen objective.** Set a new password from the email token.

**2. Overall layout.** `AuthScaffold` with back omitted (the user arrived from outside). Title “Choose a new password”.

**3. Header.** None beyond the scaffold band.

**4. Main content.** New password, Confirm password. Hint under the first field only if `validation.dart` already enforces a rule; do not invent a new policy. Show the existing validator message.

**5. Primary actions.** “Update password”.

**6. Secondary actions.** None until success, then “Sign in”.

**7. Navigation.** Public route, even if a session exists. Success → button to `/login`. Do not auto-login unless the current repository already returns a session. It does not; do not add that.

**8. Interaction.** Confirm must match. Submit disabled while the request runs.

**9. UI states.** Initial, mismatch “Passwords do not match.”, submitting, API error (expired token uses the server message), success confirmation.

**10. Responsive.** Same as login.

**11. Visual.** Same auth sheet.

**12. Preserve.** Token path parameter. Password rules already in the client validator.

**13. Acceptance.** Mismatched passwords do not call the API. An expired token shows the server message and stays on the screen.

---

### Screen: Verify email

**1. Screen objective.** Consume the verification token and tell the employee what happened.

**2. Overall layout.** `AuthScaffold` without a form. Centred result in the sheet.

**3. Header.** Title “Email verification” while the call is in flight.

**4. Main content.** Loading: spinner and “Verifying…”. Success: “Email verified” and “You can sign in.” Failure: server message.

**5. Primary actions.** “Sign in” on both success and failure.

**6. Secondary actions.** None.

**7. Navigation.** Public. “Sign in” → `/login`.

**8. Interaction.** The request starts in `initState`, as it does now. The button does nothing else.

**9. UI states.** Loading, success, error. No empty state.

**10. Responsive.** Result block max width 440, centred.

**11. Visual.** Success icon `check_circle_outline` in success `#16A34A`, 28px, no circle background. Error icon `error_outline` in danger.

**12. Preserve.** The token request and the fact that a signed-in user can still open the link.

**13. Acceptance.** A valid token shows success. An invalid token shows the API message and Sign in.

---

### Screen: Accept invite

**1. Screen objective.** An invited employee sets their name and password and enters the app.

**2. Overall layout.** `AuthScaffold`. Title “Accept invitation”. Description from the API if the screen already shows the invited email or company; do not add fields the payload does not contain. Read `accept_invite_screen.dart` and keep every field it submits.

**3. Header.** Scaffold band only.

**4. Main content.** The current fields (name, password, confirm — match the file, do not drop a field). If the screen shows the invite email as read-only text, keep it above the fields as `caption`.

**5. Primary actions.** The existing submit label, restyled as the primary button.

**6. Secondary actions.** None.

**7. Navigation.** Success → `landingPathFor`, which for an employee is `/app/home`.

**8. Interaction.** Same validation the screen already runs.

**9. UI states.** Loading the invite, invalid or expired token (`StateMessage` plus no form), form, submitting, API error under the button.

**10. Responsive.** Sheet scrolls when the keyboard is open. The button remains reachable.

**11. Visual.** Auth sheet. Token-error state uses the same plain `StateMessage` as verify-email failure.

**12. Preserve.** Token handling, submitted JSON keys, and navigation after success.

**13. Acceptance.** An expired token does not show the form. A valid submit with an employee profile opens Home. Existing accept-invite tests still pass.

---

### Screen: Public onboarding

**1. Screen objective.** A candidate completes the sections HR asked for and submits the case. This is not the signed-in profile.

**2. Overall layout.** Light scaffold, not the navy auth band (the task is long). App bar, a 4px progress track, a step caption, scrolling step body, a bottom bar with Back and the primary button.

**3. Header.** App bar title is the step name: “Welcome”, then each `onboardingSections` label, “Documents”, “Review”. Back chevron goes to the previous step, not off the flow, except on step 0 where it is hidden. Progress track `action` on `line`, value `step / lastStep`. Caption “Step n of m” in `caption`, 16px horizontal padding.

**4. Main content.** Step 0: short welcome using the case identity the repository already returns (candidate name or company if present). Do not write a new marketing paragraph if those fields are absent; use “Complete your details for HR.” Steps 1..n: the existing section fields, one column, labels above. Repeatable sections keep add and remove. Documents: existing type, filename, size, status, rejection reason. Review: a row per section with the existing summary line, chevron returns to that step. Empty repeatable section copy stays: “Nothing added — you can skip this step if it does not apply.”

**5. Primary actions.** Bottom bar, safe area: step 0 “Get started”; middle “Save & continue”; last “Submit”. While saving, the label is “Saving…” or “Submitting…” and both buttons disable.

**6. Secondary actions.** “Back” as a secondary button, hidden on step 0. On documents, the existing upload action stays.

**7. Navigation.** Public `/onboarding/:token`. No bottom nav. Terminal screens replace the wizard.

**8. Interaction.** Save validates the current section before advancing. Review rows jump back. Submit is only on the last step.

**9. UI states.** Loading the case: skeleton. Bad link: existing terminal “Link not available”. Already activated: existing terminal copy. Per-step validation errors under fields. Upload failure uses the API message. Success terminal after submit, with the copy the screen already uses.

**10. Responsive.** Bottom bar stacks only if text scale exceeds 1.3; otherwise Back (flex 1) and primary (flex 2) in a row with 12px gap. Horizontal padding 16.

**11. Visual.** Canvas background. Fields on a sheet group. Progress is the only colour bar. No step illustrations.

**12. Preserve.** Section order, PATCH-on-continue, document upload, submit, and terminal conditions in `public_onboarding_screen.dart`. Tests in `public_onboarding_screen_test.dart` and `onboarding_form_spec_test.dart`.

**13. Acceptance.** A candidate can move back without losing saved sections. Submit still calls the same endpoint. A bad token never shows fields. The wizard does not show the employee bottom nav.

---

### Screen: App shell

**1. Screen objective.** Move between Home, Attendance, Leave, and Profile without losing tab state.

**2. Overall layout.** Column: optional company banner, expanded `navigationShell`, bottom bar.

**3. Header.** None at the shell. Each tab owns its app bar.

**4. Main content.** The indexed stack. Employee branch 0 builds `EmployeeHomeScreen`. Admin branch 0 builds `DashboardScreen`.

**5. Primary actions.** The tab the employee is on.

**6. Secondary actions.** None on the bar.

**7. Navigation.** `goBranch` as today, with haptic selection click. Re-tapping the current tab resets that branch (`initialLocation: true`), keep this.

**8. Interaction.** Four destinations for an employee with `employeeId` and without `DASHBOARD.COMPANY.VIEW`: Home `home_outlined` / `home_rounded`, Attendance `fingerprint_rounded`, Leave `event_available_outlined` / `event_available_rounded`, Profile `person_outline_rounded` / `person_rounded`. A user who currently sees the company dashboard keeps the label Home on that tab and the existing dashboard icon. A user with neither an employee id nor the dashboard permission keeps today’s single explanatory dashboard tab.

**9. UI states.** Banner states are the next screen. Tabs do not have a loading state of their own.

**10. Responsive.** Labels always shown. At text scale 1.4, label size may drop to 11 but the bar grows rather than clipping. Height 64 plus safe-area inset.

**11. Visual.** Sheet background, 1px `line` on top, no shadow. Selected `action`, unselected `inkSecondary`.

**12. Preserve.** `StatefulShellRoute` state per branch. Company banner placement above the shell body. `shell_tabs_test.dart` expectations updated only for the new employee Home visibility.

**13. Acceptance.** An employee sees four tabs and lands on Home. An admin with dashboard permission still sees the company dashboard on Home and does not see `EmployeeHomeScreen`. Switching tabs does not reload the other tab’s form state.

---

### Screen: Company read-only banner

**1. Screen objective.** Tell every role that changes are blocked while the company is pending approval or suspended.

**2. Overall layout.** Full width above the shell body, under the status bar (`SafeArea` bottom false, as now).

**3. Header.** Not an app bar. One row: 18px icon, 10px gap, text.

**4. Main content.** Pending: icon `hourglass_top_rounded`, text “Your company is awaiting approval. You can view data, but changes are disabled.” Suspended: icon `lock_outline_rounded`, text “Your company is suspended. You can view data, but changes are disabled.”

**5. Primary actions.** None.

**6. Secondary actions.** None.

**7. Navigation.** Not tappable.

**8. Interaction.** None.

**9. UI states.** Hidden for every other company status.

**10. Responsive.** Text wraps. Padding 16 horizontal, 10 vertical.

**11. Visual.** Background warning subtle `#FFFBEB`. Text `ink` 13/18 weight 500. Icon warning `#F59E0B`. Not `tertiaryContainer`.

**12. Preserve.** The status strings and the fact that the API rejects writes anyway. `company_read_only_banner_test.dart`.

**13. Acceptance.** Pending and suspended show the matching sentence. Active companies show no bar.

---

### Screen: Employee Home

This screen does not exist. Build it as `lib/features/home/presentation/employee_home_screen.dart`. It composes existing repositories. It is not a reskin of `DashboardScreen`.

**1. Screen objective.** Show the workday and the next employee action: punch, a pending request, leave balance, or the latest payslip.

**2. Overall layout.** App bar, then a scroll view on `canvas`, bottom padding 24. Order: identity line, today panel, punch actions, leave strip, pending corrections, recent leave, latest payslip. Pull to refresh reloads all of those calls.

**3. Header.** App bar title “Home”. No back. Trailing text button “More” → `/app/more`. Do not put the grid icon here.

**4. Main content.**

1. Identity. `label`: weekday and date in the company zone, for example “Friday, 30 Oct”. `title`: first name from the employee record, falling back to the user profile name, then “there” only if both are empty. `caption`: employee code. No gradient, no avatar on this screen (the avatar is on Profile).
2. `TodayStatusPanel` for the attendance day whose `attendanceDate` equals `businessToday(zone)`. If the list call has not returned that date, status text is “Not punched in” and times are omitted.
3. `CheckInAction` when the user has `ATTENDANCE.PUNCH` and an `employeeId`. Same code path as the attendance screen (`_punch` / face card). Do not duplicate idempotency logic; extract the existing methods and call them.
4. `LeaveBalanceStrip` from `listLeaveBalances`. Trailing “All balances” pushes `/app/leave-balances`.
5. Section “Needs attention” only if there is at least one own regularization in `SUBMITTED` or one own leave application in `SUBMITTED` in the loaded page. Each is a `LeaveRequestItem`-style row. If there are none, omit the section. Do not show an empty “you’re all caught up” card.
6. Section “Leave” with at most three latest applications and “See all” selecting the Leave tab. Omit if the list is empty.
7. Section “Payslip” with one row: month, net pay, chevron, only if `listMyPayslips` returns a row. Tap opens `PayslipScreen` with `getMyPayslip`.

Do not add holidays, announcements, tasks, or team counts.

**5. Primary actions.** The punch button inside the today panel’s sticky area on this screen is inline, not stuck to the bottom (the bottom is the tab bar). Full width, 16px below the panel.

**6. Secondary actions.** “More”, “All balances”, “See all”, alternate punch as a text button.

**7. Navigation.** Tab root. More pushes `/app/more`. Balances, leave detail, regularization detail, and payslip push existing screens. “See all” uses `goBranch` to Leave.

**8. Interaction.** Punch uses the attendance flow including location dialogs and face capture. Rows open the existing detail screens. Refresh reloads.

**9. UI states.** Initial: skeletons for the panel, the strip, and three rows. Partial failure: if attendance fails, the panel shows the attendance error and a “Try again” text button, and leave can still render. If the user has no `employeeId`: the existing “No employee record” `StateMessage` and no punch button. Empty attendance and empty leave simply omit optional sections. No permission-denied state beyond the no-employee message; these calls are in the EMPLOYEE grant set.

**10. Responsive.** Below 360px, the balance strip scrolls horizontally. The today panel stacks the two times in a column when they do not fit. Text scale 1.4 does not clip the punch button.

**11. Visual.** Canvas. Today panel is the only bordered surface. Sections use `SectionHeader`. No `IconBadge`, no gradient.

**12. Preserve.** All calls are read-only except punch, which must keep idempotency, geofence handling, and face-required behaviour. Company timezone. Do not call dashboard company endpoints.

**13. Acceptance.** Employee login opens this screen. Today’s status matches the attendance day API for the company-local date. Punch in shows the same snackbar as the attendance tab and both screens show the new punch after refresh. A user with `DASHBOARD.COMPANY.VIEW` never sees this widget on Home. No request is made to `/dashboard` or holiday-calendar routes from this screen.

---

### Screen: Attendance

**1. Screen objective.** Punch, see today’s result, and review the month and the last 14 days.

**2. Overall layout.** App bar. Scroll view: today panel, face status (conditional), month section, 14-day section. The punch control is a sticky bar at the bottom of the body, above the tab bar. List padding bottom equals the bar height so the last day is not covered.

**3. Header.** Title “Attendance”. No back (`automaticallyImplyLeading: false`). No More icon. Refresh is pull-to-refresh, not an app-bar button.

**4. Main content.**

1. `TodayStatusPanel` bound to today’s row inside `_days` if that date is in the 14-day window; also read from the month card’s map when the month shown is the current month. Prefer the 14-day payload so one refresh updates the panel.
2. Face block, under the panel:
   - Required, enrolled, pending, rejected, or window open: keep the current sentences from `FacePunchCard` (they are operational, not decoration). Present them as a flat inset, not an `AppCard` with an icon badge. Buttons for face punch move into the sticky bar.
   - Not set up and not required: one caption line “Face attendance is not set up.” No button. Do not lead the screen with it.
3. Section “This month” and `AttendanceMonthCard`, restyled (below).
4. Section “Last 14 days”. Rows are flat list rows: the existing date block (month abbreviation and day number) stays, because it is the one distinctive element. Title is the status word. Caption is the existing time range and worked minutes. Trailing chevron. Grouped in one sheet. Empty: “No attendance yet” / “Your punches will show up here.”

Month grid: Monday-first labels “Mo Tu We Th Fr Sa Su” so the two T and two S days are distinct. Cell 40px minimum, radius 8. Background is the status subtle colour. A 10px glyph, not only a tint: check, clock, cross, calendar, dot, house, matching the design-system table. Today’s date has a 1.5px `action` ring. Days with no record are plain numerals in `inkTertiary` and are not tappable. Under the grid, a wrapping legend of only the buckets present that month, word plus glyph. Summary line remains “Present n · Absent n · Leave n” using the same bucket rules as now (`attendanceBucketOf`). Month title centred, chevrons 44px.

**5. Primary actions.** Sticky `CheckInAction`. Face-required: the filled button starts the existing face punch for the likely direction and the text button starts the other. Labels “Face punch in” / “Face punch out” so the camera step is expected. Not face-required: “Punch in” / “Punch out”.

**6. Secondary actions.** Month previous and next. Day tap. No calculate-today button (that stays on the HR attendance panel).

**7. Navigation.** Tab root. Day push → attendance day detail. Face window → enrollment. Face punch → liveness route.

**8. Interaction.** Punch flow is unchanged: location plan, idempotency key, geofence dialog, snackbar “Punched in.” / “Punched out.” or the face match snackbar, then `_load`. Month change loads that month only. Pull to refresh reloads the 14-day list, face status, and the visible month.

**9. UI states.** No employee record: current warning message, no punch bar. History loading: skeleton rows, punch bar still active. History error: `StateMessage` with “Try again”, punch bar still active. Empty history: the empty copy above. Face loading: the caption “Loading…” in the face slot, punch bar disabled until status returns so a plain punch is not offered and then rejected. Punch busy: button shows the phase sentence and disables. Geofence and camera failures use the existing dialogs and snackbars.

**10. Responsive.** Sticky bar respects the bottom safe area. On width under 340, the alternate punch is a full-width text button under the primary, not beside it. Month cells wrap to 7 columns without horizontal scroll.

**11. Visual.** Canvas. Today panel bordered. Day list is one sheet. Calendar is one sheet. Status colours from `AppStatusColors`, not `Colors.green`.

**12. Preserve.** `punchMe` and `facePunchMe` payloads, idempotency, geofence policy modes, face-required hiding of plain punch, company timezone window (`businessDayOffset` −13 through today), sort descending, snackbar copy, and `attendance_self_mandatory_face_test.dart`.

**13. Acceptance.** With face not required, the first primary button is visible without scrolling. With face required, plain punch buttons are absent. A successful punch refreshes today’s status. Month colours match the bucket. HR-only actions do not appear. Existing punch and face tests pass.

---

### Screen: Face enrollment

**1. Screen objective.** Capture five poses inside an HR-opened window and submit them for approval.

**2. Overall layout.** Full screen, four stages already in the file: consent, capturing, review, submitting. Keep that order.

**3. Header.** App bar “Set up face attendance” on consent and review. On the camera stage, a transparent bar over the preview with a close button. Close asks for confirmation only if at least one pose is stored: “Leave setup? Photos already taken will be discarded.”

**4. Main content.** Consent: the existing explanation and a checkbox the user must tick. Camera: preview, current pose name, the existing hint from `FacePoseTracker`. Review: the five thumbnails in pose order with retake per pose if the screen already supports retake; if it does not, do not add retake. Submitting: “Submitting…” and a linear progress indicator.

**5. Primary actions.** Consent “Continue” disabled until the box is checked. Review “Submit”.

**6. Secondary actions.** Close. Back from review to camera only if already implemented.

**7. Navigation.** Pushed from attendance or home. Pop `true` after a successful submit so the card can snackbar “Face submitted. HR will review it before face punching is switched on.”

**8. Interaction.** Do not change pose order, auto-capture rules, or image encoding.

**9. UI states.** Camera permission denied: the existing settings sentence. Camera start failure: existing message. Submit error: API message, stay on review. Loading cameras: the capturing stage with “Starting camera…”.

**10. Responsive.** Preview uses the full width. Controls sit in the bottom safe area on a `sheet` scrim so they remain visible on short phones.

**11. Visual.** Camera stage is edge-to-edge. Consent and review use the employee form style. No decorative face illustration.

**12. Preserve.** Consent flag sent to the API, five-pose contract, front camera preference, resolution, audio off, ML Kit options, and frame disposal. `face_pose_tracker_test.dart`.

**13. Acceptance.** Submit still sends the same photo map and `consentConfirmed: true`. Denying the camera shows the settings sentence and does not crash. Cancelling after a capture discards images and pops `false`.

---

### Screen: Face liveness capture

**1. Screen objective.** Record the frames for the server challenge. The phone does not decide liveness.

**2. Overall layout.** Full-screen dialog, camera preview, instruction line, close.

**3. Header.** Close only. Title is unnecessary over the preview.

**4. Main content.** The instruction string the screen already shows from the session. A thin progress indicator for frames captured versus frames required, using counts the session already exposes. If the session does not expose a count, omit the indicator rather than inventing one.

**5. Primary actions.** None. Capture is automatic, as now.

**6. Secondary actions.** Close → `FaceCaptureCancelled`.

**7. Navigation.** Pushed `fullscreenDialog` from the punch card. The card handles the outcome.

**8. Interaction.** Unchanged capture loop.

**9. UI states.** Permission denied, expired, failed, cancelled, frames ready. Messages stay in the punch card (`face_punch_card.dart`), not new copy here, except the on-preview hint.

**10. Responsive.** Instruction sits above the bottom safe area. Preview covers the screen.

**11. Visual.** Black preview, white instruction text, no card.

**12. Preserve.** Outcome types in `face_liveness_capture.dart`. Frames cleared by the punch card in `finally`. Server messages shown as-is.

**13. Acceptance.** Cancel returns `FaceCaptureCancelled` and does not call `facePunchMe`. A full capture still posts the session id and frames. `face_liveness_capture_test.dart` passes.

---

### Screen: Location and geofence dialogs

**1. Screen objective.** Explain a location failure and let the employee retry or cancel before a punch is sent.

**2. Overall layout.** Standard dialog, not a bottom sheet. Title, body, two actions.

**3. Header.** Dialog title from the existing helpers: keep current titles in `punch_location_flow.dart` and `showLocationProblemDialog` / `showGeofenceRejectedDialog`.

**4. Main content.** The existing message. Do not shorten server geofence text.

**5. Primary actions.** The existing retry or settings action.

**6. Secondary actions.** Cancel, which aborts the punch (`PunchLocationPlan.abort`).

**7. Navigation.** Modal over attendance or home. Dismiss returns to the punch button, idle.

**8. Interaction.** REQUIRED: no punch until a fix exists or the employee cancels. OPTIONAL: failure is sent as `locationError` and the punch proceeds. DISABLED: no dialog. Policy lookup failure: punch proceeds without location, as now.

**9. UI states.** Services off, permission denied, timeout, outside fence (`isGeofenceError`). Each keeps its current branch.

**10. Responsive.** Dialog max width 400, margin 24, so it does not touch screen edges on a 320px phone.

**11. Visual.** Employee dialog: radius 16, title `heading`, body `body`.

**12. Preserve.** `planPunchLocation`, one foreground fix, no background collection, idempotency when the server never answers. Tests `punch_location_flow_test.dart` and `location_capture_test.dart`.

**13. Acceptance.** REQUIRED plus a denied permission does not call `punchMe` until retry succeeds or the user cancels. OPTIONAL still calls `punchMe`. DISABLED never prompts.

---

### Screen: Attendance day

**1. Screen objective.** Read one calculated day: status, times, breaks, and the pay-related facts the API already returns.

**2. Overall layout.** App bar, scroll view, 16px padding. Order: status block, flag chips, schedule, actuals and breaks, overtime facts, leave overlay if any, audit collapsed.

**3. Header.** Title is the formatted date in the day’s zone, not the string “Attendance day”. Subtitle in the app bar is omitted; the zone label sits in the status block as `caption`. Back chevron.

**4. Main content.**

1. Status block on `sheet` with a 3px left border in the status colour. `StatusChip` for `attendanceStatus`. Two columns: “First in” and “Last out” using `formatClockTime`. Under them, worked minutes as `heading` if non-null.
2. Flag chips, same set as today (`is_late`, `is_early_out`, `is_overtime`, `is_regularized`, `is_pending_approval`, `worked_on_holiday`, `worked_on_weekly_off`, `missing_punch`, work-on-leave phrases, core hours, on duty, locked). Wrap, 6px gap.
3. Section “Schedule”: calendar day type, holiday name, scheduled start–end, scheduled minutes. Omit a row whose value is null or “—”.
4. Section “Actual”: first in and last out as datetimes, worked, unpaid break, paid break, excess break, late minutes, early departure minutes, classifications. Then one row per break: “09:30–09:45 · 15m · paid” using the existing format string.
5. Section “Overtime and pay”: the current overtime and fraction rows. Same omit-empty rule.
6. Leave overlay only when projections loaded. Keep the provenance sentence.
7. “Calculation details” is a collapsed expansion tile containing the audit rows (versions, calculated at, locked at). Default collapsed for everyone. HR still sees Recompute and Keep leave above the fold when permitted.

**5. Primary actions.** None for an employee.

**6. Secondary actions.** Recompute and Keep leave, same visibility as now (`attendanceRecompute`, not locked, keep-leave only when flagged and unresolved).

**7. Navigation.** Pushed from the 14-day list, the month grid, or the record attendance tab. Back pops.

**8. Interaction.** Pull to refresh calls `_load`. Keep-leave still requires a reason dialog.

**9. UI states.** Skeleton when there is no initial day. 404: “This attendance day was not found, or you don't have access to it.” Other errors: message plus Retry. Leave projections failing stay silent, as now.

**10. Responsive.** The two time columns stack under 340px. Chips wrap.

**11. Visual.** No `HeroCard`, no gradient. Left border carries the status colour. Sections are open, separated by 24px, not individual cards.

**12. Preserve.** `getAttendanceDay`, projection fetch, recompute, keep-leave reason, all flags, timezone of the day (`day.timezone`, not the device).

**13. Acceptance.** An employee does not see Recompute. An admin with the permission does. Worked time matches `formatMinutes`. Empty holiday row is hidden. Collapsed audit tile still contains the calculation version after expand.

---

### Screen: Leave applications

**1. Screen objective.** See own applications and start a new one. Reviewers additionally see Team.

**2. Overall layout.** App bar with “Apply”. Caption under the app bar for the active filter, default “All dates · All statuses”. List of rows. Filter sheet, not an always-open form.

**3. Header.** Title “Leave”. No back on the tab. Text button “Apply” when `canCreate` is true (same condition as the FAB today). Employee label “Apply”. On-behalf label “Apply on behalf”.

**4. Main content.** Optional segmented control Mine / Team only when `leaveApplicationApprove` or `leaveApplicationSubmitOnBehalf` is held. Then the list. Row: leave type name as title, “1 Apr – 3 Apr · 3 days” as caption (use the fields already on `LeaveApplication`), `StatusChip` from the existing status map. Chevron. Grouped sheet. The balance strip from Home is repeated here as the first content block, because this is where the employee decides to apply. It links to the balances screen. It is hidden for the Team segment so a manager is not shown their own strip while looking at someone else.

**5. Primary actions.** “Apply” in the app bar and, when the list is empty, a primary button in the empty state “Apply for leave”.

**6. Secondary actions.** “Filter” text button opening a sheet: From, To, Clear dates, status chips. Applying the sheet reloads, as the current controls do.

**7. Navigation.** Tab. Row pushes detail. Apply opens the form. Balances push `/app/leave-balances`.

**8. Interaction.** Changing Mine/Team or a filter calls `_load`. Load more stays at the bottom when `hasMore`. Pull to refresh.

**9. UI states.** Skeleton. Error “Couldn't load leave” plus Try again. Empty “No leave applications” / “Applications you submit will show up here.” plus the apply button when allowed. Submitting snackbar “Leave application submitted.” then reload.

**10. Responsive.** Segmented control is full width. Filter sheet scrolls. Rows are at least 64px tall.

**11. Visual.** No FAB. No date-shaped buttons eating the first screenful. Status chips use `StatusChip`, including Submitted as warning, Approved as success, Rejected as danger, Cancelled as neutral.

**12. Preserve.** List query (`employeeId` forced to self unless Team), pagination, status values, choice loading, and the on-behalf form flag. `leave_applications_test.dart`.

**13. Acceptance.** An employee sees no Team control and no on-behalf form. Apply submits the same body. Filters still change the query. The FAB is gone and Apply remains reachable in the empty state.

---

### Screen: Apply for leave

**1. Screen objective.** Submit one application for the signed-in employee.

**2. Overall layout.** Full-screen form, not a dialog, so the keyboard and the date pickers have room. App bar, scrolling fields, sticky submit.

**3. Header.** Title “Apply for leave”. Close or back discards. If any field is dirty, confirm “Discard this application?”.

**4. Main content.** Fields in `leaveApplicationSpec`, self mode, in this order: Leave type (choice), Start date, End date, Half day (select, hint “Only for a single-day application”), Reason (multiline, optional), Attachment reference (optional, hint unchanged), Expected delivery date (optional, hint “Maternity leave only”). Employee picker is absent unless `onBehalf` is true. Above the fields, a caption listing the employee’s balances that were already loaded: “Casual · 8.5 available”. If balances failed to load, omit the caption. Do not block submit on that failure. Do not compute eligibility on the client.

**5. Primary actions.** Sticky “Submit”. Disabled while submitting. Label “Submitting…”.

**6. Secondary actions.** None.

**7. Navigation.** Opened from Leave or, if Home later adds a shortcut, from Home. Success pops and the list snackbars.

**8. Interaction.** Date pickers. `extraValidate` still rejects end before start and a half day on a range. Keyboard done on the last field focuses submit rather than closing the screen.

**9. UI states.** Choices loading: skeleton fields. Choice error: message and Retry. Validation under the field. API error under the button, including overlap and balance errors from the server, unmodified.

**10. Responsive.** Sticky button plus safe area. Fields scroll above it. Horizontal padding 16.

**11. Visual.** Employee inputs. Required marker is the existing asterisk from `AuthFormField` / spec form. One column.

**12. Preserve.** Payload keys, idempotency key inside `submitLeaveApplication`, on-behalf `employee_id` only when that mode is on, half-day and date validation.

**13. Acceptance.** Self submit body has no `employee_id`. Half day on a multi-day range shows the existing error and does not POST. Server 422 shows `error.message`.

---

### Screen: Leave application detail

**1. Screen objective.** Understand one application and withdraw it when the rules allow.

**2. Overall layout.** App bar, scroll, optional bottom bar for cancel.

**3. Header.** Title is the leave type name once loaded, otherwise “Leave”. Back.

**4. Main content.** Status chip and date range as the first block (sheet, left border in the status colour). `heading` total days. Then sections, omitting empty values: Reason, Attachment reference, Expected delivery, Approval chain, Approval stage, Submitted at. If status is not `SUBMITTED`: Reviewed at, Reviewer comment, Rejection reason, Cancelled at, Cancellation reason. Then “Days” rows if `days` is non-empty, using the current per-day formatting. Then “History” lines from `actions`.

**5. Primary actions.** “Cancel application” in a bottom bar only when `canCancel` is already true. The button is destructive text, full width.

**6. Secondary actions.** Approve and Reject stay above the sections, in a row, only when `canReview` is true. Do not show them to the applicant.

**7. Navigation.** Pushed from the list. After cancel or review, stay on the screen and reload, as now.

**8. Interaction.** Cancel opens the confirm dialog. Pull to refresh.

**9. UI states.** Skeleton. 404 “Not found” with the current access sentence. Other errors with Retry. Busy disables the action buttons.

**10. Responsive.** Approve and Reject wrap onto two lines under 360px. Bottom bar adds safe area.

**11. Visual.** No gradient hero. Status border uses the chip tone.

**12. Preserve.** `isOwn`, `hasStarted` in the company zone, cancel-approved permission, reason-required when approved leave has started, `If-Match`, excess-as-lop if the review dialog already has it. Do not relax cancel rules.

**13. Acceptance.** An employee can cancel a `SUBMITTED` application. An employee cannot cancel an approved application on or after the start date. A manager who is not the applicant still sees Approve and Reject on a pending row. Rejection reason is visible when present.

---

### Screen: Cancel leave dialog

**1. Screen objective.** Confirm withdrawal and collect a reason when required.

**2. Overall layout.** Dialog.

**3. Header.** Title “Cancel this application?”.

**4. Main content.** Body is the existing sentence: approved → “The leave balance and attendance are reversed.” Otherwise “The application is withdrawn.” Reason field. Helper “Required — the leave has already started.” or “Optional”.

**5. Primary actions.** “Cancel application” in filled error, as today, because this reverses attendance when the leave was approved.

**6. Secondary actions.** “Keep it”.

**7. Navigation.** Stays on the detail. Success reloads the detail and snackbars via the existing path.

**8. Interaction.** Empty reason blocked only when `reasonRequired`.

**9. UI states.** Validation “A reason is required.” API error snackbar, dialog already closed only after a yes; on API failure the detail shows the toast and clears busy.

**10. Responsive.** Max width 400. Reason field is multiline, two lines.

**11. Visual.** Employee dialog chrome. Destructive button stays filled `#EF4444`.

**12. Preserve.** Reason payload and `If-Match`.

**13. Acceptance.** Optional reason can be blank for a submitted application. Required reason cannot. The API body matches the current repository.

---

### Screen: Leave balances

**1. Screen objective.** Read remaining leave by type, and the ledger behind it.

**2. Overall layout.** App bar, scroll. Balances first, ledger second.

**3. Header.** Title “Leave balances”. Back. No apply button (apply lives on the Leave tab).

**4. Main content.** For each balance, a row in one sheet: type name `bodyStrong`, code as `caption`, balance as `heading` tabular on the trailing side, “n reserved” in `micro` when reserved is not zero. Then section “Ledger”. Each entry is a row: title `humanize(entryType)` plus type name, caption date and reason, trailing signed amount. Negative amount uses danger colour. Load more as a text button when `hasMore`.

**5. Primary actions.** None for an employee.

**6. Secondary actions.** Encash and Adjust only when `leaveBalanceAdjust`. Employee dropdown only when `leaveBalanceViewAll` and more than one employee loaded. Keep both.

**7. Navigation.** Pushed from More, Home, or Leave. Back pops.

**8. Interaction.** Pull to refresh. Changing employee reloads. Encash and adjust keep their dialogs.

**9. UI states.** Skeleton. Error “Couldn't load balances” plus Retry. Empty “No balances yet” / “No balance-backed leave types configured yet.” Ledger empty: “No ledger activity yet.” No employee id: do not call the API; show “No employee record is linked to your account.”

**10. Responsive.** The balance figure does not wrap under the name; the row uses a trailing column. At text scale 1.4 the figure moves below the name.

**11. Visual.** No beach icon badge. One sheet for balances, one for the ledger.

**12. Preserve.** Decimal strings exactly. Ledger paging. Encash and adjust endpoints and dialogs for holders of `LEAVE.BALANCE_ADJUST`. Self id from the auth profile when the dropdown is hidden.

**13. Acceptance.** An employee sees their types and no Encash button. A holder of adjust still sees Encash and Adjust. Empty types use the existing sentence. `leave_decimal_parsing_test.dart` still passes.

---

### Screen: Profile

**1. Screen objective.** See who the employee is at work, and reach the longer record.

**2. Overall layout.** App bar, scroll. Identity block, work block, contact block, one link into records, sign out at the bottom.

**3. Header.** Title “Profile”. No back. No More icon.

**4. Main content.**

1. Identity block, flat, no gradient. Initials avatar 56. Name `title`. Employee code `caption`. `StatusChip` for `humanize(status)`. If `isActive` is false, a second chip “Inactive”.
2. Section “Work”, filled from the employment and assignment endpoints the record screen already calls (`/employments`, `/assignments`), only the active row (`status == ACTIVE` or the open-ended assignment). Show joining date, pay basis, work location type, and, if a human-readable name is already on the JSON, designation, department, branch, manager, and shift. If the value is a UUID, omit that row and do not display the UUID. If those calls 403, omit the section rather than showing an error where the overview succeeded; the records screen remains the fallback.
3. Section “Contact”: personal email, personal mobile, emergency name, relationship, phone. Omit empty fields. No “Not set”.
4. Address only if at least one present-address field is non-empty, as a single paragraph, not six labelled blanks.
5. Row “Employment records” with caption “Statutory, bank, documents, and history.” Pushes `EmployeeDetailScreen`.
6. Text button “Sign out” in danger, which opens the same confirm dialog as More.

Identity fields that are not the header (date of birth, gender, marital status, blood group, nationality) move into a section “Personal” and follow the omit-empty rule.

**5. Primary actions.** “Employment records” is the forward action. It is a row, not a loud button.

**6. Secondary actions.** Sign out.

**7. Navigation.** Tab root, no longer the post-login landing. Records push. Sign out ends the session and the router returns to login.

**8. Interaction.** Pull to refresh reloads the employee and the work calls.

**9. UI states.** No employee id: current warning copy. Skeleton. Error “Couldn't load profile” plus Try again. Work-section failure is silent omission, as specified above.

**10. Responsive.** Identity row wraps the name to two lines. No two-column field wrap. One column always.

**11. Visual.** Canvas. Avatar on `actionSubtle`. No navy banner. Sections separated by 24px.

**12. Preserve.** `getEmployee`. Sign-out still calls `logout()`. Edit, deactivate, invite, and confirm remain on the detail screen for roles that have those permissions, not on this overview.

**13. Acceptance.** Empty optional fields are absent. A populated email is visible. Sign out asks for confirmation. An admin opening their own profile, if they have an employee id, sees the same layout plus any actions that already depended on permissions inside the detail screen.

---

### Screen: Employment records

**1. Screen objective.** Read the rest of the employee file. HR keeps every write action.

**2. Overall layout.** App bar with the employee name. Scrollable tabs, unchanged set and order for the permissions the user holds: Overview, then record sections the user may view, then Salary if `EMPLOYEE.VIEW_COMPENSATION`, Documents, Attendance if `ATTENDANCE.VIEW`.

**3. Header.** Name as the title. Back. Tab bar is the existing scrollable `TabBar`, restyled only in type (label 13 weight 600, indicator `action`).

**4. Main content.** Overview tab uses the same new profile blocks when the screen is opened on the signed-in employee, and keeps the HR action row (Edit, Confirm, Invite, Deactivate) when those permissions exist. Other tabs keep `EmployeeRecordPanel` content: card title and fields. For the employee, hide write buttons (already permission-gated). Format enums with `humanize` / `prettyEnum` where the panel already does. Where a field is an id and the panel already has choice labels, show the label. Where it does not, leave the value as the API returns it rather than guessing; the audit’s UUID problem is fixed only for fields that already have a loaded label. Do not add a new choice fetch that the EMPLOYEE role cannot call. If `loadChoices` for branches fails, keep the raw value and do not block the tab. Document this limit in the tab’s caption only if the value looks like a UUID: show “Recorded by HR” instead of the UUID for `branch_id`, `department_id`, `designation_id`, `grade_id`, `reporting_manager_id`, and `shift_id`. That substitution is display-only and does not change the payload.

**5. Primary actions.** None for the employee.

**6. Secondary actions.** All current `RecordAction` and row actions for permitted users.

**7. Navigation.** Pushed from Profile or from the employee directory. Back pops.

**8. Interaction.** Tabs keep their state while the detail route is open. Pull to refresh on overview reloads the employee.

**9. UI states.** Per-tab loading, empty “Nothing here yet”, and error with Retry stay. 403 on a tab the permission list thought was allowed: the existing error `StateMessage`.

**10. Responsive.** Tabs scroll horizontally. Tab label is not truncated below 4 characters; the bar scrolls instead.

**11. Visual.** Tab content uses flat sections on the overview and the existing list structure on other tabs, without adding new icon badges.

**12. Preserve.** Every route, `If-Match`, and action in `employee_record_sections.dart`. Tests `employee_record_sections_test.dart` and `employee_record_actions_test.dart`. Salary assign and document manage stay gated.

**13. Acceptance.** EMPLOYEE sees no Edit, no Upload, no Assign, no Terminate. HR still sees them. Switching tabs does not drop a half-finished HR form. UUID substitution applies only to the six id fields named above.

---

### Screen: Documents

**1. Screen objective.** Open a document HR has stored.

**2. Overall layout.** A tab, not a separate route. List of rows.

**3. Header.** The tab label “Documents”.

**4. Main content.** Row title: document type humanized. Caption: filename and size if present. Trailing “Open” only when `downloadUrl` is non-null. No chevron when there is no URL.

**5. Primary actions.** Open, which launches the URL the same way as `_open` today.

**6. Secondary actions.** Upload, verify, reject, delete only when `employeeUpdateSensitive`.

**7. Navigation.** Stays in the tab. Open leaves the app via the existing launcher.

**8. Interaction.** Tap row to open when a URL exists.

**9. UI states.** Loading, empty “No documents yet”, error with retry, missing URL (row visible, Open absent).

**10. Responsive.** Title wraps to two lines. Open stays on the trailing edge.

**11. Visual.** Flat rows. No folder badge on every row.

**12. Preserve.** Download URL handling, upload flow, and verify/reject for HR.

**13. Acceptance.** An employee can open a row that has a URL and cannot see Upload. A document without a URL is visible and not tappable.

---

### Screen: Salary inside records

**1. Screen objective.** Read own compensation history and breakup. HR can still assign.

**2. Overall layout.** The existing panel, with the breakup figures as the first block and history beneath.

**3. Header.** Tab “Salary”.

**4. Main content.** As-of date control stays. Breakup amounts use tabular figures and `formatInr` where the panel already formats money. History rows: effective range, revision type. Assign button unchanged in its permission gate.

**5. Primary actions.** None for the employee.

**6. Secondary actions.** Assign when `payrollSetupManage`.

**7. Navigation.** Tab only.

**8. Interaction.** Changing the as-of date refetches the breakup.

**9. UI states.** Loading, error, empty history. Keep current messages.

**10. Responsive.** Amounts align trailing. Labels wrap.

**11. Visual.** Remove icon badges. Keep the numbers large (`heading`).

**12. Preserve.** Endpoints `/salary` and `/salary/breakup?as_of=`. No client-side salary maths.

**13. Acceptance.** EMPLOYEE sees figures and no Assign. Changing as-of still refetches.

---

### Screen: More

**1. Screen objective.** Reach the few employee tools that are not tabs, and sign out. Administrators still reach settings.

**2. Overall layout.** App bar “More”, optional search, groups, sign out.

**3. Header.** Title “More”. Back, because this route is pushed.

**4. Main content.** For a user whose only grants are the EMPLOYEE set: one group “Your work” with Leave balances, Attendance corrections (`/app/regularizations`), Overtime, Payslips. Then sign out. For a user with further permissions: those four, plus any hub item whose permission they hold, under the existing group labels. Search filters the visible items only. Empty search: “No matches” / “Try a different word.”

**5. Primary actions.** None. Rows navigate.

**6. Secondary actions.** Sign out row, danger text, icon `logout_rounded`.

**7. Navigation.** Each row `context.push` to the existing route. Sign out confirms then `logout()`.

**8. Interaction.** Search is case-insensitive on label and group, as now.

**9. UI states.** No loading state (the list is local). Search empty state as above.

**10. Responsive.** Rows min height 52. Labels wrap to two lines.

**11. Visual.** One sheet per group. Row: title only, chevron. No two-column quick-link grid. No `IconBadge`.

**12. Preserve.** Routes. Sign-out dialog copy “Sign out?” / “You will need to sign in again to use the app.” / Cancel / Sign out. Do not delete administrator routes.

**13. Acceptance.** An EMPLOYEE session does not show Users, Payroll pay runs, or Departments. A user with `SETTINGS.USER.MANAGE` still sees Users. Search for “Users” as an employee returns no matches. Sign out still confirms.

---

### Screen: Regularizations

**1. Screen objective.** See own correction requests and file a new one.

**2. Overall layout.** Same pattern as Leave: app bar action, filter caption, list, filter sheet.

**3. Header.** Title “Attendance corrections”. The route stays `/app/regularizations`. Text button “Request” when `canCreate`.

**4. Main content.** Caption default is the current 30-business-day window, written as dates in the company zone, plus status if not all. Rows: type label and date as title (`regularizationTypeLabels`), reason as caption if non-empty, `StatusChip`. No initials avatar. Mine/Team segment only when approve or on-behalf permission exists.

**5. Primary actions.** “Request”, and the same button in the empty state.

**6. Secondary actions.** Filter sheet: from, to, status, request type.

**7. Navigation.** Pushed from More or from a Home pending row. Detail push. Create opens the form.

**8. Interaction.** Filter changes reload. Pull to refresh. Range still defaults to `businessDayOffset(zone, -30)` through `businessToday`.

**9. UI states.** Skeleton, error with retry, empty “No corrections” / “Requests you submit will show up here.”

**10. Responsive.** Same as Leave.

**11. Visual.** Flat rows. Status chips shared with leave. No raw green box.

**12. Preserve.** Query parameters, including `employee_id` on Mine. Create body via `buildRegularizationBody`. `request_screens_test.dart`.

**13. Acceptance.** Employee sees Request and not Team. Default dates match the company zone. Status colours match leave for the same words (Submitted, Approved, Rejected, Cancelled).

---

### Screen: Regularization detail

**1. Screen objective.** Read one request and cancel it while it is still submitted by this user.

**2. Overall layout.** App bar, sections, bottom cancel when `canCancel` is true.

**3. Header.** Title is the type label. Back.

**4. Main content.** Status chip and attendance date. Sections already defined in `_regularizationSections`: Request, Requested punches, Outcome if not submitted, History. Omit rows whose value is “—”.

**5. Primary actions.** “Cancel request” when the existing `canCancel` allows it.

**6. Secondary actions.** Approve and Reject for reviewers, unchanged.

**7. Navigation.** Pushed from the list. Pop after a successful cancel only if the current code pops; if it reloads in place, keep that.

**8. Interaction.** Cancel confirm dialog uses `cancelLabel` “Cancel request”.

**9. UI states.** Skeleton, error, not found. Busy on the buttons.

**10. Responsive.** Sections full width, 16px padding.

**11. Visual.** Same status header as leave detail. No gradient.

**12. Preserve.** Self-approval and approver-mismatch error codes surfaced from the API. Cancel only when `submitted_by_user_id` matches and status is `SUBMITTED`.

**13. Acceptance.** The submitter sees cancel on a submitted request. They do not see Approve. Punch lines show company-zone times.

---

### Screen: Regularization form

**1. Screen objective.** Submit a correction for one date.

**2. Overall layout.** Full-screen form, sticky submit, same shell as apply-for-leave.

**3. Header.** Title “Attendance correction”. Dirty close confirms discard.

**4. Main content.** Fields from `regularizationSpec(false)`: Attendance date, Request type, toggle “Correct the assigned shift instead of punch times”, then either shift choice or check-in time and check-out time, Reason, Attachment reference. Helper under the times: “Times use your company timezone.” Do not add a timezone picker.

**5. Primary actions.** “Submit”.

**6. Secondary actions.** None.

**7. Navigation.** From the list. Success snackbar “Regularization request submitted.” and reload.

**8. Interaction.** `correct_shift` toggles which fields show (`showWhen`). Validation: shift required when correcting the shift; at least one punch time otherwise. The existing messages stay.

**9. UI states.** Choice load for shifts, validation errors, API errors.

**10. Responsive.** Time fields stack vertically, full width. Do not place them side by side on a phone.

**11. Visual.** Employee inputs.

**12. Preserve.** `buildRegularizationBody`, `wallTimeToUtcIso`, no `correct_shift` key in the JSON, on-behalf employee field only in that mode.

**13. Acceptance.** A time-only request sends `requested_punches` and not `requested_shift_id`. A shift correction does the opposite. The UTC conversion uses the company zone from the auth profile.

---

### Screen: Overtime

**1. Screen objective.** Read overtime the system recorded for the employee. They cannot create it.

**2. Overall layout.** App bar, filter caption, list. No create button.

**3. Header.** Title “Overtime”. Back. “Filter” text button.

**4. Main content.** Row title is the attendance date. Caption is the existing subtitle: detected minutes and approved minutes when approved is greater than zero. `StatusChip` for PENDING, AUTO_APPROVED, APPROVED, REJECTED. Map AUTO_APPROVED to success and the label “Auto-approved”. Default range last 30 business days, same as regularizations.

**5. Primary actions.** None.

**6. Secondary actions.** Filter sheet: dates and status. Team segment and employee filter only with `ATTENDANCE.OVERTIME_APPROVE`.

**7. Navigation.** From More or a future Home row. Detail is pushed.

**8. Interaction.** Pull to refresh. Mine filter keeps sending `employee_id`.

**9. UI states.** Skeleton, error, empty “No overtime” / “Overtime appears here when it is recorded on your attendance.”

**10. Responsive.** Same row rules as leave.

**11. Visual.** Flat rows. No FAB.

**12. Preserve.** `overtimeConfig` has no `createSpec`. Approve and reject remain on the detail for reviewers. List permission is `ATTENDANCE.VIEW`.

**13. Acceptance.** An employee sees no create control and no approve control. A reviewer with the approve permission still sees Team and the decision buttons.

---

### Screen: Overtime detail

**1. Screen objective.** Read minutes, classification, and the approval outcome.

**2. Overall layout.** App bar, sections.

**3. Header.** Title is the attendance date. Back.

**4. Main content.** Status chip. Section “Overtime”: day class, classification, multiplier, minutes detected, minutes approved, comp-off and expiry when the section builder already includes them. Section “Approval”: chain, stage, and the reviewed fields when status is not PENDING. History if actions exist.

**5. Primary actions.** None for the employee.

**6. Secondary actions.** Approve and Reject with comment for reviewers, unchanged.

**7. Navigation.** Back to the list.

**8. Interaction.** Pull to refresh if the detail screen already reloads; keep it.

**9. UI states.** Skeleton and error from `RequestDetailScreen`.

**10. Responsive.** Key-value rows: label 40% , value 60%, value wraps.

**11. Visual.** Same as regularization detail.

**12. Preserve.** Self-approval error code `OVERTIME_SELF_APPROVAL_NOT_ALLOWED` and mismatch code. No create path.

**13. Acceptance.** Detected and approved minutes use `formatMinutes`. An employee does not see Approve.

---

### Screen: My payslips

**1. Screen objective.** Open a finalised payslip.

**2. Overall layout.** App bar and a single sheet of rows.

**3. Header.** Title “Payslips”. Back.

**4. Main content.** One row per `PayslipSummary`: title `formatPayMonth`, caption “Paid {payDate}” or “Paid —” if null, trailing net amount `bodyStrong` tabular and the word “Net pay” in `micro`. No receipt icon badge.

**5. Primary actions.** The row itself.

**6. Secondary actions.** None.

**7. Navigation.** From More and from Home’s latest row. Tap pushes `PayslipScreen` with `getMyPayslip(payRunId)` and the current title.

**8. Interaction.** Pull to refresh via `AsyncListScreen` if it already supports it; if it does not, add refresh without changing the fetch function.

**9. UI states.** Skeleton, error from the list widget, empty “No payslips yet — they appear once a pay run is finalised.”

**10. Responsive.** Net amount stays on one line. The month wraps.

**11. Visual.** Flat sheet. Amount `ink`, not a second colour.

**12. Preserve.** `GET /me/payslips` only on this screen. Do not list company pay runs.

**13. Acceptance.** Empty copy unchanged. Tap loads the self payslip endpoint, not the HR pay-run payslip endpoint.

---

### Screen: Payslip

**1. Screen objective.** Read the slip and share or print the PDF.

**2. Overall layout.** App bar, scroll. Net block, employment facts, earnings, deductions, employer contributions, leave balances on the slip, disclaimer.

**3. Header.** Title “Payslip · {month}” as passed in. Back. Actions: PDF icon “Share / save as PDF”, print icon “Print”, same tooltips.

**4. Main content.**

1. If `isFinal` is false, the existing preview banner. Own slips should be final; the banner stays for the HR caller.
2. Net block on `sheet` with a 3px `ink` top border, not a gradient. Legal entity or company name as `caption`. “Net pay” as `label`. Amount as `display` tabular via `formatInr`. `netInWords` as `caption` when non-empty. Gross and Deductions as two `heading` figures under it.
3. Address line if `legalEntityAddress` is set, centred caption.
4. Facts sheet: employee, code, designation, department, date of joining, masked PAN, UAN, ESI IP if present, paid by, days in month, paid days, LOP days, pay date. Omit null facts.
5. Earnings, deductions, and employer contributions keep their line items, notes, full-month amount when it differs, and section totals. Employer section title stays “Employer contributions (not part of net pay)”.
6. Leave balances on the slip, if the payload includes them, as caption chips “{name}: {balance}”.
7. Footer “This is a computer-generated payslip and does not need a signature.”

**5. Primary actions.** Share PDF in the app bar. It is an icon, not a second hero button, because reading comes first.

**6. Secondary actions.** Print.

**7. Navigation.** Pushed. PDF share uses the system sheet (`Printing.sharePdf`). Print uses `Printing.layoutPdf`.

**8. Interaction.** Share and print build `buildPayslipPdf` for the loaded slip. Failures surface as a snackbar with the error string; do not swallow them.

**9. UI states.** Skeleton. “Couldn't load payslip” plus Retry. Loaded. Share in progress disables the icon.

**10. Responsive.** `display` amount scales down to 24px if it would wrap. Facts are one column. Line amounts align trailing.

**11. Visual.** No navy gradient. Earnings and deductions are open sections with a `label` header, not icon-badge cards. Totals are `bodyStrong`.

**12. Preserve.** Both loaders (`getMyPayslip` and `getPayRunPayslip`). PDF filename pattern. All money fields. Preview banner condition.

**13. Acceptance.** Employee share produces a PDF for the same payslip object. Net, gross, and deduction figures match `formatInr` of the API minor units. The gradient container is gone. HR can still open this screen from a pay run.

---

### Screen: Sign out dialog

**1. Screen objective.** Confirm before destroying the session.

**2. Overall layout.** Dialog used from More and from Profile.

**3. Header.** “Sign out?”.

**4. Main content.** “You will need to sign in again to use the app.”

**5. Primary actions.** “Sign out”, text button in `#EF4444`, not a filled button.

**6. Secondary actions.** “Cancel”.

**7. Navigation.** Confirm calls `logout()`. Router redirects to `/login`.

**8. Interaction.** Cancel dismisses.

**9. UI states.** If logout throws, show the API or a generic snackbar and stay signed in. Match the controller’s current error behaviour; do not add a new failure mode.

**10. Responsive.** Max width 400.

**11. Visual.** Employee dialog.

**12. Preserve.** `AuthController.logout` clears the secure session and refresh cookie the way it does now.

**13. Acceptance.** Profile sign out no longer logs out on the first tap. Cancel leaves the session intact. Confirm reaches the login screen.

---

### Shared visual rules for administrator modes

When the same widget is showing Team, Approve, Encash, Recompute, Upload, or Assign:

- Keep the control.
- Place it where this spec says “secondary” or “only when permission”.
- Do not restyle `DashboardScreen`, `ResourceListScreen`, pay-run processing, or organisation masters in this programme.
- `RequestListScreen` and leave list changes must keep the Team segment and the reviewer buttons. Tests that look for those buttons when the permission is present must still find them.

### Explicit non-goals

- No notification inbox, announcement list, task list, holiday browser, or team directory for the EMPLOYEE role.
- No new punch direction for breaks.
- No offline queue.
- No dark-mode toggle.
- No change to attendance maths, leave maths, or payslip maths.
- No redesign of the company dashboard.

---

<a id="implementation-plan"></a>

## Employee mobile implementation plan

Audit date: 2026-10-30. Build from [EMPLOYEE_MOBILE_REDESIGN_SPECIFICATION.md](#redesign-specification) and [EMPLOYEE_MOBILE_DESIGN_SYSTEM.md](#design-system). Do not start with a screen. Start with tokens, then shell, then Home and Attendance.

This plan does not change APIs, database schemas, or business rules. It changes Flutter presentation, navigation visibility, and tests that assert the old chrome.

### 1. Dependency order

```text
Phase 0 tokens and employee widgets
    → Phase 1 shell, landing, Home, Attendance
        → Phase 2 Leave and Profile
            → Phase 3 More, requests, payslips, onboarding
                → Phase 4 states, accessibility, regression
```

Parallel after Phase 0:

- Home and Attendance both need `TodayStatusPanel` and `CheckInAction`. Build those in Phase 0 and share them.
- Leave list and balances can proceed once `StatusChip` usage and the filter sheet exist.
- Payslip visual work does not depend on Home, except Home’s payslip row, which can ship behind the payslip screen.

Do not restyle `lib/core/widgets/ui.dart` `AppCard` in place for every caller. Administrator resource screens use it. Add employee widgets beside it.

### 2. Phase 0 — Design system foundation

| ID | Item | Description | Files | Depends on | Priority | Complexity | Sequence |
|---|---|---|---|---|---|---|---|
| P0-1 | Light lock | Set `themeMode: ThemeMode.light` on `MaterialApp.router`. Leave `darkTheme` defined. | `lib/main.dart` | None | P0 | Low | 1 |
| P0-2 | Employee colours | Add an employee `ColorScheme` and `ThemeExtension` using the hex values in the design system. Canvas `#F4F6F8`, sheet white, ink `#102A43`, action `#004AC6`. | `lib/core/theme/app_theme.dart`, `app_colors.dart` | None | P0 | Medium | 1 |
| P0-3 | Type scale | Employee text theme: 16 body, 18 heading, 22 title, 28 display. Tabular figures helper. | `app_theme.dart` | P0-2 | P0 | Low | 2 |
| P0-4 | Employee widgets | `TodayStatusPanel`, `CheckInAction`, `SectionHeader` variant, flat `EmployeeListGroup`, `EmployeeStatusHeader`, filter sheet shell, confirm dialog. | New `lib/core/widgets/employee/` | P0-2, P0-3 | P0 | Medium | 3 |
| P0-5 | Status mapping | One function from attendance bucket and request status to `Tone` plus glyph. Month grid and request chips will call it. | `lib/core/widgets/employee/status_map.dart` | P0-4 | P0 | Low | 3 |

Acceptance: a widget test pumps `TodayStatusPanel` with a present day and finds the status word, first in, and last out. `AppCard` golden behaviour for an admin list test is unchanged. The app builds in light mode on a device set to dark.

Testing: `flutter test` for `test/shell_tabs_test.dart` and a new `test/employee_widgets_test.dart`. No API.

### 3. Phase 1 — Core employee experience

| ID | Item | Description | Files | Depends on | Priority | Complexity | Sequence |
|---|---|---|---|---|---|---|---|
| P1-1 | Landing | `landingPathFor` returns `/app/home` when there is an `employeeId` and no dashboard permission. Add the route inside the shell. | `auth_state.dart`, `app_router.dart` | P0-1 | P0 | Medium | 4 |
| P1-2 | Tabs | Employees see Home, Attendance, Leave, Profile. Admins with `DASHBOARD.COMPANY.VIEW` still get `DashboardScreen` on the first branch. | `app_shell.dart`, `app_router.dart` | P1-1 | P0 | Medium | 5 |
| P1-3 | Extract punch | Move punch, face status, idempotency, and geofence orchestration out of the attendance state class into a notifier or helper both Home and Attendance call. No behaviour change. | `attendance_self_screen.dart`, `face_punch_card.dart`, new helper | None, but UI lands in P1-4 | P0 | High | 4 |
| P1-4 | Attendance layout | Today panel, conditional face block, sticky punch, restyled month and 14-day list. | `attendance_self_screen.dart`, `attendance_month_card.dart`, `attendance_widgets.dart`, `face_punch_card.dart` | P0-4, P1-3 | P0 | High | 6 |
| P1-5 | Day detail | Remove the gradient hero. Collapse audit. Keep HR buttons. | `attendance_day_detail_screen.dart` | P0-4 | P1 | Medium | 7 |
| P1-6 | Home | New screen composing attendance today, balances, pending leave and regularizations, latest payslip, shared punch. | `lib/features/home/presentation/employee_home_screen.dart` | P1-2, P1-3, P0-4 | P0 | High | 7 |
| P1-7 | Banner | Recolour `CompanyReadOnlyBanner` only. | `app_shell.dart` | P0-2 | P2 | Low | 5 |
| P1-8 | Location dialogs | Apply dialog radius and type. Do not change button semantics. | `punch_location_flow.dart` | P0-4 | P2 | Low | 8 |

Acceptance:

- Employee fixture in `shell_tabs_test.dart` expects four tabs and a Home landing.
- Admin fixture with `DASHBOARD.COMPANY.VIEW` still builds `DashboardScreen`.
- Face-required test still hides plain punch.
- Punch idempotency tests still pass.
- Home makes no call to a dashboard or holiday-calendar path (assert with `fake_api_client.dart`).

Testing: `test/shell_tabs_test.dart`, `test/attendance_self_mandatory_face_test.dart`, `test/face_punch_card_test.dart`, `test/punch_location_flow_test.dart`, `test/attendance_summary_test.dart`, new `test/employee_home_test.dart`.

### 4. Phase 2 — Leave and profile

| ID | Item | Description | Files | Depends on | Priority | Complexity | Sequence |
|---|---|---|---|---|---|---|---|
| P2-1 | Leave list | Remove FAB. App-bar Apply. Filter sheet. Balance strip. Keep Team. | `leave_applications_screen.dart` | P0-4 | P0 | Medium | 8 |
| P2-2 | Apply form | Full-screen employee form over the same `FormSpec`. Discard confirm. | `spec_form_screen.dart` or a thin employee wrapper, `leave_application_form.dart` | P0-3 | P1 | Medium | 9 |
| P2-3 | Leave detail and cancel | Status header, bottom cancel, keep review buttons. | `leave_application_detail_screen.dart` | P0-4 | P1 | Medium | 9 |
| P2-4 | Balances | Flat rows, ledger secondary. Keep adjust and the employee picker. | `leave_balances_screen.dart` | P0-4 | P1 | Low | 8 |
| P2-5 | Profile | Omit empty fields. Work section from existing employment and assignment reads. UUID display rule. Confirmed sign-out. | `profile_screen.dart`, `employee_overview.dart` | P0-4 | P0 | High | 10 |
| P2-6 | Records tabs | Overview actions preserved. UUID display for the six id fields. Documents and salary visual only. | `employees_screen.dart`, `employee_record_sections.dart`, `employee_documents_panel.dart`, `employee_salary_panel.dart` | P2-5 | P1 | High | 11 |

Acceptance:

- Leave tests still submit and still show Approve when the permission is on.
- Employee overview test shows a non-empty email and does not show “Not set” for a null gender.
- Record action tests still find Terminate when the permission is granted.
- Decimal balance strings unchanged.

Testing: `test/leave_applications_test.dart`, `test/leave_decimal_parsing_test.dart`, `test/employee_record_sections_test.dart`, `test/employee_record_actions_test.dart`, new `test/profile_screen_test.dart`.

### 5. Phase 3 — Supporting modules

| ID | Item | Description | Files | Depends on | Priority | Complexity | Sequence |
|---|---|---|---|---|---|---|---|
| P3-1 | More filter | Permission-filtered hub. Employee group of four links. Search respects the filter. | `settings_hub_screen.dart` | P1-2 | P0 | Medium | 8, can start after P0 |
| P3-2 | Sign-out dialog | Shared dialog from More and Profile. | `settings_hub_screen.dart`, `profile_screen.dart` | P3-1, P2-5 | P1 | Low | 12 |
| P3-3 | Corrections | `RequestListScreen` employee layout, filter sheet, no avatar, shared status chip. Team and approve preserved. | `request_screens.dart`, `request_resources.dart` | P0-4, P2-2 | P1 | High | 12 |
| P3-4 | Overtime | Same list chrome, no create button. | same, `overtimeConfig` | P3-3 | P2 | Low | 13 |
| P3-5 | Payslips | Flat list and payslip page without the gradient. PDF actions unchanged. | `my_payslips_screen.dart`, `payslip_screen.dart` | P0-4 | P1 | Medium | 11, parallel with P2 |
| P3-6 | Auth sheet | Radius 16, labels above fields, keep all error branches. | `auth_scaffold.dart`, login, forgot, reset, verify, accept invite | P0-2 | P2 | Medium | 14 |
| P3-7 | Onboarding | Progress and bottom bar only. Same steps. | `public_onboarding_screen.dart` | P0-3 | P2 | Medium | 14 |
| P3-8 | Face chrome | App bar and consent layout. Camera behaviour untouched. | `face_enrollment_screen.dart`, `face_liveness_capture_screen.dart` | P0-3 | P2 | Medium | 13 |

Acceptance:

- More test: employee permissions do not find a “Users” label; `SETTINGS.USER.MANAGE` does.
- Request tests still create a regularization and still show approve when permitted.
- Payroll widget tests still find net pay and the PDF action.
- Public onboarding tests still walk sections.

Testing: `test/request_screens_test.dart`, `test/payroll_test.dart`, `test/public_onboarding_screen_test.dart`, `test/deep_link_test.dart`, new `test/settings_hub_test.dart`.

### 6. Phase 4 — Polish and quality

| ID | Item | Description | Files | Depends on | Priority | Complexity | Sequence |
|---|---|---|---|---|---|---|---|
| P4-1 | Small width | 320px pass on Home, Attendance month, Leave filters, Profile. | Screens above | Phases 1–3 | P1 | Medium | 15 |
| P4-2 | Text scale | 1.4 scale: punch button and net pay do not clip. | Punch bar, payslip, profile | P1-4, P3-5 | P1 | Medium | 15 |
| P4-3 | Semantics | Month cell labels, punch button labels. | Month card, punch bar | P1-4 | P1 | Low | 16 |
| P4-4 | Loading | Home partial failure. Attendance punch bar stays up when history fails. | Home, attendance | P1-4, P1-6 | P1 | Medium | 16 |
| P4-5 | Safe area | Sticky punch and form submit clear the system gesture inset and the tab bar. | Attendance, forms | P1-4, P2-2 | P1 | Low | 16 |
| P4-6 | Copy pass | Empty states match the specification strings. | All employee screens | Phases 1–3 | P2 | Low | 17 |

No new animation package. Keep the existing page transitions.

Acceptance: widget tests at `surfaceSize` 320×640 and with `textScaler: TextScaler.linear(1.4)` for Home and Attendance. Semantics test finds “Punch in”.

### 7. What can ship alone

| Independent after Phase 0 | Blocked |
|---|---|
| Banner recolour, payslip gradient removal, auth sheet, onboarding chrome, face app bar | Home until punch extraction and the route exist |
| Balances visual | Leave strip on Home until balances widget exists |
| More filter | Can ship before Home, and should, because it removes the admin leak |
| Day detail | Can ship as soon as employee header widgets exist |

Recommended first merge: P0 plus P3-1 (tokens, light lock, More filter). Employees stop seeing the admin catalogue even before Home exists.

### 8. Regression strategy

Functional areas that must keep working:

| Area | What to run | What must stay true |
|---|---|---|
| Navigation | `shell_tabs_test.dart`, `deep_link_test.dart` | Public routes stay public. Admin dashboard route still builds for dashboard permission. Employee no longer lands on `/app/me` only. |
| Auth | Existing auth widget tests if present; otherwise add one for 401 and unverified email | Error strings in the login spec. |
| Permissions | Leave, request, record-action, face-admin tests | Buttons appear only with the permission. |
| Attendance punch | `attendance_self_mandatory_face_test.dart`, `face_punch_card_test.dart`, `punch_location_flow_test.dart`, `location_capture_test.dart` | Idempotency, face required, geofence modes. |
| Attendance display | `attendance_summary_test.dart`, `attendance_screens_test.dart` | Bucket counts unchanged. |
| Leave | `leave_applications_test.dart`, `leave_decimal_parsing_test.dart` | Submit body, decimals, cancel rules. |
| Profile writes | `employee_record_actions_test.dart`, `employee_record_sections_test.dart` | HR actions still submit. |
| Payroll | `payroll_test.dart` | PDF entry points exist. Own list still uses `/me/payslips`. |
| Onboarding | `public_onboarding_screen_test.dart`, `onboarding_form_spec_test.dart` | Section order and submit. |
| Forms | `form_spec_test.dart` | Spec validation still runs. |
| Banner | `company_read_only_banner_test.dart` | Both sentences. |

Manual pass after Phase 1 and again after Phase 3, on a narrow phone and a tall phone:

1. Login as EMPLOYEE. Land on Home. Punch in. Confirm the snackbar and the today status.
2. If face is required in that tenant, confirm plain punch is absent and the camera flow still completes or cancels cleanly.
3. Deny location when the policy is REQUIRED. Confirm no punch request. Repeat with OPTIONAL if a tenant exists.
4. Apply for leave with an end date before the start. Confirm the inline error.
5. Open balances from Leave. Confirm the figures match the API.
6. Open More. Confirm admin rows are absent. Sign out and cancel, then sign out and confirm.
7. Open a payslip and share the PDF sheet (cancel the system sheet).
8. Login as a user with `DASHBOARD.COMPANY.VIEW`. Confirm Home is still the company dashboard and More still lists settings they are allowed to open.
9. Login as a reviewer. Confirm Leave → Team and Approve still appear on someone else’s pending application.

Device sizes: 320×568, 360×800, 390×844. Landscape is not a target; the scroll views must not overflow. There is no in-app browser requirement for this Flutter work. Widget tests are the verification available in the repository. A manual device pass is still required before calling the visual work done, because font metrics and safe areas are not fully proven by the current test suite.

### 9. Risks

| Risk | Why | Mitigation |
|---|---|---|
| Shared widgets change HR screens | `AppCard`, `RequestListScreen`, and `EmployeeDetailScreen` are shared. | Employee variants and permission branches. Run the admin-facing widget tests after each phase. |
| Punch extraction introduces a double submit | Home and Attendance could each hold a key. | One helper owns `_unconfirmedPunch`. |
| `landingPathFor` drift from web | The comment says it mirrors `apps/web/src/lib/auth/landing.ts`. | Change mobile only. Note the divergence in the PR. Do not change the web landing in this programme. |
| Assignment names | UUIDs hidden as “Recorded by HR” may look like missing data. | Only those six fields. The records tab remains. |
| Filter sheet drops a query param | Leave and requests have several filters. | Widget test that applying the sheet sets `date_from`, status, and type. |
| ThemeMode.light surprises admin users who wanted dark | Dark was implicit, not a setting. | Call it out in release notes. Dark theme code stays. |
| Home over-fetches | Five calls on launch. | Parallelise. Do not block punch on leave or payslip. |

### 10. Out of scope

Administrator dashboard visual redesign, resource master screens, pay-run processing, roster management, new notification infrastructure, offline punch queue, break punch as a new direction, holiday API, and any change under `apps/api` or `apps/web`.
