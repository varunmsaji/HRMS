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
    FaceProviderMultipleFacesError,
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
    assert isinstance(get_face_verification_provider(_settings()), FaceppFaceVerificationProvider)


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


def _fallback_handler(
    *, stored: list[str], confidence: float | None, calls: list[str] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    """`search` answers 200 with no results (what a trial key does); getdetail lists `stored`; every
    `compare` answers `confidence`."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if calls is not None:
            calls.append(path)
        if path == "/facepp/v3/detect":
            return httpx.Response(200, json=_detect([_face()]))
        if path == "/facepp/v3/search":
            return httpx.Response(200, json={"results": []})
        if path == "/facepp/v3/faceset/getdetail":
            return httpx.Response(200, json={"face_tokens": stored, "face_count": len(stored)})
        if path == "/facepp/v3/compare":
            return httpx.Response(200, json={"confidence": confidence, "request_id": "req-c"})
        raise AssertionError(path)

    return handler


async def test_verify_empty_search_falls_back_to_compare_and_matches() -> None:
    calls: list[str] = []
    handler = _fallback_handler(stored=["ft_a", "ft_b"], confidence=91.0, calls=calls)

    result = await _provider(handler).verify(
        person_id=_PERSON, image=_IMG, content_type="image/jpeg"
    )

    assert result.decision == "MATCHED"
    assert result.similarity == Decimal("0.91")
    assert calls.count("/facepp/v3/compare") == 2


async def test_verify_empty_search_fallback_below_threshold_is_no_match() -> None:
    handler = _fallback_handler(stored=["ft_a"], confidence=12.0)

    result = await _provider(handler).verify(
        person_id=_PERSON, image=_IMG, content_type="image/jpeg"
    )

    assert result.decision == "NO_MATCH"
    assert result.similarity == Decimal("0.12")


async def test_verify_empty_search_with_no_stored_faces_is_no_match() -> None:
    handler = _fallback_handler(stored=[], confidence=99.0)

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


# --- no liveness here ---------------------------------------------------------------------------


def test_adapter_offers_no_liveness_check() -> None:
    """Face++ detection is not anti-spoofing. The former presence-only `check_liveness` (LIVE for
    any detected face) is gone so nothing can mistake it for liveness again; liveness is
    `attendance/liveness.py`, on our own server."""
    provider = _provider(_respond({}))
    assert not hasattr(provider, "check_liveness")


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
    provider = _provider(_respond({"error_message": "INVALID_FACESET_TOKEN"}, status=400))
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
        await _provider(handler).verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")


async def test_non_json_response_raises_provider_error() -> None:
    provider = _provider(lambda _r: httpx.Response(200, text="<html>bad gateway</html>"))
    with pytest.raises(FaceProviderError):
        await provider.verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")


# --- identity-integrity hardening ---------------------------------------------------------------


def _search_handler(search_body: object) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/facepp/v3/detect":
            return httpx.Response(200, json=_detect([_face()]))
        return httpx.Response(200, json=search_body)

    return handler


async def test_verify_with_several_faces_is_ambiguous_not_a_guess() -> None:
    """The adapter used to take `faces[0]`; which of two faces is the employee is unknowable."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_detect([_face("ft_a"), _face("ft_b")]))

    result = await _provider(handler).verify(
        person_id=_PERSON, image=_IMG, content_type="image/jpeg"
    )

    assert result.decision == "MULTIPLE_FACES"
    assert result.similarity is None
    assert calls == ["/facepp/v3/detect"]  # no search was made with a guessed face


async def test_enroll_and_reference_photo_with_several_faces_are_refused() -> None:
    provider = _provider(_respond(_detect([_face("ft_a"), _face("ft_b")])))
    with pytest.raises(FaceProviderMultipleFacesError):
        await provider.enroll(label="x", image=_IMG, content_type="image/jpeg")
    with pytest.raises(FaceProviderMultipleFacesError):
        await provider.add_reference_photo(person_id=_PERSON, image=_IMG, content_type="image/jpeg")


async def test_verify_uses_the_best_confidence_and_searches_only_the_given_faceset() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/facepp/v3/detect":
            return httpx.Response(200, json=_detect([_face()]))
        seen.update(dict(p.split("=") for p in request.content.decode().split("&") if "=" in p))
        return httpx.Response(
            200, json={"results": [{"confidence": 40.0}, {"confidence": 93.0}], "request_id": "r-1"}
        )

    result = await _provider(handler).verify(
        person_id=_PERSON, image=_IMG, content_type="image/jpeg"
    )

    assert (result.decision, result.similarity) == ("MATCHED", Decimal("0.93"))
    assert seen["faceset_token"] == _PERSON


@pytest.mark.parametrize(
    "results",
    [
        [{"confidence": 97.0}, {"face_token": "no-confidence"}],
        [{"confidence": 97.0}, "not-a-dict"],
        [{"confidence": "97"}],
        [{"confidence": True}],
        None,
        {"confidence": 97.0},
    ],
)
async def test_malformed_search_results_fail_closed(results: object) -> None:
    """One bad entry makes the whole response untrustworthy: it is an error, never a match and
    never silently skipped."""
    handler = _search_handler({"results": results})
    with pytest.raises(FaceProviderError):
        await _provider(handler).verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")


async def test_result_carries_no_raw_provider_body() -> None:
    body = {
        "request_id": "req-abc_123",
        "image_id": "img-secret-id",
        "time_used": 12,
        "results": [{"confidence": 97.0, "face_token": _FACE_TOKEN, "user_id": "u-1"}],
        "thresholds": {"1e-3": 62.0},
        "faces": [{"face_token": _FACE_TOKEN, "face_rectangle": {"top": 1}}],
    }

    result = await _provider(_search_handler(body)).verify(
        person_id=_PERSON, image=_IMG, content_type="image/jpeg"
    )

    assert result.provider_request_id == "req-abc_123"
    rendered = repr(result)
    for leaked in (_FACE_TOKEN, "img-secret-id", "face_rectangle", "thresholds", "u-1"):
        assert leaked not in rendered
    assert not hasattr(result, "provider_response")


@pytest.mark.parametrize(
    "request_id", ["has space", "x" * 65, "<script>", "line\nbreak", 12345, None, ""]
)
async def test_untrusted_request_ids_are_dropped(request_id: object) -> None:
    body = {"request_id": request_id, "results": [{"confidence": 97.0}]}
    result = await _provider(_search_handler(body)).verify(
        person_id=_PERSON, image=_IMG, content_type="image/jpeg"
    )
    assert result.provider_request_id is None
    assert result.decision == "MATCHED"


async def test_provider_error_logs_only_the_error_code_never_echoed_arguments() -> None:
    echoed = f"INVALID_FACESET_TOKEN:{_PERSON} api_key={_API_KEY} face_token={_FACE_TOKEN}"
    provider = _provider(_respond({"error_message": echoed}, status=400))

    with capture_logs() as logs, pytest.raises(FaceProviderError) as exc_info:
        await provider.verify(person_id=_PERSON, image=_IMG, content_type="image/jpeg")

    rendered = json.dumps(logs, default=str) + str(exc_info.value)
    assert "INVALID_FACESET_TOKEN" in rendered
    for leaked in (_PERSON, _API_KEY, _API_SECRET, _FACE_TOKEN):
        assert leaked not in rendered


async def test_unrecognisable_error_message_is_logged_as_unknown() -> None:
    provider = _provider(_respond({"error_message": "secret stuff: " + _API_KEY}, status=400))
    with capture_logs() as logs, pytest.raises(FaceProviderError):
        await provider.delete_person(person_id=_PERSON)
    rendered = json.dumps(logs, default=str)
    assert '"error_code": "UNKNOWN"' in rendered
    assert _API_KEY not in rendered


# --- retention / limit settings -----------------------------------------------------------------


def test_retention_is_unset_and_cleanup_is_report_only_by_default() -> None:
    settings = Settings(environment="development")
    assert settings.face_liveness_session_retention_days is None
    assert settings.face_attempt_detail_retention_days is None
    assert settings.face_enrollment_attempt_retention_days is None
    assert settings.face_cleanup_dry_run is True
    assert settings.face_cleanup_hold_company_id_set == frozenset()
    assert settings.face_enrollment_max_failed_attempts == 5


def test_hold_list_is_parsed_and_a_typo_refuses_to_boot() -> None:
    a, b = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
    ok = Settings(environment="development", face_cleanup_hold_company_ids=f"{a}, {b} ,")
    assert {str(u) for u in ok.face_cleanup_hold_company_id_set} == {a, b}
    with pytest.raises(ValidationError):
        Settings(environment="development", face_cleanup_hold_company_ids=f"{a},not-a-uuid")


@pytest.mark.parametrize(
    "name",
    [
        "face_liveness_session_retention_days",
        "face_attempt_detail_retention_days",
        "face_enrollment_attempt_retention_days",
        "face_enrollment_max_failed_attempts",
    ],
)
def test_zero_or_negative_periods_and_limits_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        Settings(environment="development", **{name: 0})  # type: ignore[arg-type]
