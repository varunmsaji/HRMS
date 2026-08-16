# Employee Statutory (E-07) — API Reference

Sub-resource routes under `/v1/employees/{employee_id}/statutory`, per
`29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md §16`. All responses use the standard
`DataEnvelope`/`ListEnvelope` shape; errors use the standard `{"error": {"code": ..., "message":
..., "details": [...]}}` envelope, same as every other route in this codebase.

---

## `GET /v1/employees/{employee_id}/statutory`

Full effective-dated history, ordered by `effective_from`, or — with `?as_of=YYYY-MM-DD` — a
single-item list containing the row covering that date (empty list if none).

- **Permission**: `EMPLOYEE.VIEW_STATUTORY`
- **Data scope**: `COMPANY` only — the resolved `DataScope` is discarded regardless of the
  granting role's `data_scope` value (deliberate, plan §11.3)
- **Response**: `200`, `ListEnvelope[StatutoryRead]`
- **404**: employee does not exist or belongs to another tenant
- **403**: caller lacks `EMPLOYEE.VIEW_STATUTORY` — the entire sub-resource is absent (outright
  denial), not a response with masked/degraded fields

## `GET /v1/employees/{employee_id}/statutory/{statutory_id}`

Single row by id.

- **Permission**: `EMPLOYEE.VIEW_STATUTORY`
- **Response**: `200`, `DataEnvelope[StatutoryRead]`
- **404**: employee or statutory row not found, or either belongs to another tenant

## `POST /v1/employees/{employee_id}/statutory`

Closes the employee's current statutory row (if any) and inserts a new one. Covers an employee's
first statutory profile and every later revision alike.

- **Permission**: `EMPLOYEE.UPDATE_SENSITIVE` — scoped strictly to this route; not wired to
  `employee`'s PAN/Aadhaar/UAN fields (E-02) or `employee_bank` (E-08, does not exist yet)
- **Header**: `If-Match: <version>` — **required only when the employee already has a current
  statutory row** (the version being checked belongs to the row being closed, not the row being
  created). Omit entirely for an employee's very first statutory row.
- **Request body** (`StatutoryCreate`, `extra="forbid"`) — **no carry-forward semantics**; every
  field is always stated on every write:

  | Field | Type | Required | Notes |
  |---|---|---|---|
  | `effective_from` | date | yes | Must be strictly after the current row's `effective_from`, if one exists |
  | `is_pf_applicable` | bool | yes | |
  | `pf_number` | string (≤30) | no | Not required even when `is_pf_applicable=true` — no correlation enforced (plan §17/§26 item 6) |
  | `pf_wage_ceiling_opt_out` | bool | no, default `false` | |
  | `vpf_amount` | int (`>= 0`), minor units | no | |
  | `vpf_percentage` | number (`>= 0`) | no | |
  | `is_esi_applicable` | bool | yes | |
  | `esi_ip_number` | string (≤30) | no | Not required even when `is_esi_applicable=true` — same as `pf_number` |
  | `pt_state_code` | string (≤10) | no | |
  | `is_lwf_applicable` | bool | yes | |
  | `tax_regime` | `OLD` \| `NEW` | yes | Subject to the once-per-FY switch rule when a current row exists |
  | `is_director` | bool | no, default `false` | |
  | `is_international_worker` | bool | no, default `false` | |
  | `revision_reason` | string | yes | Free text |

- **Response**: `201`, `DataEnvelope[StatutoryRead]`

### Error codes

| HTTP | Code | Cause |
|---|---|---|
| `404` | `NOT_FOUND` | Employee does not exist or belongs to another tenant |
| `409` | `NO_ACTIVE_EMPLOYMENT` | `effective_from` falls on a date with no covering employment episode |
| `422` | `STATUTORY_VERSION_REQUIRED` | A current row exists but `If-Match` was omitted |
| `422` | `INVALID_EFFECTIVE_FROM` | `effective_from` is not strictly after the current row's `effective_from` |
| `409` | `STALE_RESOURCE` | `If-Match` does not match the current row's `version` |
| `409` | `STATUTORY_DATES_OVERLAP` | The `employee_statutory_no_overlap` GiST exclusion constraint rejected the insert (race-condition backstop) |
| `409` | `TAX_REGIME_SWITCH_NOT_ALLOWED` | `tax_regime` differs from the current row's and both `effective_from` dates fall in the same April-March fiscal year |
| `403` | `PERMISSION_DENIED` | Caller lacks `EMPLOYEE.UPDATE_SENSITIVE` (or `.VIEW_STATUTORY` for GET) |
| `422` | (FastAPI validation) | `extra="forbid"`, negative `vpf_amount`/`vpf_percentage`, or an invalid `tax_regime` — unknown/extra fields and invalid values rejected |

### Example — first statutory row (joining)

```
POST /v1/employees/{employee_id}/statutory
{
  "effective_from": "2027-06-01",
  "is_pf_applicable": true,
  "pf_number": "PF1234567890",
  "is_esi_applicable": false,
  "is_lwf_applicable": true,
  "tax_regime": "NEW",
  "revision_reason": "Initial statutory profile"
}
```
No `If-Match` header.

### Example — ESI becomes applicable (revision, same FY, no tax-regime change)

```
POST /v1/employees/{employee_id}/statutory
If-Match: 1
{
  "effective_from": "2027-12-01",
  "is_pf_applicable": true,
  "pf_number": "PF1234567890",
  "is_esi_applicable": true,
  "esi_ip_number": "ESI9876543210",
  "is_lwf_applicable": true,
  "tax_regime": "NEW",
  "revision_reason": "ESI became applicable"
}
```

---

## Fields never accepted in the request body

`id`, `company_id`, `employee_id`, `version`, `effective_to` — all system-computed. Attempting to
set any of these (or any other unknown field, including `uan`/`pan`/`aadhaar`) is rejected with a
`422` by `extra="forbid"`.

## What this API does not do

- No bulk/batch statutory endpoint.
- No endpoint to close a statutory row without opening a new one — no standalone "clear
  statutory" action.
- No `PATCH`/`DELETE` on an individual statutory row — history is never edited in place.
- No `SELF`/`REPORTEES`/`REPORTEE_TREE` data-scope narrowing on the `GET` routes — gated only on
  the coarse `EMPLOYEE.VIEW_STATUTORY` grant, a deliberate posture (see the module reference §8).
- No PF/ESI applicability-vs-identifier correlation validation, and no legal-entity-registration
  correlation validation — both open, undocumented product questions (plan §17/§26 items 6-7).
- No field-level masking of `pf_number`/`esi_ip_number`/`tax_regime`/etc. — whole-sub-resource
  gating only.
