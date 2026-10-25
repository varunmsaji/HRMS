# Data models - shared

Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list (for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "Server-generated" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart (derived by name match - an inference, not a declared flag).

## Body_create_employee_import_v1_employee_imports_post
<a id="body_create_employee_import_v1_employee_imports_post"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `file` | yes | string | no | - | - |

## Body_create_face_punch_v1_attendance_face_punches_me_post
<a id="body_create_face_punch_v1_attendance_face_punches_me_post"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `direction` | yes | enum `IN`/`OUT` | no | - | - |
| `frames` | no | array&lt;string&gt; | yes | - | - |
| `liveness_session_id` | no | string(uuid) | yes | - | - |
| `idempotency_key` | no | string | yes | - | - |

## Body_submit_my_face_enrollment_v1_attendance_face_enrollment_me_post
<a id="body_submit_my_face_enrollment_v1_attendance_face_enrollment_me_post"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `front` | yes | string | no | - | - |
| `left` | yes | string | no | - | - |
| `right` | yes | string | no | - | - |
| `up` | yes | string | no | - | - |
| `down` | yes | string | no | - | - |
| `consent_confirmed` | yes | boolean | no | - | - |

## Body_upload_employee_document_v1_employees__employee_id__documents_post
<a id="body_upload_employee_document_v1_employees__employee_id__documents_post"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `document_type` | yes | string | no | - | - |
| `file` | yes | string | no | - | - |

## Body_upload_onboarding_document_v1_public_onboarding__token__documents_post
<a id="body_upload_onboarding_document_v1_public_onboarding__token__documents_post"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `document_type` | yes | string | no | - | - |
| `file` | yes | string | no | - | - |

## PaginationMeta
<a id="paginationmeta"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `page` | no | integer | no | default=`1` | - |
| `per_page` | no | integer | no | default=`25` | - |
| `total` | no | integer | no | default=`0` | - |
| `total_pages` | no | integer | no | default=`0` | - |
| `next_cursor` | no | string | yes | - | - |

## ResponseMeta
<a id="responsemeta"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `request_id` | yes | string | no | - | - |
| `server_time` | no | string | yes | - | - |

## hrms__modules__identity__schemas__CompanyDetail
<a id="hrms__modules__identity__schemas__companydetail"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `status` | yes | string | no | - | - |

## hrms__modules__platform__schemas__CompanyDetail
<a id="hrms__modules__platform__schemas__companydetail"></a>

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
| `country_code` | yes | string | no | - | - |
| `timezone` | yes | string | no | - | - |
| `status_reason` | yes | string | yes | - | - |
| `status_changed_at` | yes | string(date-time) | yes | - | - |
| `approved_at` | yes | string(date-time) | yes | - | - |
| `retention_until` | yes | string(date-time) | yes | - | - |
| `admin_locked` | yes | boolean | no | - | - |
| `subscription` | yes | [SubscriptionInfo](platform.md#subscriptioninfo) | yes | - | - |
| `usage` | yes | [UsageInfo](platform.md#usageinfo) | no | - | - |

## hrms__shared__pagination__DataEnvelope_CompanyDetail___1
<a id="hrms__shared__pagination__dataenvelope_companydetail___1"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `data` | yes | [hrms__modules__identity__schemas__CompanyDetail](#hrms__modules__identity__schemas__companydetail) | no | - | - |
| `meta` | yes | [ResponseMeta](#responsemeta) | no | - | - |

## hrms__shared__pagination__DataEnvelope_CompanyDetail___2
<a id="hrms__shared__pagination__dataenvelope_companydetail___2"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `data` | yes | [hrms__modules__platform__schemas__CompanyDetail](#hrms__modules__platform__schemas__companydetail) | no | - | - |
| `meta` | yes | [ResponseMeta](#responsemeta) | no | - | - |

