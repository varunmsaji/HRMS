# Mobile UI/UX audit (Krewoxa Flutter app)

Date: 2026-11-15 · Scope: `apps/mobile` (Flutter, 42.9k lines of Dart, branch `test` at `c06647c`) · Documentation only, no code changed.

---

## 0. Method and limits

**How this was done.** Every finding comes from reading the implementation: router and shell (`core/router/app_router.dart`, `features/shell/`), navigation table (`core/nav/nav_entries.dart`), theme and shared widgets (`core/theme/`, `core/widgets/`), the generic form and request frameworks (`core/forms/`, `core/requests/`, `core/resource/`), and the screens for Home, Dashboard, Attendance, Leave, Requests, Notifications, Profile, Employees, Auth and Onboarding. Where a finding rests on a specific line, the file is cited.

**What was not done.** Flutter is not installed on the audit machine, so the app was **not run**. Nothing here was checked on a device. Layout claims that depend on real rendering (fold position, overflow at large text, grid usability) are marked **[verify on device]**. Before Phase 1 starts, someone should spend 30 minutes on a 360×640 Android phone at 1.0× and 1.3× text to confirm them.

**Relation to earlier work.** `docs/design/employee-mobile/` holds an approved employee redesign specification (S01–S34, decisions D-01…D-15). This audit treats that spec as the intended design. Where the code departs from it, the finding says so (MOB-UX-019, 020, 024 and 034). This audit also covers the manager and HR/administrator experience, which the employee spec left out of scope.

**Severity rubric.** 🔴 Critical: a core task fails, or users are seriously misdirected. 🟠 High: frequent friction, or a common task reads like an admin tool. 🟡 Medium: a noticeable usability or consistency problem. 🟢 Low: polish.
**Frequency:** Daily / Weekly / Occasional. **Complexity:** S (≤1 day), M (2–5 days), L (more than a week, or a backend dependency).

---

## 1. Executive summary

### Overall assessment

The app is **functionally broad and technically careful, but organised around the data model rather than around what users do day to day.** The plumbing is unusually solid: punches are idempotent and survive retries, location and camera failures get plain-language dialogs, every list has loading, error and empty states, menus are filtered by permission, and the employee widgets respect large text. Above that plumbing, the experience is weaker:

* **The UI does not say what needs the user's attention.** A manager's Home has no count of requests waiting for them, approvals are spread over three screens, and notifications open lists rather than the item. For an HRMS, approvals are the main thing that moves work along, so this is the biggest gap.
* **Shortcuts don't do what their labels say.** "Apply Leave", "Correction: fix missed punch", "My Shifts: upcoming roster" and "Download Sept slip" on Home all open a list screen, not the action.
* **Forms are generic.** One spec-driven form engine serves leave, corrections, employees and settings. That makes them consistent, but leave application shows maternity and attachment fields to everyone, submits with a button labelled **"Create"**, and gives no balance or day-count preview. Any form loses its contents silently on Back.
* **Several visual systems have grown side by side**: 201 hard-coded colour literals, 255 hard-coded font sizes (down to 9 pt), and six different status-chip widgets. Screens look visibly different from one another, and an administrator in dark mode sees the theme flip between light and dark as they switch tabs.

### Strengths worth keeping

1. **Punch flow robustness** (`attendance/state/punch_controller.dart`): one in-flight guard, idempotency keys reused on unknown outcomes, honest "may have been recorded, retrying is safe" copy, and the location check before the face capture so nobody does the slow step for nothing.
2. **Consistent state components**: `StateMessage`, `ListSkeleton` and pull-to-refresh on nearly every list, plus a readable release-mode error widget instead of a grey box (`main.dart`).
3. **Permission-driven navigation from one table** (`nav_entries.dart`), so the menu and the route guard cannot disagree.
4. **Large-text awareness in the employee widgets** (`core/widgets/employee/*`): layouts switch to stacked at 1.4×, and buttons use minimum rather than fixed heights.
5. **Rich approver cards** (`leave_decision_center_screen.dart`): balance after approval, loss-of-pay days and team clashes are shown before the decision.
6. **Public onboarding as a real stepper** that saves each section as it goes.

### Biggest UX risks

| Risk | Why it matters | Issues |
|---|---|---|
| Approvals stall | Managers on the employee surface see no "waiting for you" count on Home, there are no push notifications, and corrections and overtime approvals are buried in More | 001, 002, 003 |
| Employees misled about their own status | "Needs attention" lists the employee's *own* submitted requests, which are waiting on someone else, and its "View all" goes to Leave even when the items are corrections | 006 |
| Lost work | No unsaved-changes guard on any form, and session expiry drops the user on Login silently | 024, 031 |
| Leave applied blind | The Leave tab and the apply form show no balance, no day count and no holiday awareness | 011, 012 |
| Inconsistency erodes trust | Four visual systems, mixed terms ("Regularization", "Correction", "Punch Correction"), and light/dark flips between tabs | 019, 040–043 |

---

## 2. UX scorecard

| Category | Score | Key finding |
|---|---:|---|
| Navigation | 5/10 | Four clear tabs, but everything else, including daily employee tasks, sits behind a gear labelled "Settings & more". Approvals have no single place. |
| Ease of use | 6/10 | Punching is good. Leave and corrections take more steps than they should, and shortcuts land on lists. |
| Visual hierarchy | 6/10 | Home leads with date and greeting rather than status. The admin dashboard puts charts above the approvals queue. |
| Mobile optimization | 6/10 | Sticky punch bar and good safe-area handling. Filter stacks eat ~25–35% of the screen, and many small text-only tap targets. |
| Forms | 4/10 | Generic engine, ISO dates, wrong keyboards, no discard guard, no sticky submit, irrelevant fields, "Create" as the leave submit label. |
| Feedback & states | 6/10 | States exist everywhere. Session expiry, partial dashboard failures and load-more failures are silent. |
| Accessibility | 5/10 | Text scaling handled in the employee kit. Home uses `GestureDetector` (no semantics or ripple), 9–11 pt fixed text, and colour carries some meaning. |
| Consistency | 4/10 | Four visual systems, six status chips, three filter patterns, mixed terminology. |
| Performance UX | 6/10 | Progressive loading on Attendance. Home rebuilds every second, the dashboard waits for its slowest call, and lists reload to page 1 after viewing a detail. |
| **Overall** | **5.5/10** | Solid engineering foundation. The UX layer needs to be organised around tasks and pending work. |

---

## 3. Findings

Format for each issue: **Location**, then **Problem**, **Impact**, **Severity · Frequency · Complexity**, **Recommendation**, **Expected improvement** and **Implementation notes**.

### 3.1 Navigation and information architecture

#### MOB-UX-001: Approvals have no single home, and managers never see what is waiting for them
* **Location:** Employee Home (`home/presentation/employee_home_screen.dart`), Leave tab, More → Regularizations / Overtime / Shift Swaps. Manager and HR flows.
* **Problem:** A manager with an employee record uses the *employee* surface (`core/auth/surface.dart`). Their Home builds "Needs attention" only from their **own** leave and correction requests (lines 174–176). Nothing on Home counts requests waiting for *them* to decide. Leave decisions sit in a "Decisions" segment inside the Leave tab. Correction decisions sit in More → Regularizations → Decisions. Overtime has no decision centre at all; approval goes through the generic list. Shift-swap approval is in a separate screen again. Only administrators (company dashboard) get a "Pending Approvals" tile, and its "View all" opens the leave list only (`dashboard_screen.dart`, Pending Approvals panel).
* **Impact:** Managers learn about pending work only from notifications (see 002). Corrections that block payroll and attendance lock can wait for days unnoticed. Every manager has to remember three or four separate places to check.
* **Severity:** 🔴 Critical · Daily · M
* **Recommendation:** Add an **Approvals inbox**: one screen listing every request the user can decide (leave, correction, overtime, shift swap, and onboarding review for HR), newest or oldest first, with a type filter chip row. Put a "Waiting for you · N" card at the top of the manager's Home and on the admin Dashboard, linking there. Keep the existing decision-centre cards as the row content.
* **Expected improvement:** One place to clear the queue, with a count visible on the first screen. Faster turnaround on corrections and leave.
* **Implementation notes:** New route `/app/approvals`. Reuse `DecisionCenterView` cards and `_Pending` queue fetches from `dashboard_screen.dart`. Add an entry to `navQuickLinks` gated on any `*_APPROVE` permission. Home gets a `homePendingApprovalsProvider`.

#### MOB-UX-002: No push notifications; in-app polling only
* **Location:** `notifications/presentation/notification_popup_host.dart` (30 s foreground poll), `pubspec.yaml` (no `firebase_messaging` or equivalent).
* **Problem:** Notifications reach a user only while the app is open and in the foreground.
* **Impact:** Approvers are not alerted to new requests. Employees are not told when leave is approved or a correction is rejected. This compounds 001.
* **Severity:** 🟠 High · Daily · L (FCM/APNs setup plus a backend sender)
* **Recommendation:** Add push for a short, high-value set of events: request waiting for your decision, your request decided, punch-out reminder at shift end, face enrollment decided. Respect a per-user opt-out.
* **Expected improvement:** Approval latency falls from "next time I open the app" to minutes.
* **Implementation notes:** Backend already produces `AppNotification` rows with `action_url`. Push should carry the same id and URL so a tap reuses `safeNotificationPath`.

#### MOB-UX-003: Notification and dashboard taps open lists, not the item
* **Location:** `notifications/domain/*.dart` `_listOnlyOnMobile` (leave applications, regularizations, overtime, onboarding, payslips). Dashboard "Pending Approvals" rows (`_pendingRoute`) and Home correction rows (`context.push('/app/regularizations')`).
* **Problem:** "Your leave for 12 Nov was approved" opens the whole leave list, filtered to the default view. The user then has to find the item themselves. Detail screens exist (`LeaveApplicationDetailScreen`, `RequestDetailScreen`) but have no route.
* **Impact:** Every notification costs an extra search. Approvers tapping "Leave request from Ravi" may land on the Mine segment, not the item.
* **Severity:** 🟠 High · Daily · S–M
* **Recommendation:** Add detail routes (`/app/leave-applications/:id`, `/app/regularizations/:id`, `/app/overtime/:id`, `/app/me/payslips/:payRunId`) and map notification URLs to them. Dashboard and Home rows push the item's detail.
* **Expected improvement:** One tap from alert to decision.
* **Implementation notes:** Routes outside the shell so Back returns to where the user was. Remove the entries from `_listOnlyOnMobile`.

#### MOB-UX-004: Everyday employee tasks are hidden behind a "Settings" gear
* **Location:** `shell/more_action.dart` (gear icon, tooltip "Settings & more"), `shell/settings_hub_screen.dart`, Home header avatar (`_Header`, which opens `/app/more`).
* **Problem:** Leave Balances, My Calendar, Corrections, Overtime, Shift Swaps and My Payslips are reachable only through **More**. On Home, More's entry point is a generic person avatar, which looks like "Profile" but opens a settings hub. On the Attendance tab the gear is hidden for employees (D-15), so from there More is unreachable without going Home first. A gear icon tells users "settings", not "my payslips".
* **Impact:** Users who don't happen to tap the avatar never find payslips or corrections. Support tickets follow ("where is my payslip?").
* **Severity:** 🟠 High · Weekly · S–M
* **Recommendation:** (a) Make the header avatar show the user's initials and open **Profile**. (b) Rename More's entry to a labelled "More" or "Menu" (grid icon) and make it reachable from all four tabs. (c) Surface the two highest-value items in context: Leave Balances on the Leave tab (011) and Corrections on each attendance day (013). Payslips stay as a Home tile.
* **Expected improvement:** No daily task is more than two taps from any tab, and icons mean what they look like.
* **Implementation notes:** `MoreAction` icon and label. `_Header.onProfile` changes to `context.go('/app/me')`. Revisit D-15 with this evidence.

#### MOB-UX-005: Tab and title naming swapped between surfaces
* **Location:** `app_shell.dart` `_destinations` / `_employeeDestinations`.
* **Problem:** The administrator's tab is labelled **"Home"** but opens `/app/dashboard` with the title "Dashboard". The employee's tab is labelled **"Dashboard"** but opens `/app/home`. The Leave tab has a beach-umbrella icon for admins and a calendar-check icon for employees.
* **Impact:** Small but persistent confusion, and it breaks shared vocabulary in training and support ("tap Home").
* **Severity:** 🟢 Low · Daily · S
* **Recommendation:** Call it "Home" on both surfaces and use one icon set.

#### MOB-UX-006: "Needs attention" and "Pending" mislabel what they show, and route to the wrong place
* **Location:** `employee_home_screen.dart` `_attention()` and the "Pending · with HR" `DdStatTile`.
* **Problem:** (a) "Needs attention" lists the employee's own *submitted* requests. They need nothing from the employee; they are waiting on an approver. (b) "View all (N)" always opens the Leave tab, even when the items are corrections. (c) The Pending tile adds leave and corrections, labels the total "with HR" (often it is with a manager), and also always opens Leave. (d) Only three rows are shown, with no indication of what was cut.
* **Impact:** The employee cannot tell what they need to do (nothing) from what they are waiting for. A correction count leads to a leave screen with no corrections on it.
* **Severity:** 🟠 High · Daily · S
* **Recommendation:** Rename the section **"Waiting for approval"**, with a caption naming the approver stage when the API provides it. Reserve "Needs attention" for things the employee must act on: a missing punch yesterday, a rejected correction to redo, face enrollment requested, a leave sent back for changes. Route each row and "View all" by type.
* **Expected improvement:** The Home screen answers "do I need to do anything?" correctly.

#### MOB-UX-007: Home shortcuts don't do what their labels promise
* **Location:** `employee_home_screen.dart` `_quickActions()`.
* **Problem:**

  | Tile | Label promises | Actually opens |
  |---|---|---|
  | Apply Leave | "Quick balance slip" (meaningless) | Leave list; the user then finds the FAB |
  | Correction | "Fix missed punch" | Regularizations list, no form, no date |
  | Payslips | "Download Sept slip" | Payslip list |
  | My Shifts | "Upcoming roster" | Attendance tab (no roster shown) |
* **Impact:** Each shortcut costs one or two extra taps, and users stop trusting the shortcuts.
* **Severity:** 🟠 High · Daily · S
* **Recommendation:** Apply Leave opens the apply form directly. Correction opens the correction form, defaulting to the most recent day with a missing punch. The Payslip tile opens the latest payslip. My Shifts opens My Calendar (`/app/me/calendar`), which does show shifts. Rewrite the subtitles in plain terms ("4 casual days left", "Yesterday: no punch-out").

#### MOB-UX-008: Admin dashboard puts decoration above action
* **Location:** `dashboard_screen.dart` build order: header, branch, setup, 4 stat tiles, Attendance donut, Leave Statistics donut, **Pending Approvals**, Recent Activities, Quick Actions.
* **Problem:** The only actionable block (pending approvals) is the third panel, below two charts. On a phone that is about two screens down **[verify on device]**. "View all" opens leave only. Quick action "Requests" opens regularizations only, and "Leave" opens balances, not applications.
* **Impact:** HR opens the app to clear work and has to scroll past charts every time.
* **Severity:** 🟡 Medium · Daily · S
* **Recommendation:** Order: Waiting for you (001), then Today (present / absent / not punched in, each tappable to a filtered Team Attendance), then the charts. Relabel "Requests" as "Corrections", or point it at the Approvals inbox.

#### MOB-UX-009: Administrator More menu is a 40-item settings catalogue
* **Location:** `nav_entries.dart` `navSettingsGroups` (12 groups, ~35 settings plus 14 quick links).
* **Problem:** Rarely-used, desktop-class configuration (Leave Combination Rules, Statutory Minimums, Salary Structures, Rules by Group) gets the same weight as daily tools. Search exists, which helps, but the first view is long.
* **Impact:** Daily tools are hard to scan. Configuring complex policies on a phone also invites mistakes.
* **Severity:** 🟡 Medium · Weekly · S
* **Recommendation:** Show "Daily" (Employees, Team attendance, Approvals, Rosters, Payroll) first. Collapse configuration under one "Company setup" row that opens the grouped list. Consider marking complex policy editors as "Best done on the web" with a share-link option.

#### MOB-UX-010: Returning from a detail screen resets the list
* **Location:** `employees_screen.dart` (`await push…; _load(); _loadSummary();`), `leave_applications_screen.dart`, `request_screens.dart`.
* **Problem:** After viewing any row, the list reloads from page 1 and shows the skeleton. Scroll position and loaded pages are lost.
* **Impact:** Working through a long list (reviewing 30 employees, scanning team leave) means scrolling back after every item.
* **Severity:** 🟡 Medium · Daily for HR · S
* **Recommendation:** Reload only when the detail screen reports a change (pop with `true`). When it does, refresh in place (keep rows, update the changed one) without the skeleton.

### 3.2 Leave

#### MOB-UX-011: The Leave tab never shows the balance
* **Location:** `leave_applications_screen.dart`. Balances are only at More → Leave Balances, or on the Home tile.
* **Problem:** The tab opens on a filter bar and a list of past applications. "How many days do I have?", the first question before applying, isn't answered here.
* **Severity:** 🟠 High · Weekly · S
* **Recommendation:** Put a horizontal `LeaveBalanceStrip` (it already exists in `core/widgets/employee/leave_balance_strip.dart`) at the top of the Mine view: one chip per type, full names, available days. Tapping a chip opens the ledger for that type.
* **Expected improvement:** Balance and history together, and no trip to More.

#### MOB-UX-012: The apply-for-leave form is a generic record form
* **Location:** `leave/domain/leave_application_form.dart`, `core/forms/spec_form_screen.dart`, called from `_apply()` without a `submitLabel`.
* **Problem:**
  1. Submit button reads **"Create"** (and "Saving…").
  2. Every user sees **Expected delivery date (maternity only)** and **Attachment reference** (a free-text field, not a file upload).
  3. End date does not default to the start date, so a one-day leave needs the date picked twice.
  4. Half day is a separate dropdown that throws a validation error for multi-day ranges instead of being hidden.
  5. No preview of working days counted (weekends and holidays excluded), and no balance after the request.
  6. Dates display as `YYYY-MM-DD`. The picker allows 1900–2100 and marks no holidays.
  7. Reason uses no sentence capitalisation (no field in the app uses `TextCapitalization.sentences`).
* **Impact:** The most common employee form feels like a database screen. Users submit requests that overrun their balance, then get rejected.
* **Severity:** 🟠 High · Weekly · M
* **Recommendation:** A dedicated leave form: type chips showing available balance, then a date-range picker (one control), a half-day toggle shown only for single days, and a live summary line ("2 working days · Casual balance 4 → 2"). Reason gets sentence case. Attachment is a real file picker, shown only if the type requires one. Expected delivery date appears only for maternity types. The sticky bottom button reads "Submit request".
* **Implementation notes:** Leave-type metadata (requires attachment, maternity) is needed from `/leave-types`. If it's missing, show attachment as optional for all types and hide the maternity field unless the type name matches. The day-count preview needs either a backend "preview" endpoint or client-side use of the work calendar. Prefer the backend for correctness.

#### MOB-UX-013: The leave and request filter bar takes the top of every list
* **Location:** `leave_applications_screen.dart` (segmented control, From/To buttons, 5 status chips, employee dropdown). `request_screens.dart` `RequestListScreen` (segmented control, From/To, Status dropdown, extra dropdowns, employee dropdown).
* **Problem:** Before the first row there are up to five rows of filters, roughly 200–260 dp **[verify on device]**, on a 640 dp screen that also loses about 136 dp to the app bar and tab bar. Leave uses chips, while requests use dropdowns for the same "status" concept. The request list silently limits to the **last 30 days**, so an older pending correction disappears from Mine. Dates show raw ("From 2026-10-16").
* **Impact:** Employees with a handful of requests see more controls than content. Approvers can miss old pending items.
* **Severity:** 🟡 Medium · Daily · M
* **Recommendation:** One pattern for all lists: a search or summary line plus a single **"Filter" button with an active-count badge** that opens a bottom sheet. `core/widgets/employee/filter_sheet.dart` already exists and is **used nowhere**. Default the request lists to "Open + last 30 days", so pending items never age out of view.

#### MOB-UX-014: Approving takes a detour through the detail screen
* **Location:** `leave_decision_center_screen.dart` `_LeaveCard._open(review: true)` and `RequestDetailScreen.reviewOnOpen`.
* **Problem:** Tapping **Approve** on a card pushes the detail screen, which opens the dialog on load, then pops on completion. The user sees a screen flash under the dialog. The card's button reads "Decline", while the dialog and detail screen say "Reject".
* **Severity:** 🟡 Medium · Daily for approvers · S
* **Recommendation:** Open the decision sheet (as a bottom sheet) directly from the card, run the same submit code, and refresh the card in place. Use one verb, "Reject", everywhere.

#### MOB-UX-015: Reject dialog asks for two near-identical texts
* **Location:** `leave_application_detail_screen.dart` `_review`, `request_screens.dart` `_review`.
* **Problem:** Rejecting shows "Comment (optional, visible to the employee)" **and** "Rejection reason" (also optional). Users can't tell which to fill in. A rejection with no reason is allowed.
* **Severity:** 🟡 Medium · Daily for approvers · S
* **Recommendation:** One field, "Reason (shown to the employee)", required on reject and optional on approve. Offer three or four quick-reason chips ("Team coverage", "Insufficient balance", "Please add details").

#### MOB-UX-016: The approver centre puts four statistic tiles above the queue
* **Location:** `core/requests/decision_center_view.dart` `_StatGrid`.
* **Problem:** Pending requests, on leave today, starts in the next 7 days, and staff available: two rows of cards (about 220 dp) before the first request **[verify on device]**. Switching tabs replaces the cards with a spinner.
* **Severity:** 🟡 Medium · Daily for approvers · S
* **Recommendation:** Collapse the statistics into a single summary line ("5 pending · oldest 3 d · 2 on leave today") that expands on tap. Keep the cards visible while the tab reloads.

#### MOB-UX-017: Balance adjustment uses a typed date
* **Location:** `leave_balances_screen.dart` `_entryDialog` (Effective date `TextField`, description "YYYY-MM-DD", default from the device date).
* **Severity:** 🟡 Medium · Occasional (HR) · S
* **Recommendation:** Use the date picker, default to the company-zone today (`businessToday`), and show the resulting balance before confirming.

### 3.3 Attendance

#### MOB-UX-018: The correction form makes the employee classify their own problem
* **Location:** `attendance/domain/request_resources.dart` `regularizationSpec`, `attendance_day_detail_screen.dart` `_requestCorrection`.
* **Problem:** The form lists **9 request types** (Missing punch, Wrong punch, Wrong shift, Wrong status, WFH, On duty, Excess break, Full day, Early departure approval). From a day screen, only the date is prefilled. The app already knows the day was `missing_punch`, `is_late` or `INCOMPLETE` (it uses these to show the "needs correction" hint), and it knows the punches that exist. Those could prefill the type and the known time.
* **Impact:** Employees pick the wrong type, which leads to rejections and resubmissions. It is also the most frequent exception workflow in attendance.
* **Severity:** 🟠 High · Weekly · S–M
* **Recommendation:** From a day with an exception, prefill `request_type` (missing punch → `MISSING_PUNCH`) and the existing punch time, and leave only the missing time and the reason to fill in. Group the types into "Fix my times" (missing or wrong punch), "I worked elsewhere" (WFH, on duty) and "Other", each with one-line help.

#### MOB-UX-019: The same concept goes by four names
* **Location:** Menu "Regularizations" (manager) and "Corrections" (employee), Home "Punch Correction" and "Correction", form title "Raise a regularization request", settings "Correction Policies".
* **Problem:** The employee spec says the form title should be "Attendance correction". The implementation says "Raise a regularization request".
* **Severity:** 🟡 Medium · Weekly · S
* **Recommendation:** Use "Attendance correction" everywhere a user sees it. "Regularization" stays in code and API only.

#### MOB-UX-020: Home punches one direction only; Attendance offers both
* **Location:** `employee_home_screen.dart` `_PunchCard` (single button on `state.likely`) vs `core/widgets/employee/check_in_action.dart` (primary plus "Punch out instead").
* **Problem:** If the inferred state is wrong (a forgotten punch-out yesterday, or a server-calculated state that lags), Home offers only the wrong direction. The spec deliberately keeps both reachable ("a forgotten punch-out must not trap the employee").
* **Severity:** 🟡 Medium · Occasional · S
* **Recommendation:** Reuse `CheckInAction` on Home (with `showIcons: false`) so behaviour and copy match the tab.

#### MOB-UX-021: The punch bar is always present, even when it doesn't apply
* **Location:** `attendance_self_screen.dart` `WithStickyBar`.
* **Problem:** On leave days, weekly offs and holidays, the sticky bar still shows two punch buttons (about 120–130 dp of permanent space), above a list that is mostly history.
* **Severity:** 🟢 Low · Daily · S
* **Recommendation:** On non-working or leave days, collapse it to a one-line note ("On leave today · punch anyway") that expands on tap.

#### MOB-UX-022: Punch confirmation is too quiet for the most important daily action
* **Location:** `punch_controller.dart` → `ui.message('Punched in.')` / `'Punched out · face verified (82% match)'`.
* **Problem:** Success is a snackbar that disappears after about 4 seconds, with no recorded time. A face punch shows a raw similarity percentage, which reads as a score ("only 82%?") rather than a pass.
* **Severity:** 🟡 Medium · Daily · S
* **Recommendation:** After a successful punch, update the status card in place with a check animation and "Punched in at 09:02". Add a success haptic. Drop the percentage ("Face verified").

#### MOB-UX-023: Home rebuilds the whole screen every second
* **Location:** `employee_home_screen.dart` `initState`, `Timer.periodic(1 s, setState)`.
* **Problem:** The live clock causes a full rebuild of Home every second (tiles, donut, lists), even when the user is not punched in and the clock shows a static value.
* **Impact:** Wasted battery and jank on low-end Android phones, which are common among shop-floor staff.
* **Severity:** 🟡 Medium (Performance UX) · Daily · S
* **Recommendation:** Move the ticker into a small `_LiveClock` widget that runs only while punched in. Update minute-precision text once a minute.

### 3.4 Forms and data entry (cross-cutting)

#### MOB-UX-024: Back silently discards a filled form
* **Location:** `core/forms/spec_form_screen.dart`, which has no `PopScope`.
* **Problem:** System Back or the app-bar back arrow on a half-filled leave, correction, employee or settings form discards everything without asking. The employee spec requires a discard confirmation ("discard confirm when dirty").
* **Severity:** 🟠 High · Weekly · S
* **Recommendation:** Track a dirty flag. On pop, show "Discard changes?" (Keep editing / Discard). For long forms (new employee, onboarding), also keep a local draft.

#### MOB-UX-025: Wrong keyboards and missing input helpers
* **Location:** `spec_form.dart` `_keyboard()`, plus `employee_forms.dart` and `onboarding_form_spec.dart`.
* **Problem:** No phone kind exists, so mobile and emergency phone numbers open the **text keyboard**, as do pincodes. Fields don't chain with `textInputAction: next`. No autofill hints on personal data. No sentence capitalisation anywhere. Money fields allow a minus sign.
* **Severity:** 🟡 Medium · Weekly · S
* **Recommendation:** Add `FieldKind.phone` (`TextInputType.phone`, `AutofillHints.telephoneNumber`) and `FieldKind.pincode` (number pad, max length 6). Chain fields with `next`. Default multiline fields to `sentences`. Make money unsigned unless the spec says otherwise.

#### MOB-UX-026: Dates are ISO strings everywhere
* **Location:** `spec_form.dart` (hint `YYYY-MM-DD`), list subtitles (`2026-11-12 → 2026-11-13 · 2 day(s)`), filter buttons ("From 2026-10-16"), team attendance date button.
* **Severity:** 🟡 Medium · Daily · S
* **Recommendation:** One formatter: "Wed, 12 Nov" (with the year only when it differs from now), and ranges "12–13 Nov · 2 days". Keep ISO on the wire only. Home already has `_range`/`_shortDate`; promote them to `core/format.dart`.

#### MOB-UX-027: Errors and the submit button are far from the fields
* **Location:** `spec_form_screen.dart`.
* **Problem:** The "Please fix the highlighted fields" banner sits at the top of a long scroll, and there is no scroll to the first error. Submit is the last item in the scroll, not pinned, so on long forms the user has to scroll to the end to act, and the keyboard covers it.
* **Severity:** 🟡 Medium · Weekly · S
* **Recommendation:** Pin the primary button in a bottom bar that sits above the keyboard (`MediaQuery.viewInsets`). On a validation failure, scroll to and focus the first invalid field.

#### MOB-UX-028: Employee pickers are plain dropdowns
* **Location:** The employee field in leave, correction and overtime forms "on behalf"; filters in leave, requests and team attendance (`DropdownButtonFormField` over every employee).
* **Problem:** In a 300-person company this is a 300-item unsearchable list. A searchable `pickEmployee` sheet already exists (`employees/presentation/employee_picker_sheet.dart`) but is only used on Leave Balances.
* **Severity:** 🟡 Medium · Daily for HR · S
* **Recommendation:** Add `FieldKind.employee` that opens `pickEmployee`, and use it in every filter and form.

#### MOB-UX-029: The new-employee form is one 28-field page
* **Location:** `employee_forms.dart` `employeeSpec`.
* **Problem:** One unbroken scroll mixes identity, contact, two addresses and emergency details. "State code", "Country code" and "Photo URL" are free text.
* **Severity:** 🟡 Medium · Occasional · M
* **Recommendation:** Group into collapsible sections (Basics: name, DOB, gender, mobile, email, which are enough to create the record; then Address; Emergency; More). Use pickers for state and country, a camera or gallery picker for the photo, and save after Basics.

#### MOB-UX-030: Login friction for repeat users
* **Location:** `auth/presentation/login_screen.dart`.
* **Problem:** (a) The company code is not remembered, so employees signing in with an employee ID retype it every time the session ends. (b) The company-code field appears on the first non-email keystroke, which shifts the layout while the user types. (c) "Register your company" is a prominent outlined button on a screen used almost entirely by employees. (d) No biometric quick unlock.
* **Severity:** 🟡 Medium · Weekly · S–M
* **Recommendation:** Remember the last company code and identifier (not the password) in secure storage. Show the company-code field from the start with "Only for employee ID sign-in" as helper text, or put it behind a "Sign in with employee ID" toggle. Demote registration to a text link. Add optional biometric unlock of the stored session (`local_auth`).

### 3.5 States and feedback

#### MOB-UX-031: Session expiry is silent and loses context
* **Location:** `auth/state/auth_controller.dart` (`onSessionExpired`, which goes straight to `unauthenticated`) and the router redirect to `/login`.
* **Problem:** Mid-task (for example halfway through a leave form), a failed token refresh throws the user onto the Login screen with no explanation. After signing in they land on Home, not where they were, and the form contents are gone.
* **Severity:** 🟠 High · Occasional · M
* **Recommendation:** Show "Your session ended. Sign in again to continue." on the login screen. Store the attempted location and return there after login. With 024's draft-keeping, the form survives.

#### MOB-UX-032: No awareness of being offline
* **Location:** App-wide. No connectivity listener (the only network handling is the per-request `NetworkError`, "Could not reach the server…").
* **Problem:** Every screen fails separately with its own error state. Home goes blank rather than showing last-known data. A punch attempted offline fails like any other error.
* **Severity:** 🟡 Medium · Occasional (higher on factory floors and in the field) · M
* **Recommendation:** Add a thin global "You're offline" banner. Cache the last Home and today's state and show them with "Last updated 09:14". For punches, keep the current honest failure; a queued offline punch is a product and compliance decision, so don't add one silently.

#### MOB-UX-033: Partial failures are hidden on the dashboards
* **Location:** `dashboard_screen.dart` (`quiet()` means a failed block is simply omitted), and the employee Home tiles (a dash with no reason, except balances).
* **Problem:** A failed attendance overview looks the same as "you have no permission". The admin can't tell that data is missing. The whole dashboard also waits on nine parallel calls before showing anything, so the slowest call sets the load time.
* **Severity:** 🟡 Medium · Daily · S–M
* **Recommendation:** Render each panel independently with its own skeleton. On failure show a compact "Couldn't load · Retry" inside the panel. Omit a panel only for 403/404.

#### MOB-UX-034: Sign-out is inconsistent
* **Location:** `profile_screen.dart` (signs out immediately) vs `settings_hub_screen.dart` (asks to confirm).
* **Problem:** The employee spec (S21) requires confirmation. A mis-tap on Profile signs the user out. If they sign in with an employee ID, they then have to retype the company code (030).
* **Severity:** 🟡 Medium · Occasional · S
* **Recommendation:** Use the same confirmation everywhere. Factor it out as `confirmSignOut(context, ref)`.

#### MOB-UX-035: The admin "Pending Approvals" number doesn't add up
* **Location:** `dashboard_screen.dart` `_Pending.total`.
* **Problem:** The total includes onboarding cases waiting on **candidates** (invited, in progress, changes requested), which are not approvals. The hint lists only Leave, Attendance and Overtime. A tile showing "14" with a hint of "3 Leave · 2 Attendance" is inconsistent.
* **Severity:** 🟡 Medium · Daily · S
* **Recommendation:** Count only items awaiting this user's decision (HR onboarding review included, candidate statuses excluded). Show every part in the hint.

#### MOB-UX-036: Silent failures on "Load more"
* **Location:** `leave_applications_screen.dart` `_more()` (`catch (_) {}`) and `notifications_screen.dart` `_loadMore()`.
* **Severity:** 🟢 Low · Occasional · S
* **Recommendation:** Show an inline "Couldn't load more · Retry" row at the end of the list.

### 3.6 Accessibility

#### MOB-UX-037: Home's tappable cards are not buttons to assistive technology
* **Location:** `home/presentation/dashboard_design.dart` (`DdStatTile`, `DdAttentionRow`, `DdQuickAction` all use `GestureDetector`), Home "View logs" and "View all", `SectionHeader.action` in `ui.dart`, and the login "Resend verification email".
* **Problem:** `GestureDetector` gives no button role or focus to TalkBack/VoiceOver, and no ripple. Text-only links ("View logs", 12 pt) have tap areas well under 48 dp.
* **Severity:** 🟠 High · Daily · S
* **Recommendation:** Use `InkWell` inside `Material` (or `Semantics(button: true)` plus a minimum 48×48 `ConstrainedBox`) for all of them. Make text links `TextButton`s.

#### MOB-UX-038: Small fixed type sizes
* **Location:** 255 hard-coded `fontSize` values, including 9 pt in `roster_calendar_screen.dart`, `attendance_insights_screen.dart` and `insight_charts.dart`; 38 uses of 11 pt; status chips at 11 and 11.5 pt.
* **Problem:** Hard-coded sizes still scale with the system setting, but they start below the readable floor and ignore the type scale in `app_theme.dart`. 9 pt is unreadable for many users at 1.0×.
* **Severity:** 🟡 Medium · Daily · M
* **Recommendation:** Set a 12 pt floor for body and meta text, 11 pt only for all-caps labels. Replace literals with `textTheme` roles. Add a lint or grep check in CI to stop new literals.

#### MOB-UX-039: Meaning carried by colour alone
* **Location:** Punch-card status dot, donut charts (legend dots plus counts are fine), the 9 pt calendar cells, `RequestStatusChip` raw `Colors.green/red/orange` on a 15% tint (contrast is likely below 4.5:1 for orange text **[verify with a contrast checker]**).
* **Severity:** 🟡 Medium · Daily · S
* **Recommendation:** Always pair a status colour with a word or icon (already true for chips). Calendar cells need a glyph or letter (P, A, L). Use the theme `AppStatusColors`, which can be contrast-checked.

#### MOB-UX-040: The theme flips between light and dark as administrators switch tabs
* **Location:** `theme_selection.dart` (employee surface forced light; administrators follow the system), and `employee_theme_scope.dart` (wraps the Attendance, Leave and Profile routes in the light employee theme for administrators with an employee record).
* **Problem:** An HR administrator in dark mode gets a dark Dashboard, then a light Attendance, Leave and Profile, then a dark More. The employee Home and its `Dd*` widgets hard-code light colours (`Dd.canvas`, `Color(0xFFE8EEF9)`…), so they cannot follow dark mode. Employees get no dark mode at all.
* **Severity:** 🟡 Medium · Daily for affected users · M–L
* **Recommendation:** Short term: when the administrator's system is dark, use the dark theme for the scoped routes too, so the flicker stops. Medium term: express the employee tokens in both brightnesses and retire hard-coded `Dd` colours (see 041).

### 3.7 Consistency and design system

#### MOB-UX-041: Four visual systems
* **Location:**
  * `core/widgets/ui.dart`: `AppCard`, `StatusChip`, `IconBadge` (theme-driven).
  * `features/home/presentation/dashboard_design.dart`: `Dd*` (hard-coded colours and sizes).
  * `core/widgets/dashboard_kit.dart`: `DashPanel`, `StatTile`, `DashHeader`.
  * `core/widgets/employee/*` plus `EmployeeTokens`.
  * Private duplicates: `_Panel` in `dashboard_screen.dart` repeats `AppCard`.
* **Problem:** 201 colour literals across 12 files. The same "stat tile" exists as `DdStatTile`, `StatTile` and the decision-centre `_StatGrid`. Corner radii, paddings and title sizes differ from screen to screen.
* **Impact:** Users see different products in different tabs, and every new screen copies whichever kit its author found first.
* **Severity:** 🟡 Medium · Always · L
* **Recommendation:** Choose one kit (theme-driven `ui.dart` plus `EmployeeTokens` for spacing and typography). Move Home and Dashboard onto it. Delete `Dd*` and `_Panel`. Document the kit in `docs/design/01_Design_System.md` and add a widget-catalogue golden test.

#### MOB-UX-042: Six status-chip implementations and inconsistent status words
* **Location:** `StatusChip` (`ui.dart`), `RequestStatusChip` (`request_screens.dart`, raw colours, 4 px radius, no dot), `EmployeeStatusChip`, `AttendanceStatusBadge`, `_StatusChip` / `LeaveStatusChip`, and the Home `badge:` strings.
* **Problem:** The same "submitted" request reads "Submitted", "Pending approval" or "Pending" depending on the screen, in a round pill or a square tag.
* **Severity:** 🟡 Medium · Daily · S
* **Recommendation:** One `StatusChip.status(code)` with a single label map (`Submitted` → "Awaiting approval", and so on) and the single `toneForStatus`.

#### MOB-UX-043: Three filter patterns, and the sheet that would unify them is unused
* **Location:** Chips (Leave), dropdowns (Requests, Team attendance), `_FilterMenu` (Employees). `filter_sheet.dart` has no callers.
* **Severity:** 🟡 Medium · Daily · M
* **Recommendation:** See 013. Standardise on a Filter button plus bottom sheet plus active chips row.

#### MOB-UX-044: Error, empty and loading visuals vary by screen
* **Location:** `notifications_screen.dart` (its own spinner, error and empty layout), `DecisionCenterView` (spinner instead of skeleton), generic titles "Something went wrong" and "Nothing here".
* **Severity:** 🟢 Low · Occasional · S
* **Recommendation:** Use `StateMessage` and `ListSkeleton` everywhere. Make every empty state say what will appear and how to make it appear ("No corrections yet. Raise one from any attendance day.").

### 3.8 HR and administrator workflows

#### MOB-UX-045: Employee record opens on a 13-tab strip, with a destructive action beside Edit
* **Location:** `employees_screen.dart` `EmployeeDetailScreen` (Overview plus up to 9 record sections, Salary, Documents, Attendance).
* **Problem:** Scrollable tabs hide most sections off-screen. "Deactivate" is an outlined button next to "Edit" and "Invite". "Confirm" (end probation) is ambiguous on its own.
* **Severity:** 🟡 Medium · Weekly · M
* **Recommendation:** The Overview becomes a sectioned page with a summary per area that opens the section on tap (fewer tabs: Overview, Attendance, Documents). Move Deactivate into an overflow menu. Rename Confirm to "Confirm employment".

#### MOB-UX-046: Employee list filters apply only to loaded pages, and rows can't contact the person
* **Location:** `employees_screen.dart` (`filterEmployees` on `_items`; notice "Filters apply to the N employees loaded so far").
* **Problem:** A status filter on a partially loaded list gives wrong answers. Managers can't call or message someone from the row, which is the most common reason to open a directory on a phone.
* **Severity:** 🟡 Medium · Weekly · S–M
* **Recommendation:** Send status and state as server-side filters. Add tap-to-call and email actions on the row or a swipe (`url_launcher` is already a dependency).

#### MOB-UX-047: Team Attendance shows raw enums and has an unsearchable employee filter
* **Location:** `team_attendance_screen.dart` (status dropdown shows `MISSING PUNCH`, employee dropdown).
* **Severity:** 🟢 Low · Daily for managers · S
* **Recommendation:** Use the shared status labels. Add quick chips "Not in yet", "Late", "Missing punch" for today. Use the employee picker (028).

#### MOB-UX-048: Desktop-class grids on a phone
* **Location:** `workforce_roster_screen.dart`, `attendance_calendar_screen.dart`, `attendance_insights_screen.dart` (horizontal scrolling grids, 9 pt labels).
* **Problem:** Employee-by-day grids need two-axis scrolling on a 360 dp screen **[verify on device]**.
* **Severity:** 🟡 Medium · Weekly for managers · M
* **Recommendation:** On phones, default to a per-day list ("Monday: 12 on shift A, 3 off…") with a person drill-down, and offer the grid as an alternative or in landscape.

### 3.9 Smaller items

| ID | Location | Problem | Severity | Recommendation |
|---|---|---|---|---|
| MOB-UX-049 | Home leave tile | "Paid" badge over the sum of *all* types. Breakdown uses three-letter abbreviations ("Cas 4 · Sic 2 · Ear 10") | 🟡 | Label "Leave available". Full type names, two at most plus "+1" |
| MOB-UX-050 | Home header and greeting | Brand bar, then a date pill, then a two-line 25 pt greeting, all before status. The avatar is a generic glyph | 🟢 | Combine date and greeting on one line and lead with the punch/status card. Avatar shows initials (004) |
| MOB-UX-051 | Home with no employee record | Bare centred sentence, no action | 🟢 | `StateMessage` with "Contact HR" and a link to More |
| MOB-UX-052 | Home month card | "Other" segment unexplained. Percentages show one decimal place inconsistently | 🟢 | Name it ("Weekly off / holiday / not marked"). Show whole percentages |
| MOB-UX-053 | Request list (Mine) | The avatar shows initials of the request *type* ("RE"). Team names blank if the employee list fails to load | 🟢 | Use a type icon on Mine. Fall back to the employee code |
| MOB-UX-054 | Request list | `perPage: 100` with no pagination | 🟢 | Paginate like Leave and Notifications |
| MOB-UX-055 | Notifications | One generic bell icon for all types. "Mark all as read" text button crowds the title at large text | 🟢 | Per-type icon (leave, attendance, payroll, face). Move the action into an overflow menu |
| MOB-UX-056 | Dashboard date | `_longDate()` uses the device clock, not the company zone | 🟢 | Use `businessToday(zone)` like Home |
| MOB-UX-057 | Splash | Fixed navy splash with no timeout message if `/auth/me` hangs (10 s connect plus 30 s receive) **[verify on device]** | 🟢 | After about 8 s, show "Still connecting…" with Retry and Sign out |
| MOB-UX-058 | Haptics and motion | 3 haptic calls and one animated widget in the whole app | 🟢 | Success haptic on punch and approval, `AnimatedSwitcher` on status changes (Phase 5) |

---

## 4. User journey analysis

Step counts are taps after the app is open and signed in. Typing is noted separately.

### J1. Daily punch in and out (employee, daily)
* **Current:** `Home → Punch in` (1 tap) → (face: camera challenge) → snackbar "Punched in."
* **Friction:** Weak confirmation (022). Only one direction on Home (020). The whole screen rebuilds every second (023).
* **Recommended:** `Home → Punch in → status card turns green "In since 09:02" plus haptic`. Push reminder at shift end if not punched out (002).
* **Changes:** 020, 022, 023, 002.

### J2. Apply for one day of leave (employee, weekly)
* **Current:** `Home → Apply Leave tile → Leave list → FAB "Apply for leave" → Leave type dropdown → Start date picker → End date picker (same date again) → [scroll past maternity and attachment fields] → "Create"` = **8 taps**, no balance seen anywhere along the way.
* **Friction:** Shortcut lands on the list (007). Balance not visible (011). Irrelevant fields, duplicate date entry, "Create" (012). Back loses the form (024).
* **Recommended:** `Home → Apply Leave → [type chip shows "Casual · 4 left"] → pick 1 date (range picker) → "2 → 1 day left" summary → Submit request` = **4 taps**.
* **Changes:** 007, 011, 012, 024, 026.

### J3. Fix a missed punch (employee, weekly)
* **Current (from Home):** `Home → Correction tile → Regularizations list → FAB → pick date → choose 1 of 9 types → pick check-in → pick check-out → Create` = **9 taps**.
* **Current (best path):** `Attendance → scroll Last 14 days → day → Raise correction → type → time → Submit` = 7 taps.
* **Friction:** Shortcut lands on the list (007). The employee has to classify the problem (018). Mixed terminology (019).
* **Recommended:** `Home "Needs attention: no punch-out on Tue" → prefilled form (type and punch-in known) → pick punch-out time → Submit` = **3 taps**.
* **Changes:** 006, 007, 018, 019.

### J4. Manager approves a leave (manager, daily)
* **Current:** (No push.) `Open app → Home (nothing about approvals) → Leave tab → Decisions segment → scroll past 4 stat cards → Approve on card → detail screen flashes → dialog → Approve` = **5 taps plus a scroll**, and only if the manager remembers to look.
* **Friction:** 001, 002, 014, 016.
* **Recommended:** `Push "Asha requests 2 days casual" → item opens with balance and clash → Approve (sheet) → Done` = **2 taps**, or `Home "Waiting for you · 3" → Approvals inbox → Approve` = 3 taps.

### J5. Manager approves an attendance correction (manager, daily)
* **Current:** `Home → avatar (More) → find "Regularizations" → Decisions → Approve → dialog → Approve` = **6 taps**, with the entry point hidden behind a profile-looking avatar.
* **Recommended:** Same as J4 via the Approvals inbox: **2–3 taps**.

### J6. Act on a notification (all users, daily)
* **Current:** `Bell → notification → list screen → find the item → open it` (3+ taps plus searching).
* **Recommended:** `Bell (or push) → notification → the item` (2 taps). Changes: 003.

### J7. First launch and sign-in (new employee)
* **Current:** `Splash → Login → type employee ID → company-code field appears → type company code → password → Sign in → Home`. Next time the session expires: retype all three, with no explanation of why (031).
* **Friction:** 030, 031. "Register your company" competes with Sign in.
* **Recommended:** Remembered company code and ID, so the user types only the password; biometric unlock afterwards. Return to the last screen after re-auth.

### J8. Find my payslip (employee, monthly)
* **Current:** `Home → Payslip tile → (opens the latest payslip, good)`, but the quick action "Download Sept slip" opens the list instead (007). Without the Home tile (no permission or no payslip), the route is `Avatar → More → My Payslips`.
* **Recommended:** Tile and quick action both open the latest payslip, with "Share PDF" in the app bar (already present).

### J9. HR adds an employee (HR, occasional)
* **Current:** `More → Employees → New employee → 28-field single scroll (text keyboard for phone and pincode) → Create`. Back at any point loses everything.
* **Recommended:** `Employees → New → Basics (6 fields) → Create → "Add address / emergency / invite now?" follow-ups`. Changes: 024, 025, 029.

### J10. HR checks who is absent today (HR or manager, daily)
* **Current:** `Dashboard → scroll to Attendance Overview → View all → Team attendance → status dropdown → "ABSENT"`.
* **Recommended:** `Dashboard "Today: 4 absent" → filtered Team attendance` (1 tap). Changes: 008, 047.

---

## 5. Prioritised implementation plan

Ordering principle: fix what misdirects users first, then what costs them taps every day, then what makes the app feel inconsistent. Most items are client-only. Backend dependencies are named.

### Phase 1: Critical UX fixes (about 1–1.5 weeks)

**Status (2026-11-15):** implemented on `test`. 001 as an Approvals inbox (`/app/approvals`) plus a "waiting for your decision" card on Home and the Dashboard's "View all"; 003 as item routes for leave, corrections, overtime, onboarding cases and payslips; 006 and 007 on Home; 024 as a discard guard on every spec-driven form; 034 as one shared sign-out confirmation; 037 for the Home cards, Home text links, the shared section-header action and the login resend link. Not yet tried on a device.

| Order | Issues | Expected impact | Dependencies |
|---|---|---|---|
| 1 | 006, 007 | Home stops misleading people, and shortcuts do what they say | None |
| 2 | 003 | Notifications open the item | Detail routes (client only) |
| 3 | 001 | Managers see and clear their queue in one place | Reuses existing queue endpoints |
| 4 | 024, 034 | No lost forms, no accidental sign-out | None |
| 5 | 037 | Home usable with TalkBack/VoiceOver | None |

### Phase 2: High-impact improvements (about 2–3 weeks)

**Status (2026-11-15):** implemented on `test` except 002 and biometric unlock.
* 004/005: Home's avatar shows initials and opens Profile; a labelled "More" button is on every tab, including Attendance (this reverses decision D-15); both surfaces use the same tab names and icons ("Home").
* 011/012: the Leave tab shows balances above "Mine"; self-service leave has its own form (type chips with balances, one date-range picker, half day only for one day, maternity date only for maternity leave, a summary of selected and working days that defers to the leave rules, sticky "Submit request", discard guard). Applying on behalf keeps the generic form.
* 014/015/016: Approve and Reject on decision cards open the decision dialog over the list; one comment/reason field (reason required on reject, sent as `rejection_reason`); "Decline" is now "Reject"; the headline figures fold into one line.
* 018/019: the correction form is prefilled with the likely type from the day's flags and shows the recorded punches (times are not prefilled); type names are plain language; "Attendance correction" replaces "Regularization" in everything a user reads.
* 030/031: the login screen remembers the identifier and company code (never the password); "Register your company" is a link; an expired session is explained and the same user returns to the screen they were on. A half-filled form is still lost when the session expires.
* Not done: **002 push notifications** need a Firebase project, platform config files and an APNs key, plus a backend sender. **Biometric unlock** needs native changes that should be tested on devices.

| Order | Issues | Expected impact | Dependencies |
|---|---|---|---|
| 1 | 011, 012 | Leave applied with full information, fewer rejections | Leave-type metadata; day-count preview (backend preferred) |
| 2 | 018, 019 | Corrections take 3 taps and get filed under the right type | None |
| 3 | 004, 005 | Daily items are findable, and icons mean what they look like | Revisit decision D-15 |
| 4 | 031, 030 | Re-login is quick and keeps context | `local_auth` (optional) |
| 5 | 002 | Out-of-app alerts for approvals and decisions | FCM/APNs project, backend sender |
| 6 | 014, 015, 016 | Faster, clearer approving | After 001 |

### Phase 3: Design consistency (about 3–4 weeks, can run alongside Phase 2 after week 1)

**Status (2026-11-15):** partly implemented on `test`; 041 and the employee dark theme wait on a design decision.
* 042: one set of status words (`core/status_words.dart`). Anything waiting reads "Awaiting approval" (or "Awaiting HR/manager approval" on a correction card), whether the API says `SUBMITTED` or `PENDING`. Every request chip uses `StatusChip.request`, so it gets the same words and theme colours. `RequestStatusChip` no longer uses raw `Colors.orange/green/red`, which also covers that part of 039. Cancelled is neutral, not red. Decision-centre tabs read "Awaiting approval / Approved / Rejected".
* 026: readable dates in list rows, detail headers, decision cards, filter buttons and spec-form date fields ("Thu, 12 Nov"; the year appears only when it is not this year). Effective periods read "1 Apr 2026 – 31 Mar 2027". ISO stays on the wire.
* 013/043: one pattern, a summary line plus a "Filter (n)" button that opens a bottom sheet (`core/widgets/list_filter.dart`), on Leave, both request lists (corrections, overtime) and Team attendance. The unused `filter_sheet.dart` is removed. With no status chosen, the request lists also show every open request whatever its date. The Employees list keeps its search-and-menus row.
* 028: any choice list longer than 10 options, in every spec form and in the filters, opens a searchable sheet (`core/widgets/choice_picker.dart`). This covers the employee pickers without a new field kind.
* 044: Notifications and the decision centres use `ListSkeleton` and `StateMessage`. Error titles name what failed ("Couldn't load attendance"), and the action is always "Try again". Empty states say what will appear and how.
* 038 (part): on-screen text below 11 pt is raised to 11 pt (charts, calendar headers, roster cells). Status chips are 12 pt. 3 sizes under 11 pt remain: the notification badge, avatar initials and calendar glyphs, all inside fixed circles. The `fontSize:` literal count is 266, so the CI check proposed below is not added yet.
* 040 (short term): in dark mode the administrator's Attendance, Leave and Profile tabs stay dark instead of switching to the light employee theme.
* Not done: **041** (one component kit, retiring `Dd*` and `_Panel`; 201 colour literals unchanged) needs the design sign-off listed as its dependency. **Employee dark mode** (040, medium term) depends on it. The calendar cells already carry letters (039).
| Order | Issues | Expected impact | Dependencies |
|---|---|---|---|
| 1 | 042, 026 | One status vocabulary, human dates everywhere | None |
| 2 | 013, 043, 028 | One filter pattern, searchable people pickers | `filter_sheet.dart`, `employee_picker_sheet.dart` exist |
| 3 | 041, 038, 039 | One component kit, readable type, contrast-checked colours | Design sign-off on the kit |
| 4 | 040 | No light/dark flip; dark mode for employees | After 041 |
| 5 | 044 | Uniform states | None |

### Phase 4: UX enhancements (ongoing)
| Issues | Expected impact | Dependencies |
|---|---|---|
| 025, 027, 029 | Faster, less error-prone data entry | Form engine changes |
| 008, 009, 035, 033, 056 | Action-first admin dashboard with honest numbers | None |
| 010, 046, 047, 048 | HR and manager lists that respect position and scale | Server-side employee filters (046) |
| 020, 021, 023, 032, 036, 045 | Steadier attendance and profile screens, offline awareness | `connectivity_plus` (032) |
| New: swipe to approve, bulk approve for overtime, "who's off" calendar while applying for leave | Fewer taps for approvers, fewer clashes | After 001 |

### Phase 5: Premium polish
| Issues | Expected impact |
|---|---|
| 022, 058 | Punch and approval feel confirmed: animation, haptics, in-place status change |
| 049–055, 057 | Clean copy, icons and edge cases |
| Skeleton-to-content cross-fades, Hero transition from list row to detail, a celebratory state on "nothing waiting" | Perceived speed and finish |

### Suggested acceptance checks per phase
* Every journey in §4 re-counted on a 360×640 device at 1.0× and 1.3× text, with each tap count at or below the "Recommended" figure.
* TalkBack pass on Home, Attendance, Leave apply and Approvals: every control announced with a role and label.
* `grep -c "Color(0x" lib` and `grep -c "fontSize: " lib` decrease each phase. Phase 3 ends with literals only inside `core/theme/`.

---

## 6. Open items to verify on a device

1. The fold position of the Home punch button and of the admin "Pending Approvals" panel (MOB-UX-008, 050).
2. Filter-bar height on the Leave and Requests lists at 1.3× text (013).
3. `RequestStatusChip` orange-on-tint contrast (039).
4. Roster and calendar grid usability at 360 dp (048).
5. Splash behaviour on a dead network (057).
6. Whether the keyboard covers the submit button on the longest forms (027).
