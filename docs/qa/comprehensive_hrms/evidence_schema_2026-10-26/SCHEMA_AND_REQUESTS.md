# Schema setup and Batch 0 / Batch S request definitions

Date: 2026-10-26. No application HTTP request was issued. Batch 0 and Batch S were not run.

## Isolation

`ISOLATION PROVED` before any DDL.

- Free space before schema work: 26339962880 bytes. Free space after fixture preparation: 26315116544 bytes. Both are above the 4 GiB gate.
- Migration and seed processes used `MIGRATIONS_DATABASE_URL` / `DATABASE_URL` for `127.0.0.1:15433/hrms_qa_20261026` only. `SELECT current_database()` returned `hrms_qa_20261026` before role creation and after upgrade.
- API PID 1312568 and worker PID 1312569 were still the QA processes. Their `DATABASE_URL`, Redis `127.0.0.1:16380/0`, Celery `127.0.0.1:16380/1`, bucket `hrms-qa-20261026`, and `EMAIL_PROVIDER=logging` matched `runtime/qa.env`.
- Developer containers were unchanged and were not connected to: `hrms-postgres` `b90719b25090ef13f9f9470bef7274f15d488cfdb146c9d12296526236d4af60`, `hrms-redis` `e451a0191fa9f735f08a2df959f9e5de2b0bdcde307cacc8e244b0667ab6085c`, `hrms-minio` `dc8318a20fd487481d154458aca85e912133d97ebab28ece29fc888fc33012b4`.
- Email provider `logging`. SMTP host, username, and password empty. Mailtrap, Hostinger, and Face++ tokens empty. The object-store key is the QA MinIO user for `http://127.0.0.1:19000`, bucket `hrms-qa-20261026`.
- Alembic was run with cwd `docs/qa/comprehensive_hrms/runtime` and `runtime/alembic.qa.ini`. That ini points at the existing `apps/api/alembic` scripts. `apps/api/.env` was not the working directory and was not loaded.
- Git before and after: branch `main`, commit `436a2e5e35b97ae65b27f9553e2317e9b7f6f7b0`, porcelain 263 lines, content hash `db2dc52f1f2ec8c7b8f6a4dba22bb60c730b1182`. The hash is unchanged because this phase only added files inside the already untracked `docs/qa/comprehensive_hrms/` tree. Nothing was staged, committed, reset, or discarded.

## Migration review and result

Mechanism: Alembic. There is one head. Startup does not run migrations. No migration drops the database or opens SMTP or HTTP.

`002_app_role.sh` was not run. The DDL trigger probe was not run. One revision, `20260828090000`, grants execute on `login_lookup_user_companies` to `hrms_app` without a role-existence guard. Other revisions revoke privileges from that role only inside `IF EXISTS`. Before upgrade, the empty role was created on `hrms_qa_20261026` only:

`CREATE ROLE hrms_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`

No `GRANT ALL` and no `ALTER DEFAULT PRIVILEGES`. The password is only in gitignored `runtime/qa.env` as `QA_HRMS_APP_PASSWORD`. The running API and worker were not restarted and still connect as `hrms_qa`, which bypasses row-level security. Application queries that take a company id still constrain by that id. A later smoke test on this API process therefore exercises those application filters. It does not exercise PostgreSQL row-level security.

Command, from the runtime directory, with `qa.env` sourced and `PYTHONPATH` set to `apps/api/src` and `apps/api`:

`apps/api/.venv/bin/python -m alembic -c runtime/alembic.qa.ini heads`

`apps/api/.venv/bin/python -m alembic -c runtime/alembic.qa.ini upgrade head`

Result: single head `20261027092000`. The database had no `alembic_version` row; upgrade started at `20260803124757` and ended at `20261027092000`. Read-only check: `alembic_version.version_num = 20261027092000`, 114 public base tables, `current_database() = hrms_qa_20261026`.

## Synthetic tenants

Prepared in-process through `seed_plan_catalogue`, `OrganisationService.register_company`, `IdentityService.verify_email`, `IdentityService.reset_password`, and `EmployeeService.create_employee`. No HTTP call. No SMTP delivery. `email_log` has 6 rows, all `provider=logging` and `status=LOGGED_ONLY`.

`founder.a@qa.invalid` is rejected by `CompanyRegistrationRequest.admin_email` (`EmailStr` refuses the reserved `.invalid` domain). The supported registration path therefore used `founder.a@example.com` and `founder.b@example.com`. Passwords are only in gitignored `runtime/fixture-secrets.env`.

| Marker | Company id | Status | Admin user | Admin email | Admin role | Employee id |
| --- | --- | --- | --- | --- | --- | --- |
| MARKER-FOUNDRY | `a6c1f28f-3c8c-4148-b7f5-e43dbecf91f4` | PENDING_APPROVAL | `dfe01642-db29-4ad6-8645-1fe785791c80` | founder.a@example.com | COMPANY_ADMIN | `eee9f7cc-292c-49f4-aff9-92d490ff6b1f` |
| MARKER-NORTHWIND | `567bc97e-c165-4cc4-a0bc-98f527077f2c` | PENDING_APPROVAL | `0fffc8c9-fbf8-447a-b716-4d6248f495f1` | founder.b@example.com | COMPANY_ADMIN | `d265d407-1d86-4947-b147-f1805eb91d21` |

Both admins have `email_verified_at` set and membership status `ACTIVE`. Registration also created unassigned roles `HR_ADMIN`, `REPORTING_MANAGER`, `BRANCH_MANAGER`, and `EMPLOYEE` in each company. `COMPANY_ADMIN` holds `EMPLOYEE.VIEW_ALL` and `EMPLOYEE.VIEW`. Employee `first_name` is the marker and `last_name` is `Employee`. Companies are `PENDING_APPROVAL`: sign-in is allowed, and GET/HEAD/OPTIONS are allowed; other methods return 403.

Identifiers are also in `fixtures.json`.

## Exact requests, not executed

Base URL of the already running QA API: `http://127.0.0.1:18000`.

Authentication setup for later use, not called in this phase:

- `POST /v1/auth/login`
- Header: `Content-Type: application/json`
- Body: `{"email":"<admin email>","password":"<value from fixture-secrets.env>"}`
- Expected success: 200 `{"data":{"access_token":"...","token_type":"Bearer","expires_in_minutes":...,"company_id":"...","companies":[...]},"meta":{...}}`
- Later calls use `Authorization: Bearer <access_token>` and `X-Company-Id: <company id from that token>`.

### PLT-001 — specified, not run

- `GET /health`
- No authentication and no company header.
- Expected: 200 `{"data":{"status":"ok"|"degraded","database":"ok"|"error","redis":"ok"|"error"|"skipped"},"meta":{...}}`
- The model has no person, company, or marker fields. Neither `MARKER-FOUNDRY` nor `MARKER-NORTHWIND` may appear.
- This route runs a database check. It was not called.

### AUTH-004 — specified, not run

- `GET /v1/employees`
- No `Authorization` header and no `X-Company-Id`.
- Expected: 401, `WWW-Authenticate: Bearer`, body `{"error":{"code":"UNAUTHORIZED","message":"Authentication required","details":[],"request_id":"..."}}`
- Neither marker and neither admin email may appear.

### AUTH-008 — BLOCKED

The catalogue expects a missing company context to be rejected with 400 or 401 and no employee rows. `get_tenant_context` does not reject a missing `X-Company-Id`. It uses `company_id` from the access token and continues. A request definition that expected 400 or 401 would contradict the code, and the catalogue expectation was not changed. Do not send this case until the expected result is clarified.

### AUTH-009 — specified, not run

- `GET /v1/employees`
- `Authorization: Bearer <Foundry access token>`
- `X-Company-Id: 567bc97e-c165-4cc4-a0bc-98f527077f2c`
- Expected: 404 `{"error":{"code":"NOT_FOUND","message":"Resource not found","details":[],"request_id":"..."}}`
- `MARKER-NORTHWIND` and `founder.b@example.com` must be absent. The catalogue's accepted statuses include 404.

### SEC-001 — specified, not run

- `GET /v1/employees` as Foundry: `Authorization` Foundry bearer and `X-Company-Id: a6c1f28f-3c8c-4148-b7f5-e43dbecf91f4`
- `GET /v1/employees` as Northwind: Northwind bearer and `X-Company-Id: 567bc97e-c165-4cc4-a0bc-98f527077f2c`
- Expected: 200 `{"data":[...],"pagination":{...},"meta":{...}}`
- The Foundry body may contain `MARKER-FOUNDRY` and must not contain `MARKER-NORTHWIND` or `founder.b@example.com`.
- The Northwind body may contain `MARKER-NORTHWIND` and must not contain `MARKER-FOUNDRY` or `founder.a@example.com`.

### SEC-002 — employee GET specified; the rest of the case is BLOCKED

Employee GET, not run:

- As Northwind, `GET /v1/employees/eee9f7cc-292c-49f4-aff9-92d490ff6b1f` with the Northwind bearer and Northwind `X-Company-Id`.
- As Foundry, `GET /v1/employees/d265d407-1d86-4947-b147-f1805eb91d21` with the Foundry bearer and Foundry `X-Company-Id`.
- Expected: 404 `NOT_FOUND` / `Resource not found`. The other tenant's marker and email must be absent.
- The same call with the owning tenant's bearer and company header is the control and is expected to be 200 with that tenant's marker only. It is not part of the cross-tenant assertion and was not sent.

Leave, attendance, payroll, and document GET-by-id are BLOCKED. No fixture rows exist for those resources, and none were invented. The PATCH half of SEC-002 is outside this batch and must not be sent. Do not score SEC-002 from the employee GET alone.

## Files changed

All under `docs/qa/comprehensive_hrms/`, which was already untracked:

- `.gitignore` now ignores fixture secrets and runtime SQL.
- `runtime/alembic.qa.ini`
- `runtime/qa.env` gained `QA_HRMS_APP_PASSWORD` only.
- `runtime/fixture-secrets.env`
- `runtime/seed_markers.py`
- `runtime/finish_markers.py`
- `evidence_schema_2026-10-26/fixtures.json`
- `evidence_schema_2026-10-26/SCHEMA_AND_REQUESTS.md`

## Confirmation

No test batch, health request, login, or other application HTTP request was run. Pytest was not run. The QA database was not reset.

AWAITING HUMAN REVIEW BEFORE INITIAL SMOKE TESTS
