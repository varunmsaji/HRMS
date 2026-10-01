"""`FaceppFaceVerificationProvider` against canned Face++ (faceplusplus.com) response shapes.
Uses `httpx.MockTransport`; nothing here contacts Face++."""

import json
from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

from hrms.core.config.settings import Settings
from hrms.modules.attendance.face_verification import (
    FaceppFaceVerificationProvider,
    FaceProviderError,
    FaceProviderNoFaceError,
    get_face_verification_provider,
)

_API_KEY = "s3cr3t-facepp-key-marker-zzz"
_API_SECRET = "s3cr3t-facepp-secret-marker-zzz"
_PERSON = "fs_37aab195bd3a11f186d30242ac120002"
_FACE_TOKEN = "ft_e1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6"
_IMG = b"\xff\xd8fake-jpeg"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "development",
        "face_verification_provider": "facepp",
        "facepp_api_key": _API_KEY,
        "facepp_api_secret": _API_SECRET,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _provider(
    handler: Callable[[httpx.Request], httpx.Response], **overrides: object
) -> FaceppFaceVerificationProvider:
    return FaceppFaceVerificationProvider(
        _settings(**overrides), transport=httpx.MockTransport(handler)
    )


def _respond(body: object, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(status, json=body)


def _detect(faces: list[dict[str, object]]) -> dict[str, object]:
    return {"faces": faces, "image_id": "img-1", "request_id": "req-1", "time_used": 100}


def _face(token: str = _FACE_TOKEN) -> dict[str, object]:
    return {"face_token": token, "face_rectangle": {"top": 1, "left": 1, "width": 1, "height": 1}}


# --- settings / factory --------------------------------------------------------------------------


def test_disabled_by_default() -> None:
    settings = Settings(environment="development", face_verification_provider="disabled")
    assert get_face_verification_provider(settings) is None


def test_facepp_selected_when_configured() -> None:
    assert isinstance(
        get_face_verification_provider(_settings()), FaceppFaceVerificationProvider
    )


def test_facepp_without_credentials_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(facepp_api_key="")
    with pytest.raises(ValidationError):
        _settings(facepp_api_secret="")


def test_threshold_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(face_match_min_similarity=1.5)


# --- enroll -----------------------------------------------------------------------------------


async def test_enroll_detects_then_creates_faceset() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/facepp/v3/detect":
            return httpx.Response(200, json=_detect([_face()]))
        return httpx.Response(
            200,
            json={
                "faceset_token": _PERSON,
                "face_count": 1,
                "face_tokens": [_FACE_TOKEN],
                "request_id": "req-2",
                "time_used": 50,
            },
        )

    person_id = await _provider(handler).enroll(
        label="emp-1", image=_IMG, content_type="image/jpeg"
    )

    assert person_id == _PERSON
    assert [r.url.path for r in seen] == ["/facepp/v3/detect", "/facepp/v3/faceset/create"]
    create_body = seen[1].content
    assert _API_KEY.encode() in create_body
    assert _API_SECRET.encode() in create_body
    assert _FACE_TOKEN.encode() in create_body


async def test_enroll_no_face_is_user_correctable() -> None:
    provider = _provider(_respond(_detect([])))
    with pytest.raises(FaceProviderNoFaceError):
        await provider.enroll(label="emp-1", image=_IMG, content_type="image/jpeg")


# --- add_reference_photo ------------------------------------------------------------------------


async def test_add_reference_photo_adds_face_to_existing_faceset() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/facepp/v3/detect":
            return httpx.Response(200, json=_detect([_face()]))
        return httpx.Response(
            200,
            json={"faceset_token": _PERSON, "face_added": 1, "face_count": 2, "failure_detail": []},
        )

    await _provider(handler).add_reference_photo(
        person_id=_PERSON, image=_IMG, content_type="image/jpeg"
    )
    assert seen[1].url.path == "/facepp/v3/faceset/addface"
    assert _PERSON.encode() in seen[1].content


async def test_add_reference_photo_no_face_is_user_correctable() -> None:
    provider = _provider(_respond(_detect([])))
    with pytest.raises(FaceProviderNoFaceError):
        await provider.add_reference_photo(person_id=_PERSON, image=_IMG, content_type="image/jpeg")


# --- verify -----------------------------------------------------------------------------------


async def test_verify_match_above_threshold() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/facepp/v3/detect":
            return httpx.Response(200, json=_detect([_face()]))
        return httpx.Response(
            200,
            json={
                "results": [{"confidence": 97.123, "face_token": _FACE_TOKEN}],
                "thresholds": {"1e-3": 62.0, "1e-4": 69.9, "1e-5": 73.8},
            },
        )

    result = await _provider(handler).verify(
        person_id=_PERSON, image=_IMG, content_type="image/jpeg"
    )
    assert result.decision == "MATCHED"
    assert result.similarity == Decimal("0.9712")


async def test_verify_provider_match_below_our_threshold_is_no_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/facepp/v3/detect":
            return httpx.Response(200, json=_detect([_face()]))
        return httpx.Response(200, json={"results": [{"confidence": 85.0}]})

    result = await _provider(handler, face_match_min_similarity=0.9).verify(
        person_id=_PERSON, image=_IMG, content_type="image/jpeg"
    )
    assert result.decision == "NO_MATCH"
    assert result.similarity == Decimal("0.85")


async def test_verify_empty_results_is_no_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/facepp/v3/detect":
            return httpx.Response(200, json=_detect([_face()]))
        return httpx.Response(200, json={"results": []})

    result = await _provider(handler).verify(
        person_id=_PERSON, image=_IMG, content_type="image/jpeg"
    )
    assert result.decision == "NO_MATCH"
    assert result.similarity is None


async def test_verify_no_face() -> None:
    provider = _provider(_respond(_detect([])))
    result = await provider.verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")
    assert result.decision == "NO_FACE"


async def test_verify_result_without_confidence_is_unrecognised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/facepp/v3/detect":
            return httpx.Response(200, json=_detect([_face()]))
        return httpx.Response(200, json={"results": [{"face_token": _FACE_TOKEN}]})

    with pytest.raises(FaceProviderError):
        await _provider(handler).verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")


async def test_verify_unknown_error_is_error_not_silent_reject() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/facepp/v3/detect":
            return httpx.Response(200, json=_detect([_face()]))
        return httpx.Response(400, json={"error_message": "CONCURRENCY_LIMIT_EXCEEDED"})

    with pytest.raises(FaceProviderError):
        await _provider(handler).verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")


# --- liveness (presence-only placeholder, not real anti-spoofing) -------------------------------


async def test_liveness_face_present_is_live_with_no_score() -> None:
    provider = _provider(_respond(_detect([_face()])))
    result = await provider.check_liveness(image=_IMG, content_type="image/jpeg")
    assert result.decision == "LIVE"
    assert result.score is None


async def test_liveness_no_face() -> None:
    provider = _provider(_respond(_detect([])))
    result = await provider.check_liveness(image=_IMG, content_type="image/jpeg")
    assert result.decision == "NO_FACE"


# --- delete -----------------------------------------------------------------------------------


async def test_delete_sends_faceset_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"faceset_token": _PERSON})

    await _provider(handler).delete_person(person_id=_PERSON)
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/facepp/v3/faceset/delete"
    assert _PERSON.encode() in seen[0].content


async def test_delete_already_gone_is_success() -> None:
    provider = _provider(
        _respond({"error_message": "INVALID_FACESET_TOKEN"}, status=400)
    )
    await provider.delete_person(person_id=_PERSON)


# --- transport failures & log hygiene ----------------------------------------------------------


async def test_error_response_raises_and_never_logs_credentials() -> None:
    provider = _provider(_respond({"error_message": "AUTHENTICATION_ERROR"}, status=403))
    with capture_logs() as logs, pytest.raises(FaceProviderError) as exc_info:
        await provider.delete_person(person_id=_PERSON)

    rendered = json.dumps(logs, default=str) + str(exc_info.value)
    assert _API_KEY not in rendered
    assert _API_SECRET not in rendered


async def test_timeout_raises_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(FaceProviderError):
        await _provider(handler).check_liveness(image=_IMG, content_type="image/jpeg")


async def test_non_json_response_raises_provider_error() -> None:
    provider = _provider(lambda _r: httpx.Response(200, text="<html>bad gateway</html>"))
    with pytest.raises(FaceProviderError):
        await provider.verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")
