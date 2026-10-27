# HRMS Database Schema Audit

Evidence tags as defined in `HRMS_ARCHITECTURE_INVENTORY.md` ([REPO], [DEV-DB] = empty dev DB at revision `20261022090000`, [UNVERIFIED]). `email_outbox` (revision `20261027090000`) is in the repo but not in the dev DB, so the table inventory below has 112 tables, the ORM metadata 113.

## 1. Headline results

| Area | Result |
|---|---|
| Tables | 113 in ORM metadata / 112 in dev DB; 101 carry `company_id` |
| Constraints [DEV-DB] | 113 PK, 298 FK, 29 UNIQUE, 153 CHECK, 14 EXCLUDE (gist) |
| FK delete rules [DEV-DB] | 179 RESTRICT, 89 SET NULL, 23 CASCADE, 7 NO ACTION. CASCADE is limited to child/line tables (policy version bands, break rows, pay-run children, period summaries) plus `idempotency_key→company` and two token/session tables |
| Money | All payroll money is `BIGINT *_minor` (integer paise). No `float/real/money` column exists anywhere [DEV-DB]. Day quantities are `NUMERIC(6,2)` |
| Timestamps | No `timestamp without time zone` column [DEV-DB]; punches are `timestamptz` |
| Effective dating | `EXCLUDE USING gist` no-overlap on `employment`, `employee_compensation` (and others in 003 SQL) [DEV-DB] |
| Tenant FK integrity | **0 composite `(id, company_id)` foreign keys** [DEV-DB] – see F-03 |
| Model ↔ migration drift | Columns/nullability match; indexes, FKs and 20 unique constraints exist only in raw SQL, not on ORM models – see F-10 |

## 2. Findings (schema)

Classification: **C** = confirmed defect/gap, **R** = potential risk, **U** = unverified assumption.

| ID | Pri | Type | Finding | Evidence |
|---|---|---|---|---|
| F-03 | P1 | C | Every tenant FK is a single-column FK to `x.id`. Nothing at the database level prevents e.g. an `attendance_day` row of company A pointing to an employee of company B; protection is RLS (on `company_id` of the row *being written*) and service code. RLS `USING` also acts as `WITH CHECK`, so the row's own `company_id` must equal the GUC, but the referenced parent is only checked for existence, and FK checks bypass RLS. A service bug that passes a foreign UUID would be accepted. Revision `20261027092000_attendance_day_tenant_fk` starts to fix this for one table (not applied in dev) | 0 composite FKs [DEV-DB]; `alembic/versions/20261027092000_attendance_day_tenant_fk.py` |
| F-04 | P1 | C | Tenant-bearing tables without RLS: `refresh_token`, `session`, `account_invite`, `onboarding_token`, `email_log`, `platform_audit_log` (plus `email_outbox` in repo). `company_id` is nullable on `session`, `refresh_token`, `email_log`, `email_outbox`, `platform_audit_log`. They are reached by unguessable hashed token or by platform-admin code, which is a legitimate design, but each needs an explicit test that a tenant-scoped request cannot enumerate them | RLS flags [DEV-DB]; `tests/security` lacks per-table coverage for these (U) |
| F-08 | P2 | C | `punch` (raw attendance evidence) grants `UPDATE, DELETE` to `hrms_app` and has no immutability trigger; duplicate prevention is only the optional `(company_id, idempotency_key)` partial unique index. Two identical punches without a client key are both stored | `punch_company_idempotency_key_idx`; grants [DEV-DB] |
| F-09 | P3 | R | `pay_run*` tables grant UPDATE/DELETE but are protected by `payroll_guard_*` BEFORE triggers (immutable once FINALISED, migration `20261013090000`). Good. Trigger bypass is gated by `payroll_is_maintenance_role`; confirm which role it names and that `hrms_app` is excluded | triggers [DEV-DB] |
| F-11 | P2 | C | Dev DB is 4 revisions behind repo and the working tree has uncommitted migrations. Production must be built from a tagged commit with `alembic heads` == 1 | `alembic_version`=`20261022090000` |
| F-12 | P3 | R | `role.company_id` is nullable but its RLS policy is `company_id = GUC`; any NULL (system) roles would be invisible to tenants. Confirm no system roles rely on NULL | policy [DEV-DB] |
| F-13 | P2 | R | Global `user.email` / `user.phone` are UNIQUE across all tenants (identity table has no `company_id`; membership in `user_company`). This is a deliberate single-identity model; it means one email can belong to only one human account and a user's existence is detectable across tenants via signup/invite errors. Confirm error messages do not reveal cross-tenant existence | `user_email_key`, `user_phone_key` [DEV-DB] |
| F-14 | P3 | U | Right-to-erasure / employee purge: 179 RESTRICT FKs and `deleted_at` soft-delete columns mean employee/company hard-deletes are blocked once payroll/attendance exist (good for retention). No documented anonymisation path was found | `employee*` tables |

## 3. Relationship-integrity review

| Relationship | Verdict |
|---|---|
| company → branch/department/designation/grade/legal_entity | `company_id` NOT NULL, FK RESTRICT, RLS. Deleting a company with data is impossible (RESTRICT) – retention-safe |
| user ↔ employee | `employee` links to `user` via nullable FK; membership in `user_company`; access end handled by `end_company_access` (revokes sessions) rather than deletes |
| attendance_day → employee | FK RESTRICT; `UNIQUE (company_id, employee_id, attendance_date)` `attendance_day_unique`; children `attendance_break` CASCADE from day (acceptable – derived data) |
| punch → employee | FK RESTRICT; no CASCADE; raw payload JSONB retained |
| shift/policy versions | Versioned tables (`*_version`) with CASCADE only to their band/row children; partial unique "one open draft" index per policy |
| leave_application → leave_ledger | Ledger is append-only for the app role (`INSERT, SELECT` only) with partial unique indexes for accrual / carry-forward / comp-off credit / year-end encashment idempotency [DEV-DB] |
| pay_run → pay_run_employee → pay_run_line | CASCADE chain, but guarded by immutability triggers once finalised; `UNIQUE (company_id, legal_entity_id, period_month)` |
| payslip | Stored as `pay_run_employee.payslip_details JSONB` + `snapshot JSONB`: payslips render from the frozen run, not from current salary. No standalone payslip table (checked: none exists) |
| audit_log | `hrms_app` has `SELECT, INSERT` only – append-only by grant; actor stored as id columns; `platform_audit_log` additionally has a no-update/delete trigger |
| subscription / plan | `subscription` (RLS) → `plan` (global); `plan_feature`, `company_feature_flag` |
| orphan risk | 53 SET NULL FKs (mostly policy-version pointers on `attendance_day` and `*_by` actor columns). Setting actor to NULL on user deletion loses attribution; since `user` rows are not hard-deleted by the app this is acceptable [R] |

## 4. Attendance & leave integrity (D)

* **Representation**: raw `punch` (IN/OUT, `timestamptz`, source enum, optional idempotency key) → derived `attendance_day` per (company, employee, date) → `attendance_period` close/lock with frozen `attendance_period_summary`. Business dates are derived from the company IANA timezone, not the host (`TZ=UTC` pinned in Dockerfile and CI; DEC-TZ-04) [REPO].
* **Overnight shifts**: handled in the calculation engine (punch pad ±2h; daily job at 09:30 with trailing 3 days) `attendance/tasks.py`, `core/celery_app.py:105-108` [REPO]; [UNVERIFIED] by data.
* **Duplicates / retries**: idempotency via `core/idempotency.py` + `idempotency_key` table `UNIQUE(company_id, operation, idempotency_key)`; mobile punch key partial unique index. Gap F-08 for key-less clients.
* **Concurrency**: advisory locks with a documented acyclic order `leave-dates → payroll-finalise → attendance-period-close → leave balance`, bounded by `attendance_lock_timeout_ms` (`core/db/locks.py:1-60`). Strong design; needs the concurrent tests in the testing plan to be automated (T-04, T-05).
* **Leave balances**: ledger-based (balance = sum of ledger), no mutable balance column to lose updates on; `leave_reserve_balance` and negative-floor migrations exist. Comp-off credit/expiry sweeps are idempotent by partial unique index.
* **Corrections**: `attendance_regularization_request` + `_action` history tables; `leave_application_action`, `overtime_action`; append-only history migration `20261009090000`.

## 5. Payroll & financial integrity (E)

| Check | Result |
|---|---|
| Precision | BIGINT minor units; `variance_percent` NUMERIC; no float |
| Currency | `employee_compensation.currency CHAR(3)`; `pay_run` has no currency column – INR implicit [R, F-15 P3] |
| Period uniqueness | `pay_run_entity_month_uq` |
| Effective dating | gist EXCLUDE on compensation; `employee_salary` / `salary_structure_version` versioned |
| Approval/finalisation | `status` workflow with timestamps and actor ids per stage (inputs_locked, computed, approved, finalised, paid) |
| Historical stability | `pay_run_employee.snapshot` JSONB + `pay_run_line.trace` freeze inputs; finalised rows immutable by trigger. Changing current salary cannot rewrite a finalised run |
| Corrections | `pay_adjustment` (immutable guard) and `pay_run_arrear`, serialised by `pay-adjustment` advisory lock |
| Idempotency | Idempotency-key table + `payroll-finalise` per-legal-entity lock |
| Residual risks | Draft runs are mutable by design; recompute of a draft after approval must be blocked by status checks [U – covered by T-06]; JSONB snapshots are not schema-validated at DB level |

## 6. Privacy & security of data (H)

* Passwords: `argon2.PasswordHasher` (`core/auth/passwords.py:1-6`); reset/verify/invite tokens stored as hashes (`token_hash` UNIQUE) [REPO/DEV-DB].
* PII: `*_enc` columns (PAN, Aadhaar, bank account, dependent Aadhaar) AES-GCM; **loss of `PII_MASTER_KEY` = permanent loss** (documented). Key must be escrowed off-VPS.
* Logging: `hide_parameters=True` on the engine so bound values do not appear in DBAPI errors (`core/db/session.py`); redaction module in `core/observability/redaction.py`.
* Salary figures (`*_minor`) and face embeddings (`face_embedding`) are *not* field-encrypted – protected by RLS, role grants, TLS and disk encryption only. Decide whether that is acceptable (F-16 P2, decision).
* Least privilege: `hrms_app` NOSUPERUSER NOBYPASSRLS, DML only, no DDL; CI asserts this. **But** the API container receives the schema-owner credential – F-01.
* Encryption in transit DB: asyncpg to `postgres:5432` over the private docker network; no TLS (acceptable on an internal bridge, document it). Backups: unencrypted (F-02).

### F-01 (P1, confirmed) Migration/owner credential is available to the running API
`alembic/env.py` states the app process must never hold `MIGRATIONS_DATABASE_URL`, and `Settings` has no field for it. But `docker-compose.prod.yml` gives `api`, `worker`, `beat` and `migrate` the **same** `env_file: apps/api/env/.env.production`, and `env/.env.production.example:33` places `MIGRATIONS_DATABASE_URL` in that file. Every container therefore has the schema-owner credential in its OS environment (readable via any RCE, `/proc/self/environ`, or a debug dump). The owner/superuser role bypasses RLS, so a compromise of the API defeats the tenant-isolation design. **Fix**: separate `env/.env.migrate` used only by the `migrate` service. **Downtime**: none. **Effort**: 0.5 d. **Test**: `docker compose exec api env | grep -c MIGRATIONS` → 0.

## 7. Table inventory

Columns: RLS = row-level security (`FORCE` = enabled and forced), PK, number of columns, FKs other than `company_id`, counts of UNIQUE/CHECK/EXCLUDE constraints, number of indexes, and sensitive-looking columns (heuristic on names; review manually). Every table with `company_id` has `company_id` NOT NULL except those listed in F-04. Purpose is evident from the table name; module ownership is in `HRMS_TENANT_ISOLATION_MATRIX.md`.

Orphan/unused scan: no table without an ORM model; the 18 non-RLS tables are all intentional (global identity/catalog/platform/token). Redundant-index candidates are in the performance audit.

| Table | RLS | PK | Cols | Non-tenant FKs (target; CASC=cascade) | UQ/CHK/EXCL | Idx | Sensitive columns (name-pattern heuristic) |
|---|---|---|---|---|---|---|---|
| `account_invite` | **off** | id | 12 | employee_id→employee, created_by_user_id→user | 1/0/0 | 5 | email, token_hash |
| `attendance_break` | FORCE | id | 11 | attendance_day_id→attendance_day(CASC), shift_break_id→shift_break(NULL) | 0/0/0 | 3 | - |
| `attendance_day` | FORCE | id | 66 | work_on_leave_resolved_by→user(NULL), employee_id→employee, shift_id→shift(NULL), shift_version_id→shift_version(NULL), work_calendar_id→work_calendar(NULL), attendance_policy_version_id→attendance_policy_version(NULL), overtime_p | 1/2/0 | 6 | - |
| `attendance_period` | FORCE | id | 19 | legal_entity_id→legal_entity, opened_by_user_id→user(NULL), closed_by_user_id→user(NULL), reopened_by_user_id→user(NULL) | 0/3/1 | 5 | - |
| `attendance_period_action` | FORCE | id | 8 | attendance_period_id→attendance_period(CASC), actor_user_id→user(NULL) | 0/1/0 | 2 | - |
| `attendance_period_summary` | FORCE | id | 27 | attendance_period_id→attendance_period(CASC), employee_id→employee | 1/0/0 | 3 | - |
| `attendance_policy` | FORCE | id | 9 | - | 0/0/0 | 3 | - |
| `attendance_policy_early_departure_band` | FORCE | id | 10 | policy_version_id→attendance_policy_version(CASC) | 0/2/0 | 3 | - |
| `attendance_policy_hour_band` | FORCE | id | 9 | policy_version_id→attendance_policy_version(CASC) | 0/2/0 | 3 | - |
| `attendance_policy_late_band` | FORCE | id | 10 | policy_version_id→attendance_policy_version(CASC) | 0/2/0 | 3 | - |
| `attendance_policy_version` | FORCE | id | 41 | policy_id→attendance_policy, published_by→user(NULL) | 0/3/1 | 5 | - |
| `attendance_regularization_action` | FORCE | id | 10 | request_id→attendance_regularization_request(CASC), actor_user_id→user(NULL), actor_employee_id→employee(NULL) | 0/2/0 | 2 | - |
| `attendance_regularization_request` | FORCE | id | 26 | submitted_by_user_id→user(NULL), reviewed_by_user_id→user(NULL), cancelled_by_user_id→user(NULL), employee_id→employee, attendance_day_id→attendance_day(NULL), requested_shift_id→shift(NULL), regularization_policy_version_id→regul | 0/4/0 | 5 | - |
| `attendance_regularization_requested_punch` | FORCE | id | 8 | request_id→attendance_regularization_request(CASC) | 0/1/0 | 2 | - |
| `audit_log` | FORCE | id | 12 | actor_user_id→user | 0/0/0 | 2 | - |
| `branch` | FORCE | id | 19 | legal_entity_id→legal_entity | 0/0/0 | 4 | address_line1, address_line2 |
| `calendar_exception` | FORCE | id | 13 | work_calendar_id→work_calendar | 0/1/0 | 4 | - |
| `company` | **off** | id | 42 | created_by→user(NULL), updated_by→user(NULL), status_changed_by_platform_admin_id→platform_admin(NULL) | 0/4/0 | 5 | contact_email, contact_phone, address_line1, address_line2, address_city, address_state |
| `company_feature_flag` | FORCE | id | 11 | created_by→user(NULL), updated_by→user(NULL) | 1/0/0 | 3 | - |
| `company_setup_progress` | FORCE | id | 10 | - | 1/1/0 | 2 | - |
| `department` | FORCE | id | 12 | branch_id→branch(NULL), parent_id→department(NULL), head_employee_id→employee(NULL) | 0/0/0 | 5 | - |
| `designation` | FORCE | id | 12 | department_id→department(NULL), next_designation_id→designation(NULL), grade_id→grade(NULL) | 0/0/0 | 5 | - |
| `email_log` | **off** | id | 17 | - | 0/1/0 | 4 | - |
| `email_verification_token` | **off** | id | 6 | user_id→user(CASC) | 1/0/0 | 3 | token_hash |
| `employee` | FORCE | id | 43 | user_id→user(NULL) | 0/1/0 | 5 | date_of_birth, personal_email, photo_url, pan_number_enc, aadhaar_number_enc, present_address_line1 |
| `employee_assignment` | FORCE | id | 20 | employee_id→employee, department_id→department(NULL), designation_id→designation(NULL), grade_id→grade(NULL), branch_id→branch(NULL), reporting_manager_id→employee(NULL), dotted_line_manager_id→employee(NULL), shift_id→shift(NULL) | 0/0/1 | 6 | - |
| `employee_bank` | FORCE | id | 18 | employee_id→employee | 0/0/1 | 4 | account_number_enc, bank_name |
| `employee_compensation` | FORCE | id | 13 | employee_id→employee | 0/1/1 | 4 | annual_ctc_minor |
| `employee_dependent` | FORCE | id | 21 | employee_id→employee | 0/0/0 | 3 | date_of_birth, is_minor, aadhaar_number_enc, is_pf_nominee, pf_nominee_share_percentage, is_gratuity_nominee |
| `employee_document` | FORCE | id | 16 | employee_id→employee, verified_by_user_id→user | 0/0/0 | 3 | - |
| `employee_education` | FORCE | id | 11 | employee_id→employee | 0/0/0 | 3 | - |
| `employee_experience` | FORCE | id | 18 | employee_id→employee | 0/0/0 | 3 | last_ctc_minor |
| `employee_face_profile` | FORCE | id | 19 | employee_id→employee, enrolled_by_user_id→user(NULL), revoked_by_user_id→user(NULL), enrollment_window_id→face_enrollment_window(NULL), reviewed_by_user_id→user(NULL) | 1/5/0 | 3 | reference_photo_count, review_photo_key |
| `employee_import_batch` | FORCE | id | 15 | created_by→user(NULL) | 0/0/0 | 3 | - |
| `employee_import_row_error` | FORCE | id | 8 | batch_id→employee_import_batch(CASC) | 0/0/0 | 2 | - |
| `employee_salary` | FORCE | id | 12 | employee_id→employee, salary_structure_id→salary_structure | 0/3/1 | 3 | salary_structure_id, daily_rate_minor |
| `employee_statutory` | FORCE | id | 22 | employee_id→employee | 0/0/1 | 4 | - |
| `employment` | FORCE | id | 14 | employee_id→employee, legal_entity_id→legal_entity, previous_employment_id→employment(NULL) | 0/4/1 | 5 | - |
| `encryption_keys` | **off** | id | 10 | - | 1/1/0 | 4 | - |
| `face_embedding` | FORCE | id | 8 | employee_id→employee | 1/1/0 | 3 | embedding_enc |
| `face_enrollment_attempt` | FORCE | id | 8 | employee_id→employee, actor_user_id→user(NULL) | 0/2/0 | 4 | - |
| `face_enrollment_window` | FORCE | id | 14 | employee_id→employee, opened_by_user_id→user(NULL), cancelled_by_user_id→user(NULL) | 0/4/0 | 3 | - |
| `face_external_deletion` | FORCE | id | 13 | - | 1/3/0 | 4 | - |
| `face_liveness_session` | FORCE | id | 12 | employee_id→employee, issued_by_user_id→user(NULL) | 0/4/0 | 6 | - |
| `face_verification_attempt` | FORCE | id | 12 | employee_id→employee, punch_id→punch, liveness_session_id→face_liveness_session(NULL) | 1/5/0 | 5 | - |
| `grade` | FORCE | id | 15 | - | 0/0/0 | 3 | min_ctc, max_ctc |
| `holiday` | FORCE | id | 16 | calendar_id→holiday_calendar, replaced_holiday_id→holiday | 0/1/0 | 5 | - |
| `holiday_calendar` | FORCE | id | 13 | - | 0/1/0 | 3 | - |
| `idempotency_key` | FORCE | id | 9 | - | 1/0/0 | 2 | - |
| `leave_application` | FORCE | id | 29 | resolved_department_head_id→employee(NULL), submitted_by_user_id→user(NULL), reviewed_by_user_id→user(NULL), cancelled_by_user_id→user(NULL), employee_id→employee, leave_type_id→leave_type, leave_policy_version_id→leave_policy_ver | 0/4/0 | 3 | - |
| `leave_application_action` | FORCE | id | 9 | leave_application_id→leave_application, actor_user_id→user(NULL), actor_employee_id→employee(NULL) | 0/0/0 | 3 | - |
| `leave_application_day` | FORCE | id | 11 | leave_application_id→leave_application | 1/1/0 | 4 | - |
| `leave_combination_rule` | FORCE | id | 9 | leave_type_id_a→leave_type, leave_type_id_b→leave_type, created_by_user_id→user(NULL) | 0/1/0 | 3 | - |
| `leave_day_projection` | FORCE | id | 19 | employee_id→employee, created_by_user_id→user(NULL) | 1/3/0 | 3 | - |
| `leave_ledger` | FORCE | id | 11 | employee_id→employee, leave_type_id→leave_type, created_by_user_id→user(NULL) | 0/2/0 | 6 | - |
| `leave_policy` | FORCE | id | 10 | leave_type_id→leave_type | 0/0/0 | 4 | - |
| `leave_policy_version` | FORCE | id | 40 | policy_id→leave_policy, published_by→user(NULL) | 0/8/1 | 5 | - |
| `leave_type` | FORCE | id | 13 | - | 0/1/0 | 4 | - |
| `leave_year_end_run` | FORCE | id | 5 | employee_id→employee | 1/0/0 | 2 | - |
| `leave_year_setting` | FORCE | id | 8 | - | 0/4/0 | 2 | - |
| `legal_entity` | FORCE | id | 19 | - | 0/0/0 | 3 | registered_address |
| `number_series` | FORCE | id | 11 | - | 0/0/0 | 2 | - |
| `onboarding_case` | FORCE | id | 29 | designation_id→designation, department_id→department, branch_id→branch, legal_entity_id→legal_entity, created_by_user_id→user, employee_id→employee | 0/0/0 | 3 | personal_email, address_info, bank_info, nominee_info |
| `onboarding_document` | FORCE | id | 15 | onboarding_case_id→onboarding_case, verified_by_user_id→user | 0/0/0 | 3 | - |
| `onboarding_section_review` | FORCE | id | 10 | onboarding_case_id→onboarding_case, reviewed_by_user_id→user | 0/0/0 | 3 | - |
| `onboarding_token` | **off** | id | 9 | onboarding_case_id→onboarding_case | 1/0/0 | 4 | token_hash |
| `overtime_action` | FORCE | id | 10 | overtime_record_id→overtime_record(CASC), actor_user_id→user(NULL), actor_employee_id→employee(NULL) | 0/2/0 | 2 | - |
| `overtime_policy` | FORCE | id | 9 | - | 0/0/0 | 3 | - |
| `overtime_policy_rate_row` | FORCE | id | 9 | policy_version_id→overtime_policy_version(CASC) | 1/2/0 | 4 | - |
| `overtime_policy_version` | FORCE | id | 29 | policy_id→overtime_policy, published_by→user(NULL) | 0/4/1 | 5 | - |
| `overtime_record` | FORCE | id | 24 | employee_id→employee, attendance_day_id→attendance_day(CASC), overtime_policy_version_id→overtime_policy_version, resolved_approver_manager_id→employee(NULL), reviewed_by_user_id→user(NULL) | 1/5/0 | 5 | - |
| `password_reset_token` | **off** | id | 6 | user_id→user | 1/0/0 | 3 | token_hash |
| `pay_adjustment` | FORCE | id | 14 | legal_entity_id→legal_entity, employee_id→employee, source_pay_run_id→pay_run, applied_pay_run_id→pay_run, created_by_user_id→user(NULL) | 0/4/0 | 2 | - |
| `pay_run` | FORCE | id | 37 | legal_entity_id→legal_entity, attendance_period_id→attendance_period, previous_pay_run_id→pay_run, created_by_user_id→user(NULL), inputs_locked_by_user_id→user(NULL), computed_by_user_id→user(NULL), approved_by_user_id→user(NULL), | 1/3/0 | 3 | gross_minor, deductions_minor, employer_contributions_minor, net_minor |
| `pay_run_arrear` | FORCE | id | 12 | pay_run_id→pay_run(CASC), employee_id→employee, source_pay_run_id→pay_run | 0/1/0 | 4 | amount_minor |
| `pay_run_employee` | FORCE | id | 29 | pay_run_id→pay_run(CASC), employee_id→employee, variance_acknowledged_by_user_id→user(NULL) | 1/0/0 | 3 | gross_minor, deductions_minor, employer_contributions_minor, net_before_rounding_minor, rounding_minor, net_minor |
| `pay_run_line` | FORCE | id | 13 | pay_run_id→pay_run(CASC), pay_run_employee_id→pay_run_employee(CASC), employee_id→employee | 1/1/0 | 3 | full_monthly_minor, amount_minor |
| `payroll_setting` | FORCE | company_id | 5 | - | 0/1/0 | 1 | - |
| `permission` | **off** | id | 4 | - | 0/0/0 | 2 | - |
| `plan` | **off** | id | 8 | - | 1/0/0 | 2 | - |
| `plan_feature` | **off** | id | 7 | plan_id→plan | 1/0/0 | 3 | - |
| `platform_admin` | **off** | id | 10 | - | 0/2/0 | 2 | password_hash |
| `platform_audit_log` | **off** | id | 13 | - | 0/0/0 | 3 | - |
| `platform_session` | **off** | id | 7 | platform_admin_id→platform_admin(CASC) | 0/0/0 | 2 | - |
| `policy_assignment` | FORCE | id | 16 | leave_type_id→leave_type | 0/5/1 | 5 | - |
| `punch` | FORCE | id | 11 | employee_id→employee, recorded_by_user_id→user(NULL) | 0/2/0 | 5 | - |
| `refresh_token` | **off** | id | 10 | user_id→user, session_id→session | 0/0/0 | 3 | token_hash |
| `regularization_policy` | FORCE | id | 9 | - | 0/0/0 | 3 | - |
| `regularization_policy_allowed_type` | FORCE | id | 7 | policy_version_id→regularization_policy_version(CASC) | 1/1/0 | 4 | - |
| `regularization_policy_version` | FORCE | id | 23 | policy_id→regularization_policy, published_by→user(NULL) | 0/3/1 | 5 | - |
| `role` | FORCE | id | 8 | - | 0/0/0 | 3 | - |
| `role_permission` | **off** | role_id,permission_id | 3 | role_id→role, permission_id→permission | 0/1/0 | 1 | - |
| `salary_component` | FORCE | id | 17 | - | 0/1/0 | 2 | - |
| `salary_structure` | FORCE | id | 10 | - | 0/0/0 | 2 | - |
| `salary_structure_line` | FORCE | id | 13 | salary_structure_version_id→salary_structure_version(CASC), salary_component_id→salary_component, base_salary_component_id→salary_component | 1/2/0 | 3 | salary_structure_version_id, salary_component_id, amount_monthly_minor, base_salary_component_id, max_monthly_minor |
| `salary_structure_version` | FORCE | id | 12 | salary_structure_id→salary_structure, published_by_user_id→user(NULL) | 1/3/0 | 4 | salary_structure_id |
| `session` | **off** | id | 8 | user_id→user | 0/0/0 | 2 | ip_address |
| `shift` | FORCE | id | 20 | - | 0/0/0 | 3 | - |
| `shift_break` | FORCE | id | 19 | shift_version_id→shift_version(CASC) | 0/3/0 | 3 | - |
| `shift_duty_block` | FORCE | id | 9 | shift_version_id→shift_version(CASC) | 1/1/0 | 3 | - |
| `shift_roster` | FORCE | id | 15 | employee_id→employee, shift_id→shift(NULL), created_by→user(NULL), updated_by→user(NULL) | 0/2/0 | 5 | - |
| `shift_version` | FORCE | id | 31 | shift_id→shift, weekly_off_pattern_id→weekly_off_pattern(NULL), published_by→user(NULL) | 0/4/1 | 5 | - |
| `statutory_leave_minimum` | FORCE | id | 10 | created_by_user_id→user(NULL) | 0/2/0 | 3 | - |
| `statutory_rate` | FORCE | id | 14 | verified_by_user_id→user(NULL) | 0/3/1 | 3 | - |
| `subscription` | FORCE | id | 13 | plan_id→plan | 0/1/0 | 4 | - |
| `user` | **off** | - | 15 | - | 0/0/0 | 3 | email, phone, password_hash, email_verified_at |
| `user_company` | FORCE | id | 7 | user_id→user | 0/0/0 | 3 | - |
| `user_role` | **off** | id | 3 | user_company_id→user_company, role_id→role | 0/0/0 | 2 | - |
| `weekly_off_pattern` | FORCE | id | 10 | - | 0/1/0 | 3 | - |
| `weekly_off_rule` | FORCE | id | 10 | pattern_id→weekly_off_pattern | 0/4/0 | 3 | - |
| `work_calendar` | FORCE | id | 12 | weekly_off_pattern_id→weekly_off_pattern | 0/0/0 | 3 | - |
| `work_calendar_holiday_calendar` | FORCE | id | 6 | work_calendar_id→work_calendar, holiday_calendar_id→holiday_calendar | 1/0/0 | 4 | - |