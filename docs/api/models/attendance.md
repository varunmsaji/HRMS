# Data models - attendance

Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list (for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "Server-generated" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart (derived by name match - an inference, not a declared flag).

## AttendanceBreakRead
<a id="attendancebreakread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `attendance_day_id` | yes | string(uuid) | no | - | - |
| `shift_break_id` | yes | string(uuid) | yes | - | - |
| `break_start` | yes | string | yes | - | - |
| `break_end` | yes | string | yes | - | - |
| `minutes` | yes | integer | no | - | - |
| `is_paid` | yes | boolean | no | - | - |
| `is_excess` | yes | boolean | no | - | - |

## AttendanceDayRead
<a id="attendancedayread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `attendance_date` | yes | string(date) | no | - | - |
| `timezone` | yes | string | no | - | - |
| `shift_id` | yes | string(uuid) | yes | - | - |
| `shift_version_id` | yes | string(uuid) | yes | - | - |
| `work_calendar_id` | yes | string(uuid) | yes | - | - |
| `attendance_policy_version_id` | yes | string(uuid) | yes | - | - |
| `overtime_policy_version_id` | yes | string(uuid) | yes | - | - |
| `regularization_policy_version_id` | yes | string(uuid) | yes | - | - |
| `calendar_day_type` | yes | string | yes | - | - |
| `holiday_name` | yes | string | yes | - | - |
| `holiday_on_weekly_off` | yes | boolean | no | - | - |
| `scheduled_start` | yes | string | yes | - | - |
| `scheduled_end` | yes | string | yes | - | - |
| `scheduled_minutes` | yes | integer | yes | - | - |
| `actual_first_in` | yes | string | yes | - | - |
| `actual_last_out` | yes | string | yes | - | - |
| `worked_minutes` | yes | integer | no | - | - |
| `unpaid_break_minutes` | yes | integer | no | - | - |
| `paid_break_minutes` | yes | integer | no | - | - |
| `excess_break_minutes` | yes | integer | no | - | - |
| `attendance_status` | yes | string | no | - | - |
| `late_minutes` | yes | integer | no | - | - |
| `early_departure_minutes` | yes | integer | no | - | - |
| `late_classification` | yes | string | yes | - | - |
| `early_departure_classification` | yes | string | yes | - | - |
| `missing_punch` | yes | boolean | no | - | - |
| `auto_closed` | yes | boolean | no | - | - |
| `is_late` | yes | boolean | no | - | - |
| `is_early_out` | yes | boolean | no | - | - |
| `is_overtime` | yes | boolean | no | - | - |
| `is_regularized` | yes | boolean | no | - | - |
| `is_pending_approval` | yes | boolean | no | - | - |
| `worked_on_holiday` | yes | boolean | no | - | - |
| `worked_on_weekly_off` | yes | boolean | no | - | - |
| `work_on_leave_flagged` | yes | boolean | no | - | - |
| `work_on_leave_resolution` | yes | string | yes | - | - |
| `work_on_leave_resolution_reason` | yes | string | yes | - | - |
| `work_on_leave_resolved_by` | yes | string(uuid) | yes | - | - |
| `work_on_leave_resolved_at` | yes | string | yes | - | - |
| `is_core_hours_breach` | yes | boolean | no | - | - |
| `on_duty` | yes | boolean | no | - | - |
| `on_duty_regularization_id` | yes | string(uuid) | yes | - | - |
| `paid_day_fraction` | yes | string | no | - | - |
| `lop_fraction` | yes | string | no | - | - |
| `leave_fraction` | yes | string | no | - | - |
| `weekly_off_fraction` | yes | string | no | - | - |
| `unpaid_off_fraction` | yes | string | no | - | - |
| `ot_minutes_detected` | yes | integer | no | - | - |
| `ot_minutes_approved` | yes | integer | no | - | - |
| `ot_pending` | yes | boolean | no | - | - |
| `ot_classification` | yes | string | yes | - | - |
| `ot_day_class` | yes | string | yes | - | - |
| `comp_off_minutes_earned` | yes | integer | no | - | - |
| `calculation_version` | yes | integer | no | - | - |
| `engine_version` | yes | integer | yes | - | - |
| `computation_snapshot` | yes | object | yes | - | - |
| `calculated_at` | yes | string | yes | - | - |
| `is_locked` | yes | boolean | no | - | - |
| `locked_at` | yes | string | yes | - | - |
| `locked_by` | yes | string(uuid) | yes | - | - |
| `breaks` | yes | array&lt;[AttendanceBreakRead](#attendancebreakread)&gt; | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

## AttendancePeriodActionRead
<a id="attendanceperiodactionread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `action` | yes | string | no | - | - |
| `actor_user_id` | yes | string(uuid) | yes | - | - |
| `comment` | yes | string | yes | - | - |
| `created_at` | yes | string | no | - | - |

## AttendancePeriodBlockingReason
<a id="attendanceperiodblockingreason"></a>

One typed blocking bucket. `count` is the number of underlying rows/employees in this bucket; `sample` carries up to 20 identifying values (employee ids, or `employee_id:date` pairs) so the caller can navigate straight to the first few offenders without a second, unbounded query.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `code` | yes | string | no | - | - |
| `message` | yes | string | no | - | - |
| `count` | yes | integer | no | - | - |
| `sample` | yes | array&lt;string&gt; | no | - | - |

## AttendancePeriodCreate
<a id="attendanceperiodcreate"></a>

Create always opens immediately — no separate "open" action, mirroring WD-28's no-DRAFT-state precedent (a period isn't useful in a created-but-not-open state; every date inside it is mutable/computable from the instant it exists). Decision 14 — one legal entity per period. Decision 18 — the cycle is a full calendar month by default: send `month` (`YYYY-MM`) and the 1st-to-last-day range is derived from it (and a "September 2026"-style label when none is given). An explicit `period_start`/`period_end` pair is still accepted for an off-cycle period; send one form or the other, not both.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `legal_entity_id` | yes | string(uuid) | no | - | - |
| `month` | no | string | yes | pattern=`^\d{4}-(0[1-9]|1[0-2])$` | - |
| `period_start` | no | string(date) | yes | - | - |
| `period_end` | no | string(date) | yes | - | - |
| `label` | no | string | yes | maxLength=100 | - |

## AttendancePeriodRead
<a id="attendanceperiodread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `legal_entity_id` | yes | string(uuid) | no | - | - |
| `period_start` | yes | string(date) | no | - | - |
| `period_end` | yes | string(date) | no | - | - |
| `label` | yes | string | yes | - | - |
| `status` | yes | string | no | - | - |
| `opened_by_user_id` | yes | string(uuid) | yes | - | - |
| `opened_at` | yes | string | no | - | - |
| `last_validated_at` | yes | string | yes | - | - |
| `last_validation_status` | yes | string | yes | - | - |
| `closed_by_user_id` | yes | string(uuid) | yes | - | - |
| `closed_at` | yes | string | yes | - | - |
| `reopened_by_user_id` | yes | string(uuid) | yes | - | - |
| `reopened_at` | yes | string | yes | - | - |
| `reopen_reason` | yes | string | yes | - | - |
| `version` | yes | integer | no | - | - |
| `actions` | yes | array&lt;[AttendancePeriodActionRead](#attendanceperiodactionread)&gt; | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `AttendancePeriodCreate`: `actions`, `closed_at`, `closed_by_user_id`, `company_id`, `created_at`, `id`, `last_validated_at`, `last_validation_status`, `opened_at`, `opened_by_user_id`, `reopen_reason`, `reopened_at`, `reopened_by_user_id`, `status`, `updated_at`, `version`

## AttendancePeriodReopenInput
<a id="attendanceperiodreopeninput"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `reason` | yes | string | no | minLength=1, maxLength=1000 | - |

## AttendancePeriodSummaryRead
<a id="attendanceperiodsummaryread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `present_days` | yes | string | no | - | - |
| `absent_days` | yes | string | no | - | - |
| `leave_days` | yes | string | no | - | - |
| `holiday_days` | yes | string | no | - | - |
| `weekly_off_days` | yes | string | no | - | - |
| `half_days` | yes | string | no | - | - |
| `lop_days` | yes | string | no | - | - |
| `on_duty_days` | yes | string | yes | - | - |
| `incomplete_days` | yes | string | yes | - | - |
| `not_employed_days` | yes | string | yes | - | - |
| `unpaid_off_days` | yes | string | yes | - | - |
| `paid_days` | yes | string | yes | - | - |
| `payable_days` | yes | string | yes | - | - |
| `ot_minutes_normal` | yes | integer | no | - | - |
| `ot_minutes_weekly_off` | yes | integer | no | - | - |
| `ot_minutes_holiday` | yes | integer | no | - | - |
| `ot_minutes_night` | yes | integer | no | - | - |
| `comp_off_minutes_earned` | yes | integer | no | - | - |
| `late_count` | yes | integer | no | - | - |
| `worked_minutes_total` | yes | integer | no | - | - |
| `generated_at` | yes | string | no | - | - |
| `frozen` | yes | boolean | no | - | - |

## AttendancePeriodValidationRead
<a id="attendanceperiodvalidationread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `status` | yes | string | no | - | - |
| `reasons` | yes | array&lt;[AttendancePeriodBlockingReason](#attendanceperiodblockingreason)&gt; | no | - | - |
| `validated_at` | yes | string | no | - | - |

## AttendancePolicyCreate
<a id="attendancepolicycreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | yes | string | no | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |

## AttendancePolicyEarlyDepartureBandInput
<a id="attendancepolicyearlydeparturebandinput"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `min_minutes` | yes | integer | no | min=0.0 | - |
| `max_minutes` | no | integer | yes | min=0.0 | - |
| `classification` | yes | string | no | - | - |
| `counts_toward_cap` | no | boolean | no | default=`true` | - |
| `sort_order` | no | integer | no | default=`0` | - |

## AttendancePolicyEarlyDepartureBandRead
<a id="attendancepolicyearlydeparturebandread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `min_minutes` | yes | integer | no | - | - |
| `max_minutes` | yes | integer | yes | - | - |
| `classification` | yes | string | no | - | - |
| `counts_toward_cap` | yes | boolean | no | - | - |
| `sort_order` | yes | integer | no | - | - |

## AttendancePolicyHourBandInput
<a id="attendancepolicyhourbandinput"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `min_minutes` | yes | integer | no | min=0.0 | - |
| `max_minutes` | no | integer | yes | min=0.0 | - |
| `result_status` | yes | string | no | - | - |
| `sort_order` | no | integer | no | default=`0` | - |

## AttendancePolicyHourBandRead
<a id="attendancepolicyhourbandread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `min_minutes` | yes | integer | no | - | - |
| `max_minutes` | yes | integer | yes | - | - |
| `result_status` | yes | string | no | - | - |
| `sort_order` | yes | integer | no | - | - |

## AttendancePolicyLateBandInput
<a id="attendancepolicylatebandinput"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `min_minutes` | yes | integer | no | min=0.0 | - |
| `max_minutes` | no | integer | yes | min=0.0 | - |
| `classification` | yes | string | no | - | - |
| `counts_toward_cap` | no | boolean | no | default=`true` | - |
| `sort_order` | no | integer | no | default=`0` | - |

## AttendancePolicyLateBandRead
<a id="attendancepolicylatebandread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `min_minutes` | yes | integer | no | - | - |
| `max_minutes` | yes | integer | yes | - | - |
| `classification` | yes | string | no | - | - |
| `counts_toward_cap` | yes | boolean | no | - | - |
| `sort_order` | yes | integer | no | - | - |

## AttendancePolicyRead
<a id="attendancepolicyread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `code` | yes | string | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `AttendancePolicyCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## AttendancePolicyUpdate
<a id="attendancepolicyupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `is_active` | no | boolean | yes | - | - |

## AttendancePolicyVersionCreate
<a id="attendancepolicyversioncreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | no | string(date) | yes | - | - |
| `grace_in_minutes` | no | integer | no | min=0.0, default=`0` | - |
| `grace_out_minutes` | no | integer | no | min=0.0, default=`0` | - |
| `punch_rounding` | no | string | no | default=`"NONE"` | - |
| `rounding_minutes` | no | integer | yes | >=0.0 | - |
| `missing_punch_behaviour` | no | string | no | default=`"INCOMPLETE"` | - |
| `auto_close_after_minutes` | no | integer | yes | >=0.0 | - |
| `auto_close_uses_shift_end` | no | boolean | no | default=`true` | - |
| `missing_shift_behaviour` | no | string | no | default=`"INCOMPLETE"` | - |
| `half_day_split` | no | string | no | default=`"BY_HOURS"` | - |
| `half_day_boundary_minutes` | no | integer | yes | min=0.0 | - |
| `multi_punch_mode` | no | string | no | default=`"PAIR_ALL"` | - |
| `duplicate_punch_window_seconds` | no | integer | no | min=0.0, default=`60` | - |
| `core_hours_breach_behaviour` | no | string | no | default=`"FLAG"` | - |
| `early_out_uses_core_end` | no | boolean | no | default=`false` | - |
| `split_shift_block_mandatory` | no | boolean | no | default=`true` | - |
| `split_shift_missed_block_behaviour` | no | string | no | default=`"HALF_DAY"` | - |
| `split_shift_allow_hours_compensation` | no | boolean | no | default=`false` | - |
| `wfh_requires_punch` | no | boolean | no | default=`true` | - |
| `on_duty_requires_punch` | no | boolean | no | default=`false` | - |
| `wfh_uses_shift_hours` | no | boolean | no | default=`true` | - |
| `work_on_leave_behaviour` | no | string | no | default=`"KEEP_LEAVE"` | - |
| `excess_break_behaviour` | no | string | no | default=`"FLAG"` | - |
| `late_count_window` | no | string | no | default=`"MONTH"` | - |
| `lates_to_half_day_count` | no | integer | yes | >=0.0 | - |
| `early_departure_requires_approval` | no | boolean | no | default=`false` | - |
| `excess_break_count_window` | no | string | no | default=`"MONTH"` | - |
| `excess_break_days_to_half_day_count` | no | integer | yes | >=0.0 | - |
| `incomplete_at_lock_behaviour` | no | string | no | default=`"TREAT_ABSENT"` | - |
| `hour_bands` | no | array&lt;[AttendancePolicyHourBandInput](#attendancepolicyhourbandinput)&gt; | no | - | - |
| `late_bands` | no | array&lt;[AttendancePolicyLateBandInput](#attendancepolicylatebandinput)&gt; | no | - | - |
| `early_departure_bands` | no | array&lt;[AttendancePolicyEarlyDepartureBandInput](#attendancepolicyearlydeparturebandinput)&gt; | no | - | - |

## AttendancePolicyVersionPublishRequest
<a id="attendancepolicyversionpublishrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `publish_reason` | no | string | yes | - | - |
| `expected_previous_version` | no | integer | yes | - | - |

## AttendancePolicyVersionRead
<a id="attendancepolicyversionread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `policy_id` | yes | string(uuid) | no | - | - |
| `status` | yes | string | no | - | - |
| `version` | yes | integer | no | - | - |
| `effective_from` | yes | string(date) | yes | - | - |
| `effective_to` | yes | string(date) | yes | - | - |
| `grace_in_minutes` | yes | integer | no | - | - |
| `grace_out_minutes` | yes | integer | no | - | - |
| `punch_rounding` | yes | string | no | - | - |
| `rounding_minutes` | yes | integer | yes | - | - |
| `missing_punch_behaviour` | yes | string | no | - | - |
| `auto_close_after_minutes` | yes | integer | yes | - | - |
| `auto_close_uses_shift_end` | yes | boolean | no | - | - |
| `missing_shift_behaviour` | yes | string | no | - | - |
| `half_day_split` | yes | string | no | - | - |
| `half_day_boundary_minutes` | yes | integer | yes | - | - |
| `multi_punch_mode` | yes | string | no | - | - |
| `duplicate_punch_window_seconds` | yes | integer | no | - | - |
| `core_hours_breach_behaviour` | yes | string | no | - | - |
| `early_out_uses_core_end` | yes | boolean | no | - | - |
| `split_shift_block_mandatory` | yes | boolean | no | - | - |
| `split_shift_missed_block_behaviour` | yes | string | no | - | - |
| `split_shift_allow_hours_compensation` | yes | boolean | no | - | - |
| `wfh_requires_punch` | yes | boolean | no | - | - |
| `on_duty_requires_punch` | yes | boolean | no | - | - |
| `wfh_uses_shift_hours` | yes | boolean | no | - | - |
| `work_on_leave_behaviour` | yes | string | no | - | - |
| `excess_break_behaviour` | yes | string | no | - | - |
| `late_count_window` | yes | string | no | - | - |
| `lates_to_half_day_count` | yes | integer | yes | - | - |
| `early_departure_requires_approval` | yes | boolean | no | - | - |
| `excess_break_count_window` | yes | string | no | - | - |
| `excess_break_days_to_half_day_count` | yes | integer | yes | - | - |
| `incomplete_at_lock_behaviour` | yes | string | no | - | - |
| `hour_bands` | yes | array&lt;[AttendancePolicyHourBandRead](#attendancepolicyhourbandread)&gt; | no | - | - |
| `late_bands` | yes | array&lt;[AttendancePolicyLateBandRead](#attendancepolicylatebandread)&gt; | no | - | - |
| `early_departure_bands` | yes | array&lt;[AttendancePolicyEarlyDepartureBandRead](#attendancepolicyearlydeparturebandread)&gt; | no | - | - |
| `publish_reason` | yes | string | yes | - | - |
| `published_at` | yes | string | yes | - | - |
| `published_by` | yes | string(uuid) | yes | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `AttendancePolicyVersionCreate`: `company_id`, `created_at`, `effective_to`, `id`, `policy_id`, `publish_reason`, `published_at`, `published_by`, `status`, `updated_at`, `version`

## AttendancePolicyVersionUpdate
<a id="attendancepolicyversionupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | no | string(date) | yes | - | - |
| `grace_in_minutes` | no | integer | yes | min=0.0 | - |
| `grace_out_minutes` | no | integer | yes | min=0.0 | - |
| `punch_rounding` | no | string | yes | - | - |
| `rounding_minutes` | no | integer | yes | >=0.0 | - |
| `missing_punch_behaviour` | no | string | yes | - | - |
| `auto_close_after_minutes` | no | integer | yes | >=0.0 | - |
| `auto_close_uses_shift_end` | no | boolean | yes | - | - |
| `missing_shift_behaviour` | no | string | yes | - | - |
| `half_day_split` | no | string | yes | - | - |
| `half_day_boundary_minutes` | no | integer | yes | min=0.0 | - |
| `multi_punch_mode` | no | string | yes | - | - |
| `duplicate_punch_window_seconds` | no | integer | yes | min=0.0 | - |
| `core_hours_breach_behaviour` | no | string | yes | - | - |
| `early_out_uses_core_end` | no | boolean | yes | - | - |
| `split_shift_block_mandatory` | no | boolean | yes | - | - |
| `split_shift_missed_block_behaviour` | no | string | yes | - | - |
| `split_shift_allow_hours_compensation` | no | boolean | yes | - | - |
| `wfh_requires_punch` | no | boolean | yes | - | - |
| `on_duty_requires_punch` | no | boolean | yes | - | - |
| `wfh_uses_shift_hours` | no | boolean | yes | - | - |
| `work_on_leave_behaviour` | no | string | yes | - | - |
| `excess_break_behaviour` | no | string | yes | - | - |
| `late_count_window` | no | string | yes | - | - |
| `lates_to_half_day_count` | no | integer | yes | >=0.0 | - |
| `early_departure_requires_approval` | no | boolean | yes | - | - |
| `excess_break_count_window` | no | string | yes | - | - |
| `excess_break_days_to_half_day_count` | no | integer | yes | >=0.0 | - |
| `incomplete_at_lock_behaviour` | no | string | yes | - | - |
| `hour_bands` | no | array&lt;[AttendancePolicyHourBandInput](#attendancepolicyhourbandinput)&gt; | yes | - | - |
| `late_bands` | no | array&lt;[AttendancePolicyLateBandInput](#attendancepolicylatebandinput)&gt; | yes | - | - |
| `early_departure_bands` | no | array&lt;[AttendancePolicyEarlyDepartureBandInput](#attendancepolicyearlydeparturebandinput)&gt; | yes | - | - |

## AttendanceRangeCalculateInput
<a id="attendancerangecalculateinput"></a>

PAY-001 — backfill every employed day in `[date_from, date_to]` (company-local business dates), optionally only for `employee_ids`.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `date_from` | yes | string(date) | no | - | - |
| `date_to` | yes | string(date) | no | - | - |
| `employee_ids` | no | array&lt;string(uuid)&gt; | yes | minItems=1, maxItems=1000 | - |
| `legal_entity_id` | no | string(uuid) | yes | - | - |

## AttendanceRangeCalculateQueued
<a id="attendancerangecalculatequeued"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `task_id` | yes | string | no | - | - |
| `date_from` | yes | string(date) | no | - | - |
| `date_to` | yes | string(date) | no | - | - |
| `employee_ids` | yes | array&lt;string(uuid)&gt; | yes | - | - |
| `legal_entity_id` | no | string(uuid) | yes | - | - |

## FaceEnrollmentStatusRead
<a id="faceenrollmentstatusread"></a>

Everything a screen needs to decide what to show: the profile (if any) and the currently usable enrollment window (OPEN and unexpired), if any.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `profile` | yes | [FaceProfileRead](#faceprofileread) | yes | - | - |
| `open_window` | yes | [FaceEnrollmentWindowRead](#faceenrollmentwindowread) | yes | - | - |

## FaceEnrollmentWindowRead
<a id="faceenrollmentwindowread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `status` | yes | string | no | - | - |
| `opened_by_user_id` | yes | string(uuid) | yes | - | - |
| `opened_at` | yes | string | no | - | - |
| `expires_at` | yes | string | no | - | - |

## FaceLivenessSessionCreate
<a id="facelivenesssessioncreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `direction` | yes | enum `IN`/`OUT` | no | - | - |

## FaceLivenessSessionRead
<a id="facelivenesssessionread"></a>

`POST /attendance/face-punches/me/liveness-sessions` — the single-use challenge the next face punch must present, and how many frames it must carry.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `session_id` | yes | string(uuid) | no | - | - |
| `direction` | yes | string | no | - | - |
| `expires_at` | yes | string(date-time) | no | - | - |
| `frames_required` | yes | integer | no | - | - |

Server-generated / read-only vs `FaceLivenessSessionCreate`: `expires_at`, `frames_required`, `session_id`

## FaceProfileRead
<a id="faceprofileread"></a>

Never exposes `provider_person_id` (a handle into the vendor's biometric store) or the review photo's storage key.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `provider` | yes | string | no | - | - |
| `status` | yes | string | no | - | - |
| `reference_photo_count` | yes | integer | no | - | - |
| `consent_recorded_at` | yes | string | no | - | - |
| `enrolled_at` | yes | string | no | - | - |
| `enrolled_by_user_id` | yes | string(uuid) | yes | - | - |
| `has_review_photo` | yes | boolean | no | - | - |
| `reviewed_at` | yes | string | yes | - | - |
| `reviewed_by_user_id` | yes | string(uuid) | yes | - | - |
| `review_note` | yes | string | yes | - | - |
| `revoked_at` | yes | string | yes | - | - |
| `revoked_by_user_id` | yes | string(uuid) | yes | - | - |

## FaceProfileRejectInput
<a id="faceprofilerejectinput"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `note` | no | string | yes | maxLength=500 | - |

## FacePunchRead
<a id="facepunchread"></a>

`POST /attendance/face-punches/me` — the punch recorded plus the scores that justified it.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `punch` | yes | [PunchRead](#punchread) | no | - | - |
| `similarity` | yes | decimal (JSON **string**) | no | - | - |
| `liveness_score` | no | decimal (JSON **string**) | yes | - | - |

## LeaveDayProjectionRead
<a id="leavedayprojectionread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `attendance_date` | yes | string(date) | no | - | - |
| `leave_application_id` | yes | string(uuid) | no | - | - |
| `leave_type_id` | yes | string(uuid) | yes | - | - |
| `leave_type_code` | yes | string | yes | - | - |
| `fraction` | yes | string | no | - | - |
| `half` | yes | string | yes | - | - |
| `is_paid` | yes | boolean | no | - | - |
| `status` | yes | string | no | - | - |
| `source_version` | yes | integer | no | - | - |
| `synced_at` | yes | string | no | - | - |
| `cancelled_at` | yes | string | yes | - | - |
| `cancelled_reason` | yes | string | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

## LeaveProjectionCancelInput
<a id="leaveprojectioncancelinput"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `reason` | yes | string | no | minLength=1, maxLength=1000 | - |

## LeaveProjectionSync
<a id="leaveprojectionsync"></a>

Publishes (or republishes) one approved leave day projection — architecture §21's `LeaveDayProjection` read model. LM-14: the body only *identifies* the day (`employee_id` + `leave_application_id` + `attendance_date`). Leave type, fraction, half and paid/unpaid are always taken from the APPROVED `LeaveApplicationDay` in the Leave module; the optional fields below are accepted for backward compatibility and IGNORED, so a caller can never contradict the approved leave. The cross-row "active fractions for this employee-date must not exceed 1.00" check still happens in the service layer, on the authoritative fraction.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `attendance_date` | yes | string(date) | no | - | - |
| `leave_application_id` | yes | string(uuid) | no | - | - |
| `leave_type_id` | no | string(uuid) | yes | - | - |
| `leave_type_code` | no | string | yes | maxLength=30 | - |
| `fraction` | no | string | yes | - | - |
| `half` | no | string | yes | - | - |
| `is_paid` | no | boolean | yes | - | - |

## OvertimeActionRead
<a id="overtimeactionread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `action` | yes | string | no | - | - |
| `actor_user_id` | yes | string(uuid) | yes | - | - |
| `actor_employee_id` | yes | string(uuid) | yes | - | - |
| `stage` | yes | string | yes | - | - |
| `comment` | yes | string | yes | - | - |
| `created_at` | yes | string | no | - | - |

## OvertimePolicyCreate
<a id="overtimepolicycreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | yes | string | no | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |

## OvertimePolicyRateRowInput
<a id="overtimepolicyraterowinput"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `day_class` | yes | string | no | - | - |
| `classification_code` | yes | string | no | minLength=1, maxLength=50 | - |
| `multiplier_decimal` | no | number \| decimal (JSON **string**) | yes | - | - |
| `sort_order` | no | integer | no | default=`0` | - |

## OvertimePolicyRateRowRead
<a id="overtimepolicyraterowread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `day_class` | yes | string | no | - | - |
| `classification_code` | yes | string | no | - | - |
| `multiplier_decimal` | yes | decimal (JSON **string**) | yes | - | - |
| `sort_order` | yes | integer | no | - | - |

## OvertimePolicyRead
<a id="overtimepolicyread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `code` | yes | string | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `OvertimePolicyCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## OvertimePolicyUpdate
<a id="overtimepolicyupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `is_active` | no | boolean | yes | - | - |

## OvertimePolicyVersionCreate
<a id="overtimepolicyversioncreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | no | string(date) | yes | - | - |
| `eligibility` | no | string | no | default=`"SHIFT_FLAG"` | - |
| `min_ot_minutes` | no | integer | no | min=0.0, default=`0` | - |
| `rounding_minutes` | no | integer | yes | >=0.0 | - |
| `rounding_mode` | no | string | no | default=`"NONE"` | - |
| `requires_pre_approval` | no | boolean | no | default=`false` | - |
| `requires_post_approval` | no | boolean | no | default=`true` | - |
| `daily_cap_minutes` | no | integer | yes | >=0.0 | - |
| `weekly_cap_minutes` | no | integer | yes | >=0.0 | - |
| `monthly_cap_minutes` | no | integer | yes | >=0.0 | - |
| `comp_off_instead_of_pay` | no | boolean | no | default=`false` | - |
| `comp_off_expiry_days` | no | integer | yes | >=0.0 | - |
| `comp_off_day_length_minutes` | no | integer | yes | >=0.0 | - |
| `night_ot_mode` | no | string | no | default=`"SHIFT_FLAG"` | - |
| `night_window_start` | no | string | yes | - | - |
| `night_window_end` | no | string | yes | - | - |
| `approval_chain` | no | string | no | default=`"MANAGER"` | - |
| `rate_rows` | no | array&lt;[OvertimePolicyRateRowInput](#overtimepolicyraterowinput)&gt; | no | - | - |

## OvertimePolicyVersionPublishRequest
<a id="overtimepolicyversionpublishrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `publish_reason` | no | string | yes | - | - |
| `expected_previous_version` | no | integer | yes | - | - |

## OvertimePolicyVersionRead
<a id="overtimepolicyversionread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `policy_id` | yes | string(uuid) | no | - | - |
| `status` | yes | string | no | - | - |
| `version` | yes | integer | no | - | - |
| `effective_from` | yes | string(date) | yes | - | - |
| `effective_to` | yes | string(date) | yes | - | - |
| `eligibility` | yes | string | no | - | - |
| `min_ot_minutes` | yes | integer | no | - | - |
| `rounding_minutes` | yes | integer | yes | - | - |
| `rounding_mode` | yes | string | no | - | - |
| `requires_pre_approval` | yes | boolean | no | - | - |
| `requires_post_approval` | yes | boolean | no | - | - |
| `daily_cap_minutes` | yes | integer | yes | - | - |
| `weekly_cap_minutes` | yes | integer | yes | - | - |
| `monthly_cap_minutes` | yes | integer | yes | - | - |
| `comp_off_instead_of_pay` | yes | boolean | no | - | - |
| `comp_off_expiry_days` | yes | integer | yes | - | - |
| `comp_off_day_length_minutes` | yes | integer | yes | - | - |
| `night_ot_mode` | yes | string | no | - | - |
| `night_window_start` | yes | string | yes | - | - |
| `night_window_end` | yes | string | yes | - | - |
| `approval_chain` | yes | string | no | - | - |
| `rate_rows` | yes | array&lt;[OvertimePolicyRateRowRead](#overtimepolicyraterowread)&gt; | no | - | - |
| `publish_reason` | yes | string | yes | - | - |
| `published_at` | yes | string | yes | - | - |
| `published_by` | yes | string(uuid) | yes | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `OvertimePolicyVersionCreate`: `company_id`, `created_at`, `effective_to`, `id`, `policy_id`, `publish_reason`, `published_at`, `published_by`, `status`, `updated_at`, `version`

## OvertimePolicyVersionUpdate
<a id="overtimepolicyversionupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | no | string(date) | yes | - | - |
| `eligibility` | no | string | yes | - | - |
| `min_ot_minutes` | no | integer | yes | min=0.0 | - |
| `rounding_minutes` | no | integer | yes | >=0.0 | - |
| `rounding_mode` | no | string | yes | - | - |
| `requires_pre_approval` | no | boolean | yes | - | - |
| `requires_post_approval` | no | boolean | yes | - | - |
| `daily_cap_minutes` | no | integer | yes | >=0.0 | - |
| `weekly_cap_minutes` | no | integer | yes | >=0.0 | - |
| `monthly_cap_minutes` | no | integer | yes | >=0.0 | - |
| `comp_off_instead_of_pay` | no | boolean | yes | - | - |
| `comp_off_expiry_days` | no | integer | yes | >=0.0 | - |
| `comp_off_day_length_minutes` | no | integer | yes | >=0.0 | - |
| `night_ot_mode` | no | string | yes | - | - |
| `night_window_start` | no | string | yes | - | - |
| `night_window_end` | no | string | yes | - | - |
| `approval_chain` | no | string | yes | - | - |
| `rate_rows` | no | array&lt;[OvertimePolicyRateRowInput](#overtimepolicyraterowinput)&gt; | yes | - | - |

## OvertimeRecordRead
<a id="overtimerecordread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `attendance_day_id` | yes | string(uuid) | no | - | - |
| `attendance_date` | yes | string(date) | no | - | - |
| `overtime_policy_version_id` | yes | string(uuid) | no | - | - |
| `day_class` | yes | string | yes | - | - |
| `classification_code` | yes | string | yes | - | - |
| `configured_multiplier` | yes | string | yes | - | - |
| `minutes_detected` | yes | integer | no | - | - |
| `minutes_approved` | yes | integer | no | - | - |
| `status` | yes | string | no | - | - |
| `approval_chain` | yes | string | no | - | - |
| `approval_stage` | yes | string | yes | - | - |
| `resolved_approver_manager_id` | yes | string(uuid) | yes | - | - |
| `reviewed_by_user_id` | yes | string(uuid) | yes | - | - |
| `reviewed_at` | yes | string | yes | - | - |
| `reviewer_comment` | yes | string | yes | - | - |
| `rejection_reason` | yes | string | yes | - | - |
| `comp_off_minutes` | yes | integer | no | - | - |
| `comp_off_expiry_date` | yes | string(date) | yes | - | - |
| `version` | yes | integer | no | - | - |
| `actions` | yes | array&lt;[OvertimeActionRead](#overtimeactionread)&gt; | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

## OvertimeReviewInput
<a id="overtimereviewinput"></a>

Body for approve/reject — identical shape to `RegularizationReviewInput`.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `reviewer_comment` | no | string | yes | - | - |
| `rejection_reason` | no | string | yes | - | - |

## PolicyResolutionRead
<a id="policyresolutionread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `date` | yes | string(date) | no | - | - |
| `policy_kind` | yes | string | no | - | - |
| `config_incomplete` | yes | boolean | no | - | - |
| `resolved_policy_id` | no | string(uuid) | yes | - | - |
| `resolved_policy_name` | no | string | yes | - | - |
| `resolved_policy_code` | no | string | yes | - | - |
| `resolved_version_id` | no | string(uuid) | yes | - | - |
| `resolved_through` | no | string | yes | - | - |

## PunchCreateOnBehalf
<a id="punchcreateonbehalf"></a>

Body for `POST /attendance/punches` — HR/admin entering a punch for someone else (`ATTENDANCE.PUNCH_ON_BEHALF`). Client-supplied time is **required** here, because that is the workflow's entire purpose: recording an instant the server did not itself observe. It is bounded rather than trusted — not in the future (`FuturePunchTimeError`), not inside a `CLOSED` period (`_ensure_date_open`), not before the employee's employment began (`PunchTimeBeforeEmploymentError`). `reference` is the **reason** and is mandatory here (it stays optional on the self route), so every administrative override carries its own justification into the audit log. `source` is absent by design and server-assigned as `ADMIN`, closing `F-11`: the value can no longer be chosen by the caller on any route.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `punch_time` | yes | string(date-time) | no | - | - |
| `direction` | yes | string | no | - | - |
| `reference` | yes | string | no | minLength=1, maxLength=200 | - |
| `idempotency_key` | no | string | yes | maxLength=100 | - |

## PunchCreateSelf
<a id="punchcreateself"></a>

Body for `POST /attendance/punches/me` — employee self-service (`DEC-TZ-01`, SELECTED). **There is deliberately no `punch_time`, no `source`, and no `employee_id` field here.** The punch instant is the moment the server receives the request; the source is assigned from the authenticated route; the employee is the caller. Under `extra="forbid"` a client that sends any of the three gets a 422 rather than being quietly ignored, so an old client fails loudly instead of silently having its timestamp discarded. This is why no clock-skew tolerance is configurable anywhere in the module: with no client-supplied instant on this path there is nothing to compare a tolerance against. The control is structural, not a threshold (execution gate §7.1).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `direction` | yes | string | no | - | - |
| `reference` | no | string | yes | maxLength=200 | - |
| `idempotency_key` | no | string | yes | maxLength=100 | - |

## PunchRead
<a id="punchread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `punch_time` | yes | string | no | - | - |
| `direction` | yes | string | no | - | - |
| `source` | yes | string | no | - | - |
| `idempotency_key` | yes | string | yes | - | - |
| `recorded_by_user_id` | yes | string(uuid) | yes | - | - |
| `reference` | yes | string | yes | - | - |
| `created_at` | yes | string | no | - | - |

## RegularizationActionRead
<a id="regularizationactionread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `action` | yes | string | no | - | - |
| `actor_user_id` | yes | string(uuid) | yes | - | - |
| `actor_employee_id` | yes | string(uuid) | yes | - | - |
| `stage` | yes | string | yes | - | - |
| `comment` | yes | string | yes | - | - |
| `created_at` | yes | string | no | - | - |

## RegularizationPolicyAllowedTypeInput
<a id="regularizationpolicyallowedtypeinput"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `regularization_type` | yes | string | no | - | - |
| `sort_order` | no | integer | no | default=`0` | - |

## RegularizationPolicyAllowedTypeRead
<a id="regularizationpolicyallowedtyperead"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `regularization_type` | yes | string | no | - | - |
| `sort_order` | yes | integer | no | - | - |

## RegularizationPolicyCreate
<a id="regularizationpolicycreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | yes | string | no | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |

## RegularizationPolicyRead
<a id="regularizationpolicyread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `code` | yes | string | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `RegularizationPolicyCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## RegularizationPolicyUpdate
<a id="regularizationpolicyupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `is_active` | no | boolean | yes | - | - |

## RegularizationPolicyVersionCreate
<a id="regularizationpolicyversioncreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | no | string(date) | yes | - | - |
| `allow_employee_request` | no | boolean | no | default=`true` | - |
| `allow_manager_request` | no | boolean | no | default=`true` | - |
| `allow_hr_request` | no | boolean | no | default=`true` | - |
| `max_backdated_days` | no | integer | yes | min=0.0 | - |
| `max_requests_per_month` | no | integer | yes | >=0.0 | - |
| `reason_required` | no | boolean | no | default=`true` | - |
| `attachment_required` | no | boolean | no | default=`false` | - |
| `approval_chain` | no | string | no | default=`"MANAGER"` | - |
| `auto_approve_within_minutes` | no | integer | yes | min=0.0 | - |
| `blocked_when_locked` | no | boolean | no | default=`true` | - |
| `allowed_types` | no | array&lt;[RegularizationPolicyAllowedTypeInput](#regularizationpolicyallowedtypeinput)&gt; | no | - | - |

## RegularizationPolicyVersionPublishRequest
<a id="regularizationpolicyversionpublishrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `publish_reason` | no | string | yes | - | - |
| `expected_previous_version` | no | integer | yes | - | - |

## RegularizationPolicyVersionRead
<a id="regularizationpolicyversionread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `policy_id` | yes | string(uuid) | no | - | - |
| `status` | yes | string | no | - | - |
| `version` | yes | integer | no | - | - |
| `effective_from` | yes | string(date) | yes | - | - |
| `effective_to` | yes | string(date) | yes | - | - |
| `allow_employee_request` | yes | boolean | no | - | - |
| `allow_manager_request` | yes | boolean | no | - | - |
| `allow_hr_request` | yes | boolean | no | - | - |
| `max_backdated_days` | yes | integer | yes | - | - |
| `max_requests_per_month` | yes | integer | yes | - | - |
| `reason_required` | yes | boolean | no | - | - |
| `attachment_required` | yes | boolean | no | - | - |
| `approval_chain` | yes | string | no | - | - |
| `auto_approve_within_minutes` | yes | integer | yes | - | - |
| `blocked_when_locked` | yes | boolean | no | - | - |
| `allowed_types` | yes | array&lt;[RegularizationPolicyAllowedTypeRead](#regularizationpolicyallowedtyperead)&gt; | no | - | - |
| `publish_reason` | yes | string | yes | - | - |
| `published_at` | yes | string | yes | - | - |
| `published_by` | yes | string(uuid) | yes | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `RegularizationPolicyVersionCreate`: `company_id`, `created_at`, `effective_to`, `id`, `policy_id`, `publish_reason`, `published_at`, `published_by`, `status`, `updated_at`, `version`

## RegularizationPolicyVersionUpdate
<a id="regularizationpolicyversionupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | no | string(date) | yes | - | - |
| `allow_employee_request` | no | boolean | yes | - | - |
| `allow_manager_request` | no | boolean | yes | - | - |
| `allow_hr_request` | no | boolean | yes | - | - |
| `max_backdated_days` | no | integer | yes | min=0.0 | - |
| `max_requests_per_month` | no | integer | yes | >=0.0 | - |
| `reason_required` | no | boolean | yes | - | - |
| `attachment_required` | no | boolean | yes | - | - |
| `approval_chain` | no | string | yes | - | - |
| `auto_approve_within_minutes` | no | integer | yes | min=0.0 | - |
| `blocked_when_locked` | no | boolean | yes | - | - |
| `allowed_types` | no | array&lt;[RegularizationPolicyAllowedTypeInput](#regularizationpolicyallowedtypeinput)&gt; | yes | - | - |

## RegularizationRequestCreate
<a id="regularizationrequestcreate"></a>

Shared by self-submit and on-behalf-submit (router decides `employee_id` — architecture §23.2: self is SELF-scoped, on-behalf is COMPANY-scoped). WD-28 decision 2: every request must carry `requested_punches` and/or `requested_shift_id` so an approval always has a well-defined, engine-supported effect. Note this schema keeps the single-endpoint, body-decides-`employee_id` shape that the punch routes deliberately moved away from in Phase 1 (`ED-4`). That is intentional and not an oversight: regularization is approval-gated end to end, so the body cannot select a *privilege* here the way it could on the punch path — the reviewer, not the submitter, decides whether anything is written.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | no | string(uuid) | yes | - | - |
| `attendance_date` | yes | string(date) | no | - | - |
| `request_type` | yes | string | no | - | - |
| `reason` | no | string | yes | - | - |
| `requested_shift_id` | no | string(uuid) | yes | - | - |
| `attachment_reference` | no | string | yes | maxLength=500 | - |
| `requested_punches` | no | array&lt;[RegularizationRequestedPunchInput](#regularizationrequestedpunchinput)&gt; | no | - | - |

## RegularizationRequestRead
<a id="regularizationrequestread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `attendance_day_id` | yes | string(uuid) | yes | - | - |
| `attendance_date` | yes | string(date) | no | - | - |
| `request_type` | yes | string | no | - | - |
| `reason` | yes | string | yes | - | - |
| `requested_shift_id` | yes | string(uuid) | yes | - | - |
| `attachment_reference` | yes | string | yes | - | - |
| `status` | yes | string | no | - | - |
| `approval_chain` | yes | string | no | - | - |
| `approval_stage` | yes | string | yes | - | - |
| `regularization_policy_version_id` | yes | string(uuid) | no | - | - |
| `resolved_approver_manager_id` | yes | string(uuid) | yes | - | - |
| `submitted_by_user_id` | yes | string(uuid) | yes | - | - |
| `submitted_at` | yes | string | no | - | - |
| `reviewed_by_user_id` | yes | string(uuid) | yes | - | - |
| `reviewed_at` | yes | string | yes | - | - |
| `reviewer_comment` | yes | string | yes | - | - |
| `rejection_reason` | yes | string | yes | - | - |
| `applied_at` | yes | string | yes | - | - |
| `cancelled_at` | yes | string | yes | - | - |
| `cancelled_by_user_id` | yes | string(uuid) | yes | - | - |
| `version` | yes | integer | no | - | - |
| `requested_punches` | yes | array&lt;[RegularizationRequestedPunchRead](#regularizationrequestedpunchread)&gt; | no | - | - |
| `actions` | yes | array&lt;[RegularizationActionRead](#regularizationactionread)&gt; | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `RegularizationRequestCreate`: `actions`, `applied_at`, `approval_chain`, `approval_stage`, `attendance_day_id`, `cancelled_at`, `cancelled_by_user_id`, `company_id`, `created_at`, `id`, `regularization_policy_version_id`, `rejection_reason`, `resolved_approver_manager_id`, `reviewed_at`, `reviewed_by_user_id`, `reviewer_comment`, `status`, `submitted_at`, `submitted_by_user_id`, `updated_at`, `version`

## RegularizationRequestedPunchInput
<a id="regularizationrequestedpunchinput"></a>

One requested IN/OUT instant — reuses `_PUNCH_DIRECTIONS` verbatim (WD-12: don't redefine a second direction enum). `requested_time` carries the same `AwareIsoDatetime` contract as the on-behalf punch route: regularization is the *other* legitimately client-time-accepting path (execution gate §7.2), so it gets the identical wire guard rather than a weaker one. It stays approval-gated — the instant only becomes a `punch` row once a reviewer approves it.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `direction` | yes | string | no | - | - |
| `requested_time` | yes | string(date-time) | no | - | - |

## RegularizationRequestedPunchRead
<a id="regularizationrequestedpunchread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `direction` | yes | string | no | - | - |
| `requested_time` | yes | string | no | - | - |
| `sort_order` | yes | integer | no | - | - |

## RegularizationReviewInput
<a id="regularizationreviewinput"></a>

Body for approve/reject. `rejection_reason` is only meaningful (and only persisted) on reject; the service ignores it on approve rather than erroring, since a caller-supplied but-unused field on the wrong action is not itself invalid input.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `reviewer_comment` | no | string | yes | - | - |
| `rejection_reason` | no | string | yes | - | - |

## ShiftRosterBulkCreate
<a id="shiftrosterbulkcreate"></a>

Covers the brief's "fixed roster" (repeat one shift across a date range, expanded client-side into `entries`) and "monthly roster" (an explicit date→shift list) — no rotation-pattern generator is built server-side (WD-27); the backend only ever sees dated rows, matching the architecture's typed/no-generic-engine posture (WD-12).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `entries` | yes | array&lt;[ShiftRosterBulkCreateItem](#shiftrosterbulkcreateitem)&gt; | no | minItems=1, maxItems=366 | - |
| `reason` | no | string | yes | maxLength=500 | - |

## ShiftRosterBulkCreateItem
<a id="shiftrosterbulkcreateitem"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `roster_date` | yes | string(date) | no | - | - |
| `shift_id` | no | string(uuid) | yes | - | - |
| `is_week_off_override` | no | boolean | no | default=`false` | - |
| `is_holiday_working_override` | no | boolean | no | default=`false` | - |

## ShiftRosterCreate
<a id="shiftrostercreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `roster_date` | yes | string(date) | no | - | - |
| `shift_id` | no | string(uuid) | yes | - | - |
| `is_week_off_override` | no | boolean | no | default=`false` | - |
| `is_holiday_working_override` | no | boolean | no | default=`false` | - |
| `reason` | no | string | yes | maxLength=500 | - |

## ShiftRosterRead
<a id="shiftrosterread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `roster_date` | yes | string(date) | no | - | - |
| `shift_id` | yes | string(uuid) | yes | - | - |
| `is_week_off_override` | yes | boolean | no | - | - |
| `is_holiday_working_override` | yes | boolean | no | - | - |
| `status` | yes | string | no | - | - |
| `reason` | yes | string | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `ShiftRosterCreate`: `company_id`, `created_at`, `id`, `status`, `updated_at`, `version`

## ShiftRosterUpdate
<a id="shiftrosterupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `shift_id` | no | string(uuid) | yes | - | - |
| `is_week_off_override` | no | boolean | yes | - | - |
| `is_holiday_working_override` | no | boolean | yes | - | - |
| `reason` | no | string | yes | maxLength=500 | - |

## WorkOnLeaveKeepLeaveInput
<a id="workonleavekeepleaveinput"></a>

BUS-012 — HR confirms an approved full-day leave stands over punches on the same day.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `reason` | yes | string | no | minLength=1, maxLength=1000 | - |

