# Employee mobile: final API and permission matrix

Status: **approved baseline pending sign-off** · Verified 2026-10-30 against `apps/api` and `apps/mobile` at working-tree state (see §9 for uncommitted files) · Documentation only, no source changed.

Companion documents (all must agree; IDs are shared):
[Final audit](EMPLOYEE_MOBILE_FINAL_AUDIT.md) · [Final redesign specification](EMPLOYEE_MOBILE_FINAL_REDESIGN_SPECIFICATION.md) · [Final implementation plan](EMPLOYEE_MOBILE_FINAL_IMPLEMENTATION_PLAN.md) · [Final design system](EMPLOYEE_MOBILE_FINAL_DESIGN_SYSTEM.md).

Verification marks used throughout: **✔** read in source in this pass · **◐** partly verified, remainder stated · **✖** not verified (stated as such, never assumed).

---

## 1. What this document is

The single list of every backend call the employee mobile experience makes or may make, the permission that gates it, and what the screen may rely on. Nothing here is a new API. Anything the redesign would like but the API cannot give is in §8 as a *future proposal* and is not a dependency of any task.

Rules that follow from it:

1. A screen or Home widget may call only the endpoints in §3.
2. Hiding a control or menu entry is never authorisation. The API enforces every row below; the client mirrors it only to avoid showing dead ends (§6 of the redesign spec).
3. Every list call for "mine" sends `employee_id=<own id>` explicitly. The permission scope narrows results for an `EMPLOYEE` but widens them for a user who also holds a broader role (§2.3).

---

## 2. Role grants (✔ `apps/api/src/hrms/modules/organisation/service.py`)

### 2.1 System `EMPLOYEE` role, every grant `SELF` scope

| Permission | Gate for |
|---|---|
| `EMPLOYEE.VIEW` | `GET /employees/{id}`, `/employments`, `/assignments` (own record only) |
| `EMPLOYEE.VIEW_COMPENSATION` / `_STATUTORY` / `_BANKING` / `_SENSITIVE` / `_EXPERIENCE` / `_NOMINEE` / `_DOCUMENTS` | The matching own-record tabs (read only) |
| `LEAVE.APPLICATION_SUBMIT` | `POST /leave-applications` (self), cancel own |
| `LEAVE.BALANCE_VIEW` | `GET /leave-balances`, `GET /leave-ledger`, **and** `GET /leave-applications` (see §4) |
| `ATTENDANCE.PUNCH` | `POST /attendance/punches/me`, face punch, `GET /attendance/geofence-policy/me`, `GET`/`POST /attendance/face-enrollment/me` |
| `ATTENDANCE.VIEW` | `GET /attendance/days`, `/attendance/days/{id}`, `/attendance/punches`, `/regularizations`, `/overtime` |
| `ATTENDANCE.REGULARIZATION_REQUEST` | `POST /regularizations`, cancel own |
| `PAYROLL.PAYSLIP_VIEW_OWN` | `GET /me/payslips`, `GET /me/payslips/{run_id}` |

Not granted (must stay unreachable from employee UI): punch on behalf, attendance recompute, keep-leave, regularization/overtime/leave approve, leave submit on behalf, balance adjust/encash, `LEAVE.BALANCE_VIEW_ALL`, employee list/edit, `UPDATE_SENSITIVE` (document manage), payroll process/setup, every `ORG.*.MANAGE`, `SETTINGS.*`, `DASHBOARD.COMPANY.VIEW`.

### 2.2 Other seeded roles that hold `employeeId` and no dashboard grant

`REPORTING_MANAGER` (adds `LEAVE.APPLICATION_APPROVE`, `ATTENDANCE.REGULARIZATION_APPROVE`, `ATTENDANCE.OVERTIME_APPROVE`, `LEAVE.BALANCE_VIEW_ALL`, `EMPLOYEE.VIEW` at `REPORTEE_TREE`) and `BRANCH_MANAGER` (adds `EMPLOYEE.VIEW_ALL`, `ATTENDANCE.VIEW` at `BRANCH`). Roles are additive. These users are on the **employee surface** (§D-03) but carry Team/approve permissions, so every shared screen must keep its permission branches.

### 2.3 Scope caveat (✔)

`GET /attendance/days`, `/attendance/punches`, `/regularizations`, `/overtime` resolve scope from `ATTENDANCE.VIEW`; `GET /leave-applications` from the combined leave scope. With `employee_id` omitted a user holding a wider scope receives other people's rows. Therefore **Home and every "Mine" view send `employee_id` = `UserProfile.employeeId`**. This is already what the Attendance screen does.

---

## 3. Endpoint catalogue

`Repo` = existing Dart method. "Perm" = what the API checks. "Employee" = reachable with default `EMPLOYEE` grants.

### 3.1 Authentication and session

| Endpoint | Repo (`features/auth/data/auth_repository.dart`) | Perm | Employee | Notes |
|---|---|---|---|---|
| `POST /auth/login` | `login` | public | ✔ | 401 invalid, 423 lock, 429 throttle, `EMAIL_NOT_VERIFIED` |
| `GET /auth/me` | `me` | authenticated | ✔ | `UserProfile`: `id, email, company_id, employee_id, permissions[], company_timezone, company_status`. **No name field**; display name needs `GET /employees/{id}` |
| `POST /auth/logout` | `logout` | authenticated | ✔ | `AuthController.logout` swallows errors and always clears local session ✔ |
| 401 refresh | `ApiClient` (cookie jar) | refresh cookie | ✔ | automatic, one in flight |
| `POST /auth/password/forgot` | `forgotPassword` | public | ✔ | *prior docs said `/auth/forgot-password`: wrong* |
| `POST /auth/password/reset` | `resetPassword` | public | ✔ | |
| `POST /auth/email/verify` | `verifyEmail` | public | ✔ | |
| `POST /auth/email/resend-verification` | `resendVerification` | public | ✔ | |
| `GET /public/account-invites/{token}` | `getInvite` | token | ✔ | |
| `POST /public/account-invites/{token}/accept` | `acceptInvite` | token | ✔ | *prior docs said `/auth/accept-invite`: wrong* |
| `POST /companies/register` | `registerCompany` | public | n/a | company sign-up, out of scope |

### 3.2 Public onboarding (token, no session)

Base `/public/onboarding/{token}` (`public_onboarding_repository.dart` ✔): load case, `PATCH` section, upload document, submit. Auth is the token. Section order and PATCH-on-continue are contract.

### 3.3 Attendance

| Endpoint | Repo (`attendance_repository.dart`) | Perm / scope | Key response fields | Notes |
|---|---|---|---|---|
| `GET /attendance/days?employee_id&date_from&date_to` | `listAttendanceDays` | `ATTENDANCE.VIEW` | `AttendanceDayRead`: `attendance_date, timezone, attendance_status, actual_first_in, actual_last_out, worked_minutes (int, never null), scheduled_start/end, late_minutes, missing_punch, auto_closed, calendar_day_type, holiday_name, calculated_at, is_locked, breaks[]` | Pages of 100, capped 50. **Returns persisted rows only; never creates one** ✔ |
| `GET /attendance/days/{id}` | `getAttendanceDay` | `ATTENDANCE.VIEW` | same | 404 if outside scope |
| `GET /attendance/punches?employee_id&date_from&date_to` | `listPunches` (exists, today used only by HR panel) | `ATTENDANCE.VIEW` | `PunchRead`: `punch_time, direction (IN|OUT), source, reference, created_at` | **Ordered `punch_time DESC`** ✔. Date bounds are **UTC calendar days**, not company-zone ✔ |
| `POST /attendance/punches/me` | `punchMe` | `ATTENDANCE.PUNCH` (+ rate limit) | `PunchRead` (+ `geofence`) | body: `direction`, `idempotency_key`, `reference?`, `location?` xor `location_error?`; server stamps time, `source=WEB`; 403 `FACE_VERIFICATION_REQUIRED` when profile `ENROLLED` |
| `GET /attendance/geofence-policy/me` | `getMyGeofencePolicy` | `ATTENDANCE.PUNCH` | `mode DISABLED|OPTIONAL|REQUIRED`, `max_accuracy_m`, `max_age_seconds` | |
| `POST /attendance/face-punches/me/liveness-sessions` | `startFaceLivenessSession` | `ATTENDANCE.PUNCH` | session id, challenge | |
| `POST /attendance/face-punches/me` (multipart) | `facePunchMe` | `ATTENDANCE.PUNCH` | `punch`, `similarity`, `liveness_score` | |
| `GET /attendance/face-enrollment/me` | `getMyFaceEnrollment` | `ATTENDANCE.PUNCH` | `profile.status`, `open_window.expires_at`, `face_verification_required` | |
| `POST /attendance/face-enrollment/me` (multipart) | `submitFaceEnrollment` | `ATTENDANCE.PUNCH` | | only inside an HR-opened window |
| `GET /leave-projections?employee_id&date_from&date_to` | `listLeaveProjections` | leave/attendance scope ◐ | `leave_application_id, fraction, half, is_paid, status` | best effort on day detail; failure is silent today |
| `POST /attendance/days/calculate` | `calculateToday` | **`ATTENDANCE.VIEW_ALL`** | | HR only. Never from employee UI ✔ |
| `POST /attendance/days/{id}/recompute`, `.../work-on-leave/keep-leave` | | `ATTENDANCE.RECOMPUTE` | | HR only |
| `POST /attendance/punches` | `createPunchOnBehalf` | `ATTENDANCE.PUNCH_ON_BEHALF` | | HR only |

### 3.4 Leave

| Endpoint | Repo (`leave_repository.dart`) | Perm | Employee | Notes |
|---|---|---|---|---|
| `GET /leave-balances?employee_id=` | `listLeaveBalances` | `LEAVE.BALANCE_VIEW` (self) or `_VIEW_ALL` | ✔ | **The verified balance contract** (§4). Fields: `leave_type_id, leave_type_code, leave_type_name, balance (decimal string), reserved_balance` |
| `GET /leave-ledger?employee_id=&page=` | `listLeaveLedger` | same | ✔ | paged |
| `GET /leave-types` | `listLeaveTypes` | any authenticated; non-managers see active types only ✔ | ✔ | |
| `GET /leave-applications?employee_id&date_from&date_to&application_status&page` | `listLeaveApplicationsPage` | combined `LEAVE.BALANCE_VIEW`/`_VIEW_ALL` scope ✔ | ✔ | status query param is `application_status` |
| `GET /leave-applications/{id}` | `getLeaveApplication` | same | ✔ | |
| `POST /leave-applications` | `submitLeaveApplication` | `LEAVE.APPLICATION_SUBMIT` self; `_ON_BEHALF` if `employee_id` differs ✔ | ✔ self | `Idempotency-Key` required (repo supplies) |
| `POST /leave-applications/{id}/cancel` | `cancelLeaveApplication` | owner, or `LEAVE.APPLICATION_CANCEL_APPROVED` | ✔ | `If-Match` required; approved+started needs the permission |
| `POST .../approve`, `.../reject` | | `LEAVE.APPLICATION_APPROVE` | ✗ | |
| `POST /leave-ledger/adjustments`, `/encashments` | | `LEAVE.BALANCE_ADJUST` | ✗ | |

### 3.5 Regularizations and overtime

| Endpoint | Perm | Employee | Notes |
|---|---|---|---|
| `GET /regularizations` (`employee_id,date_from,date_to,request_status,request_type`) | `ATTENDANCE.VIEW` | ✔ | |
| `GET /regularizations/{id}` | `ATTENDANCE.VIEW` | ✔ | |
| `POST /regularizations` | `ATTENDANCE.REGULARIZATION_REQUEST` | ✔ | on-behalf variant needs `_ON_BEHALF` |
| `POST /regularizations/{id}/cancel` | submitter | ✔ | only while `SUBMITTED` |
| `POST .../approve`, `.../reject` | `ATTENDANCE.REGULARIZATION_APPROVE` | ✗ | |
| `GET /overtime`, `GET /overtime/{id}` | `ATTENDANCE.VIEW` ✔ | ✔ read | `OVERTIME_APPROVE` only for decisions |
| **`GET /shifts`** (form choice `shifts`) | **`ORG.SHIFT.MANAGE`** ✔ | **✗ 403** | see §9 finding F-1 |

### 3.6 Profile, records, documents, salary

| Endpoint | Perm | Employee | Notes |
|---|---|---|---|
| `GET /employees/{id}` | `EMPLOYEE.VIEW` | ✔ own | identity, contact, status; no department/designation/manager |
| `GET /employees/{id}/employments` | `EMPLOYEE.VIEW` ✔ | ✔ | joining date, pay basis |
| `GET /employees/{id}/assignments` | `EMPLOYEE.VIEW` ✔ | ✔ | **ids only**: `branch_id, department_id, designation_id, grade_id, reporting_manager_id, shift_id`, plus `work_location_type` ✔ |
| `GET /branches`, `/departments`, `/designations`, `/grades`, `/shifts`, `/legal-entities` | each `ORG.*.MANAGE` ✔ (confirmed for branches, departments, designations, shifts) | **✗** | **no employee-permitted way to turn those ids into names** |
| `GET /employees/{id}/statutory`, `/banking`, `/identity` etc. | `EMPLOYEE.VIEW_*` | ✔ | read-only |
| `GET /employees/{id}/documents` | `EMPLOYEE.VIEW_DOCUMENTS` ✔ | ✔ | presigned `download_url` |
| `GET /employees/{id}/salary`, `/salary/breakup?as_of=` | `EMPLOYEE.VIEW_COMPENSATION` | ✔ | |
| `GET /me/payslips` | `PAYROLL.PAYSLIP_VIEW_OWN` ✔ | ✔ | `PayslipSummary`: `pay_run_id, month, pay_date?, net_minor, status`; own **finalised** only; not paginated |
| `GET /me/payslips/{run_id}` | same ✔ | ✔ | full slip |

### 3.7 Not available (confirmed absent)

Announcements, tasks, notifications/push, employee holiday feed, team directory for `EMPLOYEE`, break punch, offline queue, help screen, employee dashboard. `GET /dashboards/company/attendance-overview` needs `DASHBOARD.COMPANY.VIEW` ✔ and must never be called from Home.

---

## 4. Leave balance contract (resolves audit item 2.3)

| Claim in the prior documents | Verified fact |
|---|---|
| `GET /employees/{id}/leave-balances` is used by employee leave balances | **False.** No such route exists in `apps/api`, and no mobile or web code calls it (grep over `api/src`, `mobile/lib`, `web/src`). |
| `GET /leave-balances` is used | **True.** `LeaveRepository.listLeaveBalances(employeeId)` calls `GET /leave-balances?employee_id=<id>` (`leave_repository.dart:248`); backend `leave/router.py:605` `get_leave_balances`; web calls the same URL (`leave-balances/page.tsx:116`). |

Contract: permission `LEAVE.BALANCE_VIEW` (SELF) **or** `LEAVE.BALANCE_VIEW_ALL`, combined in `_combined_balance_scope`; `employee_id` is a required query parameter; an employee outside scope gets the "not visible" error; the service also returns `reserved_balance` derived live from open applications. Ledger is `GET /leave-ledger?employee_id=&page=` under the same scope. **All specs and tasks cite `/leave-balances` only.** Existing tests: `test/leave_decimal_parsing_test.dart`, `test/leave_applications_test.dart`, `test/contract_fixtures_test.dart`.

---

## 5. Punch and attendance-day contract (resolves 2.4 and 2.5)

### 5.1 Facts (✔)

1. Directions are exactly `IN` and `OUT` (`_PUNCH_DIRECTIONS`). There is no break direction.
2. The server **does not enforce alternation.** `record_punch_outcome` validates employee visibility, face-required (`WEB` only), idempotency, geofence, period/last-working-day checks; it never compares with the previous punch. `IN` after `IN` is accepted.
3. Self punch time is server time; the client sends no timestamp.
4. Idempotency: same `idempotency_key` + same employee + same logical punch returns the original (replay); a key reused for another employee is refused; reuse with a different direction/source is refused (`_ensure_same_logical_punch`).
5. After a punch the server tries an immediate day calculation in a savepoint; **failure is swallowed** and the 09:30 IST sweep (today and two trailing days) repairs it. So a day row can be missing or stale right after a successful punch.
6. A day row exists only if (a) a punch triggered calculation, (b) the 09:30 IST sweep ran, or (c) HR called calculate. `GET /attendance/days` never creates one.
7. A zero-punch expected working day calculates to `INCOMPLETE` (default `missing_punch_behaviour`) or `ABSENT` (policy), and the sweep writes that row for *today* at 09:30 IST while the day is still in progress. A row with `ABSENT`/`INCOMPLETE` and `actual_first_in == null` for **today** is therefore provisional.
8. `GET /attendance/punches` is `punch_time DESC` with UTC-day filters. A company-zone "today" cannot be expressed exactly as a filter.
9. Overnight shifts: a punch may attribute to the previous `attendance_date` (FR-ATT-005), so the row for `businessToday` is not necessarily the day a night-shift employee is working.

### 5.2 Decision D-06: how the client knows the current punch state

Use **only existing reads**, no new calculation and no backend change:

```
punches = GET /attendance/punches?employee_id=<me>
          &date_from=businessDayOffset(zone,-1)&date_to=businessDayOffset(zone,+1)&per_page=20
last    = punches[0]                      // already newest-first; null if empty
```

* `last.direction == IN` → the employee is **clocked in**; the likely next action is **Punch out**.
* `last == null` or `last.direction == OUT` → likely next action is **Punch in**.
* This is shift-agnostic (works across midnight) and independent of `actual_first_in/last_out`, which the prior documents proposed and which cannot represent multiple cycles.
* **Both directions stay reachable at all times** (filled primary for the likely one, text button for the other). The server accepts either, and a stale `IN` older than 24 h (forgotten punch-out) must not trap the employee.
* If the punches request fails the screen falls back to **two equal buttons** (today's layout) and says nothing false.
* Idempotency state (`_unconfirmedPunch`) moves with the extracted punch controller (T1-03) and is per direction exactly as today.

Documented limitations: the 20-row window can in theory miss a very old open `IN` (acceptable: it degrades to "Punch in" primary, other still reachable); the list is a *recent punches* view, not a per-`attendance_date` view.

### 5.3 Today-status state table (D-07). The UI must use exactly these states

Inputs: `E` = employee record present, `P` = punches call (ok / failed), `R` = day row for `businessToday(zone)` (present / absent / failed), `last` = newest punch, `todayPunch` = a punch whose company-zone date equals today.

| # | State | Detect (all conditions) | Panel shows | Never |
|---|---|---|---|---|
| 0 | No employee record | `employeeId == null` | existing "No employee record" message | punch controls |
| 1 | Loading | requests in flight, nothing cached | skeleton | spinner replacing the punch control |
| 2 | **No attendance data** | `P` ok, no punch in window, `R` absent | "No attendance recorded yet today." primary **Punch in** | "Absent", any status chip |
| 3 | **Not punched in** | `P` ok, no `todayPunch` and no open `IN` from earlier, `R` present with `ABSENT`/`INCOMPLETE` and `actual_first_in == null` and `!is_locked` | "Not punched in yet." (row status **suppressed** for today: provisional, fact 7) | the word "Absent" for the current date |
| 4 | **Punched in** | `last.direction == IN` | "Punched in at HH:mm" (company zone; add "yesterday" if date differs) + row's worked time only if row `calculated_at` ≥ `last.punch_time` | an elapsed-time timer computed on device |
| 5 | **Punched out / day done** | `last.direction == OUT` and `R` present and `R.calculated_at ≥ last.punch_time` | row status chip, first in, last out, `worked_minutes` via `formatMinutes` | device-summed hours |
| 6 | **Being calculated** | a punch exists and (`R` absent **or** `R.calculated_at < last.punch_time`) | punch facts (state 4/5 wording) + caption "Attendance is being calculated." | a status chip from stale data |
| 7 | **Calculation failed** | `R.attendance_status == CONFIG_ERROR` | "We couldn't calculate this day. Contact HR." + raw punch facts | retry button (employee cannot recompute) |
| 8 | Not a working day | `R.attendance_status == NOT_EXPECTED` (holiday/weekly-off via `calendar_day_type`, `holiday_name`) | "Holiday: <name>" / "Weekly off"; punch still available | hiding punch |
| 9 | On leave | `R.attendance_status == LEAVE` | "On leave" chip | hiding punch |
| 10 | Data unavailable | `P` failed **and** `R` failed/absent | "Today's status is unavailable." + Try again; punch buttons **remain** (equal weight) | inventing a status |
| 11 | Partial | `P` failed, `R` present | row facts, no direction hint, equal buttons | a "clocked in" claim |

Two states were added while implementing `resolveTodayState` (T1-04), for cases the table above left open:

| # | State | Detect | Panel shows |
|---|---|---|---|
| 12 | Recorded without a punch | no punch today, row present, status not provisional (`ON_DUTY`, `WFH`, regularized `PRESENT`, or any **locked** row) | the row's status chip, first in/out and worked time |
| 13 | Not employed | `NOT_JOINED` / `EXITED` | "Not employed on this date." |

An open `IN` from an earlier date (overnight shift, forgotten punch-out) is "Punched in" labelled yesterday, with no calculation claim (today's row belongs to a different attendance date).

States 6 and 7 are the only "calculating / failed" signals the contract offers; "failed" is limited to `CONFIG_ERROR`. A calculation that failed silently and left no row is indistinguishable from a delay (state 6) and is documented as a limitation, not guessed. `NOT_JOINED`/`EXITED` render a plain "Not employed on this date" caption and no punch emphasis.

---

## 6. Home data sources (H-xx)

All requests run in parallel; none blocks another; each widget has its own loading/failure. A widget is **omitted entirely** (no placeholder) when the permission it needs is absent from `UserProfile.permissions`. All ✔ unless noted. `me` = `UserProfile.employeeId`. `zone` = `UserProfile.companyTimezone`.

| ID | Widget | 1 Endpoint | 2 Method | 3 Repo method | 4 Permission | 5 Scope | 6 Fields used | 7 Loading | 8 Failure | 9 Fit |
|---|---|---|---|---|---|---|---|---|---|---|
| H-01 | Identity line | `/employees/{me}` (+ `/auth/me` cached) | GET | `EmployeeRepository.getEmployee` (`features/profile/data/employee_repository.dart`) | `EMPLOYEE.VIEW` | SELF | first name, `employee_code` | text skeleton | fall back to "Home" title; no name shown, no error | Yes. `/auth/me` has no name |
| H-02 | Today panel | `/attendance/days` + `/attendance/punches` | GET | `listAttendanceDays` (from=to=today), `listPunches` | `ATTENDANCE.VIEW` | SELF (send `employee_id`) | §5.3 | 2-line skeleton | state 10/11 with Try again | Yes |
| H-03 | CheckInAction | `/attendance/punches/me`, `/attendance/face-punches/me[...]`, `/attendance/geofence-policy/me` | POST/GET | `punchMe`, `facePunchMe`, `startFaceLivenessSession`, `getMyGeofencePolicy` | `ATTENDANCE.PUNCH` | SELF | direction | disabled until face status known | existing snackbars/dialogs | Yes, shared controller |
| H-04 | Face status | `/attendance/face-enrollment/me` | GET | `getMyFaceEnrollment` | `ATTENDANCE.PUNCH` | SELF | `profile.status`, `open_window`, `face_verification_required` | "Loading…" caption | punch bar stays disabled until known (as Attendance today) | Yes |
| H-05 | Leave balances | `/leave-balances?employee_id=` | GET | `listLeaveBalances` | `LEAVE.BALANCE_VIEW` | SELF | `leave_type_name, balance, reserved_balance` | 3 text skeletons | strip omitted + text "Balances unavailable" with retry | Yes (contract §4) |
| H-06 | Needs attention | `/regularizations?employee_id=&request_status=SUBMITTED`, `/leave-applications?employee_id=&application_status=SUBMITTED` | GET ×2 | request list loader (`request_screens.dart`), `listLeaveApplicationsPage` | `ATTENDANCE.VIEW`; `LEAVE.BALANCE_VIEW` | SELF | id, type, dates, status | skeleton rows | section omitted | Yes ◐ param spelling of regularization status filter to be confirmed against `RequestListScreen` in T1-07 |
| H-07 | Recent leave | `/leave-applications?employee_id=&per_page=3` | GET | `listLeaveApplicationsPage` | `LEAVE.BALANCE_VIEW` | SELF | type, dates, days, status | skeleton rows | omitted | Yes |
| H-08 | Latest payslip | `/me/payslips` | GET | `PayrollRepository.listMyPayslips` | `PAYROLL.PAYSLIP_VIEW_OWN` | SELF | `month, net_minor, pay_date` (first row, assumed newest ◐: sort client-side by `month` desc) | one row skeleton | omitted | Yes |
| H-09 | Recent days (optional, ≤3) | reuse H-02 days call widened to last 4 days | GET | `listAttendanceDays` | `ATTENDANCE.VIEW` | SELF | date, status, worked | with H-02 | omitted | Yes, **no extra request** |

Not on Home: announcements, tasks, team, holidays, notifications, dashboard company calls, overtime (secondary; reachable from More). Payslip net on a shared device is sensitive: H-08 shows month and net exactly as the Payslips list already does; no new exposure.

---

## 7. Screen → dependency matrix

`Perm` is the gate for the screen's *data*; the screen is shown to a user who lacks it only as the existing error/empty state, never as a crash.

| Screen (spec ID) | Endpoints | Perm | Writes |
|---|---|---|---|
| S02 Login … S06 Accept invite | §3.1 | public | login, reset, verify, accept |
| S07 Public onboarding | §3.2 | token | PATCH/upload/submit |
| S10 Home | §6 | per widget | punch only |
| S11 Attendance | days, punches, geofence, face, `punches/me` | `ATTENDANCE.VIEW`, `.PUNCH` | punch |
| S12 Attendance day | `days/{id}`, leave-projections | `ATTENDANCE.VIEW` | HR-only recompute/keep-leave |
| S13–S14 Face | face-enrollment, liveness, face-punch | `ATTENDANCE.PUNCH` | enrollment, punch |
| S16–S19 Leave list/apply/detail/cancel | leave-applications, leave-types, balances | `LEAVE.*` | submit, cancel |
| S20 Leave balances | `/leave-balances`, `/leave-ledger` | `LEAVE.BALANCE_VIEW` | HR-only adjust/encash |
| S21–S24 Profile & records | employees, employments, assignments, tabs, documents, salary | `EMPLOYEE.VIEW[_*]` | none for employee |
| S26–S28 Corrections | regularizations (+ `/shifts` choice ✗) | `ATTENDANCE.VIEW`, `.REGULARIZATION_REQUEST` | create, cancel |
| S29–S30 Overtime | overtime | `ATTENDANCE.VIEW` | none (HR decisions) |
| S31–S32 Payslips | `/me/payslips[...]` | `PAYROLL.PAYSLIP_VIEW_OWN` | none |
| S33 More, S34 Sign out | none / `/auth/logout` | n/a | logout |

---

## 8. Future proposals (explicitly **not** dependencies)

| ID | Proposal | Why | Blocks anything? |
|---|---|---|---|
| FP-1 | Let `GET /auth/me` (or `GET /employees/{id}`) return the employee's own department, designation, branch and manager *names* | Employees cannot resolve assignment ids (§3.6); Profile "Work" can only show dates and location type | No. UI omits the rows |
| FP-2 | `GET /attendance/days/today` (or a `current_state` field) returning punch state and calculation freshness | Removes the punches-list inference and the `calculated_at` comparison | No. §5.2 works today |
| FP-3 | An employee-readable shift list or the employee's own shift name | Regularization shift correction and Home shift window | No. See F-1 |
| FP-4 | Employee-scoped upcoming holidays | A holiday strip on Home | No. Not on Home |

---

## 9. Findings recorded during verification

| ID | Finding | Evidence | Consequence |
|---|---|---|---|
| F-1 | Regularization create form loads `GET /shifts` (`ORG.SHIFT.MANAGE`) as a choice source; `loadChoices` is all-or-nothing, so an `EMPLOYEE` always sees the banner "Could not load the options for this form." and cannot use shift correction | `request_resources.dart:123` `createChoiceKeys: ['shifts']`; `choice_sources.dart:28,43`; `spec_form_screen.dart:63`; `organisation/router.py:648`; the unit test fake supplies `/shifts`, which masks it | Existing defect on the employee path. Task T3-03 fixes presentation only (lazy, per-key, tolerant of 403). Not a backend change |
| F-2 | `GET /leave-types` is available to non-managers (active types) | `leave/router.py:116-139` | Apply form works for employees |
| F-3 | Android intent filter `hrms://app` has **no path restriction**; any `/app/...` route is deep-linkable for a signed-in user; router has no permission guard for `/app/*` | `AndroidManifest.xml:35-40`, `app_router.dart` | Mitigated by API 403, but UI lands on error screens. Task T3-01 adds a client guard (UX only) |
| F-4 | `permissions.dart` lacks constants for `EMPLOYEE.VIEW`, `EMPLOYEE.VIEW_ALL`, `EMPLOYEE.VIEW_DOCUMENTS`, `LEAVE.BALANCE_VIEW`, `PAYROLL.PAYSLIP_VIEW_OWN`, `PAYROLL.RUN_VIEW`, `ATTENDANCE.OVERTIME_*` read | read of `permissions.dart` | T0-01 adds them |
| F-5 | Working tree is dirty: `settings_hub_screen.dart` already contains an uncommitted sign-out row with confirmation; `shell_tabs_test` and others pass against HEAD | `git diff` | T3-02 builds on that change; the prior claim "More confirms sign-out" is true of the working tree, not of HEAD |
| F-6 | Prior docs: `AttendanceDay.workedMinutes` "may be null" | Server field is a non-null `int` (`schemas.py:1497`); Dart model is nullable only by construction | "Worked time appears after the day is calculated" is shown for state 6, not for null |

Tests: the Flutter test suite was **not run** in this pass (running `flutter test` can rewrite `pubspec.lock`/tool caches, which the no-source-change rule forbids). Baseline run is task T0-08's first step.
