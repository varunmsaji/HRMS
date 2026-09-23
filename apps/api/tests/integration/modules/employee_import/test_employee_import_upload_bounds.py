"""Integration tests for Upload Security Batch B (SEC-03/SEC-04,
docs/audits/UPLOAD_BATCH_B_FILE_VALIDATION.md) against the real `/v1/employee-imports` upload
endpoint and real local MinIO — the size-boundary and safe-object-key behaviour shared with the
onboarding document upload path (`test_onboarding_upload_bounds.py`), scoped here to what
actually applies to a CSV-only, authenticated upload (no MIME/magic-byte sniffing — see
docs/audits/UPLOAD_BATCH_B_FILE_VALIDATION.md §Known Remaining Findings for why)."""


import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from httpx import AsyncClient

from hrms.core.config.settings import get_settings
from hrms.modules.employee_import.schemas import MAX_IMPORT_FILE_SIZE_BYTES

from ..employee.test_employee_assignment import _setup_org_structure
from ..organisation.test_registration_flow import _cleanup
from .test_employee_import import (
    CSV_HEADER,
    _cleanup_import_tables,
    _cleanup_org_structure,
    _register_tenant,
)

pytestmark = pytest.mark.asyncio


def _s3_object_exists(bucket: str, key: str) -> bool:
    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        config=Config(signature_version="s3v4"),
    )
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise
    else:
        return True


async def test_below_maximum_reaches_business_validation_not_a_size_rejection(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    csv_bytes = (CSV_HEADER + "\n").encode()
    try:
        response = await client.post(
            "/v1/employee-imports",
            headers=headers,
            files={"file": ("employees.csv", csv_bytes, "text/csv")},
        )
        # Empty (header-only) CSV is rejected for having no data rows — proves the request made
        # it all the way through the size guard to the existing business validation, not a
        # false-positive size rejection.
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "IMPORT_FILE_EMPTY"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_one_byte_above_the_asgi_middleware_ceiling_is_rejected_with_413(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        oversized = (CSV_HEADER + "\n").encode() + b"0" * (
            MAX_IMPORT_FILE_SIZE_BYTES + 2 * 1024 * 1024
        )
        response = await client.post(
            "/v1/employee-imports",
            headers=headers,
            files={"file": ("employees.csv", oversized, "text/csv")},
        )
        assert response.status_code == 413, response.text
        assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_over_the_business_limit_but_under_the_asgi_ceiling_gets_the_specific_error(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        over_business_limit = (CSV_HEADER + "\n").encode() + b"0" * (
            MAX_IMPORT_FILE_SIZE_BYTES + 1024
        )
        response = await client.post(
            "/v1/employee-imports",
            headers=headers,
            files={"file": ("employees.csv", over_business_limit, "text/csv")},
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "IMPORT_FILE_TOO_LARGE"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_object_key_ignores_the_client_supplied_filename(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    org = await _setup_org_structure(client, headers)
    csv_bytes = (
        CSV_HEADER + "\n"
        ",Ravi,,Kumar,1995-06-12,MALE,,,Indian,ravi@example.com,9876500001,"
        f"{org['legal_entity']['name']},{org['branch']['name']},{org['department']['name']},"
        f"{org['designation']['title']},,,OFFICE,2026-09-15,120000000,inr\n"
    ).encode()
    try:
        response = await client.post(
            "/v1/employee-imports",
            headers=headers,
            files={"file": ("../../../etc/passwd.csv", csv_bytes, "text/csv")},
        )
        assert response.status_code == 201, response.text
        batch = response.json()["data"]
        assert batch["original_filename"] == "../../../etc/passwd.csv"

        settings = get_settings()
        safe_key = f"employee-imports/{company_id}/{batch['id']}/import.csv"
        assert _s3_object_exists(settings.s3_bucket_documents, safe_key)
    finally:
        await _cleanup_import_tables(company_id=company_id)
        await _cleanup_org_structure(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
