"""Integration tests for `DocumentStorageService` against the real local MinIO container
(docker-compose.yml `minio` service) — no mocking, same convention as
`tests/integration/modules/onboarding/test_onboarding_documents.py`, since the point of these
tests is that document bytes actually round-trip through S3-compatible storage and back
(Upload Security Batch A, docs/audits/UPLOAD_BATCH_A_STORAGE_ARCHITECTURE.md).

The restart/persistence test additionally shells out to `docker restart` on the MinIO container
named in docker-compose.yml — it is skipped when the `docker` CLI or that specific container
isn't reachable (e.g. a sandboxed CI runner without Docker-in-Docker), rather than failing the
whole suite; every other test here only needs the container already running, exactly like the
rest of this repository's integration suite."""

import shutil
import subprocess
import uuid

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError

from hrms.core.config.settings import get_settings
from hrms.core.storage import DocumentStorageService

pytestmark = pytest.mark.asyncio

#: Matches docker-compose.yml's `minio` service `container_name` — used only by the
#: restart/persistence test below.
_MINIO_CONTAINER_NAME = "hrms-minio"


def _s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        config=Config(signature_version="s3v4"),
    )


def _object_exists(bucket: str, key: str) -> bool:
    try:
        _s3_client().head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise
    else:
        return True


def _cleanup(*, bucket: str, key: str) -> None:
    try:
        _s3_client().delete_object(Bucket=bucket, Key=key)
    except ClientError:
        pass


def _minio_container_available() -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", _MINIO_CONTAINER_NAME],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


async def test_put_get_delete_round_trip() -> None:
    settings = get_settings()
    service = DocumentStorageService(settings)
    key = f"test-storage/{uuid.uuid4()}.txt"
    body = b"upload-security-batch-a-round-trip"

    try:
        await service.put_object(key=key, body=body, content_type="text/plain")
        assert _object_exists(settings.s3_bucket_documents, key)

        fetched = await service.get_object(key=key)
        assert fetched == body

        await service.delete_object(key=key)
        assert not _object_exists(settings.s3_bucket_documents, key)
    finally:
        _cleanup(bucket=settings.s3_bucket_documents, key=key)


async def test_presigned_get_url_is_independently_fetchable() -> None:
    """The presigned URL is handed to `httpx`/`requests` here rather than to a browser, but the
    point is the same as Phase 6's requirement: the signed URL must be independently usable
    without any HRMS-side authorization check, by whoever holds it, until it expires."""
    import httpx

    settings = get_settings()
    service = DocumentStorageService(settings)
    key = f"test-storage/{uuid.uuid4()}.txt"
    body = b"presigned-url-content"

    try:
        await service.put_object(key=key, body=body, content_type="text/plain")
        url = await service.presigned_get_url(key=key, expires_in=60)
        assert url.startswith("http")

        async with httpx.AsyncClient() as client:
            response = await client.get(url)
        assert response.status_code == 200
        assert response.content == body
    finally:
        _cleanup(bucket=settings.s3_bucket_documents, key=key)


async def test_get_object_raises_for_a_missing_key() -> None:
    settings = get_settings()
    service = DocumentStorageService(settings)
    key = f"test-storage/does-not-exist-{uuid.uuid4()}.txt"

    with pytest.raises(Exception):  # noqa: B017, PT011 — botocore's own ClientError, not ours
        await service.get_object(key=key)


async def test_put_object_fails_closed_against_an_invalid_endpoint() -> None:
    """Phase 8 — an invalid/unreachable endpoint must raise (and, via the global exception
    handler already registered in `hrms.core.errors.handlers`, surface to callers as a generic
    500 rather than leaking this endpoint/credential detail) instead of silently succeeding or
    falling back to any other endpoint, AWS included."""
    settings = get_settings()
    broken_settings = settings.model_copy(
        update={"s3_endpoint_url": "http://127.0.0.1:1"}  # nothing listens here
    )
    service = DocumentStorageService(broken_settings)

    with pytest.raises(Exception):  # noqa: B017, PT011 — a connection error, not ours to narrow
        await service.put_object(key="unreachable", body=b"x", content_type="text/plain")


@pytest.mark.skipif(
    not _minio_container_available(),
    reason=f"docker CLI or the '{_MINIO_CONTAINER_NAME}' container is not reachable here",
)
async def test_object_survives_a_minio_container_restart() -> None:
    """Phase 4/9 — proves the `minio_data` named Docker volume (docker-compose.yml), not the
    container's own writable layer, is what actually holds uploaded documents: an object written
    before a `docker restart` of the MinIO container must still be readable after it comes back
    up, with no re-upload."""
    settings = get_settings()
    service = DocumentStorageService(settings)
    key = f"test-storage/restart-persistence-{uuid.uuid4()}.txt"
    body = b"still-here-after-a-restart"

    try:
        await service.put_object(key=key, body=body, content_type="text/plain")
        assert _object_exists(settings.s3_bucket_documents, key)

        subprocess.run(
            ["docker", "restart", "--time", "10", _MINIO_CONTAINER_NAME],
            check=True,
            capture_output=True,
            timeout=60,
        )

        _wait_for_minio_ready()

        assert _object_exists(settings.s3_bucket_documents, key)
        fetched = await service.get_object(key=key)
        assert fetched == body
    finally:
        _cleanup(bucket=settings.s3_bucket_documents, key=key)


def _wait_for_minio_ready(*, timeout_seconds: float = 30.0) -> None:
    import time

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            _s3_client().list_buckets()
        except Exception as exc:  # noqa: BLE001 — retrying until MinIO answers or we time out
            last_error = exc
            time.sleep(1)
        else:
            return
    raise TimeoutError(
        f"MinIO did not become reachable within {timeout_seconds}s after restart"
    ) from last_error
