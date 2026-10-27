# Work calendar - Phase 4: policy alignment, safe resolution and readiness

Date: 2026-10-27. Builds on `work_calendar_phase3_change_impact.md` and
`work_calendar_phase3_closure.md`, whose "open product decision" rows D1-D7 this phase answers.
Anything marked **proposed / not implemented** is stated as such; everything else is in the code and
covered by a test that was run (section 8).

## 1. Policy decisions and their validated meaning

| | Policy | Status | Final meaning (what the code now does) |
|---|---|---|---|
| A | Half-day weekly off | **Implemented** | `WeeklyOffRule.off_fraction` (`DayTypeRead.weekly_off_fraction`) is the **off (non-working) share** of the date: `1.00` full day off, `0.50` half off and half working. Only `0.50` and `1.00` are accepted (`WeeklyOffRuleCreate` validator). `None` on a `WEEKLY_OFF` day means a full day (a holiday on a half-day weekly off covers the working half too). Two shared functions in `calendar_resolution.py` define it: `weekly_off_fraction_of(day)` (attendance) and `working_fraction_of(day)` = 1 - off share for weekly offs, 1 for `WORKING`/`SPECIAL_WORKING`, 0 for holiday/shutdown (leave). |
| B | No automatic substitute holiday | **Implemented (already true; now pinned by tests)** | A hard holiday on a weekly off stays `WEEKLY_OFF` with `holiday_on_weekly_off=true`. The only substitute mechanism is an HR-created `CalendarException` of type `SUBSTITUTE_HOLIDAY` on another date, which classifies that date as `HOLIDAY` (holiday type `SUBSTITUTE`, paid). No code path creates one automatically. |
| C | `Holiday.is_working` | **Implemented (as a mirror, not an independent switch)** | `is_working` is true exactly when `holiday_type = WORKING_HOLIDAY` (architecture table: "true for WORKING_HOLIDAY"). Resolution keeps keying off the type, so the flag can never disagree with a day's classification. API: creating/updating with a contradictory explicit flag is `422 HOLIDAY_IS_WORKING_CONFLICT`; omitting it stores the implied value; changing the type re-derives it. Legacy rows that already disagree are not rewritten (see section 4). |
| D | Holiday-calendar validity | **Implemented** | `holiday_calendar.valid_from` / `valid_to`, both **inclusive**, both nullable (open-ended). The window belongs to the **holiday calendar** (not to the assignment or to a single holiday) and is applied per target date: a holiday dated outside its calendar's window does not take part in classification and the next linked calendar is consulted. An inverted window (`from > to`) matches no date and is now rejected on write. |
| E | Locked attendance / closed payroll | **Implemented in phase 3; extended with tests** | Allowed after explicit acknowledgement; protected records are never rewritten; digest covers the protected periods, so a period closed after the preview makes the preview stale. |
| F | Deactivation with dependants | **Implemented** | A work calendar cannot be deactivated while an active `WORK_CALENDAR` assignment for it is not yet over. A weekly-off pattern cannot be deactivated while an active `WEEKLY_OFF` assignment is not yet over **or** while an active work calendar uses it as its default pattern. "Not yet over" = `effective_to IS NULL OR effective_to >= today` in the **company's** time zone, so currently effective, future-dated and ending-today assignments all block; expired ones do not. |

## 2. Evidence from the original code, and conflicts found

**A. The fraction convention.** Established from five independent places, all agreeing that it is the
*off* share: `WeeklyOffRuleCreate.validate_off_fraction` (0.50 or 1.00 only); `weekly_off_rule.off_fraction`
defaulting to `1.00` (a normal weekly off is a full day off); attendance `_apply_half_weekly_off`
("half off, half working: the off half is always paid; the working half is paid only if worked, else
loss of pay"); `attendance_day.weekly_off_fraction` ("paid off share of a half-day weekly off");
attendance `period summary` splitting a day into leave/off/rest. The name was not trusted on its own.

*Conflict found:* `LeaveService._compute_day_breakdown` treated any `WEEKLY_OFF` date as non-working,
ignoring the fraction, so a half-day Saturday could never be taken as leave although attendance
already expected (and could pay) a 0.5 leave + 0.5 off day (`_apply_leave_overlay` computes
`remaining = 1 - leave - weekly_off`). *Resolution:* leave now consumes `working_fraction_of(day)`.

**B.** `classify_work_calendar_date` (WD-05 / PD-CAL-2 comments) already returned `WEEKLY_OFF` for a hard
holiday on a weekly off and the exception types are `SPECIAL_WORKING`, `SHUTDOWN`,
`SUBSTITUTE_HOLIDAY`, `CANCEL_HOLIDAY`. No conflict.

**C.** The column is never read by the resolver (verified by grep across `modules/`). The only
statement of intent is `WORKFORCE_ATTENDANCE_ARCHITECTURE.md` ("`is_working` ... true for
WORKING_HOLIDAY"), and `HolidayCreate` defaults it to `false`. *Conflict found:* the API accepted
`is_working=true` on a `PUBLIC` holiday, which then still classified as `HOLIDAY` - a silent lie.
*Resolution:* reject contradictions; do not make the flag an independent second switch, because
that would reinterpret any stored `is_working=true` rows on non-working-holiday types.

**D.** The columns existed (`20260818090000_holiday_calendar_expand`) and were never read: the resolver
loaded every holiday of every linked calendar regardless of date. No DB constraint ordered the two
dates.

**F.** *Conflicts found:* (1) the guard existed only on `DELETE /work-calendars/{id}`;
`PATCH {is_active:false}` and the confirmed-change path (`WORK_CALENDAR_UPDATE`) bypassed it;
(2) it counted only assignments with `effective_to IS NULL`, so a still-current assignment given a
future end date, or a future-dated one, did not block; (3) it had no lock, so an assignment could be
created between the check and the deactivation; (4) weekly-off patterns had no guard at all;
(5) an inactive calendar could still be assigned.

## 3. Resolver and downstream behaviour changes

* `calendar_resolution.py`: `HolidayData` gains `calendar_valid_from/to` and `applies_on(date)`; the
  classifier's match only considers holidays that apply on the date. `load_ordered_holidays_for_calendars`
  stamps each calendar's window on **every** row after the overlay is applied (so a proposed holiday
  and a proposed validity change are evaluated by the same code as saved data) using one extra
  query (`HolidayCalendarRepository.list_by_ids`). New: `weekly_off_fraction_of`, `working_fraction_of`,
  `reconcile_holiday_is_working`, `HolidayIsWorkingConflictError`. Single-date, range, employee
  calendar, admin calendar, preview and confirm all go through the same loader and classifier.
* `calendar_overlay.py`: `validity` map (+ `adjust_validity`) for a proposed holiday-calendar window.
* Leave (`leave/service.py`): per-date consumable fraction = `working_fraction_of`; a full-day
  application over a half-day weekly off books `0.50` (no `half` marker); a half-day request keeps
  its `half`; a sandwich-generated full off day is still `1.00`; the same-type per-date cap is
  now the date's working fraction instead of `1.00`. Fully-off days still consume nothing.
* Attendance (`attendance/service.py`): reads `weekly_off_fraction_of` instead of its own
  `None -> "1.00"` default. Numerically identical; no calculation change.
* No change to how an approved leave day, an attendance day, a period or a pay run is stored or
  recalculated.

## 4. Migration, data and compatibility implications

**No migration was created.** Everything uses existing columns. Consequences to review before a
production rollout (the disposable database has no real data, so these were **not** measured):

* **D changes classification for existing data.** Any holiday dated outside its calendar's window
  stops applying. Diagnostic (read-only, run per tenant before deploying):
  ```sql
  SELECT hc.company_id, hc.id AS holiday_calendar_id, hc.name, h.date, h.name
  FROM holiday h JOIN holiday_calendar hc ON hc.id = h.calendar_id
  WHERE h.is_active AND h.deleted_at IS NULL AND hc.deleted_at IS NULL
    AND ((hc.valid_from IS NOT NULL AND h.date < hc.valid_from)
      OR (hc.valid_to   IS NOT NULL AND h.date > hc.valid_to));
  SELECT id, company_id, name FROM holiday_calendar
  WHERE valid_from IS NOT NULL AND valid_to IS NOT NULL AND valid_from > valid_to;
  ```
  Historical `attendance_day` / `leave_application_day` / pay-run rows are not touched and keep what
  they were computed with; dates in an open period will pick the new classification the next time
  they are recalculated.
* **C is forward-looking.** Legacy rows where `is_working` disagrees with the type are left alone
  and keep classifying by type (their behaviour does not change). Diagnostic:
  ```sql
  SELECT company_id, calendar_id, date, holiday_type, is_working FROM holiday
  WHERE is_working <> (holiday_type = 'WORKING_HOLIDAY') AND deleted_at IS NULL;
  ```
  Editing such a row's type or flag normalises it; renaming it does not.
* **A is not retroactive.** Approved/pending leave days already stored keep their fractions
  (tested: a pattern change after approval leaves `leave_application_day` byte-identical). A
  half-day weekly off that already existed now allows leave on its working half; no earlier
  application can have been affected because they were all rejected or skipped that date.
* **F** rejects deactivation (409) and assignment to an inactive calendar/pattern (422
  `INVALID_POLICY_REFERENCE`) where it was previously accepted.
* Rollback = deploy the previous API/web build. No schema to revert.

Deployment order: API first, then web. Until the web is deployed, the old holiday form's
"Working holiday" checkbox can send a contradictory flag and gets the clear 422
`HOLIDAY_IS_WORKING_CONFLICT`; old holiday-calendar validity edits skip the impact preview.

## 5. API changes (all additive except where stated)

* `POST /v1/work-calendar-changes/{preview,confirm}`: new `change_type` **`HOLIDAY_CALENDAR_UPDATE`**
  (`holiday_calendar_id`, `expected_version`, `patch: HolidayCalendarUpdate`), permission
  `ORG.HOLIDAY.MANAGE`. Removed warning codes `HOLIDAY_IS_WORKING_IGNORED`,
  `HOLIDAY_CALENDAR_VALIDITY_IGNORED`; new warning `HOLIDAY_OUTSIDE_CALENDAR_VALIDITY`;
  `HALF_DAY_WEEKLY_OFF` text updated. Request/response shapes are otherwise unchanged.
* Holidays: `422 HOLIDAY_IS_WORKING_CONFLICT` (create, update, preview, confirm). `is_working` is
  always present on `HolidayRead` as before.
* Holiday calendars: `valid_from > valid_to` is `422` on create and `422 HOLIDAY_CALENDAR_VALIDITY_INVALID`
  on update. **Behavioural change:** validity now affects resolution.
* Work calendars / weekly-off patterns: `409 WORK_CALENDAR_HAS_ACTIVE_ASSIGNMENTS` /
  `409 WEEKLY_OFF_PATTERN_HAS_ACTIVE_ASSIGNMENTS` for **DELETE, PATCH `is_active=false` and the
  confirm path**. `error.details[0].context` = `{active_assignment_count, assignments[≤10]{scope_type,
  scope_id, effective_from, effective_to}, default_for_work_calendars, next_action}`.
* Leave: `POST /v1/leave-applications` now succeeds for a date that is a half-day weekly off and
  books `0.50` (previously 422 "no leave-consuming days" for a lone such date).
* `GET /v1/employee-calendar/me`: **unchanged shape**; see section 9 for the semantics mobile relies on.

## 6. Historical-record protections

Verified by full-row md5 of `leave_application`, `leave_application_day`, `leave_ledger`,
`attendance_day` (locked), `attendance_period` (CLOSED) and `pay_run` (FINALISED) before and after
preview and after acknowledged confirmation: `test_confirmed_change_leaves_leave_locked_attendance_and_payroll_untouched`
(phase 3). Phase 4 adds: a period closed *after* the preview makes it stale
(`CALENDAR_PREVIEW_STALE`) and a fresh preview then demands acknowledgement; acknowledgement does not
bypass the employee-role 403 or a cross-tenant 404; the audit row names actor, tenant and digest and
contains no leave reason; and a pattern change after leave approval leaves the stored leave days
identical. Nothing triggers recalculation of historical attendance or payroll.

## 7. Concurrency

* Change confirmation: per-company `work-calendar-change:<company>` advisory lock (phase 3).
* Deactivation vs assignment: new per-company `calendar-policy-dependencies:<company>` advisory lock
  (`core/db/locks.py`), taken by deactivation of a calendar/pattern, by assignment creation for
  `WORK_CALENDAR`/`WEEKLY_OFF`, and by a calendar's default-pattern change. Lock order is always
  change-lock -> dependency-lock; nothing takes them in the other order. Tested with six concurrent
  rounds: never both "deactivated" and "assigned".

## 8. Tests and results

Commands and counts actually observed are in section 12.

New/changed tests:
* `tests/unit/modules/organisation/test_calendar_policies.py` (42 tests, pure): fractions, B, C, D.
* `tests/integration/modules/organisation/test_calendar_policies.py` (21 tests): A (leave + attendance
  for the same employee/date, spanning, half-day, overrides, effective-dated assignment, not
  retroactive), B (preview -> confirm -> resolved), C (API + resolution + preview), D (every path,
  preview == confirmed resolution, link changes, employee-specific calendar), E (stale/ack/
  tenant/permission/audit), F (all nine requested cases).
* Web: `deactivation.test.ts` (3), `validate-holiday.test.ts` (+1).
* `test_route_authorization_matrix.py` unchanged this phase (phase 3 registered the routes).

Not covered by a test, stated plainly: **branch**-scope assignment of a validity-windowed calendar
(the validity filter sits below scope resolution and is the same code for every scope; employee
scope is tested and branch precedence is covered by the existing resolution tests); cross-type
leave on a half-day weekly off (below); the web admin screens end to end (no browser).

## 9. Known limitations / unresolved

1. **Which half is the working half** is not modelled. A half-day weekly off says "50 % off", not
   "morning off"; leave on it carries no `half` unless the employee asked for one.
2. **Cross-type leave on a half-day weekly off:** the per-date cap is per leave type. Two different
   leave types could each book 0.5 on the same half-off date; only the approval-time projection total
   (<= 1.00) stops more. Not fixed.
3. Deactivating a **holiday calendar** is still unguarded and does not change resolution (its links
   to work calendars keep applying). Product decision, unchanged from phase 3.
4. Validity is on the holiday calendar only; per-holiday and per-link windows do not exist.
5. `Holiday.is_working` remains a redundant stored field. Removing it (or making it independent) is a
   product/engineering decision; this phase deliberately did neither.
6. The pre-existing `attendance/service.py` mypy errors (2) and the repository-wide `eslint`
   `react-hooks/set-state-in-effect` pattern are untouched.
7. **Browser verification was not performed** - see section 10.

## 10. Browser verification status: NOT performed

The repository's only app launcher (`.claude/launch.json`, `scripts/dev.sh`) runs the API and web
against the shared development database, which this task must not write to; the QA harness's
disposable stack is deliberately network-less, so a browser cannot reach an API running inside it. No
Playwright/Cypress harness exists. Component-level behaviour is covered by vitest/jsdom (impact
dialog states, employee calendar, new deactivation message, holiday payloads). The UI changes of this
phase (explanatory text for working holidays, inclusive-validity hints, validity edits through the
impact dialog, actionable deactivation messages) have **not** been seen in a browser.

## 11. Stable backend contract for Flutter mobile

Safe to build against (unchanged by this phase except as noted):

`GET /v1/employee-calendar/me?from=YYYY-MM-DD&to=YYYY-MM-DD` - inclusive, at most 100 days, no
employee/company parameter (taken from the token; extra parameters are ignored). Response `data`:
`from_date`, `to_date`, `configuration` (`COMPLETE`|`PARTIAL`|`INCOMPLETE`), `leave_included`, `days[]`.
Each day: `date` (date-only string, never a timestamp - do not apply a device time zone),
`configured` (false = calendar not set up; show "not set up", never "working"), `day_type`
(`WORKING`|`WEEKLY_OFF`|`HOLIDAY`|`SPECIAL_WORKING`|`SHUTDOWN`|null), `holiday_name`, `holiday_type`,
`holiday_on_weekly_off`, `is_holiday_named`, `optional_holiday_name`, `restricted_holiday_name`,
`exception_type`, `weekly_off_fraction`, `leave[]{status APPROVED|PENDING, fraction, half}`.

Semantics mobile can rely on after this phase:
* `weekly_off_fraction` (string decimal) = the **off share**. `"1.00"` or `null` on a `WEEKLY_OFF` day =
  whole day off; `"0.50"` = half off, half working (render as a partial day, not a full off day).
* A holiday outside its calendar's validity window does not appear at all.
* Leave `fraction "0.50"` with `half null` = the working half of a half-day weekly off.
* `HOLIDAY` with `exception_type = SUBSTITUTE_HOLIDAY` is an HR-created substitute.
* Leave detail is hidden (`leave_included=false`) without the leave-balance view grant.

Admin preview/confirm and deactivation errors are web-only today and not part of the mobile contract.
Mobile should **not** assume anything about the unresolved items in section 9.

## 12. Commands and observed results

Disposable stack `cal4d-20261027a` (`stack.sh up` -> `guard`: ISOLATION PROVED -> `migrate`: single
head `20261029090000`; no migration added). OpenCV supplied as in the phase 3 closure report
(`QA_EXTRA_ENV` -> `/artifacts/cvdeps`). The suite was run in the same 15 per-directory chunks as
phase 3 (a single process exceeds the runner's 1.5 GB cap), **all against the same final backend
code** (a comment-only docstring edit in `employee_calendar.py` followed the unit chunk):

`stack.sh pytest cal4d-20261027a <dir> -q -p no:cacheprovider -rfEs`

| Chunk | Result |
|---|---|
| tests/unit (incl. 42 new) | 1430 passed, 40 skipped |
| tests/security | 38 passed |
| integration auth / core / migrations / top-level | 60 / 107 (+1 skipped) / 7 / 31 passed |
| modules account_invite / attendance / employee / employee_import | 91 / 395 / 398 / 17 passed |
| modules leave / onboarding | 259 / 156 passed |
| modules organisation (incl. 21 new) | 366 passed |
| modules payroll / platform | 72 / 28 passed |
| **Total** | **3,455 passed, 41 skipped, 0 failed, 0 errors** |

Earlier in the phase, intermediate runs against a first stack hit teardown failures in *my own new
tests* (cleanup order; one left a stuck tenant that poisoned later tests). They were fixed in the
tests and the stack was rebuilt; they were not product failures.

Static: `ruff format --check` clean (695 files); `ruff check` 5 E501 in five older, untouched
migrations (unchanged); `mypy` 2 errors in `attendance/service.py` (unchanged baseline; the
phase 3 `calendar_resolution` error stays fixed); `lint-imports` 1 kept / 0 broken; web `tsc` clean;
`vitest` 72 files, 574 passed; `eslint` 112 errors (same count as before this phase; the new files
add none).

Migration upgrade/downgrade: no migration in this phase, so none to test; the phase 3 data migration
`20261029090000` round trip stands (14 -> 0 -> 14 grants).

Browser: not performed (section 10).
