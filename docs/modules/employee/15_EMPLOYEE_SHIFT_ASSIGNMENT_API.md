# Employee Shift Assignment (E-05) — API Reference

Delta on top of `11_EMPLOYEE_ASSIGNMENT_API.md` (E-04) — no new route. `shift_id` and
`change_type = "SHIFT_CHANGE"` are additions to the existing
`POST /v1/employees/{employee_id}/assignments` request/response shape.

---

## `POST /v1/employees/{employee_id}/assignments` — additions

- **Permission**: unchanged selection rule — `EMPLOYEE.PROMOTE` when `change_type = "PROMOTION"`,
  `EMPLOYEE.TRANSFER` for every other value, **including** `SHIFT_CHANGE`.
- **Header**: `If-Match` requirement unchanged — required only when the employee already has a
  current assignment row.
- **Request body** (`AssignmentCreate`, `extra="forbid"`) — new field:

  | Field | Type | Required | Notes |
  |---|---|---|---|
  | `shift_id` | UUID | **conditionally** | **Required when `change_type = "SHIFT_CHANGE"`.** Otherwise optional; carries forward from the current row if omitted, same as every other optional field. |

- `change_type` now accepts a fifth value: `INITIAL \| TRANSFER \| PROMOTION \| MANAGER_CHANGE \|
  SHIFT_CHANGE`.
- **Response** (`AssignmentRead`): gains `shift_id: UUID | null`.

### New error codes

| HTTP | Code | Cause |
|---|---|---|
| `422` | `INVALID_SHIFT` | `shift_id` does not exist, is soft-deleted, or belongs to another tenant — same shape as `INVALID_BRANCH`/`INVALID_GRADE`/etc. |
| `422` | `SHIFT_ID_REQUIRED` | `change_type = "SHIFT_CHANGE"` was requested with no `shift_id` in the body |

All other error codes from `11_EMPLOYEE_ASSIGNMENT_API.md`'s table are unchanged and apply
identically regardless of `change_type`.

### Example — pure shift change

```
POST /v1/employees/{employee_id}/assignments
If-Match: 2
{
  "effective_from": "2028-04-01",
  "change_type": "SHIFT_CHANGE",
  "shift_id": "..."
}
```

Every other field (branch/department/designation/grade/managers/cost_centre/work_location_type)
carries forward unchanged from the current row.

### Example — a deactivated shift is still a valid reference

A shift with `is_active = false` (but not soft-deleted) is a valid `shift_id` reference — the
ownership check does not gate on `is_active`, matching every sibling reference field's existing
depth (see module reference §4). This is intentional, not an oversight to fix later.

## `GET /v1/employees/{employee_id}/assignments` / `.../{assignment_id}`

No change beyond `shift_id` now appearing in every `AssignmentRead` in the response, including
`?as_of=` results.

## What this API still does not do

- No `GET /v1/employees/{employee_id}/shifts` or any other shift-specific sub-resource — reading
  an employee's current shift is `GET .../assignments?as_of=<date>` returning `shift_id`, the
  same as every other assignment field.
- No `PATCH`/`DELETE` on an individual assignment row — unchanged from E-04.
- No bulk/batch shift-reassignment endpoint.
