# Leave

48 cases. Execution status is `NOT_RUN`. The machine-readable copy is `TEST_CASES.csv`.

## State machine

Statuses implemented on `LeaveApplication`: `SUBMITTED`, `APPROVED`, `REJECTED`, `CANCELLED`. There is no `WITHDRAWN` status. Employee cancel of a pending request is `CANCELLED`.

Approval chains: `AUTO`, `HR`, `MANAGER`, `MANAGER_THEN_HR`, `MANAGER_THEN_HOD_THEN_HR`. A missing manager or head of department is dropped and the request falls through to HR.

| From | Action | Actor | To | Balance | Covered by |
|---|---|---|---|---|---|
| none | submit, chain AUTO | employee | APPROVED | debit total_days − lop_days | LEV-C04 |
| none | submit, chain MANAGER | employee | SUBMITTED | no debit when reserve is off | LEV-C13 |
| SUBMITTED | approve, stage remains | snapshotted manager | SUBMITTED | no debit yet | LEV-C25 |
| SUBMITTED | approve, final stage | manager or HR for that stage | APPROVED | one debit | LEV-C20, LEV-C25 |
| SUBMITTED | reject | that stage's actor | REJECTED | no debit | LEV-C26 |
| SUBMITTED | cancel | employee | CANCELLED | no credit needed if never debited | LEV-C31 |
| APPROVED | cancel before start | employee | CANCELLED | credit the debit | LEV-C32 |
| APPROVED | cancel after start | employee | unchanged | none | LEV-C33 |
| APPROVED | cancel after start with reason | holder of APPLICATION_CANCEL_APPROVED | CANCELLED | credit | LEV-C34 |
| APPROVED | reject | manager | unchanged | none | LEV-C30 |
| REJECTED or CANCELLED | approve, reject, or cancel | HR | unchanged | none | LEV-C48 |

Sandwich rule, as implemented: a non-working day is charged only when the previous and next day in the same request are both consuming. A two-day weekend between Friday and Monday is not charged. That behaviour is LEV-C05 and LEV-C06. Whether the business wanted both weekend days charged is BR-01.

Half day is 0.50 and only when start date equals end date (LEV-C07). An unresolved calendar never counts as a working day (LEV-C08). Ledger is append-only. Displayed balance must equal the sum (LEV-C37).

## LEV-C01 — HR cannot create a leave type; company admin can

- **Module:** Leave / Type
- **Objective:** Leave type management stays with COMPANY_ADMIN.
- **Source:** default grants; LEAVE.TYPE_MANAGE is not in the HR_ADMIN loop
- **Type:** security
- **Priority:** P0
- **Risk:** High. HR creating policy would bypass the company-admin control the grants encode.
- **Role and scope:** COMPANY_ADMIN and HR_ADMIN; COMPANY
- **Preconditions:** Tenant A seeded. No type code QA_CL.
- **Test data:** code QA_CL, name QA Casual, paid=true.
- **Initial database:** leave_type has no QA_CL.
- **Steps:** 1. Sign in as HR and POST a leave type. 2. Sign in as company admin and POST the same body. 3. Open the leave types page as each user.
- **Expected results:** 1. HR receives 403 and no row. 2. Admin receives 201. 3. Admin sees QA Casual. HR page either hides the action or shows the same 403 on save.
- **Expected UI:** Admin list contains QA Casual. HR has no successful create toast.
- **Expected API:** 403 then 201.
- **Expected database:** Exactly one leave_type row for QA_CL in company A. Zero rows in company B.
- **Expected audit:** Leave type created by the admin user id.
- **Cleanup:** Disable the type if later cases need a clean list; otherwise keep it.
- **Automation:** API plus one UI create.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C02 — Publish a casual policy with explicit rules

- **Module:** Leave / Policy
- **Objective:** A published version snapshots the rules applications will use.
- **Source:** LeavePolicyVersion fields; publish path in leave service
- **Type:** functional
- **Priority:** P0
- **Risk:** High. Wrong snapshot makes every balance assertion meaningless.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** QA_CL type exists.
- **Test data:** accrual NONE, annual entitlement 12.00, max_consecutive_days 5, half_day_allowed true, sandwich_rule_enabled true, reserve_balance_on_submission false, allow_negative_balance false, reason_required true, approval_chain MANAGER, year_end CARRY_FORWARD, carry cap 5.
- **Initial database:** No published version for QA_CL.
- **Steps:** 1. Create the draft with those values. 2. Publish it. 3. Read the version back.
- **Expected results:** Published version returns every value unchanged. Status is published. A second publish of the same draft is rejected.
- **Expected UI:** Policy page shows published and the numbers above.
- **Expected API:** Publish 200. Repeat publish 409.
- **Expected database:** One published leave_policy_version. Draft is not editable in place.
- **Expected audit:** Policy published.
- **Cleanup:** Keep as the casual policy for application cases.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C03 — Negative balance without a floor is rejected

- **Module:** Leave / Policy
- **Objective:** Publishing allow_negative_balance without negative_balance_floor fails closed.
- **Source:** leave service publish validation around allow_negative_balance
- **Type:** functional
- **Priority:** P1
- **Risk:** Medium. An unbounded negative balance is an unapproved loan of leave.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** A draft type QA_BAD.
- **Test data:** allow_negative_balance true, negative_balance_floor null.
- **Initial database:** Draft only.
- **Steps:** 1. Attempt to publish.
- **Expected results:** Publish is rejected. No published version.
- **Expected UI:** Validation message naming the floor.
- **Expected API:** 422.
- **Expected database:** Zero published versions for QA_BAD.
- **Expected audit:** No publish event.
- **Cleanup:** Delete the draft if the API allows; else leave it unpublished.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C04 — Three working days debit 3.00

- **Module:** Leave / Day count
- **Objective:** Tue–Thu in a Mon–Fri calendar charges 3.00 and ignores nothing inside the span.
- **Source:** _compute_day_breakdown
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. Day count is the money input to payroll.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Alice, employee of company A, branch North, calendar Mon–Fri, no holiday on 2026-06-02, 2026-06-03, 2026-06-04. Casual policy published as LEV-C02 but approval_chain AUTO for this fixture variant, opening ledger +10.00.
- **Test data:** start=2026-06-02 end=2026-06-04 half_day empty reason 'QA three day'.
- **Initial database:** balance = sum(ledger) = 10.00. No overlapping application.
- **Steps:** 1. Employee opens leave apply. 2. Submits the range. 3. Read the application, ledger, and balance.
- **Expected results:** total_days=3.00. AUTO chain approves immediately. Ledger amount -3.00. Balance 7.00.
- **Expected UI:** Status Approved. Balance 7.00 on the leave page and on the profile leave panel.
- **Expected API:** 201 with total_days '3.00' and status APPROVED.
- **Expected database:** 3 leave_application_day rows fraction 1.00. One ledger debit -3.00. No company B row.
- **Expected audit:** Submit and approve events with Alice's user id.
- **Cleanup:** Cancel before start if the employee may; else HR cancel. Balance returns to 10.00.
- **Automation:** API arithmetic plus one UI submit.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C05 — Weekend inside Mon–Fri is not charged when both weekend days sit together

- **Module:** Leave / Day count
- **Objective:** Prove the implemented sandwich: only a non-working day whose immediate neighbours are both consuming is charged.
- **Source:** _compute_day_breakdown sandwich loop; OPEN_BUSINESS_RULES BR-01
- **Type:** functional
- **Priority:** P0
- **Risk:** High. Clients often expect both weekend days to count. The code does not do that.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Calendar Sat–Sun WEEKLY_OFF. Policy sandwich on. AUTO chain. Balance 10.00.
- **Test data:** Friday 2026-06-05 through Monday 2026-06-08.
- **Initial database:** Four dates resolve to WORKING, WEEKLY_OFF, WEEKLY_OFF, WORKING.
- **Steps:** 1. Submit Fri–Mon. 2. Read day rows.
- **Expected results:** Days charged: Fri and Mon only. Sat is not sandwiched because Sunday is not consuming. Sun is not sandwiched because Saturday is not consuming. total_days=2.00. Ledger -2.00. Balance 8.00.
- **Expected UI:** Approved. Days shown as 2, not 4.
- **Expected API:** total_days 2.00.
- **Expected database:** Two day rows. No day row for 2026-06-06 or 2026-06-07.
- **Expected audit:** Approve with amount -2.00.
- **Cleanup:** Cancel and confirm balance 10.00.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C06 — A single weekly off between two working days is sandwiched

- **Module:** Leave / Day count
- **Objective:** Thu working, Fri weekly off, Sat special working charges Friday too.
- **Source:** same sandwich loop
- **Type:** functional
- **Priority:** P1
- **Risk:** High. This is the only shape the sandwich rule implements.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Fixture calendar where 2026-06-12 is WEEKLY_OFF and 2026-06-11 and 2026-06-13 are WORKING. Sandwich on. Balance 10.
- **Test data:** 2026-06-11 to 2026-06-13.
- **Initial database:** Those three day types.
- **Steps:** 1. Submit the range. 2. Read days and ledger.
- **Expected results:** total_days=3.00 including Friday with is_sandwich_generated true. Ledger -3.00. Balance 7.00.
- **Expected UI:** 3 days.
- **Expected API:** total_days 3.00.
- **Expected database:** Three day rows. Friday flagged sandwich.
- **Expected audit:** Debit -3.00.
- **Cleanup:** Cancel. Balance 10.00.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C07 — Half day on one date charges 0.50

- **Module:** Leave / Day count
- **Objective:** Half-day is accepted only when start equals end.
- **Source:** fraction 0.50 when half_day set and start==end
- **Type:** functional
- **Priority:** P0
- **Risk:** High. Half-day errors double or halve a day's pay.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** half_day_allowed true. 2026-06-02 WORKING. Balance 10. AUTO.
- **Test data:** start=end=2026-06-02 half_day=FIRST_HALF reason present.
- **Initial database:** balance 10.00.
- **Steps:** 1. Submit the half day. 2. Submit a second request for 2026-06-02 to 2026-06-03 with half_day set.
- **Expected results:** 1. total_days=0.50, ledger -0.50, balance 9.50. 2. The multi-day half-day request is rejected and does not add a second debit.
- **Expected UI:** Balance 9.50. Second form shows a validation error.
- **Expected API:** 201 then 422.
- **Expected database:** One application. Ledger sum 9.50.
- **Expected audit:** One debit -0.50.
- **Cleanup:** Cancel. Balance 10.00.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C08 — Unresolved calendar fails closed

- **Module:** Leave / Day count
- **Objective:** A date with no work calendar is not treated as a working day.
- **Source:** LeaveApplicationCalendarNotResolvedError
- **Type:** functional
- **Priority:** P0
- **Risk:** High. Assuming WORKING would debit leave the company never configured.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Employee with no calendar assignment on 2026-07-01.
- **Test data:** 2026-07-01 to 2026-07-01.
- **Initial database:** balance 10.00.
- **Steps:** 1. Submit that date.
- **Expected results:** Error. Balance stays 10.00. No application row.
- **Expected UI:** Message that the calendar is incomplete, not a generic 500.
- **Expected API:** 4xx.
- **Expected database:** ledger unchanged.
- **Expected audit:** No approve event.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C09 — Range longer than max consecutive days is rejected

- **Module:** Leave / Apply
- **Objective:** max_consecutive_days 5 blocks a 6-day span.
- **Source:** submit check requested_span > max_consecutive_days
- **Type:** functional
- **Priority:** P1
- **Risk:** Medium. The cap is a policy control, not a display hint.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Policy max 5. Six working days 2026-06-15 through 2026-06-20.
- **Test data:** That range. Balance 10.
- **Initial database:** balance 10.
- **Steps:** 1. Submit.
- **Expected results:** Rejected. Balance 10. No application.
- **Expected UI:** Limit message states 5.
- **Expected API:** 4xx naming the limit.
- **Expected database:** No new application.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C10 — Exactly the available balance is approved

- **Module:** Leave / Apply
- **Objective:** A request for the full balance succeeds and leaves 0.00.
- **Source:** balance floor 0 when allow_negative_balance is false
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. Off-by-one here zeroes the wrong balance.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Balance exactly 2.00. Two working days. AUTO. No reserve.
- **Test data:** Two working dates.
- **Initial database:** ledger sum 2.00.
- **Steps:** 1. Submit both days.
- **Expected results:** APPROVED. Ledger -2.00. Balance 0.00.
- **Expected UI:** Balance 0.
- **Expected API:** 201 APPROVED.
- **Expected database:** sum(ledger)=0.00.
- **Expected audit:** Debit -2.00.
- **Cleanup:** Cancel to restore 2.00.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C11 — One day over the balance is rejected when negative is off

- **Module:** Leave / Apply
- **Objective:** 3.00 requested against 2.00 does not create an application or a debit.
- **Source:** allow_negative_balance false
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. Silent overdraft creates unpaid-leave disputes.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Balance 2.00. Negative off. AUTO.
- **Test data:** Three working days.
- **Initial database:** ledger sum 2.00.
- **Steps:** 1. Submit three days.
- **Expected results:** Rejected. Balance stays 2.00.
- **Expected UI:** Insufficient balance.
- **Expected API:** 4xx.
- **Expected database:** No application. No ledger row.
- **Expected audit:** No debit.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C12 — Loss-of-pay covers only the shortfall on approval

- **Module:** Leave / Apply
- **Objective:** When the approval path marks uncovered days as LOP, the ledger debits total_days minus lop_days.
- **Source:** set_lop_days and debit amount -(total_days-lop_days) in leave service
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. Debiting the LOP portion double-penalises pay.
- **Role and scope:** REPORTING_MANAGER; REPORTEE_TREE
- **Preconditions:** Policy that reaches the LOP branch on approval. Balance 1.00. Request 2.00 working days. Chain MANAGER so the application exists as SUBMITTED before the decision. Confirm in this run whether submit itself allows the shortfall or only the approval shortfall path does. If submit rejects first, status of this case is BLOCKED and BR-02 records the decision.
- **Test data:** Two working days, balance 1.00.
- **Initial database:** ledger sum 1.00.
- **Steps:** 1. Submit. 2. If submit is stored, manager approves. 3. Read lop_days and ledger.
- **Expected results:** If the LOP path runs: status APPROVED, lop_days=1.00, ledger -1.00, balance 0.00. If submit rejects the shortfall: no row, and this case is BLOCKED pending BR-02 rather than forced to pass.
- **Expected UI:** Either approved with 1 LOP day or an insufficient-balance error. Record which.
- **Expected API:** Do not treat 200 as success unless lop_days and the ledger match.
- **Expected database:** Ledger debit equals paid days only.
- **Expected audit:** Comment contains loss of pay when LOP is used.
- **Cleanup:** Cancel if a row exists.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C13 — Pending request does not debit when reserve is off

- **Module:** Leave / Apply
- **Objective:** Default reserve_balance_on_submission false leaves the ledger untouched until approval.
- **Source:** submit comment and reserve flag
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. An early debit that approval also debits is a double charge.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Chain MANAGER. reserve false. Balance 10. One working day.
- **Test data:** 2026-06-16.
- **Initial database:** ledger sum 10.
- **Steps:** 1. Employee submits. 2. Read ledger before the manager acts.
- **Expected results:** Status SUBMITTED. Ledger still sums to 10.00. No debit row.
- **Expected UI:** Pending. Balance still 10, or the UI shows 10 available and 1 pending. If the UI shows 9 while the ledger is 10, file a defect for display drift.
- **Expected API:** 201 SUBMITTED.
- **Expected database:** sum(ledger)=10.00.
- **Expected audit:** Submit event, no debit.
- **Cleanup:** Employee cancels the pending request.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C14 — Reserve on submit reduces availability and approval does not debit twice

- **Module:** Leave / Apply
- **Objective:** When reserve is on, the pending request holds the days and final approval keeps a single net debit.
- **Source:** reserve_balance_on_submission branch
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. Double debit is a payroll error.
- **Role and scope:** EMPLOYEE then REPORTING_MANAGER; SELF then REPORTEE_TREE
- **Preconditions:** A second policy version with reserve true and chain MANAGER. Balance 10. One working day. Manager is the snapshotted reporting manager.
- **Test data:** 2026-06-17.
- **Initial database:** ledger sum 10.
- **Steps:** 1. Submit. 2. Read ledger and any reservation. 3. Manager approves once. 4. Read ledger again.
- **Expected results:** After approve, net leave consumed is 1.00 and balance is 9.00. A second ledger debit of 1.00 is a failure.
- **Expected UI:** Pending then Approved. Final balance 9.
- **Expected API:** Approve 200 once.
- **Expected database:** Net ledger movement -1.00.
- **Expected audit:** One consumption of 1.00.
- **Cleanup:** Cancel before start and confirm balance 10.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C15 — Overlap with a pending or approved request is blocked

- **Module:** Leave / Apply
- **Objective:** A second application on the same day is rejected while SUBMITTED or APPROVED exists.
- **Source:** overlap rule in submit
- **Type:** functional
- **Priority:** P0
- **Risk:** High. Two approved rows would debit twice.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** One APPROVED day on 2026-06-18 and, in a second fixture, one SUBMITTED day.
- **Test data:** Same date, same employee.
- **Initial database:** One open application.
- **Steps:** 1. Submit the same date again. 2. Reject or cancel the first. 3. Submit again.
- **Expected results:** 1. Rejected, no extra debit. 2. First becomes REJECTED or CANCELLED. 3. The new request is accepted.
- **Expected UI:** Overlap error, then success after the first is closed.
- **Expected API:** 4xx then 201.
- **Expected database:** Never two APPROVED rows on that date for this employee.
- **Expected audit:** One successful submit after the release.
- **Cleanup:** Cancel the survivor.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C16 — Rejected and cancelled requests do not block a new request

- **Module:** Leave / Apply
- **Objective:** Only SUBMITTED and APPROVED occupy the date.
- **Source:** overlap statuses
- **Type:** functional
- **Priority:** P1
- **Risk:** Medium. A stuck rejected row would lock the employee out of leave.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** A REJECTED application on 2026-06-19.
- **Test data:** Same date.
- **Initial database:** status REJECTED.
- **Steps:** 1. Submit 2026-06-19.
- **Expected results:** Accepted.
- **Expected UI:** New request is pending or approved.
- **Expected API:** 201.
- **Expected database:** New row plus the old REJECTED row.
- **Expected audit:** Submit.
- **Cleanup:** Cancel the new row if approved.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C17 — Reversed and empty ranges are rejected

- **Module:** Leave / Apply
- **Objective:** end before start, and a range with no consuming day, create nothing.
- **Source:** date validation and empty breakdown error
- **Type:** functional
- **Priority:** P1
- **Risk:** Medium. A negative span could credit leave.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Balance 10. A weekend-only range where sandwich cannot apply because there is no consuming neighbour.
- **Test data:** end 2026-06-02 start 2026-06-04; and Sat–Sun 2026-06-06 to 2026-06-07.
- **Initial database:** ledger 10.
- **Steps:** 1. Submit the reversed range. 2. Submit Sat–Sun.
- **Expected results:** Both fail. Balance 10. No application.
- **Expected UI:** Date error.
- **Expected API:** 422.
- **Expected database:** ledger unchanged.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C18 — Missing reason is rejected when reason_required

- **Module:** Leave / Apply
- **Objective:** The published policy's reason flag is enforced.
- **Source:** reason_required on the snapshotted version
- **Type:** functional
- **Priority:** P1
- **Risk:** Low. Applications without a reason break the audit the policy asked for.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** reason_required true.
- **Test data:** One working day, reason blank.
- **Initial database:** balance 10.
- **Steps:** 1. Submit with an empty reason.
- **Expected results:** 422. No row.
- **Expected UI:** Reason is marked required.
- **Expected API:** 422.
- **Expected database:** unchanged.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** API and UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C19 — Repeat submit of the same idempotency key does not create two rows

- **Module:** Leave / Apply
- **Objective:** A double click or retry returns the original application.
- **Source:** idempotency on submit where the router exposes a key; if no key exists, two rapid submits of the same date must still leave at most one open application because of the overlap rule
- **Type:** concurrency
- **Priority:** P0
- **Risk:** Critical. Double submit is the normal UI failure mode.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Balance 10. One working day free.
- **Test data:** Same JSON body posted twice in parallel.
- **Initial database:** No application on that date.
- **Steps:** 1. Fire two submits together. 2. Count applications and ledger debits.
- **Expected results:** One open application. Net debit 0 while pending (reserve off) or 1.00 if AUTO. Never two debits.
- **Expected UI:** One row in the list.
- **Expected API:** One 201 and one 4xx, or two 201 with the same id.
- **Expected database:** count(open applications on that date)=1.
- **Expected audit:** One submit.
- **Cleanup:** Cancel.
- **Automation:** API concurrency.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C20 — Reporting manager approves the snapshotted stage

- **Module:** Leave / Approval
- **Objective:** The manager stored on the application, not whoever currently sits above the employee, can approve a MANAGER stage.
- **Source:** approval_chain identity match on resolved_approver_manager_id
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. The wrong person must not move leave to approved.
- **Role and scope:** REPORTING_MANAGER; REPORTEE_TREE
- **Preconditions:** Alice reports to Maya. Chain MANAGER. Request SUBMITTED for 1.00 day. Balance 10. reserve off.
- **Test data:** Maya's user.
- **Initial database:** status SUBMITTED, stage MANAGER, approver Maya's employee id.
- **Steps:** 1. Maya opens the approval inbox. 2. Approves with the current version / If-Match. 3. Read ledger.
- **Expected results:** Status APPROVED. Ledger -1.00. Balance 9.00. Attendance projection written.
- **Expected UI:** Request leaves the pending list. Alice sees Approved.
- **Expected API:** 200 APPROVED.
- **Expected database:** One debit -1.00. action row by Maya's user id.
- **Expected audit:** LEAVE decision recorded with Maya.
- **Cleanup:** Cancel before start. Balance 10.
- **Automation:** API plus UI approve.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C21 — A different manager cannot approve

- **Module:** Leave / Approval
- **Objective:** Branch manager who is not the snapshotted manager is rejected even with APPLICATION_APPROVE.
- **Source:** manager stage requires caller employee id = snapshotted manager
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Scope permission alone must not approve another tree.
- **Role and scope:** BRANCH_MANAGER; BRANCH
- **Preconditions:** North branch manager is not Alice's reporting manager. Alice is in North.
- **Test data:** Pending application id.
- **Initial database:** SUBMITTED.
- **Steps:** 1. Branch manager calls approve. 2. Maya then approves.
- **Expected results:** 1. 404 as the out-of-scope pattern, or 403. Status stays SUBMITTED. Ledger unchanged. 2. Maya's approve succeeds.
- **Expected UI:** Branch manager does not see a successful toast.
- **Expected API:** Not 200 for the branch manager.
- **Expected database:** No debit until Maya approves.
- **Expected audit:** Denial not required. Success audit names Maya only.
- **Cleanup:** Cancel.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C22 — Employee cannot approve their own request

- **Module:** Leave / Approval
- **Objective:** Self-approval fails on a MANAGER chain.
- **Source:** caller employee id must equal the manager id
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Self-approval is the classic leave control failure.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Alice's own SUBMITTED request. Alice does not also hold the manager id.
- **Test data:** Alice's token and the application id.
- **Initial database:** SUBMITTED. ledger 10.
- **Steps:** 1. Alice calls the approve endpoint.
- **Expected results:** Rejected. Status SUBMITTED. Balance 10.
- **Expected UI:** No approve control on her own request, and the direct call still fails.
- **Expected API:** 403 or 404.
- **Expected database:** unchanged.
- **Expected audit:** No approve event.
- **Cleanup:** Cancel as employee.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C23 — Company B approver cannot decide company A leave

- **Module:** Leave / Approval
- **Objective:** Cross-tenant application id is invisible.
- **Source:** company_id filter and RLS
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Guessed UUID must not approve another company's leave.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** Two tenants. Application belongs to A.
- **Test data:** B admin token, A's application id, B company context.
- **Initial database:** A row exists.
- **Steps:** 1. B calls approve, reject, and cancel with A's id.
- **Expected results:** All three fail. A's status and ledger unchanged.
- **Expected UI:** Not found.
- **Expected API:** 404.
- **Expected database:** A ledger bytes identical.
- **Expected audit:** No event on A's application.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C24 — Missing manager falls through to HR

- **Module:** Leave / Approval
- **Objective:** effective_stage_sequence drops a missing manager and the HR stage can finish the request.
- **Source:** approval_chain.effective_stage_sequence
- **Type:** functional
- **Priority:** P1
- **Risk:** High. A missing manager must not strand leave forever, and must not let a random user approve it.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** Chain MANAGER. Employee has null reporting manager so the stage resolves to HR. Balance 10. One day.
- **Test data:** HR user with LEAVE.APPLICATION_APPROVE at COMPANY.
- **Initial database:** SUBMITTED at HR stage.
- **Steps:** 1. Confirm the stored stage is HR. 2. HR approves.
- **Expected results:** APPROVED. Ledger -1.00. Balance 9.00.
- **Expected UI:** HR inbox shows the request. Employee sees Approved.
- **Expected API:** 200.
- **Expected database:** approver is the HR user, debit -1.00.
- **Expected audit:** Approve by HR.
- **Cleanup:** Cancel before start.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C25 — Manager-then-HR needs both decisions and debits once

- **Module:** Leave / Approval
- **Objective:** First approval only advances the stage.
- **Source:** STAGE_APPROVED versus final APPROVED
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. Debiting at the intermediate stage and again at the end doubles the charge.
- **Role and scope:** REPORTING_MANAGER then HR_ADMIN; REPORTEE_TREE then COMPANY
- **Preconditions:** Chain MANAGER_THEN_HR. Balance 10. One working day. reserve off.
- **Test data:** Maya then HR.
- **Initial database:** SUBMITTED stage MANAGER.
- **Steps:** 1. Maya approves. 2. Read ledger and status. 3. HR approves. 4. Read ledger.
- **Expected results:** After Maya: still SUBMITTED, stage HR, ledger sum 10. After HR: APPROVED, ledger -1.00, balance 9.00.
- **Expected UI:** Two-step history visible.
- **Expected API:** 200 then 200.
- **Expected database:** One debit only, after the second call.
- **Expected audit:** STAGE_APPROVED then APPROVED.
- **Cleanup:** Cancel before start. Balance 10.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C26 — Reject with reason leaves the ledger unchanged

- **Module:** Leave / Approval
- **Objective:** Rejection from SUBMITTED does not debit.
- **Source:** reject transition
- **Type:** functional
- **Priority:** P0
- **Risk:** High. A debit on rejection takes leave the employee did not use.
- **Role and scope:** REPORTING_MANAGER; REPORTEE_TREE
- **Preconditions:** SUBMITTED, reserve off, balance 10.
- **Test data:** reason 'coverage'.
- **Initial database:** ledger 10.
- **Steps:** 1. Maya rejects with the reason.
- **Expected results:** REJECTED. Ledger 10. The date is free for a new request.
- **Expected UI:** Rejected, reason visible to Alice.
- **Expected API:** 200 REJECTED.
- **Expected database:** No debit row.
- **Expected audit:** Reject with reason and Maya's user id.
- **Cleanup:** None.
- **Automation:** API plus UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C27 — Stale If-Match does not approve

- **Module:** Leave / Approval
- **Objective:** Optimistic concurrency blocks a decision on an old version.
- **Source:** version / If-Match
- **Type:** concurrency
- **Priority:** P0
- **Risk:** Critical. A stale approve can override a cancel.
- **Role and scope:** REPORTING_MANAGER; REPORTEE_TREE
- **Preconditions:** SUBMITTED version N.
- **Test data:** If-Match N-1, then a valid N.
- **Initial database:** version N.
- **Steps:** 1. Approve with N-1. 2. Approve with N.
- **Expected results:** 1. 409. Status unchanged. 2. APPROVED and a single debit.
- **Expected UI:** Conflict message, then success on refresh.
- **Expected API:** 409 then 200.
- **Expected database:** One debit.
- **Expected audit:** One approve.
- **Cleanup:** Cancel.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C28 — Two approvers at once produce one decision

- **Module:** Leave / Approval
- **Objective:** Parallel approve calls do not double-debit.
- **Source:** version check; live QA double-approve result
- **Type:** concurrency
- **Priority:** P0
- **Risk:** Critical. Double debit is a P0 money defect.
- **Role and scope:** REPORTING_MANAGER; REPORTEE_TREE
- **Preconditions:** One SUBMITTED row. Balance 10.
- **Test data:** Two parallel approves with the same version.
- **Initial database:** version N ledger 10.
- **Steps:** 1. Send both approves. 2. Sum the ledger.
- **Expected results:** One success and one conflict. Balance 9.00. Not 8.00.
- **Expected UI:** One approved row.
- **Expected API:** One 200 and one 409.
- **Expected database:** Exactly one debit of -1.00.
- **Expected audit:** One approve.
- **Cleanup:** Cancel.
- **Automation:** API concurrency.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C29 — Approve after cancel does not debit

- **Module:** Leave / Approval
- **Objective:** A decision loses to a cancel that committed first.
- **Source:** approve requires SUBMITTED
- **Type:** concurrency
- **Priority:** P0
- **Risk:** Critical. Approving a cancelled request grants leave the employee withdrew.
- **Role and scope:** EMPLOYEE and REPORTING_MANAGER; SELF and REPORTEE_TREE
- **Preconditions:** SUBMITTED.
- **Test data:** Cancel and approve in parallel.
- **Initial database:** ledger 10.
- **Steps:** 1. Employee cancels. 2. Manager approves with the pre-cancel version.
- **Expected results:** Final status CANCELLED. Ledger 10. Approve returns conflict or not-found state.
- **Expected UI:** Cancelled.
- **Expected API:** Approve is not 200.
- **Expected database:** No debit.
- **Expected audit:** Cancel only.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C30 — Reject after approve does not credit or debit

- **Module:** Leave / Approval
- **Objective:** Terminal APPROVED is not rejectable.
- **Source:** reject only from SUBMITTED
- **Type:** functional
- **Priority:** P1
- **Risk:** High. A late reject could erase an approved debit incorrectly.
- **Role and scope:** REPORTING_MANAGER; REPORTEE_TREE
- **Preconditions:** APPROVED, ledger already -1.00, balance 9.
- **Test data:** Reject call.
- **Initial database:** APPROVED.
- **Steps:** 1. Manager rejects.
- **Expected results:** Error. Status stays APPROVED. Balance stays 9.00.
- **Expected UI:** Error.
- **Expected API:** 409.
- **Expected database:** No new ledger row.
- **Expected audit:** No reject success.
- **Cleanup:** Cancel through the cancel path if restoration is required.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C31 — Employee withdraws a pending request

- **Module:** Leave / Cancel
- **Objective:** Cancel of SUBMITTED is the product's withdrawal. There is no WITHDRAWN status.
- **Source:** cancel allows SUBMITTED or APPROVED
- **Type:** functional
- **Priority:** P0
- **Risk:** High. A stuck pending request blocks the dates.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Alice's SUBMITTED request. reserve off.
- **Test data:** Her application id.
- **Initial database:** SUBMITTED ledger 10.
- **Steps:** 1. Alice cancels from the leave list.
- **Expected results:** Status CANCELLED. Ledger 10. Date is free.
- **Expected UI:** Cancelled. Not a separate Withdrawn label unless the UI renames it.
- **Expected API:** 200 CANCELLED.
- **Expected database:** No debit and no credit.
- **Expected audit:** Cancel by Alice.
- **Cleanup:** None.
- **Automation:** UI plus API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C32 — Employee cancels approved leave before it starts and the debit reverses

- **Module:** Leave / Cancel
- **Objective:** Balance returns to the pre-approval figure.
- **Source:** cancel of APPROVED before start by the employee
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. Missing reversal steals leave.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** APPROVED future date. Ledger went from 10.00 to 9.00.
- **Test data:** start date tomorrow or later in the fixture clock.
- **Initial database:** balance 9.00.
- **Steps:** 1. Alice cancels. 2. Sum the ledger. 3. Check attendance projection.
- **Expected results:** CANCELLED. A credit +1.00. Balance 10.00. Projection removed.
- **Expected UI:** Balance 10.
- **Expected API:** 200.
- **Expected database:** sum(ledger)=10.00. Projection cancelled.
- **Expected audit:** Cancel and reversal.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C33 — Employee cannot cancel approved leave after it has started

- **Module:** Leave / Cancel
- **Objective:** After the start date only APPLICATION_CANCEL_APPROVED may cancel, and it requires a reason.
- **Source:** cancel rules in leave service
- **Type:** security
- **Priority:** P0
- **Risk:** High. Back-dating a cancel rewrites attendance and pay.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** APPROVED leave whose start date is today or earlier. Balance 9.
- **Test data:** Alice's token.
- **Initial database:** APPROVED.
- **Steps:** 1. Alice cancels.
- **Expected results:** Rejected. Status APPROVED. Balance 9.00.
- **Expected UI:** Not allowed.
- **Expected API:** 403 or 409.
- **Expected database:** No credit.
- **Expected audit:** No successful cancel.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C34 — HR cancels started leave with a reason and restores the debit

- **Module:** Leave / Cancel
- **Objective:** The authorised reversal credits total_days minus lop_days.
- **Source:** LEAVE.APPLICATION_CANCEL_APPROVED
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. Wrong credit amount corrupts the ledger.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** APPROVED started leave, debit was -1.00, balance 9.00. HR holds CANCEL_APPROVED. Company admin is not required.
- **Test data:** reason 'entered in error'.
- **Initial database:** APPROVED balance 9.
- **Steps:** 1. HR cancels without a reason. 2. HR cancels with a reason.
- **Expected results:** 1. Rejected, balance 9. 2. CANCELLED, credit +1.00, balance 10.00.
- **Expected UI:** Reason required, then cancelled.
- **Expected API:** 4xx then 200.
- **Expected database:** sum(ledger)=10.00.
- **Expected audit:** Reason stored.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C35 — Second cancel does not credit again

- **Module:** Leave / Cancel
- **Objective:** Duplicate cancel is idempotent or a conflict, never a second credit.
- **Source:** status must be SUBMITTED or APPROVED
- **Type:** concurrency
- **Priority:** P0
- **Risk:** Critical. A second credit mints leave.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** After LEV-C34 style cancel, balance 10.
- **Test data:** Same id, two cancel calls.
- **Initial database:** CANCELLED, ledger 10.
- **Steps:** 1. Cancel again.
- **Expected results:** Error. Balance stays 10.00.
- **Expected UI:** Already cancelled.
- **Expected API:** 409.
- **Expected database:** No extra credit.
- **Expected audit:** No second reversal.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C36 — Another employee cannot cancel Alice's request

- **Module:** Leave / Cancel
- **Objective:** Self-scope cancel does not accept a different employee id.
- **Source:** self scope on cancel
- **Type:** security
- **Priority:** P0
- **Risk:** High. Any employee could wipe a colleague's leave.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Bob is a second employee. Alice has SUBMITTED leave.
- **Test data:** Bob's token, Alice's application id.
- **Initial database:** SUBMITTED.
- **Steps:** 1. Bob calls cancel.
- **Expected results:** 404 or 403. Alice's row stays SUBMITTED.
- **Expected UI:** Bob's list does not show Alice's request.
- **Expected API:** Not 200.
- **Expected database:** unchanged.
- **Expected audit:** None on Alice's row.
- **Cleanup:** Alice cancels her own.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C37 — Displayed balance equals the ledger sum

- **Module:** Leave / Balance
- **Objective:** Profile, leave page, and API balance are the same number.
- **Source:** balance is the sum of the append-only ledger
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. Screens that disagree cause employees to apply against a fictional balance.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Ledger +10.00, -3.00, +1.00.
- **Test data:** Alice.
- **Initial database:** Those three rows. Expected 8.00.
- **Steps:** 1. Open profile leave panel. 2. Open leave balances. 3. GET the balance API.
- **Expected results:** All three show 8.00.
- **Expected UI:** 8.00 in both places.
- **Expected API:** 8.00.
- **Expected database:** sum(ledger)=8.00.
- **Expected audit:** Not applicable.
- **Cleanup:** None.
- **Automation:** API and UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C38 — HR adjustment in company scope writes a reasoned ledger row

- **Module:** Leave / Balance
- **Objective:** Manual adjust changes the balance by the exact amount.
- **Source:** LEAVE.BALANCE_ADJUST
- **Type:** functional
- **Priority:** P0
- **Risk:** High. Adjustments are unaudited money if the reason is optional in practice.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** HR has BALANCE_ADJUST. Alice balance 8.00.
- **Test data:** amount +1.50 reason 'opening correction'.
- **Initial database:** sum 8.00.
- **Steps:** 1. Adjust. 2. Read balance. 3. Repeat the same request if an idempotency key is supported.
- **Expected results:** Balance 9.50. A repeated key does not make 11.00. Employee role cannot call this.
- **Expected UI:** HR sees 9.50. Alice sees 9.50 and cannot open the adjust control.
- **Expected API:** 200 then 403 for Alice.
- **Expected database:** One +1.50 row with the reason.
- **Expected audit:** Adjust actor is HR.
- **Cleanup:** Adjust -1.50 with reason 'test reversal' if the suite must restore 8.00.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C39 — Manager cannot adjust a balance outside the granted action

- **Module:** Leave / Balance
- **Objective:** BALANCE_VIEW_ALL does not imply BALANCE_ADJUST.
- **Source:** HR grant includes adjust; reporting manager grant includes view all at tree scope but the adjust code is on HR
- **Type:** security
- **Priority:** P0
- **Risk:** High. Managers rewriting balances bypass HR control.
- **Role and scope:** REPORTING_MANAGER; REPORTEE_TREE
- **Preconditions:** Maya can see Alice's balance.
- **Test data:** Adjust +5.
- **Initial database:** balance 8.
- **Steps:** 1. Maya calls adjust.
- **Expected results:** 403. Balance 8.00.
- **Expected UI:** No adjust action.
- **Expected API:** 403.
- **Expected database:** unchanged.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C40 — Year-end carry keeps the cap and lapses the rest

- **Module:** Leave / Balance
- **Objective:** CARRY_FORWARD with cap 5 turns a balance of 8.00 into 5.00.
- **Source:** year-end mode on the policy version
- **Type:** functional
- **Priority:** P1
- **Risk:** High. Year-end is an irreversible bulk ledger write.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** Disposable leave year, Alice balance 8.00, cap 5, mode CARRY_FORWARD. Job runner pointed at the disposable broker.
- **Test data:** Run the year-end operation once, then run it again.
- **Initial database:** sum 8.00.
- **Steps:** 1. Run year-end. 2. Run it again.
- **Expected results:** Balance 5.00 after the first run. The second run does not move it to 2.00 or 0.
- **Expected UI:** Balance 5.
- **Expected API:** Job completes once.
- **Expected database:** Net -3.00 from the lapse of the excess, and no further row on the second run.
- **Expected audit:** Year-end actor or job id.
- **Cleanup:** Disposable year only.
- **Automation:** Worker test.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C41 — Monthly accrual does not run outside the first five days

- **Module:** Leave / Accrual
- **Objective:** Re-running the accrual outside the window does not credit a second month.
- **Source:** functional gap G-L4; accrual service window
- **Type:** functional
- **Priority:** P1
- **Risk:** High. An unrestricted rerun mints leave.
- **Role and scope:** system job; COMPANY
- **Preconditions:** A policy whose accrual frequency is monthly. Disposable clock or a date both inside and outside day 1–5.
- **Test data:** Entitlement that yields 1.00 per month.
- **Initial database:** balance 0.
- **Steps:** 1. Run accrual on a date inside the window. 2. Run it again the same day. 3. Run it on day 6.
- **Expected results:** Balance 1.00 after step 1, still 1.00 after steps 2 and 3.
- **Expected UI:** Balance 1.00.
- **Expected API:** Job result shows skipped on the repeat.
- **Expected database:** One +1.00 accrual row.
- **Expected audit:** One accrual.
- **Cleanup:** Disposable policy.
- **Automation:** Worker.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C42 — Encashment cannot reduce the balance below the configured minimum

- **Module:** Leave / Encashment
- **Objective:** Eligibility uses available balance, max days, and minimum remaining.
- **Source:** encashment_allowed and related policy fields
- **Type:** functional
- **Priority:** P1
- **Risk:** High. Encashment becomes pay. Over-encashment is a salary defect.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Policy encashment_allowed true, max 5, min balance after 2. Balance 6.00.
- **Test data:** Request 5 days, then a legal request of 4.
- **Initial database:** balance 6.
- **Steps:** 1. Request 5. 2. Request 4 and complete the approval the product requires. 3. Read balance.
- **Expected results:** 1. Rejected, balance 6. 2. Accepted. Balance 2.00. Payroll later sees one ENCASHMENT row for 4, which is BR-03 because a code comment and list_encashments_between disagree on which rows are payable.
- **Expected UI:** Error then success. Balance 2.
- **Expected API:** 4xx then success.
- **Expected database:** Net ledger -4.00 if encashment debits the balance.
- **Expected audit:** Encashment requested and decided.
- **Cleanup:** Disposable year.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C43 — Comp-off credit is consumed once and then cannot be reused

- **Module:** Leave / Comp-off
- **Objective:** A credited day pays for one leave day and a second use fails.
- **Source:** LeaveCompOffService
- **Type:** functional
- **Priority:** P1
- **Risk:** High. Double consumption grants two days for one worked day.
- **Role and scope:** HR_ADMIN then EMPLOYEE; COMPANY then SELF
- **Preconditions:** Comp-off type configured. Balance of that type 0.
- **Test data:** Credit 1.00 for a worked weekly off, then two applications for 1.00.
- **Initial database:** 0.
- **Steps:** 1. HR credits 1.00. 2. Employee applies one day and it is approved. 3. Employee applies another day.
- **Expected results:** Balance goes 0 → 1.00 → 0. The second application is rejected.
- **Expected UI:** Balance 0 after the first approval.
- **Expected API:** Second submit 4xx.
- **Expected database:** Net ledger 0. One credit and one debit.
- **Expected audit:** Credit actor is HR.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C44 — Employee API cannot read a colleague's balance

- **Module:** Leave / Reporting
- **Objective:** SELF scope returns not-found for another employee id.
- **Source:** data scope; out of scope is NotFound
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Balance disclosure reveals attendance plans.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Alice and Bob in the same company.
- **Test data:** Alice's token, Bob's employee id.
- **Initial database:** Bob balance 4.00.
- **Steps:** 1. Alice opens her leave page. 2. Alice calls the balance endpoint with Bob's id.
- **Expected results:** Her page shows only her balance. The API is 404 and the body does not contain 4.00.
- **Expected UI:** No Bob row.
- **Expected API:** 404.
- **Expected database:** No write.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** API and UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C45 — Manager sees reportee leave and not the rest of the company

- **Module:** Leave / Reporting
- **Objective:** REPORTEE_TREE includes Alice and excludes an employee in another tree.
- **Source:** data scope REPORTEE_TREE
- **Type:** security
- **Priority:** P0
- **Risk:** High. Managers reading the whole company breaks least privilege.
- **Role and scope:** REPORTING_MANAGER; REPORTEE_TREE
- **Preconditions:** Maya manages Alice. Charlie reports to someone else.
- **Test data:** Maya's token.
- **Initial database:** Both have applications.
- **Steps:** 1. Open the manager leave list. 2. Request Charlie's application by id.
- **Expected results:** Alice is visible. Charlie's id is 404.
- **Expected UI:** Alice only.
- **Expected API:** 404 for Charlie.
- **Expected database:** No write.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** API and UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C46 — An in-flight application keeps the version it snapshotted

- **Module:** Leave / Policy change
- **Objective:** Publishing a new max-days value does not rewrite a pending request.
- **Source:** policy version id stored on the application
- **Type:** functional
- **Priority:** P1
- **Risk:** High. Retroactive policy edits change balances people already submitted against.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** SUBMITTED application snapshotted at max 5, total_days 3.
- **Test data:** Publish a new version with max 1, then approve the old application.
- **Initial database:** Old version id on the row.
- **Steps:** 1. Publish the stricter version. 2. Approve the pending application.
- **Expected results:** Approval still uses the snapshotted version. total_days stays 3.00. Debit -3.00.
- **Expected UI:** The pending request still says 3 days.
- **Expected API:** 200.
- **Expected database:** application.policy_version_id unchanged. New requests see the new version.
- **Expected audit:** Approve references the old version.
- **Cleanup:** Cancel.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C47 — Probation block is enforced only when the policy says so

- **Module:** Leave / Probation
- **Objective:** An employee on probation is rejected when the version disallows probation, and allowed when it does not.
- **Source:** probation flag on the policy version; employee probation state
- **Type:** functional
- **Priority:** P1
- **Risk:** Medium. New joiners are the usual exception case.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Two versions, one blocking probation. Employee is on probation.
- **Test data:** One day against each version.
- **Initial database:** probation true. balance 10 on the allowing type.
- **Steps:** 1. Apply against the blocking type. 2. Apply against the allowing type.
- **Expected results:** 1. Rejected, no debit. 2. Accepted under that type's chain.
- **Expected UI:** Probation message, then a normal request.
- **Expected API:** 4xx then 201.
- **Expected database:** Only the second type has an application.
- **Expected audit:** One submit.
- **Cleanup:** Cancel the second.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## LEV-C48 — Illegal transitions from each terminal state

- **Module:** Leave / State
- **Objective:** REJECTED and CANCELLED accept neither approve nor a reversing credit.
- **Source:** status guards in approve, reject, cancel
- **Type:** functional
- **Priority:** P0
- **Risk:** Critical. A missing guard mints or destroys leave.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** One REJECTED and one CANCELLED application. Balances known.
- **Test data:** approve, reject, and cancel against each.
- **Initial database:** Terminal rows.
- **Steps:** 1. Call all three actions on both rows.
- **Expected results:** Every call fails. Ledger sums unchanged.
- **Expected UI:** Error.
- **Expected API:** 409.
- **Expected database:** No new ledger rows for those ids.
- **Expected audit:** No success event.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

