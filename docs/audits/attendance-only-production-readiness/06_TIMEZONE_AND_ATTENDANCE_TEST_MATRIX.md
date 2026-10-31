# Timezone and attendance calculation matrix

Product zone: `Asia/Kolkata`. Companies are allow-listed to that zone (`apps/api/src/hrms/core/config/settings.py` 155–160). `Asia/Calcutta` canonicalises to `Asia/Kolkata` (`shared/timezone.py`).

The API container sets `TZ=UTC` (`apps/api/Dockerfile` line 52). Business dates go through `business_today()` (`shared/business_time.py` 23–28): the UTC clock converted into the company zone. That part matches `docs/audits/ATTENDANCE_TIMEZONE_IMPLEMENTATION_COMPLETION_REPORT.md`. This audit did not repeat that report’s staging session.

Legend: **Unit** = executed in this audit. **Code** = read, not executed against a database. **Unverified** = not executed and not fully traced with a fixture.

## Date and clock

| Case | Expected | Result in this audit |
|---|---|---|
| Server `TZ` changed to something other than UTC or IST | Attendance date still follows the company zone | **Code.** `business_today` converts an aware UTC now. Not executed by changing the host timezone. |
| Stored punch | `timestamptz` | **Code.** Migration `20260820090000_punch.py`. |
| Self punch instant | Server UTC now, displayed in company zone | **Code.** `service.py` 2722–2732. Web and Flutter omit `punch_time`. |
| On-behalf 09:00 IST | Same UTC instant regardless of the browser process zone | **Unit.** `punch-entry-dialog.test.tsx` passed on isolated rerun for `Asia/Kolkata` and `UTC`. |
| UI fallback zone | `Asia/Kolkata` when the profile has no zone | **Code.** Web call sites and Flutter `time.dart`. |
| Unknown IANA name on mobile | Falls back to UTC | **Code.** `lib/core/time.dart` 18–24. Flutter `time_test.dart` was inside the passing suite. |
| Company registration | Rejects zones other than Kolkata | **Code.** `organisation/schemas.py` 114–131 and 275–285. Not executed as an HTTP call. |

## Shift and day boundary

| Case | Expected | Result |
|---|---|---|
| No shift | Local midnight to next local midnight, not a UTC day | **Code.** `calendar_day_window_utc` (`calculation.py` 384–390). Covered by calculation unit tests (window helpers are imported by `test_calculation.py`). |
| Fixed shift, same civil day | Late/early against scheduled start/end minus grace | **Unit.** `test_calculation.py` passed (part of 180). |
| Cross-midnight flag | End is the next local date | **Code + unit helpers.** `scheduled_span_utc` (`calculation.py` 365–380). |
| Overnight punch just after local midnight | Should belong to the shift’s start date | **Code gap.** Immediate calculate uses the punch’s company-local date (`service.py` 2877–2896). The 09:30 sweep recalculates three local days. See ATT-SHIFT-001. **Not executed** as an HTTP scenario. |
| Punch more than 2 hours outside the fixed window | Not loaded for that date | **Code.** Default pad in `punch_window_utc`. |
| Flexible shift | Load window −2h / +12h | **Code.** `calculation.py` 454–464. |
| Weekly off | `NOT_EXPECTED`, not absent, unless a roster override expects work | **Code.** `evaluate_day` 948–988. |
| Holiday | Same, with holiday pay rules by `is_paid` and pay basis | **Code.** `_off_day_is_paid` 1024–1037. |
| Half-day weekly off | `off_fraction` < 1 splits the day | **Code.** `calculation.py` 1052–1104. Not re-run as a named case in this write-up; the file is part of the passing unit module. |
| Shift not started, day row exists, today | Overview: `NOT_CHECKED_IN`, not absent, until `scheduled_end` | **Code.** `overview.py` 84–102. Integration test file exists and was **not run**. |
| No day row yet | Overview: `no_record`, never guessed absent | **Code.** `overview.py` 12–14. |
| Employee on weekly off counted absent | Must not happen when the engine has written `NOT_EXPECTED` | **Code.** Overview maps `NOT_EXPECTED` away from absent. If beat has not created the row, the person is `no_record`, which is also not absent. |

## Leave and regularization

| Case | Expected | Result |
|---|---|---|
| Pending leave | Does not change status and is not “on leave” | **Code.** Projection query requires `APPROVED` (`repository.py` 2254–2268). |
| Approved full-day leave | Status `LEAVE` | **Code.** `_apply_leave_overlay`. |
| Approved half-day leave | Not a re-evaluation of half the shift; flat fraction | **Code.** `calculation.py` 35–39 and 1181–1198. |
| Rejected or cancelled leave | Projection removed, day recalculated | **Code.** Leave cancel calls `LeaveProjectionService.cancel`. |
| Early-departure approval request | Persisted and applied on calculate | **Fails in schema.** ATT-REG-001. Python accepts the type. The check constraint does not. |
| Approved missing-punch regularization | Synthetic punches, then normal engine | **Code.** `service.py` 5086–5124. Not executed. |
| `is_regularized` after the next day’s sweep | Remains true | **Fails in code.** ATT-CALC-003. The sweep writes `False`. |

## Jobs

| Job | Intended local time | Result |
|---|---|---|
| Daily calculation | 09:30 `Asia/Kolkata` | **Code.** `celery_app.py` crontab `minute=30, hour=9` with `timezone=settings.app_timezone_default`. |
| Incomplete reminders | 10:00 | **Code.** Same file. |
| Leave accrual | 01:00, uses `business_today` | **Code.** `leave/tasks.py` 99–107. Shared scheduler. A failure in that task does not by itself rewrite attendance days. |
| Which database “today” the geofence assignment uses | Company local date | **Gap.** `geofence_service.py` line 466 uses `datetime.now(UTC).date()`. Between 00:00 and 05:29 IST that is yesterday. Finding ATT-TZ-001. |

### ATT-TZ-001 — Geofence “assigned today” uses the UTC date

- Severity: Medium. Platform: API. Feature: who is inside the fence after midnight IST.
- Path: `apps/api/src/hrms/modules/attendance/geofence_service.py` line 466.
- Impact: for the first five and a half hours of the Indian day, workplace assignment can follow the previous UTC date.
- Correction: `business_today(company.timezone)`.
- Blocks deployment: no while geofence mode stays `DISABLED`. Yes before required geofence is enabled.

### ATT-TZ-002 — Punch list date filters are UTC calendar days

- Severity: Low. Platform: API. Feature: punch history filters.
- Path: `attendance/repository.py` 1055–1070.
- Impact: a filter of “today” built as a UTC date can omit or include punches near the IST boundary. Day calculation itself uses the company zone.
- Blocks deployment: no.

### ATT-TZ-003 — Work-calendar “effective date is in the past” uses `datetime.now(UTC).date()`

- Severity: Low. Platform: API. Feature: calendar preview warning.
- Path: `organisation/calendar_setup.py` line 325.
- Blocks deployment: no.

## What this matrix does not prove

No fixture was loaded for a 22:00–06:00 shift with a punch at 00:30 IST. No dashboard response was captured at 09:00 versus 18:00 to show the not-checked-in to absent transition. No Celery beat fire was observed. Those remain unverified runtime cases. The code paths above are the ones a later test should pin.
