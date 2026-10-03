"""Generated crash-fuzz over every organisation / employee / employee-import route: hostile input
must always produce a clean 4xx, never an unhandled exception (500). Uses the same route discovery
as `test_route_authorization_matrix.py`, so new endpoints are swept automatically."""

import pytest
from httpx import AsyncClient

from .modules.account_invite.conftest import seeded_plan_catalogue  # noqa: F401
from .modules.account_invite.uac_helpers import register_tenant, teardown
from .test_route_authorization_matrix import PROTECTED, RouteInfo

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]

_WRITE = {"POST", "PATCH", "PUT"}
_BODIES = [
    {},
    [],
    "text",
    None,
    123,
    {"name": None, "code": None, "effective_from": "not-a-date", "email": 5},
    {"name": "x" * 100_000},
    {"a": {"b": {"c": [1, 2, {"d": None}]}}},
]
_IF_MATCH = ["abc", '"3"', "-1", "", "99999999999999999999", "1.5", 'W/"2"']
_QUERIES = [
    {"page": "-1"},
    {"page": "0"},
    {"page": "abc"},
    {"page_size": "100000000"},
    {"page_size": "0"},
    {"limit": "-5", "offset": "-5"},
    {"as_of": "garbage"},
    {"q": "%" * 500},
    {"status": "'; DROP TABLE employee; --"},
]


async def _send(client: AsyncClient, route: RouteInfo, headers: dict[str, str], **kw) -> int:
    r = await client.request(route.method, route.url(), headers=headers, **kw)
    return r.status_code


async def test_hostile_bodies_never_500(client: AsyncClient) -> None:
    tenant = await register_tenant(client)
    try:
        bad = []
        for route in PROTECTED:
            if route.method not in _WRITE:
                continue
            for body in _BODIES:
                try:
                    status = await _send(client, route, tenant.headers, json=body)
                except Exception as exc:  # noqa: BLE001 - an escaped exception is the failure signal
                    bad.append(
                        f"{route.label} body={str(body)[:30]!r} -> RAISED {type(exc).__name__}"
                    )
                    continue
                if status >= 500:
                    bad.append(f"{route.label} body={str(body)[:30]!r} -> {status}")
        assert not bad, f"{len(bad)} crashes:\n" + "\n".join(bad[:50])
    finally:
        await teardown(tenant)


async def test_malformed_if_match_never_500(client: AsyncClient) -> None:
    tenant = await register_tenant(client)
    try:
        bad = []
        for route in PROTECTED:
            if route.method not in _WRITE | {"DELETE"}:
                continue
            for value in _IF_MATCH:
                headers = {**tenant.headers, "If-Match": value}
                try:
                    status = await _send(
                        client, route, headers, json={} if route.method in _WRITE else None
                    )
                except Exception as exc:  # noqa: BLE001
                    bad.append(f"{route.label} If-Match={value!r} -> RAISED {type(exc).__name__}")
                    continue
                if status >= 500:
                    bad.append(f"{route.label} If-Match={value!r} -> {status}")
        assert not bad, f"{len(bad)} crashes:\n" + "\n".join(bad[:50])
    finally:
        await teardown(tenant)


async def test_hostile_query_strings_never_500(client: AsyncClient) -> None:
    tenant = await register_tenant(client)
    try:
        bad = []
        for route in PROTECTED:
            if route.method != "GET":
                continue
            for params in _QUERIES:
                try:
                    r = await client.get(route.url(), headers=tenant.headers, params=params)
                except Exception as exc:  # noqa: BLE001
                    bad.append(f"{route.label} {params} -> RAISED {type(exc).__name__}")
                    continue
                if r.status_code >= 500:
                    bad.append(f"{route.label} {params} -> {r.status_code}")
        assert not bad, f"{len(bad)} crashes:\n" + "\n".join(bad[:50])
    finally:
        await teardown(tenant)


async def test_malformed_path_ids_are_422_not_500(client: AsyncClient) -> None:
    tenant = await register_tenant(client)
    try:
        bad = []
        for route in PROTECTED:
            if "{" not in route.path:
                continue
            url = "/v1" + route.path
            for part in [p for p in route.path.split("/") if p.startswith("{")]:
                url = url.replace(part, "not-a-uuid")
            kw = {"json": {}} if route.method in _WRITE else {}
            r = await client.request(route.method, url, headers=tenant.headers, **kw)
            if r.status_code not in (404, 422):
                bad.append(f"{route.label} -> {r.status_code}")
        assert not bad, "\n".join(bad[:40])
    finally:
        await teardown(tenant)
