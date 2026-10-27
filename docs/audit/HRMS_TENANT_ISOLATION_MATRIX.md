# HRMS Tenant Isolation Matrix

**Model**: shared database, shared tables, `company_id UUID` tenant key, enforced by (1) JWT-bound tenant + membership check, (2) PostgreSQL Row-Level Security with `FORCE ROW LEVEL SECURITY` on 94 tables, (3) repository/service filtering, (4) RBAC with data scopes. Evidence tags: [REPO], [DEV-DB] (empty dev DB, catalog only), [UNVERIFIED].

## 1. How tenant identity is established

| Step | Mechanism | Evidence |
|---|---|---|
| Source of truth | `company_id` inside the signed JWT (`AuthenticatedUser.company_id`), **not** the header | `core/tenancy/dependencies.py:12-54` |
| Header | `X-Company-Id` optional; if present and ≠ token company → `404` + `tenant.rejected` security event | same, lines 18-31 |
| Membership | `user_company` row must exist for (user, token company) else 404 | same, lines 33-44 |
| DB scope | `set_config('app.company_id', <verified id>, true)` (transaction-local) | `core/db/session.py:53-60` |
| Policy | `USING (company_id = current_setting('app.company_id', true)::uuid)` for ALL commands; unset GUC → NULL → **no rows (fail-closed)** | `pg_policies` [DEV-DB] |
| Runtime role | `hrms_app`: NOSUPERUSER, NOBYPASSRLS; CI step asserts it | `infra/docker/postgres/init/002_app_role.sh`, `ci.yml` |

### Caveats found

1. **Transaction-local GUC and mid-request commits.** Services that call `session.commit()` mid-request start a new transaction with no GUC, so subsequent reads silently return empty (fail-closed, not a leak). Call sites: `identity/service.py:86,281`, `employee_import/service.py:177,197,354,438,619`, `account_invite/service.py:337`, `platform/service.py:132,369`, `attendance/face_service.py:181`, `onboarding/email_outbox.py:235-329`. Several re-apply the GUC (`employee_import/service.py:612-620` documents it); each must be proven by a test. (F-05, P2.)
2. **GUC is first set from the unverified header.** `TenancyMiddleware` parses the raw `X-Company-Id` into the ContextVar and `get_session` applies it before membership is verified (`core/tenancy/middleware.py:23-26`, `session.py:98-106`); `get_tenant_context` then overwrites it. Mitigated: mismatch → 404 and token company is what is re-applied. Residual: any dependency that reads an RLS table between those two points would run under an attacker-chosen company. [UNVERIFIED – G3; add a test with a mismatched header against every dependency that precedes `get_tenant_context`.] (F-06, P2.)
3. **Policy has no `WITH CHECK` clause** (not needed: for `ALL` policies `USING` is reused) – confirmed `qual` only [DEV-DB].
4. **Foreign keys ignore tenancy** (0 composite FKs, F-03). RLS prevents *reading* another tenant, but referential checks are tenant-blind. FK checks run without RLS, so a foreign tenant's UUID in a write is accepted whenever that row exists. Hence P1.
5. **Platform operators** (`platform_admin`, `platform_session`, `platform_audit_log`) use tables outside RLS and, for cross-company work, set the GUC per company (`platform/service.py:231,327,384`). The app has no separate BYPASSRLS role – good – but every platform route must require platform auth: covered by `tests/integration/test_route_authorization_matrix.py` (U: confirm it enumerates `/platform/*`).
6. **Background jobs** enumerate companies from the non-RLS `company` table, then open `session_scope(company_id=…)` per company (`leave/tasks.py:88-97`, `attendance/tasks.py:61`). No job found that runs unscoped against RLS tables as `hrms_app` (an unscoped query would return nothing). [REPO]
7. **Tests.** `tests/security/test_rls_runtime_role.py::test_cross_tenant_isolation_and_full_lifecycle_under_runtime_role` exercises `employee`, `audit_log` and a few more under the runtime role; module suites contain cross-tenant tests for attendance, leave, accounts, onboarding. There is **no generated test iterating every RLS table** (T-01). Status columns below say "catalog" when only RLS presence is proven.

## 2. Matrix

Status key: **RLS+test** = RLS FORCE in catalog and a behavioural cross-tenant test located in `tests/`; **RLS** = catalog only (behavioural test UNVERIFIED); **token** = no RLS, accessed by hashed secret; **global** = intentionally non-tenant.

| Module | Entities (tables) | Tenant key | Access path | Status |
|---|---|---|---|---|
| Identity | `user`, `user_company`, `role`, `permission`, `role_permission`, `user_role` | `user`: none (global identity); `user_company.company_id`, `role.company_id` (nullable) | login via `login_lookup_user_companies` SECURITY DEFINER; membership via `IdentityRepository.get_user_company` | `user_company`, `role`: RLS+test (rbac scope test). `user`, `permission`, `role_permission`, `user_role`: global – **F-04/F-13**; `user_role` links user→role without company column: confirm role visibility is enforced via `role` RLS |
| Sessions | `session`, `refresh_token`, `password_reset_token`, `email_verification_token` | `session`/`refresh_token.company_id` nullable; token tables none | by token hash / session id from signed JWT | token (no RLS) – needs explicit tests (F-04) |
| Company/billing | `company`, `subscription`, `plan`, `plan_feature`, `company_feature_flag`, `company_setup_progress`, `number_series` | `company.id`; others `company_id` | `company` readable by id for task fan-out; `FORCE` set but RLS not enabled (inert) | `subscription`, flags, setup, series: RLS; `company`, `plan*`: global |
| Organisation | `legal_entity`, `branch`, `department`, `designation`, `grade`, `holiday_calendar`, `holiday`, `weekly_off_pattern`, `weekly_off_rule`, `work_calendar`, `work_calendar_holiday_calendar`, `calendar_exception`, `shift`, `shift_version`, `shift_break`, `shift_duty_block`, `shift_roster`, `policy_assignment` | `company_id` | `modules/organisation/repository.py` via request session | RLS; `tests/security/test_organisation_security.py` → RLS+test |
| Employee | `employee`, `employment`, `employee_assignment`, `employee_compensation`, `employee_salary`, `employee_statutory`, `employee_bank`, `employee_dependent`, `employee_education`, `employee_experience`, `employee_document` | `company_id` | `employee/repository.py`; data-scope (self/reportees/branch) in RBAC | `employee`: RLS+test; others RLS |
| Documents (object store) | key `employee/{company_id}/{employee_id}/{document_id}/document{ext}`; `employee_document`, `onboarding_document` rows hold key | company in key and row | server-built key (`employee/document_validation.py:52-59`, never from client input); download via presigned URL minted after RLS-scoped row lookup | Bucket has no per-tenant policy: isolation depends on row lookup before signing. RLS on rows → OK. [UNVERIFIED] expiry of presigned URL (check `s3_presign_expiry`); presigned URL is bearer – short TTL required |
| Onboarding / invites | `onboarding_case`, `onboarding_document`, `onboarding_section_review`, `onboarding_token`, `account_invite`, `email_outbox`, `email_log` | `company_id` (`email_*` nullable) | candidate/invite flows by hashed token; then GUC set from the token's company (`onboarding/service.py:742`, `account_invite/service.py:269,311`) | cases/documents/reviews: RLS; `onboarding_token`, `account_invite`, `email_log`: token/no RLS; `test_account_invite_onboarding_token_isolation.py` → partial test |
| Import | `employee_import_batch`, `employee_import_row_error` | `company_id` | Celery `employee_import.process_batch` receives company id, uses `session_scope(company_id=…)` | RLS |
| Attendance | `punch`, `attendance_day`, `attendance_break`, `attendance_period`, `attendance_period_action`, `attendance_period_summary`, `attendance_policy`(+`_version`, bands), `regularization_policy`(+`_version`, `_allowed_type`), `attendance_regularization_request/_action/_requested_punch`, `overtime_policy`(+`_version`, `_rate_row`), `overtime_record`, `overtime_action`, `leave_day_projection` | `company_id` | `attendance/repository.py`; mobile punch with idempotency; Celery daily calc per company | `punch`,`attendance_day`: RLS+test (`test_b12_cross_tenant_and_scope.py`, `test_b13_attendance_tenant_fk.py`); rest RLS. `attendance_day` composite tenant FK only after `20261027092000` |
| Face attendance | `employee_face_profile`, `face_embedding`, `face_enrollment_attempt`, `face_enrollment_window`, `face_external_deletion`, `face_liveness_session`, `face_verification_attempt` | `company_id` | `attendance/face_service.py`, external Face++ provider (data leaves tenant boundary to a third party – legal review) | RLS; biometric data – highest sensitivity |
| Leave | `leave_type`, `leave_policy`(+`_version`), `leave_combination_rule`, `leave_year_setting`, `statutory_leave_minimum`, `leave_application`, `leave_application_day`, `leave_application_action`, `leave_ledger`, `leave_year_end_run` | `company_id` | `leave/repository.py`; sweeps per company | `leave_application`: RLS+test (`test_leave_application.py`, `test_adjustment_scope.py`); rest RLS |
| Payroll | `salary_component`, `salary_structure`(+`_version`,`_line`), `payroll_setting`, `statutory_rate`, `pay_run`, `pay_run_employee`, `pay_run_line`, `pay_run_arrear`, `pay_adjustment` | `company_id` | `payroll/repository.py`, finalise under advisory locks | RLS; payroll integration tests exist under `tests/integration/modules/payroll` (cross-tenant case U) |
| Cross-cutting | `audit_log`, `idempotency_key`, `encryption_keys`, `platform_admin`, `platform_session`, `platform_audit_log` | `audit_log`,`idempotency_key.company_id`; keys global | audit append-only (SELECT/INSERT grants) | `audit_log`: RLS+test (`test_rls_runtime_role.py:362`); `encryption_keys`: global **but holds wrapped DEKs, app role has full DML** (F-17, P2: restrict to SELECT/INSERT) |
| Unique constraints | `employee (company_id, employee_code)`, `attendance_day (company_id, employee_id, attendance_date)`, `pay_run (company_id, legal_entity_id, period_month)`, `idempotency_key (company_id, operation, idempotency_key)` | include `company_id` | – | OK. Global uniques (`user.email`, `user.phone`, token hashes) are intentional |

## 3. RLS defence-in-depth assessment

RLS is **already enabled** and is the primary backstop (not an addition). Recommendations (none applied):

* Keep GUC transaction-local (`is_local=true`) – correct with pooled connections: the setting dies at commit/rollback so a recycled connection never carries a tenant. Do **not** introduce PgBouncer in *statement* mode; *transaction* mode is compatible because the GUC is set inside each transaction.
* Add a `after_begin` SQLAlchemy event that re-applies the GUC from the ContextVar at the start of every transaction to remove caveat 1 structurally.
* Add composite `(id, company_id)` unique keys + composite FKs for the high-value chains (employee → attendance/leave/payroll rows) – F-03.
* Add a catalog test: every table with `company_id` must have RLS FORCE + policy, or appear on a reviewed allow-list (the 18 non-RLS tables). This fails the build if a future migration forgets RLS.
* Move `encryption_keys` writes to a dedicated narrow path / role.
* Platform cross-tenant reads: prefer an explicit `platform_reader` role with audited SECURITY DEFINER functions over ad-hoc GUC switching. P3.
