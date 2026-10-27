# Work calendar phase 3 - change-impact preview and safe confirmation

Date: 2026-10-27. Builds on `work_calendar_implementation_audit.md` and
`work_calendar_phase2_employee_calendar.md`. The Work Calendar feature as a whole is **not**
complete; see "Not done" at the end.

## 1. Policy decision table

"Decision" means what this phase implements. No existing business rule was changed; where the
product has not decided, the preview reports the situation instead of choosing.

| Question | Existing code behaviour | Tests / evidence | Decision in this phase |
|---|---|---|---|
| Holiday on a weekly off: substitute holiday? | `classify_work_calendar_date`: a hard holiday on a weekly-off date stays `WEEKLY_OFF` with `holiday_on_weekly_off=true`; only an explicit `SUBSTITUTE_HOLIDAY` exception creates a day off (PD-CAL-2, WD-05) | `test_calendar_range_and_setup`, `test_workforce_calendar`; audit §17 Q5 still open | Preview mirrors it: the row shows `WEEKLY_OFF` with the holiday label and a `HOLIDAY_ON_WEEKLY_OFF` notice. No substitute is proposed. Test: `test_holiday_on_weekly_off_stays_weekly_off_with_a_warning`. **Open product decision** |
| `Holiday.is_working` | Stored and editable; **never read** by the resolver. A working holiday is modelled by `holiday_type = WORKING_HOLIDAY` | grep of `calendar_resolution.py`; no test | Not modelled by the overlay (that would invent semantics). A change that sets it raises notice `HOLIDAY_IS_WORKING_IGNORED`. **Open: remove the column or define it** |
| Holiday-calendar `valid_from`/`valid_to` | Stored; **not applied** by resolution; holidays are loaded regardless of date | grep; no test | Not applied by the preview either; notice `HOLIDAY_CALENDAR_VALIDITY_IGNORED` when such a calendar is involved. **Open: should validity constrain resolution?** |
| Optional / restricted holidays | Working days unless the work calendar's `restricted_holidays_are_off_by_default` is set (PD-CAL-1); the name is carried in `optional_holiday_name`/`restricted_holiday_name` | `test_range_keeps_optional_holiday_a_working_day` | Mirrored. Rows show `Working day - Optional: <name>`; notice `OPTIONAL_RESTRICTED_WORKING`. The work-calendar flag is previewable (`WORK_CALENDAR_UPDATE`) |
| Half-day weekly off | Classifier returns `WEEKLY_OFF` with `weekly_off_fraction`; attendance treats 0.50 as workable, leave treats the whole day as non-working (audit §9) | audit §9; no cross-module test | Not resolved. Preview shows the fraction and raises `HALF_DAY_WEEKLY_OFF` whenever one is involved. **Open product decision (audit §17 Q6)** |
| Calendar edits vs employee overrides / effective-dated assignments | WD-09 precedence EMPLOYEE > SHIFT > ... > COMPANY; assignments are insert-new/close-previous; edits to a calendar/pattern/holiday are live for every employee resolving to it | `test_policy_and_calendar_rules`, `test_calendar_resolution_branch_scope_beats_company` | Preview resolves each employee with the real resolver, so an employee-scope assignment shields that employee from a company-calendar edit, and an assignment change takes effect from `effective_from`. Tests: `..._employee_specific_assignment_is_not_affected...`, `..._assignment_effective_date_boundary` |
| Employee joins/leaves inside the window | Resolver does not consider employment dates (leave and attendance enforce them elsewhere) | Phase 2 doc | Preview counts only dates inside an `employment` span (`joining_date`..`last_working_day`); excluded employee-dates are reported (`excluded_not_employed_employee_dates`). Test: `test_dates_outside_employment_are_excluded` |
| Is an edit allowed after a period is locked? | Nothing blocks a calendar edit; locked attendance and finalised payroll keep their frozen summaries | audit §13 | Allowed, **not** rewritten, and listed. Impact on a `CLOSED` attendance period or a pay run in `INPUTS_LOCKED`..`PAID` requires an explicit acknowledgement (`acknowledge_protected_impact`). Rejecting edits inside locked periods is audit §17 Q7, left open |

## 2. API

Both routes need `ORG.HOLIDAY.MANAGE` for holiday changes and `ORG.CALENDAR.MANAGE` for the rest
(the codes the ordinary routes use; `COMPANY_ADMIN` and, since migration `20261029090000`,
`HR_ADMIN` hold both). Company and actor come from the authenticated context; the request bodies
reject unknown fields, so a client-supplied `company_id` is a 422.

### `POST /v1/work-calendar-changes/preview` (read-only, 200)

```
{ "change": <ProposedChange>, "window_from": "YYYY-MM-DD", "window_to": "YYYY-MM-DD" }
```
Window: inclusive, at most 366 days, else `422 CALENDAR_PREVIEW_INVALID`.

`ProposedChange` (discriminated by `change_type`; each wraps the existing create/update model, so
there is no second policy schema):

| `change_type` | Fields |
|---|---|
| `HOLIDAY_CREATE` | `holiday_calendar_id`, `body: HolidayCreate` |
| `HOLIDAY_UPDATE` | `holiday_id`, `expected_version`, `patch: HolidayUpdate` (includes `is_active` for deactivate/reactivate) |
| `EXCEPTION_CREATE` | `work_calendar_id`, `body: CalendarExceptionCreate` |
| `EXCEPTION_UPDATE` | `exception_id`, `expected_version`, `patch: CalendarExceptionUpdate` |
| `WEEKLY_OFF_PATTERN_UPDATE` | `pattern_id`, `expected_version`, `patch: WeeklyOffPatternUpdate` (only `rules` affect resolution) |
| `WORK_CALENDAR_UPDATE` | `work_calendar_id`, `expected_version`, `patch: WorkCalendarUpdate` (links, weekly-off pattern, restricted flag) |
| `ASSIGNMENT_CREATE` | `body: PolicyAssignmentCreate` (`WORK_CALENDAR` or `WEEKLY_OFF` only), `expected_version` of the open assignment at that scope, if any |

Response (`data`): `population` (`employees_in_scope`, `employees_analysed`, `groups_analysed`,
`complete`), `changed_date_count`, `affected_employee_count`, `rows[]` (`date`, `previous`,
`proposed` snapshots with `day_type`/`label`/`weekly_off_fraction`, `affected_employee_count`; at
most 500, `rows_truncated`), `employee_samples[]`, `excluded_not_employed_employee_dates`,
`incomplete_configuration{employees,dates}`, `leave_impact` (approved/pending **day-record**
counts, applications, employees, up to 100 `items`, `records_modified: 0`), `protected_periods[]`
(attendance periods that are not `OPEN`, pay runs `INPUTS_LOCKED`..`PAID`), `warnings[]`,
`requires_acknowledgement`, `impact_digest`. Leave items expose application id, employee code,
date and status only - never reasons or leave types.

Errors: `404` for any referenced record of another company, `409 STALE_RESOURCE` when
`expected_version` no longer matches, `422 CALENDAR_PREVIEW_INVALID` for duplicates / bad window /
unsupported policy kind, `403` without permission.

### `POST /v1/work-calendar-changes/confirm` (201)

Same body plus `impact_digest` (from the preview) and `acknowledge_protected_impact`.
Errors: `409 CALENDAR_PREVIEW_STALE`, `422 CALENDAR_IMPACT_ACKNOWLEDGEMENT_REQUIRED`, plus any error
the underlying service raises. Result: `entity_id`, `impact_digest`, counts, `confirmed_by/at`.

## 3. Stale-preview and concurrency strategy

A preview is never authority. Confirm (1) takes a per-company transaction advisory lock
(`work-calendar-change:<company>`), (2) recomputes the full impact against the database as it is
now, (3) compares its SHA-256 digest with the client's, (4) requires the acknowledgement if
leave or protected periods are involved, (5) calls the existing `OrganisationService` method
(own validation, optimistic `If-Match` version, per-entity audit), (6) writes one
`WORK_CALENDAR_CHANGE_CONFIRMED` audit event - all in the request transaction. The digest covers the
change, window, every changed row, affected-employee count, leave counts, protected periods and
population limits, so any change to configuration, employment, leave or period state that alters
the impact invalidates it. Optimistic entity versions are checked at both preview and apply time.
A repeated or concurrent confirmation either fails the digest (state moved on), the service's own
duplicate/overlap checks, or the version check; tested with four simultaneous confirms (exactly one
201). Any exception rolls back the change and its audit rows together (tested).

## 4. How the impact is computed

* One resolver, one classifier. `CalendarResolutionService` takes an optional in-memory
  `CalendarOverlay` (`calendar_overlay.py`) that adjusts holidays, links, rules, calendar settings,
  exceptions and assignments after they are loaded. Without an overlay behaviour is unchanged
  (`resolve_for_employee` now delegates to the new `resolve_calendar_choice`).
* Employees with identical placement history are grouped; the resolver runs once per group and
  segment (dates where an assignment can change), current and proposed, with shared memoisation.
  Employees with their own EMPLOYEE-scope assignment are resolved individually. Query count is
  independent of the number of employees in a group (tested: 2 vs 5 employees).
* Caps: 5,000 employees and 300 groups per preview. If hit, `population.complete=false`, counts are
  a lower bound, the UI says "At least", and the digest records it.
* Leave: one bounded join on the affected employees; only `SUBMITTED`/`APPROVED` records on changed
  dates inside employment are counted. Nothing is written.

## 5. Protected historical data

A calendar change never touches `leave_application_day`, `leave_ledger`, `attendance_day`,
`attendance_period` or `pay_run` (tests compare row counts and content hashes before and after
preview and after acknowledged confirmation). Pending leave is reported, never approved/rejected.
No recalculation is triggered; only future calculations see the new configuration.

## 6. Limitations

* Employee-scope assignments created for employees outside the analysed population are not seen.
* `SHIFT`-scope resolution uses `EmployeeAssignment.shift_id` like the resolver (roster overrides
  are not part of calendar resolution and are not previewed).
* `HOLIDAY_CALENDAR`/`WEEKLY_OFF_PATTERN`/`WORK_CALENDAR` *creation* and deactivation of whole
  calendars are not previewed (a new calendar affects nobody until assigned; deactivation does not
  change resolution today). Guided setup keeps its own preview.
* Protected-period matching uses the legal entity of the employee's employment; pay runs in
  `INPUTS_LOCKED`/`COMPUTED`/`APPROVED` are reported as protected too, not only finalised ones.
* Digest comparison is exact; a harmless unrelated change that alters a counted number (for
  example a new leave application on a changed date) correctly forces a re-preview.
* The UI shows at most 100 changed dates and 10 leave items; the API returns more.

## 7. Rollout

No migration, no new permission code, no data backfill. New files: `calendar_overlay.py`,
`calendar_impact.py`, web `change-impact-dialog`. Existing admin routes are unchanged; the web
screens for holidays, weekly-off patterns, work-calendar settings, exceptions and
WORK_CALENDAR/WEEKLY_OFF assignments now save through the dialog. Roll back by deploying the
previous web build (the old direct routes remain). Plan to verify in staging with a realistic
tenant size before relying on the 5,000-employee cap.

## 8. Test commands

Backend (disposable stack created with the QA harness, run id `cal2-20261027a`):

```
bash docs/testing/qa_harness/stack.sh up cal2-20261027a
bash docs/testing/qa_harness/stack.sh guard cal2-20261027a
bash docs/testing/qa_harness/stack.sh migrate cal2-20261027a
bash docs/testing/qa_harness/stack.sh pytest cal2-20261027a tests/integration/modules/organisation/test_calendar_impact.py
```
Web: `cd apps/web && npx vitest run && npx tsc --noEmit -p . && npx eslint <changed files>`.
Actual results are recorded in the implementation report.
