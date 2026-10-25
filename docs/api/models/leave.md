# Data models - leave

Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list (for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "Server-generated" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart (derived by name match - an inference, not a declared flag).

## LeaveApplicationActionRead
<a id="leaveapplicationactionread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `action` | yes | string | no | - | - |
| `actor_user_id` | yes | string(uuid) | yes | - | - |
| `actor_employee_id` | yes | string(uuid) | yes | - | - |
| `stage` | yes | string | yes | - | - |
| `comment` | yes | string | yes | - | - |
| `created_at` | yes | string | no | - | - |

## LeaveApplicationCancelInput
<a id="leaveapplicationcancelinput"></a>

Optional body for cancel. `reason` is mandatory when HR cancels an approved application that has already started (decision 10); recorded whenever given.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `reason` | no | string | yes | maxLength=2000 | - |

## LeaveApplicationCreate
<a id="leaveapplicationcreate"></a>

Shared by self-submit and on-behalf-submit (router decides `employee_id`, mirrors `RegularizationRequestCreate`'s convention). `half_day` is only valid for a single-day application (`start_date == end_date`) — this first cut does not support a half-day boundary on a multi-day range (e.g. half day at the start, full days between, half day at the end); every day in a multi-day range is a full day or a sandwich-rule-generated day.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | no | string(uuid) | yes | - | - |
| `leave_type_id` | yes | string(uuid) | no | - | - |
| `start_date` | yes | string(date) | no | - | - |
| `end_date` | yes | string(date) | no | - | - |
| `half_day` | no | string | yes | - | - |
| `reason` | no | string | yes | - | - |
| `attachment_reference` | no | string | yes | maxLength=500 | - |
| `expected_delivery_date` | no | string(date) | yes | - | - |

## LeaveApplicationDayRead
<a id="leaveapplicationdayread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `calendar_date` | yes | string(date) | no | - | - |
| `fraction` | yes | decimal (JSON **string**) | no | - | - |
| `half` | yes | string | yes | - | - |
| `is_sandwich_generated` | yes | boolean | no | - | - |
| `is_lop` | yes | boolean | no | - | - |
| `leave_day_projection_id` | yes | string(uuid) | yes | - | - |

## LeaveApplicationRead
<a id="leaveapplicationread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `leave_type_id` | yes | string(uuid) | no | - | - |
| `leave_policy_version_id` | yes | string(uuid) | no | - | - |
| `start_date` | yes | string(date) | no | - | - |
| `end_date` | yes | string(date) | no | - | - |
| `total_days` | yes | decimal (JSON **string**) | no | - | - |
| `lop_days` | yes | decimal (JSON **string**) | no | - | - |
| `reason` | yes | string | yes | - | - |
| `attachment_reference` | yes | string | yes | - | - |
| `expected_delivery_date` | yes | string(date) | yes | - | - |
| `status` | yes | string | no | - | - |
| `approval_chain` | yes | string | no | - | - |
| `approval_stage` | yes | string | yes | - | - |
| `resolved_approver_manager_id` | yes | string(uuid) | yes | - | - |
| `resolved_department_head_id` | yes | string(uuid) | yes | - | - |
| `submitted_by_user_id` | yes | string(uuid) | yes | - | - |
| `submitted_at` | yes | string | no | - | - |
| `reviewed_by_user_id` | yes | string(uuid) | yes | - | - |
| `reviewed_at` | yes | string | yes | - | - |
| `reviewer_comment` | yes | string | yes | - | - |
| `rejection_reason` | yes | string | yes | - | - |
| `cancelled_at` | yes | string | yes | - | - |
| `cancelled_by_user_id` | yes | string(uuid) | yes | - | - |
| `cancellation_reason` | yes | string | yes | - | - |
| `version` | yes | integer | no | - | - |
| `days` | yes | array&lt;[LeaveApplicationDayRead](#leaveapplicationdayread)&gt; | no | - | - |
| `actions` | yes | array&lt;[LeaveApplicationActionRead](#leaveapplicationactionread)&gt; | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `LeaveApplicationCreate`: `actions`, `approval_chain`, `approval_stage`, `cancellation_reason`, `cancelled_at`, `cancelled_by_user_id`, `company_id`, `created_at`, `days`, `id`, `leave_policy_version_id`, `lop_days`, `rejection_reason`, `resolved_approver_manager_id`, `resolved_department_head_id`, `reviewed_at`, `reviewed_by_user_id`, `reviewer_comment`, `status`, `submitted_at`, `submitted_by_user_id`, `total_days`, `updated_at`, `version`

## LeaveApplicationReassignInput
<a id="leaveapplicationreassigninput"></a>

Decision 13 - HR hands a stuck approval stage to another approver. `reason` is mandatory.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `new_approver_employee_id` | yes | string(uuid) | no | - | - |
| `reason` | yes | string | no | minLength=1, maxLength=2000 | - |

## LeaveApplicationReviewInput
<a id="leaveapplicationreviewinput"></a>

Body for approve/reject — mirrors `RegularizationReviewInput` exactly. `rejection_reason` is only meaningful on reject; ignored (not an error) if supplied on approve.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `reviewer_comment` | no | string | yes | - | - |
| `rejection_reason` | no | string | yes | - | - |
| `excess_as_lop` | no | boolean | no | default=`false` | - |

## LeaveBalanceRead
<a id="leavebalanceread"></a>

One row per leave type that `requires_balance` — a type with zero ledger activity still appears, with `balance=0`, rather than being silently omitted. `balance` (LD-03's derived ledger sum, "Available Balance" in the client's own terminology) is never reduced by a pending application unless `reserve_balance_on_submission` is enabled for it — `reserved_balance` (LD-15) is always shown alongside it regardless, so HR/employee can see both figures separately (client spec §8) even when reservation itself is off.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `leave_type_id` | yes | string(uuid) | no | - | - |
| `leave_type_code` | yes | string | no | - | - |
| `leave_type_name` | yes | string | no | - | - |
| `balance` | yes | decimal (JSON **string**) | no | - | - |
| `reserved_balance` | yes | decimal (JSON **string**) | no | - | - |

## LeaveCombinationRuleCreate
<a id="leavecombinationrulecreate"></a>

`leave_type_id_a`/`_b` may be given in either order — the pair is unordered (LD-16).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `leave_type_id_a` | yes | string(uuid) | no | - | - |
| `leave_type_id_b` | yes | string(uuid) | no | - | - |
| `allowed` | yes | boolean | no | - | - |
| `reason` | no | string | yes | maxLength=2000 | - |

## LeaveCombinationRuleRead
<a id="leavecombinationruleread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `leave_type_id_a` | yes | string(uuid) | no | - | - |
| `leave_type_id_b` | yes | string(uuid) | no | - | - |
| `allowed` | yes | boolean | no | - | - |
| `reason` | yes | string | yes | - | - |
| `created_by_user_id` | yes | string(uuid) | yes | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `LeaveCombinationRuleCreate`: `company_id`, `created_at`, `created_by_user_id`, `id`, `updated_at`

## LeaveLedgerAdjustmentCreate
<a id="leaveledgeradjustmentcreate"></a>

Input for a manual HR balance correction, writing a generic `ADJUSTMENT` entry (ACCRUAL/APPLICATION/CARRY_FORWARD/COMP_OFF_CREDIT are reserved for L3/L4/L5; `ENCASHMENT` has its own dedicated, validated path — `LeaveLedgerEncashmentCreate` below, LD-19). `employee_id` lives in the body, mirroring `RegularizationRequestCreate`'s convention, not a query param.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `leave_type_id` | yes | string(uuid) | no | - | - |
| `amount` | yes | number \| string | no | - | Signed — positive credits, negative debits. |
| `effective_date` | yes | string(date) | no | - | - |
| `reason` | yes | string | no | minLength=1, maxLength=2000 | - |

## LeaveLedgerEncashmentCreate
<a id="leaveledgerencashmentcreate"></a>

Input for L2.5's dedicated encashment path (client spec §12, LD-19) — `days` is always positive (the amount encashed, debited from balance), unlike `LeaveLedgerAdjustmentCreate. amount`'s signed shape. Validated against the applicable `LeavePolicyVersion`'s `encashment_allowed`/`max_encashment_days`/`min_balance_after_encashment` before writing an `ENCASHMENT` entry — never a bare unvalidated adjustment.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employee_id` | yes | string(uuid) | no | - | - |
| `leave_type_id` | yes | string(uuid) | no | - | - |
| `days` | yes | number \| string | no | - | - |
| `effective_date` | yes | string(date) | no | - | - |
| `reason` | yes | string | no | minLength=1, maxLength=2000 | - |

## LeaveLedgerEntryRead
<a id="leaveledgerentryread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | no | - | - |
| `leave_type_id` | yes | string(uuid) | no | - | - |
| `entry_type` | yes | string | no | - | - |
| `amount` | yes | decimal (JSON **string**) | no | - | - |
| `effective_date` | yes | string(date) | no | - | - |
| `reference_id` | yes | string(uuid) | yes | - | - |
| `reason` | yes | string | yes | - | - |
| `created_by_user_id` | yes | string(uuid) | yes | - | - |
| `created_at` | yes | string | no | - | - |

## LeavePolicyCreate
<a id="leavepolicycreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `leave_type_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |

## LeavePolicyRead
<a id="leavepolicyread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `leave_type_id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `code` | yes | string | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `LeavePolicyCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## LeavePolicyUpdate
<a id="leavepolicyupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=150 | - |
| `code` | no | string | yes | maxLength=30 | - |
| `is_active` | no | boolean | yes | - | - |

## LeavePolicyVersionCreate
<a id="leavepolicyversioncreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | no | string(date) | yes | - | - |
| `allow_employee_request` | no | boolean | no | default=`true` | - |
| `allow_manager_request_on_behalf` | no | boolean | no | default=`true` | - |
| `allow_hr_request_on_behalf` | no | boolean | no | default=`true` | - |
| `max_backdated_days` | no | integer | yes | - | - |
| `max_requests_per_month` | no | integer | yes | - | - |
| `reason_required` | no | boolean | no | default=`true` | - |
| `attachment_required` | no | boolean | no | default=`false` | - |
| `approval_chain` | no | string | no | default=`"MANAGER"` | - |
| `half_day_allowed` | no | boolean | no | default=`true` | - |
| `accrual_frequency` | no | string | no | default=`"NONE"` | - |
| `accrual_rate_per_cycle` | no | number \| decimal (JSON **string**) | yes | - | - |
| `max_carry_forward_days` | no | number \| decimal (JSON **string**) | yes | - | - |
| `encashment_allowed` | no | boolean | no | default=`false` | - |
| `allow_negative_balance` | no | boolean | no | default=`false` | - |
| `negative_balance_floor` | no | number \| decimal (JSON **string**) | yes | - | - |
| `year_end_action` | no | string | no | default=`"CARRY_FORWARD"` | - |
| `sandwich_rule_enabled` | no | boolean | no | default=`true` | - |
| `reserve_balance_on_submission` | no | boolean | no | default=`false` | - |
| `pre_delivery_days` | no | integer | yes | min=0.0 | - |
| `post_delivery_days` | no | integer | yes | min=0.0 | - |
| `allowed_during_probation` | no | boolean | no | default=`true` | - |
| `accrue_during_probation` | no | boolean | no | default=`true` | - |
| `max_consecutive_days` | no | integer | no | min=1.0, max=90.0, default=`30` | - |
| `max_encashment_days` | no | number \| decimal (JSON **string**) | yes | - | - |
| `min_balance_after_encashment` | no | number \| decimal (JSON **string**) | yes | - | - |
| `encashment_frequency` | no | string | yes | maxLength=20 | - |
| `encashment_calculation_basis` | no | string | yes | maxLength=50 | - |

## LeavePolicyVersionPublishRequest
<a id="leavepolicyversionpublishrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `publish_reason` | no | string | yes | maxLength=2000 | - |
| `expected_previous_version` | no | integer | yes | - | - |

## LeavePolicyVersionRead
<a id="leavepolicyversionread"></a>

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
| `allow_manager_request_on_behalf` | yes | boolean | no | - | - |
| `allow_hr_request_on_behalf` | yes | boolean | no | - | - |
| `max_backdated_days` | yes | integer | yes | - | - |
| `max_requests_per_month` | yes | integer | yes | - | - |
| `reason_required` | yes | boolean | no | - | - |
| `attachment_required` | yes | boolean | no | - | - |
| `approval_chain` | yes | string | no | - | - |
| `half_day_allowed` | yes | boolean | no | - | - |
| `accrual_frequency` | yes | string | no | - | - |
| `accrual_rate_per_cycle` | yes | decimal (JSON **string**) | yes | - | - |
| `max_carry_forward_days` | yes | decimal (JSON **string**) | yes | - | - |
| `encashment_allowed` | yes | boolean | no | - | - |
| `allow_negative_balance` | yes | boolean | no | - | - |
| `negative_balance_floor` | yes | decimal (JSON **string**) | yes | - | - |
| `year_end_action` | yes | string | no | - | - |
| `sandwich_rule_enabled` | yes | boolean | no | - | - |
| `reserve_balance_on_submission` | yes | boolean | no | - | - |
| `pre_delivery_days` | yes | integer | yes | - | - |
| `post_delivery_days` | yes | integer | yes | - | - |
| `allowed_during_probation` | yes | boolean | no | - | - |
| `accrue_during_probation` | yes | boolean | no | - | - |
| `max_consecutive_days` | yes | integer | no | - | - |
| `max_encashment_days` | yes | decimal (JSON **string**) | yes | - | - |
| `min_balance_after_encashment` | yes | decimal (JSON **string**) | yes | - | - |
| `encashment_frequency` | yes | string | yes | - | - |
| `encashment_calculation_basis` | yes | string | yes | - | - |
| `publish_reason` | yes | string | yes | - | - |
| `published_at` | yes | string | yes | - | - |
| `published_by` | yes | string(uuid) | yes | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `LeavePolicyVersionCreate`: `company_id`, `created_at`, `effective_to`, `id`, `policy_id`, `publish_reason`, `published_at`, `published_by`, `status`, `updated_at`, `version`

## LeavePolicyVersionUpdate
<a id="leavepolicyversionupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `effective_from` | no | string(date) | yes | - | - |
| `allow_employee_request` | no | boolean | yes | - | - |
| `allow_manager_request_on_behalf` | no | boolean | yes | - | - |
| `allow_hr_request_on_behalf` | no | boolean | yes | - | - |
| `max_backdated_days` | no | integer | yes | - | - |
| `max_requests_per_month` | no | integer | yes | - | - |
| `reason_required` | no | boolean | yes | - | - |
| `attachment_required` | no | boolean | yes | - | - |
| `approval_chain` | no | string | yes | - | - |
| `half_day_allowed` | no | boolean | yes | - | - |
| `accrual_frequency` | no | string | yes | - | - |
| `accrual_rate_per_cycle` | no | number \| decimal (JSON **string**) | yes | - | - |
| `max_carry_forward_days` | no | number \| decimal (JSON **string**) | yes | - | - |
| `encashment_allowed` | no | boolean | yes | - | - |
| `allow_negative_balance` | no | boolean | yes | - | - |
| `negative_balance_floor` | no | number \| decimal (JSON **string**) | yes | - | - |
| `year_end_action` | no | string | yes | - | - |
| `sandwich_rule_enabled` | no | boolean | yes | - | - |
| `reserve_balance_on_submission` | no | boolean | yes | - | - |
| `pre_delivery_days` | no | integer | yes | min=0.0 | - |
| `post_delivery_days` | no | integer | yes | min=0.0 | - |
| `allowed_during_probation` | no | boolean | yes | - | - |
| `accrue_during_probation` | no | boolean | yes | - | - |
| `max_consecutive_days` | no | integer | yes | min=1.0, max=90.0 | - |
| `max_encashment_days` | no | number \| decimal (JSON **string**) | yes | - | - |
| `min_balance_after_encashment` | no | number \| decimal (JSON **string**) | yes | - | - |
| `encashment_frequency` | no | string | yes | maxLength=20 | - |
| `encashment_calculation_basis` | no | string | yes | maxLength=50 | - |

## LeaveTypeCreate
<a id="leavetypecreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `code` | yes | string | no | minLength=1, maxLength=30 | - |
| `name` | yes | string | no | minLength=1, maxLength=150 | - |
| `is_paid_default` | no | boolean | no | default=`true` | - |
| `requires_balance` | no | boolean | no | default=`true` | - |
| `is_comp_off` | no | boolean | no | default=`false` | - |
| `statutory_category` | no | string | yes | - | - |

## LeaveTypeRead
<a id="leavetyperead"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `code` | yes | string | no | - | - |
| `name` | yes | string | no | - | - |
| `is_paid_default` | yes | boolean | no | - | - |
| `requires_balance` | yes | boolean | no | - | - |
| `is_comp_off` | yes | boolean | no | - | - |
| `statutory_category` | yes | string | yes | - | - |
| `is_active` | yes | boolean | no | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `LeaveTypeCreate`: `company_id`, `created_at`, `id`, `is_active`, `updated_at`, `version`

## LeaveTypeUpdate
<a id="leavetypeupdate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `name` | no | string | yes | minLength=1, maxLength=150 | - |
| `is_paid_default` | no | boolean | yes | - | - |
| `requires_balance` | no | boolean | yes | - | - |
| `is_comp_off` | no | boolean | yes | - | - |
| `statutory_category` | no | string | yes | - | - |
| `is_active` | no | boolean | yes | - | - |

## LeaveYearSettingRead
<a id="leaveyearsettingread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `leave_year_type` | yes | string | no | - | - |
| `start_month` | yes | integer | yes | - | - |
| `start_day` | yes | integer | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

## LeaveYearSettingUpsert
<a id="leaveyearsettingupsert"></a>

`start_month`/`start_day` only apply to `CUSTOM` — required together when `leave_year_type=CUSTOM`, ignored (must be omitted) otherwise, since `CALENDAR`/`FINANCIAL` have fixed, non-configurable start dates and `ANNIVERSARY` has no company-wide date at all (LD-20).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `leave_year_type` | yes | string | no | - | - |
| `start_month` | no | integer | yes | min=1.0, max=12.0 | - |
| `start_day` | no | integer | yes | min=1.0, max=31.0 | - |

## StatutoryLeaveMinimumCreate
<a id="statutoryleaveminimumcreate"></a>

`state_code`/`establishment_type` are optional narrowing dimensions, not required identifiers — `None` on either means "applies regardless of that dimension" (LD-22).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `state_code` | no | string | yes | maxLength=10 | - |
| `establishment_type` | no | string | yes | maxLength=30 | - |
| `leave_category` | yes | string | no | - | - |
| `min_days_per_year` | yes | number \| decimal (JSON **string**) | no | - | - |
| `note` | no | string | yes | maxLength=2000 | - |

## StatutoryLeaveMinimumRead
<a id="statutoryleaveminimumread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `state_code` | yes | string | yes | - | - |
| `establishment_type` | yes | string | yes | - | - |
| `leave_category` | yes | string | no | - | - |
| `min_days_per_year` | yes | decimal (JSON **string**) | no | - | - |
| `note` | yes | string | yes | - | - |
| `created_by_user_id` | yes | string(uuid) | yes | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `StatutoryLeaveMinimumCreate`: `company_id`, `created_at`, `created_by_user_id`, `id`, `updated_at`

