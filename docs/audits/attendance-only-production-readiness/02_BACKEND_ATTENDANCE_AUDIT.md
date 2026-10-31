# Backend attendance audit

Evidence: working-tree source. HTTP behaviour was **not** executed against Postgres in this audit (see `07_TEST_AND_QA_RESULTS.md`). Calculation unit tests were executed.

## 4.1 Recording a punch

### Self punch

`POST /v1/attendance/punches/me` (`router.py` 802–843).

- Permission: `ATTENDANCE.PUNCH`.
- Body: `PunchCreateSelf` (`schemas.py` 1339–1381). `extra="forbid"`. Fields are `direction`, optional `reference`, optional `idempotency_key`, optional `location`, optional `location_error`. There is no `employee_id`, `punch_time`, or `source`.
- Employee id is the token’s `employee_id`.
- Source stored as `WEB` (face uses `FACE`).
- Clock: `datetime.now(UTC)` when the client does not supply a time (`service.py` 2722–2732).
- Rate limit: 600/minute per tenant and client IP (`router.py` around 806).

### On-behalf punch

`POST /v1/attendance/punches` (`router.py` 846–884).

- Permission: `ATTENDANCE.PUNCH_ON_BEHALF`.
- Body requires `employee_id`, timezone-aware `punch_time`, `direction`, and a non-empty `reference`.
- Future `punch_time` raises `FuturePunchTimeError` (`service.py` 2722–2732).
- No rate limit on this route.
- Visibility: `_ensure_employee_visible` runs before idempotency lookup (`service.py` 2680–2682). Out of scope is a 404.

### What holds

| Check | Result | Evidence |
|---|---|---|
| Employee cannot punch as someone else on `/me` | Holds in code | Schema forbids `employee_id`. Handler uses the token. |
| Tenant comes from the token in the working tree | Holds in code | `tenancy/middleware.py` 8–29 does not read the header. `get_tenant_context` 404s a mismatched header. |
| Same check on committed `HEAD` | **Fails** | `git show HEAD:apps/api/src/hrms/core/tenancy/middleware.py` sets tenant from `X-Company-Id` before auth. Finding ATT-SEC-001. |
| Duplicate check-in prevented at insert | **Does not hold** unless the client sends an idempotency key | Partial unique index only on `(company_id, idempotency_key)` where the key is not null (`20260820090000_punch.py` 57–59). Two self punches without a key both insert. |
| Calculation-time collapse | Holds inside the policy duplicate window | `collapse_duplicate_punches` (`calculation.py` 500–515) keeps the first of consecutive same-direction punches. |
| Check-out without check-in | Stored as an orphan punch. Day status follows missing-punch policy. | `pair_punches` (`calculation.py` 523–549). |
| Concurrent first day row | Savepoint plus unique `(company_id, employee_id, attendance_date)`, then re-read | `service.py` 3187–3234. Day row is locked with `FOR UPDATE` when it already exists (`repository.py` 1120–1128). |
| Punch then failed calculate | Punch remains. Calculate errors are logged and swallowed | `_try_immediate_calculate` (`service.py` 2852–2913). The 09:30 sweep is the backstop. |
| Client timestamps on self punch | Not accepted | Schema. |
| Geofence | `WEB` and `FACE` only. `ADMIN` and `REGULARIZATION` skip it. Default policy mode `DISABLED` (`schemas.py` 414, `models.py` 149). `REQUIRED` rejects a punch with no acceptable fix and writes no punch row. | `geofence.py` 163–194, `geofence_service.py` 245–315. |

### ATT-PUNCH-001 — Idempotency is optional and the web client omits it

- Severity: Medium. Platform: API + web. Feature: check-in / check-out.
- Paths: `schemas.py` 1339–1381; `punch-entry-dialog.tsx` (self body has direction and optional reference only); unique index in `20260820090000_punch.py` 57–59.
- Evidence: code inspection. Flutter does send a key (`attendance_repository.dart` 376–385).
- Reproduction: two `POST /attendance/punches/me` calls without `idempotency_key`, same direction, close together. Both rows insert. Hours collapse only if they fall inside `duplicate_punch_window_seconds`.
- Impact: a double click or a retried web request can store two punches. A retry after the process dies on mobile can do the same, because the key is not persisted.
- Correction: require a key on self punch, or make the web dialog send one and reuse it when the response is unknown. Keep the calculation collapse as a backstop.
- Blocks deployment: no for a single careful user. Yes as a correctness fix before a large rollout. Classed as “should fix soon” in document 09.

### ATT-PUNCH-002 — A successful punch can commit without a day row

- Severity: Medium. Platform: API. Feature: immediate status.
- Path: `service.py` 2852–2913.
- Evidence: code inspection. The nested calculation exception is logged and not re-raised.
- Impact: the employee sees a stored punch and may not see worked hours until the sweep or a manual recompute. The data is not half-written inside the punch row. The day can be missing or stale.
- Correction: surface the calculation failure to the client, or retry it on the same transaction when the error is transient. Keep the sweep.
- Blocks deployment: no. Operators must know to watch that log line.

## 4.2 Calculation engine

`evaluate_day` (`calculation.py` 879–1016) is the status engine. `AttendanceDayService._calculate` (`service.py` 3151–3154) is the production caller. Callers include the punch hook, HTTP recompute, the Celery range task, approved regularization, and leave projection sync/cancel.

Worked minutes: `pair_punches` then `presence_span` (`PAIR_ALL` sums pairs; `FIRST_IN_LAST_OUT` uses first in to last out) then `worked_minutes_from_gross` (582–598).

Late: minutes after `scheduled_start` minus `grace_in_minutes` (1407–1412). Early: minutes before `scheduled_end` minus `grace_out_minutes` (1413–1416).

Missing checkout: zero work becomes `ABSENT` only when policy says so, otherwise `INCOMPLETE` (1745–1749). Some work with `AUTO_CLOSE` falls through to hour bands (1755–1756).

Leave overlay: approved fraction ≥ 1.00 becomes `LEAVE` (`_apply_leave_overlay`, 1107–1198). Pending projections are not loaded (`repository.py` 2254–2268).

Overtime: `detect_overtime` (824–871). `NEVER` and `SHIFT_FLAG` are special. `GRADE_VIA_ASSIGNMENT` is not a separate branch.

There is no second hours formula in the web or Flutter clients. They display stored minutes.

### ATT-CALC-001 — Punch rounding is stored and never applied

- Severity: Medium. Platform: API. Feature: late / early / worked minutes.
- Paths: `apply_rounding` defined at `calculation.py` 696. Repository search finds no caller. Policy column default `NONE` (`models.py` 95).
- Impact: a company that sets rounding to 5 or 15 minutes still gets raw instants. With the default `NONE`, results match the raw clock.
- Correction: call `apply_rounding` on the copies used for late, early, and duration. Do not mutate stored punch times.
- Blocks deployment: no while every policy stays `NONE`. Becomes a blocker the moment rounding is configured.

### ATT-CALC-002 — `missing_punch_behaviour=AUTO_CLOSE` does not set `auto_closed`

- Severity: Medium. Platform: API. Feature: missing checkout.
- Paths: `auto_closed = False` at `calculation.py` 1400. The branch at 1755–1756 says the caller sets the flag. No assignment of `True` exists in the module.
- Impact: status can still follow hour bands. The flag the UI and reports would use stays false. The policy does not synthesize a checkout.
- Correction: set the flag in the engine when that behaviour is selected, and define the synthetic end (scheduled end versus last legal instant) in one place.
- Blocks deployment: no at the default missing-punch behaviour.

### ATT-CALC-003 — `is_regularized` is cleared by the next calculate

- Severity: High. Platform: API. Feature: regularization audit flag.
- Paths: `_result_to_values` sets `"is_regularized": False` (`service.py` 3596). Approval calls `calculate` and then `mark_regularized` (`service.py` 5117–5127, repository `mark_regularized` at 1300). The daily task recalculates today and two trailing days (`tasks.py` 56–58 and 122–148) and writes `False` again.
- Impact: hours and status are recomputed from punches, including the synthetic regularization punches, so the worked result can stay correct. The day no longer says it was regularized after the next sweep. `is_pending_approval` is also overwritten with overtime’s `ot_pending` (`service.py` 3597), while regularization submit uses the same column (`repository.py` 1272–1289).
- The overview does not trust that flag alone. It also uses an `EXISTS` on `SUBMITTED` regularization (`overview.py` 107–112).
- Correction: preserve `is_regularized` across recompute. Store overtime pending on its own column.
- Blocks deployment: no for recording punches. Yes before regularization is presented as a durable audit mark. Classed as should-fix-soon because the request row, action timeline, and synthetic punches remain.

### ATT-CALC-004 — Several regularization types do not change status

- Severity: High for any company that offers them. Platform: API + both clients.
- Paths: engine comment at `calculation.py` 1732–1734 (WFH is a no-op). `_apply_correction` writes punches and an optional roster shift, then runs the normal engine (`service.py` 5086–5127). `ON_DUTY` is a real overlay (`calculation.py` 1201–1224). Overview buckets status `WFH` as `REMOTE` (`overview.py` 94) and nothing in the engine emits `WFH`.
- Impact: an approved WFH, WRONG_STATUS, FULL_DAY, or EXCESS_BREAK request can leave the day status unchanged except for whatever punches or shift it happened to carry. The employee sees an approved request and the same attendance result.
- Correction: either implement the status effect or remove those types from policy allow-lists and both clients.
- Blocks deployment: no if those types are not enabled on the published regularization policy. The schema still lists them, so a default policy that allows them is a release problem. Treat as should-fix-soon and verify the seeded allow-list before go-live.

### ATT-REG-001 — `EARLY_DEPARTURE_APPROVAL` cannot be stored

- Severity: High. Platform: API, database, Flutter, web if the type is selectable.
- Paths: Python allow-list `schemas.py` line 123. Submit and calculate read the type (`service.py` 4037, 4454–4458). Check constraint `attendance_regularization_request_request_type_check` (`20260822090000_regularization_request.py` 100–105) lists `MISSING_PUNCH`, `WRONG_PUNCH`, `WRONG_SHIFT`, `WRONG_STATUS`, `WFH`, `ON_DUTY`, `EXCESS_BREAK`, `FULL_DAY` only. The policy allowed-type check in `20260819120000_regularization_policy.py` 137–141 matches that shorter list. No later migration adds the new type.
- Reproduction: submit a regularization with `request_type=EARLY_DEPARTURE_APPROVAL`. Pydantic accepts it. The insert fails the check constraint.
- Impact: the early-departure approval overlay in the engine cannot be reached through a persisted request. The client shows a type the database rejects.
- Correction: a migration that extends both check constraints, or remove the type from `schemas.py` and the mobile form until the migration exists. This audit did not add that migration.
- Blocks deployment: yes, unless the type is removed from every client and from the API schema before release.

## 4.3 Shifts, weekly offs, holidays, overnight

Resolution order in `_build_calculation_input` (`service.py` 3677–3766):

1. Published `ShiftRoster` for that employee and date.
2. Else `EmployeeAssignment.shift_id` as of the date.
3. Shift version effective on that date. Missing version yields no shift.

Timezone for the window: shift version, else branch, else company (`calculation.py` 326–330). Companies are allow-listed to `Asia/Kolkata`. A branch or shift may still name another IANA zone.

Window (`resolve_schedule_window`, 407–479):

- No shift: local midnight to next local midnight.
- `FIXED`: scheduled span, punch load padded by 2 hours each side. Cross-midnight uses `is_cross_midnight`.
- `FLEXIBLE`: window is the span; punch load is −2h / +12h.
- `SPLIT`: first block start to last block end.

Weekly off and holiday come from calendar resolution. A weekly off or holiday is `NOT_EXPECTED`, not `ABSENT`, unless a roster override says the person is expected to work (`evaluate_day` 948–988).

The company overview does not mark “shift not started” as absent **when an `attendance_day` row exists**: for today, a zero-punch open status stays `NOT_CHECKED_IN` until `scheduled_end` (`overview.py` 84–102). Employees with **no row** are `no_record`, not absent (`overview.py` 12–14). If beat is down and nobody has punched or calculated, the dashboard shows no record rather than a false absence. That is the safe failure. It is also an empty dashboard.

### ATT-SHIFT-001 — Immediate calculate uses the punch’s local calendar date

- Severity: Medium. Platform: API. Feature: overnight shifts.
- Path: `service.py` 2877–2896. The comment there states a cross-midnight punch can belong to the previous local date and this hook does not resolve that. The 09:30 sweep covers three local days (`tasks.py` 56–58).
- Impact: an overnight checkout just after midnight can update “today” first and leave “yesterday” stale until the sweep, a manual recompute, or another punch. A punch more than 2 hours outside the scheduled window is not loaded for that date.
- Correction: resolve the shift date before choosing which day to calculate, and calculate both candidate dates when the punch sits near midnight.
- Blocks deployment: no for daytime shifts. Yes as a known limit for overnight rosters until the sweep has run. Document it for the first customers if they run night shifts.

Hardcoded pads (±2h, flexible +12h) are engine constants, not company settings.

## 4.4 Leave

| Case | Effect on the day | Evidence |
|---|---|---|
| Approved full day | Status `LEAVE`, late/early/OT cleared, fraction `1.00`. Worked minutes raise `work_on_leave_flagged`. | `calculation.py` 1107–1198. Projection written in the leave approval transaction (`leave/service.py` 3145–3162). |
| Approved half day | `HALF_DAY` if any minutes worked, else `LEAVE`. The working remainder is a flat fraction, not half of the shift window. | Same overlay, docstring lines 35–39. |
| Pending | Not read. Query filters `status == APPROVED`. | `repository.py` 2254–2268. |
| Rejected / cancelled | Cancel removes the projection and recalculates (`LeaveProjectionService.cancel`). | `attendance/service.py` around 6833; leave cancel around `leave/service.py` 3408–3468. |
| Leave on weekly off or holiday | Overlay runs after the calendar short-circuit only when the day is still evaluated. A pure off day returns `NOT_EXPECTED` before pairing when no work is expected. | `evaluate_day` 948–1004. Exact stacking was not executed as a fixture in this audit. |
| Leave approved after a punch exists | Sync calls `calculate` in the same transaction. Closed period refuses the sync and rolls the leave transaction back. | `service.py` 6626–6629 and 6723–6728. |

`LeaveDayProjection.leave_application_id` has no foreign key (`models.py` 1255–1257). The model comment still says no leave module exists (`models.py` 1221–1225). The leave module does call this adapter. Integrity of the link is application-level.

Pending leave is not counted as approved leave by the engine or by the overview (`overview.py` buckets status `LEAVE` only).

## 4.5 Regularization workflow

| Rule | Evidence |
|---|---|
| Self request uses `REGULARIZATION_REQUEST`. Another employee id requires `REGULARIZATION_REQUEST_ON_BEHALF`. | `router.py` 1288–1302. |
| Scope is checked again in the service. | `service.py` 4432–4434. |
| One `SUBMITTED` row per employee per date. | Partial unique index `20260822090000_regularization_request.py` 108–110. IntegrityError becomes a duplicate error (`service.py` 4540–4547). |
| Self-approval on the review route is refused when the caller’s employee id is the subject. | `service.py` 4869–4871. |
| `AUTO` chain approves inside submit and skips that check. | `service.py` 4668–4678. Schema default chain is `MANAGER` (`schemas.py` 786). |
| Approval writes `source=REGULARIZATION` punches and then calculates. A calculation error rolls the approval back. | `service.py` 5086–5124. |
| Reject and cancel do not apply punches. Cancel is only the original submitter, and only while `SUBMITTED`. | `service.py` 4694–4705. |
| History | `AttendanceRegularizationAction` plus `AuditService.record`. |
| Monthly cap window | Built from `datetime(now.year, now.month, 1, tzinfo=UTC)` (`service.py` 4531–4536). That is the UTC month, not the company month. |

### ATT-REG-002 — Regularization monthly cap uses the UTC month

- Severity: Low for India (UTC month flips at 05:30 IST). Platform: API.
- Path: `service.py` 4531–4536.
- Impact: a request just after midnight IST on the 1st can count against the previous UTC month.
- Correction: use `business_month_start(company.timezone)`, which leave already uses.
- Blocks deployment: no.

## 4.6 API surface (attendance)

All routes require an authenticated tenant. Envelope types are `DataEnvelope` / `ListEnvelope`. List endpoints that use `bounded_pagination_params` cap at **500** (`apps/api/src/hrms/shared/pagination.py` 95–110).

| Method | URL | Permission | Notes |
|---|---|---|---|
| POST | `/v1/attendance/punches/me` | `ATTENDANCE.PUNCH` | 201 `PunchRead`. Server time. |
| POST | `/v1/attendance/punches` | `PUNCH_ON_BEHALF` | Client time, must not be in the future. |
| GET | `/v1/attendance/punches` | `VIEW` | Filters, page, scope. |
| GET | `/v1/dashboards/company/attendance-overview` | `DASHBOARD.COMPANY_VIEW` and `ATTENDANCE.VIEW` | **Working tree only.** Query `date`, `department_id`, `branch_id`. |
| GET | `/v1/attendance/days` | `VIEW` | Status filter. Max 500. |
| GET | `/v1/attendance/days/{id}` | `VIEW` | 404 outside scope. |
| POST | `/v1/attendance/days/calculate` | `VIEW_ALL` | |
| POST | `/v1/attendance/days/{id}/recompute` | `RECOMPUTE` | |
| POST | `/v1/attendance/days/calculate-range` | `RECOMPUTE` | 202 queued. |
| POST | `.../work-on-leave/keep-leave` | `RECOMPUTE` | |
| POST/GET/PATCH | `/v1/regularizations` and `/{id}/approve\|reject\|cancel` | Request or `REGULARIZATION_APPROVE` | `If-Match` on review. |
| GET/POST | `/v1/overtime` and approve/reject | `VIEW` / `OVERTIME_APPROVE` | |
| * | `/v1/attendance-periods` | `VIEW` / `LOCK` / `UNLOCK` | Reopen checks payroll finalised runs. |
| * | `/v1/rosters` | `VIEW` / `ROSTER_MANAGE` | |
| * | Policy, overtime policy, regularization policy | `POLICY_MANAGE` | Versioned drafts and publish. |
| GET | `/v1/attendance/geofence-policy/me` | `PUNCH` | |
| * | Geofence admin and attempts | `POLICY_MANAGE` / `VIEW_ALL` | |
| * | Face enrollment and face punch | `PUNCH` or `FACE_ENROLLMENT_MANAGE` | Provider must be enabled. |

Error contract is the shared envelope (`docs/development/API_ERROR_CONTRACT.md`). This audit did not replay every status code.

Date/time: punch instants are timezone-aware UTC. Attendance dates are civil dates. Clients are expected to format with the company or day zone, not the browser zone. Web on-behalf entry does that (`wallTimeToUtcIso`). Self punch sends no time.

### ATT-API-001 — Web list clients drop pagination

- Severity: High once a company has more than 500 day-rows in the fetched window. Platform: web against API.
- Paths: days route `router.py` 951–977; `apiClient.get` unwraps `.data` and drops `pagination` (`apps/web/src/lib/api/client.ts` 192–195); `use-dashboard-data.ts` does not request later pages.
- Impact: the Attendance command centre can under-count present, absent, and hours. The company overview endpoint does not have this cap because it aggregates in SQL.
- Correction: page until `pagination.total` is consumed, or stop using the day list as a company total.
- Blocks deployment: no for a team that fits in 500 rows (about 35 employees over 14 days). Yes before the Attendance page is used as the company total for a larger workforce. The company dashboard overview is the path that scales.

## Permissions that matter for this release

Seeded employee role (`organisation/service.py` 818–834): `ATTENDANCE.PUNCH`, `ATTENDANCE.VIEW`, `ATTENDANCE.REGULARIZATION_REQUEST`, all `SELF`. It does not receive punch-on-behalf, view-all, on-behalf regularization, or approve.

`HR_ADMIN` and `COMPANY_ADMIN` receive company-wide attendance permissions (same file, admin around 578–581, HR around 655–684). A reporting-manager role gets approve codes and does not get `ATTENDANCE.VIEW`, so it cannot list reportee attendance. That is fail-closed.

## Background jobs required for attendance

The 09:30 calculation sweep is required for days that never receive a punch and for overnight correction. Without beat, those employees stay `no_record` on the overview until someone runs calculate. Incomplete reminders are operational, not required to record a punch. Face deletion is required only if face enrollment is turned on. Leave accrual at 01:00 is outside attendance status except where leave approval writes a projection immediately (it does, in-process).

Beat documents that duplicate firings are possible (`tasks.py` 19–21). Recalculation replaces derived fields, so a double run does not double hours. It does re-clear `is_regularized` (ATT-CALC-003).
