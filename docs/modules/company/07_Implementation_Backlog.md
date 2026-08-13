# Company Module — Implementation Backlog

Each task is scoped to fit one AI coding session (no task spans more than a handful of files or mixes unrelated concerns), following the granularity precedent of `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md`. Tasks are numbered `C-01`…`C-16` and must be executed roughly in order — dependencies are stated explicitly per task, not just implied by number.

---

### C-01 — Fix `Company` ORM/schema drift

- **Objective:** The live SQLAlchemy `Company` model is missing columns that already exist in the deployed SQL schema (`industry_code`, `fy_start_month`, `logo_url`, `theme_json`, `onboarded_at`, `trial_ends_at`, `data_region`). Bring the model in sync — no DB change, model-only.
- **Dependencies:** None.
- **Files created:** None.
- **Files modified:** `apps/api/src/hrms/core/db/models/identity.py` (`Company` class — add the missing `Mapped[...]` columns matching existing types/defaults from `scripts/sql/001_init_schema.sql`).
- **Acceptance criteria:** `mypy --strict` passes; a fresh `alembic revision --autogenerate` against the corrected model produces **zero** diff against the current live schema (proving the model now matches reality, not the other way around).
- **Estimated complexity:** XS.
- **Testing required:** Existing model/repository unit tests still pass; no new test needed (this is a correctness fix, not new behaviour) — but add one assertion that `Company.__table__.columns` includes every column name from §2.1 of [03_Database_Design.md](03_Database_Design.md).

---

### C-02 — `organisation` module package scaffold

- **Objective:** Create the `organisation` package following `02_Module_Standard.md`'s standard layout, empty but wired in.
- **Dependencies:** C-01.
- **Files created:** `apps/api/src/hrms/modules/organisation/{__init__.py,router.py,service.py,repository.py,models.py,schemas.py,permissions.py,exceptions.py,dependencies.py,events.py,tasks.py}`; `apps/api/tests/unit/modules/organisation/__init__.py`; `apps/api/tests/integration/modules/organisation/__init__.py`.
- **Files modified:** `apps/api/src/hrms/app.py` (register the empty `organisation_router` under `/v1`, mirroring `identity_router`'s registration).
- **Acceptance criteria:** `uv run lint-imports` passes; app starts with the router mounted (returns 404 for any path — no routes yet — not a startup error).
- **Estimated complexity:** XS.
- **Testing required:** None beyond app-startup smoke test (existing pattern).

---

### C-03 — `company` table gap-fill migration

- **Objective:** Add every new column in [03_Database_Design.md §2.2](03_Database_Design.md#22-new-columns-added-by-this-design) plus the two new `CHECK` constraints (§2.1) and the two new indexes (§2.5).
- **Dependencies:** C-01 (model must be drift-free before autogenerate).
- **Files created:** `apps/api/alembic/versions/<rev>_company_profile_fields.py`.
- **Files modified:** `hrms/core/db/models/identity.py::Company` (add the new columns).
- **Database work:** `ALTER TABLE company ADD COLUMN ...` (17 new columns per §2.2), `ADD CONSTRAINT ... CHECK (...)` for `fy_start_month` and `status`, two new indexes. All additive — no data migration needed (new columns are nullable or carry a `DEFAULT`).
- **Acceptance criteria:** `alembic upgrade head` then `downgrade -1` then `upgrade head` is clean; `mypy --strict` passes on the updated model.
- **Estimated complexity:** S.
- **Testing required:** Migration up/down test (existing repository pattern).

---

### C-04 — `company_setup_progress` table

- **Objective:** New table per [03_Database_Design.md §3](03_Database_Design.md#3-company_setup_progress), with RLS.
- **Dependencies:** C-02.
- **Files created:** `apps/api/alembic/versions/<rev>_company_setup_progress.py`.
- **Files modified:** `organisation/models.py` (`CompanySetupProgress` class); the migration created above inlines `ENABLE`/`FORCE ROW LEVEL SECURITY` + `CREATE POLICY` for `company_setup_progress` directly in its own `op.execute()` block, following the pattern in `alembic/versions/20260803200000_b1_auth_audit.py`. Do **not** edit `scripts/sql/002_row_level_security.sql` — it is not invoked by any migration and is not the live RLS registry.
- **Acceptance criteria:** RLS policy present and enforced (verified in C-16's isolation suite, not here); migration up/down clean.
- **Estimated complexity:** S.
- **Testing required:** Migration up/down test only at this stage — behavioural tests land with C-10.

---

### C-05 — `plan` + `plan_feature` tables and seed data

- **Objective:** New global reference tables per [03_Database_Design.md §4–5](03_Database_Design.md#4-plan-global-reference-data--no-rls-no-company_id), plus a seed script populating an initial plan catalogue (no RLS — these are not tenant-scoped).
- **Dependencies:** C-02.
- **Files created:** `apps/api/alembic/versions/<rev>_plan_and_plan_feature.py`; a seed script under the repository's existing seed-script location (mirrors the seed-data convention in `docs/database/Database_Architecture.md` §9 — plan definitions are data, not schema).
- **Files modified:** `organisation/models.py` (`Plan`, `PlanFeature` classes).
- **Acceptance criteria:** Migration clean; seed script is idempotent (re-running it does not duplicate `plan` rows — upsert by `code`).
- **Estimated complexity:** S.
- **Testing required:** Migration up/down test; a unit test that the seed script is idempotent.

---

### C-06 — `subscription` table

- **Objective:** New table per [03_Database_Design.md §6](03_Database_Design.md#6-subscription), with RLS and the partial-unique "at most one live subscription per company" constraint.
- **Dependencies:** C-05 (FK to `plan`).
- **Files created:** `apps/api/alembic/versions/<rev>_subscription.py`.
- **Files modified:** `organisation/models.py` (`Subscription` class); the migration created above inlines `ENABLE`/`FORCE ROW LEVEL SECURITY` + `CREATE POLICY` for `subscription` directly in its own `op.execute()` block, following the pattern in `alembic/versions/20260803200000_b1_auth_audit.py`. Do **not** edit `scripts/sql/002_row_level_security.sql` — it is not invoked by any migration and is not the live RLS registry.
- **Acceptance criteria:** Inserting two non-terminal subscriptions for the same company raises a DB constraint violation (verified in C-16); migration up/down clean.
- **Estimated complexity:** S.
- **Testing required:** Migration up/down test; the constraint-violation integration test can land here or with C-16 — do not duplicate if C-16 already covers it.
- **Status:** ✅ Done.

---

### C-07 — `company_feature_flag` table

- **Objective:** New table per [03_Database_Design.md §7](03_Database_Design.md#7-company_feature_flag), with RLS.
- **Dependencies:** C-02.
- **Files created:** `apps/api/alembic/versions/<rev>_company_feature_flag.py`.
- **Files modified:** `organisation/models.py` (`CompanyFeatureFlag` class); the migration created above inlines `ENABLE`/`FORCE ROW LEVEL SECURITY` + `CREATE POLICY` for `company_feature_flag` directly in its own `op.execute()` block, following the pattern in `alembic/versions/20260803200000_b1_auth_audit.py`. Do **not** edit `scripts/sql/002_row_level_security.sql` — it is not invoked by any migration and is not the live RLS registry.
- **Acceptance criteria:** Migration up/down clean; `UNIQUE (company_id, feature_code)` enforced.
- **Estimated complexity:** XS.
- **Testing required:** Migration up/down test.
- **Status:** ✅ Done.

---

### C-08 — Company registration endpoint

- **Objective:** `POST /v1/companies/register` — the full transactional flow in [05_Backend_Architecture.md §11](05_Backend_Architecture.md#11-transactions): `User`, `Company`, `UserCompany`, `Role`/`RolePermission`/`UserRole`, `CompanySetupProgress`, optional trial `Subscription`, audit, token issuance.
- **Dependencies:** C-03, C-04, C-05, C-06 (all tables registration writes to must exist).
- **Files created:** None beyond what C-02 scaffolded.
- **Files modified:** `organisation/schemas.py` (`CompanyRegistrationRequest`, `TokenResponseData` reuse from `identity.schemas`), `organisation/service.py` (`OrganisationService.register_company`), `organisation/repository.py` (insert methods), `organisation/router.py` (the route), `organisation/permissions.py` (move `ORG_COMPANY_MANAGE` here per [05_Backend_Architecture.md §6](05_Backend_Architecture.md#6-permission-code-ownership--a-migration-decision); add `DASHBOARD_COMPANY_VIEW`), `organisation/exceptions.py` (`SubdomainTakenError`), `identity/permissions.py` (remove `ORG_COMPANY_MANAGE`, keep the string value identical), `identity/service.py` (extract a public `issue_tokens_for(user_id, company_id)` wrapper around the existing private `_issue_tokens`, if not already public — do not duplicate JWT logic), `src/hrms/seed/bootstrap.py` (`seed_b1_foundation` currently grants every code in `identity.permissions.B1_PERMISSIONS` to the demo `COMPANY_ADMIN` role and `clear_b1_seed` deletes the same list on teardown — moving `ORG_COMPANY_MANAGE` out of `identity/permissions.py` silently drops it, and the new `DASHBOARD_COMPANY_VIEW`, from both paths unless this file is updated to also seed/grant the two organisation-owned codes to the demo company; update both functions so the pre-seeded demo tenant keeps receiving `ORG.COMPANY.MANAGE` and gains `DASHBOARD.COMPANY.VIEW`).
- **Acceptance criteria:** A single `POST` call results in a fully authenticated tenant with zero manual follow-up, matching [04_API_Design.md §2](04_API_Design.md#2-post-v1companiesregister) exactly; duplicate subdomain → `409`; weak password → `422` with field detail; the pre-existing B1 demo company (`scripts/seed.py`) still has `ORG.COMPANY.MANAGE` and now also `DASHBOARD.COMPANY.VIEW` granted to its `COMPANY_ADMIN` role after this change — no regression to existing seeded fixtures; the endpoint is assigned a rate-limit bucket (reuse the existing `/v1/auth/login` bucket if one exists, otherwise the general per-IP limit) — this pins the open decision flagged in [06_Testing_Strategy.md §3](06_Testing_Strategy.md#3-security-tests-testssecurity), which C-16's rate-limit test asserts against.
- **Estimated complexity:** L.
- **Testing required:** Unit (`test_service.py` registration cases from [06_Testing_Strategy.md §1](06_Testing_Strategy.md#1-unit-tests-testsunitmodulesorganisation)) + integration (`test_registration_flow`, `test_registration_duplicate_subdomain`, `test_registration_weak_password`, `test_registration_atomicity` from §2).
- **Status:** ✅ Done. Implementation notes/deviations (see final report for full detail): `user.first_name`/`last_name` did not exist on the `user` table (neither SQL nor ORM) — added via a small additive migration, per `SPRINT_3_COMPANY_FOUNDATION.md`'s explicit anticipation of this gap. No password-strength policy existed anywhere — added a minimal one to `core/auth/passwords.py`, per the same prior art's explicit instruction. No `Plan.is_default` flag exists — `Plan.code == "FREE"` is treated as the default trial plan (best match to "for evaluating the platform" in C-05's seed data); `Subscription` creation is skipped if absent. Duplicate `admin_email` (undefined in the frozen API design) is rejected with `409 CONFLICT`, backed by the real `user_email_key` DB unique index. Built the rate-limiter (`shared/rate_limit.py`) named but never implemented in `docs/product/09_API_Standards.md` §1.9, applied only to this endpoint. `SubdomainTakenError` was not added — the frozen request schema has no `subdomain` field in V1, so it would be unreachable dead code; the generic `ConflictError` is used instead.

---

### C-09 — Company profile read/update endpoints

- **Objective:** `GET/PATCH /v1/companies/current` per [04_API_Design.md §3–4](04_API_Design.md#3-get-v1companiescurrent), including every value object, validation rule, and optimistic-locking behaviour from [02_Domain_Model.md §3 and §5](02_Domain_Model.md#3-value-objects).
- **Dependencies:** C-08 (needs a company to exist and `ORG.COMPANY.MANAGE` seeded).
- **Files created:** None.
- **Files modified:** `organisation/schemas.py` (`CompanyProfileRead`, `CompanyProfileUpdate`, and the value-object schemas — `AddressSchema`, `ContactInfoSchema`, `LocaleSchema`, `FiscalYearSchema`, `WorkingDaysPatternSchema`, `BusinessHoursSchema`, `BrandingSchema`), `organisation/service.py` (`get_company_profile`, `update_company_profile`), `organisation/repository.py` (`get_company`, `update_company`), `organisation/router.py`, `organisation/exceptions.py` (`CurrencyLockedError`, `InvalidWorkingDaysError`).
- **Decision to make during this task:** whether to deprecate/remove the existing `GET /v1/auth/companies/{id}` stub in `identity/router.py` now that profile ownership moves here — acceptable to retain temporarily for backward compatibility if anything still depends on it, but must not become the canonical read path.
- **Acceptance criteria:** All validation rules in [02_Domain_Model.md §5](02_Domain_Model.md#5-validation-rules--business-invariants) enforced; `primary_legal_entity` returns `null` (not an error) since Legal Entity doesn't exist yet; every update audited with before/after JSON; a company with `status = SUSPENDED` is write-blocked on this route per the lifecycle rule in [02_Domain_Model.md §7.1](02_Domain_Model.md#71-companystatus-state-machine) (this is a separate rule from §5 and easy to miss — tested explicitly, see [06_Testing_Strategy.md §7](06_Testing_Strategy.md#7-edge-cases)).
- **Estimated complexity:** L.
- **Testing required:** Full unit + integration coverage per [06_Testing_Strategy.md §1–2](06_Testing_Strategy.md#1-unit-tests-testsunitmodulesorganisation) for `update_company_profile`/`get_company_profile` rows.
- **Status:** ✅ Done (working tree).

---

### C-10 — Setup progress endpoint

- **Objective:** `GET /v1/companies/current/setup-progress`, the setup-step registry from [05_Backend_Architecture.md §3.1](05_Backend_Architecture.md#31-setup-step-registry-extensibility-point), with exactly one real step (`COMPANY_PROFILE`) this module's delivery.
- **Dependencies:** C-04, C-09 (needs `company_profile_is_complete` logic, which depends on the profile fields C-09 defines).
- **Files created:** None.
- **Files modified:** `organisation/schemas.py` (`CompanySetupProgressSummary`, `SetupStepDefinition`), `organisation/service.py` (`get_setup_progress`, `SETUP_STEPS` registry), `organisation/repository.py` (`company_profile_is_complete`, `get_setup_progress`, `update_setup_progress`), `organisation/router.py`.
- **Acceptance criteria:** `status` is derived from real row/field state on every read, never a stored click-flag; the registry is extensible (a fake step definition in tests proves this without editing `service.py`'s aggregation loop).
- **Estimated complexity:** M.
- **Testing required:** `test_setup_progress_derivation` (integration) + `test_service.py` registry test (unit) per [06_Testing_Strategy.md](06_Testing_Strategy.md).
- **Status:** ✅ Done (working tree).

---

### C-11 — Subscription & feature flag summary endpoint

- **Objective:** `GET /v1/companies/current/subscription` per [04_API_Design.md §6](04_API_Design.md#6-get-v1companiescurrentsubscription), including plan/company-override feature resolution.
- **Dependencies:** C-05, C-06, C-07.
- **Files created:** None.
- **Files modified:** `organisation/schemas.py` (`SubscriptionSummary`, `FeatureFlagView`), `organisation/service.py` (`get_subscription_summary`), `organisation/repository.py` (`get_active_subscription`, `get_plan_features`, `get_company_feature_flags`), `organisation/router.py`.
- **Acceptance criteria:** Feature resolution matches [02_Domain_Model.md §5.10](02_Domain_Model.md#5-validation-rules--business-invariants) exactly — `overrides_plan=true` wins even absent from the plan; a stale override never grants access once the plan changes underneath it (tested explicitly, see [06_Testing_Strategy.md §7](06_Testing_Strategy.md#7-edge-cases)).
- **Estimated complexity:** M.
- **Testing required:** `get_subscription_summary` unit tests (feature resolution matrix) + the feature-flag-vs-plan-drift edge case.
- **Status:** ✅ Done (working tree).

---

### C-12 — Company dashboard endpoint

- **Objective:** `GET /v1/dashboards/company` per [04_API_Design.md §7](04_API_Design.md#7-get-v1dashboardscompany) — `null`-safe aggregation that degrades gracefully when sibling sub-domain tables don't exist yet.
- **Dependencies:** C-10, C-11.
- **Files created:** None.
- **Files modified:** `organisation/schemas.py` (`CompanyDashboardSummary`), `organisation/service.py` (`get_dashboard_summary`), `organisation/permissions.py` (`DASHBOARD_COMPANY_VIEW` already added in C-08 — wire it to this route), `organisation/router.py`.
- **Acceptance criteria:** Count fields for non-existent sibling tables are `null`, never `0`, per the explicit distinction in [04_API_Design.md §7](04_API_Design.md#7-get-v1dashboardscompany); adding a sibling sub-domain later only requires adding one field, never restructuring the response.
- **Estimated complexity:** S.
- **Testing required:** `get_dashboard_summary` unit test asserting `null` vs. real-count behaviour.
- **Status:** ✅ Done (working tree). Frontend `/app/dashboard` consumes this endpoint (and subscription) with no fabricated metrics.

---

### C-13 — Trial expiry sweep

- **Objective:** `organisation.sweep_trial_expirations` Celery Beat task per [05_Backend_Architecture.md §5.2](05_Backend_Architecture.md#52-organisationsweep_trial_expirations-celery-beat-daily).
- **Dependencies:** C-08 (needs `trial_ends_at` populated at registration), C-09 (the version-guarded update pattern `update_company_profile` establishes, which `transition_status` follows). **Ownership note (audit finding):** `transition_status` is not built by C-09 — it is implemented by this task, alongside the sweep itself (see Files modified below); C-09 only needs to exist first so the update pattern it establishes is available to mirror.
- **Files created:** None.
- **Files modified:** `organisation/tasks.py` (`sweep_trial_expirations`), `organisation/repository.py` (`count_trials_expiring_before`), `organisation/service.py` (`transition_status`), Celery Beat schedule registration (wherever the repo's existing beat schedule is centrally defined, e.g. `core/celery_app.py`).
- **Acceptance criteria:** Idempotent — running twice against the same data produces the same end state and does not double-audit; scheduled once daily, not per-tenant-timezone (per the documented reasoning that `trial_ends_at` is an absolute instant).
- **Estimated complexity:** M.
- **Testing required:** `test_trial_expiry_sweep_idempotent` (integration).

---

### C-14 — Company settings cache

- **Objective:** Cache-aside Redis layer for the hot-path settings subset (`timezone`, `currency`, `locale`, `fiscal_year`) per [05_Backend_Architecture.md §8](05_Backend_Architecture.md#8-caching), with invalidation on update.
- **Dependencies:** C-09.
- **Files created:** None.
- **Files modified:** `organisation/service.py` (cache-aside wrapper around the settings-read path; explicit `DEL` on `update_company_profile` success).
- **Acceptance criteria:** A settings read after an update never returns stale data even within the TTL window (invalidation, not just expiry, is what's tested); cache key is namespaced per `company_id`.
- **Estimated complexity:** S.
- **Testing required:** Unit test with a fake Redis client asserting invalidation fires on update; the tenant-isolation cache-key test from [06_Testing_Strategy.md §5](06_Testing_Strategy.md#5-tenant-isolation-tests).

---

### C-15 — Domain events (`CompanyRegistered`, `CompanyProfileUpdated`)

- **Objective:** Emit the two events per [05_Backend_Architecture.md §5.3](05_Backend_Architecture.md#53-domain-events-eventspy), outbox-backed per the ADR-0012 extension-by-analogy decision.
- **Dependencies:** C-08, C-09, **and** `core/events` (the outbox mechanism) — per `docs/architecture/01_Backend_Structure.md` §1, `core/events/` is listed as "(planned B4)" and may not exist yet at the time this task is picked up.
- **Files created:** `organisation/events.py` content (`CompanyRegistered`, `CompanyProfileUpdated` event classes).
- **Files modified:** `organisation/service.py` (emit calls at the end of `register_company`/`update_company_profile`).
- **Fallback if `core/events` does not exist yet:** implement `events.py`'s classes now (harmless, no dependency), but have `service.py` call a small local no-op `emit()` shim instead of a real outbox write, clearly marked, so this task doesn't block on core infrastructure landing first — swapping the shim for the real outbox call later is a one-line change once `core/events` ships.
- **Acceptance criteria:** Events are emitted in the same transaction as the state change (once real outbox infra exists) or via the documented shim (if not); no consumer required to exist yet.
- **Estimated complexity:** S (M if `core/events` must be stood up as part of this task — flag and re-scope if so, since that would be a different, larger, core-infrastructure task outside this module's backlog).
- **Testing required:** Unit test asserting the event object's shape and that emission is called exactly once per successful operation (not on validation failure).

---

### C-16 — Cross-tenant isolation, RBAC matrix, and security test suite

- **Objective:** Cover this module's five endpoints for cross-tenant isolation, the RBAC role×endpoint matrix, and the security checks in [06_Testing_Strategy.md §2.1, §3, §4](06_Testing_Strategy.md#21-cross-tenant-isolation-blocking-every-ci-build--files15_testing_strategymd-61). **Audit finding:** no repository-wide automated cross-tenant isolation generator, data-driven permission-matrix suite, or `tests/security/` directory exists in the codebase today (verified — the only precedent is the hand-written `tests/integration/auth/test_auth_security.py`). This task is therefore hand-written tests, one function per case, following that file's existing pattern — not a generator or a new test framework. Building a repository-wide generator/matrix framework is explicitly out of scope for this module; track it separately if the org wants one later.
- **Dependencies:** C-08 through C-12 (every route must exist).
- **Files created:** `apps/api/tests/integration/modules/organisation/test_cross_tenant_isolation.py` (one hand-written test per endpoint — `GET/PATCH /companies/current`, `GET .../setup-progress`, `GET .../subscription`, `GET /dashboards/company` — each asserting tenant B's token can't read/modify tenant A's data, mirroring `test_cross_company_data_access_blocked`/`test_cross_company_header_mismatch_blocked` in `test_auth_security.py`); `apps/api/tests/integration/modules/organisation/test_permission_matrix.py` (explicit test functions for the role × endpoint table in [06_Testing_Strategy.md §4](06_Testing_Strategy.md#4-rbac-tests) — `COMPANY_ADMIN`, zero-permission user, different-company user — for each of the five routes); `apps/api/tests/security/test_organisation_security.py` (first file under `tests/security/`; hand-written cases for rate limiting, mass-assignment on `PATCH /companies/current`, the no-`{id}`-route structural check, malformed `theme_json`, and password-not-logged, per [06_Testing_Strategy.md §3](06_Testing_Strategy.md#3-security-tests-testssecurity)).
- **Files modified:** None.
- **Acceptance criteria:** Every item in [06_Testing_Strategy.md §2.1, §3, §4](06_Testing_Strategy.md#21-cross-tenant-isolation-blocking-every-ci-build--files15_testing_strategymd-61) has a corresponding hand-written test that passes; each of the five routes has an explicit isolation test and an explicit permission-matrix test (verified by reading the test file, not by an automated route count).
- **Estimated complexity:** M (reduced scope vs. the original "wire into a generator" framing — this is now module-scoped, hand-written work matching an existing pattern).
- **Testing required:** This task *is* the testing work — no separate follow-up.
- **Status:** ✅ Done (working tree) — `test_cross_tenant_isolation.py`, `test_permission_matrix.py`, `tests/security/test_organisation_security.py`.

---

## Summary Table

| Task | Complexity | Depends on | Status |
|---|---|---|---|
| C-01 Fix Company model drift | XS | — | ✅ Done |
| C-02 Module scaffold | XS | C-01 | ✅ Done |
| C-03 Company gap-fill migration | S | C-01 | ✅ Done |
| C-04 `company_setup_progress` table | S | C-02 | ✅ Done |
| C-05 `plan`/`plan_feature` tables + seed | S | C-02 | ✅ Done |
| C-06 `subscription` table | S | C-05 | ✅ Done |
| C-07 `company_feature_flag` table | XS | C-02 | ✅ Done |
| C-08 Registration endpoint | L | C-03, C-04, C-05, C-06 | ✅ Done |
| C-09 Profile read/update endpoints | L | C-08 | ✅ Done |
| C-10 Setup progress endpoint | M | C-04, C-09 | ✅ Done |
| C-11 Subscription summary endpoint | M | C-05, C-06, C-07 | ✅ Done |
| C-12 Dashboard endpoint | S | C-10, C-11 | ✅ Done |
| C-13 Trial expiry sweep | M | C-08, C-09 | ⏳ Not started |
| C-14 Settings cache | S | C-09 | ⏳ Not started |
| C-15 Domain events | S–M | C-08, C-09, (core/events) | ⏳ Not started |
| C-16 Isolation/RBAC/security tests | M | C-08…C-12 | ✅ Done |

---

## Definition of Done (module-level)

Added per audit finding — mirrors `SPRINT_3_COMPANY_FOUNDATION.md` §1's format, scoped to this module. All must be true, not "mostly true":

- [ ] C-01 through C-16 each pass their own acceptance criteria.
- [ ] `pytest`, `mypy --strict`, `ruff check`, `ruff format --check`, `uv run lint-imports` all pass in CI.
- [ ] `organisation/service.py` and `organisation/repository.py` Company-owned code carry ≥95% coverage ([06_Testing_Strategy.md](06_Testing_Strategy.md), intro).
- [ ] Every RLS-bearing table this module adds (`company_setup_progress`, `subscription`, `company_feature_flag`) has its policy enabled inline in its own migration (per the corrected guidance in C-04/C-06/C-07 and [03_Database_Design.md §8](03_Database_Design.md#8-migration-order)) and verified under `alembic upgrade head` / `downgrade -1` / `upgrade head`.
- [ ] The pre-existing B1 demo company (`scripts/seed.py`) still resolves `ORG.COMPANY.MANAGE` and `DASHBOARD.COMPANY.VIEW` for its `COMPANY_ADMIN` role after the C-08 permission move (no seed-data regression).
- [ ] All five endpoints are reachable end-to-end against a fresh database: register → `GET`/`PATCH /companies/current` → `GET .../setup-progress` → `GET .../subscription` → `GET /dashboards/company`, with zero manual DB intervention.
- [ ] C-16's hand-written cross-tenant isolation, RBAC-matrix, and security tests all pass.
- [ ] The OpenAPI schema snapshot and idempotency contract tests in [06_Testing_Strategy.md §6](06_Testing_Strategy.md#6-api-tests-contract-level) exist and pass.
- [ ] Every edge case in [06_Testing_Strategy.md §7](06_Testing_Strategy.md#7-edge-cases) has a passing test under its assigned owning task.
