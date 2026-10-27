# Security and tenant isolation

16 cases. Execution status is `NOT_RUN`. The machine-readable copy is `TEST_CASES.csv`.

## AUTH-001 — Valid company user signs in

- **Module:** Identity / Login
- **Objective:** A registered user reaches the company shell with a session bound to one company.
- **Source:** identity auth router; apps/web login page
- **Type:** UI
- **Priority:** P0
- **Risk:** Critical. Broken login blocks every journey.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Tenant A exists. User auth.emp.a@qa.invalid is active, email verified, password set in the disposable seed.
- **Test data:** Email auth.emp.a@qa.invalid, password from the seed secret file, company A.
- **Initial database:** users.status=ACTIVE, one company membership.
- **Steps:** 1. Open /login. 2. Enter the email and password. 3. Submit. 4. Open /app.
- **Expected results:** 1. Login form is shown. 2. Fields accept input. 3. Session cookie is set. 4. Shell shows the employee name and company A.
- **Expected UI:** No error banner. Employee navigation is visible.
- **Expected API:** POST login returns 200 and does not include the password hash.
- **Expected database:** A session or refresh row exists for this user. No second company membership is created.
- **Expected audit:** Login success event if the identity module writes one; otherwise record NOT_APPLICABLE with the code path.
- **Cleanup:** Sign out.
- **Automation:** API plus one browser login.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## AUTH-002 — Wrong password is rejected without enumeration

- **Module:** Identity / Login
- **Objective:** A bad password does not reveal whether the email exists.
- **Source:** 2026-10-25 AUTH checks; identity login
- **Type:** security
- **Priority:** P0
- **Risk:** High. Account enumeration aids credential stuffing.
- **Role and scope:** anonymous; none
- **Preconditions:** Known user and an unknown email.
- **Test data:** Known email with password 'wrong-password'; unknown email nobody@qa.invalid with the same password.
- **Initial database:** Known user exists. Unknown email has no row.
- **Steps:** 1. Submit the known email with the wrong password. 2. Submit the unknown email. 3. Compare status, body shape, and timing bucket.
- **Expected results:** Both responses are the same generic failure. Neither body contains a user id.
- **Expected UI:** Same error message on both attempts.
- **Expected API:** 401 for both. Body does not say 'user not found'.
- **Expected database:** Failed-attempt counter increments only for the known user if the product stores one. Unknown email creates no user.
- **Expected audit:** Failure recorded for the known account only.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## AUTH-003 — Repeated failures hit the rate limit

- **Module:** Identity / Lockout
- **Objective:** The lockout already observed in live QA still returns 429 and then recovers.
- **Source:** register AUTH lockout 429
- **Type:** security
- **Priority:** P1
- **Risk:** Medium. Missing lockout enables online guessing.
- **Role and scope:** anonymous; none
- **Preconditions:** A disposable user whose lockout counter can be reset.
- **Test data:** Correct email, wrong password, attempt count from the identity setting.
- **Initial database:** failed_attempts=0.
- **Steps:** 1. Submit wrong passwords until the limit. 2. Submit the correct password while locked. 3. Wait out or reset only this disposable user and sign in.
- **Expected results:** 1. Responses become 429. 2. Correct password is still rejected while locked. 3. After the window, correct password returns 200.
- **Expected UI:** Lockout message, not a stack trace.
- **Expected API:** 429 then 200.
- **Expected database:** Counter returns to a state that allows login. No other user is locked.
- **Expected audit:** Lockout event for this user only.
- **Cleanup:** Reset the disposable user.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## AUTH-004 — Anonymous request to a company API is rejected

- **Module:** Identity / Session
- **Objective:** Company routes require a session.
- **Source:** auth dependency on company routers
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Missing auth exposes employee data.
- **Role and scope:** anonymous; none
- **Preconditions:** No cookie.
- **Test data:** GET /api employee list for company A.
- **Initial database:** Employees exist in company A.
- **Steps:** 1. Call the employee list with no cookie and no company header.
- **Expected results:** 401. Body has no employee names.
- **Expected UI:** Web redirects to login.
- **Expected API:** 401.
- **Expected database:** No reads are required to be proven beyond an empty response body.
- **Expected audit:** Not required.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## AUTH-005 — Disabled user cannot sign in

- **Module:** Identity / Session
- **Objective:** A disabled membership loses access immediately.
- **Source:** identity user status
- **Type:** security
- **Priority:** P0
- **Risk:** High. Disabled staff must not keep punching or reading payroll.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** User is active, then an admin disables them.
- **Test data:** auth.disabled@qa.invalid.
- **Initial database:** status=ACTIVE.
- **Steps:** 1. Sign in as the user. 2. Admin sets the user disabled. 3. Repeat a company API call with the old session. 4. Attempt a new login.
- **Expected results:** 1. Login works. 2. Disable succeeds. 3. Old session is rejected. 4. New login is rejected.
- **Expected UI:** Session ends on the next navigation.
- **Expected API:** 401 or 403 on the old session and on the new login.
- **Expected database:** User status is disabled. Employee row is unchanged.
- **Expected audit:** User disabled event.
- **Cleanup:** Leave the user disabled.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## AUTH-006 — Password reset uses the test sender only

- **Module:** Identity / Password
- **Objective:** Reset creates a token and a captured message, and does not call a real SMTP host.
- **Source:** onboarding email sender sandbox; forgot-password route
- **Type:** integration
- **Priority:** P1
- **Risk:** High. A real send would leave the disposable environment.
- **Role and scope:** anonymous; none
- **Preconditions:** Email backend is the logging or capture sender. Network egress to SMTP is disabled.
- **Test data:** auth.emp.a@qa.invalid.
- **Initial database:** No unused reset token.
- **Steps:** 1. Submit forgot-password. 2. Read the captured message. 3. Open the reset link on localhost. 4. Set a new password and sign in.
- **Expected results:** 1. Generic success even if the email exists. 2. Exactly one captured message. 3. Form loads. 4. New password works and the old one fails.
- **Expected UI:** Generic confirmation, then reset form, then shell.
- **Expected API:** Token is single use.
- **Expected database:** One reset token, consumed after use. Password hash changed.
- **Expected audit:** Reset requested and completed.
- **Cleanup:** Restore the seed password for later cases.
- **Automation:** API with mailbox capture.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## AUTH-007 — Expired reset token is rejected

- **Module:** Identity / Password
- **Objective:** An old token cannot set a password.
- **Source:** reset token expiry
- **Type:** security
- **Priority:** P1
- **Risk:** High. Long-lived tokens are account takeover.
- **Role and scope:** anonymous; none
- **Preconditions:** A token whose expiry is in the past.
- **Test data:** Token row edited only in the disposable database.
- **Initial database:** expires_at < now.
- **Steps:** 1. POST the expired token with a new password.
- **Expected results:** Rejection. Password hash unchanged.
- **Expected UI:** Expired-link message.
- **Expected API:** 400.
- **Expected database:** password hash identical before and after.
- **Expected audit:** Rejected reset.
- **Cleanup:** Delete the token.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## AUTH-008 — Missing company context is rejected

- **Module:** Identity / Tenant context
- **Objective:** A session without a selected company cannot read company data.
- **Source:** company context dependency
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. A missing tenant filter is a cross-tenant leak.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** User belongs to company A only.
- **Test data:** Call employee list omitting the company header or cookie the API requires.
- **Initial database:** Company A and company B both have employees.
- **Steps:** 1. Authenticate. 2. Call the list without company context.
- **Expected results:** 400 or 401. Body contains neither company's employees.
- **Expected UI:** Company picker or error, not a mixed list.
- **Expected API:** No 200 with rows.
- **Expected database:** No write.
- **Expected audit:** Not required.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## AUTH-009 — User cannot select a company they do not belong to

- **Module:** Identity / Tenant context
- **Objective:** Company B's id is not a valid context for a company A user.
- **Source:** membership check
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Header spoofing must not switch tenant.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** Two tenants in the seed.
- **Test data:** Company A admin sends company B id.
- **Initial database:** Membership only for A.
- **Steps:** 1. Sign in as A. 2. Request company B employees with B's id.
- **Expected results:** 403 or 404. Zero company B rows.
- **Expected UI:** Access error.
- **Expected API:** No employee payload from B.
- **Expected database:** No write in B.
- **Expected audit:** Denied access if logged.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## AUTH-010 — New company registration creates five roles

- **Module:** Identity / Register
- **Objective:** The supported signup path creates the tenant and the five default roles with the grants in organisation/service.py.
- **Source:** OrganisationService.register_company
- **Type:** functional
- **Priority:** P0
- **Risk:** High. Wrong default grants ship every later permission bug.
- **Role and scope:** anonymous; none
- **Preconditions:** Email qa.founder@qa.invalid is unused. Captured email sender.
- **Test data:** Company name QA Foundry, founder name, password.
- **Initial database:** No company with that name.
- **Steps:** 1. Open /register. 2. Submit the form. 3. Verify email through the captured link. 4. Sign in. 5. Read roles and role_permission.
- **Expected results:** Company, founder user, and roles COMPANY_ADMIN, HR_ADMIN, REPORTING_MANAGER, BRANCH_MANAGER, EMPLOYEE exist. Founder holds COMPANY_ADMIN.
- **Expected UI:** Setup or company home after verification.
- **Expected API:** 201 then verified login.
- **Expected database:** EMPLOYEE role includes ATTENDANCE.PUNCH, ATTENDANCE.VIEW, ATTENDANCE.REGULARIZATION_REQUEST, LEAVE.APPLICATION_SUBMIT, LEAVE.BALANCE_VIEW, PAYROLL.PAYSLIP_VIEW_OWN at SELF. HR_ADMIN has no PAYROLL.RUN_APPROVE. COMPANY_ADMIN has leave type manage and payroll approve.
- **Expected audit:** Company registered.
- **Cleanup:** This company can be tenant A for the rest of the batch if the seed is not preloaded.
- **Automation:** API assertion on role_permission.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## SEC-001 — List endpoints never mix two companies

- **Module:** Security / Tenant
- **Objective:** Every list the seed can call returns only the caller's company.
- **Source:** RLS
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. A mixed list is a full data breach.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** Both tenants populated.
- **Test data:** Employees, leave, attendance, payroll, documents.
- **Initial database:** Known names in each tenant.
- **Steps:** 1. As A, list each resource. 2. Search the JSON for B's unique marker string.
- **Expected results:** Marker is absent in every body.
- **Expected UI:** Company switcher does not offer B.
- **Expected API:** 200 with only A.
- **Expected database:** No write.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## SEC-002 — Guessed ids across modules return 404

- **Module:** Security / Tenant
- **Objective:** B cannot read or mutate A's employee, leave, punch, pay run, or document by UUID.
- **Source:** company filter
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. UUID guessing is the direct bypass of the UI.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** Ids captured from A.
- **Test data:** GET and a harmless field update on each id, using B's context.
- **Initial database:** Snapshot of A's rows.
- **Steps:** 1. GET each. 2. PATCH each with a harmless name change. 3. Re-read as A.
- **Expected results:** All B calls 404. A's values unchanged.
- **Expected UI:** Not found.
- **Expected API:** 404.
- **Expected database:** Row hashes unchanged.
- **Expected audit:** No update on A.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## SEC-003 — Hidden nav is not the control

- **Module:** Security / Nav
- **Objective:** A page the employee menu hides still enforces the API.
- **Source:** gap G-W1 web nav is not permission filtered
- **Type:** security
- **Priority:** P0
- **Risk:** High. A visible link that 403s is acceptable. A hidden link that 200s is not.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Employee user.
- **Test data:** Direct URL to pay-run admin, leave type create, and user admin.
- **Initial database:** Those resources exist.
- **Steps:** 1. Open each URL. 2. Submit a create.
- **Expected results:** Page may render shell chrome. Create and list of other people's data are 403 or 404.
- **Expected UI:** Error state, not an editable admin table.
- **Expected API:** 403.
- **Expected database:** No new admin rows.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** UI and API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** G-W1

## SEC-004 — Employee cannot set their own salary through the profile update

- **Module:** Security / Mass assignment
- **Objective:** Extra JSON fields are ignored.
- **Source:** employee update schema
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. Mass assignment is a direct pay change.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Alice salary 30000.
- **Test data:** Profile PATCH including salary 999999 and role COMPANY_ADMIN.
- **Initial database:** salary 30000, role EMPLOYEE.
- **Steps:** 1. Send the PATCH.
- **Expected results:** Either 422 or 200 with salary still 30000 and role still EMPLOYEE.
- **Expected UI:** Profile does not show 999999.
- **Expected API:** No privilege change.
- **Expected database:** salary 30000. role unchanged.
- **Expected audit:** Only an allowed profile change, if any field was actually allowed.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## SEC-005 — A worker processes only the company on the job payload

- **Module:** Security / Jobs
- **Objective:** A leave accrual or payroll job for A does not write B.
- **Source:** task company id
- **Type:** security
- **Priority:** P0
- **Risk:** Critical. A bad task fan-out is a cross-tenant write.
- **Role and scope:** system job; COMPANY
- **Preconditions:** Disposable worker. Both companies have employees.
- **Test data:** Enqueue accrual for A only.
- **Initial database:** Snapshot B ledger counts.
- **Steps:** 1. Run the worker until the job finishes. 2. Compare B.
- **Expected results:** B's ledger count is unchanged. If it changes, stop the batch.
- **Expected UI:** Not applicable.
- **Expected API:** Job success for A.
- **Expected database:** B unchanged.
- **Expected audit:** Job references A.
- **Cleanup:** None.
- **Automation:** Worker.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## SEC-006 — CSV export is limited to scope

- **Module:** Security / Export
- **Objective:** An export cannot be used as a scope bypass.
- **Source:** any export endpoint discovered at execution; employee import is API-only
- **Type:** security
- **Priority:** P1
- **Risk:** High. Exports are bulk disclosure.
- **Role and scope:** BRANCH_MANAGER; BRANCH
- **Preconditions:** North and South employees.
- **Test data:** Export employees.
- **Initial database:** Both branches populated.
- **Steps:** 1. Download the export as the North manager.
- **Expected results:** File contains North and not South. If no export exists, BLOCKED rather than pass.
- **Expected UI:** Download or a missing action.
- **Expected API:** 200 with filtered rows, or 404.
- **Expected database:** No write.
- **Expected audit:** Export if it exists.
- **Cleanup:** Delete the file.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

