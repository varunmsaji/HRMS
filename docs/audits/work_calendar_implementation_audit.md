# Work calendar — implementation audit and plan

Audit date: 2026-10-27. Branch `main`, HEAD `436a2e5e35b97ae65b27f9553e2317e9b7f6f7b0`. The working tree already contains a large set of unrelated modified and untracked files (onboarding email, observability, attendance, mobile, and others). Those files were not reset, stashed, or edited for this audit.

This document records what the code does and a phased plan. It does not implement that plan. Tests listed below were **not executed**. “Covered” means a test file names the case; it does not mean the test was observed passing in this session.

Labels: **VERIFIED** (seen in source), **PARTIALLY VERIFIED** (main path seen, a caller remains untraced), **NOT FOUND**, **UNVERIFIED**, **PRODUCT DECISION REQUIRED**.

---

## 1. Executive summary

The product already has a tenant-owned workforce calendar. It is not a single month view and it is not a hardcoded Monday–Friday rule used by leave and attendance.

What exists (**VERIFIED**):

- Reusable **holiday calendars** and dated **holidays** (`holiday_calendar`, `holiday`).
- Typed **weekly-off patterns** and rules (`weekly_off_pattern`, `weekly_off_rule`).
- A **work calendar** that composes those plus one-off **exceptions** (`work_calendar`, `work_calendar_holiday_calendar`, `calendar_exception`).
- Effective-dated **policy assignments** from employee down to company (`policy_assignment`).
- One pure classifier, `classify_work_calendar_date`, and one resolver, `CalendarResolutionService`, in `apps/api/src/hrms/modules/organisation/calendar_resolution.py`.
- Leave day-counting and attendance day evaluation both call `resolve_for_employee`.
- Admin list/form screens for work calendars, holiday calendars, weekly-off patterns, shifts, and a roster month grid.
- Shifts have draft/publish and effective dates. Work calendars do not; a holiday or pattern edit is live for the next resolution.

What does **not** exist (**VERIFIED** unless noted):

- No holiday list, weekly-off pattern, or work calendar is created when a company registers.
- No public-holiday import or seed was found.
- Company profile `working_days_pattern` defaults to Monday–Friday working and Saturday–Sunday off, and **leave/attendance do not read it**.
- Without a `WORK_CALENDAR` assignment, resolution returns `config_incomplete=True`. Leave submit fails. Attendance records `CONFIG_ERROR`. There is no silent “treat as working” default in that resolver.
- There is no combined month calendar of workdays, holidays, weekly offs, and leave. Admin UX is separate settings lists.
- `HR_ADMIN` is not granted `ORG.CALENDAR.MANAGE`, `ORG.HOLIDAY.MANAGE`, or `ORG.SHIFT.MANAGE`. Those sit on `COMPANY_ADMIN`.
- Approved leave days are stored on `leave_application_day` at submit time and are not recomputed when the calendar later changes (**PARTIALLY VERIFIED**: no recalculation caller was found). Unlocked attendance can be recalculated from the calendar as it stands at calculation time.
- Half-day weekly offs are a fraction on the calendar and are treated as a working-style day by attendance, but leave treats any `WEEKLY_OFF` as a non-working day and ignores the fraction.

The smallest useful next step is not a new calendar schema. It is a read-only month view over the existing resolver, plus an explicit empty/unassigned state, and a product decision on whether `company.working_days_pattern` should be retired, mirrored into a real work calendar, or left as profile metadata only.

---

## 2. Current architecture

**VERIFIED.** The calendar is a combination of database-backed definitions, an assignment chain, and a shared classifier. It is not a frontend-only display and not one hardcoded rule.

```
Company profile.working_days_pattern     (JSONB, Mon–Fri default)
        used by company-profile completeness and the company settings form
        NOT used by leave or attendance

HolidayCalendar (kind, state, validity) ──< Holiday (one date row)
WeeklyOffPattern ──< WeeklyOffRule (weekday, nth, parity, off_fraction)
WorkCalendar ── links holiday calendars in sort order
             ── optional weekly_off_pattern_id
             ── CalendarException (SPECIAL_WORKING, SHUTDOWN, SUBSTITUTE_HOLIDAY, CANCEL_HOLIDAY)
PolicyAssignment (WORK_CALENDAR | WEEKLY_OFF | …)
        scope: EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH > LEGAL_ENTITY > COMPANY
        effective_from / effective_to

CalendarResolutionService.resolve_for_employee
        → classify_work_calendar_date
        → DayType: WORKING | WEEKLY_OFF | HOLIDAY | SPECIAL_WORKING | SHUTDOWN

LeaveApplicationService._compute_day_breakdown   (submit; stores leave_application_day)
Attendance day evaluation                          (stores calendar_day_type on attendance_day)
Payroll                                            (reads frozen attendance LOP, not the calendar)
```

Architecture comments point at `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md`. Open product flags named in code: **PD-CAL-1** (optional/restricted holidays are working days unless `restricted_holidays_are_off_by_default`) and **PD-CAL-2** (a holiday on a weekly off stays a weekly off; no automatic substitute).

Shifts and rosters are a second schedule layer. `ShiftVersion.operates_on_holiday` / `operates_on_weekly_off` and `ShiftRoster` can mark a person expected to work on an off day, or force a roster week-off, without rewriting `calendar_day_type` (`attendance/calculation.py` comments at the roster override).

---

## 3. Current-state implementation matrix

| Capability | Status | Evidence |
|---|---|---|
| Database holiday catalogue | **VERIFIED** implemented | `HolidayCalendar`, `Holiday` |
| Weekly offs as rules, not a hardcoded weekend | **VERIFIED** implemented, only after an admin creates a pattern and assigns a calendar | `WeeklyOffRule`, `evaluate_weekly_off` |
| Company-wide default calendar on signup | **NOT FOUND** | `register_company` inserts the company and roles; no calendar rows |
| Mon–Fri profile default | **VERIFIED** stored, **not** the leave/attendance rule | `_default_working_days_pattern` |
| Branch-specific holiday calendar | **VERIFIED** possible via `PolicyAssignment` scope `BRANCH` | `test_calendar_resolution_branch_scope_beats_company` |
| Employee / department / shift scope | **VERIFIED** in the precedence tuple | `_PRECEDENCE_SCOPES` |
| Effective-dated assignment | **VERIFIED** | `PolicyAssignment.effective_from` / `effective_to`; close-previous on new insert |
| Draft vs published work calendar | **NOT FOUND** for work calendars | Shifts have `DRAFT`/`PUBLISHED`. Work calendars are active rows |
| Preview impact on future leave | **NOT FOUND** | — |
| Combined month calendar UI | **NOT FOUND** | Admin pages are lists. Roster page is a shift grid |
| Holiday seed / import | **NOT FOUND** | No seed of holiday rows in registration or a holiday import module located |
| Recurring holiday rule (e.g. “25 Dec every year”) | **NOT FOUND** | Each `Holiday.date` is one row |
| Optional / restricted / company / public types | **VERIFIED** | `_HOLIDAY_TYPES` |
| Half-day weekly off | **VERIFIED** in the classifier; **inconsistent** in leave vs attendance | `off_fraction`; see section 9 |
| Special working day | **VERIFIED** | `CalendarException` `SPECIAL_WORKING` |
| Admin CRUD | **VERIFIED** for calendars, holidays (no date change, deactivate instead of delete), patterns, exceptions, assignments | Organisation router |
| Who can edit | **VERIFIED** `COMPANY_ADMIN` via `ORG.CALENDAR.MANAGE` and `ORG.HOLIDAY.MANAGE`. `HR_ADMIN` grant list does not include those codes | `organisation/service.py` registration |

---

## 4. File and symbol inventory

### Backend — definitions and resolution

| Path | Symbols |
|---|---|
| `apps/api/src/hrms/modules/organisation/models.py` | `Shift`, `ShiftVersion`, `ShiftBreak`, `ShiftDutyBlock`, `HolidayCalendar`, `Holiday`, `WeeklyOffPattern`, `WeeklyOffRule`, `WorkCalendar`, `WorkCalendarHolidayCalendar`, `CalendarException`, `PolicyAssignment` |
| `apps/api/src/hrms/modules/organisation/calendar_resolution.py` | `classify_work_calendar_date`, `evaluate_weekly_off`, `CalendarResolutionService.resolve_for_employee`, `classify_date_for_work_calendar` |
| `apps/api/src/hrms/modules/organisation/schemas.py` | Create/read/update models from about line 1466; constants `_HOLIDAY_CALENDAR_KINDS`, `_HOLIDAY_TYPES`, `_WEEKLY_OFF_PATTERN_KINDS`, `_CALENDAR_EXCEPTION_TYPES`, `_SCOPE_TYPES` |
| `apps/api/src/hrms/modules/organisation/repository.py` | `HolidayCalendarRepository`, `HolidayRepository`, `WeeklyOffPatternRepository`, `WorkCalendarRepository`, `CalendarExceptionRepository`, `PolicyAssignmentRepository` |
| `apps/api/src/hrms/modules/organisation/service.py` | `create_holiday_calendar` and the matching work-calendar, pattern, exception, and assignment methods; `register_company` |
| `apps/api/src/hrms/modules/organisation/router.py` | Routes listed in section 11 |
| `apps/api/src/hrms/modules/organisation/permissions.py` | `ORG.CALENDAR.MANAGE`, `ORG.HOLIDAY.MANAGE`, `ORG.SHIFT.MANAGE` |
| `apps/api/src/hrms/core/db/models/identity.py` | `Company.working_days_pattern`, `_default_working_days_pattern` |

### Leave, attendance, payroll

| Path | Role |
|---|---|
| `apps/api/src/hrms/modules/leave/service.py` | `_compute_day_breakdown` (about lines 2290–2354) |
| `apps/api/src/hrms/modules/leave/models.py` | `LeaveApplicationDay`, `LeaveYearSetting`, `LeavePolicy` (`sandwich_rule_enabled`) |
| `apps/api/src/hrms/modules/attendance/service.py` | Builds day inputs and calls `resolve_for_employee` (about lines 3704–3722) |
| `apps/api/src/hrms/modules/attendance/calculation.py` | `evaluate_day`; holiday/weekly-off/roster handling |
| `apps/api/src/hrms/modules/attendance/models.py` | `ShiftRoster`; `AttendanceDay.calendar_day_type` |
| `apps/api/src/hrms/modules/attendance/resolution.py` | Reuses assignment walking for attendance policies |
| `apps/api/src/hrms/modules/payroll/engine.py` | Prorates from attendance paid/LOP figures, not from a calendar read found in this audit |

### Frontend and mobile

| Path | Role |
|---|---|
| `apps/web/src/app/app/work-calendars/page.tsx` and `[id]/page.tsx` | List and edit work calendars. Permission `ORG.CALENDAR.MANAGE` |
| `apps/web/src/app/app/holiday-calendars/page.tsx` and `[id]/page.tsx` | Holiday catalogues. Permission `ORG.HOLIDAY.MANAGE` |
| `apps/web/src/app/app/weekly-off-patterns/page.tsx` and `[id]/page.tsx` | Weekly-off rules |
| `apps/web/src/app/app/shifts/` | Shift master and version publish |
| `apps/web/src/app/app/rosters/calendar/page.tsx` | Month grid of **roster entries**, not holidays and leave |
| `apps/web/src/components/attendance/dashboard/month-calendar.tsx` | Attendance month display |
| `apps/web/src/components/company/company-profile-form.tsx` | Working-day checkboxes bound to `working_days_pattern` |
| `apps/web/src/components/layout/nav-items.ts` | Settings links for shifts, work calendars, holiday calendars, weekly offs; primary nav link for rosters. Items are not permission-filtered |
| `apps/mobile/lib/core/router/app_router.dart` | `/app/holiday-calendars`, `/app/weekly-off-patterns`, `/app/work-calendars` as generic resource lists |
| `apps/mobile/lib/features/organisation/presentation/day_type_lookup.dart` | `GET /work-calendars/{id}/day-type` |

---

## 5. Database model and relationship inventory

All of these rows carry `company_id`. RLS is enabled on the holiday expansion migration (`apps/api/alembic/versions/20260818100000_holiday_expand.py` enables RLS on `holiday`). Other calendar tables were introduced in the workforce-calendar migrations named in model comments (`20260818090000_holiday_calendar_expand`, `20260818120000_work_calendar`). This audit did not re-read every RLS policy line. **PARTIALLY VERIFIED** that tenant queries also filter `company_id` in repositories (seen on `HolidayRepository.list_for_calendars` and `get`).

| Model / table | Purpose | Ownership | Relationships | HR can edit? | Effective dates | Constraints seen in code/tests | Consumers |
|---|---|---|---|---|---|---|---|
| `company.working_days_pattern` | Profile JSON, seven weekday flags | Company | None | Yes, company profile, `ORG.COMPANY.MANAGE` | No history | At least one working day (`count_working_days`) | Profile completeness only |
| `holiday_calendar` | Named catalogue. `kind`: NATIONAL, REGIONAL, COMPANY, LOCATION. Optional `state_code`, `valid_from`, `valid_to` | Company | Company | `ORG.HOLIDAY.MANAGE` | Validity columns exist | Unique `(company_id, code)` when code set (`HolidayCalendarCodeAlreadyExistsError`) | Linked from work calendars |
| `holiday` | One date | Company | `calendar_id` → holiday calendar; optional `replaced_holiday_id` | Same permission. Date immutable. Deactivate via `is_active`. **No DELETE route** | The date is the fact. No version table | One active holiday per calendar per date (`test_holiday_duplicate_active_date_rejected`) | Classifier via `list_for_calendars` (active, not deleted) |
| `weekly_off_pattern` / `weekly_off_rule` | Rule set. Kinds FIXED_WEEKDAYS, NTH_WEEKDAY, ALTERNATE, CUSTOM. Weekday is Python Monday=0 | Company | Rules → pattern | `ORG.CALENDAR.MANAGE`. Update replaces rules | Pattern row has `version`, not a date range | Shape must match kind (`WeeklyOffRuleInvalidError`) | Classifier; optional override on `ShiftVersion.weekly_off_pattern_id` |
| `work_calendar` | Composition | Company | Optional `weekly_off_pattern_id`; flag `restricted_holidays_are_off_by_default` | `ORG.CALENDAR.MANAGE`. Deactivate blocked while assigned | `version` optimistic field. Not a published version chain | Composition must reference same-company calendars/patterns | Resolver |
| `work_calendar_holiday_calendar` | Ordered join | Company | Both ids | Replaced with the work calendar update | `sort_order` | — | First list wins the holiday display name |
| `calendar_exception` | One date override | Company | `work_calendar_id` | Create and limited PATCH. Date and type immutable after create | The exception date | One active exception per calendar per date | Classifier, highest precedence |
| `policy_assignment` | Which policy applies to a scope | Company | `policy_id` polymorphic (no FK). `leave_type_id` FK for leave policies | `ORG.CALENDAR.MANAGE` for calendar kinds | `effective_from` / `effective_to`. New row closes the previous | Overlap rejected; parallel insert has a single winner (`test_parallel_policy_assignments_have_a_single_winner`) | Resolver, leave policy resolution, attendance policy resolution |
| `shift` / `shift_version` | Clock times, night/cross-midnight, operates-on-holiday/weekly-off | Company | Version → shift; optional weekly-off pattern | `ORG.SHIFT.MANAGE`. Publish closes the previous version | `effective_from` / `effective_to`, DRAFT/PUBLISHED, GiST overlap (model comment) | One open draft | Attendance engine |
| `shift_roster` | Per employee per date shift or week-off override | Company | Employee, optional shift | Attendance roster permissions (not re-listed here) | The roster date | Date conflict error | `evaluate_day` roster override |
| `leave_application` / `leave_application_day` | Request and the days actually deducted | Company, employee | Days stored with `fraction`, `half`, `is_sandwich_generated` | Leave permissions | The application dates are the snapshot | Period must be open at submit | Balances, attendance leave projection |
| `leave_year_setting` | Leave year, not the work week | Company | — | Leave year UI | Leave year bounds | Separate from work calendar | Balance periods |
| `attendance_day` | Calculated day | Company, employee | `calendar_day_type` stored | Recalculated while the period is unlocked | The attendance date | Frozen when the period locks (`attendance/service.py` freeze comments) | Payroll LOP |
| `attendance_period` | Lock boundary | Legal entity / company | — | Lock permission stays with company admin (HR grant comment) | Period dates | Close freezes summaries | Payroll input |

`Holiday.is_working` is a column. `HolidayData` passed into the classifier has `date`, `name`, `holiday_type`, `is_paid` only. **VERIFIED:** classification does not read `is_working`. A working day that is also a named holiday is the type `WORKING_HOLIDAY`.

`HolidayCalendar.valid_from` / `valid_to` are **not** applied in `_load_ordered_holidays`. An out-of-window calendar that is still linked and active still contributes its holidays. **VERIFIED** gap between the columns and the resolver.

Holiday and schedule rows are tenant-owned records created by API calls. They are not hardcoded into leave math, not inserted by registration, and not generated for a region. **VERIFIED.**

---

## 6. Existing default-calendar behaviour

**VERIFIED** for registration and the profile default. **NOT FOUND** for a seeded holiday calendar.

`register_company` (`organisation/service.py` from line 288) creates the company, admin user, permissions, and `COMPANY_ADMIN` / `HR_ADMIN` roles. It grants `ORG.CALENDAR.MANAGE` and `ORG.HOLIDAY.MANAGE` to the company-admin role (lines 563–565). It does not insert `holiday_calendar`, `weekly_off_pattern`, `work_calendar`, or `policy_assignment`.

`Company.working_days_pattern` defaults, when the ORM default runs, to Monday–Friday working and Saturday–Sunday off (`identity.py` `_default_working_days_pattern`). Registration’s `insert_company` payload in the snippet read does not set `working_days_pattern`, so the column default applies if the database column has that default (migration `20260807140000_company_profile_fields.py` adds the column). **PARTIALLY VERIFIED:** the ORM default is explicit; this audit did not re-read the SQL default expression in that migration.

That JSON is used by:

- `company_profile_is_complete` (at least one working day).
- Company profile read/update (`schemas.py` `count_working_days`).
- The web company form.

It is **not** referenced from `calendar_resolution.py`, `leave/service.py`, or `attendance/calculation.py`. A new company can look “Monday to Friday” on the profile screen and still have **no** resolvable work calendar. `test_calendar_resolution_config_incomplete_without_assignment` encodes the fail-closed result.

There is no preview, no draft calendar, and no retained history of `working_days_pattern` edits beyond the audit log if the company update records one (**UNVERIFIED** whether every profile save writes an audit row; the calendar assignment path does use insert-new/close-previous).

An unconfirmed default must not be presented as published policy. The current resolver already refuses to invent `WORKING`. A future UI should show “no work calendar assigned” rather than painting the profile JSON as the live schedule.

---

## 7. Holiday-management findings

**VERIFIED** lifecycle:

1. Admin with `ORG.HOLIDAY.MANAGE` creates a `HolidayCalendar` (`POST /holiday-calendars`).
2. Admin adds holidays (`POST /holiday-calendars/{id}/holidays`). Fields: date, name, `holiday_type` (default `PUBLIC`), `is_paid` (default true), `is_working` (default false, unused by the classifier), optional `region_note`, optional `replaced_holiday_id`.
3. List supports a year filter and pagination (`test_holidays_paginate_within_year_filter`).
4. `PATCH /holidays/{id}` can change name, type, paid flag, working flag, region note, replacement, and `is_active`. It cannot change `date` or `calendar_id` (`HolidayUpdate` docstring; `test_holiday_update_cannot_change_date`).
5. There is no `DELETE /holidays/{id}`. Removal is deactivation.
6. Deactivating a calendar is supported (`test_deactivate_holiday_calendar`).
7. A work calendar must link the catalogue before classification sees those dates.
8. A `PolicyAssignment` of kind `WORK_CALENDAR` must cover the employee and date.

Categories that exist:

| Kind | Meaning in `classify_work_calendar_date` |
|---|---|
| `PUBLIC`, `COMPANY` | Hard holiday → `HOLIDAY`, unless it falls on a weekly off, in which case `WEEKLY_OFF` with `holiday_on_weekly_off` |
| `OPTIONAL`, `RESTRICTED` | Working day, name surfaced, unless `restricted_holidays_are_off_by_default` (PD-CAL-1) |
| `WORKING_HOLIDAY` | `WORKING` but named |
| Exception `SHUTDOWN` | Wins over everything for that date |
| Exception `SPECIAL_WORKING` | Wins; a weekly off becomes a working day |
| Exception `SUBSTITUTE_HOLIDAY` | Becomes `HOLIDAY` type `SUBSTITUTE` |
| Exception `CANCEL_HOLIDAY` | Drops the holiday match; weekly off still applies |
| Weekly off | Not a holiday row |

Public holidays are **not** automatically non-working for every employee. They apply only through a linked work calendar and an assignment that resolves for that person. Optional holidays are working days by default. **VERIFIED.**

Duplicates: a second **active** holiday on the same calendar and date is rejected. Two calendars may both contain the same date; the work calendar’s sort order picks the display name (`test_first_calendar_wins_display_name_on_tie`).

Past holidays: the date cannot be patched. Deactivating an active row changes future classification immediately. Already stored leave days are a snapshot. **PRODUCT DECISION REQUIRED** whether deactivating a past holiday should be blocked when a locked payroll period covers that date. The code does not do that today (**NOT FOUND** as a guard on holiday PATCH).

Employees: no employee-scoped holiday list endpoint was found. They see effects through leave rejection/acceptance and attendance day type, not a holiday catalogue. **NOT FOUND** as a dedicated employee holiday API.

Imports: **NOT FOUND**. Nothing in registration overwrites admin holidays because nothing seeds them.

`kind` on the calendar (NATIONAL, REGIONAL, COMPANY, LOCATION) is a label plus optional `state_code`. Resolution does not filter by the employee’s state. **VERIFIED.** A regional calendar applies only if an admin links it and assigns the work calendar to the right scope.

---

## 8. Leave integration

**VERIFIED** counting function: `LeaveApplicationService._compute_day_breakdown`.

Rules in that function:

- Every date in the inclusive range is resolved with `CalendarResolutionService.resolve_for_employee`.
- `config_incomplete` or a null day type raises `LeaveApplicationCalendarNotResolvedError`. It does not assume a working day.
- `WORKING` and `SPECIAL_WORKING` consume leave.
- `WEEKLY_OFF`, `HOLIDAY`, and `SHUTDOWN` do not, unless the sandwich rule is on.
- Sandwich (`LeavePolicy.sandwich_rule_enabled`, model default `True` for new drafts): a non-consuming day **strictly between** two consuming days **inside the same application** becomes a deducted day with `is_sandwich_generated`. No look at a neighbouring application.
- Half day: only when `half_day` is set and the range is a single date. Fraction `0.50`. A multi-day range is full days or sandwich days (schema comment near `LeaveApplicationCreate`).
- `off_fraction` from a half-day weekly off is **not** read. If the classifier returns `WEEKLY_OFF`, the whole day is non-consuming.
- Submit also requires an effective `LEAVE_POLICY` assignment, employment covering the dates, an open attendance period, and combination rules.
- Days are inserted as `leave_application_day` rows. Approval projects them into attendance (`leave_day_projection_id` comment). Cancel is a leave action (LD-13), not a calendar edit.

| Question | Finding |
|---|---|
| Single shared day service? | **VERIFIED** yes: `CalendarResolutionService` / `classify_work_calendar_date`. Leave does not reimplement weekday math |
| Same schedule as attendance? | **VERIFIED** both call `resolve_for_employee`. They then **interpret** half weekly offs differently (section 9) |
| Public holidays excluded from deduction? | **VERIFIED** when the resolved type is `HOLIDAY` and sandwich does not pull the day in |
| Weekly offs excluded? | **VERIFIED** the same way, including half-day weekly offs (entire day skipped) |
| Holiday added after approval? | Stored days stay. No recalculation job was found. **PARTIALLY VERIFIED** |
| Schedule change after approval? | Same. Future **new** applications see the new assignment because resolution is as-of the leave date |
| Balance reversal | Cancel path exists on leave; this audit did not re-read every ledger line. **PARTIALLY VERIFIED** |
| Leave year | `LeaveYearSetting` is separate. A request that crosses the leave year is **UNVERIFIED** in this pass beyond the date-range breakdown, which does not split on leave-year boundaries inside `_compute_day_breakdown` |
| Branch holidays | Follow the assignment chain. A branch assignment beats company (`test_calendar_resolution_branch_scope_beats_company`) |

Sandwich tests exist: `test_submit_sandwich_rule_generates_weekend_day`, `test_submit_without_sandwich_rule_skips_weekly_off` in `apps/api/tests/integration/modules/leave/test_leave_application.py`. Not run here.

There is no second leave-day counter in payroll. Payroll uses attendance LOP after the period is frozen.

---

## 9. Attendance and shift integration

**VERIFIED** path: attendance evaluation loads timezone (shift version, else branch, else `company.timezone`), builds the schedule window (including cross-midnight shifts), then `resolve_for_employee`.

`evaluate_day` (`calculation.py`):

- `calendar_day_type is None` → `CONFIG_ERROR` (`no_calendar_resolved`). Not absent, not present.
- A roster week-off override with no punches → `NOT_EXPECTED`, and does not change the stored calendar type.
- `HOLIDAY`, `WEEKLY_OFF`, or `SHUTDOWN`, or a roster week-off, means the person is not expected, unless the shift `operates_on_holiday` or `operates_on_weekly_off`.
- `_is_half_weekly_off`: if type is `WEEKLY_OFF` and fraction is 0.50, the engine treats the day as `WORKING` for the rest of evaluation. **This disagrees with leave**, which skips the whole `WEEKLY_OFF` day.
- Unpaid holiday types can affect pay classification (`holiday_is_paid`, `_DAILY_WAGE_PAID_HOLIDAY_TYPES`). Details of wage types were not fully expanded. **PARTIALLY VERIFIED.**
- Overnight: `Shift.is_cross_midnight` / `ShiftVersion.is_cross_midnight` and duty-block `crosses_midnight` exist. The attendance date is the roster/calendar date passed into `resolve_schedule_window`, not “whichever civil date the punch falls on” as a second holiday lookup. **PARTIALLY VERIFIED:** the window helper was not line-read in full. A holiday is resolved for `target_date` only.

Historical attendance: comments and the freeze branch say a frozen decision is not rewritten, and summaries regenerate only while the period is unlocked. A holiday edit can change the **next** calculation of an unlocked day. A locked period’s payroll inputs stay on the frozen summary. **VERIFIED** as the stated service behaviour around `frozen` in `attendance/service.py`. Not re-proven by running a test.

Payroll does not call `classify_work_calendar_date`. It consumes `lop_days` from the attendance summary (`payroll/service.py` around the summary read). Changing a calendar after lock does not, by that path, rewrite a closed run. **PARTIALLY VERIFIED** (no calendar import in `payroll/` was found).

Dependency map:

| Rule | Leave submit | Attendance evaluate | Payroll | Company profile UI |
|---|---|---|---|---|
| `working_days_pattern` | No | No | No | Yes |
| Assigned work calendar + holidays + weekly offs | Yes | Yes | Indirect, via frozen attendance | No |
| Calendar exception | Yes, via classifier | Yes | Indirect | Admin exception API |
| Shift operates-on-off-day | No | Yes | Indirect | Shift editor |
| Roster week-off | No | Yes | Indirect | Roster calendar |
| Sandwich policy | Yes | No (uses leave projection instead) | Indirect | Leave policy |

Conflicting “working day” definitions:

1. Profile JSON versus assigned work calendar.
2. Leave versus attendance on `WEEKLY_OFF` with `off_fraction` 0.50.
3. Optional holiday: working for leave and attendance unless the work-calendar flag says otherwise. Easy to misread as a company holiday in a UI that only shows the name.

---

## 10. Frontend and mobile findings

**VERIFIED** from the pages read and the route list.

There is no single “Work calendar” month that mixes holidays and leave. Settings pages:

- `/app/work-calendars` — table, create dialog, link to detail. Empty, loading, and error states exist (`EmptyState`, `LoadingState`, `ErrorState`). Create is hidden without `ORG.CALENDAR.MANAGE`. The nav item itself is always shown.
- `/app/holiday-calendars` — same pattern, permission `ORG.HOLIDAY.MANAGE`.
- `/app/weekly-off-patterns` — create and edit rules.
- `/app/shifts` — versions and publish dialog.
- `/app/rosters/calendar` — month grid of roster cells.
- `/app/company` — working-day checkboxes. This is the only “pick the week” control, and it does not publish a work calendar.
- Attendance `month-calendar.tsx` — attendance statuses, not the admin holiday catalogue.

Web validation tests exist for the forms (`validate-work-calendar.test.ts`, `validate-holiday.test.ts`, `validate-holiday-calendar.test.ts`, `validate-weekly-off-pattern.test.ts`, shift and roster validators). They check client payloads, not a rendered month of mixed events.

Mobile uses the same REST resources for the three catalogues and a day-type lookup. It does not add a different calendar engine. **VERIFIED** from `app_router.dart` and `day_type_lookup.dart`. A full visual pass of the Flutter resource screens was not done. **PARTIALLY VERIFIED.**

Missing relative to the requested UX: legend, pending versus approved leave on the same grid, branch filter, “published vs unconfirmed” banner, preview, effective-date review of a calendar edit. Assignment effective dates exist in the API; this audit did not find a dedicated preview screen.

Reuse: keep the existing forms. A month view should call existing day-type or a new range endpoint, and existing leave-application list APIs. Do not replace `WorkCalendar`.

---

## 11. API and permissions inventory

All routes are under `/v1` on the organisation router unless noted. Auth is the tenant bearer. Scope is the token company. Repositories filter `company_id`.

| Method and path | Permission | Purpose | Tests (not run) |
|---|---|---|---|
| `GET/POST /holiday-calendars` | `ORG.HOLIDAY.MANAGE` | List, create | `test_workforce_calendar.py` |
| `GET/PATCH/DELETE /holiday-calendars/{id}` | same | Read, update, deactivate | same, cross-tenant 404, permission denial |
| `GET/POST /holiday-calendars/{id}/holidays` | same | List (year, page), create | pagination tests |
| `GET/PATCH /holidays/{id}` | same | Read, update metadata or deactivate | date immutability |
| `GET/POST /weekly-off-patterns` | `ORG.CALENDAR.MANAGE` | List, create with rules | shape mismatch test |
| `GET/PATCH/DELETE /weekly-off-patterns/{id}` | same | Read, replace rules, deactivate | — |
| `GET/POST /work-calendars` | same | List, create composition | invalid composition |
| `GET/PATCH/DELETE /work-calendars/{id}` | same | Read, update, deactivate if unassigned | cross-tenant, permission |
| `GET /work-calendars/{id}/day-type` | same | Classify one date for that calendar, not for an employee | `test_work_calendar_day_type_classification` |
| `GET/POST /work-calendars/{id}/exceptions` | same | List, create | duplicate date |
| `PATCH /calendar-exceptions/{id}` | same | Limited update | cannot change date or type |
| `GET/POST /policy-assignments` | same (router line 1310 area uses calendar manage; **PARTIALLY VERIFIED** for every query variant) | List, create effective-dated scope | overlap, branch beats company, parallel winner |
| `GET /calendar-resolution` | `ORG.CALENDAR.MANAGE` | Employee + date → day type or `config_incomplete` | `test_calendar_resolution_config_incomplete_without_assignment` |
| Shift and shift-version routes | `ORG.SHIFT.MANAGE` | Including publish | shift page tests on the web |
| Leave application routes | Leave permissions | Submit uses the resolver internally | sandwich tests |
| Attendance day routes | Attendance permissions | Day stores `calendar_day_type` | not enumerated here |

**NOT FOUND:** a month range calendar, publish-calendar, preview-impact, calendar change history beyond audit rows and assignment close-previous, holiday DELETE, employee self-service holiday feed.

Validation highlights: extra fields forbidden; holiday type and exception type enums; weekly-off rule shape; same-company foreign keys (`test_calendar_parents_must_exist_in_this_company`, `test_scope_target_must_exist_in_this_company`).

Frontend consumers: the web pages in section 10. Mobile resource lists and `day_type_lookup.dart`.

Permission gap: an HR administrator role cannot call these routes. Hiding a button is irrelevant; the API returns 403. **VERIFIED** from the HR grant loop, which lists attendance read, leave approval, payroll subset, and onboarding, and explicitly leaves shift/roster/policy management with company admin.

---

## 12. Tenant security and data integrity

**VERIFIED** controls that were read:

- Create paths check holiday calendars, weekly-off patterns, and scope targets belong to the company.
- Cross-tenant get returns 404 (`test_work_calendar_cross_tenant_404`, `test_holiday_calendar_cross_tenant_404`).
- Holiday list pagination is isolated (`test_calendar_exceptions_cross_calendar_isolation` is per calendar inside a tenant; cross-tenant holiday tests exist for the calendar resource).
- `policy_id` has no database foreign key (polymorphic). The service validates the id. A bug in that check could point an assignment at another company’s id; the tests say the scope target and the calendar parent must exist in this company. **PARTIALLY VERIFIED** that the service check is the backstop, not a FK.
- Deactivating a work calendar that still has assignments is blocked (`WorkCalendarDeactivationBlockedError`).
- Holiday date uniqueness is partial on active rows, so a deactivated date can be recreated. That is history-by-deactivation, not a second live row.

**NOT FOUND:** a guard that stops a holiday edit when the date sits in a locked payroll period.

Orphans: closing an assignment leaves the old row with `effective_to` set (insert-new/close-previous). Deleting a company is outside this audit. Branch delete behaviour versus assignments was **not** fully traced. **UNVERIFIED** whether a branch delete is blocked while a `BRANCH` policy assignment exists.

RLS: holiday table policy is enabled in the expand migration. This audit did not diff every later calendar migration for `FORCE ROW LEVEL SECURITY`. Treat “RLS on every calendar table” as **PARTIALLY VERIFIED**.

---

## 13. Historical data and effective dates

| Mechanism | Present? |
|---|---|
| Assignment `effective_from` / `effective_to` | **VERIFIED** |
| Shift version publish | **VERIFIED** |
| Work-calendar draft/publish | **NOT FOUND** |
| Holiday date immutability | **VERIFIED** |
| Holiday type/name editable in place | **VERIFIED**, and the next resolution sees it |
| Leave day snapshot | **VERIFIED** rows written at submit |
| Attendance freeze at period lock | **VERIFIED** in service comments and freeze branch |
| Silent rebuild of approved leave | **NOT FOUND** |
| Silent rebuild of locked attendance | **NOT FOUND** as an allowed path; unlocked days can be recalculated |
| Audit | Calendar creates go through audit helpers (`holiday_calendar_to_audit_dict` and siblings). A full history UI was **NOT FOUND** |

Recommended policy, matching the code’s fail-closed and snapshot habits:

1. A newly published assignment affects dates on or after `effective_from` for **new** resolutions only.
2. Already stored `leave_application_day` rows stay. The admin is shown a list of future approved leave that would classify differently; changing them is an explicit leave adjustment, not a side effect of saving a holiday.
3. Unlocked attendance may be recalculated; locked periods and payroll runs stay on the frozen summary.
4. Closed payroll is not recomputed by a calendar save.
5. Preview is a dry-run of `classify_work_calendar_date` over a range plus a diff of future leave applications. It must not write.
6. Reversal of an assignment is close-the-row or a new assignment with a later `effective_from`, which already exists. Reversal of a holiday is deactivate plus a new row, which already exists. There is no one-click rollback of a live metadata edit.
7. History is the closed assignment row, the deactivated holiday, and audit log entries. Do not add a second version table until those are insufficient.

---

## 14. Tests and coverage gaps

Not run. Classification from source:

| Area | Coverage | Result |
|---|---|---|
| Pure weekday, nth, alternate, half-day fraction, holiday precedence, exceptions, PD-CAL-1, PD-CAL-2 | `apps/api/tests/unit/modules/organisation/test_calendar_resolution.py` | Present, **not executed** |
| CRUD, day-type, assignment overlap, branch precedence, cross-tenant, permissions, registration grants | `test_workforce_calendar.py` | Present, **not executed** |
| Holiday and exception pagination | `test_workforce_calendar_pagination.py` | Present, **not executed** |
| Assignment concurrency | `test_policy_and_calendar_rules.py` | Present, **not executed** |
| Leave sandwich and skip weekly off | `test_leave_application.py` | Present, **not executed** |
| Half-day weekly off in **leave** deduction | **Not covered** (no test name found) | Gap |
| Holiday added after approval does not rewrite days | **Not covered** | Gap |
| Profile `working_days_pattern` ignored by resolver | **Not covered** as an explicit test | Gap |
| Combined calendar UI | Web form unit tests only | Gap |
| Payroll period blocks a calendar edit | **Not covered** | Gap |
| `Holiday.is_working` ignored | **Not covered** | Gap |
| `valid_from` / `valid_to` ignored by resolver | **Not covered** | Gap |

No test was marked failing because none was run.

---

## 15. Target architecture proposal

Do not add a parallel calendar. The split the product wants is already the table split.

| Piece | Needed? | Reuse | Schema | Dependents | Behaviour change | Security | Migration |
|---|---|---|---|---|---|---|---|
| Work schedule | Already `WeeklyOffPattern` + optional shift | Reuse | No for phase 1 | Leave, attendance | None if profile JSON stays display-only | Existing permission | None |
| Holiday definitions | Already `HolidayCalendar` + `Holiday` | Reuse | No | Resolver | None | `ORG.HOLIDAY.MANAGE` | None |
| Assignment | Already `PolicyAssignment` | Reuse | No | Resolver | None | `ORG.CALENDAR.MANAGE` | None |
| Employee effective schedule | Already `resolve_for_employee` | Reuse | No | Leave, attendance | Fix half-day interpretation only if product says so | Internal | None |
| Display API | **Missing** range view | New read endpoint calling the resolver | No | New UI | Read-only | Decide who may view. Today only calendar managers can call resolution | None |
| Admin workflow | Mostly present as separate screens | Add a month shell and an empty state | No until preview persistence is required | — | Do not auto-seed holidays | Keep company admin unless product grants HR | None |

`company.working_days_pattern` should not become a third classifier. Either stop implying it is the schedule, or add an explicit “create work calendar from this week” action that writes a `WeeklyOffPattern`, a `WorkCalendar`, and a company-scoped assignment. That action is new behaviour and needs a product decision. It must not insert holidays.

If optional holidays must count as leave-deductible only when the employee opts in, that is a leave-type rule, not a new holiday table. **PRODUCT DECISION REQUIRED.** The flag `restricted_holidays_are_off_by_default` is the only switch that exists.

---

## 16. Proposed user experience

Fit the current settings hub. Do not invent a designer.

1. **Work calendars** stays the list of compositions.
2. A detail view gains a **month grid** for one work calendar: call day-type for each date, or one range API. Legend: working, weekly off (show fraction if not 1), holiday, optional/restricted name on a working day, special working, shutdown.
3. If the company has **no** `WORK_CALENDAR` assignment, the grid is not painted as Monday–Friday. Banner: no calendar is assigned. Profile working days, if shown, are labelled as company-profile fields, not as the live policy.
4. Holiday editing stays on the holiday calendar page. The month grid links to the holiday row.
5. Assignments stay effective-dated. The grid takes an “as of” date and a scope (company or branch) so the admin sees which assignment won.
6. Leave overlay, for users who may view leave: approved versus pending as two styles. Pending must not look like a deduction. This reads leave applications; it does not create a new event type.
7. Preview of an **unpublished** edit can be client-side only until save: the current API writes immediately. A true preview-without-write is a later endpoint. Do not pretend the existing PATCH is a draft.
8. Employees do not get holiday-admin controls. A later self-service month can use a view permission that does not imply manage. That permission does not exist today.

Web components to reuse: `PageHeader`, `EmptyState`, `ErrorState`, `LoadingState`, existing forms, roster month grid **layout** only (`buildMonthGrid` in the roster calendar page). Do not bind that page to holidays.

---

## 17. Required product decisions

1. Is `working_days_pattern` retired, kept as a hint, or used to **create** the first weekly-off pattern on an explicit admin action? Do not silently treat it as published policy.
2. Should a new company stay with zero calendars (current, fail closed) or get an empty work calendar plus a weekly-off pattern and **no** holidays?
3. May `HR_ADMIN` manage calendars, or only `COMPANY_ADMIN`?
4. Are optional and restricted holidays non-working? Today they are working unless the work-calendar flag is set (PD-CAL-1).
5. Does a holiday on a weekly off stay a weekly off (PD-CAL-2, current) or become a substitute working day elsewhere?
6. Should a half-day weekly off consume half a day of leave? Today it consumes none, while attendance treats 0.50 as workable.
7. May holiday metadata edits affect unlocked attendance? Current code allows recalculation. Should edits to dates inside a locked period be rejected?
8. Should approved future leave be left untouched (recommended) when holidays change?
9. Is a combined employee calendar in scope for the first UI, or admin-only?
10. Regional `state_code` is stored and not resolved. Should branch state drive calendar choice, or only explicit assignments?

---

## 18. Phased implementation plan

### Phase 0 — Resolve ambiguity

| Item | Detail |
|---|---|
| Objective | Stop two “working week” definitions being described as one calendar |
| Gap | Profile JSON vs `CalendarResolutionService` |
| Files | Docs only, plus a short comment if a later phase touches `company-profile-form.tsx`. No code in this audit |
| Database | None |
| API | None |
| Frontend | None |
| Dependencies | None |
| Tests | Add a characterization test that profile Saturday-working does not change `resolve_for_employee` until an assignment exists |
| Risks | Low |
| Acceptance | Written decision on questions 1–3 in section 17 |
| Effort | **S** |

### Phase 1 — Consistent resolution, no policy change

| Item | Detail |
|---|---|
| Objective | One documented resolver; fix only contradictions the product has already decided |
| Gap | Half-day weekly off split; `is_working` and `valid_from` ignored |
| Files | `calendar_resolution.py`, `leave/service.py` `_compute_day_breakdown`, `attendance/calculation.py` `_is_half_weekly_off` only if a decision says they must match |
| Database | None unless `valid_from` filtering is required (code change, no column) |
| API | None |
| Frontend | None |
| Dependencies | Phase 0 decisions |
| Tests | Half-day Saturday leave fraction; holiday calendar outside `valid_to` excluded or explicitly included; `is_working` either wired to `WORKING_HOLIDAY` or rejected on create |
| Risks | Changing half-day leave changes balances. Do not change it without a decision. Default this phase to **no calculation change** |
| Acceptance | New tests lock current behaviour where product says “keep”; changed behaviour only where a decision is recorded |
| Effort | **M** if behaviour stays; **L** if leave and attendance are aligned |

### Phase 2 — Basic calendar display and holiday management

| Item | Detail |
|---|---|
| Objective | One month an admin can read, using data that already exists |
| Gap | No combined grid; holidays already CRUD-capable |
| Files | New web route under `apps/web/src/app/app/work-calendars/[id]/` or a sibling `calendar` page; optional `GET /work-calendars/{id}/days?from&to` on `organisation/router.py` |
| Database | Not required |
| API | Range classify. Reuse day-type rules. Do not mint holidays |
| Frontend | Month grid, legend, empty state when no assignment. Pending vs approved leave if the viewer has leave view permission |
| Dependencies | Phase 0 |
| Tests | Range endpoint tenant isolation; unassigned company returns an explicit empty payload; holiday and weekly off render from fixture data in unit tests of the pure function, plus one API test |
| Risks | N+1 `resolve` calls if the UI loops day-type. Prefer one range query |
| Acceptance | Admin sees configured holidays and weekly offs; unconfigured company does not show a fake public-holiday set; leave pending and approved are visually distinct |
| Effort | **M** |

### Phase 3 — Admin configuration polish

| Item | Detail |
|---|---|
| Objective | Working week, holidays, and branch assignment from one flow, still on current tables |
| Gap | Three settings pages plus company profile; no guided publish |
| Files | Existing form components; `policy-assignments` UI if it is only API today (**UNVERIFIED** whether web has a policy-assignment page; mobile has `policy_assignments_screen.dart` under attendance) |
| Database | Not required |
| API | Optional `POST /work-calendars/from-profile` that copies weekday flags into a pattern and assignment. Must be explicit |
| Frontend | Wizard is optional. A single page with links is enough |
| Dependencies | Phase 2 and decision 1 |
| Tests | Creating from profile does not insert holidays; second call does not duplicate the company assignment |
| Risks | Accidental second company-level assignment (overlap is already rejected if dates overlap — good) |
| Acceptance | Admin can point a branch at a different work calendar with `effective_from` and see that calendar on the grid |
| Effort | **M** |

### Phase 4 — Leave and attendance alignment

| Item | Detail |
|---|---|
| Objective | Same meaning of half-day off, optional holiday, and special working day in leave and attendance |
| Gap | Section 9 |
| Files | `leave/service.py`, `attendance/calculation.py`, leave policy docs |
| Database | Not required |
| API | None if behaviour changes inside existing submit |
| Frontend | Legend must match the new meaning |
| Dependencies | Product decisions 4–6 |
| Tests | Matrix rows 6, 7, 8, 15. Regression on sandwich tests |
| Risks | **High** for balances and LOP if historical unlocked days are recalculated. Limit the new meaning to dates after an effective assignment, and do not rewrite `leave_application_day` |
| Acceptance | Documented rule; new applications follow it; old application rows unchanged; locked payroll unchanged |
| Effort | **L** |

### Phase 5 — Versioning and impact preview

| Item | Detail |
|---|---|
| Objective | Show what a change would do before it is saved, and keep history readable |
| Gap | PATCH is immediate; no impact list |
| Files | Organisation service (dry-run), audit read API if one does not already expose these entities |
| Database | Not required if preview is stateless. A draft table is unnecessary while assignments are already effective-dated |
| API | `POST /work-calendars/{id}/preview` body = proposed holiday or exception, no write. Response = dates whose type would change, plus future leave application ids |
| Frontend | Confirm step |
| Dependencies | Phase 2 |
| Tests | Preview writes nothing; locked period dates are flagged, not recalculated |
| Risks | Preview that forgets branch assignment will lie |
| Acceptance | Admin sees effective date, affected future leave, and a statement that locked periods stay frozen |
| Effort | **L** |

### Phase 6 — Hardening

| Item | Detail |
|---|---|
| Objective | Tenant, permission, and concurrency tests for any new read API |
| Files | `apps/api/tests/integration/modules/organisation/` |
| Database | None |
| Tests | Cross-tenant range, HR without permission, two admins assigning the same company scope (existing single-winner test should still pass) |
| Risks | Low if phase 2 stayed read-only |
| Acceptance | New endpoints documented; rollback is “do not deploy the UI” because no migration is required for phases 0–3 |
| Effort | **M** |

---

## 19. Edge-case matrix

| # | Scenario | Current behaviour | Proposed | Code path | Test | Decision? |
|---|---|---|---|---|---|---|
| 1 | New company, no calendar | Profile may show Mon–Fri. Resolver `config_incomplete`. Leave submit fails. Attendance `CONFIG_ERROR` | UI says unassigned. Do not invent holidays | `resolve_for_employee` | `test_calendar_resolution_config_incomplete_without_assignment` | Yes: seed a pattern or not |
| 2 | Mon–Fri configured | Only if a weekly-off pattern says Sat+Sun off and a work calendar is assigned | Same, via pattern, not via profile JSON | `evaluate_weekly_off` | `test_fixed_weekdays_saturday_and_sunday` | No |
| 3 | Saturday working | Profile checkbox does nothing for leave. A pattern with no Saturday rule makes Saturday `WORKING` | One source: the pattern | Profile vs pattern | **Add** | Yes: which control is authoritative |
| 4 | Branch holiday calendar | Branch `PolicyAssignment` beats company | Keep | `test_calendar_resolution_branch_scope_beats_company` | Exists, not run | No |
| 5 | Employee on a different shift | Shift scope is in the chain. Shift also has operates-on-holiday. Roster can override expectation | Keep both layers. Display calendar type and shift expectation separately | `_PRECEDENCE_SCOPES`, `evaluate_day` | Shift/calendar tests exist separately | No for storage; yes for UI wording |
| 6 | Leave across a weekly off | Off day not deducted unless sandwich brackets it inside the same request | Keep unless decision 6 | `_compute_day_breakdown` | `test_submit_without_sandwich_rule_skips_weekly_off` | Sandwich default is already true on new policy drafts |
| 7 | Leave across a public holiday | Same as weekly off, type `HOLIDAY` | Keep | same | **Add** an explicit holiday case if not already in the leave file (sandwich test uses a weekend) | No |
| 8 | Half-day leave on a working day | 0.50 only when the range is one day | Keep | `_compute_day_breakdown` | Leave application tests | No |
| 9 | Leave across a leave year | Breakdown does not split on leave year | Do not invent a split in the calendar project | `_compute_day_breakdown` | **UNVERIFIED** | Yes, owned by leave year, not this calendar |
| 10 | Holiday added after approval | Stored days remain. Next attendance calc of an unlocked day can change | Do not rewrite leave rows. Flag unlocked attendance | `leave_application_day` | **Add** | Yes for unlocked attendance |
| 11 | Holiday removed before a future date | Deactivate; future resolve no longer sees it. Past leave rows remain | Preview, then deactivate | `HolidayUpdate.is_active` | **Add** | No if preview is read-only |
| 12 | Working week changed with future leave approved | New resolutions differ. Old rows remain. Overlap of assignments is rejected until the previous row is closed | Close previous assignment with `effective_from` | `test_policy_assignment_insert_new_close_previous` | Exists | Yes: whether to offer a leave adjustment list |
| 13 | Branch assignment changed | As-of date uses the winning scope | Keep | branch precedence test | Exists | No |
| 14 | Employee transfers branch | Assignment as-of uses `get_assignment_as_of` | Calendar follows the employee assignment on that date, then policy scope | `CalendarResolutionService._scope_candidates` | **Add** if not present | No for the mechanism |
| 15 | Special working on a weekly off | Exception `SPECIAL_WORKING` wins. Leave consumes it | Keep | `test_exception_special_working_wins_over_weekly_off` | Exists | No |
| 16 | Overnight shift | Cross-midnight flags exist. Holiday is resolved for the attendance date argument | Document that the holiday date is the attendance date, not both civil dates, unless a later read of `resolve_schedule_window` shows otherwise | `attendance/service.py` around 3694–3706 | **UNVERIFIED** full window | Yes only if product wants both dates checked |
| 17 | Two admins, same assignment | Single winner; overlap conflict | Keep | `test_parallel_policy_assignments_have_a_single_winner` | Exists | No |
| 18 | Unauthorised edit | 403 without `ORG.CALENDAR.MANAGE` or `ORG.HOLIDAY.MANAGE` | Keep. HR role still denied unless decision 3 | `test_work_calendar_denied_without_org_calendar_manage` | Exists | Yes: grant HR or not |
| 19 | Other company’s calendar | 404 | Any new range API must use `company_id` from the tenant, never from the body | cross-tenant tests | Exists for get; **add** for a new range route | No |
| 20 | Update would touch a closed payroll period | No block on holiday PATCH. Frozen attendance summary is what payroll already stored | Preview warns; do not recompute the run. Optionally reject edits whose date falls in a locked period | payroll reads `lop_days`; holiday PATCH has no period check | **Add** | Yes: reject vs warn |

---

## 20. Migration and backfill

Phases 0–3 need **no migration** if they only read and display, and if “create from profile” writes existing tables through existing services.

Do not backfill holidays. Do not copy `working_days_pattern` into `weekly_off_pattern` for every company in a migration. That would publish a policy the company did not confirm, and it would change leave and attendance from `CONFIG_ERROR` to real offs without an admin action.

If a later decision says existing companies should get a pattern, make it a **reviewed** admin action or a one-off script that prints the companies it would change and does not insert holidays. Companies that already have a company-scoped `WORK_CALENDAR` assignment must be skipped.

`Holiday.is_working` and calendar `valid_from`/`valid_to`: prefer using them in the resolver over new columns. If `is_working` is abandoned, stop accepting it on create so admins are not misled. That is an API change, not a table change.

---

## 21. Rollout and rollback

- Phase 2 UI can ship behind the existing permissions. Users without `ORG.CALENDAR.MANAGE` already cannot load the lists.
- No feature flag is required for a read-only grid. If calculation behaviour changes (phase 4), gate it by assignment `effective_from`, not by rewriting history.
- Rollback of a UI-only release is a deploy rollback. No data migration to undo.
- Rollback of an explicit “create calendar from profile” is deactivate the work calendar only if it has no assignments, or close the assignment. Do not delete holiday rows that an admin added afterwards.
- Do not recalculate locked attendance or posted payroll as part of rollout.

---

## 22. Risks and dependencies

- Treating the company profile week as the live calendar would contradict `resolve_for_employee` and the fail-closed tests.
- Seeding Indian public holidays would invent dates the company has not adopted and could double-count once an admin imports their own list.
- Aligning half-day weekly offs between leave and attendance changes money and balances.
- A month API that accepts `company_id` from the client would be an IDOR. The tenant context must supply it.
- `policy_id` without a foreign key depends on service checks. New write paths must keep those checks.
- N+1 day resolution will be slow for a year grid if each day opens the full assignment walk. Batch later; do not fork a second classifier.
- Depends on existing leave and attendance period locks. Calendar work must not bypass `_ensure_period_open` or the attendance freeze.

---

## 23. Recommended first implementation phase

**Phase 0 plus a read-only Phase 2 grid**, with **no** change to leave or attendance math and **no** holiday seed.

Ship:

- Empty state when `GET /calendar-resolution` would be `config_incomplete`.
- Month view for one work calendar using the existing classifier.
- Clear separation from the company-profile working-day checkboxes.
- Pending versus approved leave only as a read overlay.

Do not ship in that first slice: HR permission expansion, profile-to-calendar copy, half-day leave alignment, or draft/publish of work calendars. Assignments are already effective-dated; use them instead of a new version table.

---

## 24. Out of scope

- Implementing any of the phases.
- Offer letters, onboarding email, or face attendance.
- Designing a visual holiday importer for a specific country.
- Rewriting payroll formulas.
- Changing RLS policies in this audit.
- Mobile visual redesign beyond noting that mobile already calls the same catalogue APIs.
- Leave-year boundary policy (owned by `LeaveYearSetting`).
- Automatic substitute holidays (PD-CAL-2 currently says no).

---

## 25. Audit limitations

- Tests named above were **not run**. Passing is unknown.
- `resolve_schedule_window` was not read line by line, so overnight holiday spanning is **PARTIALLY VERIFIED**.
- Not every RLS `CREATE POLICY` for `work_calendar` and `weekly_off_pattern` was re-read. Repositories do filter `company_id`.
- Whether the web app has a full policy-assignment screen was not confirmed beyond the mobile attendance policy screens and the API. Mark the web assignment UI **UNVERIFIED** if a later implementer cannot find a page under `apps/web/src/app/app/`.
- Payroll was searched for calendar symbols and not fully traced through pay-run calculation. The link found is frozen attendance `lop_days`.
- The working tree contains unrelated uncommitted work. Calendar conclusions are from the files cited, including any uncommitted edits already present in `attendance` and `leave` services. Those edits were not produced by this audit.
- No database was queried. No migration was applied. No application file other than this report was written.

`AUDIT COMPLETE — NO APPLICATION CODE, DATABASE RECORDS, MIGRATIONS, OR CONFIGURATION MODIFIED`
