"""Integration tests for W8 — `/v1/attendance-periods*` (architecture §4.2/§22, decision log
WD-30).

Reuses `_build_wired_employee`/`_punch`/`_register_tenant`/`_cleanup_attendance_day` from
`test_attendance_day.py`, `_add_reportee_employee`/`_create_permission_scoped_user`/
`_cleanup_scoped_users` from `test_attendance_security.py`, `_create_regularization_policy`/
`_cleanup_regularization` from `test_regularization.py`, and `_create_overtime_policy`/
`_cleanup_overtime` from `test_overtime_record.py` — the same cross-file reuse pattern every W6/W7
test file already established.

Some tests insert a `CLOSED` `attendance_period` row directly via raw SQL rather than going
through the real create->validate->finalize flow — this isolates one mutating service's lock
enforcement at a time (mirrors `test_attendance_day.py::test_locked_day_refuses_recompute`'s
identical raw-SQL-flip convention for `AttendanceDay.is_locked`). The full real flow (create,
validate, finalize, verify locked/frozen, reopen) is covered separately by the end-to-end tests
below without any shortcut.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_overtime_record import (
    _cleanup_overtime,
    _create_overtime_policy,
    _ot_calculate_day,
)
from tests.integration.modules.attendance.test_regularization import (
    _cleanup_regularization,
    _create_regularization_policy,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

_DAY = "2026-08-10"


async def _cleanup_attendance_period(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "attendance_period_summary",
            "attendance_period_action",
            "attendance_period",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


async def _first_legal_entity_id(client: AsyncClient, headers: dict[str, str]) -> str:
    """The tenant's oldest legal entity — the one `_build_wired_employee` created first — or a
    new one when the tenant has none yet."""
    response = await client.get("/v1/legal-entities", headers=headers)
    assert response.status_code == 200, response.text
    entities = sorted(response.json()["data"], key=lambda e: e["created_at"])
    if entities:
        return str(entities[0]["id"])
    created = await client.post("/v1/legal-entities", headers=headers, json={"name": "Acme LE"})
    assert created.status_code == 201, created.text
    return str(created.json()["data"]["id"])


async def _create_period(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    period_start: str = _DAY,
    period_end: str = _DAY,
    label: str | None = "August window",
    legal_entity_id: str | None = None,
) -> dict[str, Any]:
    if legal_entity_id is None:
        legal_entity_id = await _first_legal_entity_id(client, headers)
    response = await client.post(
        "/v1/attendance-periods",
        headers=headers,
        json={
            "legal_entity_id": legal_entity_id,
            "period_start": period_start,
            "period_end": period_end,
            "label": label,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _insert_closed_period(
    *,
    company_id: UUID,
    period_start: str = _DAY,
    period_end: str = _DAY,
    legal_entity_id: str | UUID | None = None,
) -> None:
    """Test-only shortcut (see module docstring) — bypasses validation entirely to unit-test one
    guard at a time. Defaults to the tenant's oldest legal entity."""
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        now = datetime.now(UTC)
        if legal_entity_id is None:
            legal_entity_id = (
                await session.execute(
                    text(
                        "SELECT id FROM legal_entity WHERE company_id = :cid "
                        "ORDER BY created_at LIMIT 1"
                    ),
                    {"cid": str(company_id)},
                )
            ).scalar_one_or_none()
        if legal_entity_id is None:
            legal_entity_id = (
                await session.execute(
                    text(
                        "INSERT INTO legal_entity (id, company_id, name, is_active, version, "
                        "created_at, updated_at) VALUES (gen_random_uuid(), :cid, 'Acme LE', "
                        "true, 1, :now, :now) RETURNING id"
                    ),
                    {"cid": str(company_id), "now": now},
                )
            ).scalar_one()
        await session.execute(
            text(
                """
                INSERT INTO attendance_period
                  (id, company_id, legal_entity_id, period_start, period_end, label, status,
                   opened_at, closed_at, version, created_at, updated_at)
                VALUES
                  (gen_random_uuid(), :cid, :le, :start, :end, 'raw-closed', 'CLOSED',
                   :now, :now, 1, :now, :now)
                """
            ),
            {
                "cid": str(company_id),
                "le": str(legal_entity_id),
                "start": date.fromisoformat(period_start),
                "end": date.fromisoformat(period_end),
                "now": now,
            },
        )
        await session.commit()


async def _full_calculate(
    client: AsyncClient, headers: dict[str, str], *, employee_id: str, day: str = _DAY
) -> dict[str, Any]:
    await _punch(
        client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN", day=day
    )
    await _punch(
        client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT", day=day
    )
    response = await client.post(
        "/v1/attendance/days/calculate",
        headers=headers,
        params={"employee_id": employee_id, "date": day},
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


# ---------------------------------------------------------------------------
# CRUD / security
# ---------------------------------------------------------------------------


async def test_create_period_opens_immediately_and_lists(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        period = await _create_period(client, headers)
        assert period["status"] == "OPEN"
        assert period["version"] == 1
        assert any(a["action"] == "OPENED" for a in period["actions"])

        listed = await client.get("/v1/attendance-periods", headers=headers)
        assert listed.status_code == 200, listed.text
        assert any(p["id"] == period["id"] for p in listed.json()["data"])

        got = await client.get(f"/v1/attendance-periods/{period['id']}", headers=headers)
        assert got.status_code == 200, got.text
        assert got.json()["data"]["id"] == period["id"]
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_overlapping_period_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        first = await _create_period(
            client, headers, period_start="2026-08-01", period_end="2026-08-31"
        )
        overlapping = await client.post(
            "/v1/attendance-periods",
            headers=headers,
            json={
                "legal_entity_id": first["legal_entity_id"],
                "period_start": "2026-08-15",
                "period_end": "2026-09-15",
            },
        )
        assert overlapping.status_code == 409, overlapping.text
        assert overlapping.json()["error"]["code"] == "ATTENDANCE_PERIOD_OVERLAP"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_cross_tenant_period_returns_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        period = await _create_period(client, headers_a)
        response = await client.get(f"/v1/attendance-periods/{period['id']}", headers=headers_b)
        assert response.status_code == 404, response.text
    finally:
        await _cleanup_attendance_period(company_id=company_a)
        await _cleanup_attendance_period(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


async def test_unauthorized_user_cannot_create_period(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        scoped_headers, scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[], data_scope="COMPANY"
        )
        response = await client.post(
            "/v1/attendance-periods",
            headers=scoped_headers,
            json={"period_start": _DAY, "period_end": _DAY},
        )
        assert response.status_code == 403, response.text
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_unlock_requires_separate_permission(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.attendance.permissions import ATTENDANCE_LOCK

    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        await _full_calculate(client, headers, employee_id=wired["employee"]["id"])
        period = await _create_period(client, headers)

        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text

        scoped_headers, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[ATTENDANCE_LOCK], data_scope="COMPANY"
        )
        reopened = await client.post(
            f"/v1/attendance-periods/{period['id']}/reopen",
            headers={**scoped_headers, "If-Match": "2"},
            json={"reason": "need to fix a punch"},
        )
        assert reopened.status_code == 403, reopened.text
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# ---------------------------------------------------------------------------
# Finalization validation
# ---------------------------------------------------------------------------


async def test_validate_ready_and_finalize_locks_days_and_freezes_summary(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _full_calculate(client, headers, employee_id=employee_id)
        period = await _create_period(client, headers)

        validated = await client.post(
            f"/v1/attendance-periods/{period['id']}/validate", headers=headers
        )
        assert validated.status_code == 200, validated.text
        assert validated.json()["data"]["status"] == "READY"
        assert validated.json()["data"]["reasons"] == []

        preview = await client.get(
            f"/v1/attendance-periods/{period['id']}/summary", headers=headers
        )
        assert preview.status_code == 200, preview.text
        preview_row = next(r for r in preview.json()["data"] if r["employee_id"] == employee_id)
        assert preview_row["frozen"] is False
        assert preview_row["present_days"] == "1.00"

        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text
        assert finalized.json()["data"]["status"] == "CLOSED"
        assert any(a["action"] == "CLOSED" for a in finalized.json()["data"]["actions"])

        day = await client.get(
            "/v1/attendance/days",
            headers=headers,
            params={"employee_id": employee_id, "date_from": _DAY, "date_to": _DAY},
        )
        assert day.json()["data"][0]["is_locked"] is True

        frozen = await client.get(f"/v1/attendance-periods/{period['id']}/summary", headers=headers)
        assert frozen.status_code == 200, frozen.text
        frozen_row = next(r for r in frozen.json()["data"] if r["employee_id"] == employee_id)
        assert frozen_row["frozen"] is True
        assert frozen_row["present_days"] == "1.00"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_finalize_blocked_missing_employee_attendance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _build_wired_employee(client, headers)
        period = await _create_period(client, headers)

        response = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ATTENDANCE_FINALIZATION_BLOCKED"
        reasons = response.json()["error"]["details"][0]["context"]["reasons"]
        assert any(r["code"] == "EMPLOYEES_WITHOUT_ATTENDANCE" for r in reasons)

        current = await client.get(f"/v1/attendance-periods/{period['id']}", headers=headers)
        assert current.json()["data"]["status"] == "OPEN"

        # `finalize`'s own BLOCKED path raises inside the same transaction that would have
        # cached the result, so it rolls back along with everything else (WD-30 — no partial
        # side effect survives a failed atomic finalize, matching "no partial finalization").
        # The separate, non-raising `POST .../validate` diagnostic call does persist its cache.
        validated = await client.post(
            f"/v1/attendance-periods/{period['id']}/validate", headers=headers
        )
        assert validated.status_code == 200, validated.text
        assert validated.json()["data"]["status"] == "BLOCKED"
        after_validate = await client.get(f"/v1/attendance-periods/{period['id']}", headers=headers)
        assert after_validate.json()["data"]["last_validation_status"] == "BLOCKED"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_finalize_blocked_config_error(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _full_calculate(client, headers, employee_id=employee_id)

        # A real configuration error: the attendance policy no longer resolves. Writing
        # CONFIG_ERROR onto the day directly would not hold, because finalize recalculates
        # open days first (R-09).
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text(
                    "DELETE FROM policy_assignment "
                    "WHERE company_id = :cid AND policy_kind = 'ATTENDANCE_POLICY'"
                ),
                {"cid": str(company_id)},
            )
            await session.commit()

        period = await _create_period(client, headers)
        response = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert response.status_code == 409, response.text
        reasons = response.json()["error"]["details"][0]["context"]["reasons"]
        assert any(r["code"] == "CONFIG_ERROR" for r in reasons)
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_finalize_blocked_incomplete_with_keep_incomplete_policy(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        calculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": _DAY},
        )
        assert calculated.json()["data"]["attendance_status"] == "INCOMPLETE"

        policy = (await client.get("/v1/attendance-policies", headers=headers)).json()["data"][0]
        versions = (
            await client.get(f"/v1/attendance-policies/{policy['id']}/versions", headers=headers)
        ).json()["data"]
        published_version = next(v for v in versions if v["status"] == "PUBLISHED")
        assert published_version["incomplete_at_lock_behaviour"] == "TREAT_ABSENT"

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text(
                    "UPDATE attendance_policy_version SET incomplete_at_lock_behaviour = "
                    "'KEEP_INCOMPLETE' WHERE id = :id"
                ),
                {"id": published_version["id"]},
            )
            await session.commit()

        period = await _create_period(client, headers)
        response = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert response.status_code == 409, response.text
        reasons = response.json()["error"]["details"][0]["context"]["reasons"]
        assert any(r["code"] == "INCOMPLETE_ATTENDANCE" for r in reasons)
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_finalize_resolves_incomplete_with_default_treat_absent_policy(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Architecture §11.4 — a `TREAT_ABSENT` (the shipped default) `INCOMPLETE` day is not a
    blocker at all; `finalize` resolves its `paid_day_fraction`/`lop_fraction` to the ABSENT
    mapping as part of locking, never touching `attendance_status` itself."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        calculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": _DAY},
        )
        assert calculated.json()["data"]["attendance_status"] == "INCOMPLETE"
        assert calculated.json()["data"]["paid_day_fraction"] == "0.00"

        period = await _create_period(client, headers)
        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text

        day = await client.get(
            "/v1/attendance/days",
            headers=headers,
            params={"employee_id": employee_id, "date_from": _DAY, "date_to": _DAY},
        )
        locked_day = day.json()["data"][0]
        assert locked_day["is_locked"] is True
        assert locked_day["attendance_status"] == "INCOMPLETE"
        assert locked_day["paid_day_fraction"] == "0.00"
        assert locked_day["lop_fraction"] == "1.00"

        # PAY-007 — the frozen summary reflects the resolution, not the pre-lock 0.00/0.00.
        frozen = await client.get(f"/v1/attendance-periods/{period['id']}/summary", headers=headers)
        frozen_row = next(r for r in frozen.json()["data"] if r["employee_id"] == employee_id)
        assert frozen_row["lop_days"] == "1.00"
        assert frozen_row["paid_days"] == "0.00"
        assert frozen_row["payable_days"] == "1.00"
        assert frozen_row["absent_days"] == "1.00"
        assert frozen_row["incomplete_days"] == "0.00"

        # PAY-007 — the lock-time rewrite is audited, per resolved day.
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            audit_after = (
                await session.execute(
                    text(
                        "SELECT after_json FROM audit_log WHERE company_id = :cid "
                        "AND action = 'ATTENDANCE_INCOMPLETE_RESOLVED_AT_LOCK'"
                    ),
                    {"cid": str(company_id)},
                )
            ).scalar_one()
        resolved = audit_after["resolved_days"]
        assert len(resolved) == 1
        assert resolved[0]["behaviour"] == "TREAT_ABSENT"
        assert resolved[0]["before"] == {"paid_day_fraction": "0.00", "lop_fraction": "0.00"}
        assert resolved[0]["after"] == {"paid_day_fraction": "0.00", "lop_fraction": "1.00"}
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_mid_period_joiner_gate_and_frozen_summary(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """PAY-002/PAY-003/PAY-004 end to end — an employee joining on day 2 of a 3-day period.

    The NOT_JOINED day before joining must not satisfy the missing-attendance gate for an
    uncalculated employed day (the old row-count check let it), must carry 0.00 paid / 0.00
    LOP, and the frozen summary must report it as not-employed with paid + LOP = payable."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers, joining_date="2026-08-11")
        employee_id = wired["employee"]["id"]

        before_joining = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert before_joining.status_code == 200, before_joining.text
        assert before_joining.json()["data"]["attendance_status"] == "NOT_JOINED"
        assert before_joining.json()["data"]["paid_day_fraction"] == "0.00"
        assert before_joining.json()["data"]["lop_fraction"] == "0.00"

        await _full_calculate(client, headers, employee_id=employee_id, day="2026-08-11")
        period = await _create_period(
            client, headers, period_start="2026-08-10", period_end="2026-08-12"
        )

        # 2 rows for 2 employed days, but 2026-08-12 is uncalculated — must block.
        validated = await client.post(
            f"/v1/attendance-periods/{period['id']}/validate", headers=headers
        )
        assert validated.json()["data"]["status"] == "BLOCKED"
        assert [r["code"] for r in validated.json()["data"]["reasons"]] == [
            "EMPLOYEES_WITHOUT_ATTENDANCE"
        ]

        await _full_calculate(client, headers, employee_id=employee_id, day="2026-08-12")
        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text

        frozen = await client.get(f"/v1/attendance-periods/{period['id']}/summary", headers=headers)
        row = next(r for r in frozen.json()["data"] if r["employee_id"] == employee_id)
        assert row["frozen"] is True
        assert row["present_days"] == "2.00"
        assert row["not_employed_days"] == "1.00"
        assert row["payable_days"] == "2.00"
        assert row["paid_days"] == "2.00"
        assert row["lop_days"] == "0.00"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_finalize_blocked_pending_regularization(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _full_calculate(client, headers, employee_id=employee_id)
        await _create_regularization_policy(client, headers, approval_chain="HR")

        submitted = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": _DAY,
                "request_type": "MISSING_PUNCH",
                "reason": "forgot to punch out on time",
                "requested_punches": [
                    {"direction": "IN", "requested_time": f"{_DAY}T09:00:00Z"},
                    {"direction": "OUT", "requested_time": f"{_DAY}T18:30:00Z"},
                ],
            },
        )
        assert submitted.status_code == 201, submitted.text

        period = await _create_period(client, headers)
        response = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert response.status_code == 409, response.text
        reasons = response.json()["error"]["details"][0]["context"]["reasons"]
        assert any(r["code"] == "PENDING_REGULARIZATION" for r in reasons)
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_finalize_blocked_pending_overtime_approval(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(
            client, headers, approval_chain="MANAGER", requires_post_approval=True
        )
        await _ot_calculate_day(client, headers, employee_id=employee_id, day=_DAY)

        period = await _create_period(client, headers)
        response = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert response.status_code == 409, response.text
        reasons = response.json()["error"]["details"][0]["context"]["reasons"]
        assert any(r["code"] == "PENDING_OVERTIME_APPROVAL" for r in reasons)
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_finalize_blocked_unpublished_roster(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _full_calculate(client, headers, employee_id=employee_id)

        draft = await client.post(
            "/v1/rosters",
            headers=headers,
            json={
                "employee_id": employee_id,
                "roster_date": "2026-08-11",
                "shift_id": wired["shift"]["id"],
            },
        )
        assert draft.status_code == 201, draft.text

        period = await _create_period(client, headers, period_start=_DAY, period_end="2026-08-11")
        response = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert response.status_code == 409, response.text
        reasons = response.json()["error"]["details"][0]["context"]["reasons"]
        # Both the roster-date's own missing-attendance gap and its DRAFT status are real,
        # independent blockers here — assert the one this test exists to prove.
        assert any(r["code"] == "UNPUBLISHED_ROSTER" for r in reasons)
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Lock enforcement (isolated per mutating service — see module docstring)
# ---------------------------------------------------------------------------


async def test_punch_rejected_deep_inside_closed_period(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`DEC-TZ-05`/`CD-1` (SELECTED, execution gate §10.6): a punch is refused only when BOTH
    its own local (IST) date and the previous local date are `CLOSED`. A realistic month-long
    closed period (not a single isolated day) is what makes that true here — the punch's own
    date and the day before it are both deep inside the same closed month, so this is the
    "both closed" case the guard still rejects.

    (Renamed from `test_punch_rejected_for_closed_period_date`, whose single-day `[_DAY, _DAY]`
    closed window is exactly the boundary case Phase 4 intentionally makes more permissive —
    see `test_punch_accepted_night_shift_month_boundary_*` below for that behaviour.)"""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _insert_closed_period(
            company_id=company_id, period_start="2026-08-01", period_end="2026-08-31"
        )

        response = await client.post(
            "/v1/attendance/punches",
            headers=headers,
            json={
                "employee_id": employee_id,
                "punch_time": f"{_DAY}T09:00:00Z",
                "direction": "IN",
                "reference": "backdated correction",
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ATTENDANCE_PERIOD_CLOSED"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# DEC-TZ-05 / CD-1 — the night-shift month-boundary scenario, frozen as a test
# (execution gate §10.2's exact worked table: September CLOSED, October OPEN,
# a 22:00->06:00 shift starting 30 Sep, punches walked from 00:30 to 06:00 IST on 1 Oct).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ist_time_and_utc_instant",
    [
        ("00:30 IST", "2026-07-31T19:00:00Z"),
        ("01:30 IST", "2026-07-31T20:00:00Z"),
        ("03:00 IST", "2026-07-31T21:30:00Z"),
        ("05:00 IST", "2026-07-31T23:30:00Z"),
        ("05:29 IST", "2026-07-31T23:59:00Z"),
        ("05:30 IST", "2026-08-01T00:00:00Z"),
        ("06:00 IST", "2026-08-01T00:30:00Z"),
    ],
    ids=lambda p: p[0] if isinstance(p, tuple) else p,
)
async def test_punch_accepted_night_shift_month_boundary(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    ist_time_and_utc_instant: tuple[str, str],
) -> None:
    """The exact scenario `CD-1`'s recommendation was selected to fix: a night-shift punch
    landing between 00:00 and 05:29 IST would, under the OLD UTC-date basis, have been WRONGLY
    ACCEPTED for the two latest instants and correctly rejected for the five earlier ones
    (execution gate §10.2's table) — an asymmetry with no relationship to the shift or the work
    performed, purely an artefact of the UTC-date rollover at 05:30.

    Under the SELECTED basis, every instant in this band is now ACCEPTED: the punch's own local
    (IST) date is 1 Oct, in the OPEN October period, which alone is enough (`or`, not `and`) —
    this is the deliberate trade the recommendation names explicitly (`§10.6`: "the cost of some
    recoverable false acceptances"). Nothing about a locked, already-computed figure changes as
    a result — `calculate()`'s own separate lock check is what keeps that true, and is exercised
    by a different test, not this one."""
    _, utc_instant = ist_time_and_utc_instant
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers, joining_date="2026-07-01")
        employee_id = wired["employee"]["id"]
        await _insert_closed_period(
            company_id=company_id, period_start="2026-07-01", period_end="2026-07-31"
        )

        response = await client.post(
            "/v1/attendance/punches",
            headers=headers,
            json={
                "employee_id": employee_id,
                "punch_time": utc_instant,
                "direction": "IN",
                "reference": "night-shift punch near month boundary",
            },
        )
        assert response.status_code == 201, response.text
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_punch_still_rejected_when_both_local_and_previous_day_closed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The mirror of the parametrised test above: if the SECOND month were also closed (both the
    punch's own local date and the previous local date `CLOSED`), the punch must still be
    refused. This is what proves the new basis is `or`, not "always accept near a boundary" —
    the guard is still a real guard, not a no-op."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers, joining_date="2026-07-01")
        employee_id = wired["employee"]["id"]
        await _insert_closed_period(
            company_id=company_id, period_start="2026-07-01", period_end="2026-08-31"
        )

        response = await client.post(
            "/v1/attendance/punches",
            headers=headers,
            json={
                "employee_id": employee_id,
                "punch_time": "2026-08-01T00:30:00Z",  # 06:00 IST, 1 Aug
                "direction": "IN",
                "reference": "night-shift punch, both months closed",
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ATTENDANCE_PERIOD_CLOSED"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_punch_accepted_early_day_shift_mirror_case(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Execution gate §10.3's mirror case (dates shifted safely into the past from the
    document's own Sept/Oct worked example): an early day shift's 04:30 IST punch on 1 Aug maps
    to UTC date 31 Jul (CLOSED under the old basis, a FALSE rejection — the opposite error from
    §10.2). Under the SELECTED basis the punch's own local date (1 Aug, OPEN) accepts it
    directly, closing the unrecoverable-loss case `CD-1` was chosen to eliminate."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers, joining_date="2026-07-01")
        employee_id = wired["employee"]["id"]
        await _insert_closed_period(
            company_id=company_id, period_start="2026-07-01", period_end="2026-07-31"
        )

        response = await client.post(
            "/v1/attendance/punches",
            headers=headers,
            json={
                "employee_id": employee_id,
                "punch_time": "2026-07-31T23:00:00Z",  # 04:30 IST, 1 Aug
                "direction": "IN",
                "reference": "early day-shift punch near month boundary",
            },
        )
        assert response.status_code == 201, response.text
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_roster_create_rejected_for_closed_period_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _insert_closed_period(company_id=company_id)

        response = await client.post(
            "/v1/rosters",
            headers=headers,
            json={
                "employee_id": employee_id,
                "roster_date": _DAY,
                "shift_id": wired["shift"]["id"],
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ATTENDANCE_PERIOD_CLOSED"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_regularization_submit_rejected_for_closed_period_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers)
        await _insert_closed_period(company_id=company_id)

        response = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": _DAY,
                "request_type": "MISSING_PUNCH",
                "reason": "late correction attempt",
                "requested_punches": [
                    {"direction": "IN", "requested_time": f"{_DAY}T09:00:00Z"},
                    {"direction": "OUT", "requested_time": f"{_DAY}T18:00:00Z"},
                ],
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ATTENDANCE_PERIOD_CLOSED"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_recompute_rejected_for_closed_period_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Covers the create-path gap `AttendanceDay.is_locked` alone cannot catch — no day row
    exists yet at all for this date, only the period says it is closed."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        await _insert_closed_period(company_id=company_id)

        response = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": _DAY},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ATTENDANCE_PERIOD_CLOSED"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_overtime_approve_rejected_for_closed_period_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(
            client, headers, approval_chain="MANAGER", requires_post_approval=True
        )
        await _ot_calculate_day(client, headers, employee_id=employee_id, day=_DAY)
        listed = await client.get(
            "/v1/overtime",
            headers=headers,
            params={"employee_id": employee_id, "date_from": _DAY, "date_to": _DAY},
        )
        record_id = listed.json()["data"][0]["id"]

        await _insert_closed_period(company_id=company_id)

        response = await client.post(
            f"/v1/overtime/{record_id}/approve",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ATTENDANCE_PERIOD_CLOSED"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Reopen
# ---------------------------------------------------------------------------


async def test_reopen_unlocks_days_and_refinalize_regenerates_summary(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _full_calculate(client, headers, employee_id=employee_id)
        period = await _create_period(client, headers)

        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text

        reopened = await client.post(
            f"/v1/attendance-periods/{period['id']}/reopen",
            headers={**headers, "If-Match": "2"},
            json={"reason": "correcting a punch before payroll"},
        )
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["data"]["status"] == "OPEN"
        assert reopened.json()["data"]["reopen_reason"] == "correcting a punch before payroll"

        day = await client.get(
            "/v1/attendance/days",
            headers=headers,
            params={"employee_id": employee_id, "date_from": _DAY, "date_to": _DAY},
        )
        assert day.json()["data"][0]["is_locked"] is False

        recomputed = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": _DAY},
        )
        assert recomputed.status_code == 200, recomputed.text

        refinalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "3"},
            json={},
        )
        assert refinalized.status_code == 200, refinalized.text
        summary = await client.get(
            f"/v1/attendance-periods/{period['id']}/summary", headers=headers
        )
        row = next(r for r in summary.json()["data"] if r["employee_id"] == employee_id)
        assert row["frozen"] is True
        assert row["present_days"] == "1.00"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


async def test_stale_if_match_on_finalize_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        await _full_calculate(client, headers, employee_id=wired["employee"]["id"])
        period = await _create_period(client, headers)

        response = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "99"},
            json={},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_simultaneous_finalize_only_one_wins(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        await _full_calculate(client, headers, employee_id=wired["employee"]["id"])
        period = await _create_period(client, headers)

        first = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        second = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        statuses = sorted([first.status_code, second.status_code])
        assert statuses == [200, 409], (first.text, second.text)

        final = await client.get(f"/v1/attendance-periods/{period['id']}", headers=headers)
        assert final.json()["data"]["status"] == "CLOSED"
        assert final.json()["data"]["version"] == 2
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
