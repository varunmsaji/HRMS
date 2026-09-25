"""Unit tests for `DocumentStorageService` (Upload Security Batch A,
docs/audits/UPLOAD_BATCH_A_STORAGE_ARCHITECTURE.md) — the endpoint-selection logic (internal vs.
public/presigned) exercised here against a fake aioboto3 client, since the point under test is
*which endpoint each operation is signed/issued against*, not the S3-protocol wire format itself.
The actual round trip against real MinIO (upload/download/delete/presigned GET, and persistence
across a MinIO restart) is covered by `tests/integration/core/test_storage.py`."""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

import pytest

from hrms.core.config.settings import Settings
from hrms.core.storage import DocumentStorageService

pytestmark = pytest.mark.asyncio


class _FakeBody:
    async def read(self) -> bytes:
        return b"fake-object-bytes"


class _FakeS3Client:
    def __init__(self) -> None:
        self.put_object_calls: list[dict[str, Any]] = []
        self.get_object_calls: list[dict[str, Any]] = []
        self.delete_object_calls: list[dict[str, Any]] = []
        self.presign_calls: list[dict[str, Any]] = []

    async def put_object(self, **kwargs: Any) -> None:
        self.put_object_calls.append(kwargs)

    async def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.get_object_calls.append(kwargs)
        return {"Body": _FakeBody()}

    async def delete_object(self, **kwargs: Any) -> None:
        self.delete_object_calls.append(kwargs)

    async def generate_presigned_url(self, operation: str, **kwargs: Any) -> str:
        self.presign_calls.append({"operation": operation, **kwargs})
        return "http://presigned.example/fake"


class _FakeSession:
    """Records every `client(...)` call's kwargs (in particular `endpoint_url`) so tests can
    assert which endpoint each operation was signed/issued against, and hands back the same
    `_FakeS3Client` instance so put/get/delete/presign calls all land on one recorder."""

    instances: list["_FakeSession"] = []

    def __init__(self) -> None:
        self.client_calls: list[dict[str, Any]] = []
        self.fake_client = _FakeS3Client()
        _FakeSession.instances.append(self)

    def client(self, service_name: str, **kwargs: Any):  # noqa: ANN201
        self.client_calls.append({"service_name": service_name, **kwargs})
        fake_client = self.fake_client

        @asynccontextmanager
        async def _ctx():
            yield fake_client

        return _ctx()


@pytest.fixture(autouse=True)
def _reset_fake_session_instances() -> None:
    _FakeSession.instances = []
    yield
    _FakeSession.instances = []


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": "development",
        "s3_endpoint_url": "http://minio:9000",
        "s3_bucket_documents": "hrms-documents",
        "aws_access_key_id": "test-access-key",
        "aws_secret_access_key": "test-secret-key",
    }
    base.update(overrides)
    return Settings(**base)


async def test_put_object_uses_the_internal_endpoint_and_bucket() -> None:
    service = DocumentStorageService(_settings())
    with patch("hrms.core.storage.aioboto3.Session", _FakeSession):
        await service.put_object(key="onboarding/doc.png", body=b"data", content_type="image/png")

    session = _FakeSession.instances[0]
    assert session.client_calls[0]["endpoint_url"] == "http://minio:9000"
    call = session.fake_client.put_object_calls[0]
    assert call["Bucket"] == "hrms-documents"
    assert call["Key"] == "onboarding/doc.png"
    assert call["Body"] == b"data"
    assert call["ContentType"] == "image/png"


async def test_get_object_uses_the_internal_endpoint_and_returns_bytes() -> None:
    service = DocumentStorageService(_settings())
    with patch("hrms.core.storage.aioboto3.Session", _FakeSession):
        body = await service.get_object(key="employee-imports/batch.csv")

    assert body == b"fake-object-bytes"
    session = _FakeSession.instances[0]
    assert session.client_calls[0]["endpoint_url"] == "http://minio:9000"
    assert session.fake_client.get_object_calls[0]["Bucket"] == "hrms-documents"


async def test_delete_object_uses_the_internal_endpoint() -> None:
    service = DocumentStorageService(_settings())
    with patch("hrms.core.storage.aioboto3.Session", _FakeSession):
        await service.delete_object(key="onboarding/doc.png")

    session = _FakeSession.instances[0]
    assert session.client_calls[0]["endpoint_url"] == "http://minio:9000"
    assert session.fake_client.delete_object_calls[0]["Key"] == "onboarding/doc.png"


async def test_presigned_get_url_falls_back_to_the_internal_endpoint_when_unconfigured() -> None:
    service = DocumentStorageService(_settings(s3_public_endpoint_url=None))
    with patch("hrms.core.storage.aioboto3.Session", _FakeSession):
        url = await service.presigned_get_url(key="onboarding/doc.png")

    assert url == "http://presigned.example/fake"
    session = _FakeSession.instances[0]
    assert session.client_calls[0]["endpoint_url"] == "http://minio:9000"


async def test_presigned_get_url_signs_against_the_public_endpoint_when_configured() -> None:
    """The core Phase 6 requirement: when MinIO sits on an internal Docker-network address but
    presigned URLs must be reachable from a browser through a separate Nginx-fronted hostname,
    `presigned_get_url` must sign against the public hostname — not the internal one every other
    operation uses — since the URL's host is baked into its SigV4 signature."""
    service = DocumentStorageService(
        _settings(s3_public_endpoint_url="https://storage.hrms.example.com")
    )
    with patch("hrms.core.storage.aioboto3.Session", _FakeSession):
        await service.presigned_get_url(key="onboarding/doc.png")

    session = _FakeSession.instances[0]
    assert session.client_calls[0]["endpoint_url"] == "https://storage.hrms.example.com"


async def test_presigned_get_url_passes_bucket_key_and_expiry() -> None:
    service = DocumentStorageService(_settings())
    with patch("hrms.core.storage.aioboto3.Session", _FakeSession):
        await service.presigned_get_url(key="some/key", expires_in=120)

    session = _FakeSession.instances[0]
    call = session.fake_client.presign_calls[0]
    assert call["operation"] == "get_object"
    assert call["Params"] == {"Bucket": "hrms-documents", "Key": "some/key"}
    assert call["ExpiresIn"] == 120


async def test_other_operations_never_fall_back_to_the_public_endpoint() -> None:
    """`s3_public_endpoint_url` exists purely to fix up presigned URLs for a browser — every
    other operation must keep using the internal endpoint even when a public one is configured,
    so backend-to-MinIO traffic never leaves the internal Docker network unnecessarily."""
    service = DocumentStorageService(
        _settings(s3_public_endpoint_url="https://storage.hrms.example.com")
    )
    with patch("hrms.core.storage.aioboto3.Session", _FakeSession):
        await service.put_object(key="k", body=b"d", content_type="text/plain")
        await service.get_object(key="k")
        await service.delete_object(key="k")

    # A fresh `aioboto3.Session()` per call (this class's existing pattern), so each operation
    # produced its own `_FakeSession` instance — every one must have used the internal endpoint.
    endpoints = [instance.client_calls[0]["endpoint_url"] for instance in _FakeSession.instances]
    assert endpoints == ["http://minio:9000", "http://minio:9000", "http://minio:9000"]
