# Company Module — Database Design

Conforms to the binding conventions in `docs/database/Database_Architecture.md` and `docs/product/08_Database_Architecture.md`: UUID PKs (`gen_random_uuid()`), `snake_case` singular table names, audit columns (`created_at`, `created_by`, `updated_at`, `updated_by`, `deleted_at`, `version`), no hard deletes, RLS on every tenant table, every FK indexed, enums as `VARCHAR` + `CHECK` (never native `PG ENUM`), JSONB reserved for tenant custom fields / structured config snapshots (never core relational attributes).

**Known drift to fix, not invent:** the live SQLAlchemy `Company` model (`hrms/core/db/models/identity.py`) is missing several columns that already exist in `scripts/sql/001_init_schema.sql` (`industry_code`, `fy_start_month`, `logo_url`, `theme_json`, `onboarded_at`, `trial_ends_at`, `data_region`). This is called out explicitly in [07_Implementation_Backlog.md](07_Implementation_Backlog.md) Task C-01 — it must be fixed before any new column is added, so the model and schema never drift further apart.

---

## 1. Table Catalogue

| Table | Tenant-scoped (RLS) | Status |
|---|---|---|
| `company` | No (tenant root) | Exists — extended by this design |
| `company_setup_progress` | Yes | New |
| `subscription` | Yes | New |
| `company_feature_flag` | Yes | New |
| `plan` | No (global reference data) | New |
| `plan_feature` | No (global reference data) | New |

---

## 2. `company` (tenant root — no `company_id`, exempt from RLS)

### 2.1 Existing columns (unchanged)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, `DEFAULT gen_random_uuid()` |
| `name` | VARCHAR(200) | NOT NULL |
| `legal_name` | VARCHAR(200) | |
| `subdomain` | VARCHAR(63) | UNIQUE |
| `industry_code` | VARCHAR(40) | |
| `country_code` | CHAR(2) | NOT NULL, DEFAULT `'IN'` |
| `currency` | CHAR(3) | NOT NULL, DEFAULT `'INR'` |
| `timezone` | VARCHAR(50) | NOT NULL, DEFAULT `'Asia/Kolkata'` |
| `fy_start_month` | SMALLINT | NOT NULL, DEFAULT `4`, CHECK `(fy_start_month BETWEEN 1 AND 12)` *(constraint is new — not present in the original DDL; add via migration, see §6)* |
| `logo_url` | TEXT | |
| `theme_json` | JSONB | Branding/white-label payload |
| `status` | VARCHAR(20) | NOT NULL, DEFAULT `'TRIAL'`, CHECK `(status IN ('TRIAL','ACTIVE','SUSPENDED','TERMINATED'))` *(CHECK is new)* |
| `onboarded_at` | TIMESTAMPTZ | |
| `trial_ends_at` | TIMESTAMPTZ | |
| `data_region` | VARCHAR(20) | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT `CURRENT_TIMESTAMP` |
| `updated_at` | TIMESTAMPTZ | NOT NULL |
| `deleted_at` | TIMESTAMPTZ | See §2.4 — meaning is narrower than "company terminated" |
| `version` | INTEGER | NOT NULL, DEFAULT `1` — optimistic locking |

### 2.2 New columns added by this design

Gap-filled against the brief's requirement list (Company Profile: registration number, contact, industry sizing, address; Company Settings: locale, working days, business hours) — none of these exist in the current schema and none duplicate the `legal_entity` table's statutory fields (see [02_Domain_Model.md §6](02_Domain_Model.md#6-primary-legal-entity-read-through-not-owned)).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `registration_number` | VARCHAR(64) | | Generic business registration id — not GSTIN/PAN/CIN |
| `contact_email` | VARCHAR(255) | | Published company contact, distinct from any user login email |
| `contact_phone` | VARCHAR(32) | | |
| `website` | VARCHAR(255) | | |
| `company_size` | VARCHAR(20) | CHECK `(company_size IN ('1-10','11-50','51-200','201-500','501-1000','1000+'))` | Self-declared band, informational |
| `address_line1` | VARCHAR(255) | | |
| `address_line2` | VARCHAR(255) | | |
| `address_city` | VARCHAR(100) | | |
| `address_state` | VARCHAR(100) | | |
| `address_postal_code` | VARCHAR(20) | | |
| `address_country_code` | CHAR(2) | | Defaults to `country_code` at write time if omitted — enforced in service, not DB |
| `locale_language_code` | VARCHAR(10) | NOT NULL, DEFAULT `'en-IN'` | BCP-47 |
| `date_format` | VARCHAR(20) | NOT NULL, DEFAULT `'DD/MM/YYYY'` | |
| `working_days_pattern` | JSONB | NOT NULL, DEFAULT `'[{"day":"MON","is_working":true},...]'` | Structured config snapshot — same JSONB-for-config-not-custom-fields pattern already used by the existing `week_off_pattern.pattern JSONB` column (`docs/product/08` §4), not a tenant-custom-field use |
| `business_hours_start` | TIME | | Local to `Company.timezone`; NULL = not set |
| `business_hours_end` | TIME | CHECK `(business_hours_end IS NULL OR business_hours_start IS NULL OR business_hours_end > business_hours_start)` | |
| `created_by` | UUID | FK → `user(id)`, NULLABLE, `ON DELETE SET NULL` | Nullable because platform-seeded companies (dev fixtures, tests) have no registering user; for self-service registration this is the newly created admin user's id — inserted in the same transaction, user row first (see [05_Backend_Architecture.md](05_Backend_Architecture.md)) |
| `updated_by` | UUID | FK → `user(id)`, NULLABLE, `ON DELETE SET NULL` | |

### 2.3 Why no `company_id` / RLS

`company.id` **is** the tenant identity — there is no parent tenant for it to be scoped under. Per `apps/api/scripts/sql/002_row_level_security.sql` (existing, unchanged): `company` gets `ALTER TABLE company FORCE ROW LEVEL SECURITY` with **no policy**, i.e. access control for `company` rows happens exclusively at the application layer — a request can only ever resolve `Company.id` via the authenticated user's `UserCompany` membership (`get_tenant_context`, existing `core/tenancy` dependency), never by an arbitrary path parameter. There is deliberately no `GET /v1/companies/{id}` route in this design (see [04_API_Design.md](04_API_Design.md)) — only `/companies/current`, resolved server-side from the JWT — which is what makes "no RLS policy" safe: the row-selection logic never takes a client-supplied company id as a filter in the first place.

### 2.4 Soft delete on `company` — narrower meaning than "terminated"

`deleted_at`/`deleted_by` on `company` follows the repository-wide soft-delete convention, but its meaning is deliberately narrower than the business lifecycle state (`status = TERMINATED`, [02_Domain_Model.md §7.1](02_Domain_Model.md#71-companystatus-state-machine)):

- **`status = TERMINATED`** — the normal, expected end state of a customer relationship (churn, offboarding). The row is retained, queryable, and excluded from active-tenant queries by status, not by `deleted_at`.
- **`deleted_at` set** — reserved for erroneous or duplicate tenant records (a duplicate self-service registration, a test/spam signup) that should never have existed as a real tenant. Physical deletion only via the retention job, per repository-wide policy (`docs/database/Database_Architecture.md` §7).

This distinction is called out explicitly because conflating them would make `TERMINATED` (a legitimate, common, reportable state) invisible to any query that filters `WHERE deleted_at IS NULL` the way every other soft-deletable table does.

### 2.5 Indexes

| Index | Definition | Purpose |
|---|---|---|
| `company_subdomain_key` | UNIQUE `(subdomain)` | Existing — subdomain uniqueness |
| `company_status_idx` | `(status) WHERE deleted_at IS NULL` | Platform-level queries (trial-expiry sweep, active-tenant counts) |
| `company_trial_ends_at_idx` | `(trial_ends_at) WHERE status = 'TRIAL'` | Background job scanning for trial expiry (§7.2 in Domain Model) |

---

## 3. `company_setup_progress`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, `DEFAULT gen_random_uuid()` |
| `company_id` | UUID | NOT NULL, UNIQUE, FK → `company(id)` ON DELETE RESTRICT ON UPDATE CASCADE |
| `steps_completed` | JSONB | NOT NULL, DEFAULT `'[]'` — array of step codes, recomputed not hand-edited (see [05_Backend_Architecture.md](05_Backend_Architecture.md)) |
| `current_step` | VARCHAR(40) | |
| `status` | VARCHAR(20) | NOT NULL, DEFAULT `'IN_PROGRESS'`, CHECK `(status IN ('IN_PROGRESS','COMPLETE'))` |
| `started_at` | TIMESTAMPTZ | NOT NULL, DEFAULT `CURRENT_TIMESTAMP` |
| `completed_at` | TIMESTAMPTZ | |
| `created_at` / `updated_at` | TIMESTAMPTZ | Standard |
| `version` | INTEGER | NOT NULL, DEFAULT `1` |

No `deleted_at` — this row's lifecycle is bound 1:1 to its `company` row (never independently deleted; removed only if the company itself is, via the same retention job). No `created_by`/`updated_by` — every write is system-derived (a step-completion recount), never directly user-authored.

**Indexes:** `company_id` UNIQUE (already required by the constraint, forms its own index).

**RLS:** standard tenant policy (`company_id = current_setting('app.company_id', true)::uuid`).

---

## 4. `plan` (global reference data — no RLS, no `company_id`)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, `DEFAULT gen_random_uuid()` |
| `code` | VARCHAR(40) | NOT NULL, UNIQUE |
| `name` | VARCHAR(100) | NOT NULL |
| `description` | TEXT | |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT `true` |
| `created_at` / `updated_at` | TIMESTAMPTZ | Standard |
| `version` | INTEGER | NOT NULL, DEFAULT `1` |

Seed data, not user-created (`docs/database/Database_Architecture.md` §9 — "seed data ... loaded via a seed script rather than Alembic"). No `company_id` — this is a platform catalogue shared by every tenant, structurally identical to how `statutory_master` is global reference data per `docs/product/08`.

## 5. `plan_feature` (global reference data)

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, `DEFAULT gen_random_uuid()` |
| `plan_id` | UUID | NOT NULL, FK → `plan(id)` ON DELETE RESTRICT |
| `feature_code` | VARCHAR(60) | NOT NULL |
| `is_enabled` | BOOLEAN | NOT NULL, DEFAULT `true` |
| `limit_value` | INTEGER | Nullable — e.g. max employee seats for this plan |
| `created_at` / `updated_at` | TIMESTAMPTZ | Standard |

**Constraint:** UNIQUE `(plan_id, feature_code)`. **Index:** `(plan_id)` (FK-indexing rule).

---

## 6. `subscription`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, `DEFAULT gen_random_uuid()` |
| `company_id` | UUID | NOT NULL, FK → `company(id)` ON DELETE RESTRICT ON UPDATE CASCADE |
| `plan_id` | UUID | NOT NULL, FK → `plan(id)` ON DELETE RESTRICT |
| `status` | VARCHAR(20) | NOT NULL, DEFAULT `'TRIALING'`, CHECK `(status IN ('TRIALING','ACTIVE','PAST_DUE','CANCELED','EXPIRED'))` |
| `current_period_start` | TIMESTAMPTZ | |
| `current_period_end` | TIMESTAMPTZ | |
| `trial_ends_at` | TIMESTAMPTZ | |
| `canceled_at` | TIMESTAMPTZ | |
| `seat_limit_override` | INTEGER | |
| `created_at` / `updated_at` / `deleted_at` | TIMESTAMPTZ | Standard |
| `version` | INTEGER | NOT NULL, DEFAULT `1` |

**Constraints:**
- Partial UNIQUE `(company_id) WHERE status NOT IN ('CANCELED','EXPIRED')` — at most one live subscription per company ([02_Domain_Model.md §5.9](02_Domain_Model.md#5-validation-rules--business-invariants)).

**Indexes:** `(company_id)`, `(plan_id)` — both FKs, per the FK-indexing rule.

**RLS:** standard tenant policy.

---

## 7. `company_feature_flag`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, `DEFAULT gen_random_uuid()` |
| `company_id` | UUID | NOT NULL, FK → `company(id)` ON DELETE RESTRICT ON UPDATE CASCADE |
| `feature_code` | VARCHAR(60) | NOT NULL |
| `is_enabled` | BOOLEAN | NOT NULL, DEFAULT `true` |
| `overrides_plan` | BOOLEAN | NOT NULL, DEFAULT `false` |
| `value` | JSONB | Nullable — config payload for non-boolean flags |
| `created_at` / `created_by` / `updated_at` / `updated_by` | | Standard — these ARE directly user/platform-authored, unlike `company_setup_progress` |
| `version` | INTEGER | NOT NULL, DEFAULT `1` |

**Constraints:** UNIQUE `(company_id, feature_code)`.
**Indexes:** `(company_id)`.
**RLS:** standard tenant policy.

---

## 8. Migration Order

Alembic migrations, in dependency order (autogenerate for routine adds, hand-written SQL for RLS/CHECK constraints per `docs/database/Database_Architecture.md` §9):

1. **`company` fix-drift migration** — bring `hrms/core/db/models/identity.py::Company` in sync with the already-deployed SQL schema (no DB change, model-only — see backlog Task C-01). Must land first so every later migration autogenerates cleanly against a non-drifted model.
2. **`company` gap-fill migration** — `ALTER TABLE company ADD COLUMN ...` for every column in §2.2, plus the two new `CHECK` constraints on `fy_start_month` and `status` noted in §2.1 (added `NOT VALID` then `VALIDATE CONSTRAINT` in a following step per the large-table-safe pattern, even though `company` is low-cardinality — consistency with the documented convention). Plus the two new indexes in §2.5.
3. **`plan` + `plan_feature`** — new tables, no RLS. Followed by a seed script (not a migration) populating the initial plan catalogue (e.g. `FREE_TRIAL`, `STANDARD`, `ENTERPRISE`) — actual plan definitions are a product/pricing decision outside this design doc's scope.
4. **`company_setup_progress`** — new table + RLS policy in the same migration (hand-written SQL block, per convention).
5. **`subscription`** — new table + RLS policy + partial unique index. Depends on `plan` existing (step 3).
6. **`company_feature_flag`** — new table + RLS policy.

Each RLS-bearing table added here must also add its table name to the `FOREACH tbl IN ARRAY [...]` loop in `scripts/sql/002_row_level_security.sql` (or an equivalent follow-up SQL file per the existing convention of keeping that script as the canonical RLS registry).

---

## 9. Future Expansion

- **`legal_entity`, `branch`, `department`, `designation`, `grade`, `holiday_calendar`** already exist in SQL (`001_init_schema.sql`) with no ORM models yet — out of scope for this module, noted here only so a future migration doesn't collide with these table names.
- **`primary_legal_entity` read-through** ([02_Domain_Model.md §6](02_Domain_Model.md#6-primary-legal-entity-read-through-not-owned)) requires `legal_entity.is_primary BOOLEAN` + a partial unique index `(company_id) WHERE is_primary = true` — to be added when the Legal Entity sub-domain is built, not by this module.
- **Billing integration** would add `payment_method`, `invoice` tables referencing `subscription` — explicitly deferred (Overview §5).
- **Platform/Super-Admin tooling** would need a cross-tenant read path that intentionally bypasses the single-tenant `X-Company-Id` resolution this design relies on — a distinct, carefully-scoped mechanism, not an extension of `CompanyRepository`.
