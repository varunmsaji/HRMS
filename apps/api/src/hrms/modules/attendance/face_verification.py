"""Face-verification provider port for face attendance, mirroring `onboarding/email_sender.py`:
a `Protocol`, one real implementation over `httpx` (no vendor SDK, stays async), and a factory
keyed off `Settings.face_verification_provider`.

Face++ (faceplusplus.com) behaviour this adapter relies on:
- Every request authenticates with `api_key` AND `api_secret` as plain form fields — there is no
  header-based token like Luxand's.
- `/facepp/v3/detect` finding no face is a *success* response with `faces: []`, not an error — so
  "no face" is read from an empty list, never from a failure status.
- A face is identified by a `face_token`, valid for 72 hours unless added to a FaceSet, where it
  persists indefinitely. One FaceSet per employee stands in for Luxand's "person": its
  `faceset_token` is what this adapter returns as `person_id` and stores in
  `employee_face_profile.provider_person_id`.
- `/facepp/v3/search` compares a fresh `face_token` against a FaceSet and returns `confidence` on
  a 0..100 scale (not 0..1) — normalised here before comparing against `Settings.
  face_match_min_similarity`.
- Errors come back as a JSON body with an `error_message` field (success bodies never have one),
  regardless of HTTP status — so outcomes are read from that field, not the status code.
- There is no confirmed single-photo liveness/anti-spoofing endpoint: Face++ markets liveness as
  part of a separate "FaceID" product built on active, multi-frame challenges (blink, turn head)
  via a client SDK, not a plain REST call on one still image. This adapter therefore does
  identity only; liveness is decided on our own server by `attendance/liveness.py`. (The former
  `check_liveness` here reported LIVE for any detected face; it was removed so nothing can treat
  face detection as anti-spoofing again.)"""

import asyncio
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

import httpx

from hrms.core.config.settings import Settings
from hrms.core.observability.logging import get_logger

PROVIDER_FACEPP = "FACEPP"

MatchDecision = Literal["MATCHED", "NO_MATCH", "NO_FACE", "MULTIPLE_FACES"]


@dataclass(frozen=True)
class FaceMatchResult:
    """The only part of a Face++ search that leaves this adapter. Deliberately minimal: the raw
    body carries face tokens, rectangles and landmarks that nothing downstream needs, so it is
    neither returned nor stored. `provider_request_id` is Face++'s own correlation id (for a
    support ticket); it identifies a request, not a face."""

    decision: MatchDecision
    similarity: Decimal | None
    provider_request_id: str | None = None


class FaceProviderError(Exception):
    """Transport failure, auth failure, or a response this adapter does not recognise. The
    message never contains the API key/secret or the provider's response body."""


class FaceProviderNoFaceError(FaceProviderError):
    """The enrollment/reference photo has no detectable face — user-correctable, unlike other
    `FaceProviderError`s."""


class FaceProviderMultipleFacesError(FaceProviderError):
    """The photo has more than one detectable face. Which one is the employee is a guess the
    adapter refuses to make (it used to take the first), so this is ambiguity, not a match."""


class FaceVerificationProvider(Protocol):
    provider_name: str

    async def enroll(self, *, label: str, image: bytes, content_type: str) -> str: ...

    async def add_reference_photo(
        self, *, person_id: str, image: bytes, content_type: str
    ) -> None: ...

    async def verify(
        self, *, person_id: str, image: bytes, content_type: str
    ) -> FaceMatchResult: ...

    async def delete_person(self, *, person_id: str) -> None: ...

    async def aclose(self) -> None: ...


def _similarity(confidence: object) -> Decimal | None:
    """Face++ `confidence` is 0..100; everything downstream of this adapter (settings
    thresholds, stored `similarity` column) is 0..1, matching Luxand's original scale."""
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        return None
    return Decimal(str(round(min(max(float(confidence) / 100.0, 0.0), 1.0), 4)))


_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_ERROR_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,64}")


def _request_id(body: dict[str, Any]) -> str | None:
    """Face++'s `request_id`, only when it is a short plain token — it is stored on attempt rows
    and logged, so provider-controlled text must not reach either unvalidated."""
    value = body.get("request_id")
    return value if isinstance(value, str) and _REQUEST_ID_PATTERN.fullmatch(value) else None


def _error_code(error_message: str) -> str:
    """The leading UPPER_SNAKE code of a Face++ `error_message` (e.g. `INVALID_FACESET_TOKEN`
    from `INVALID_FACESET_TOKEN:fs_...`). Everything after the code can echo a token or an
    argument, so it is dropped before logging; anything unrecognisable becomes `UNKNOWN`."""
    match = _ERROR_CODE_PATTERN.match(error_message.strip())
    return match.group(0) if match else "UNKNOWN"


def _is_missing_faceset(error_message: str) -> bool:
    upper = error_message.upper()
    return "FACESET_NOT_FOUND" in upper or "INVALID_FACESET_TOKEN" in upper


class FaceppFaceVerificationProvider:
    provider_name = PROVIDER_FACEPP

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._base_url = settings.facepp_api_base_url.rstrip("/")
        self._api_key = settings.facepp_api_key
        self._api_secret = settings.facepp_api_secret
        self._timeout = settings.face_provider_timeout_seconds
        self._connect_timeout = settings.face_provider_connect_timeout_seconds
        self._max_concurrency = settings.face_provider_max_concurrency
        self._min_similarity = Decimal(str(settings.face_match_min_similarity))
        self._transport = transport
        # One pooled client (keep-alive connections reused across calls) and one concurrency
        # gate per event loop. Both are created lazily on first use, because an `httpx` client
        # and an `asyncio.Semaphore` belong to the loop they first run on; a different running
        # loop (Celery's `asyncio.run`, a test) gets fresh ones instead of sharing state across
        # loops. The client holds only the connection pool: every request builds its own form
        # payload, so no mutable request state is shared between concurrent calls.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: httpx.AsyncClient | None = None
        self._gate: asyncio.Semaphore | None = None

    def _pooled(self) -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
        loop = asyncio.get_running_loop()
        if self._client is None or self._gate is None or self._loop is not loop:
            # A client left over from another (finished) loop cannot be closed from this one;
            # it is dropped and garbage-collected with its loop.
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
        """Closes the pool (application shutdown, or the end of a one-off task). Safe to call
        repeatedly and when no call was ever made."""
        client, self._client, self._gate, self._loop = self._client, None, None, None
        if client is not None:
            try:
                await client.aclose()
            except RuntimeError:
                # The client's loop is already closed; there is nothing left to release.
                pass

    async def _request(
        self,
        path: str,
        *,
        operation: str,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> dict[str, Any]:
        payload = {"api_key": self._api_key, "api_secret": self._api_secret, **(data or {})}
        client, gate = self._pooled()
        try:
            async with gate:
                response = await client.post(path, data=payload, files=files)
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            status_code = (
                exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            )
            get_logger(__name__).error(
                "face_provider_request_failed",
                provider=PROVIDER_FACEPP,
                operation=operation,
                error_type=type(exc).__name__,
                status_code=status_code,
            )
            raise FaceProviderError(f"Face provider {operation} request failed.") from exc
        if not isinstance(body, dict):
            raise FaceProviderError(f"Face provider {operation} returned an unexpected payload.")
        error_message = body.get("error_message")
        if error_message:
            return {**body, "_error_message": str(error_message)}
        return body

    def _unrecognised(self, operation: str, body: dict[str, Any]) -> FaceProviderError:
        get_logger(__name__).error(
            "face_provider_unrecognised_response",
            provider=PROVIDER_FACEPP,
            operation=operation,
        )
        return FaceProviderError(f"Face provider {operation} returned an unrecognised response.")

    def _error(self, operation: str, body: dict[str, Any]) -> FaceProviderError:
        get_logger(__name__).error(
            "face_provider_request_rejected",
            provider=PROVIDER_FACEPP,
            operation=operation,
            error_code=_error_code(body["_error_message"]),
        )
        return FaceProviderError(f"Face provider {operation} request failed.")

    async def _detect_face_token(
        self, image: bytes, content_type: str, *, operation: str
    ) -> str | None:
        body = await self._request(
            "/facepp/v3/detect",
            operation=operation,
            files={"image_file": ("face", image, content_type)},
        )
        if "_error_message" in body:
            raise self._error(operation, body)
        faces = body.get("faces")
        if not isinstance(faces, list):
            raise self._unrecognised(operation, body)
        if not faces:
            return None
        if len(faces) > 1:
            raise FaceProviderMultipleFacesError("More than one face was detected in the photo.")
        token = faces[0].get("face_token") if isinstance(faces[0], dict) else None
        if not isinstance(token, str) or not token:
            raise self._unrecognised(operation, body)
        return token

    async def enroll(self, *, label: str, image: bytes, content_type: str) -> str:
        token = await self._detect_face_token(image, content_type, operation="enroll")
        if token is None:
            raise FaceProviderNoFaceError("No face detected in the enrollment photo.")
        body = await self._request(
            "/facepp/v3/faceset/create",
            operation="enroll",
            data={"face_tokens": token},
        )
        if "_error_message" in body:
            raise self._error("enroll", body)
        faceset_token = body.get("faceset_token")
        if not isinstance(faceset_token, str) or not faceset_token:
            raise self._unrecognised("enroll", body)
        return faceset_token

    async def add_reference_photo(self, *, person_id: str, image: bytes, content_type: str) -> None:
        token = await self._detect_face_token(image, content_type, operation="add_reference_photo")
        if token is None:
            raise FaceProviderNoFaceError("No face detected in the reference photo.")
        body = await self._request(
            "/facepp/v3/faceset/addface",
            operation="add_reference_photo",
            data={"faceset_token": person_id, "face_tokens": token},
        )
        if "_error_message" in body:
            raise self._error("add_reference_photo", body)

    async def verify(self, *, person_id: str, image: bytes, content_type: str) -> FaceMatchResult:
        """Searches this one employee's FaceSet (`person_id`) for the face in `image`. Because the
        FaceSet belongs to a single employee, a result at or above the threshold means "this
        employee"; it is never a match against some other face in the tenant."""
        try:
            token = await self._detect_face_token(image, content_type, operation="verify")
        except FaceProviderMultipleFacesError:
            return FaceMatchResult("MULTIPLE_FACES", None)
        if token is None:
            return FaceMatchResult("NO_FACE", None)
        body = await self._request(
            "/facepp/v3/search",
            operation="verify",
            data={"faceset_token": person_id, "face_token": token},
        )
        if "_error_message" in body:
            raise self._error("verify", body)
        results = body.get("results")
        if not isinstance(results, list):
            raise self._unrecognised("verify", body)
        request_id = _request_id(body)
        if not results:
            return FaceMatchResult("NO_MATCH", None, request_id)
        # Every entry must be well formed; one malformed entry makes the whole response
        # untrustworthy rather than silently skipped. The best confidence decides.
        similarities: list[Decimal] = []
        for entry in results:
            similarity = _similarity(entry.get("confidence")) if isinstance(entry, dict) else None
            if similarity is None:
                raise self._unrecognised("verify", body)
            similarities.append(similarity)
        best = max(similarities)
        decision: MatchDecision = "MATCHED" if best >= self._min_similarity else "NO_MATCH"
        return FaceMatchResult(decision, best, request_id)

    async def delete_person(self, *, person_id: str) -> None:
        body = await self._request(
            "/facepp/v3/faceset/delete",
            operation="delete_person",
            data={"faceset_token": person_id, "check_empty": "0"},
        )
        if "_error_message" not in body or _is_missing_faceset(body["_error_message"]):
            return
        raise self._error("delete_person", body)


_shared_providers: dict[tuple[object, ...], FaceVerificationProvider] = {}


def get_face_verification_provider(settings: Settings) -> FaceVerificationProvider | None:
    """The process-wide provider for the API: one instance (so one connection pool) per
    configuration, closed by `close_face_verification_providers` at shutdown. One-off callers
    (Celery tasks, each on its own event loop) build `FaceppFaceVerificationProvider` directly
    and `aclose()` it themselves."""
    if settings.face_verification_provider != "facepp":
        return None
    key = (
        settings.facepp_api_base_url,
        settings.facepp_api_key,
        settings.facepp_api_secret,
        settings.face_provider_timeout_seconds,
        settings.face_provider_connect_timeout_seconds,
        settings.face_provider_max_concurrency,
        settings.face_match_min_similarity,
    )
    provider = _shared_providers.get(key)
    if provider is None:
        provider = _shared_providers[key] = FaceppFaceVerificationProvider(settings)
    return provider


async def close_face_verification_providers() -> None:
    providers = list(_shared_providers.values())
    _shared_providers.clear()
    for provider in providers:
        await provider.aclose()
