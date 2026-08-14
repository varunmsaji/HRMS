# Employee Assignment (E-04) — API Reference

Sub-resource routes under `/v1/employees/{employee_id}/assignments`, per
`03_EMPLOYEE_API_PLAN.md §2.2`. All responses use the standard `DataEnvelope`/`ListEnvelope`
shape; errors use the standard `{"error": {"code": ..., "message": ..., "details": [...]}}`
envelope, same as every other route in this codebase.

---

## `GET /v1/employees/{employee_id}/assignments`

Full effective-dated history, ordered by `effective_from`, or — with `?as_of=YYYY-MM-DD` — a
single-item list containing the row covering that date (empty list if none).

- **Permission**: `EMPLOYEE.VIEW`
- **Response**: `200`, `ListEnvelope[AssignmentRead]`
- **404**: employee does not exist or belongs to another tenant

## `GET /v1/employees/{employee_id}/assignments/{assignment_id}`

Single row by id.

- **Permission**: `EMPLOYEE.VIEW`
- **Response**: `200`, `DataEnvelope[AssignmentRead]`
- **404**: employee or assignment not found, or either belongs to another tenant

## `POST /v1/employees/{employee_id}/assignments`

Closes the employee's current assignment row (if any) and inserts a new one. Covers initial
placement, transfer, promotion, and manager change alike — distinguished only by `change_type`.

- **Permission**: `EMPLOYEE.PROMOTE` when `change_type = "PROMOTION"`; `EMPLOYEE.TRANSFER`
  otherwise. Selected dynamically from the request body — the only route in this module where
  the required permission isn't a single static code.
- **Header**: `If-Match: <version>` — **required only when the employee already has a current
  assignment row** (the version being checked belongs to the row being closed, not the row
  being created). Omit entirely for an employee's very first assignment.
- **Request body** (`AssignmentCreate`, `extra="forbid"`):

  | Field | Type | Required | Notes |
  |---|---|---|---|
  | `effective_from` | date | yes | Must be strictly after the current row's `effective_from`, if one exists |
  | `change_type` | `INITIAL` \| `TRANSFER` \| `PROMOTION` \| `MANAGER_CHANGE` | yes | Selects the required permission |
  | `change_reason` | string | no | Free text |
  | `branch_id` | UUID | conditionally | Required if no current row exists |
  | `department_id` | UUID | conditionally | Required if no current row exists |
  | `designation_id` | UUID | conditionally | Required if no current row exists |
  | `grade_id` | UUID | no | Carries forward if omitted and a current row exists |
  | `reporting_manager_id` | UUID | no | Must not equal `employee_id`; carries forward if omitted |
  | `dotted_line_manager_id` | UUID | no | Must not equal `employee_id`; carries forward if omitted |
  | `cost_centre_id` | UUID | no | No FK — no `cost_centre` table exists yet |
  | `work_location_type` | `OFFICE` \| `WFH` \| `HYBRID` \| `FIELD` | no | Carries forward if omitted |

- **Response**: `201`, `DataEnvelope[AssignmentRead]`

### Error codes

| HTTP | Code | Cause |
|---|---|---|
| `404` | `NOT_FOUND` | Employee does not exist or belongs to another tenant |
| `409` | `NO_ACTIVE_EMPLOYMENT` | `effective_from` falls on a date with no covering employment episode |
| `422` | `ASSIGNMENT_FIELDS_REQUIRED` | No current row exists and one of `branch_id`/`department_id`/`designation_id` is missing |
| `422` | `ASSIGNMENT_VERSION_REQUIRED` | A current row exists but `If-Match` was omitted |
| `422` | `INVALID_EFFECTIVE_FROM` | `effective_from` is not strictly after the current row's `effective_from` |
| `422` | `INVALID_BRANCH` / `INVALID_DEPARTMENT` / `INVALID_DESIGNATION` / `INVALID_GRADE` | Reference does not exist, is soft-deleted, or belongs to another tenant |
| `422` | `INVALID_REPORTING_MANAGER` | `reporting_manager_id`/`dotted_line_manager_id` does not resolve to a valid employee, or equals `employee_id` itself |
| `409` | `STALE_RESOURCE` | `If-Match` does not match the current row's `version` |
| `409` | `ASSIGNMENT_DATES_OVERLAP` | The `employee_assignment_no_overlap` GiST exclusion constraint rejected the insert (race-condition backstop) |
| `403` | `PERMISSION_DENIED` | Caller lacks the permission selected by `change_type` |
| `422` | (FastAPI validation) | `extra="forbid"` — unknown/extra fields rejected (mass-assignment protection) |

### Example — first placement

```
POST /v1/employees/{employee_id}/assignments
{
  "effective_from": "2027-06-01",
  "change_type": "INITIAL",
  "branch_id": "...",
  "department_id": "...",
  "designation_id": "..."
}
```
No `If-Match` header.

### Example — transfer (department change, everything else carried forward)

```
POST /v1/employees/{employee_id}/assignments
If-Match: 1
{
  "effective_from": "2028-04-01",
  "change_type": "TRANSFER",
  "change_reason": "Relocation",
  "department_id": "..."
}
```

### Example — promotion

```
POST /v1/employees/{employee_id}/assignments
If-Match: 2
{
  "effective_from": "2029-01-01",
  "change_type": "PROMOTION",
  "designation_id": "...",
  "grade_id": "..."
}
```

---

## Fields never accepted in the request body

`id`, `company_id`, `employee_id`, `version`, `effective_to` — all system-computed. Attempting
to set any of these (or any other unknown field) is rejected with a `422` by `extra="forbid"`.

## What this API does not do

- No bulk/batch assignment endpoint.
- No endpoint to close an assignment without opening a new one (no "resignation-only" close —
  see the known limitation in `12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md` §9 about
  assignment rows not auto-closing on employment termination).
- No `shift_id` field — ships in E-05.
- No `SELF`/`REPORTEES`/`REPORTEE_TREE` data-scope narrowing on the `GET` routes — gated only on
  the coarse `EMPLOYEE.VIEW` company-wide grant, same as `Employment`'s reads. The data-scope
  resolver is E-10's scope.
