"""Integration tests for Upload Security Batch C — the public onboarding document-upload
endpoint's rate limiter (SEC-03, docs/audits/UPLOAD_BATCH_C_RATE_LIMITING.md).

`OnboardingUploadRateLimitMiddleware` is ASGI-level, not a `Depends()` (see its docstring in
`hrms.shared.rate_limit` for why), so these tests exercise it through the real mounted route —
there is no per-route dependency object to unit-test in isolation the way
`tests/integration/modules/organisation/test_registration_rate_limit.py` does.

Configured limits (`app.py`): 30 requests/60s per client IP, 10 requests/60s per onboarding
token — both this batch's own engineering decision (§4/§6 of the report), not a documented
product requirement.
"""

from uuid import UUID

import boto3
import pytest
import redis.asyncio as redis
from botocore.config import Config
from entrypoints.api import app
from httpx import ASGITransport, AsyncClient

from hrms.core.config.settings import get_settings

from .test_onboarding_case import _register_tenant
from .test_onboarding_documents import _create_case, _teardown_with_tokens
from .test_onboarding_public import _issue_token

pytestmark = pytest.mark.asyncio

_REAL_PDF = b"%PDF-1.4\n" + b"0" * 100


async def _upload(client: AsyncClient, token: str, *, document_type: str = "OTHER"):
    return await client.post(
        f"/v1/public/onboarding/{token}/documents",
        data={"document_type": document_type},
        files={"file": ("doc.pdf", _REAL_PDF, "application/pdf")},
    )


def _s3_object_count(prefix: str) -> int:
    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        config=Config(signature_version="s3v4"),
    )
    response = client.list_objects_v2(Bucket=settings.s3_bucket_documents, Prefix=prefix)
    return int(response.get("KeyCount", 0))


class TestTokenBucket:
    async def test_below_token_limit_all_succeed(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            for _ in range(10):
                response = await _upload(client, token)
                assert response.status_code == 201, response.text
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)

    async def test_one_request_past_the_token_limit_is_429(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            responses = [await _upload(client, token) for _ in range(11)]
            assert all(r.status_code == 201 for r in responses[:10])
            assert responses[10].status_code == 429
            assert responses[10].json()["error"]["code"] == "RATE_LIMITED"
            assert responses[10].headers.get("retry-after") is not None
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)

    async def test_no_minio_object_or_document_row_created_for_the_rejected_upload(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            case_id = UUID(case["id"])
            token = await _issue_token(company_id=company_id, case_id=case_id)
            for _ in range(10):
                assert (await _upload(client, token)).status_code == 201
            prefix = f"onboarding/{company_id}/{case_id}/"
            count_before = _s3_object_count(prefix)

            rejected = await _upload(client, token)
            assert rejected.status_code == 429

            list_response = await client.get(
                f"/v1/public/onboarding/{token}/documents"
            )
            assert list_response.status_code == 200
            assert len(list_response.json()["data"]) == 10
            assert _s3_object_count(prefix) == count_before
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)

    async def test_token_bucket_recovers_after_the_window_expires(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            redis_client = redis.from_url(get_settings().redis_url, decode_responses=True)
            try:
                for _ in range(10):
                    assert (await _upload(client, token)).status_code == 201
                assert (await _upload(client, token)).status_code == 429
                # Force the window to have already elapsed rather than sleeping 60s in a test.
                async for key in redis_client.scan_iter(match="ratelimit:onboarding_upload:*"):
                    await redis_client.delete(key)
            finally:
                await redis_client.aclose()
            assert (await _upload(client, token)).status_code == 201
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)

    async def test_same_token_hammered_from_many_ips_is_still_rate_limited(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        """The anti-botnet case (§5 of the report): one onboarding case's token bucket must trip
        even when each individual request comes from a different source IP — an IP-only limiter
        would let this through."""
        headers, company_id, user_id = await _register_tenant(client)
        try:
            case = await _create_case(client, headers)
            token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
            responses = []
            for i in range(11):
                transport = ASGITransport(app=app, client=(f"10.50.0.{i + 1}", 1))
                async with AsyncClient(transport=transport, base_url="http://test") as scoped:
                    responses.append(await _upload(scoped, token))
            assert all(r.status_code == 201 for r in responses[:10])
            assert responses[10].status_code == 429
        finally:
            await _teardown_with_tokens(company_id=company_id, user_id=user_id)


class TestIpBucket:
    async def test_one_ip_spraying_garbage_tokens_is_rate_limited(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        """An attacker who never resolves a real token (so no case/company exists to key on)
        must still be bounded by the IP bucket alone."""
        responses = [await _upload(client, f"not-a-real-token-{i}") for i in range(31)]
        assert all(r.status_code == 404 for r in responses[:30])
        assert responses[30].status_code == 429
        assert responses[30].json()["error"]["code"] == "RATE_LIMITED"

    async def test_different_ips_get_independent_ip_buckets(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        # A distinct garbage token per request so only the IP bucket (limit 30), never the
        # token bucket (limit 10), is what this test exercises.
        transport_a = ASGITransport(app=app, client=("10.60.0.1", 1))
        transport_b = ASGITransport(app=app, client=("10.60.0.2", 1))
        async with AsyncClient(transport=transport_a, base_url="http://test") as client_a:
            responses_a = [await _upload(client_a, f"bad-token-a-{i}") for i in range(30)]
        async with AsyncClient(transport=transport_b, base_url="http://test") as client_b:
            response_b = await _upload(client_b, "bad-token-b-0")
        assert all(r.status_code == 404 for r in responses_a)
        assert response_b.status_code == 404  # not 429 — a fresh IP has its own untouched bucket


class TestMultiTenantIsolation:
    async def test_two_customers_uploading_concurrently_do_not_share_the_token_bucket(
        self, client: AsyncClient, seeded_plan_catalogue: None
    ) -> None:
        headers_a, company_a, user_a = await _register_tenant(client)
        headers_b, company_b, user_b = await _register_tenant(client)
        try:
            case_a = await _create_case(client, headers_a)
            case_b = await _create_case(client, headers_b)
            token_a = await _issue_token(company_id=company_a, case_id=UUID(case_a["id"]))
            token_b = await _issue_token(company_id=company_b, case_id=UUID(case_b["id"]))

            transport_a = ASGITransport(app=app, client=("10.70.0.1", 1))
            transport_b = ASGITransport(app=app, client=("10.70.0.2", 1))

            async with AsyncClient(transport=transport_a, base_url="http://test") as client_a:
                responses_a = [await _upload(client_a, token_a) for _ in range(10)]
            assert all(r.status_code == 201 for r in responses_a)

            # Customer B, different IP and token, is unaffected by A's exhausted token bucket.
            async with AsyncClient(transport=transport_b, base_url="http://test") as client_b:
                response_b = await _upload(client_b, token_b)
            assert response_b.status_code == 201
        finally:
            await _teardown_with_tokens(company_id=company_a, user_id=user_a)
            await _teardown_with_tokens(company_id=company_b, user_id=user_b)
