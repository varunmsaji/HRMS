"""DATA-01 — typed, fail-closed errors for the envelope-encryption path
(`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §5.5/§11). Every message here is
reviewed to never include plaintext, ciphertext, key material, or ARNs — only field/table names,
key versions (metadata, not secret, §2.3 of the plan), and identifiers."""

from hrms.core.errors.base import AppError


class EncryptionUnavailableError(AppError):
    """KMS/DEK resolution failed on a write — the write must fail closed rather than silently
    persist plaintext or skip encryption (plan §5.5)."""

    code = "ENCRYPTION_UNAVAILABLE"
    status_code = 503


class DecryptionUnavailableError(AppError):
    """KMS/DEK resolution failed on a read — this field's value is temporarily unreadable; must
    not take down the rest of the response (plan §5.5)."""

    code = "DECRYPTION_UNAVAILABLE"
    status_code = 503


class DecryptionFailedError(AppError):
    """AES-GCM authentication failed (tampered ciphertext, wrong AAD, or ciphertext copied from a
    different record/field/key-version, plan §2.4) — never returns partial or corrupted
    plaintext."""

    code = "DECRYPTION_FAILED"
    status_code = 500


class MalformedCiphertextError(AppError):
    """A stored value does not match the `v1:<key_version>:<nonce>:<ciphertext>` shape at all
    (plan §2.3) — rejected before any cryptographic operation is attempted."""

    code = "MALFORMED_CIPHERTEXT"
    status_code = 500


class UnknownKeyVersionError(AppError):
    """A ciphertext's `key_version` has no matching `encryption_keys` row — never falls back to
    "use the current key instead" (plan §2.2)."""

    code = "UNKNOWN_KEY_VERSION"
    status_code = 500


class NoActiveEncryptionKeyError(AppError):
    """Zero (or more than one) `ACTIVE` row exists in `encryption_keys` — a data-integrity fault,
    not a normal "just provision one" condition (plan §2.2)."""

    code = "NO_ACTIVE_ENCRYPTION_KEY"
    status_code = 503
