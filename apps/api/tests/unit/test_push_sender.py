"""FCM push sender: request shape, dead-token detection, and that a failure never raises."""

import httpx
import pytest

from hrms.modules.notification.push import (
    DisabledPushSender,
    FcmPushSender,
    PushMessage,
    PushResult,
    _is_invalid_token,
    build_fcm_body,
    get_push_sender,
)

MSG = PushMessage(
    title="Leave request", body="Asha applied for 2 days", data={"notification_id": "n1"}
)


def test_body_is_string_only_and_truncated() -> None:
    long = PushMessage(title="t" * 500, body="b" * 900, data={"n": "1"}, high_priority=True)
    body = build_fcm_body("tok", long)["message"]
    assert len(body["notification"]["title"]) == 120
    assert len(body["notification"]["body"]) == 240
    assert body["android"]["priority"] == "HIGH"
    assert all(isinstance(v, str) for v in body["data"].values())


@pytest.mark.parametrize(
    ("status", "payload", "dead"),
    [
        (404, None, True),
        (400, {"error": {"status": "NOT_FOUND"}}, True),
        (400, {"error": {"details": [{"errorCode": "UNREGISTERED"}]}}, True),
        (
            400,
            {
                "error": {
                    "status": "INVALID_ARGUMENT",
                    "message": "The registration token is not valid",
                }
            },
            True,
        ),
        (400, {"error": {"status": "INVALID_ARGUMENT", "message": "Invalid JSON payload"}}, False),
        (500, None, False),
        (401, {"error": {}}, False),
    ],
)
def test_dead_token_detection(status: int, payload: object, dead: bool) -> None:
    assert _is_invalid_token(status, payload) is dead


def _sender(handler: httpx.MockTransport, monkeypatch: pytest.MonkeyPatch) -> FcmPushSender:
    real = httpx.AsyncClient
    monkeypatch.setattr(
        "hrms.modules.notification.push.httpx.AsyncClient",
        lambda **kw: real(transport=handler, **kw),
    )
    sender = FcmPushSender(
        project_id="proj", service_account={"client_email": "x", "private_key": "k"}
    )

    # Skip the OAuth exchange; it is a signed-JWT call covered by Google's own contract.
    async def fake_token(_client: httpx.AsyncClient) -> str:
        return "access"

    monkeypatch.setattr(sender, "_token", fake_token)
    return sender


@pytest.mark.asyncio
async def test_sent_and_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"name": "m"})

    sender = _sender(httpx.MockTransport(handler), monkeypatch)
    assert await sender.send("tok", MSG) is PushResult.SENT
    assert seen["url"] == "https://fcm.googleapis.com/v1/projects/proj/messages:send"
    assert seen["auth"] == "Bearer access"


@pytest.mark.asyncio
async def test_unregistered_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    dead = _sender(httpx.MockTransport(lambda r: httpx.Response(404, json={})), monkeypatch)
    assert await dead.send("tok", MSG) is PushResult.INVALID_TOKEN

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    down = _sender(httpx.MockTransport(boom), monkeypatch)
    assert await down.send("tok", MSG) is PushResult.FAILED


def test_disabled_by_default() -> None:
    from hrms.core.config.settings import Settings

    assert isinstance(get_push_sender(Settings()), DisabledPushSender)
