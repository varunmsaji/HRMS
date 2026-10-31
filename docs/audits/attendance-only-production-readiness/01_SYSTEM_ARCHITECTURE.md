# System architecture — attendance release

Evidence class: code inspection of the working tree on 2026-10-30, plus the committed contrast called out where it matters.

## Layout

| Part | Path | Role |
|---|---|---|
| API | `apps/api` | FastAPI app `hrms.app:create_app`, Alembic, Celery worker and beat |
| Web | `apps/web` | Next.js App Router, `NEXT_PUBLIC_API_URL` |
| Mobile | `apps/mobile` | Flutter, `API_BASE_URL` via `--dart-define` |
| Production compose | `docker-compose.prod.yml` | Postgres 16, Redis 7, object storage, migrate, api, worker, beat, web, nginx, certbot |
| Dev compose | `docker-compose.yml` | Host ports 5433, 6380, 9000. Not for the VPS |
| Edge | `infra/nginx` | TLS vhosts for web, API, storage |

There are no systemd units in the repository. Process supervision in the documented production shape is Docker Compose. Hostinger firewall, DNS, and cron are operator steps in `docs/deployment/`, and those runbooks say they have not been executed.

## Request path

```
Web or Flutter
  -> HTTPS (intended) /v1
  -> Nginx
  -> API (gunicorn)
  -> RequestContextMiddleware (X-Request-Id)
  -> auth dependency (access JWT, session row, membership)
  -> tenant context from the token, not from X-Company-Id   [working tree only]
  -> permission + data scope
  -> attendance service
  -> PostgreSQL (RLS on company_id)
  -> optional immediate AttendanceDayService.calculate
  -> JSON envelope
  -> client renders stored fields
```

Routers mount at `/v1` in `apps/api/src/hrms/app.py` (attendance around lines 203–224, payroll included unconditionally at line 226).

Company id on writes comes from the tenant context. Self punch uses `user.employee_id` from the access token (`apps/api/src/hrms/modules/attendance/router.py`, `POST /attendance/punches/me`).

## Attendance data model (logical)

```
company
  employee  -- employment (joining / last working day, pay basis)
           -- employee_assignment (shift, branch, department, effective dates)
  attendance_policy / overtime_policy / regularization_policy  (+ versions)
  shift / shift_version / shift_break / duty blocks
  work calendar, holiday calendar, weekly-off pattern
  shift_roster (published row wins over the assignment for that date)
  punch (insert-only)
  attendance_day (one row per company + employee + date)  <-- calculation output
  attendance_break, overtime_record
  attendance_regularization_request + requested punches + actions
  leave_application -> leave_day_projection (only APPROVED projections affect the day)
  attendance_period (lock) + summary
  geofence authorizations + geofence_attempt
  face profile / liveness (optional, provider off unless configured)
```

The calculation source of truth is `evaluate_day` in `apps/api/src/hrms/modules/attendance/calculation.py`. `AttendanceDayService.calculate` in `service.py` is the only production writer of a day row. The company overview (`overview.py`) groups those stored rows. It does not re-run rules.

Background:

| Beat name | Local time (`Asia/Kolkata`) | Task |
|---|---|---|
| `attendance-run-daily-calculation` | 09:30 | Recalculate today and the previous two local days for active employees |
| `attendance-run-incomplete-reminders` | 10:00 | Email incomplete days |
| `attendance-run-face-cleanup` | 03:15 | No-op until retention is configured |
| `attendance-run-face-deletions` | every 2 minutes | Deletes queued face artifacts |

Defined in `apps/api/src/hrms/core/celery_app.py`. The API image sets `TZ=UTC` (`apps/api/Dockerfile`). Beat’s timezone is the application setting, default `Asia/Kolkata`, with `enable_utc=True`.

## Feature-to-code map

Status is whether a full path exists in code. “Verified live” means this audit executed the user-facing workflow against a running API. None of the rows below were verified live.

| Feature | Backend | Web | Flutter | Database | Tests |
|---|---|---|---|---|---|
| Login / session | `modules/identity` login, refresh cookie, logout | `lib/auth`, localStorage access token, HttpOnly refresh cookie | `auth_controller`, secure storage + cookie jar | `user`, session, refresh token hash | Flutter auth tests passed. API integration tests not run here. |
| Self check-in / check-out | `POST /v1/attendance/punches/me`. Server clock. No client `punch_time`. | `punch-entry-dialog.tsx` posts `{direction, reference?}`. | `attendance_repository.dart` posts direction, idempotency key, location or location error. | `punch` timestamptz, partial unique idempotency index | Calculation unit tests passed. Punch HTTP tests not run. |
| On-behalf punch | `POST /v1/attendance/punches` requires `PUNCH_ON_BEHALF` and a timezone-aware `punch_time`. | Same dialog, other employee, wall time converted in company zone. | Team attendance screen. | Same `punch` table, source `ADMIN`. | Web punch-time tests passed on isolated rerun. |
| Working hours, late, early, OT, half day | `evaluate_day` only. | Displays `worked_minutes` and clocks in the day/company zone. | Same stored fields. Month card counts client-side from day rows. | `attendance_day` columns. | `test_calculation.py` and related unit files passed (180 tests in the first batch). |
| Duplicate punch | Optional idempotency key. Same-direction punches inside the policy window collapse at calculation time, not at insert. | Button disabled while `saving`. No idempotency key. | In-memory key reused only after a status-0 failure. | No unique punch instant. | Idempotency widget tests exist and were part of the Flutter suite that passed. Not proven under concurrency against Postgres. |
| Geofence | `geofence.py` / `geofence_service.py`. Default mode `DISABLED`. | Dialog sends no location. `Permissions-Policy` sets `geolocation=()`. | GPS when policy is not `DISABLED`. | `employee_workplace_authorization`, `geofence_attempt`. | Geofence unit tests passed. Runtime RLS test not run. |
| Face punch | Optional. Blocks plain web punch only when a profile is `ENROLLED`. Provider default disabled. | Enrollment UI exists. | Liveness capture and multipart punch. | Face tables in `20261005090000_face_attendance.py`. | Flutter face widget tests ran inside the passing suite. OpenCV missing in this environment for two liveness unit tests. |
| History / day detail | `GET /attendance/days`, `GET /attendance/days/{id}`. | `/app/attendance`, `/app/me`, `/app/attendance/[id]`, employee panel. | Last 14 business days, month grid, day detail. | Unique `(company_id, employee_id, attendance_date)`. | Web page tests exist. Not live. |
| Monthly summary | Period summary is a lock-time artifact. Employee month views sum day rows. | Attendance page `summarizeWorkHours` in the browser. | `attendance_month_card.dart` counts locally. | `attendance_period_summary`. | Period summary unit tests included in the second pytest batch (see doc 07). |
| Company dashboard | `GET /v1/dashboards/company/attendance-overview` (**untracked** `overview.py`). | `components/dashboard`, `lib/dashboard/overview.ts` (**untracked**). | `dashboard_screen.dart` loads company dashboard; team attendance is separate. | Reads `attendance_day` + active employment. | `test_company_attendance_overview.py` exists and was **not run**. |
| Pending approvals | Leave, regularization, overtime list endpoints. | `use-pending-approvals.ts` with permission gates. | Request screens. | Status columns and partial unique submitted regularization. | Not run live. |
| Shifts / rosters | Organisation shift APIs + attendance roster APIs. Published roster wins for the date. | Shifts, rosters, calendar, grid pages call the API. Grid pages past 500; calendar uses one page. | Roster screens. | Shift versions, roster partial unique per employee-date. Composite shift FK is the untracked migration. | Shift service unit tests were not in the executed subset. |
| Weekly off / holiday | Calendar resolution inside `calculate`. | Holiday calendars and weekly-off pages. My Calendar uses `/employee-calendar/me`. | Day type lookup. | Holiday and weekly-off unique codes/dates. | Calendar page test passed on rerun. |
| Leave vs attendance | Only `leave_day_projection.status == APPROVED` changes the day. Pending leave is ignored. | Leave application UI. | Leave screens. | Projection has no FK to the leave application id. | Leave integration tests not run. |
| Regularization | Submit, cancel, approve, reject. Synthetic punches then `calculate`, then `mark_regularized`. | `/app/regularizations`. | `request_resources.dart`. | Partial unique on `SUBMITTED`. Check constraint omits `EARLY_DEPARTURE_APPROVAL`. | Not run against the database. |
| Overtime approval | Records produced by the engine; approve/reject routes. | `/app/overtime`. | Request screens. | `overtime_record` unique per day. | Night OT unit tests passed. |
| Notifications | Incomplete-day email at 10:00 IST. | No separate attendance push channel found as the source of truth. | No offline outbox. | Audit action dedupes the reminder. | Not run. |
| Exports | Not a dedicated attendance export product in the paths traced. Period summary is the closest HR artifact. | Attendance page is on-screen. | Insights screen. | — | Not claimed. |

## What is outside the calculation engine

These are not second engines, and they must not be treated as one:

- `overview.py` classifies a **today** row whose shift has not ended: zero punches become “not checked in”, an open punch becomes “present”. That judgement is time-based and documented at the top of the file. It does not recompute minutes.
- `apps/web/src/lib/attendance/dashboard.ts` `bucketOf` / KPI helpers re-bucket day rows already returned by the list API. They do not recompute minutes. They do use different bucket names than the company overview (half day is its own bucket; overview folds `HALF_DAY` into present).
- Flutter month counts are a client tally of returned statuses.

## Payroll coupling

`create_app` always imports `hrms.modules.payroll.router` (`app.py` line 212 and 226). A broken payroll import prevents API startup. The worker entrypoint does not import payroll. The only attendance-to-payroll call on the attendance side is `AttendancePeriodService.reopen`, which refuses to reopen a period that already has a finalised pay run (`service.py` around 6517–6521). Punch and daily status do not import payroll.

## Classification of modules for this release

| Module | Class |
|---|---|
| Identity / auth | Required |
| Employee, employment, assignment | Required |
| Attendance punch, day, calculation | Required |
| Company attendance overview | Required for the admin dashboard (present only in the working tree) |
| Shifts, rosters, calendars, holidays, weekly offs | Supporting |
| Leave projections | Supporting, because approved leave changes attendance status |
| Regularization | In the product today; required if the menus stay enabled |
| Geofence | Supporting; default off |
| Face | Optional and must stay off until calibrated |
| Onboarding | Supporting only so an employee can exist and sign in |
| Payroll, payslips, statutory | Outside this release. Do not delete. Do not block startup. |
