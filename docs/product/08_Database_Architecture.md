# Document 08 — Database Architecture

**Version:** 2.0 — migrated from Document 04 v1.0 ("Database Design & Data Dictionary"). **The data
model itself is entirely unchanged** — every table, column, constraint and index in this document
is stack-independent (Document 04 §4, unchanged principle) and was correct before this migration and
remains correct after it. What changed is the tooling: Prisma is replaced by **SQLAlchemy 2.x
(async) + Alembic**, and §1 and §15 (new) cover what that means in practice. If you are looking for
*why* a table is shaped the way it is, nothing in this rewrite affects that reasoning.

**DBMS:** PostgreSQL 16 (unchanged)
**ORM:** SQLAlchemy 2.x, async mode, `asyncpg` driver (was: Prisma)
**Migrations:** Alembic (was: Prisma Migrate)
**Conventions:** `snake_case`; PK `id UUID DEFAULT gen_random_uuid()`; every tenant table has
`company_id UUID NOT NULL`; audit columns `created_at, created_by, updated_at, updated_by,
deleted_at (soft delete where applicable), version INT (optimistic locking)`.
Money = `BIGINT` minor units + `currency CHAR(3)`. Percentages = `NUMERIC(9,4)`.

---

## 1. Global Design Rules

1. **Tenant column on everything.** `company_id` on every business table, indexed as the leading
   column of most composite indexes. RLS policy on every one.
2. **Effective dating.** Any attribute that changes over time lives in a child table with
   `effective_from DATE NOT NULL`, `effective_to DATE` (NULL = current), enforced by:
   ```sql
   EXCLUDE USING gist (
     employee_id WITH =,
     daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
   )
   ```
   This makes overlapping periods **structurally impossible** rather than a code convention.
3. **No hard deletes** of business records. `deleted_at` + `deleted_by` + reason. Physical deletion
   only via the retention job.
4. **Enums as lookup tables**, not PostgreSQL enum types (adding a value to a PG enum requires a
   migration and locks; HRMS statuses change often). Exception: truly fixed technical enums, modelled
   as Python `enum.StrEnum` mapped to a `VARCHAR` column with a `CHECK` constraint, never a native
   PG enum type.
5. **JSONB for tenant-defined custom fields only** (`custom_fields JSONB`), with a GIN index. Never
   for core business attributes — you cannot constrain, join or report on them reliably.
6. **Every FK is indexed.** Missing FK indexes are the #1 cause of slow HRMS delete/update cascades.
7. **Partition high-volume tables**: `punch`, `attendance_day`, `notification_log`, `audit_log`,
   `payslip_line` — by month (`RANGE` on date).
8. **Naming:** table names singular (`employee`, not `employees`); junction tables `a_b`;
   history tables `x_history` only where effective dating does not apply.

### 1.1 SQLAlchemy Model Conventions (new)

Every table has a corresponding SQLAlchemy 2.x declarative model in the owning module's `models.py`
(Document 06 §3.1), using typed `Mapped[...]`/`mapped_column(...)` syntax throughout — not the
legacy `Column(...)` style — so that `mypy` can verify model attribute types the same way it verifies
everything else in the codebase (Document 05 §2):

```python
# modules/leave/models.py
class LeaveLedgerEntry(TenantScopedBase):
    __tablename__ = "leave_ledger"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"), nullable=False, index=True)
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employee.id"), nullable=False)
    leave_type_id: Mapped[UUID] = mapped_column(ForeignKey("leave_type.id"), nullable=False)
    entry_type: Mapped[LeaveLedgerEntryType] = mapped_column(String(30), nullable=False)
    days: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    leave_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # ... see §7.3 for the full column list
```

`TenantScopedBase` (in `core/db/base.py`) is a small declarative mixin providing `company_id`'s
common definition and the audit columns (§1 header) — it does **not** provide query methods (that
would blur the model/repository boundary from Document 07 §1); it is a schema mixin only.

**What SQLAlchemy models deliberately do not express**, because the ORM layer cannot: Row-Level
Security policies, the `EXCLUDE USING gist` effective-dating constraints, and table partitioning.
These are written as raw DDL inside hand-authored Alembic migrations (§14), with a comment in the
corresponding `models.py` pointing at the migration that establishes them — this mirrors exactly how
the original Prisma-based design handled the same limitation (Prisma's schema language could not
express RLS or exclusion constraints either; see the original `prisma/sql/README.md` convention,
carried forward as `alembic/versions/README.md`).

---

## 2. Entity Relationship Overview

```
company ──┬── legal_entity ──┬── branch ──┬── department ──── designation
          │                  │            └── geofence
          │                  └── statutory_registration
          ├── grade / band
          ├── holiday_calendar ── holiday
          ├── subscription ── plan ── plan_module
          └── user_company ── user

employee ─┬── employment ──── (legal_entity)
          ├── employee_assignment*     (dept, designation, grade, manager, branch, shift)
          ├── employee_compensation*   ── compensation_component
          ├── employee_statutory*
          ├── employee_bank*
          ├── employee_document
          ├── employee_dependent / education / experience / skill
          ├── employee_custom_field (JSONB on employee)
          └── employee_event (timeline)
   * = effective-dated

attendance:  shift ── shift_roster ── punch ── attendance_day ── regularisation_request ── ot_request
leave:       leave_type ── leave_policy ── leave_ledger ── leave_application ── comp_off_ledger
payroll:     salary_component ── salary_structure ── statutory_master ──
             pay_run ── pay_run_input_snapshot ── payslip ── payslip_line ── loan ── loan_schedule
recruitment: requisition ── job_opening ── candidate ── application ── interview ──
             interview_feedback ── offer
workflow:    workflow_definition ── workflow_version ── workflow_node ──
             approval_request ── approval_step ── approval_action
```

---

## 3. Core Tenancy & Identity

### 3.1 `company` (tenant root)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| name | VARCHAR(200) NOT NULL | |
| legal_name | VARCHAR(200) | |
| subdomain | VARCHAR(63) UNIQUE | tenant URL |
| industry_code | VARCHAR(40) | drives seed templates |
| country_code | CHAR(2) DEFAULT 'IN' | |
| currency | CHAR(3) DEFAULT 'INR' | |
| timezone | VARCHAR(50) DEFAULT 'Asia/Kolkata' | **business-day boundary source** |
| fy_start_month | SMALLINT DEFAULT 4 | April for India |
| logo_url, theme_json | | white-labelling |
| status | VARCHAR(20) | ACTIVE, SUSPENDED, TRIAL, TERMINATED |
| onboarded_at, trial_ends_at | TIMESTAMPTZ | |
| data_region | VARCHAR(20) | residency |

### 3.2 `user`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| email | CITEXT UNIQUE | |
| mobile | VARCHAR(20) | E.164 |
| password_hash | TEXT | Argon2id (via `argon2-cffi`, Document 10 §2) |
| mfa_secret_enc | TEXT | encrypted |
| mfa_enabled | BOOLEAN | |
| status | VARCHAR(20) | ACTIVE, LOCKED, DISABLED, INVITED |
| failed_attempts, locked_until | | |
| last_login_at, last_login_ip | | |
| must_change_password | BOOLEAN | |

**Note:** `user` has **no** `company_id`. Membership is via `user_company`, which is what makes
multi-company users possible.

### 3.3 `user_company`
`id, user_id FK, company_id FK, employee_id FK NULL, is_default BOOLEAN, status, joined_at`
UNIQUE(user_id, company_id).

### 3.4 `user_role` / `role` / `permission` / `role_permission`
| Table | Key columns |
|---|---|
| `role` | id, company_id NULL (NULL = system role), code, name, description, is_system, is_active |
| `permission` | id, code (e.g. `PAYROLL.RUN.FINALISE`), module, description, is_sensitive |
| `role_permission` | role_id, permission_id, effect (`ALLOW`/`DENY`) |
| `user_role` | user_id, company_id, role_id, data_scope, scope_ref_ids UUID[], valid_from, valid_to |

`data_scope` ∈ `SELF, REPORTEES, REPORTEE_TREE, DEPARTMENT, BRANCH, LEGAL_ENTITY, COMPANY, ALL_COMPANIES`.
`scope_ref_ids` holds the specific branch/department ids when the scope is limited. Full detail in
Document 19.

### 3.5 `session` / `refresh_token`
`id, user_id, company_id, token_family_id, token_hash, device_info, ip, expires_at, revoked_at,
revoked_reason`. Reuse detection compares `token_family_id`. Full auth-flow detail in Document 10.

---

## 4. Organisation Master

| Table | Key Columns |
|---|---|
| `legal_entity` | id, company_id, name, registered_address, pan, tan, cin, gstin, pf_code, esi_code, lwf_reg, signatory_name, signatory_designation, signature_image_url, is_active |
| `branch` | id, company_id, legal_entity_id, code, name, address_line1/2, city, state_code, pincode, timezone, latitude, longitude, geofence_radius_m, holiday_calendar_id, week_off_pattern_id, is_active |
| `department` | id, company_id, parent_id, code, name, head_employee_id, cost_centre_id, is_active |
| `designation` | id, company_id, code, title, grade_id, department_id NULL, jd_document_id, next_designation_id |
| `grade` | id, company_id, code, name, level INT, min_ctc, max_ctc, notice_period_days, probation_days, leave_policy_id, approval_limit |
| `cost_centre` | id, company_id, code, name, gl_code |
| `employment_type` | id, company_id, code, name, is_pf_applicable, is_esi_applicable, is_gratuity_eligible, is_leave_eligible, is_ot_eligible |
| `holiday_calendar` | id, company_id, name, year, state_code NULL |
| `holiday` | id, calendar_id, date, name, type (`FIXED/OPTIONAL/RESTRICTED`), is_paid |
| `week_off_pattern` | id, company_id, name, pattern JSONB (per weekday: FULL/HALF/WORKING; supports alternate Saturdays via week-of-month rules) |
| `number_series` | id, company_id, entity_type, prefix, separator, current_number, padding, reset_rule, last_reset_at |
| `custom_field_definition` | id, company_id, entity_type, field_key, label, data_type, options JSONB, is_required, visible_to_roles UUID[], section, display_order |

**Race-safety note for `number_series`:** allocation uses `UPDATE ... RETURNING` inside the same
transaction with row lock (`SELECT ... FOR UPDATE` semantics via the `UPDATE`), or a dedicated
PostgreSQL sequence per series. Never `SELECT max()+1`. In SQLAlchemy, this is a repository method
using `Update(...).returning(...)` executed against the async session — not the ORM's identity-map
convenience methods, which are not safe for this pattern.

---

## 5. Employee Domain

### 5.1 `employee` (identity — attributes that do not change)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| company_id | UUID FK | |
| employee_code | VARCHAR(30) | UNIQUE(company_id, employee_code) |
| first_name, middle_name, last_name | VARCHAR | |
| display_name | VARCHAR(200) | generated |
| date_of_birth | DATE | |
| gender | VARCHAR(20) | MALE/FEMALE/OTHER/UNDISCLOSED |
| blood_group, marital_status, nationality | | |
| personal_email | CITEXT | |
| personal_mobile | VARCHAR(20) | |
| photo_url | TEXT | |
| pan_number_enc, aadhaar_number_enc | TEXT | **encrypted at column level**, masked in API |
| uan_number | VARCHAR(20) | |
| status | VARCHAR(25) | see Document 17 |
| custom_fields | JSONB | GIN index |
| user_id | UUID FK NULL | may have no login |

### 5.2 `employment`
`id, company_id, employee_id, legal_entity_id, employment_number, employment_type_id,
date_of_joining, date_of_confirmation, probation_end_date, notice_period_days,
date_of_resignation, last_working_day, exit_type, exit_reason_id, is_rehire,
previous_employment_id, status`

Supports rehire and inter-entity transfer as separate employment rows for one employee.

### 5.3 `employee_assignment` (effective-dated) ⭐
`id, company_id, employee_id, effective_from, effective_to, branch_id, department_id,
designation_id, grade_id, reporting_manager_id, dotted_line_manager_id, shift_id,
cost_centre_id, work_location_type (OFFICE/WFH/HYBRID/FIELD), change_reason, change_type
(JOINING/PROMOTION/TRANSFER/MANAGER_CHANGE/SHIFT_CHANGE/CONFIRMATION), reference_document_id`

+ GiST exclusion constraint on (employee_id, daterange).
Index: `(company_id, employee_id, effective_from DESC)`, `(company_id, reporting_manager_id)` for
manager-tree queries, `(company_id, department_id, effective_from)`.

### 5.4 `employee_compensation` (effective-dated) ⭐
`id, company_id, employee_id, effective_from, effective_to, salary_structure_id, annual_ctc,
monthly_gross, revision_type (JOINING/ANNUAL/PROMOTION/CORRECTION/MARKET), revision_reason,
approved_by, approval_request_id, is_arrears_processed`
Child: `employee_compensation_component (compensation_id, salary_component_id, amount,
percentage, formula_override, is_monthly)`

### 5.5 `employee_statutory` (effective-dated)
`employee_id, effective_from, effective_to, is_pf_applicable, pf_number, uan, pf_wage_ceiling_opt_out,
vpf_amount, vpf_percentage, is_esi_applicable, esi_ip_number, pt_state_code, is_lwf_applicable,
tax_regime (OLD/NEW), is_director, is_international_worker`

### 5.6 `employee_bank` (effective-dated)
`employee_id, effective_from, effective_to, account_holder_name, account_number_enc, bank_name,
ifsc, branch_name, payment_mode (BANK/CASH/CHEQUE/UPI), is_primary, verification_status,
penny_drop_reference`

### 5.7 Supporting tables
| Table | Key columns |
|---|---|
| `employee_document` | id, employee_id, document_type_id, document_number, issue_date, expiry_date, file_id, verification_status, verified_by, verified_at, rejection_reason |
| `employee_dependent` | employee_id, relation, name, dob, gender, is_nominee, nominee_percentage, is_insurance_covered, aadhaar_enc |
| `employee_education` | employee_id, level, degree, specialisation, institution, university, year_of_passing, percentage, document_id |
| `employee_experience` | employee_id, company_name, designation, from_date, to_date, last_ctc, reason_for_leaving, document_id |
| `employee_skill` | employee_id, skill_id, proficiency, years_of_experience, is_certified |
| `employee_address` | employee_id, type (PERMANENT/CURRENT), lines, city, state, country, pincode, is_same_as_permanent |
| `employee_emergency_contact` | employee_id, name, relation, phone, address, is_primary |
| `employee_event` | employee_id, event_type, event_date, description, reference_type, reference_id — **the unified timeline feed** |

---

## 6. Attendance Domain

### 6.1 `shift`
`id, company_id, code, name, shift_type (FIXED/FLEXIBLE/SPLIT/ROTATIONAL), start_time, end_time,
is_night_shift, crosses_midnight, total_hours, break_minutes, is_break_paid,
break_windows JSONB, grace_in_minutes, grace_out_minutes, min_hours_full_day,
min_hours_half_day, max_hours_per_day, is_ot_eligible, ot_starts_after_minutes,
week_off_pattern_id, flexible_core_start, flexible_core_end, flexible_window_start,
flexible_window_end, second_block_start, second_block_end (split shift)`

### 6.2 `shift_rotation_pattern` / `shift_roster`
`shift_rotation_pattern`: id, company_id, name, sequence JSONB (ordered list of shift_id + day counts), cycle_days
`shift_roster`: id, company_id, employee_id, roster_date, shift_id, is_week_off, is_holiday,
source (DEFAULT/PATTERN/MANUAL/IMPORT), assigned_by
UNIQUE(employee_id, roster_date). Generated N weeks ahead by a Celery Beat scheduled task (Document 16 §5).

### 6.3 `punch` (partitioned by month) ⭐
| Column | Type | Notes |
|---|---|---|
| id | UUID | |
| company_id | UUID | |
| employee_id | UUID | |
| punch_time | TIMESTAMPTZ NOT NULL | stored UTC |
| punch_date_local | DATE | generated using company timezone; partition key |
| direction | VARCHAR(10) | IN / OUT / AUTO |
| source | VARCHAR(20) | BIOMETRIC/FACE/MOBILE_GPS/WEB/KIOSK/QR/MANUAL/IMPORT/RFID |
| device_id | UUID NULL | |
| latitude, longitude, accuracy_m | NUMERIC | |
| geofence_id, is_within_geofence | | |
| selfie_file_id | UUID NULL | |
| face_match_score | NUMERIC(5,2) NULL | |
| is_mock_location, device_time_skew_seconds | | tamper detection |
| sync_status | VARCHAR(20) | REALTIME / OFFLINE_SYNCED |
| idempotency_key | TEXT | UNIQUE(company_id, idempotency_key) — device_id+emp+timestamp |
| raw_payload | JSONB | for forensics |
| created_by_user_id, manual_reason | | when source = MANUAL |

**Immutable.** Corrections are new punches or regularisations, never edits.

### 6.4 `attendance_day` (derived, partitioned by month) ⭐
| Column | Notes |
|---|---|
| company_id, employee_id, attendance_date | UNIQUE together |
| shift_id, roster_source | shift in effect that day |
| first_in_at, last_out_at | |
| total_worked_minutes, break_minutes, effective_minutes | |
| late_by_minutes, early_out_by_minutes | |
| status | PRESENT/ABSENT/HALF_DAY/WEEKLY_OFF/HOLIDAY/ON_LEAVE/ON_DUTY/WFH/COMP_OFF/NOT_JOINED/EXITED |
| leave_application_id, leave_type_id | when ON_LEAVE |
| paid_day_fraction | NUMERIC(3,2) — 1.00, 0.50, 0.00 (the value payroll consumes) |
| lop_fraction | NUMERIC(3,2) |
| ot_minutes, approved_ot_minutes | |
| is_regularised, regularisation_id | |
| is_manual_override, override_by, override_reason | |
| computed_at, computation_version, computation_trace JSONB | explainability |
| is_locked | payroll lock |

Index: `(company_id, employee_id, attendance_date)`, `(company_id, attendance_date, status)`.

### 6.5 Requests
| Table | Key columns |
|---|---|
| `regularisation_request` | id, company_id, employee_id, attendance_date, request_type (MISSING_PUNCH/WRONG_PUNCH/ON_DUTY/WFH/FULL_DAY), proposed_in_time, proposed_out_time, reason, attachment_id, approval_request_id, status |
| `ot_request` | id, employee_id, ot_date, planned_from, planned_to, actual_minutes, reason, is_pre_approved, approval_request_id, rate_multiplier, payroll_status |
| `attendance_lock` | company_id, legal_entity_id, period_start, period_end, locked_by, locked_at, unlocked_by, unlock_reason |
| `attendance_device` | id, company_id, branch_id, serial_number, model, protocol, api_key_hash, last_heartbeat_at, status, firmware, punch_count_today |
| `geofence` | id, company_id, branch_id NULL, site_name, latitude, longitude, radius_m, is_active |
| `employee_geofence` | employee_id, geofence_id (many-to-many for field staff) |

---

## 7. Leave Domain

### 7.1 `leave_type`
`id, company_id, code, name, is_paid, accrual_method (NONE/MONTHLY/QUARTERLY/YEARLY/ON_JOINING/
ON_REQUEST), accrual_rate NUMERIC, accrual_day, is_prorated_on_joining, is_prorated_on_exit,
max_balance, carry_forward_allowed, carry_forward_max, is_encashable, encashment_basis
(BASIC/BASIC_DA/GROSS), encashment_max_days, lapse_on_year_end, allow_negative_balance,
negative_limit, min_days_per_application, max_days_per_application, min_notice_days,
max_backdated_days, document_required_after_days, counts_holidays (sandwich rule),
counts_week_offs, allow_half_day, allow_hourly, applicable_gender, applicable_marital_status,
applicable_after_months, max_times_in_career (maternity/marriage), display_order, is_active`

### 7.2 `leave_policy` / `leave_policy_assignment`
`leave_policy`: id, company_id, name, description, effective_from
`leave_policy_line`: policy_id, leave_type_id, overrides (JSONB of leave_type fields)
`leave_policy_assignment`: policy_id, applies_to_type (COMPANY/BRANCH/DEPARTMENT/GRADE/EMPLOYMENT_TYPE/EMPLOYEE), applies_to_id, priority

Resolution follows BR-14 (Document 02 §7 — most specific wins).

### 7.3 `leave_ledger` (append-only) ⭐
| Column | Notes |
|---|---|
| id, company_id, employee_id, leave_type_id | |
| entry_type | OPENING/ACCRUAL/APPLICATION/CANCELLATION/ENCASHMENT/LAPSE/CARRY_FORWARD_IN/CARRY_FORWARD_OUT/ADJUSTMENT/COMP_OFF_CREDIT |
| days | NUMERIC(6,2) — signed: + credit, − debit |
| entry_date, effective_period_start, effective_period_end | |
| leave_year | INT — enables per-year balance queries |
| reference_type, reference_id | e.g. leave_application id |
| expires_on | DATE NULL — for comp-off |
| remarks, created_by | |

**No UPDATE, no DELETE.** Balance = `SUM(days)` filtered by leave_year and expiry.
A materialised `leave_balance_snapshot` may be maintained for performance, but it is a **cache**,
rebuildable from the ledger, and never the source of truth.

### 7.4 `leave_application`
`id, company_id, employee_id, leave_type_id, from_date, to_date, from_half (FIRST/SECOND/FULL),
to_half, total_days NUMERIC(5,2), reason, contact_number, address_during_leave,
handover_to_employee_id, attachment_id, status (DRAFT/PENDING/APPROVED/REJECTED/CANCELLED/
WITHDRAWN/PARTIALLY_CANCELLED), approval_request_id, applied_at, approved_at,
cancelled_days NUMERIC, is_lop, payroll_period_id`

### 7.5 `comp_off_ledger`
`employee_id, earned_date, earned_hours, credited_days, expires_on, consumed_days, status`

---

## 8. Payroll Domain

### 8.1 `salary_component`
`id, company_id, code, name, component_type (EARNING/DEDUCTION/EMPLOYER_CONTRIBUTION/
REIMBURSEMENT/INFORMATIONAL), calculation_type (FIXED/PERCENT_OF/FORMULA/SLAB/ATTENDANCE_BASED/
MANUAL), base_component_id, percentage, formula_expression, is_taxable, is_pf_applicable,
is_esi_applicable, is_pt_applicable, is_lop_applicable, is_arrears_applicable,
is_prorated, rounding_rule (NONE/NEAREST/UP/DOWN), rounding_precision, display_order,
show_on_payslip, payslip_label, gl_code, is_statutory, is_system, is_active`

### 8.2 `salary_structure` / `salary_structure_component`
`salary_structure`: id, company_id, name, description, applicable_grade_ids UUID[], is_default, effective_from
`salary_structure_component`: structure_id, salary_component_id, value_type (AMOUNT/PERCENT_OF_CTC/PERCENT_OF_BASIC/FORMULA), value, min_value, max_value, display_order

### 8.3 `statutory_master` (effective-dated, seeded data) ⭐
| Column | Notes |
|---|---|
| id, country_code, state_code NULL, statutory_type | PF / ESI / PT / TDS / LWF / GRATUITY / BONUS / MIN_WAGE |
| effective_from, effective_to | |
| config | JSONB — the full rate/slab structure |
| notification_reference | government circular reference |
| verified_by, verified_at | compliance sign-off trail |

Example `config` for PF:
```json
{ "employee_rate": 12, "employer_rate": 12, "eps_rate": 8.33, "epf_employer_rate": 3.67,
  "wage_ceiling": 1500000, "eps_ceiling": 1500000, "admin_charge_rate": 0.5,
  "admin_charge_min": 50000, "edli_rate": 0.5, "edli_ceiling": 1500000 }
```
*(amounts in paise)*

> ⚠ **All seeded statutory values are indicative and MUST be verified by the client's compliance
> consultant before go-live (Document 02 dependency D5). Rates and ceilings change by notification;
> the effective-dated design exists precisely so that changes are data updates, not releases.**

### 8.4 `pay_run` ⭐
`id, company_id, legal_entity_id, period_start, period_end, pay_date, run_type (REGULAR/OFF_CYCLE/
BONUS/ARREARS/FNF), status (DRAFT/INPUTS_LOCKED/COMPUTING/COMPUTED/UNDER_REVIEW/APPROVED/
FINALISED/PAID/CANCELLED), employee_count, total_gross, total_deductions, total_net,
total_employer_cost, computed_at, computed_by, approved_by, approved_at, finalised_by,
finalised_at, checkpoint JSONB, error_log JSONB`

`checkpoint` records progress through the Celery `chain` pipeline (Document 03 §5) so a crashed run
resumes from the last completed step rather than restarting.

### 8.5 `pay_run_input_snapshot` (immutability guarantee)
`id, pay_run_id, employee_id, snapshot JSONB` — containing the compensation, attendance summary,
leave, LOP days, arrears, loans, statutory profile and statutory_master version ids used.
**Nothing outside this snapshot may influence computation.**

### 8.6 `payslip` / `payslip_line` (partitioned by period)
`payslip`: id, company_id, pay_run_id, employee_id, employee_code_snapshot, name_snapshot,
designation_snapshot, department_snapshot, payable_days, lop_days, present_days,
gross_earnings, gross_deductions, employer_contributions, net_pay, net_pay_words,
ytd_gross, ytd_tax, bank_account_masked, payment_status, payment_reference, pdf_file_id,
published_at, viewed_at

`payslip_line`: id, payslip_id, salary_component_id, component_code, component_label,
component_type, amount, ytd_amount, is_arrears, arrears_month, calculation_trace JSONB,
display_order

### 8.7 Supporting payroll tables
| Table | Key columns |
|---|---|
| `payroll_input` | pay_run_id, employee_id, salary_component_id, amount, input_type (OT/INCENTIVE/BONUS/DEDUCTION/ADJUSTMENT), remarks, source, created_by |
| `arrears` | employee_id, component_id, for_period_start, for_period_end, old_amount, new_amount, difference, pay_run_id, status |
| `loan` | id, employee_id, loan_type, principal, interest_rate, tenure_months, emi_amount, disbursed_on, outstanding, status, approval_request_id |
| `loan_schedule` | loan_id, installment_no, due_period, principal_part, interest_part, emi, status, pay_run_id |
| `tax_declaration` | employee_id, financial_year, section, sub_section, declared_amount, proof_amount, proof_file_id, verification_status, verified_by |
| `tax_computation` | employee_id, financial_year, month, gross_income, exemptions, deductions, taxable_income, tax_liability, tax_paid_ytd, monthly_tds, regime, computation_trace JSONB |
| `bank_advice` | pay_run_id, bank_code, file_format, file_id, total_amount, record_count, generated_at, downloaded_by |
| `statutory_filing` | company_id, legal_entity_id, filing_type, period, due_date, file_id, status, filed_on, acknowledgement_ref |
| `fnf_settlement` | employee_id, employment_id, last_working_day, salary_payable, leave_encashment, gratuity, bonus, notice_recovery, loan_recovery, asset_recovery, other_deductions, net_payable, status, acknowledged_at, paid_on |

---

## 9. Recruitment Domain

| Table | Key columns |
|---|---|
| `requisition` | id, company_id, requested_by, department_id, designation_id, positions, budget_min, budget_max, justification, replacement_for_employee_id, target_date, status, approval_request_id |
| `job_opening` | id, company_id, requisition_id, code, title, description, responsibilities, must_have_skills, good_to_have_skills, min_experience, max_experience, qualification, branch_id, employment_type_id, salary_min, salary_max, show_salary, hiring_manager_id, recruiter_id, panel_member_ids, pipeline_id, positions, filled_count, status, published_at, closes_on, external_slug |
| `candidate` | id, company_id, first_name, last_name, email, mobile, current_company, current_designation, total_experience_months, current_ctc, expected_ctc, notice_period_days, location, resume_file_id, resume_text, parsed_data JSONB, parse_confidence, source, source_detail, referred_by_employee_id, agency_id, consent_given_at, consent_expires_at, is_blacklisted, custom_fields |
| `application` | id, company_id, candidate_id, job_opening_id, current_stage_id, status, applied_at, ai_match_score, ai_match_explanation JSONB, rejection_reason_id, rejected_at, withdrawn_at |
| `pipeline` / `pipeline_stage` | id, company_id, name; stage: pipeline_id, name, order, stage_type, is_terminal, sla_days, required_fields JSONB |
| `application_stage_history` | application_id, from_stage, to_stage, moved_by, moved_at, duration_hours, notes |
| `interview` | id, application_id, round_number, round_name, interview_type (PHONE/VIDEO/IN_PERSON/PANEL), scheduled_start, scheduled_end, timezone, location, meeting_link, status, calendar_event_id, rescheduled_from |
| `interview_panel` | interview_id, employee_id, is_primary, response (ACCEPTED/DECLINED/PENDING) |
| `interview_feedback` | interview_id, employee_id, overall_recommendation, ratings JSONB, strengths, concerns, comments, submitted_at, is_locked |
| `offer` | id, application_id, candidate_id, offer_number, designation_id, department_id, branch_id, grade_id, joining_date, annual_ctc, salary_structure_id, breakup JSONB, probation_days, notice_period_days, status, valid_till, approval_request_id, letter_file_id, sent_at, responded_at, decline_reason, revision_number, previous_offer_id |
| `talent_pool` | candidate_id, tags, added_by, notes, next_review_date |

---

## 10. Workflow Domain

| Table | Key columns |
|---|---|
| `workflow_definition` | id, company_id, entity_type (LEAVE/EXPENSE/OFFER/...), name, is_active, current_version_id |
| `workflow_version` | id, definition_id, version_number, graph JSONB (nodes + edges), published_at, published_by |
| `approval_request` | id, company_id, workflow_version_id, entity_type, entity_id, requester_employee_id, current_node_id, status (PENDING/APPROVED/REJECTED/CANCELLED/INFO_REQUESTED), submitted_at, completed_at, sla_due_at, is_escalated, context JSONB (snapshot of the deciding attributes) |
| `approval_step` | id, request_id, node_id, level, approver_employee_id, approver_role_id, status, assigned_at, acted_at, delegated_from, escalated_from, reminder_count |
| `approval_action` | id, step_id, actor_user_id, action (APPROVE/REJECT/REQUEST_INFO/FORWARD/WITHDRAW), comment, acted_at, ip |
| `delegation` | company_id, from_employee_id, to_employee_id, from_date, to_date, entity_types TEXT[], reason, is_active |

---

## 11. Notification, Audit & Files

| Table | Key columns |
|---|---|
| `notification_event` | code, name, module, default_channels, default_recipients, template_variables JSONB |
| `notification_template` | id, company_id NULL, event_code, channel, language, subject, body, is_active, version |
| `notification_log` (partitioned) | id, company_id, event_code, channel, recipient_user_id, recipient_address_masked, template_id, status (QUEUED/SENT/DELIVERED/FAILED/BOUNCED), provider, provider_message_id, attempts, error, sent_at, delivered_at, read_at |
| `notification_preference` | user_id, company_id, category, channel, is_enabled |
| `audit_log` (partitioned, append-only) | id, company_id, actor_user_id, actor_employee_id, impersonated_by, entity_type, entity_id, action, before JSONB, after JSONB, diff_fields TEXT[], ip, user_agent, request_id, occurred_at |
| `sensitive_access_log` | company_id, actor_user_id, entity_type, entity_id, fields TEXT[], purpose, occurred_at |
| `file` | id, company_id, storage_key, original_name, mime_type, size_bytes, checksum_sha256, virus_scan_status, scanned_at, uploaded_by, entity_type, entity_id, is_encrypted, retention_until |
| `outbox_event` | id, company_id, event_type, payload JSONB, status, attempts, available_at, published_at |
| `job_log` | id, company_id, job_type, params JSONB, status, started_at, finished_at, records_processed, error, triggered_by |
| `import_batch` | id, company_id, entity_type, file_id, total_rows, valid_rows, error_rows, status, error_report_file_id, committed_at, committed_by |

---

## 12. Indexing Plan (the ones that matter)

```sql
-- Tenancy: leading column on virtually every index
CREATE INDEX ON employee (company_id, status) WHERE deleted_at IS NULL;
CREATE INDEX ON employee (company_id, employee_code);
CREATE INDEX ON employee USING gin (custom_fields);

-- Manager tree traversal (used by every scope resolution)
CREATE INDEX ON employee_assignment (company_id, reporting_manager_id, effective_from DESC);

-- Current-record lookup (the hottest query in the system)
CREATE INDEX ON employee_assignment (company_id, employee_id, effective_from DESC)
  INCLUDE (department_id, designation_id, reporting_manager_id, shift_id);
CREATE INDEX ON employee_assignment (company_id, employee_id) WHERE effective_to IS NULL;

-- Attendance
CREATE INDEX ON attendance_day (company_id, attendance_date, status);
CREATE INDEX ON attendance_day (company_id, employee_id, attendance_date DESC);
CREATE UNIQUE INDEX ON punch (company_id, idempotency_key);
CREATE INDEX ON punch (company_id, employee_id, punch_date_local);

-- Leave
CREATE INDEX ON leave_ledger (company_id, employee_id, leave_type_id, leave_year);
CREATE INDEX ON leave_application (company_id, employee_id, from_date, to_date);
CREATE INDEX ON leave_application (company_id, status) WHERE status = 'PENDING';

-- Payroll
CREATE INDEX ON payslip (company_id, pay_run_id);
CREATE INDEX ON payslip (company_id, employee_id, pay_run_id);
CREATE INDEX ON payslip_line (payslip_id, display_order);

-- Approvals (drives every "My Approvals" screen)
CREATE INDEX ON approval_step (company_id, approver_employee_id, status)
  WHERE status = 'PENDING';

-- Audit
CREATE INDEX ON audit_log (company_id, entity_type, entity_id, occurred_at DESC);
CREATE INDEX ON audit_log (company_id, actor_user_id, occurred_at DESC);
```

---

## 13. Data Volume Estimates (500 tenants, 150k employees, year 1)

| Table | Rows/year | Notes |
|---|---|---|
| `punch` | ~150M | 150k × 4/day × 250 days — partitioned monthly |
| `attendance_day` | ~40M | 150k × 260 days |
| `leave_ledger` | ~6M | accruals + applications |
| `payslip` + `payslip_line` | 1.8M + ~30M | 12 runs × 150k, ~17 lines each |
| `audit_log` | ~200M | the largest table; partition + archive to S3 after 12 months |
| `notification_log` | ~100M | partition + 6-month retention in DB |
| `candidate` / `application` | ~2M | |

Estimated primary DB size at end of year 1: **~600 GB–1 TB** with indexes. Plan for
`db.r6g.2xlarge` or larger, with archival of `audit_log` and `punch` partitions to S3/Athena
(Document 13 §1).

---

## 14. Migration & Seeding (Alembic)

- Migrations are **forward-only**, reviewed, and never destructive in a single step: a column
  rename = add → backfill → dual-write → switch reads → drop (across ≥2 releases) — the
  expand/contract pattern, unchanged from the original design and now executed via Alembic revisions.
- Every migration must run online (no `ACCESS EXCLUSIVE` locks on large tables during business
  hours; use `CREATE INDEX CONCURRENTLY` for indexes — note that Alembic's `op.create_index` needs
  `postgresql_concurrently=True` and must run **outside** a transaction block, i.e. the specific
  Alembic revision sets `# alembic: no_transaction` at the top of the file — and `NOT VALID` +
  `VALIDATE CONSTRAINT` for constraints).
- **Alembic autogenerate** (`alembic revision --autogenerate`) handles routine column/table/index
  changes correctly by diffing SQLAlchemy models against the current schema, but it does **not**
  detect RLS policies, exclusion constraints, or partitioning — these are always hand-written in the
  migration, with a comment block explaining the intent (mirrors the original Prisma-based design's
  identical limitation, documented in `alembic/versions/README.md`).
- **Seed data set** (required, versioned in the repo, loaded via a seed script rather than
  Alembic — seeds are data, not schema):
  1. Permission catalogue (~250 permission codes, Document 19)
  2. System roles + role_permission mapping
  3. Statutory master for India (all states' PT slabs, TDS slabs both regimes, PF/ESI/LWF/gratuity/bonus)
  4. Industry templates × 8 (leave types, shifts, salary structures, workflows, letter templates, designations)
  5. Notification event catalogue + default templates (~120 events × 3 channels)
  6. Document type master, skill master, exit reason master, rejection reason master
  7. Standard report definitions (~60)
- **Demo tenant generator** for sales and QA: creates a realistic 250-employee company with 6 months
  of attendance, leave and payroll history in under 5 minutes (`scripts/generate_demo_tenant.py`,
  Document 06 §2). Build this early — it pays for itself in demos, testing and onboarding.

---

## 15. Async Session Management (new — SQLAlchemy-specific)

```python
# core/db/session.py
engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=20, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        async with session.begin():
            yield session
            # commits on clean exit, rolls back on exception — FastAPI's Depends
            # teardown handles this via the generator's context manager
```

Key operational rules, enforced by code review and, where possible, by `mypy`/`ruff` custom rules:

- **One session per request**, injected via `Depends(get_session)` — never a module-level or
  application-global session (this would break tenant isolation, since the RLS `SET LOCAL` is
  transaction-scoped, and would break under concurrent requests in the same worker process).
- **Celery tasks open their own session** from the same `async_session_factory`, scoped to the task's
  lifetime — they do not and cannot reuse a request's session (Document 07 §5).
- **No lazy-loading across an `await` boundary outside the session's lifetime.** Relationships
  needed by a Pydantic response schema are either eagerly loaded (`selectinload`/`joinedload` in the
  repository query) or the repository returns exactly the shape the schema needs — this avoids the
  classic async-ORM foot-gun of a `DetachedInstanceError` after the session closes, which has no
  equivalent failure mode in Prisma's generated-client model and is the main new class of bug this
  ORM change introduces. It is covered explicitly in the integration test suite (Document 15 §2) by
  asserting response serialisation succeeds without additional queries (also enforced generally by
  the N+1 query-count assertion, Document 23 §1 NFR-P11).
- **Connection pool sizing** is tuned per deployable (Document 03 §1.1): the Core API pool is sized
  for interactive request concurrency; the Worker pool is sized separately and smaller per process
  since Celery worker concurrency is bounded by CPU cores, not I/O concurrency, for the CPU-bound
  payroll compute step.
