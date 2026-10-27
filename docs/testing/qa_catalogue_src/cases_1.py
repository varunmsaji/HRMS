from qa_lib import C, defaults

SYN = "Synthetic only: emails *@example.com, company names 'QA-<tag>-<rand>', password Qa-Pass-123456!"
PS = "PRIVATE_STACK"

# ------------------------------------------------------------------ AUTH
defaults(module="Auth", src="docs/testing/MASTER_PRODUCT_TEST_PLAN.md §1 (2.x); FUNCTIONAL_QA_REPORT §6", pri="P0",
         role="Anonymous / registered COMPANY_ADMIN of tenant T1", data=SYN, env=PS, auto="AUTOMATED+LIVE_SCRIPT",
         pre="Private DB migrated to head; EMAIL_PROVIDER=logging; rate-limit keys reset between runs")
C("AUTH-LOGIN-001", "Login + cookie", "A verified user logs in and receives an access token and an HttpOnly refresh cookie.",
  "200; body has access token; Set-Cookie refresh token has HttpOnly (and Secure outside development); /auth/me returns the caller.",
  "1) Register company 2) Verify email 3) POST /v1/auth/login 4) GET /v1/auth/me", live=["AUTH-06"],
  tests=["integration/auth/test_auth_security", "unit/core/test_passwords"], neg="Refresh token not present in JSON body.",
  inv="One active `session` row for the login.")
C("AUTH-LOGIN-002", "Login gate: unverified email", "Login is refused until the email is verified.",
  "403 EMAIL_NOT_VERIFIED; no session row created.", "1) Register 2) POST login before verification",
  live=["AUTH-01"], tests=["integration/auth/test_email_verification"], inv="0 session rows for the user.")
C("AUTH-LOGIN-003", "No user enumeration", "Wrong password and unknown email are indistinguishable.",
  "Identical status code and error body (code, message) for both; comparable latency (not asserted live).",
  "1) Login unknown email 2) Login known email wrong password 3) Diff responses", live=["AUTH-07", "AUTH-22"],
  tests=["integration/auth/test_auth_security"], amb="Timing side-channel not covered by any existing check.")
C("AUTH-LOGIN-004", "Account lockout", "5 failed attempts lock the account for 15 minutes (documented rule).",
  "6th attempt (even with correct password) refused with a lock error until lock expiry; unlock after 15 min or via admin unlock.",
  "1) 5 wrong-password logins 2) correct-password login 3) advance clock / wait / admin unlock 4) login",
  src="MASTER_PRODUCT_TEST_PLAN §1 (2.6)", live=["AUTH-31", "AUTH-32"], tests=["integration/auth/test_credential_rate_limit"],
  amb="Live checks AUTH-31/32 prove IP/credential RATE LIMIT (429) only; the documented ACCOUNT LOCKOUT (5 fails / 15 min) has no live check. Confirm whether lockout and rate limit are the same mechanism.",
  type="API-E2E+BOUNDARY")
C("AUTH-LOGIN-005", "Validation envelope", "Malformed login input returns a stable 4xx envelope without stack traces.",
  "Missing fields -> 422 with field details; malformed JSON -> 4xx; no traceback text.", "1) POST {} 2) POST invalid JSON",
  live=["AUTH-29", "AUTH-30"], tests=["unit/core/test_error_contract"], pri="P1")
C("AUTH-TOKEN-001", "Forged / tampered tokens", "Only correctly signed, unexpired tokens bound to a live session are accepted.",
  "Garbage, tampered signature, alg=none, expired, wrong-secret and non-existent-session tokens -> 401/403 on /auth/me.",
  "1) Build each token variant (qa.py forge()) 2) GET /auth/me", live=["AUTH-08", "AUTH-09", "AUTH-10", "AUTH-11", "AUTH-12", "AUTH-13", "AUTH-14"],
  tests=["integration/auth/test_auth_security"], type="SECURITY", env=PS)
C("AUTH-REFRESH-001", "Refresh rotation + reuse detection", "Refresh rotates the token; reuse of a rotated token revokes the whole token family.",
  "New access token + new cookie; replayed old token -> rejected; afterwards the newest token is also dead.",
  "1) login 2) refresh 3) replay old cookie 4) use newest cookie", live=["AUTH-15", "AUTH-16", "AUTH-17"],
  tests=["integration/auth/test_refresh_token_reuse"], inv="All refresh tokens of family revoked after reuse.")
C("AUTH-LOGOUT-001", "Logout invalidates session", "After logout the access token and refresh token are immediately invalid.",
  "Logout 200/204; access token -> 401 at once; refresh -> rejected.", "1) login 2) call /auth/me OK 3) logout 4) /auth/me 5) refresh",
  live=["AUTH-18", "AUTH-19", "AUTH-20", "AUTH-21"], tests=["integration/modules/account_invite/test_session_lifecycle"])
C("AUTH-RESET-001", "Password reset happy path + single use", "Reset email only for known accounts; token single-use; weak passwords refused; old password stops working.",
  "Per live checks AUTH-22..28.", "1) forgot-password known+unknown 2) reset weak 3) reset strong 4) reuse token 5) old/new login",
  live=["AUTH-22", "AUTH-23", "AUTH-24", "AUTH-25", "AUTH-26", "AUTH-27", "AUTH-28"], tests=["integration/auth/test_password_reset"])
C("AUTH-RESET-002", "Reset revokes all sessions", "A password reset revokes ALL sessions and refresh tokens of the user (documented SEC-07).",
  "Sessions opened before reset get 401 on next request; refresh tokens rejected.",
  "1) login on two clients 2) complete reset 3) use both old access tokens and refresh tokens",
  src="MASTER_PRODUCT_TEST_PLAN §1 (2.3)", tests=["integration/auth/test_password_reset"],
  amb="No live check asserts this; automated coverage claimed by master plan but not verified in this phase.")
C("AUTH-VERIFY-001", "Email verification token", "Garbage tokens rejected; valid token accepted once.",
  "AUTH-02/04/05 behaviour.", "1) garbage token 2) real token 3) replay", live=["AUTH-02", "AUTH-03", "AUTH-04", "AUTH-05"],
  tests=["integration/auth/test_email_verification"])
C("AUTH-RATE-001", "Auth rate limiting", "Brute-force login attempts are throttled with 429, Retry-After and stable body.",
  "429 after threshold; Retry-After header present.", "1) N bad logins from one source 2) inspect 429",
  live=["AUTH-31", "AUTH-32"], tests=["integration/auth/test_credential_rate_limit", "integration/test_proxy_aware_rate_limiting",
  "unit/shared/test_rate_limit_dual_bucket", "unit/shared/test_rate_limit_redis_failure"], type="SECURITY+BOUNDARY")
C("AUTH-RATE-002", "Redis outage behaviour of auth", "With Redis down login fails closed (503) while authenticated reads continue.",
  "Login 503 promptly (<15 s); /health/ready 503; /health/live 200; reads 200/503 defined.", "1) kill private Redis 2) login 3) read 4) health",
  live=["DEP-04", "DEP-05", "DEP-06", "DEP-07"], tests=["unit/shared/test_rate_limit_redis_failure"],
  amb="Is fail-closed login the intended product behaviour (availability trade-off)? Report calls it an observation.")
C("AUTH-INVITE-001", "Account invite accept", "An invited user accepts a single-use token, sets a password and can log in with the assigned role.",
  "Accept 2xx; login 200; role as invited; token replay refused; token not present in logs.",
  "1) admin POST /users/invite 2) read token from logging sender 3) POST /public/account-invites/{token}/accept 4) login 5) replay",
  live=["LV-22", "LV-23", "LV-24", "LV-25"], tests=["integration/modules/account_invite/test_account_invite.py",
  "integration/modules/account_invite/test_invite_accept_hardening", "integration/modules/account_invite/test_account_invite_pagination",
  "security/test_account_invite_onboarding_token_isolation"])
C("AUTH-INVITE-002", "Mobile email deep links", "Invite/verify/reset emails carry links valid for the mobile app.",
  "Link format matches mobile deep-link handler.", "1) trigger emails 2) parse link 3) feed to deep_link_test fixtures",
  tests=["integration/modules/account_invite/test_mobile_email_links", "unit/core/test_web_app_base_url"], pri="P2", type="API+CONTRACT")
C("AUTH-LINK-001", "Employee login linked to employee record", "An employee invited from an employee record gets a login linked to that record (employee_id in /auth/me).",
  "/auth/me.employee_id equals the invited employee.", "1) POST /employees/{id}/invite 2) accept 3) login 4) /auth/me",
  live=["LV-26"], tests=["integration/auth/test_employee_jwt_linkage"])

# ------------------------------------------------------------------ TENANT ISOLATION + RLS
defaults(module="Tenant isolation", src="FUNCTIONAL_QA_REPORT §6; MASTER_PRODUCT_TEST_PLAN §1.3/1.4", pri="P0",
         role="T1 COMPANY_ADMIN vs T2 COMPANY_ADMIN", data=SYN, env=PS, auto="AUTOMATED+LIVE_SCRIPT", type="SECURITY")
C("TEN-ISO-001", "Employee cross-tenant access", "T2 cannot read/modify/delete T1 employees; probes look like 'not found'.",
  "GET/PATCH/DELETE -> 404; T1 data unchanged; T2 list contains no T1 rows.", "1) T1 creates employees 2) T2 attempts GET/PATCH/DELETE/list",
  live=["TEN-01", "TEN-02", "TEN-03", "TEN-04", "TEN-05"], tests=["integration/modules/organisation/test_cross_tenant_isolation",
  "security/test_organisation_security"], inv="T1 employee rows byte-identical before/after.")
C("TEN-ISO-002", "Cross-tenant on leave, payroll, imports, docs, punches, regularization", "No module leaks across tenants on read, write or transition.",
  "404/403 and no row changes for every listed resource.", "1) T1 creates resource 2) T2 reads/transitions/creates against it",
  live=["LV-41", "PAY-18", "PAY-19", "PAY-20", "PAY-21", "JOB-06", "DOC-07", "DOC-08", "ATT-11", "ATT-12", "REG-15", "LV-31"],
  tests=["integration/test_route_authorization_matrix"])
C("TEN-HDR-001", "Company header handling", "Token for T1 plus X-Company-Id of T2/random/missing never yields another tenant's data.",
  "T2 id or random id -> denied; missing header -> safe response (400/403/200 only with own data).",
  "1) call with each header variant", live=["TEN-06", "TEN-07", "TEN-08", "TEN-09"], tests=["unit/core/test_company_access"],
  amb="Missing X-Company-Id accepts 200/400/403/422 in the live script (disjunctive); expected single behaviour should be fixed by product owner.")
C("TEN-LIST-001", "List endpoints disjoint across tenants", "Eleven org/leave list endpoints return only own rows.",
  "No overlapping IDs between T1 and T2 lists.", "1) populate both tenants 2) compare lists", live=["TEN-10"],
  tests=["integration/modules/organisation/test_cross_tenant_isolation"], amb="Only 11 endpoints, only when lists non-empty; vacuous for empty lists.")
C("TEN-RLS-001", "RLS as the real runtime role", "As hrms_app: no tenant context -> 0 rows; with context only own rows; cannot cross-read/insert/update.",
  "RLS-01..05 outcomes.", "1) connect as hrms_app (not the owner) 2) set app.company_id 3) run SELECT/INSERT/UPDATE across tenants",
  live=["RLS-01", "RLS-02", "RLS-03", "RLS-04", "RLS-05"], tests=["security/test_rls_runtime_role"], type="DB-INVARIANT",
  risk="Connects with hrms_app dev password; run only against a private DB.")
C("TEN-RLS-002", "Runtime role privileges", "hrms_app is NOSUPERUSER/NOBYPASSRLS; append-only tables lack UPDATE/DELETE/TRUNCATE.",
  "has_table_privilege matrix per tests/integration/core/test_runtime_role_grants.py.", "1) read pg_roles and privileges",
  live=["RLS-06", "RLS-07", "LV-21"], tests=["integration/core/test_runtime_role_grants", "security/test_db01_credential_provisioning",
  "integration/modules/payroll/test_b05_db_immutability"], type="DB-INVARIANT",
  amb="`002_app_role.sh` re-run re-grants ALL privileges (see ENV-GRANT-001).")
C("TEN-DEL-001", "Tenant wipe helper safety", "Test tenant-wipe helper deletes only the named company's rows.",
  "Only rows with company_id = target removed.", "1) create two tenants 2) wipe one 3) verify other intact",
  tests=["integration/tenant_wipe", "unit/test_test_isolation"], pri="P2", type="INFRA",
  amb="tenant_wipe.py is a helper not a test; its safety depends on DATABASE_URL (see ENV-ISOL-001).")

# ------------------------------------------------------------------ RBAC
defaults(module="RBAC", src="docs/modules/employee/26_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_REPORT.md; FUNCTIONAL_QA_REPORT §6",
         pri="P0", role="EMPLOYEE / HR_ADMIN / COMPANY_ADMIN of T1", data=SYN, env=PS, auto="AUTOMATED+LIVE_SCRIPT", type="SECURITY")
C("RBAC-ESS-001", "EMPLOYEE role write denials", "EMPLOYEE cannot create/patch employees, invite users, escalate roles, create leave types/org structure, edit company.",
  "403 for each; no rows created.", "1) login as EMPLOYEE 2) attempt each mutation",
  live=["RBAC-01", "RBAC-04", "RBAC-05", "RBAC-06", "RBAC-12", "RBAC-13"], tests=["integration/modules/organisation/test_permission_matrix",
  "integration/test_route_authorization_matrix"])
C("RBAC-ESS-002", "EMPLOYEE role read scope", "EMPLOYEE sees only own record; cannot read directory, users, payroll config, imports, onboarding cases.",
  "403/404 or own-record-only lists.", "1) login as EMPLOYEE 2) GET each listed resource",
  live=["RBAC-02", "RBAC-03", "RBAC-07", "RBAC-08", "RBAC-09", "RBAC-10", "RBAC-11"], tests=["integration/modules/employee/test_employee_data_scope",
  "integration/modules/attendance/test_employee_default_role_attendance"])
C("RBAC-ADM-001", "HR_ADMIN capabilities and ceiling", "HR_ADMIN can create employees but cannot grant COMPANY_ADMIN.",
  "201 on create; 403 on grant.", "1) HR_ADMIN creates employee 2) attempts role grant", live=["RBAC-15", "RBAC-16"],
  tests=["integration/modules/account_invite/test_user_access_control"])
C("RBAC-MGR-001", "Manager data scope", "A manager sees/approves only direct (or as-of-date) reports; HOD chain per policy.",
  "Out-of-scope reads 404; approvals by non-assigned approver 403.", "1) build reporting tree 2) manager acts on report and non-report",
  src="docs/modules/employee/27_REPORTING_MANAGER_SECURITY_AUDIT.md", tests=["integration/modules/leave/test_leave_rbac_matrix",
  "integration/modules/leave/test_leave_approval_hod"], auto="AUTOMATED", amb="PD-APR-1: approval uses the manager as of the ATTENDANCE DATE, not today (open product decision).",
  pri="P0")
C("RBAC-MATRIX-001", "Route authorization matrix", "Every operation requires auth unless documented public; permission codes enforced per route.",
  "No 2xx/3xx without credentials except documented public routes (335 ops).", "1) sweep OpenAPI without credentials",
  live=["SWP-01"], tests=["integration/test_route_authorization_matrix", "security/test_api_docs_exposure"])

# ------------------------------------------------------------------ ORG / CONFIG
defaults(module="Organisation", src="docs/modules/* (company, branch, department, designation, grade, legal-entity)", pri="P2",
         role="COMPANY_ADMIN T1", data=SYN, env=PS, auto="AUTOMATED")
C("ORG-REG-001", "Company registration", "Registration creates company + admin atomically, rate limited, plan seeded.",
  "201; company, admin user, subscription rows exist or none exist on failure.", "1) register 2) force failure mid-way (existing test) 3) rate-limit",
  tests=["integration/modules/organisation/test_registration", "integration/modules/organisation/test_plan_catalogue_seed",
  "integration/modules/organisation/test_subscription_constraint", "integration/modules/organisation/test_company_feature_flag_constraint"],
  inv="No orphan company/user rows after failed registration.", pri="P1")
C("ORG-STRUCT-001", "Branches, departments, designations, grades, legal entities", "CRUD with uniqueness, optimistic concurrency, tenant scoping.",
  "Per module unit/integration tests.", "1) CRUD each master 2) duplicate code 3) stale If-Match",
  tests=["integration/modules/organisation/test_branch", "integration/modules/organisation/test_department",
  "integration/modules/organisation/test_designation", "integration/modules/organisation/test_grade", "integration/modules/organisation/test_legal_entity",
  "unit/modules/organisation/test_branch_service", "unit/modules/organisation/test_department_service", "unit/modules/organisation/test_designation_service",
  "unit/modules/organisation/test_grade_service", "unit/modules/organisation/test_legal_entity_service", "unit/modules/organisation/test_router",
  "unit/modules/organisation/test_service"])
C("ORG-PROFILE-001", "Company profile + setup progress + timezone guard", "Profile edits validated; timezone change guarded; setup progress computed.",
  "Per tests.", "1) edit profile 2) change timezone with existing attendance 3) read setup-progress",
  tests=["integration/modules/organisation/test_company_profile", "integration/modules/organisation/test_setup_progress",
  "integration/modules/organisation/test_timezone_change_guard", "unit/shared/test_timezone", "unit/shared/test_business_time"],
  amb="Which timezone rule governs business dates: company vs legal-entity (WD-06 / DEC-TZ)? See ATTENDANCE_TIMEZONE_* docs.")
C("ORG-POLCAL-001", "Policy and calendar rules (org level)", "Calendars/holidays/weekly-off patterns validated and resolved by precedence.",
  "Per tests.", "1) create calendar/pattern 2) resolve a date", tests=["integration/modules/organisation/test_policy_and_calendar_rules",
  "integration/modules/organisation/test_workforce_calendar", "unit/modules/organisation/test_calendar_resolution"])
C("SUB-READ-001", "Subscription read-only summary", "GET plan/feature summary and dashboard reflect plan and seats.",
  "Matches subscription row; no billing/usage mutation exists.", "1) GET /company/subscription and dashboard",
  tests=["integration/modules/organisation/test_subscription_dashboard", "unit/modules/organisation/test_subscription_dashboard"],
  amb="Seat/feature limits enforcement on create is not covered by any live check.")
C("PAGE-001", "Pagination contract", "per_page/page honoured, max enforced, stable ordering, disjoint pages.",
  "No duplicates or skips across pages; per_page>max clamped or 422; page=0 never 500.", "1) seed >N rows 2) walk pages",
  live=["EMP-07", "EMP-08", "EMP-09"], tests=["unit/shared/test_pagination", "integration/modules/attendance/test_bounded_list_pagination",
  "integration/modules/employee/test_employee_pagination", "integration/modules/leave/test_leave_application_pagination",
  "integration/modules/leave/test_leave_ledger_pagination", "integration/modules/onboarding/test_onboarding_case_pagination",
  "integration/modules/organisation/test_shift_version_pagination", "integration/modules/organisation/test_workforce_calendar_pagination",
  "integration/modules/payroll/test_p1_hardening"], pri="P1", amb="EMP-09 accepts 'clamped OR 422' - fix one expected behaviour.")
C("CONC-IFMATCH-001", "Optimistic concurrency (ETag / If-Match)", "Mutations require a current If-Match; stale -> 409/412; missing -> 428.",
  "Stale rejected with data unchanged; missing rejected.", "1) GET ETag 2) PATCH ok 3) PATCH stale 4) PATCH none",
  live=["EMP-10", "EMP-11", "EMP-12", "EMP-13", "LV-16", "LV-36", "PAY-11"], tests=["unit/shared/test_if_match"], pri="P1",
  amb="EMP-13 accepts 400/409/412/422/428 - exact status contract unspecified in the live check.")
C("API-CONTRACT-001", "Core API contract & robustness", "Unknown route 404 JSON, wrong method 405 JSON, bad UUID 422, injection-shaped input safe, 3 MB body rejected.",
  "SWP-05..11 behaviour.", "1) probe each", live=["SWP-02", "SWP-03", "SWP-04", "SWP-05", "SWP-06", "SWP-07", "SWP-08", "SWP-09", "SWP-10", "SWP-11"],
  tests=["integration/test_api_contract_core", "integration/test_route_robustness", "security/test_security_headers", "unit/core/test_cors_middleware"],
  pri="P1", type="SECURITY+ROBUSTNESS", amb="SWP-02/03 only assert 'no 5xx' on garbage input - technical, not business correctness.")

# ------------------------------------------------------------------ EMPLOYEE + ONBOARDING
defaults(module="Employee", src="docs/modules/employee/*; FUNCTIONAL_QA_REPORT §1", pri="P1",
         role="HR_ADMIN T1", data=SYN, env=PS, auto="AUTOMATED")
C("EMP-CRUD-001", "Create employee", "Employee created with generated code, validation of names/email/DOB.",
  "201 + code; invalid input 422 with field errors.", "1) POST /employees valid 2) missing first_name 3) bad email 4) future DOB",
  live=["EMP-01", "EMP-04", "EMP-05", "EMP-06"], tests=["integration/modules/employee/test_employee.py", "integration/modules/employee/test_employee_input_validation",
  "unit/modules/employee/test_employee_service", "unit/modules/employee/test_employee_identity_service"], auto="AUTOMATED+LIVE_SCRIPT")
C("EMP-IDEM-001", "Employee create idempotency", "Replayed Idempotency-Key returns same employee; changed body with same key rejected.",
  "Same id on replay; 409/422 on mismatch; exactly one row.", "1) POST with key 2) replay 3) replay with different body",
  live=["EMP-02", "EMP-03"], tests=["integration/modules/employee/test_optional_idempotency"], pri="P1",
  defect="OBS-IDEM-01", amb="Report observation: Idempotency-Key is OPTIONAL on employee-create and onboarding-case create, so an API double-submit creates 2 employees. Product owner to decide whether it must be mandatory.",
  auto="AUTOMATED+LIVE_SCRIPT")
C("EMP-LIFE-001", "Lifecycle and concurrency", "Update, confirm, terminate follow valid transitions under concurrency.",
  "Invalid transitions 409; parallel updates serialised.", "1) update/confirm/terminate 2) parallel conflicting updates",
  tests=["integration/modules/employee/test_employee_lifecycle_and_concurrency", "integration/modules/employee/test_employee_confirmation",
  "integration/modules/employee/test_master_data_compensation_termination", "test_termination_task_registration"])
C("EMP-EMPLOY-001", "Employment / assignment / effective dating", "Employments, assignments, compensation, banking, statutory, dependants are effective-dated without overlap/gaps; pay_basis settable.",
  "Overlaps rejected; history preserved; pay_basis MONTHLY|DAILY_WAGE.", "1) add employment 2) overlapping employment 3) change assignment 4) edit pay_basis",
  tests=["integration/modules/employee/test_employment", "integration/modules/employee/test_effective_dated_integrity",
  "integration/modules/employee/test_employee_assignment", "integration/modules/employee/test_employee_compensation",
  "integration/modules/employee/test_employee_banking", "integration/modules/employee/test_employee_statutory",
  "integration/modules/employee/test_employee_dependent", "unit/modules/employee/test_employment", "unit/modules/employee/test_employee_assignment_service",
  "unit/modules/employee/test_employee_bank_service", "unit/modules/employee/test_employee_compensation_service",
  "unit/modules/employee/test_employee_statutory_service"], pri="P0",
  amb="Onboarding wizard and CSV import default pay_basis to MONTHLY and do not collect it (PAYROLL_BUSINESS_DECISIONS follow-up).")
C("EMP-PII-001", "PII field encryption", "Sensitive fields are encrypted at rest; backfill is safe; key registry validated.",
  "Ciphertext in DB, plaintext via API for authorised roles; backfill idempotent.", "1) create employee with PAN/bank 2) read raw column 3) run backfill twice",
  tests=["unit/core/test_crypto", "unit/core/test_pii_crypto_service", "integration/test_pii_encryption_backfill"], pri="P0", type="DB-INVARIANT+UNIT",
  inv="Raw column != plaintext.")
C("ONB-FLOW-001", "Full onboarding: case -> invite -> public submit -> review -> activate", "A new hire completes the public form, HR reviews, activation creates employee, employment and optional login.",
  "Case moves DRAFT->INVITED->SUBMITTED->APPROVED->ACTIVATED; employee has data from submission; invalid transitions 409; activation failure is isolated (no half-created employee).",
  "1) HR creates case 2) invite email token 3) public GET/PUT/submit with token 4) HR approves 5) activate 6) verify employee + login",
  tests=["integration/modules/onboarding/test_onboarding_case.py", "integration/modules/onboarding/test_onboarding_invite", "integration/modules/onboarding/test_onboarding_public",
  "integration/modules/onboarding/test_onboarding_submit", "integration/modules/onboarding/test_onboarding_review", "integration/modules/onboarding/test_onboarding_activation",
  "integration/modules/onboarding/test_activation_failure_isolation"], pri="P0", auto="AUTOMATED",
  amb="NO live end-to-end exists for this workflow. Whether the wizard must collect pay_basis, statutory and bank data before activation needs product-owner confirmation.",
  inv="Exactly one employee per activated case; no employee row for failed activation.")
C("ONB-DOC-001", "Onboarding document upload bounds", "Type/size/magic-byte validation; per-token rate limit; tenant-scoped storage keys.",
  "Invalid files 4xx; rate limit 429; no object left on rejection.", "1) upload valid/invalid/oversize/rapid-fire with token",
  tests=["integration/modules/onboarding/test_onboarding_documents", "integration/modules/onboarding/test_onboarding_upload_bounds",
  "integration/modules/onboarding/test_onboarding_upload_rate_limit", "unit/modules/onboarding/test_document_validation",
  "unit/shared/test_onboarding_upload_rate_limit_middleware"], pri="P1")
C("ONB-EMAIL-001", "Onboarding email sending + failure classification", "Email sender classifies transient vs permanent failures; no real send in tests.",
  "Logging provider used; failure classes mapped.", "1) send with each provider stub",
  tests=["unit/modules/onboarding/test_email_sender", "unit/modules/onboarding/test_email_failure_classification"], pri="P2",
  risk="Real SES must never be configured in QA (EMAIL_PROVIDER=logging).")

defaults(module="Employee import", src="docs/audits/UPLOAD_BATCH_*; FUNCTIONAL_QA_REPORT §5 (DEF-02/03)", pri="P1",
         role="HR_ADMIN T1", data=SYN + "; CSV with 4 rows (2 valid, 2 invalid)", env=PS, auto="AUTOMATED+LIVE_SCRIPT")
C("IMP-CSV-001", "CSV import round trip via real worker", "Upload -> Celery -> rows -> row errors with codes; valid rows create employees; invalid create none.",
  "Batch COMPLETED; 2 succeeded 2 failed; row numbers + codes visible; exactly 2 employees.", "1) upload 2) wait for worker 3) read batch + errors",
  live=["JOB-01", "JOB-02", "JOB-03", "JOB-04", "JOB-05"], tests=["integration/modules/employee_import/test_employee_import.py",
  "unit/modules/employee_import/test_row_validation"], inv="employee count == succeeded rows.")
C("IMP-VAL-001", "Upload validation", "Non-CSV, missing header, binary/non-UTF-8 bytes rejected cleanly before S3/queue.",
  "4xx/422 IMPORT_FILE_UNREADABLE; no batch row; no object.", "1) upload each bad file", live=["JOB-07", "JOB-08"],
  tests=["integration/modules/employee_import/test_employee_import_upload_bounds"], defect="DEF-03")
C("IMP-IDEM-001", "Import idempotency & backlog reconciliation", "Re-processing a batch never duplicates employees; backlog reconciler finds stuck batches.",
  "Exactly-once creation; stuck PENDING detected.", "1) process same batch twice 2) run reconciler",
  live=["JOB-10", "JOB-11", "JOB-12"], tests=["integration/modules/employee_import/test_import_idempotency",
  "integration/modules/employee_import/test_import_backlog_reconciliation", "unit/ops/test_import_backlog"])
C("IMP-OUTAGE-001", "Worker down / killed", "With worker down the batch stays PENDING and completes exactly once after restart.",
  "No lost/half batch; no duplicates.", "1) stop worker 2) upload 3) start worker", live=["JOB-09", "JOB-10", "JOB-11"],
  tests=[], risk="Needs a PRIVATE worker process; never stop the shared worker.")
C("IMP-UI-001", "Import UI", "A user can import employees from web/mobile.", "n/a - NOT IMPLEMENTED in UI (API only).",
  "n/a", status="NOT_APPLICABLE", type="UI-E2E", pri="P2", amb="Report: employee CSV import has no web or mobile UI. Treat as feature gap, not failure.", auto="N/A", env="BROWSER")

# ------------------------------------------------------------------ DOCUMENTS
defaults(module="Documents", src="docs/audits/UPLOAD_BATCH_A/B/C; docs/modules/employee", pri="P0",
         role="HR_ADMIN T1 vs T2", data=SYN + "; tiny synthetic PDF, fake-exe-as-pdf, empty file, 11 MB file", env=PS, auto="AUTOMATED+LIVE_SCRIPT")
C("DOC-UP-001", "Upload validation", "Valid PDF accepted and metadata stored; executables/HTML disguised as PDF, empty and oversize files rejected with 4xx; path traversal names safe.",
  "201 for valid; 4xx (never 500) for others; no row/object for rejected.", "1) upload each sample", live=["DOC-01", "DOC-02", "DOC-03", "DOC-04", "DOC-05", "DOC-06"],
  tests=["unit/modules/employee/test_document_validation", "unit/core/test_uploads", "integration/modules/employee/test_employee_documents"],
  inv="Rejected upload leaves 0 document rows and 0 storage objects.")
C("DOC-XT-001", "Cross-tenant document denial", "T2 cannot upload/list/download T1 documents; presigned URLs are scoped.",
  "Denied; URL not issued for foreign document.", "1) T1 uploads 2) T2 list/download/upload", live=["DOC-07", "DOC-08"],
  tests=["integration/modules/employee/test_employee_documents"], amb="Presigned-URL expiry and reuse by another tenant after issue are NOT tested.")
C("DOC-DL-001", "Presigned download", "Presigned URL returns exactly the bytes uploaded (hash match); URL expires.",
  "SHA-256 equal; expired URL fails.", "1) upload 2) fetch URL 3) wait past expiry 4) refetch", live=["DOC-09"], tests=[], pri="P1",
  amb="Expiry and permission re-check at download time untested.")
C("DOC-STORE-001", "Storage failure behaviour", "Storage unreachable -> clean error envelope, no partial rows.",
  "5xx with stable envelope; 0 document rows; 0 batch rows.", "1) point API at dead storage 2) upload doc/import", live=["DEP-00", "DEP-01", "DEP-02", "DEP-03", "DEP-08"],
  tests=["unit/core/test_storage", "unit/core/test_storage_metrics", "integration/core/test_storage"], defect="OBS-STOR-01",
  amb="Report observation: storage failure surfaces as 500 INTERNAL_ERROR not a retryable 503, and /health/ready reports configuration not reachability. Desired contract needs decision.")
