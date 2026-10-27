# Initial smoke results

Environment: `hrms_qa_20261026`. Timezone: Asia/Kolkata. Run start: 2026-10-26T18:16:55+05:30.

The API connects as `hrms_qa` (`rolbypassrls = true`). These results show the application company filter and authentication behaviour. They do not verify PostgreSQL row-level security.

Git before and after: `main` at `436a2e5e35b97ae65b27f9553e2317e9b7f6f7b0`, porcelain hash `db2dc52f1f2ec8c7b8f6a4dba22bb60c730b1182`.

Runner: `runtime/smoke_initial.py` with cwd `runtime` and no `.env` file. Not pytest. API PID 1312568. Worker PID 1312569. Celery index 1 still has only the two kombu binding keys. `email_log` stayed at 6. Employee id, name, company, and `updated_at` were unchanged. Developer containers were not connected to.

Two `POST /v1/auth/login` calls obtained bearer tokens for the approved GET cases. They are setup, not scored cases. Each returned only its own company.

| Case | Status | Request | Actual |
| --- | --- | --- | --- |
| PLT-001 | PASS | `GET /health` | 200. `status=ok`, `database=ok`, `redis=skipped`. No email, marker, or company id. |
| AUTH-004 | PASS | `GET /v1/employees` with no auth | 401 `UNAUTHORIZED`, `WWW-Authenticate: Bearer`. No employee names. |
| AUTH-008 | BLOCKED | not sent | Catalogue expectation does not match the missing-header behaviour. |
| AUTH-009 | PASS | Foundry bearer, `X-Company-Id` Northwind, `GET /v1/employees` | 404 `NOT_FOUND`. No employee payload. |
| SEC-001 employee lists | PASS | each admin, own `X-Company-Id`, `GET /v1/employees` | 200, total 1, own employee only. |
| SEC-002 employee GET | PASS | own GET and the other tenant's GET of that id | Own 200 with own id and marker. Cross 404 with neither marker. |
| SEC-001 other lists | not run | leave, attendance, payroll, documents | Outside this approval. |
| SEC-002 other resources and PATCH | BLOCKED | not sent | No fixture rows, and PATCH was not approved. |

Evidence files are the JSON files in this directory.

AWAITING HUMAN REVIEW OF INITIAL SMOKE TEST RESULTS
