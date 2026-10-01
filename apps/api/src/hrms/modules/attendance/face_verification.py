"""Face-verification provider port for face attendance, mirroring `onboarding/email_sender.py`:
a `Protocol`, one real implementation over `httpx` (no vendor SDK, stays async), and a factory
keyed off `Settings.face_verification_provider`.

Luxand.cloud behaviour this adapter relies on (verified against the live API, 2026-10-01):
- Enrollment always sends `store=0`. With `store=1` Luxand hosts every enrolled face image at an
  unauthenticated public URL; `store=0` keeps verification working with no hosted image.
- Errors arrive as HTTP 200 with `{"status": "failure", "message": ...}`, so outcomes are read
  from the message, not the status code.
- An unknown person id is reported as "No face detected", indistinguishable from a bad photo —
  callers must decide "not enrolled" from their own `employee_face_profile`, never from this.
- Delete only works on the legacy `DELETE /person/{id}` route (`/v2/person/{id}` returns 500).
- The person `name` sent to Luxand is the employee UUID, never a human name.
- Liveness `score` behaves like P(real): Luxand applies its own cutoff (observed ~0.95) to pick
  `result`, so "fake" can carry a score as high as 0.946. It is deterministic per image bytes
  but sensitive to re-encoding, and single-frame liveness is weak anti-spoofing on its own."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol
from uuid import UUID

import httpx

from hrms.core.config.settings import Settings
from hrms.core.observability.logging import get_logger

PROVIDER_LUXAND = "LUXAND"

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
    message never contains the API token or the provider's response body."""


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


def _score(value: object) -> Decimal | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    return Decimal(str(round(min(max(float(value), 0.0), 1.0), 4)))


def _is_no_face(message: str) -> bool:
    # Luxand words this differently per endpoint: "No face detected..." (verify), "there is no
    # faces..." (liveness), "Can't find faces in attached images" (enroll).
    lowered = message.lower()
    return "no face" in lowered or "find face" in lowered


class LuxandFaceVerificationProvider:
    provider_name = PROVIDER_LUXAND

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._base_url = settings.luxand_api_base_url.rstrip("/")
        self._token = settings.luxand_api_token
        self._timeout = settings.face_provider_timeout_seconds
        self._min_similarity = Decimal(str(settings.face_match_min_similarity))
        self._min_liveness = Decimal(str(settings.face_liveness_min_score))
        self._transport = transport

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.request(
                    method, path, headers={"token": self._token}, data=data, files=files
                )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            status_code = (
                exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            )
            get_logger(__name__).error(
                "face_provider_request_failed",
                provider=PROVIDER_LUXAND,
                operation=operation,
                error_type=type(exc).__name__,
                status_code=status_code,
            )
            raise FaceProviderError(f"Face provider {operation} request failed.") from exc
        if not isinstance(body, dict):
            raise FaceProviderError(f"Face provider {operation} returned an unexpected payload.")
        return body

    def _unrecognised(self, operation: str, body: dict[str, Any]) -> FaceProviderError:
        get_logger(__name__).error(
            "face_provider_unrecognised_response",
            provider=PROVIDER_LUXAND,
            operation=operation,
            status=body.get("status"),
        )
        return FaceProviderError(f"Face provider {operation} returned an unrecognised response.")

    @staticmethod
    def _person_path(prefix: str, person_id: str) -> str:
        try:
            return f"{prefix}/{UUID(person_id)}"
        except ValueError as exc:
            raise FaceProviderError("Face provider person id is malformed.") from exc

    async def enroll(self, *, label: str, image: bytes, content_type: str) -> str:
        body = await self._request(
            "POST",
            "/v2/person",
            operation="enroll",
            data={"name": label, "store": "0"},
            files={"photos": ("face", image, content_type)},
        )
        person_id = body.get("uuid")
        if body.get("status") == "success" and isinstance(person_id, str) and person_id:
            return person_id
        if _is_no_face(str(body.get("message", ""))):
            raise FaceProviderNoFaceError("No face detected in the enrollment photo.")
        raise self._unrecognised("enroll", body)

    async def add_reference_photo(self, *, person_id: str, image: bytes, content_type: str) -> None:
        body = await self._request(
            "POST",
            self._person_path("/v2/person", person_id),
            operation="add_reference_photo",
            data={"store": "0"},
            files={"photos": ("face", image, content_type)},
        )
        if body.get("status") == "success":
            return
        if _is_no_face(str(body.get("message", ""))):
            raise FaceProviderNoFaceError("No face detected in the reference photo.")
        raise self._unrecognised("add_reference_photo", body)

    async def verify(self, *, person_id: str, image: bytes, content_type: str) -> FaceMatchResult:
        body = await self._request(
            "POST",
            self._person_path("/photo/verify", person_id),
            operation="verify",
            files={"photo": ("face", image, content_type)},
        )
        message = str(body.get("message", ""))
        if body.get("status") == "success" and message.lower() == "verified":
            similarity = _score(body.get("probability"))
            if similarity is None:
                raise self._unrecognised("verify", body)
            decision: MatchDecision = (
                "MATCHED" if similarity >= self._min_similarity else "NO_MATCH"
            )
            return FaceMatchResult(decision, similarity, body)
        if body.get("status") == "failure":
            if message.lower() == "not verified":
                return FaceMatchResult("NO_MATCH", None, body)
            if _is_no_face(message):
                return FaceMatchResult("NO_FACE", None, body)
        raise self._unrecognised("verify", body)

    async def check_liveness(self, *, image: bytes, content_type: str) -> LivenessResult:
        body = await self._request(
            "POST",
            "/photo/liveness",
            operation="check_liveness",
            files={"photo": ("face", image, content_type)},
        )
        if body.get("status") == "success":
            score = _score(body.get("score"))
            if score is None or body.get("result") not in ("real", "fake"):
                raise self._unrecognised("check_liveness", body)
            live = body["result"] == "real" and score >= self._min_liveness
            return LivenessResult("LIVE" if live else "SPOOF", score, body)
        if body.get("status") == "failure" and _is_no_face(str(body.get("message", ""))):
            return LivenessResult("NO_FACE", None, body)
        raise self._unrecognised("check_liveness", body)

    async def delete_person(self, *, person_id: str) -> None:
        body = await self._request(
            "DELETE", self._person_path("/person", person_id), operation="delete_person"
        )
        message = str(body.get("message", "")).lower()
        # Already gone counts as deleted — revocation must be safely retryable.
        if body.get("status") == "success" or "no person" in message:
            return
        raise self._unrecognised("delete_person", body)


def get_face_verification_provider(settings: Settings) -> FaceVerificationProvider | None:
    if settings.face_verification_provider == "luxand":
        return LuxandFaceVerificationProvider(settings)
    return None
