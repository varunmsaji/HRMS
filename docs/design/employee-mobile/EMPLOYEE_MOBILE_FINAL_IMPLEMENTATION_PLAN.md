# Employee mobile: final implementation plan

Status: **approved baseline pending sign-off** · 2026-10-30 · **Implementation has not started and must not start without explicit approval.**

Companions: [Final audit](EMPLOYEE_MOBILE_FINAL_AUDIT.md) (`EA-n`, `D-n`, `O-n`) · [Redesign specification](EMPLOYEE_MOBILE_FINAL_REDESIGN_SPECIFICATION.md) (`S-n`, §3 navigation) · [Design system](EMPLOYEE_MOBILE_FINAL_DESIGN_SYSTEM.md) · [API and permission matrix](EMPLOYEE_MOBILE_FINAL_API_AND_PERMISSION_MATRIX.md) (`H-n`, `F-n`).

Scope: Flutter presentation, navigation visibility and tests under `apps/mobile`. **No change** to `apps/api`, `apps/web`, schemas, migrations, API contracts, attendance/leave/payroll rules or permission checks. Paths below are relative to `apps/mobile/` and are *likely* files (confirm when starting each task).

---

## 1. Phase sequence and the one justified deviation

The requested sequence is kept: **Phase 0** foundation → **Phase 1** core → **Phase 2** leave and information → **Phase 3** supporting modules → **Phase 4** quality.

Deviation, justified by repository dependencies: **T3-01 (permission-filtered More and route guard) may ship right after T0-01**, ahead of Phase 1. It depends only on permission constants, it closes EA-02 and EA-05 (the highest-risk issues), and it needs neither the theme nor Home. It is listed in Phase 3 for ownership but scheduled as **Release R1** (§5).

Plan-level corrections to the earlier plan: global `ThemeMode.light` (P0-1) is replaced by data-driven theme selection (T0-02, D-04); the punch direction rule changes (T1-03/T1-04, D-06/D-07); Home reuses branch 0 (T1-01, D-02); `LeaveBalanceStrip` and `RequestRow` move into Phase 0 so Home and Leave do not depend on each other.

---

## 2. Definition of Done (referenced by every task)

* **DoD-A (code):** merged on a branch with passing `flutter analyze` and `flutter test`; no new analyzer warnings; no change outside the task's files except tests; permission branches in shared files unchanged (diff reviewed); no backend/web file touched (CI path check).
* **DoD-B (visual):** golden images (§6.2) for the task's screens at 320×568, 360×800, 390×844, text scale 1.0 and 2.0, light and (for shared screens in admin sessions) dark; reviewed against the spec section.
* **DoD-C (device):** manual pass on one small Android, one large Android, one iPhone, using the §6.4 checklist for the task's flows.
* **Spec-conformance:** every "Acceptance" line of the cited screens (`S-n`) demonstrated by a test or recorded manual step.

"Done" in a task = the DoD levels listed in its **Done** field plus its **Acceptance**.

---

## 3. Task breakdown (43 tasks)

Priority: P0 foundation/release-critical · P1 core · P2 later. Complexity: L / M / H (days: ≈1 / 2–3 / 4+).

### Phase 0: design system foundation

**T0-01 Surface predicate, permission constants.** *Component* auth core · Deps none · P0 · L
Files: new `lib/core/auth/surface.dart`; `lib/core/auth/permissions.dart` (add `employeeView`, `employeeViewAll`, `employeeViewDocuments`, `leaveBalanceView`, `payrollPayslipViewOwn`, `payrollRunView`, any missing in redesign §3.4). Risks: constant string typos silently hide menu items → test each against the API's permission catalogue file. Tests: unit for `usesEmployeeSurface` (employee, manager, admin, no-employee, null); constants test comparing strings to a fixture copied from the seeded catalogue. Acceptance: predicate truth table matches D-03; every constant used in §3.4 exists. Done: A.

**T0-02 Employee theme and wiring.** *Theme* · Deps T0-01 · P0 · M
Files: `lib/core/theme/app_theme.dart` (`_build(scheme, {EmployeeTokens? tokens})`, `AppTheme.employee`, `EmployeeTokens extension`), new `lib/core/theme/employee_tokens.dart`, `lib/main.dart` (select + `theme`/`themeMode`). Risks: any edit to the `tokens == null` path changes admin appearance (**highest risk in Phase 0**); `tertiaryContainer` used elsewhere (grep first); rebuild flicker at login. Tests: T0-07. Acceptance: design system §8.2 verbatim; employee on a dark device renders light; admin identical. Done: A, B.

**T0-03 Employee typography.** Deps T0-02 · P0 · L
Files: `app_theme.dart` (employee `TextTheme`, app-bar title 18, tabular-figures helper in `lib/core/format.dart` or theme). Risks: shared widgets using hard-coded `fontSize` stay small → listed per screen task. Tests: theme test asserts slot sizes; text-scale golden. Acceptance: design system §3 table. Done: A, B. (EA-08)

**T0-04 Status map, chip, contrast.** Deps T0-02 · P0 · M
Files: new `lib/core/widgets/employee/status_map.dart`, `employee_status_chip.dart`; reads `attendance_summary.dart`. Risks: two mapping sources drifting → one function, replace callers in later tasks. Tests: table-driven map test; **contrast unit test computing ratios from token constants** (fails under 4.5 text / 3.0 non-text). Acceptance: design system §2.2–2.3; every attendance bucket and request status maps to one tone+glyph+word. Done: A, B. (EA-09, EA-10)

**T0-05 Primitives.** Deps T0-02, T0-03 · P0 · M
Files: `lib/core/widgets/employee/` — `section_header`, `list_group`/`list_row`, `status_header`, `empty_state`, `skeleton_block`, `leave_balance_strip`, `request_row`. Risks: duplicating `ui.dart` behaviour → variants only, `ui.dart` not edited. Tests: widget tests per component incl. text scale 2.0 and long text; strip with decimal strings. Acceptance: design system §6. Done: A, B. (EA-06, EA-07)

**T0-06 Interaction components.** Deps T0-02, T0-03 · P0 · M
Files: `employee/filter_sheet.dart`, `confirm_dialog.dart` (`confirmDestructive`), `sticky_action_bar.dart`, `form_scaffold.dart`, `progress_track.dart`. Risks: form scaffold must wrap `SpecFormScreen`, not fork it (`form_spec_test` stays green); sticky bar vs keyboard. Tests: filter sheet returns value and clears; sticky bar adds bottom padding; keyboard inset test. Acceptance: spec S17 interaction, S16 filter. Done: A, B.

**T0-07 Theme-isolation proof.** Deps T0-02 · P0 · M
Files: `test/theme_isolation_test.dart`. Tests: (1) for admin and no-employee users `MaterialApp.theme/darkTheme/themeMode` equal today's; (2) `_build(tokens:null)` equals pre-change golden output; (3) `AppTheme.dark` golden unchanged; (4) employee theme has `EmployeeTokens`, admin does not; (5) shared widgets (`AppCard`, `StatusChip`, `async_list_screen`) render in both themes without throwing. Acceptance: all five pass in CI; this test is required for every later PR touching `app_theme.dart`. Done: A.

**T0-08 Test harness and baseline.** Deps none (start first) · P0 · M
Files: `test/support/` (surface-size and text-scale helpers, golden helper, fake clock, fake punches/days fixtures, extend `fake_api_client.dart`), CI job. First step: run the full suite on a clean checkout and record failures as the **baseline** (never run in this audit). Risks: goldens flaky across platforms → pin Linux CI font. Tests: harness self-test. Acceptance: baseline report committed to docs; golden command documented. Done: A.

### Phase 1: core employee experience

**T1-01 Router, landing, Home route.** *Navigation* · Deps T0-01 · P0 · M
Files: `lib/core/router/app_router.dart`, `lib/features/auth/state/auth_state.dart`. Add `/app/home` to branch 0; cross-redirects; `landingPathFor` → `/app/home`. **Spike first (O-03):** with a stub Home, confirm `goBranch(0, initialLocation:true)` and cold start end on `/app/home` for employees and `/app/dashboard` for admins; fallback per-user `initialLocation`. Risks: redirect loops; admin landing regression; deep link to `/app/dashboard` as employee. Tests: router tests for all four user types, cold start, tab re-tap, login → landing. Acceptance: S08, S01, S02, S06 acceptance lines. Done: A. (EA-01)

**T1-02 Shell: tabs, icons, back.** Deps T1-01, T0-02 · P0 · M
Files: `lib/features/shell/app_shell.dart`, `test/shell_tabs_test.dart`. Employee Home icon; remove navy shadow on employee surface; `PopScope` Back→Home; banner recolour verified by theme only. Risks: `visibleShellBranches` contract changes; update test for the intended new behaviour only. Tests: updated `shell_tabs_test`, back-navigation widget test, banner test unchanged. Acceptance: redesign §3.3, S08, S09. Done: A, B.

**T1-03 Punch controller extraction.** *Behaviour-preserving refactor* · Deps T0-08 · P0 · H
Files: new `lib/features/attendance/state/punch_controller.dart`; `attendance_self_screen.dart`, `face_punch_card.dart`. One Riverpod notifier keyed by `employeeId` owns: phase, `_unconfirmedPunch` (per direction), face-required flag, location plan, plain and face punch, snackbar events. Risks: **double submit / lost idempotency key** across two screens; face-required race; behaviour drift. Mitigation: refactor first with the existing screen unchanged and all current punch tests green, then add Home. Tests: existing `punch_idempotency_test`, `attendance_self_mandatory_face_test`, `face_punch_card_test`, `punch_location_flow_test`, `location_capture_test`; new: two consumers share one in-flight punch; retry after status 0 reuses the key for the same direction only. Acceptance: no test edits except import paths. Done: A.

**T1-04 Today-state resolver and punch-state read.** Deps T0-08 · P0 · M
Files: new `lib/features/attendance/domain/today_state.dart` (pure function), repository provider for `listPunches` with the D-06 window and `per_page=20`. Risks: UTC-window mistakes; overnight shifts; `calculated_at` parse. Tests: table test for all 12 states of API matrix §5.3, including provisional ABSENT today suppressed, stale row → "being calculated", `CONFIG_ERROR`, punches failure fallback, midnight in IST and a negative-offset zone, forgotten OUT older than 24 h. Acceptance: each state's "Never" column enforced. Done: A. (EA-03)

**T1-05 TodayStatusPanel and CheckInAction.** Deps T0-05, T1-03, T1-04 · P0 · M
Files: `employee/today_status_panel.dart`, `check_in_action.dart`. Risks: wrong likely action; face vs plain routing; busy labels. Tests: widget per state; both directions reachable; face-required shows face labels only; text scale 2.0 does not clip. Acceptance: design system §6, S10/S11 acceptance. Done: A, B.

**T1-06 Attendance screen.** Deps T1-05, T0-06, T1-07 · P0 · H
Files: `attendance_self_screen.dart`, `face_punch_card.dart` (visual), `attendance_widgets.dart`. Sticky bar; conditional face block; grouped 14-day list; remove More icon on employee surface only. Risks: face-required gating regression; bottom padding hides last row; HR users' tab. Tests: all S11 preserve tests; golden. Acceptance: S11. Done: A, B, C. (EA-03, EA-04)

**T1-07 Month card.** Deps T0-04 · P1 · M
Files: `attendance_month_card.dart`. Monday-first labels, glyph cells, legend, semantics, today ring, no raw `Colors.*`. Risks: bucket mapping change → use `attendanceBucketOf` unchanged. Tests: `attendance_summary_test`, `attendance_screens_test` unchanged; new semantics + 320 px cell-size test. Acceptance: S11 month spec. Done: A, B. (EA-09)

**T1-08 Attendance day detail.** Deps T0-05 · P1 · M
Files: `attendance_day_detail_screen.dart`. Remove `HeroCard`; collapsed calculation details; keep HR buttons. Tests: employee no Recompute; HR sees it; expand shows version. Acceptance: S12. Done: A, B. (EA-07)

**T1-09 Employee Home.** Deps T1-01, T1-05, T0-05 · P0 · H
Files: new `lib/features/home/presentation/employee_home_screen.dart` (+ providers per H-n). Parallel independent fetches; per-widget failure; permission-omit. Risks: over-fetching (≈8 calls), leaking previous user's data, calling forbidden endpoints. Tests: `fake_api_client` asserts zero calls to `/dashboards/*`, `/holiday-calendars`, `/employees` list; partial failure; missing permission omits widget; logout A / login B no leakage. Acceptance: S10, API matrix §6. Done: A, B, C. (EA-01, EA-16)

**T1-10 Location dialogs chrome.** Deps T0-06 · P2 · L
Files: `punch_location_flow.dart`. Radius/type only. Tests: existing flow tests unchanged. Acceptance: S15. Done: A.

### Phase 2: leave and employee information

**T2-01 Leave list.** Deps T0-05, T0-06 · P1 · M
Files: `leave_applications_screen.dart`. Remove FAB, add app-bar Apply, filter sheet, strip (Mine only). Risks: dropping a query param; Team/on-behalf regression for managers. Tests: `leave_applications_test`; new: sheet applies `date_from/date_to/application_status`; manager fixture still sees Team and "Apply on behalf". Acceptance: S16. Done: A, B. (EA-12, EA-13, EA-16)

**T2-02 Leave balances.** Deps T0-05 · P1 · L
Files: `leave_balances_screen.dart`. Tests: `leave_decimal_parsing_test`; adjust holder sees Encash/Adjust; no-employee path makes no call. Acceptance: S20, API matrix §4. Done: A, B.

**T2-03 Apply leave form.** Deps T0-06 · P1 · M
Files: `leave_application_form.dart`, thin wrapper over `spec_form_screen.dart` via `EmployeeFormScaffold`. Tests: `form_spec_test`, `leave_applications_test` validation cases; discard confirm; self body has no `employee_id`. Acceptance: S17. Done: A, B, C.

**T2-04 Leave detail and cancel.** Deps T0-05, T0-06 · P1 · M
Files: `leave_application_detail_screen.dart`. Risks: cancel-rule drift. Tests: cancel matrix (submitted, approved-before-start, approved-started, with/without permission); reviewer buttons for non-applicant. Acceptance: S18, S19. Done: A, B. (EA-07)

**T2-05 Profile.** Deps T0-05, T3-02 (dialog; may use interim confirm) · P1 · H
Files: `profile_screen.dart`, `employee_overview.dart`. Omit-empty, Work from readable fields only (D-10), no UUIDs. Risks: losing a field HR relies on in Overview (HR still has S22). Tests: new `profile_screen_test` (populated email, null gender hidden, no "Not set", Work omitted on 403, sign-out confirm). Acceptance: S21. Done: A, B, C. (EA-11, EA-15, EA-21)

**T2-06 Records screen.** Deps T2-05 · P1 · H
Files: `employees_screen.dart` (`EmployeeDetailScreen`), `employee_record_sections.dart`. "Recorded by HR" for six id fields (display only), tab type tweaks, Overview reuse. Risks: shared with HR; any payload change. Tests: `employee_record_sections_test`, `employee_record_actions_test` unchanged; new: EMPLOYEE sees no write action, label rule on six fields only. Acceptance: S22. Done: A, B. (EA-17)

**T2-07 Documents, Salary, Attendance tabs.** Deps T0-05 · P1 · M
Files: `employee_documents_panel.dart`, `employee_salary_panel.dart`, `employee_attendance_panel.dart`. Visual only. Tests: no Upload/Assign/Calculate for employee; URL-less row not tappable. Acceptance: S23–S25. Done: A, B.

### Phase 3: supporting modules

**T3-01 Permission-filtered More and route guard.** Deps T0-01 (visual part optionally T0-05) · **P0, Release R1** · M
Files: `lib/features/shell/settings_hub_screen.dart` (builds on the **uncommitted** change, F-5), new `lib/core/router/route_guard.dart`, `app_router.dart`. `NavEntry` list from redesign §3.4; filter by `anyOf`; employee flat group; guard in `redirect`. Risks: **hiding a manager's existing access** (the gates marked ◐ must be confirmed against each backend router before merge); redirect loops. Tests: new `settings_hub_test` (employee: no Users/Payroll/Departments, search "Users" empty; `SETTINGS.USER.MANAGE` sees Users; manager still sees Team attendance; sign-out confirm), guard tests for every prefix in §3.5, deep-link test `hrms://app/app/users` as employee lands on Home. Acceptance: S33, redesign §3.4–3.5. Done: A, C. (EA-02, EA-05, EA-25)

**T3-02 Shared sign-out dialog.** Deps T0-06 · P1 · L
Files: `settings_hub_screen.dart`, `profile_screen.dart`. Reconcile with the uncommitted dialog. Tests: cancel/confirm from both entries. Acceptance: S34. Done: A.

**T3-03 Corrections list, detail, form.** Deps T0-05, T0-06, T2-03 · P1 · H
Files: `lib/core/requests/request_screens.dart`, `request_config.dart`, `lib/features/attendance/domain/request_resources.dart`, `lib/core/forms/choice_sources.dart`/`spec_form_screen.dart` (per-key, lazy, 403-tolerant loading, **F-1**). Replace `RequestStatusChip` use on the employee path with `EmployeeStatusChip`. Risks: shared `RequestListScreen` serves HR (Team, approve, on-behalf); `loadChoices` is used by many HR forms: the per-key tolerance must be opt-in per field. Tests: `request_screens_test` unchanged for HR; new: EMPLOYEE opens form with `/shifts` returning 403 → no banner, time request submits, toggle disabled with caption; filter sheet keeps `employee_id`, `date_*`, `request_status`, `request_type`; status colours equal leave's. Acceptance: S26–S28. Done: A, B, C. (EA-09, EA-12, EA-13, F-1)

**T3-04 Overtime.** Deps T3-03 · P2 · L
Files: `request_screens.dart` (`overtimeConfig`). Tests: no create/approve for employee; reviewer keeps decisions; AUTO_APPROVED success tone. Acceptance: S29–S30. Done: A, B. (EA-22)

**T3-05 Payslips list and payslip.** Deps T0-05 · P1 · M
Files: `my_payslips_screen.dart`, `payslip_screen.dart`, `async_list_screen.dart` (refresh only if absent). Risks: HR payslip shares the widget. Tests: `payroll_test` (net, PDF entry points), self endpoint used, HR route unchanged, display scales at 2.0. Acceptance: S31–S32. Done: A, B, C. (EA-07, EA-24)

**T3-06 Auth sheet and splash.** Deps T0-02 · P2 · M
Files: `auth_scaffold.dart`, login/forgot/reset/verify/accept-invite screens, `splash_screen.dart`. Radius 16, labels above, copy and error branches unchanged. Risks: these screens are shared pre-login (admin too): changes are structural only, colours stay (D-14). Tests: login error-branch tests (add if absent: 401, 423, 429, unverified). Acceptance: S01–S06. Done: A, B. (EA-23)

**T3-07 Public onboarding.** Deps T0-06 · P2 · M
Files: `public_onboarding_screen.dart`. Progress track + bottom bar, forced light. Tests: `public_onboarding_screen_test`, `onboarding_form_spec_test`. Acceptance: S07. Done: A, B, C. (EA-20)

**T3-08 Face enrollment and liveness chrome.** Deps T0-06 · P2 · M
Files: `face_enrollment_screen.dart`, `face_liveness_capture_screen.dart`. Camera behaviour untouched. Tests: `face_pose_tracker_test`, `face_liveness_capture_test`; denial copy. Acceptance: S13–S14. Done: A, C.

### Phase 4: quality and final polish

**T4-01 320 px pass** (Home, Attendance month, Leave filters, Profile, forms) · Deps phases 1–3 · P1 · M. Tests: 320×568 goldens, no overflow. Done: A, B.
**T4-02 Text scale** 1.0/1.3/2.0 on Home, Attendance, Payslip, Balances · P1 · M. Tests: no clipping, punch control reachable. Done: A, B.
**T4-03 Semantics** TalkBack/VoiceOver labels (punch, month cells, chips, panel state sentence) · P1 · M. Tests: semantics finders; manual screen-reader pass. Done: A, C.
**T4-04 Loading/error/partial-failure audit** (Home, Attendance, Profile Work, Leave strip) · P1 · M. Tests: each failure injected via fake client. Done: A.
**T4-05 Safe area and keyboard** (sticky bars, forms, onboarding bar, dialogs) · P1 · M. Tests: inset golden; manual with gesture bar and notch. Done: A, C.
**T4-06 Copy pass** against spec strings · P2 · L. Tests: string-presence tests for empty states. Done: A.
**T4-07 Visual regression suite** (§6.2) · P1 · M. Done: A, B.
**T4-08 Device pass** (§6.4 matrix) · P1 · M. Done: C. Resolves O-06, O-07.
**T4-09 Performance** (Home fan-out, rebuild counts, frame timing on a low-end device, image/PDF memory) · P2 · M. Tests: rebuild-count test on Home; profile run attached. Done: A, C.
**T4-10 Permission regression suite** (§6.3) · P0 for R1 subset, P1 rest · M. Done: A.

---

## 4. Dependency graph and parallelism

```
T0-08 ───────────────────────────────┐ (start first; baseline)
T0-01 ─┬─ T0-02 ─┬─ T0-03 ─┬─ T0-05 ─┬────────────────────── all visual tasks
       │         │         └─ T0-06 ─┤
       │         ├─ T0-04 ───────────┤
       │         └─ T0-07 (gate for any app_theme.dart change)
       ├─ T1-01 ─ T1-02
       └─ T3-01 (R1)
T0-08 ─┬─ T1-03 ─┐
       └─ T1-04 ─┴─ T1-05 ─ T1-06 ─(with T1-07)
T1-01 + T1-05 + T0-05 ─ T1-09
T0-06 ─ T2-03 ─ T3-03 ─ T3-04
T2-05 ─ T2-06            T0-06 ─ T3-02 ─ (T2-05 final)
Phase 4 after phases 1–3 (T4-10 R1 subset after T3-01)
```

**Must precede:** T0-02 before T0-03/04/05/06/07; T0-05/06 before every screen task; T1-03 and T1-04 before T1-05; T1-01 before T1-09; T2-05 before T2-06; T2-03 before T3-03; T0-07 before any later change to `app_theme.dart`.

**Can run independently (after their dependencies):**
* Track A attendance/Home: T0-08 → T1-03 ‖ T1-04 (no UI dependency; can start on day 1) → T1-05 → T1-06 ‖ T1-07 → T1-09.
* Track B leave: T2-01 ‖ T2-02 ‖ T2-04, then T2-03.
* Track C profile: T2-05 → T2-06 ‖ T2-07.
* Track D supporting: T3-05, T3-06, T3-07, T3-08 are mutually independent after Phase 0.
* Track R1: T0-01 → T3-01 ‖ T4-10 (subset): no dependency on any visual work.

---

## 5. Releases

| Release | Contents | Why it stands alone |
|---|---|---|
| **R1: stop the leak** | T0-01, T3-01 (+ T3-02 interim), T4-10 subset, T0-08 | Removes EA-02/EA-05 with no visual or navigation-shape change |
| **R2: foundation** | T0-02…T0-07 | Invisible to admins (proved by T0-07); employee gets light canvas/type |
| **R3: workday** | T1-01…T1-10 | Home, Attendance, punch refactor; the first employee-visible change |
| **R4: leave & profile** | Phase 2 | |
| **R5: supporting** | T3-03…T3-08 | |
| **R6: polish** | Phase 4 | Gate for calling the programme done |

---

## 6. Test strategy

### 6.1 Functional regression (existing tests are the safety net; list = what each phase must re-run)

| Area | Tests that must stay green | New coverage |
|---|---|---|
| Login, logout, session restore | `token_refresh_test`, `api_error_handling_test`; login widget tests | Add if absent: login 401/423/429/unverified; logout → `/login`; restore → Home (employee) |
| Role access | `shell_tabs_test` (updated only for employee Home) | Landing per user type (T1-01) |
| Attendance punches | `punch_idempotency_test`, `attendance_self_mandatory_face_test`, `face_punch_card_test`, `attendance_screens_test`, `attendance_summary_test` | `today_state` 12-state table; shared controller; both directions reachable |
| Face attendance | `face_pose_tracker_test`, `face_liveness_capture_test`, `face_punch_result_test` | Face-required routes both buttons to face flow |
| Geofence | `punch_location_flow_test`, `location_capture_test`, `punch_location_payload_test` | REQUIRED/OPTIONAL/DISABLED matrix through the new controller |
| Leave | `leave_applications_test`, `leave_decimal_parsing_test` | Filter-sheet params, cancel matrix, strip decimals |
| Regularization / Overtime | `request_screens_test` | F-1 (403 on `/shifts`), body shape, UTC conversion |
| Profile / records | `employee_record_sections_test`, `employee_record_actions_test` | No UUID text, omit-empty, Work omission |
| Documents / payslips / PDF | `payroll_test` | Share/print entry points, self endpoint only |
| Onboarding | `public_onboarding_screen_test`, `onboarding_form_spec_test` | Section order unchanged |
| Forms | `form_spec_test` | Wrapper does not alter validation |
| Banner | `company_read_only_banner_test` | Recolour via theme |

Contract tests: `contract_fixtures_test` plus new fixtures for `GET /attendance/punches` (ordering), `GET /leave-balances` response.

### 6.2 Visual regression

Goldens (Linux CI, pinned fonts) for every employee screen state in the spec: sizes 320×568, 360×800, 390×844, 600×900 (tablet width); text scale 1.0 and 2.0; light employee theme; **admin screens in light and dark** for every shared screen to prove no change (compare to baseline taken before Phase 0); keyboard visible on forms; safe-area insets (notch 44, gesture 34); navigation transitions smoke-tested (no overflow during push/pop). Device settings "dark mode on" is a theme test: employee remains light, admin follows system.

### 6.3 Permission regression (do not rely on UI hiding)

1. **Navigation:** employee More shows exactly the §3.4 employee rows; search cannot reveal others.
2. **Deep links:** `hrms://app/app/users`, `/app/payroll/pay-runs`, `/app/employees`, `/app/departments`, `/app/shifts`, `/app/setup` as employee → Home, with the admin screen never built (build counter).
3. **Direct navigation:** `context.go/push` to each guarded prefix.
4. **Shared screens:** employee sees no Team, on-behalf, Approve, Reject, Encash, Adjust, Recompute, Keep leave, Upload, Assign, Calculate today, Edit, Terminate; the same screens in manager/admin fixtures still show them.
5. **Buttons and actions:** fake API returns 403 for each admin endpoint; UI shows the server message, no crash, no retry loop.
6. **Guard bypass:** with the guard disabled in a test, every admin endpoint still returns 403 from the fake (documents that the API, not the UI, is the authority). Backend authorization is covered by the existing API test suite and is out of scope here.
7. **Session isolation:** log out A, log in B: no A data in Home/Profile/Leave providers.

### 6.4 Manual device checklist (T4-08)

Small Android (≈360×640), large Android, iPhone; for each: login → Home → punch in (plain) → location refused (REQUIRED) → punch out; face-required tenant: cancel and complete a face punch; overnight-shift fixture; apply leave (end before start; half day on range); balances from Leave; correction without `/shifts` error; More as employee and as admin; sign-out cancel/confirm; payslip share/print sheet; TalkBack/VoiceOver on Home and Attendance; text size largest; dark mode on (employee light, admin dark); rotate (no overflow); airplane mode on punch (idempotency).

---

## 7. Risks and mitigations

| Risk | Where | Mitigation |
|---|---|---|
| Admin appearance changes by accident | T0-02 | Single `_build` path, `tokens == null` identical, T0-07 gates every theme PR |
| Punch refactor double-submits or drops idempotency | T1-03 | Behaviour-preserving refactor first; existing tests unchanged; shared in-flight guard |
| Misreporting attendance (e.g. "Absent" today) | T1-04 | Pure resolver with 12-state table test; provisional rule |
| Hiding a manager's legitimate menu access | T3-01 | `anyOf` lists; ◐ gates verified against routers before merge; manager fixtures |
| Redirect loops / admin landing regression | T1-01, T3-01 | Router tests per user type; spike |
| Shared widgets (HR) change | T2-*, T3-* | Variants in `employee/`; HR tests unchanged; admin goldens |
| `loadChoices` change breaks HR forms | T3-03 | Opt-in tolerance per field |
| Home over-fetch (≈8 calls) | T1-09 | Parallel, independent, cached per refresh; T4-09 measurement |
| Previous user's data visible after switching accounts | T1-09 | Providers keyed by `employeeId`; isolation test |
| Uncommitted work in `settings_hub_screen.dart` | T3-01/T3-02 | Commit or stash the owner's change first; build on top (F-5) |
| Goldens flaky | T0-08 | Pinned fonts, Linux-only baselines |
| O-01 unresolved when T1-06/T2-01/T2-05 begin | Phase 1–2 | Default D-13; if rejected, add the legacy branch behind `usesEmployeeSurface` (≈ +25 % on those three tasks) |

---

## 8. Approval gates

1. Sign-off on this baseline and open items O-01 (shared layouts for HR users) and O-02 (login stays system-themed).
2. Start **T0-08 baseline** and **T0-01**, then **R1**.
3. Each release R1…R6 requires its DoD levels and the permission regression subset.

No source file has been changed to produce this plan.

---

## 9. Implementation status

| Date | Gate | Done | Report |
|---|---|---|---|
| 2026-10-30 | Phase 0 | T0-01…T0-07; T0-08 partly (baseline, harness; no CI job) | Phase 0 review |
| 2026-10-30 | Phase 1 (first slice) | T1-01, T1-03, T1-04, T3-01, per-route theme scope (EmployeeThemeScope). Not started: T1-02 (shell icons/back), T1-05…T1-10 | Phase 1 review; `PUNCH_BEHAVIOUR.md` |
| 2026-10-30 | Phase 1 (second slice) | T1-02, T1-05, T1-06 (see limits), T1-07, T1-08, T1-09; payroll boundary (`kPayrollInRelease = false`); pushed-route theme (`pushKeepingTheme`); permission matrix test. Not started: T1-10. T3-03 investigated only: blocked on a backend decision, see `T3-03_SHIFTS_DEPENDENCY.md` | Phase 1 second review |
| 2026-10-30 | Phase 1 (third slice) | T3-03 (mobile-only form fix, no backend change), T1-06, T1-08, T1-10 completed; calendar touch targets; history pagination hardening (`listPunches`); goldens with Inter (`test/goldens/screens/`); Android emulator verification harness (`test/device/`) | Phase 1 third review |

Approved changes to this plan: O-01 became a **per-route theme scope** (administrators with an employee record get the employee tokens only on Attendance, Leave and Profile; the global administrator theme is unchanged); O-02 login and the other shared auth screens stay system-themed.
