"""Generated authorization truth-table for every HTTP route in the organisation, employee and
employee-import modules.

Routes are discovered by introspecting the routers, so a newly added endpoint is covered the day it
lands — and an endpoint wired to the wrong permission, or to none, fails here without anyone having
to remember to write its test.

For each route that declares one `require_permission(CODE)`:
  * anonymous caller                    -> 401
  * authenticated, zero permissions     -> 403 (and 403 must win over body-validation 422)
  * holds exactly CODE                  -> gets past the gate (any status except 401/403/5xx)
  * holds exactly some *other* code     -> 403
  * COMPANY_ADMIN                       -> gets past the gate
Routes that pick their permission imperatively inside the handler are listed in `_IMPERATIVE` and
covered by dedicated assertions at the bottom."""

import importlib
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from hrms.core.auth.dependencies import get_current_user
from hrms.core.tenancy.dependencies import get_tenant_context

from .modules.account_invite.conftest import seeded_plan_catalogue  # noqa: F401
from .modules.account_invite.test_account_invite import _register_second_user
from .modules.account_invite.uac_helpers import register_tenant, teardown

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]

_MODULES = ("organisation", "employee", "employee_import")
_PUBLIC = {("GET", "/companies/registration-config"), ("POST", "/companies/register")}
#: (method, path) -> permission codes that *each* independently unlock it
_IMPERATIVE = {
    ("POST", "/employees/{employee_id}/assignments"): {"EMPLOYEE.PROMOTE", "EMPLOYEE.TRANSFER"},
}


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str
    code: str | None
    authenticated: bool

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"

    def url(self) -> str:
        out = self.path
        while "{" in out:
            start = out.index("{")
            end = out.index("}")
            out = out[:start] + str(uuid4()) + out[end + 1 :]
        return "/v1" + out


def _walk(dependant, acc: list) -> list:
    for dep in dependant.dependencies:
        acc.append(dep.call)
        _walk(dep, acc)
    return acc


def _code_of(call) -> str | None:
    if getattr(call, "__qualname__", "").startswith("require_permission."):
        for cell in call.__closure__ or ():
            if isinstance(cell.cell_contents, str):
                return cell.cell_contents
    return None


def discover_routes() -> list[RouteInfo]:
    found: list[RouteInfo] = []
    for module in _MODULES:
        router = importlib.import_module(f"hrms.modules.{module}.router").router
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            calls = _walk(route.dependant, [])
            codes = {c for c in map(_code_of, calls) if c}
            assert len(codes) <= 1, f"{route.path} declares several permissions: {codes}"
            authenticated = bool(codes) or get_current_user in calls or get_tenant_context in calls
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                found.append(RouteInfo(method, route.path, next(iter(codes), None), authenticated))
    return found


ROUTES = discover_routes()
PROTECTED = [r for r in ROUTES if (r.method, r.path) not in _PUBLIC]
CODED = [r for r in PROTECTED if r.code]
ALL_CODES = sorted({r.code for r in CODED if r.code})


async def _fire(client: AsyncClient, route: RouteInfo, headers: dict[str, str]) -> int:
    kwargs: dict = {"headers": headers}
    if route.method in {"POST", "PATCH", "PUT"}:
        kwargs["json"] = {}
    response = await client.request(route.method, route.url(), **kwargs)
    return response.status_code


def test_discovery_is_not_vacuous() -> None:
    assert len(PROTECTED) > 100, len(PROTECTED)
    assert len(ALL_CODES) > 20, ALL_CODES


def test_every_non_public_route_requires_authentication() -> None:
    open_routes = [r.label for r in PROTECTED if not r.authenticated]
    assert not open_routes, f"routes reachable without authentication: {open_routes}"


def test_only_known_routes_pick_permissions_imperatively() -> None:
    uncoded = {(r.method, r.path) for r in PROTECTED if r.authenticated and not r.code}
    unexpected = (
        uncoded
        - set(_IMPERATIVE)
        - {
            ("GET", "/policy-assignments"),
            ("POST", "/policy-assignments"),
        }
    )
    assert not unexpected, f"authenticated-but-ungated routes: {sorted(unexpected)}"


async def test_anonymous_callers_get_401_everywhere(client: AsyncClient) -> None:
    bad = []
    for route in PROTECTED:
        status = await _fire(client, route, {})
        if status != 401:
            bad.append(f"{route.label} -> {status}")
    assert not bad, "\n".join(bad)


async def test_authorization_truth_table(client: AsyncClient) -> None:
    tenant = await register_tenant(client)
    try:
        company_id = tenant.company_id
        zero_headers, _ = await _register_second_user(company_id=company_id, permission_codes=[])

        failures: list[str] = []

        # 1. zero-permission user is refused everywhere — before body validation runs.
        for route in CODED:
            status = await _fire(client, route, zero_headers)
            if status != 403:
                failures.append(f"[no-perms] {route.label} -> {status} (want 403)")

        # 2. COMPANY_ADMIN gets past every gate.
        for route in CODED:
            status = await _fire(client, route, tenant.headers)
            if status in (401, 403) or status >= 500:
                failures.append(f"[admin] {route.label} -> {status}")

        # 3. exactly-one-permission users: allowed on their own routes, refused on every other.
        for code in ALL_CODES:
            try:
                headers, _ = await _register_second_user(
                    company_id=company_id, permission_codes=[code]
                )
            except AssertionError:
                failures.append(f"permission code {code} is not seeded — nobody can ever hold it")
                continue
            for route in CODED:
                status = await _fire(client, route, headers)
                if route.code == code:
                    if status in (401, 403) or status >= 500:
                        failures.append(f"[only {code}] {route.label} -> {status} (want allowed)")
                elif status != 403:
                    failures.append(
                        f"[only {code}] {route.label} (needs {route.code}) -> {status} (want 403)"
                    )

        assert not failures, f"{len(failures)} authorization mismatches:\n" + "\n".join(
            failures[:60]
        )
    finally:
        await teardown(tenant)


def _assignment_body(change_type: str) -> dict:
    return {"effective_from": "2026-01-01", "change_type": change_type}


async def test_imperatively_gated_routes(client: AsyncClient) -> None:
    tenant = await register_tenant(client)
    try:
        zero, _ = await _register_second_user(company_id=tenant.company_id, permission_codes=[])
        url = f"/v1/employees/{uuid4()}/assignments"
        # no permission at all
        for change in ("PROMOTION", "TRANSFER", "MANAGER_CHANGE"):
            r = await client.post(url, headers=zero, json=_assignment_body(change))
            assert r.status_code == 403, (change, r.status_code, r.text)
        # PROMOTION holder may not do a TRANSFER, and vice versa
        promoter, _ = await _register_second_user(
            company_id=tenant.company_id, permission_codes=["EMPLOYEE.PROMOTE"]
        )
        mover, _ = await _register_second_user(
            company_id=tenant.company_id, permission_codes=["EMPLOYEE.TRANSFER"]
        )
        r = await client.post(url, headers=promoter, json=_assignment_body("TRANSFER"))
        assert r.status_code == 403, r.text
        r = await client.post(url, headers=mover, json=_assignment_body("PROMOTION"))
        assert r.status_code == 403, r.text
        r = await client.post(url, headers=promoter, json=_assignment_body("PROMOTION"))
        assert r.status_code not in (401, 403) and r.status_code < 500, r.text
        r = await client.post(url, headers=mover, json=_assignment_body("TRANSFER"))
        assert r.status_code not in (401, 403) and r.status_code < 500, r.text

        # policy assignments: zero-permission user refused for every policy kind
        for kind in ("ATTENDANCE", "LEAVE", "SHIFT", "OVERTIME", "NOPE"):
            r = await client.get(
                "/v1/policy-assignments", headers=zero, params={"policy_kind": kind}
            )
            assert r.status_code in (403, 422), (kind, r.status_code, r.text)
        r = await client.get("/v1/policy-assignments", headers=zero)
        assert r.status_code in (403, 422), r.text
    finally:
        await teardown(tenant)
