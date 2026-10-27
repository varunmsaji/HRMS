# End-to-end journey cases

10 cases. Execution status is `NOT_RUN`. The machine-readable copy is `TEST_CASES.csv`.

## JRN-001 — Register a company and apply a policy to a new employee

- **Module:** Journey / Company setup
- **Objective:** Journey 1 from founder signup through policy applicability.
- **Source:** composition of AUTH-010, ORG-001, ORG-003, LEV-C02, EMP-001
- **Type:** UI
- **Priority:** P0
- **Risk:** High. If this journey fails, no later journey is meaningful.
- **Role and scope:** anonymous then COMPANY_ADMIN; COMPANY
- **Preconditions:** Captured email. Empty disposable database.
- **Test data:** Company QA Foundry. Branch North. Calendar Mon–Fri. Casual policy 12 days. Employee Alice.
- **Initial database:** Empty.
- **Steps:** 1. Register and verify. 2. Create branch, department, designation, calendar. 3. Publish casual policy. 4. Create Alice. 5. Resolve her calendar and leave balance.
- **Expected results:** Each saved value reloads unchanged. Alice's weekend resolves WEEKLY_OFF. Her casual balance is the opening figure the policy assigns on create, recorded before the assertion.
- **Expected UI:** Setup completes and Alice's profile shows North.
- **Expected API:** Each create 201.
- **Expected database:** All rows share one company id.
- **Expected audit:** Register, masters, policy, employee.
- **Cleanup:** This tenant becomes tenant A.
- **Automation:** UI journey.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## JRN-002 — Hire, invite, activate, sign in

- **Module:** Journey / Onboarding
- **Objective:** Journey 2 end to end.
- **Source:** ONB-001
- **Type:** UI
- **Priority:** P0
- **Risk:** High. The candidate must land in the right company.
- **Role and scope:** HR_ADMIN then candidate; COMPANY
- **Preconditions:** Tenant A. Captured mail.
- **Test data:** new.hire@qa.invalid.
- **Initial database:** No such user.
- **Steps:** 1. Create the case. 2. Open the captured link. 3. Activate. 4. Sign in and open profile and leave balance.
- **Expected results:** Profile company is A. Leave balance is the new-joiner figure. Token does not work a second time.
- **Expected UI:** Shell for the new hire.
- **Expected API:** Login 200.
- **Expected database:** Membership in A only.
- **Expected audit:** Onboarding complete and login.
- **Cleanup:** Keep the user.
- **Automation:** UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## JRN-003 — Work a normal day and review it

- **Module:** Journey / Attendance day
- **Objective:** Journey 3.
- **Source:** ATT-001
- **Type:** UI
- **Priority:** P0
- **Risk:** High. Daily use.
- **Role and scope:** EMPLOYEE then REPORTING_MANAGER; SELF then REPORTEE_TREE
- **Preconditions:** Alice and Maya. Shift assigned.
- **Test data:** 09:05 and 18:10.
- **Initial database:** No punches.
- **Steps:** 1. Alice punches in and out. 2. Maya opens team attendance. 3. Alice opens her day.
- **Expected results:** All three views show the same two times.
- **Expected UI:** Times match.
- **Expected API:** Day payload matches.
- **Expected database:** Two punches.
- **Expected audit:** Two punches.
- **Cleanup:** None.
- **Automation:** UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## JRN-004 — Correct a missing punch

- **Module:** Journey / Regularisation
- **Objective:** Journey 4.
- **Source:** ATT-008
- **Type:** UI
- **Priority:** P0
- **Risk:** High. Missing punches become loss of pay if ignored.
- **Role and scope:** EMPLOYEE then REPORTING_MANAGER; SELF then REPORTEE_TREE
- **Preconditions:** Open punch.
- **Test data:** Out 18:00.
- **Initial database:** One in punch.
- **Steps:** 1. Alice submits regularisation. 2. Maya approves. 3. Alice reloads the day.
- **Expected results:** Out 18:00 shown once.
- **Expected UI:** Approved.
- **Expected API:** One punch written.
- **Expected database:** One out.
- **Expected audit:** Approve.
- **Cleanup:** None.
- **Automation:** UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## JRN-005 — Apply, approve, see the balance and the attendance day

- **Module:** Journey / Leave
- **Objective:** Journey 5 happy path with exact arithmetic.
- **Source:** LEV-C13, LEV-C20, ATT-010, LEV-C37
- **Type:** UI
- **Priority:** P0
- **Risk:** Critical. The main leave journey.
- **Role and scope:** EMPLOYEE then REPORTING_MANAGER; SELF then REPORTEE_TREE
- **Preconditions:** Balance 10.00. Chain MANAGER. Reserve off. One future working day.
- **Test data:** That date. Reason 'clinic'.
- **Initial database:** ledger 10.
- **Steps:** 1. Alice reads balance 10. 2. Submits. 3. Balance still 10 while pending. 4. Maya approves. 5. Balance 9. 6. Attendance day shows leave.
- **Expected results:** Numbers above. Ledger -1.00 only after approval.
- **Expected UI:** Pending then Approved, balance 9.
- **Expected API:** SUBMITTED then APPROVED.
- **Expected database:** sum=9.00. Projection present.
- **Expected audit:** Submit and approve.
- **Cleanup:** Cancel before start if the batch must restore 10.
- **Automation:** UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## JRN-006 — Compute, approve by someone else, finalise, open payslip

- **Module:** Journey / Payroll
- **Objective:** Journey 6.
- **Source:** PAY-002 through PAY-007
- **Type:** UI
- **Priority:** P0
- **Risk:** Critical. This is the money journey.
- **Role and scope:** HR_ADMIN then COMPANY_ADMIN then EMPLOYEE; COMPANY then SELF
- **Preconditions:** Salary 30000. No unpaid leave. Two different users for compute and approve.
- **Test data:** June 2026 run.
- **Initial database:** No run.
- **Steps:** 1. HR computes. 2. HR attempts approve and is denied. 3. Admin approves and finalises. 4. Alice opens the payslip. 5. Bob cannot open Alice's.
- **Expected results:** Net matches the engine. Payslip exists only after finalise. Bob is 404.
- **Expected UI:** Payslip net matches the run line.
- **Expected API:** Each status transition as in the payroll cases.
- **Expected database:** One finalised run.
- **Expected audit:** Compute, approve, finalise.
- **Cleanup:** Disposable period.
- **Automation:** UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## JRN-007 — Terminate an employee and keep their history

- **Module:** Journey / Lifecycle
- **Objective:** Journey 7.
- **Source:** EMP-005
- **Type:** UI
- **Priority:** P1
- **Risk:** High. Leaver access.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** Bob has history.
- **Test data:** Termination yesterday.
- **Initial database:** Bob active.
- **Steps:** 1. Terminate. 2. Bob logs in. 3. HR opens old attendance.
- **Expected results:** Login fails. History remains.
- **Expected UI:** Denied. History visible to HR.
- **Expected API:** Login denied.
- **Expected database:** History rows present.
- **Expected audit:** Terminate.
- **Cleanup:** None.
- **Automation:** UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## JRN-008 — Upload and download a synthetic file

- **Module:** Journey / Documents
- **Objective:** Journey 8.
- **Source:** DOC-001
- **Type:** UI
- **Priority:** P1
- **Risk:** High. Document leak.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Disposable bucket.
- **Test data:** qa.txt.
- **Initial database:** None.
- **Steps:** 1. Upload. 2. Download. 3. Second employee requests it.
- **Expected results:** Bytes match. Second employee denied.
- **Expected UI:** File opens.
- **Expected API:** 404 for the second employee.
- **Expected database:** One row.
- **Expected audit:** Upload.
- **Cleanup:** Delete if allowed.
- **Automation:** UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## JRN-009 — Two companies work side by side

- **Module:** Journey / Isolation
- **Objective:** Journey 9.
- **Source:** SEC-001, SEC-002
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Tenant breach.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** Tenant A and tenant B both set up as in JRN-001.
- **Test data:** Marker names unique to each.
- **Initial database:** Both populated.
- **Steps:** 1. Create an employee in each. 2. From each admin, search the other marker through the UI and by UUID.
- **Expected results:** No marker crosses. Updates do not land.
- **Expected UI:** Each admin sees one company.
- **Expected API:** 404 on foreign ids.
- **Expected database:** No cross company_id.
- **Expected audit:** Creates stay in their company.
- **Cleanup:** Discard both databases.
- **Automation:** UI and API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## JRN-010 — Failed mail and failed upload leave consistent state

- **Module:** Journey / Recovery
- **Objective:** Journey 10.
- **Source:** ONB-004, DOC-002
- **Type:** recovery
- **Priority:** P1
- **Risk:** High. Partial writes.
- **Role and scope:** HR_ADMIN and EMPLOYEE; COMPANY and SELF
- **Preconditions:** Failing mail stub and closed storage port.
- **Test data:** One invite and one file.
- **Initial database:** Counts known.
- **Steps:** 1. Send the invite. 2. Upload the file. 3. Restore dependencies and retry each once.
- **Expected results:** Failed attempts add no user and no document. Retries add exactly one of each.
- **Expected UI:** Error then success.
- **Expected API:** Failure then 200.
- **Expected database:** Final counts increase by one.
- **Expected audit:** Failure then success.
- **Cleanup:** Restore stubs.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

