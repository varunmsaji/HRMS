# Shift Rules — Implementation Report

Closeout report for the Shift Rules vertical slice (Sprint 3 Feature 4.2, Task 4.2.1,
Decision D5). Scope: shift *master* data only — no assignment, roster, rotation pattern, or
Attendance-side consumption. Employee, Employee Assignment, and Attendance were not touched.

## 1. Audit findings

Full detail in `00_SHIFT_RULES_AUDIT.md`. Summary of the load-bearing findings:

- Shift had zero application code and zero database presence before this slice — a genuinely
  new table, not a column-expansion migration (unlike Legal Entity/Branch/Department/
  Designation/Grade, which all began from a Prisma-era DB stub).
- Two documents describe the `shift` table at different scopes: the long-term full-featured
  target (`08_Database_Architecture.md` §6.1 — shift type, flexible/split-shift fields,
  companion roster/rotation tables) vs. the Sprint 3 build-time scope (Decision D5, Task
  4.2.1 — master-only). This slice builds the narrower, build-time scope.
- `week_off_pattern_id` is a documented dependency (Task 4.2.1's own "Dependencies: 3.1.1")
  pointing at a table (`week_off_pattern`) that was never built by any prior slice (Branch
  deferred it to its own Task 3.1.3, never picked up since).
- Two inconsistent permission codes exist in product docs (`ATTENDANCE.SHIFT_MANAGE` vs.
  `ORG.SHIFT.MANAGE`); resolved in favor of the Sprint-doc code, matching this series'
  existing Legal Entity precedent.
- No document specifies a uniqueness constraint on `shift.code` or `shift.name`, and (unlike
  Grade) there was no pre-existing DB-level constraint to preserve.

## 2. Requirements decisions

All six audit decisions (§10) were carried through into the implementation unchanged:

1. Column scope = Sprint 3 Task 4.2.1's master-only set, not the full `08_Database_
   Architecture.md` §6.1 shape.
2. `week_off_pattern_id` excluded entirely (not added as an inert column).
3. Permission code = `ORG.SHIFT.MANAGE`.
4. `code` is optional, no uniqueness constraint.
5. No default "General Shift" seed at registration (Task 4.2.2) — no existing
   registration-time seeding precedent to reuse.
6. Cross-midnight time-ordering and half-day/min-hours-range validation implemented as
   service-layer checks, structured identically to Grade's `min_ctc <= max_ctc` rule.

## 3. Files created

- `apps/api/alembic/versions/20260813170000_shift_rules.py` — migration (`CREATE TABLE
  shift`, indexes, RLS policy)
- `apps/api/tests/integration/modules/organisation/test_shift.py` — 17 integration tests
- `apps/api/tests/unit/modules/organisation/test_shift_service.py` — 14 unit tests
- `apps/web/src/app/app/shifts/page.tsx` + `page.test.tsx` — list/create page
- `apps/web/src/app/app/shifts/[id]/page.tsx` + `page.test.tsx` — detail/edit page
- `apps/web/src/components/shift/shift-form.tsx` — shared create/edit form
- `apps/web/src/lib/shift/types.ts` — `Shift`/`ShiftWritableFields` TS types
- `apps/web/src/lib/shift/validate-shift.ts` + `validate-shift.test.ts` — client validation,
  payload builders, form-value mapping
- `docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md` (pre-existing, source of truth for this
  report)
- `docs/modules/shift-rules/01_Shift_Rules_Module.md` (this task, Phase 1)
- `docs/modules/shift-rules/02_Shift_Rules_API.md` (this task, Phase 1)
- `docs/modules/shift-rules/03_Shift_Rules_Implementation_Report.md` (this file)

## 4. Files modified

All within `apps/api/src/hrms/modules/organisation/` (the module that owns Shift) plus one
frontend nav file and one pre-existing integration test:

- `exceptions.py` — added `InvalidShiftTimeRangeError` (422), `InvalidShiftHoursRangeError`
  (422)
- `models.py` — added `Shift` ORM class
- `permissions.py` — added `ORG_SHIFT_MANAGE`, appended to `ORGANISATION_PERMISSIONS`
- `repository.py` — added `insert_shift`, `list_shifts`, `get_shift`, `update_shift`
- `router.py` — added `GET/POST /shifts`, `GET/PATCH/DELETE /shifts/{shift_id}`
- `schemas.py` — added `ShiftCreate`, `ShiftUpdate`, `ShiftRead`, `shift_to_read`,
  `shift_to_audit_dict`, `build_shift_update_values`
- `service.py` — added `create_shift`, `list_shifts`, `get_shift`, `update_shift`,
  `deactivate_shift`, two private validation methods, permission-grant wiring in
  `register_company`
- `apps/api/tests/integration/modules/organisation/test_registration_flow.py` — asserts
  `ORG_SHIFT_MANAGE` is among the permissions granted to `COMPANY_ADMIN` at registration
- `apps/web/src/components/layout/nav-items.ts` — added "Shifts" nav entry

No other module's files were modified.

## 5. Database changes

One new table, created by `apps/api/alembic/versions/20260813170000_shift_rules.py`:

```sql
CREATE TABLE shift (
  id, company_id (FK company.id), name, code, start_time, end_time,
  break_minutes_paid, break_minutes_unpaid, grace_in_minutes, grace_out_minutes,
  half_day_threshold_hours, min_hours_full_day, is_night_shift, is_cross_midnight,
  is_ot_eligible, is_active, deleted_at, version, created_at, updated_at
);
```

Plus `shift_company_id_idx`, `shift_company_active_idx`, and RLS enabled/forced with a
`tenant_isolation` policy. No changes to any other table. No `week_off_pattern_id` column (by
design — see §1).

## 6. API endpoints

| Method | Path | Permission |
|---|---|---|
| GET | `/v1/shifts` | `ORG.SHIFT.MANAGE` |
| POST | `/v1/shifts` | `ORG.SHIFT.MANAGE` |
| GET | `/v1/shifts/{shift_id}` | `ORG.SHIFT.MANAGE` |
| PATCH | `/v1/shifts/{shift_id}` | `ORG.SHIFT.MANAGE` |
| DELETE | `/v1/shifts/{shift_id}` | `ORG.SHIFT.MANAGE` |

Full request/response reference: `02_Shift_Rules_API.md`.

## 7. Permissions

Single permission code, `ORG.SHIFT.MANAGE`, added to `ORGANISATION_PERMISSIONS` and granted
to the `COMPANY_ADMIN` system role at company registration time (same
`get_or_create_permission` → `insert_role_permission` pattern as every prior organisation
permission). Confirmed by `test_registration_success_full_row_graph` in
`test_registration_flow.py`.

## 8. Business rules

1. Company ownership (identical mechanism to every organisation resource).
2. Cross-midnight time-ordering: `end_time <= start_time` rejected unless
   `is_cross_midnight=true`; re-validated on update against the effective row.
3. Half-day/full-day hour ordering: `half_day_threshold_hours >= min_hours_full_day` rejected
   when both present; re-validated on update against the effective row.
4. No deactivation-blocking rule (Employee doesn't exist to check against).
5. Optimistic concurrency via `version` + `If-Match`.
6. Soft deactivation only — `DELETE` never hard-deletes.
7. No shift_type, flexible/split-shift, OT computation, weekly-off resolution, or any other
   rule beyond the above — none is documented as buildable this slice.

## 9. Audit behavior

Four `AuditService` actions, `entity_type = "shift"`: `SHIFT_CREATED`, `SHIFT_UPDATED`,
`SHIFT_DEACTIVATED`, `SHIFT_REACTIVATED`. Before/after snapshots are the `ShiftRead` DTO. IP
address and user agent captured from the request. Verified by
`test_create_shift_records_audit`, `test_deactivate_shift_success`,
`test_reactivate_shift_via_patch` (integration) and
`test_create_shift_records_audit`/`test_reactivate_shift_records_distinct_audit_action`
(unit).

## 10. Tenant/RLS behavior

`TenancyMiddleware` + `get_tenant_context` resolve `company_id` before any handler runs;
every repository method filters by `company_id` explicitly; RLS enabled/forced at the DB
level with a `tenant_isolation` policy, asserted directly in the new-table migration.
Cross-tenant access returns `404`, never `403`, never leaks existence — confirmed by
`test_get_shift_not_found` and `test_create_shift_same_code_different_tenant_allowed`.

**Gap identified during this closeout**: unlike every sibling resource (Legal Entity, Branch,
Department, Designation, Grade), Shift has no dedicated pair of tests in the shared
`test_cross_tenant_isolation.py` (`test_cross_tenant_shift_get_blocked` /
`test_cross_tenant_shift_list_never_leaks`) or `test_permission_matrix.py`
(`test_shift_company_admin_allowed` / `test_shift_zero_permission_denied`). `test_shift.py`'s
own module docstring states this coverage "lives in the sibling
`test_cross_tenant_isolation.py` / `test_permission_matrix.py` files" — that statement does
not currently hold; neither file references Shift. The underlying tenant-isolation and
permission-check *mechanism* is identical to every other resource (same middleware, same
repository pattern, same `require_permission` dependency) and is exercised indirectly by
`test_shift.py`'s own tests (e.g. `test_create_shift_same_code_different_tenant_allowed` uses
two tenants), but the explicit blocked-cross-tenant-GET and permission-denied test pairs that
exist for every other resource do not exist for Shift. Flagged here rather than silently
left; not fixed as part of this closeout since it is a test-file addition, not a behavior
change, and out of this task's stated scope (documentation, review, and validation — not new
test authorship).

## 11. Frontend changes

- **Routes**: `apps/web/src/app/app/shifts/page.tsx` (list + create-dialog) and
  `apps/web/src/app/app/shifts/[id]/page.tsx` (detail + inline edit) — same two-route shape
  every prior organisation resource used.
- **Nav**: "Shifts" added to `NAV_ITEMS` between Grades and Setup, using the `Clock` icon.
- **Form**: `components/shift/shift-form.tsx`, a single shared component used by both the
  create dialog and the detail-page edit mode.
- **Client validation**: `lib/shift/validate-shift.ts` mirrors both service-layer rules
  (time-range, hours-range) so invalid input is caught before a round-trip, with server-side
  `422` codes (`INVALID_SHIFT_TIME_RANGE`/`INVALID_SHIFT_HOURS_RANGE`) mapped back onto the
  relevant form field if a race lets an invalid value reach the server anyway.
- **Lifecycle UI**: deactivate/reactivate confirmation dialog, stale-version (`409`) handling
  with "reload latest" / "cancel current changes" — same pattern as Grade/Designation.
- **Reused components**: `PageHeader`, `FormField`, `LoadingState`, `ErrorState`,
  `EmptyState`, `toast`, `Card`, `Button`, `Badge`, `Dialog` — zero new shared primitives.

## 12. Tests added

- **Backend integration** (`test_shift.py`, 17 tests): empty list, create success, create
  cross-midnight success, create rejected (time range, hours range), same `code` across two
  tenants allowed, missing required fields rejected, mass-assignment rejected (create and
  update), get-not-found, update success, update rejected (time range), update stale-version
  conflict, deactivate success + audit, reactivate via PATCH + audit, multiple shifts listed.
- **Backend unit** (`test_shift_service.py`, 14 tests): audit recording, time-range
  accept/reject including the cross-midnight and equal-start/end edge cases, hours-range
  accept/reject, get/update not-found, effective-value re-validation on update, deactivation
  not blocked by anything, reactivation's distinct audit action, stale-version conflict,
  no-op update (empty patch), deactivate-as-wrapper-around-update semantics.
- **Frontend** (`page.test.tsx` ×2, `validate-shift.test.ts`, 35 test cases across the three
  files): list/create/detail/edit page behavior, client-side validation rules, payload
  builders.
- **Gap**: see §10 — no dedicated cross-tenant-isolation or permission-matrix test pair for
  Shift in the shared test files, unlike every sibling resource.

## 13. Validation results

Re-run in full during this closeout session (not carried over from a prior session):

**Backend**
- `pytest`: **317 passed**
- `ruff check`: **all checks passed**
- `ruff format --check`: **129 files already formatted**
- `mypy src`: **no issues found in 64 source files**
- `lint-imports`: **1 contract kept, 0 broken**

**Frontend**
- `vitest run`: **227 passed** (30 test files)
- `tsc --noEmit`: **clean, no output**
- `next build`: **compiled successfully**, all 16 routes generated (`/app/shifts` and
  `/app/shifts/[id]` included), no type/lint errors

## 14. Documentation changes

- `docs/modules/shift-rules/01_Shift_Rules_Module.md` — new (this task)
- `docs/modules/shift-rules/02_Shift_Rules_API.md` — new (this task)
- `docs/modules/shift-rules/03_Shift_Rules_Implementation_Report.md` — new (this file)
- `docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md` — pre-existing, unmodified, used as
  source of truth throughout

## 15. Known limitations

Carried forward from the audit (§9) and confirmed still accurate against the shipped code:
no `week_off_pattern_id`; no `shift_type`/flexible/split-shift support; no BR-14/FR-EMP-018
override-chain mechanism; no Attendance-side consumption (grace-period math, late-marking,
cross-midnight day attribution, OT computation, weekly-off/holiday resolution); no default
shift seed at registration; no query-param filtering on `GET /shifts`; no uniqueness
constraint on `code`/`name`; no deactivation-blocking rule. Full detail in
`01_Shift_Rules_Module.md` §13.

**Additional limitation identified during this closeout** (not in the original audit): no
dedicated cross-tenant-isolation / permission-matrix test pair for Shift in the shared test
files, unlike every sibling organisation resource (§10, §12).

**Repository hygiene, unrelated to Shift's own correctness**:
- `apps/web/.next` (Next.js build output) is tracked in git and not listed in `.gitignore`.
  Running `next build` as part of this closeout's Phase 3 validation regenerated ~120 tracked
  files under `.next`, which now show as modified/deleted in `git status`. This is a
  pre-existing repository condition (the directory was already tracked before this task
  began), not something introduced by the Shift Rules implementation, but it is visible in
  the current working tree and worth flagging: recommend adding `.next/` to `.gitignore` and
  untracking it (`git rm -r --cached apps/web/.next`) in a separate, unrelated change. Not
  done as part of this closeout.
- `.claude/launch.json` — see §16.

## 16. Unresolved decisions

- Whether/when `week_off_pattern` will be built, and how `shift.week_off_pattern_id` should
  be added once it exists.
- Whether the BR-14/FR-EMP-018 shift-override chain will ever be built, and on which table(s).
- Whether Shift deactivation should eventually be blocked by active Employee-Assignment
  references, once Employee Assignment exists.
- Whether the missing cross-tenant-isolation/permission-matrix test pair (§10/§12) should be
  added to align Shift with every sibling resource's test coverage pattern — flagged, not
  actioned, in this closeout.
- **`.claude/launch.json`**: untracked, defines local dev-server launch configuration for
  `api` (`uv run uvicorn ... --port 8000`) and `web` (`npm run dev`, port 3000). Contains no
  secrets, no machine-specific absolute paths, and no environment-specific values — it is
  generic, reusable project tooling that any contributor cloning the repo could use unchanged.
  **Recommendation: commit it** (it is not personal machine-specific configuration), but this
  is a judgment call left to the user per this task's explicit instruction not to
  auto-resolve it.

## 17. Manual UI verification status

**Manual UI verification: pending user verification.** The manual browser walkthrough was not
completed in this session — a previous walkthrough was stopped by the user before completion.
No manual UI verification results are reported or implied by this document. `next build` and
`vitest run` confirm the frontend compiles, type-checks, and passes its automated component
tests, but that is not a substitute for an actual browser walkthrough of the create/edit/
deactivate/reactivate flows.

## 18. Database/test-data verification

Queried the persistent development database directly (via the application's own session
factory, not a separate test database) after the full backend test run completed:

- `shift` table: **0 rows**
- `company` table: **2 rows** — both pre-existing seed/demo companies (`Demo Company A`,
  `Demo Company B`, fixed UUIDs `11111111-…`/`22222222-…`, `created_at` predates this
  session), not test-created
- `user` table: **2 rows** (`admin@example.com`, `viewer@example.com`) — seed/demo users, not
  test-created
- `user_company`: 3 rows, `audit_log`: 1 row, `permission`: 31 rows, `role`: 12 rows — all
  consistent with the two seed companies' own setup, no anomalous volume

**Conclusion**: no orphaned test companies, users, or shift rows were left behind by this
session's `pytest` run. `test_shift.py`'s and `test_cross_tenant_isolation.py`'s own
try/finally cleanup helpers (`_cleanup`, `_cleanup_shifts`) ran successfully for every test.
No data was deleted as part of this verification — it was inspect-only, per this task's
instructions.

## 19. Employee / Employee Assignment / Attendance confirmation

**Explicitly confirmed NOT touched by this slice**:
- No file under any Employee, Employee Assignment, or Attendance module path was created or
  modified. `git status` shows changes confined to `apps/api/src/hrms/modules/organisation/`,
  new `apps/api/tests/**/test_shift*.py` files, the new
  `apps/api/alembic/versions/20260813170000_shift_rules.py` migration, and
  `apps/web/src/{app/app/shifts,components/shift,lib/shift}` plus one nav-file line — nothing
  else.
- No `Employee`, `EmployeeAssignment`, or `Attendance` ORM class, table, schema, or route was
  added, modified, or referenced.
- `employee_assignment.shift_id` (the future FK Employee Assignment will use to reference this
  table) does not exist yet and is not referenced by any code in this slice — the
  relationship is one-directional and forward-only, exactly as scoped.

## 20. Recommended next step

**EMPLOYEE.**

Employee is the natural next vertical slice: it is the remaining foundational entity every
deferred item in this report depends on — the BR-14 override chain, Employee Assignment's
`shift_id`/`grade_id`/`designation_id` references, and ultimately Attendance's consumption of
Shift's grace/OT/cross-midnight fields all require Employee to exist first. Per this task's
own instructions, **Employee is explicitly not implemented as part of this closeout** — this
is a recommendation for a future task, not an action taken here.

---

## Final status

```
SHIFT RULES:
- Implementation: COMPLETE
- Automated tests: PASS
- Documentation: COMPLETE
- Manual UI: PENDING USER VERIFICATION
- Commit: NOT DONE
```
