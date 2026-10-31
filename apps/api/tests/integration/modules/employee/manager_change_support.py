"""Shared setup for the manager-change tests: one tenant in which an employee can have a pending
Leave application, Regularization request and Overtime record at once, plus the people who can act
on them.

    A  (wired employee, "Asha")  - the employee's first reporting manager
    B  (reportee "MgrB")         - the manager the employee is later moved to
    E  (reportee "Emp")          - the employee under test; reports to A from 2026-01-01

Approvers use the company's real default `REPORTING_MANAGER` role (not a hand-built role), so what
they can and cannot see is what a real manager gets.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select, text
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _add_reportee_employee,
    _cleanup_scoped_users,
)
from tests.integration.modules.attendance.test_overtime_record import (
    _cleanup_overtime,
    _create_overtime_policy,
    _get_overtime_record_for_day,
    _ot_calculate_day,
)
from tests.integration.modules.attendance.test_regularization import (
    _cleanup_regularization,
    _create_regularization_policy,
    _requested_punches,
)
from tests.integration.modules.leave.test_leave_application import (
    _create_leave_type,
    _give_balance,
    _setup_leave_policy,
    _submit,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.auth.jwt import create_access_token
from hrms.core.auth.passwords import hash_password
from hrms.core.db.models.identity import Role, Session, User, UserCompany, UserRole
from hrms.core.db.session import get_session_factory, set_rls_company_id

CONFIRMATION_REQUIRED = "MANAGER_CHANGE_REQUIRES_CONFIRMATION"

#: Leave / regularization / overtime dates. Each "before" date precedes `CHANGE_FROM`, each "after"
#: date follows it, so as-of-date resolution can be told apart from "whoever is manager today".
CHANGE_FROM = "2026-10-01"
LEAVE_BEFORE, LEAVE_AFTER = "2026-09-08", "2026-10-20"
REG_BEFORE, REG_AFTER = "2026-08-12", "2026-10-12"
#: Distinct from every regularization date: approving a correction recalculates its day, and a
#: recalculation would otherwise rewrite the overtime record this day is meant to keep stable.
REG_BEFORE_OTHER = "2026-08-13"
OT_DAY = "2026-08-10"


async def build_world(
    client: AsyncClient, headers: dict[str, str], *, ot_chain: str = "MANAGER"
) -> dict[str, Any]:
    wired = await _build_wired_employee(client, headers)
    manager_a = wired["employee"]
    manager_b = await _add_reportee_employee(
        client, headers, wired=wired, first_name="MgrB", reporting_manager_id=None
    )
    employee = await _add_reportee_employee(
        client, headers, wired=wired, first_name="Emp", reporting_manager_id=UUID(manager_a["id"])
    )
    leave_type = await _create_leave_type(client, headers)
    await _setup_leave_policy(
        client, headers, leave_type_id=leave_type["id"], approval_chain="MANAGER"
    )
    await _give_balance(
        client, headers, employee_id=employee["id"], leave_type_id=leave_type["id"], amount="20.00"
    )
    await _create_regularization_policy(client, headers, approval_chain="MANAGER")
    await _create_overtime_policy(client, headers, approval_chain=ot_chain)
    return {"wired": wired, "a": manager_a, "b": manager_b, "e": employee, "leave_type": leave_type}


async def teardown_world(*, company_id: UUID, user_id: UUID | None) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "leave_day_projection",
            "leave_application_day",
            "leave_application_action",
            "leave_application",
            "leave_ledger",
            "leave_year_end_run",
            "leave_combination_rule",
            "policy_assignment",
            "leave_policy_version",
            "leave_policy",
            "leave_type",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()
    await _cleanup_overtime(company_id=company_id)
    await _cleanup_regularization(company_id=company_id)
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)
    await _cleanup_scoped_users()


async def manager_headers(company_id: UUID, employee_id: str) -> dict[str, str]:
    """A login for `employee_id` holding the company's real `REPORTING_MANAGER` role."""
    now = datetime.now(UTC)
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        role = (
            await session.execute(
                select(Role).where(Role.company_id == company_id, Role.code == "REPORTING_MANAGER")
            )
        ).scalar_one()
        user_id, session_id = uuid4(), uuid4()
        session.add(
            User(
                id=user_id,
                email=f"scoped-mgr-{user_id.hex[:8]}@example.com",
                password_hash=hash_password("CorrectHorse9"),
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        membership = UserCompany(
            id=uuid4(),
            user_id=user_id,
            company_id=company_id,
            is_primary=True,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(membership)
        await session.flush()
        session.add(UserRole(id=uuid4(), user_company_id=membership.id, role_id=role.id))
        # A real manager's employee record is linked to their login; "can this person act as an
        # approver?" (leave reassignment) is answered from that link.
        await session.execute(
            text("UPDATE employee SET user_id = :u WHERE id = :e AND company_id = :c"),
            {"u": user_id, "e": employee_id, "c": company_id},
        )
        session.add(
            Session(
                id=session_id,
                user_id=user_id,
                company_id=company_id,
                expires_at=now + timedelta(days=1),
            )
        )
        await session.commit()
    token = create_access_token(
        user_id=user_id,
        company_id=company_id,
        session_id=session_id,
        employee_id=UUID(employee_id),
    )
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


# --- Submitting requests ---------------------------------------------------------------------


async def submit_leave(
    client: AsyncClient, headers: dict[str, str], world: dict[str, Any], day: str = LEAVE_BEFORE
) -> dict[str, Any]:
    response = await _submit(
        client,
        headers,
        employee_id=world["e"]["id"],
        leave_type_id=world["leave_type"]["id"],
        start_date=day,
        end_date=day,
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def submit_regularization(
    client: AsyncClient, headers: dict[str, str], world: dict[str, Any], day: str = REG_BEFORE
) -> dict[str, Any]:
    response = await client.post(
        "/v1/regularizations",
        headers=headers,
        json={
            "employee_id": world["e"]["id"],
            "attendance_date": day,
            "request_type": "MISSING_PUNCH",
            "reason": "Forgot to punch",
            "requested_punches": _requested_punches(day),
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def detect_overtime(
    client: AsyncClient, headers: dict[str, str], world: dict[str, Any], day: str = OT_DAY
) -> dict[str, Any]:
    await _ot_calculate_day(client, headers, employee_id=world["e"]["id"], day=day)
    return await ot_record(client, headers, world, day)


async def ot_record(
    client: AsyncClient, headers: dict[str, str], world: dict[str, Any], day: str = OT_DAY
) -> dict[str, Any]:
    return await _get_overtime_record_for_day(
        client, headers, employee_id=world["e"]["id"], day=day
    )


async def recalculate_day(
    client: AsyncClient, headers: dict[str, str], world: dict[str, Any], day: str = OT_DAY
) -> None:
    response = await client.post(
        "/v1/attendance/days/calculate",
        headers=headers,
        params={"employee_id": world["e"]["id"], "date": day},
    )
    assert response.status_code == 200, response.text


# --- Changing the manager --------------------------------------------------------------------


async def current_assignment(
    client: AsyncClient, headers: dict[str, str], employee_id: str
) -> dict[str, Any]:
    rows = (await client.get(f"/v1/employees/{employee_id}/assignments", headers=headers)).json()[
        "data"
    ]
    return [row for row in rows if row["effective_to"] is None][0]


async def post_manager_change(
    client: AsyncClient,
    headers: dict[str, str],
    employee_id: str,
    *,
    manager_id: str | None,
    effective_from: str,
    extra: dict[str, Any] | None = None,
    if_match: int | None = None,
) -> Any:
    """One raw attempt: set `manager_id`, or remove the manager when it is `None`."""
    version = (
        if_match
        if if_match is not None
        else (await current_assignment(client, headers, employee_id))["version"]
    )
    body: dict[str, Any] = {"effective_from": effective_from, "change_type": "MANAGER_CHANGE"}
    if manager_id is None:
        body["clear_reporting_manager"] = True
    else:
        body["reporting_manager_id"] = manager_id
    body.update(extra or {})
    return await client.post(
        f"/v1/employees/{employee_id}/assignments",
        headers={**headers, "If-Match": str(version)},
        json=body,
    )


async def change_manager(
    client: AsyncClient,
    headers: dict[str, str],
    employee_id: str,
    *,
    manager_id: str | None,
    effective_from: str,
) -> Any:
    """Changes (or removes) the manager, acknowledging the pending-request warning if the backend
    raises one. Works both when no confirmation gate exists and when it does."""
    response = await post_manager_change(
        client, headers, employee_id, manager_id=manager_id, effective_from=effective_from
    )
    if response.status_code == 409 and _is_confirmation(response):
        context = response.json()["error"]["details"][0]["context"]
        response = await post_manager_change(
            client,
            headers,
            employee_id,
            manager_id=manager_id,
            effective_from=effective_from,
            extra={
                "confirm_pending_request_impact": True,
                "pending_impact_token": context["impact_token"],
            },
        )
    return response


def _is_confirmation(response: Any) -> bool:
    return response.json().get("error", {}).get("code") == CONFIRMATION_REQUIRED


# --- Deciding requests -----------------------------------------------------------------------


async def approve(
    client: AsyncClient, headers: dict[str, str], kind: str, request: dict[str, Any]
) -> Any:
    path = {
        "leave": "/v1/leave-applications",
        "reg": "/v1/regularizations",
        "ot": "/v1/overtime",
    }[kind]
    return await client.post(
        f"{path}/{request['id']}/approve",
        headers={**headers, "If-Match": str(request["version"])},
        json={},
    )


async def fetch(
    client: AsyncClient, headers: dict[str, str], kind: str, request_id: str
) -> dict[str, Any]:
    path = {
        "leave": "/v1/leave-applications",
        "reg": "/v1/regularizations",
        "ot": "/v1/overtime",
    }[kind]
    response = await client.get(f"{path}/{request_id}", headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


def approver_of(kind: str, request: dict[str, Any]) -> str | None:
    key = "resolved_approver_manager_id"
    return request.get(key)
