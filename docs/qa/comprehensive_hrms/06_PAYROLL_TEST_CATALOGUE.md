# Payroll

12 cases. Execution status is `NOT_RUN`. The machine-readable copy is `TEST_CASES.csv`.

## PAY-001 — HR assigns a salary structure and the employee cannot

- **Module:** Payroll / Structure
- **Objective:** Salary setup is an HR grant, not a self grant.
- **Source:** payroll permissions on HR_ADMIN versus EMPLOYEE
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Employees editing their own salary is fraud.
- **Role and scope:** HR_ADMIN and EMPLOYEE; COMPANY and SELF
- **Preconditions:** Component Basic 30000.00 monthly. Alice has no structure.
- **Test data:** Effective 2026-04-01, Basic 30000.00.
- **Initial database:** No salary row.
- **Steps:** 1. Alice posts a structure. 2. HR posts it. 3. Alice reads her own structure. 4. Bob reads Alice's structure.
- **Expected results:** Alice's post is 403. HR's post stores 30000.00. Alice can see her own if the view grant exists. Bob gets 404.
- **Expected UI:** HR form saves. Employee form is absent and the direct call fails.
- **Expected API:** 403, 201, 200, 404.
- **Expected database:** One structure, amount 30000.00, company A.
- **Expected audit:** Salary assigned by HR.
- **Cleanup:** Keep for the pay run.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PAY-002 — Compute a one-employee run with exact rupees

- **Module:** Payroll / Run
- **Objective:** Gross, deductions, and net match the engine for a known input.
- **Source:** payroll.engine.compute_employee
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. Rounding errors become salary payments.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** Alice Basic 30000.00. No unpaid leave. No statutory rate beyond what the disposable company configures. Record the configured PF/ESI/PT flags. If statutory is off, net equals 30000.00.
- **Test data:** Period 2026-06-01 to 2026-06-30. Legal entity of company A.
- **Initial database:** No run for that period.
- **Steps:** 1. HR creates the run. 2. HR computes it. 3. Read Alice's line.
- **Expected results:** Status COMPUTED. Alice gross 30000.00 when no other component exists. Net equals gross minus the configured statutory amounts, each rounded the way the engine rounds, and the line stores those paise. Write the expected paise into the result after reading the rate table for this fixture, before comparing.
- **Expected UI:** Run shows Computed and Alice's net.
- **Expected API:** 200 COMPUTED. error_count 0.
- **Expected database:** One employee line. computed_by is the HR user.
- **Expected audit:** PAYROLL compute.
- **Cleanup:** Leave the run for approval cases.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PAY-003 — The user who computed the run cannot approve it

- **Module:** Payroll / Approval
- **Objective:** Maker-checker blocks the same user id.
- **Source:** PayRunMakerCheckerError when actor_user_id == computed_by_user_id
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. One person could compute and release pay.
- **Role and scope:** HR_ADMIN and COMPANY_ADMIN; COMPANY
- **Preconditions:** Run COMPUTED by HR. HR does not hold RUN_APPROVE. Admin does. Admin is a different user.
- **Test data:** HR calls approve, then admin calls approve.
- **Initial database:** status COMPUTED. version N.
- **Steps:** 1. HR approves. 2. Admin approves with If-Match N.
- **Expected results:** HR 403. Admin 200. Status APPROVED. approved_by is the admin.
- **Expected UI:** HR has no successful approve. Admin sees Approved.
- **Expected API:** 403 then 200.
- **Expected database:** status APPROVED. Net unchanged from compute.
- **Expected audit:** PAYROLL_PAY_RUN_APPROVED by admin.
- **Cleanup:** Continue to finalise or discard the company.
- **Automation:** API plus UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PAY-004 — Admin who computed the run cannot approve it either

- **Module:** Payroll / Approval
- **Objective:** The maker-checker is on the user id, not the role name.
- **Source:** same guard
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. A company admin is still a single person.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** A second run computed by the admin user.
- **Test data:** Same user calls approve.
- **Initial database:** computed_by = admin.
- **Steps:** 1. Admin approves.
- **Expected results:** Rejected. Status stays COMPUTED.
- **Expected UI:** Maker-checker message.
- **Expected API:** 409 or the product's PayRunMakerChecker status.
- **Expected database:** status COMPUTED.
- **Expected audit:** No approve success.
- **Cleanup:** Have the other admin account approve, or delete the run.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PAY-005 — Finalise locks the run and the attendance period

- **Module:** Payroll / Finalise
- **Objective:** After finalise the totals cannot be recomputed in place.
- **Source:** finalise requires APPROVED; ADR-0005 immutability
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. Recomputing a finalised run changes money already declared.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** Run APPROVED by a user who did not compute it. Attendance period open.
- **Test data:** Finalise, then compute again, then edit Alice's salary and compute again.
- **Initial database:** APPROVED.
- **Steps:** 1. Admin finalises. 2. Admin computes again. 3. Employee opens payslip.
- **Expected results:** Status FINALISED. Second compute is rejected. Payslip shows the finalised net. Attendance period for that range can no longer be reopened.
- **Expected UI:** Payslip available. Compute button fails.
- **Expected API:** 200 then 409.
- **Expected database:** Totals unchanged. Payslip row exists only after finalise.
- **Expected audit:** Finalise event.
- **Cleanup:** Disposable period.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PAY-006 — Employee sees only their own payslip

- **Module:** Payroll / Payslip
- **Objective:** SELF payslip view does not return a colleague's slip.
- **Source:** PAYROLL.PAYSLIP_VIEW_OWN
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Salary disclosure.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Finalised run with Alice and Bob.
- **Test data:** Alice requests Bob's payslip id.
- **Initial database:** Both slips exist.
- **Steps:** 1. Alice opens her payslip. 2. Alice requests Bob's id.
- **Expected results:** Her net matches the line. Bob's id is 404 and the body has no salary figures.
- **Expected UI:** Own slip only.
- **Expected API:** 404.
- **Expected database:** No write.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** API and UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PAY-007 — Payslip is unavailable before finalise

- **Module:** Payroll / Payslip
- **Objective:** COMPUTED and APPROVED runs do not publish slips.
- **Source:** payslips only from finalised runs
- **Type:** functional
- **Priority:** P0
- **Risk:** High. A draft slip can be mistaken for pay.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Run COMPUTED.
- **Test data:** Alice.
- **Initial database:** No finalised slip.
- **Steps:** 1. Alice opens my payslips.
- **Expected results:** Empty, or the draft run is absent. No net is shown as paid.
- **Expected UI:** Empty state.
- **Expected API:** Empty list.
- **Expected database:** No payslip row.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PAY-008 — Mark paid is company admin and does not call a bank

- **Module:** Payroll / Paid
- **Objective:** Payment marking is a status change with no external transfer.
- **Source:** mark_paid; no payment gateway
- **Type:** functional
- **Priority:** P1
- **Risk:** High. A real payment instruction would leave the sandbox.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** FINALISED run. No bank integration configured.
- **Test data:** Mark paid.
- **Initial database:** FINALISED.
- **Steps:** 1. Confirm outbound network is limited. 2. Mark paid. 3. Mark paid again.
- **Expected results:** Status PAID. No external HTTP. Second call is a conflict or an idempotent no-op, not a second payment record that doubles the amount.
- **Expected UI:** Paid.
- **Expected API:** 200 then 409 or 200 with the same paid timestamp.
- **Expected database:** One paid transition.
- **Expected audit:** Mark paid by admin.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PAY-009 — Unpaid leave reduces pay for that month

- **Module:** Payroll / Unpaid leave
- **Objective:** Approved unpaid leave changes the computed net.
- **Source:** payroll inputs from attendance and leave; exact formula is the engine's
- **Type:** integration
- **Priority:** P0
- **Risk:** Critical. Unpaid leave that does not affect pay overpays.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** Basic 30000.00. June 2026 has 22 working days in the fixture calendar, or use the engine's day divisor and record it before the run. One approved unpaid day.
- **Test data:** Compare a control run with zero unpaid days to a run with one unpaid day. They must be separate disposable periods or the second run is a fresh compute before approval.
- **Initial database:** Control net known from PAY-002.
- **Steps:** 1. Approve one unpaid day inside the period. 2. Compute. 3. Subtract nets.
- **Expected results:** Net is lower by Basic divided by the engine's working-day divisor for one day, rounded as the engine rounds. Record the divisor from the code path before asserting the paise.
- **Expected UI:** Line shows the unpaid day.
- **Expected API:** COMPUTED.
- **Expected database:** Deduction or reduced gross equals that one day.
- **Expected audit:** Compute.
- **Cleanup:** Do not finalise unless the batch says so.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PAY-010 — Two computes do not create two lines

- **Module:** Payroll / Concurrency
- **Objective:** Parallel compute on one run is single-flight.
- **Source:** run version and status guard
- **Type:** concurrency
- **Priority:** P1
- **Risk:** High. Duplicate lines would double pay.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** Draft run.
- **Test data:** Two compute calls.
- **Initial database:** One run.
- **Steps:** 1. Fire both. 2. Count employee lines.
- **Expected results:** One line per employee. Status COMPUTED. Net not doubled.
- **Expected UI:** One run.
- **Expected API:** One 200 and one conflict, or two 200 with the same totals.
- **Expected database:** line count = employee count.
- **Expected audit:** One effective compute.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PAY-011 — Bank advice is company admin and shows full account numbers only there

- **Module:** Payroll / Bank advice
- **Objective:** HR and employees do not download the advice file.
- **Source:** bank advice grant on COMPANY_ADMIN
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Account numbers are payment credentials.
- **Role and scope:** COMPANY_ADMIN, HR_ADMIN, EMPLOYEE; COMPANY and SELF
- **Preconditions:** Alice has a synthetic account number '999000111222' in the disposable profile.
- **Test data:** Download advice.
- **Initial database:** Finalised or the status the advice endpoint requires.
- **Steps:** 1. Employee downloads. 2. HR downloads. 3. Admin downloads.
- **Expected results:** Employee and HR are 403 and the body does not contain 999000111222. Admin's file contains it.
- **Expected UI:** No download for employee and HR.
- **Expected API:** 403, 403, 200.
- **Expected database:** No write.
- **Expected audit:** Advice generated by admin.
- **Cleanup:** Delete the downloaded file from the evidence folder after redaction review.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PAY-012 — Open variance blocks approval

- **Module:** Payroll / Blocked
- **Objective:** variance_open_count greater than zero returns PayRunBlockedError.
- **Source:** approve() reasons VARIANCE_UNACKNOWLEDGED
- **Type:** functional
- **Priority:** P1
- **Risk:** High. Approving past a variance pays an unexplained delta.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** A computed run whose variance_open_count is 1.
- **Test data:** Approve.
- **Initial database:** COMPUTED, variance_open_count 1.
- **Steps:** 1. Approve.
- **Expected results:** Blocked. Status stays COMPUTED. Body names VARIANCE_UNACKNOWLEDGED.
- **Expected UI:** The reason is visible.
- **Expected API:** 409 or the product's blocked status.
- **Expected database:** status COMPUTED.
- **Expected audit:** No approve.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

