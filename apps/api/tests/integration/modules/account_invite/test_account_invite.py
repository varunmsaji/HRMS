"""Integration tests for the account-invite module (`docs/modules/employee/
41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md` Phase 2) —
`POST /employees/{id}/invite`, `POST /users/invite`, `GET/POST /public/account-invites/{token}...`,
`PATCH /users/{id}/roles`, `GET /users`.

Follows the exact checklist/helper conventions established by `test_onboarding_invite.py`
(register → act → assert → teardown, resend-revokes-previous-token, permission gating,
not-found/not-invitable rejection) and `test_employee.py` (`_register_tenant`/`_create_employee`),
reused here rather than reinvented."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.auth.passwords import verify_password
from hrms.core.db.models.identity import User
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.core.rbac.service import RbacService

from ..organisation.test_registration_flow import VALID_PASSWORD, _cleanup, _register

pytestmark = pytest.mark.asyncio


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201, response.text
    assert company_id is not None
    data = response.json()["data"]
    return (
        {
            "Authorization": f"Bearer {data['access_token']}",
            "X-Company-Id": str(company_id),
        },
        company_id,
        user_id,
    )


async def _create_employee(
    client: AsyncClient, headers: dict[str, str], first_name: str = "Asha", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/employees", headers=headers, json={"first_name": first_name, **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def _token_from_invite_url(invite_url: str) -> str:
    return invite_url.rsplit("/", 1)[-1]


async def _force_invite_expired(*, company_id: UUID, email: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE account_invite SET expires_at = :past "
                "WHERE company_id = :cid AND email = :email "
                "AND accepted_at IS NULL AND revoked_at IS NULL"
            ),
            {"past": datetime.now(UTC) - timedelta(days=1), "cid": str(company_id), "email": email},
        )
        await session.commit()


async def _extra_user_id(*, email: str) -> UUID | None:
    factory = get_session_factory()
    async with factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        return user.id if user is not None else None


async def _cleanup_extra_user_sessions(*, user_id: UUID) -> None:
    """Must run *before* `_cleanup` deletes the `Company` row — an invite-accept auto-login
    (`IdentityService.issue_tokens_for`) creates a `refresh_token`/`session` row carrying this
    `company_id`, and both FKs are `ON DELETE RESTRICT`."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM refresh_token WHERE user_id = :uid"), {"uid": str(user_id)}
        )
        await session.execute(
            text("DELETE FROM session WHERE user_id = :uid"), {"uid": str(user_id)}
        )
        await session.commit()


async def _cleanup_extra_user_row(*, user_id: UUID) -> None:
    """Must run *after* `_cleanup` — it deletes `UserCompany`/`UserRole` scoped by `company_id`
    (covering every member, not just the admin), which must happen before `User` itself can be
    deleted (`user_company_user_id_fkey`)."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text('DELETE FROM "user" WHERE id = :uid'), {"uid": str(user_id)})
        await session.commit()


async def _teardown(
    *, company_id: UUID, user_id: UUID | None, extra_emails: list[str] | None = None
) -> None:
    """Order matters throughout: `account_invite` has `ON DELETE RESTRICT` FKs to `company`/
    `employee`/`user`, so it must go first. Each extra user's sessions/refresh-tokens must be
    gone *before* `_cleanup` deletes `Company`; their `User` row itself must be deleted *after*
    `_cleanup`'s `UserCompany`/`UserRole` cleanup. See the two helpers' own docstrings."""
    extra_user_ids = [
        uid for email in extra_emails or [] for uid in [await _extra_user_id(email=email)] if uid
    ]

    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("DELETE FROM account_invite WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM number_series WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()

    for uid in extra_user_ids:
        await _cleanup_extra_user_sessions(user_id=uid)

    await _cleanup(company_id=company_id, user_id=user_id)

    for uid in extra_user_ids:
        await _cleanup_extra_user_row(user_id=uid)


async def test_invite_employee_accept_and_login_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    invitee_email = f"invitee-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _create_employee(client, headers, personal_email=invitee_email)

        invite_response = await client.post(
            f"/v1/employees/{employee['id']}/invite", headers=headers
        )
        assert invite_response.status_code == 201, invite_response.text
        invite = invite_response.json()["data"]
        assert invite["email"] == invitee_email
        assert invite["role_code"] == "EMPLOYEE"
        assert invite["email_sent"] is True
        token = _token_from_invite_url(invite["invite_url"])

        resolve_response = await client.get(f"/v1/public/account-invites/{token}")
        assert resolve_response.status_code == 200
        assert resolve_response.json()["data"]["email"] == invitee_email

        accept_response = await client.post(
            f"/v1/public/account-invites/{token}/accept",
            json={"password": VALID_PASSWORD, "first_name": "New", "last_name": "Hire"},
        )
        assert accept_response.status_code == 201, accept_response.text
        tokens = accept_response.json()["data"]
        assert tokens["company_id"] == str(company_id)
        assert tokens["access_token"]

        login_response = await client.post(
            "/v1/auth/login", json={"email": invitee_email, "password": VALID_PASSWORD}
        )
        assert login_response.status_code == 200

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            new_user = (
                await session.execute(select(User).where(User.email == invitee_email))
            ).scalar_one()
            assert verify_password(new_user.password_hash, VALID_PASSWORD)

            refreshed = (
                await client.get(f"/v1/employees/{employee['id']}", headers=headers)
            ).json()["data"]
            # `user_id` isn't serialized on `EmployeeRead` — verified directly against the row.
            rbac = RbacService(session)
            codes = await rbac.get_permission_codes(new_user.id, company_id)
            assert codes == {
                "EMPLOYEE.VIEW",
                "EMPLOYEE.VIEW_COMPENSATION",
                "EMPLOYEE.VIEW_STATUTORY",
                "EMPLOYEE.VIEW_BANKING",
                "EMPLOYEE.VIEW_SENSITIVE",
                "EMPLOYEE.VIEW_EXPERIENCE",
                "EMPLOYEE.VIEW_NOMINEE",
                # Employee documents: the base role reads (SELF-scoped) its own documents; writes
                # need EMPLOYEE.UPDATE_SENSITIVE, which it does NOT hold (see the absence below).
                "EMPLOYEE.VIEW_DOCUMENTS",
                "PAYROLL.PAYSLIP_VIEW_OWN",
                # Leave decision 12 - the default employee role submits own leave and sees own
                # balances.
                "LEAVE.APPLICATION_SUBMIT",
                "LEAVE.BALANCE_VIEW",
            }
            assert refreshed["id"] == employee["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=[invitee_email])


async def test_invite_existing_account_resolve_flags_existing_account(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """SEC-08 — the public resolve response must tell the frontend this invite belongs to an
    existing account, so the accept form asks for a login password rather than a new one."""
    headers, company_id, user_id = await _register_tenant(client)
    invitee_email = f"invitee-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _create_employee(client, headers, personal_email=invitee_email)
        first_invite = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        first_token = _token_from_invite_url(first_invite.json()["data"]["invite_url"])
        accept = await client.post(
            f"/v1/public/account-invites/{first_token}/accept",
            json={"password": VALID_PASSWORD},
        )
        assert accept.status_code == 201

        second_invite = await client.post(
            "/v1/users/invite",
            headers=headers,
            json={"email": invitee_email, "role_code": "HR_ADMIN"},
        )
        second_token = _token_from_invite_url(second_invite.json()["data"]["invite_url"])

        resolve = await client.get(f"/v1/public/account-invites/{second_token}")
        assert resolve.status_code == 200
        assert resolve.json()["data"]["existing_account"] is True

        new_employee = await _create_employee(
            client, headers, first_name="Brand", personal_email=f"new-{uuid4().hex[:8]}@example.com"
        )
        new_invite = await client.post(
            f"/v1/employees/{new_employee['id']}/invite", headers=headers
        )
        new_token = _token_from_invite_url(new_invite.json()["data"]["invite_url"])
        new_resolve = await client.get(f"/v1/public/account-invites/{new_token}")
        assert new_resolve.status_code == 200
        assert new_resolve.json()["data"]["existing_account"] is False
    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=[invitee_email])


async def test_invite_existing_account_invite_alone_cannot_authenticate(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """SEC-08 core regression: possession of a valid, unexpired, unaccepted invite token must
    never by itself grant a session for an existing account — a password that does not match
    that account's real password must be rejected, and no session/membership may be created."""
    headers, company_id, user_id = await _register_tenant(client)
    invitee_email = f"invitee-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _create_employee(client, headers, personal_email=invitee_email)
        first_invite = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        first_token = _token_from_invite_url(first_invite.json()["data"]["invite_url"])
        accept = await client.post(
            f"/v1/public/account-invites/{first_token}/accept",
            json={"password": VALID_PASSWORD},
        )
        assert accept.status_code == 201

        second_invite = await client.post(
            "/v1/users/invite",
            headers=headers,
            json={"email": invitee_email, "role_code": "HR_ADMIN"},
        )
        second_token = _token_from_invite_url(second_invite.json()["data"]["invite_url"])

        wrong_password_accept = await client.post(
            f"/v1/public/account-invites/{second_token}/accept",
            json={"password": "TotallyWrong9"},
        )
        assert wrong_password_accept.status_code == 401
        assert wrong_password_accept.json()["error"]["code"] == "INVALID_CREDENTIALS"
        assert "access_token" not in wrong_password_accept.json()

        # The invite must remain unconsumed — a wrong-password attempt is not a "used" invite.
        retry_resolve = await client.get(f"/v1/public/account-invites/{second_token}")
        assert retry_resolve.status_code == 200

        # And membership must not have been granted by the failed attempt.
        factory = get_session_factory()
        async with factory() as session:
            existing_user = (
                await session.execute(select(User).where(User.email == invitee_email))
            ).scalar_one()
            rbac = RbacService(session)
            codes = await rbac.get_permission_codes(existing_user.id, company_id)
            assert "EMPLOYEE.CREATE" not in codes  # HR_ADMIN's own permission — never granted
    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=[invitee_email])


async def test_invite_existing_account_correct_password_accepts(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """SEC-08 — with the *correct* existing password, the invite still accepts normally: a new
    membership/role is granted in a *second* company (an existing account can belong to several
    companies — see `list_user_companies_for_login`) and a real session is issued."""
    headers, company_id, user_id = await _register_tenant(client)
    second_headers, second_company_id, second_admin_user_id = await _register_tenant(client)
    invitee_email = f"invitee-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _create_employee(client, headers, personal_email=invitee_email)
        first_invite = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        first_token = _token_from_invite_url(first_invite.json()["data"]["invite_url"])
        accept = await client.post(
            f"/v1/public/account-invites/{first_token}/accept",
            json={"password": VALID_PASSWORD},
        )
        assert accept.status_code == 201

        second_invite = await client.post(
            "/v1/users/invite",
            headers=second_headers,
            json={"email": invitee_email, "role_code": "HR_ADMIN"},
        )
        second_token = _token_from_invite_url(second_invite.json()["data"]["invite_url"])

        second_accept = await client.post(
            f"/v1/public/account-invites/{second_token}/accept",
            json={"password": VALID_PASSWORD},
        )
        assert second_accept.status_code == 201, second_accept.text
        assert second_accept.json()["data"]["access_token"]
        assert second_accept.json()["data"]["company_id"] == str(second_company_id)

        factory = get_session_factory()
        async with factory() as session:
            existing_user = (
                await session.execute(select(User).where(User.email == invitee_email))
            ).scalar_one()
            rbac = RbacService(session)
            codes = await rbac.get_permission_codes(existing_user.id, second_company_id)
            assert "EMPLOYEE.CREATE" in codes  # HR_ADMIN's catalogue, granted in the 2nd company
    finally:
        # The invitee's single `User` row now has sessions/refresh-tokens/memberships in *both*
        # companies (each `ON DELETE RESTRICT`) — sessions must be gone before *either* `Company`
        # row can be deleted (not just the one from the accept that created them), and the `User`
        # row itself only after *both* `_teardown` calls have cleared their own membership.
        extra_user_id = await _extra_user_id(email=invitee_email)
        if extra_user_id is not None:
            await _cleanup_extra_user_sessions(user_id=extra_user_id)
        await _teardown(company_id=company_id, user_id=user_id)
        await _teardown(company_id=second_company_id, user_id=second_admin_user_id)
        if extra_user_id is not None:
            await _cleanup_extra_user_row(user_id=extra_user_id)


async def test_invite_existing_account_wrong_password_does_not_leak_other_companies(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A wrong-password attempt against someone else's invite must not return anything about the
    target account — no company list, no session, nothing beyond the generic auth failure."""
    headers, company_id, user_id = await _register_tenant(client)
    invitee_email = f"invitee-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _create_employee(client, headers, personal_email=invitee_email)
        first_invite = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        first_token = _token_from_invite_url(first_invite.json()["data"]["invite_url"])
        await client.post(
            f"/v1/public/account-invites/{first_token}/accept",
            json={"password": VALID_PASSWORD},
        )

        second_invite = await client.post(
            "/v1/users/invite",
            headers=headers,
            json={"email": invitee_email, "role_code": "EMPLOYEE"},
        )
        second_token = _token_from_invite_url(second_invite.json()["data"]["invite_url"])

        response = await client.post(
            f"/v1/public/account-invites/{second_token}/accept",
            json={"password": "SomeoneElseGuess9"},
        )
        body = response.json()
        assert response.status_code == 401
        assert "companies" not in body.get("data", {})
        assert body["error"]["message"] == "Invalid email or password"
    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=[invitee_email])


async def test_invite_employee_without_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers, personal_email="scoped@example.com")

        # A second user with only EMPLOYEE.VIEW — not EMPLOYEE.INVITE.
        second_headers, _second_user_id = await _register_second_user(
            company_id=company_id, permission_codes=["EMPLOYEE.VIEW"]
        )
        response = await client.post(
            f"/v1/employees/{employee['id']}/invite", headers=second_headers
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_invite_employee_already_has_account_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    invitee_email = f"invitee-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _create_employee(client, headers, personal_email=invitee_email)
        first = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        token = _token_from_invite_url(first.json()["data"]["invite_url"])
        accept = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )
        assert accept.status_code == 201

        second = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "EMPLOYEE_ALREADY_HAS_ACCOUNT"
    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=[invitee_email])


async def test_invite_employee_missing_email_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)  # no personal_email
        response = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "EMPLOYEE_MISSING_EMAIL"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_reinvite_revokes_previous_token(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    invitee_email = f"invitee-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _create_employee(client, headers, personal_email=invitee_email)

        first = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        second = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        old_token = _token_from_invite_url(first.json()["data"]["invite_url"])
        new_token = _token_from_invite_url(second.json()["data"]["invite_url"])
        assert old_token != new_token

        old_resolve = await client.get(f"/v1/public/account-invites/{old_token}")
        assert old_resolve.status_code == 404

        new_resolve = await client.get(f"/v1/public/account-invites/{new_token}")
        assert new_resolve.status_code == 200
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_accept_unknown_token_returns_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response = await client.post(
        "/v1/public/account-invites/not-a-real-token/accept",
        json={"password": VALID_PASSWORD},
    )
    assert response.status_code == 404


async def test_accept_expired_token_returns_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    invitee_email = f"invitee-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _create_employee(client, headers, personal_email=invitee_email)
        invite = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        token = _token_from_invite_url(invite.json()["data"]["invite_url"])

        await _force_invite_expired(company_id=company_id, email=invitee_email)

        response = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_accept_weak_password_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    invitee_email = f"invitee-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _create_employee(client, headers, personal_email=invitee_email)
        invite = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        token = _token_from_invite_url(invite.json()["data"]["invite_url"])

        response = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": "short"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["code"] == "WEAK_PASSWORD"
    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=[invitee_email])


async def test_invite_user_creates_second_admin_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    invitee_email = f"seconduser-{uuid4().hex[:8]}@example.com"
    try:
        response = await client.post(
            "/v1/users/invite",
            headers=headers,
            json={"email": invitee_email, "role_code": "HR_ADMIN"},
        )
        assert response.status_code == 201, response.text
        token = _token_from_invite_url(response.json()["data"]["invite_url"])

        accept = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )
        assert accept.status_code == 201

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            new_user = (
                await session.execute(select(User).where(User.email == invitee_email))
            ).scalar_one()
            rbac = RbacService(session)
            codes = await rbac.get_permission_codes(new_user.id, company_id)
            assert "EMPLOYEE.CREATE" in codes  # HR_ADMIN gets the full Employee catalogue
    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=[invitee_email])


async def test_invite_user_email_already_in_company_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    invitee_email = f"dup-{uuid4().hex[:8]}@example.com"
    try:
        first_invite = await client.post(
            "/v1/users/invite",
            headers=headers,
            json={"email": invitee_email, "role_code": "EMPLOYEE"},
        )
        first_token = _token_from_invite_url(first_invite.json()["data"]["invite_url"])
        first_accept = await client.post(
            f"/v1/public/account-invites/{first_token}/accept", json={"password": VALID_PASSWORD}
        )
        assert first_accept.status_code == 201

        second_invite = await client.post(
            "/v1/users/invite",
            headers=headers,
            json={"email": invitee_email, "role_code": "HR_ADMIN"},
        )
        second_token = _token_from_invite_url(second_invite.json()["data"]["invite_url"])
        second_accept = await client.post(
            f"/v1/public/account-invites/{second_token}/accept", json={"password": VALID_PASSWORD}
        )
        assert second_accept.status_code == 409
        assert second_accept.json()["error"]["code"] == "USER_ALREADY_IN_COMPANY"
    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=[invitee_email])


async def test_assign_roles_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    invitee_email = f"reassign-{uuid4().hex[:8]}@example.com"
    try:
        invite = await client.post(
            "/v1/users/invite",
            headers=headers,
            json={"email": invitee_email, "role_code": "EMPLOYEE"},
        )
        token = _token_from_invite_url(invite.json()["data"]["invite_url"])
        await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )

        factory = get_session_factory()
        async with factory() as session:
            target_user = (
                await session.execute(select(User).where(User.email == invitee_email))
            ).scalar_one()

        response = await client.patch(
            f"/v1/users/{target_user.id}/roles",
            headers=headers,
            json={"role_codes": ["REPORTING_MANAGER"]},
        )
        assert response.status_code == 200
        assert response.json()["data"]["role_codes"] == ["REPORTING_MANAGER"]

        list_response = await client.get("/v1/users", headers=headers)
        assert list_response.status_code == 200
        rows = {row["user_id"]: row for row in list_response.json()["data"]}
        assert rows[str(target_user.id)]["role_codes"] == ["REPORTING_MANAGER"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=[invitee_email])


async def test_assign_roles_self_change_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.patch(
            f"/v1/users/{user_id}/roles", headers=headers, json={"role_codes": ["EMPLOYEE"]}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SELF_ROLE_CHANGE_NOT_ALLOWED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_assign_roles_invalid_code_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    invitee_email = f"badrole-{uuid4().hex[:8]}@example.com"
    try:
        invite = await client.post(
            "/v1/users/invite",
            headers=headers,
            json={"email": invitee_email, "role_code": "EMPLOYEE"},
        )
        token = _token_from_invite_url(invite.json()["data"]["invite_url"])
        await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )

        factory = get_session_factory()
        async with factory() as session:
            target_user = (
                await session.execute(select(User).where(User.email == invitee_email))
            ).scalar_one()

        response = await client.patch(
            f"/v1/users/{target_user.id}/roles",
            headers=headers,
            json={"role_codes": ["SUPER_ADMIN"]},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_ROLE_CODE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=[invitee_email])


async def _register_second_user(
    *, company_id: UUID, permission_codes: list[str]
) -> tuple[dict[str, str], UUID]:
    """Mirrors `test_onboarding_case.py::_create_permission_scoped_user` — a second user in the
    same tenant, granted only the given permission codes, for permission-gating tests."""
    from hrms.core.auth.jwt import create_access_token
    from hrms.core.auth.passwords import hash_password
    from hrms.core.db.models.identity import (
        Permission,
        Role,
        RolePermission,
        Session,
        UserCompany,
        UserRole,
    )
    from hrms.core.db.models.identity import (
        User as UserModel,
    )

    factory = get_session_factory()
    async with factory() as session:
        permissions = (
            (await session.execute(select(Permission).where(Permission.code.in_(permission_codes))))
            .scalars()
            .all()
        )
        assert len(permissions) == len(permission_codes)

        now = datetime.now(UTC)
        role_id = uuid4()
        session.add(
            Role(
                id=role_id,
                company_id=company_id,
                code=f"ACCOUNT_INVITE_TEST_ROLE_{role_id.hex[:8]}",
                name="Account invite test role",
                is_system=False,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        for permission in permissions:
            session.add(
                RolePermission(role_id=role_id, permission_id=permission.id, data_scope="COMPANY")
            )

        scoped_user_id = uuid4()
        session.add(
            UserModel(
                id=scoped_user_id,
                email=f"scoped-account-invite-{scoped_user_id.hex[:8]}@example.com",
                password_hash=hash_password(VALID_PASSWORD),
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        user_company = UserCompany(
            id=uuid4(),
            user_id=scoped_user_id,
            company_id=company_id,
            is_primary=False,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(user_company)
        await session.flush()
        session.add(UserRole(id=uuid4(), user_company_id=user_company.id, role_id=role_id))
        scoped_session_id = uuid4()
        session.add(
            Session(
                id=scoped_session_id,
                user_id=scoped_user_id,
                company_id=company_id,
                expires_at=now + timedelta(days=1),
            )
        )
        await session.commit()

    token = create_access_token(
        user_id=scoped_user_id,
        company_id=company_id,
        session_id=scoped_session_id,
        employee_id=None,
    )
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}, scoped_user_id
