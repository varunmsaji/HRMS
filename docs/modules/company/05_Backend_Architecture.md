# Company Module — Backend Architecture

Conforms to `docs/architecture/02_Module_Standard.md` (file layout, layer rules, naming) and `docs/architecture/01_Backend_Structure.md` (package placement). Physical package: `apps/api/src/hrms/modules/organisation/` — already decided, not reopened here ([01_Company_Module_Overview.md §3](01_Company_Module_Overview.md#3-boundaries)). This document describes only the **Company-owned slice** of that package's files; sibling sub-domains (Branch, Department, …) add to the same files later without renaming or restructuring what's specified here.

---

## 1. File-by-file ownership

| File | Company's contribution |
|---|---|
| `router.py` | `POST /companies/register`, `GET/PATCH /companies/current`, `GET /companies/current/setup-progress`, `GET /companies/current/subscription`, `GET /dashboards/company` |
| `service.py` | `OrganisationService` class (one class per module, per `02_Module_Standard.md` §6) — Company-owned methods listed in §3 below |
| `repository.py` | `OrganisationRepository` class — Company-owned query methods, §4 below |
| `models.py` | `CompanySetupProgress`, `Subscription`, `CompanyFeatureFlag`, `Plan`, `PlanFeature` — **not** `Company` itself, which stays in `hrms/core/db/models/identity.py` (existing precedent from `SPRINT_3_COMPANY_FOUNDATION.md` Task 2.1.1 — `Company` is identity-adjacent core data, referenced by every module, and moving it would be a bigger churn than this module's scope justifies) |
| `schemas.py` | `CompanyRegistrationRequest`, `CompanyProfileRead`, `CompanyProfileUpdate`, `CompanySetupProgressSummary`, `SubscriptionSummary`, `CompanyDashboardSummary`, plus the embedded value-object schemas (`AddressSchema`, `ContactInfoSchema`, `LocaleSchema`, `FiscalYearSchema`, `WorkingDaysPatternSchema`, `BusinessHoursSchema`, `BrandingSchema`) |
| `permissions.py` | `ORG_COMPANY_MANAGE = "ORG.COMPANY.MANAGE"` (see §6 — migrated from `identity/permissions.py`), `DASHBOARD_COMPANY_VIEW = "DASHBOARD.COMPANY.VIEW"` (new) |
| `dependencies.py` | `get_organisation_service(session: Depends(get_session)) -> OrganisationService` |
| `exceptions.py` | Company-specific `AppError` subclasses — §7 |
| `events.py` | `CompanyRegistered`, `CompanyProfileUpdated` — §5 |
| `tasks.py` | `organisation.sweep_trial_expirations` — §5 |

`__init__.py` — empty, per `health`/`identity` precedent.

No `models/` sub-package split — five new Company-owned model classes plus sibling sub-domains' future tables stay well under the "split past 15 tables" threshold (`02_Module_Standard.md` §1) for the foreseeable Sprint 3 scope; revisit if the whole `organisation` package's table count approaches that number.

---

## 2. Router (thin — one service call per route)

Per `02_Module_Standard.md` §2, `router.py` parses the request, calls exactly one `OrganisationService` method, and returns a schema — no business logic, no direct ORM access, no catching domain errors (that's `core/errors/handlers.py`'s job, registered globally).

```python
@router.patch("/companies/current")
async def update_company_profile(
    body: CompanyProfileUpdate,
    if_match: Annotated[str, Header(alias="If-Match")],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _: Annotated[DataScope, Depends(require_permission(ORG_COMPANY_MANAGE))],
) -> DataEnvelope[CompanyProfileRead]:
    result = await service.update_company_profile(tenant.company_id, body, expected_version=int(if_match))
    return DataEnvelope(data=result, meta=build_meta(current_request_id() or "unknown"))
```

`POST /companies/register` is the one route in this file with **no** `require_permission` dependency and **no** `get_tenant_context` dependency (there is no tenant yet) — it still returns through the standard envelope and error handlers.

---

## 3. Service — `OrganisationService` (Company-owned methods)

One class, per the repository-wide "one public service class per module" convention (mirrors `IdentityService`, `LeaveService` in `02_Module_Standard.md` §4). Company's methods:

| Method | Responsibility |
|---|---|
| `register_company(request) -> TokenResponseData` | Orchestrates the full registration transaction (§5.1) |
| `get_company_profile(company_id) -> CompanyProfileRead` | Read, including the `primary_legal_entity` read-through resolution ([02_Domain_Model.md §6](02_Domain_Model.md#6-primary-legal-entity-read-through-not-owned)) |
| `update_company_profile(company_id, patch, expected_version) -> CompanyProfileRead` | Validates every invariant in [02_Domain_Model.md §5](02_Domain_Model.md#5-validation-rules--business-invariants), applies optimistic locking, audits, emits `CompanyProfileUpdated` |
| `get_setup_progress(company_id) -> CompanySetupProgressSummary` | Recomputes `steps_completed` by querying each step's owning repository method (own, for now just `COMPANY_PROFILE`; sibling sub-domains register their own step predicate later — see §3.1) |
| `get_subscription_summary(company_id) -> SubscriptionSummary` | Resolves effective feature set: plan features + company overrides, per [02_Domain_Model.md §5.10](02_Domain_Model.md#5-validation-rules--business-invariants) |
| `get_dashboard_summary(company_id) -> CompanyDashboardSummary` | Read-only aggregation — cheap indexed `COUNT(*)` per available sub-domain table, `null` for tables that don't exist yet ([04_API_Design.md §7](04_API_Design.md#7-get-v1dashboardscompany)) |
| `transition_status(company_id, target_status, reason)` | Internal — enforces the state machine in [02_Domain_Model.md §7.1](02_Domain_Model.md#71-companystatus-state-machine); not directly exposed via a public route in V1 (no admin UI to call it from yet), but implemented as a named method so the platform-admin surface can call it later without a new code path |

**No business logic in the router; no SQL in the service** — the service calls `OrganisationRepository` for all persistence and calls `identity.service` for token issuance (`await self._identity.issue_tokens_for(user_id, company_id)` — public method, not the private `_issue_tokens`; if `IdentityService` doesn't yet expose a public wrapper, extracting one is part of this module's backlog, not a reason to reach into a private method across modules).

### 3.1 Setup-step registry (extensibility point)

`get_setup_progress` does not hardcode nine `if/elif` branches. It iterates a small, explicit registry:

```python
SETUP_STEPS: list[SetupStepDefinition] = [
    SetupStepDefinition(code="COMPANY_PROFILE", label="Company Profile", check=lambda repo, cid: repo.company_profile_is_complete(cid)),
    # Sibling sub-domains append their own entries here when they ship —
    # e.g. SetupStepDefinition(code="BRANCHES", label="Branches", check=lambda repo, cid: repo.branch_count(cid) > 0)
]
```

Company owns the registry and the aggregation loop; it does **not** own the predicate logic for a sibling step once that sibling exists (`repo.branch_count` would live in a Branch-owned repository method, called via composition, not duplicated). This keeps the "derived, never a client-trusted flag" rule (`SPRINT_3_COMPANY_FOUNDATION.md` D9, carried forward in [02_Domain_Model.md §2.2](02_Domain_Model.md#22-companysetupprogress)) intact as the module grows.

---

## 4. Repository — `OrganisationRepository` (Company-owned methods)

Per `02_Module_Standard.md` §2, every query carries an explicit `company_id` predicate (RLS is the backstop, not the only line of defence — `docs/adr/0002-postgres-rls-multitenancy.md`). Company-owned methods:

- `insert_company(session, *, data) -> Company`
- `get_company(session, *, company_id) -> Company`
- `update_company(session, *, company_id, patch, expected_version) -> Company` — the `UPDATE ... WHERE id = :id AND version = :expected_version` pattern that backs optimistic locking at the repository layer, not merely checked in the service (`docs/product/09_API_Standards.md` §1.4 concurrency note).
- `subdomain_exists(session, *, subdomain) -> bool`
- `insert_setup_progress(session, *, company_id) -> CompanySetupProgress`
- `get_setup_progress(session, *, company_id) -> CompanySetupProgress`
- `update_setup_progress(session, *, company_id, steps_completed, status) -> CompanySetupProgress`
- `company_profile_is_complete(session, *, company_id) -> bool`
- `get_active_subscription(session, *, company_id) -> Subscription | None`
- `insert_subscription(session, *, company_id, plan_id, status) -> Subscription`
- `get_plan_features(session, *, plan_id) -> list[PlanFeature]`
- `get_company_feature_flags(session, *, company_id) -> list[CompanyFeatureFlag]`
- `count_trials_expiring_before(session, *, cutoff) -> list[Company]` — used by the background task in §5.2

`repository.py` never imports `schemas.py` and never returns anything but ORM rows/scalars (`02_Module_Standard.md` §2 layer table) — mapping to Pydantic response models happens in `service.py`.

---

## 5. Domain Events & Background Tasks

### 5.1 Registration is synchronous, not a task

`register_company` runs entirely inside the request/response cycle — the brief's own acceptance bar ("a single `POST` call results in a fully working, immediately-authenticated tenant with zero manual follow-up") rules out any async/queued step in the critical path. No Celery task is involved in registration itself.

### 5.2 `organisation.sweep_trial_expirations` (Celery Beat, daily)

Scans `company` for `status = 'TRIAL' AND trial_ends_at < now()` (via `count_trials_expiring_before`) and transitions each to `TERMINATED` through `OrganisationService.transition_status`, audited per-row. Idempotent by construction — re-running the sweep against an already-transitioned company is a no-op (`WHERE status = 'TRIAL'` in the query means a second run finds nothing to do), satisfying the repository-wide "all jobs idempotent, resumable" rule (`docs/development/AI_Coding_Guidelines.md`, ADR-0012 consequences).

`trial_ends_at` is an absolute `TIMESTAMPTZ`, not a per-tenant local-calendar-day boundary — unlike attendance/payroll jobs, this sweep does **not** need per-company-timezone-aware scheduling (ADR-0010's "business-day boundary" concern doesn't apply to a fixed instant). One global daily run is correct.

### 5.3 Domain events (`events.py`)

`CompanyRegistered` and `CompanyProfileUpdated` are declared as domain events in `organisation/events.py` (past-tense PascalCase, per `02_Module_Standard.md` §6 naming table), emitted by `service.py` at the end of `register_company`/`update_company_profile`.

ADR-0012's outbox pattern is scoped explicitly to events that "touch money or compliance" (its own named examples: `LeaveApproved`, `PayRunFinalised`, `ExitFinalised`). `CompanyRegistered` is not itself a money/compliance event, but per [01_Company_Module_Overview.md §4](01_Company_Module_Overview.md#4-dependencies), it is the root trigger every other module's onboarding chain eventually hangs off (welcome email, default seed data, future billing hooks). This design follows the conservative reading recommended during research for this doc set: **persist `CompanyRegistered` via the outbox table in the same transaction as the Company insert**, relayed to the queue afterward, consumers idempotent — the same mechanism ADR-0012 already mandates for its named events, extended here by analogy rather than by a literal rule match. `CompanyProfileUpdated` (and a future `CompanyTimezoneChanged`, `CompanyStatusChanged`) follow the same treatment, since a stale/duplicated timezone-change notification is exactly the kind of bug the outbox pattern exists to prevent. No consumer subscribes to either event in this module's V1 delivery — they are emitted, durably, for future modules to subscribe to without a schema change.

---

## 6. Permission Code Ownership — a migration decision

`ORG.COMPANY.MANAGE` already exists, declared in `hrms/modules/identity/permissions.py` (live code, confirmed), unused by any router today. This design moves its declaration to `organisation/permissions.py` (correct module ownership, per `02_Module_Standard.md`) as part of building this module — the **string value never changes**, so no re-seed or role-grant migration is needed, only the Python constant's location. `identity/permissions.py` keeps its own genuinely identity-owned codes (`SETTINGS.USER.MANAGE`, `SETTINGS.ROLE.MANAGE`, `EMPLOYEE.VIEW`).

`DASHBOARD.COMPANY.VIEW` is new, declared directly in `organisation/permissions.py`, seeded and granted to `COMPANY_ADMIN` at registration time (§3, `register_company`).

---

## 7. Exceptions

`identity/permissions.py`'s sibling module skips a dedicated `exceptions.py` today, relying entirely on `core/errors`' generic subclasses (`ConflictError`, `ValidationError`). Company introduces enough distinct, recurring domain errors that generic subclasses would blur what actually went wrong in logs/monitoring, so `organisation/exceptions.py` is added — still `AppError` subclasses, still mapped automatically by the existing global handler, no new handler-registration code needed:

```python
class SubdomainTakenError(ConflictError):
    code = "SUBDOMAIN_TAKEN"

class CurrencyLockedError(ValidationError):
    code = "CURRENCY_LOCKED"

class InvalidWorkingDaysError(ValidationError):
    code = "INVALID_WORKING_DAYS"
```

These carry the specific `code` values referenced in [04_API_Design.md §8](04_API_Design.md#8-validation-summary) — the router/handler layer needs no changes; `core/errors/handlers.py` already maps any `AppError` subclass by its declared `status_code`.

## 8. Caching

`CompanyService`'s settings (`timezone`, `currency`, `locale`, `fiscal_year`) are read on a very large fraction of requests across every other module ([01_Company_Module_Overview.md §4](01_Company_Module_Overview.md#4-dependencies)) but change rarely. Cache-aside pattern, mirroring the precedent already documented for the RBAC permission-bitmap cache (`docs/security/Auth_Architecture.md` §4):

- Key: `company:settings:{company_id}`, value: the small settings subset other modules actually consume (not the full profile — no need to cache `theme_json`/branding for hot-path reads).
- Redis, short TTL (e.g. 5 minutes) as a safety net **plus** explicit invalidation (`DEL company:settings:{company_id}`) on every successful `update_company_profile` — cache correctness must not depend on TTL alone, since a stale `timezone` read could misalign an attendance/payroll boundary computation the moment those modules exist.
- `get_dashboard_summary` and `get_setup_progress` are **not** cached — both are read-infrequently (dashboard/setup screens, not hot-path) and must always reflect current derived state per their own "never a client-trusted flag" rule.

---

## 9. Logging

Structured logging (`structlog`, existing `core/observability` convention) with `request_id` and `company_id` bound to every log line inside a request — already provided by the tenancy middleware's context, nothing Company-specific to add beyond emitting one structured log line per state transition (`status` changes, trial expiry) at `info` level, and one at `warning` for rejected invariant violations (e.g. attempted currency change) to make abuse patterns visible without needing a DB query.

## 10. Audit

Every mutation calls `AuditService.record(...)`, `entity_type="company"` (or `"subscription"` / `"company_feature_flag"` for those tables):

| Action | `action` value | Trigger |
|---|---|---|
| Registration | `COMPANY_REGISTERED` | `register_company` |
| Profile update | `UPDATED` | `update_company_profile`, with full `before_json`/`after_json` |
| Status transition | `UPDATED` (with `context.from_status`/`context.to_status` in the audit row, or a dedicated `STATUS_CHANGED` action — pick one and apply consistently; `STATUS_CHANGED` is recommended since it's queried differently than a field-level profile edit) | `transition_status` |

## 11. Transactions

- **Registration** is one database transaction: insert `User` → insert `Company` (referencing the just-inserted `User.id` as `created_by`, per [03_Database_Design.md §2.2](03_Database_Design.md#22-new-columns-added-by-this-design) — insert order matters) → insert `UserCompany` → insert `Role`/`RolePermission`/`UserRole` → insert `CompanySetupProgress` → insert `Subscription` (if a default trial plan is configured) → `AuditService.record`. Any failure rolls back the entire transaction — there is no partially-created tenant, ever.
- **Profile update** is one row, one transaction, optimistic-locked (`WHERE id = :id AND version = :expected_version`) — a `0`-row-affected result is what the repository translates into `ConflictError` → `409 STALE_RESOURCE`, not a separate `SELECT`-then-compare race-prone check.
- Session lifetime follows the existing "one session per request" rule (`docs/product/08_Database_Architecture.md` §15) — required for the RLS `SET LOCAL app.company_id` scoping to be correct, even though `company` itself has no RLS policy (other tables touched in the same transaction, like `role_permission`, do rely on it via join).

## 12. Error Handling

No new global error-handling mechanism — Company-specific errors are `AppError` subclasses (§7 above) mapped automatically by the existing `core/errors/handlers.py` global handler, exactly like every other module. Router code never builds an error response by hand.
