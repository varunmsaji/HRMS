# Post-smoke review and next read-only security batch

Reviewed 2026-10-26 from `evidence_smoke_2026-10-26/` and the route source. No application request, migration, or data change was made for this review. The catalogue text for AUTH-008 is unchanged.

## Evidence review

Environment `hrms_qa_20261026`. Run start 2026-10-26T18:16:55+05:30. The API role is `hrms_qa` with row-level security bypass. The smoke results are application filters only.

| Case | Recorded status | What the evidence shows |
| --- | --- | --- |
| PLT-001 | PASS | `GET /health` 200. `status=ok`, `database=ok`, `redis=skipped`. No email, marker, or company id. |
| AUTH-004 | PASS | Anonymous `GET /v1/employees` 401 `UNAUTHORIZED`, `WWW-Authenticate: Bearer`. No employee names. |
| AUTH-008 | BLOCKED | Not sent. |
| AUTH-009 | PASS | Foundry bearer and Northwind `X-Company-Id` on `GET /v1/employees` returned 404 `NOT_FOUND` and no employee payload. |
| SEC-001 employee lists | PASS | Each company admin received total 1 and only that tenant's employee. |
| SEC-002 employee GET | PASS | Owner GET 200 with that employee. The other tenant's GET of the same id returned 404 with neither marker. |
| Other lists and PATCH | not run / BLOCKED | Leave, attendance, payroll, documents, and PATCH were outside the approval. |

Employee rows and `email_log` were unchanged. Git at the smoke run was `main` `436a2e5e35b97ae65b27f9553e2317e9b7f6f7b0`.

## AUTH-008 expected versus actual

Catalogue case, unchanged, in `08_SECURITY_TENANT_ISOLATION_TEST_CATALOGUE.md`:

- Objective: a session without a selected company cannot read company data.
- Step: authenticate, then call the employee list without the company header.
- Expected: 400 or 401. The body contains neither company's employees. No 200 with rows.

That text is also what `02_ROLE_PERMISSION_MATRIX.md` points at for "missing company context", and what batch S in `TEST_EXECUTION_PLAN.md` lists. It was not sent, so there is still no actual HTTP result.

The implementation in `get_tenant_context` treats `X-Company-Id` as optional. When the header is absent it keeps `company_id` from the access token and continues. A header that disagrees with the token raises `NotFoundError` (404). That mismatch path is what AUTH-009 passed.

Sources that do not say "missing header is 400 or 401":

- `docs/product/17_SRS_Phase1_Core_Modules.md` `FR-AUTH-008` is forgot-password: single-use token, 30-minute expiry, identical response whether or not the account exists. It is a different requirement that shares the number.
- `docs/architecture/03_System_Architecture.md` requires `Authorization`, `X-Company-Id`, and `X-Request-Id` on mutating requests. It does not define the GET-without-header status.
- `docs/architecture/00_HRMS_SYSTEM_ARCHITECTURE.md` records mismatch as 404. It does not require rejection when the header is omitted.
- `docs/architecture/POSTGRES_RLS_ROLE_MIGRATION_PLAN.md` records the header as optional and states that `get_tenant_context` sets the company from the verified token when the header was omitted.
- `docs/api/modules/payroll.md` marks `X-Company-Id` required `no` and says to omit the header or send the token's `company_id`.

This is an unresolved product/security discrepancy. The catalogue expectation stays 400 or 401 with no employee rows. The architecture and API module docs describe a token-bound company when the header is omitted. This review does not choose which one should win, and it does not change application code or the catalogue. AUTH-008 stays unexecuted until that decision is written down.

## Proposed batch, ready with the current fixtures

Execute only after a later approval, and only after a fresh isolation proof. The API will still be `hrms_qa` unless a separate approval switches the role. A pass in this batch still does not prove PostgreSQL row-level security.

Authentication setup, not a scored case: `POST /v1/auth/login` for `founder.a@example.com` and `founder.b@example.com`, then `Authorization: Bearer` and `X-Company-Id` equal to that token's company. Login creates a session row. It does not create employees, leave, attendance, payroll, or documents.

Existing ids:

- Foundry company `a6c1f28f-3c8c-4148-b7f5-e43dbecf91f4`, employee `eee9f7cc-292c-49f4-aff9-92d490ff6b1f`, marker `MARKER-FOUNDRY`, email `founder.a@example.com`.
- Northwind company `567bc97e-c165-4cc4-a0bc-98f527077f2c`, employee `d265d407-1d86-4947-b147-f1805eb91d21`, marker `MARKER-NORTHWIND`, email `founder.b@example.com`.

Each case is run in both directions. Stop the batch if a response contains the other tenant's marker, email, company id, or employee id.

| Case | Request | Records required | Expected | Writes |
| --- | --- | --- | --- | --- |
| SEC-R01 | `GET /v1/me` | existing admins | Own header: 200 and only the caller's company. Other company header: 404 `NOT_FOUND` and no other-tenant marker or email. | none |
| SEC-R02 | `GET /v1/companies/current` | existing companies | Own header: 200 and that company's name. Other company header: 404 and no other-tenant name. | none |
| SEC-R03 | `GET /v1/companies/{company_id}` | existing company ids | Own id: 200 and own name. Other id with the caller's own header: 404 `Resource not found`. | none |
| SEC-R04 | `GET /v1/users` | existing admins | Own header: 200, own email present, other email absent. Other company header: 404 and neither email. | none |
| SEC-R05 | `GET /v1/employees/{employee_id}/identity` | existing employee ids | Own id: 200 and that employee id. Other id: 404. Neither body contains the other marker, email, or employee id. | none |
| SEC-R06 | `GET /v1/employees/{employee_id}/employments` | existing employee ids | Own id: 200 and `data` empty, because no employment row was created. Other id: 404. | none |
| SEC-R07 | `GET /v1/employees/{employee_id}/assignments` | existing employee ids | Same as SEC-R06. | none |
| SEC-R08 | `GET /v1/employees/{employee_id}/compensation` | existing employee ids | Same as SEC-R06. | none |
| SEC-R09 | `GET /v1/employees/{employee_id}/statutory` | existing employee ids | Same as SEC-R06. | none |
| SEC-R10 | `GET /v1/employees/{employee_id}/bank` | existing employee ids | Same as SEC-R06. | none |
| SEC-R11 | `GET /v1/employees/{employee_id}/experience` | existing employee ids | Same as SEC-R06. | none |
| SEC-R12 | `GET /v1/employees/{employee_id}/education` | existing employee ids | Same as SEC-R06. | none |
| SEC-R13 | `GET /v1/employees/{employee_id}/dependents` | existing employee ids | Same as SEC-R06. | none |
| SEC-R14 | `GET /v1/employees/{employee_id}/documents` | existing employee ids | Own id: 200 and `data` empty. No storage URL is built when the list is empty. Other id: 404. | none |

SEC-R06 through SEC-R14 prove that the other employee id is refused. An empty own list does not prove that a child row would stay inside the tenant. Those child rows do not exist yet.

## Not proposed for a pass

These GET routes exist. Both tenants currently have no rows, so a 200 with an empty list would be true even if the company filter were absent. They are not in the approval list above.

- Leave: `GET /v1/leave-types`, `GET /v1/leave-policies`, `GET /v1/leave-applications`, `GET /v1/leave-balances?employee_id=`, `GET /v1/leave-ledger?employee_id=`.
- Attendance: `GET /v1/attendance/punches`, `GET /v1/attendance/days`, `GET /v1/attendance-periods`, `GET /v1/regularizations`, `GET /v1/overtime`.
- Payroll lists: `GET /v1/payroll/pay-runs`, `GET /v1/payroll/salary-components`, `GET /v1/payroll/salary-structures`, `GET /v1/me/payslips`.
- Organisation masters: `GET /v1/legal-entities`, `GET /v1/branches`, `GET /v1/departments`, `GET /v1/designations`, `GET /v1/grades`, `GET /v1/shifts`.
- `GET /v1/onboarding-cases`.

`GET /v1/leave-balances` with the other employee id is not a 404 for a company administrator. Company scope skips the visibility 404 and the query returns an empty list. Without a balance row, that empty list cannot show a leak. It stays out of the scored batch.

Two GETs write a default row on first read. They are excluded from this read-only batch:

- `GET /v1/payroll/settings` calls `get_or_create`.
- `GET /v1/leave-year-setting` inserts a default when the row is absent.

There is no separate document-download route. The document list is what attaches a presigned URL, and only after a document row exists. PATCH and DELETE are not in this batch. AUTH-008 is not in this batch.

## Fixtures that need a separate approval

Do not create these in the next run unless that approval names them.

Smallest set that would make list and GET-by-id isolation scoreable:

1. One leave type, one published policy, and one leave application in each company, with the marker in the application reason. `GET /v1/leave-applications` and `GET /v1/leave-applications/{id}` can then require the caller's marker and forbid the other marker, and the other id must be 404.
2. One punch for each existing employee. `GET /v1/attendance/punches` and the day read that the punch creates can use the same ownership rule.
3. One employee document in each company, stored only in bucket `hrms-qa-20261026`. `GET /v1/employees/{id}/documents` would then return that tenant's metadata and a QA presigned URL, and the other employee id would remain 404.
4. Payroll needs a salary assignment before `GET /v1/employees/{id}/salary` has a row, and a pay run before `GET /v1/payroll/pay-runs/{id}` has an id. That is a larger write than items 1–3. It should be a separate decision.

Any of those setups must stay on the logging email provider and the QA bucket. No live mail, payment, or webhook.

## Files changed

- Added `docs/qa/comprehensive_hrms/evidence_smoke_2026-10-26/POST_SMOKE_REVIEW.md`.

No catalogue expected result, application source, migration, or fixture row was edited.

AWAITING HUMAN APPROVAL FOR NEXT READ-ONLY SECURITY BATCH
