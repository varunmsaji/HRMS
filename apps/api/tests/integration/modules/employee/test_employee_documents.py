"""Integration tests for the Employee Document module (post-onboarding document management) —
`/v1/employees/{employee_id}/documents*`.

Mirrors `tests/integration/modules/onboarding/test_onboarding_documents.py`'s coverage shape
(upload/list/delete/review against real local MinIO, no mocking of `DocumentStorageService`) for
this module's own, independent `employee_document` table. The onboarding-activation migration
path itself (`EmployeeDocumentService.migrate_from_onboarding`) is covered separately, in
`tests/integration/modules/onboarding/test_onboarding_activation.py`."""

from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import boto3
import httpx
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.auth.jwt import create_access_token
from hrms.core.auth.passwords import hash_password
from hrms.core.config.settings import get_settings
from hrms.core.db.models.identity import (
    Permission,
    Role,
    RolePermission,
    Session,
    User,
    UserCompany,
    UserRole,
)
from hrms.core.db.session import get_session_factory
from hrms.modules.employee.permissions import EMPLOYEE_VIEW_DOCUMENTS
from hrms.modules.identity.permissions import EMPLOYEE_VIEW

from ..organisation.test_registration_flow import _cleanup, _register

pytestmark = pytest.mark.asyncio

# Same SEC-04 posture as the onboarding equivalent — any fixture meant to be *accepted* must
# start with a real signature `sniff_document_content_type` recognizes.
_JPEG_BYTES = b"\xff\xd8\xff" + b"fake-image-bytes"
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes"


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201
    assert company_id is not None
    data = response.json()["data"]
    return (
        {
            "Authorization": f"Bearer {data['access_token']}",
            "X-Company-Id": str(company_id),
        },
        company_id,
        user_id,
    )


async def _create_employee(
    client: AsyncClient, headers: dict[str, str], first_name: str = "Nisha", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/employees", headers=headers, json={"first_name": first_name, **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_scoped_actor(
    *,
    company_id: UUID,
    grants: list[tuple[str, str]],
    employee_id: UUID | None,
) -> tuple[dict[str, str], UUID]:
    """One role granting the listed `(permission_code, data_scope)` pairs — mirrors
    `test_employee_data_scope.py::_create_scoped_actor`'s single-role shape, the established
    pattern for a non-default-role test actor in this module."""
    factory = get_session_factory()
    from datetime import UTC, datetime, timedelta

    async with factory() as session:
        now = datetime.now(UTC)
        user_id = uuid4()
        session.add(
            User(
                id=user_id,
                email=f"actor-{user_id.hex[:8]}@example.com",
                password_hash=hash_password("CorrectHorse9"),
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()

        user_company = UserCompany(
            id=uuid4(),
            user_id=user_id,
            company_id=company_id,
            is_primary=True,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(user_company)
        await session.flush()

        role_id = uuid4()
        session.add(
            Role(
                id=role_id,
                company_id=company_id,
                code=f"TEST_SCOPED_ROLE_{role_id.hex[:8]}",
                name="Test scoped role",
                is_system=False,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        for code, data_scope in grants:
            permission = (
                await session.execute(select(Permission).where(Permission.code == code))
            ).scalar_one()
            session.add(
                RolePermission(role_id=role_id, permission_id=permission.id, data_scope=data_scope)
            )
        await session.flush()
        session.add(UserRole(id=uuid4(), user_company_id=user_company.id, role_id=role_id))

        session_id = uuid4()
        session.add(
            Session(
                id=session_id,
                user_id=user_id,
                company_id=company_id,
                expires_at=now + timedelta(days=1),
            )
        )
        await session.commit()

    token = create_access_token(
        user_id=user_id, company_id=company_id, session_id=session_id, employee_id=employee_id
    )
    headers = {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}
    return headers, user_id


async def _cleanup_documents(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employee_document WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _cleanup_employees(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM number_series WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _teardown(*, company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_documents(company_id=company_id)
    await _cleanup_employees(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


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
        employee = await _create_employee(client, headers)

        response = await client.post(
            f"/v1/employees/{employee['id']}/documents",
            headers=headers,
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
        assert data["employee_id"] == employee["id"]
        assert "s3_key" not in data
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_upload_invalid_document_type_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.post(
            f"/v1/employees/{employee['id']}/documents",
            headers=headers,
            data={"document_type": "NOT_A_REAL_TYPE"},
            files={"file": ("x.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_DOCUMENT_TYPE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_upload_too_large_rejected(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hrms.modules.employee.service.EMPLOYEE_DOCUMENT_MAX_SIZE_BYTES", 10)
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.post(
            f"/v1/employees/{employee['id']}/documents",
            headers=headers,
            data={"document_type": "PAN"},
            files={"file": ("pan.jpg", _JPEG_BYTES + b"-more-than-ten-bytes", "image/jpeg")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "DOCUMENT_TOO_LARGE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_upload_unsupported_content_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        # Claims image/jpeg via Content-Type, but the bytes don't match any allowed signature —
        # SEC-04: the client's claim is never trusted, only the sniffed magic bytes matter.
        response = await client.post(
            f"/v1/employees/{employee['id']}/documents",
            headers=headers,
            data={"document_type": "PAN"},
            files={"file": ("fake.jpg", b"<html>not a real document</html>", "image/jpeg")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "UNSUPPORTED_DOCUMENT_CONTENT"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_list_documents_has_download_url(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    settings = get_settings()
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        upload = await client.post(
            f"/v1/employees/{employee['id']}/documents",
            headers=headers,
            data={"document_type": "PHOTO"},
            files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        document_id = upload.json()["data"]["id"]

        response = await client.get(f"/v1/employees/{employee['id']}/documents", headers=headers)
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == document_id
        assert data[0]["download_url"].startswith("http")
        assert "s3_key" not in data[0]

        s3_key = f"employee/{company_id}/{employee['id']}/{document_id}/document.jpg"
        assert _s3_object_exists(settings.s3_bucket_documents, s3_key)

        parsed = urlparse(data[0]["download_url"])
        query = parse_qs(parsed.query)
        assert query["response-content-disposition"] == ['attachment; filename="photo.jpg"']

        async with httpx.AsyncClient() as raw_client:
            download = await raw_client.get(data[0]["download_url"])
        assert download.status_code == 200
        assert download.content == _JPEG_BYTES
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_delete_document_removes_row_and_s3_object(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    settings = get_settings()
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        upload = await client.post(
            f"/v1/employees/{employee['id']}/documents",
            headers=headers,
            data={"document_type": "AADHAAR"},
            files={"file": ("aadhaar.png", _PNG_BYTES, "image/png")},
        )
        document_id = upload.json()["data"]["id"]
        s3_key = f"employee/{company_id}/{employee['id']}/{document_id}/document.png"
        assert _s3_object_exists(settings.s3_bucket_documents, s3_key)

        delete_response = await client.delete(
            f"/v1/employees/{employee['id']}/documents/{document_id}", headers=headers
        )
        assert delete_response.status_code == 200, delete_response.text

        empty_list = await client.get(f"/v1/employees/{employee['id']}/documents", headers=headers)
        assert empty_list.json()["data"] == []
        assert not _s3_object_exists(settings.s3_bucket_documents, s3_key)
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_review_document_verified(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        upload = await client.post(
            f"/v1/employees/{employee['id']}/documents",
            headers=headers,
            data={"document_type": "PHOTO"},
            files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        document_id = upload.json()["data"]["id"]

        response = await client.post(
            f"/v1/employees/{employee['id']}/documents/{document_id}/review",
            headers=headers,
            json={"status": "VERIFIED"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "VERIFIED"
        assert response.json()["data"]["verified_at"] is not None

        # Audit trail.
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT action FROM audit_log WHERE entity_type = 'employee_document' "
                        "AND entity_id = :id AND action = 'EMPLOYEE_DOCUMENT_REVIEWED'"
                    ),
                    {"id": document_id},
                )
            ).first()
            assert row is not None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_review_document_rejected_requires_reason(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        upload = await client.post(
            f"/v1/employees/{employee['id']}/documents",
            headers=headers,
            data={"document_type": "PHOTO"},
            files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        document_id = upload.json()["data"]["id"]

        response = await client.post(
            f"/v1/employees/{employee['id']}/documents/{document_id}/review",
            headers=headers,
            json={"status": "REJECTED"},
        )
        assert response.status_code == 422

        with_reason = await client.post(
            f"/v1/employees/{employee['id']}/documents/{document_id}/review",
            headers=headers,
            json={"status": "REJECTED", "rejection_reason": "Blurry photo"},
        )
        assert with_reason.status_code == 200
        assert with_reason.json()["data"]["status"] == "REJECTED"
        assert with_reason.json()["data"]["rejection_reason"] == "Blurry photo"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_upload_without_update_sensitive_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        scoped_headers, _scoped_user_id = await _create_scoped_actor(
            company_id=company_id, grants=[(EMPLOYEE_VIEW, "COMPANY")], employee_id=None
        )
        response = await client.post(
            f"/v1/employees/{employee['id']}/documents",
            headers=scoped_headers,
            data={"document_type": "PAN"},
            files={"file": ("pan.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_list_without_view_documents_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        scoped_headers, _scoped_user_id = await _create_scoped_actor(
            company_id=company_id, grants=[(EMPLOYEE_VIEW, "COMPANY")], employee_id=None
        )
        response = await client.get(
            f"/v1/employees/{employee['id']}/documents", headers=scoped_headers
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_self_scoped_employee_sees_own_documents_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        own_employee = await _create_employee(client, headers, first_name="Self")
        other_employee = await _create_employee(client, headers, first_name="Other")

        await client.post(
            f"/v1/employees/{own_employee['id']}/documents",
            headers=headers,
            data={"document_type": "PHOTO"},
            files={"file": ("own.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        await client.post(
            f"/v1/employees/{other_employee['id']}/documents",
            headers=headers,
            data={"document_type": "PHOTO"},
            files={"file": ("other.jpg", _JPEG_BYTES, "image/jpeg")},
        )

        self_headers, _self_user_id = await _create_scoped_actor(
            company_id=company_id,
            grants=[(EMPLOYEE_VIEW_DOCUMENTS, "SELF")],
            employee_id=UUID(own_employee["id"]),
        )

        own_list = await client.get(
            f"/v1/employees/{own_employee['id']}/documents", headers=self_headers
        )
        assert own_list.status_code == 200
        assert len(own_list.json()["data"]) == 1

        # Out-of-scope target: 404, not 403 (same convention as every other scoped sub-resource
        # in this module — doesn't reveal the target's existence).
        other_list = await client.get(
            f"/v1/employees/{other_employee['id']}/documents", headers=self_headers
        )
        assert other_list.status_code == 404

        # A SELF-scoped caller still cannot upload/delete/review — EMPLOYEE_VIEW_DOCUMENTS alone
        # does not grant EMPLOYEE_UPDATE_SENSITIVE.
        upload_attempt = await client.post(
            f"/v1/employees/{own_employee['id']}/documents",
            headers=self_headers,
            data={"document_type": "PAN"},
            files={"file": ("pan.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        assert upload_attempt.status_code == 403
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_documents_cross_tenant_isolation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_id_a, user_id_a = await _register_tenant(client)
    headers_b, company_id_b, user_id_b = await _register_tenant(client)
    try:
        employee_a = await _create_employee(client, headers_a)
        await client.post(
            f"/v1/employees/{employee_a['id']}/documents",
            headers=headers_a,
            data={"document_type": "PHOTO"},
            files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        )

        response = await client.get(
            f"/v1/employees/{employee_a['id']}/documents", headers=headers_b
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id_a, user_id=user_id_a)
        await _teardown(company_id=company_id_b, user_id=user_id_b)


async def _revoke_company_admin_view_documents(*, company_id: UUID) -> None:
    """Simulates a company registered before `EMPLOYEE.VIEW_DOCUMENTS` existed: deletes just the
    `COMPANY_ADMIN` -> `EMPLOYEE.VIEW_DOCUMENTS` `role_permission` row this company's own
    registration would otherwise have created, same gap
    `20261014091000_employee_view_documents_backfill.py` fixes for real pre-existing tenants."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                DELETE FROM role_permission
                WHERE permission_id = (SELECT id FROM permission WHERE code = 'EMPLOYEE.VIEW_DOCUMENTS')
                  AND role_id = (
                      SELECT id FROM role WHERE company_id = :cid AND code = 'COMPANY_ADMIN'
                  )
                """
            ),
            {"cid": str(company_id)},
        )
        await session.commit()


async def _run_view_documents_backfill() -> None:
    """The exact `upgrade()` SQL of `20261014091000_employee_view_documents_backfill.py` —
    kept in sync with that migration so this test exercises the real fix, not a paraphrase."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO permission (id, code, domain, description)
                VALUES (gen_random_uuid(), 'EMPLOYEE.VIEW_DOCUMENTS', 'EMPLOYEE',
                        'View an employee''s documents')
                ON CONFLICT (code) DO NOTHING
                """
            )
        )
        await session.execute(
            text(
                """
                INSERT INTO role_permission (role_id, permission_id, data_scope)
                SELECT ca.id, p.id, 'COMPANY'
                FROM role ca
                JOIN permission p ON p.code = 'EMPLOYEE.VIEW_DOCUMENTS'
                WHERE ca.code = 'COMPANY_ADMIN' AND ca.deleted_at IS NULL
                ON CONFLICT (role_id, permission_id) DO NOTHING
                """
            )
        )
        await session.execute(
            text(
                """
                INSERT INTO role_permission (role_id, permission_id, data_scope)
                SELECT hr.id, p.id, 'COMPANY'
                FROM role hr
                JOIN permission p ON p.code = 'EMPLOYEE.VIEW_DOCUMENTS'
                WHERE hr.code = 'HR_ADMIN' AND hr.deleted_at IS NULL
                ON CONFLICT (role_id, permission_id) DO NOTHING
                """
            )
        )
        await session.execute(
            text(
                """
                INSERT INTO role_permission (role_id, permission_id, data_scope)
                SELECT emp.id, p.id, 'SELF'
                FROM role emp
                JOIN permission p ON p.code = 'EMPLOYEE.VIEW_DOCUMENTS'
                WHERE emp.code = 'EMPLOYEE' AND emp.deleted_at IS NULL
                ON CONFLICT (role_id, permission_id) DO NOTHING
                """
            )
        )
        await session.commit()


async def test_existing_company_admin_backfilled_gains_view_documents(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """TEST 1 + TEST 9 (migration idempotency) from the remediation brief: a tenant whose
    `COMPANY_ADMIN` role predates `EMPLOYEE.VIEW_DOCUMENTS` gets a 403 on `GET .../documents`
    until the backfill runs; running the backfill twice is safe and leaves no duplicate rows."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        await client.post(
            f"/v1/employees/{employee['id']}/documents",
            headers=headers,
            data={"document_type": "PHOTO"},
            files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        )

        await _revoke_company_admin_view_documents(company_id=company_id)
        before = await client.get(f"/v1/employees/{employee['id']}/documents", headers=headers)
        assert before.status_code == 403
        assert before.json()["error"]["code"] == "PERMISSION_DENIED"

        await _run_view_documents_backfill()
        after = await client.get(f"/v1/employees/{employee['id']}/documents", headers=headers)
        assert after.status_code == 200
        assert len(after.json()["data"]) == 1

        # Idempotency: running it again must not raise or create duplicate role_permission rows.
        await _run_view_documents_backfill()
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(RolePermission)
                    .join(Role, Role.id == RolePermission.role_id)
                    .join(Permission, Permission.id == RolePermission.permission_id)
                    .where(
                        Role.company_id == company_id,
                        Role.code == "COMPANY_ADMIN",
                        Permission.code == "EMPLOYEE.VIEW_DOCUMENTS",
                    )
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].data_scope == "COMPANY"

            permission_rows = (
                await session.execute(
                    select(Permission).where(Permission.code == "EMPLOYEE.VIEW_DOCUMENTS")
                )
            ).scalars().all()
            assert len(permission_rows) == 1

        still_works = await client.get(
            f"/v1/employees/{employee['id']}/documents", headers=headers
        )
        assert still_works.status_code == 200
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_hr_admin_retains_view_documents_access(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """TEST 2: HR_ADMIN (COMPANY scope, same as its own registration-time grant) can list an
    employee's documents it did not upload itself."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        await client.post(
            f"/v1/employees/{employee['id']}/documents",
            headers=headers,
            data={"document_type": "PHOTO"},
            files={"file": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        )

        hr_admin_headers, _hr_admin_user_id = await _create_scoped_actor(
            company_id=company_id,
            grants=[(EMPLOYEE_VIEW_DOCUMENTS, "COMPANY")],
            employee_id=None,
        )
        response = await client.get(
            f"/v1/employees/{employee['id']}/documents", headers=hr_admin_headers
        )
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_view_documents_permission_catalogue_has_single_row(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """TEST 10: exactly one `EMPLOYEE.VIEW_DOCUMENTS` permission row exists, regardless of how
    many tenants have registered (each registration's `get_or_create_permission` call and the
    backfill migration's `ON CONFLICT (code) DO NOTHING` both guard the same unique index)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(Permission).where(Permission.code == "EMPLOYEE.VIEW_DOCUMENTS")
                )
            ).scalars().all()
            assert len(rows) == 1
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
