# HRMS Database Design Audit

Source: `apps/api/src/hrms/**/models.py`, `core/db/models/*`, `apps/api/alembic/versions/*` (127 revisions). Live DB **not** inspected (see Executive Summary §1). Everything below is *static*.

## 1. Engine & access layer
PostgreSQL 16 (compose image `postgres:16-alpine`), SQLAlchemy 2 async + `asyncpg`, `psycopg` for migrations, Alembic. Tenancy = **shared database, shared tables, `company_id` + PostgreSQL RLS** via transaction-local GUC `app.company_id` (`core/db/session.py:53-60`). Runtime role `hrms_app` (NOSUPERUSER/NOBYPASSRLS asserted in CI); schema owner `hrms`.

## 2. Schema inventory (116 ORM tables, grouped)

| Domain | Tables | Tenant key | RLS (per migrations) |
|---|---|---|---|
| Identity/RBAC | company, user, user_company, role, permission, role_permission, user_role, session, refresh_token, password_reset_token, email_verification_token | `company` is the tenant root; `user` is global (one login across companies); `user_company` is the membership | `user_company`, `session`, `refresh_token`, `role`, `user_role`: **no RLS found** (F-06). Login lookups need cross-tenant reads (migration `20260828090000_login_lookup_function`, `core/db/models/identity.py:192`) |
| Organisation | legal_entity, branch, department, grade, designation, shift, shift_version, shift_break, shift_duty_block, holiday_calendar, holiday, weekly_off_*, work_calendar*, calendar_exception, policy_assignment, plan, plan_feature, subscription, company_feature_flag, company_setup_progress | `company_id` | RLS on all except `holiday_calendar` (candidate, F-06). `plan`/`plan_feature` are global catalogues |
| Employee | employee, employment, employee_assignment, employee_compensation, employee_statutory, employee_bank, employee_experience/education/dependent/document, number_series | `company_id` | RLS, FORCE |
| Attendance | punch, attendance_day, attendance_break, regularization (4), overtime (5), attendance_period (3), attendance/overtime/regularization policy (+versions/bands), shift_roster, leave_day_projection, face_* (7), employee_workplace_authorization, geofence_attempt | `company_id` | RLS, FORCE |
| Leave | leave_type, leave_policy(+version), leave_ledger, leave_application(+day,+action), leave_combination_rule, leave_year_setting, statutory_leave_minimum, leave_year_end_run | `company_id` (`statutory_leave_minimum` may be global — unverified) | RLS, FORCE |
| Payroll | salary_component, salary_structure(+version,+line), employee_salary, payroll_setting, pay_run, pay_run_employee, pay_run_line, statutory_rate, pay_adjustment, pay_run_arrear | `company_id` | RLS via looped migrations (`20261004105000`, `...106000`, `...109000`) — false positive in naive regex; **verify live** |
| Onboarding / import | onboarding_case/token/document/section_review/message, employee_import_batch/row_error, account_invite | `company_id` | RLS; `onboarding_token` deliberately `NO FORCE` (`20260906090000`); `account_invite` no RLS |
| Platform / ops | platform_admin, platform_session, platform_audit_log, email_log, email_outbox, audit_log, idempotency_key, encryption_keys | mixed | `audit_log` RLS+append-only; `email_log`, `email_outbox`, `platform_*`: no RLS (platform-global by design, F-06) |

Per-table detail (PK type, nullability, defaults, FKs, indexes) is intentionally **not** reproduced for all 116 tables here; the authoritative source is the migrations. Spot-checked in depth: punch, attendance_day, leave_ledger, pay_run*, employee_salary, audit_log.

## 3. What the schema does well (confirmed in migrations)
* **Money** — integer minor units (`*_minor BIGINT`) throughout payroll (`payroll/models.py:117-122, 204-209, 266-271, 400`); `Numeric` used only for percentages/day-fractions. No `Float` in payroll.
* **Overlap protection** — 16 `EXCLUDE USING gist` constraints (employment, bank, statutory, salary `employee_salary_no_overlap`, statutory_rate, policy_assignment, attendance_period…).
* **Uniqueness** — `pay_run_entity_month_uq (company_id, legal_entity_id, period_month)`, `pay_run_employee_uq`, `attendance_day UNIQUE(company_id, employee_id, attendance_date)`, `punch_company_idempotency_key_idx` (partial), `uq_leave_ledger_cycle_entry` / `comp_off_credit` (idempotent accruals), `leave_application_day UNIQUE(application, date)`.
* **Immutability** — trigger `payroll_finalised_immutable` (`20261013090000`) blocks edits/deletes of FINALISED/PAID runs and children; `REVOKE UPDATE,DELETE,TRUNCATE ... FROM hrms_app` on `leave_ledger`, `leave_application_action`, `audit_log` (`20261009090000`).
* **Ledger model** — leave balance is an append-only ledger (`amount <> 0` check), not a mutable counter.
* **PII** — field-level AES-256-GCM with key registry (`encryption_keys`, `core/crypto/*`).

## 4. Design concerns
| ID | Sev | Conf. | Concern |
|---|---|---|---|
| F-03 | P1 | confirmed (schema) | Only 4 composite tenant FKs (`attendance_day→employee`, 3 in geofencing). The other ≥10 single-column FKs to `employee(id)` and all FKs to parents (shift, structure, policy versions, leave_type…) can reference another company's row. RLS `USING` checks the row's own `company_id`, not the parent's. Exploitability depends on each endpoint validating referenced IDs (not exhaustively verified). |
| F-06 | P2 | needs live check | ~10 tenant-keyed tables have no RLS in migrations: `account_invite, email_log, email_outbox, holiday_calendar, refresh_token, role, session, user_company, user_role` (+ `platform_audit_log`, platform-global). Several are explained (login needs cross-tenant lookup). `holiday_calendar` has no stated reason. |
| F-10 | P2 | confirmed | Append-only enforced for 3 tables only; `attendance_regularization_action`, `overtime_action`, `attendance_period_action`, `email_log`, `geofence_attempt` are mutable by the runtime role. |
| F-11 | P2 | confirmed | ORM models declare **no** constraints/indexes (0 `UniqueConstraint/CheckConstraint/Index` objects; only `idempotency.py` has `__table_args__`). The DB truth lives only in raw SQL, so `alembic revision --autogenerate`/`alembic check` cannot detect drift, and models mislead readers. |
| — | P3 | confirmed | Mixed naming/versioning: `version` int columns for optimistic locking on some tables, `*_version` tables on others. Acceptable but unevenly documented. |
| — | P3 | needs validation | Two designs of time: `punch` has instant+local fields; `app_timezone_default="Asia/Kolkata"` is a **global** default. Per-company timezone behaviour not verified. |

## 5. Historical data retention
`terminated_company_retention_days=90` (purge is manual); `geofence_attempt_retention_days=90`; face data cleanup tasks; leave/payroll/audit are append-only/immutable. Hard-delete paths exist for employee/onboarding documents (`employee/service.py:3640-3675`) — acceptable if policy allows, but they remove HR records outright (F-12 for ordering).

## 6. Sensitive-data classification (observed)
High: bank, statutory IDs, compensation, salary/payslips, face embeddings/images, documents (S3). Medium: personal contact/address, dependents. Credentials: `user.password_hash`, hashed refresh/reset/verify/invite tokens. Logging: `hide_parameters=True` on the engine (`session.py:36`); central redaction module exists (`core/observability/redaction.py`).

## 7. Schema improvements (recommendations only)
1. Add `UNIQUE (company_id, id)` + composite `FOREIGN KEY (company_id, x_id)` on high-value edges first: `employee_salary→employee/salary_structure_version`, `pay_run_employee→employee`, `leave_application→employee/leave_type`, `leave_ledger→employee/leave_type`, `punch→employee`. Use `NOT VALID` then `VALIDATE CONSTRAINT` to avoid long locks.
2. Mirror constraints/indexes into ORM `__table_args__` (or generate a drift test) so autogenerate is trustworthy.
3. Extend append-only `REVOKE` to the other `*_action` tables.
4. Decide RLS posture for `holiday_calendar`, `account_invite`, `role` (company-scoped rows) and document the intentional exceptions in one place.
5. Document the tenant-timezone source of truth (company vs global) for attendance boundaries.
