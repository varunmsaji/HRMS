# HRMS API & Authorization Audit

Method: AST scan of every `@router.get/post/put/patch/delete` in `src/hrms` (354 routes), resolving module-level `Annotated[..., Depends(require_permission(...))]` aliases; then manual reading of every route that the scan could not classify as permission-gated. Scan limits: dependency detection is textual; router-level `dependencies=[...]` were not present.

## 1. Inventory by module
| Module | Routes | Gate style |
|---|---|---|
| attendance (+geofence) | 83 + 6 | permission deps + data-scope deps |
| organisation | 77 | permission deps; 4 gated in-handler |
| payroll | 43 | aliased permission deps |
| employee | 41 | permission deps + in-handler (assignments) |
| leave | 34 | permission or combined balance scope |
| platform | 21 (+4 log/email) | platform principal |
| onboarding | 13 admin + 6 public | permission / opaque token |
| identity | 10 | public auth + bearer |
| employee_import 5 · account_invite 4+2 · health 3 · metrics 1 · ingestion 1 | | |

## 2. Unauthenticated routes (21, all intentional-looking)
`/metrics` (bearer token, nginx 404) · `/ingestion/health` (**purpose unclear — F-26 P3**) · health ×3 · `/auth/{login, token/refresh, password/forgot, password/reset, email/verify, email/resend-verification}` · company registration (`/companies/register`, `/companies/registration-config`) · public account-invite ×2 · public onboarding ×6 (token path param) · `/platform/auth/login`.
Rate limiting on these: login/refresh/platform-login confirmed (`rate_limit(...)`); limits on forgot/reset/verify/resend, registration, and public onboarding token endpoints were **not individually traced** — flagged *unverified*.

## 3. Authenticated, no static permission (18) — each read
| Route | Real gate | Verdict |
|---|---|---|
| `POST /employees/{id}/assignments` | in-handler `resolve_data_scope(EMPLOYEE_PROMOTE|TRANSFER)` chosen by `change_type`; empty levels → 403 (`employee/router.py:558-595`) | ✔ |
| `GET/POST /policy-assignments` | `_require_policy_assignment_permission` (both domains when unfiltered) (`organisation/router.py:1318-1333`) | ✔ |
| `POST /work-calendar-changes/{preview,confirm}` | `_require_calendar_change_permission` + per-change-type permission (`:1543-1572`) | ✔ |
| `GET /companies/{company_id}` | service rejects `company_id != tenant.company_id` with 404 (`identity/service.py:330-335`) | ✔ (IDOR-safe) |
| `/leave-types`, `/leave-ledger`, `/leave-balances`, `/leave-applications*` | self-service; combined view scope + `caller_employee_id` (`leave/router.py:578-607`) | ✔ |
| `/regularizations` (create/cancel) | self-service, caller employee from token | ✔ (cancel-by-other not traced) |
| `GET /attendance-periods/{id}/summary` | `_attendance_view_scope` DataScope applied (DEF-B6-02) (`attendance/router.py:1596-1612`) | ✔ |
| `/auth/me`, `/auth/logout` | caller's own | ✔ |

## 4. Authorization design notes
* Permission codes are DB-driven (`permission`, `role_permission.data_scope`); resolved **fresh on every request** so role changes are immediate. Data scope levels: SELF / REPORTEES / BRANCH / COMPANY; empty set fails closed (`core/rbac/service.py`).
* `tests/unit/core/scope_guard_exceptions.toml` pins routes that are permission-gated but ignore scope; currently only `company_level` entries remain (the file also shows 6 uncommitted added lines). Good ratchet.
* `tests/integration/test_route_authorization_matrix.py` exists (not run) — the right control for this class of bug.
* Mass assignment: request bodies are explicit Pydantic models; no `**body.dict()` into ORM seen in sampled routes. Not exhaustively checked.
* Payroll/salary: `/payroll/*` split into SETUP / RUN_VIEW / RUN_PROCESS / RUN_APPROVE / STATUTORY / BANK_ADVICE_DOWNLOAD / PAYSLIP_VIEW_OWN; employee payslips take `employee_id` from the token only. Employee compensation requires `EMPLOYEE_VIEW_COMPENSATION` + scope.
* `GET /payroll/pay-runs/{run}/bank-advice`: permission-gated export of bank details; audit entry on download **not verified**.

## 5. Contract consistency
Uniform envelopes (`DataEnvelope`, `ListEnvelope`, `ResponseMeta` with request id), shared pagination (`bounded_pagination_params`; API_01 report exists), `If-Match` for optimistic concurrency, `Idempotency-Key` + replay marker for write-heavy endpoints, structured error envelope (`core/errors/envelope.py`). Mobile-readiness: stable envelope; versioned prefix `/v1`. Generated API docs are stale (`docs/api/tools/build_api_docs.py` aborts on `GET /metrics` drift, per project notes) — **F-27 P3**.

## 6. Findings
| ID | Sev | Conf. | Finding |
|---|---|---|---|
| F-26 | P3 | confirmed | `GET /ingestion/health` unauthenticated and unclear ownership; remove or gate. |
| F-27 | P3 | confirmed | Generated API docs generator broken → clients may rely on stale docs. |
| F-28 | P2 | unverified | Rate limits on forgot/reset/verify/resend/registration/public-onboarding not traced; confirm each has a bucket. |
| F-29 | P2 | unverified | Large list endpoints: pagination is standard, but unbounded exports/CSV (bank advice, employee import template/results) not checked for size caps. |
