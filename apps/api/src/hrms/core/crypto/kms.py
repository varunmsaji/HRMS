"""DATA-01 — thin AWS KMS wrapper (`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md`
§2.1/§5). Mirrors `core.storage.DocumentStorageService`'s exact shape (a thin class constructed
from `Settings`, a fresh `aioboto3` session/client per call — no new AWS-SDK usage pattern
introduced).

Called only to wrap/unwrap a DEK (`GenerateDataKey`/`Decrypt`), never with field plaintext —
that is the entire point of envelope encryption (plan §2.1): KMS never sees a PAN, Aadhaar, or
bank-account value."""

import base64

import aioboto3

from hrms.core.config.settings import Settings


class KmsKeyService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _client_kwargs(self) -> dict[str, str | None]:
        return {
            "aws_access_key_id": self._settings.aws_access_key_id or None,
            "aws_secret_access_key": self._settings.aws_secret_access_key or None,
            "region_name": self._settings.aws_region,
        }

    async def generate_data_key(self, *, key_arn: str) -> tuple[bytes, str]:
        """Establishes a new DEK. Returns `(plaintext_dek, wrapped_dek_base64)`. Called only at
        initial provisioning or rotation (plan §10.2) — never per field operation."""
        session = aioboto3.Session()
        async with session.client("kms", **self._client_kwargs()) as kms:
            response = await kms.generate_data_key(KeyId=key_arn, KeySpec="AES_256")
            plaintext_dek: bytes = response["Plaintext"]
            wrapped: bytes = response["CiphertextBlob"]
            return plaintext_dek, base64.b64encode(wrapped).decode("ascii")

    async def decrypt_wrapped_dek(self, *, key_arn: str, wrapped_dek_base64: str) -> bytes:
        """Unwraps a `wrapped_dek` back into its plaintext DEK. Called at most once per
        `key_version` per process per DEK-cache TTL window (plan §2.1) — not per field
        operation."""
        session = aioboto3.Session()
        async with session.client("kms", **self._client_kwargs()) as kms:
            response = await kms.decrypt(
                KeyId=key_arn,
                CiphertextBlob=base64.b64decode(wrapped_dek_base64),
            )
            plaintext_dek: bytes = response["Plaintext"]
            return plaintext_dek
