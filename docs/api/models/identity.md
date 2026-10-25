# Data models - identity

Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list (for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "Server-generated" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart (derived by name match - an inference, not a declared flag).

## CompanySummary
<a id="companysummary"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `name` | yes | string | no | - | - |
| `is_primary` | yes | boolean | no | - | - |

## ForgotPasswordRequest
<a id="forgotpasswordrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `email` | yes | string(email) | no | - | - |

## LoginRequest
<a id="loginrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `email` | yes | string(email) | no | - | - |
| `password` | yes | string | no | minLength=1, maxLength=128 | - |
| `company_id` | no | string(uuid) | yes | - | - |

## MeResponseData
<a id="meresponsedata"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `user` | yes | [UserProfile](#userprofile) | no | - | - |

## PublicTokenResponseData
<a id="publictokenresponsedata"></a>

SEC-06 (RELEASE_HARDENING_PHASE_3A) — the actual HTTP response shape for every token-issuing endpoint (login, refresh, registration, invite acceptance): identical to `TokenResponseData` minus `refresh_token`, which travels only as an HttpOnly cookie (`hrms.core.auth.refresh_cookie.set_refresh_cookie`).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `access_token` | yes | string | no | - | - |
| `token_type` | no | string | no | default=`"Bearer"` | - |
| `expires_in_minutes` | yes | integer | no | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `companies` | no | array&lt;[CompanySummary](#companysummary)&gt; | no | - | - |

## RefreshRequest
<a id="refreshrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `refresh_token` | no | string | yes | - | - |

## ResendVerificationRequest
<a id="resendverificationrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `email` | yes | string(email) | no | - | - |

## ResetPasswordRequest
<a id="resetpasswordrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `token` | yes | string | no | - | - |
| `password` | yes | string | no | minLength=1, maxLength=128 | - |

## UserProfile
<a id="userprofile"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `email` | yes | string | yes | - | - |
| `company_id` | yes | string(uuid) | no | - | - |
| `employee_id` | yes | string(uuid) | yes | - | - |
| `permissions` | yes | array&lt;string&gt; | no | - | - |
| `company_timezone` | yes | string | no | - | - |
| `company_status` | no | string | no | default=`"ACTIVE"` | - |

## VerifyEmailRequest
<a id="verifyemailrequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `token` | yes | string | no | - | - |

