# String vocabularies declared only in validators (generated)

The OpenAPI schema types these fields as `string`. The tuples below are module-level constants in each module's `schemas.py` / `models.py` / `service.py` that validators or DB check constraints use. **Which request/response field consumes which constant is not mapped here** - match by name (e.g. `_PUNCH_DIRECTIONS` -> `direction`) and confirm in the linked source.

## account_invite

| Constant | File | Values |
|---|---|---|
| `ASSIGNABLE_ROLE_CODES` | `account_invite/service.py` | `COMPANY_ADMIN`, `HR_ADMIN`, `REPORTING_MANAGER`, `BRANCH_MANAGER`, `EMPLOYEE` |

## attendance

| Constant | File | Values |
|---|---|---|
| `ENROLLMENT_UNCOUNTED_DECISIONS` | `attendance/repository.py` | `PROVIDER_ERROR`, `LIVENESS_ERROR` |
| `FACE_PUNCH_REJECTION_REASONS` | `attendance/face_service.py` | `AMBIGUOUS_FACE`, `CAPTURE_REPLAYED`, `CHALLENGE_REJECTED`, `IDENTITY_INCONSISTENT`, `LIVENESS_ERROR`, `LIVENESS_INCONCLUSIVE`, `NOT_ENROLLED`, `NO_FACE`, `NO_MATCH`, `PROVIDER_ERROR`, `SPOOF_SUSPECTED` |
| `INFRASTRUCTURE_FAILURE_DECISIONS` | `attendance/repository.py` | `PROVIDER_ERROR`, `LIVENESS_ERROR` |
| `_APPROVAL_CHAINS` | `attendance/schemas.py` | `AUTO`, `MANAGER`, `MANAGER_THEN_HR`, `HR` |
| `_APPROVAL_STAGES` | `attendance/schemas.py` | `MANAGER`, `HR` |
| `_ATTENDANCE_PERIOD_BLOCKING_REASON_CODES` | `attendance/schemas.py` | `EMPLOYEES_WITHOUT_ATTENDANCE`, `CONFIG_ERROR`, `INCOMPLETE_ATTENDANCE`, `PENDING_REGULARIZATION`, `PENDING_OVERTIME_APPROVAL`, `UNPUBLISHED_ROSTER` |
| `_ATTENDANCE_PERIOD_STATUSES` | `attendance/schemas.py` | `OPEN`, `CLOSED` |
| `_ATTENDANCE_PERIOD_VALIDATION_STATUSES` | `attendance/schemas.py` | `READY`, `BLOCKED` |
| `_ATTENDANCE_STATUSES` | `attendance/schemas.py` | `NOT_JOINED`, `EXITED`, `NOT_EXPECTED`, `PRESENT`, `HALF_DAY`, `ABSENT`, `LEAVE`, `ON_DUTY`, `WFH`, `INCOMPLETE`, `CONFIG_ERROR` |
| `_CORE_HOURS_BREACH_BEHAVIOURS` | `attendance/schemas.py` | `IGNORE`, `FLAG`, `HALF_DAY`, `ABSENT` |
| `_DAILY_WAGE_PAID_HOLIDAY_TYPES` | `attendance/calculation.py` | `PUBLIC`, `SUBSTITUTE` |
| `_DAY_CLASSES` | `attendance/schemas.py` | `NORMAL`, `WEEKLY_OFF`, `HOLIDAY`, `NIGHT` |
| `_EARLY_CLASSIFICATIONS` | `attendance/schemas.py` | `NONE`, `EARLY_DEPARTURE`, `HALF_DAY`, `ABSENT` |
| `_EXCESS_BREAK_BEHAVIOURS` | `attendance/schemas.py` | `IGNORE`, `DEDUCT`, `FLAG`, `REQUIRE_APPROVAL` |
| `_HALF_DAY_SPLITS` | `attendance/schemas.py` | `BY_HOURS`, `BY_MIDPOINT` |
| `_HOUR_BAND_STATUSES` | `attendance/schemas.py` | `PRESENT`, `HALF_DAY`, `ABSENT` |
| `_INCOMPLETE_AT_LOCK_BEHAVIOURS` | `attendance/schemas.py` | `TREAT_ABSENT`, `TREAT_PRESENT`, `KEEP_INCOMPLETE` |
| `_LATE_CLASSIFICATIONS` | `attendance/schemas.py` | `NONE`, `LATE`, `HALF_DAY`, `ABSENT` |
| `_LEAVE_PROJECTION_HALVES` | `attendance/schemas.py` | `FIRST`, `SECOND` |
| `_MISSING_PUNCH_BEHAVIOURS` | `attendance/schemas.py` | `INCOMPLETE`, `ABSENT`, `AUTO_CLOSE`, `REQUIRE_REGULARIZATION` |
| `_MISSING_SHIFT_BEHAVIOURS` | `attendance/schemas.py` | `INCOMPLETE`, `ABSENT` |
| `_MULTI_PUNCH_MODES` | `attendance/schemas.py` | `PAIR_ALL`, `FIRST_IN_LAST_OUT` |
| `_NIGHT_OT_MODES` | `attendance/schemas.py` | `SHIFT_FLAG`, `WINDOW`, `BOTH` |
| `_OT_ELIGIBILITY` | `attendance/schemas.py` | `SHIFT_FLAG`, `ALWAYS`, `NEVER`, `GRADE_VIA_ASSIGNMENT` |
| `_OT_ROUNDING_MODES` | `attendance/schemas.py` | `NONE`, `NEAREST`, `UP`, `DOWN` |
| `_OVERTIME_ACTIONS` | `attendance/schemas.py` | `DETECTED`, `APPROVER_UNRESOLVED`, `AUTO_APPROVED`, `STAGE_APPROVED`, `APPROVED`, `REJECTED` |
| `_OVERTIME_RECORD_STATUSES` | `attendance/schemas.py` | `PENDING`, `AUTO_APPROVED`, `APPROVED`, `REJECTED` |
| `_POLICY_RESOLUTION_KINDS` | `attendance/schemas.py` | `ATTENDANCE_POLICY`, `OVERTIME_POLICY`, `REGULARIZATION_POLICY` |
| `_PUNCH_DIRECTIONS` | `attendance/schemas.py` | `IN`, `OUT` |
| `_PUNCH_ROUNDING` | `attendance/schemas.py` | `NONE`, `NEAREST`, `UP`, `DOWN` |
| `_PUNCH_SOURCES` | `attendance/schemas.py` | `WEB`, `MOBILE`, `DEVICE`, `IMPORT`, `ADMIN`, `API`, `REGULARIZATION`, `FACE` |
| `_REGULARIZATION_ACTIONS` | `attendance/schemas.py` | `SUBMITTED`, `APPROVER_UNRESOLVED`, `STAGE_APPROVED`, `APPROVED`, `REJECTED`, `CANCELLED`, `APPLIED` |
| `_REGULARIZATION_STATUSES` | `attendance/schemas.py` | `SUBMITTED`, `APPROVED`, `REJECTED`, `CANCELLED` |
| `_REGULARIZATION_TYPES` | `attendance/schemas.py` | `MISSING_PUNCH`, `WRONG_PUNCH`, `WRONG_SHIFT`, `WRONG_STATUS`, `WFH`, `ON_DUTY`, `EXCESS_BREAK`, `FULL_DAY`, `EARLY_DEPARTURE_APPROVAL` |
| `_RESOLUTION_KINDS` | `attendance/router.py` | `ATTENDANCE_POLICY`, `OVERTIME_POLICY`, `REGULARIZATION_POLICY` |
| `_ROSTER_STATUSES` | `attendance/schemas.py` | `DRAFT`, `PUBLISHED` |
| `_SPLIT_SHIFT_MISSED_BLOCK_BEHAVIOURS` | `attendance/schemas.py` | `IGNORE`, `HALF_DAY`, `ABSENT`, `REQUIRE_REGULARIZATION` |
| `_WORK_ON_LEAVE_BEHAVIOURS` | `attendance/schemas.py` | `KEEP_LEAVE`, `PRESENT_CANCEL_LEAVE_HINT` |

## employee

| Constant | File | Values |
|---|---|---|
| `ASSIGNMENT_CHANGE_TYPE_VALUES` | `employee/schemas.py` | `INITIAL`, `TRANSFER`, `PROMOTION`, `MANAGER_CHANGE`, `SHIFT_CHANGE` |
| `EMPLOYEE_DOCUMENT_STATUS_VALUES` | `employee/schemas.py` | `PENDING`, `VERIFIED`, `REJECTED` |
| `EMPLOYEE_DOCUMENT_TYPES` | `employee/schemas.py` | `PHOTO`, `PAN`, `AADHAAR`, `ADDRESS_PROOF`, `EDUCATION_CERTIFICATE`, `PREVIOUS_EMPLOYMENT_PROOF`, `BANK_PROOF`, `OTHER` |
| `EMPLOYEE_DOCUMENT_TYPES` | `employee/service.py` | `PHOTO`, `PAN`, `AADHAAR`, `ADDRESS_PROOF`, `EDUCATION_CERTIFICATE`, `PREVIOUS_EMPLOYMENT_PROOF`, `BANK_PROOF`, `OTHER` |
| `EMPLOYEE_STATUS_VALUES` | `employee/schemas.py` | `PRE_JOINING`, `PROBATION`, `ACTIVE`, `ON_NOTICE`, `SUSPENDED`, `ON_LONG_LEAVE`, `EXITED`, `ABSCONDING`, `RETIRED`, `DECEASED` |
| `EMPLOYMENT_STATUS_VALUES` | `employee/schemas.py` | `ACTIVE`, `TERMINATED` |
| `PAYMENT_MODE_VALUES` | `employee/schemas.py` | `BANK`, `CASH`, `CHEQUE`, `UPI` |
| `REVISION_TYPE_VALUES` | `employee/schemas.py` | `JOINING`, `ANNUAL`, `PROMOTION`, `CORRECTION`, `MARKET` |
| `TAX_REGIME_VALUES` | `employee/schemas.py` | `OLD`, `NEW` |
| `WORK_LOCATION_TYPE_VALUES` | `employee/schemas.py` | `OFFICE`, `WFH`, `HYBRID`, `FIELD` |

## leave

| Constant | File | Values |
|---|---|---|
| `LEAVE_YEAR_TYPES` | `leave/schemas.py` | `CALENDAR`, `FINANCIAL`, `ANNIVERSARY`, `CUSTOM` |
| `LEAVE_YEAR_TYPES` | `leave/year.py` | `CALENDAR`, `FINANCIAL`, `ANNIVERSARY`, `CUSTOM` |
| `STATUTORY_LEAVE_CATEGORIES` | `leave/schemas.py` | `EARNED`, `SICK`, `CASUAL`, `MATERNITY`, `PATERNITY` |
| `_ACCRUAL_FREQUENCIES` | `leave/schemas.py` | `NONE`, `MONTHLY`, `YEARLY` |
| `_APPROVAL_CHAINS` | `leave/schemas.py` | `AUTO`, `MANAGER`, `MANAGER_THEN_HR`, `MANAGER_THEN_HOD_THEN_HR`, `HR` |
| `_HALF_DAY_VALUES` | `leave/schemas.py` | `FIRST_HALF`, `SECOND_HALF` |
| `_LEDGER_ENTRY_TYPES` | `leave/schemas.py` | `ACCRUAL`, `APPLICATION`, `ADJUSTMENT`, `ENCASHMENT`, `CARRY_FORWARD`, `COMP_OFF_CREDIT` |
| `_YEAR_END_ACTIONS` | `leave/schemas.py` | `CARRY_FORWARD`, `LAPSE`, `ENCASH_EXCESS` |

## onboarding

| Constant | File | Values |
|---|---|---|
| `ONBOARDING_CASE_INVITABLE_STATUSES` | `onboarding/service.py` | `DRAFT`, `EXPIRED`, `INVITED`, `IN_PROGRESS`, `ACTIVATED` |
| `ONBOARDING_CASE_REVIEWABLE_STATUSES` | `onboarding/schemas.py` | `SUBMITTED`, `UNDER_REVIEW` |
| `ONBOARDING_CASE_REVIEWABLE_STATUSES` | `onboarding/service.py` | `SUBMITTED`, `UNDER_REVIEW` |
| `ONBOARDING_CASE_STATUS_VALUES` | `onboarding/schemas.py` | `DRAFT`, `INVITED`, `IN_PROGRESS`, `SUBMITTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED`, `VERIFIED`, `ACTIVATED`, `EXPIRED`, `CANCELLED` |
| `ONBOARDING_CASE_TERMINAL_STATUSES` | `onboarding/repository.py` | `ACTIVATED`, `EXPIRED`, `CANCELLED` |
| `ONBOARDING_CASE_TERMINAL_STATUSES` | `onboarding/schemas.py` | `ACTIVATED`, `EXPIRED`, `CANCELLED` |
| `ONBOARDING_CASE_WRITABLE_STATUSES` | `onboarding/schemas.py` | `INVITED`, `IN_PROGRESS`, `CHANGES_REQUESTED` |
| `ONBOARDING_CASE_WRITABLE_STATUSES` | `onboarding/service.py` | `INVITED`, `IN_PROGRESS`, `CHANGES_REQUESTED` |
| `ONBOARDING_DOCUMENT_STATUS_VALUES` | `onboarding/schemas.py` | `PENDING`, `VERIFIED`, `REJECTED` |
| `ONBOARDING_DOCUMENT_TYPES` | `onboarding/schemas.py` | `PHOTO`, `PAN`, `AADHAAR`, `ADDRESS_PROOF`, `EDUCATION_CERTIFICATE`, `PREVIOUS_EMPLOYMENT_PROOF`, `BANK_PROOF`, `OTHER` |
| `ONBOARDING_DOCUMENT_TYPES` | `onboarding/service.py` | `PHOTO`, `PAN`, `AADHAAR`, `ADDRESS_PROOF`, `EDUCATION_CERTIFICATE`, `PREVIOUS_EMPLOYMENT_PROOF`, `BANK_PROOF`, `OTHER` |
| `ONBOARDING_SECTION_REVIEW_STATUS_VALUES` | `onboarding/schemas.py` | `PENDING`, `VERIFIED`, `REJECTED` |

## organisation

| Constant | File | Values |
|---|---|---|
| `_ATTENDANCE_POLICY_KINDS` | `organisation/router.py` | `ATTENDANCE_POLICY`, `OVERTIME_POLICY`, `REGULARIZATION_POLICY` |
| `_CALENDAR_DAY_TYPES` | `organisation/schemas.py` | `WORKING`, `WEEKLY_OFF`, `HOLIDAY`, `SPECIAL_WORKING`, `SHUTDOWN` |
| `_CALENDAR_EXCEPTION_TYPES` | `organisation/schemas.py` | `SPECIAL_WORKING`, `SHUTDOWN`, `SUBSTITUTE_HOLIDAY`, `CANCEL_HOLIDAY` |
| `_CALENDAR_POLICY_KINDS` | `organisation/router.py` | `WEEKLY_OFF`, `WORK_CALENDAR` |
| `_DAYS_OF_WEEK` | `organisation/schemas.py` | `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN` |
| `_HOLIDAY_CALENDAR_KINDS` | `organisation/schemas.py` | `NATIONAL`, `REGIONAL`, `COMPANY`, `LOCATION` |
| `_HOLIDAY_TYPES` | `organisation/schemas.py` | `PUBLIC`, `COMPANY`, `OPTIONAL`, `RESTRICTED`, `WORKING_HOLIDAY` |
| `_POLICY_KINDS` | `organisation/schemas.py` | `WORK_CALENDAR`, `WEEKLY_OFF`, `ATTENDANCE_POLICY`, `OVERTIME_POLICY`, `REGULARIZATION_POLICY`, `LEAVE_POLICY` |
| `_PRECEDENCE_SCOPES` | `organisation/calendar_resolution.py` | `EMPLOYEE`, `SHIFT`, `DESIGNATION`, `GRADE`, `DEPARTMENT`, `BRANCH`, `LEGAL_ENTITY`, `COMPANY` |
| `_SCOPE_TYPES` | `organisation/schemas.py` | `COMPANY`, `LEGAL_ENTITY`, `BRANCH`, `DEPARTMENT`, `GRADE`, `DESIGNATION`, `SHIFT`, `EMPLOYEE` |
| `_SHIFT_BREAK_KINDS` | `organisation/schemas.py` | `FIXED_WINDOW`, `FLEXIBLE_DURATION` |
| `_SHIFT_VERSION_TYPES` | `organisation/schemas.py` | `FIXED`, `FLEXIBLE`, `SPLIT` |
| `_TERMINAL_SUBSCRIPTION_STATUSES` | `organisation/repository.py` | `CANCELED`, `EXPIRED` |
| `_WEEKLY_OFF_PATTERN_KINDS` | `organisation/schemas.py` | `FIXED_WEEKDAYS`, `NTH_WEEKDAY`, `ALTERNATE`, `CUSTOM` |

## payroll

| Constant | File | Values |
|---|---|---|
| `APPLIES_WHEN` | `payroll/breakup.py` | `ALWAYS`, `PF_APPLICABLE`, `ESI_APPLICABLE` |
| `APPLIES_WHEN` | `payroll/schemas.py` | `ALWAYS`, `PF_APPLICABLE`, `ESI_APPLICABLE` |
| `CALCULATION_TYPES` | `payroll/breakup.py` | `FIXED`, `PERCENTAGE_OF_CTC`, `PERCENTAGE_OF_GROSS`, `PERCENTAGE_OF_COMPONENT`, `BALANCING` |
| `CALCULATION_TYPES` | `payroll/schemas.py` | `FIXED`, `PERCENTAGE_OF_CTC`, `PERCENTAGE_OF_GROSS`, `PERCENTAGE_OF_COMPONENT`, `BALANCING` |
| `COMPONENT_TYPES` | `payroll/breakup.py` | `EARNING`, `DEDUCTION`, `EMPLOYER_CONTRIBUTION` |
| `COMPONENT_TYPES` | `payroll/schemas.py` | `EARNING`, `DEDUCTION`, `EMPLOYER_CONTRIBUTION` |
| `PAY_RUN_STATUSES` | `payroll/schemas.py` | `DRAFT`, `INPUTS_LOCKED`, `COMPUTED`, `APPROVED`, `FINALISED`, `PAID` |
| `RUN_LINE_CODES` | `payroll/breakup.py` | `DAILY_WAGES`, `EPF_EMPLOYER`, `EPS_EMPLOYER`, `ESI_EMPLOYEE`, `ESI_EMPLOYER`, `LEAVE_ENCASHMENT`, `LWF_EMPLOYEE`, `LWF_EMPLOYER`, `OVERTIME`, `PF_ADMIN`, `PF_EDLI`, `PF_EMPLOYEE`, `PT`, `ROUNDING`, `TDS_EMPLOYEE`, `VPF` |
| `STATUTORY_SCHEMES` | `payroll/schemas.py` | `PF`, `ESI`, `PT`, `LWF`, `TDS` |
| `_ARREARS_IGNORED_ISSUES` | `payroll/engine.py` | `BANK_ACCOUNT_MISSING`, `BANK_MISSING`, `BASIC_MISSING`, `ESI_ABOVE_CEILING`, `ESI_IP_MISSING`, `NEGATIVE_NET`, `PT_RATE_MISSING`, `UAN_MISSING`, `ZERO_NET` |
| `_FINAL_STATUSES` | `payroll/service.py` | `FINALISED`, `PAID` |
| `_MUTABLE` | `payroll/repository.py` | `DRAFT`, `INPUTS_LOCKED`, `COMPUTED`, `APPROVED` |
| `_PAYSLIP_STATUSES` | `payroll/service.py` | `COMPUTED`, `APPROVED`, `FINALISED`, `PAID` |
| `_STATUTORY_STRUCTURE_LINES` | `payroll/engine.py` | `EMPLOYER_ESI`, `EMPLOYER_PF` |

## platform

| Constant | File | Values |
|---|---|---|
| `_LIVE_SUBSCRIPTION_EXCLUDED` | `platform/repository.py` | `CANCELED`, `EXPIRED` |

