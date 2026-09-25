"""RELEASE_HARDENING_PHASE_3A — local application-key DEK wrapping, replacing this module's
previous AWS KMS dependency (`hrms.core.crypto.kms`, removed by this change).

The Phase 3A audit found AWS KMS was a hard, enforced boot-time dependency for every
non-development environment (`Settings._guard_non_development_config`, `app.py`'s
`lifespan()`), directly contradicting this deployment's cost-constrained, self-hosted
architecture (Hostinger VPS, no AWS-managed services —
docs/audits/RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md §9). Since no real production
ciphertext existed at the time of this change (confirmed in that report), moving the
DEK-wrapping mechanism now is a zero-data-migration change: envelope encryption only needs
*something* to wrap/unwrap the 32-byte DEK, and the DEK itself is the only key `field.py`'s
AES-256-GCM primitive ever uses to encrypt/decrypt a PII field — that primitive, and every
existing field ciphertext, is completely unaffected by this file.

The wrapping key is derived (SHA-256, the same derivation `keys.derive_dev_dek` already used for
the development-only path) from `Settings.pii_master_key` — a required, boot-validated
application secret with the same guard shape as the JWT signing secrets, never AWS KMS, never
logged, never returned via any API response. Wrapping is AES-256-GCM with a fixed, non-secret
AAD, so a wrapped DEK can never be silently accepted under a different master key — a mismatch
fails authentication exactly like `field.py`'s own AAD check.
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from hrms.core.config.settings import Settings

_WRAP_AAD = b"hrms-dek-wrap:v1"
_NONCE_LENGTH_BYTES = 12
_DEK_LENGTH_BYTES = 32


def derive_wrapping_key(secret: str) -> bytes:
    """SHA-256 of the configured secret, so any length input yields a valid 32-byte AES-256 key
    deterministically — same shape as `keys.derive_dev_dek`, applied to `pii_master_key`."""
    return hashlib.sha256(secret.encode("utf-8")).digest()


def fingerprint(secret: str) -> str:
    """A short, non-secret identifier for *which* master key wrapped a given DEK — safe to store
    in `encryption_keys.wrapping_key_id` (a one-way hash reveals nothing about the secret) and
    useful if this deployment ever needs to detect a master-key rotation later."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


class MasterKeyService:
    """Mirrors the previous `KmsKeyService`'s shape (constructed from `Settings`, async
    `generate_data_key`/`decrypt_wrapped_dek` methods) so `DekCache`/`provisioning.py` needed
    only their call sites updated, not their control flow. `async` on the methods below is kept
    only for that call-shape parity — there is no actual I/O here anymore."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._key: bytes | None = None

    def _master_key(self) -> bytes:
        if self._key is None:
            secret = (
                self._settings.dev_encryption_key
                if self._settings.is_development
                else self._settings.pii_master_key
            )
            self._key = derive_wrapping_key(secret)
        return self._key

    async def generate_data_key(self) -> tuple[bytes, str]:
        """Mints a fresh 32-byte DEK and wraps it under the current master key. Called only at
        initial provisioning or rotation (plan §10.2) — never per field operation."""
        plaintext_dek = os.urandom(_DEK_LENGTH_BYTES)
        wrapped = self._wrap(plaintext_dek)
        return plaintext_dek, wrapped

    def _wrap(self, plaintext_dek: bytes) -> str:
        nonce = os.urandom(_NONCE_LENGTH_BYTES)
        aesgcm = AESGCM(self._master_key())
        ciphertext_and_tag = aesgcm.encrypt(nonce, plaintext_dek, _WRAP_AAD)
        return (
            f"{base64.b64encode(nonce).decode('ascii')}:"
            f"{base64.b64encode(ciphertext_and_tag).decode('ascii')}"
        )

    async def decrypt_wrapped_dek(self, *, wrapped_dek_base64: str) -> bytes:
        """Unwraps a `wrapped_dek` back into its plaintext DEK. Callers (`DekCache`) already wrap
        every call to this in a broad `except Exception` that fails closed (plan §5.5) — malformed
        input or a mismatched master key are both allowed to raise their natural exception type
        rather than this method inventing its own."""
        nonce_b64, ciphertext_b64 = wrapped_dek_base64.split(":")
        nonce = base64.b64decode(nonce_b64)
        ciphertext_and_tag = base64.b64decode(ciphertext_b64)
        aesgcm = AESGCM(self._master_key())
        return aesgcm.decrypt(nonce, ciphertext_and_tag, _WRAP_AAD)
