"""R-2 (owner decision D-01b), through the real API: the per-policy-version mark-credit ceiling.

* the field defaults to 59, accepts 0-120 and refuses anything else, on create and on update;
* a published version is immutable, so the ceiling cannot be edited after publishing;
* creating, updating and publishing a version audit the value (before and after);
* the one-call setup endpoint accepts it;
* a calculated day uses the ceiling of the policy version in force and stores the complete credit
  calculation in its snapshot (the borderline 09:40-17:20 day flips between versions 59 and 60).

Day used end to end: 09:00-18:00 UTC with an unpaid 13:00-14:00 lunch (net 480), grace 10/10, hour
bands ABSENT < 240, HALF_DAY 240-479, PRESENT >= 480, broad `LATE` / `EARLY_DEPARTURE` mark bands.
"""

import json
from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _punch,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_policy import (
    _cleanup_attendance,
    _create_policy,
)
from tests.integration.modules.attendance.test_attendance_rules_remediation import (
    _calc,
    _cleanup_all,
    _stored,
)
from tests.integration.modules.attendance.test_break_events_api import LUNCH
from tests.integration.modules.attendance.test_shift_window import _sql
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio

HOUR_BANDS = [
    {"min_minutes": 0, "max_minutes": 239, "result_status": "ABSENT"},
    {"min_minutes": 240, "max_minutes": 479, "result_status": "HALF_DAY"},
    {"min_minutes": 480, "max_minutes": None, "result_status": "PRESENT"},
]
LATE_BANDS = [{"min_minutes": 1, "max_minutes": 240, "classification": "LATE"}]
EARLY_BANDS = [{"min_minutes": 1, "max_minutes": 240, "classification": "EARLY_DEPARTURE"}]


async def _draft(
    client: AsyncClient, headers: dict[str, str], policy_id: str, **body: Any
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/attendance-policies/{policy_id}/versions",
        headers=headers,
        json={"effective_from": "2026-01-01", **body},
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _audit(company_id: Any, version_id: str, action: str) -> list[dict[str, Any]]:
    rows = await _sql(
        company_id,
        "SELECT before_json, after_json FROM audit_log WHERE company_id = :cid "
        f"AND entity_id = '{version_id}' AND action = '{action}' ORDER BY occurred_at",
    )
    return [
        {
            "before": json.loads(b) if isinstance(b, str) else b,
            "after": json.loads(a) if isinstance(a, str) else a,
        }
        for b, a in rows
    ]


async def test_the_ceiling_defaults_to_59_and_is_returned(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        draft = await _draft(client, headers, policy["id"])
        assert draft["mark_credit_ceiling_minutes"] == 59
        fetched = await client.get(
            f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}", headers=headers
        )
        assert fetched.json()["data"]["mark_credit_ceiling_minutes"] == 59
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize(
    ("value", "ok"), [(-1, False), (0, True), (59, True), (120, True), (121, False)]
)
async def test_the_range_is_0_to_120_on_create_and_on_update(
    client: AsyncClient, seeded_plan_catalogue: None, value: int, ok: bool
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        # create (a policy allows one open draft, so create and update use separate policies)
        created_policy = await _create_policy(client, headers, name="Create policy")
        created = await client.post(
            f"/v1/attendance-policies/{created_policy['id']}/versions",
            headers=headers,
            json={"effective_from": "2026-01-01", "mark_credit_ceiling_minutes": value},
        )
        assert created.status_code == (201 if ok else 422), created.text
        if ok:
            assert created.json()["data"]["mark_credit_ceiling_minutes"] == value
        # update of a valid draft
        update_policy = await _create_policy(client, headers, name="Update policy")
        draft = await _draft(client, headers, update_policy["id"])
        patched = await client.patch(
            f"/v1/attendance-policies/{update_policy['id']}/versions/{draft['id']}",
            headers={**headers, "If-Match": str(draft["version"])},
            json={"mark_credit_ceiling_minutes": value},
        )
        assert patched.status_code == (200 if ok else 422), patched.text
        if ok:
            assert patched.json()["data"]["mark_credit_ceiling_minutes"] == value
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_non_integer_ceiling_is_refused(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        for bad in ("abc", 12.5, None):
            response = await client.post(
                f"/v1/attendance-policies/{policy['id']}/versions",
                headers=headers,
                json={"effective_from": "2026-01-01", "mark_credit_ceiling_minutes": bad},
            )
            assert response.status_code == 422, (bad, response.text)
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_published_version_keeps_its_ceiling(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        draft = await _draft(
            client, headers, policy["id"], hour_bands=HOUR_BANDS, mark_credit_ceiling_minutes=45
        )
        published = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}/publish",
            headers={**headers, "If-Match": str(draft["version"])},
            json={},
        )
        assert published.status_code == 200, published.text
        assert published.json()["data"]["mark_credit_ceiling_minutes"] == 45
        patched = await client.patch(
            f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}",
            headers={**headers, "If-Match": str(published.json()["data"]["version"])},
            json={"mark_credit_ceiling_minutes": 100},
        )
        assert patched.status_code == 409, patched.text
        assert patched.json()["error"]["code"] == "POLICY_VERSION_NOT_DRAFT"
        row = await _sql(
            company_id,
            "SELECT mark_credit_ceiling_minutes FROM attendance_policy_version "
            f"WHERE company_id = :cid AND id = '{draft['id']}'",
        )
        assert row[0][0] == 45
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_the_value_is_audited_on_create_update_and_publish(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        draft = await _draft(client, headers, policy["id"], hour_bands=HOUR_BANDS)
        patched = await client.patch(
            f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}",
            headers={**headers, "If-Match": str(draft["version"])},
            json={"mark_credit_ceiling_minutes": 30},
        )
        assert patched.status_code == 200, patched.text
        published = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}/publish",
            headers={**headers, "If-Match": str(patched.json()["data"]["version"])},
            json={},
        )
        assert published.status_code == 200, published.text

        created = await _audit(company_id, draft["id"], "ATTENDANCE_POLICY_VERSION_CREATED")
        updated = await _audit(company_id, draft["id"], "ATTENDANCE_POLICY_VERSION_UPDATED")
        publish = await _audit(company_id, draft["id"], "ATTENDANCE_POLICY_VERSION_PUBLISHED")
        assert created[0]["after"]["mark_credit_ceiling_minutes"] == 59
        assert updated[0]["before"]["mark_credit_ceiling_minutes"] == 59
        assert updated[0]["after"]["mark_credit_ceiling_minutes"] == 30
        assert publish[0]["before"]["mark_credit_ceiling_minutes"] == 30
        assert publish[0]["after"]["mark_credit_ceiling_minutes"] == 30
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_the_setup_endpoint_accepts_and_validates_the_ceiling(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        good = await client.post(
            "/v1/attendance-policies/setup",
            headers=headers,
            json={
                "name": "Setup policy",
                "rules": {
                    "effective_from": "2026-01-01",
                    "hour_bands": HOUR_BANDS,
                    "mark_credit_ceiling_minutes": 90,
                },
            },
        )
        assert good.status_code == 201, good.text
        assert good.json()["data"]["version"]["mark_credit_ceiling_minutes"] == 90
        bad = await client.post(
            "/v1/attendance-policies/setup",
            headers=headers,
            json={
                "name": "Setup policy 2",
                "rules": {"hour_bands": HOUR_BANDS, "mark_credit_ceiling_minutes": 121},
            },
        )
        assert bad.status_code == 422, bad.text
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def _publish_version(
    client: AsyncClient,
    headers: dict[str, str],
    policy_id: str,
    *,
    effective_from: str,
    ceiling: int,
) -> dict[str, Any]:
    draft = await _draft(
        client,
        headers,
        policy_id,
        effective_from=effective_from,
        grace_in_minutes=10,
        grace_out_minutes=10,
        hour_bands=HOUR_BANDS,
        late_bands=LATE_BANDS,
        early_departure_bands=EARLY_BANDS,
        mark_credit_ceiling_minutes=ceiling,
    )
    versions = (
        await client.get(f"/v1/attendance-policies/{policy_id}/versions", headers=headers)
    ).json()["data"]
    current = next(v for v in versions if v["status"] == "PUBLISHED" and v["effective_to"] is None)
    published = await client.post(
        f"/v1/attendance-policies/{policy_id}/versions/{draft['id']}/publish",
        headers={**headers, "If-Match": str(draft["version"])},
        json={"expected_previous_version": current["version"]},
    )
    assert published.status_code == 200, published.text
    return dict(published.json()["data"])


async def test_a_calculated_day_uses_the_ceiling_of_the_version_in_force(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """09:40 in, 17:20 out: 400 worked, 30 + 30 beyond-grace minutes marked. Ceiling 60: credit
    10 + 10 + 60 = 80, band 480, PRESENT. Ceiling 59: 79, band 479, HALF_DAY. Same punches, two
    policy versions effective on different days."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(
            client, headers, breaks=[LUNCH | {"mode": "AUTO_DEDUCT"}]
        )
        employee_id = str(wired["employee"]["id"])
        policies = (await client.get("/v1/attendance-policies", headers=headers)).json()["data"]
        policy_id = policies[0]["id"]
        v60 = await _publish_version(
            client, headers, policy_id, effective_from="2026-08-01", ceiling=60
        )
        v59 = await _publish_version(
            client, headers, policy_id, effective_from="2026-08-11", ceiling=59
        )
        assert (v60["mark_credit_ceiling_minutes"], v59["mark_credit_ceiling_minutes"]) == (60, 59)

        for day in ("2026-08-10", "2026-08-11"):
            await _punch(
                client, headers, employee_id=employee_id, hour=9, minute=40, direction="IN", day=day
            )
            await _punch(
                client,
                headers,
                employee_id=employee_id,
                hour=17,
                minute=20,
                direction="OUT",
                day=day,
            )
            await _calc(client, headers, employee_id, day)

        monday = await _stored(client, headers, employee_id, "2026-08-10")
        tuesday = await _stored(client, headers, employee_id, "2026-08-11")

        credit = monday["computation_snapshot"]["grace_band_credit"]
        assert monday["attendance_status"] == "PRESENT" and monday["paid_day_fraction"] == "1.00"
        assert credit["ceiling"] == 60 and credit["band_minutes"] == 480
        assert credit["beyond_grace_credit"] == {
            "total": 60,
            "allocated_in": 30,
            "allocated_out": 30,
        }
        assert monday["attendance_policy_version_id"] == v60["id"]

        credit = tuesday["computation_snapshot"]["grace_band_credit"]
        assert tuesday["attendance_status"] == "HALF_DAY", json.dumps(credit)
        assert tuesday["paid_day_fraction"] == "0.50"
        assert credit["ceiling"] == 59 and credit["band_minutes"] == 479
        assert credit["capped"] is True
        assert credit["plain_grace"] == {"in": 10, "out": 10}
        assert credit["qualifying_beyond_grace"] == {"in": 30, "out": 30, "total": 60}
        assert credit["beyond_grace_credit"] == {
            "total": 59,
            "allocated_in": 30,
            "allocated_out": 29,
        }
        assert tuesday["attendance_policy_version_id"] == v59["id"]
    finally:
        await _cleanup_all(company_id, user_id)
