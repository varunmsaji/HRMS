# Employee Document permission backfill — fix report

Narrow remediation for one issue: an existing (pre-feature) `COMPANY_ADMIN` account received
HTTP 403 on `GET /v1/employees/{id}/documents`, while a freshly registered tenant worked fine.

## 1. Root cause

`organisation/service.py::register_company` grants `COMPANY_ADMIN` **every** code in
`EMPLOYEE_PERMISSIONS` (including the new `EMPLOYEE.VIEW_DOCUMENTS`) at `COMPANY` scope, via the
same loop that also grants `HR_ADMIN`. But the one-time catch-up migration for existing tenants,
`20261014091000_employee_view_documents_backfill.py`, only backfilled `HR_ADMIN` (COMPANY scope)
and `EMPLOYEE` (SELF scope) — it never inserted the corresponding `role_permission` row for
`COMPANY_ADMIN`. Any tenant registered before this permission existed was left with a
`COMPANY_ADMIN` role missing exactly this one code, so `require_permission(EMPLOYEE_VIEW_DOCUMENTS)`
(`core/rbac/dependencies.py`) failed closed with `PERMISSION_DENIED` (403). There is no
superuser/role-code bypass anywhere in the RBAC path (`RbacService.resolve_data_scope` is a plain
`role_permission` join) — every permission, `COMPANY_ADMIN` included, is strictly row-driven.

Confirmed directly against the dev database before any fix: "My Company"'s `COMPANY_ADMIN` role
held every other `EMPLOYEE.*` code at `COMPANY` scope (`VIEW_SENSITIVE`, `VIEW_STATUTORY`,
`UPDATE_SENSITIVE`, `VIEW_EXPERIENCE`, `VIEW_NOMINEE`, etc.) and only `EMPLOYEE.VIEW_DOCUMENTS` was
absent — an isolated gap, not a symptom of a broader pattern (see §19 Remaining risks for the one
caveat).

## 2. Intended role/permission behavior

Traced from `register_company` (the live source of truth) and the existing
`EMPLOYEE.VIEW_SENSITIVE` / `EMPLOYEE.VIEW_NOMINEE` backfill migrations it mirrors:

| Role | `EMPLOYEE.VIEW_DOCUMENTS` | `EMPLOYEE.UPDATE_SENSITIVE` |
|---|---|---|
| `COMPANY_ADMIN` | **Yes**, `COMPANY` scope (holds the full `EMPLOYEE.*` catalogue, no exceptions) | Yes, `COMPANY` scope — already correct, unaffected by this fix |
| `HR_ADMIN` | Yes, `COMPANY` scope — already correct | Yes, `COMPANY` scope — already correct |
| `EMPLOYEE` | Yes, `SELF` scope (can view/download own documents) | No — ordinary employees cannot upload/delete/review |
| Any other role | No, unless explicitly granted | No, unless explicitly granted |

No permission was broadened beyond what `register_company` already grants new tenants.

## 3. Existing behavior before fix

- New tenant → `COMPANY_ADMIN`/`HR_ADMIN`/`EMPLOYEE` all correctly provisioned at registration;
  `GET .../documents` worked for all three.
- Existing tenant ("My Company") → `HR_ADMIN` and `EMPLOYEE` worked (covered by the original
  backfill); `COMPANY_ADMIN` got 403 on `GET .../documents`.

## 4. Migration created

No new migration file — `20261014091000_employee_view_documents_backfill.py` was itself still
uncommitted (drafted by the prior agent, already applied once to the dev DB with the gap). Added
one more `INSERT INTO role_permission ... SELECT ca.id, p.id, 'COMPANY' FROM role ca ...  WHERE
ca.code = 'COMPANY_ADMIN'` block, same shape and same `ON CONFLICT (role_id, permission_id) DO
NOTHING` idempotency guard as the pre-existing `HR_ADMIN` block right next to it. `downgrade()`
needed no change — it already deletes every `role_permission` row by `permission_id` regardless of
role.

## 5. Exact roles affected

`COMPANY_ADMIN` only. `HR_ADMIN` and `EMPLOYEE` blocks are untouched (byte-for-byte identical to
the prior draft).

## 6. Exact permission(s) granted

`EMPLOYEE.VIEW_DOCUMENTS`, `COMPANY` scope, to the `COMPANY_ADMIN` role of every company whose row
doesn't already have it. No other permission code touched.

## 7. Migration safety/idempotency

- Guarded by `ON CONFLICT (role_id, permission_id) DO NOTHING` (same composite PK as every other
  backfill migration in this repo).
- Re-ran the full `upgrade()` SQL a second time directly against `hrms_dev`: `INSERT 0 0` for all
  four statements — zero rows affected, no errors.
- `downgrade()` → `upgrade()` cycle (required since the migration had already been marked applied)
  completed cleanly on both `hrms_dev` and `hrms_test`.

## 8. Database verification

**Before fix** (`hrms_dev`, "My Company"): `COMPANY_ADMIN` had every `EMPLOYEE.*` code except
`VIEW_DOCUMENTS`; `HR_ADMIN` had `VIEW_DOCUMENTS` at `COMPANY`; `EMPLOYEE` had it at `SELF`.

**After fix**: exactly one `permission` row for `EMPLOYEE.VIEW_DOCUMENTS` (no duplicate catalogue
row); exactly 3 `role_permission` rows per company (`COMPANY_ADMIN`/`COMPANY`,
`HR_ADMIN`/`COMPANY`, `EMPLOYEE`/`SELF`) — verified across both companies in the dev DB
(`My Company`, `Doc Verify Co`), no duplicates, no unintended grants to `REPORTING_MANAGER`,
`BRANCH_MANAGER`, or any other role.

## 9. Tests added/updated

In `tests/integration/modules/employee/test_employee_documents.py` (file was already drafted by
the prior agent; only additions below, nothing pre-existing changed):

- `test_existing_company_admin_backfilled_gains_view_documents` — simulates a pre-existing tenant
  by deleting just the `COMPANY_ADMIN → EMPLOYEE.VIEW_DOCUMENTS` row, asserts 403, runs the
  migration's exact backfill SQL, asserts 200, runs it again to prove idempotency (no duplicate
  rows, no error), asserts the endpoint still works.
- `test_hr_admin_retains_view_documents_access` — HR_ADMIN (COMPANY scope) can list documents it
  didn't upload.
- `test_view_documents_permission_catalogue_has_single_row` — exactly one `permission` row for
  the code.

Pre-existing tests in that same file already cover: new-tenant COMPANY_ADMIN access (via the
registering admin's own `headers` in `test_list_documents_has_download_url` etc.), unauthorized
role → 403, SELF-scoped employee → own documents only / 404 on another employee / no write access,
and cross-tenant isolation → 404. `tests/integration/modules/organisation/test_registration_flow.py`
already asserted (pre-existing, unmodified by this fix) that a freshly registered `COMPANY_ADMIN`'s
permission set includes `EMPLOYEE.VIEW_DOCUMENTS`.

## 10. Targeted test results

```
tests/integration/modules/employee/test_employee_documents.py — 15 passed
tests/integration/test_route_authorization_matrix.py — 6 passed
tests/integration/modules/organisation/test_permission_matrix.py (isolated) — 24 passed
```

## 11. Full regression results

`tests/integration/modules/employee`, `tests/integration/modules/organisation`,
`tests/unit/modules/employee` together: **831 passed, 2 errors**. The 2 errors
(`test_permission_matrix.py::test_company_admin_allowed[...]`) are a `UniqueViolationError` on
`plan.code = 'FREE'` — a pre-existing test-isolation flake from a session-scoped plan-seeding
fixture colliding across files when run in one large batch. Confirmed unrelated to this fix by
running that file alone: 24/24 pass cleanly. Not touched, per scope.

Frontend was not touched by this fix (migration + backend tests only) and was not re-verified;
the uncommitted `apps/web` document-panel files predate this session and are unrelated to the
permission-backfill gap.

## 12. Browser verification

The built-in browser tools were available, but "My Company"'s `COMPANY_ADMIN` account
(`varunmsaji01@gmail.com`) is a real-looking personal email with no known password, and no demo
seed exists for it — resetting a real account's credentials to log in was avoided as out of scope
and risky. Instead, verified end-to-end against the live dev API using a JWT minted for that exact
`user_id`/`company_id` (same technique `tests/.../test_employee_documents.py::_create_scoped_actor`
already uses, and the established fallback this repo's own environment notes document when full
browser login isn't available):

- Created a throwaway employee under "My Company" via the real `POST /v1/employees` endpoint.
- `GET /v1/employees/{id}/documents` as `COMPANY_ADMIN` → **200** (was 403 before the fix).
- `POST .../documents` (upload) → **201** — confirms `UPDATE_SENSITIVE` (already correct,
  untouched by this fix) still works.
- `DELETE .../documents/{id}` → **200**.
- Cleaned up: deleted the throwaway employee, its `number_series` row, the uploaded document (via
  the real delete endpoint, which also removed the S3 object), and the ad hoc `session` row used
  to mint the verification JWT. Confirmed 0 leftover employees/documents for that company
  afterward.

`HR_ADMIN`/`EMPLOYEE` live-tenant browser verification was not performed — "My Company" has no
user assigned to either role — but both are covered by the automated integration tests above
(`test_hr_admin_retains_view_documents_access`,
`test_self_scoped_employee_sees_own_documents_only`).

## 13. Existing tenant verification

"My Company" (`22646824-9ddf-4939-81e0-0f19e8c9f5b8`) — see §12. `COMPANY_ADMIN` went from 403 to
200 on `GET .../documents`; `UPDATE_SENSITIVE`-gated routes (upload/delete) were unaffected and
continued to work (they always worked — this fix didn't touch that code).

## 14. New tenant verification

`test_existing_company_admin_backfilled_gains_view_documents` and the full
`test_employee_documents.py` suite register fresh tenants per test and confirm `COMPANY_ADMIN`
gets `GET .../documents` → 200 immediately (no backfill needed) — unaffected by this change, still
passing. `test_registration_flow.py`'s permission-set assertion for a new `COMPANY_ADMIN` already
includes `EMPLOYEE.VIEW_DOCUMENTS` and still passes.

## 15. Employee SELF verification

`test_self_scoped_employee_sees_own_documents_only` — a `SELF`-scoped `EMPLOYEE.VIEW_DOCUMENTS`
holder sees their own employee's documents (200, 1 row), gets 404 on another employee's documents,
and gets 403 trying to upload (no `UPDATE_SENSITIVE`). Unaffected by this fix, still passing.

## 16. Cross-tenant verification

`test_documents_cross_tenant_isolation` — Company A's `COMPANY_ADMIN`/registering admin gets 404
on Company B's employee's documents. Still passing; this fix only added rows scoped to each
company's own `COMPANY_ADMIN` role (`WHERE ca.code = 'COMPANY_ADMIN'` has no cross-tenant join),
so no new cross-tenant exposure was introduced.

## 17. Test artifact cleanup

- Everything created during this session's own verification (one employee, its `number_series`
  row, one uploaded document + S3 object, one ad hoc `session` row) was deleted; confirmed via
  direct count queries afterward (0 leftover rows).
- `pytest` fixtures in the added/existing tests all run through the file's existing `_teardown`
  helper — no new leftover rows from the automated test run.
- **Not cleaned up, reported instead**: `Doc Verify Co` (`4cffbbca-6d0b-4529-810a-c5a93b107173`)
  — an empty shell tenant (0 employees, 0 documents, 0 `user_company` rows, just `company` + `role`
  + `role_permission` rows) found in `hrms_dev` at the start of this session. It predates this
  session (not created by this fix) and is harmless as-is; left alone rather than guessing it's
  safe to delete someone else's leftover test tenant.

## 18. Files changed

- `apps/api/alembic/versions/20261014091000_employee_view_documents_backfill.py` — added the
  `COMPANY_ADMIN` grant block + updated the module docstring to describe it. (File was already
  uncommitted/untracked before this session.)
- `apps/api/tests/integration/modules/employee/test_employee_documents.py` — added 3 tests (§9).
  (File was already uncommitted/untracked before this session.)
- `docs/audits/EMPLOYEE_DOCUMENT_PERMISSION_BACKFILL_FIX.md` — this report (new).

No other file was modified. `git status --short` before and after this session is identical for
every file this session didn't touch.

## 19. Remaining risks

- **Pattern risk, not a live bug today**: the `EMPLOYEE.VIEW_SENSITIVE` (20260928091000),
  `EMPLOYEE.VIEW_EXPERIENCE` (20261001091000), and `EMPLOYEE.VIEW_NOMINEE` (20261003091000)
  backfill migrations have the identical shape gap — they backfill `HR_ADMIN`/`EMPLOYEE` only, not
  `COMPANY_ADMIN`. Direct DB inspection shows this is **not currently biting** any existing tenant
  (both companies in `hrms_dev` already hold all three codes on `COMPANY_ADMIN`, most likely
  because those tenants were registered after those migrations landed, via `register_company`'s
  own grant loop, so they never needed the backfill). But a tenant registered *before*
  `20260920090000` (which introduced `VIEW_STATUTORY`/`UPDATE_SENSITIVE` for `HR_ADMIN` only, same
  gap) and never backfilled for `COMPANY_ADMIN` on any of these codes could still be exposed to
  this same class of 403. Left untouched — out of scope for this remediation, which is one
  permission on one role — but worth a dedicated follow-up migration audit.
- `Doc Verify Co` empty shell tenant remains in `hrms_dev` (§17) — flagged, not removed.
- The pre-existing `plan.code = 'FREE'` test-isolation flake (§11) is unrelated to this fix and
  was not investigated further.

## 20. Final verdict

**FIX VERIFIED**

- `COMPANY_ADMIN` now receives exactly the one missing permission (`EMPLOYEE.VIEW_DOCUMENTS`,
  `COMPANY` scope) — nothing broader.
- Existing tenants are covered (verified against the real "My Company" tenant, not a synthetic
  one).
- New tenants are unaffected and still correct.
- No unintended permission escalation (verified: exactly 3 `role_permission` rows per company for
  this code, no duplicates, no new grants to any other role).
- Migration re-applies cleanly and idempotently on both `hrms_dev` and `hrms_test`.
- No duplicate permission or `role_permission` rows.
- Targeted tests pass (15/15 in the module's own file, plus the route-authorization matrix and
  permission-matrix suites).
- Full employee+organisation+unit regression: 831 passed; the 2 errors are a pre-existing,
  unrelated test-isolation flake, confirmed by isolated re-run.
- Live browser/API verification against the real pre-existing tenant succeeded (403 → 200), with
  full artifact cleanup.
- Cross-tenant isolation remains intact.
