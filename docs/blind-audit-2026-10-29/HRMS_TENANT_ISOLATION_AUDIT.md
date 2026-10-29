# HRMS Tenant Isolation Audit

**Verdict: designed well, partially demonstrated, not fully verified.** `company_id` presence alone was *not* treated as proof.

## 1. Actual tenancy model (confirmed)
Shared DB / shared tables. Layers, outermost first:
1. **Token** carries `company_id` + `session_id` (`core/auth/jwt.py`); HS256, 15-min access TTL.
2. **Per-request revalidation** (`core/auth/dependencies.py:get_current_user`): user ACTIVE & not deleted → session not revoked → `user_company` ACTIVE → company lifecycle (`assert_request_allowed`). Suspension/termination take effect on the next request.
3. **`get_tenant_context`** (`core/tenancy/dependencies.py`): `X-Company-Id` header must equal the token's company, else 404 + `tenant.rejected` event; membership re-checked; RLS GUC re-set from the verified company.
4. **Repositories** filter by `company_id` explicitly (394 / 442 query functions reference it; the other 48 are identity/platform/plan code — reviewed list below).
5. **PostgreSQL RLS** `FORCE ROW LEVEL SECURITY` + policy `company_id = current_setting('app.company_id', true)::uuid` on the 84 tables with direct statements plus the looped payroll/leave/face migrations.

Tenant identity comes from the **verified token**, not from client input (header is only compared). ✔

## 2. Findings
| ID | Sev | Conf. | Finding | Evidence |
|---|---|---|---|---|
| F-01 | P1 | probable | RLS is only *proven* under the real runtime role by 4 tests + geofence RLS. All other integration tests run as `hrms` (SUPERUSER+BYPASSRLS) — the test file's own docstring says so — so they cannot catch an RLS-dependent bug or a missing GUC. Payroll, leave, attendance, org, onboarding flows were **never** exercised under `hrms_app` by the evidence available. | `tests/security/test_rls_runtime_role.py:1-17` |
| F-03 | P1 | confirmed (schema) | Cross-tenant parent references not prevented by the DB for all but 4 FKs. | `alembic/versions/20261027092000…`, `20261030090000…` |
| F-05 | P2 | confirmed | `TenancyMiddleware` copies the **raw, unverified** `X-Company-Id` into the context var (`core/tenancy/middleware.py:21-26`); `get_session` then sets `app.company_id` from it (`core/db/session.py:98-104`) *before* authentication. It is overwritten after verification in `get_tenant_context`. Two routes never run `get_tenant_context` (`GET /auth/admin/users-check`, `GET /employee-imports/template`); both touch no tenant rows. Not exploitable today; fragile by construction (a future route using `require_permission` only, with a repository that trusts RLS instead of `company_id`, would read the attacker-named tenant). | as cited |
| F-06 | P2 | needs live check | ~10 tenant-keyed tables without RLS (`session, refresh_token, user_company, user_role, role, account_invite, email_log, email_outbox, holiday_calendar`). Most are justified by login-time lookup; `holiday_calendar` is not. | migrations |
| F-02 | P1 | probable | Mid-request `commit()` then RLS-table query without re-setting the GUC (employee import enqueue-failure path). Same bug class could recur at other commit sites. | `modules/employee_import/service.py:177-197` vs helper `:611-620` |
| F-23 | P2 | confirmed | `set_rls_company_id(None)` silently no-ops (`session.py:55-56`). With no GUC the policy yields NULL/'' (rows hidden or uuid-cast error) — fail-closed, but the failure mode is a confusing 500 rather than an explicit "tenant context missing". | `core/db/session.py:53-60` |

## 3. Unscoped repository functions (48) — disposition
* `core/db/repositories/identity.py` (15): global user/session/refresh/reset/verify tokens — by design (token hash or user id is the key).
* `modules/platform/repository.py` (18): platform-admin cross-tenant console, gated by `get_current_platform_admin`; every route uses `Principal` (20 routes) except `POST /platform/auth/login` (rate-limited 10/min). Audited into `platform_audit_log`.
* `modules/organisation/repository.py` (plans, permissions, `insert_user`, two count helpers), `modules/onboarding` (`get_by_hash`, token revocation), `modules/account_invite` (`get_by_hash`): token-hash lookups or global catalogues.
* `employee.delete_document`, `onboarding.delete_document`: take an already-loaded, tenant-scoped ORM object.
* `leave._advisory_lock`: lock key only.
* **Residual to confirm:** `organisation.count_active_branches_for_legal_entity` and `count_active_departments_for_branch` (counts keyed by parent id; leak is a count only; RLS would hide other tenants' rows under `hrms_app`).

## 4. Tenant-owned entity × access matrix (summary)
| Entity group | Primary endpoints | Gate | Scope control | Evidence of tenant check | Residual risk |
|---|---|---|---|---|---|
| Employee, employment, assignments, compensation, statutory, bank, docs | `/employees/**` (41 routes) | `require_permission(EMPLOYEE_*)` + `DataScope` (SELF/REPORTEES/BRANCH/COMPANY) | `_assert_employee_visible` | repos filter `company_id`; RLS | F-03 (child refs) |
| Attendance, punches, regularization, periods, overtime | `/attendance/**` (83+6 routes) | permission or self-scope; scope-guard test pins list | `DataScope` | `tests/unit/core/test_scope_enforcement_guard.py` + toml exceptions | F-01 |
| Leave types/policy/ledger/applications | `/leave-*` (34) | permission; balance routes use combined VIEW/VIEW_ALL scope (`leave/router.py:578-607`) | scope + `caller_employee_id` | | F-01 |
| Payroll config, pay runs, payslips, bank advice | `/payroll/**`, `/me/payslips` (43) | `PAYROLL_*` permissions via aliased Depends; `/me/*` uses token `employee_id`, never a path param | | RLS (looped migrations) | F-01, F-03 |
| Organisation (branches, depts, shifts, calendars, policies) | `/…` (77) | `ORG_*_MANAGE`; policy-assignment & calendar-change gate inside handlers (`organisation/router.py:1318-1333, 1543-1572`) | company-level | | F-03 |
| Onboarding (admin) / public token flows | `/onboarding/**` (13), `/public/onboarding/**` (6) | admin permission / opaque hashed token | token → case → company | `onboarding_token` NO FORCE RLS (deliberate, `20260906090000`) | token entropy/rate limit not reviewed |
| Documents | S3 keys from DB rows; presigned GET (`core/storage.py:130`) | via owning entity checks | key derived from row, not client | | presign TTL not reviewed |
| Platform console | `/platform/**` (21) | platform token only | cross-tenant by design | `platform_audit_log` | support-access audit exists; content not reviewed |
| Background jobs | Celery tasks | n/a | `session_scope(company_id=…)` per tenant (leave, attendance, face) | | some sweeps call `session_scope()` without tenant (leave/tasks.py:88, attendance/tasks.py:62, face_cleanup.py:221) to enumerate companies — acceptable because `company` has no RLS; confirm |

## 5. Would RLS add more protection? (not implemented)
It already exists. The gap is *verification*, not mechanism. Recommended: (a) run the whole integration suite as `hrms_app` using a separate admin connection for fixtures; (b) add composite FKs (F-03); (c) make `app.company_id` assignment single-sourced, after authentication only (F-05).

## 6. Not verified
Live `pg_class` flags; `relforcerowsecurity` in production; super-admin/support impersonation depth; presigned-URL TTL; public onboarding token entropy & brute-force limit; export endpoints (`bank-advice` CSV) beyond their permission gate.
