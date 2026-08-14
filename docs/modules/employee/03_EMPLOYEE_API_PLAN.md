# Employee API Plan

Companion to `00_EMPLOYEE_AUDIT.md §13`. This is a proposed endpoint surface for review, not an
implemented API — no router/schema code exists yet. Conventions (envelope shapes, headers, error
format, optimistic concurrency) follow `docs/product/09_API_Standards.md` and the organisation
module's shipped implementation exactly, per the audit brief's explicit instruction not to
blindly copy Grade/Designation's flat single-resource shape, since Employee is a materially
larger aggregate.

---

## 1. Why Employee's API shape differs from Grade/Designation/Branch

Every organisation-module entity is a single table with a flat `Create`/`Update`/`Read` schema
triplet and five routes (`GET` list, `POST`, `GET` detail, `PATCH`, `DELETE`-as-deactivate).
Employee is a nine-table aggregate (identity + employment + assignment + compensation +
statutory + bank + documents + dependents/education/experience/skills + timeline) where several
of the children are effective-dated collections, not single mutable rows. `docs/product/
09_API_Standards.md §3.2` already specifies this as sub-resource routes under `/employees/{id}/*`
rather than one flat resource — this plan follows that existing, authoritative catalogue rather
than inventing a new shape.

---

## 2. Proposed endpoints

All routes are company-scoped via `X-Company-Id` + JWT (never the path), require the permission
listed, use `DataEnvelope`/`ListEnvelope`/`ErrorEnvelope` per `docs/product/09_API_Standards.md`,
and never return `403` for a cross-tenant id — always `404`, matching every organisation-module
precedent.

### 2.1 Core identity + employment

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/employees` | `EMPLOYEE.VIEW` (own scope) / `EMPLOYEE.VIEW_ALL` (company-wide) | Search (name/code/email/phone), filter (department/branch/designation/status), paginated — **not** the organisation module's "unfiltered list" shortcut; Employee lists can reach thousands of rows (`docs/design/screens/01_Employee_List_Directory.md §7`: virtualization-first, cursor pagination) |
| POST | `/v1/employees` | `EMPLOYEE.CREATE` | Nested body: identity + `employment{}` + `assignment{}` + `compensation{}` + `statutory{}` + `custom_fields{}` (shape per `docs/product/09_API_Standards.md:285-309`). No ATS/candidate fields (`00_EMPLOYEE_AUDIT.md §6`). Enforces `EMPLOYEE_SEATS` plan limit (`00_EMPLOYEE_AUDIT.md §15.6`) before insert. Allocates `employee_code` via the (currently unbuilt, `00_EMPLOYEE_AUDIT.md §1.4`) number-series mechanism. |
| GET | `/v1/employees/{id}` | `EMPLOYEE.VIEW` (self/scope) / `.VIEW_ALL` | Summary view — identity + current employment + current assignment, field-masked per classification (`00_EMPLOYEE_AUDIT.md §11.3`) |
| GET | `/v1/employees/{id}/full` | same as above | 360° view — every tab's data in one call, mobile-optimised, per FR-EMP-017 |
| PATCH | `/v1/employees/{id}` | `EMPLOYEE.UPDATE` (basic fields) / `.UPDATE_SENSITIVE` (PAN/Aadhaar/UAN) | `If-Match: <version>`; partial update to `employee` identity columns only — assignment/compensation/statutory/bank changes go through their own sub-resource POST (§2.2-2.4), never through this PATCH, since those are inserts of new effective-dated rows, not column updates |
| DELETE | `/v1/employees/{id}` | `EMPLOYEE.DEACTIVATE` | Deactivate only, matching every organisation-module `DELETE`. **Employee deactivation is not the same as exit** — deactivation is an account-level lock (e.g. suspected fraud, immediate access cutoff); exit (`status → EXITED`) is the FR-EMP-014 lifecycle transition driven by the Exit module, out of this module's scope. This distinction should be confirmed with product before implementation (not asserted here as settled) |
| POST | `/v1/employees/{id}/confirm` | `EMPLOYEE.CONFIRM` | Probation confirmation workflow (FR-EMP-010) |

### 2.2 Assignment (effective-dated — insert-only, never `PATCH`)

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/employees/{id}/assignments` | `EMPLOYEE.VIEW` | Full effective-dated history, or `?as_of=2029-03-15` for a single as-of-date row (§00 §4/§7.3 query pattern) |
| POST | `/v1/employees/{id}/assignments` | `EMPLOYEE.TRANSFER` / `.PROMOTE` (per `change_type`) | Closes the current row's `effective_to`, inserts a new row. Body: `effective_from`, changed fields only (unchanged fields carry forward from the current row), `change_type`, `change_reason`. Backdating subject to the FR-EMP-004 payroll-lock check (`02_EMPLOYEE_DATA_MODEL.md §1.4` — not enforceable until Payroll exists) |

No `PATCH`/`DELETE` on an individual assignment row — per ADR-0003, history is never edited in
place. A data-entry mistake is corrected by inserting a further correcting row, not by mutating
a past one (mirrors Payroll's own immutability posture, ADR-0005).

### 2.3 Compensation (effective-dated, `EMPLOYEE.VIEW_COMPENSATION`/`.UPDATE_COMPENSATION` gated)

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/employees/{id}/compensation` | `EMPLOYEE.VIEW_COMPENSATION` | History or `?as_of=` — same pattern as assignments. **Absent entirely from the response for a caller without this permission** (not a masked field — the whole sub-resource is gated, matching the Directory screen spec's "absent, not disabled" rule) |
| POST | `/v1/employees/{id}/compensation` | `EMPLOYEE.UPDATE_COMPENSATION` | Salary revision — `revision_type`, `revision_reason` required; may require `approval_request_id` depending on the (not-yet-built) approval-routing engine |

### 2.4 Statutory / Bank (effective-dated, RESTRICTED)

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET / PATCH | `/v1/employees/{id}/statutory` | `EMPLOYEE.UPDATE_SENSITIVE` (view permission unresolved, `02_EMPLOYEE_DATA_MODEL.md §2` section F gap) | Insert-only per ADR-0003 despite "PATCH" being the doc-listed verb (`docs/product/09_API_Standards.md:269` literally shows `PATCH` here) — flagged as a doc/architecture tension: a `PATCH` verb implies in-place mutation, but ADR-0003 requires insert-only for effective-dated data. **Recommendation: implement as insert-only (POST semantics) even though the API standards doc names the verb PATCH**, and flag the doc for correction, since ADR-0003 is the more specific and more recently reasoned source for this exact class of data |
| GET / POST | `/v1/employees/{id}/bank-accounts` | `EMPLOYEE.UPDATE_SENSITIVE` | Insert-only, same as above. `account_number_enc` masked in every read response (`******7890`) |

### 2.5 Documents / Dependents / Education / Experience / Skills (not effective-dated — plain collections)

| Method | Path | Permission |
|---|---|---|
| GET / POST | `/v1/employees/{id}/documents` | `EMPLOYEE.VIEW_DOCUMENTS` / `.UPLOAD_DOCUMENTS` |
| PATCH | `/v1/employees/{id}/documents/{docId}/verify` | `EMPLOYEE.VERIFY_DOCUMENTS` |
| GET / POST | `/v1/employees/{id}/dependents` \| `/education` \| `/experience` \| `/skills` | `EMPLOYEE.VIEW` / `.UPDATE` |

### 2.6 Timeline, team, reporting tree

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/employees/{id}/timeline` | `EMPLOYEE.VIEW` | Unified `employee_event` feed |
| GET | `/v1/employees/{id}/team` | `EMPLOYEE.VIEW` (scope-checked) | Direct reports — `employee_assignment WHERE reporting_manager_id = :id AND effective_to IS NULL` |
| GET | `/v1/employees/{id}/reporting-tree` | `EMPLOYEE.VIEW_ALL` or scope-matched | Full subtree, recursive CTE per `docs/product/19 §5`, depth-capped at 20 |

### 2.7 Bulk operations

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/v1/employees/import` | `EMPLOYEE.IMPORT` | Multipart → `202 + job_id`. Dry-run validation, all-or-nothing commit, 5,000-row cap (FR-EMP-006) |
| GET | `/v1/employees/import/{batchId}` | `EMPLOYEE.IMPORT` | Row-level validation/result report |
| GET | `/v1/employees/export` | `EMPLOYEE.EXPORT` | `202 + job_id`, operates on the full filtered/scoped result set server-side (`docs/design/screens/01_Employee_List_Directory.md §7`) |

### 2.8 Letters, directory, profile-change-requests

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/v1/employees/{id}/letters` | `EMPLOYEE.GENERATE_LETTER` | 11 non-offer templates (offer letter excluded — moves with ATS/V2, `00_EMPLOYEE_AUDIT.md §6`) |
| GET | `/v1/employees/directory` | any `EMPLOYEE.VIEW*` | Lightweight, cached, for ESS — a reduced-field projection distinct from `GET /employees` |
| POST | `/v1/profile-change-requests` | employee self-service | Employee-initiated edit to a controlled field, routes to HR approval per FR-EMP-009 |

---

## 3. Request/response conventions carried over unchanged from the organisation module

- `DataEnvelope<T>` / `ListEnvelope<T>` / `ErrorEnvelope` — identical shape.
- `version` + `If-Match` optimistic concurrency on every mutating call to a non-effective-dated
  resource (`employee`, `employment`). Effective-dated sub-resources (assignment, compensation,
  statutory, bank) do **not** need `If-Match` on their `POST` (there is nothing to race against —
  every write is a new row), but the "close the current row" half of that write (§1.2 of
  `02_EMPLOYEE_DATA_MODEL.md`) should itself be guarded by the current row's `version` internally,
  to avoid a lost-update race between two concurrent transfer requests.
- `extra="forbid"` on every input schema; explicit `*Create`/`*Update` schemas, never binding the
  request body directly to an ORM model.
- Cross-tenant or not-found → `404`, never `403`.
- RESTRICTED fields (`§00 §11.3`) are **omitted** from JSON when the caller's permission set
  doesn't include them — never sent as `null`.
- Rate limiting: none of the organisation module's endpoints beyond `POST /companies/register` are
  rate-limited; `POST /v1/employees/import` is a plausible candidate for rate limiting given its
  cost (5,000-row dry-run validation), but no document specifies a limit — flagged as a decision,
  not invented here.

---

## 4. Explicitly not designed here

Approval-routing integration (compensation revision / transfer approval chains — depends on the
not-yet-built workflow-routing core, `docs/product/VERSION_1_ROADMAP.md §8` item 4, sequenced
after Employee per the roadmap's own backend order), the exact `EmployeeCreate` Pydantic
sub-model field lists (belongs in `02_EMPLOYEE_DATA_MODEL.md`'s inventory, not repeated here), and
OpenAPI contract-snapshot wiring (`docs/product/VERSION_1_ROADMAP.md §11` recommends this exist
*before* Employee's endpoints ship — a process decision, not an endpoint-design one).
