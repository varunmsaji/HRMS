# Work calendar phase 2 - employee calendar

Date: 2026-10-27. Builds on `work_calendar_implementation_audit.md`. This phase adds a read-only
employee self-service calendar. Change-impact preview and mobile are later phases and are not
started here.

## API

`GET /v1/employee-calendar/me?from=YYYY-MM-DD&to=YYYY-MM-DD`

* Auth: bearer token plus `X-Company-Id`; permission `ATTENDANCE.VIEW` (held SELF by every
  default `EMPLOYEE`, so no migration or new permission code).
* The employee is `AuthenticatedUser.employee_id` (JWT claim) and the company is the validated
  tenant context. There is **no** `employee_id`/`company_id` parameter; unknown query parameters
  are ignored (tested). A caller with no linked employee gets `422` with detail code
  `EMPLOYEE_RECORD_REQUIRED`.
* Range: inclusive, `to >= from`, at most 100 days (`MAX_CALENDAR_RANGE_DAYS`). Violations return
  `422 CALENDAR_RANGE_INVALID`; malformed/missing dates return the standard `422`.

Response (`data`):

| Field | Meaning |
|---|---|
| `from_date`, `to_date` | echo of the range |
| `configuration` | `COMPLETE`, `PARTIAL` (some dates unresolved) or `INCOMPLETE` (none) |
| `leave_included` | `false` when the caller holds neither `LEAVE.BALANCE_VIEW` nor `_VIEW_ALL`; `leave` is then empty |
| `days[]` | one entry per date, ascending |

Day: `date`, `configured`, `day_type` (`WORKING`/`WEEKLY_OFF`/`HOLIDAY`/`SPECIAL_WORKING`/`SHUTDOWN`,
`null` when `configured=false`), `holiday_name`, `holiday_type`, `holiday_on_weekly_off`,
`is_holiday_named`, `optional_holiday_name`, `restricted_holiday_name`, `exception_type`,
`weekly_off_fraction`, `leave[]`. Leave: `status` (`APPROVED`|`PENDING`), `fraction`, `half`
(`FIRST_HALF`/`SECOND_HALF`/null).

Existing admin endpoints (`/calendar-resolution`, `/work-calendars/{id}/days`, `/day-type`) are
unchanged. `CalendarResolutionService.classify_range_for_work_calendar` gained two optional
keyword arguments (`weekly_off_pattern_id_override`, `_weekly_off_override_present`, same
convention as `classify_date_for_work_calendar`); existing callers are unaffected.

## How the employee's calendar is resolved

1. Segments: two bounded queries (the employee's `employee_assignment` history; `WORK_CALENDAR`/
   `WEEKLY_OFF` `policy_assignment` rows overlapping the range) give the dates on which the
   effective assignment can change. A typical month is one segment.
2. For each segment start, the existing `resolve_for_employee` runs the WD-09 precedence walk
   (EMPLOYEE > SHIFT > ... > COMPANY, including an employee-level weekly-off override). No
   resolution -> `config_incomplete` -> the dates are returned `configured=false`; nothing is
   defaulted to working.
3. The whole segment is classified with `classify_range_for_work_calendar` (the one classifier).
4. Query count is independent of range length (asserted by a test comparing 7 and 41 days).

## Leave

Read from persisted `leave_application_day` joined to `leave_application` (one query).
`SUBMITTED` -> `PENDING`, `APPROVED` -> `APPROVED`; `REJECTED` and `CANCELLED` are excluded in SQL.
Nothing is recalculated or written. Half days are stored only on single-day applications
(`half`, `fraction=0.50`); multi-day applications are one row per date, full day. Sandwich-generated
days are persisted leave days and are shown as leave (no flag is exposed). Not selected or returned:
reason, attachment, leave type, approver/comment, application id, LOP flag. Only the caller's own
`employee_id` is queried; there is no team view.

## Web

Route `/app/me/calendar` ("My Calendar" in the sidebar, shown only when the account has an
employee record). Month navigation requests the Monday-first month grid (at most 42 days).
Classification labels reuse `presentDay` from the admin day grid. States: loading, error with retry,
no employee record, `INCOMPLETE`, `PARTIAL` (per-date "Not set up"), leave hidden. Approved vs
pending leave differ by text, glyph and solid/dashed border. All date arithmetic is UTC on
date-only strings.

## Open questions / limitations

* Whether the leave type name may be shown to the employee on their own calendar (omitted for now
  as potentially sensitive, e.g. sick leave).
* A weekly-off half day is shown from `weekly_off_fraction`; leave and attendance still disagree on
  its meaning (audit section 9) - unchanged here.
* Dates before joining or after the last working day are not special-cased; the resolver does not
  consider employment dates.
* Segment boundaries come from every active assignment of the two kinds in the company (EMPLOYEE
  scope is filtered to the caller); over-segmenting is correct but costs extra resolver calls.
* Browser (visual) verification was not run.
