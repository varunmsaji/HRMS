# Grade Module

Status: **Implemented** (vertical slice scoped per this task's own Phase 4–9 instructions —
narrower than the full Sprint 3 plan's Task 3.3.1, most notably excluding
`leave_policy_id`/leave-entitlement override; see §9). This document covers purpose, data
model, the Designation relationship, API, permissions, business rules, lifecycle, audit,
tenant isolation, frontend behavior, known limitations, and unresolved decisions — mirroring
the shape of `docs/modules/designation/01_Designation_Module.md`. The full endpoint reference
lives in the sibling `02_Grade_API.md`.

## 1. Purpose

A **Grade** (band) is a compensation/seniority tier that a Designation can reference. It is
independent master data — not nested under any other org unit:

```
Company (tenant)
    ├── ... Branch → Department → Designation ──┐
    │                                            ├── grade_id (optional)
    └── Grade                                  ──┘
```

**Not built in this slice** (per task scope): `leave_policy_id`/leave-entitlement override
(see §9), any employee-dependency deactivation-blocking check, per-Grade currency, Employee,
Employee Assignment, Attendance, Shift Rules, Leave, Payroll.

## 2. Domain model

**Aggregate boundary**: `Grade` is its own aggregate, referencing only `company_id`. It has no
FK to Department, Branch, or Legal Entity — a Grade applies company-wide, and Designations
opt into referencing it.

**Entity — `Grade`**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `company_id` | UUID | FK → `company.id`, indexed |
| `code` | string (30) | Required; **unique per company** (`grade_company_id_code_key`, a real DB constraint that predates this slice) |
| `name` | string (100) | Required |
| `level` | integer, nullable | Renamed from the DB stub's `rank` this slice (clean rename, no data loss — `rank` had no real data) |
| `min_ctc` | BIGINT minor units, nullable | ADR-0006 — never a float; no per-row currency (Company owns one) |
| `max_ctc` | BIGINT minor units, nullable | Must be `>= min_ctc` when both present (§4.4) |
| `notice_period_days` | integer, nullable | Override-chain field (PRD BR-14) |
| `probation_days` | integer, nullable | Override-chain field (PRD BR-14) |
| `approval_limit` | BIGINT minor units, nullable | |
| `is_active` | boolean | Default `true` |
| `version` | integer | Optimistic concurrency (`If-Match`) |
| `created_at` / `updated_at` / `deleted_at` | timestamptz | `deleted_at` reserved, unused (deactivation ≠ deletion) |

Field list sourced from `docs/product/08_Database_Architecture.md` §4 and FR-ORG-007 —
`leave_policy_id` deliberately excluded, §9.

## 3. Relationship with Designation

Per `docs/modules/grade/00_GRADE_AUDIT.md` §3, the documentation is unambiguous:
**Designation references Grade**, via `designation.grade_id` (nullable FK, `ON DELETE SET
NULL`). This was documented in FR-ORG-006 (grade/band as one of Designation's own fields),
Database Architecture's `designation` column list, and the Sprint 3 plan's own Scope Decision
D2 — but could not be built in the prior Designation slice because Grade did not exist yet.
This slice completes that relationship:

- `DesignationCreate`/`DesignationUpdate` gain an optional `grade_id` field, validated for
  same-tenant ownership (`422 INVALID_GRADE`), same posture as `department_id`'s
  `INVALID_DEPARTMENT` check.
- No hierarchy/cycle logic applies — `grade_id` references a different entity type
  (Designation → Grade, one direction only), not a self-reference.
- Setting `grade_id` on a Designation requires only `ORG.DESIGNATION.MANAGE`, not
  `ORG.GRADE.MANAGE` — same posture as `department_id` requiring only
  `ORG.DESIGNATION.MANAGE`, not `ORG.DEPARTMENT.MANAGE`.
- `employee_assignment.grade_id` and `employee_assignment.designation_id` remain separate,
  independent bare columns at the DB level — that is a distinct relationship (an employee's
  *current* grade/designation assignment, time-versioned per ADR-0003), not a substitute for
  or a contradiction of `designation.grade_id`, which is a structural master-data
  relationship (a Designation's *own* grade).

## 4. Business rules

1. **Company ownership** — identical mechanism to every other organisation-module resource.
2. **Code uniqueness — already enforced, not invented.** `grade_company_id_code_key UNIQUE
   (company_id, code)` predates this slice. The service layer catches the resulting
   `IntegrityError` on create/update and raises `409 GRADE_CODE_ALREADY_EXISTS`, mirroring
   how `register_company` converts a duplicate-email `IntegrityError` into `ConflictError`.
3. **No documented deactivation-blocking rule.** FR-ORG-014's literal text blocks
   deactivation of an org unit "only if no active employee is assigned" — Employee doesn't
   exist, so this can't be checked. No document names an active Designation referencing a
   Grade as a blocker either. **This slice ships Grade deactivation/reactivation with no
   active-dependency check** — a Grade referenced by an active Designation can still be
   deactivated.
4. **`min_ctc <= max_ctc` — documented, implemented.** Sprint 3 Task 3.3.1's own Testing
   Requirements name this explicitly: "Unit: `min_ctc <= max_ctc` validated at the service
   layer when both present." Enforced as `422 INVALID_CTC_RANGE`. Not required when either
   value is absent. Re-validated on update against the *effective* range (existing value +
   patch), not just the fields present in a given PATCH request.
5. **Optimistic concurrency** — `version` + `If-Match`, identical mechanism to every other
   organisation-module resource.
6. **Soft deactivation only** — `DELETE` never hard-deletes; flips `is_active` to `false` via
   the same code path as `PATCH {is_active: false}`.
7. **No invented rules** — no hierarchy/ordering enforcement beyond the plain `level`
   integer (no min/max level range, no gap rules), no salary-calculation rules, no
   employee-dependency deactivation blocking, no payroll behavior.

## 5. API

Per this task's own instructions, matching `docs/product/09_API_Standards.md:246` exactly:

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/grades` | `ORG.GRADE.MANAGE` | List, company-scoped, unfiltered |
| POST | `/v1/grades` | `ORG.GRADE.MANAGE` | Create; `is_active` always `true` |
| GET | `/v1/grades/{grade_id}` | `ORG.GRADE.MANAGE` | 404 (never 403) cross-tenant or not-found |
| PATCH | `/v1/grades/{grade_id}` | `ORG.GRADE.MANAGE` | `If-Match: <version>`; partial update |
| DELETE | `/v1/grades/{grade_id}` | `ORG.GRADE.MANAGE` | Soft deactivation only; `If-Match`; `200 DataEnvelope<GradeRead>`, not `204` |

Full field/error reference in `02_Grade_API.md`.

## 6. Permissions

Single permission, matching the Company/Legal Entity/Branch/Department/Designation
precedent:

```
ORG.GRADE.MANAGE
```

Confirmed against `docs/product/19_RBAC_and_Permission_Matrix.md:100` with no naming
conflict. Granted to `COMPANY_ADMIN` at company registration time, the same
`get_or_create_permission` → `insert_role_permission` pattern used for every prior
organisation-module permission.

## 7. Audit

Uses the existing `AuditService`. Four events, mirroring Designation's:

- `GRADE_CREATED`
- `GRADE_UPDATED`
- `GRADE_DEACTIVATED`
- `GRADE_REACTIVATED`

Each with `before_json`/`after_json` snapshots of the `GradeRead` DTO (`entity_type =
"grade"`). No `RESTRICTED`-classified fields — `min_ctc`/`max_ctc` are compensation *bands*
(a grade-level policy value), not an individual employee's actual compensation. Designation's
own `DESIGNATION_UPDATED` audit action automatically captures `grade_id` changes in its
existing before/after snapshots — no separate audit event type was added for that.

## 8. Tenant isolation

Identical mechanism to every other organisation-module resource: `TenancyMiddleware` +
`get_tenant_context`, belt-and-suspenders `company_id` filtering in every repository method,
RLS re-asserted idempotently in the migration. Cross-tenant access — including a guessed
`grade_id` or a cross-tenant `grade_id` referenced from Designation — returns `404`/`422` as
appropriate, never leaks. Covered by
`test_cross_tenant_grade_get_blocked`/`test_cross_tenant_grade_list_never_leaks` in
`test_cross_tenant_isolation.py`, and the cross-tenant grade-reference rejection test in
`test_grade.py`.

## 9. Frontend behavior

- **Routes**: `apps/web/src/app/app/grades/page.tsx` (list + create-dialog) and
  `apps/web/src/app/app/grades/[id]/page.tsx` (detail + inline edit) — the same two-route
  shape Department/Designation established.
- **Nav**: "Grades" added to `NAV_ITEMS`, between Designations and Setup.
- **Money fields**: `min_ctc`/`max_ctc`/`approval_limit` are integer minor units on the wire
  (ADR-0006). The form works in whole rupees and converts at the boundary
  (`lib/grade/validate-grade.ts`'s `rupeesToMinorUnits`/`minorUnitsToRupees`) — no
  `MoneyDisplay` primitive exists yet anywhere in the frontend (only named as a future
  primitive in the Sprint 3 plan), so this slice adds a small local conversion helper rather
  than inventing a new shared component.
- **Designation form integration**: `components/designation/designation-form.tsx` gained a
  "Grade" `<NativeSelect>` picker alongside the existing "Department" picker, sourced from
  `GET /grades`. The Designation list/detail pages now also show the linked grade's name.
- **Lifecycle UI**: deactivate/reactivate confirmation dialog, stale-version handling — same
  as Designation. No "blocked deactivation" toast exists for Grade (§4.3 — no rule to block
  on).
- **Reused components**: `PageHeader`, `FormField`, `LoadingState`, `ErrorState`,
  `EmptyState`, `toast`, `Card`, `Button`, `Badge`, `Dialog`, `NativeSelect`, `Input` — zero
  new primitives beyond the local money-conversion helpers.

## 10. Known limitations

- **No `leave_policy_id`** — the Sprint doc's own later self-correction (Feature 4.3's text)
  retracts this column in favor of `leave_policy_assignment`, itself out of scope (Leave
  excluded this task). FR-ORG-007's "leave entitlement override" and PRD BR-14's
  leave-entitlement link in the override chain are not implemented.
- **No deactivation-blocking rule** (§4.3) — a Grade referenced by an active Designation (or,
  once it exists, an active Employee) can still be deactivated freely this slice.
- **No per-Grade `currency` column** — money fields are assumed to be in the owning
  Company's single configured currency.
- **No query-param filtering** on `GET /grades` — consistent with every prior
  organisation-module list endpoint.
- **No `MoneyDisplay` shared component** — money formatting is handled locally in
  `lib/grade/validate-grade.ts` and the detail page's own `formatRupees` helper; a future
  slice may extract this into a shared primitive once more money-bearing modules exist.

## 11. Unresolved product decisions

- Whether/when `leave_policy_assignment` (the retracted `grade.leave_policy_id`'s
  replacement mechanism) will be built, and how Grade will participate in it.
- Whether Grade deactivation should eventually be blocked by active Employee assignments
  (FR-ORG-014) once Employee ships, and/or by active Designations referencing it — no
  document currently specifies either.
- Whether a per-Grade currency override will ever be needed (e.g., for multi-currency
  companies) — no product document currently anticipates this.
