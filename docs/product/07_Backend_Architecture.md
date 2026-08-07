# Document 07 — Backend Architecture

**Version:** 2.0 — new document. This is the detailed enterprise FastAPI architecture requested
alongside the migration: layered architecture, dependency injection, module boundaries enforcement,
event-driven patterns, and the mechanics of tenancy/audit/error handling inside a single Python
codebase serving 500+ APIs across 20+ modules. Folder layout is Document 06; system-level
deployables and request lifecycle are Document 03; this document is what lives *inside* the boxes
in Document 03's diagram.

---

## 1. Layered Architecture

Every module (Document 06 §3.1) has four layers, each with one job:

```
┌─────────────────────────────────────────────────────────────┐
│  router.py         HTTP concern only: parse request, call    │
│                     ONE service method, shape the response.   │
│                     No business logic. No direct DB access.   │
├─────────────────────────────────────────────────────────────┤
│  service.py        Business logic. Orchestrates repositories, │
│                     emits domain events, enforces business     │
│                     rules that span more than one query.       │
│                     This is the module's PUBLIC interface —    │
│                     the only thing another module may import.  │
├─────────────────────────────────────────────────────────────┤
│  repository.py     Query layer. All SQLAlchemy queries for      │
│                     this module's tables live here and ONLY     │
│                     here. Returns ORM models or lightweight      │
│                     query-result objects — never Pydantic         │
│                     schemas (that translation happens in           │
│                     service.py or router.py).                       │
├─────────────────────────────────────────────────────────────┤
│  models.py          SQLAlchemy declarative models. Pure data       │
│                      shape + relationships + constraints.           │
│                      No behaviour beyond simple computed              │
│                      properties.                                       │
└─────────────────────────────────────────────────────────────┘
```

**Why a repository layer at all, when SQLAlchemy already is an abstraction over SQL:** the
repository layer is not there to make the database swappable (it won't be — this is a PostgreSQL-
specific design, per Document 04 §2, using RLS, exclusion constraints and partitioning that don't
port to another engine). It exists so that **every query enforcing tenant and data-scope predicates
lives in one place per module**, reviewable and testable in isolation, rather than scattered across
service methods where a missing `WHERE company_id = ?` is one careless line away (Document 03 §2.1).
A repository method's signature makes the tenant/scope contract explicit:

```python
class LeaveRepository:
    async def list_pending_for_approver(
        self,
        session: AsyncSession,
        *,
        tenant: TenantContext,          # carries company_id — cannot be omitted, it's positional-required
        approver_employee_id: UUID,
    ) -> list[LeaveApplication]:
        ...
```

A repository method that does not accept a `TenantContext` is a code-review red flag and, for
list/detail queries, is caught mechanically by the cross-tenant leakage suite (Document 15 §6).

---

## 2. Dependency Injection Strategy

FastAPI's `Depends()` system **is** the dependency injection mechanism — no third-party DI
container (e.g. `dependency-injector`) is used, deliberately: FastAPI's native DI already solves
constructor injection, request-scoped lifetimes, and testability via `app.dependency_overrides`,
and adding a second DI framework on top would be exactly the kind of unnecessary complexity this
migration is trying to remove (Document 01 §2).

### 2.1 The Dependency Chain for a Typical Endpoint

```python
# core/db/session.py
async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session

# core/tenancy/dependencies.py
async def get_tenant_context(
    x_company_id: Annotated[UUID, Header(alias="X-Company-Id")],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TenantContext:
    # Validates X-Company-Id against user_company membership (404 on mismatch — Document 09 §1.4)
    # Sets SET LOCAL app.company_id on the session's current transaction (Document 03 §2.1)
    ...

# core/rbac/dependencies.py
def require_permission(code: str) -> Callable:
    async def _check(
        tenant: Annotated[TenantContext, Depends(get_tenant_context)],
        rbac: Annotated[RbacService, Depends(get_rbac_service)],
    ) -> DataScope:
        if not await rbac.has_permission(tenant, code):
            raise PermissionDeniedError(code)
        return await rbac.resolve_data_scope(tenant, code)
    return _check

# modules/leave/service.py
class LeaveService:
    def __init__(self, session: AsyncSession, tenant: TenantContext) -> None:
        self._repo = LeaveRepository()
        self._session = session
        self._tenant = tenant
    ...

def get_leave_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
) -> LeaveService:
    return LeaveService(session, tenant)

# modules/leave/router.py
@router.get("/leave-applications/{id}")
async def get_leave_application(
    id: UUID,
    scope: Annotated[DataScope, Depends(require_permission("LEAVE.VIEW_TEAM"))],
    service: Annotated[LeaveService, Depends(get_leave_service)],
) -> LeaveApplicationRead:
    return await service.get(id, scope)
```

This is the FastAPI-native realisation of the request lifecycle in Document 03 §1.3: each numbered
step in that pipeline is either a `Depends()` in this chain or the ASGI tenancy middleware that runs
before dependency resolution even starts (§5 below).

### 2.2 Service Lifetimes

All services and repositories are **request-scoped** (a fresh instance per request, via `Depends`
without `use_cache` tricks beyond FastAPI's default per-request caching of a given dependency
callable). There are no singleton services holding mutable state — the only long-lived,
shared-across-requests objects are the SQLAlchemy engine (connection pool) and the Redis client,
both created once at app startup (`app.py` lifespan handler) and injected via `Depends` that read
from `app.state`.

### 2.3 Testability

Because every cross-cutting concern (session, tenant, permission, current user) is a `Depends`,
tests override exactly what they need via `app.dependency_overrides[get_current_user] = lambda: fake_user`
without monkeypatching or a mock framework reaching into module internals — this is a deliberate
enabler for the testing organisation in Document 15 §2.

---

## 3. Module Boundaries — Enforcement Mechanics

The rules (Document 03 §3, Document 06 §3.1) are enforced by **`import-linter`**, configured in
`.importlinter` at the repo root:

```ini
[importlinter]
root_package = hrms

[importlinter:contract:1]
name = Modules may not import each other's internals
type = forbidden
source_modules =
    hrms.modules
forbidden_modules =
    hrms.modules
allow_indirect_imports = False
# A more precise per-module contract set (below) allows the *public* surface
# (service.py, schemas.py, events.py, permissions.py) while forbidding the rest.

[importlinter:contract:2]
name = Modules may only depend on core and shared
type = layers
layers =
    hrms.modules
    hrms.shared
    hrms.core
```

In practice this is expressed as a generated set of per-module contracts (one per module pair that
has a legitimate dependency, e.g. `payroll` legitimately depends on `employee.service` and
`attendance.service`) rather than a single blanket rule — the exact contract list is maintained in
`.importlinter` and reviewed whenever a new cross-module dependency is introduced. **A new
cross-module dependency is itself a design decision** that should prompt the question "should this
be a direct call, or a domain event?" (§7) before it's added to the allow-list.

CI runs `lint-imports` as a required check; a violation fails the build with the exact forbidden
import path in the failure message — this is what makes the boundary a fact about the codebase, not
a convention that erodes over time (the failure mode the original Document 03 v1.0 explicitly
called out as the reason to make this a CI gate rather than a lint suggestion).

---

## 4. Cross-Cutting Middleware vs Dependencies

| Concern | Implemented as | Why |
|---|---|---|
| Tenant context resolution & `SET LOCAL app.company_id` | ASGI middleware (`TenancyMiddleware`) wrapping the whole app, **plus** a `Depends(get_tenant_context)` that reads what the middleware resolved | The `company_id` must be available before route matching for the ingestion app's device-key auth path (which doesn't go through the normal user-JWT dependency chain), so the initial resolution happens in middleware; the typed, injectable `TenantContext` object is then exposed to routes via `Depends` for ergonomic, testable access. |
| Request ID propagation | ASGI middleware, sets a `contextvars.ContextVar`, read by the logging formatter and included in every log line and error response | Needed before any application code runs, including error handlers for requests that fail before reaching a route. |
| CORS, security headers, GZip | Starlette's built-in middleware classes, configured in `app.py` | No custom code needed; these are solved problems. |
| Authentication (JWT verification) | `Depends(get_current_user)` | Not middleware, because public endpoints (careers page, webhook receivers, device ingestion) must skip it entirely — a dependency that's simply not included in those routers' dependency list is cleaner than a middleware with allow-list exceptions. |
| Permission / data-scope checks | `Depends(require_permission(code))`, applied per-route | Must be declarative and visible in the route signature — the same reason Document 09 §6 requires every endpoint to declare its permission explicitly; a middleware-based approach would make this invisible at the route definition. |
| Audit logging | `Depends` for read-path sensitive-access logging (runs synchronously, cheap) **and** a Celery task enqueued from the service layer for write-path audit entries (before/after diff, Document 08 §11) | Mutations need the before/after state that only the service layer has after the write completes; making this async keeps write latency off the audit path while still guaranteeing delivery via the outbox pattern (ADR-0012). |

---

## 5. Multi-Tenancy: The `contextvars` Detail

This is the one place the language change requires materially different plumbing than the original
NestJS design, so it's worth stating precisely. NestJS's request-scoped providers (backed by
Node's `AsyncLocalStorage`) gave every downstream call implicit access to "the current tenant"
without threading it through every function signature. Python's `asyncio` has an equivalent
primitive — `contextvars.ContextVar` — which correctly propagates across `await` boundaries within
a single request's coroutine chain (unlike a plain module-level global, which would leak state
across concurrent requests sharing the same worker process).

```python
# core/tenancy/context.py
_tenant_var: ContextVar[TenantContext | None] = ContextVar("tenant", default=None)

def set_tenant(ctx: TenantContext) -> None:
    _tenant_var.set(ctx)

def current_tenant() -> TenantContext:
    ctx = _tenant_var.get()
    if ctx is None:
        raise RuntimeError("No tenant context set — this code path must run inside a request")
    return ctx
```

`TenancyMiddleware` sets this at the start of each request; the SQLAlchemy session's `begin()` event
hook reads it to issue `SET LOCAL app.company_id` on every new transaction (Document 03 §2.1). The
explicit `TenantContext` parameter threaded through repository method signatures (§1) is **preferred
practice within `service.py`/`repository.py`** for testability and clarity even though `current_tenant()`
is available implicitly — implicit context access is reserved for framework-level code (the session
hook, the audit dependency) where threading an explicit parameter isn't practical.

**Celery tasks do not have an ambient request context.** A task that needs tenant context receives
`company_id` as an explicit task argument and constructs a `TenantContext` at the start of the task
body — this is a deliberate, enforced difference from the request path, and it's why every Celery
task signature in this codebase takes `company_id` as its first argument (Document 11 §2).

---

## 6. Shared Services & Common Utilities (`shared/`)

| Component | Purpose |
|---|---|
| `shared/value_objects/money.py` | `Money` value object: integer minor units + `currency`, arithmetic operators that refuse to silently mix currencies, no implicit float conversion (ADR-0006, unchanged). |
| `shared/value_objects/date_range.py`, `effective_period.py` | Effective-dating primitives used across Employee, Payroll, Leave (Document 08 §1.2, ADR-0003). |
| `shared/pagination.py` | Cursor pagination (mandatory for `punch`, `audit_log`, `notification_log` — Document 09 §1.5) and offset pagination helpers, shared response envelope builders. |
| `shared/files/` | S3/MinIO client wrapper (`aioboto3`), presigned URL generation, virus-scan trigger hook. |
| `shared/notifications_client/` | The interface modules use to *request* a notification (`await notify(event_code, recipients, context)`) — a thin call into `modules/notification`'s public service, kept in `shared/` only because nearly every module needs it and importing `modules.notification.service` directly from 20 other modules would clutter the import-linter contract list for no benefit; this wrapper still ultimately delegates to `notification`'s public service, so the module boundary is not actually bypassed. |
| `shared/testing/` | Pytest fixture base classes, factory-boy-style object factories used across module test suites (Document 15 §2, §7). |

**What does not belong in `shared/`:** anything that encodes a business rule specific to one domain
(e.g. a leave-day-counting function belongs in `modules/leave/`, not `shared/`, even if it looks
generically useful — Document 06 §6).

---

## 7. Domain Events & Event-Driven Patterns

Unchanged in design from Document 03 v1.0 §4.1 — the catalogue of events (`EmployeeJoined`,
`LeaveApproved`, `PayRunFinalised`, etc.) is stack-independent and reproduced here with its
implementation mechanics:

```python
# core/events/base.py
class DomainEvent(BaseModel):
    event_id: UUID
    event_type: str            # "leave.approved"
    company_id: UUID
    occurred_at: datetime
    payload: dict[str, Any]

# core/events/outbox.py
async def publish(session: AsyncSession, event: DomainEvent) -> None:
    """Writes to outbox_event in the SAME transaction as the business write.
    A separate Celery Beat-scheduled task polls outbox_event and dispatches
    to Celery task queues, marking rows published. This is the outbox pattern
    (ADR-0012) — never publish directly from the request path for anything
    touching money or compliance."""
    session.add(OutboxEvent(event_type=event.event_type, payload=event.payload, ...))
```

**Consumption:** a module subscribes to an event by registering a Celery task against the event
type in its `events.py`, e.g. `modules/attendance/events.py` registers a handler for
`leave.approved` that triggers attendance recompute. The dispatcher (a small piece of `core/events/`
infrastructure) looks up registered handlers by event type and enqueues one Celery task per
handler — this is the `group` fan-out pattern noted in Document 04 §3.

**When to use an event vs a direct service call:** per Document 03 §3, a direct call
(`await employee_service.get(...)`) is appropriate for synchronous reads within the same request
where the caller needs the result immediately. An event is appropriate when the side effect is
naturally asynchronous, can tolerate eventual consistency of at most a few seconds, and — critically
— when using an event lets the emitting module avoid depending on the consuming module at all
(`leave` does not need to know `attendance` exists; it just emits `LeaveApproved`). This second
property is usually the deciding one: it's what keeps the module boundary graph from becoming a
tangle as the module count grows past 20.

---

## 8. Error Handling

| Layer | Behaviour |
|---|---|
| Domain/business errors | Each module defines exceptions in `exceptions.py` subclassing a small hierarchy in `core/errors/` (`NotFoundError`, `ValidationError`, `ConflictError`, `PermissionDeniedError`, `LockedError`, ...). Business logic raises these; it never returns error tuples or `None`-means-error. |
| HTTP translation | A single set of FastAPI exception handlers, registered once in `app.py`, maps the `core/errors/` hierarchy to the HTTP status codes and error envelope defined in Document 09 §1.3/§1.4. Individual routers **never** catch-and-translate errors themselves — this is what keeps the error envelope consistent across 500+ endpoints without 500 copies of the same `try/except`. |
| Unexpected exceptions | A catch-all handler logs the full traceback (with request ID, tenant, user — PII-redacted per Document 14), returns a generic `500` envelope with no internal detail leaked, and reports to Sentry with the same request ID for correlation. |
| Validation errors | Handled natively by FastAPI/Pydantic for request-shape errors (`422`, standard envelope); business-rule validation (e.g. "insufficient leave balance") raises a domain `ValidationError` with a machine-readable `code`, translated the same way as any other domain error. |

---

## 9. Audit Logging

Implementation of the audit requirements in Document 02 BR-04/BR-09 and the `audit_log` table
(Document 08 §11):

- **Write-path:** every service method that mutates a business record calls
  `await audit.record(entity_type, entity_id, action, before, after)` as its last step, inside the
  same transaction where feasible, or via the outbox pattern (§7) where the mutation itself is
  processed asynchronously (e.g. a Celery-task-driven payroll finalisation). This is not optional
  boilerplate the developer might forget — a `service.py` method decorated as a "mutating operation"
  without a corresponding audit call is caught by a static check in CI (a small custom `ast`-based
  lint rule, documented in `core/audit/README.md`).
- **Read-path (sensitive access):** `Depends(require_permission(...))` for a `RESTRICTED`-classified
  field (Document 19 §6) additionally enqueues a lightweight `sensitive_access_log` write — this is
  cheap and synchronous because it's a single-row insert, not a diff computation.
- **Immutability:** `audit_log` and `sensitive_access_log` are append-only at the application layer
  (no `service.py` anywhere exposes an update/delete for them) and, as defence in depth, the
  database role the application connects as has no `UPDATE`/`DELETE` grant on either table
  (Document 14 §3).

---

## 10. Versioning Strategy

- **API versioning** is path-based (`/v1/...`), per Document 09 §7 — this document does not repeat
  those rules, only notes the code-organisation consequence: a breaking `/v2` would live as a
  parallel `router.py` (or a parallel module tree) rather than branching logic inside a single
  router, keeping the migration period's two versions independently testable.
- **Workflow definition versioning** (Document 20 §1) and **statutory master versioning**
  (Document 08 §8.3) are *data* versioning, not code versioning — both are effective-dated rows,
  consistent with the "configuration over code" principle (Document 01 §3).
- **Database migration versioning** is Alembic's linear revision history (Document 08 §14) — always
  forward-only, expand/contract for anything destructive, exactly as in the original design.

---

## 11. Multi-Tenancy Approach — Summary Cross-Reference

The full multi-tenancy design (RLS policies, tenant tiers, connection resolver) is Document 03 §2.
This document's contribution is the `contextvars` propagation mechanics (§5 above) and the
dependency-chain wiring (§2) that connects the middleware-resolved tenant to every downstream
repository call.

---

## 12. Testing Organisation — Pointer

Full testing strategy, coverage targets, and the golden-dataset payroll methodology are in
Document 15. This document's contribution is structural: the 1:1 mapping between `src/hrms/` and
`tests/` (Document 06 §4) and the FastAPI `dependency_overrides` mechanism (§2.3 above) that makes
each layer in §1 independently testable — a `service.py` unit test can override
`get_session`/`get_tenant_context` with in-memory fakes without spinning up Postgres, while an
integration test uses the real `AsyncSession` against a Testcontainers-managed Postgres instance to
verify the repository layer's actual SQL, including RLS behaviour.
