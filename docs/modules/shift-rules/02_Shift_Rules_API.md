# Shift Rules API

Endpoint reference for `/v1/shifts`. See `01_Shift_Rules_Module.md` for data model, business
rules, and audit/tenant behavior. Envelope shapes (`DataEnvelope`, `ListEnvelope`,
`ErrorEnvelope`), header conventions, and error codes follow `docs/product/
09_API_Standards.md` exactly as Designation/Department/Branch/Legal Entity/Grade do — no new
conventions introduced.

## Authentication

Every route requires a valid access token:

```
Authorization: Bearer <access_token>
```

## Tenant headers

```
X-Company-Id: <uuid>
```

`X-Company-Id` must identify a company the authenticated user belongs to; it is resolved by
`TenancyMiddleware`/`get_tenant_context` before any handler runs, not hand-parsed per route.
The `{shift_id}` path parameter on single-resource routes is a plain resource identifier,
re-checked against `company_id` server-side on every operation — it is never itself a
tenant-scoping mechanism, and a cross-tenant guess always resolves to `404`, never `403`.

## Permission

All five routes require:

```
ORG.SHIFT.MANAGE
```

A caller without this permission on the active company gets `403 PERMISSION_DENIED` on every
route below.

---

## GET /v1/shifts

List all shifts for the current company. Unfiltered, unpaginated (same low-cardinality
assumption as `GET /grades`/`GET /designations`), ordered by `created_at`. Soft-deactivated
rows are still returned (`is_active: false`) — this endpoint does not hide inactive shifts.

**Response** `200` — `ListEnvelope<ShiftRead>`

```json
{
  "data": [],
  "meta": { "request_id": "...", "server_time": "..." }
}
```

## POST /v1/shifts

Create a shift. `is_active` is always `true` on create — it is not a field on the request
schema at all (not merely server-overridden); sending it is rejected as an unknown field.

**Request body** (`ShiftCreate`, `extra=forbid`):

| Field | Required | Notes |
|---|---|---|
| `name` | yes | 1–100 chars |
| `code` | no | ≤30 chars; no uniqueness check |
| `start_time` | yes | `"HH:MM"`, pattern `^\d{2}:\d{2}$` |
| `end_time` | yes | `"HH:MM"`, pattern `^\d{2}:\d{2}$` |
| `break_minutes_paid` | no | Integer, `>= 0`, default `0` |
| `break_minutes_unpaid` | no | Integer, `>= 0`, default `0` |
| `grace_in_minutes` | no | Integer, `>= 0`, default `0` |
| `grace_out_minutes` | no | Integer, `>= 0`, default `0` |
| `half_day_threshold_hours` | no | Decimal, `>= 0`; must be `< min_hours_full_day` if both present |
| `min_hours_full_day` | no | Decimal, `>= 0` |
| `is_night_shift` | no | Boolean, default `false` |
| `is_cross_midnight` | no | Boolean, default `false`; gates the `end_time <= start_time` rule |
| `is_ot_eligible` | no | Boolean, default `false` |

**Example — regular shift**

```json
POST /v1/shifts
{
  "code": "GEN",
  "name": "General Shift",
  "start_time": "09:00",
  "end_time": "18:00",
  "break_minutes_unpaid": 30,
  "grace_in_minutes": 10
}
```

```json
201
{
  "data": {
    "id": "…",
    "company_id": "…",
    "name": "General Shift",
    "code": "GEN",
    "start_time": "09:00",
    "end_time": "18:00",
    "break_minutes_paid": 0,
    "break_minutes_unpaid": 30,
    "grace_in_minutes": 10,
    "grace_out_minutes": 0,
    "half_day_threshold_hours": null,
    "min_hours_full_day": null,
    "is_night_shift": false,
    "is_cross_midnight": false,
    "is_ot_eligible": false,
    "is_active": true,
    "version": 1,
    "created_at": "…",
    "updated_at": "…"
  },
  "meta": { "request_id": "...", "server_time": "..." }
}
```

**Example — cross-midnight shift**

```json
POST /v1/shifts
{
  "code": "NGT",
  "name": "Night Shift",
  "start_time": "22:00",
  "end_time": "06:00",
  "is_cross_midnight": true,
  "is_night_shift": true
}
```

`201` — accepted; `end_time` (`06:00`) is before `start_time` (`22:00`), which is exactly what
`is_cross_midnight: true` permits.

**Responses**
- `201` — `DataEnvelope<ShiftRead>`
- `422 REQUEST_VALIDATION_ERROR` — missing required field, malformed `"HH:MM"` string, unknown
  field in the body (mass-assignment attempt, e.g. sending `is_active` or `version` on create)
- `422 INVALID_SHIFT_TIME_RANGE` — `end_time <= start_time` and `is_cross_midnight` is not
  `true`
- `422 INVALID_SHIFT_HOURS_RANGE` — `half_day_threshold_hours >= min_hours_full_day` when
  both present
- `403 PERMISSION_DENIED`

No `409` on create — `code`/`name` carry no uniqueness constraint, so two shifts in the same
company (or two different companies) may share the same `code`.

## GET /v1/shifts/{shift_id}

**Responses**
- `200` — `DataEnvelope<ShiftRead>`
- `404 NOT_FOUND` — not found, or belongs to another tenant (never `403` for a cross-tenant id
  — existence is never leaked)
- `403 PERMISSION_DENIED`

## PATCH /v1/shifts/{shift_id}

Partial update. Requires `If-Match: <version>`. Same field set as `ShiftCreate`, all optional,
plus `is_active` (togglable here — this is how reactivation happens; there is no separate
reactivate endpoint). Only fields present in the request body are applied — omitted fields
keep their current stored value. `INVALID_SHIFT_TIME_RANGE`/`INVALID_SHIFT_HOURS_RANGE` are
re-validated against the *effective* row (patch value where present, otherwise the existing
stored value), not just the fields present in a given request.

**Example**

```json
PATCH /v1/shifts/{shift_id}
If-Match: 1
{ "grace_in_minutes": 15 }
```

```json
200
{
  "data": { "...": "...", "grace_in_minutes": 15, "version": 2 },
  "meta": { "request_id": "...", "server_time": "..." }
}
```

**Responses**
- `200` — `DataEnvelope<ShiftRead>`
- `422 REQUEST_VALIDATION_ERROR` — malformed field, unknown field (e.g. attempting to set
  `id`/`company_id` directly is rejected by `extra="forbid"`, not silently ignored)
- `422 INVALID_SHIFT_TIME_RANGE` / `422 INVALID_SHIFT_HOURS_RANGE`
- `409 STALE_RESOURCE` — `If-Match` doesn't match the current `version`; response body
  includes the current row under `error.details[0].context.current` so the client can offer
  "reload latest" / "cancel current changes"
- `404 NOT_FOUND`
- `403 PERMISSION_DENIED`

No dependency-blocking `409` exists for Shift deactivation this slice — see
`01_Shift_Rules_Module.md` §4.4.

## DELETE /v1/shifts/{shift_id}

Soft deactivation only (FR-ORG-014) — never a hard delete. Semantically identical to `PATCH
{"is_active": false}` (the router handler delegates to the same service method). Requires
`If-Match`. Returns the updated resource with `is_active: false`, **not** `204`.

**Responses**
- `200` — `DataEnvelope<ShiftRead>`, `data.is_active == false`
- `409 STALE_RESOURCE`
- `404 NOT_FOUND`
- `403 PERMISSION_DENIED`

### Reactivation

There is no `POST /v1/shifts/{id}/reactivate` endpoint. Reactivation is `PATCH
/v1/shifts/{shift_id}` with `{"is_active": true}` and the current `If-Match` version — the
same endpoint and the same underlying `update_shift` code path as any other field update. The
service layer determines the audit action (`SHIFT_DEACTIVATED` vs. `SHIFT_REACTIVATED` vs.
`SHIFT_UPDATED`) from the transition it observes, not from which HTTP verb was used.

---

## Validation error behavior

Two distinct `422` families exist, and clients should distinguish them by `error.code`, not by
status code alone:

1. **Schema-level (`REQUEST_VALIDATION_ERROR`)** — Pydantic rejects the request before it
   reaches the service layer: missing required field, wrong type, `"HH:MM"` pattern mismatch,
   negative integer where `ge=0` is required, or any field not defined on `ShiftCreate`/
   `ShiftUpdate` (both use `extra="forbid"`, so sending `is_active`/`version`/`id`/
   `company_id` on create, or `id`/`company_id` on update, is rejected outright rather than
   silently ignored — confirmed by `test_create_shift_mass_assignment_rejected`/
   `test_update_shift_mass_assignment_rejected`).
2. **Business-rule level (`INVALID_SHIFT_TIME_RANGE`, `INVALID_SHIFT_HOURS_RANGE`)** — the
   request is well-formed but violates §4.1/§4.2 of `01_Shift_Rules_Module.md`. Raised by the
   service layer after schema validation passes.

## 404 behavior

`GET`/`PATCH`/`DELETE` on a `shift_id` that doesn't exist, was created under a different
company, or has been filtered out by tenant isolation all return the same `404 NOT_FOUND` —
there is no way for a caller to distinguish "doesn't exist" from "exists but isn't yours" from
the response.

## 409 stale-resource behavior

Any `PATCH`/`DELETE` whose `If-Match` value doesn't equal the row's current `version` returns
`409 STALE_RESOURCE`. The row is not modified. `error.details[0].context.current` carries the
current `ShiftRead` snapshot, letting the client show the caller what changed without a
separate `GET`. `code`/`name` never cause a `409` (no uniqueness constraint exists), unlike
Grade's `GRADE_CODE_ALREADY_EXISTS`.

## 422 validation behavior

See "Validation error behavior" above. Both `INVALID_SHIFT_TIME_RANGE` and
`INVALID_SHIFT_HOURS_RANGE` are returned with `details[0].field` naming the more
user-relevant field (`end_time` and `half_day_threshold_hours` respectively) even though both
rules are two-field comparisons.

## Deactivation/reactivation behavior

See "DELETE /v1/shifts/{shift_id}" and "Reactivation" above. Summary: `DELETE` always
deactivates; `PATCH {"is_active": true|false}` can do either; both paths converge on the same
`update_shift` service method, the same optimistic-concurrency check, and the same audit
recording, differing only in which of `SHIFT_DEACTIVATED`/`SHIFT_REACTIVATED`/`SHIFT_UPDATED`
gets recorded based on the observed `is_active` transition.

## ShiftRead shape

```json
{
  "id": "uuid",
  "company_id": "uuid",
  "name": "string",
  "code": "string | null",
  "start_time": "HH:MM",
  "end_time": "HH:MM",
  "break_minutes_paid": "integer",
  "break_minutes_unpaid": "integer",
  "grace_in_minutes": "integer",
  "grace_out_minutes": "integer",
  "half_day_threshold_hours": "number | null",
  "min_hours_full_day": "number | null",
  "is_night_shift": "boolean",
  "is_cross_midnight": "boolean",
  "is_ot_eligible": "boolean",
  "is_active": "boolean",
  "version": "integer",
  "created_at": "ISO 8601 string",
  "updated_at": "ISO 8601 string"
}
```

`start_time`/`end_time` are always `"HH:MM"` strings, never minutes-since-midnight or ISO
durations. `half_day_threshold_hours`/`min_hours_full_day` are decimal hours (e.g. `4.5`), not
minutes. `week_off_pattern_id` does not exist at all this slice.
