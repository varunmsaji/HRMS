# Department API

Endpoint reference for `/v1/departments`. See `01_Department_Module.md` for data model,
hierarchy rules, permissions, and audit behavior. Envelope shapes (`DataEnvelope`,
`ListEnvelope`, `ErrorEnvelope`), header conventions (`X-Company-Id`, `Authorization`,
`If-Match`), and error codes follow `docs/product/09_API_Standards.md` exactly as
Branch/Legal Entity do — no new conventions introduced.

All routes require `ORG.DEPARTMENT.MANAGE` and are company-scoped via `X-Company-Id` + JWT
only — the `{department_id}` path parameter is a plain resource identifier re-checked
against `company_id` server-side on every operation, never a tenant-scoping mechanism.

## GET /v1/departments

List all departments for the current company. Unfiltered, unpaginated (same low-cardinality
assumption as `GET /branches`/`GET /legal-entities`). No `GET /v1/departments/tree` endpoint
this slice — see `01_Department_Module.md` §1/§9.

**Response** `200` — `ListEnvelope<DepartmentRead>`

## POST /v1/departments

Create a department, optionally under a Branch and/or a parent Department.

**Request body** (`DepartmentCreate`, `extra=forbid`):

| Field | Required | Notes |
|---|---|---|
| `name` | yes | 1–150 chars |
| `code` | no | ≤30 chars |
| `branch_id` | no | Must belong to the current tenant if provided |
| `parent_id` | no | Must belong to the current tenant; must not create a cycle; hierarchy capped at 5 levels |

`is_active` and `version` are server-controlled and rejected if present in the body (schema
`extra="forbid"` → `422`).

**Responses**
- `201` — `DataEnvelope<DepartmentRead>`
- `422 VALIDATION_ERROR` — missing/malformed field
- `422 INVALID_BRANCH` — `branch_id` doesn't exist, is deleted, or belongs to another tenant
- `422 INVALID_PARENT_DEPARTMENT` — `parent_id` doesn't exist, is deleted, or belongs to
  another tenant
- `409 DEPARTMENT_CYCLE_DETECTED` — `parent_id` would create a cycle (only reachable on
  create via an already-existing cross-request race; ordinarily only relevant on update,
  since a new department has no id yet to appear in its own ancestor chain)
- `409 DEPARTMENT_MAX_DEPTH_EXCEEDED` — `parent_id`'s own ancestor chain is already at the
  5-level cap
- `403 PERMISSION_DENIED`

## GET /v1/departments/{department_id}

**Responses**
- `200` — `DataEnvelope<DepartmentRead>`
- `404 NOT_FOUND` — not found or belongs to another tenant (never `403` for a cross-tenant id)

## PATCH /v1/departments/{department_id}

Partial update. Requires `If-Match: <version>`. Same field set as `DepartmentCreate`, all
optional, plus `is_active` (togglable here — this is how reactivation happens). Changing
`parent_id` re-runs the full ownership/cycle/depth validation in §above, evaluated against
the department being updated (so a direct self-reference and indirect ancestor cycles are
both caught).

**Responses**
- `200` — `DataEnvelope<DepartmentRead>`
- `422 VALIDATION_ERROR` / `422 INVALID_BRANCH` / `422 INVALID_PARENT_DEPARTMENT`
- `409 STALE_RESOURCE` — `If-Match` doesn't match the current `version`; body includes the
  current row under `error.details[0].context.current`
- `409 DEPARTMENT_CYCLE_DETECTED` / `409 DEPARTMENT_MAX_DEPTH_EXCEEDED`
- `404 NOT_FOUND`
- `403 PERMISSION_DENIED`

No `409` dependency-blocking error exists for Department deactivation this slice — see
`01_Department_Module.md` §5.3.

## DELETE /v1/departments/{department_id}

Soft deactivation only (FR-ORG-014) — never a hard delete. Semantically identical to
`PATCH {is_active: false}`; requires `If-Match`. Returns the updated resource with
`is_active: false`, **not** `204`.

**Responses**
- `200` — `DataEnvelope<DepartmentRead>`
- `409 STALE_RESOURCE`
- `404 NOT_FOUND`
- `403 PERMISSION_DENIED`

## DepartmentRead shape

```json
{
  "id": "uuid",
  "company_id": "uuid",
  "branch_id": "uuid | null",
  "parent_id": "uuid | null",
  "name": "string",
  "code": "string | null",
  "is_active": "boolean",
  "version": "number",
  "created_at": "ISO 8601 string",
  "updated_at": "ISO 8601 string"
}
```

Note: `head_employee_id` is intentionally **not** in this shape — it exists at the DB/model
level only this slice (see `01_Department_Module.md` §1).
