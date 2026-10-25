# Data models - payroll

Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list (for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "Server-generated" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart (derived by name match - an inference, not a declared flag).

## EmployeeSalaryBreakupRead
<a id="employeesalarybreakupread"></a>

An employee's pay as of a date: the structure breakup for a monthly-paid employee, or the daily rate for a daily-wage one (D5) — `breakup` is `None` then.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `as_of` | yes | string(date) | no | - | - |
| `pay_basis` | yes | string | no | - | - |
| `salary_structure_id` | yes | string(uuid) | yes | - | - |
| `salary_structure_version_id` | yes | string(uuid) | yes | - | - |
| `daily_rate_minor` | yes | integer | yes | - | - |
| `pf_applicable` | yes | boolean | no | - | - |
| `esi_applicable` | yes | boolean | no | - | - |
| `breakup` | yes | [SalaryBreakupRead](#salarybreakupread) | yes | - | - |

## EmployeeSalaryBulkAssign
<a id="employeesalarybulkassign"></a>

Assign one structure to monthly-paid employees who have no salary assignment covering `effective_from` — the one-off step that lets existing employees reach their first pay run. Without `employee_ids`, every such employee employed on that date.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `salary_structure_id` | yes | string(uuid) | no | - | - |
| `effective_from` | yes | string(date) | no | - | - |
| `reason` | no | string | no | minLength=1, maxLength=500, default=`"Initial salary structure assignment"` | - |
| `employee_ids` | no | array&lt;string(uuid)&gt; | yes | minItems=1, maxItems=5000 | - |

## EmployeeSalaryBulkResult
<a id="employeesalarybulkresult"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `assigned` | yes | array&lt;string(uuid)&gt; | no | - | - |
| `skipped` | yes | array&lt;[EmployeeSalaryBulkSkip](#employeesalarybulkskip)&gt; | no | - | - |

## EmployeeSalaryBulkSkip
<a id="employeesalarybulkskip"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `reason` | yes | string | no | - | - |

## EmployeeSalaryCreate
<a id="employeesalarycreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `salary_structure_id` | no | string(uuid) | yes | - | - |
| `daily_rate_minor` | no | integer | yes | >=0.0 | - |
| `effective_from` | yes | string(date) | no | - | - |
| `reason` | yes | string | no | minLength=1, maxLength=500 | - |

## EmployeeSalaryRead
<a id="employeesalaryread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `salary_structure_id` | yes | string(uuid) | yes | - | - |
| `daily_rate_minor` | yes | integer | yes | - | - |
| `effective_from` | yes | string(date) | no | - | - |
| `effective_to` | yes | string(date) | yes | - | - |
| `reason` | yes | string | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `EmployeeSalaryCreate`: `company_id`, `created_at`, `effective_to`, `employee_id`, `id`, `updated_at`, `version`

## PayAdjustmentCreate
<a id="payadjustmentcreate"></a>

D7 — correct a finalised month's paid days for one employee; paid as arrears by the legal entity's next pay run.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `source_pay_run_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `paid_days_delta` | yes | number \| string | no | - | - |
| `reason` | yes | string | no | minLength=1, maxLength=1000 | - |

## PayAdjustmentRead
<a id="payadjustmentread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `legal_entity_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `month` | yes | string | no | - | - |
| `source_pay_run_id` | yes | string(uuid) | no | - | - |
| `paid_days_delta` | yes | string | no | - | - |
| `reason` | yes | string | no | - | - |
| `status` | yes | string | no | - | - |
| `applied_pay_run_id` | yes | string(uuid) | yes | - | - |
| `created_by_user_id` | yes | string(uuid) | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |

Server-generated / read-only vs `PayAdjustmentCreate`: `applied_pay_run_id`, `created_at`, `created_by_user_id`, `id`, `legal_entity_id`, `month`, `status`, `version`

## PayRunCreate
<a id="payruncreate"></a>

`month` is `YYYY-MM` — a pay run always covers one whole calendar month (decision 18). `pay_date` defaults to the first weekday of the following month (D11).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `legal_entity_id` | yes | string(uuid) | no | - | - |
| `month` | yes | string | no | pattern=`^\d{4}-(0[1-9]|1[0-2])$` | - |
| `pay_date` | no | string(date) | yes | - | - |

## PayRunEmployeeDetailRead
<a id="payrunemployeedetailread"></a>

One employee's pay in a run: the totals, every line with its trace, and the input snapshot the figures were computed from.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `employee_code` | yes | string | yes | - | - |
| `employee_name` | yes | string | yes | - | - |
| `pay_basis` | yes | string | yes | - | - |
| `paid_days` | yes | string | yes | - | - |
| `lop_days` | yes | string | yes | - | - |
| `payable_days` | yes | string | yes | - | - |
| `is_computed` | yes | boolean | no | - | - |
| `gross_minor` | yes | integer | no | - | - |
| `deductions_minor` | yes | integer | no | - | - |
| `employer_contributions_minor` | yes | integer | no | - | - |
| `rounding_minor` | yes | integer | no | - | - |
| `net_minor` | yes | integer | no | - | - |
| `issues` | yes | array&lt;[PayRunIssueRead](#payrunissueread)&gt; | no | - | - |
| `has_error` | yes | boolean | no | - | - |
| `previous_net_minor` | yes | integer | yes | - | - |
| `variance_percent` | yes | string | yes | - | - |
| `variance_flagged` | yes | boolean | no | - | - |
| `variance_reason` | yes | string | yes | - | - |
| `variance_acknowledged_by_user_id` | yes | string(uuid) | yes | - | - |
| `variance_acknowledged_at` | yes | string | yes | - | - |
| `lines` | yes | array&lt;[PayRunLineRead](#payrunlineread)&gt; | no | - | - |
| `snapshot` | yes | object | no | - | - |

## PayRunEmployeeRead
<a id="payrunemployeeread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `employee_code` | yes | string | yes | - | - |
| `employee_name` | yes | string | yes | - | - |
| `pay_basis` | yes | string | yes | - | - |
| `paid_days` | yes | string | yes | - | - |
| `lop_days` | yes | string | yes | - | - |
| `payable_days` | yes | string | yes | - | - |
| `is_computed` | yes | boolean | no | - | - |
| `gross_minor` | yes | integer | no | - | - |
| `deductions_minor` | yes | integer | no | - | - |
| `employer_contributions_minor` | yes | integer | no | - | - |
| `rounding_minor` | yes | integer | no | - | - |
| `net_minor` | yes | integer | no | - | - |
| `issues` | yes | array&lt;[PayRunIssueRead](#payrunissueread)&gt; | no | - | - |
| `has_error` | yes | boolean | no | - | - |
| `previous_net_minor` | yes | integer | yes | - | - |
| `variance_percent` | yes | string | yes | - | - |
| `variance_flagged` | yes | boolean | no | - | - |
| `variance_reason` | yes | string | yes | - | - |
| `variance_acknowledged_by_user_id` | yes | string(uuid) | yes | - | - |
| `variance_acknowledged_at` | yes | string | yes | - | - |

## PayRunIssueRead
<a id="payrunissueread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `code` | yes | string | no | - | - |
| `severity` | yes | string | no | - | - |
| `message` | yes | string | no | - | - |

## PayRunLineRead
<a id="payrunlineread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `component_code` | yes | string | no | - | - |
| `component_name` | yes | string | no | - | - |
| `line_type` | yes | string | no | - | - |
| `full_monthly_minor` | yes | integer | yes | - | - |
| `amount_minor` | yes | integer | no | - | - |
| `display_order` | yes | integer | no | - | - |
| `trace` | yes | object | no | - | - |

## PayRunRead
<a id="payrunread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `legal_entity_id` | yes | string(uuid) | no | - | - |
| `month` | yes | string | no | - | - |
| `period_start` | yes | string(date) | no | - | - |
| `period_end` | yes | string(date) | no | - | - |
| `days_in_month` | yes | integer | no | - | - |
| `status` | yes | string | no | - | - |
| `pay_date` | yes | string(date) | no | - | - |
| `attendance_period_id` | yes | string(uuid) | yes | - | - |
| `variance_threshold_percent` | yes | string | yes | - | - |
| `previous_pay_run_id` | yes | string(uuid) | yes | - | - |
| `employee_count` | yes | integer | no | - | - |
| `gross_minor` | yes | integer | no | - | - |
| `deductions_minor` | yes | integer | no | - | - |
| `employer_contributions_minor` | yes | integer | no | - | - |
| `net_minor` | yes | integer | no | - | - |
| `error_count` | yes | integer | no | - | - |
| `warning_count` | yes | integer | no | - | - |
| `variance_flag_count` | yes | integer | no | - | - |
| `variance_open_count` | yes | integer | no | - | - |
| `created_by_user_id` | yes | string(uuid) | yes | - | - |
| `inputs_locked_at` | yes | string | yes | - | - |
| `inputs_locked_by_user_id` | yes | string(uuid) | yes | - | - |
| `computed_at` | yes | string | yes | - | - |
| `computed_by_user_id` | yes | string(uuid) | yes | - | - |
| `approved_at` | yes | string | yes | - | - |
| `approved_by_user_id` | yes | string(uuid) | yes | - | - |
| `finalised_at` | yes | string | yes | - | - |
| `finalised_by_user_id` | yes | string(uuid) | yes | - | - |
| `paid_at` | yes | string | yes | - | - |
| `paid_by_user_id` | yes | string(uuid) | yes | - | - |
| `last_rollback_reason` | yes | string | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `PayRunCreate`: `approved_at`, `approved_by_user_id`, `attendance_period_id`, `company_id`, `computed_at`, `computed_by_user_id`, `created_at`, `created_by_user_id`, `days_in_month`, `deductions_minor`, `employee_count`, `employer_contributions_minor`, `error_count`, `finalised_at`, `finalised_by_user_id`, `gross_minor`, `id`, `inputs_locked_at`, `inputs_locked_by_user_id`, `last_rollback_reason`, `net_minor`, `paid_at`, `paid_by_user_id`, `period_end`, `period_start`, `previous_pay_run_id`, `status`, `updated_at`, `variance_flag_count`, `variance_open_count`, `variance_threshold_percent`, `version`, `warning_count`

## PayRunRollback
<a id="payrunrollback"></a>

Back to `DRAFT` (drops the snapshot) or `INPUTS_LOCKED` (drops the computed pay).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `to_status` | yes | string | no | - | - |
| `reason` | yes | string | no | minLength=1, maxLength=1000 | - |

## PayRunUpdate
<a id="payrunupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `pay_date` | yes | string(date) | no | - | - |

## PayRunVarianceAcknowledge
<a id="payrunvarianceacknowledge"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `reason` | yes | string | no | minLength=1, maxLength=1000 | - |

## PayrollSettingRead
<a id="payrollsettingread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `company_id` | yes | string(uuid) | no | - | - |
| `variance_threshold_percent` | yes | string | no | - | - |
| `version` | yes | integer | no | - | - |

Server-generated / read-only vs `PayrollSettingUpdate`: `company_id`, `version`

## PayrollSettingUpdate
<a id="payrollsettingupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `variance_threshold_percent` | yes | number \| string | no | - | - |

## PayslipLeaveBalanceRead
<a id="payslipleavebalanceread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `code` | yes | string | no | - | - |
| `name` | yes | string | no | - | - |
| `balance` | yes | string | no | - | - |

## PayslipLineRead
<a id="paysliplineread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `component_code` | yes | string | no | - | - |
| `component_name` | yes | string | no | - | - |
| `full_monthly_minor` | yes | integer | yes | - | - |
| `amount_minor` | yes | integer | no | - | - |
| `note` | no | string | yes | - | - |

## PayslipRead
<a id="payslipread"></a>

One employee's payslip for one pay run (FR-PAY-017). `is_final` is false for an HR preview of a run not yet finalised — employees only ever see final ones.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `pay_run_id` | yes | string(uuid) | no | - | - |
| `month` | yes | string | no | - | - |
| `period_start` | yes | string(date) | no | - | - |
| `period_end` | yes | string(date) | no | - | - |
| `pay_date` | yes | string(date) | no | - | - |
| `status` | yes | string | no | - | - |
| `is_final` | yes | boolean | no | - | - |
| `company_name` | yes | string | yes | - | - |
| `legal_entity_name` | yes | string | yes | - | - |
| `legal_entity_address` | yes | string | yes | - | - |
| `legal_entity_pan` | yes | string | yes | - | - |
| `legal_entity_tan` | yes | string | yes | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `employee_code` | yes | string | yes | - | - |
| `employee_name` | yes | string | yes | - | - |
| `designation` | yes | string | yes | - | - |
| `department` | yes | string | yes | - | - |
| `date_of_joining` | yes | string(date) | yes | - | - |
| `pan_masked` | yes | string | yes | - | - |
| `uan_number` | yes | string | yes | - | - |
| `esi_ip_number` | yes | string | yes | - | - |
| `payment_mode` | yes | string | yes | - | - |
| `bank_name` | yes | string | yes | - | - |
| `account_last4` | yes | string | yes | - | - |
| `days_in_month` | yes | integer | no | - | - |
| `paid_days` | yes | string | yes | - | - |
| `lop_days` | yes | string | yes | - | - |
| `earnings` | yes | array&lt;[PayslipLineRead](#paysliplineread)&gt; | no | - | - |
| `deductions` | yes | array&lt;[PayslipLineRead](#paysliplineread)&gt; | no | - | - |
| `employer_contributions` | yes | array&lt;[PayslipLineRead](#paysliplineread)&gt; | no | - | - |
| `gross_minor` | yes | integer | no | - | - |
| `deductions_minor` | yes | integer | no | - | - |
| `net_minor` | yes | integer | no | - | - |
| `net_in_words` | yes | string | no | - | - |
| `leave_balances` | yes | array&lt;[PayslipLeaveBalanceRead](#payslipleavebalanceread)&gt; | no | - | - |

## PayslipSummaryRead
<a id="payslipsummaryread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `pay_run_id` | yes | string(uuid) | no | - | - |
| `month` | yes | string | no | - | - |
| `legal_entity_id` | yes | string(uuid) | no | - | - |
| `pay_date` | yes | string(date) | no | - | - |
| `net_minor` | yes | integer | no | - | - |
| `status` | yes | string | no | - | - |

## SalaryBreakupLineRead
<a id="salarybreakuplineread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `component_code` | yes | string | no | - | - |
| `component_name` | yes | string | no | - | - |
| `component_type` | yes | string | no | - | - |
| `monthly_minor` | yes | integer | no | - | - |
| `annual_minor` | yes | integer | no | - | - |
| `basis` | yes | string | no | - | - |

## SalaryBreakupPreviewInput
<a id="salarybreakuppreviewinput"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `annual_ctc_minor` | yes | integer | no | >=0.0 | - |
| `pf_applicable` | no | boolean | no | default=`true` | - |
| `esi_applicable` | no | boolean | no | default=`false` | - |

## SalaryBreakupRead
<a id="salarybreakupread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `annual_ctc_minor` | yes | integer | no | - | - |
| `monthly_ctc_minor` | yes | integer | no | - | - |
| `gross_monthly_minor` | yes | integer | no | - | - |
| `employer_contributions_monthly_minor` | yes | integer | no | - | - |
| `lines` | yes | array&lt;[SalaryBreakupLineRead](#salarybreakuplineread)&gt; | no | - | - |

## SalaryComponentCreate
<a id="salarycomponentcreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `code` | yes | string | no | minLength=1, maxLength=30, pattern=`^[A-Z0-9_]+$` | - |
| `name` | yes | string | no | minLength=1, maxLength=150 | - |
| `component_type` | yes | string | no | - | - |
| `is_taxable` | no | boolean | no | default=`true` | - |
| `is_pf_wage` | no | boolean | no | default=`false` | - |
| `is_esi_wage` | no | boolean | no | default=`false` | - |
| `is_prorated` | no | boolean | no | default=`true` | - |
| `show_on_payslip` | no | boolean | no | default=`true` | - |
| `display_order` | no | integer | no | min=0.0, max=10000.0, default=`0` | - |

## SalaryComponentRead
<a id="salarycomponentread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `code` | yes | string | no | - | - |
| `name` | yes | string | no | - | - |
| `component_type` | yes | string | no | - | - |
| `is_system` | yes | boolean | no | - | - |
| `is_taxable` | yes | boolean | no | - | - |
| `is_pf_wage` | yes | boolean | no | - | - |
| `is_esi_wage` | yes | boolean | no | - | - |
| `is_prorated` | yes | boolean | no | - | - |
| `show_on_payslip` | yes | boolean | no | - | - |
| `display_order` | yes | integer | no | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `SalaryComponentCreate`: `company_id`, `created_at`, `id`, `is_active`, `is_system`, `updated_at`, `version`

## SalaryComponentUpdate
<a id="salarycomponentupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=150 | - |
| `component_type` | no | string | yes | - | - |
| `is_taxable` | no | boolean | yes | - | - |
| `is_pf_wage` | no | boolean | yes | - | - |
| `is_esi_wage` | no | boolean | yes | - | - |
| `is_prorated` | no | boolean | yes | - | - |
| `show_on_payslip` | no | boolean | yes | - | - |
| `display_order` | no | integer | yes | min=0.0, max=10000.0 | - |
| `is_active` | no | boolean | yes | - | - |

## SalaryStructureCreate
<a id="salarystructurecreate"></a>

Creates the structure and its first draft version (with `lines`, if given).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `code` | yes | string | no | minLength=1, maxLength=30, pattern=`^[A-Z0-9_]+$` | - |
| `name` | yes | string | no | minLength=1, maxLength=150 | - |
| `description` | no | string | yes | maxLength=2000 | - |
| `lines` | no | array&lt;[SalaryStructureLineInput](#salarystructurelineinput)&gt; | no | maxItems=50 | - |

## SalaryStructureLineInput
<a id="salarystructurelineinput"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `salary_component_id` | yes | string(uuid) | no | - | - |
| `calculation_type` | yes | string | no | - | - |
| `percentage` | no | number \| string | yes | - | - |
| `amount_monthly_minor` | no | integer | yes | min=0.0 | - |
| `base_salary_component_id` | no | string(uuid) | yes | - | - |
| `max_monthly_minor` | no | integer | yes | min=0.0 | - |
| `applies_when` | no | string | no | default=`"ALWAYS"` | - |
| `display_order` | no | integer | no | min=0.0, max=10000.0, default=`0` | - |

## SalaryStructureLineRead
<a id="salarystructurelineread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `salary_component_id` | yes | string(uuid) | no | - | - |
| `component_code` | yes | string | no | - | - |
| `component_name` | yes | string | no | - | - |
| `component_type` | yes | string | no | - | - |
| `calculation_type` | yes | string | no | - | - |
| `percentage` | yes | string | yes | - | - |
| `amount_monthly_minor` | yes | integer | yes | - | - |
| `base_salary_component_id` | yes | string(uuid) | yes | - | - |
| `max_monthly_minor` | yes | integer | yes | - | - |
| `applies_when` | yes | string | no | - | - |
| `display_order` | yes | integer | no | - | - |

## SalaryStructureRead
<a id="salarystructureread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `code` | yes | string | no | - | - |
| `name` | yes | string | no | - | - |
| `description` | yes | string | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `versions` | yes | array&lt;[SalaryStructureVersionRead](#salarystructureversionread)&gt; | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `SalaryStructureCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`, `versions`

## SalaryStructureUpdate
<a id="salarystructureupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=150 | - |
| `description` | no | string | yes | maxLength=2000 | - |
| `is_active` | no | boolean | yes | - | - |

## SalaryStructureVersionCreate
<a id="salarystructureversioncreate"></a>

A new draft. Without `lines`, it starts as a copy of the latest published version.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `lines` | no | array&lt;[SalaryStructureLineInput](#salarystructurelineinput)&gt; | yes | maxItems=50 | - |

## SalaryStructureVersionLinesUpdate
<a id="salarystructureversionlinesupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `lines` | yes | array&lt;[SalaryStructureLineInput](#salarystructurelineinput)&gt; | no | maxItems=50 | - |

## SalaryStructureVersionPublish
<a id="salarystructureversionpublish"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | yes | string(date) | no | - | - |

## SalaryStructureVersionRead
<a id="salarystructureversionread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `salary_structure_id` | yes | string(uuid) | no | - | - |
| `version_number` | yes | integer | no | - | - |
| `status` | yes | string | no | - | - |
| `effective_from` | yes | string(date) | yes | - | - |
| `effective_to` | yes | string(date) | yes | - | - |
| `published_at` | yes | string | yes | - | - |
| `version` | yes | integer | no | - | - |
| `lines` | yes | array&lt;[SalaryStructureLineRead](#salarystructurelineread)&gt; | no | - | - |

Server-generated / read-only vs `SalaryStructureVersionCreate`: `effective_from`, `effective_to`, `id`, `published_at`, `salary_structure_id`, `status`, `version`, `version_number`

## StatutoryRateCreate
<a id="statutoryratecreate"></a>

A new effective-dated rate. When a rate for the same scheme and state is open, it ends the day before `effective_from`.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `scheme` | yes | string | no | - | - |
| `state_code` | no | string | yes | minLength=2, maxLength=10 | - |
| `effective_from` | yes | string(date) | no | - | - |
| `parameters` | yes | object | no | - | - |
| `notes` | no | string | yes | maxLength=2000 | - |

## StatutoryRateRead
<a id="statutoryrateread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `scheme` | yes | string | no | - | - |
| `state_code` | yes | string | yes | - | - |
| `effective_from` | yes | string(date) | no | - | - |
| `effective_to` | yes | string(date) | yes | - | - |
| `parameters` | yes | object | no | - | - |
| `notes` | yes | string | yes | - | - |
| `is_seeded` | yes | boolean | no | - | - |
| `verified` | yes | boolean | no | - | - |
| `verified_at` | yes | string | yes | - | - |
| `verified_by_user_id` | yes | string(uuid) | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `StatutoryRateCreate`: `company_id`, `created_at`, `effective_to`, `id`, `is_seeded`, `updated_at`, `verified`, `verified_at`, `verified_by_user_id`, `version`

## StatutoryRateUpdate
<a id="statutoryrateupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `parameters` | no | object | yes | - | - |
| `notes` | no | string | yes | maxLength=2000 | - |

