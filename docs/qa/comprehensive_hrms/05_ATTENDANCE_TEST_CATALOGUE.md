# Attendance

12 cases. Execution status is `NOT_RUN`. The machine-readable copy is `TEST_CASES.csv`.

## ATT-001 — Employee punch in and punch out on a working day

- **Module:** Attendance / Punch
- **Objective:** One in and one out produce a worked interval and a day status.
- **Source:** ATTENDANCE.PUNCH on EMPLOYEE SELF; attendance day calculation
- **Type:** UI
- **Priority:** P0
- **Risk:** High. The daily attendance record feeds payroll.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Alice has the employee attendance grants. Shift 09:00–18:00 Asia/Kolkata. No open punch. Disposable clock or a real local day that is WORKING.
- **Test data:** Punch in 09:05, punch out 18:10 local.
- **Initial database:** No punches today.
- **Steps:** 1. Sign in on the web attendance page. 2. Punch in. 3. Punch out. 4. Open the day detail as Alice and as Maya.
- **Expected results:** Two punches. Worked time 9h05m. Status present. Maya can see Alice. Bob cannot.
- **Expected UI:** In then Out, then a completed day. No second open punch.
- **Expected API:** Both posts 200.
- **Expected database:** Two punch rows for Alice, company A only. Out time after in time.
- **Expected audit:** Punch events with Alice's user.
- **Cleanup:** Leave the day; it is fixture history.
- **Automation:** API plus one UI punch.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ATT-002 — Duplicate punch in does not create a second open interval

- **Module:** Attendance / Punch
- **Objective:** Repeating punch-in is idempotent or rejected.
- **Source:** punch idempotency noted in the attendance service
- **Type:** concurrency
- **Priority:** P0
- **Risk:** High. Two open punches make the day uncalculable.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** After a successful punch in.
- **Test data:** Same punch-in body twice, including parallel.
- **Initial database:** One open punch.
- **Steps:** 1. Punch in again. 2. Count punches.
- **Expected results:** Still one open punch. No second in at the same logical action.
- **Expected UI:** Already punched in.
- **Expected API:** 200 same id or 409.
- **Expected database:** count of open punches = 1.
- **Expected audit:** One in.
- **Cleanup:** Punch out.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ATT-003 — Employee cannot punch for a colleague

- **Module:** Attendance / Punch
- **Objective:** SELF punch ignores a foreign employee id.
- **Source:** scope enforcement
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Punching for someone else forges attendance.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Bob exists.
- **Test data:** Alice token, Bob employee id.
- **Initial database:** Bob has no punch today.
- **Steps:** 1. POST a punch naming Bob.
- **Expected results:** 404 or 403. Bob has zero new punches.
- **Expected UI:** Alice's screen punches only herself.
- **Expected API:** Not 200 for Bob.
- **Expected database:** Bob punch count unchanged.
- **Expected audit:** None for Bob.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ATT-004 — Company B cannot punch company A's employee

- **Module:** Attendance / Punch
- **Objective:** Cross-tenant employee id is rejected.
- **Source:** RLS and company filter
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Cross-tenant punch is time-record fraud.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** Two tenants.
- **Test data:** B token, Alice's id, B company context.
- **Initial database:** Alice punch count known.
- **Steps:** 1. POST punch.
- **Expected results:** 404. Alice's count unchanged.
- **Expected UI:** Not found.
- **Expected API:** 404.
- **Expected database:** No punch with company B and Alice's id.
- **Expected audit:** None in A.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ATT-005 — Punch after the grace period is late

- **Module:** Attendance / Late
- **Objective:** A shift with a known grace marks 09:30 as late when grace is 10 minutes.
- **Source:** shift and attendance policy evaluation that is actually implemented; if the stored grace field is not evaluated, record BLOCKED against BR-04
- **Type:** functional
- **Priority:** P1
- **Risk:** Medium. Late flags drive deductions only if the engine reads them.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Policy grace 10 minutes. Shift start 09:00. Inspect the calculator before asserting. Gap G-A2 says some policy fields are stored and not evaluated.
- **Test data:** Punch in 09:30.
- **Initial database:** No punch.
- **Steps:** 1. Punch in at 09:30. 2. Read the day status.
- **Expected results:** If the engine evaluates grace: status late. If the field is stored but unused: BLOCKED, defect note BR-04, do not change the expected result to match silence.
- **Expected UI:** Late indicator only if the engine sets it.
- **Expected API:** Day payload includes the status the engine actually computes. Record both.
- **Expected database:** Punch time 09:30 stored. Status column matches the engine.
- **Expected audit:** Punch.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ATT-006 — Overnight shift checkout is the next local date

- **Module:** Attendance / Overnight
- **Objective:** A 22:00–06:00 shift stays one attendance day.
- **Source:** shift overnight handling in the attendance day builder
- **Type:** functional
- **Priority:** P1
- **Risk:** High. Splitting an overnight shift creates a phantom absence.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Employee assigned an overnight shift. Time zone Asia/Kolkata.
- **Test data:** In 22:00 local, out 06:00 next local morning.
- **Initial database:** No punches.
- **Steps:** 1. Punch both times. 2. Read the attendance date.
- **Expected results:** One day, worked 8h00m, attendance date is the shift start date.
- **Expected UI:** One day row.
- **Expected API:** worked minutes 480.
- **Expected database:** Out punch linked to the same day as in.
- **Expected audit:** Two punches.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ATT-007 — Missing out keeps the day incomplete

- **Module:** Attendance / Missing punch
- **Objective:** An open punch is not silently closed at midnight.
- **Source:** day status for a missing punch
- **Type:** functional
- **Priority:** P0
- **Risk:** High. Auto-close would invent hours.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Punch in only.
- **Test data:** In 09:00, no out.
- **Initial database:** One open punch.
- **Steps:** 1. Read the day after the shift end.
- **Expected results:** Status incomplete or missing punch. Worked time is not a full shift unless a rule explicitly says so. If no such rule exists, worked time stays open.
- **Expected UI:** Missing punch shown.
- **Expected API:** No fabricated out timestamp.
- **Expected database:** out time null.
- **Expected audit:** Only the in punch.
- **Cleanup:** Regularise later.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ATT-008 — Manager approves a missing punch once

- **Module:** Attendance / Regularisation
- **Objective:** Approval writes the punch a single time.
- **Source:** regularisation approve writes punches once
- **Type:** functional
- **Priority:** P0
- **Risk:** High. A second write doubles hours.
- **Role and scope:** EMPLOYEE then REPORTING_MANAGER; SELF then REPORTEE_TREE
- **Preconditions:** Alice missing out. Maya is her manager and holds REGULARIZATION_APPROVE at REPORTEE_TREE.
- **Test data:** Requested out 18:00, reason 'forgot'.
- **Initial database:** Open punch.
- **Steps:** 1. Alice submits. 2. Bob tries to approve. 3. Maya approves. 4. Maya approves again.
- **Expected results:** Bob is rejected. First Maya call writes one out punch at 18:00. Second call does not write another.
- **Expected UI:** Pending then approved.
- **Expected API:** 200 then 409.
- **Expected database:** One out punch at 18:00.
- **Expected audit:** Request and one approval.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ATT-009 — Locked period rejects a new punch

- **Module:** Attendance / Period
- **Objective:** COMPANY_ADMIN lock freezes punches for that period.
- **Source:** attendance period lock
- **Type:** functional
- **Priority:** P0
- **Risk:** High. Edits after lock change a payroll input.
- **Role and scope:** COMPANY_ADMIN and EMPLOYEE; COMPANY and SELF
- **Preconditions:** A period covering today can be locked in the disposable company. HR does not hold lock.
- **Test data:** Lock, then Alice punches, then HR tries to lock, then admin unlocks if the product allows.
- **Initial database:** Period open.
- **Steps:** 1. Admin locks. 2. Alice punches. 3. HR calls lock on another period to confirm 403 if HR lacks the grant.
- **Expected results:** Alice's punch is rejected. Period stays locked. HR lock is 403.
- **Expected UI:** Punch disabled or an error that names the lock.
- **Expected API:** 4xx for the punch, 403 for HR lock.
- **Expected database:** No new punch. Period status locked.
- **Expected audit:** Lock by admin.
- **Cleanup:** Unlock only if later cases need the period.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ATT-010 — Approved leave appears on the attendance day

- **Module:** Attendance / Leave projection
- **Objective:** Final leave approval syncs the attendance projection.
- **Source:** ATTENDANCE.LEAVE_PROJECTION_SYNC
- **Type:** integration
- **Priority:** P0
- **Risk:** High. Payroll may deduct absence that is actually leave.
- **Role and scope:** REPORTING_MANAGER; REPORTEE_TREE
- **Preconditions:** Leave case style: one future working day approved.
- **Test data:** The approved date.
- **Initial database:** Leave APPROVED.
- **Steps:** 1. Open that attendance day as Alice and as HR.
- **Expected results:** Day shows leave, not absence. Cancelling the leave before it starts removes the projection.
- **Expected UI:** Leave on the day cell.
- **Expected API:** Day status is leave.
- **Expected database:** Projection row for that date. None after cancel.
- **Expected audit:** Projection sync.
- **Cleanup:** Cancel the leave.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ATT-011 — Runtime role can still update a punch row

- **Module:** Attendance / Security
- **Objective:** Keep K-1 visible. Do not treat a successful UPDATE as a pass.
- **Source:** decision D11; live QA ATT-15 FAIL
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. The application role can mutate punches outside the service.
- **Role and scope:** database runtime role; database
- **Preconditions:** Disposable database only. Use the same check as ATT-15.
- **Test data:** One punch id.
- **Initial database:** Punch exists.
- **Steps:** 1. As the runtime DB role, UPDATE the punch time. 2. SELECT it back.
- **Expected results:** This case FAILS if the UPDATE succeeds. Expected secure behaviour is that the runtime role cannot UPDATE or DELETE punches. Current known behaviour is that it can. Record FAIL and defect K-1. Do not change the expected result to 'update allowed'.
- **Expected UI:** Not applicable.
- **Expected API:** Not applicable.
- **Expected database:** Punch time unchanged. Actual known behaviour writes the new time.
- **Expected audit:** Not produced by a raw UPDATE.
- **Cleanup:** Restore the punch time if the UPDATE was attempted, and keep the evidence.
- **Automation:** SQL in disposable DB.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** K-1

## ATT-012 — Fresh company employee role includes punch grants

- **Module:** Attendance / Grant
- **Objective:** Confirm the code grant, which contradicts older gap G-A1.
- **Source:** organisation/service.py EMPLOYEE grants; migration 20261020090000
- **Type:** functional
- **Priority:** P0
- **Risk:** High. If a tenant was not backfilled, employees cannot punch.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Company created in this disposable run, not an old tenant.
- **Test data:** role_permission for EMPLOYEE.
- **Initial database:** Just registered.
- **Steps:** 1. Query grants. 2. Punch as the employee user.
- **Expected results:** PUNCH, VIEW, and REGULARIZATION_REQUEST are present at SELF. Punch API is not 403.
- **Expected UI:** Punch control is shown.
- **Expected API:** 200.
- **Expected database:** Three permission rows.
- **Expected audit:** Punch.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

