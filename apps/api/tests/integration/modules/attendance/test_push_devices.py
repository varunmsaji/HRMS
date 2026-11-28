"""Push device registration (`/v1/notifications/devices`) and the worker's delivery step."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_face_enrollment import _employee, _sql
from tests.integration.modules.attendance.test_in_app_notifications import (
    Tenant,
    _login_for_employee,
    _produce,
)

from hrms.core.db.session import session_scope
from hrms.modules.notification.push import PushMessage, PushResult
from hrms.modules.notification.service import NotificationService
from hrms.modules.notification.tasks import push_notification
from hrms.modules.notification.types import FACE_ENROLLMENT_REQUESTED

pytestmark = pytest.mark.asyncio

TOKEN_A = "fcm-token-device-a-" + "x" * 30
TOKEN_B = "fcm-token-device-b-" + "y" * 30


async def _devices(company_id: UUID) -> list[tuple[str, UUID]]:
    rows = await _sql(
        company_id,
        "SELECT token, user_id FROM device_token WHERE company_id = :cid ORDER BY created_at",
    )
    return [(r[0], r[1]) for r in rows]


async def _register(client: AsyncClient, headers: dict[str, str], token: str) -> int:
    response = await client.post(
        "/v1/notifications/devices",
        headers=headers,
        json={"token": token, "platform": "android", "app_version": "1.2.3"},
    )
    return response.status_code


class _FakeSender:
    def __init__(self, results: dict[str, PushResult]) -> None:
        self.results = results
        self.sent: list[tuple[str, PushMessage]] = []

    async def send(self, token: str, message: PushMessage) -> PushResult:
        self.sent.append((token, message))
        return self.results.get(token, PushResult.SENT)


async def test_register_is_idempotent_and_moves_between_users(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    first, first_id = await _login_for_employee(company_id, await _employee(client, admin))
    second, second_id = await _login_for_employee(company_id, await _employee(client, admin))

    assert await _register(client, first, TOKEN_A) == 200
    assert await _register(client, first, TOKEN_A) == 200
    assert await _devices(company_id) == [(TOKEN_A, first_id)]

    # The same phone, a second person signs in: the token moves, it is not duplicated.
    assert await _register(client, second, TOKEN_A) == 200
    assert await _devices(company_id) == [(TOKEN_A, second_id)]


async def test_unregister_only_removes_own_token(client: AsyncClient, face_tenant: Tenant) -> None:
    admin, company_id = face_tenant
    owner, owner_id = await _login_for_employee(company_id, await _employee(client, admin))
    other, _ = await _login_for_employee(company_id, await _employee(client, admin))
    assert await _register(client, owner, TOKEN_A) == 200

    body = {"token": TOKEN_A}
    stranger = await client.post("/v1/notifications/devices/unregister", headers=other, json=body)
    assert stranger.status_code == 204  # never reveals who holds it
    assert await _devices(company_id) == [(TOKEN_A, owner_id)]

    mine = await client.post("/v1/notifications/devices/unregister", headers=owner, json=body)
    assert mine.status_code == 204
    assert await _devices(company_id) == []
    again = await client.post("/v1/notifications/devices/unregister", headers=owner, json=body)
    assert again.status_code == 204  # idempotent


async def test_register_validates_input_and_needs_login(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    headers, _ = await _login_for_employee(company_id, await _employee(client, admin))
    url = "/v1/notifications/devices"
    assert (
        await client.post(url, headers=headers, json={"token": "short", "platform": "android"})
    ).status_code == 422
    assert (
        await client.post(url, headers=headers, json={"token": TOKEN_A, "platform": "web"})
    ).status_code == 422
    assert (
        await client.post(url, json={"token": TOKEN_A, "platform": "android"})
    ).status_code == 401


async def test_push_goes_to_recipient_devices_only_and_prunes_dead_tokens(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    recipient, recipient_id = await _login_for_employee(company_id, await _employee(client, admin))
    bystander, _ = await _login_for_employee(company_id, await _employee(client, admin))
    assert await _register(client, recipient, TOKEN_A) == 200
    assert await _register(client, recipient, TOKEN_B) == 200
    assert await _register(client, bystander, "fcm-token-bystander-" + "z" * 30) == 200

    notification_id = await _produce(company_id, recipient_id, title="Leave approved")
    sender = _FakeSender({TOKEN_B: PushResult.INVALID_TOKEN})
    counts = await push_notification(company_id, notification_id, sender)

    assert counts == {"sent": 1, "removed": 1, "failed": 0}
    assert {t for t, _ in sender.sent} == {TOKEN_A, TOKEN_B}  # never the bystander's phone
    assert sender.sent[0][1].title == "Leave approved"
    assert sender.sent[0][1].data["notification_id"] == str(notification_id)
    remaining = {t for t, _ in await _devices(company_id)}
    assert TOKEN_B not in remaining and TOKEN_A in remaining


async def test_push_skips_a_notification_already_read(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    recipient, recipient_id = await _login_for_employee(company_id, await _employee(client, admin))
    assert await _register(client, recipient, TOKEN_A) == 200
    notification_id = await _produce(company_id, recipient_id)
    await client.patch(f"/v1/notifications/{notification_id}/read", headers=recipient)

    sender = _FakeSender({})
    assert await push_notification(company_id, notification_id, sender) == {
        "sent": 0,
        "removed": 0,
        "failed": 0,
    }
    assert sender.sent == []


async def test_creating_a_notification_queues_a_push_only_when_enabled(
    client: AsyncClient, face_tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hrms.core.config.settings import Settings
    from hrms.modules.notification import service as service_module
    from hrms.modules.notification import tasks as tasks_module

    admin, company_id = face_tenant
    _, recipient_id = await _login_for_employee(company_id, await _employee(client, admin))
    queued: list[tuple[str, str]] = []
    monkeypatch.setattr(tasks_module.send_push, "delay", lambda cid, nid: queued.append((cid, nid)))

    async def produce(title: str) -> UUID:
        # `session_scope` is what runs post-commit actions, as the app's own code paths do.
        async with session_scope(company_id=str(company_id)) as session:
            row = await NotificationService(session).create_notification(
                company_id=company_id,
                recipient_user_id=recipient_id,
                type=FACE_ENROLLMENT_REQUESTED,
                title=title,
                body="body",
            )
            assert row is not None
            return row.id

    await produce("provider off")
    assert queued == []  # the default: nothing is queued

    monkeypatch.setattr(service_module, "get_settings", lambda: Settings(push_provider="fcm"))
    nid = await produce("provider on")
    assert queued == [(str(company_id), str(nid))]
