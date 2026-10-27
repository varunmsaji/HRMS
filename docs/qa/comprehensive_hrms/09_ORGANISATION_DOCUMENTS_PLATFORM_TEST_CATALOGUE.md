# Organisation, documents, and platform

10 cases. Execution status is `NOT_RUN`. The machine-readable copy is `TEST_CASES.csv`.

## ORG-001 — Admin creates branch, department, and designation

- **Module:** Organisation / Masters
- **Objective:** Saved names round-trip.
- **Source:** organisation routers and web org pages
- **Type:** UI
- **Priority:** P0
- **Risk:** Medium. Employees cannot be placed without masters.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** Fresh company.
- **Test data:** Branch North, Department Engineering, Designation Engineer.
- **Initial database:** Empty masters.
- **Steps:** 1. Create each. 2. Reload each page.
- **Expected results:** All three persist with the typed names.
- **Expected UI:** Lists show them after reload.
- **Expected API:** 201.
- **Expected database:** Three rows in company A.
- **Expected audit:** Create events.
- **Cleanup:** Keep.
- **Automation:** UI.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ORG-002 — HR cannot create organisation masters

- **Module:** Organisation / Masters
- **Objective:** ORG grants are not on HR_ADMIN.
- **Source:** register_company grant loops
- **Type:** security
- **Priority:** P1
- **Risk:** Medium. Unreviewed org edits change who is in scope.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** HR user.
- **Test data:** Branch South.
- **Initial database:** No South.
- **Steps:** 1. HR posts a branch.
- **Expected results:** 403. No South row.
- **Expected UI:** The nav may still show the page because nav is not permission-filtered. The save fails.
- **Expected API:** 403.
- **Expected database:** No row.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** G-W1

## ORG-003 — Weekly off is Saturday and Sunday

- **Module:** Organisation / Calendar
- **Objective:** The calendar used by leave day-count resolves those days as WEEKLY_OFF.
- **Source:** work calendar resolution
- **Type:** functional
- **Priority:** P0
- **Risk:** High. Leave arithmetic depends on this.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** Calendar assigned to Alice.
- **Test data:** 2026-06-06 and 2026-06-07.
- **Initial database:** Assignment present.
- **Steps:** 1. Resolve both dates.
- **Expected results:** WEEKLY_OFF. config_incomplete false.
- **Expected UI:** Calendar page shows the weekend.
- **Expected API:** day_type WEEKLY_OFF.
- **Expected database:** Assignment row.
- **Expected audit:** Not required.
- **Cleanup:** Keep.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## ORG-004 — There is no role editor

- **Module:** Organisation / Roles
- **Objective:** Custom role creation is not offered.
- **Source:** no permission editor in the product
- **Type:** functional
- **Priority:** P2
- **Risk:** Medium. Testers must not assume a custom-role screen exists.
- **Role and scope:** COMPANY_ADMIN; COMPANY
- **Preconditions:** Signed in as admin.
- **Test data:** Users and setup pages.
- **Initial database:** Five roles.
- **Steps:** 1. Walk the settings pages for a create-role control. 2. POST a role if a route exists.
- **Expected results:** No create-role UI. If a route exists and creates a sixth role, record it and stop using the assumption that only five roles exist. If it 404s, BLOCKED for custom-role cases.
- **Expected UI:** Five roles, no editor.
- **Expected API:** 404.
- **Expected database:** Still five roles.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** UI inspection.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## DOC-001 — Employee uploads a synthetic file and downloads it

- **Module:** Documents / Upload
- **Objective:** Stored object matches the bytes and is scoped to the employee.
- **Source:** document panel and storage service
- **Type:** UI
- **Priority:** P1
- **Risk:** High. Wrong object or wrong owner leaks documents.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Disposable bucket. File is a local text file named qa.txt containing 'synthetic-document'.
- **Test data:** qa.txt.
- **Initial database:** No document.
- **Steps:** 1. Upload. 2. Download. 3. Bob requests the same document id.
- **Expected results:** Download bytes equal the file. Bob is 404.
- **Expected UI:** File listed then downloaded.
- **Expected API:** 201 then 200 then 404.
- **Expected database:** One metadata row in company A.
- **Expected audit:** Upload.
- **Cleanup:** Delete if a delete grant exists for the owner.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## DOC-002 — Storage outage does not create a metadata row

- **Module:** Documents / Storage failure
- **Objective:** A failed put rolls back.
- **Source:** storage and DB transaction
- **Type:** recovery
- **Priority:** P1
- **Risk:** High. An orphan row downloads nothing or the wrong file later.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Bucket endpoint pointed at a closed port in the disposable env.
- **Test data:** qa.txt.
- **Initial database:** Zero documents.
- **Steps:** 1. Upload.
- **Expected results:** Error. Document count stays 0.
- **Expected UI:** Upload failed.
- **Expected API:** 5xx.
- **Expected database:** count=0.
- **Expected audit:** Failure, no success.
- **Cleanup:** Restore the bucket endpoint.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## DOC-003 — Terminated employee cannot download

- **Module:** Documents / Access
- **Objective:** Access ends when the account is disabled.
- **Source:** auth plus document scope
- **Type:** security
- **Priority:** P1
- **Risk:** High. Ex-employees retaining files.
- **Role and scope:** EMPLOYEE; SELF
- **Preconditions:** Bob uploaded a file, then was terminated.
- **Test data:** Old session and a new login.
- **Initial database:** File exists.
- **Steps:** 1. Call download with the old session. 2. Login again.
- **Expected results:** Both fail. HR can still download if HR has the grant.
- **Expected UI:** Denied.
- **Expected API:** 401 or 403.
- **Expected database:** File still stored.
- **Expected audit:** Denied.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PLT-001 — Health responds without company data

- **Module:** Platform / Health
- **Objective:** The liveness route is anonymous and contains no employee fields.
- **Source:** health router
- **Type:** functional
- **Priority:** P1
- **Risk:** Low. Health is the first isolation smoke check.
- **Role and scope:** anonymous; none
- **Preconditions:** API up.
- **Test data:** GET health.
- **Initial database:** Not applicable.
- **Steps:** 1. GET the health route with no cookie.
- **Expected results:** 200. Body has no email, name, or company list.
- **Expected UI:** Not applicable.
- **Expected API:** 200.
- **Expected database:** No write.
- **Expected audit:** None.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** —

## PLT-002 — Non-UTF8 employee CSV returns a controlled error

- **Module:** Platform / Import
- **Objective:** The DEF-03 fix still holds.
- **Source:** DEF-03 fixed; employee import
- **Type:** functional
- **Priority:** P2
- **Risk:** Medium. A 500 on a bad file can leak a traceback.
- **Role and scope:** HR_ADMIN; COMPANY
- **Preconditions:** Import route. A latin-1 CSV that is not UTF-8.
- **Test data:** bytes 0xFF in a name column.
- **Initial database:** Employee count known.
- **Steps:** 1. Upload the file.
- **Expected results:** 4xx, not 500. Employee count unchanged. Body has no traceback.
- **Expected UI:** Import may be API-only. Use the API.
- **Expected API:** 4xx.
- **Expected database:** count unchanged.
- **Expected audit:** Rejected import.
- **Cleanup:** None.
- **Automation:** API.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** DEF-03

## PLT-003 — Celery task uses a fresh event loop

- **Module:** Platform / Jobs
- **Objective:** DEF-02 stays fixed.
- **Source:** DEF-02; celery task event loop test
- **Type:** integration
- **Priority:** P1
- **Risk:** High. A loop bug drops leave and payroll jobs.
- **Role and scope:** system job; COMPANY
- **Preconditions:** Disposable worker.
- **Test data:** One no-side-effect or disposable accrual task.
- **Initial database:** Broker empty.
- **Steps:** 1. Enqueue. 2. Wait for success. 3. Read the worker log.
- **Expected results:** Task succeeds. Log has no 'event loop is closed'.
- **Expected UI:** Not applicable.
- **Expected API:** Job success.
- **Expected database:** Only the intended disposable write.
- **Expected audit:** Job complete.
- **Cleanup:** Stop the disposable worker.
- **Automation:** Worker.
- **Status:** NOT_RUN
- **Actual result:**
- **Evidence:**
- **Defect:** DEF-02

