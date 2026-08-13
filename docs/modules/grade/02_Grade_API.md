# Grade API

Endpoint reference for `/v1/grades`. See `01_Grade_Module.md` for data model, the
Designation relationship, permissions, and audit behavior. Envelope shapes (`DataEnvelope`,
`ListEnvelope`, `ErrorEnvelope`), header conventions (`X-Company-Id`, `Authorization`,
`If-Match`), and error codes follow `docs/product/09_API_Standards.md` exactly as
Designation/Department/Branch/Legal Entity do — no new conventions introduced.

All routes require `ORG.GRADE.MANAGE` and are company-scoped via `X-Company-Id` + JWT only —
the `{grade_id}` path parameter is a plain resource identifier re-checked against
`company_id` server-side on every operation, never a tenant-scoping mechanism.

## GET /v1/grades

List all grades for the current company. Unfiltered, unpaginated (same low-cardinality
assumption as `GET /designations`/`GET /departments`).

**Response** `200` — `ListEnvelope<GradeRead>`

## POST /v1/grades

Create a grade.

**Request body** (`GradeCreate`, `extra=forbid`):

| Field | Required | Notes |
|---|---|---|
| `code` | yes | 1–30 chars |
| `name` | yes | 1–100 chars |
| `level` | no | Integer |
| `min_ctc` | no | Integer minor units (paise), `>= 0` |
| `max_ctc` | no | Integer minor units (paise), `>= 0`; must be `>= min_ctc` if both present |
| `notice_period_days` | no | Integer, `>= 0` |
| `probation_days` | no | Integer, `>= 0` |
| `approval_limit` | no | Integer minor units (paise), `>= 0` |

`is_active` and `version` are server-controlled and rejected if present in the body (schema
`extra="forbid"` → `422`). `leave_policy_id` is not a schema field this slice — see
`01_Grade_Module.md` §1/§10.

**Responses**
- `201` — `DataEnvelope<GradeRead>`
- `422 VALIDATION_ERROR` — missing/malformed field
- `422 INVALID_CTC_RANGE` — `min_ctc` is greater than `max_ctc`
- `409 GRADE_CODE_ALREADY_EXISTS` — `code` already used by another grade in this company
- `403 PERMISSION_DENIED`

## GET /v1/grades/{grade_id}

**Responses**
- `200` — `DataEnvelope<GradeRead>`
- `404 NOT_FOUND` — not found or belongs to another tenant (never `403` for a cross-tenant id)

## PATCH /v1/grades/{grade_id}

Partial update. Requires `If-Match: <version>`. Same field set as `GradeCreate`, all optional,
plus `is_active` (togglable here — this is how reactivation happens). `min_ctc <= max_ctc` is
re-validated against the *effective* range (patch value where present, otherwise the
existing stored value).

**Responses**
- `200` — `DataEnvelope<GradeRead>`
- `422 VALIDATION_ERROR` / `422 INVALID_CTC_RANGE`
- `409 STALE_RESOURCE` — `If-Match` doesn't match the current `version`; body includes the
  current row under `error.details[0].context.current`
- `409 GRADE_CODE_ALREADY_EXISTS`
- `404 NOT_FOUND`
- `403 PERMISSION_DENIED`

No dependency-blocking `409` exists for Grade deactivation this slice — see
`01_Grade_Module.md` §4.3.

## DELETE /v1/grades/{grade_id}

Soft deactivation only (FR-ORG-014) — never a hard delete. Semantically identical to
`PATCH {is_active: false}`; requires `If-Match`. Returns the updated resource with
`is_active: false`, **not** `204`.

**Responses**
- `200` — `DataEnvelope<GradeRead>`
- `409 STALE_RESOURCE`
- `404 NOT_FOUND`
- `403 PERMISSION_DENIED`

## GradeRead shape

```json
{
  "id": "uuid",
  "company_id": "uuid",
  "code": "string",
  "name": "string",
  "level": "number | null",
  "min_ctc": "number | null",
  "max_ctc": "number | null",
  "notice_period_days": "number | null",
  "probation_days": "number | null",
  "approval_limit": "number | null",
  "is_active": "boolean",
  "version": "number",
  "created_at": "ISO 8601 string",
  "updated_at": "ISO 8601 string"
}
```

Money fields (`min_ctc`, `max_ctc`, `approval_limit`) are integer minor units (paise per
ADR-0006) — never floats, never pre-formatted with a currency symbol. `leave_policy_id` does
not exist at all this slice.

## Designation↔Grade — the `grade_id` field on `/v1/designations`

This slice also adds `grade_id: UUID | null` to `DesignationCreate`/`DesignationUpdate`/
`DesignationRead` (documented fully in `docs/modules/designation/02_Designation_API.md`,
updated alongside this slice). Summary:

- `POST /v1/designations` / `PATCH /v1/designations/{id}` accept an optional `grade_id`,
  validated for same-tenant ownership.
- `422 INVALID_GRADE` — `grade_id` doesn't exist, is deleted, or belongs to another tenant.
- Requires only `ORG.DESIGNATION.MANAGE`, not `ORG.GRADE.MANAGE`.
