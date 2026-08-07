# FastAPI Development Standards

**Operational guide for daily development.**  
**Canonical standard:** `docs/product/05_Development_Standards.md`

---

## 1. Python style

| Rule | Enforcement |
|------|-------------|
| Python 3.12+ | `pyproject.toml` `requires-python` |
| Type hints on all function signatures | `mypy` strict on `src/hrms` |
| Formatting | `ruff format` |
| Linting | `ruff check` (E, F, I, N, B, UP, BLE, TRY) |
| Naming | `snake_case` functions/modules, `PascalCase` classes, `SCREAMING_SNAKE` constants |
| No bare `except` | Catch specific exceptions; `raise ... from e` when wrapping |
| No mutable default args | Ruff B006 |

---

## 2. Project layout rules

| Rule | Detail |
|------|--------|
| Backend root | `apps/api/` only — no second Python app |
| Package | `src/hrms/` — installable via `uv sync` |
| New module | `modules/<name>/` per [Module Standard](../architecture/02_Module_Standard.md) |
| No `utils.py` | Use `shared/<descriptive_name>.py` |
| Entrypoints | Thin — only composition, no business logic |
| Dependencies | Add via `uv add`; justify in PR; pin in `uv.lock` |

---

## 3. Error handling

| Layer | Rule |
|-------|------|
| Domain | Raise `core/errors` subclasses (`NotFoundError`, `ValidationError`, …) |
| HTTP mapping | **Only** global handlers in `core/errors/handlers.py` |
| Router | Never build error JSON manually |
| Unexpected | Log + Sentry + generic 500 envelope (no stack trace to client) |

Envelope format: `docs/product/09` §1.3 — `ErrorEnvelope` with `code`, `message`, `details`, `request_id`.

---

## 4. Logging

- **structlog** JSON to stdout (`core/observability/logging.py`).
- Every log line includes `request_id` via `contextvars`.
- Celery tasks: pass `company_id`, `task_id` in log context.
- Never log passwords, tokens, PAN, Aadhaar, full bank account.

---

## 5. API response format

Success:

```json
{
  "data": { ... },
  "meta": { "request_id": "...", "server_time": "..." }
}
```

Use `DataEnvelope[T]` / `ListEnvelope[T]` from `shared/pagination.py`.

---

## 6. Testing rules

| Rule | Target |
|------|--------|
| Framework | pytest + pytest-asyncio + httpx ASGI client |
| Coverage | ≥80% overall; **≥95%** payroll, leave accrual, attendance, RBAC, tenancy |
| Mirror paths | `tests/unit/modules/<name>/test_*.py` matches `src/hrms/modules/<name>/` |
| Integration | Testcontainers Postgres/Redis for repository + RLS tests |
| Security | `tests/security/` — cross-tenant leakage on every CI build (planned B1) |
| Payroll/RBAC PRs | Must include test changes — hard gate |

---

## 7. Migration rules

- **Alembic only** — never Prisma or hand-applied prod SQL without migration file.
- Review: locking, reversibility, RLS for new tenant tables.
- Expand-contract for column drops/renames.
- No destructive migration during payroll blackout (25th–5th) unless hotfix.

---

## 8. Module boundaries

- Run `uv run lint-imports` before push.
- Cross-module: service calls or domain events — not repository imports.
- New cross-module dependency = design decision + import-linter allow-list update.

---

## 9. Code review checklist (solo / AI-assisted)

- [ ] Matches [Module Standard](../architecture/02_Module_Standard.md)
- [ ] Tenant `company_id` on all list/detail repository queries
- [ ] Mutations audited (when audit core exists)
- [ ] Tests added/updated for changed `service`/`router`/`repository`
- [ ] Alembic migration if schema changed (+ RLS SQL if tenant table)
- [ ] No secrets in code or committed `.env`
- [ ] OpenAPI still valid (`/docs` smoke check)
- [ ] Permission declared on every new endpoint (`permissions.py` + `Depends`)
- [ ] ADR if architectural decision changed

---

## 10. CI gates (`.github/workflows/ci.yml`)

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/hrms
uv run lint-imports
uv run pytest
```

---

## 11. Related

- [AI Coding Guidelines](AI_Coding_Guidelines.md)
- `docs/product/09_API_Standards.md`
- `apps/api/README.md`
