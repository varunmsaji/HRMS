# Company Module — Domain Model

Companion to [01_Company_Module_Overview.md](01_Company_Module_Overview.md). This is a logical domain model — physical column types and indexes are in [03_Database_Design.md](03_Database_Design.md).

---

## 1. Aggregate

```
Company (aggregate root)
 ├── CompanySetupProgress   (1:1 — lifecycle bound to Company)
 ├── Subscription           (1:0..1 active — lifecycle bound to Company)
 └── CompanyFeatureFlag     (1:0..N — lifecycle bound to Company)
```

**Rule:** all writes to `CompanySetupProgress`, `Subscription`, and `CompanyFeatureFlag` happen through `CompanyService` in the same transaction boundary as the Company they belong to conceptually own. No other module ever writes these tables directly.

**Explicitly not part of this aggregate** (separate aggregates referencing `company_id`, owned by sibling sub-domains of the same `organisation` package or by other modules entirely — see [01_Company_Module_Overview.md §2](01_Company_Module_Overview.md#2-responsibilities)): `LegalEntity`, `Branch`, `Department`, `Designation`, `Grade`, `EmploymentType`, `HolidayCalendar`, `Shift`, `LeavePolicy`, `PayrollPolicy`, `NumberSeries`, `Employee`, and everything downstream of Employee.

**Reference/global data, not tenant-scoped, read by this aggregate:** `Plan`, `PlanFeature` — a catalogue every company's `Subscription` points into. These are platform-managed master data (own lifecycle, own future admin surface), not owned by any one company.

---

## 2. Entities

### 2.1 `Company` — the aggregate root

The tenant itself. Exactly one row identifies one tenant; `Company.id` **is** the tenant id used throughout the system as `company_id`.

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | Tenant identity |
| `name` | string | Trading/display name |
| `legal_name` | string, optional | |
| `registration_number` | string, optional | Generic business registration id — see [Overview §6](01_Company_Module_Overview.md#6-domain-ownership) for why this is not GSTIN/PAN |
| `subdomain` | string, unique, optional | Tenant URL slug |
| `contact` | value object — see §3.3 | Email, phone, website |
| `address` | value object — see §3.1 | Primary/registered business address |
| `industry_code` | string, optional | References an industry lookup (not modelled by this module) |
| `company_size` | enum — see §4.5 | Headcount band, self-declared at registration, informational only (not the live employee count) |
| `country_code` | ISO 3166-1 alpha-2 | Drives default currency/locale/timezone at registration |
| `currency` | ISO 4217 alpha-3 | Tenant-default currency — see invariant §5.4 |
| `timezone` | IANA tz name | Business-day boundary source for the whole tenant (ADR-0010) — see invariant §5.5 |
| `locale` | value object — see §3.4 | Language + date format |
| `fiscal_year` | value object — see §3.2 | Start month |
| `working_days` | value object — see §3.5 | Company-wide default week pattern |
| `business_hours` | value object — see §3.6, optional | Company-wide default |
| `branding` | value object — see §3.7 | Logo + theme |
| `status` | enum — see §4.1 | Lifecycle state |
| `data_region` | string, optional | Data residency marker — enforcement is infra-layer, not this module's (see Overview §5) |
| `onboarded_at` | timestamp, optional | Set when setup progress first reaches `COMPLETE` |
| `trial_ends_at` | timestamp, optional | |

### 2.2 `CompanySetupProgress`

One row per company. Tracks onboarding completion **as derived state**, never a client-trusted flag (binding rule carried forward from `SPRINT_3_COMPANY_FOUNDATION.md` D9 — see [Overview](01_Company_Module_Overview.md), applies unchanged to this narrower Company-only design).

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `company_id` | UUID, unique | One row per company |
| `steps_completed` | set of step codes | Derived by counting rows in the owning module's table for each step — Company does not decide *how* a step completes, it only aggregates the answer |
| `current_step` | step code, optional | Last step the user was on — UX hint only, never gates access |
| `status` | enum — see §4.2 | |
| `started_at` | timestamp | |
| `completed_at` | timestamp, optional | |

### 2.3 `Subscription`

At most one **non-terminal** subscription per company.

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `company_id` | UUID | |
| `plan_id` | UUID | FK to `Plan` (reference data) |
| `status` | enum — see §4.3 | |
| `current_period_start` / `current_period_end` | timestamp | |
| `trial_ends_at` | timestamp, optional | Mirrors `Company.trial_ends_at` at subscription grant time — see invariant §5.9 |
| `canceled_at` | timestamp, optional | |
| `seat_limit_override` | integer, optional | Overrides the plan's default seat/employee limit for a negotiated deal |

### 2.4 `CompanyFeatureFlag`

Company-specific feature toggles layered on top of the plan's feature set.

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `company_id` | UUID | |
| `feature_code` | string | e.g. `AI_RESUME_PARSING`, `BETA_PAYROLL_V2` |
| `is_enabled` | boolean | |
| `overrides_plan` | boolean | If true, this flag is honoured even when the plan doesn't include `feature_code` (negotiated/beta access) — see invariant §5.10 |
| `value` | JSON, optional | For flags that carry a config payload rather than a plain on/off |

### 2.5 `Plan` / `PlanFeature` (reference data, not tenant-scoped)

| Entity | Purpose |
|---|---|
| `Plan` | `code`, `name`, `description`, `is_active` — the sellable catalogue |
| `PlanFeature` | `plan_id`, `feature_code`, `is_enabled`, `limit_value` (optional numeric, e.g. max employees) — what a plan includes |

Ownership note: these are platform/catalogue data, not written by the Company module's tenant-facing endpoints. Company only *reads* them (to resolve effective feature flags) and *references* them (via `Subscription.plan_id`). A platform-admin surface to manage `Plan`/`PlanFeature` is future scope (Overview §5).

---

## 3. Value Objects

Value objects have no independent identity or lifecycle — they are embedded in `Company` and replaced wholesale on update, never partially mutated field-by-field at the domain layer (the API may accept partial JSON, but the service reconstructs the whole value object before persisting).

### 3.1 `Address`
`line1`, `line2` (optional), `city`, `state`, `postal_code`, `country_code`. All optional at the domain level (a company can register before it has a finalized office address); the API layer may require completeness before allowing `status` to leave `TRIAL`.

### 3.2 `FiscalYear`
`start_month` (1–12). Derives the current fiscal year label and boundaries; consumed by Payroll/Leave for period alignment (see Overview §4).

### 3.3 `ContactInfo`
`email`, `phone` (optional), `website` (optional). `email` is distinct from any user's login email — this is the company's published contact address.

### 3.4 `Locale`
`language_code` (BCP-47, e.g. `en-IN`), `date_format` (e.g. `DD/MM/YYYY`). Number/currency formatting is derived from `language_code` + `Company.currency` at render time by clients — not a separate stored field.

### 3.5 `WorkingDaysPattern`
A set of `{day_of_week, is_working, is_alternate}` entries covering Monday–Sunday, supporting the common Indian "1st/3rd Saturday off" pattern via `is_alternate`. This is the **company-wide default**; Branches/Shifts (separate sub-domain) may override it per location — Company never reads those overrides back.

### 3.6 `BusinessHours`
`start_time`, `end_time` (both local to `Company.timezone`), optional. Company-wide default; Shift (separate sub-domain) is the actual scheduling unit and may override.

### 3.7 `Branding`
`logo_url` (optional), `theme` (optional structured payload — primary color, accent color; free-form beyond that, consumed by frontend white-labelling, not validated beyond "is well-formed JSON" at this layer).

---

## 4. Enums

All enums follow the repository-wide convention (`docs/product/08` Global Design Rule #4): **`VARCHAR` + `CHECK` constraint backed by a Python `StrEnum`**, never a native PostgreSQL `ENUM` type, because these values are expected to grow (e.g. a new `Subscription.status`) without a blocking migration.

### 4.1 `CompanyStatus`
`TRIAL` → `ACTIVE` → `SUSPENDED` ⇄ `ACTIVE` → `TERMINATED` (terminal). See lifecycle §7.1.

### 4.2 `SetupProgressStatus`
`IN_PROGRESS`, `COMPLETE`.

### 4.3 `SubscriptionStatus`
`TRIALING`, `ACTIVE`, `PAST_DUE`, `CANCELED`, `EXPIRED`.

### 4.4 `DayOfWeek`
`MON`..`SUN` (used inside `WorkingDaysPattern`).

### 4.5 `CompanySizeBand`
`1-10`, `11-50`, `51-200`, `201-500`, `501-1000`, `1000+` — self-declared at registration, purely informational (segments onboarding UX/sales, never gates behaviour; the live employee count is Employee module's job, surfaced separately on the Company Dashboard per Overview §2).

---

## 5. Validation Rules & Business Invariants

1. **`name`** — required, 1–200 characters.
2. **`subdomain`** — if set, unique across all companies (including soft-deleted, i.e. no re-use of a terminated tenant's subdomain without an explicit release step); lowercase alphanumeric + hyphen, 3–63 characters; may not match a reserved word list (`www`, `api`, `app`, `admin`, `mail`, `assets`).
3. **`fiscal_year.start_month`** — integer 1–12.
4. **`currency` is immutable once `status` leaves `TRIAL`.** Once a company has gone `ACTIVE`, financial data (payroll, leave-with-encashment, expense claims — all future modules) will be created in that currency; changing it later would silently corrupt every existing money value. Enforced at the service layer as a hard rule, not merely a UI warning.
5. **`timezone` must be a valid IANA time zone identifier.** Changing it is a significant, audited operation (ADR-0010 — it drives attendance/payroll business-day boundaries). This design reserves a guard — *disallow changing `timezone` while any dependent module reports an open/locked period* — but since Payroll/Attendance do not exist yet in V1, the guard is a documented no-op hook (`CompanyService._assert_timezone_change_allowed()`) to be filled in when those modules ship, not skipped silently. See [06_Testing_Strategy.md](06_Testing_Strategy.md) for the edge case this must eventually cover.
6. **`WorkingDaysPattern` must mark at least one day as working.** A company with zero working days is not a valid configuration.
7. **`BusinessHours.start_time < end_time`** when both are set (no overnight-spanning company-wide default; Shift-level overrides may model overnight shifts — that's the Shift sub-domain's concern, not Company's).
8. **`CompanyStatus` transitions must follow the defined state machine** (§7.1) — no direct jump from `TRIAL` to `TERMINATED` without passing through the transition's own validation (e.g. a reason code), and `TERMINATED` is terminal (no transition out).
9. **`Subscription`** — at most one row per company with `status NOT IN (CANCELED, EXPIRED)`; `trial_ends_at` set at grant time should not silently drift from `Company.trial_ends_at` (kept in sync by the service, not two independently-editable fields).
10. **`CompanyFeatureFlag`** — a flag with `overrides_plan = false` that enables a feature the current `Plan` does not include is a contradiction and must be rejected at write time; only `overrides_plan = true` flags may enable a feature outside the plan (reserved for negotiated/beta access, itself gated by a platform-level permission — see [Auth/RBAC note in 04_API_Design.md](04_API_Design.md)).
11. **Every mutation is optimistically locked** via `version` (repository-wide convention) and audited with before/after JSON (repository-wide convention, `AuditService.record`).
12. **`CompanySetupProgress`** has exactly one row per company, created at registration, never deleted.

---

## 6. Primary Legal Entity (read-through, not owned)

`Company` does **not** store GSTIN/PAN/CIN. Once the Legal Entity sub-domain exists (`legal_entity` table, already present in schema — see [01_Company_Module_Overview.md §6](01_Company_Module_Overview.md#6-domain-ownership)), the Company Profile API exposes a `primary_legal_entity` projection resolved by querying for the `legal_entity` row flagged `is_primary = true` for that `company_id`. This is a **read-only join at the API layer**, not a foreign key on `Company` — the aggregate boundary stays clean (Legal Entity references Company, not the reverse), and Company's own persistence never depends on Legal Entity existing. Until that sub-domain is built, `primary_legal_entity` is always `null` in the API response — an honest empty state, not a stub error.

---

## 7. Lifecycle

### 7.1 `Company.status` state machine

```
                 ┌──────────────────────────────┐
                 │                               │
  (register) ──► TRIAL ──► ACTIVE ──► SUSPENDED ─┘
                   │           │           │
                   │           │           │
                   └────► TERMINATED ◄─────┘
                          (terminal)
```

| Transition | Trigger | Notes |
|---|---|---|
| — → `TRIAL` | Self-service registration | Initial state, always |
| `TRIAL` → `ACTIVE` | Subscription activated (plan selected/paid, or platform override) | |
| `TRIAL` → `TERMINATED` | Trial expires without conversion (background job) or admin cancels during trial | |
| `ACTIVE` → `SUSPENDED` | Billing failure, manual platform action, ToS violation | Reversible |
| `SUSPENDED` → `ACTIVE` | Issue resolved (payment recovered, manual reinstatement) | |
| `ACTIVE`/`SUSPENDED` → `TERMINATED` | Cancellation, non-payment past grace period, manual offboarding | Terminal — no path back out. A terminated company's data retention follows the same soft-delete + retention-job policy as any other business record (`docs/database/Database_Architecture.md` §7) |

A `SUSPENDED` company is read-accessible (so admins can see why) but write-blocked at the API layer for everything except reactivation-relevant actions — enforced in `CompanyService`, not by RLS (RLS has no concept of status).

### 7.2 `CompanySetupProgress.status`

Not a linear workflow — recomputed from underlying row counts on every read (or by a periodic refresher job, see [05_Backend_Architecture.md](05_Backend_Architecture.md)). It is therefore possible, honestly, for `status` to move from `COMPLETE` back to `IN_PROGRESS` if a previously-satisfied step's data is later removed (e.g. every Branch is deleted). This is intentional — the field states a fact about current data, not a ratcheting achievement.

### 7.3 `Subscription.status`

`TRIALING` → `ACTIVE` → (`PAST_DUE` ⇄ `ACTIVE`) → `CANCELED` | `EXPIRED`. `PAST_DUE` and `CANCELED`/`EXPIRED` are billing-integration concerns; this module's V1 scope models the states and their effect on `CompanyFeatureFlag` resolution, not the payment retries themselves (Overview §5 — billing integration is future scope).
