# Module Architecture Standard

Every business module under `src/hrms/modules/<name>/` follows the same shape.
**Spec reference:** `files/06` §3.1, `files/07` §1.

---

## 1. Standard file layout

```text
modules/<name>/
├── __init__.py
├── router.py        # HTTP — thin only
├── service.py       # Business logic — PUBLIC interface for other modules
├── repository.py    # SQLAlchemy queries only
├── models.py        # ORM models (or models/ package if >15 tables)
├── schemas.py       # Pydantic request/response (never ORM in API layer)
├── permissions.py   # Permission codes this module defines
├── events.py        # Domain events emitted/consumed
├── exceptions.py    # Module-specific AppError subclasses
├── dependencies.py  # FastAPI Depends() for this module's services
├── tasks.py         # Celery tasks owned by this module
└── tests/           # (under apps/api/tests/unit/modules/<name>/)
```

---

## 2. Layer rules (mandatory)

| Layer | Allowed | Forbidden |
|-------|---------|-----------|
| **router.py** | Parse request, call **one** service method, return schema | Business logic, SQL, direct ORM, catching domain errors |
| **service.py** | Orchestration, business rules, call repositories, emit events, audit | Raw SQL strings, HTTP concepts |
| **repository.py** | SQLAlchemy queries, tenant predicates, return ORM rows | Business rules, Pydantic schemas |
| **models.py** | Table mapping, relationships, simple computed properties | Workflow logic, validation rules |
| **schemas.py** | Input/output validation, API shapes | Database access |

### Cross-module imports

- **Allowed:** `other_module.service`, `other_module.schemas` (at API boundaries), `other_module.events`
- **Forbidden:** `other_module.repository`, `other_module.models`, `other_module.router`
- Enforced by **import-linter** — CI fails on violation (`apps/api/.importlinter`)

---

## 3. Router example (pattern)

```python
@router.post("/leave-applications", status_code=201)
async def create_leave_application(
    body: LeaveApplicationCreate,
    service: Annotated[LeaveService, Depends(get_leave_service)],
    _: Annotated[DataScope, Depends(require_permission("LEAVE.APPLICATION.CREATE"))],
) -> DataEnvelope[LeaveApplicationRead]:
    result = await service.create(body)
    return build_data_envelope(result)
```

---

## 4. Service example (pattern)

```python
class LeaveService:
    def __init__(self, session: AsyncSession, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant
        self._repo = LeaveRepository()

    async def create(self, data: LeaveApplicationCreate) -> LeaveApplicationRead:
        # business rules here
        row = await self._repo.insert(self._session, tenant=self._tenant, ...)
        await audit.record(...)  # when audit core exists
        return LeaveApplicationRead.model_validate(row)
```

---

## 5. Repository example (pattern)

```python
class LeaveRepository:
    async def list_for_employee(
        self,
        session: AsyncSession,
        *,
        tenant: TenantContext,
        employee_id: UUID,
    ) -> list[LeaveApplication]:
        # Every query includes company_id predicate; RLS is backstop
        ...
```

---

## 6. Naming conventions

| Item | Convention | Example |
|------|------------|---------|
| Package | `snake_case`, singular | `modules/leave/` |
| Service class | `<Module>Service` | `LeaveService` |
| Repository | `<Module>Repository` | `LeaveRepository` |
| ORM class | PascalCase, matches table | `LeaveApplication` |
| Pydantic | `<Entity><Purpose>` | `LeaveApplicationCreate` |
| Celery task | `<module>.<verb_noun>` | `leave.run_monthly_accrual` |
| Permission | `MODULE.RESOURCE.ACTION` | `LEAVE.APPLICATION.APPROVE` |
| Event | Past tense PascalCase | `LeaveApproved` |

---

## 7. Testing mirror

| Source | Test path |
|--------|-----------|
| `service.py` | `tests/unit/modules/<name>/test_service.py` |
| `router.py` | `tests/unit/modules/<name>/test_router.py` |
| `repository.py` | `tests/integration/modules/<name>/test_repository.py` |

Payroll, RBAC, tenancy: **≥95% coverage** (`files/05` §4).

---

## 8. Anti-patterns

- `utils.py` grab-bag → use `shared/` with a descriptive name
- Joining another module's tables in your repository → call their `service.py` or use a reporting view
- Fat routers with `if/else` business branches
- Returning ORM models from router (always map to `schemas.py`)
