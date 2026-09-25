"""Thin S3-compatible wrapper — first built for onboarding document upload (O5, plan §8.3) as
`modules/onboarding/document_storage.py`, moved here once a second consumer
(`modules/employee_import`, bulk employee CSV import) needed the same S3 client wiring —
`hrms.core` may be depended on by every module (`apps/api/.importlinter`), a domain module may
not depend on another domain module's internals. Uses `aioboto3` (a pinned dependency; this is
its only remaining consumer since RELEASE_HARDENING_PHASE_5A moved email delivery off AWS SES
onto SMTP — `aioboto3` stays pinned solely for this self-hosted MinIO S3 client, not for email),
against
`Settings.s3_bucket_documents`/`aws_region`/`aws_access_key_id`/`aws_secret_access_key`/
`s3_endpoint_url`.

The actual object store behind this client is self-hosted MinIO (docker-compose's `minio`
service in development; a VPS-internal MinIO container everywhere else), not AWS S3 — this
codebase runs on a Hostinger VPS, not AWS (docs/audits/UPLOAD_BATCH_A_STORAGE_ARCHITECTURE.md).
`Settings._guard_non_development_config` refuses to boot staging/production without an explicit
`s3_endpoint_url`/`s3_bucket_documents`/credentials set, so this client can never silently fall
back to real AWS S3 the way an unset `endpoint_url` normally would.

Onboarding document bytes never round-trip through the API server for the admin review UI — only
a short-lived presigned GET URL does (plan §8.3), so `presigned_get_url` remains the only
onboarding-facing read path. `get_object` was added for employee_import's Celery task, which has
no browser to hand a presigned URL to and needs the raw CSV bytes server-side to parse."""

import aioboto3

from hrms.core.config.settings import Settings


class DocumentStorageService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _client_kwargs(self, *, endpoint_url: str | None = None) -> dict[str, str | None]:
        resolved_endpoint = (
            endpoint_url if endpoint_url is not None else self._settings.s3_endpoint_url
        )
        return {
            "endpoint_url": resolved_endpoint,
            "aws_access_key_id": self._settings.aws_access_key_id,
            "aws_secret_access_key": self._settings.aws_secret_access_key,
            "region_name": self._settings.aws_region,
        }

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            await s3.put_object(
                Bucket=self._settings.s3_bucket_documents,
                Key=key,
                Body=body,
                ContentType=content_type,
            )

    async def get_object(self, *, key: str) -> bytes:
        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            response = await s3.get_object(Bucket=self._settings.s3_bucket_documents, Key=key)
            body: bytes = await response["Body"].read()
            return body

    async def delete_object(self, *, key: str) -> None:
        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            await s3.delete_object(Bucket=self._settings.s3_bucket_documents, Key=key)

    async def presigned_get_url(
        self,
        *,
        key: str,
        expires_in: int = 300,
        response_content_disposition: str | None = None,
    ) -> str:
        """Signed against `s3_public_endpoint_url` (falling back to `s3_endpoint_url` when unset)
        rather than the endpoint every other method uses — the URL's host is baked into its
        SigV4 signature, so it must already be the browser-reachable, Nginx-fronted hostname the
        request will actually arrive on, not the internal Docker-network address `put_object`/
        `get_object`/`delete_object` talk to
        (docs/audits/UPLOAD_BATCH_A_STORAGE_ARCHITECTURE.md).

        `response_content_disposition` (SEC-04,
        docs/audits/UPLOAD_BATCH_B_FILE_VALIDATION.md) is S3's standard `ResponseContentDisposition`
        override param — it forces the `Content-Disposition` header on the signed GET response
        itself, without needing to have set (or re-set) that header on the stored object, so a
        candidate-uploaded HTML/SVG file can never be rendered in-browser via this URL, only
        downloaded as an attachment."""
        endpoint = self._settings.s3_public_endpoint_url or self._settings.s3_endpoint_url
        params: dict[str, str] = {"Bucket": self._settings.s3_bucket_documents, "Key": key}
        if response_content_disposition is not None:
            params["ResponseContentDisposition"] = response_content_disposition
        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs(endpoint_url=endpoint)) as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=expires_in,
            )
            return url
