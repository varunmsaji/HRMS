# Data models - platform

Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list (for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "Server-generated" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart (derived by name match - an inference, not a declared flag).

## CompanyListItem
<a id="companylistitem"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `status` | yes | enum `PENDING_APPROVAL`/`TRIAL`/`ACTIVE`/`SUSPENDED`/`REJECTED`/`TERMINATED` | no | - | - |
| `industry_code` | yes | string | yes | - | - |
| `company_size` | yes | string | yes | - | - |
| `created_at` | yes | string(date-time) | no | - | - |
| `trial_ends_at` | yes | string(date-time) | yes | - | - |
| `admin_email` | yes | string | yes | - | - |
| `admin_name` | yes | string | yes | - | - |

## DashboardData
<a id="dashboarddata"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `counts_by_status` | yes | map&lt;string, integer&gt; | no | - | - |
| `total_companies` | yes | integer | no | - | - |
| `pending_count` | yes | integer | no | - | - |
| `oldest_pending_since` | yes | string(date-time) | yes | - | - |
| `trials_expiring_within_7_days` | yes | integer | no | - | - |
| `registrations_last_30_days` | yes | array&lt;[DayCount](#daycount)&gt; | no | - | - |
| `registrations_total_30_days` | yes | integer | no | - | - |
| `locked_company_admins` | yes | integer | no | - | - |
| `active_platform_admins` | yes | integer | no | - | - |
| `pending` | yes | array&lt;[CompanyListItem](#companylistitem)&gt; | no | - | - |
| `trials_expiring` | yes | array&lt;[CompanyListItem](#companylistitem)&gt; | no | - | - |
| `retention_due` | yes | array&lt;[CompanyListItem](#companylistitem)&gt; | no | - | - |
| `recent_activity` | yes | array&lt;[PlatformAuditEntry](#platformauditentry)&gt; | no | - | - |

## DayCount
<a id="daycount"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `day` | yes | string(date) | no | - | - |
| `count` | yes | integer | no | - | - |

## LogEntriesOut
<a id="logentriesout"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `channel` | yes | string | no | - | - |
| `entries` | yes | array&lt;object&gt; | no | - | - |
| `next_before` | yes | string | yes | - | - |
| `truncated` | yes | boolean | no | - | - |

## LogFileOut
<a id="logfileout"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `channel` | yes | string | no | - | - |
| `size_bytes` | yes | integer | no | - | - |
| `modified_at` | yes | string(date-time) | yes | - | - |
| `backups` | yes | integer | no | - | - |

## LogFilesOut
<a id="logfilesout"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `enabled` | yes | boolean | no | - | - |
| `files` | yes | array&lt;[LogFileOut](#logfileout)&gt; | no | - | - |

## OptionalReasonRequest
<a id="optionalreasonrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `reason` | no | string | yes | minLength=3, maxLength=500 | - |

## PlanItem
<a id="planitem"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `code` | yes | string | no | - | - |
| `name` | yes | string | no | - | - |
| `description` | yes | string | yes | - | - |

## PlatformAdminCreate
<a id="platformadmincreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `username` | yes | string | no | minLength=3, maxLength=64, pattern=`^[A-Za-z0-9._-]+$` | - |
| `password` | yes | string | no | minLength=1, maxLength=128 | - |

## PlatformAdminItem
<a id="platformadminitem"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `username` | yes | string | no | - | - |
| `status` | yes | enum `ACTIVE`/`DISABLED` | no | - | - |
| `locked` | yes | boolean | no | - | - |
| `last_login_at` | yes | string(date-time) | yes | - | - |
| `created_at` | yes | string(date-time) | no | - | - |
| `is_you` | no | boolean | no | default=`false` | - |

## PlatformAdminPasswordReset
<a id="platformadminpasswordreset"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `password` | yes | string | no | minLength=1, maxLength=128 | - |

## PlatformAuditEntry
<a id="platformauditentry"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `created_at` | yes | string(date-time) | no | - | - |
| `actor_username` | yes | string | yes | - | - |
| `action` | yes | string | no | - | - |
| `company_id` | yes | string(uuid) | yes | - | - |
| `reason` | yes | string | yes | - | - |
| `before_status` | yes | string | yes | - | - |
| `after_status` | yes | string | yes | - | - |
| `request_id` | yes | string | yes | - | - |

## PlatformLoginRequest
<a id="platformloginrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `username` | yes | string | no | minLength=1, maxLength=64 | - |
| `password` | yes | string | no | minLength=1, maxLength=128 | - |

## PlatformMe
<a id="platformme"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `username` | yes | string | no | - | - |

## PlatformTokenData
<a id="platformtokendata"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `access_token` | yes | string | no | - | - |
| `token_type` | no | const `Bearer` | no | default=`"Bearer"` | - |
| `expires_at` | yes | string(date-time) | no | - | - |
| `username` | yes | string | no | - | - |

## ReasonRequest
<a id="reasonrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `reason` | yes | string | no | minLength=3, maxLength=500 | - |

## SubscriptionInfo
<a id="subscriptioninfo"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `plan_code` | yes | string | no | - | - |
| `plan_name` | yes | string | no | - | - |
| `status` | yes | string | no | - | - |
| `trial_ends_at` | yes | string(date-time) | yes | - | - |
| `seat_limit_override` | yes | integer | yes | - | - |

## SubscriptionPatch
<a id="subscriptionpatch"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `plan_code` | no | string | yes | minLength=1, maxLength=40 | - |
| `extend_trial_days` | no | integer | yes | min=1.0, max=365.0 | - |
| `seat_limit_override` | no | integer | yes | min=1.0, max=1000000.0 | - |
| `reason` | no | string | yes | minLength=3, maxLength=500 | - |

## TerminateRequest
<a id="terminaterequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `reason` | yes | string | no | minLength=3, maxLength=500 | - |
| `confirm_name` | yes | string | no | minLength=1, maxLength=200 | - |

## UsageInfo
<a id="usageinfo"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `employees` | yes | integer | no | - | - |
| `active_users` | yes | integer | no | - | - |

