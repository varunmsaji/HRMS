# Data models - onboarding

Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list (for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "Server-generated" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart (derived by name match - an inference, not a declared flag).

## OnboardingCaseCreate
<a id="onboardingcasecreate"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `candidate_first_name` | yes | string | no | minLength=1, maxLength=100 | - |
| `candidate_last_name` | no | string | yes | maxLength=100 | - |
| `personal_email` | yes | string(email) | no | - | - |
| `personal_mobile` | no | string | yes | maxLength=20 | - |
| `designation_id` | no | string(uuid) | yes | - | - |
| `department_id` | no | string(uuid) | yes | - | - |
| `branch_id` | no | string(uuid) | yes | - | - |
| `proposed_joining_date` | yes | string(date) | no | - | - |

## OnboardingCaseDetailRead
<a id="onboardingcasedetailread"></a>

`GET /onboarding-cases/{id}` (admin) — extends the list-safe `OnboardingCaseRead` with the five section JSON blobs and their review status, so HR can actually see what the candidate submitted, not just verify/reject blind (plan §9: "per-section review cards"). Deliberately not folded into `OnboardingCaseRead` itself — that shape is also used by `GET /onboarding-cases` (the list view), which has no business returning bank-account/statutory detail for every row on a list screen.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `status` | yes | string | no | - | - |
| `candidate_first_name` | yes | string | no | - | - |
| `candidate_last_name` | yes | string | yes | - | - |
| `personal_email` | yes | string | no | - | - |
| `personal_mobile` | yes | string | yes | - | - |
| `designation_id` | yes | string(uuid) | yes | - | - |
| `department_id` | yes | string(uuid) | yes | - | - |
| `branch_id` | yes | string(uuid) | yes | - | - |
| `legal_entity_id` | yes | string(uuid) | yes | - | - |
| `proposed_joining_date` | yes | string(date) | no | - | - |
| `created_by_user_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |
| `personal_info` | yes | object | no | - | - |
| `address_info` | yes | object | no | - | - |
| `emergency_contact` | yes | object | no | - | - |
| `bank_info` | yes | object | no | - | - |
| `statutory_info` | yes | object | no | - | - |
| `compensation_info` | yes | object | no | - | - |
| `previous_employment_info` | yes | object | no | - | - |
| `education_info` | yes | object | no | - | - |
| `nominee_info` | yes | object | no | - | - |
| `section_reviews` | yes | array&lt;[OnboardingSectionReviewRead](#onboardingsectionreviewread)&gt; | no | - | - |
| `token_status` | no | enum `ACTIVE`/`EXPIRED`/`REVOKED` | yes | - | - |
| `token_expires_at` | no | string | yes | - | - |

## OnboardingCaseRead
<a id="onboardingcaseread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `status` | yes | string | no | - | - |
| `candidate_first_name` | yes | string | no | - | - |
| `candidate_last_name` | yes | string | yes | - | - |
| `personal_email` | yes | string | no | - | - |
| `personal_mobile` | yes | string | yes | - | - |
| `designation_id` | yes | string(uuid) | yes | - | - |
| `department_id` | yes | string(uuid) | yes | - | - |
| `branch_id` | yes | string(uuid) | yes | - | - |
| `legal_entity_id` | yes | string(uuid) | yes | - | - |
| `proposed_joining_date` | yes | string(date) | no | - | - |
| `created_by_user_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | yes | - | - |
| `version` | yes | integer | no | - | - |
| `created_at` | yes | string | no | - | - |
| `updated_at` | yes | string | no | - | - |

Server-generated / read-only vs `OnboardingCaseCreate`: `company_id`, `created_at`, `created_by_user_id`, `employee_id`, `id`, `legal_entity_id`, `status`, `updated_at`, `version`

## OnboardingDocumentRead
<a id="onboardingdocumentread"></a>

Deliberately excludes `s3_key` — an internal storage detail, never returned to either the candidate or the admin UI (which gets a presigned URL instead, `OnboardingDocumentWithUrlRead` below).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `document_type` | yes | string | no | - | - |
| `original_filename` | yes | string | no | - | - |
| `content_type` | yes | string | no | - | - |
| `size_bytes` | yes | integer | no | - | - |
| `status` | yes | string | no | - | - |
| `rejection_reason` | yes | string | yes | - | - |
| `uploaded_at` | yes | string | no | - | - |

## OnboardingDocumentReviewRequest
<a id="onboardingdocumentreviewrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `status` | yes | enum `VERIFIED`/`REJECTED` | no | - | - |
| `rejection_reason` | no | string | yes | - | - |

## OnboardingDocumentWithUrlRead
<a id="onboardingdocumentwithurlread"></a>

The admin-only shape (`GET /onboarding-cases/{id}/documents`) — adds the short-lived presigned GET URL so document bytes never round-trip through the API server (plan §8.3).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `document_type` | yes | string | no | - | - |
| `original_filename` | yes | string | no | - | - |
| `content_type` | yes | string | no | - | - |
| `size_bytes` | yes | integer | no | - | - |
| `status` | yes | string | no | - | - |
| `rejection_reason` | yes | string | yes | - | - |
| `uploaded_at` | yes | string | no | - | - |
| `download_url` | yes | string | no | - | - |

## OnboardingInviteRead
<a id="onboardinginviteread"></a>

`POST /onboarding-cases/{id}/send-invite` (O3) — returns the updated case plus the raw `invite_url`, since this response is the *only* time the raw link is ever available (only its token's SHA-256 hash is persisted, plan §8.1). This is also what backs the admin UI's "Copy link" action (plan §9) independent of whether `email_sent` succeeded — a failed email delivery must not block HR from getting the link some other way.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `case` | yes | [OnboardingCaseRead](#onboardingcaseread) | no | - | - |
| `invite_url` | yes | string | no | - | - |
| `email_sent` | yes | boolean | no | - | - |

## OnboardingSectionReviewRead
<a id="onboardingsectionreviewread"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `section` | yes | string | no | - | - |
| `status` | yes | string | no | - | - |
| `rejection_reason` | yes | string | yes | - | - |

## OnboardingSectionReviewRequest
<a id="onboardingsectionreviewrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `status` | yes | enum `VERIFIED`/`REJECTED` | no | - | - |
| `rejection_reason` | no | string | yes | - | - |

## PublicOnboardingCaseRead
<a id="publiconboardingcaseread"></a>

`GET /public/onboarding/{token}` — deliberately narrower than `OnboardingCaseRead`: no `id`/`company_id`/`created_by_user_id`/`employee_id` (the candidate has no use for internal IDs and no session to authorize looking anything else up with), and `writable` tells the wizard which sections it may currently `PATCH` (module docstring, `ONBOARDING_CASE_WRITABLE_STATUSES`). `section_reviews` (O6) lets the wizard show which sections HR has already verified (lock the fields, nothing left to fix) versus rejected (show the reason) — deliberately just `section`/`status`/`rejection_reason`, no reviewer identity or timestamp, which the candidate has no use for.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `status` | yes | string | no | - | - |
| `candidate_first_name` | yes | string | no | - | - |
| `candidate_last_name` | yes | string | yes | - | - |
| `proposed_joining_date` | yes | string(date) | no | - | - |
| `writable` | yes | boolean | no | - | - |
| `personal_info` | yes | object | no | - | - |
| `address_info` | yes | object | no | - | - |
| `emergency_contact` | yes | object | no | - | - |
| `bank_info` | yes | object | no | - | - |
| `statutory_info` | yes | object | no | - | - |
| `compensation_info` | yes | object | no | - | - |
| `previous_employment_info` | yes | object | no | - | - |
| `education_info` | yes | object | no | - | - |
| `nominee_info` | yes | object | no | - | - |
| `section_reviews` | yes | array&lt;[OnboardingSectionReviewRead](#onboardingsectionreviewread)&gt; | no | - | - |

