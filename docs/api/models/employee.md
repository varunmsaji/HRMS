# Data models - employee

Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list (for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "Server-generated" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart (derived by name match - an inference, not a declared flag).

## AssignmentCreate
<a id="assignmentcreate"></a>

Creates a new effective-dated assignment row — covers initial placement, transfer, promotion, and manager change alike; all are the same insert-a-new-row operation, distinguished only by `change_type` (plan §9). Every organisational reference field is optional here even though `branch_id`/`department_id`/`designation_id` are mandatory for an employee's very first assignment — when a current row exists, an omitted field carries forward unchanged from it (`03_EMPLOYEE_API_PLAN.md` §2.2); the "required on first row" rule is therefore enforced in the service, not this schema (plan §14.3).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | yes | string(date) | no | - | - |
| `change_type` | yes | enum `INITIAL`/`TRANSFER`/`PROMOTION`/`MANAGER_CHANGE`/`SHIFT_CHANGE` | no | - | - |
| `change_reason` | no | string | yes | - | - |
| `branch_id` | no | string(uuid) | yes | - | - |
| `department_id` | no | string(uuid) | yes | - | - |
| `designation_id` | no | string(uuid) | yes | - | - |
| `grade_id` | no | string(uuid) | yes | - | - |
| `reporting_manager_id` | no | string(uuid) | yes | - | - |
| `dotted_line_manager_id` | no | string(uuid) | yes | - | - |
| `cost_centre_id` | no | string(uuid) | yes | - | - |
| `shift_id` | no | string(uuid) | yes | - | - |
| `work_location_type` | no | enum `OFFICE`/`WFH`/`HYBRID`/`FIELD` | yes | - | - |

## AssignmentRead
<a id="assignmentread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `branch_id` | yes | string(uuid) | yes | - | - |
| `department_id` | yes | string(uuid) | yes | - | - |
| `designation_id` | yes | string(uuid) | yes | - | - |
| `grade_id` | yes | string(uuid) | yes | - | - |
| `reporting_manager_id` | yes | string(uuid) | yes | - | - |
| `dotted_line_manager_id` | yes | string(uuid) | yes | - | - |
| `cost_centre_id` | yes | string(uuid) | yes | - | - |
| `shift_id` | yes | string(uuid) | yes | - | - |
| `work_location_type` | yes | string | yes | - | - |
| `change_type` | yes | string | yes | - | - |
| `change_reason` | yes | string | yes | - | - |
| `effective_from` | yes | string(date) | no | - | - |
| `effective_to` | yes | string(date) | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `AssignmentCreate`: `company_id`, `created_at`, `effective_to`, `employee_id`, `id`, `updated_at`, `version`

## BankCreate
<a id="bankcreate"></a>

Creates a new effective-dated bank row — closes the employee's current row (if any) and inserts a new one, mirroring `StatutoryCreate`'s write shape. Unlike Statutory, no `revision_reason` field — no source document requires one for Banking (`docs/modules/employee/33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` §5/§13). `is_primary`/`verification_status`/`penny_drop_reference` are deliberately absent — system-managed, never client-writable (plan §13).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | yes | string(date) | no | - | - |
| `account_holder_name` | no | string | yes | maxLength=150 | - |
| `account_number_enc` | no | string | yes | - | - |
| `bank_name` | no | string | yes | maxLength=150 | - |
| `ifsc` | no | string | yes | maxLength=15 | - |
| `branch_name` | no | string | yes | maxLength=150 | - |
| `payment_mode` | yes | enum `BANK`/`CASH`/`CHEQUE`/`UPI` | no | - | - |

## BankRead
<a id="bankread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `effective_from` | yes | string(date) | no | - | - |
| `effective_to` | yes | string(date) | yes | - | - |
| `account_holder_name` | yes | string | yes | - | - |
| `account_number_enc` | yes | string | yes | - | - |
| `bank_name` | yes | string | yes | - | - |
| `ifsc` | yes | string | yes | - | - |
| `branch_name` | yes | string | yes | - | - |
| `payment_mode` | yes | string | yes | - | - |
| `is_primary` | yes | boolean | no | - | - |
| `verification_status` | yes | string | no | - | - |
| `penny_drop_reference` | yes | string | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `BankCreate`: `company_id`, `created_at`, `effective_to`, `employee_id`, `id`, `is_primary`, `penny_drop_reference`, `updated_at`, `verification_status`, `version`

## CompensationCreate
<a id="compensationcreate"></a>

Creates a new effective-dated compensation row — closes the employee's current row (if any) and inserts a new one. Unlike `AssignmentCreate`, no field carries forward from the current row: `annual_ctc_minor`, `currency`, `revision_type`, and `revision_reason` are always required, on every write, including an employee's very first compensation row (plan §17.2/§17.3) — a stale CTC carried forward by omission is a materially worse failure mode than a stale org-placement field.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | yes | string(date) | no | - | - |
| `annual_ctc_minor` | yes | integer | no | max=10000000000000.0, >=0.0 | - |
| `currency` | yes | string | no | pattern=`^[A-Z]{3}$` | - |
| `revision_type` | yes | enum `JOINING`/`ANNUAL`/`PROMOTION`/`CORRECTION`/`MARKET` | no | - | - |
| `revision_reason` | yes | string | no | minLength=1, maxLength=1000 | - |

## CompensationRead
<a id="compensationread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `annual_ctc_minor` | yes | integer | no | - | - |
| `currency` | yes | string | no | - | - |
| `revision_type` | yes | string | no | - | - |
| `revision_reason` | yes | string | yes | - | - |
| `effective_from` | yes | string(date) | no | - | - |
| `effective_to` | yes | string(date) | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `CompensationCreate`: `company_id`, `created_at`, `effective_to`, `employee_id`, `id`, `updated_at`, `version`

## EmployeeConfirmInput
<a id="employeeconfirminput"></a>

`POST /employees/{id}/confirm` — transitions `PROBATION` -> `ACTIVE`. No fields: unlike `EmploymentTerminate` (which needs `last_working_day`), confirmation needs no input at all — the before/after `Employee.status` values in the audit record are the entire story. Kept as an explicit (empty) body model rather than no body, matching every other action in this router.

_No properties (free-form or alias)._

## EmployeeCreate
<a id="employeecreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `first_name` | yes | string | no | minLength=1, maxLength=100 | - |
| `middle_name` | no | string | yes | maxLength=100 | - |
| `last_name` | no | string | yes | maxLength=100 | - |
| `date_of_birth` | no | string(date) | yes | - | - |
| `gender` | no | string | yes | maxLength=20 | - |
| `blood_group` | no | string | yes | maxLength=10 | - |
| `marital_status` | no | string | yes | maxLength=20 | - |
| `nationality` | no | string | yes | maxLength=80 | - |
| `father_or_husband_name` | no | string | yes | maxLength=150 | - |
| `personal_email` | no | string | yes | maxLength=255 | - |
| `personal_mobile` | no | string | yes | maxLength=20, pattern=`^\+?[0-9][0-9 ()\-]{5,18}[0-9]$` | - |
| `present_address_line1` | no | string | yes | maxLength=200 | - |
| `present_address_line2` | no | string | yes | maxLength=200 | - |
| `present_city` | no | string | yes | maxLength=100 | - |
| `present_state_code` | no | string | yes | maxLength=10 | - |
| `present_pincode` | no | string | yes | maxLength=10, pattern=`^[A-Za-z0-9][A-Za-z0-9 \-]{1,8}[A-Za-z0-9]$` | - |
| `present_country_code` | no | string | yes | minLength=2, maxLength=2, pattern=`^[A-Za-z]{2}$` | - |
| `permanent_address_line1` | no | string | yes | maxLength=200 | - |
| `permanent_address_line2` | no | string | yes | maxLength=200 | - |
| `permanent_city` | no | string | yes | maxLength=100 | - |
| `permanent_state_code` | no | string | yes | maxLength=10 | - |
| `permanent_pincode` | no | string | yes | maxLength=10, pattern=`^[A-Za-z0-9][A-Za-z0-9 \-]{1,8}[A-Za-z0-9]$` | - |
| `permanent_country_code` | no | string | yes | minLength=2, maxLength=2, pattern=`^[A-Za-z]{2}$` | - |
| `permanent_same_as_present` | no | boolean | no | default=`true` | - |
| `emergency_contact_name` | no | string | yes | maxLength=150 | - |
| `emergency_contact_relationship` | no | string | yes | maxLength=50 | - |
| `emergency_contact_phone` | no | string | yes | maxLength=20, pattern=`^\+?[0-9][0-9 ()\-]{5,18}[0-9]$` | - |
| `photo_url` | no | string | yes | - | - |
| `custom_fields` | no | object | yes | - | - |

## EmployeeDependentCreate
<a id="employeedependentcreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `full_name` | yes | string | no | minLength=1, maxLength=150 | - |
| `relationship` | yes | string | no | minLength=1, maxLength=50 | - |
| `date_of_birth` | no | string(date) | yes | - | - |
| `gender` | no | string | yes | maxLength=20 | - |
| `is_minor` | no | boolean | no | default=`false` | - |
| `guardian_name` | no | string | yes | maxLength=150 | - |
| `guardian_relationship` | no | string | yes | maxLength=50 | - |
| `aadhaar_number_enc` | no | string | yes | minLength=12, maxLength=12 | - |
| `is_pf_nominee` | no | boolean | no | default=`false` | - |
| `pf_nominee_share_percentage` | no | number | yes | max=100.0, >=0.0 | - |
| `is_gratuity_nominee` | no | boolean | no | default=`false` | - |
| `gratuity_nominee_share_percentage` | no | number | yes | max=100.0, >=0.0 | - |
| `is_esi_dependent` | no | boolean | no | default=`false` | - |
| `document_id` | no | string(uuid) | yes | - | - |

## EmployeeDependentRead
<a id="employeedependentread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `full_name` | yes | string | no | - | - |
| `relationship` | yes | string | no | - | - |
| `date_of_birth` | yes | string(date) | yes | - | - |
| `gender` | yes | string | yes | - | - |
| `is_minor` | yes | boolean | no | - | - |
| `guardian_name` | yes | string | yes | - | - |
| `guardian_relationship` | yes | string | yes | - | - |
| `aadhaar_number_enc` | yes | string | yes | - | - |
| `is_pf_nominee` | yes | boolean | no | - | - |
| `pf_nominee_share_percentage` | yes | number | yes | - | - |
| `is_gratuity_nominee` | yes | boolean | no | - | - |
| `gratuity_nominee_share_percentage` | yes | number | yes | - | - |
| `is_esi_dependent` | yes | boolean | no | - | - |
| `document_id` | yes | string(uuid) | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `EmployeeDependentCreate`: `company_id`, `created_at`, `employee_id`, `id`, `updated_at`, `version`

## EmployeeDocumentRead
<a id="employeedocumentread"></a>

Deliberately excludes `s3_key`/`source_onboarding_document_id` — internal storage/ provenance details, never returned to a caller.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `document_type` | yes | string | no | - | - |
| `original_filename` | yes | string | no | - | - |
| `content_type` | yes | string | no | - | - |
| `size_bytes` | yes | integer | no | - | - |
| `status` | yes | string | no | - | - |
| `verified_by_user_id` | yes | string(uuid) | yes | - | - |
| `verified_at` | yes | string | yes | - | - |
| `rejection_reason` | yes | string | yes | - | - |
| `uploaded_at` | yes | string | no | - | - |

## EmployeeDocumentReviewRequest
<a id="employeedocumentreviewrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `status` | yes | enum `VERIFIED`/`REJECTED` | no | - | - |
| `rejection_reason` | no | string | yes | - | - |

## EmployeeDocumentWithUrlRead
<a id="employeedocumentwithurlread"></a>

Adds the short-lived presigned GET URL — document bytes never round-trip through the API server. Returned to every caller who can list documents at all (HR/Admin and the SELF-scoped employee alike): unlike onboarding's candidate-facing `list_documents` (no URL, because an unreviewed candidate upload might still be replaced), every viewer here is already permitted to download what they can see.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `document_type` | yes | string | no | - | - |
| `original_filename` | yes | string | no | - | - |
| `content_type` | yes | string | no | - | - |
| `size_bytes` | yes | integer | no | - | - |
| `status` | yes | string | no | - | - |
| `verified_by_user_id` | yes | string(uuid) | yes | - | - |
| `verified_at` | yes | string | yes | - | - |
| `rejection_reason` | yes | string | yes | - | - |
| `uploaded_at` | yes | string | no | - | - |
| `download_url` | yes | string | no | - | - |

## EmployeeEducationCreate
<a id="employeeeducationcreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `qualification` | yes | string | no | minLength=1, maxLength=150 | - |
| `institution_name` | no | string | yes | maxLength=200 | - |
| `year_of_passing` | no | integer | yes | min=1950.0, max=2100.0 | - |
| `document_id` | no | string(uuid) | yes | - | - |

## EmployeeEducationRead
<a id="employeeeducationread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `qualification` | yes | string | no | - | - |
| `institution_name` | yes | string | yes | - | - |
| `year_of_passing` | yes | integer | yes | - | - |
| `document_id` | yes | string(uuid) | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `EmployeeEducationCreate`: `company_id`, `created_at`, `employee_id`, `id`, `updated_at`, `version`

## EmployeeExperienceCreate
<a id="employeeexperiencecreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `company_name` | yes | string | no | minLength=1, maxLength=200 | - |
| `designation` | no | string | yes | maxLength=150 | - |
| `from_date` | yes | string(date) | no | - | - |
| `to_date` | no | string(date) | yes | - | - |
| `last_ctc_minor` | no | integer | yes | min=0.0, max=10000000000000.0 | - |
| `reason_for_leaving` | no | string | yes | - | - |
| `had_prior_pf_membership` | no | boolean | no | default=`false` | - |
| `previous_uan` | no | string | yes | maxLength=20 | - |
| `previous_pf_account_number` | no | string | yes | maxLength=30 | - |
| `previous_esi_ip_number` | no | string | yes | maxLength=30 | - |
| `document_id` | no | string(uuid) | yes | - | - |

## EmployeeExperienceRead
<a id="employeeexperienceread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `company_name` | yes | string | no | - | - |
| `designation` | yes | string | yes | - | - |
| `from_date` | yes | string(date) | no | - | - |
| `to_date` | yes | string(date) | yes | - | - |
| `last_ctc_minor` | yes | integer | yes | - | - |
| `reason_for_leaving` | yes | string | yes | - | - |
| `had_prior_pf_membership` | yes | boolean | no | - | - |
| `previous_uan` | yes | string | yes | - | - |
| `previous_pf_account_number` | yes | string | yes | - | - |
| `previous_esi_ip_number` | yes | string | yes | - | - |
| `document_id` | yes | string(uuid) | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `EmployeeExperienceCreate`: `company_id`, `created_at`, `employee_id`, `id`, `updated_at`, `version`

## EmployeeIdentityRead
<a id="employeeidentityread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `pan_number` | yes | string | yes | - | - |
| `aadhaar_number` | yes | string | yes | - | - |
| `uan_number` | yes | string | yes | - | - |
| `father_or_husband_name` | yes | string | yes | - | - |
| `version` | yes | integer | no | - | - |

Server-generated / read-only vs `EmployeeIdentityUpdate`: `employee_id`, `version`

## EmployeeIdentityUpdate
<a id="employeeidentityupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `pan_number` | no | string | yes | minLength=10, maxLength=10 | - |
| `aadhaar_number` | no | string | yes | minLength=12, maxLength=12 | - |
| `uan_number` | no | string | yes | maxLength=20 | - |
| `father_or_husband_name` | no | string | yes | maxLength=150 | - |

## EmployeeRead
<a id="employeeread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_code` | yes | string | no | - | - |
| `first_name` | yes | string | no | - | - |
| `middle_name` | yes | string | yes | - | - |
| `last_name` | yes | string | yes | - | - |
| `display_name` | yes | string | yes | - | - |
| `date_of_birth` | yes | string(date) | yes | - | - |
| `gender` | yes | string | yes | - | - |
| `blood_group` | yes | string | yes | - | - |
| `marital_status` | yes | string | yes | - | - |
| `nationality` | yes | string | yes | - | - |
| `father_or_husband_name` | yes | string | yes | - | - |
| `personal_email` | yes | string | yes | - | - |
| `personal_mobile` | yes | string | yes | - | - |
| `present_address_line1` | yes | string | yes | - | - |
| `present_address_line2` | yes | string | yes | - | - |
| `present_city` | yes | string | yes | - | - |
| `present_state_code` | yes | string | yes | - | - |
| `present_pincode` | yes | string | yes | - | - |
| `present_country_code` | yes | string | yes | - | - |
| `permanent_address_line1` | yes | string | yes | - | - |
| `permanent_address_line2` | yes | string | yes | - | - |
| `permanent_city` | yes | string | yes | - | - |
| `permanent_state_code` | yes | string | yes | - | - |
| `permanent_pincode` | yes | string | yes | - | - |
| `permanent_country_code` | yes | string | yes | - | - |
| `permanent_same_as_present` | yes | boolean | no | - | - |
| `emergency_contact_name` | yes | string | yes | - | - |
| `emergency_contact_relationship` | yes | string | yes | - | - |
| `emergency_contact_phone` | yes | string | yes | - | - |
| `photo_url` | yes | string | yes | - | - |
| `status` | yes | string | no | - | - |
| `custom_fields` | yes | object | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |
| `employment_joining_date` | no | string(date) | yes | - | - |
| `employment_last_working_day` | no | string(date) | yes | - | - |

Server-generated / read-only vs `EmployeeCreate`: `company_id`, `created_at`, `display_name`, `employee_code`, `employment_joining_date`, `employment_last_working_day`, `id`, `is_active`, `status`, `updated_at`, `version`

## EmployeeUpdate
<a id="employeeupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `first_name` | no | string | yes | minLength=1, maxLength=100 | - |
| `middle_name` | no | string | yes | maxLength=100 | - |
| `last_name` | no | string | yes | maxLength=100 | - |
| `date_of_birth` | no | string(date) | yes | - | - |
| `gender` | no | string | yes | maxLength=20 | - |
| `blood_group` | no | string | yes | maxLength=10 | - |
| `marital_status` | no | string | yes | maxLength=20 | - |
| `nationality` | no | string | yes | maxLength=80 | - |
| `father_or_husband_name` | no | string | yes | maxLength=150 | - |
| `personal_email` | no | string | yes | maxLength=255 | - |
| `personal_mobile` | no | string | yes | maxLength=20, pattern=`^\+?[0-9][0-9 ()\-]{5,18}[0-9]$` | - |
| `present_address_line1` | no | string | yes | maxLength=200 | - |
| `present_address_line2` | no | string | yes | maxLength=200 | - |
| `present_city` | no | string | yes | maxLength=100 | - |
| `present_state_code` | no | string | yes | maxLength=10 | - |
| `present_pincode` | no | string | yes | maxLength=10, pattern=`^[A-Za-z0-9][A-Za-z0-9 \-]{1,8}[A-Za-z0-9]$` | - |
| `present_country_code` | no | string | yes | minLength=2, maxLength=2, pattern=`^[A-Za-z]{2}$` | - |
| `permanent_address_line1` | no | string | yes | maxLength=200 | - |
| `permanent_address_line2` | no | string | yes | maxLength=200 | - |
| `permanent_city` | no | string | yes | maxLength=100 | - |
| `permanent_state_code` | no | string | yes | maxLength=10 | - |
| `permanent_pincode` | no | string | yes | maxLength=10, pattern=`^[A-Za-z0-9][A-Za-z0-9 \-]{1,8}[A-Za-z0-9]$` | - |
| `permanent_country_code` | no | string | yes | minLength=2, maxLength=2, pattern=`^[A-Za-z]{2}$` | - |
| `permanent_same_as_present` | no | boolean | yes | - | - |
| `emergency_contact_name` | no | string | yes | maxLength=150 | - |
| `emergency_contact_relationship` | no | string | yes | maxLength=50 | - |
| `emergency_contact_phone` | no | string | yes | maxLength=20, pattern=`^\+?[0-9][0-9 ()\-]{5,18}[0-9]$` | - |
| `photo_url` | no | string | yes | - | - |
| `custom_fields` | no | object | yes | - | - |
| `is_active` | no | boolean | yes | - | - |

## EmploymentCreate
<a id="employmentcreate"></a>

Creates a new employment episode for an existing employee — covers both a first hire (no prior employment rows) and a rehire (at least one prior, necessarily `TERMINATED`, episode exists). The distinction is not client-supplied: `previous_employment_id` is always computed server-side from the employee's own employment history, never accepted as input (`status`/`version` are likewise system-set, never client-settable). `probation_end_date` is optional and purely informational — nothing reads or auto-computes it; the actual `PROBATION` -> `ACTIVE` transition is the explicit `confirm` action, never gated by this date.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `legal_entity_id` | yes | string(uuid) | no | - | - |
| `joining_date` | yes | string(date) | no | - | - |
| `probation_end_date` | no | string(date) | yes | - | - |
| `pay_basis` | no | enum `MONTHLY`/`DAILY_WAGE` | no | default=`"MONTHLY"` | - |

## EmploymentRead
<a id="employmentread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `legal_entity_id` | yes | string(uuid) | no | - | - |
| `joining_date` | yes | string(date) | no | - | - |
| `last_working_day` | yes | string(date) | yes | - | - |
| `probation_end_date` | yes | string(date) | yes | - | - |
| `pay_basis` | yes | string | no | - | - |
| `status` | yes | string | no | - | - |
| `previous_employment_id` | yes | string(uuid) | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `EmploymentCreate`: `company_id`, `created_at`, `employee_id`, `id`, `last_working_day`, `previous_employment_id`, `status`, `updated_at`, `version`

## EmploymentTerminate
<a id="employmentterminate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `last_working_day` | yes | string(date) | no | - | - |

## EmploymentUpdate
<a id="employmentupdate"></a>

Only `legal_entity_id` and `probation_end_date` are correctable post-creation. `joining_date` is a historical fact once recorded (no document states it is ever legitimately revised, and every other slice in this codebase treats a spell's start as immutable); `status`/`last_working_day` only ever change via the dedicated `terminate` action, never a generic field patch — this keeps the one-way `ACTIVE` → `TERMINATED` transition from being reachable through an unvalidated arbitrary-field update. `probation_end_date` is the one exception to "immutable once set": it's purely informational bookkeeping, not a fact anything downstream depends on, so HR correcting it carries none of `joining_date`'s risk.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `legal_entity_id` | no | string(uuid) | yes | - | - |
| `probation_end_date` | no | string(date) | yes | - | - |
| `pay_basis` | no | enum `MONTHLY`/`DAILY_WAGE` | yes | - | - |

## StatutoryCreate
<a id="statutorycreate"></a>

Creates a new effective-dated statutory row — closes the employee's current row (if any) and inserts a new one, mirroring `CompensationCreate` exactly: no field carries forward from the current row, `revision_reason` is required on every write (plan §16/§27 item 7), including an employee's very first statutory row.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | yes | string(date) | no | - | - |
| `is_pf_applicable` | yes | boolean | no | - | - |
| `pf_number` | no | string | yes | maxLength=30 | - |
| `pf_wage_ceiling_opt_out` | no | boolean | no | default=`false` | - |
| `vpf_amount` | no | integer | yes | min=0.0, max=10000000000000.0 | - |
| `vpf_percentage` | no | number | yes | min=0.0, max=100.0 | - |
| `is_esi_applicable` | yes | boolean | no | - | - |
| `esi_ip_number` | no | string | yes | maxLength=30 | - |
| `pt_state_code` | no | string | yes | maxLength=10 | - |
| `is_lwf_applicable` | yes | boolean | no | - | - |
| `tax_regime` | yes | enum `OLD`/`NEW` | no | - | - |
| `is_director` | no | boolean | no | default=`false` | - |
| `is_international_worker` | no | boolean | no | default=`false` | - |
| `revision_reason` | yes | string | no | minLength=1, maxLength=1000 | - |

## StatutoryRead
<a id="statutoryread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `effective_from` | yes | string(date) | no | - | - |
| `effective_to` | yes | string(date) | yes | - | - |
| `is_pf_applicable` | yes | boolean | no | - | - |
| `pf_number` | yes | string | yes | - | - |
| `pf_wage_ceiling_opt_out` | yes | boolean | no | - | - |
| `vpf_amount` | yes | integer | yes | - | - |
| `vpf_percentage` | yes | number | yes | - | - |
| `is_esi_applicable` | yes | boolean | no | - | - |
| `esi_ip_number` | yes | string | yes | - | - |
| `pt_state_code` | yes | string | yes | - | - |
| `is_lwf_applicable` | yes | boolean | no | - | - |
| `tax_regime` | yes | string | yes | - | - |
| `is_director` | yes | boolean | no | - | - |
| `is_international_worker` | yes | boolean | no | - | - |
| `revision_reason` | yes | string | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `StatutoryCreate`: `company_id`, `created_at`, `effective_to`, `employee_id`, `id`, `updated_at`, `version`

