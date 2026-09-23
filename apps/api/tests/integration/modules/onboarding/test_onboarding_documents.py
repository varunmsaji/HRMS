"""Integration tests for the Onboarding module's O5 slice — document upload/list/delete
(public, token-authenticated) and document list/review (admin, `ONBOARDING.VIEW`/
`ONBOARDING.REVIEW`).

Runs against the real local MinIO container (docker-compose.yml `minio` service) — no mocking
of `DocumentStorageService`, since the whole point of this slice is that document bytes actually
round-trip through S3-compatible storage and back out via a presigned URL (plan §8.3)."""

from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import boto3
import httpx
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory

from .test_onboarding_case import (
    _case_payload,
    _cleanup_scoped_users,
    _create_permission_scoped_user,
    _register_tenant,
    _teardown,
)
from .test_onboarding_public import _cleanup_tokens, _issue_token

pytestmark = pytest.mark.asyncio

# SEC-04 (docs/audits/UPLOAD_BATCH_B_FILE_VALIDATION.md) — upload now classifies content from its
# own magic bytes rather than the caller-supplied `Content-Type`/filename, so any fixture meant to
# be *accepted* must start with a real signature `sniff_document_content_type` recognizes. The
# rest of the payload is still arbitrary — sniffing only inspects the prefix.
_JPEG_BYTES = b"\xff\xd8\xff" + b"fake-image-bytes"
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes"


async def _create_case(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/onboarding-cases", headers=headers, json=_case_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _cleanup_documents(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM onboarding_document WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.commit()


async def _teardown_with_tokens(*, company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_documents(company_id=company_id)
    await _cleanup_tokens(company_id=company_id)
    await _teardown(company_id=company_id, user_id=user_id)


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


def _s3_object_exists(bucket: str, key: str) -> bool:
    try:
        _s3_client().head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise
    else:
        return True


async def test_upload_document_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        response = await client.post(
            f"/v1/public/onboarding/{token}/documents",
            data={"document_type": "PAN"},
            files={"file": ("pan.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert data["document_type"] == "PAN"
        assert data["status"] == "PENDING"
        assert data["original_filename"] == "pan.jpg"
        assert data["content_type"] == "image/jpeg"
        assert data["size_bytes"] == len(_JPEG_BYTES)
        assert "s3_key" not in data
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_upload_invalid_document_type_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        response = await client.post(
            f"/v1/public/onboarding/{token}/documents",
            data={"document_type": "NOT_A_REAL_TYPE"},
            files={"file": ("x.jpg", b"data", "image/jpeg")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_DOCUMENT_TYPE"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_upload_too_large_rejected(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "hrms.modules.onboarding.service.ONBOARDING_DOCUMENT_MAX_SIZE_BYTES", 10
    )
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        response = await client.post(
            f"/v1/public/onboarding/{token}/documents",
            data={"document_type": "PAN"},
            files={"file": ("pan.jpg", b"this-is-more-than-ten-bytes", "image/jpeg")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "DOCUMENT_TOO_LARGE"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_upload_rejected_when_case_not_writable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from .test_onboarding_invite import _force_status

    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        await _force_status(case_id=UUID(case["id"]), status="SUBMITTED")

        response = await client.post(
            f"/v1/public/onboarding/{token}/documents",
            data={"document_type": "PAN"},
            files={"file": ("pan.jpg", b"data", "image/jpeg")},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ONBOARDING_SECTION_NOT_WRITABLE"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_list_and_delete_document_public(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    settings = get_settings()
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        upload = await client.post(
            f"/v1/public/onboarding/{token}/documents",
            data={"document_type": "AADHAAR"},
            files={"file": ("aadhaar.png", _PNG_BYTES, "image/png")},
        )
        assert upload.status_code == 201
        document_id = upload.json()["data"]["id"]

        list_response = await client.get(f"/v1/public/onboarding/{token}/documents")
        assert list_response.status_code == 200
        assert [d["id"] for d in list_response.json()["data"]] == [document_id]

        admin_docs = (
            await client.get(f"/v1/onboarding-cases/{case['id']}/documents", headers=headers)
        ).json()["data"]
        # SEC-04 — the object key's filename component is always this fixed, server-chosen
        # literal (never the client-supplied "aadhaar.png"); `original_filename` in the API
        # response is still the display name, unaffected.
        s3_key = f"onboarding/{company_id}/{case['id']}/{document_id}/document.png"
        assert _s3_object_exists(settings.s3_bucket_documents, s3_key)
        assert len(admin_docs) == 1
        assert admin_docs[0]["original_filename"] == "aadhaar.png"

        delete_response = await client.delete(
            f"/v1/public/onboarding/{token}/documents/{document_id}"
        )
        assert delete_response.status_code == 200

        empty_list = await client.get(f"/v1/public/onboarding/{token}/documents")
        assert empty_list.json()["data"] == []
        assert not _s3_object_exists(settings.s3_bucket_documents, s3_key)
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_admin_list_documents_has_download_url(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        await client.post(
            f"/v1/public/onboarding/{token}/documents",
            data={"document_type": "PHOTO"},
            files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        )

        response = await client.get(
            f"/v1/onboarding-cases/{case['id']}/documents", headers=headers
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["download_url"].startswith("http")
        assert "s3_key" not in data[0]

        # SEC-04 — the presigned URL itself carries a `response-content-disposition` override
        # forcing an attachment download (real MinIO honours it, verified below), independent of
        # what's stored as the object's own Content-Type/Content-Disposition.
        parsed = urlparse(data[0]["download_url"])
        query = parse_qs(parsed.query)
        assert query["response-content-disposition"] == ['attachment; filename="photo.jpg"']

        async with httpx.AsyncClient() as raw_client:
            download = await raw_client.get(data[0]["download_url"])
        assert download.status_code == 200
        assert download.headers["content-disposition"] == 'attachment; filename="photo.jpg"'
        assert download.content == _JPEG_BYTES
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_review_document_verified(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        upload = await client.post(
            f"/v1/public/onboarding/{token}/documents",
            data={"document_type": "PHOTO"},
            files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        document_id = upload.json()["data"]["id"]

        response = await client.post(
            f"/v1/onboarding-cases/{case['id']}/documents/{document_id}/review",
            headers=headers,
            json={"status": "VERIFIED"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "VERIFIED"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_review_document_rejected_requires_reason(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        upload = await client.post(
            f"/v1/public/onboarding/{token}/documents",
            data={"document_type": "PHOTO"},
            files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        document_id = upload.json()["data"]["id"]

        response = await client.post(
            f"/v1/onboarding-cases/{case['id']}/documents/{document_id}/review",
            headers=headers,
            json={"status": "REJECTED"},
        )
        assert response.status_code == 422

        with_reason = await client.post(
            f"/v1/onboarding-cases/{case['id']}/documents/{document_id}/review",
            headers=headers,
            json={"status": "REJECTED", "rejection_reason": "Blurry photo"},
        )
        assert with_reason.status_code == 200
        assert with_reason.json()["data"]["status"] == "REJECTED"
        assert with_reason.json()["data"]["rejection_reason"] == "Blurry photo"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_review_document_without_review_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.onboarding.permissions import ONBOARDING_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        upload = await client.post(
            f"/v1/public/onboarding/{token}/documents",
            data={"document_type": "PHOTO"},
            files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        document_id = upload.json()["data"]["id"]

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[ONBOARDING_VIEW]
        )
        response = await client.post(
            f"/v1/onboarding-cases/{case['id']}/documents/{document_id}/review",
            headers=scoped_headers,
            json={"status": "VERIFIED"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_admin_documents_cross_tenant_isolation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_id_a, user_id_a = await _register_tenant(client)
    headers_b, company_id_b, user_id_b = await _register_tenant(client)
    try:
        case_a = await _create_case(client, headers_a)
        token_a = await _issue_token(company_id=company_id_a, case_id=UUID(case_a["id"]))
        await client.post(
            f"/v1/public/onboarding/{token_a}/documents",
            data={"document_type": "PHOTO"},
            files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        )

        response = await client.get(
            f"/v1/onboarding-cases/{case_a['id']}/documents", headers=headers_b
        )
        assert response.status_code == 404
    finally:
        await _teardown_with_tokens(company_id=company_id_a, user_id=user_id_a)
        await _teardown_with_tokens(company_id=company_id_b, user_id=user_id_b)
