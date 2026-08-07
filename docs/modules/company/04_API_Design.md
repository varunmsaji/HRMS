# Company Module — API Design

Conforms to `docs/product/09_API_Standards.md`: base path `/v1`, envelopes (`DataEnvelope<T>` / `ListEnvelope<T>` / `ErrorEnvelope`), `X-Company-Id` + `Authorization: Bearer` on every authenticated request, `If-Match`/`version` optimistic concurrency on mutations, cross-tenant access → `404` never `403`.

**No `{id}` path parameters anywhere in this API.** Every endpoint operates on "the current company" — resolved server-side from the authenticated user's JWT + `X-Company-Id` via the existing `get_tenant_context` dependency, never from a client-supplied company id. This is a deliberate simplification enabled by [03_Database_Design.md §2.3](03_Database_Design.md#23-why-no-company_id--rls): since `company` has no RLS policy of its own, keeping company-scoped writes off any `{id}`-shaped route removes an entire class of IDOR risk by construction rather than by relying on a check.

---

## 1. Endpoint Catalogue

| Method | Path | Auth | Permission | Purpose |
|---|---|---|---|---|
| `POST` | `/v1/companies/register` | Public | — | Self-service tenant creation |
| `GET` | `/v1/companies/current` | Required | `ORG.COMPANY.MANAGE` | Read company profile + settings |
| `PATCH` | `/v1/companies/current` | Required | `ORG.COMPANY.MANAGE` | Update company profile + settings |
| `GET` | `/v1/companies/current/setup-progress` | Required | `ORG.COMPANY.MANAGE` | Read onboarding completion state |
| `GET` | `/v1/companies/current/subscription` | Required | `ORG.COMPANY.MANAGE` | Read plan + subscription + effective feature flags |
| `GET` | `/v1/dashboards/company` | Required | `DASHBOARD.COMPANY.VIEW` | Read-only aggregation for the Company Admin dashboard |

Every response is `DataEnvelope<T>` (all six endpoints return a single object, never a collection — `company`, `company_setup_progress`, and `subscription` are singleton resources per tenant, so no `ListEnvelope`/pagination/filtering/sorting applies anywhere in this API, per `docs/product/09` §1.5's own scoping of list conventions to actual collections).

---

## 2. `POST /v1/companies/register`

Public, unauthenticated. No `Depends(require_permission(...))` — still runs through the standard exception handlers (`docs/product/09_API_Standards.md` conventions apply to error shape even on public routes).

**Request** (`CompanyRegistrationRequest`):

```json
{
  "name": "Acme Manufacturing Pvt Ltd",
  "industry_code": "MANUFACTURING",
  "country_code": "IN",
  "currency": "INR",
  "timezone": "Asia/Kolkata",
  "fy_start_month": 4,
  "company_size": "51-200",
  "admin_first_name": "Priya",
  "admin_last_name": "Sharma",
  "admin_email": "priya@acme.example",
  "admin_password": "•••••••••"
}
```

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | 1–200 chars |
| `industry_code` | No | |
| `country_code` | No | Defaults `IN` |
| `currency` | No | Defaults `INR`; must be a valid ISO 4217 code |
| `timezone` | No | Defaults `Asia/Kolkata`; must be a valid IANA name |
| `fy_start_month` | No | Defaults `4`; 1–12 |
| `company_size` | No | One of the bands in [02_Domain_Model.md §4.5](02_Domain_Model.md#4-enums) |
| `admin_first_name`, `admin_last_name` | Yes | |
| `admin_email` | Yes | Valid email, becomes the admin `User.email` |
| `admin_password` | Yes | Subject to the platform's password-strength policy (owned by `core/auth`, not redefined here) |

**Behaviour:** transactional creation of `User` (admin), `Company`, `UserCompany` (`is_primary=true`), a company-scoped `Role` (`code=COMPANY_ADMIN`, `is_system=true`) granted `ORG.COMPANY.MANAGE` + `DASHBOARD.COMPANY.VIEW`, `RolePermission`, `UserRole`, an initial `CompanySetupProgress` row (`status=IN_PROGRESS`), and (if a default trial plan exists) a `Subscription` row (`status=TRIALING`). Audited as `AuditService.record(action="COMPANY_REGISTERED", entity_type="company", entity_id=company.id)`. Delegates token issuance to `identity` module's existing logic — never re-implements JWT signing (`docs/architecture/02_Module_Standard.md` §2 cross-module rule: import `identity.service`, not its internals).

**Response `201`** — identical shape to `POST /v1/auth/login`'s success response (`DataEnvelope<TokenResponseData>`): access token, refresh cookie set, `companies: [{id, name, status}]`.

**Errors:**

| Status | Code | Cause |
|---|---|---|
| `409` | `CONFLICT` | `subdomain` (if client-supplied) or a uniqueness rule already taken |
| `422` | `VALIDATION_ERROR` | Weak password (`details[].field = "admin_password"`), invalid `timezone`/`currency`/`fy_start_month`, missing required field |

---

## 3. `GET /v1/companies/current`

**Response `200`** (`DataEnvelope<CompanyProfile>`):

```json
{
  "data": {
    "id": "…",
    "name": "Acme Manufacturing Pvt Ltd",
    "legal_name": "Acme Manufacturing Private Limited",
    "registration_number": "U29100MH2010PTC123456",
    "subdomain": "acme",
    "contact": { "email": "info@acme.example", "phone": "+91-…", "website": "https://acme.example" },
    "address": { "line1": "…", "line2": null, "city": "Pune", "state": "Maharashtra", "postal_code": "411001", "country_code": "IN" },
    "industry_code": "MANUFACTURING",
    "company_size": "51-200",
    "country_code": "IN",
    "currency": "INR",
    "timezone": "Asia/Kolkata",
    "locale": { "language_code": "en-IN", "date_format": "DD/MM/YYYY" },
    "fiscal_year": { "start_month": 4 },
    "working_days": [ { "day": "MON", "is_working": true, "is_alternate": false }, "…" ],
    "business_hours": { "start_time": "09:00", "end_time": "18:00" },
    "branding": { "logo_url": "https://…", "theme": { "primary_color": "#4F46E5" } },
    "status": "ACTIVE",
    "primary_legal_entity": null,
    "onboarded_at": "2026-08-01T09:12:00Z",
    "trial_ends_at": null,
    "version": 3
  },
  "meta": { "request_id": "…", "server_time": "…" }
}
```

`primary_legal_entity` is always `null` until the Legal Entity sub-domain exists ([02_Domain_Model.md §6](02_Domain_Model.md#6-primary-legal-entity-read-through-not-owned)) — an honest empty state, not an error.

**Errors:** `401` (no/invalid token), `404` (should not occur for an authenticated user with valid tenant membership — would indicate a data-integrity bug, not a normal client error).

---

## 4. `PATCH /v1/companies/current`

Partial update. Requires `If-Match: "<version>"` header (repository-wide optimistic-locking convention).

**Request** — any subset of the writable fields shown in §3's response except `id`, `status`, `subdomain` (immutable post-registration in V1 — changing a live tenant's URL slug is a deliberately separate, higher-friction operation not exposed here), `primary_legal_entity` (read-only, sourced elsewhere), `version` (managed by `If-Match`).

```json
{ "timezone": "Asia/Kolkata", "business_hours": { "start_time": "09:30", "end_time": "18:30" } }
```

**Value-object replacement rule:** per [02_Domain_Model.md §3](02_Domain_Model.md#3-value-objects), a value object field (`contact`, `address`, `locale`, `fiscal_year`, `working_days`, `business_hours`, `branding`) is replaced as a whole when present in the request body — the client must send the complete object, not a sub-field patch of it. Omitting the key entirely leaves it unchanged.

**Response `200`** — same shape as §3, reflecting the update.

**Errors:**

| Status | Code | Cause |
|---|---|---|
| `409` | `STALE_RESOURCE` | `If-Match` doesn't match current `version` |
| `422` | `VALIDATION_ERROR` | Any rule in [02_Domain_Model.md §5](02_Domain_Model.md#5-validation-rules--business-invariants) — e.g. `currency` change attempted while `status != TRIAL` (field `currency`, code `CURRENCY_LOCKED`), zero working days, `business_hours.end_time <= start_time` |
| `423` | `LOCKED` | Reserved for the timezone-change-during-open-payroll-period guard once Payroll exists ([02_Domain_Model.md §5.5](02_Domain_Model.md#5-validation-rules--business-invariants)) — not reachable in V1 since no dependent module exists yet |

Every successful update is audited (`AuditService.record(action="UPDATED", entity_type="company", before_json, after_json)`).

---

## 5. `GET /v1/companies/current/setup-progress`

**Response `200`** (`DataEnvelope<CompanySetupProgressSummary>`):

```json
{
  "data": {
    "status": "IN_PROGRESS",
    "current_step": "BRANCHES",
    "steps": [
      { "code": "COMPANY_PROFILE", "label": "Company Profile", "is_complete": true },
      { "code": "BRANCHES", "label": "Branches", "is_complete": false }
    ],
    "started_at": "…",
    "completed_at": null
  },
  "meta": { "request_id": "…" }
}
```

The `steps[]` list itself is a fixed, versioned catalogue (which steps exist, and what "complete" means for each) — Company owns the catalogue and the aggregation endpoint, but each step's completion predicate is answered by querying the owning sub-domain's row count, never by Company reaching into that sub-domain's business rules (see [05_Backend_Architecture.md](05_Backend_Architecture.md)). In this module's initial delivery (before sibling sub-domains exist), only the `COMPANY_PROFILE` step is meaningful — implicitly complete once registration finishes — and the catalogue is designed to extend without a contract change as sibling steps land.

**Errors:** `401`. No `404`/`409` — this resource always exists once a company does (created at registration).

---

## 6. `GET /v1/companies/current/subscription`

**Response `200`** (`DataEnvelope<SubscriptionSummary>`):

```json
{
  "data": {
    "plan": { "code": "STANDARD", "name": "Standard" },
    "status": "TRIALING",
    "current_period_start": null,
    "current_period_end": null,
    "trial_ends_at": "2026-08-21T00:00:00Z",
    "seat_limit": 200,
    "features": [
      { "code": "AI_RESUME_PARSING", "is_enabled": false, "source": "PLAN" },
      { "code": "BETA_PAYROLL_V2", "is_enabled": true, "source": "COMPANY_OVERRIDE" }
    ]
  },
  "meta": { "request_id": "…" }
}
```

`features[].source` tells the client whether a flag's effective value came from the plan or a company-level override (`overrides_plan = true` row) — resolution logic lives in `CompanyService`, never duplicated client-side.

**Write access to feature flags is not exposed in V1.** Per [02_Domain_Model.md §5.10](02_Domain_Model.md#5-validation-rules--business-invariants), an `overrides_plan=true` flag is a negotiated/beta-access mechanism gated by a platform-level permission (`PLATFORM.FEATURE_FLAG.MANAGE`) that has no seeded role or admin surface yet ([01_Company_Module_Overview.md §5](01_Company_Module_Overview.md#5-future-extensions)). This endpoint is read-only until that surface exists; the contract is designed so adding `PATCH /v1/companies/current/feature-flags/{feature_code}` later is additive, not a breaking change.

---

## 7. `GET /v1/dashboards/company`

**Response `200`** (`DataEnvelope<CompanyDashboardSummary>`):

```json
{
  "data": {
    "setup_progress": { "status": "IN_PROGRESS", "steps_completed": 1, "steps_total": 9 },
    "subscription": { "plan_code": "STANDARD", "status": "TRIALING", "trial_ends_at": "…" },
    "branch_count": null,
    "department_count": null,
    "employee_count": null
  },
  "meta": { "request_id": "…" }
}
```

Count fields for sub-domains that don't exist yet in this module's delivery are `null` (not `0`) — distinct from Sprint 3's precedent of returning `employee_count: 0` for an *existing-but-empty* table. `null` here means "the counting module doesn't exist yet," `0` would incorrectly imply "it exists and has no rows." Once a sibling sub-domain ships, its count field switches from `null` to a real integer — additive, non-breaking. This mirrors the same forward-compatible-contract principle Sprint 3 documents for `employee_count`.

---

## 8. Validation Summary

| Rule | Enforced at | Error shape |
|---|---|---|
| Required fields, string lengths, enum membership | Pydantic schema (`schemas.py`) | `422` `VALIDATION_ERROR`, `details[].field` |
| `currency` immutable post-`TRIAL` | Service | `422`, `details[].field="currency"`, `details[].code="CURRENCY_LOCKED"` |
| `timezone` valid IANA name | Schema (format validator) | `422`, `details[].field="timezone"` |
| Working days ≥ 1 | Service | `422`, `details[].field="working_days"` |
| `business_hours.end_time > start_time` | Schema/service | `422`, `details[].field="business_hours"` |
| `subdomain` uniqueness | Service (DB constraint as backstop) | `409` `CONFLICT` |
| `version` match on `PATCH` | Service (`WHERE version = :expected`) | `409` `STALE_RESOURCE` |
| Permission present | `Depends(require_permission(...))` | `403` `PERMISSION_DENIED` |
| Tenant membership resolves | `get_tenant_context` | `404` `NOT_FOUND` (never `403`) |

## 9. Pagination, Filtering, Versioning

- **Pagination/filtering:** not applicable — every resource in this API is a per-tenant singleton (`docs/product/09` §1.5 conventions govern collections; none exist here).
- **Versioning:** `/v1` prefix per repository convention. Any breaking change (e.g. splitting `address` into a separate endpoint) ships as `/v2`; additive changes (new optional field, the future feature-flag write endpoint) stay in `/v1` (`docs/product/09_API_Standards.md` §7).
