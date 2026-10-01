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
  via a client SDK, not a plain REST call on one still image. Until that is wired in,
  `check_liveness` only confirms a face is present (via `/detect`) and always reports `LIVE` when
  one is found — this is NOT real anti-spoofing, deliberately, rather than faking a score."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol

import httpx

from hrms.core.config.settings import Settings
from hrms.core.observability.logging import get_logger

PROVIDER_FACEPP = "FACEPP"

MatchDecision = Literal["MATCHED", "NO_MATCH", "NO_FACE"]
LivenessDecision = Literal["LIVE", "SPOOF", "NO_FACE"]


@dataclass(frozen=True)
class FaceMatchResult:
    decision: MatchDecision
    similarity: Decimal | None
    provider_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LivenessResult:
    decision: LivenessDecision
    score: Decimal | None
    provider_response: dict[str, Any] = field(default_factory=dict)


class FaceProviderError(Exception):
    """Transport failure, auth failure, or a response this adapter does not recognise. The
    message never contains the API key/secret or the provider's response body."""


class FaceProviderNoFaceError(FaceProviderError):
    """The enrollment/reference photo has no detectable face — user-correctable, unlike other
    `FaceProviderError`s."""


class FaceVerificationProvider(Protocol):
    provider_name: str

    async def enroll(self, *, label: str, image: bytes, content_type: str) -> str: ...

    async def add_reference_photo(
        self, *, person_id: str, image: bytes, content_type: str
    ) -> None: ...

    async def verify(
        self, *, person_id: str, image: bytes, content_type: str
    ) -> FaceMatchResult: ...

    async def check_liveness(self, *, image: bytes, content_type: str) -> LivenessResult: ...

    async def delete_person(self, *, person_id: str) -> None: ...


def _similarity(confidence: object) -> Decimal | None:
    """Face++ `confidence` is 0..100; everything downstream of this adapter (settings
    thresholds, stored `similarity` column) is 0..1, matching Luxand's original scale."""
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        return None
    return Decimal(str(round(min(max(float(confidence) / 100.0, 0.0), 1.0), 4)))


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
        self._min_similarity = Decimal(str(settings.face_match_min_similarity))
        self._transport = transport

    async def _request(
        self,
        path: str,
        *,
        operation: str,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> dict[str, Any]:
        payload = {"api_key": self._api_key, "api_secret": self._api_secret, **(data or {})}
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
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
            error_message=body["_error_message"],
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
        token = await self._detect_face_token(image, content_type, operation="verify")
        if token is None:
            return FaceMatchResult("NO_FACE", None, {})
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
        if not results:
            return FaceMatchResult("NO_MATCH", None, body)
        top = results[0]
        similarity = _similarity(top.get("confidence")) if isinstance(top, dict) else None
        if similarity is None:
            raise self._unrecognised("verify", body)
        decision: MatchDecision = "MATCHED" if similarity >= self._min_similarity else "NO_MATCH"
        return FaceMatchResult(decision, similarity, body)

    async def check_liveness(self, *, image: bytes, content_type: str) -> LivenessResult:
        token = await self._detect_face_token(image, content_type, operation="check_liveness")
        if token is None:
            return LivenessResult("NO_FACE", None, {})
        return LivenessResult("LIVE", None, {})

    async def delete_person(self, *, person_id: str) -> None:
        body = await self._request(
            "/facepp/v3/faceset/delete",
            operation="delete_person",
            data={"faceset_token": person_id, "check_empty": "0"},
        )
        if "_error_message" not in body or _is_missing_faceset(body["_error_message"]):
            return
        raise self._error("delete_person", body)


def get_face_verification_provider(settings: Settings) -> FaceVerificationProvider | None:
    if settings.face_verification_provider == "facepp":
        return FaceppFaceVerificationProvider(settings)
    return None
