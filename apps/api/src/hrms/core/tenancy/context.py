from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantContext:
    company_id: UUID
    user_id: UUID | None = None


_tenant_var: ContextVar[TenantContext | None] = ContextVar("tenant", default=None)
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_tenant(ctx: TenantContext) -> None:
    _tenant_var.set(ctx)


def current_tenant() -> TenantContext:
    ctx = _tenant_var.get()
    if ctx is None:
        raise RuntimeError("tenant_context_missing")
    return ctx


def current_tenant_company_id() -> str | None:
    ctx = _tenant_var.get()
    return str(ctx.company_id) if ctx is not None else None


def set_request_id(request_id: str) -> None:
    _request_id_var.set(request_id)


def current_request_id() -> str | None:
    return _request_id_var.get()


def clear_context() -> None:
    _tenant_var.set(None)
    _request_id_var.set(None)
