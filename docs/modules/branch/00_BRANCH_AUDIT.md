# Branch Module — Pre-Implementation Audit

Status: **Audit only — no code changed.** Produced before starting the Branch vertical
slice, following the same audit-then-build discipline used for Legal Entity
(`docs/modules/legal-entity/01_Legal_Entity_Module.md`). This document inspects the
current DB, the completed Legal Entity slice (the pattern to replicate), and all Branch
references across product docs, then states exactly what Branch needs, what's already
there, and what decisions are needed before writing code.

---

## 1. Current State

**Branch has zero application code.** There is no ORM model, no repository/service/router
methods, no Pydantic schemas, no permission code, no frontend page, and no dedicated test
file anywhere in the repo.

The only things that exist today:

- A **DB-level stub table** `branch`, created in the original baseline schema
  (`apps/api/scripts/sql/001_init_schema.sql:144-156`) — present since the very first
  migration, never touched since.
- **Incidental, defensive references** from the Legal Entity slice, which explicitly
  treats Branch as "not yet built" and works around that:
  - `OrganisationRepository.count_active_branches_for_legal_entity()`
    (`apps/api/src/hrms/modules/organisation/repository.py:364-377`) — raw SQL
    (`text("SELECT count(*) FROM branch ...")`) because "the Branch module itself is out
    of scope for this slice (no ORM model yet)."
  - `LegalEntityDeactivationBlockedError` (`.../organisation/exceptions.py:47-65`), code
    `LEGAL_ENTITY_HAS_ACTIVE_BRANCHES`.
  - `LegalEntity` model docstring (`.../organisation/models.py:73-77`): "Branch/Employment
    already carry a `legal_entity_id` FK at the DB level; this module does not yet own
    either."
  - `CompanyDashboardSummary.branch_count` (`.../organisation/schemas.py:458`) — always
    returned as `None` (`service.py:484`) since nothing populates it.
  - A comment in `service.py:70-71` sketching a future `SetupStepDefinition(code="BRANCHES", ...)`
    setup-wizard step that a Branch-owned repository method would supply.
- **Frontend**: only a disabled/placeholder "Branches" stat tile on the dashboard
  (`apps/web/src/app/app/dashboard/page.tsx:149`, renders `formatCount(dashboard.branch_count)`
  which is always "—") and a "BRANCHES" label in the setup-checklist step list
  (`apps/web/src/app/app/setup/page.tsx`). Neither is a real feature.
- **Documentation**: no `docs/modules/branch/` directory existed before this audit. Branch
  is discussed only inside broader docs (SRS, Database Architecture, RBAC matrix, the
  Sprint 3 plan, and the Legal Entity module doc's own "recommended next slice" section).

**The good news**: the Legal Entity slice, which just shipped, is a complete, current,
single-file reference implementation of the exact pattern Branch must follow — same
module (`organisation`), same layering, same conventions. It is the primary source for
"how" in this audit; the Sprint 3 plan and Database Architecture doc are the primary
sources for "what."

---

## 2. Database State

### 2.1 What exists today

`branch` table (`apps/api/scripts/sql/001_init_schema.sql:144-156`):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK, `gen_random_uuid()` default |
| `company_id` | UUID NOT NULL | no FK constraint declared (same as every other org table at init) |
| `legal_entity_id` | UUID NOT NULL | FK'd (`branch_legal_entity_id_fkey → legal_entity(id) ON DELETE RESTRICT ON UPDATE CASCADE`, line 410) |
| `name` | VARCHAR(200) NOT NULL | |
| `state` | VARCHAR(60) | free text — no code/format |
| `timezone` | VARCHAR(50) | |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `updated_at` | TIMESTAMPTZ NOT NULL | |
| `deleted_at` | TIMESTAMPTZ | reserved, unused |

Indexes: `branch_company_id_idx`, `branch_legal_entity_id_idx` (lines 335, 338).

Referenced by: `department.branch_id` (FK, `ON DELETE SET NULL`, line 416) and
`employee_assignment.branch_id` (column only, no FK yet declared — line 267). Neither
`department` nor `employee_assignment`/`employee` has application code yet either.

**RLS**: `branch` is included in the generic tenant-isolation loop embedded directly in
`001_init_schema.sql:467-483` (`ENABLE`/`FORCE ROW LEVEL SECURITY` + a `tenant_isolation`
policy on `company_id`), alongside `legal_entity`, `department`, etc.

**Important caveat, carried over from the Legal Entity audit** — do not treat this as
settled: `legal_entity` was *also* listed in that same init-schema loop, yet the Legal
Entity slice still found it necessary to re-apply RLS idempotently in its own migration
(`20260813120000_legal_entity_fields.py:42-46`, with `DROP POLICY IF EXISTS` +
`CREATE POLICY`), because — per that migration's own comment — "the standalone
`scripts/sql/002_row_level_security.sql` file... is never invoked by Alembic and is not
the live RLS registry," and because a table only reliably has RLS in *every* environment
once it's asserted in its own dedicated, idempotent migration step, not merely present in
a possibly-since-edited historical migration file. **The same caveat applies to `branch`
verbatim.** §3 below carries this forward as a required (not optional) part of the Branch
migration, exactly mirroring what Legal Entity did — even though `branch` nominally
"already has RLS" the same way `legal_entity` nominally did.

### 2.2 What the spec requires

`docs/product/08_Database_Architecture.md:180` (§4, Organisation Master):

```
branch | id, company_id, legal_entity_id, code, name, address_line1/2, city, state_code,
         pincode, timezone, latitude, longitude, geofence_radius_m, holiday_calendar_id,
         week_off_pattern_id, is_active
```

`docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:419` (Task 3.1.1) gives the exact migration
spec, including types and an explicit sequencing decision:

> Migration adding: `code VARCHAR(30)`, `address_line1 VARCHAR(200)`,
> `address_line2 VARCHAR(200)`, `city VARCHAR(100)`, `state_code VARCHAR(10)` (**replaces**
> free-text `state`; since this is pre-launch with only seed data, drop and recreate the
> column rather than writing a data-migration step), `pincode VARCHAR(10)`,
> `latitude NUMERIC(9,6)`, `longitude NUMERIC(9,6)`, `geofence_radius_m INTEGER`,
> `is_active BOOLEAN DEFAULT true`, `version INTEGER DEFAULT 1`.
>
> `holiday_calendar_id UUID NULL` and `week_off_pattern_id UUID NULL` are **explicitly
> deferred** — added as forward-reference follow-up migrations once `holiday_calendar` is
> expanded (Feature 4.1) and `week_off_pattern` is created (Task 3.1.3), respectively.
> Branch ships in Task 3.1.1 **without** those two FK columns.

This mirrors exactly how Legal Entity's stub (`id, company_id, name, pan, gstin, ...`)
was expanded in one additive migration (`20260813120000_legal_entity_fields.py`) rather
than a rewrite.

### 2.3 Gap: existing column vs. target

| Column | Status |
|---|---|
| `id`, `company_id`, `legal_entity_id`, `name`, `timezone` | ✅ present, keep as-is |
| `state` (free text) | ⚠️ **replace** with `state_code VARCHAR(10)` (validated) |
| `code` | ❌ missing |
| `address_line1`, `address_line2`, `city`, `pincode` | ❌ missing |
| `latitude`, `longitude`, `geofence_radius_m` | ❌ missing |
| `is_active`, `version` | ❌ missing (needed for the same soft-deactivate + optimistic-concurrency pattern Legal Entity uses) |
| `holiday_calendar_id`, `week_off_pattern_id` | ❌ missing — **intentionally deferred**, see §2.2 |

---

## 3. Required Data Model

### 3.1 ORM model — `organisation/models.py::Branch`

Same file as `LegalEntity` (the `organisation` module owns the whole Company→Employee
hierarchy per `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md`'s owning-module column — no
new `modules/branch/` package, exactly as Legal Entity did not get its own package).

```python
class Branch(Base, TimestampMixin):
    __tablename__ = "branch"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)
    legal_entity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("legal_entity.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    geofence_radius_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
```

`holiday_calendar_id`/`week_off_pattern_id` intentionally absent per §2.2/§14.

### 3.2 Migration

New file, e.g. `apps/api/alembic/versions/20260813130000_branch_fields.py`
(`down_revision = "20260813120000"`, i.e. chained after the Legal Entity migration —
today's head). Content mirrors `20260813120000_legal_entity_fields.py`'s shape exactly:

```sql
ALTER TABLE branch
  DROP COLUMN state,
  ADD COLUMN code VARCHAR(30),
  ADD COLUMN address_line1 VARCHAR(200),
  ADD COLUMN address_line2 VARCHAR(200),
  ADD COLUMN city VARCHAR(100),
  ADD COLUMN state_code VARCHAR(10),
  ADD COLUMN pincode VARCHAR(10),
  ADD COLUMN latitude NUMERIC(9,6),
  ADD COLUMN longitude NUMERIC(9,6),
  ADD COLUMN geofence_radius_m INTEGER,
  ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN version INTEGER NOT NULL DEFAULT 1;

CREATE INDEX branch_company_active_idx ON branch (company_id, is_active) WHERE deleted_at IS NULL;

-- Re-assert RLS idempotently — see §2.1 caveat; do not rely on the 001_init_schema.sql loop.
ALTER TABLE branch ENABLE ROW LEVEL SECURITY;
ALTER TABLE branch FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON branch;
CREATE POLICY tenant_isolation ON branch
  USING (company_id = current_setting('app.company_id', true)::uuid);
```

`timezone` already exists and stays; no type change needed. `DROP COLUMN state` is safe
per the sprint doc's own note — pre-launch, only seed/test data exists — but see the test
fixture impact in §10.

### 3.3 Schemas (`organisation/schemas.py`)

Add `BranchCreate`, `BranchUpdate`, `BranchRead`, `branch_to_read`,
`build_branch_update_values` — same shape as the `LegalEntity*` quartet
(`schemas.py:463-581`). Differences from Legal Entity's schema set:

- `legal_entity_id: UUID` is **required** on create (Branch cannot exist without a parent
  legal entity — matches the FK's `NOT NULL`).
- `state_code` gets a validator against a static Indian-state constant (see §5.3), not a
  regex — this is new; Legal Entity's PAN/GSTIN validators are regex-based and not a
  reusable pattern for a fixed enum list.
- `pincode`: format-validate as 6 digits (India) — same "documented gap if not validated"
  posture as Legal Entity's PAN/GSTIN, i.e. validate what's named in a spec doc, don't
  invent formats for fields no doc constrains.
- `latitude`/`longitude`/`geofence_radius_m`: range-validate (`-90..90`, `-180..180`,
  positive int) per the sprint doc's testing requirement (§9 below), independently
  optional (a branch can have zero, some, or all three set — but see §12 open question on
  whether partial geofence data should be rejected).
- `is_active` is server-controlled on create (`True`, not client-settable) and
  client-settable via PATCH only — identical rule to `LegalEntityUpdate.is_active`.

---

## 4. API Requirements

Per `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:422` and the Legal Entity precedent
(`docs/modules/legal-entity/01_Legal_Entity_Module.md §4`), same router file
(`organisation/router.py`), same conventions (`DataEnvelope`/`ListEnvelope`,
`ErrorEnvelope`, `extra="forbid"`, tenant from `X-Company-Id` + JWT only, `{id}` in the
path is a plain resource identifier re-checked against `company_id` server-side, never a
tenant-scoping mechanism):

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/branches` | `ORG.BRANCH.MANAGE` | List, company-scoped, no pagination (same low-cardinality assumption as legal entities) |
| POST | `/v1/branches` | `ORG.BRANCH.MANAGE` | Create; `is_active` always `true` |
| GET | `/v1/branches/{branch_id}` | `ORG.BRANCH.MANAGE` | 404 (never 403) cross-tenant or not-found |
| PATCH | `/v1/branches/{branch_id}` | `ORG.BRANCH.MANAGE` | `If-Match: <version>`; partial update; `is_active` togglable here |
| DELETE | `/v1/branches/{branch_id}` | `ORG.BRANCH.MANAGE` | Soft deactivation only; `If-Match`; returns `200 DataEnvelope<BranchRead>`, not `204` |

Open question folded into §12: should `GET /v1/branches` support filtering by
`legal_entity_id` (e.g. `?legal_entity_id=...`)? No doc specifies this, and Legal
Entity's own list endpoint takes no query params. Recommendation: **not this slice** —
list is unfiltered (same low-cardinality assumption), consistent with "don't invent
requirements."

---

## 5. Business Rules

### 5.1 Deactivation blocking (FR-ORG-014)

`docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:419`: "Deactivation blocked if referenced by
an active `department` or (later) employee (FR-ORG-014)."

Department has no application code either (no ORM model — confirmed absent from
`organisation/models.py`), so this must be implemented the same defensive way Legal
Entity checks Branch today: **raw SQL against the `department` table**
(`SELECT count(*) FROM department WHERE branch_id = :branch_id AND deleted_at IS NULL`),
since `department` has no `is_active` column at all yet (`001_init_schema.sql:159-171`
— only `deleted_at`). New exception class `BranchDeactivationBlockedError` (mirrors
`LegalEntityDeactivationBlockedError`, code e.g. `BRANCH_HAS_ACTIVE_DEPARTMENTS`).

The "(later) employee" half is explicitly out of scope — Employee doesn't exist.

### 5.2 A real bug this slice must fix in Legal Entity's existing code

`OrganisationRepository.count_active_branches_for_legal_entity`
(`repository.py:370-376`) currently counts branches by `deleted_at IS NULL` only:

```sql
SELECT count(*) FROM branch WHERE legal_entity_id = :entity_id AND deleted_at IS NULL
```

That was correct **only** because `branch` had no `is_active` column to distinguish
"deactivated" from "still active" — every non-deleted row necessarily counted as
"active." Once this slice adds `branch.is_active`, that query becomes wrong: a
**deactivated** branch (`is_active = false`, `deleted_at` still `NULL`, since
deactivation is never a delete) would still be counted, incorrectly blocking Legal
Entity deactivation on branches that are themselves already inactive. This query must be
updated to `AND is_active = true AND deleted_at IS NULL` **as part of this slice** — it's
a direct, mechanical consequence of adding the column Legal Entity's own check depends
on, not scope creep. Flagged explicitly in §11 and §13.

### 5.3 `state_code` validation

Sprint doc, Testing Requirements (`SPRINT_3_COMPANY_FOUNDATION.md:423`): "`state_code`
validated against the ISO 3166-2:IN state list (a static constant — needed because state
drives PT slab and holiday calendar per FR-ORG-004, even though PT/statutory computation
itself is out of scope this sprint)." No such constant exists anywhere in the codebase
today (checked both `apps/api/src` and `apps/web/src` — no hits for `state_code`,
`ISO 3166`, or any Indian-states list). This is new work, not reuse: a ~36-entry static
list (28 states + 8 union territories) needs to be authored on both backend (validator)
and frontend (`<Select>` options), mirroring how the register page already hand-rolls
small static option lists inline (`apps/web/src/app/register/page.tsx`) rather than
fetching them from an API.

### 5.4 Optimistic concurrency

`version` + `If-Match`, identical mechanism to Legal Entity and Company.

### 5.5 Geofence field validation

Sprint doc (`SPRINT_3_COMPANY_FOUNDATION.md:423`): "geofence fields accept null (not
every branch needs geofencing yet) and a valid radius when present." Recommendation:
validate ranges when present (lat/long bounds, positive radius) but do not require all
three together — no doc mandates that a partial set (e.g. lat/long without radius) be
rejected, and inventing that constraint isn't supported by the spec. Flagged as an open
question in §12 in case product wants stricter all-or-nothing semantics.

---

## 6. Permission Requirements

Single permission, matching the Company/Legal Entity precedent exactly (no view/manage
split — same reasoning `permissions.py:6-12` already documents for Legal Entity):

```python
ORG_BRANCH_MANAGE = "ORG.BRANCH.MANAGE"
```

Add to `ORGANISATION_PERMISSIONS` list (`permissions.py:15-19`) and grant it to the
`COMPANY_ADMIN` system role at registration time in
`OrganisationService.register_company` (`service.py:172-207`), the same three-step
pattern used for `ORG_LEGAL_ENTITY_MANAGE`: `get_or_create_permission` →
`insert_role_permission` on the newly-created role. This is inline in `register_company`,
**not** in `seed/bootstrap.py` (checked — `bootstrap.py` has no legal-entity permission
references either; the grant-at-registration pattern is deliberate, not an oversight).

`docs/product/19_RBAC_and_Permission_Matrix.md:100` independently confirms the code:
`ORG.BRANCH.MANAGE` (no naming conflict like the Legal Entity/`ORG.ENTITY.MANAGE`
mismatch — see §11).

---

## 7. Tenant / RLS Requirements

Identical mechanism to every other `organisation`-module resource
(`docs/modules/legal-entity/01_Legal_Entity_Module.md §7`): `TenancyMiddleware` +
`get_tenant_context` sets both the `TenantContext` contextvar and the Postgres
`app.company_id` session variable; repository queries filter explicitly by `company_id`
in addition to RLS (belt-and-suspenders, ADR-0002). Cross-tenant access — including
guessing a real `branch_id` — must return `404`, never `403` or a leak.

RLS itself: see §2.1/§3.2 — must be re-asserted idempotently in the Branch migration
exactly as Legal Entity's migration did, not assumed-present from the init-schema loop.

---

## 8. Audit Requirements

Use the existing `AuditService` (`hrms/core/audit/service.py`) — no new audit
infrastructure. Events, mirroring Legal Entity's four (`service.py:523-533, 606-625`):

- `BRANCH_CREATED`
- `BRANCH_UPDATED`
- `BRANCH_DEACTIVATED`
- `BRANCH_REACTIVATED`

Each with `before_json`/`after_json` snapshots of the `BranchRead` DTO. No sensitive
fields in this resource (address/geo data is not `RESTRICTED`-classified per
`docs/product/19_RBAC_and_Permission_Matrix.md:201-205`'s field-sensitivity table), so no
special masking is needed — same posture as Legal Entity.

---

## 9. Frontend Requirements

Per `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:427-436` (Task 3.1.2) and the Legal
Entity precedent for structure:

- **Routes**: the sprint doc's own task text names
  `apps/web/src/app/(app)/settings/branches/...`, but the *actual, current* app-router
  convention established by every other slice is a flat top-level group —
  `apps/web/src/app/app/legal-entities/`, `apps/web/src/app/app/company/` (no
  `(app)`/`settings` grouping exists anywhere in the repo today; `app/app/` is the real
  authenticated route root). **Follow the codebase's actual convention, not the sprint
  doc's aspirational path** — same "exact patterns established" instruction the task
  brief gives. Concretely: `apps/web/src/app/app/branches/page.tsx` (list),
  `apps/web/src/app/app/branches/[id]/page.tsx` (detail/edit) — matching Legal Entity's
  two-route shape (list-with-create-dialog + detail-with-edit-toggle), not the sprint
  doc's three-route `new/` + `[id]/` split, since Legal Entity already established
  create-via-dialog-on-the-list-page as this codebase's actual pattern, superseding the
  sprint doc's earlier draft. Flagged as a decision in §12 in case the team wants a
  standalone create page instead.
- **Nav**: add "Branches" to the flat `NAV_ITEMS` array
  (`apps/web/src/components/layout/nav-items.ts`), same as "Legal Entities" was added.
- **Data fetching**: plain `useState`/`useEffect` + `apiClient`, no TanStack Query — same
  explicit instruction that governed Legal Entity.
- **Map / geofence entry**: sprint doc explicitly **scopes this down** to manual
  latitude/longitude number inputs + a static map preview image (e.g. an embedded OSM
  tile URL), not an interactive picker — the real interactive geofence editor is
  correctly deferred to the Attendance sprint where geofencing is actually enforced
  (`docs/product/24_UIUX_Screen_Inventory_and_Design_System.md` names it as a separate
  screen, "Geofence map editor," §4 area). Building that now would be scope creep.
- **`legal_entity_id` picker**: the Branch form needs a `<Select>` of the company's legal
  entities, populated via `GET /v1/legal-entities` (already built, reusable as-is with
  the existing `apiClient`). This is the first real cross-entity consumer of the Legal
  Entity list endpoint.
- **Reused components**: `PageHeader`, `FormField`, `LoadingState`, `ErrorState`,
  `EmptyState`, `toast`, `Card`, `Button`, `Badge`, `Dialog` — all already exist from the
  Legal Entity slice, zero new primitives needed.
- **New files**: `components/branch/branch-form.tsx`, `lib/branch/types.ts`,
  `lib/branch/validate-branch.ts` (+ `.test.ts`) — same three-file shape as
  `lib/legal-entity/`.
- **Week-off picker**: **excluded from this slice** per §14 — the sprint doc's Task 3.1.3
  scopes it as a separate supporting-entity task; the Branch form ships without a
  week-off selector until that FK column exists (§2.2).

---

## 10. Test Requirements

Mirror Legal Entity's file layout exactly (`docs/modules/legal-entity/01 §10`):

- `apps/api/tests/unit/modules/organisation/test_branch_service.py` — business-rule
  branches against a mocked repo (create/update/deactivate/reactivate, deactivation
  blocked/allowed, stale-version conflict, no-op patch), mirroring
  `test_legal_entity_service.py`'s 8 tests (`test_legal_entity_service.py:56-181`).
- `apps/api/tests/integration/modules/organisation/test_branch.py` — full CRUD,
  `state_code` validation (valid/invalid codes), pincode format, lat/long range,
  deactivation blocked by active department, reactivation, audit rows, stale-version
  conflict, not-found, mass-assignment rejection — mirroring
  `test_legal_entity.py`'s 15 tests (`test_legal_entity.py:71-405`).
- Branch cases **added to** the existing shared suites (not duplicated):
  `test_cross_tenant_isolation.py` (mirror `test_cross_tenant_legal_entity_get_blocked` /
  `..._list_never_leaks`, lines 106/139), `test_permission_matrix.py` (mirror
  `test_legal_entity_company_admin_allowed` / `..._zero_permission_denied`, lines
  174/190), `test_organisation_security.py`.
- **Existing test impact**: `test_legal_entity.py`'s `_insert_active_branch()` helper
  (lines 41-56) does a raw `INSERT INTO branch (id, company_id, legal_entity_id, name,
  created_at, updated_at) VALUES (...)` — this will keep working unmodified since none of
  the new Branch columns are `NOT NULL` without a default (`is_active` defaults `true` at
  the DB level, so an insert omitting it still produces an "active" row — correct for
  that test's purpose). No change needed there, but worth a note in the PR since it's a
  file this slice doesn't otherwise touch.
- Frontend: `lib/branch/validate-branch.test.ts` (pure validation/patch-diff logic),
  `app/app/branches/page.test.tsx`, `app/app/branches/[id]/page.test.tsx` — same coverage
  shape as the Legal Entity frontend tests (loading, empty state, create + validation +
  API-error paths, edit + stale conflict, deactivate/reactivate + blocked-deactivation
  toast, forbidden/not-found).
- E2E cross-feature check named in the sprint doc (`SPRINT_3_COMPANY_FOUNDATION.md:434`):
  "create branch → appears in Departments' branch picker" — **not implementable this
  slice** since Department doesn't exist; defer to whenever Department ships (§14).

---

## 11. Documentation Inconsistencies Found

1. **Route path**: sprint doc says `apps/web/src/app/(app)/settings/branches/...`; actual
   established convention is `apps/web/src/app/app/<resource>/...` flat, no `(app)`
   group, no `settings/` prefix. See §9 — recommend following the real codebase
   convention, and updating the sprint doc in a follow-up doc-only change (same
   resolution style Legal Entity used for its own `ORG.ENTITY.MANAGE` vs
   `ORG.LEGAL_ENTITY.MANAGE` naming conflict, `docs/modules/legal-entity/01 §5`).
2. **Route shape**: sprint doc implies three routes (list, `new/`, `[id]/`); Legal
   Entity's actual precedent is two (list-with-create-dialog, `[id]/` with inline edit
   toggle). Recommend following the precedent, not the sprint doc's draft shape.
3. **`count_active_branches_for_legal_entity` will become stale/incorrect** the moment
   `branch.is_active` exists (§5.2) — not a pre-existing doc contradiction, but a
   mechanical fact this audit surfaces so it isn't missed mid-implementation.
4. **RLS "already there" is not reliable** — `branch` is nominally in the
   `001_init_schema.sql` RLS loop, but per Legal Entity's own migration comment, that
   loop is not trustworthy as the live registry for any environment where the table
   predates an edit to that file. Re-assert idempotently regardless (§2.1, §3.2) — not a
   contradiction to resolve, just a trap not to fall into by assuming "the column list
   says RLS is already on, skip it."
5. No contradiction found on the `code`/`is_active`/`version` field set itself —
   Database Architecture (`08 §4`) and the Sprint 3 task spec (`3.1.1`) agree with each
   other.

---

## 12. Decisions Required From You

1. **Frontend route shape** (§9, §11.1-2): follow the actual `app/app/<resource>/`
   flat-route + create-dialog pattern (like Legal Entity), or the sprint doc's literal
   `(app)/settings/branches/{new,[id]}` three-route shape? **Recommendation: follow the
   established codebase pattern** (Legal Entity), treat the sprint doc's path as
   aspirational/superseded, same resolution style already used once.
2. **Geofence field strictness** (§5.5): allow partial geofence data (e.g. lat/long set,
   radius null), or require all-or-nothing? No doc mandates either. **Recommendation:
   allow partial** — matches the sprint doc's explicit "geofence fields accept null."
3. **`GET /v1/branches` filtering** (§4): add `?legal_entity_id=` filtering now, or leave
   unfiltered like Legal Entity's list endpoint? **Recommendation: unfiltered this
   slice** — no doc asks for it, low cardinality expected.
4. **Fixing `count_active_branches_for_legal_entity`** (§5.2): confirm this is in-scope
   for the Branch slice (it's a one-line `WHERE` clause change in a Legal-Entity-owned
   repository method, triggered by a column Branch adds). **Recommendation: yes, fix it
   here** — leaving it broken would silently reintroduce a bug the moment this slice
   ships, and it's a direct, mechanical consequence of this slice's own schema change,
   not unrelated scope creep.
5. **Week-off pattern** (§14): confirm Task 3.1.3 (`WeekOffPattern` table + seed +
   `branch.week_off_pattern_id` FK + inline `<Select>` in the Branch form) is excluded
   from this slice, per your instruction not to invent requirements and the sprint doc's
   own explicit sequencing (it's a separate task, not part of 3.1.1/3.1.2).
   **Recommendation: exclude** — ship Branch without a week-off selector; add the column
   and picker as a small follow-up once `week_off_pattern` exists.
6. **`holiday_calendar_id`** (§2.2, §14): same as above — deferred to Feature 4.1 per the
   sprint doc's explicit forward-reference sequencing. **Recommendation: exclude.**

---

## 13. Recommended Implementation Plan

Scoped to Task 3.1.1 + 3.1.2 only (backend + frontend CRUD for Branch), matching your
instruction to build "the next vertical slice" without pulling in Week-off Pattern,
Department, or later features.

1. **Migration** (§3.2): drop `state`, add `code`/`address_line1`/`address_line2`/
   `city`/`state_code`/`pincode`/`latitude`/`longitude`/`geofence_radius_m`/`is_active`/
   `version`, add the `branch_company_active_idx` index, re-assert RLS idempotently.
2. **Model** (§3.1): `Branch` in `organisation/models.py`.
3. **Static state-code constant** (§5.3): new list (backend validator constant; a mirrored
   frontend `<Select>` option list, same "mirrors the backend pattern" comment style
   `validate-legal-entity.ts:20-22` already uses for PAN/GSTIN).
4. **Schemas** (§3.3): `BranchCreate`/`BranchUpdate`/`BranchRead` + mapper functions.
5. **Exceptions**: `BranchDeactivationBlockedError` (mirrors
   `LegalEntityDeactivationBlockedError`).
6. **Repository**: `insert_branch`/`list_branches`/`get_branch`/`update_branch` (mirror
   the Legal Entity four exactly) + `count_active_departments_for_branch` (raw SQL, same
   shape as `count_active_branches_for_legal_entity`) + the one-line fix to
   `count_active_branches_for_legal_entity`'s `WHERE` clause (§5.2/§12.4).
7. **Service**: `create_branch`/`list_branches`/`get_branch`/`update_branch`/
   `deactivate_branch`, audit calls for all four event types (§8).
8. **Permissions**: `ORG_BRANCH_MANAGE`, grant to `COMPANY_ADMIN` at registration
   (§6).
9. **Router**: five endpoints (§4), same envelope/header conventions.
10. **Frontend**: `lib/branch/{types,validate-branch}.ts(+.test.ts)`,
    `components/branch/branch-form.tsx`, `app/app/branches/{page,[id]/page}.tsx(+.test.tsx)`,
    nav item.
11. **Tests**: unit + integration for Branch (§10), Branch cases added to the three
    shared suites, frontend component tests.
12. **Docs**: split this audit into (or supersede it with) a `docs/modules/branch/`
    module doc following Legal Entity's single-file shape (per that doc's own note that
    Legal Entity "mirrors the topics covered by the 7-file `docs/modules/company/` set...
    kept as one file... split into the same structure if/when this module grows").

---

## 14. Explicit Out-of-Scope Items

Per your instructions and this audit's findings, **not** part of this slice:

- Department, Designation, Grade, Employee, Attendance, Leave, Payroll, ESS — as
  instructed.
- **Week-off Pattern** (`WeekOffPattern` model, seed, `branch.week_off_pattern_id` FK,
  inline form `<Select>`) — Sprint 3 Task 3.1.3, a separate, later task by the doc's own
  sequencing.
- **`holiday_calendar_id` FK on `branch`** — deferred to Feature 4.1 (`holiday_calendar`
  expansion) by the sprint doc's own explicit forward-reference note.
- **Interactive geofence-radius map editor** — correctly scheduled for the Attendance
  sprint, where geofencing is actually enforced against punches. This slice only stores
  coordinates via manual number entry + static preview image.
- **PT (Professional Tax) slab computation / state-driven holiday calendar generation** —
  `state_code` is captured and validated (it's needed structurally, per FR-ORG-004), but
  no statutory computation reads it yet; that's Payroll/Holiday-Calendar territory.
- **`department.branch_id`-driven "active department" blocking check`** is *included*
  (§5.1) since it's part of FR-ORG-014 as directly implementable today via raw SQL — but
  the **employee** half of that same rule is excluded (Employee doesn't exist).
- **E2E "branch → Department picker" test** (§10) — deferred until Department ships.
- **`?legal_entity_id=` list filtering** — see §12.3, deferred pending a decision, not
  built by default in this plan.
