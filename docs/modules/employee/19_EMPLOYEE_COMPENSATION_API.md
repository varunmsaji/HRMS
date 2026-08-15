# Employee Compensation (E-06) — API Reference

Sub-resource routes under `/v1/employees/{employee_id}/compensation`, per
`03_EMPLOYEE_API_PLAN.md §2.3`. All responses use the standard `DataEnvelope`/`ListEnvelope`
shape; errors use the standard `{"error": {"code": ..., "message": ..., "details": [...]}}`
envelope, same as every other route in this codebase.

---

## `GET /v1/employees/{employee_id}/compensation`

Full effective-dated history, ordered by `effective_from`, or — with `?as_of=YYYY-MM-DD` — a
single-item list containing the row covering that date (empty list if none).

- **Permission**: `EMPLOYEE.VIEW_COMPENSATION`
- **Response**: `200`, `ListEnvelope[CompensationRead]`
- **404**: employee does not exist or belongs to another tenant
- **403**: caller lacks `EMPLOYEE.VIEW_COMPENSATION` — the entire sub-resource is absent
  (outright denial), not a response with masked/degraded fields

## `GET /v1/employees/{employee_id}/compensation/{compensation_id}`

Single row by id.

- **Permission**: `EMPLOYEE.VIEW_COMPENSATION`
- **Response**: `200`, `DataEnvelope[CompensationRead]`
- **404**: employee or compensation row not found, or either belongs to another tenant

## `POST /v1/employees/{employee_id}/compensation`

Closes the employee's current compensation row (if any) and inserts a new one. Covers an
employee's first CTC and every later revision alike — distinguished only by `revision_type`.

- **Permission**: `EMPLOYEE.UPDATE_COMPENSATION` — a single static code, unlike Assignment's
  `POST .../assignments` (no dynamic permission selection by request body; `.VIEW_COMPENSATION`/
  `.UPDATE_COMPENSATION` map 1:1 to GET/POST).
- **Header**: `If-Match: <version>` — **required only when the employee already has a current
  compensation row** (the version being checked belongs to the row being closed, not the row
  being created). Omit entirely for an employee's very first compensation row.
- **Request body** (`CompensationCreate`, `extra="forbid"`) — **no carry-forward semantics**;
  every field below is always required, on every write:

  | Field | Type | Required | Notes |
  |---|---|---|---|
  | `effective_from` | date | yes | Must be strictly after the current row's `effective_from`, if one exists |
  | `annual_ctc_minor` | int (`>= 0`) | yes, always | No carry-forward, including on a revision |
  | `currency` | string, 3 chars | yes, always | No cross-check against a company-level currency setting |
  | `revision_type` | `JOINING` \| `ANNUAL` \| `PROMOTION` \| `CORRECTION` \| `MARKET` | yes, always | Use `JOINING` for an employee's first compensation row (including a rehire's first row) |
  | `revision_reason` | string | yes, always | Free text |

- **Response**: `201`, `DataEnvelope[CompensationRead]`

### Error codes

| HTTP | Code | Cause |
|---|---|---|
| `404` | `NOT_FOUND` | Employee does not exist or belongs to another tenant |
| `409` | `NO_ACTIVE_EMPLOYMENT` | `effective_from` falls on a date with no covering employment episode |
| `422` | `COMPENSATION_VERSION_REQUIRED` | A current row exists but `If-Match` was omitted |
| `422` | `INVALID_EFFECTIVE_FROM` | `effective_from` is not strictly after the current row's `effective_from` |
| `409` | `STALE_RESOURCE` | `If-Match` does not match the current row's `version` |
| `409` | `COMPENSATION_DATES_OVERLAP` | The `employee_compensation_no_overlap` GiST exclusion constraint rejected the insert (race-condition backstop) |
| `403` | `PERMISSION_DENIED` | Caller lacks `EMPLOYEE.UPDATE_COMPENSATION` (or `.VIEW_COMPENSATION` for GET) |
| `422` | (FastAPI validation) | `extra="forbid"`, `annual_ctc_minor < 0`, or an invalid `revision_type` — unknown/extra fields and invalid values rejected |

### Example — first compensation row (joining CTC)

```
POST /v1/employees/{employee_id}/compensation
{
  "effective_from": "2027-06-01",
  "annual_ctc_minor": 1200000000,
  "currency": "INR",
  "revision_type": "JOINING",
  "revision_reason": "Initial hire"
}
```
No `If-Match` header.

### Example — annual revision

```
POST /v1/employees/{employee_id}/compensation
If-Match: 1
{
  "effective_from": "2029-01-01",
  "annual_ctc_minor": 1500000000,
  "currency": "INR",
  "revision_type": "ANNUAL",
  "revision_reason": "Annual increment"
}
```

---

## Fields never accepted in the request body

`id`, `company_id`, `employee_id`, `version`, `effective_to` — all system-computed. Attempting
to set any of these (or any other unknown field) is rejected with a `422` by `extra="forbid"`.

## What this API does not do

- No bulk/batch compensation endpoint.
- No endpoint to close a compensation row without opening a new one — no "stop paying" close
  action.
- No `salary_structure_id`/component-breakdown field — Payroll's own catalogue tables do not
  exist yet.
- No approval-routing field or gate (`approved_by`/`approval_request_id`) — no engine exists.
- No `SELF`/`REPORTEES`/`REPORTEE_TREE` data-scope narrowing on the `GET` routes — gated only on
  the coarse `EMPLOYEE.VIEW_COMPENSATION` grant, same precedent as `Employment`/`Assignment`'s
  own reads. The data-scope resolver is E-10's scope.
- No Grade `min_ctc`/`max_ctc` band validation on `annual_ctc_minor` — PD-1, deliberately not
  built (see `18_EMPLOYEE_COMPENSATION_MODULE.md` §6).
