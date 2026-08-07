# Company Module — Testing Strategy

Conforms to `docs/product/15_Testing_Strategy.md`, `docs/product/05_Development_Standards.md` §4, `docs/development/FastAPI_Development_Standards.md` §6. Company is both **RBAC/tenancy-adjacent code** (the ≥95% coverage tier applies directly — `core/tenancy` is named explicitly, and Company is the tenant root) and the module every cross-tenant isolation test's fixture data ultimately depends on, so its test bar is the highest in the codebase alongside payroll.

**Coverage targets:** `organisation/service.py` and `organisation/repository.py` Company-owned code: **≥95%**, not the general ≥80% floor — matching the explicit `core/rbac`/`core/tenancy` tier and the sprint precedent that RBAC/tenancy-gated paths (which every `ORG.COMPANY.MANAGE`-checked route is) carry the stricter bar. This is a hard CI gate: a PR touching this module without corresponding test changes is blocked, no override (`docs/product/05_Development_Standards.md` §4).

---

## 1. Unit Tests (`tests/unit/modules/organisation/`)

Mirrors `service.py`/`router.py`/`repository.py` per `02_Module_Standard.md` §7 (`repository.py`'s tests are integration-tier, per §3 below, since they need real RLS behaviour).

### `test_service.py`

| Test | Asserts |
|---|---|
| `register_company` happy path | All rows created (mocked repository calls verified), audit called with `COMPANY_REGISTERED`, token issuance delegated to `identity`, not reimplemented |
| `register_company` duplicate subdomain | Raises `SubdomainTakenError` before any row is persisted |
| `register_company` weak password | Raises `ValidationError` with `details[].field == "admin_password"` |
| `update_company_profile` — currency change while `status == "ACTIVE"` | Raises `CurrencyLockedError` ([02_Domain_Model.md §5.4](02_Domain_Model.md#5-validation-rules--business-invariants)) |
| `update_company_profile` — currency change while `status == "TRIAL"` | Succeeds |
| `update_company_profile` — invalid IANA timezone string | Raises `ValidationError` before any DB write |
| `update_company_profile` — zero working days | Raises `InvalidWorkingDaysError` |
| `update_company_profile` — `business_hours.end_time <= start_time` | Raises `ValidationError` |
| `update_company_profile` — stale `version` | Raises `ConflictError` → mapped to `409` |
| `update_company_profile` — value-object replacement semantics | Sending `address` replaces the whole object; omitting `address` entirely leaves the stored value unchanged ([02_Domain_Model.md §3](02_Domain_Model.md#3-value-objects)) |
| `get_company_profile` — no primary legal entity yet | `primary_legal_entity` is `null`, not an error |
| `transition_status` — every valid transition in the state machine | Each succeeds and calls audit with `STATUS_CHANGED` |
| `transition_status` — every invalid transition (e.g. `TERMINATED → ACTIVE`) | Raises, no row mutated |
| `get_setup_progress` — registry-driven aggregation | A fake `SetupStepDefinition` with a controllable predicate correctly flips `status` between `IN_PROGRESS`/`COMPLETE` |
| `get_subscription_summary` — feature resolution | Plan-only feature resolves `source: PLAN`; a `overrides_plan=true` company flag resolves `source: COMPANY_OVERRIDE` and wins even when the plan lacks the feature; a `overrides_plan=false` flag attempting to enable a feature outside the plan is rejected at write time (tested here, not just at the schema layer) — [02_Domain_Model.md §5.10](02_Domain_Model.md#5-validation-rules--business-invariants) |
| `get_dashboard_summary` — sibling table absent | Returns `null` for counts whose underlying repository method doesn't exist/isn't wired yet, never `0` (see [04_API_Design.md §7](04_API_Design.md#7-get-v1dashboardscompany)) |

### `test_router.py`

- Every route resolves through exactly one service call (assert via mock — no business logic leaks into the router).
- `POST /companies/register` has no permission dependency; every other route does.
- `PATCH /companies/current` without `If-Match` header → `422` (missing required header), not a silent default.
- Response bodies conform to `DataEnvelope[T]` shape for every route (schema-level contract test).

---

## 2. Integration Tests (`tests/integration/modules/organisation/`)

`httpx.AsyncClient` + Testcontainers Postgres 16 — required here specifically because several Company behaviours depend on real RLS/constraint behaviour a mocked session cannot verify (`docs/product/15_Testing_Strategy.md` §2's own stated reason for the integration tier).

| Test | Asserts |
|---|---|
| `test_registration_flow` | Full `POST /companies/register` → `Company`, `User`, `UserCompany`, `Role`, `RolePermission`, `UserRole`, `CompanySetupProgress` all exist and are correctly linked; returned access token authenticates a subsequent `GET /companies/current` call |
| `test_registration_duplicate_subdomain` | Second registration with the same `subdomain` → `409 CONFLICT`; first company's data untouched |
| `test_registration_weak_password` | → `422`, zero rows created (transaction rolled back — verified by re-querying, not just asserting the response) |
| `test_registration_atomicity` | Force a failure after `Company` insert but before `Role` insert (e.g. inject a constraint violation) → **no** `Company` row survives; proves the whole registration is one transaction, not a sequence of independently-committed steps |
| `test_company_no_rls_policy_but_scoped_by_membership` | A user with no `UserCompany` row for Company B cannot resolve Company B via `/companies/current` even with a manually-crafted `X-Company-Id` header — proves the "access control via `get_tenant_context` + membership check, not RLS" design decision ([03_Database_Design.md §2.3](03_Database_Design.md#23-why-no-company_id--rls)) actually holds under a real DB |
| `test_optimistic_locking` | Two concurrent `PATCH` requests with the same starting `If-Match`: first succeeds, second → `409 STALE_RESOURCE` with the *current* representation in the error body, not a generic message |
| `test_profile_update_audit_trail` | Successful `PATCH` produces exactly one `audit_log` row with correct `before_json`/`after_json` diffing only the changed fields |
| `test_setup_progress_derivation` | `company_profile_is_complete` flips `true`→ once required profile fields are set; `CompanySetupProgress.status` recomputation is exercised against real row state, not a mock |
| `test_subscription_partial_unique_constraint` | Attempting to insert a second non-terminal `Subscription` row for the same company → DB constraint violation surfaces as `409`, not a `500` |
| `test_trial_expiry_sweep_idempotent` | Running `sweep_trial_expirations` twice against the same expired-trial company transitions it once; the second run is a no-op (query returns zero matching rows) |
| `test_migration_up_down` | `alembic downgrade -1` then `upgrade head` is clean for every migration this module adds (existing repository-wide pattern) |

### 2.1 Cross-tenant isolation (blocking, every CI build — `docs/product/15_Testing_Strategy.md` §6.1)

Company is the seed input for this suite's own fixtures (create tenant A, tenant B), so its own endpoints must pass the **automated, OpenAPI-route-introspected** cross-tenant generator like every other endpoint — no bespoke exemption for "there's no `{id}` in the path." Specific to this module:

- `GET /companies/current` authenticated as tenant B never returns tenant A's data (trivially true since resolution is membership-based, but must still be asserted, not assumed).
- `PATCH /companies/current` with tenant B's token and an `X-Company-Id` header set to tenant A's id → `404`, not `403`, and tenant A's row is provably unmodified.
- `GET /companies/current/setup-progress`, `/subscription`, and `GET /dashboards/company` — same pattern, each independently, since each is a separate route the generator discovers via `app.routes`.

---

## 3. Security Tests (`tests/security/`)

| Test | Asserts |
|---|---|
| Rate limiting on `POST /companies/register` | Confirms whichever bucket this module's implementation assigns it to (the general per-IP limit, or the stricter "auth endpoint" bucket — [04_API_Design.md](04_API_Design.md) flags this as an open decision the implementing session must pin, and this test is what pins it in code) |
| Mass-assignment on `PATCH /companies/current` | Posting `status`, `id`, `subdomain`, or `version` in the body is ignored/rejected (`422`), never silently applied — these are exactly the fields [04_API_Design.md §4](04_API_Design.md#4-patch-v1companiescurrent) declares immutable via this route |
| IDOR on the (nonexistent) `{id}` surface | Confirms no route in this module accepts a company id as a path or query parameter that bypasses `get_tenant_context` — a structural test (route introspection), not just a behavioural one, so a future PR can't accidentally reintroduce an `{id}`-shaped route without this test failing |
| SQL injection / malformed `theme_json` | A crafted `theme_json` payload (deeply nested, huge, or containing unexpected types) is rejected by schema validation before reaching the repository, never causes a 500 |
| Password hashing | `admin_password` is never present in logs, audit `before_json`/`after_json`, or any response body — grep-style assertion against captured log/audit output in the test |

---

## 4. RBAC Tests

Company's two permission codes (`ORG.COMPANY.MANAGE`, `DASHBOARD.COMPANY.VIEW`) are asserted as part of the repository-wide, data-driven permission-matrix suite (`docs/product/15_Testing_Strategy.md` §6.2) — role × endpoint pairs:

| Role | `GET/PATCH /companies/current` | `GET .../setup-progress` | `GET .../subscription` | `GET /dashboards/company` |
|---|---|---|---|---|
| `COMPANY_ADMIN` | Allow | Allow | Allow | Allow |
| Zero-permission user (valid session, no roles) | `403` | `403` | `403` | `403` |
| User from a different company entirely | `404` (never reaches the permission check — tenant resolution fails first) | `404` | `404` | `404` |

Also: `PLATFORM.FEATURE_FLAG.MANAGE`-gated write access to feature flags is **not tested here** because the endpoint doesn't exist in V1 ([04_API_Design.md §6](04_API_Design.md#6-get-v1companiescurrentsubscription)) — noted so a future PR adding that endpoint knows to extend this table, not treat it as new territory.

---

## 5. Tenant Isolation Tests

Covered primarily by §2.1 above (the blocking automated suite). Additionally, module-specific:

- A background job run (`sweep_trial_expirations`) operating across multiple tenants never sets `app.company_id` incorrectly for one tenant's transaction while processing another's — verified by asserting each per-company update happens in its own correctly-scoped transaction, not a single unscoped bulk `UPDATE`.
- Redis cache keys (`company:settings:{company_id}`, [05_Backend_Architecture.md §8](05_Backend_Architecture.md#8-caching)) are namespaced per company id; a test asserts that invalidating tenant A's cache entry never evicts or corrupts tenant B's.

---

## 6. API Tests (contract-level)

- OpenAPI schema snapshot test — this module's five routes match a committed snapshot; a breaking diff fails CI (`docs/product/09_API_Standards.md` §8 / `docs/product/05_Development_Standards.md` §6 convention, applied to this module's contribution).
- Envelope shape — every success response is `DataEnvelope<T>`; every error response is `ErrorEnvelope` with a `code` from the set declared in [04_API_Design.md §8](04_API_Design.md#8-validation-summary) — no ad hoc error shapes.
- Idempotency — re-`GET`ting any of the four authenticated `GET` routes twice in a row returns byte-identical `data` (excluding `meta.server_time`) absent an intervening write.

---

## 7. Edge Cases

| Edge case | Expected behaviour |
|---|---|
| Two registrations racing for the same `subdomain` simultaneously | DB unique constraint is the final backstop even if the application-layer `subdomain_exists` check races — the loser gets `409`, never a duplicate row (test forces the race with concurrent DB sessions, not just sequential calls) |
| Trial expiring at exactly `sweep_trial_expirations`'s boundary instant | `trial_ends_at = now()` (equal, not less-than) is treated consistently — pin the `<` vs `<=` decision in a test, don't leave it ambiguous |
| Timezone change requested while a future module reports a locked period | Currently a documented no-op guard ([02_Domain_Model.md §5.5](02_Domain_Model.md#5-validation-rules--business-invariants)) — test asserts the hook is *called* (even though it currently always allows), so wiring in the real guard later is a one-line change verified by an existing test, not a new code path |
| Malformed/oversized `theme_json` | Rejected at the schema layer with a clear `422`, never reaches Postgres |
| `fiscal_year.start_month` out of range (`0`, `13`) | `422` before any write |
| Feature flag conflict: `overrides_plan=false` row somehow enables a feature outside the plan (e.g. the plan itself changes after the flag was written) | `get_subscription_summary`'s resolution logic re-evaluates against the *current* plan on every read, so a stale flag never silently grants access — test changes the plan underneath an existing flag and asserts the feature reports disabled |
| Concurrent `PATCH` and `transition_status` on the same company | Both go through the same `version`-guarded update path — one wins, the other gets `409`, no lost update |
| A company with `status = SUSPENDED` calling `PATCH /companies/current` | Blocked at the service layer (write-blocked per [02_Domain_Model.md §7.1](02_Domain_Model.md#71-companystatus-state-machine)) even though the caller has valid `ORG.COMPANY.MANAGE` — test distinguishes this `403`/`423` from the permission-denied case so client error messaging can differ |
