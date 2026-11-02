"""Azure AI Face adapter for face attendance (`face_verification_provider="azure"`), behind the same
`FaceVerificationProvider` port as the Face++ and open-source engines. Plain `httpx`, no SDK.

Azure behaviour this adapter relies on:
- Auth is the `Ocp-Apim-Subscription-Key` header; the resource URL is `azure_endpoint`.
- One Large Person Group (`azure_face_person_group_id`, created on first use) holds one *person*
  per employee; the person's id is what this adapter returns as `person_id` and what is stored in
  `employee_face_profile.provider_person_id`. Each reference photo is a persisted face of that
  person. Persisted faces never expire, and no image is kept on our side.
- `detect` returns a `faceId` (valid 24h) per face. Zero faces is a success with `[]`, never an
  error. Face IDs, like person-group verification, are a *Limited Access* feature: Microsoft must
  approve the resource (https://aka.ms/facerecognition). Until then Azure answers 403 and this
  adapter surfaces a `FaceProviderError` (error code logged, never the body).
- `verify` (faceId vs personId) answers `confidence` on 0..1 — the same scale as the stored
  `similarity` column, so no rescaling. The best of the person's reference faces decides.
- Errors are `{"error": {"code", "message"}}`. HTTP 429 (the free tier allows 20 calls/minute) is
  retried with the server's `Retry-After`, bounded, rather than failing the whole punch.
- Free-tier (F0) keeps the concurrency gate at `face_provider_max_concurrency`; nothing here calls
  a paid-only feature (no liveness/analysis attributes), so an F0 resource never bills."""

import asyncio
import re
import time
from decimal import Decimal
from typing import Any

import httpx

from hrms.core.config.settings import Settings
from hrms.core.observability.logging import get_logger
from hrms.core.observability.metrics import (
    DEPENDENCY_CALLS,
    DEPENDENCY_DURATION,
    DEPENDENCY_ERRORS,
    safe_count,
    safe_observe,
)
from hrms.modules.attendance.face_verification import (
    FaceMatchResult,
    FaceProviderError,
    FaceProviderMultipleFacesError,
    FaceProviderNoFaceError,
    MatchDecision,
)

PROVIDER_AZURE = "AZURE"

_API = "/face/v1.0"
_DETECTION_MODEL = "detection_03"
_RECOGNITION_MODEL = "recognition_04"
_MAX_RATE_LIMIT_RETRIES = 4
_MAX_RETRY_SLEEP_SECONDS = 20.0

_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_UUID_PATTERN = re.compile(r"^[0-9a-fA-F-]{32,40}$")
_GROUP_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")


def _similarity(confidence: object) -> Decimal | None:
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        return None
    return Decimal(str(round(min(max(float(confidence), 0.0), 1.0), 4)))


def _error_code(body: object) -> str:
    """Azure's short `error.code` (e.g. `PersonNotFound`); anything else becomes `UNKNOWN`, so
    provider-controlled text never reaches a log line."""
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and _CODE_PATTERN.fullmatch(code) else "UNKNOWN"


class AzureFaceVerificationProvider:
    provider_name = PROVIDER_AZURE

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._base_url = settings.azure_endpoint.strip().rstrip("/")
        self._api_key = settings.azure_face_api_key
        self._group = settings.azure_face_person_group_id
        self._timeout = settings.face_provider_timeout_seconds
        self._connect_timeout = settings.face_provider_connect_timeout_seconds
        self._max_concurrency = settings.face_provider_max_concurrency
        self._min_similarity = Decimal(str(settings.face_match_min_similarity))
        self._transport = transport
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: httpx.AsyncClient | None = None
        self._gate: asyncio.Semaphore | None = None
        self._group_ready = False

    def _pooled(self) -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
        loop = asyncio.get_running_loop()
        if self._client is None or self._gate is None or self._loop is not loop:
            self._loop = loop
            self._gate = asyncio.Semaphore(self._max_concurrency)
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(
                    self._timeout, connect=min(self._connect_timeout, self._timeout)
                ),
                limits=httpx.Limits(
                    max_connections=self._max_concurrency,
                    max_keepalive_connections=self._max_concurrency,
                ),
                transport=self._transport,
            )
        return self._client, self._gate

    async def aclose(self) -> None:
        client, self._client, self._gate, self._loop = self._client, None, None, None
        if client is not None:
            try:
                await client.aclose()
            except RuntimeError:
                pass

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        image: bytes | None = None,
    ) -> tuple[int, Any]:
        """Returns `(status, parsed body)`. 4xx/5xx statuses are returned, not raised, so each
        caller can treat the codes it expects (409 exists, 404 gone) as normal."""
        headers = {"Ocp-Apim-Subscription-Key": self._api_key}
        content: bytes | None = None
        if image is not None:
            headers["Content-Type"] = "application/octet-stream"
            content = image
        client, gate = self._pooled()
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            started = time.perf_counter()
            try:
                async with gate:
                    response = await client.request(
                        method,
                        f"{_API}{path}",
                        params=params,
                        json=json if image is None else None,
                        content=content,
                        headers=headers,
                    )
                body: Any = response.json() if response.content else {}
            except (httpx.HTTPError, ValueError) as exc:
                safe_count(DEPENDENCY_CALLS, "face_provider", "failure")
                safe_observe(DEPENDENCY_DURATION, time.perf_counter() - started, "face_provider")
                safe_count(
                    DEPENDENCY_ERRORS,
                    "face_provider",
                    "timeout" if isinstance(exc, httpx.TimeoutException) else "transport",
                )
                get_logger(__name__).error(
                    "face_provider_request_failed",
                    provider=PROVIDER_AZURE,
                    operation=operation,
                    error_type=type(exc).__name__,
                )
                raise FaceProviderError(f"Face provider {operation} request failed.") from exc
            safe_observe(DEPENDENCY_DURATION, time.perf_counter() - started, "face_provider")
            safe_count(DEPENDENCY_CALLS, "face_provider", "success")
            if response.status_code == 429 and attempt < _MAX_RATE_LIMIT_RETRIES:
                try:
                    wait = float(response.headers.get("Retry-After", ""))
                except ValueError:
                    wait = 2.0 * (attempt + 1)
                await asyncio.sleep(min(max(wait, 1.0), _MAX_RETRY_SLEEP_SECONDS))
                continue
            return response.status_code, body
        raise AssertionError("unreachable")  # pragma: no cover

    def _rejected(self, operation: str, status: int, body: object) -> FaceProviderError:
        safe_count(DEPENDENCY_ERRORS, "face_provider", "provider_rejected")
        get_logger(__name__).error(
            "face_provider_request_rejected",
            provider=PROVIDER_AZURE,
            operation=operation,
            status_code=status,
            error_code=_error_code(body),
        )
        return FaceProviderError(f"Face provider {operation} request failed.")

    def _unrecognised(self, operation: str) -> FaceProviderError:
        safe_count(DEPENDENCY_ERRORS, "face_provider", "unrecognised_response")
        get_logger(__name__).error(
            "face_provider_unrecognised_response", provider=PROVIDER_AZURE, operation=operation
        )
        return FaceProviderError(f"Face provider {operation} returned an unrecognised response.")

    async def _detect(self, image: bytes, *, operation: str, want_face_id: bool) -> str | None:
        """The single face's `faceId` (or "" when `want_face_id` is false), None when there is no
        face. More than one face is ambiguity and raises."""
        status, body = await self._request(
            "POST",
            "/detect",
            operation=operation,
            params={
                "returnFaceId": "true" if want_face_id else "false",
                "detectionModel": _DETECTION_MODEL,
                "recognitionModel": _RECOGNITION_MODEL,
            },
            image=image,
        )
        if status == 400 and _error_code(body) in {"InvalidImage", "InvalidImageSize"}:
            # Azure reports an undecodable/unusable image as 400; for the caller that is "no
            # usable face", the user-correctable case.
            return None
        if status != 200:
            raise self._rejected(operation, status, body)
        if not isinstance(body, list):
            raise self._unrecognised(operation)
        if not body:
            return None
        if len(body) > 1:
            raise FaceProviderMultipleFacesError("More than one face was detected in the photo.")
        if not want_face_id:
            return ""
        face_id = body[0].get("faceId") if isinstance(body[0], dict) else None
        if not isinstance(face_id, str) or not _UUID_PATTERN.fullmatch(face_id):
            raise self._unrecognised(operation)
        return face_id

    async def _ensure_group(self, operation: str) -> None:
        if self._group_ready:
            return
        if not _GROUP_PATTERN.fullmatch(self._group):
            raise FaceProviderError("Azure person group id is invalid.")
        status, body = await self._request(
            "PUT",
            f"/largepersongroups/{self._group}",
            operation=operation,
            json={"name": self._group, "recognitionModel": _RECOGNITION_MODEL},
        )
        if status not in (200, 409):
            raise self._rejected(operation, status, body)
        self._group_ready = True

    async def _add_face(self, person_id: str, image: bytes, operation: str) -> None:
        status, body = await self._request(
            "POST",
            f"/largepersongroups/{self._group}/persons/{person_id}/persistedfaces",
            operation=operation,
            params={"detectionModel": _DETECTION_MODEL},
            image=image,
        )
        if status == 400 and _error_code(body) in {"InvalidImage", "InvalidImageSize"}:
            raise FaceProviderNoFaceError("No face detected in the photo.")
        if status != 200:
            raise self._rejected(operation, status, body)

    async def enroll(self, *, label: str, image: bytes, content_type: str) -> str:
        if await self._detect(image, operation="enroll", want_face_id=False) is None:
            raise FaceProviderNoFaceError("No face detected in the enrollment photo.")
        await self._ensure_group("enroll")
        status, body = await self._request(
            "POST",
            f"/largepersongroups/{self._group}/persons",
            operation="enroll",
            # The label is an internal id; nothing identifying is sent to Azure.
            json={"name": label[:60] or "employee"},
        )
        person_id = body.get("personId") if isinstance(body, dict) else None
        if status != 200:
            raise self._rejected("enroll", status, body)
        if not isinstance(person_id, str) or not _UUID_PATTERN.fullmatch(person_id):
            raise self._unrecognised("enroll")
        try:
            await self._add_face(person_id, image, "enroll")
        except FaceProviderError:
            await self.delete_person(person_id=person_id)  # no half-created person left behind
            raise
        return person_id

    async def add_reference_photo(self, *, person_id: str, image: bytes, content_type: str) -> None:
        if await self._detect(image, operation="add_reference_photo", want_face_id=False) is None:
            raise FaceProviderNoFaceError("No face detected in the reference photo.")
        await self._add_face(person_id, image, "add_reference_photo")

    async def verify(self, *, person_id: str, image: bytes, content_type: str) -> FaceMatchResult:
        try:
            face_id = await self._detect(image, operation="verify", want_face_id=True)
        except FaceProviderMultipleFacesError:
            return FaceMatchResult("MULTIPLE_FACES", None)
        if face_id is None:
            return FaceMatchResult("NO_FACE", None)
        status, body = await self._request(
            "POST",
            "/verify",
            operation="verify",
            json={
                "faceId": face_id,
                "personId": person_id,
                "largePersonGroupId": self._group,
            },
        )
        if status != 200:
            raise self._rejected("verify", status, body)
        similarity = _similarity(body.get("confidence") if isinstance(body, dict) else None)
        if similarity is None:
            raise self._unrecognised("verify")
        decision: MatchDecision = "MATCHED" if similarity >= self._min_similarity else "NO_MATCH"
        return FaceMatchResult(decision, similarity)

    async def delete_person(self, *, person_id: str) -> None:
        if not _UUID_PATTERN.fullmatch(person_id):
            return
        status, body = await self._request(
            "DELETE",
            f"/largepersongroups/{self._group}/persons/{person_id}",
            operation="delete_person",
        )
        if status == 200 or (
            status == 404
            and _error_code(body)
            in {
                "PersonNotFound",
                "PersonGroupNotFound",
                "LargePersonGroupNotFound",
            }
        ):
            return
        raise self._rejected("delete_person", status, body)
