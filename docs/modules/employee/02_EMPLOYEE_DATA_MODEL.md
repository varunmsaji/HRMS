# Employee Data Model

Companion to `00_EMPLOYEE_AUDIT.md` — this document covers Phase 4 (effective-dated data
architecture) and Phase 5 (full field inventory) of the audit in schema-level detail. No code or
migration is written here; SQL blocks below are proposed shapes for review, not applied DDL.

**Sourcing discipline**: every table/column below traces to `docs/product/08_Database_Architecture.md
§5`, the live schema (`apps/api/scripts/sql/001_init_schema.sql`), or a named FR-EMP-*
requirement. Where a field's sensitivity classification or view/edit permission is not explicitly
stated in `docs/product/19_RBAC_and_Permission_Matrix.md §6`, it is marked **(inferred)** and
should be confirmed, not treated as settled.

---

## 1. Effective-dating architecture

### 1.1 The pattern (ADR-0003, already live at the DB level)

```sql
CREATE TABLE employee_assignment (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES company(id),
  employee_id UUID NOT NULL REFERENCES employee(id),
  effective_from DATE NOT NULL,
  effective_to DATE,                          -- NULL = current
  ...business columns...,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL,
  deleted_at TIMESTAMPTZ,
  version INTEGER NOT NULL DEFAULT 1
);

ALTER TABLE employee_assignment
  ADD CONSTRAINT employee_assignment_no_overlap
  EXCLUDE USING gist (
    employee_id WITH =,
    daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
  );
```

This constraint (already live for `employee_assignment` and `employee_compensation`,
`001_init_schema.sql:494-506`) makes two overlapping "current" rows for the same employee
**structurally impossible** — a bug that tries to insert an overlapping period fails at the
database, not silently in application logic.

### 1.2 The write pattern — insert, never update-in-place
A change (transfer, promotion, manager change, shift change, compensation revision) is:
1. Read the current row (`effective_to IS NULL`) for the employee.
2. `UPDATE ... SET effective_to = :new_effective_from - 1 day WHERE id = :current_row_id` (close
   the old row — this is the one allowed "edit," and it only ever touches `effective_to`, never
   any business column, per ADR-0003: "never an edit of an existing one's core values").
3. `INSERT` a new row with `effective_from = :new_effective_from`, `effective_to = NULL`, the new
   business column values.

Steps 2-3 happen in the same transaction. FR-EMP-003 (`docs/product/17_SRS_Phase1_Core_Modules.md:140`)
states this explicitly for assignment changes: "the previous row is closed the day before."

### 1.3 The read pattern — "current" vs "as of date"
- **Current value**: `WHERE employee_id = :id AND effective_to IS NULL` (at most one row, by the
  exclusion constraint).
- **As of a past/future date**: `WHERE employee_id = :id AND effective_from <= :date AND
  (effective_to IS NULL OR effective_to >= :date)` (at most one row).
- **Full history**: `WHERE employee_id = :id ORDER BY effective_from`.

**Recommendation**: implement this once as a shared repository helper (e.g.
`EmployeeAssignmentRepository.get_as_of(employee_id, date)` /
`EmployeeCompensationRepository.get_as_of(employee_id, date)`), not re-derived ad hoc in each
consuming module (Attendance, Leave, Payroll) — this is the "disciplined service-layer helper"
ADR-0003's consequences section calls for. No such helper exists anywhere in the codebase today
(§00 §4) — this is new infrastructure Employee introduces, not an extension of an existing one.

### 1.4 Backdating and future-dating (FR-EMP-004, FR-EMP-005)
- **Future-dated changes** are permitted and "activate automatically on the effective date via a
  scheduled job" (FR-EMP-005) — i.e., a row with `effective_from` in the future can be inserted
  now; no job actually needs to "activate" it, since the as-of-date read pattern (§1.3) already
  returns the right row for any given date without a state transition. The "scheduled job" language
  in the SRS likely refers to notification/UI purposes (e.g., "this transfer takes effect
  tomorrow"), not a data-model requirement — flagged as a minor interpretation, not a contradiction.
- **Backdated changes** are permitted only if `effective_from` is after the last finalised payroll
  period, unless the actor holds `PAYROLL.BACKDATE_OVERRIDE` — in which case Payroll auto-generates
  an arrears line (FR-EMP-004). This is a **Payroll-owned business rule enforced at Employee's
  write boundary** — Employee's service layer needs to ask Payroll (via `payroll.service`, once it
  exists) whether a given backdate is inside a locked period. Until Payroll exists, this check
  cannot be implemented — flagged as a known limitation for Employee's first slice, not silently
  skipped without a note (mirrors how the organisation module explicitly comments "Employee
  doesn't exist yet" wherever it skips a cross-module check today).

---

## 2. Full employee data inventory

Legend: **Req** = required at creation per FR-EMP-002 unless noted; **Mut** = mutable after
creation; **Eff** = effective-dated (lives on a history table, not a plain column);
**Class** = PUBLIC / INTERNAL / SENSITIVE / RESTRICTED per `docs/product/19 §6`.

### A. Identity — `employee` table

| Field | Table | Req | Mut | Eff | Class | View | Edit |
|---|---|:--:|:--:|:--:|:--:|---|---|
| `employee_code` | employee | auto-generated | no (immutability not explicitly stated — recommended immutable, §00 §3.4) | no | PUBLIC | `EMPLOYEE.VIEW` | system-generated only |
| `first_name` / `last_name` / `middle_name` | employee | first_name yes | yes | no | PUBLIC | `EMPLOYEE.VIEW` | `EMPLOYEE.UPDATE` |
| `display_name` | employee | generated | derived | no | PUBLIC | `EMPLOYEE.VIEW` | derived, not directly editable |
| `date_of_birth` | employee | no | yes (controlled field, FR-EMP-009) | no | SENSITIVE | HR + self | `EMPLOYEE.UPDATE_SENSITIVE` — routes to HR approval per FR-EMP-009 |
| `gender` | employee | no | yes | no | INTERNAL **(inferred)** | `EMPLOYEE.VIEW` | `EMPLOYEE.UPDATE` |
| `blood_group` | employee | no | yes | no | INTERNAL | `EMPLOYEE.VIEW` | `EMPLOYEE.UPDATE` |
| `marital_status` | employee | no | yes | no | SENSITIVE **(inferred — personal status)** | HR + self | `EMPLOYEE.UPDATE` |
| `nationality` | employee | no | yes | no | INTERNAL **(inferred)** | `EMPLOYEE.VIEW` | `EMPLOYEE.UPDATE` |
| `photo_url` | employee | no | yes (uncontrolled, FR-EMP-009) | no | PUBLIC | everyone | self, direct update |
| `pan_number_enc` | employee | no | yes (controlled) | no | RESTRICTED — encrypted at column level, masked in API (`ABCDE****F`) | `EMPLOYEE.UPDATE_SENSITIVE` | `EMPLOYEE.UPDATE_SENSITIVE` |
| `aadhaar_number_enc` | employee | no | yes (controlled) | no | RESTRICTED — encrypted, masked (`XXXX XXXX 1234`) | `EMPLOYEE.UPDATE_SENSITIVE` | `EMPLOYEE.UPDATE_SENSITIVE` |
| `uan_number` | employee | no | yes | no | RESTRICTED **(inferred — statutory identifier)** | `EMPLOYEE.UPDATE_SENSITIVE` | `EMPLOYEE.UPDATE_SENSITIVE` |
| `status` | employee | system-managed | state-machine only (FR-EMP-014) | no | INTERNAL **(inferred)** | `EMPLOYEE.VIEW` | system-managed via lifecycle actions, not direct edit |
| `custom_fields` (JSONB) | employee | no | yes | no | varies per `custom_field_definition.visible_to_roles` | per-field config | per-field config |
| `user_id` | employee | no | system-managed | no | INTERNAL | `EMPLOYEE.VIEW` | system-managed (login provisioning) |

### B. Contact — `employee` + `employee_address` + `employee_emergency_contact`

| Field | Table | Req | Mut | Eff | Class | View | Edit |
|---|---|:--:|:--:|:--:|:--:|---|---|
| `personal_email` | employee | no | yes (controlled, FR-EMP-009) | no | SENSITIVE | HR + self | `EMPLOYEE.VIEW_PERSONAL_CONTACT` to view; HR-approved change |
| `personal_mobile` | employee | no | yes (controlled) | no | SENSITIVE | HR + self | `EMPLOYEE.VIEW_PERSONAL_CONTACT` to view; HR-approved change |
| work email / work phone | *(not on `employee` per Doc 08 — likely derived/provisioned via identity, or a custom field)* | — | — | — | PUBLIC | everyone | HR/IT provisioning, not an Employee-module field |
| `employee_address.lines/city/state/country/pincode` | employee_address | no | yes | no | SENSITIVE | HR + self | `EMPLOYEE.UPDATE` |
| `employee_address.type` (PERMANENT/CURRENT) | employee_address | no | yes | no | SENSITIVE | HR + self | `EMPLOYEE.UPDATE` |

### C. Employment — `employment` table

| Field | Table | Req | Mut | Eff | Class | View | Edit |
|---|---|:--:|:--:|:--:|:--:|---|---|
| `legal_entity_id` | employment | yes | rare (inter-entity transfer closes/opens employment, FR-EMP-011) | no (own row is the version) | INTERNAL | `EMPLOYEE.VIEW` | `EMPLOYEE.TRANSFER` |
| `employment_number` | employment | auto/optional | no | no | INTERNAL **(inferred)** | `EMPLOYEE.VIEW` | system-generated |
| `employment_type_id` | employment | yes | yes | no | INTERNAL | `EMPLOYEE.VIEW` | `EMPLOYEE.UPDATE` |
| `date_of_joining` | employment | yes | no post-creation (immutability not stated; recommended immutable — joining date is a historical fact) | no | INTERNAL | `EMPLOYEE.VIEW` | set at creation only |
| `date_of_confirmation` | employment | no | set once by confirmation workflow (FR-EMP-010) | no | INTERNAL | `EMPLOYEE.VIEW` | `EMPLOYEE.CONFIRM` |
| `probation_end_date` | employment | auto-computed | yes (extend, FR-EMP-010) | no | INTERNAL | `EMPLOYEE.VIEW` | `EMPLOYEE.CONFIRM` |
| `notice_period_days` | employment | no (override chain, §00 §7.2) | yes | no | INTERNAL | `EMPLOYEE.VIEW` | `EMPLOYEE.UPDATE` |
| `date_of_resignation` / `last_working_day` | employment | no | set once (exit initiation) | no | INTERNAL | `EMPLOYEE.VIEW` | Exit module (`EXIT.INITIATE_*`), not Employee directly |
| `exit_type` / `exit_reason_id` | employment | no | set once | no | INTERNAL **(inferred)** | `EMPLOYEE.VIEW` | Exit module |
| `is_rehire` / `previous_employment_id` | employment | system-set | no | no | INTERNAL | `EMPLOYEE.VIEW` | system-set during rehire creation (§00 §3) |
| `status` | employment | system-managed | state-machine | no | INTERNAL — **value set undefined, §00 §14 row 3** | `EMPLOYEE.VIEW` | system-managed |

### D. Organisation — `employee_assignment` table (effective-dated)

| Field | Table | Req | Mut | Eff | Class | View | Edit |
|---|---|:--:|:--:|:--:|:--:|---|---|
| `branch_id` | employee_assignment | yes (at creation) | yes → new row | **yes** | INTERNAL | `EMPLOYEE.VIEW` | `EMPLOYEE.TRANSFER` |
| `department_id` | employee_assignment | yes | yes → new row | **yes** | PUBLIC | everyone | `EMPLOYEE.TRANSFER` |
| `designation_id` | employee_assignment | yes | yes → new row | **yes** | PUBLIC | everyone | `EMPLOYEE.PROMOTE` / `.TRANSFER` |
| `grade_id` | employee_assignment | no | yes → new row | **yes** | INTERNAL **(inferred — compensation-adjacent but not itself CTC)** | `EMPLOYEE.VIEW` | `EMPLOYEE.PROMOTE` |
| `reporting_manager_id` | employee_assignment | no (nullable for CEO, FR-EMP-002) | yes → new row | **yes** | PUBLIC | everyone | `EMPLOYEE.UPDATE` (reassignment also reassigns pending approvals, FR-EMP-013) |
| `dotted_line_manager_id` | employee_assignment | no | yes → new row | **yes** | INTERNAL **(inferred)** | `EMPLOYEE.VIEW` | `EMPLOYEE.UPDATE` |
| `cost_centre_id` | employee_assignment | no | yes → new row | **yes** | INTERNAL **(inferred — finance-adjacent)** | `EMPLOYEE.VIEW` | `EMPLOYEE.UPDATE` |
| `work_location_type` (OFFICE/WFH/HYBRID/FIELD) | employee_assignment | no | yes → new row | **yes** | INTERNAL **(inferred)** | `EMPLOYEE.VIEW` | `EMPLOYEE.UPDATE` |
| `change_reason` / `change_type` | employee_assignment | yes (on any change) | n/a (write-once per row) | n/a | INTERNAL | `EMPLOYEE.VIEW` | set at write time by whichever action created the row |

### E. Shift — `employee_assignment.shift_id`

| Field | Table | Req | Mut | Eff | Class | View | Edit |
|---|---|:--:|:--:|:--:|:--:|---|---|
| `shift_id` | employee_assignment | no (§00 §7.2 — override chain unresolved) | yes → new row (`change_type = SHIFT_CHANGE`) | **yes** | INTERNAL | `EMPLOYEE.VIEW` | `EMPLOYEE.UPDATE` |

No separate shift-assignment table — shift is one column on the same `employee_assignment` row as
department/designation/grade/manager (§00 §7.1). Per-date roster overrides (`shift_roster`) are
out of Employee's scope (Attendance-owned).

### F. Statutory (India-specific) — `employee_statutory` table (documented, **not in live schema**)

| Field | Table | Req | Mut | Eff | Class | View | Edit |
|---|---|:--:|:--:|:--:|:--:|---|---|
| `is_pf_applicable` / `pf_number` / `pf_wage_ceiling_opt_out` | employee_statutory | no | yes → new row | **yes** | RESTRICTED **(inferred — statutory financial data)** | `EMPLOYEE.VIEW_COMPENSATION`-adjacent **(no exact permission named — flag as gap)** | `EMPLOYEE.UPDATE_SENSITIVE` |
| `uan` | employee_statutory | no | yes → new row | **yes** | RESTRICTED | as above | `EMPLOYEE.UPDATE_SENSITIVE` |
| `vpf_amount` / `vpf_percentage` | employee_statutory | no | yes → new row | **yes** | RESTRICTED | as above | `EMPLOYEE.UPDATE_SENSITIVE` |
| `is_esi_applicable` / `esi_ip_number` | employee_statutory | no | yes → new row | **yes** | RESTRICTED | as above | `EMPLOYEE.UPDATE_SENSITIVE` |
| `pt_state_code` | employee_statutory | no | yes → new row | **yes** | RESTRICTED **(inferred)** | as above | `EMPLOYEE.UPDATE_SENSITIVE` |
| `is_lwf_applicable` | employee_statutory | no | yes → new row | **yes** | RESTRICTED **(inferred)** | as above | `EMPLOYEE.UPDATE_SENSITIVE` |
| `tax_regime` (OLD/NEW) | employee_statutory | no | yes → new row (once-per-FY switch rule, FR-PAY-006) | **yes** | RESTRICTED | Payroll-facing | `EMPLOYEE.UPDATE_SENSITIVE` |
| `is_director` / `is_international_worker` | employee_statutory | no | yes → new row | **yes** | RESTRICTED **(inferred)** | as above | `EMPLOYEE.UPDATE_SENSITIVE` |

**Gap flagged explicitly**: no permission code in the 14-item catalogue names statutory data
specifically — the closest is `EMPLOYEE.UPDATE_SENSITIVE` ("Edit PAN/Aadhaar/bank/statutory").
There is no separate `EMPLOYEE.VIEW_STATUTORY`; the audit assumes it is bundled under
`EMPLOYEE.VIEW_COMPENSATION` or a to-be-confirmed equivalent — flagged as a decision, not
resolved here.

### G. Banking — `employee_bank` table (documented, **not in live schema**)

| Field | Table | Req | Mut | Eff | Class | View | Edit |
|---|---|:--:|:--:|:--:|:--:|---|---|
| `account_holder_name` | employee_bank | no | yes → new row | **yes** | RESTRICTED | explicit permission only | `EMPLOYEE.UPDATE_SENSITIVE` |
| `account_number_enc` | employee_bank | no | yes → new row | **yes** | RESTRICTED — encrypted, masked (`******7890`) | explicit permission only | `EMPLOYEE.UPDATE_SENSITIVE` |
| `bank_name` / `ifsc` / `branch_name` | employee_bank | no | yes → new row | **yes** | RESTRICTED | explicit permission only | `EMPLOYEE.UPDATE_SENSITIVE` |
| `payment_mode` (BANK/CASH/CHEQUE/UPI) | employee_bank | no | yes → new row | **yes** | RESTRICTED **(inferred)** | explicit permission only | `EMPLOYEE.UPDATE_SENSITIVE` |
| `is_primary` / `verification_status` / `penny_drop_reference` | employee_bank | system-managed | system-managed | **yes** | RESTRICTED | explicit permission only | system-managed / `EMPLOYEE.VERIFY_DOCUMENTS`-adjacent |

### H. Emergency contacts — `employee_emergency_contact` table (documented, not in live schema)

| Field | Table | Req | Mut | Eff | Class | View | Edit |
|---|---|:--:|:--:|:--:|:--:|---|---|
| `name` / `relation` / `phone` / `address` | employee_emergency_contact | no | yes (uncontrolled, FR-EMP-009) | no | SENSITIVE | HR + self | self, direct update |
| `is_primary` | employee_emergency_contact | no | yes | no | SENSITIVE | HR + self | self |

### I. Documents — `employee_document` table (documented, not in live schema)

| Field | Table | Req | Mut | Eff | Class | View | Edit |
|---|---|:--:|:--:|:--:|:--:|---|---|
| `document_type_id` / `document_number` | employee_document | no | yes (re-upload) | no | RESTRICTED **(identity documents — inferred)** | `EMPLOYEE.VIEW_DOCUMENTS` | `EMPLOYEE.UPLOAD_DOCUMENTS` |
| `issue_date` / `expiry_date` | employee_document | no | yes | no | INTERNAL **(inferred — dates alone, not the document content)** | `EMPLOYEE.VIEW_DOCUMENTS` | `EMPLOYEE.UPLOAD_DOCUMENTS` |
| `file_id` | employee_document | yes | replaces on re-upload | no | RESTRICTED | `EMPLOYEE.VIEW_DOCUMENTS` | `EMPLOYEE.UPLOAD_DOCUMENTS` |
| `verification_status` / `verified_by` / `verified_at` / `rejection_reason` | employee_document | system-managed | via verification workflow | no | INTERNAL | `EMPLOYEE.VIEW_DOCUMENTS` | `EMPLOYEE.VERIFY_DOCUMENTS` |

### J. Compensation — `employee_compensation` table (effective-dated, live but partial)

| Field | Table | Req | Mut | Eff | Class | View | Edit |
|---|---|:--:|:--:|:--:|:--:|---|---|
| `annual_ctc_minor` (live) / `annual_ctc` (doc name) | employee_compensation | yes (at creation) | yes → new row | **yes** | RESTRICTED | `EMPLOYEE.VIEW_COMPENSATION` | `EMPLOYEE.UPDATE_COMPENSATION` |
| `currency` (live only — not in Doc 08's field list) | employee_compensation | yes | no per row | **yes** (part of the row) | RESTRICTED | `EMPLOYEE.VIEW_COMPENSATION` | `EMPLOYEE.UPDATE_COMPENSATION` |
| `salary_structure_id` (doc only) | employee_compensation | no | yes → new row | **yes** | RESTRICTED | `EMPLOYEE.VIEW_COMPENSATION` | `EMPLOYEE.UPDATE_COMPENSATION` |
| `monthly_gross` (doc only) | employee_compensation | no (derivable) | yes → new row | **yes** | RESTRICTED | `EMPLOYEE.VIEW_COMPENSATION` | `EMPLOYEE.UPDATE_COMPENSATION` |
| `revision_type` (JOINING/ANNUAL/PROMOTION/CORRECTION/MARKET) / `revision_reason` | employee_compensation | yes on revision | write-once per row | n/a | RESTRICTED | `EMPLOYEE.VIEW_COMPENSATION` | `EMPLOYEE.UPDATE_COMPENSATION` |
| `approved_by` / `approval_request_id` | employee_compensation | yes if approval-gated | system-set | n/a | RESTRICTED | `EMPLOYEE.VIEW_COMPENSATION` | system-set via approval workflow |
| `is_arrears_processed` | employee_compensation | system-managed | system-managed | n/a | RESTRICTED | `EMPLOYEE.VIEW_COMPENSATION` | Payroll-owned |
| `employee_compensation_component` (child: component_id, amount, percentage, formula_override, is_monthly) | employee_compensation_component | no | yes | tied to parent row's effective range | RESTRICTED | `EMPLOYEE.VIEW_COMPENSATION` | `EMPLOYEE.UPDATE_COMPENSATION` |

### K. Other employee metadata — supporting tables (documented, not in live schema)

| Table | Purpose | Class | View | Edit |
|---|---|---|---|---|
| `employee_dependent` | relation, name, DOB, gender, is_nominee, nominee_percentage, is_insurance_covered, aadhaar_enc | SENSITIVE (aadhaar_enc RESTRICTED) | HR + self | `EMPLOYEE.UPDATE` |
| `employee_education` | level, degree, specialisation, institution, university, year_of_passing, percentage, document_id | INTERNAL **(inferred)** | `EMPLOYEE.VIEW` | `EMPLOYEE.UPDATE` |
| `employee_experience` | company_name, designation, from/to date, last_ctc, reason_for_leaving, document_id | SENSITIVE **(last_ctc is compensation-adjacent — inferred RESTRICTED for that one field)** | `EMPLOYEE.VIEW` (last_ctc: `EMPLOYEE.VIEW_COMPENSATION`) | `EMPLOYEE.UPDATE` |
| `employee_skill` | skill_id, proficiency, years_of_experience, is_certified | PUBLIC **(inferred — professional profile data)** | everyone | `EMPLOYEE.UPDATE` |
| `employee_event` | event_type, event_date, description, reference_type, reference_id — the unified timeline feed | mirrors the referenced event's own classification | `EMPLOYEE.VIEW` (per-event masking of referenced sensitive data) | system-generated only |

---

## 3. Recommended migration shape (extends the live stubs, per `00_EMPLOYEE_AUDIT.md §15.7`)

Following the exact pattern every organisation-module entity used to extend its own baseline stub
(e.g. `20260813160000_grade_fields.py`): one migration per table, `ALTER TABLE ... ADD COLUMN IF
NOT EXISTS`, plus new FK constraints, plus two brand-new tables (`employee_statutory`,
`employee_bank`) built fresh with the same effective-dating exclusion-constraint pattern as
`employee_assignment`/`employee_compensation`.

```sql
-- employee: extend identity fields
ALTER TABLE employee
  ADD COLUMN IF NOT EXISTS middle_name VARCHAR(100),
  ADD COLUMN IF NOT EXISTS display_name VARCHAR(200),
  ADD COLUMN IF NOT EXISTS blood_group VARCHAR(10),
  ADD COLUMN IF NOT EXISTS marital_status VARCHAR(20),
  ADD COLUMN IF NOT EXISTS nationality VARCHAR(80),
  ADD COLUMN IF NOT EXISTS personal_email CITEXT,
  ADD COLUMN IF NOT EXISTS personal_mobile VARCHAR(20),
  ADD COLUMN IF NOT EXISTS photo_url TEXT,
  ADD COLUMN IF NOT EXISTS pan_number_enc TEXT,
  ADD COLUMN IF NOT EXISTS aadhaar_number_enc TEXT,
  ADD COLUMN IF NOT EXISTS uan_number VARCHAR(20),
  ADD COLUMN IF NOT EXISTS status VARCHAR(25) NOT NULL DEFAULT 'PRE_JOINING';

-- employment: extend lifecycle fields
ALTER TABLE employment
  ADD COLUMN IF NOT EXISTS employment_number VARCHAR(30),
  ADD COLUMN IF NOT EXISTS employment_type_id UUID REFERENCES employment_type(id),
  ADD COLUMN IF NOT EXISTS date_of_confirmation DATE,
  ADD COLUMN IF NOT EXISTS probation_end_date DATE,
  ADD COLUMN IF NOT EXISTS notice_period_days INTEGER,
  ADD COLUMN IF NOT EXISTS date_of_resignation DATE,
  ADD COLUMN IF NOT EXISTS last_working_day DATE,
  ADD COLUMN IF NOT EXISTS exit_type VARCHAR(30),
  ADD COLUMN IF NOT EXISTS exit_reason_id UUID,
  ADD COLUMN IF NOT EXISTS is_rehire BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS previous_employment_id UUID REFERENCES employment(id),
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;   -- missing today, §00 §1.2

-- employee_assignment: extend + add FK constraints (currently plain UUID, §00 §14 row 8)
ALTER TABLE employee_assignment
  ADD COLUMN IF NOT EXISTS dotted_line_manager_id UUID,
  ADD COLUMN IF NOT EXISTS shift_id UUID,
  ADD COLUMN IF NOT EXISTS cost_centre_id UUID,
  ADD COLUMN IF NOT EXISTS work_location_type VARCHAR(20),
  ADD COLUMN IF NOT EXISTS change_reason TEXT,
  ADD COLUMN IF NOT EXISTS change_type VARCHAR(30);

ALTER TABLE employee_assignment
  ADD CONSTRAINT employee_assignment_department_id_fkey FOREIGN KEY (department_id) REFERENCES department(id) ON DELETE SET NULL,
  ADD CONSTRAINT employee_assignment_designation_id_fkey FOREIGN KEY (designation_id) REFERENCES designation(id) ON DELETE SET NULL,
  ADD CONSTRAINT employee_assignment_grade_id_fkey FOREIGN KEY (grade_id) REFERENCES grade(id) ON DELETE SET NULL,
  ADD CONSTRAINT employee_assignment_branch_id_fkey FOREIGN KEY (branch_id) REFERENCES branch(id) ON DELETE SET NULL,
  ADD CONSTRAINT employee_assignment_reporting_manager_id_fkey FOREIGN KEY (reporting_manager_id) REFERENCES employee(id) ON DELETE SET NULL,
  ADD CONSTRAINT employee_assignment_shift_id_fkey FOREIGN KEY (shift_id) REFERENCES shift(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS employee_assignment_current_idx
  ON employee_assignment (company_id, employee_id, effective_from DESC);
CREATE INDEX IF NOT EXISTS employee_assignment_manager_idx
  ON employee_assignment (company_id, reporting_manager_id) WHERE effective_to IS NULL;

-- employee_compensation: extend
ALTER TABLE employee_compensation
  ADD COLUMN IF NOT EXISTS salary_structure_id UUID,
  ADD COLUMN IF NOT EXISTS monthly_gross BIGINT,
  ADD COLUMN IF NOT EXISTS revision_type VARCHAR(20),
  ADD COLUMN IF NOT EXISTS revision_reason TEXT,
  ADD COLUMN IF NOT EXISTS approved_by UUID,
  ADD COLUMN IF NOT EXISTS approval_request_id UUID,
  ADD COLUMN IF NOT EXISTS is_arrears_processed BOOLEAN NOT NULL DEFAULT false;

-- employee_statutory: new table, same effective-dating pattern
CREATE TABLE employee_statutory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES company(id),
  employee_id UUID NOT NULL REFERENCES employee(id),
  effective_from DATE NOT NULL,
  effective_to DATE,
  is_pf_applicable BOOLEAN NOT NULL DEFAULT false,
  pf_number VARCHAR(30),
  pf_wage_ceiling_opt_out BOOLEAN NOT NULL DEFAULT false,
  vpf_amount BIGINT,
  vpf_percentage NUMERIC(9,4),
  is_esi_applicable BOOLEAN NOT NULL DEFAULT false,
  esi_ip_number VARCHAR(30),
  pt_state_code VARCHAR(10),
  is_lwf_applicable BOOLEAN NOT NULL DEFAULT false,
  tax_regime VARCHAR(10),
  is_director BOOLEAN NOT NULL DEFAULT false,
  is_international_worker BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL,
  deleted_at TIMESTAMPTZ,
  version INTEGER NOT NULL DEFAULT 1
);
ALTER TABLE employee_statutory
  ADD CONSTRAINT employee_statutory_no_overlap
  EXCLUDE USING gist (
    employee_id WITH =,
    daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
  );

-- employee_bank: new table, same pattern (account_number_enc encrypted at column level)
CREATE TABLE employee_bank (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES company(id),
  employee_id UUID NOT NULL REFERENCES employee(id),
  effective_from DATE NOT NULL,
  effective_to DATE,
  account_holder_name VARCHAR(150),
  account_number_enc TEXT,
  bank_name VARCHAR(150),
  ifsc VARCHAR(15),
  branch_name VARCHAR(150),
  payment_mode VARCHAR(10),
  is_primary BOOLEAN NOT NULL DEFAULT true,
  verification_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
  penny_drop_reference VARCHAR(60),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL,
  deleted_at TIMESTAMPTZ,
  version INTEGER NOT NULL DEFAULT 1
);
ALTER TABLE employee_bank
  ADD CONSTRAINT employee_bank_no_overlap
  EXCLUDE USING gist (
    employee_id WITH =,
    daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
  );

-- RLS re-asserted idempotently for both new tables (matching every prior migration's own convention)
ALTER TABLE employee_statutory ENABLE ROW LEVEL SECURITY;
ALTER TABLE employee_statutory FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON employee_statutory
  USING (company_id = current_setting('app.company_id', true)::uuid);

ALTER TABLE employee_bank ENABLE ROW LEVEL SECURITY;
ALTER TABLE employee_bank FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON employee_bank
  USING (company_id = current_setting('app.company_id', true)::uuid);
```

`employee_document`, `employee_dependent`, `employee_education`, `employee_experience`,
`employee_skill`, `employee_address`, `employee_emergency_contact`, `employee_event` are all new
tables, none effective-dated (they are append/replace collections, not time-versioned facts) —
full DDL is deferred to the implementation slice that builds them (`01_EMPLOYEE_MODULE_PLAN.md`,
E-06/E-08), since the audit brief scopes this document to the core identity/employment/assignment/
compensation/statutory/bank shape that every other module depends on.

---

## 4. What is deliberately not decided here

Per `00_EMPLOYEE_AUDIT.md §15`: exact `employment.status` value set (row 3), the BR-14 override
chain mechanism, whether `employee_code` is ever reissued, and the exact permission code for
viewing statutory data (§2 section F gap) are all open product decisions, not defaulted silently
in this schema. Column types/nullability above follow the DB Architecture doc's own types where
stated; where the doc gives no type (e.g. `exit_type`), a conservative `VARCHAR` is proposed for
review, not asserted as final.
