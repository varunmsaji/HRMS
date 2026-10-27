# Pre-execution validation, SEC-R01–SEC-R14

Validated from router and service source on 2026-10-26. No HTTP request, login, test, fixture, or migration was run. Catalogue expectations were not edited.

Statuses: `READY` means the proposed method, path, tenant behaviour, and response check are fixed by the code and the GET does not write a business row. `INVALID_ROUTE` means the proposed path is not registered. `EXPECTATION_UNRESOLVED` was not needed.

The API process still uses `hrms_qa`, which bypasses PostgreSQL row-level security. These cases, if later approved, would exercise application filters only.

A foreign `X-Company-Id` is rejected in `get_tenant_context` before the handler: `apps/api/src/hrms/core/tenancy/dependencies.py` lines 20–30 raise `NotFoundError` (`core/errors/base.py` lines 30–32, HTTP 404, code `NOT_FOUND`, message `Resource not found`). Authentication is `get_current_user` through that dependency (`core/auth/dependencies.py` lines 19–25): no bearer is HTTP 401 `UNAUTHORIZED`.

## Case list

| Case | Status | Proposed request | Code result |
| --- | --- | --- | --- |
| SEC-R01 | INVALID_ROUTE | `GET /v1/me` | No router registers `/v1/me`. |
| SEC-R02 | READY | `GET /v1/companies/current` | Own header 200 with that company name. Foreign header 404. |
| SEC-R03 | INVALID_ROUTE | `GET /v1/companies/{company_id}` | No router registers that path. |
| SEC-R04 | READY | `GET /v1/users` | Own header 200 with that admin email and first name. Foreign header 404. |
| SEC-R05 | READY | `GET /v1/employees/{employee_id}/identity` | Own id 200 with that `employee_id`. Other id 404. |
| SEC-R06 | READY | `GET /v1/employees/{employee_id}/employments` | Own id 200, `data` empty. Other id 404. |
| SEC-R07 | READY | `GET /v1/employees/{employee_id}/assignments` | Same contract as SEC-R06. |
| SEC-R08 | READY | `GET /v1/employees/{employee_id}/compensation` | Same contract as SEC-R06. |
| SEC-R09 | READY | `GET /v1/employees/{employee_id}/statutory` | Same contract as SEC-R06. |
| SEC-R10 | READY | `GET /v1/employees/{employee_id}/bank` | Same contract as SEC-R06. |
| SEC-R11 | READY | `GET /v1/employees/{employee_id}/experience` | Same contract as SEC-R06. |
| SEC-R12 | READY | `GET /v1/employees/{employee_id}/education` | Same contract as SEC-R06. |
| SEC-R13 | READY | `GET /v1/employees/{employee_id}/dependents` | Same contract as SEC-R06. |
| SEC-R14 | READY | `GET /v1/employees/{employee_id}/documents` | Own id 200, `data` empty, no storage URL. Other id 404. |

## SEC-R01 and SEC-R03

`identity/router.py` line 32 sets prefix `/auth`, and `app.py` line 218 mounts that router at `/v1`.

- `GET /me` is `identity/router.py` lines 159–170, so the registered path is `GET /v1/auth/me`.
- `GET /companies/{company_id}` is `identity/router.py` lines 183–194, so the registered path is `GET /v1/auth/companies/{company_id}`.

`organisation/router.py` line 97 has no prefix. Its company read is only `GET /companies/current` (lines 141–148). `platform/router.py` line 113 is a platform route, not this tenant route.

Those two implemented paths are not approved by correcting them here. For a later decision, their contracts are:

- `GET /v1/auth/me` has no extra permission. `get_me` (`identity/service.py` lines 308–327) returns `user.email`, `user.company_id`, `user.employee_id`, permissions, timezone, and `company_status`. It does not return the company name, so `MARKER-FOUNDRY` is not in this body. The admin was not linked to the employee row, so `employee_id` is null. A foreign header is 404 and the body has neither admin email. The read does not insert a row.
- `GET /v1/auth/companies/{company_id}` compares the path id with the token company (`identity/service.py` lines 330–340). Own id returns 200 `CompanyDetail` with `name` and `status`. The other id, with the caller's own header, returns 404. A foreign header is 404 before that comparison. The read does not insert a row.

## READY cases

Mounts: organisation and account-invite and employee routers are included at `/v1` in `app.py` lines 219, 220, and 227. None of those three routers adds another prefix.

SEC-R02. `organisation/router.py` lines 141–148. Permission `ORG.COMPANY.MANAGE`, granted to `COMPANY_ADMIN` at `organisation/service.py` lines 532–534. `get_company_profile` (lines 873–877) loads one company and returns `CompanyProfileRead.name` (`organisation/schemas.py` lines 231–233). The stored names contain the markers. A foreign header never reaches this handler.

SEC-R04. `account_invite/router.py` lines 59–70. Permission `SETTINGS.USER.MANAGE`, granted at `organisation/service.py` lines 592–607. `list_users` (`account_invite/service.py` lines 456–495) returns `UserSummary.email` and `first_name` (`account_invite/schemas.py` lines 63–72). The admin first names are the markers, so each list must contain its own email and marker and must not contain the other email or marker. A foreign header is 404 and contains neither email.

SEC-R05. `employee/router.py` lines 309–326. Permission `EMPLOYEE.VIEW_SENSITIVE` (`employee/permissions.py` line 185), included in `EMPLOYEE_PERMISSIONS` and granted to `COMPANY_ADMIN` at `organisation/service.py` lines 559–562. `get_identity` (`employee/service.py` lines 631–655) loads the employee in the token company and raises `NotFoundError` when that row is absent. `EmployeeIdentityRead.employee_id` is the ownership field (`employee/schemas.py` lines 856–857). The marker and email are not fields of this schema. Null PAN and Aadhaar return before decryption writes anything (`core/crypto/service.py` lines 64–65).

SEC-R06 through SEC-R13. Each list calls `_assert_employee_visible` or the same `get_employee` lookup, then returns the child rows. `create_employee` returns after the employee and its audit row (`employee/service.py` lines 389–401) and does not create those children, so the own list is empty. The other employee id is not in the caller's company, so the lookup raises 404.

| Case | Route lines | Permission | Visibility check |
| --- | --- | --- | --- |
| SEC-R06 | `employee/router.py` 389–410 | `EMPLOYEE.VIEW` (`identity/permissions.py` line 5; grant `organisation/service.py` line 557) | `EmploymentService.list_employments` line 1172 |
| SEC-R07 | 508–516 | `EMPLOYEE.VIEW` | `EmployeeAssignmentService.list_assignments` line 2042 |
| SEC-R08 | 615–623 | `EMPLOYEE.VIEW_COMPENSATION` | `EmployeeCompensationService.list_compensations` line 2301 |
| SEC-R09 | 709–717 | `EMPLOYEE.VIEW_STATUTORY` | `EmployeeStatutoryService.list_statutories` line 2543 |
| SEC-R10 | 798–806 | `EMPLOYEE.VIEW_BANKING` | `EmployeeBankService.list_banks` line 2811 |
| SEC-R11 | 886–894 | `EMPLOYEE.VIEW_EXPERIENCE` | `EmployeeExperienceService.list_experiences` line 2964 |
| SEC-R12 | 992–1000 | `EMPLOYEE.VIEW_EXPERIENCE` | `EmployeeEducationService.list_educations` line 3148 |
| SEC-R13 | 1096–1104 | `EMPLOYEE.VIEW_NOMINEE` | `EmployeeDependentService.list_dependents` line 3395 |

The `.VIEW_*` codes are in `EMPLOYEE_PERMISSIONS` (`employee/permissions.py` lines 169–196) and are granted with the default scope `COMPANY` (`organisation/repository.py` lines 165–174). An empty own list shows that the caller's employee id is accepted. It does not show that a child row would stay inside the tenant, because no child row exists.

SEC-R14. `employee/router.py` lines 1234–1251. Permission `EMPLOYEE.VIEW_DOCUMENTS`. `list_documents_with_urls` (`employee/service.py` lines 3609–3636) checks visibility, then builds a presigned URL only inside the loop over existing documents. An empty list does not call storage.

None of these GET handlers call `get_or_create` or insert a business row. A rejected foreign header writes a security log event only (`dependencies.py` lines 23–29).

## Not executed

SEC-R01 and SEC-R03 are not executable as proposed. SEC-R02 and SEC-R04 through SEC-R14 are ready and still wait for approval. No request from this review was sent.

AWAITING HUMAN APPROVAL FOR READ-ONLY SECURITY BATCH
