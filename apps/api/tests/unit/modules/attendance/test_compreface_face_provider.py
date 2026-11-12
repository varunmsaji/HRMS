"""CompreFace adapter against `httpx.MockTransport` only — nothing here contacts CompreFace."""

from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from hrms.core.config.settings import Settings
from hrms.modules.attendance.compreface_face_provider import CompreFaceVerificationProvider
from hrms.modules.attendance.face_verification import (
    FaceProviderError,
    FaceProviderMultipleFacesError,
    FaceProviderNoFaceError,
    get_face_verification_provider,
    provider_for_stored_name,
)

_KEY = "k" * 36
_SUBJECT = "11111111-2222-3333-4444-555555555555"
_IMG_A = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_IMG_B = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
_NO_FACE = {"message": "No face is found in the given image", "code": 28}


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "development",
        "face_verification_provider": "compreface",
        "compreface_base_url": "http://compreface-api:8080",
        "compreface_api_key": _KEY,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
) -> CompreFaceVerificationProvider:
    return CompreFaceVerificationProvider(_settings(), transport=httpx.MockTransport(handler))


def _faces(*similarities: float) -> httpx.Response:
    return httpx.Response(200, json={"result": [{"similarity": s} for s in similarities]})


def _examples(*ids: str) -> httpx.Response:
    return httpx.Response(200, json={"faces": [{"image_id": i, "subject": _SUBJECT} for i in ids]})


@pytest.mark.parametrize(
    "overrides",
    [
        {"compreface_api_key": ""},
        {"compreface_base_url": ""},
        # Plain http to a public host would carry face photos unencrypted.
        {"compreface_base_url": "http://compreface.example.com"},
        {"compreface_base_url": "http://10.0.0.5:8080"},
    ],
)
def test_compreface_refuses_to_boot_without_safe_config(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _settings(**overrides)


@pytest.mark.parametrize(
    "url", ["http://compreface-api:8080", "http://localhost:8000", "https://face.example.com"]
)
def test_compreface_accepts_internal_http_or_https(url: str) -> None:
    assert _settings(compreface_base_url=url).compreface_base_url == url


def test_shadow_compreface_also_needs_config() -> None:
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg]
            environment="development",
            face_verification_provider="facepp",
            facepp_api_key="a",
            facepp_api_secret="b",
            face_provider_comparison_enabled=True,
            face_verification_shadow_provider="compreface",
        )


def test_factory_selects_compreface_and_stored_name_resolves() -> None:
    settings = _settings()
    assert get_face_verification_provider(settings).provider_name == "COMPREFACE"  # type: ignore[union-attr]
    stored = provider_for_stored_name("COMPREFACE", settings)
    assert isinstance(stored, CompreFaceVerificationProvider)


def test_own_thresholds_are_exposed_to_the_service() -> None:
    provider = CompreFaceVerificationProvider(
        _settings(
            compreface_match_min_similarity=0.97, compreface_enrollment_angle_min_similarity=0.9
        )
    )
    assert (provider.match_threshold, provider.angle_threshold) == (
        Decimal("0.97"),
        Decimal("0.9"),
    )


async def test_verify_takes_best_example_and_sends_key_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            assert request.url.params["subject"] == _SUBJECT
            return _examples(_IMG_A, _IMG_B)
        return _faces(0.95 if _IMG_B in request.url.path else 0.7)

    result = await _provider(handler).verify(
        person_id=_SUBJECT, image=b"x", content_type="image/jpeg"
    )

    assert result.decision == "MATCHED"
    assert result.similarity == Decimal("0.95")
    assert all(r.headers["x-api-key"] == _KEY for r in seen)
    assert seen[1].url.path == f"/api/v1/recognition/faces/{_IMG_A}/verify"


async def test_verify_below_threshold_is_no_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _examples(_IMG_A) if request.method == "GET" else _faces(0.4)

    result = await _provider(handler).verify(
        person_id=_SUBJECT, image=b"x", content_type="image/jpeg"
    )
    assert (result.decision, result.similarity) == ("NO_MATCH", Decimal("0.4"))


async def test_verify_no_face_and_multiple_faces() -> None:
    def no_face(request: httpx.Request) -> httpx.Response:
        return _examples(_IMG_A) if request.method == "GET" else httpx.Response(400, json=_NO_FACE)

    def crowded(request: httpx.Request) -> httpx.Response:
        return _examples(_IMG_A, _IMG_B) if request.method == "GET" else _faces(0.99, 0.3)

    none = await _provider(no_face).verify(person_id=_SUBJECT, image=b"x", content_type="")
    many = await _provider(crowded).verify(person_id=_SUBJECT, image=b"x", content_type="")
    assert (none.decision, many.decision) == ("NO_FACE", "MULTIPLE_FACES")


async def test_verify_with_no_enrolled_examples_is_a_provider_error() -> None:
    with pytest.raises(FaceProviderError):
        await _provider(lambda r: _examples()).verify(
            person_id=_SUBJECT, image=b"x", content_type="image/jpeg"
        )


async def test_rejection_does_not_leak_body() -> None:
    body = {"message": "secret detail", "code": 5}
    with pytest.raises(FaceProviderError) as exc:
        await _provider(lambda r: httpx.Response(401, json=body)).verify(
            person_id=_SUBJECT, image=b"x", content_type="image/jpeg"
        )
    assert "secret detail" not in str(exc.value)


async def test_enroll_uses_an_opaque_subject_and_checks_face_count() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/verify"):
            return _faces(1.0)
        return httpx.Response(201, json={"image_id": _IMG_A, "subject": "s"})

    person = await _provider(handler).enroll(
        label="employee-123", image=b"x", content_type="image/jpeg"
    )

    assert person != "employee-123" and len(person) == 36
    assert calls == [
        ("POST", "/api/v1/recognition/faces"),
        ("POST", f"/api/v1/recognition/faces/{_IMG_A}/verify"),
    ]


async def test_enroll_without_a_face_raises_no_face_and_cleans_up() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "DELETE":
            return httpx.Response(404, json={})
        return httpx.Response(400, json=_NO_FACE)

    with pytest.raises(FaceProviderNoFaceError):
        await _provider(handler).enroll(label="emp", image=b"x", content_type="image/jpeg")
    assert calls == ["POST", "DELETE"]


async def test_reference_photo_with_two_faces_is_removed_again() -> None:
    deleted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            deleted.append(request.url.path)
            return httpx.Response(200, json={"image_id": _IMG_B})
        if request.url.path.endswith("/verify"):
            return _faces(1.0, 0.2)
        return httpx.Response(201, json={"image_id": _IMG_B, "subject": _SUBJECT})

    with pytest.raises(FaceProviderMultipleFacesError):
        await _provider(handler).add_reference_photo(
            person_id=_SUBJECT, image=b"x", content_type="image/jpeg"
        )
    assert deleted == [f"/api/v1/recognition/faces/{_IMG_B}"]


async def test_delete_person_tolerates_already_gone() -> None:
    await _provider(lambda r: httpx.Response(404, json={})).delete_person(person_id=_SUBJECT)
    gone = {"message": f"Subject {_SUBJECT} not found", "code": 34}
    await _provider(lambda r: httpx.Response(400, json=gone)).delete_person(person_id=_SUBJECT)


async def test_delete_person_surfaces_other_failures() -> None:
    with pytest.raises(FaceProviderError):
        await _provider(lambda r: httpx.Response(500, json={})).delete_person(person_id=_SUBJECT)
