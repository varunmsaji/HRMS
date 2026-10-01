"""`LuxandFaceVerificationProvider` against canned responses captured from the live Luxand API
(2026-10-01). Uses `httpx.MockTransport`; nothing here contacts Luxand."""

import json
from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

from hrms.core.config.settings import Settings
from hrms.modules.attendance.face_verification import (
    FaceProviderError,
    FaceProviderNoFaceError,
    LuxandFaceVerificationProvider,
    get_face_verification_provider,
)

_TOKEN = "s3cr3t-luxand-token-marker-zzz"
_PERSON = "37aab195-bd3a-11f1-86d3-0242ac120002"
_IMG = b"\xff\xd8fake-jpeg"
_NO_FACE = "No face detected in the photo. Check lighting, avoid backlight and strong shadows."


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "development",
        "face_verification_provider": "luxand",
        "luxand_api_token": _TOKEN,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _provider(
    handler: Callable[[httpx.Request], httpx.Response], **overrides: object
) -> LuxandFaceVerificationProvider:
    return LuxandFaceVerificationProvider(
        _settings(**overrides), transport=httpx.MockTransport(handler)
    )


def _respond(body: object, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(status, json=body)


# --- settings / factory ------------------------------------------------------------------------


def test_disabled_by_default() -> None:
    settings = Settings(environment="development", face_verification_provider="disabled")
    assert get_face_verification_provider(settings) is None


def test_luxand_selected_when_configured() -> None:
    assert isinstance(get_face_verification_provider(_settings()), LuxandFaceVerificationProvider)


def test_luxand_without_token_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(luxand_api_token="")


def test_threshold_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(face_match_min_similarity=1.5)


# --- enroll -------------------------------------------------------------------------------------


async def test_enroll_sends_store_0_and_returns_uuid() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "status": "success",
                "uuid": _PERSON,
                "name": "x",
                "faces": [],
                "collections": [],
            },
        )

    person_id = await _provider(handler).enroll(
        label="emp-1", image=_IMG, content_type="image/jpeg"
    )

    assert person_id == _PERSON
    (request,) = seen
    assert request.method == "POST"
    assert request.url.path == "/v2/person"
    assert request.headers["token"] == _TOKEN
    body = request.content
    # Never let Luxand host the face image publicly.
    assert b'name="store"\r\n\r\n0' in body
    assert b'name="name"\r\n\r\nemp-1' in body


async def test_enroll_no_face_is_user_correctable() -> None:
    provider = _provider(
        _respond({"status": "failure", "message": "Can't find faces in attached images"})
    )
    with pytest.raises(FaceProviderNoFaceError):
        await provider.enroll(label="emp-1", image=_IMG, content_type="image/jpeg")


# --- verify -------------------------------------------------------------------------------------


async def test_verify_match_above_threshold() -> None:
    provider = _provider(
        _respond({"status": "success", "message": "verified", "probability": 0.97, "rotation": 0})
    )
    result = await provider.verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")
    assert result.decision == "MATCHED"
    assert result.similarity == Decimal("0.97")


async def test_verify_provider_match_below_our_threshold_is_no_match() -> None:
    provider = _provider(
        _respond({"status": "success", "message": "verified", "probability": 0.85}),
        face_match_min_similarity=0.9,
    )
    result = await provider.verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")
    assert result.decision == "NO_MATCH"
    assert result.similarity == Decimal("0.85")


async def test_verify_not_verified() -> None:
    provider = _provider(_respond({"status": "failure", "message": "Not verified"}))
    result = await provider.verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")
    assert result.decision == "NO_MATCH"
    assert result.similarity is None


async def test_verify_no_face() -> None:
    provider = _provider(_respond({"status": "failure", "message": _NO_FACE}))
    result = await provider.verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")
    assert result.decision == "NO_FACE"


async def test_verify_success_without_probability_is_unrecognised() -> None:
    provider = _provider(_respond({"status": "success", "message": "verified"}))
    with pytest.raises(FaceProviderError):
        await provider.verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")


async def test_verify_unknown_failure_message_is_error_not_silent_reject() -> None:
    provider = _provider(_respond({"status": "failure", "message": "Quota exceeded"}))
    with pytest.raises(FaceProviderError):
        await provider.verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")


async def test_verify_rejects_malformed_person_id_without_request() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call the provider")

    with pytest.raises(FaceProviderError):
        await _provider(handler).verify(
            person_id="../v2/person", image=_IMG, content_type="image/jpeg"
        )


# --- liveness -----------------------------------------------------------------------------------


async def test_liveness_real_above_threshold() -> None:
    provider = _provider(_respond({"status": "success", "score": 0.980349, "result": "real"}))
    result = await provider.check_liveness(image=_IMG, content_type="image/jpeg")
    assert result.decision == "LIVE"
    assert result.score == Decimal("0.9803")


async def test_liveness_fake_is_spoof() -> None:
    provider = _provider(_respond({"status": "success", "score": 0.694354, "result": "fake"}))
    result = await provider.check_liveness(image=_IMG, content_type="image/jpeg")
    assert result.decision == "SPOOF"


async def test_liveness_real_below_threshold_is_spoof() -> None:
    provider = _provider(
        _respond({"status": "success", "score": 0.7, "result": "real"}),
        face_liveness_min_score=0.8,
    )
    result = await provider.check_liveness(image=_IMG, content_type="image/jpeg")
    assert result.decision == "SPOOF"


async def test_liveness_no_face() -> None:
    provider = _provider(
        _respond({"status": "failure", "message": "there is no faces in the photo"})
    )
    result = await provider.check_liveness(image=_IMG, content_type="image/jpeg")
    assert result.decision == "NO_FACE"


# --- delete -------------------------------------------------------------------------------------


async def test_delete_uses_legacy_person_route() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "success", "message": "Successfully deleted"})

    await _provider(handler).delete_person(person_id=_PERSON)
    assert seen[0].method == "DELETE"
    assert seen[0].url.path == f"/person/{_PERSON}"


async def test_delete_already_gone_is_success() -> None:
    provider = _provider(
        _respond({"status": "failure", "message": f"There is no Person with ID {_PERSON}"})
    )
    await provider.delete_person(person_id=_PERSON)


# --- transport failures & log hygiene ----------------------------------------------------------


async def test_unauthorized_raises_and_never_logs_token_or_body() -> None:
    body = {"message": "You are not authorized for the request: can't get your token"}
    provider = _provider(_respond(body, status=401))
    with capture_logs() as logs, pytest.raises(FaceProviderError) as exc_info:
        await provider.verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")

    rendered = json.dumps(logs, default=str) + str(exc_info.value)
    assert _TOKEN not in rendered
    assert "not authorized" not in rendered
    assert logs[0]["status_code"] == 401


async def test_timeout_raises_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(FaceProviderError):
        await _provider(handler).check_liveness(image=_IMG, content_type="image/jpeg")


async def test_non_json_response_raises_provider_error() -> None:
    provider = _provider(lambda _r: httpx.Response(200, text="<html>bad gateway</html>"))
    with pytest.raises(FaceProviderError):
        await provider.verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")
