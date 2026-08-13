# Designation API

Endpoint reference for `/v1/designations`. See `01_Designation_Module.md` for data model,
permissions, and audit behavior. Envelope shapes (`DataEnvelope`, `ListEnvelope`,
`ErrorEnvelope`), header conventions (`X-Company-Id`, `Authorization`, `If-Match`), and error
codes follow `docs/product/09_API_Standards.md` exactly as Department/Branch/Legal Entity
do — no new conventions introduced.

All routes require `ORG.DESIGNATION.MANAGE` and are company-scoped via `X-Company-Id` + JWT
only — the `{designation_id}` path parameter is a plain resource identifier re-checked
against `company_id` server-side on every operation, never a tenant-scoping mechanism.

## GET /v1/designations

List all designations for the current company. Unfiltered, unpaginated (same low-cardinality
assumption as `GET /departments`/`GET /branches`). No `department_id`/`status` query filters
this slice — see `01_Designation_Module.md` §9.

**Response** `200` — `ListEnvelope<DesignationRead>`

## POST /v1/designations

Create a designation, optionally under a Department and/or a Grade.

**Request body** (`DesignationCreate`, `extra=forbid`):

| Field | Required | Notes |
|---|---|---|
| `title` | yes | 1–150 chars |
| `code` | no | ≤30 chars |
| `department_id` | no | Must belong to the current tenant if provided |
| `grade_id` | no | Must belong to the current tenant if provided — added in the Grade slice, see `docs/modules/grade/00_GRADE_AUDIT.md` §3 |

`is_active` and `version` are server-controlled and rejected if present in the body (schema
`extra="forbid"` → `422`). `next_designation_id` and `jd_document_id` are not schema fields
this slice — see `01_Designation_Module.md` §1/§9.

**Responses**
- `201` — `DataEnvelope<DesignationRead>`
- `422 VALIDATION_ERROR` — missing/malformed field
- `422 INVALID_DEPARTMENT` — `department_id` doesn't exist, is deleted, or belongs to another
  tenant
- `422 INVALID_GRADE` — `grade_id` doesn't exist, is deleted, or belongs to another tenant
- `403 PERMISSION_DENIED`

## GET /v1/designations/{designation_id}

**Responses**
- `200` — `DataEnvelope<DesignationRead>`
- `404 NOT_FOUND` — not found or belongs to another tenant (never `403` for a cross-tenant id)

## PATCH /v1/designations/{designation_id}

Partial update. Requires `If-Match: <version>`. Same field set as `DesignationCreate`, all
optional, plus `is_active` (togglable here — this is how reactivation happens).

**Responses**
- `200` — `DataEnvelope<DesignationRead>`
- `422 VALIDATION_ERROR` / `422 INVALID_DEPARTMENT` / `422 INVALID_GRADE`
- `409 STALE_RESOURCE` — `If-Match` doesn't match the current `version`; body includes the
  current row under `error.details[0].context.current`
- `404 NOT_FOUND`
- `403 PERMISSION_DENIED`

No `409` dependency-blocking error exists for Designation deactivation this slice — see
`01_Designation_Module.md` §4.3.

## DELETE /v1/designations/{designation_id}

Soft deactivation only (FR-ORG-014) — never a hard delete. Semantically identical to
`PATCH {is_active: false}`; requires `If-Match`. Returns the updated resource with
`is_active: false`, **not** `204`.

**Responses**
- `200` — `DataEnvelope<DesignationRead>`
- `409 STALE_RESOURCE`
- `404 NOT_FOUND`
- `403 PERMISSION_DENIED`

## DesignationRead shape

```json
{
  "id": "uuid",
  "company_id": "uuid",
  "department_id": "uuid | null",
  "grade_id": "uuid | null",
  "title": "string",
  "code": "string | null",
  "is_active": "boolean",
  "version": "number",
  "created_at": "ISO 8601 string",
  "updated_at": "ISO 8601 string"
}
```

Note: `next_designation_id` is intentionally **not** in this shape — it exists at the
DB/model level only this slice (see `01_Designation_Module.md` §1/§9). `jd_document_id` does
not exist at all this slice. `grade_id` was added in the Grade slice — see
`docs/modules/grade/00_GRADE_AUDIT.md` §3 and `01_Designation_Module.md`'s own note on this
field.
