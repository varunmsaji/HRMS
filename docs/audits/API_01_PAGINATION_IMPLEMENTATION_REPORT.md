# API-01 — Production-Safe Pagination Implementation Report

## 1. Executive result

```
API-01 IMPLEMENTATION PASS — READY FOR SECURITY REVIEW
```

Every Tier 1 endpoint is now paginated at the SQL level, authorization is applied before
`LIMIT`/`OFFSET` in every case (verified with tests, including a `BRANCH`-scope + pagination
combination test), the `/leave-applications` N+1 pattern is replaced with 2 bounded batch
queries per page, Tier 2 endpoints have a documented, non-silent decision, and the frontend
consumers of every changed endpoint have been updated to the new envelope. Two pre-existing,
unrelated test failures were found and flagged separately (§9, §10) — neither blocks this
result.

## 2. Endpoint inventory

| Endpoint | Decision | Pagination | Reason |
| --- | --- | --- | --- |
| `GET /employees` | Paginate | ✅ | Tenant-wide employee population, genuinely unbounded over a tenant's lifetime |
| `GET /leave-applications` | Paginate + fix N+1 | ✅ | Company-wide scope + no default date window + 2N query pattern |
| `GET /policy-assignments` | Paginate | ✅ | Append-only history table |
| `GET /leave-ledger` | Paginate | ✅ | Append-only ledger, grows for a tenant's lifetime |
| `GET /shifts/{id}/versions` | Paginate | ✅ | Version history, unbounded over time |
| `GET /work-calendars/{id}/exceptions` | Paginate | ✅ | Exception history, unbounded over time |
| `GET /holiday-calendars/{id}/holidays` | Paginate | ✅ | `year` filter optional/insufficient alone |
| `GET /branches` | Leave unpaginated + defensive `LIMIT 1000` | ❌ (real pagination) | Bounded config collection (physical locations); no UI page controls; consumed as complete dropdown/table lists elsewhere. Ceiling is a data-anomaly safety net, not a designed UX |
| `GET /departments` | Leave unpaginated + defensive `LIMIT 1000` | ❌ | Same reasoning as branches — bounded org config |
| `GET /designations` | Leave unpaginated + defensive `LIMIT 1000` | ❌ | Same reasoning |
| `GET /shifts` (list) | Leave unpaginated + defensive `LIMIT 1000` | ❌ | Shift *definitions* (templates), not roster instances — small, closed set |
| grades, holiday calendars, weekly-off patterns, leave types, leave policies, leave combination rules, statutory minimums, legal entities | Untouched | ❌ | Tier 3 — no repository evidence of unbounded growth; out of scope per audit |

## 3. Pagination contract

- **Query params**: `page` (1-indexed, `ge=1`, default `1`), `per_page` (`ge=1`, `le=100`, default `25`).
- **Invalid params**: `page<1` or `per_page` outside `[1,100]` → `422` via FastAPI's own validation, before the route body runs — never silently clamped.
- **Response envelope**: existing `ListEnvelope[T]` (`data: list[T]`, `pagination: PaginationMeta`, `meta`) — no new envelope type introduced.
- **`PaginationMeta`**: `page`, `per_page`, `total` (exact count under the same filters, pre-pagination), `total_pages = ceil(total / per_page)` (`0` when `total==0`), `next_cursor` left `null` (offset-based, not cursor-based).
- **Total-count behavior**: a separate `COUNT(*)` query, sharing the identical `WHERE` predicates as the data query (extracted into a shared `_conditions`/`_filtered_conditions` helper per repository, so the two can never drift).
- **Ordering**: each endpoint's existing business ordering is preserved, with a stable secondary key added (usually `.id`, or `created_at` where none existed) only where ties were possible — never changing the primary sort a client already depends on.
- **Filtering/sorting interaction**: all existing filters (`employee_id`, `date_from`/`date_to`, `application_status`, `policy_kind`, `scope_type`, `scope_id`, `leave_type_id`, `year`) apply identically before pagination; no client-supplied `sort` parameter exists anywhere in this API, so none was added.
- **Empty-page / beyond-final-page**: both return `200` with `data: []` and an accurate `pagination` block — never an error.
- **Server-side maximum**: `per_page` is hard-capped at `100` (`MAX_PAGE_SIZE`) — a client cannot request an arbitrarily large page under any circumstance.

Implemented once in `apps/api/src/hrms/shared/pagination.py`: `PageParams`, `pagination_params` (the shared FastAPI `Depends`), `build_pagination_meta`. Every Tier 1 router uses the exact same three symbols — no per-endpoint reinvention.

## 4. High-risk fixes

- **`/employees`**: `EmployeeRepository.list_employees`/`count_employees` gained `limit`/`offset` (repo) driven by `EmployeeService.list_employees`'s new `page: PageParams | None` parameter. `page=None` (every non-HTTP caller, e.g. `attendance/tasks.py`'s background job) preserves the exact pre-API-01 full-scan behavior — nothing else changed. `GET /employees` always passes `page`; `resolve_visible_employee_ids` (RBAC/DataScope) still runs first and the `LIMIT`/`OFFSET` only ever slides across the resulting visible-ID set.
- **`/leave-applications`**: `LeaveApplicationRepository.list_filtered`/`count_filtered` share one `_filtered_conditions` builder so pagination's `total` can never disagree with the actual filtered rows. `date_from`/`date_to`/`employee_id`/`application_status` semantics are byte-for-byte unchanged.
- **`/policy-assignments`**: `PolicyAssignmentRepository` gained `limit`/`offset`/`count_assignments`; `policy_kind`/`scope_type`/`scope_id` filters unchanged. No default date filter was invented (explicitly disallowed by the brief) — pagination alone protects this append-only table.
- **`/leave-ledger`**: `employee_id` remains required, `leave_type_id` remains optional; no year/date restriction was added (also explicitly disallowed) — pagination is the sole protection.
- **`/shifts/{id}/versions`**: pagination narrows the parent `ShiftVersion` query first; the already-batched `list_breaks_for_versions`/`list_duty_blocks_for_versions` calls (pre-existing, not touched) then run only against that page's version IDs — composes correctly, no new N+1 introduced.
- **`/work-calendars/{id}/exceptions`**: date ordering preserved, calendar isolation preserved (verified by a cross-calendar test).
- **`/holiday-calendars/{id}/holidays`**: `year` stays optional and is applied *before* pagination, not treated as sufficient protection on its own — an omitted `year` still cannot return an unbounded result.

## 5. N+1 result

**Before**: `LeaveApplicationService.list_applications` ran `_read()` once per row — 2 extra queries (`days`, `actions`) per application, i.e. `1 + 2N` queries for a page of `N` applications.

**After**: `_read_many()` collects the page's application IDs once, then issues exactly 2 batch queries (`LeaveApplicationDayRepository.list_for_applications` / `LeaveApplicationActionRepository.list_for_applications`, both `WHERE leave_application_id IN (...)`), groups the flat results by `leave_application_id` in Python, and reassembles each `LeaveApplicationRead`. Total query shape is now `1 (applications) + 1 (count) + 1 (days) + 1 (actions)` — **flat, independent of how many rows are on the page**.

Proven empirically, not just by code inspection: `test_n_plus_one_removed_query_count_bounded` (`tests/integration/modules/leave/test_leave_application_pagination.py`) creates 12 applications, wraps two HTTP calls (`per_page=3` and `per_page=12`) each in a `QueryCounter` (a SQLAlchemy `before_cursor_execute` listener on the shared engine), and asserts the two calls issue the **exact same number of SQL statements** — if the old per-row pattern still existed, the 12-row call would issue ~4x more statements than the 3-row call. `test_day_and_action_data_correct_under_pagination` proves the batched regrouping never cross-associates one application's `days`/`actions` with another's.

## 6. Security verification

- Every Tier 1 service method resolves `DataScope`/tenant filtering **before** constructing the paginated query — `page.limit`/`page.offset` are applied to a `WHERE` clause that already includes the visible-ID/tenant predicate, never after.
- `test_branch_scope_pagination_narrows_before_paging` (employees): a `BRANCH`-scoped actor with 8 visible colleagues out of 13 total company employees pages through `per_page=5` and the union of both pages equals exactly the 8 visible IDs — the 5 outsiders never appear on any page, at any `page`/`per_page` value.
- `test_tenant_isolation_pagination_total`: a second tenant's 9 employees never contribute to the first tenant's `pagination.total`.
- Cross-resource isolation verified for shift versions (`test_versions_cross_shift_isolation_under_pagination`) and calendar exceptions (`test_calendar_exceptions_cross_calendar_isolation`).
- `page`/`per_page`/`offset` are never accepted as anything but validated integers via the shared `pagination_params` dependency — no raw client input reaches SQL string-formatted, all via SQLAlchemy `.limit()`/`.offset()` bind parameters.
- No changes were made to CORS, JWT, rate limiting, or authentication — confirmed by `git diff` scope (§12).

## 7. Performance

- **SQL-level pagination**: every Tier 1 endpoint uses `.limit(page.limit).offset(page.offset)` in the repository — never fetches the full result set and slices in Python.
- **Indexes reviewed, none added**: `Employee.company_id`, `LeaveApplication.company_id`/`.employee_id`, `PolicyAssignment.company_id`, `LeaveLedgerEntry.company_id`/`.employee_id`, `ShiftVersion.company_id`/`.shift_id`, `CalendarException.company_id`/`.work_calendar_id`, `Holiday.company_id`/`.calendar_id` already carry single-column B-tree indexes (`index=True` at the model level) covering every filter predicate used by these queries. No composite `(company_id, created_at)`-style covering index was added — there is no query-latency evidence at current expected data volumes that the existing single-column indexes plus a sort are insufficient, and the brief explicitly disallows adding indexes speculatively. If a specific tenant's row counts or p95 latency later prove otherwise, the concrete follow-up is a composite index on `(company_id, <ordering column>, id)` for whichever table shows it — not a blanket addition now.
- **COUNT behavior**: a second query per request, same predicates as the data query, extracted into a shared conditions-builder per repository to guarantee they can't drift apart.
- **Remaining concern**: `COUNT(*)` is a second full predicate scan; for the largest, longest-lived tables (`leave_application`, `leave_ledger`, `policy_assignment`) this is the standard offset-pagination cost and is consistent with every other paginated endpoint in this contract — not a regression specific to any one endpoint.

## 8. Frontend compatibility

`lib/api/types.ts` gained `PaginationMeta`/`ListEnvelope<T>`; `lib/api/client.ts` gained `apiClient.getList<T>(path, query)`, returning the full envelope (`data` + `pagination`) instead of just unwrapping `.data`. A new `components/common/pagination-controls.tsx` (Previous/Next + "Showing X–Y of Z") is shared across every updated page.

Consumers updated:

- **Primary paginated views** (added page state + `PaginationControls`): `app/employees`, `app/leave-applications`, `app/policy-assignments`, `app/leave-balances` (ledger section), `app/shifts/[id]` (Versions/History tab — draft/current-published detection deliberately pinned to page 1, immune to History pagination), `app/work-calendars/[id]` (Exceptions tab), `app/holiday-calendars/[id]` (Holidays section, plus its "total holidays" summary field now reads `pagination.total`).
- **Reference-data dropdowns** consuming `/employees` for a picker, not a table (now request `per_page: 100`, the server max, with a documented known limitation for >100-employee tenants): `app/leave-applications` (team filter), `app/leave-balances` (team picker), `app/departments` + `app/departments/[id]` (department-head picker), `components/employee/assignment-panel.tsx` (manager picker), `app/attendance`, `app/overtime`, `app/regularizations`, `app/rosters`, `app/rosters/calendar`, `app/policy-resolution`, `components/attendance/punch-entry-dialog.tsx`, `components/regularization/regularization-request-dialog.tsx`, `components/leave-application/leave-application-dialog.tsx`, `components/shift-roster/roster-entry-dialog.tsx`.
- **Tier 2/3 dropdown consumers** (`/branches`, `/departments`, `/designations`, `/shifts`, `/grades`, `/leave-types`, …): unchanged — still unpaginated envelopes, no pagination UI added, matching the Tier 2 decision in §2.

## 9. Tests

| Suite | Result |
| --- | --- |
| Targeted API-01 backend tests (new files, see below) | **40 passed / 40** |
| Full backend `pytest` | **1402 passed, 1 failed** (pre-existing, unrelated — §10) / 1403 |
| Full frontend `vitest` | **364 passed, 4 failed** (pre-existing, unrelated — §10) / 368 |
| Backend `mypy --strict` (touched files) | Clean — 4 pre-existing, unrelated errors elsewhere unaffected |
| Frontend `tsc --noEmit` | Clean |
| Backend `ruff check` (touched files) | Clean |
| Migrations | None added — no schema changes; not required |
| OpenAPI schema generation | Clean; verified `page`/`per_page` present on every Tier 1 path and absent from Tier 2/3 paths |

New backend test files (40 tests): `tests/integration/modules/employee/test_employee_pagination.py` (12), `tests/integration/modules/leave/test_leave_application_pagination.py` (7), `tests/integration/modules/leave/test_leave_ledger_pagination.py` (3), `tests/integration/modules/organisation/test_shift_version_pagination.py` (3), `tests/integration/modules/organisation/test_workforce_calendar_pagination.py` (6, covering policy-assignments + calendar-exceptions + holidays), `tests/unit/shared/test_pagination.py` (9, the shared contract itself).

Coverage against the Phase 11 checklist: default/explicit page, max/invalid page size, empty dataset, beyond-final-page, exact boundaries, deterministic ordering with no duplicate/missing rows across pages, filter+pagination interaction, tenant isolation, RBAC/DataScope (`BRANCH` scope specifically combined with pagination), regression correctness of child records (`days`/`actions`), and the N+1 query-count proof.

## 10. Remaining risks / follow-ups

1. **Two pre-existing, unrelated test failures found during verification** (not caused by this work — confirmed via `git stash` against a clean checkout of `c3b8cec`), flagged as separate background tasks rather than fixed inline (scope lock):
   - `apps/web/src/app/app/branches/page.test.tsx` — 4 failing tests, unrelated to any endpoint touched here.
   - `test_registration_success_full_row_graph` — hardcoded expected permission-code set is missing 3 codes a recent RBAC commit added (`SETTINGS.ROLE.MANAGE`, `SETTINGS.USER.MANAGE`, `EMPLOYEE.INVITE`).
2. **Reference-data employee dropdowns cap at 100** (`per_page=100`, the server max) — tenants with more than 100 employees will see a truncated manager/department-head/team-filter picker. A proper fix is a searchable/paginated employee-picker component; out of scope for API-01 (backend pagination + basic frontend compatibility), tracked as a known limitation, not silently ignored.
3. **`COUNT(*)` cost at very large scale** is unaddressed by design (§7) — acceptable at current evidence, worth revisiting with real production row-count/latency data before it becomes a bottleneck.
4. **Tier 2 safety ceiling (`LIMIT 1000`)** on `branches`/`departments`/`designations`/`shifts` is a defensive net, not a designed pagination UX — if a tenant ever legitimately approaches it, that itself is the signal to revisit these as Tier 1.
5. **DATA-01 deployment/key-management decisions** are explicitly out of scope here and were not touched, per the scope lock.
