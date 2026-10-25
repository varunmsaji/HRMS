# Data models - organisation

Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list (for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "Server-generated" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart (derived by name match - an inference, not a declared flag).

## AddressSchema
<a id="addressschema"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `line1` | no | string | yes | maxLength=255 | - |
| `line2` | no | string | yes | maxLength=255 | - |
| `city` | no | string | yes | maxLength=100 | - |
| `state` | no | string | yes | maxLength=100 | - |
| `postal_code` | no | string | yes | maxLength=20 | - |
| `country_code` | no | string | yes | minLength=2, maxLength=2 | - |

## BranchCreate
<a id="branchcreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `legal_entity_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | minLength=1, maxLength=200 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `address_line1` | no | string | yes | maxLength=200 | - |
| `address_line2` | no | string | yes | maxLength=200 | - |
| `city` | no | string | yes | maxLength=100 | - |
| `state_code` | no | string | yes | maxLength=10 | - |
| `pincode` | no | string | yes | maxLength=10 | - |
| `timezone` | no | string | yes | - | - |
| `latitude` | no | number \| decimal (JSON **string**) | yes | - | - |
| `longitude` | no | number \| decimal (JSON **string**) | yes | - | - |
| `geofence_radius_m` | no | integer | yes | max=100000.0, >=0.0 | - |

## BranchRead
<a id="branchread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `legal_entity_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `code` | yes | string | yes | - | - |
| `address_line1` | yes | string | yes | - | - |
| `address_line2` | yes | string | yes | - | - |
| `city` | yes | string | yes | - | - |
| `state_code` | yes | string | yes | - | - |
| `pincode` | yes | string | yes | - | - |
| `timezone` | yes | string | yes | - | - |
| `latitude` | yes | decimal (JSON **string**) | yes | - | - |
| `longitude` | yes | decimal (JSON **string**) | yes | - | - |
| `geofence_radius_m` | yes | integer | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `BranchCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## BranchUpdate
<a id="branchupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `legal_entity_id` | no | string(uuid) | yes | - | - |
| `name` | no | string | yes | minLength=1, maxLength=200 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `address_line1` | no | string | yes | maxLength=200 | - |
| `address_line2` | no | string | yes | maxLength=200 | - |
| `city` | no | string | yes | maxLength=100 | - |
| `state_code` | no | string | yes | maxLength=10 | - |
| `pincode` | no | string | yes | maxLength=10 | - |
| `timezone` | no | string | yes | - | - |
| `latitude` | no | number \| decimal (JSON **string**) | yes | - | - |
| `longitude` | no | number \| decimal (JSON **string**) | yes | - | - |
| `geofence_radius_m` | no | integer | yes | max=100000.0, >=0.0 | - |
| `is_active` | no | boolean | yes | - | - |

## BrandingSchema
<a id="brandingschema"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `logo_url` | no | string | yes | maxLength=2048 | - |
| `theme` | no | [ThemeSchema](#themeschema) | yes | - | - |

## BusinessHoursSchema
<a id="businesshoursschema"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `start_time` | yes | string | no | pattern=`^\d{2}:\d{2}$` | - |
| `end_time` | yes | string | no | pattern=`^\d{2}:\d{2}$` | - |

## CalendarExceptionCreate
<a id="calendarexceptioncreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `exception_date` | yes | string(date) | no | - | - |
| `exception_type` | yes | string | no | - | - |
| `name` | no | string | yes | maxLength=150 | - |
| `reason` | no | string | yes | - | - |
| `is_paid` | no | boolean | yes | - | - |

## CalendarExceptionRead
<a id="calendarexceptionread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `work_calendar_id` | yes | string(uuid) | no | - | - |
| `exception_date` | yes | string(date) | no | - | - |
| `exception_type` | yes | string | no | - | - |
| `name` | yes | string | yes | - | - |
| `reason` | yes | string | yes | - | - |
| `is_paid` | yes | boolean | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `CalendarExceptionCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`, `work_calendar_id`

## CalendarExceptionUpdate
<a id="calendarexceptionupdate"></a>

Never accepts `exception_date`/`exception_type` — corrections are deactivate-then- insert (architecture §7.3), matching `HolidayUpdate`'s immutable-date posture.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | maxLength=150 | - |
| `reason` | no | string | yes | - | - |
| `is_paid` | no | boolean | yes | - | - |
| `is_active` | no | boolean | yes | - | - |

## CalendarResolutionRead
<a id="calendarresolutionread"></a>

Response for `GET /calendar-resolution?employee_id=&date=` — the full WD-09 precedence walk plus the resulting day-type classification, or `config_incomplete=true` (fail-closed, WD-21) when no WorkCalendar resolves for this employee+date.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `date` | yes | string(date) | no | - | - |
| `config_incomplete` | yes | boolean | no | - | - |
| `work_calendar_id` | no | string(uuid) | yes | - | - |
| `work_calendar_name` | no | string | yes | - | - |
| `resolved_scope_type` | no | string | yes | - | - |
| `weekly_off_pattern_id` | no | string(uuid) | yes | - | - |
| `weekly_off_resolved_scope_type` | no | string | yes | - | - |
| `day_type` | no | [DayTypeRead](#daytyperead) | yes | - | - |

## CompanyDashboardSummary
<a id="companydashboardsummary"></a>

Stable dashboard DTO — sibling counts stay null until those modules ship (04_API_Design.md §7). Additive optional fields may be added later without breaking this contract.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `setup_progress` | yes | [DashboardSetupProgress](#dashboardsetupprogress) | no | - | - |
| `subscription` | yes | [DashboardSubscription](#dashboardsubscription) | yes | - | - |
| `branch_count` | yes | integer | yes | - | - |
| `department_count` | yes | integer | yes | - | - |
| `employee_count` | yes | integer | yes | - | - |

## CompanyProfileRead
<a id="companyprofileread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `legal_name` | yes | string | yes | - | - |
| `registration_number` | yes | string | yes | - | - |
| `subdomain` | yes | string | yes | - | - |
| `contact` | yes | [ContactInfoSchema](#contactinfoschema) | no | - | - |
| `address` | yes | [AddressSchema](#addressschema) | no | - | - |
| `industry_code` | yes | string | yes | - | - |
| `company_size` | yes | string | yes | - | - |
| `country_code` | yes | string | no | - | - |
| `currency` | yes | string | no | - | - |
| `timezone` | yes | string | no | - | - |
| `locale` | yes | [LocaleSchema](#localeschema) | no | - | - |
| `fiscal_year` | yes | [FiscalYearSchema](#fiscalyearschema) | no | - | - |
| `working_days` | yes | array&lt;[WorkingDaySchema](#workingdayschema)&gt; | no | - | - |
| `business_hours` | yes | [BusinessHoursSchema](#businesshoursschema) | yes | - | - |
| `branding` | yes | [BrandingSchema](#brandingschema) | no | - | - |
| `status` | yes | string | no | - | - |
| `primary_legal_entity` | no | null | no | - | - |
| `onboarded_at` | yes | string | yes | - | - |
| `trial_ends_at` | yes | string | yes | - | - |
| `version` | yes | integer | no | - | - |

Server-generated / read-only vs `CompanyProfileUpdate`: `id`, `onboarded_at`, `primary_legal_entity`, `status`, `subdomain`, `trial_ends_at`, `version`

## CompanyProfileUpdate
<a id="companyprofileupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=200 | - |
| `legal_name` | no | string | yes | maxLength=200 | - |
| `registration_number` | no | string | yes | maxLength=64 | - |
| `industry_code` | no | string | yes | maxLength=40 | - |
| `company_size` | no | string | yes | - | - |
| `country_code` | no | string | yes | minLength=2, maxLength=2 | - |
| `currency` | no | string | yes | minLength=3, maxLength=3 | - |
| `timezone` | no | string | yes | - | - |
| `contact` | no | [ContactInfoSchema](#contactinfoschema) | yes | - | - |
| `address` | no | [AddressSchema](#addressschema) | yes | - | - |
| `locale` | no | [LocaleSchema](#localeschema) | yes | - | - |
| `fiscal_year` | no | [FiscalYearSchema](#fiscalyearschema) | yes | - | - |
| `working_days` | no | array&lt;[WorkingDaySchema](#workingdayschema)&gt; | yes | - | - |
| `business_hours` | no | [BusinessHoursSchema](#businesshoursschema) | yes | - | - |
| `branding` | no | [BrandingSchema](#brandingschema) | yes | - | - |

## CompanyRegistrationRequest
<a id="companyregistrationrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | yes | string | no | minLength=1, maxLength=200 | - |
| `industry_code` | no | string | yes | maxLength=40 | - |
| `country_code` | no | string | no | minLength=2, maxLength=2, default=`"IN"` | - |
| `currency` | no | string | no | minLength=3, maxLength=3, default=`"INR"` | - |
| `timezone` | no | string | no | default=`"Asia/Kolkata"` | - |
| `fy_start_month` | no | integer | no | min=1.0, max=12.0, default=`4` | - |
| `company_size` | no | string | yes | - | - |
| `admin_first_name` | yes | string | no | minLength=1, maxLength=100 | - |
| `admin_last_name` | yes | string | no | minLength=1, maxLength=100 | - |
| `admin_email` | yes | string(email) | no | - | - |
| `admin_password` | yes | string | no | minLength=1, maxLength=128 | - |

## CompanySetupProgressSummary
<a id="companysetupprogresssummary"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `status` | yes | string | no | - | - |
| `current_step` | yes | string | yes | - | - |
| `steps` | yes | array&lt;[SetupStepSummary](#setupstepsummary)&gt; | no | - | - |
| `started_at` | yes | string | no | - | - |
| `completed_at` | yes | string | yes | - | - |

## ContactInfoSchema
<a id="contactinfoschema"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `email` | no | string(email) | yes | - | - |
| `phone` | no | string | yes | maxLength=32 | - |
| `website` | no | string | yes | maxLength=255 | - |

## DashboardSetupProgress
<a id="dashboardsetupprogress"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `status` | yes | string | no | - | - |
| `steps_completed` | yes | integer | no | - | - |
| `steps_total` | yes | integer | no | - | - |

## DashboardSubscription
<a id="dashboardsubscription"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `plan_code` | yes | string | no | - | - |
| `status` | yes | string | no | - | - |
| `trial_ends_at` | yes | string | yes | - | - |

## DayTypeRead
<a id="daytyperead"></a>

Computed classification of a single date against a WorkCalendar — never persisted (no `AttendanceDay` exists yet). See `calendar_resolution.classify_work_calendar_date`.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `date` | yes | string(date) | no | - | - |
| `day_type` | yes | string | no | - | - |
| `holiday_name` | no | string | yes | - | - |
| `exception_type` | no | string | yes | - | - |
| `holiday_on_weekly_off` | no | boolean | no | default=`false` | - |
| `is_holiday_named` | no | boolean | no | default=`false` | - |
| `optional_holiday_name` | no | string | yes | - | - |
| `restricted_holiday_name` | no | string | yes | - | - |
| `weekly_off_fraction` | no | decimal (JSON **string**) | yes | - | - |
| `holiday_type` | no | string | yes | - | - |
| `holiday_is_paid` | no | boolean | yes | - | - |

## DepartmentCreate
<a id="departmentcreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | yes | string | no | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `branch_id` | no | string(uuid) | yes | - | - |
| `parent_id` | no | string(uuid) | yes | - | - |
| `head_employee_id` | no | string(uuid) | yes | - | - |

## DepartmentRead
<a id="departmentread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `branch_id` | yes | string(uuid) | yes | - | - |
| `parent_id` | yes | string(uuid) | yes | - | - |
| `name` | yes | string | no | - | - |
| `code` | yes | string | yes | - | - |
| `head_employee_id` | yes | string(uuid) | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `DepartmentCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## DepartmentUpdate
<a id="departmentupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `branch_id` | no | string(uuid) | yes | - | - |
| `parent_id` | no | string(uuid) | yes | - | - |
| `head_employee_id` | no | string(uuid) | yes | - | - |
| `is_active` | no | boolean | yes | - | - |

## DesignationCreate
<a id="designationcreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `title` | yes | string | no | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `department_id` | no | string(uuid) | yes | - | - |
| `grade_id` | no | string(uuid) | yes | - | - |

## DesignationRead
<a id="designationread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `department_id` | yes | string(uuid) | yes | - | - |
| `grade_id` | yes | string(uuid) | yes | - | - |
| `title` | yes | string | no | - | - |
| `code` | yes | string | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `DesignationCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## DesignationUpdate
<a id="designationupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `title` | no | string | yes | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `department_id` | no | string(uuid) | yes | - | - |
| `grade_id` | no | string(uuid) | yes | - | - |
| `is_active` | no | boolean | yes | - | - |

## FeatureFlagView
<a id="featureflagview"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `code` | yes | string | no | - | - |
| `is_enabled` | yes | boolean | no | - | - |
| `source` | yes | string | no | - | - |
| `limit_value` | no | integer | yes | - | - |

## FiscalYearSchema
<a id="fiscalyearschema"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `start_month` | yes | integer | no | min=1.0, max=12.0 | - |

## GradeCreate
<a id="gradecreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `code` | yes | string | no | minLength=1, maxLength=30 | - |
| `name` | yes | string | no | minLength=1, maxLength=100 | - |
| `level` | no | integer | yes | min=0.0, max=2147483647.0 | - |
| `min_ctc` | no | integer | yes | min=0.0, max=10000000000000.0 | - |
| `max_ctc` | no | integer | yes | min=0.0, max=10000000000000.0 | - |
| `notice_period_days` | no | integer | yes | min=0.0, max=3650.0 | - |
| `probation_days` | no | integer | yes | min=0.0, max=3650.0 | - |
| `approval_limit` | no | integer | yes | min=0.0, max=10000000000000.0 | - |

## GradeRead
<a id="graderead"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `code` | yes | string | no | - | - |
| `name` | yes | string | no | - | - |
| `level` | yes | integer | yes | - | - |
| `min_ctc` | yes | integer | yes | - | - |
| `max_ctc` | yes | integer | yes | - | - |
| `notice_period_days` | yes | integer | yes | - | - |
| `probation_days` | yes | integer | yes | - | - |
| `approval_limit` | yes | integer | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `GradeCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## GradeUpdate
<a id="gradeupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `code` | no | string | yes | minLength=1, maxLength=30 | - |
| `name` | no | string | yes | minLength=1, maxLength=100 | - |
| `level` | no | integer | yes | min=0.0, max=2147483647.0 | - |
| `min_ctc` | no | integer | yes | min=0.0, max=10000000000000.0 | - |
| `max_ctc` | no | integer | yes | min=0.0, max=10000000000000.0 | - |
| `notice_period_days` | no | integer | yes | min=0.0, max=3650.0 | - |
| `probation_days` | no | integer | yes | min=0.0, max=3650.0 | - |
| `approval_limit` | no | integer | yes | min=0.0, max=10000000000000.0 | - |
| `is_active` | no | boolean | yes | - | - |

## HolidayCalendarCreate
<a id="holidaycalendarcreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | yes | string | no | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `kind` | no | string | no | default=`"COMPANY"` | - |
| `state_code` | no | string | yes | maxLength=10 | - |
| `valid_from` | no | string(date) | yes | - | - |
| `valid_to` | no | string(date) | yes | - | - |

## HolidayCalendarRead
<a id="holidaycalendarread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `code` | yes | string | yes | - | - |
| `kind` | yes | string | no | - | - |
| `state_code` | yes | string | yes | - | - |
| `valid_from` | yes | string(date) | yes | - | - |
| `valid_to` | yes | string(date) | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `HolidayCalendarCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## HolidayCalendarUpdate
<a id="holidaycalendarupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `kind` | no | string | yes | - | - |
| `state_code` | no | string | yes | maxLength=10 | - |
| `valid_from` | no | string(date) | yes | - | - |
| `valid_to` | no | string(date) | yes | - | - |
| `is_active` | no | boolean | yes | - | - |

## HolidayCreate
<a id="holidaycreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `date` | yes | string(date) | no | - | - |
| `name` | yes | string | no | minLength=1, maxLength=150 | - |
| `holiday_type` | no | string | no | default=`"PUBLIC"` | - |
| `is_paid` | no | boolean | no | default=`true` | - |
| `is_working` | no | boolean | no | default=`false` | - |
| `region_note` | no | string | yes | maxLength=200 | - |
| `replaced_holiday_id` | no | string(uuid) | yes | - | - |

## HolidayRead
<a id="holidayread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `calendar_id` | yes | string(uuid) | no | - | - |
| `date` | yes | string(date) | no | - | - |
| `name` | yes | string | no | - | - |
| `is_optional` | yes | boolean | no | - | - |
| `holiday_type` | yes | string | no | - | - |
| `is_paid` | yes | boolean | no | - | - |
| `is_working` | yes | boolean | no | - | - |
| `region_note` | yes | string | yes | - | - |
| `replaced_holiday_id` | yes | string(uuid) | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `HolidayCreate`: `calendar_id`, `company_id`, `created_at`, `id`, `is_active`, `is_optional`, `updated_at`, `version`

## HolidayUpdate
<a id="holidayupdate"></a>

Never accepts `date`/`calendar_id` — a holiday's date is immutable after creation (architecture §25: "no PATCH of used dates"). Correcting a wrong date is deactivate this row + create a new one, preserving history.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=150 | - |
| `holiday_type` | no | string | yes | - | - |
| `is_paid` | no | boolean | yes | - | - |
| `is_working` | no | boolean | yes | - | - |
| `region_note` | no | string | yes | maxLength=200 | - |
| `replaced_holiday_id` | no | string(uuid) | yes | - | - |
| `is_active` | no | boolean | yes | - | - |

## LegalEntityCreate
<a id="legalentitycreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | yes | string | no | minLength=1, maxLength=200 | - |
| `registered_address` | no | string | yes | maxLength=4000 | - |
| `pan` | no | string | yes | maxLength=20 | - |
| `tan` | no | string | yes | maxLength=20 | - |
| `cin` | no | string | yes | maxLength=30 | - |
| `gstin` | no | string | yes | maxLength=20 | - |
| `pf_code` | no | string | yes | maxLength=30 | - |
| `esi_code` | no | string | yes | maxLength=30 | - |
| `lwf_reg` | no | string | yes | maxLength=30 | - |
| `signatory_name` | no | string | yes | maxLength=150 | - |
| `signatory_designation` | no | string | yes | maxLength=150 | - |
| `signature_image_url` | no | string | yes | maxLength=2048 | - |

## LegalEntityRead
<a id="legalentityread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `registered_address` | yes | string | yes | - | - |
| `pan` | yes | string | yes | - | - |
| `tan` | yes | string | yes | - | - |
| `cin` | yes | string | yes | - | - |
| `gstin` | yes | string | yes | - | - |
| `pf_code` | yes | string | yes | - | - |
| `esi_code` | yes | string | yes | - | - |
| `lwf_reg` | yes | string | yes | - | - |
| `signatory_name` | yes | string | yes | - | - |
| `signatory_designation` | yes | string | yes | - | - |
| `signature_image_url` | yes | string | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `LegalEntityCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## LegalEntityUpdate
<a id="legalentityupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=200 | - |
| `registered_address` | no | string | yes | maxLength=4000 | - |
| `pan` | no | string | yes | maxLength=20 | - |
| `tan` | no | string | yes | maxLength=20 | - |
| `cin` | no | string | yes | maxLength=30 | - |
| `gstin` | no | string | yes | maxLength=20 | - |
| `pf_code` | no | string | yes | maxLength=30 | - |
| `esi_code` | no | string | yes | maxLength=30 | - |
| `lwf_reg` | no | string | yes | maxLength=30 | - |
| `signatory_name` | no | string | yes | maxLength=150 | - |
| `signatory_designation` | no | string | yes | maxLength=150 | - |
| `signature_image_url` | no | string | yes | maxLength=2048 | - |
| `is_active` | no | boolean | yes | - | - |

## LocaleSchema
<a id="localeschema"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `language_code` | yes | string | no | minLength=2, maxLength=10 | - |
| `date_format` | yes | string | no | minLength=1, maxLength=20 | - |

## PlanSummary
<a id="plansummary"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `code` | yes | string | no | - | - |
| `name` | yes | string | no | - | - |

## PolicyAssignmentCreate
<a id="policyassignmentcreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `policy_kind` | yes | string | no | - | - |
| `policy_id` | yes | string(uuid) | no | - | - |
| `leave_type_id` | no | string(uuid) | yes | - | - |
| `scope_type` | yes | string | no | - | - |
| `scope_id` | no | string(uuid) | yes | - | - |
| `effective_from` | yes | string(date) | no | - | - |
| `effective_to` | no | string(date) | yes | - | - |
| `priority` | no | integer | no | default=`0` | - |
| `reason` | no | string | yes | - | - |

## PolicyAssignmentRead
<a id="policyassignmentread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `policy_kind` | yes | string | no | - | - |
| `policy_id` | yes | string(uuid) | no | - | - |
| `leave_type_id` | yes | string(uuid) | yes | - | - |
| `scope_type` | yes | string | no | - | - |
| `scope_id` | yes | string(uuid) | yes | - | - |
| `effective_from` | yes | string(date) | no | - | - |
| `effective_to` | yes | string(date) | yes | - | - |
| `priority` | yes | integer | no | - | - |
| `reason` | yes | string | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `PolicyAssignmentCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## RegistrationConfigRead
<a id="registrationconfigread"></a>

Body for the public, unauthenticated `GET /companies/registration-config` — lets the sign-up page narrow its timezone `<select>` to what the server will actually accept, fetched from the API rather than duplicated as a second, independently-maintained TypeScript list (execution gate §6.3: "two independently maintained lists is how they drift"). Read-only; changing the allowed set is a `settings.allowed_company_timezones` configuration change, not a schema change.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `allowed_company_timezones` | yes | array&lt;string&gt; | no | - | - |

## SetupStepSummary
<a id="setupstepsummary"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `code` | yes | string | no | - | - |
| `label` | yes | string | no | - | - |
| `is_complete` | yes | boolean | no | - | - |

## ShiftBreakCreate
<a id="shiftbreakcreate"></a>

Nested input for `ShiftVersionCreate.breaks`/`ShiftVersionUpdate.breaks` — no independent lifecycle, no standalone endpoint (full-replace only). `crosses_midnight` is not client-settable — server-derived from the time comparison, same posture as `ShiftVersion.is_cross_midnight`.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | yes | string | no | minLength=1, maxLength=100 | - |
| `break_kind` | yes | string | no | - | - |
| `start_time` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `end_time` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `window_start` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `window_end` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `min_minutes` | no | integer | yes | min=0.0 | - |
| `max_minutes` | no | integer | yes | min=0.0 | - |
| `scheduled_minutes` | no | integer | yes | min=0.0 | - |
| `is_paid` | no | boolean | no | default=`false` | - |
| `is_mandatory` | no | boolean | no | default=`true` | - |
| `allows_split` | no | boolean | no | default=`false` | - |
| `sort_order` | no | integer | no | default=`0` | - |

## ShiftBreakRead
<a id="shiftbreakread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `shift_version_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `break_kind` | yes | string | no | - | - |
| `start_time` | yes | string | yes | - | - |
| `end_time` | yes | string | yes | - | - |
| `window_start` | yes | string | yes | - | - |
| `window_end` | yes | string | yes | - | - |
| `min_minutes` | yes | integer | yes | - | - |
| `max_minutes` | yes | integer | yes | - | - |
| `scheduled_minutes` | yes | integer | yes | - | - |
| `is_paid` | yes | boolean | no | - | - |
| `is_mandatory` | yes | boolean | no | - | - |
| `allows_split` | yes | boolean | no | - | - |
| `crosses_midnight` | yes | boolean | no | - | - |
| `sort_order` | yes | integer | no | - | - |

Server-generated / read-only vs `ShiftBreakCreate`: `crosses_midnight`, `id`, `shift_version_id`

## ShiftCreate
<a id="shiftcreate"></a>

W2 — trimmed to identity-only (name/code). The nine schedule/evaluation fields the legacy `Shift` used to accept here now live on `ShiftVersion` (docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md §9-§10).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | yes | string | no | minLength=1, maxLength=100 | - |
| `code` | no | string | yes | maxLength=30 | - |

## ShiftDutyBlockCreate
<a id="shiftdutyblockcreate"></a>

Nested input for `ShiftVersionCreate.duty_blocks`/`ShiftVersionUpdate.duty_blocks` — SPLIT shift types only, no independent lifecycle. `crosses_midnight` is not client-settable — server-derived from the time comparison.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `sequence` | yes | integer | no | min=1.0 | - |
| `start_time` | yes | string | no | pattern=`^\d{2}:\d{2}$` | - |
| `end_time` | yes | string | no | pattern=`^\d{2}:\d{2}$` | - |

## ShiftDutyBlockRead
<a id="shiftdutyblockread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `shift_version_id` | yes | string(uuid) | no | - | - |
| `sequence` | yes | integer | no | - | - |
| `start_time` | yes | string | no | - | - |
| `end_time` | yes | string | no | - | - |
| `crosses_midnight` | yes | boolean | no | - | - |

Server-generated / read-only vs `ShiftDutyBlockCreate`: `crosses_midnight`, `id`, `shift_version_id`

## ShiftRead
<a id="shiftread"></a>

The nine legacy schedule/evaluation fields below are **deprecated, read-only, and frozen at W2-migration time** — kept for audit/back-compat continuity only, never written again by W2+ code (superseded by `ShiftVersion`/`ShiftBreak`, see field-level descriptions). `current_version_id`/`draft_version_id` are cheap lookups so a caller knows schedule state without a second round trip.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `code` | yes | string | yes | - | - |
| `start_time` | yes | string | no | - | Deprecated — frozen at W2 migration time, superseded by ShiftVersion.start_time. Never written again. |
| `end_time` | yes | string | no | - | Deprecated — frozen at W2 migration time, superseded by ShiftVersion.end_time. Never written again. |
| `break_minutes_paid` | yes | integer | no | - | Deprecated — frozen at W2 migration time, superseded by ShiftBreak rows (is_paid=true). Never written again. |
| `break_minutes_unpaid` | yes | integer | no | - | Deprecated — frozen at W2 migration time, superseded by ShiftBreak rows (is_paid=false). Never written again. |
| `grace_in_minutes` | yes | integer | no | - | Deprecated — frozen at W2 migration time; grace-period fields migrate off Shift in W3 (AttendancePolicy). Never written again. |
| `grace_out_minutes` | yes | integer | no | - | Deprecated — frozen at W2 migration time; grace-period fields migrate off Shift in W3 (AttendancePolicy). Never written again. |
| `half_day_threshold_hours` | yes | decimal (JSON **string**) | yes | - | Deprecated — frozen at W2 migration time; half-day/min-hours fields migrate off Shift in W3 (AttendancePolicy). Never written again. |
| `min_hours_full_day` | yes | decimal (JSON **string**) | yes | - | Deprecated — frozen at W2 migration time; half-day/min-hours fields migrate off Shift in W3 (AttendancePolicy). Never written again. |
| `is_night_shift` | yes | boolean | no | - | Deprecated — frozen at W2 migration time, superseded by ShiftVersion.is_night_shift. Never written again. |
| `is_cross_midnight` | yes | boolean | no | - | Deprecated — frozen at W2 migration time, superseded by ShiftVersion.is_cross_midnight. Never written again. |
| `is_ot_eligible` | yes | boolean | no | - | Deprecated — frozen at W2 migration time, superseded by ShiftVersion.is_ot_eligible. Never written again. |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |
| `current_version_id` | no | string(uuid) | yes | - | - |
| `draft_version_id` | no | string(uuid) | yes | - | - |

Server-generated / read-only vs `ShiftCreate`: `break_minutes_paid`, `break_minutes_unpaid`, `company_id`, `created_at`, `current_version_id`, `draft_version_id`, `end_time`, `grace_in_minutes`, `grace_out_minutes`, `half_day_threshold_hours`, `id`, `is_active`, `is_cross_midnight`, `is_night_shift`, `is_ot_eligible`, `min_hours_full_day`, `start_time`, `updated_at`, `version`

## ShiftUpdate
<a id="shiftupdate"></a>

W2 — trimmed to identity-only (name/code/is_active). See `ShiftCreate`.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=100 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `is_active` | no | boolean | yes | - | - |

## ShiftVersionCreate
<a id="shiftversioncreate"></a>

Creates a new open DRAFT `ShiftVersion` for a shift (409 `SHIFT_VERSION_DRAFT_ALREADY_EXISTS` if one is already open). All fields are optional — a draft may be incomplete mid-edit; only `POST .../publish` enforces the full, type-specific field set. `is_cross_midnight` is never client-settable — always server-derived from the time fields. `is_night_shift` IS client-settable: architecture §9.5 is explicit that it "is an explicit flag (night OT classification), not inferred solely from times" — unlike `is_cross_midnight`, which the same section says "must be consistent with start/end (already validated)".

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `shift_type` | no | string | yes | - | - |
| `timezone` | no | string | yes | maxLength=64 | - |
| `effective_from` | no | string(date) | yes | - | - |
| `start_time` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `end_time` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `window_start` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `window_end` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `core_start` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `core_end` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `required_minutes` | no | integer | yes | min=0.0 | - |
| `scheduled_minutes` | no | integer | yes | min=0.0 | - |
| `min_scheduled_minutes` | no | integer | yes | min=0.0 | - |
| `max_scheduled_minutes` | no | integer | yes | min=0.0 | - |
| `is_night_shift` | no | boolean | no | default=`false` | - |
| `is_ot_eligible` | no | boolean | no | default=`false` | - |
| `operates_on_holiday` | no | boolean | no | default=`false` | - |
| `operates_on_weekly_off` | no | boolean | no | default=`false` | - |
| `weekly_off_pattern_id` | no | string(uuid) | yes | - | - |
| `breaks` | no | array&lt;[ShiftBreakCreate](#shiftbreakcreate)&gt; | yes | - | - |
| `duty_blocks` | no | array&lt;[ShiftDutyBlockCreate](#shiftdutyblockcreate)&gt; | yes | - | - |

## ShiftVersionPublishRequest
<a id="shiftversionpublishrequest"></a>

Body for `POST /shifts/{shift_id}/versions/{version_id}/publish`. `If-Match` (header, handled at the router layer) carries the draft's own `expected_version`; `expected_previous_version` is the **second** concurrency token in this two-token flow — required only when an open PUBLISHED version already exists for this shift, so it can be closed as part of the same publish (mirrors `create_policy_assignment`'s insert-new/ close-previous idiom exactly, just with two tokens instead of one since two different rows are being mutated).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `publish_reason` | no | string | yes | - | - |
| `expected_previous_version` | no | integer | yes | - | - |

## ShiftVersionRead
<a id="shiftversionread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `shift_id` | yes | string(uuid) | no | - | - |
| `status` | yes | string | no | - | - |
| `version` | yes | integer | no | - | - |
| `effective_from` | yes | string(date) | yes | - | - |
| `effective_to` | yes | string(date) | yes | - | - |
| `shift_type` | yes | string | yes | - | - |
| `timezone` | yes | string | yes | - | - |
| `start_time` | yes | string | yes | - | - |
| `end_time` | yes | string | yes | - | - |
| `window_start` | yes | string | yes | - | - |
| `window_end` | yes | string | yes | - | - |
| `core_start` | yes | string | yes | - | - |
| `core_end` | yes | string | yes | - | - |
| `required_minutes` | yes | integer | yes | - | - |
| `scheduled_minutes` | yes | integer | yes | - | - |
| `min_scheduled_minutes` | yes | integer | yes | - | - |
| `max_scheduled_minutes` | yes | integer | yes | - | - |
| `is_night_shift` | yes | boolean | no | - | - |
| `is_cross_midnight` | yes | boolean | no | - | - |
| `is_ot_eligible` | yes | boolean | no | - | - |
| `operates_on_holiday` | yes | boolean | no | - | - |
| `operates_on_weekly_off` | yes | boolean | no | - | - |
| `weekly_off_pattern_id` | yes | string(uuid) | yes | - | - |
| `publish_reason` | yes | string | yes | - | - |
| `published_at` | yes | string | yes | - | - |
| `published_by` | yes | string(uuid) | yes | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |
| `breaks` | yes | array&lt;[ShiftBreakRead](#shiftbreakread)&gt; | no | - | - |
| `duty_blocks` | yes | array&lt;[ShiftDutyBlockRead](#shiftdutyblockread)&gt; | no | - | - |

Server-generated / read-only vs `ShiftVersionCreate`: `company_id`, `created_at`, `effective_to`, `id`, `is_cross_midnight`, `publish_reason`, `published_at`, `published_by`, `shift_id`, `status`, `updated_at`, `version`

## ShiftVersionUpdate
<a id="shiftversionupdate"></a>

Draft-only PATCH (409 `SHIFT_VERSION_NOT_DRAFT` once published). `breaks`/ `duty_blocks`, when present, **replace** the entire nested collection atomically — no separate sub-resource CRUD, since they have no independent lifecycle (mirrors `WeeklyOffPatternUpdate.rules`).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `shift_type` | no | string | yes | - | - |
| `timezone` | no | string | yes | maxLength=64 | - |
| `effective_from` | no | string(date) | yes | - | - |
| `start_time` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `end_time` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `window_start` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `window_end` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `core_start` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `core_end` | no | string | yes | pattern=`^\d{2}:\d{2}$` | - |
| `required_minutes` | no | integer | yes | min=0.0 | - |
| `scheduled_minutes` | no | integer | yes | min=0.0 | - |
| `min_scheduled_minutes` | no | integer | yes | min=0.0 | - |
| `max_scheduled_minutes` | no | integer | yes | min=0.0 | - |
| `is_night_shift` | no | boolean | yes | - | - |
| `is_ot_eligible` | no | boolean | yes | - | - |
| `operates_on_holiday` | no | boolean | yes | - | - |
| `operates_on_weekly_off` | no | boolean | yes | - | - |
| `weekly_off_pattern_id` | no | string(uuid) | yes | - | - |
| `breaks` | no | array&lt;[ShiftBreakCreate](#shiftbreakcreate)&gt; | yes | - | - |
| `duty_blocks` | no | array&lt;[ShiftDutyBlockCreate](#shiftdutyblockcreate)&gt; | yes | - | - |

## SubscriptionSummary
<a id="subscriptionsummary"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `plan` | yes | [PlanSummary](#plansummary) | no | - | - |
| `status` | yes | string | no | - | - |
| `current_period_start` | yes | string | yes | - | - |
| `current_period_end` | yes | string | yes | - | - |
| `trial_ends_at` | yes | string | yes | - | - |
| `seat_limit` | yes | integer | yes | - | - |
| `features` | yes | array&lt;[FeatureFlagView](#featureflagview)&gt; | no | - | - |

## ThemeSchema
<a id="themeschema"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `primary_color` | no | string | yes | maxLength=32 | - |

## WeeklyOffPatternCreate
<a id="weeklyoffpatterncreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | yes | string | no | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `pattern_kind` | yes | string | no | - | - |
| `rules` | no | array&lt;[WeeklyOffRuleInput](#weeklyoffruleinput)&gt; | no | minItems=1 | - |

## WeeklyOffPatternRead
<a id="weeklyoffpatternread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `code` | yes | string | yes | - | - |
| `pattern_kind` | yes | string | no | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |
| `rules` | yes | array&lt;[WeeklyOffRuleRead](#weeklyoffruleread)&gt; | no | - | - |

Server-generated / read-only vs `WeeklyOffPatternCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## WeeklyOffPatternUpdate
<a id="weeklyoffpatternupdate"></a>

`rules`, when present, **replaces** the entire rule set atomically (simpler and safer than diffing individual rule rows for a typed-but-small child collection).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `pattern_kind` | no | string | yes | - | - |
| `rules` | no | array&lt;[WeeklyOffRuleInput](#weeklyoffruleinput)&gt; | yes | - | - |
| `is_active` | no | boolean | yes | - | - |

## WeeklyOffRuleInput
<a id="weeklyoffruleinput"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `weekday` | yes | integer | no | min=0.0, max=6.0 | - |
| `nth_in_month` | no | integer | yes | - | - |
| `cycle_start_date` | no | string(date) | yes | - | - |
| `off_fraction` | no | number \| decimal (JSON **string**) | no | default=`"1.00"` | - |
| `week_parity` | no | string | yes | - | - |

## WeeklyOffRuleRead
<a id="weeklyoffruleread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `weekday` | yes | integer | no | - | - |
| `nth_in_month` | yes | integer | yes | - | - |
| `cycle_start_date` | yes | string(date) | yes | - | - |
| `off_fraction` | yes | decimal (JSON **string**) | no | - | - |
| `week_parity` | yes | string | yes | - | - |

## WorkCalendarCreate
<a id="workcalendarcreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | yes | string | no | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `description` | no | string | yes | - | - |
| `weekly_off_pattern_id` | no | string(uuid) | yes | - | - |
| `restricted_holidays_are_off_by_default` | no | boolean | no | default=`false` | - |
| `holiday_calendar_ids` | no | array&lt;string(uuid)&gt; | no | - | - |

## WorkCalendarRead
<a id="workcalendarread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `code` | yes | string | yes | - | - |
| `description` | yes | string | yes | - | - |
| `weekly_off_pattern_id` | yes | string(uuid) | yes | - | - |
| `restricted_holidays_are_off_by_default` | yes | boolean | no | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |
| `holiday_calendar_ids` | yes | array&lt;string(uuid)&gt; | no | - | - |

Server-generated / read-only vs `WorkCalendarCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## WorkCalendarUpdate
<a id="workcalendarupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `description` | no | string | yes | - | - |
| `weekly_off_pattern_id` | no | string(uuid) | yes | - | - |
| `restricted_holidays_are_off_by_default` | no | boolean | yes | - | - |
| `holiday_calendar_ids` | no | array&lt;string(uuid)&gt; | yes | - | - |
| `is_active` | no | boolean | yes | - | - |

## WorkingDaySchema
<a id="workingdayschema"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `day` | yes | string | no | - | - |
| `is_working` | yes | boolean | no | - | - |
| `is_alternate` | no | boolean | no | default=`false` | - |

