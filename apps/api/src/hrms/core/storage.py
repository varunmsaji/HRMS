"""Thin S3 wrapper — first built for onboarding document upload (O5, plan §8.3) as
`modules/onboarding/document_storage.py`, moved here once a second consumer
(`modules/employee_import`, bulk employee CSV import) needed the same S3 client wiring —
`hrms.core` may be depended on by every module (`apps/api/.importlinter`), a domain module may
not depend on another domain module's internals. Uses `aioboto3` (already a pinned dependency,
already used by `email_sender.SesEmailSender`), against
`Settings.s3_bucket_documents`/`aws_region`/`aws_access_key_id`/`aws_secret_access_key`/
`s3_endpoint_url`.

Onboarding document bytes never round-trip through the API server for the admin review UI — only
a short-lived presigned GET URL does (plan §8.3), so `presigned_get_url` remains the only
onboarding-facing read path. `get_object` was added for employee_import's Celery task, which has
no browser to hand a presigned URL to and needs the raw CSV bytes server-side to parse."""

import aioboto3

from hrms.core.config.settings import Settings


class DocumentStorageService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _client_kwargs(self) -> dict[str, str | None]:
        return {
            "endpoint_url": self._settings.s3_endpoint_url,
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

    async def presigned_get_url(self, *, key: str, expires_in: int = 300) -> str:
        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._settings.s3_bucket_documents, "Key": key},
                ExpiresIn=expires_in,
            )
            return url
