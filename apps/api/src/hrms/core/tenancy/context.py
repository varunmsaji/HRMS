from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantContext:
    company_id: UUID
    user_id: UUID | None = None


_tenant_var: ContextVar[TenantContext | None] = ContextVar("tenant", default=None)
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
#: Per-request mutable holder created by `RequestContextMiddleware`. `BaseHTTPMiddleware` layers
#: (Tenancy, SecurityHeaders) run the downstream app in a child task with a *copy* of the
#: context, so a `ContextVar.set` made by a route dependency is invisible to the outermost
#: middleware. The holder dict itself is shared by reference across those copies, which lets the
#: outermost error logger see the verified tenant of a request that crashed.
_request_holder_var: ContextVar[dict[str, Any] | None] = ContextVar("request_holder", default=None)


def set_tenant(ctx: TenantContext) -> None:
    _tenant_var.set(ctx)
    holder = _request_holder_var.get()
    if holder is not None and ctx.user_id is not None:
        # Only a membership-verified context (`get_tenant_context` sets `user_id`) is recorded
        # for logging — never the raw, unverified `X-Company-Id` header value.
        holder["verified_tenant"] = ctx


@contextmanager
def tenant_scope(ctx: TenantContext | None) -> Iterator[None]:
    """Runs a block under `ctx` (or with no tenant) and restores whatever was set before. For code
    that acts for a tenant outside a request (the e-mail outbox worker): the e-mail ledger reads the
    tenant from this context."""
    token = _tenant_var.set(ctx)
    try:
        yield
    finally:
        _tenant_var.reset(token)


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


def verified_tenant_for_logging() -> TenantContext | None:
    """The membership-verified tenant of the current request, visible from any layer of the
    middleware stack (see `_request_holder_var`). `None` before verification or outside a
    request."""
    holder = _request_holder_var.get()
    if holder is not None:
        verified = holder.get("verified_tenant")
        if isinstance(verified, TenantContext):
            return verified
    ctx = _tenant_var.get()
    return ctx if ctx is not None and ctx.user_id is not None else None


def clear_tenant() -> None:
    _tenant_var.set(None)


def clear_context() -> None:
    _tenant_var.set(None)
    _request_id_var.set(None)


RequestContextSnapshot = tuple[TenantContext | None, str | None, dict[str, Any] | None]


def snapshot_request_context() -> RequestContextSnapshot:
    """Captures the current values and installs a fresh per-request holder."""
    snapshot = (_tenant_var.get(), _request_id_var.get(), _request_holder_var.get())
    _request_holder_var.set({})
    return snapshot


def reset_request_context(snapshot: RequestContextSnapshot) -> None:
    tenant, request_id, holder = snapshot
    _tenant_var.set(tenant)
    _request_id_var.set(request_id)
    _request_holder_var.set(holder)
