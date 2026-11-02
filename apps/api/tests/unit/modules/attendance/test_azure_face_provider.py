"""Azure Face adapter against `httpx.MockTransport` only — nothing here contacts Azure."""

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import ValidationError

from hrms.core.config.settings import Settings
from hrms.modules.attendance.azure_face_provider import AzureFaceVerificationProvider
from hrms.modules.attendance.face_verification import (
    FaceProviderError,
    FaceProviderNoFaceError,
)

_KEY = "k" * 32
_PERSON = "11111111-2222-3333-4444-555555555555"
_FACE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "development",
        "face_verification_provider": "azure",
        "azure_endpoint": "https://example.cognitiveservices.azure.com/",
        "azure_face_api_key": _KEY,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> AzureFaceVerificationProvider:
    return AzureFaceVerificationProvider(_settings(), transport=httpx.MockTransport(handler))


def test_azure_requires_credentials() -> None:
    with pytest.raises(ValidationError):
        _settings(azure_face_api_key="")


async def test_verify_matches_above_threshold_and_sends_key_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/detect"):
            return httpx.Response(200, json=[{"faceId": _FACE}])
        return httpx.Response(200, json={"isIdentical": True, "confidence": 0.93})

    result = await _provider(handler).verify(
        person_id=_PERSON, image=b"x", content_type="image/jpeg"
    )

    assert result.decision == "MATCHED"
    assert float(result.similarity or 0) == 0.93
    assert all(r.headers["Ocp-Apim-Subscription-Key"] == _KEY for r in seen)
    assert json.loads(seen[1].content)["personId"] == _PERSON


async def test_verify_below_threshold_is_no_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/detect"):
            return httpx.Response(200, json=[{"faceId": _FACE}])
        return httpx.Response(200, json={"isIdentical": False, "confidence": 0.2})

    result = await _provider(handler).verify(
        person_id=_PERSON, image=b"x", content_type="image/jpeg"
    )
    assert result.decision == "NO_MATCH"


async def test_verify_no_face_and_multiple_faces() -> None:
    none = await _provider(lambda r: httpx.Response(200, json=[])).verify(
        person_id=_PERSON, image=b"x", content_type="image/jpeg"
    )
    many = await _provider(
        lambda r: httpx.Response(200, json=[{"faceId": _FACE}, {"faceId": _FACE}])
    ).verify(person_id=_PERSON, image=b"x", content_type="image/jpeg")
    assert (none.decision, many.decision) == ("NO_FACE", "MULTIPLE_FACES")


async def test_limited_access_rejection_is_a_provider_error_without_leaking_body() -> None:
    body = {"error": {"code": "Forbidden", "message": "secret detail"}}
    provider = _provider(lambda r: httpx.Response(403, json=body))
    with pytest.raises(FaceProviderError) as exc:
        await provider.verify(person_id=_PERSON, image=b"x", content_type="image/jpeg")
    assert "secret detail" not in str(exc.value)


async def test_enroll_creates_group_person_and_face() -> None:
    paths: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path.endswith("/detect"):
            return httpx.Response(200, json=[{}])
        if request.method == "PUT":
            return httpx.Response(409, json={"error": {"code": "LargePersonGroupExists"}})
        if request.url.path.endswith("/persons"):
            return httpx.Response(200, json={"personId": _PERSON})
        return httpx.Response(200, json={"persistedFaceId": _FACE})

    person = await _provider(handler).enroll(label="emp", image=b"x", content_type="image/jpeg")

    assert person == _PERSON
    assert paths[-1][1].endswith(f"/persons/{_PERSON}/persistedfaces")


async def test_enroll_without_a_face_raises_no_face() -> None:
    with pytest.raises(FaceProviderNoFaceError):
        await _provider(lambda r: httpx.Response(200, json=[])).enroll(
            label="emp", image=b"x", content_type="image/jpeg"
        )


async def test_rate_limit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_s: float) -> None: ...

    monkeypatch.setattr("hrms.modules.attendance.azure_face_provider.asyncio.sleep", no_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        return httpx.Response(200, json=[])

    result = await _provider(handler).verify(
        person_id=_PERSON, image=b"x", content_type="image/jpeg"
    )
    assert result.decision == "NO_FACE" and calls["n"] == 2


async def test_delete_person_tolerates_already_gone() -> None:
    gone = {"error": {"code": "PersonNotFound"}}
    await _provider(lambda r: httpx.Response(404, json=gone)).delete_person(person_id=_PERSON)
