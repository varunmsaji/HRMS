"""API audit H-1 - collections that used to return their whole result set are now bounded.

Contract: `page` (>=1) / `per_page` (1..500, default 500), `pagination` always present, stable
total ordering (no duplicates or gaps across pages), tenant isolation unchanged. Out-of-range
parameters are a 422, never silently clamped."""

import pytest
from httpx import AsyncClient

from ...tenant_wipe import wipe_tenant
from ..account_invite.test_account_invite import _create_employee, _register_tenant
from ..organisation.test_registration_flow import VALID_PASSWORD  # noqa: F401

pytestmark = pytest.mark.asyncio

BOUNDED_ROUTES = [
    "/v1/attendance/punches",
    "/v1/attendance/days",
    "/v1/rosters",
    "/v1/regularizations",
    "/v1/overtime",
    "/v1/attendance-periods",
    "/v1/leave-projections",
    "/v1/attendance/face-profiles",
    "/v1/payroll/pay-runs",
    "/v1/payroll/adjustments",
]


async def test_every_bounded_route_has_the_pagination_contract(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        for path in BOUNDED_ROUTES:
            ok = await client.get(path, headers=headers)
            assert ok.status_code == 200, (path, ok.text)
            body = ok.json()
            assert body["pagination"] == {
                "page": 1,
                "per_page": 500,
                "total": 0,
                "total_pages": 0,
                "next_cursor": None,
            }, path
            assert body["data"] == []
            for bad in ("per_page=501", "per_page=0", "page=0", "page=-1", "per_page=abc"):
                r = await client.get(f"{path}?{bad}", headers=headers)
                assert r.status_code == 422, (path, bad, r.status_code)
                assert r.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
            assert (await client.get(path)).status_code == 401, path
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_punch_pages_are_stable_complete_filtered_and_tenant_scoped(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    other_headers, other_company, other_user = await _register_tenant(client)
    try:
        le = await client.post("/v1/legal-entities", headers=headers, json={"name": "LE"})
        emp = await _create_employee(client, headers, "Asha")
        other = await _create_employee(client, headers, "Bala")
        for e in (emp, other):
            r = await client.post(
                f"/v1/employees/{e['id']}/employments",
                headers=headers,
                json={"legal_entity_id": le.json()["data"]["id"], "joining_date": "2026-01-01"},
            )
            assert r.status_code == 201, r.text
        ids = []
        for minute in range(7):  # 7 punches for `emp`, same minute spacing
            r = await client.post(
                "/v1/attendance/punches",
                headers=headers,
                json={
                    "employee_id": emp["id"],
                    "direction": "IN" if minute % 2 == 0 else "OUT",
                    "reference": "hr-correction",
                    "punch_time": f"2026-02-02T09:{minute:02d}:00Z",
                },
            )
            assert r.status_code == 201, r.text
            ids.append(r.json()["data"]["id"])
        # one identical-instant pair: the tie-breaker must still give a total order
        for _ in range(2):
            r = await client.post(
                "/v1/attendance/punches",
                headers=headers,
                json={
                    "employee_id": emp["id"],
                    "direction": "IN",
                    "reference": "hr-correction",
                    "punch_time": "2026-02-02T10:00:00Z",
                },
            )
            assert r.status_code == 201, r.text
            ids.append(r.json()["data"]["id"])
        r = await client.post(
            "/v1/attendance/punches",
            headers=headers,
            json={
                "employee_id": other["id"],
                "direction": "IN",
                "reference": "hr-correction",
                "punch_time": "2026-02-02T09:00:00Z",
            },
        )
        assert r.status_code == 201

        base = f"/v1/attendance/punches?employee_id={emp['id']}"
        full = (await client.get(base, headers=headers)).json()
        assert full["pagination"]["total"] == 9 and len(full["data"]) == 9
        order = [p["id"] for p in full["data"]]

        seen: list[str] = []
        sizes = []
        for page in (1, 2, 3, 4):
            r = await client.get(f"{base}&per_page=4&page={page}", headers=headers)
            assert r.status_code == 200
            body = r.json()
            assert body["pagination"]["total"] == 9 and body["pagination"]["total_pages"] == 3
            sizes.append(len(body["data"]))
            seen += [p["id"] for p in body["data"]]
        assert sizes == [4, 4, 1, 0]  # last page partial, page past the end is empty not an error
        assert seen == order and len(set(seen)) == 9  # no duplicates, no gaps, same order
        # repeating a page returns the same rows (deterministic)
        again = await client.get(f"{base}&per_page=4&page=2", headers=headers)
        assert [p["id"] for p in again.json()["data"]] == order[4:8]

        # filters compose with paging
        ranged = await client.get(
            f"{base}&date_from=2026-02-02&date_to=2026-02-02&per_page=5", headers=headers
        )
        assert ranged.json()["pagination"]["total"] == 9 and len(ranged.json()["data"]) == 5
        none = await client.get(f"{base}&date_from=2026-03-01&date_to=2026-03-02", headers=headers)
        assert none.json()["data"] == [] and none.json()["pagination"]["total"] == 0

        # tenant isolation: the other company sees nothing, not even a total
        foreign = await client.get("/v1/attendance/punches", headers=other_headers)
        assert foreign.json()["pagination"]["total"] == 0 and foreign.json()["data"] == []
        both = await client.get("/v1/attendance/punches?per_page=100", headers=headers)
        assert both.json()["pagination"]["total"] == 10

        # attendance days: page through after calculating a few
        for d in ("2026-02-02", "2026-02-03", "2026-02-04"):
            c = await client.post(
                "/v1/attendance/days/calculate",
                headers=headers,
                params={"employee_id": emp["id"], "date": d},
            )
            assert c.status_code == 200, c.text
        days = await client.get(
            f"/v1/attendance/days?employee_id={emp['id']}&per_page=2", headers=headers
        )
        assert days.json()["pagination"]["total"] == 3 and len(days.json()["data"]) == 2
        p2 = await client.get(
            f"/v1/attendance/days?employee_id={emp['id']}&per_page=2&page=2", headers=headers
        )
        assert len(p2.json()["data"]) == 1
        got = [d["attendance_date"] for d in days.json()["data"] + p2.json()["data"]]
        assert got == sorted(got, reverse=True)
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)
        await wipe_tenant(company_id=other_company, user_id=other_user)
