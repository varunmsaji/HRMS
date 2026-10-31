# Employee mobile: final design system

Status: **approved baseline pending sign-off** · 2026-10-30 · Documentation only.

Visual contract for the employee surface of `apps/mobile`. Companions: [Final audit](EMPLOYEE_MOBILE_FINAL_AUDIT.md) (issues `EA-n`, decisions `D-n`) · [Redesign specification](EMPLOYEE_MOBILE_FINAL_REDESIGN_SPECIFICATION.md) · [Implementation plan](EMPLOYEE_MOBILE_FINAL_IMPLEMENTATION_PLAN.md) · [API and permission matrix](EMPLOYEE_MOBILE_FINAL_API_AND_PERMISSION_MATRIX.md).

Direction: professional, modern, premium, light, clean, enterprise. A calm operations tool with Krewoxa identity: deep navy ink, one blue for the action the employee is here to take, white sheets on a pale grey canvas, hairline structure. Not a stack of identical rounded cards, not a gradient marketing page, not an analytics dashboard.

---

## 1. Retained brand tokens (given)

| Token | Hex | Existing source |
|---|---|---|
| Navy ink | `#102A43` | `AppBrand.navy` (`app_theme.dart:25`) |
| Action blue | `#004AC6` | `ColorScheme.primary` in `_lightScheme` (`app_theme.dart:41`). **Not** `AppBrand.blue`, which is `#2563EB` and must not be used for employee actions |
| Canvas | `#F4F6F8` | new (replaces lavender `#F3F3FE`, `surfaceContainerLow`) |
| White surface | `#FFFFFF` | `surfaceContainerLowest` |
| Border | `#E4E7EB` | new (replaces `outlineVariant #C3C6D7` for hairlines) |

---

## 2. Colour tokens (final)

### 2.1 Mapping to the Flutter `ColorScheme` (employee theme only)

The employee theme is built by the existing `AppTheme._build` with a scheme copied from `_lightScheme`; only these fields differ. **Admin schemes are untouched.**

| Token | Hex | `ColorScheme` field (employee) | Use |
|---|---|---|---|
| `ink` | `#102A43` | `onSurface` | Titles, primary text |
| `inkSecondary` | `#52606D` | `onSurfaceVariant` | Supporting text, labels |
| `inkTertiary` | `#7B8794` | extension only | Icons, non-essential hints. **Never essential text** (3.66:1) |
| `action` | `#004AC6` | `primary` (unchanged) | Primary button, selected tab, links, focus |
| `actionPressed` | `#003A9E` | extension | Pressed primary |
| `actionSubtle` | `#E8F0FE` | `primaryContainer` is **not** reused (it is `#2563EB`); extension | Selected chip, today cell, avatar |
| `canvas` | `#F4F6F8` | `surfaceContainerLow` (scaffold and app bar read this) | Behind content |
| `sheet` | `#FFFFFF` | `surface`, `surfaceContainerLowest` | Rows, forms, app bar, nav |
| `inset` | `#F7F8FA` | `surfaceContainer` | Read-only fact groups |
| `line` | `#E4E7EB` | `outlineVariant` | Dividers, input borders, nav top border |
| `lineStrong` | `#CBD2D9` | `outline` | Disabled outlines, secondary button border |
| `danger` fill | `#EF4444` | extension (`AppStatusColors.danger`) | Fills, glyphs, borders |
| `danger` text | `#B91C1C` | `error` | Error text, destructive text and filled error buttons (6.47:1 on white) |
| `errorContainer` | `#FEE2E2` | `errorContainer`, `onErrorContainer #7F1D1D` | |
| banner | `#FFFBEB` | `tertiaryContainer`, `onTertiaryContainer #102A43` | Company read-only banner recolours with **no code change** because it already reads `tertiaryContainer`. T0-02 greps other `tertiaryContainer` uses before shipping |

No drop shadows. The sticky action bar and nav bar use a 1 px `line` on top only. (`AppShell` currently adds a navy box-shadow; the employee branch removes it.)

### 2.2 Status palette

Fills, borders and glyphs use the existing `AppStatusColors.light` values unchanged. **Text on a subtle fill uses the darker "on" value**, because the raw values fail AA (computed below).

| Meaning | Fill (subtle) | Glyph / border | Text on subtle (new) | Contrast of new text |
|---|---|---|---|---|
| Success, present, approved | `#F0FDF4` | `#16A34A` Check | `#15803D` | 4.79 |
| Warning, pending, half day, late | `#FFFBEB` | `#F59E0B` Clock | `#B45309` | 4.84 |
| Danger, absent, rejected | `#FEE2E2` | `#EF4444` Cross | `#B91C1C` | 5.30 |
| Info, on duty | `#E0F2FE` | `#0EA5E9` Briefcase | `#0369A1` | 5.17 |
| On leave | `#F5F3FF` | `#8B5CF6` Calendar | `#6D28D9` | 6.48 |
| Holiday, weekly off, neutral | `#F1F5F9` | `#64748B` Dot | `#475569` | 6.92 |
| Work from home | `#F0FDFA` | `#0D9488` House | `#0F766E` | 5.25 |

Implementation: a new `EmployeeTokens.statusText(tone)`; `AppStatusColors` itself is **not** changed (admin screens keep their chips). The employee `StatusChip` path reads `statusText` when `EmployeeTokens` is present.

Rule: every status is **word + colour**; on the month grid a glyph inside the cell replaces the word and the legend carries the word.

### 2.3 Computed contrast (WCAG 2.x relative luminance; script run in this pass)

| Pair | Ratio | Verdict |
|---|---|---|
| ink on sheet / on canvas | 14.64 / 13.52 | Pass AAA |
| inkSecondary on sheet / on canvas | 6.46 / 5.96 | Pass AA |
| inkTertiary on sheet / on canvas | 3.66 / 3.38 | **Fails AA text**; icons and decorative hints only (≥3:1 non-text on sheet; not on canvas for text) |
| action on sheet / canvas / actionSubtle | 7.51 / 6.94 / 6.56 | Pass |
| white on action / actionPressed | 7.51 / 10.01 | Pass |
| danger text `#B91C1C` on white | 6.47 | Pass (the prior `#EF4444` text was 3.76: **fails**) |
| ink on warning-subtle banner | 14.12 | Pass |
| line `#E4E7EB` on white | 1.24 | Decorative divider only; **input borders use `lineStrong` `#CBD2D9`+ (1.53) plus a visible label**, and the focus ring (`action`, 1.5 px) carries state (WCAG 1.4.11 non-text 3:1 is met by the ring and by the label/text, not by the hairline) |
| status raw text on subtle | 2.07 – 3.86 | **Fail** (EA-10), replaced as in §2.2 |

A unit test (T0-04) recomputes these ratios from the token constants and fails the build under 4.5 (text) or 3.0 (non-text).

---

## 3. Typography

Inter via `google_fonts` (kept). One family. Tabular figures (`FontFeature.tabularFigures()`) on every time, day count and amount.

| Token | Size / line / weight | Tracking | Material slot (employee `TextTheme`) | Use |
|---|---|---|---|---|
| `display` | 28 / 34 / 600 | −0.2 | `headlineLarge` | One figure per screen (net pay, days left) |
| `title` | 22 / 28 / 600 | −0.2 | `headlineMedium` | Home first name, Profile name |
| `heading` | 18 / 24 / 600 | −0.2 | `headlineSmall`; **app-bar title** | Section title, app-bar title |
| `body` | 16 / 22 / 400 | 0 | `bodyLarge` | Row title, input text, paragraphs |
| `bodyStrong` | 16 / 22 / 600 | 0 | `bodyLarge` + weight | Names, leave types |
| `secondary` | 14 / 20 / 400 | 0 | `bodyMedium` | Dialog body, helper text (so Material widgets never fall below 14) |
| `caption` | 13 / 18 / 400 | 0 | `bodySmall` | Secondary row text (`inkSecondary`) |
| `label` | 13 / 18 / 600 | 0.4, uppercase | `labelMedium` | Section eyebrow, field label |
| `micro` | 12 / 16 / 500 | 0 | `labelSmall` | Chips, weekday letters. **Nothing below 12** |

Admin `TextTheme` (24/20/16/14/13/12/12/11) is untouched. Scale: respect the OS scale up to **2.0** (WCAG 1.4.4 asks 200 %). Layouts must scroll or wrap rather than clip; see §9.

---

## 4. Spacing, radius, elevation, touch

* Scale: 4, 8, 12, 16, 20, 24, 32, 40. Screen side padding 16 (20 at width ≥ 390). Between sections 24. Label-to-value 2. Stacked rows 0 with an inset divider.
* Radius: control 8 · surface 10 (rare bordered summary) · sheet/dialog 16 · pill 999. Replaces 12/16/24/28 for the employee theme only. (EA-19)
* Elevation 0 everywhere. Focus: 1.5 px `action`. Error: 1.5 px `danger` fill colour.
* **Minimum interactive size 48 × 48** (Material/Android; never below 44 for iOS). Primary buttons 48 high, full width when they are the screen's main action. Icon buttons keep a 48 hit area around a 22–24 glyph. The prior 44 is raised to 48 so one number serves both platforms.
* Bottom navigation height 64 plus safe-area inset.

---

## 5. Iconography

Material rounded/outlined glyphs only (no new package). Outlined idle, filled selected. Size 22 in rows, 24 in navigation, 20 beside chips. Colour `inkSecondary` unless the icon *is* the status. Metaphors: Home `home_outlined/home_rounded`, Attendance `fingerprint_rounded`, Leave `event_available_outlined/_rounded`, Profile `person_outline_rounded/person_rounded`, Payslips `receipt_long_outlined`, Balance `account_balance_wallet_outlined` (balance figure only). No `beach_access`. No icon in a coloured circle except initials avatars (40 list, 56 profile; `actionSubtle` fill, `action` text).

---

## 6. Components (reusable employee set)

All components read colour, radius and text from `Theme.of(context)` and, when present, `EmployeeTokens`; none hard-codes hex. They therefore render correctly in the admin theme if reused there (D-13). Location: `lib/core/widgets/employee/`.

| Component | Purpose | Depends on |
|---|---|---|
| `EmployeeTokens` (`ThemeExtension`) | inkTertiary, actionPressed, actionSubtle, inset, radii, `statusText(tone)`, spacing | `app_theme.dart` |
| `usesEmployeeSurface` | D-03 predicate | `UserProfile`, `permissions.dart` |
| `StatusMap` | attendance bucket / request status → `(Tone, glyph, label)`; the only mapping in the app for employee surfaces | `attendance_summary.dart` `attendanceBucketOf`, `toneForStatus`, `humanize` |
| `EmployeeStatusChip` | pill, 24 high, word + dot/glyph, `statusText` colour | `StatusMap`, `EmployeeTokens` |
| `EmployeeSectionHeader` | `label` style, optional trailing text button | `ui.dart` `SectionHeader` (variant, not edit) |
| `EmployeeListGroup` / `EmployeeListRow` | one `sheet` group, `radiusSurface`, inset dividers; row min 64 | tokens |
| `EmployeeStatusHeader` | replaces `HeroCard`: sheet, 3 px left border in tone, chip, key figure | `EmployeeStatusChip` |
| `TodayStatusPanel` | the single bordered surface; states 0–11 of API matrix §5.3 | `StatusMap`, `formatClockTime`, `formatMinutes` |
| `CheckInAction` | likely-action filled button + alternate text button; busy label; face/plain routing | punch controller (T1-03), face status |
| `StickyActionBar` | bottom bar: `sheet`, top `line`, 16 padding, safe area; adds list bottom padding equal to its height | — |
| `LeaveBalanceStrip` | ≤3 columns (name, figure, "n reserved"), "All balances" | `LeaveBalance` model, decimals as strings |
| `RequestRow` | generic row: title, caption, chip, chevron (leave application, correction, overtime) | `EmployeeListRow` |
| `EmployeeFilterSheet` | bottom sheet: date range, status chips, optional type; returns a value object; active-filter caption helper | `showModalBottomSheet`, bottom-sheet theme |
| `confirmDestructive` | dialog helper: title, body, Cancel + destructive; used by sign-out, discard, cancel | `AlertDialog` theme |
| `EmployeeEmptyState` | 28 px `inkTertiary` icon, heading, caption, one button | `StateMessage` structure (variant) |
| `EmployeeFormScaffold` | full-screen form chrome over existing `SpecFormScreen`: app bar, scroll, sticky submit, discard confirm | `spec_form_screen.dart` (wrap, do not fork) |
| `ProgressTrack` | 4 px linear track + "Step n of m" | onboarding |
| `SkeletonBlock` | text/line/button skeletons | `ListSkeleton` |

Reused unchanged: `InitialsAvatar`, `StateMessage` (default), `ListSkeleton`, `AppSearchField`, `AuthFormField`, `AuthScaffold` (radius and label tweaks only), `CompanyReadOnlyBanner` (recolour through theme).

Not used on the employee surface: `HeroCard`, `IconBadge` per row, `AppCard` per row, extended FAB, `RequestStatusChip` (raw colours).

### 6.1 Specs for the key components

* **Buttons.** Primary: fill `action`, white `bodyStrong`, 48 high, radius 8. Secondary: outlined `lineStrong`, ink label. Text: `action`. Destructive: text or outlined in `error`; irreversible actions (cancel approved leave) keep the **filled** error button for weight. Disabled: 40 % opacity with a visible reason where the reason is not obvious.
* **Inputs.** 48 high, radius 8, fill `sheet`, border `lineStrong`, label above (not floating), error text `caption` in `error`. `FormSpec` screens pick this up from the employee theme's `InputDecorationTheme`, so no second form engine.
* **Rows.** `sheet`, padding 16/12, title `bodyStrong`, subtitle `caption`, trailing chip or value, chevron `inkTertiary` (decorative).
* **Dialogs/sheets.** `sheet`, radius 16, title `heading`, body `secondary`, actions right-aligned; sheets have a drag handle and 16 top radius. Max dialog width 400, margin 24.
* **Loading.** Skeletons shaped like the content. A whole-screen centred spinner is never shown while a punch control could be.

---

## 7. Navigation visuals

Bottom bar: height 64 + inset, `sheet`, 1 px `line` top, no shadow, labels always visible, selected `action` weight 600, unselected `inkSecondary` 500, indicator `actionSubtle`. Labels may drop to 11 only at text scale ≥ 1.4, and the bar grows instead of clipping. "More" is a text button on Home, not a tab.

---

## 8. Theme isolation (resolves audit 2.2)

### 8.1 What the code does today

`HrmsApp` passes `theme: AppTheme.light`, `darkTheme: AppTheme.dark` and no `themeMode`, so the device decides. Only four places branch on `Brightness`: `ui.dart:64`, `async_list_screen.dart:143`, and two spots in `dashboard_screen.dart`. Everything else reads `ColorScheme`/`AppStatusColors` from the theme, which is why a theme swap is safe for shared widgets. Setting `themeMode: ThemeMode.light` globally (the prior plan, P0-1) **would** change administrators on dark phones and is rejected.

### 8.2 Decision (D-03, D-04, D-14)

```dart
// lib/core/auth/surface.dart (new)
bool usesEmployeeSurface(UserProfile? u) =>
    u != null && u.employeeId != null && !u.permissions.contains(dashboardCompanyView);

// lib/main.dart, HrmsApp.build
final employee = ref.watch(authControllerProvider.select((s) => usesEmployeeSurface(s.user)));
MaterialApp.router(
  theme: employee ? AppTheme.employee : AppTheme.light,   // admin: identical object to today
  darkTheme: AppTheme.dark,                                // unchanged
  themeMode: employee ? ThemeMode.light : ThemeMode.system, // system == today's default
  routerConfig: router,
)
```

* `AppTheme.employee` is produced by the **same** `_build` with an optional `EmployeeTokens` argument: when it is `null` the output is exactly today's `ThemeData`. When present it changes the text theme, radii, button heights, input border, dialog/sheet shapes, nav height, app-bar title and `scaffoldBackgroundColor`, and registers the `EmployeeTokens` extension. No copy of the 300-line file.
* `select` on a boolean means the `MaterialApp` rebuilds only when the surface changes (login, logout), not on every auth refresh.
* Overlays (dialogs, sheets, snackbars, pushed routes) inherit because `MaterialApp.theme` wraps the Navigator.
* Pre-authentication and public screens are not employee-surface (no user), so they keep `ThemeMode.system` exactly as today; `PublicOnboardingScreen` alone wraps itself in `Theme(data: AppTheme.employee)` because it is candidate-only.
* Admin sessions: `theme`, `darkTheme`, `themeMode` evaluate to the same values as the current code. **Proof obligation (T0-07):** a test builds `HrmsApp` for an admin and a no-employee user and asserts `MaterialApp.theme == AppTheme.light`, `darkTheme == AppTheme.dark`, `themeMode == ThemeMode.system`; a second test asserts `AppTheme._build(scheme, tokens: null)` equals the pre-refactor output on a probe widget (golden) and that `AppTheme.dark` is byte-identical.

### 8.3 Shared-widget compatibility

| Widget | Reads | Under the employee theme |
|---|---|---|
| `AppCard`, `ListRowCard` | `cardTheme`, scheme | Picks employee radius/border; HR screens never see the employee theme |
| `StatusChip` | `AppStatusColors` | Employee path adds `statusText`; the chip API is unchanged |
| `async_list_screen.dart:143` | `Brightness` | light → `surfaceContainerLowest`, as today |
| `ui.dart:64` | `Brightness` | light branch |
| `CompanyReadOnlyBanner` | `tertiaryContainer` | Becomes `#FFFBEB`/ink by scheme (D-16) |
| `DashboardScreen` | `Brightness`, `AppBrand` | Never built for an employee surface; unchanged for admins |
| `FormSpec` forms | `InputDecorationTheme` | Employee inputs, same fields and validation |

### 8.4 Risks

| Risk | Mitigation |
|---|---|
| A user gains/loses `DASHBOARD.COMPANY.VIEW` mid-session | `/auth/me` refresh changes the predicate; the theme animates; Home/dashboard redirect handles the tab |
| A manager (employee surface) opens an HR-style shared screen (Team leave, Approve) | Those render in the employee theme; permission branches and controls unchanged (verified per screen in the spec) |
| HR admin's own Attendance/Leave/Profile adopt new shared layouts | O-01 (needs sign-off). Their *theme* does not change |

---

## 9. Accessibility standards (WCAG 2.2 AA target)

| Area | Standard |
|---|---|
| Contrast | Text ≥ 4.5:1, large text (≥ 18 pt or 14 pt bold) ≥ 3:1, non-text ≥ 3:1. Enforced by the §2.3 unit test |
| Colour | Never the sole carrier of meaning: word on chips, glyph in month cells, legend lists words |
| Touch | ≥ 48 × 48, ≥ 8 between adjacent targets |
| Text scale | Verified at 1.0, 1.3, 2.0 on 320 × 640 and 390 × 844. Nothing clips; long content wraps or scrolls; the punch control stays reachable (scrolls into view; the sticky bar never exceeds 35 % of the viewport at 2.0, otherwise it becomes an in-flow button at the end of the panel) |
| Semantics | Every control has a label that includes the direction or object: "Punch in", "Punch out", "Face punch in", month cell "15 October, Present", chip "Status: Approved"; decorative icons `excludeFromSemantics` |
| Focus / order | Visual order = reading order; sticky bar last; dialogs trap focus (framework default); announce snackbars via the framework |
| Motion | Existing page transitions only; no staggered entrances. Respect `MediaQuery.disableAnimations` for any new indicator |
| Forms | Label always visible, error text under the field and announced, `autofillHints` kept, keyboard `done` advances/submits, scroll-to-error |
| Time | All clocks in company zone (never device); relative words ("yesterday") use the company date |
| Loading | Skeletons carry `semanticsLabel: 'Loading'`; busy buttons announce the phase sentence |
| Language | Sentence case, no ALL-CAPS buttons, no raw enum codes (`humanize`) |

---

## 10. What stays in code

| Existing | Decision |
|---|---|
| `AppBrand.navy/navyDeep` | Keep (splash, auth). `AppBrand.blue` is not an action colour |
| `AppStatusColors` (both sets) | Keep untouched |
| `AppRadii` | Keep for admin; employee radii live in `EmployeeTokens` |
| `AppCard`, `IconBadge`, `HeroCard`, `RequestStatusChip` | Keep for admin screens; the employee path stops using them |
| `AppTheme.dark` | Keep, unchanged, no picker added |
| Inter, Material 3, page transitions | Keep |
