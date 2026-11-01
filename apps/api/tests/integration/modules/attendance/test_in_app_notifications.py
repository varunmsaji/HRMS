"""In-app notification feed: generic behaviour (ownership, tenancy, idempotency, pagination) and
the first producer, HR-initiated face enrollment (FACE_ENROLLMENT_REQUESTED)."""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import FakeFaceProvider
from tests.integration.modules.attendance.test_attendance_security import (
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_face_enrollment import (
    ANGLES,
    _employee,
    _open,
    _sql,
    _submit,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.permissions import ATTENDANCE_PUNCH, ATTENDANCE_VIEW
from hrms.modules.notification.service import NotificationService, validate_metadata
from hrms.modules.notification.types import FACE_ENROLLMENT_REQUESTED, REGISTRY

pytestmark = pytest.mark.asyncio

Tenant = tuple[dict[str, str], UUID]
FORBIDDEN = ("embedding", "template", "liveness", "score", "photo", "image", "face_token")


async def _login_for_employee(company_id: UUID, employee_id: str) -> tuple[dict[str, str], UUID]:
    """Gives the employee a login (linked to the employee row) -> (their headers, their user id)."""
    headers, user_id = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_PUNCH, ATTENDANCE_VIEW],
        data_scope="SELF",
        caller_employee_id=UUID(employee_id),
    )
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("UPDATE employee SET user_id = :u WHERE id = :e AND company_id = :c"),
            {"u": user_id, "e": employee_id, "c": company_id},
        )
        await session.commit()
    return headers, user_id


async def _produce(
    company_id: UUID, user_id: UUID, *, title: str = "Hello", dedupe_key: str | None = None
) -> Any:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        row = await NotificationService(session).create_notification(
            company_id=company_id,
            recipient_user_id=user_id,
            type=FACE_ENROLLMENT_REQUESTED,
            title=title,
            body="body",
            dedupe_key=dedupe_key,
        )
        await session.commit()
        return row.id if row else None


async def _rows(company_id: UUID) -> list[Any]:
    return await _sql(
        company_id,
        "SELECT id, recipient_user_id, type, title, body, action_url, metadata, dedupe_key,"
        " read_at FROM notification WHERE company_id = :cid ORDER BY created_at",
    )


async def _feed(client: AsyncClient, headers: dict[str, str], **params: Any) -> Any:
    response = await client.get("/v1/notifications", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _unread(client: AsyncClient, headers: dict[str, str]) -> int:
    response = await client.get("/v1/notifications/unread-count", headers=headers)
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["unread_count"])


# --- generic feed ------------------------------------------------------------------------------


async def test_feed_unread_count_read_and_read_all(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    headers, user_id = await _login_for_employee(company_id, employee_id)
    ids = [await _produce(company_id, user_id, title=f"n{i}") for i in range(5)]
    assert all(ids)

    assert await _unread(client, headers) == 5
    page1 = await _feed(client, headers, per_page=2, page=1)
    page2 = await _feed(client, headers, per_page=2, page=2)
    assert [n["title"] for n in page1["data"]] == ["n4", "n3"]  # newest first
    assert [n["title"] for n in page2["data"]] == ["n2", "n1"]
    assert page1["pagination"]["total"] == 5 and page1["pagination"]["total_pages"] == 3

    target = page1["data"][0]
    assert target["is_read"] is False and target["read_at"] is None
    first = await client.patch(f"/v1/notifications/{target['id']}/read", headers=headers)
    assert first.status_code == 200 and first.json()["data"]["is_read"] is True
    read_at = first.json()["data"]["read_at"]
    again = await client.patch(f"/v1/notifications/{target['id']}/read", headers=headers)
    assert again.status_code == 200 and again.json()["data"]["read_at"] == read_at  # idempotent
    assert await _unread(client, headers) == 4
    unread_only = await _feed(client, headers, unread_only="true", per_page=100)
    assert len(unread_only["data"]) == 4 and target["id"] not in [
        n["id"] for n in unread_only["data"]
    ]

    done = await client.post("/v1/notifications/read-all", headers=headers)
    assert done.status_code == 200
    assert done.json()["data"] == {"updated": 4, "unread_count": 0}
    assert (await client.post("/v1/notifications/read-all", headers=headers)).json()["data"][
        "updated"
    ] == 0
    assert await _unread(client, headers) == 0
    assert len((await _feed(client, headers, per_page=100))["data"]) == 5  # still listed


async def test_dismiss_hides_but_retains(client: AsyncClient, face_tenant: Tenant) -> None:
    admin, company_id = face_tenant
    headers, user_id = await _login_for_employee(company_id, await _employee(client, admin))
    nid = await _produce(company_id, user_id)
    assert (
        await client.post(f"/v1/notifications/{nid}/dismiss", headers=headers)
    ).status_code == 204
    assert (await _feed(client, headers))["data"] == []
    assert await _unread(client, headers) == 0
    assert len(await _rows(company_id)) == 1  # retained, not deleted
    # A dismissed notification can no longer be acted on.
    assert (await client.patch(f"/v1/notifications/{nid}/read", headers=headers)).status_code == 404


async def test_users_cannot_see_or_touch_each_others_notifications(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    a_headers, a_user = await _login_for_employee(company_id, await _employee(client, admin, "A"))
    b_headers, b_user = await _login_for_employee(company_id, await _employee(client, admin, "B"))
    a_note = await _produce(company_id, a_user, title="for A")

    assert (await _feed(client, b_headers))["data"] == []
    assert await _unread(client, b_headers) == 0
    # Same safe 404 as a nonexistent id: no ownership oracle.
    other = await client.patch(f"/v1/notifications/{a_note}/read", headers=b_headers)
    missing = await client.patch(f"/v1/notifications/{uuid4()}/read", headers=b_headers)
    assert other.status_code == missing.status_code == 404
    assert other.json()["error"]["code"] == missing.json()["error"]["code"]
    assert (
        await client.post(f"/v1/notifications/{a_note}/dismiss", headers=b_headers)
    ).status_code == 404
    # read-all by B must not touch A's rows
    await client.post("/v1/notifications/read-all", headers=b_headers)
    assert await _unread(client, a_headers) == 1
    # A client cannot choose the recipient: a user_id query parameter is ignored.
    spoof = await _feed(client, b_headers, user_id=str(a_user), recipient_user_id=str(a_user))
    assert spoof["data"] == []
    # And the admin (a different user) sees none of it either.
    assert (await _feed(client, admin))["data"] == []
    del b_user


async def test_cross_company_access_fails(
    client: AsyncClient, face_tenant: Tenant, face_tenant_b: Tenant
) -> None:
    admin_a, company_a = face_tenant
    admin_b, company_b = face_tenant_b
    _, user_a = await _login_for_employee(company_a, await _employee(client, admin_a))
    note = await _produce(company_a, user_a)
    assert (
        await client.patch(f"/v1/notifications/{note}/read", headers=admin_b)
    ).status_code == 404
    assert (
        await client.post(f"/v1/notifications/{note}/dismiss", headers=admin_b)
    ).status_code == 404
    assert (await _feed(client, admin_b))["data"] == []
    # A company header naming another tenant is refused outright.
    mismatched = {**admin_b, "X-Company-Id": str(company_a)}
    assert (await client.get("/v1/notifications", headers=mismatched)).status_code == 404
    # The producer cannot address a user of another company.
    assert await _produce(company_b, user_a) is None
    assert await _rows(company_b) == []


async def test_unauthenticated_and_deactivated_users_are_refused(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    for method, url in (
        ("GET", "/v1/notifications"),
        ("GET", "/v1/notifications/unread-count"),
        ("POST", "/v1/notifications/read-all"),
        ("PATCH", f"/v1/notifications/{uuid4()}/read"),
        ("POST", f"/v1/notifications/{uuid4()}/dismiss"),
    ):
        assert (await client.request(method, url)).status_code == 401, (method, url)
    headers, user_id = await _login_for_employee(company_id, await _employee(client, admin))
    await _produce(company_id, user_id)
    assert (await client.get("/v1/notifications", headers=headers)).status_code == 200
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("UPDATE \"user\" SET status = 'INACTIVE' WHERE id = :u"), {"u": user_id}
        )
        await session.commit()
    # Same behaviour as every other authenticated route.
    assert (await client.get("/v1/notifications", headers=headers)).status_code == 401
    # ... and the producer does not notify an inactive user.
    assert await _produce(company_id, user_id, dedupe_key="x") is None


async def test_dedupe_key_and_concurrent_creation_make_one_row(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    _, user_id = await _login_for_employee(company_id, await _employee(client, admin))
    results = await asyncio.gather(
        *[_produce(company_id, user_id, dedupe_key="EVENT:1") for _ in range(6)]
    )
    assert len([r for r in results if r]) == 1
    assert len(await _rows(company_id)) == 1
    assert await _produce(company_id, user_id, dedupe_key="EVENT:2") is not None
    assert len(await _rows(company_id)) == 2


async def test_producer_guards_metadata_and_links() -> None:
    assert validate_metadata({"expires_at": "2026-01-01"}) == {"expires_at": "2026-01-01"}
    for bad in (
        {"embedding": [0.1]},
        {"nested": {"Liveness_Score": 0.9}},
        {"x": [{"photo_url": "u"}]},
        {"face_token": "t"},
        {"blob": "x" * 5000},
    ):
        with pytest.raises(ValueError):
            validate_metadata(bad)
    assert FACE_ENROLLMENT_REQUESTED.code in REGISTRY
    service = NotificationService(None)  # type: ignore[arg-type]  # rejected before any query
    for url in ("https://evil.example/x", "//evil.example", "javascript:alert(1)"):
        with pytest.raises(ValueError):
            await service.create_notification(
                company_id=uuid4(),
                recipient_user_id=uuid4(),
                type=FACE_ENROLLMENT_REQUESTED,
                title="t",
                body="b",
                action_url=url,
            )


# --- face enrollment producer ------------------------------------------------------------------


async def test_hr_initiation_creates_exactly_one_notification(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    headers, user_id = await _login_for_employee(company_id, employee_id)
    assert await _unread(client, headers) == 0

    opened = await _open(client, admin, employee_id)
    assert opened.status_code == 201
    window_id = opened.json()["data"]["id"]

    rows = await _rows(company_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.recipient_user_id == user_id and row.type == "FACE_ENROLLMENT_REQUESTED"
    assert row.dedupe_key == f"FACE_ENROLLMENT_REQUESTED:{window_id}"
    assert row.action_url == "/app/attendance/face-setup"

    feed = (await _feed(client, headers))["data"]
    assert len(feed) == 1
    note = feed[0]
    assert note["title"] == "Face Enrollment Required"
    assert note["body"] == (
        "Your HR team has requested you to complete face enrollment for attendance."
    )
    assert note["action_label"] == "Complete Face Enrollment"
    assert note["entity_type"] == "face_enrollment_window" and note["entity_id"] == window_id
    assert note["is_read"] is False and await _unread(client, headers) == 1
    blob = str(note).lower()
    for word in FORBIDDEN:
        assert word not in blob, word
    # HR's own feed is untouched.
    assert (await _feed(client, admin))["data"] == []

    # Duplicate initiation (409), repeated read calls and the employee's own start add nothing.
    assert (await _open(client, admin, employee_id)).status_code == 409
    await client.post("/v1/attendance/face-enrollment/me/window", headers=headers)
    assert len(await _rows(company_id)) == 1

    # Reading it persists, and the canonical enrollment status is still the server's.
    assert (
        await client.patch(f"/v1/notifications/{note['id']}/read", headers=headers)
    ).status_code == 200
    assert await _unread(client, headers) == 0
    status = await client.get("/v1/attendance/face-enrollment/me", headers=headers)
    assert status.json()["data"]["enrollment_state"] == "ENROLLMENT_AVAILABLE"


async def test_concurrent_hr_initiations_create_one_notification(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _login_for_employee(company_id, employee_id)
    responses = await asyncio.gather(*[_open(client, admin, employee_id) for _ in range(4)])
    assert sorted(r.status_code for r in responses).count(201) == 1
    assert len(await _rows(company_id)) == 1


async def test_self_initiation_and_refused_initiations_create_none(
    client: AsyncClient,
    face_tenant: Tenant,
    face_tenant_b: Tenant,
    fake_face_provider: FakeFaceProvider,
) -> None:
    admin, company_id = face_tenant
    admin_b, company_b = face_tenant_b
    employee_id = await _employee(client, admin)
    me, _ = await _login_for_employee(company_id, employee_id)
    other = await _employee(client, admin, "Other")

    own = await client.post("/v1/attendance/face-enrollment/me/window", headers=me)
    assert own.status_code == 201
    assert (await _open(client, me, other)).status_code == 403  # employee initiating for others
    assert (await _open(client, me, employee_id)).status_code == 403  # lacks manage permission
    assert (
        await client.post(f"/v1/attendance/face-profiles/{employee_id}/enrollment-window")
    ).status_code in (401, 403)
    employee_b = await _employee(client, admin_b)
    assert (await _open(client, admin, employee_b)).status_code == 404  # cross-tenant
    assert await _rows(company_id) == []
    assert await _rows(company_b) == []


async def test_notification_failure_never_undoes_the_window(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    headers, _ = await _login_for_employee(company_id, employee_id)

    async def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("notification store unavailable")

    monkeypatch.setattr(NotificationService, "create_notification", boom)
    opened = await _open(client, admin, employee_id)
    assert opened.status_code == 201
    assert await _rows(company_id) == []
    status = await client.get("/v1/attendance/face-enrollment/me", headers=headers)
    assert status.json()["data"]["enrollment_state"] == "ENROLLMENT_AVAILABLE"
    # The employee can still enroll from the canonical status - no notification needed.
    assert (await _submit(client, headers)).status_code == 201
    assert len(ANGLES) == 5


async def test_database_error_in_notification_insert_leaves_window_and_audit_committed(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Why the savepoint exists: a real SQL error (not just a Python exception) inside the
    notification insert aborts the surrounding Postgres transaction unless it is contained.
    Contained -> the window, its audit row and the later email queueing all still commit."""
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await _login_for_employee(company_id, employee_id)

    async def sql_error(self: NotificationService, **kwargs: Any) -> None:
        await self._session.execute(
            text("INSERT INTO notification (id) VALUES (gen_random_uuid())")
        )

    monkeypatch.setattr(NotificationService, "create_notification", sql_error)
    opened = await _open(client, admin, employee_id)
    assert opened.status_code == 201
    window_id = opened.json()["data"]["id"]
    assert await _rows(company_id) == []
    windows = await _sql(
        company_id, f"SELECT status FROM face_enrollment_window WHERE id = '{UUID(window_id)}'"
    )
    assert [w.status for w in windows] == ["OPEN"]
    audits = await _sql(
        company_id,
        "SELECT 1 FROM audit_log WHERE action = 'FACE_ENROLLMENT_OPENED'"
        f" AND entity_id = '{UUID(window_id)}'",
    )
    assert len(audits) == 1


async def test_rolled_back_initiation_leaves_no_orphan_notification(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The notification shares the window's transaction: if the request fails after both were
    written, both are rolled back together."""
    from hrms.modules.attendance.exceptions import FaceEnrollmentWindowAlreadyOpenError
    from hrms.modules.attendance.face_service import FaceEnrollmentService

    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    headers, _ = await _login_for_employee(company_id, employee_id)

    async def fail_after_notification(self: Any, *args: Any, **kwargs: Any) -> str:
        raise FaceEnrollmentWindowAlreadyOpenError()

    monkeypatch.setattr(FaceEnrollmentService, "_queue_requested_email", fail_after_notification)
    assert (await _open(client, admin, employee_id)).status_code == 409
    assert await _rows(company_id) == []
    assert await _unread(client, headers) == 0
    windows = await _sql(company_id, "SELECT 1 FROM face_enrollment_window")
    assert windows == []


async def test_employee_without_login_gets_no_notification_and_window_opens(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    assert (await _open(client, admin, employee_id)).status_code == 201
    assert await _rows(company_id) == []
