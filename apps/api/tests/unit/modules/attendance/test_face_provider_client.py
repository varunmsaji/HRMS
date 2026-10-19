"""The Face++ adapter's pooled HTTP client: reuse, bounded concurrency, lifecycle, failure
handling. `httpx.MockTransport` only — nothing here contacts Face++."""

import asyncio

import httpx
import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs
from tests.unit.modules.attendance.test_face_verification import (
    _API_KEY,
    _API_SECRET,
    _PERSON,
    _settings,
)

from hrms.modules.attendance.face_verification import (
    FaceppFaceVerificationProvider,
    FaceProviderError,
    close_face_verification_providers,
    get_face_verification_provider,
)


def _ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"request_id": "r1", "time_used": 1})


async def test_one_client_is_reused_across_calls() -> None:
    provider = FaceppFaceVerificationProvider(_settings(), transport=httpx.MockTransport(_ok))

    await provider.delete_person(person_id=_PERSON)
    first = provider._client
    await provider.delete_person(person_id=_PERSON)

    assert first is not None
    assert provider._client is first
    await provider.aclose()


async def test_aclose_is_idempotent_and_the_provider_works_again_afterwards() -> None:
    provider = FaceppFaceVerificationProvider(_settings(), transport=httpx.MockTransport(_ok))
    await provider.aclose()  # never used: harmless
    await provider.delete_person(person_id=_PERSON)
    client = provider._client
    assert client is not None

    await provider.aclose()
    await provider.aclose()

    assert client.is_closed
    assert provider._client is None
    await provider.delete_person(person_id=_PERSON)  # lazily rebuilt
    assert provider._client is not None and provider._client is not client
    await provider.aclose()


def test_a_new_event_loop_gets_a_new_client_instead_of_sharing_one() -> None:
    provider = FaceppFaceVerificationProvider(_settings(), transport=httpx.MockTransport(_ok))
    seen: list[object] = []

    async def use() -> None:
        await provider.delete_person(person_id=_PERSON)
        seen.append(provider._client)

    asyncio.run(use())
    asyncio.run(use())

    assert seen[0] is not seen[1]


async def test_concurrency_is_bounded() -> None:
    in_flight = 0
    peak = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return httpx.Response(200, json={})

    provider = FaceppFaceVerificationProvider(
        _settings(face_provider_max_concurrency=2), transport=httpx.MockTransport(handler)
    )

    await asyncio.gather(*[provider.delete_person(person_id=_PERSON) for _ in range(8)])

    assert peak == 2
    await provider.aclose()


async def test_each_call_carries_its_own_payload_under_concurrency() -> None:
    seen: set[str] = set()

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)
        seen.add(request.content.decode().split("faceset_token=")[1].split("&")[0])
        return httpx.Response(200, json={})

    provider = FaceppFaceVerificationProvider(_settings(), transport=httpx.MockTransport(handler))

    await asyncio.gather(*[provider.delete_person(person_id=f"fs-{i}") for i in range(6)])

    assert seen == {f"fs-{i}" for i in range(6)}
    await provider.aclose()


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("slow"),
        httpx.ConnectTimeout("slow"),
        httpx.ConnectError("refused"),
        httpx.RemoteProtocolError("reset"),
        httpx.PoolTimeout("busy"),
    ],
)
async def test_transport_failures_become_provider_errors_without_leaking_secrets(
    failure: Exception,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise failure

    provider = FaceppFaceVerificationProvider(_settings(), transport=httpx.MockTransport(handler))

    with capture_logs() as logs, pytest.raises(FaceProviderError) as raised:
        await provider.delete_person(person_id=_PERSON)

    assert _API_KEY not in str(raised.value) and _API_SECRET not in str(raised.value)
    assert _API_KEY not in str(logs) and _API_SECRET not in str(logs)
    await provider.aclose()


@pytest.mark.parametrize("content", [b"<html>502 Bad Gateway</html>", b"", b"[1, 2]", b"null"])
async def test_malformed_or_non_object_bodies_fail_closed(content: bytes) -> None:
    provider = FaceppFaceVerificationProvider(
        _settings(), transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=content))
    )

    with pytest.raises(FaceProviderError):
        await provider.delete_person(person_id=_PERSON)
    await provider.aclose()


async def test_http_error_statuses_with_error_bodies_are_provider_errors() -> None:
    provider = FaceppFaceVerificationProvider(
        _settings(),
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(403, json={"error_message": "CONCURRENCY_LIMIT_EXCEEDED"})
        ),
    )

    with pytest.raises(FaceProviderError):
        await provider.delete_person(person_id=_PERSON)
    await provider.aclose()


async def test_factory_shares_one_provider_per_configuration_and_shutdown_closes_it() -> None:
    settings = _settings()
    first = get_face_verification_provider(settings)
    assert first is get_face_verification_provider(_settings())
    assert first is not get_face_verification_provider(_settings(face_provider_max_concurrency=7))
    assert isinstance(first, FaceppFaceVerificationProvider)
    first._transport = httpx.MockTransport(_ok)
    await first.delete_person(person_id=_PERSON)
    client = first._client
    assert client is not None

    await close_face_verification_providers()

    assert client.is_closed
    assert get_face_verification_provider(settings) is not first  # rebuilt after shutdown
    await close_face_verification_providers()


def test_provider_transport_settings_are_bounded() -> None:
    for name, bad in (
        ("face_provider_max_concurrency", 0),
        ("face_provider_max_concurrency", 1000),
        ("face_provider_connect_timeout_seconds", 0),
        ("face_enrollment_provider_budget_seconds", 0),
        ("face_enrollment_lease_seconds", 1),
    ):
        with pytest.raises(ValidationError):
            _settings(**{name: bad})


def test_the_reservation_lease_must_outlast_the_provider_budget() -> None:
    with pytest.raises(ValidationError, match="lease"):
        _settings(face_enrollment_provider_budget_seconds=200, face_enrollment_lease_seconds=100)
