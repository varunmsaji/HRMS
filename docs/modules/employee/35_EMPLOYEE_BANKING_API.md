# Employee Banking (E-08) — API Reference

Sub-resource routes under `/v1/employees/{employee_id}/bank`, per
`33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md §20`. All responses use the standard
`DataEnvelope`/`ListEnvelope` shape; errors use the standard `{"error": {"code": ...,
"message": ..., "details": [...]}}` envelope, same as every other route in this codebase.

---

## `GET /v1/employees/{employee_id}/bank`

Full effective-dated history, ordered by `effective_from`, or — with `?as_of=YYYY-MM-DD` — a
single-item list containing the row covering that date (empty list if none).

- **Permission**: `EMPLOYEE.VIEW_BANKING`
- **Data scope**: `SELF` / `REPORTEES` / `REPORTEE_TREE` / `COMPANY`, resolved and bound —
  **unlike Statutory**, the caller's `DataScope` is not discarded (module reference §7). A caller
  holding only `SELF` scope sees their own bank record only; an out-of-scope `employee_id` in the
  path returns `404`, identical in shape to a nonexistent or cross-tenant id.
- **Response**: `200`, `ListEnvelope[BankRead]`
- **404**: employee does not exist, belongs to another tenant, or is out of the caller's resolved
  data scope
- **403**: caller lacks `EMPLOYEE.VIEW_BANKING` — the entire sub-resource is absent (outright
  denial), not a response with masked/degraded fields

## `GET /v1/employees/{employee_id}/bank/{bank_id}`

Single row by id.

- **Permission**: `EMPLOYEE.VIEW_BANKING`
- **Data scope**: same as the list route above
- **Response**: `200`, `DataEnvelope[BankRead]`
- **404**: employee or bank row not found, either belongs to another tenant, or the employee is
  out of the caller's resolved data scope

## `POST /v1/employees/{employee_id}/bank`

Closes the employee's current bank row (if any) and inserts a new one. Covers an employee's first
bank account and every later revision alike.

- **Permission**: `EMPLOYEE.UPDATE_SENSITIVE` — the same code E-07 added, widened to a second
  write route
- **Data scope**: not applied — `COMPANY`-wide, matching every other write route in this module
- **Header**: `If-Match: <version>` — **required only when the employee already has a current
  bank row** (the version being checked belongs to the row being closed, not the row being
  created). Omit entirely for an employee's very first bank row. **Note**: because termination
  never closes the current row (module reference §6), a rehired employee's first post-rejoin
  write will usually still require `If-Match` against the pre-exit row's version — this is
  different from every sibling sub-resource's rehire write.
- **Request body** (`BankCreate`, `extra="forbid"`) — no carry-forward semantics; every field is
  always stated on every write:

  | Field | Type | Required | Notes |
  |---|---|---|---|
  | `effective_from` | date | yes | Must be strictly after the current row's `effective_from`, if one exists |
  | `account_holder_name` | string (≤150) | no | |
  | `account_number_enc` | string | no | Plaintext at the API boundary — see module reference §5 for the encryption caveat |
  | `bank_name` | string (≤150) | no | |
  | `ifsc` | string (≤15) | no | No format validation beyond the length bound (module reference §8) |
  | `branch_name` | string (≤150) | no | |
  | `payment_mode` | `BANK` \| `CASH` \| `CHEQUE` \| `UPI` | yes | |

- **Response**: `201`, `DataEnvelope[BankRead]` — `is_primary=true`, `verification_status=
  "PENDING"`, `penny_drop_reference=null` unconditionally, regardless of request body content
  (none of the three are accepted fields at all)

### Error codes

| HTTP | Code | Cause |
|---|---|---|
| `404` | `NOT_FOUND` | Employee does not exist, belongs to another tenant, or (GET only) is out of the caller's resolved data scope |
| `409` | `NO_ACTIVE_EMPLOYMENT` | `effective_from` falls on a date with no covering employment episode — including a date strictly after a `TERMINATED` employment's `last_working_day` (module reference §4, known limitation) |
| `422` | `BANK_VERSION_REQUIRED` | A current row exists but `If-Match` was omitted |
| `422` | `INVALID_EFFECTIVE_FROM` | `effective_from` is not strictly after the current row's `effective_from` |
| `409` | `STALE_RESOURCE` | `If-Match` does not match the current row's `version` |
| `409` | `BANK_DATES_OVERLAP` | The `employee_bank_no_overlap` GiST exclusion constraint rejected the insert (race-condition backstop) |
| `403` | `PERMISSION_DENIED` | Caller lacks `EMPLOYEE.UPDATE_SENSITIVE` (or `.VIEW_BANKING` for GET) |
| `422` | (FastAPI validation) | `extra="forbid"`, missing `payment_mode`, or an invalid `payment_mode` value — unknown/extra fields and invalid values rejected |

### Example — first bank account (joining)

```
POST /v1/employees/{employee_id}/bank
{
  "effective_from": "2027-06-01",
  "account_holder_name": "Meera Iyer",
  "account_number_enc": "1234567890",
  "bank_name": "State Bank",
  "ifsc": "SBIN0001234",
  "branch_name": "MG Road",
  "payment_mode": "BANK"
}
```
No `If-Match` header.

### Example — account changed (revision)

```
POST /v1/employees/{employee_id}/bank
If-Match: 1
{
  "effective_from": "2029-06-01",
  "account_holder_name": "Meera Iyer",
  "account_number_enc": "9876543210",
  "bank_name": "HDFC Bank",
  "ifsc": "HDFC0001234",
  "branch_name": "Indiranagar",
  "payment_mode": "BANK"
}
```

---

## Fields never accepted in the request body

`id`, `company_id`, `employee_id`, `version`, `effective_to`, `is_primary`,
`verification_status`, `penny_drop_reference` — all system-computed or system-managed. Attempting
to set any of these (or any other unknown field) is rejected with a `422` by `extra="forbid"`.

## What this API does not do

- No bulk/batch bank endpoint.
- No endpoint to close a bank row without opening a new one — no standalone "clear bank account"
  action.
- No `PATCH`/`DELETE` on an individual bank row — history is never edited in place.
- No verification-status transition endpoint — `verification_status` is always `PENDING` on every
  row this API creates.
- No `penny_drop_reference` write path.
- No field-level masking of `account_number_enc`/`ifsc`/etc. — whole-sub-resource gating only.
- No termination-triggered close or audit event — this row is never touched by
  `POST .../employments/{employment_id}/terminate` (module reference §6).
