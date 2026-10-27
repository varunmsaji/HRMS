# Employee and onboarding

12 cases. Execution status is `NOT_RUN`. The machine-readable copy is `TEST_CASES.csv`.

## EMP-001 — HR creates an employee with a unique email

- **Module:** Employee / Create
- **Objective:** The employee row, code, and org links persist.
- **Source:** employee service create
- **Type:** UI
- **Priority:** P0
- **Risk:** High. The master record feeds every other module.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** Branch North, department Engineering, designation Engineer exist.
- **Test data:** name QA Alice, email alice@qa.invalid, join 2026-04-01, branch North.
- **Initial database:** No employee with that email.
- **Steps:** 1. Open the employee create form. 2. Save. 3. Reopen the profile.
- **Expected results:** Profile shows the same name, email, date, branch, and department.
- **Expected UI:** Profile matches the form.
- **Expected API:** 201.
- **Expected database:** One employee in company A. Email stored once.
- **Expected audit:** Employee created.
- **Cleanup:** Keep Alice.
- **Automation:** UI and API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## EMP-002 — Duplicate email is rejected case-insensitively

- **Module:** Employee / Create
- **Objective:** Alice@qa.invalid and alice@qa.invalid cannot both exist.
- **Source:** employee email uniqueness; confirm whether the constraint is case-insensitive in this schema
- **Type:** functional
- **Priority:** P0
- **Risk:** High. Two people, one mailbox, breaks invitations.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** alice@qa.invalid exists.
- **Test data:** ALICE@qa.invalid.
- **Initial database:** One row.
- **Steps:** 1. Create the second email.
- **Expected results:** Rejected if the product treats email as case-insensitive. If the database accepts it, this case FAILS and BR-05 is opened. Do not weaken the expected result during the run.
- **Expected UI:** Duplicate email.
- **Expected API:** 409.
- **Expected database:** Still one employee whose email matches alice case-insensitively.
- **Expected audit:** No second create.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## EMP-003 — Two identical creates without an idempotency key

- **Module:** Employee / Create
- **Objective:** Discover whether a double submit creates two employees.
- **Source:** employee create idempotency is optional
- **Type:** concurrency
- **Priority:** P1
- **Risk:** High. Duplicate masters split leave and payroll.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** Fresh email twin@qa.invalid.
- **Test data:** Two parallel posts, same body, no idempotency key.
- **Initial database:** Zero rows.
- **Steps:** 1. Send both. 2. Count rows.
- **Expected results:** Secure expected result is one row. If two rows exist, mark FAIL and file a defect. Do not reclassify it as pass.
- **Expected UI:** One profile.
- **Expected API:** One 201.
- **Expected database:** count=1.
- **Expected audit:** One create.
- **Cleanup:** If two exist, record both ids and do not delete evidence.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## EMP-004 — Branch manager sees only their branch

- **Module:** Employee / Scope
- **Objective:** BRANCH scope hides South employees from the North manager.
- **Source:** data scope BRANCH
- **Type:** security
- **Priority:** P0
- **Risk:** High. Cross-branch HR data.
- **Role and scope:** BRANCH_MANAGER; BRANCH
- **Preconditions:** North manager, Alice in North, Dana in South.
- **Test data:** List and Dana's id.
- **Initial database:** Both active.
- **Steps:** 1. Open the employee list. 2. GET Dana.
- **Expected results:** Alice listed. Dana 404.
- **Expected UI:** North names only.
- **Expected API:** 404.
- **Expected database:** No write.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** API and UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## EMP-005 — Termination revokes sign-in and keeps history

- **Module:** Employee / Lifecycle
- **Objective:** Terminated employee cannot authenticate. Past leave and attendance rows remain.
- **Source:** employee terminate; G-E1 says status flags ON_NOTICE and EXITED may be unused
- **Type:** functional
- **Priority:** P0
- **Risk:** High. A terminated user who can still punch is a control failure.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** Bob has an approved past leave day and a user account.
- **Test data:** Termination date yesterday.
- **Initial database:** Bob active.
- **Steps:** 1. HR terminates Bob. 2. Bob signs in. 3. HR opens Bob's past leave.
- **Expected results:** Sign-in fails. Past leave still reads 1.00 day. Record the actual status column. If it is not a terminated state, file a defect against G-E1 and still require sign-in to fail.
- **Expected UI:** Bob cannot reach the shell. HR still sees history.
- **Expected API:** Login denied.
- **Expected database:** Historical leave row still present.
- **Expected audit:** Termination.
- **Cleanup:** Do not reuse Bob as an active user.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## EMP-006 — Rehire creates a new employment span without editing the old one

- **Module:** Employee / Lifecycle
- **Objective:** Historical salary and leave stay on the closed span.
- **Source:** rehire behaviour; if rehire is not a distinct operation, mark BLOCKED and cite the missing API
- **Type:** functional
- **Priority:** P1
- **Risk:** High. Rewriting history changes past payroll.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** A terminated employee.
- **Test data:** New join date after termination.
- **Initial database:** Old salary 30000.
- **Steps:** 1. Rehire with salary 32000. 2. Read the old span.
- **Expected results:** Old salary still 30000 for the old dates. New span is 32000. If no rehire API exists, BLOCKED, not a pass.
- **Expected UI:** Two spans or a clear unsupported state.
- **Expected API:** 201 or 404 if missing.
- **Expected database:** Old row unchanged.
- **Expected audit:** Rehire if it exists.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## EMP-007 — Pending leave keeps the snapshotted approver

- **Module:** Employee / Manager change
- **Objective:** Changing the reporting manager does not move an in-flight request.
- **Source:** approver id snapshotted on the application
- **Type:** integration
- **Priority:** P1
- **Risk:** High. The new manager could approve a request they were not responsible for, or the old one could lose it.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** SUBMITTED leave snapshotted to Maya. HR changes Alice's manager to Neil.
- **Test data:** Maya and Neil both call approve.
- **Initial database:** approver Maya.
- **Steps:** 1. Change manager. 2. Neil approves. 3. Maya approves.
- **Expected results:** Neil is rejected. Maya still approves. Debit once.
- **Expected UI:** Maya still has the request.
- **Expected API:** Neil not 200. Maya 200.
- **Expected database:** One debit.
- **Expected audit:** Approve by Maya.
- **Cleanup:** Cancel.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ONB-001 — HR opens a case and the public token completes activation

- **Module:** Onboarding / Case
- **Objective:** The candidate sets a password through the captured mail and becomes an employee user.
- **Source:** onboarding public token wizard; captured email sender
- **Type:** UI
- **Priority:** P0
- **Risk:** High. This is how new staff enter the system.
- **Role and scope:** HR_ADMIN then candidate; COMPANY then public token
- **Preconditions:** Captured mail only. Email new.hire@qa.invalid unused.
- **Test data:** Case for New Hire, token link from the capture file.
- **Initial database:** No user for that email.
- **Steps:** 1. HR creates the case. 2. Read the captured message. 3. Open the token on localhost. 4. Complete the wizard. 5. Sign in.
- **Expected results:** One message. Token works once. User can sign in. Profile contains the fields the wizard actually persists. Grade, manager, shift, and salary are blank if the service does not copy them.
- **Expected UI:** Wizard then shell.
- **Expected API:** Token 200 then consumed.
- **Expected database:** One user, one employee, company A.
- **Expected audit:** Case completed.
- **Cleanup:** Keep the user or disable them.
- **Automation:** API plus UI wizard.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ONB-002 — Expired and reused tokens fail

- **Module:** Onboarding / Token
- **Objective:** A token cannot activate two accounts.
- **Source:** token single use and expiry
- **Type:** security
- **Priority:** P0
- **Risk:** High. Shared links would create or overwrite accounts.
- **Role and scope:** anonymous; public
- **Preconditions:** One expired token and one already used token in the disposable DB.
- **Test data:** Both tokens.
- **Initial database:** expired; consumed.
- **Steps:** 1. Submit each token.
- **Expected results:** Both fail. No new user.
- **Expected UI:** Invalid link.
- **Expected API:** 400.
- **Expected database:** User count unchanged.
- **Expected audit:** Rejected token.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ONB-003 — Two browsers racing one token create one user

- **Module:** Onboarding / Token
- **Objective:** Parallel activation is single winner.
- **Source:** token consume transaction
- **Type:** concurrency
- **Priority:** P0
- **Risk:** High. Two users for one hire split the identity.
- **Role and scope:** anonymous; public
- **Preconditions:** Fresh token.
- **Test data:** Two parallel completions.
- **Initial database:** Token unused.
- **Steps:** 1. Submit both. 2. Count users for that email.
- **Expected results:** One user. One success and one failure.
- **Expected UI:** One account works.
- **Expected API:** One 200.
- **Expected database:** count=1.
- **Expected audit:** One completion.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ONB-004 — Mail failure does not mark the invitation sent

- **Module:** Onboarding / Mail
- **Objective:** When the capture sender is forced to fail, the case stays retryable and no real SMTP is contacted.
- **Source:** email sender failure classification
- **Type:** recovery
- **Priority:** P1
- **Risk:** High. A false 'sent' leaves the candidate with no link.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** Sender stubbed to fail. Egress blocked.
- **Test data:** One case.
- **Initial database:** Not sent.
- **Steps:** 1. Trigger send. 2. Read case status and capture log.
- **Expected results:** Status is failed or unsent. Zero captured successes. Retry can send once the stub succeeds.
- **Expected UI:** Error, not a success toast.
- **Expected API:** 5xx or a domain error.
- **Expected database:** No consumed token.
- **Expected audit:** Send failed.
- **Cleanup:** Restore the stub.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ONB-005 — ONBOARDING.CANCEL is unused

- **Module:** Onboarding / Cancel
- **Objective:** Record whether a cancel control exists. Do not invent a workflow.
- **Source:** gap G-ON1
- **Type:** functional
- **Priority:** P2
- **Risk:** Low. An unreachable cancel leaves bad cases open.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** An open case.
- **Test data:** Search the web UI and the API for cancel.
- **Initial database:** Case open.
- **Steps:** 1. Look for a cancel action in the UI. 2. Call the cancel route if one is mounted.
- **Expected results:** If no route is mounted, status BLOCKED with G-ON1, case unchanged. If a route exists, cancelling sets a cancelled state and the public token stops working.
- **Expected UI:** Document what is on the page.
- **Expected API:** 404 if unmounted.
- **Expected database:** Unchanged when unmounted.
- **Expected audit:** None when unmounted.
- **Cleanup:** None.
- **Automation:** API inspection.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** G-ON1

