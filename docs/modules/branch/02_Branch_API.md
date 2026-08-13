# Branch API

Endpoint reference for `/v1/branches`. See `01_Branch_Module.md` for data model, business
rules, permissions, and audit behavior. Envelope shapes (`DataEnvelope`, `ListEnvelope`,
`ErrorEnvelope`), header conventions (`X-Company-Id`, `Authorization`, `If-Match`), and error
codes follow `docs/product/09_API_Standards.md` exactly as Legal Entity does — no new
conventions introduced.

All routes require `ORG.BRANCH.MANAGE` and are company-scoped via `X-Company-Id` + JWT only
— the `{branch_id}` path parameter is a plain resource identifier re-checked against
`company_id` server-side on every operation, never a tenant-scoping mechanism.

## GET /v1/branches

List all branches for the current company. Unfiltered, unpaginated (same low-cardinality
assumption as `GET /legal-entities`).

**Response** `200` — `ListEnvelope<BranchRead>`

## POST /v1/branches

Create a branch under a Legal Entity owned by the current company.

**Request body** (`BranchCreate`, `extra=forbid`):

| Field | Required | Notes |
|---|---|---|
| `legal_entity_id` | yes | Must belong to the current tenant |
| `name` | yes | 1–200 chars |
| `code` | no | ≤30 chars |
| `address_line1` / `address_line2` | no | ≤200 chars each |
| `city` | no | ≤100 chars |
| `state_code` | no | ISO 3166-2:IN code, case-insensitive on input, normalized to upper |
| `pincode` | no | 6-digit Indian PIN |
| `timezone` | no | IANA identifier |
| `latitude` | no | `-90..90` |
| `longitude` | no | `-180..180` |
| `geofence_radius_m` | no | positive integer |

`is_active` and `version` are server-controlled and rejected if present in the body (schema
`extra="forbid"` → `422`).

**Responses**
- `201` — `DataEnvelope<BranchRead>`
- `422 VALIDATION_ERROR` — missing/malformed field
- `422 INVALID_LEGAL_ENTITY` — `legal_entity_id` doesn't exist, is deleted, or belongs to
  another tenant
- `403 PERMISSION_DENIED`

## GET /v1/branches/{branch_id}

**Responses**
- `200` — `DataEnvelope<BranchRead>`
- `404 NOT_FOUND` — not found or belongs to another tenant (never `403` for a cross-tenant id)

## PATCH /v1/branches/{branch_id}

Partial update. Requires `If-Match: <version>`. Same field set as `BranchCreate`, all
optional, plus `is_active` (togglable here — this is how reactivation happens).

**Responses**
- `200` — `DataEnvelope<BranchRead>`
- `422 VALIDATION_ERROR` / `422 INVALID_LEGAL_ENTITY`
- `409 STALE_RESOURCE` — `If-Match` doesn't match the current `version`; body includes the
  current row under `error.details[0].context.current`
- `409 BRANCH_HAS_ACTIVE_DEPARTMENTS` — attempted `is_active: false` while active Departments
  still reference this branch; body includes `active_department_count`
- `404 NOT_FOUND`
- `403 PERMISSION_DENIED`

## DELETE /v1/branches/{branch_id}

Soft deactivation only (FR-ORG-014) — never a hard delete. Semantically identical to
`PATCH {is_active: false}`; requires `If-Match`. Returns the updated resource with
`is_active: false`, **not** `204`.

**Responses**
- `200` — `DataEnvelope<BranchRead>`
- `409 STALE_RESOURCE` / `409 BRANCH_HAS_ACTIVE_DEPARTMENTS`
- `404 NOT_FOUND`
- `403 PERMISSION_DENIED`

## BranchRead shape

```json
{
  "id": "uuid",
  "company_id": "uuid",
  "legal_entity_id": "uuid",
  "name": "string",
  "code": "string | null",
  "address_line1": "string | null",
  "address_line2": "string | null",
  "city": "string | null",
  "state_code": "string | null",
  "pincode": "string | null",
  "timezone": "string | null",
  "latitude": "string | null",
  "longitude": "string | null",
  "geofence_radius_m": "number | null",
  "is_active": "boolean",
  "version": "number",
  "created_at": "ISO 8601 string",
  "updated_at": "ISO 8601 string"
}
```

Note: `latitude`/`longitude` serialize as JSON strings (Pydantic's default `Decimal` → JSON
behavior), not numbers — clients must `Number()`/parse them before arithmetic.
