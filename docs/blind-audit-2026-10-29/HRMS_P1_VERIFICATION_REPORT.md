# HRMS P1 Findings — Independent Verification (read-only)

Date: 2026-10-29 · Scope: verify P1 findings F-01, F-02, F-03 (+ F-19) and the Redis / Celery / migration questions from the blind audit. Original reports are untouched.

## 0. Method and limits

* **Done:** static reading of source, migrations, compose files, CI workflow and tests; `alembic heads` (reads migration scripts only); an offline import of the SQLAlchemy models to enumerate foreign keys from `Base.metadata` (no DB connection).
* **Not done, by instruction:** no test run, no migration, no DB/Redis connection, no request to the dev stack. **No finding below has a runtime reproduction.** "Confirmed" means confirmed by code/DDL reading; where a Postgres behaviour is relied on it is named.
* The FK enumeration comes from ORM metadata, not the live schema. Composite FKs added only by migrations (e.g. `attendance_day`) do not show in it. Treat the counts as an upper bound for the model layer and re-run `pg_constraint` against a disposable DB before acting.
* Status change since the audit: F-19 (dirty tree, untracked head migration) is resolved. Commit `f6340eb` now tracks `20261030090000_attendance_geofencing.py`.

## 1. Summary

| ID | Finding | Verdict | Confidence |
|---|---|---|---|
| V-1 | Integration suite runs as SUPERUSER/BYPASSRLS; runtime-role coverage is thin | **Confirmed** (design); impact probable | High |
| V-2 | Employee-import enqueue-failure path loses `app.company_id` before an RLS query | **Confirmed defect by code reading**; runtime outcome (500 vs silent no-op) unreproduced | High (defect), Medium (exact symptom) |
| V-3 | Tenant-owned parent/child FKs lack composite tenant constraints | **Confirmed** schema gap; exploitability unproven | High (gap), Low (exploit) |
| V-4a | Raw `X-Company-Id` sets the RLS GUC before authentication | **Confirmed**; fails closed for data access | High |
| V-4b | Header is documented optional, but `get_current_user` depends on it for the RLS membership lookup | **Probable defect** (contract vs implementation) | Medium |
| V-4c | `email_log.company_id` taken from the unverified header | **Probable**, low impact | Medium |
| V-4d | `user_role` / `role_permission` have no RLS and no tenant column | **Confirmed** (by design, undocumented risk) | High |
| V-5a | Redis has no auth; dev compose publishes it on all interfaces | **Confirmed** (dev), prod not published | High |
| V-5b | Only Leave tasks use `acks_late`; other tasks ack early; import has no recovery | **Confirmed** | High |
| V-6 | Geofencing migration is a single head, additive, committed | **Confirmed** | High |

## 2. V-1 RLS test coverage (F-01)

**Evidence**
* `apps/api/tests/conftest.py` defaults `DATABASE_URL` to `postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev`. CI sets the same (`.github/workflows/ci.yml:112,140,227`). `hrms` is the schema owner with SUPERUSER and BYPASSRLS (`tests/security/test_rls_runtime_role.py:1-17`, `infra/docker/postgres/init/002_app_role.sh`).
* `ci.yml` comment at ~line 197-208 states the choice is deliberate: switching the default to `hrms_app` produced 130 errors because fixtures do raw cross-tenant DELETE/INSERT.
* Files that actually use `hrms_app`: `tests/security/test_rls_runtime_role.py` (4 tests), `tests/security/test_geofence_rls.py` (4), `tests/security/test_db01_credential_provisioning.py` (6, credentials), `tests/integration/core/test_runtime_role_grants.py` (4, privileges), `.../payroll/test_b05_db_immutability.py` (immutability under the runtime role, includes an app-engine repoint at :68-100, :437), `.../attendance/test_b13_attendance_tenant_fk.py` (1), `.../attendance/test_face_opensource_engine.py:276-295` (RLS probe), `.../onboarding/test_invitation_compose.py:485-505` (one RLS check), `.../leave/test_leave_hardening.py:597-613` (privilege checks only, not RLS), `.../attendance/test_geofence*.py` via the security file.
* Of 302 test files, about 12 mention `hrms_app`, and only a handful run application flows under it.

**Module coverage under the runtime role (from grep, per `tests/integration/modules/*`)**

| Module | Test files | Files touching `hrms_app` | Flow run under RLS? |
|---|---|---|---|
| employee | 18 | 0 (the 4 core tests cover employee CRUD) | Partial (via security file) |
| organisation | 29 | 0 | Registration only |
| leave | 34 | 1 (privileges only) | No |
| attendance | 39 | 3 + geofence security | Geofence tables and face probe only |
| payroll | 13 | 1 (immutability) | Narrow |
| onboarding | 19 | 1 (one RLS check) | No |
| employee_import | 4 | 0 | **No** |
| account_invite | 7 | 0 | **No** |
| platform | 2 | 0 | **No** |

* **Misleading docstring:** `tests/integration/modules/attendance/test_attendance_day.py:7` says "real `hrms_app` role via the app's normal session". The file contains no role switch (only that docstring line matches `hrms_app`), and its `DATABASE_URL` is `hrms`. The test therefore runs with RLS bypassed. Confidence: high.

**Impact:** any bug that only appears when RLS is enforced (V-2 is one) passes CI. The suite also cannot detect a missing GUC or a missing tenant predicate.
**Reproduction approach (no mutation):** `SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname IN ('hrms','hrms_app')` on a disposable DB, then run one module's tests with the engine repointed. Not done.
**Remediation:** two engines in the test harness: an admin engine for fixtures/teardown and a runtime engine for the app under test. Migrate module by module, starting with the high-risk modules (employee_import, account_invite, leave, payroll). Add a CI lint that fails when a test docstring claims `hrms_app` without using it.
**Regression tests:** a parametrised "app engine is not superuser and not bypassrls" assertion in `conftest`; per-module smoke flows under `hrms_app`; a test that fails if `DATABASE_URL` for the app under test resolves to a BYPASSRLS role.

## 3. V-2 Employee import — transaction-local GUC (F-02)

**Trace**
* `core/db/session.py:53-60` `set_rls_company_id` uses `set_config('app.company_id', :id, true)`. The third argument `true` makes it transaction-local.
* `core/db/session.py:97-113` `get_session` and `core/tenancy/dependencies.py:55` set it once per request.
* `modules/employee_import/service.py:177` `await self._session.commit()` (before enqueue). This ends the transaction, so the GUC reverts.
* Failure branch `service.py:181-197`: `self._repo.update_batch_progress(...)` runs with no restore. It calls `get_batch` (`repository.py:22-29`), a SELECT on `employee_import_batch`, which has `FORCE ROW LEVEL SECURITY` and policy `company_id = current_setting('app.company_id', true)::uuid` (`alembic/versions/20260907090000_employee_bulk_import.py:48-51`). Then `commit()` at `:197`.
* The worker path is correct: `_commit_and_restore_rls` (`service.py:611-620`) is used after the claim and in `_flush_progress`. The other worker commits at `:354` and `:438` are followed by no further query.

**Outcome under `hrms_app`.** Either of these, depending on Postgres placeholder semantics (the GUC is `''` after a transaction-local set has been reverted on a connection that previously defined it, otherwise NULL):
1. `''::uuid` raises `22P02`; the `except` handler raises a `DBAPIError`, the client gets a 500 instead of the 503 `IMPORT_QUEUE_UNAVAILABLE`, and the batch stays `PENDING`.
2. The policy returns no rows; `get_batch` returns `None`, `update_batch_progress` silently returns, and the batch stays `PENDING` while the client gets the 503.

Either way the code's stated intent ("close it as FAILED") is not met under the real role. I have not reproduced which one occurs.

**Why tests do not catch it:** `tests/integration/modules/employee_import/test_import_idempotency.py` (`test_a_failed_enqueue_closes_the_batch_...`, ~line 134) runs as `hrms`; its follow-up query sets the GUC itself and the superuser bypasses RLS anyway.

**Other commit/rollback sites reviewed** (`grep -rn "\.commit()\|\.rollback()" src/hrms`):

| Site | Verdict |
|---|---|
| `identity/service.py:86,281`, `account_invite/service.py:337`, `platform/service.py:132` | Commit then raise; no further query. Safe. |
| `platform/service.py:369` | `_notify` reads `user` (not RLS); `get_company` re-sets the GUC at `:231`. Safe. |
| `attendance/face_service.py:183-190` | `_release_request_connection` / `_resume_request_transaction` restore the GUC by design. Safe if every caller resumes (not exhaustively checked). |
| `leave/service.py:183,258,335,677,734,1094`, `attendance/service.py:285,348` | `rollback()` on `IntegrityError` then raise. Safe. |
| `onboarding/email_outbox.py`, `email_sender.py:169` | Own sessions, no GUC set; see V-4c and the RLS state of `email_log` / `email_outbox` (policies not found in migrations; **not verified**). |
| `core/crypto/provisioning.py`, `pii_backfill.py` | Operational scripts; not assessed. |

**Remediation:** make the commit-then-continue pattern impossible to misuse. Options: (a) call `_commit_and_restore_rls` at `:177` and `:197`; (b) preferably, register a SQLAlchemy `after_begin` event on the session factory that re-applies the tenant GUC from a session-level `info["company_id"]`, which removes the whole bug class. **Regression tests:** an import-enqueue failure test run through `hrms_app` asserting the batch is `FAILED` and the response is 503; a unit test that a `commit()` followed by a query on an RLS table still sees the tenant.

## 4. V-3 Tenant-consistent foreign keys (F-03)

**Evidence.** ORM metadata: 303 single-column FKs; 136 link two tables that both carry `company_id` (excluding `company_id` itself). The DB-level composite FKs are the four named in the audit (`attendance_day→employee` in `20261027092000`, three in `20261030090000`). RLS `USING` checks only the child row's own `company_id`.

**Needs a composite constraint** (tenant-owned parent and child; a cross-tenant link is always a bug). Parent counts from the enumeration:

| Parent | Referencing columns | Priority |
|---|---|---|
| `employee` | 42 (leave_ledger, pay_adjustment, pay_run_employee, punch, employment, employee_assignment incl. reporting/dotted-line manager, leave_application, overtime_record, …) | High: money, leave balances, attendance |
| `pay_run`, `pay_run_employee` | 8 | High: payroll |
| `leave_type`, `leave_policy*`, `leave_application` | ~10 | High |
| `attendance_*`, `punch`, `shift*`, `work_calendar`, `weekly_off_pattern` | ~35 | Medium |
| `branch`, `department`, `designation`, `grade`, `legal_entity` | ~19 (employee_assignment, employment, pay_adjustment) | Medium |
| `salary_*`, `overtime_*`, `regularization_*`, `holiday*`, `onboarding_*`, `face_*` | remainder | Medium/Low |

**Valid without a composite constraint (global or cross-tenant by design):**
* All `*_user_id` / `created_by` / `published_by` / `actor_user_id` columns → `user` (about 55). `user` is a global identity that can belong to several companies. A tighter check would be `(company_id, user_id)` → `user_company`, optional hardening only.
* `employee.user_id → user`, `session.user_id`, `refresh_token.user_id`, `user_company.user_id` (global identity).
* `subscription.plan_id → plan` (global catalogue).
* Anything pointing at `company.id`.

**Related, separate gap (V-4d):** `user_role (role_id, user_company_id)` and `role_permission` have no `company_id` and no RLS policy (confirmed by absence in `scripts/sql/002_row_level_security.sql` and the migrations; `scripts/sql/002...sql` says they rely on the parent's RLS plus an application predicate). A role from company A can be linked to a `user_company` of company B at the DB level. Exploitability depends on the assignment endpoint validating both IDs; not verified.

**Exploitability:** not established. It requires an endpoint that accepts a foreign ID without scoping the lookup by `company_id`. That is the app-layer check the audit said it did not exhaustively verify, and I did not either.

**Remediation (staged, each reversible):** per parent, add `UNIQUE (company_id, id)`, add the composite FK as `NOT VALID`, run a pre-flight query for existing violations, then `VALIDATE CONSTRAINT`. Order by priority above. **Regression tests:** one per converted FK, executed as `hrms_app`, that inserts a child in tenant A pointing at a parent in tenant B and expects a constraint error (model it on `test_b13_attendance_tenant_fk.py` and `test_geofence_schema.py`); a metadata lint that lists any tenant→tenant FK lacking a composite sibling, with an allow-list for the valid cases above.

## 5. V-4 Tenant-context trust

**How `app.company_id` is established (verified path)**
1. `core/tenancy/middleware.py:21-28`: `TenancyMiddleware` reads the raw `X-Company-Id`, and if it parses as a UUID calls `set_tenant(TenantContext(company_id=...))`. No authentication has happened.
2. `core/db/session.py:97-107`: `get_session` reads `current_tenant_company_id()` and sets the GUC from that raw value.
3. `core/auth/dependencies.py:19-57`: `get_current_user` uses that session to read the user, the session row and `user_company` (RLS table) filtered by the **token's** company.
4. `core/tenancy/dependencies.py:15-55`: `get_tenant_context` rejects a header that differs from the token (404), re-checks membership, then re-sets the GUC from the verified id.

**V-4a (confirmed).** An unverified header drives the GUC before the token is even decoded. Impact today is contained: before step 4, the only RLS table read is `user_company`, and a mismatching GUC makes that lookup return nothing, so the request ends in a 401 (`membership_invalid`). No cross-tenant read is possible from this alone, and an unauthenticated request with no valid token reaches no data query. This is a fail-closed accident rather than a designed control; any new RLS-table read added to `get_current_user` before step 4 would run in the attacker-chosen tenant.

**V-4b (probable).** `docs/api/API_OVERVIEW.md:27` and `DATA_MODELS.md:62` say the header is optional and "the token alone selects the tenant". But with no header the GUC is never set, so under `hrms_app` the `user_company` lookup at `dependencies.py:54` sees an empty/NULL GUC (401, or a uuid cast error). Web and mobile always send the header (`apps/web/src/lib/api/client.ts:100`, `apps/mobile/lib/core/api/api_client.dart:127`), which hides it. Because tests run as `hrms`, the header-less case is never exercised under RLS. Not reproduced.

**V-4c (probable, low).** `onboarding/email_sender.py:144` writes `email_log.company_id` from `current_tenant_company_id()`, which on unauthenticated routes is the raw header. A caller can mislabel log rows with another company's id. No read impact found.

**Also:** `attendance/opensource_face/engine.py:79,160` compare/derive the tenant from the same context var. These run on authenticated routes after step 4, so they see the verified value; I did not trace every caller.

**Remediation:** derive the GUC only from verified identity: in `get_current_user` set it from the decoded token's `company_id` before the membership query, and stop `TenancyMiddleware` from populating the context var (or have it store the header only for logging). Keep the 404 on mismatch. **Regression tests (as `hrms_app`):** request with no header succeeds; header for another company returns 404 and never sets another tenant's GUC; unauthenticated request with a header performs no RLS-table query; `email_log` row gets the verified company or NULL.

## 6. V-5 Redis, Celery, scheduler

**Redis**
* `docker-compose.prod.yml:72-87`: `redis-server --appendonly yes`, no `requirepass`/ACL, network `data` only, no `ports:` (header comment lines 8-10 state this). Not reachable from outside the compose network; confirmed from the file, not from a port scan.
* `docker-compose.yml:29-43` (dev): `ports: "6380:6379"` with no bind address, so it listens on all host interfaces with no password. Dev only, but this machine's stack is the shared dev stack. Confirmed.
* `core/config/settings.py:114,722-727`: `redis_url` default `redis://localhost:6380/0`, no auth. The broker, result backend and rate-limit counters all share this Redis.

**Celery**
* `core/celery_app.py:50-70`: no global `task_acks_late`, `task_reject_on_worker_lost`, `broker_transport_options.visibility_timeout`, or default retry policy. Defaults apply: acknowledge before execution.
* `modules/leave/tasks.py:53-62`: Leave tasks are explicitly `acks_late=True`, `reject_on_worker_lost=True`, `autoretry_for=(OperationalError, InterfaceError)`, backoff 30→600 s, `max_retries=3`. These are idempotent by design (cycle keys, unique indexes).
* All other tasks (attendance, employee, health, email outbox, employee_import) use early ack and no retry: a worker crash after ack loses the message.
  * Attendance and employee sweeps are idempotent and re-fired by Beat (daily calculation covers a trailing 3 days; face deletions every 2 min), so loss is repaired by the next run.
  * `email_outbox.deliver_message` is backed by the 60 s sweep and leases; loss is repaired.
  * `employee_import.process_batch` (`employee_import/tasks.py:1-45`): early ack, no retry (deliberate, create-only), hard limit 3600 s. A worker kill after the claim leaves the batch `PROCESSING` forever; before the claim, `PENDING` with no message. Nothing in Beat resets or fails stale batches. Recovery is manual via `python -m hrms.ops.import_backlog` (read-only reconciliation, `STALE_PROCESSING` → `MANUAL_REVIEW`). Combined with V-2 the PENDING/PROCESSING cases have no automatic exit.
* Idempotency of import: `claim_pending_batch` (`repository.py:31`) is an atomic PENDING→PROCESSING, so duplicate delivery is skipped. Good.

**Scheduler**
* `docker-compose.prod.yml:209-226`: one `beat` instance, schedule file `/tmp/celerybeat-schedule` (not on a volume, so lost on container recreate). Crontab entries are not replayed for firings missed while Beat is down. The schedule is designed around this (daily idempotent windows, e.g. the accrual run window); `health.scheduler_heartbeat` plus `hrms.ops.job_health` is the detector. Whether anything alerts on a stale heartbeat in production is **not verified** (see `docs/operations/ALERTS_AND_RUNBOOKS.md`).

**Remediation:** set a Redis password (`--requirepass` or ACL users) and put it in `REDIS_URL`/broker/backend; bind dev Redis to `127.0.0.1:6380`; set `task_acks_late` + `task_reject_on_worker_lost` for idempotent tasks and an explicit `visibility_timeout` above the longest `time_limit` (3600 s for import); add a Beat task that fails `PROCESSING` import batches older than the hard limit (status transition only, never re-run). **Regression tests:** a unit test asserting each registered task declares its ack/retry policy (allow-list of exceptions); a test that the sweep marks a stale `PROCESSING` batch `FAILED` and leaves `PENDING` ones alone; a compose lint rejecting a `redis` service with `ports:` and no password.

## 7. V-6 Geofencing migration and release

**State.** `alembic/versions/20261030090000_attendance_geofencing.py`, revision `20261030090000`, down_revision `20261029090000` (`20261029090000` → `20261028090000` → `20261027092000`). `alembic heads` reports a single head. Tracked in commit `f6340eb`. Whether the dev or any other database has applied it is **unknown**; I did not connect.

**Contents:** adds 3 columns with constant defaults to `attendance_policy_version` (existing rows read `DISABLED`) and 3 CHECKs; `UNIQUE (company_id, id)` on `branch`; two new tables (`employee_workplace_authorization`, `geofence_attempt`) with composite FKs to `employee` / `branch`, `ENABLE`+`FORCE` RLS and `tenant_isolation` policies. Grants reach `hrms_app` through `ALTER DEFAULT PRIVILEGES FOR ROLE $POSTGRES_USER` in `infra/docker/postgres/init/002_app_role.sh:50-54` (verify the migration runs as that owner).

**Risks**
* Additive and backward compatible, so old code on the new schema is safe; new code on the old schema fails (missing columns/tables). Migrate first, then deploy.
* Lock cost is small but not zero: the CHECKs scan `attendance_policy_version`, and the unique constraint builds an index on `branch`, both under `ACCESS EXCLUSIVE` briefly. Tables are small in this product.
* Not re-runnable: `ADD CONSTRAINT` and `CREATE TABLE` lack `IF NOT EXISTS` (the column adds have it). Relies on transactional DDL; `alembic/env.py` was not confirmed to enable it.
* Downgrade drops `geofence_attempt` and the workplace table, destroying audit data. Treat rollback as roll-forward-only once real punches exist.
* "Append-only" attempts table is not DB-enforced: `hrms_app` holds UPDATE/DELETE via default privileges, and `test_geofence_rls.py` exercises both. Optional hardening: revoke UPDATE/DELETE from `hrms_app`, as done for payroll in B05.
* Mobile: new app builds send location; confirm the server version supports it before releasing the app.

**Safe release procedure (documented only; nothing run)**
1. Release from a clean, committed tree; CI green on that exact commit. Record the commit SHA.
2. Take and verify a Postgres backup; confirm a restore works (audit roadmap item).
3. On a **disposable copy** of production-shaped data: `alembic current`, `alembic upgrade head`, run the RLS/runtime-role tests, `alembic downgrade -1` then `upgrade head` to prove both directions.
4. Production: `alembic current` (expect `20261029090000`), stop or drain nothing yet. Run the one-off `migrate` service from `docker-compose.prod.yml:157-` explicitly, as the `hrms` owner role. Confirm `alembic current` = `20261030090000`.
5. Verify grants and RLS: `hrms_app` can `SELECT` both new tables; `pg_policies` shows `tenant_isolation` on both; `hrms_app` is still NOSUPERUSER/NOBYPASSRLS.
6. Deploy API and worker, then Beat, then web, then publish mobile builds. Geofence behaviour stays `DISABLED` until an administrator publishes a policy version, so a bad deploy changes no punch behaviour.
7. Smoke test as a tenant user under `hrms_app` (punch with geofence disabled), then enable on one pilot company.
8. Rollback: redeploy the previous app image (schema is compatible); do not downgrade the migration once geofence data exists.

## 8. Confirmed vs probable vs missing evidence

**Confirmed (by static evidence):** V-1 (default role bypasses RLS; misleading docstring), V-2 (GUC lost before RLS query on the enqueue-failure path), V-3 (136 candidate tenant→tenant FKs, only four composite), V-4a, V-4d, V-5a, V-5b, V-6 (single head, additive, committed).

**Probable (needs a runtime check):** V-2 exact symptom (500 vs silent skip), V-3 exploitability, V-4b header-less requests failing under `hrms_app`, V-4c log mislabelling.

**Missing evidence:** whether any DB has the geofence migration applied; live FK/constraint inventory; RLS state of `email_log` / `email_outbox`; whether production alerts on a stale scheduler heartbeat; whether `alembic/env.py` uses transactional DDL; every caller of `_resume_request_transaction`; role-assignment endpoint ID validation.

## 9. Minimal, dependency-ordered implementation plan (awaiting approval)

1. **Test harness (prerequisite for proving the rest).** Add an admin engine and a runtime-role engine in `tests/conftest.py`; fix the `test_attendance_day.py` docstring; add the "not superuser / not bypassrls" guard. No product code changes. *(V-1)*
2. **Reproduce V-2 and V-4b as failing tests under `hrms_app`** on a disposable stack. Records which symptom occurs. *(depends on 1)*
3. **Fix V-2:** restore the GUC at `service.py:177`/`:197`, or add the `after_begin` hook (preferred, covers the class). Re-run step 2 tests green. *(depends on 2)*
4. **Fix V-4a/b/c:** set the GUC from the verified token in `get_current_user`; stop trusting the raw header in `TenancyMiddleware`; fix `email_log` attribution. *(depends on 2)*
5. **Redis and Celery hardening (independent, can run in parallel with 3-4):** `requirepass` + URL update, bind dev Redis to loopback, ack/reject policy for idempotent tasks, `visibility_timeout`, Beat reaper for stale `PROCESSING` imports.
6. **Release the geofencing migration** with the procedure in section 7. *(independent; do after 1 so the release is checked under the runtime role)*
7. **Composite FKs, staged (V-3):** build the metadata lint and violation pre-flight first; then per-parent migrations in the order employee → payroll → leave → attendance → org structure; add role-link integrity for `user_role` (V-4d) alongside. *(depends on 1; each step independently shippable)*
8. **Roll the module-by-module runtime-role migration of the integration suite** (employee_import, account_invite, leave, payroll first) and make it a CI gate. *(continues step 1)*

No code, config, migration or test has been changed by this verification. Waiting for approval before implementing any step.
