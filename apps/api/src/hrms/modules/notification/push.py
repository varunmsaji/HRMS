"""Push delivery for mobile (Firebase Cloud Messaging HTTP v1).

`PushSender.send` delivers one message to one device token and says what happened, so the caller
can drop tokens FCM reports as dead and leave everything else alone. Nothing here raises: a push
is a courtesy on top of the durable in-app notification, never a reason to fail anything.

Authentication uses the service-account key directly (RS256 JWT exchanged for a short-lived OAuth
token, cached until shortly before it expires) with `pyjwt` and `httpx`, both already dependencies,
so no Google client library is added.
"""

import json
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import httpx
import jwt

from hrms.core.config.settings import Settings, get_settings
from hrms.core.observability.logging import get_logger, safe_error, safe_log

_logger = get_logger(__name__)

_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_TIMEOUT = httpx.Timeout(10.0)
#: FCM caps `data` at 4 KB in total and the title/body are shown on a lock screen: keep both short.
_MAX_TITLE = 120
_MAX_BODY = 240


class PushResult(StrEnum):
    SENT = "SENT"
    #: FCM says this token will never work again (app uninstalled / token rotated): delete it.
    INVALID_TOKEN = "INVALID_TOKEN"
    #: Anything else (network, quota, auth): keep the token, nothing is retried.
    FAILED = "FAILED"


@dataclass(frozen=True)
class PushMessage:
    title: str
    body: str
    #: String-to-string only (an FCM requirement). The app uses `notification_id` / `action_url`
    #: to open the right screen when the push is tapped.
    data: dict[str, str]
    high_priority: bool = False


class PushSender(Protocol):
    async def send(self, token: str, message: PushMessage) -> PushResult: ...


class DisabledPushSender:
    async def send(self, token: str, message: PushMessage) -> PushResult:  # noqa: ARG002
        return PushResult.FAILED


def build_fcm_body(token: str, message: PushMessage) -> dict[str, Any]:
    """The HTTP v1 request body. Pure, so it can be tested without a network."""
    return {
        "message": {
            "token": token,
            "notification": {
                "title": message.title[:_MAX_TITLE],
                "body": message.body[:_MAX_BODY],
            },
            "data": {k: str(v) for k, v in message.data.items()},
            "android": {"priority": "HIGH" if message.high_priority else "NORMAL"},
            "apns": {"headers": {"apns-priority": "10" if message.high_priority else "5"}},
        }
    }


def _is_invalid_token(status: int, payload: Any) -> bool:
    """FCM's "this registration token is dead" answers: 404 / NOT_FOUND / UNREGISTERED, or a 400
    INVALID_ARGUMENT that names the token (the only per-call argument we vary)."""
    if status == 404:
        return True
    if status != 400 or not isinstance(payload, dict):
        return False
    error = payload.get("error") or {}
    if error.get("status") == "NOT_FOUND":
        return True
    codes = {d.get("errorCode") for d in error.get("details") or [] if isinstance(d, dict)}
    if "UNREGISTERED" in codes:
        return True
    return (
        error.get("status") == "INVALID_ARGUMENT"
        and "token" in str(error.get("message", "")).lower()
    )


class FcmPushSender:
    def __init__(self, *, project_id: str, service_account: dict[str, Any]) -> None:
        self._project_id = project_id
        self._account = service_account
        self._access_token: str | None = None
        self._expires_at = 0.0

    async def _token(self, client: httpx.AsyncClient) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": self._account["client_email"],
                "scope": _SCOPE,
                "aud": self._account.get("token_uri", "https://oauth2.googleapis.com/token"),
                "iat": now,
                "exp": now + 3600,
            },
            self._account["private_key"],
            algorithm="RS256",
        )
        resp = await client.post(
            self._account.get("token_uri", "https://oauth2.googleapis.com/token"),
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        resp.raise_for_status()
        body = resp.json()
        self._access_token = str(body["access_token"])
        self._expires_at = time.time() + float(body.get("expires_in", 3600))
        return self._access_token

    async def send(self, token: str, message: PushMessage) -> PushResult:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                access = await self._token(client)
                resp = await client.post(
                    f"https://fcm.googleapis.com/v1/projects/{self._project_id}/messages:send",
                    headers={"Authorization": f"Bearer {access}"},
                    json=build_fcm_body(token, message),
                )
            if resp.status_code == 200:
                return PushResult.SENT
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            if _is_invalid_token(resp.status_code, payload):
                return PushResult.INVALID_TOKEN
            if resp.status_code in (401, 403):
                self._access_token = None  # force a fresh OAuth token next time
            safe_log(_logger.warning, "push_send_rejected", status=resp.status_code)
        except Exception as exc:  # noqa: BLE001 - a push must never break the caller
            safe_log(_logger.warning, "push_send_failed", **safe_error(exc))
        return PushResult.FAILED


def _load_service_account(settings: Settings) -> dict[str, Any] | None:
    raw = settings.fcm_service_account_json
    if not raw and settings.fcm_service_account_file:
        raw = Path(settings.fcm_service_account_file).read_text()
    if not raw:
        return None
    data = json.loads(raw)
    if not isinstance(data, dict) or "client_email" not in data or "private_key" not in data:
        return None
    return data


def get_push_sender(settings: Settings | None = None) -> PushSender:
    settings = settings or get_settings()
    if settings.push_provider != "fcm":
        return DisabledPushSender()
    try:
        account = _load_service_account(settings)
    except (OSError, ValueError) as exc:
        safe_log(_logger.error, "push_config_unreadable", **safe_error(exc))
        return DisabledPushSender()
    project = settings.fcm_project_id or (account or {}).get("project_id", "")
    if not account or not project:
        safe_log(_logger.error, "push_config_incomplete")
        return DisabledPushSender()
    return FcmPushSender(project_id=str(project), service_account=account)
