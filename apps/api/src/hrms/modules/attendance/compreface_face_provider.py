"""CompreFace adapter for face attendance (`face_verification_provider="compreface"`), behind the
same `FaceVerificationProvider` port as the Face++, Azure and open-source engines. Plain `httpx`,
no SDK.

CompreFace (github.com/exadel-inc/CompreFace, pinned 1.2.0) is self-hosted: it runs as its own
containers on our internal Docker network, so no photo leaves the host. Behaviour relied on:
- Auth is the `x-api-key` header carrying a *Recognition service* key created in the CompreFace
  admin UI. The API is served by `compreface-api` under `/api/v1/recognition`.
- A *subject* stands in for a person. This adapter names it with a fresh UUID (never the employee's
  name or id) and returns it as `person_id`, stored in `employee_face_profile.provider_person_id`.
  Each reference photo is an *example* of that subject (`image_id`). Uploading the first example
  creates the subject, and deleting the subject deletes all its examples.
- `POST /faces/{image_id}/verify` compares an uploaded image with one saved example and answers one
  `result` entry per face found in the upload, each with `similarity` on 0..1 (the stored
  `similarity` scale, no rescaling). The best of the subject's examples decides.
- Adding an example does not reject a photo with several faces (it keeps one), so after each
  upload the photo is verified against its own new example: more than one face in the answer
  means ambiguity, and the example is removed again.
- The error body (`{"message", "code"}`, HTTP 400 for "No face is found in the given image") is
  not in CompreFace's published docs; it is matched on the numeric code or that message, and
  neither the message nor the body is ever logged.
- CompreFace has no anti-spoofing; liveness stays with `attendance/liveness.py`. Run it with
  `save_images_to_db=false` so it keeps embeddings only, matching "no image is kept"."""

import asyncio
import re
import time
import uuid
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

PROVIDER_COMPREFACE = "COMPREFACE"

_API = "/api/v1/recognition"
#: Examples compared per verification (an enrollment holds the front photo plus four angles).
_MAX_COMPARE_REFERENCES = 8
_NO_FACE_CODE = 28
_NO_FACE_MESSAGE = "no face is found"

_ID_PATTERN = re.compile(r"^[0-9a-fA-F-]{32,40}$")
_NOT_FOUND_PATTERN = re.compile(r"\bnot found\b", re.IGNORECASE)


def _similarity(value: object) -> Decimal | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    return Decimal(str(round(min(max(float(value), 0.0), 1.0), 4)))


def _error_code(body: object) -> int | None:
    """CompreFace's numeric `code`, the only part of an error body that is safe to log."""
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def _message(body: object) -> str:
    message = body.get("message") if isinstance(body, dict) else None
    return message if isinstance(message, str) else ""


def _is_no_face(status: int, body: object) -> bool:
    return status == 400 and (
        _error_code(body) == _NO_FACE_CODE or _NO_FACE_MESSAGE in _message(body).lower()
    )


def _is_gone(status: int, body: object) -> bool:
    return status == 404 or (
        400 <= status < 500 and bool(_NOT_FOUND_PATTERN.search(_message(body)))
    )


class CompreFaceVerificationProvider:
    provider_name = PROVIDER_COMPREFACE

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._base_url = settings.compreface_base_url.strip().rstrip("/")
        self._api_key = settings.compreface_api_key
        self._det_prob_threshold = str(settings.compreface_det_prob_threshold)
        # Read by the service and the shadow comparison instead of `face_match_min_similarity`,
        # which is tuned for Face++/Azure scores.
        self.match_threshold = Decimal(str(settings.compreface_match_min_similarity))
        self.angle_threshold = Decimal(str(settings.compreface_enrollment_angle_min_similarity))
        self._timeout = settings.face_provider_timeout_seconds
        self._connect_timeout = settings.face_provider_connect_timeout_seconds
        self._max_concurrency = settings.face_provider_max_concurrency
        self._transport = transport
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: httpx.AsyncClient | None = None
        self._gate: asyncio.Semaphore | None = None

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
        image: tuple[bytes, str] | None = None,
    ) -> tuple[int, Any]:
        """Returns `(status, parsed body)`. 4xx/5xx statuses are returned, not raised, so each
        caller can treat the ones it expects (no face, already gone) as normal."""
        files = None
        if image is not None:
            files = {"file": ("face", image[0], image[1] or "application/octet-stream")}
        client, gate = self._pooled()
        started = time.perf_counter()
        try:
            async with gate:
                response = await client.request(
                    method,
                    f"{_API}{path}",
                    params=params,
                    files=files,
                    headers={"x-api-key": self._api_key},
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
                provider=PROVIDER_COMPREFACE,
                operation=operation,
                error_type=type(exc).__name__,
            )
            raise FaceProviderError(f"Face provider {operation} request failed.") from exc
        safe_observe(DEPENDENCY_DURATION, time.perf_counter() - started, "face_provider")
        safe_count(DEPENDENCY_CALLS, "face_provider", "success")
        return response.status_code, body

    def _rejected(self, operation: str, status: int, body: object) -> FaceProviderError:
        safe_count(DEPENDENCY_ERRORS, "face_provider", "provider_rejected")
        get_logger(__name__).error(
            "face_provider_request_rejected",
            provider=PROVIDER_COMPREFACE,
            operation=operation,
            status_code=status,
            error_code=_error_code(body),
        )
        return FaceProviderError(f"Face provider {operation} request failed.")

    def _unrecognised(self, operation: str) -> FaceProviderError:
        safe_count(DEPENDENCY_ERRORS, "face_provider", "unrecognised_response")
        get_logger(__name__).error(
            "face_provider_unrecognised_response", provider=PROVIDER_COMPREFACE, operation=operation
        )
        return FaceProviderError(f"Face provider {operation} returned an unrecognised response.")

    async def _faces_against(
        self, image_id: str, image: bytes, content_type: str, operation: str
    ) -> list[Decimal]:
        """The similarity of every face in `image` to the saved example `image_id`. Raises
        `FaceProviderNoFaceError` when the image has no face."""
        status, body = await self._request(
            "POST",
            f"/faces/{image_id}/verify",
            operation=operation,
            params={"det_prob_threshold": self._det_prob_threshold},
            image=(image, content_type),
        )
        if _is_no_face(status, body):
            raise FaceProviderNoFaceError("No face detected in the photo.")
        if status != 200:
            raise self._rejected(operation, status, body)
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, list):
            raise self._unrecognised(operation)
        if not result:
            raise FaceProviderNoFaceError("No face detected in the photo.")
        scores = [_similarity(face.get("similarity")) for face in result if isinstance(face, dict)]
        if len(scores) != len(result) or any(score is None for score in scores):
            raise self._unrecognised(operation)
        return [score for score in scores if score is not None]

    async def _add_example(
        self, subject: str, image: bytes, content_type: str, operation: str
    ) -> str:
        """Saves `image` as an example of `subject` and checks it held exactly one face. Returns
        the new `image_id`; on any failure nothing new is left saved."""
        status, body = await self._request(
            "POST",
            "/faces",
            operation=operation,
            params={"subject": subject, "det_prob_threshold": self._det_prob_threshold},
            image=(image, content_type),
        )
        if _is_no_face(status, body):
            raise FaceProviderNoFaceError("No face detected in the photo.")
        if status not in (200, 201):
            raise self._rejected(operation, status, body)
        image_id = body.get("image_id") if isinstance(body, dict) else None
        if not isinstance(image_id, str) or not _ID_PATTERN.fullmatch(image_id):
            raise self._unrecognised(operation)
        try:
            faces = await self._faces_against(image_id, image, content_type, operation)
            if len(faces) > 1:
                raise FaceProviderMultipleFacesError(
                    "More than one face was detected in the photo."
                )
        except FaceProviderError:
            await self._delete_example(image_id, operation)
            raise
        return image_id

    async def _delete_example(self, image_id: str, operation: str) -> None:
        status, body = await self._request("DELETE", f"/faces/{image_id}", operation=operation)
        if status != 200 and not _is_gone(status, body):
            raise self._rejected(operation, status, body)

    async def _examples(self, subject: str) -> list[str]:
        status, body = await self._request(
            "GET",
            "/faces",
            operation="verify",
            params={"subject": subject, "page": "0", "size": str(_MAX_COMPARE_REFERENCES)},
        )
        if status != 200:
            raise self._rejected("verify", status, body)
        faces = body.get("faces") if isinstance(body, dict) else None
        if not isinstance(faces, list):
            raise self._unrecognised("verify")
        ids = [face.get("image_id") for face in faces if isinstance(face, dict)]
        if any(not isinstance(i, str) or not _ID_PATTERN.fullmatch(i) for i in ids):
            raise self._unrecognised("verify")
        return [i for i in ids if isinstance(i, str)]

    async def enroll(self, *, label: str, image: bytes, content_type: str) -> str:
        # `label` is deliberately not sent: the subject name is a fresh opaque id.
        subject = str(uuid.uuid4())
        try:
            await self._add_example(subject, image, content_type, "enroll")
        except FaceProviderError:
            await self.delete_person(person_id=subject)  # no half-created subject left behind
            raise
        return subject

    async def add_reference_photo(self, *, person_id: str, image: bytes, content_type: str) -> None:
        if not _ID_PATTERN.fullmatch(person_id):
            raise FaceProviderError("CompreFace subject id is invalid.")
        await self._add_example(person_id, image, content_type, "add_reference_photo")

    async def verify(self, *, person_id: str, image: bytes, content_type: str) -> FaceMatchResult:
        if not _ID_PATTERN.fullmatch(person_id):
            raise FaceProviderError("CompreFace subject id is invalid.")
        examples = await self._examples(person_id)
        if not examples:
            raise FaceProviderError("Face provider verify found no enrolled photos.")
        # The first comparison also counts the faces, so a no-face or crowded frame costs one call.
        try:
            first = await self._faces_against(examples[0], image, content_type, "verify")
        except FaceProviderNoFaceError:
            return FaceMatchResult("NO_FACE", None)
        if len(first) > 1:
            return FaceMatchResult("MULTIPLE_FACES", None)
        rest = await asyncio.gather(
            *(self._faces_against(e, image, content_type, "verify") for e in examples[1:])
        )
        best = max([first[0], *(faces[0] for faces in rest if len(faces) == 1)])
        decision: MatchDecision = "MATCHED" if best >= self.match_threshold else "NO_MATCH"
        return FaceMatchResult(decision, best)

    async def delete_person(self, *, person_id: str) -> None:
        if not _ID_PATTERN.fullmatch(person_id):
            return
        status, body = await self._request(
            "DELETE", f"/subjects/{person_id}", operation="delete_person"
        )
        if status == 200 or _is_gone(status, body):
            return
        raise self._rejected("delete_person", status, body)
