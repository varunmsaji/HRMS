# Employee mobile: final audit

Status: **approved baseline pending sign-off** · 2026-10-30 · Documentation only. No application, backend, schema or API file was modified.

Supersedes the audit, inventory and decision sections of [EMPLOYEE_MOBILE_UI_UX.md](EMPLOYEE_MOBILE_UI_UX.md). Companions: [API and permission matrix](EMPLOYEE_MOBILE_FINAL_API_AND_PERMISSION_MATRIX.md) · [Redesign specification](EMPLOYEE_MOBILE_FINAL_REDESIGN_SPECIFICATION.md) · [Implementation plan](EMPLOYEE_MOBILE_FINAL_IMPLEMENTATION_PLAN.md) · [Design system](EMPLOYEE_MOBILE_FINAL_DESIGN_SYSTEM.md).

---

## 1. Scope and method

The prior programme exists as one combined file (`EMPLOYEE_MOBILE_UI_UX.md`: inventory, audit, design system, redesign, plan). It was read in full and each load-bearing claim was re-checked against source: `apps/mobile/lib` (router, shell, theme, repositories, attendance, leave, profile, requests, payroll, tests) and `apps/api/src/hrms/modules` (organisation seeds, attendance, leave, employee, payroll routers and services). Claims that could not be checked are listed as open items (§8), not carried forward as fact.

Out of scope, unchanged: the company dashboard, administrator resource screens, pay-run processing, rosters, company registration (`/register`), and any backend work.

---

## 2. Reconciled issue register

### 2.1 Why the earlier counts disagreed

| Source | Critical / High | Cause |
|---|---|---|
| Audit §6 table | 5 / 11 | Listed a fifth critical (leave balances) |
| Audit §6 "precise count" | 4 / 12 | Moved balances to High and added "assignment ids" to High, but its list of 12 names 10 G-ids plus 2 text items |
| Audit §4 priority column | P0 = 5 (G1, G3, G4, G5, G14), P1 = 9, P2 = 1 | `P0..P2` is *delivery priority*, not severity, but was summarised as if it were |

Both counts mixed two different things (severity and delivery order) and neither matched the table beneath it.

### 2.2 Rubric (applied to every row, no exceptions)

**Severity** (how bad for the employee):
* **Critical**: blocks or misdirects the employee's primary daily task, or exposes the wrong product.
* **High**: the task works but the screen behaves or reads like an admin tool, hides data, fails accessibility, or can mislead.
* **Medium**: inconsistency that makes the product feel unfinished.
* **Low**: polish.

**Delivery priority** (when to build): P0 foundation or first release, P1 core, P2 later. Priority is a plan attribute; the register carries both, separately.

### 2.3 Authoritative register (25 issues: 3 Critical, 14 High, 5 Medium, 3 Low)

Task IDs refer to the [implementation plan](EMPLOYEE_MOBILE_FINAL_IMPLEMENTATION_PLAN.md). Old IDs (G-n) are kept for traceability.

| ID | Old | Description | Screen | Sev | Why this severity | Recommended action | Acceptance criteria | Pri | Tasks |
|---|---|---|---|---|---|---|---|---|---|
| EA-01 | G3 | No employee Home. Login lands on Profile; Home tab hidden | Shell, Login | **Critical** | Navigation sends the employee to a data form instead of the workday | Add Home (reuses branch 0), `landingPathFor` → `/app/home` | Employee login opens Home; admin with `DASHBOARD.COMPANY.VIEW` still opens the dashboard; no flash of Profile | P0 | T1-01, T1-02, T1-07 |
| EA-02 | G4 | More hub lists the full administrator catalogue, searchable, unfiltered | More | **Critical** | Exposes the wrong product; employees reach 403 dead ends | Data-driven permission-filtered menu; employee sees ≤5 entries | Employee session: no Users, Payroll, Departments in list or search; `SETTINGS.USER.MANAGE` holder still sees Users | P0 | T3-01 |
| EA-03 | G5 + missing today | Attendance opens without today's status; Punch in and Punch out are equal | Attendance, Home | **Critical** | The daily task (am I in? punch) is not answered on screen | `TodayStatusPanel` + `CheckInAction` driven by D-06/D-07 | States 0–11 of API matrix §5.3 each render exactly as specified; likely action filled, other reachable | P0 | T1-04, T1-05, T1-06 |
| EA-04 | G14 | Face-status card is first, always, even when face attendance is unused | Attendance | High | Punch is still on screen, but a setup essay outranks it | Conditional face block; one caption when not set up and not required | Face not required: first filled button visible without scrolling at 360×640 | P0 | T1-06 |
| EA-05 | new (F-3) | No client guard on `/app/*`; deep link `hrms://app/app/users` or a stale push opens admin screens | Router | High | API returns 403, but employee lands on error screens; UX only, not security | Route guard redirect from a permission map | Employee deep link to any admin route lands on Home with no admin screen built | P0 | T3-01 |
| EA-06 | G1 | One card recipe for every row and section | All | High | Nothing looks more important; reads like a component demo | Flat grouped lists, one bordered surface per screen | No employee screen uses `AppCard` per row; golden diff approved | P0 | T0-05, all screens |
| EA-07 | G2 | Gradient hero on profile, day detail, leave detail, payslip | Those four | High | Dark banner on a light app; same decoration on unrelated tasks | Flat status header with tone border | `HeroCard` absent from employee render paths; HR pay-run payslip unchanged | P1 | T1-08, T2-04, T2-05, T3-05 |
| EA-08 | G6 | Type scale desktop-small (body 13–14, labels 11–12) | All | High | Hard to read on phones; weak hierarchy | Employee text theme (16/18/22/28) | Body ≥16, no text <12, tabular figures on times, money, days | P1 | T0-03 |
| EA-09 | G7 | Status colour drift: month grid uses raw `Colors.*`; `RequestStatusChip` uses raw colours at 4 px radius | Month card, requests | High | Same word, different colour; colour-only meaning | One status map (tone + glyph + word) | Month cell, leave row, correction row for "Approved" share tone and chip | P1 | T0-04, T1-05, T3-03 |
| EA-10 | new | Status colours used as chip text fail WCAG AA on their subtle fills (computed: success 3.15, warning 2.07, danger 3.08, info 2.42, on-leave 3.86, WFH 3.59) | StatusChip, month legend | High | Small text unreadable for low vision | Darker on-subtle text variants (design system §3.3) | All chip pairs ≥4.5:1 (checked in a unit test that computes ratio) | P0 | T0-04 |
| EA-11 | G8 | Every empty field prints "Not set" | Profile | High | Hides the few real values, looks unfinished | Omit empty rows | No "Not set" string in employee profile; populated email visible | P1 | T2-05 |
| EA-12 | G9 | Primary actions (Apply, Request) are extended FABs | Leave, Corrections | High | Covers content, detached from empty state | App-bar "Apply"/"Request" + empty-state button | No FAB on those screens; action reachable at 320 px | P1 | T2-01, T3-03 |
| EA-13 | G10 | Date/status/type filters always expanded above the list | Leave, Corrections, Overtime | High | List below the fold on small phones | Filter sheet + caption of active filter | First data row visible at 360×640 without scrolling | P1 | T0-06, T2-01, T3-03, T3-04 |
| EA-14 | G11 | Lavender canvas `#F3F3FE` | All scaffolds | High | Default Material tint; fights approved brand canvas | Employee canvas `#F4F6F8` via employee theme only | Admin theme object unchanged (test); employee canvas matches token | P1 | T0-02 |
| EA-15 | G15 | Own job information (designation, department, manager) is buried in a 13-tab HR record | Profile, Records | High | Wrong IA for "who is my manager" | Short profile: identity, work, contact, then Records | Profile answers joining date and work type without opening Records; see D-10 for names | P1 | T2-05, T2-06 |
| EA-16 | new in prose | Leave balances not reachable from the Leave tab | Leave | High | Apply decision is made without the balance | Balance strip on Leave (hidden in Team view) | Strip shows ≤3 types and links to Balances; `leave_decimal_parsing_test` passes | P1 | T2-01 |
| EA-17 | new in prose | Assignment tab shows raw UUIDs, and **no employee-permitted API resolves them** (API matrix §3.6) | Records | High | Unreadable, and the gap is real, not cosmetic | Never display a UUID; omit on Profile, label "Recorded by HR" on the Assignment tab (D-10) | No UUID text renders for the six id fields; HR still sees resolved labels | P1 | T2-06 |
| EA-18 | G13 | App follows device dark mode for employees | Theme | Medium | Brief wants light; but dark is a valid device preference and admin must stay unchanged | Employee surface forces light (D-04) | Employee on dark device: light tokens. Admin on dark device: unchanged dark | P1 | T0-02 |
| EA-19 | G12 | Radius mix: tokens 2–12, cards 16, dialogs 24, sheets 28, cells 10, chips 4 | Theme vs widgets | Medium | Not cut from one system | Employee radii 8 / 10 / 16 / pill | Employee components read radius tokens only | P2 | T0-02 |
| EA-20 | audit text | Public onboarding is a default scaffold | Public onboarding | Medium | First impression after an invite email | Progress track + bottom action bar, same steps | Section order, PATCH-on-continue, submit untouched | P2 | T3-07 |
| EA-21 | audit text | Profile sign-out has no confirmation (More's exists only as uncommitted work) | Profile, More | Medium | Accidental sign-out | Shared confirm dialog | Cancel keeps session on both entries | P1 | T3-02 |
| EA-22 | audit text | Overtime looks like an approval inbox | Overtime | Medium | Read-only data in admin chrome | Flat list, no create, filter sheet | No create/approve control for employee | P2 | T3-04 |
| EA-23 | audit text | Splash tagline size | Splash | Low | Cosmetic | Keep copy, size 14 | — | P2 | T3-06 |
| EA-24 | audit text | Payslip footer disclaimer styling | Payslip | Low | Cosmetic | Caption style | Copy unchanged | P2 | T3-05 |
| EA-25 | audit text | More search empty state is fine; keep | More | Low | Already adequate | Keep copy | "No matches / Try a different word." | P2 | T3-01 |

Distribution: Critical 3 · High 14 (EA-04…EA-17) · Medium 5 (EA-18…EA-22) · Low 3 · **Total 25**. Delivery priority: P0 = EA-01…EA-06, EA-10 (7); P1 = 11; P2 = 7.

Functional defect found during verification, tracked in the same register by cross-reference rather than renumbering: **F-1** (API matrix §9), regularization form always shows "Could not load the options" for an `EMPLOYEE`. Severity **High**, task T3-03, acceptance: opening the form as `EMPLOYEE` shows no error banner and a time-based request submits.

### 2.4 Every other document uses this register

Redesign spec screens cite `EA-n`; plan tasks list the `EA-n` they close; the design system cites EA-08/09/10/14/18/19. No document restates a count except by pointing here.

---

## 3. Resolution of the five identified inconsistencies

| Item | Resolution | Detail |
|---|---|---|
| 2.1 Priority count | Resolved | §2: severity and delivery priority separated, one rubric, 25 issues |
| 2.2 Theme isolation | Resolved, with one open product choice | §5 D-03/D-04/D-14, [design system §8](EMPLOYEE_MOBILE_FINAL_DESIGN_SYSTEM.md); O-01 |
| 2.3 Leave balance API | Resolved | `GET /leave-balances?employee_id=` (+ `/leave-ledger`). `/employees/{id}/leave-balances` does not exist. API matrix §4 |
| 2.4 Punch direction | Resolved | D-06: newest row of `GET /attendance/punches`; both directions always reachable; server does not enforce alternation. API matrix §5 |
| 2.5 Missing attendance data | Resolved | D-07: eleven-state table; provisional `ABSENT`/`INCOMPLETE` suppressed for today; "calculating" derived by comparing two server timestamps, never by inventing a status. API matrix §5.3 |

---

## 4. Verified architecture (what is true in code)

| Area | Fact | Source |
|---|---|---|
| Framework | Flutter, Material 3, go_router 14, Riverpod 2, Dio | `pubspec.yaml`, `app_router.dart` |
| Theme | `MaterialApp.router` sets `theme: AppTheme.light`, `darkTheme: AppTheme.dark`, no `themeMode` (device decides). Only `ui.dart:64`, `async_list_screen.dart:143`, `dashboard_screen.dart:288,722` branch on `Brightness`. `AppStatusColors` is a `ThemeExtension` with light and dark sets | `main.dart:34`, `app_theme.dart`, `app_colors.dart` |
| Brand constants | `AppBrand.navy #102A43`, `navyDeep #0B1E33`, **`blue #2563EB`** (not `#004AC6`); action blue `#004AC6` is `ColorScheme.primary` only | `app_theme.dart:21-27,41` |
| Shell | One `StatefulShellRoute.indexedStack`, four branches: `/app/dashboard`, `/app/attendance`, `/app/leave-applications`, `/app/me`. Everything else (`/app/more`, balances, corrections, overtime, payslips, all admin routes) is a **top-level route outside the shell**, so no bottom bar on those pages | `app_router.dart:134-169` |
| Employee tabs today | `showHomeTab` false ⇒ branches `[1,2,3]`, landing `/app/me` | `app_shell.dart:78-88`, `auth_state.dart:21-26`, `test/shell_tabs_test.dart` |
| Route auth | Redirect handles loading, unauthenticated, auth-only paths, and the dashboard for employees. **No permission guard on any other `/app/*` path** | `app_router.dart:56-80` |
| Deep links | `hrms://app/<path>` with no `pathPrefix`; four public token routes are tested | `AndroidManifest.xml`, `Info.plist`, `deep_link_test.dart` |
| Logout | Never throws; always clears local session | `auth_controller.dart:67-75` |
| Permissions on the client | `UserProfile.permissions` (strings) from `/auth/me`; many screens already branch on them | `auth_types.dart`, 23 files |
| Decoration widgets | `HeroCard(` is constructed in 9 files; `HeroCard` or `IconBadge` appears in 24 files | grep |

Test inventory (40 files under `apps/mobile/test`) covers shell tabs, deep links, face and punch flows, geofence, leave, requests, records, payroll, onboarding, banner. **Not run** in this pass (§1 of the API matrix).

---

## 5. Final decisions

| ID | Decision | Basis |
|---|---|---|
| D-01 | Landing: `DASHBOARD.COMPANY.VIEW` → `/app/dashboard`; else `employeeId` present → `/app/home`; else `/app/dashboard` (explanatory "no access") | Existing `landingPathFor` extended |
| D-02 | **Home reuses shell branch 0.** Branch 0 holds two `GoRoute`s (`/app/dashboard`, `/app/home`) and a redirect picks by permission. Tab order and indexes (`shellHomeBranch = 0`) do not change. A spike (T1-01) must confirm `goBranch(0, initialLocation: true)` ends on the right route; fallback is a `StatefulShellBranch.initialLocation` computed per user | Avoids re-indexing and the 5th branch |
| D-03 | **Employee surface predicate** `usesEmployeeSurface(user) = user?.employeeId != null && !user.permissions.contains(DASHBOARD.COMPANY.VIEW)`. Same condition as `showHomeTab` inverted. One function, one place (`core/auth/surface.dart`) | Matches landing and tab logic |
| D-04 | **Theme isolation by data, not by flag.** `HrmsApp` selects `theme`/`themeMode` from the predicate: employee → `AppTheme.employee` with `ThemeMode.light`; otherwise exactly today's `theme`, `darkTheme` and (absent) `themeMode`. `AppTheme.employee` is `light.copyWith(...)` plus an `EmployeeTokens` `ThemeExtension`; no second full theme | Proof: for non-employee sessions the three arguments are the identical objects, asserted by test T0-07 |
| D-05 | Leave balances use `GET /leave-balances?employee_id=` | API matrix §4 |
| D-06 | Punch state = newest `GET /attendance/punches` row; both directions always reachable | API matrix §5.2 |
| D-07 | Today-status uses the eleven-state table | API matrix §5.3 |
| D-08 | More is a data-driven list of `NavEntry(label, route, requires, surface)`; employee menu = Leave balances, Attendance corrections, Overtime, Payslips + Sign out | Redesign spec §3.4 |
| D-09 | Client route guard: a `Map<routePrefix, requiredPermission>` consulted in the existing `redirect`; failure → landing path. **UX only, never relied on for security** | F-3 |
| D-10 | **No UUID is ever displayed.** The Profile "Work" block shows only what `/employments` and `/assignments` give in readable form (joining date, pay basis, work location type); designation/department/branch/manager/shift are omitted. The Records → Assignment tab shows "Recorded by HR" for unresolved ids. Names are FP-1, not a dependency | EMPLOYEE cannot call any `ORG.*.MANAGE` list |
| D-11 | Chip and state text uses darker on-subtle colours; raw status colours remain for fills, borders, glyphs | EA-10 |
| D-12 | Regularization form: choices load per key, lazily, and a 403 on `shifts` disables only the shift-correction toggle with a caption | F-1 |
| D-13 | Self-service tab layouts (Attendance, Leave, Profile) are **one implementation shared by all roles**; employee-specific visuals come from the employee theme and `EmployeeTokens`; permission branches are preserved byte-for-byte; admin-only screens are not touched | Needs sign-off O-01 |
| D-14 | Pre-authentication screens (splash, login, forgot/reset/verify/accept-invite) keep `ThemeMode.system`; they cannot know the role. Public onboarding (`/onboarding/:token`, candidate-only) is forced light with a local `Theme` | Forcing light on login would change what administrators see |
| D-15 | `MoreAction` (grid icon) stays on administrator and dashboard app bars; on the employee surface it is replaced by the Home "More" text button and removed from Attendance, Leave, Profile | Admin behaviour unchanged |
| D-16 | The company read-only banner changes colour only for the employee surface; copy and conditions unchanged | Banner reads from theme |
| D-17 | Existing page transitions kept; no new motion packages | Prior rule retained |

---

## 6. Corrections to the prior documents

| Where | Prior statement | Correction |
|---|---|---|
| Inventory §3.4, plan, Home spec | Balances via `GET /employees/{id}/leave-balances` | `GET /leave-balances?employee_id=` |
| Inventory §3.1 | Forgot/reset/accept paths `/auth/forgot-password`, `/auth/accept-invite` | `/auth/password/forgot`, `/auth/password/reset`, `/public/account-invites/{token}/accept` |
| Design system §6.4 | Direction from `actualFirstIn`/`actualLastOut` | D-06 |
| Spec Home §4.2 | Missing today row ⇒ "Not punched in" | D-07 states 2/3/6/10 |
| Spec Home §4.5 | Needs-attention from "loaded page" | Dedicated `SUBMITTED` queries |
| Spec Profile §4.2 | Show designation/department/manager when "a readable name is on the JSON" | Never true for `EMPLOYEE` (D-10); rows omitted |
| Spec Records §4 | "Recorded by HR" on six id fields (Profile and Records) | Profile omits; Records Assignment tab labels |
| Spec Sign out §9 | "If logout throws…" | It cannot throw (`auth_controller.dart`) |
| Spec Regularization form §9 | "Choice load for shifts" as ordinary | F-1 / D-12 |
| Design system §10 | "Employee tokens alias navy and `#004AC6`" with `AppBrand.blue` | `AppBrand.blue` is `#2563EB`; action is `#004AC6` from `ColorScheme.primary` only |
| Design system §9 | "`ink`/`action` clear AA" (true) and status colours as chip text | Chip text fails AA (EA-10) |
| Design system §2.2 | `inkTertiary` for "empty-field values" | 3.66:1 on white; restricted to icons and non-essential hints |
| Spec Shell §8 | Haptic and `goBranch` unchanged | Unchanged; plus spike for the dual-route branch (D-02) |
| Plan P0-1 | `themeMode: ThemeMode.light` globally | Replaced by D-04 |
| Plan P1-1 | `landingPathFor` change alone | Also router redirect rules and `shell_tabs_test` expectation |
| Audit §3.8 / inventory | "More hub sign-out confirms first" | True only in the **uncommitted** working tree (F-5) |

---

## 7. Final employee navigation architecture (summary; full spec in redesign §3)

Four tabs for an employee-surface user: **Home · Attendance · Leave · Profile**, one `StatefulShellRoute.indexedStack`, state preserved per branch, re-tap resets the branch. Landing `/app/home`. Pushed, non-shell routes: `/app/more` (via Home), `/app/leave-balances`, `/app/regularizations`, `/app/overtime`, `/app/me/payslips`, detail and form screens. Administrators: Home = dashboard, same four tabs, same More catalogue (permission-filtered, a strict superset of today's behaviour minus entries they cannot use). A route guard redirects any `/app/*` request the user lacks permission for.

---

## 8. Remaining uncertainties and open items

| ID | Item | Status | Needed from |
|---|---|---|---|
| O-01 | **Product choice:** HR/Admin users who open Attendance, Leave or Profile see the new shared layouts (D-13) in their own theme. Alternative: keep the legacy layouts for them behind `usesEmployeeSurface` (adds three parallel code paths, ~25 % more work on T1-04, T2-01, T2-05) | **Approval required** | Product owner |
| O-02 | D-14: login screen on a dark-mode phone is dark for an employee until sign-in | Accepted unless product wants light-only login (then admins' login changes too) | Product owner |
| O-03 | `goBranch(0, initialLocation: true)` with two routes in one branch | Unproven; spike T1-01 | Engineering |
| O-04 | Whether `GET /me/payslips` returns newest first | Client sorts by `month`; confirm in T1-07 | Engineering |
| O-05 | Whether `NOT_JOINED`/`EXITED` rows ever appear for an active employee | Handled defensively | Backend (informational) |
| O-06 | Spec-form keyboard avoidance and safe areas on real devices | Not exercised; device pass in T4-08 | QA |
| O-07 | iOS permission strings and camera denial copy | Not re-verified | Engineering |
| O-08 | `GET /overtime` SELF behaviour with `employee_id` omitted | Mobile always sends it; keep | — |
| O-09 | Baseline `flutter test` result | Not run (could rewrite `pubspec.lock`) | T0-08 |
| O-10 | Regularization shift-correction: is it intended for employees at all? Web page has no such field in the file inspected | Unverified; D-12 is safe either way | Product |
| O-11 | `leave-projections` permission for `EMPLOYEE` | ◐ best-effort call, silent on failure | Engineering |

---

## 9. Counts

| Item | Count |
|---|---|
| Issues | 25 (3 / 14 / 5 / 3) |
| Employee screens and surfaces specified | 34 (S01–S34) + the excluded `/register` |
| Home widgets | 9 (H-01…H-09) |
| Implementation tasks | 43 |
| Decisions | 17 (D-01…D-17) |
| Open items | 11 |
