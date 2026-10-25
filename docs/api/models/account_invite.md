# Data models - account_invite

Generated from the Pydantic/OpenAPI schemas. `Required` = present in the schema's `required` list (for *Read* models this means the server always sends it). `Nullable` = schema allows `null`. "Server-generated" lists fields that appear on a `*Read` model but not on its `*Create`/`*Update` counterpart (derived by name match - an inference, not a declared flag).

## AcceptInviteRequest
<a id="acceptinviterequest"></a>

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `password` | yes | string | no | minLength=1, maxLength=128 | - |
| `first_name` | no | string | yes | maxLength=100 | - |
| `last_name` | no | string | yes | maxLength=100 | - |

## AccountInviteRead
<a id="accountinviteread"></a>

Returned by both issue endpoints — same "raw link is only ever available here" shape as `OnboardingInviteRead` (only the token's SHA-256 hash is persisted).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `id` | yes | string(uuid) | no | - | - |
| `email` | yes | string | no | - | - |
| `role_code` | yes | string | no | - | - |
| `expires_at` | yes | string(date-time) | no | - | - |
| `invite_url` | yes | string | no | - | - |
| `email_sent` | yes | boolean | no | - | - |

## PublicAccountInviteRead
<a id="publicaccountinviteread"></a>

Shown by the public `GET .../{token}` route before the accept form — enough for the invitee to recognize what they're accepting, nothing more (no role/permission detail). `existing_account` (SEC-08) tells the frontend whether `POST .../accept` will create a new account or authenticate an existing one — the invitee's own email is already known to them (it's the address the invite was sent to), so surfacing this is not an enumeration risk; it lets the accept form ask for a login password instead of a new one.

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `email` | yes | string | no | - | - |
| `company_name` | yes | string | no | - | - |
| `expires_at` | yes | string(date-time) | no | - | - |
| `existing_account` | yes | boolean | no | - | - |

## RoleAssignmentRequest
<a id="roleassignmentrequest"></a>

`PATCH /users/{user_id}/roles` — full replace, not a diff (module docstring, `repository.replace_user_roles`).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `role_codes` | no | array&lt;string&gt; | no | - | - |

## UserInviteRequest
<a id="userinviterequest"></a>

`POST /users/invite` — invites someone as a second admin/HR user, with no `Employee` record required. `email` is lowercased before use (`OrganisationService.register_company`'s own convention).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `email` | yes | string(email) | no | - | - |
| `role_code` | yes | string | no | - | - |

## UserSummary
<a id="usersummary"></a>

`GET /users` row — backs the minimal Settings > Users screen (doc 41 Phase 4).

| Field | Required | Type | Nullable | Constraints / default | Description |
|---|---|---|---|---|---|
| `user_id` | yes | string(uuid) | no | - | - |
| `email` | yes | string | yes | - | - |
| `first_name` | yes | string | yes | - | - |
| `last_name` | yes | string | yes | - | - |
| `is_primary` | yes | boolean | no | - | - |
| `status` | yes | string | no | - | - |
| `role_codes` | yes | array&lt;string&gt; | no | - | - |

