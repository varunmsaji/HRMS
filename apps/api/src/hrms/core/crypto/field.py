"""DATA-01 — the pure cryptographic primitive: AES-256-GCM + the versioned ciphertext format
(`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.3/§2.4/§6). Deliberately contains
no I/O (no KMS call, no DB query) — every input (the DEK bytes, the key version, the AAD string)
is already resolved by the caller (`hrms.core.crypto.service.PiiCryptoService`). This is what
keeps this module trivially unit-testable and keeps the "never call KMS per field operation"
property mechanically true: nothing in this file *can* call KMS.

Format: ``v1:<key_version>:<base64(nonce)>:<base64(ciphertext_and_tag)>``. AAD is never embedded
in this string (plan §2.4) — GCM authenticates it out-of-band; the caller must supply the same AAD
at decrypt time that it supplied at encrypt time, or authentication fails."""

import base64
import binascii
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from hrms.core.crypto.errors import DecryptionFailedError, MalformedCiphertextError

FORMAT_VERSION = "v1"
NONCE_LENGTH_BYTES = 12
DEK_LENGTH_BYTES = 32  # AES-256

_CIPHERTEXT_SHAPE = re.compile(r"^v1:\d+:")


def is_ciphertext_shaped(value: str) -> bool:
    """Plan §6.2 — the backfill's classification check: does this stored string already look
    like our ciphertext format, or is it still plaintext needing migration? A real PAN/Aadhaar/
    bank-account number never contains a colon, so this prefix match cannot collide with real
    data."""
    return bool(_CIPHERTEXT_SHAPE.match(value))


def encrypt_value(plaintext: str, *, dek: bytes, key_version: int, aad: str) -> str:
    """Plan §2.3/§6/§10.2 step "new writes use the new DEK" — the caller always passes the
    *current* DEK/version; there is no other way to reach this function with a stale version."""
    if len(dek) != DEK_LENGTH_BYTES:
        raise ValueError(f"DEK must be {DEK_LENGTH_BYTES} bytes for AES-256-GCM.")
    nonce = os.urandom(NONCE_LENGTH_BYTES)  # cryptographically secure (plan §2.3) — never reused
    aesgcm = AESGCM(dek)
    ciphertext_and_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
    return (
        f"{FORMAT_VERSION}:{key_version}:"
        f"{base64.b64encode(nonce).decode('ascii')}:"
        f"{base64.b64encode(ciphertext_and_tag).decode('ascii')}"
    )


def parse_ciphertext(value: str) -> tuple[int, bytes, bytes]:
    """Plan §2.3 "malformed ciphertext fails safely" — rejects anything that doesn't match the
    exact shape before any cryptographic operation runs, with a distinct, named exception (never
    an unhandled `IndexError`/`binascii.Error`)."""
    parts = value.split(":")
    if len(parts) != 4:
        raise MalformedCiphertextError(
            "Ciphertext does not match the expected v1:<key_version>:<nonce>:<ciphertext> shape."
        )
    version_tag, key_version_str, nonce_b64, ciphertext_b64 = parts
    if version_tag != FORMAT_VERSION:
        raise MalformedCiphertextError(f"Unsupported ciphertext format version {version_tag!r}.")
    try:
        key_version = int(key_version_str)
    except ValueError as exc:
        raise MalformedCiphertextError(
            "Ciphertext key_version segment is not a valid integer."
        ) from exc
    try:
        nonce = base64.b64decode(nonce_b64, validate=True)
        ciphertext_and_tag = base64.b64decode(ciphertext_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MalformedCiphertextError(
            "Ciphertext nonce/body segment is not valid base64."
        ) from exc
    if len(nonce) != NONCE_LENGTH_BYTES:
        raise MalformedCiphertextError(
            f"Ciphertext nonce is not {NONCE_LENGTH_BYTES} bytes."
        )
    return key_version, nonce, ciphertext_and_tag


def decrypt_value(ciphertext: str, *, dek: bytes, aad: str) -> str:
    """Plan §2.4 — AAD is required, not optional (no default value). A mismatched AAD (wrong
    row, wrong column, wrong table) fails exactly like a tampered ciphertext — GCM's
    authentication tag check does not distinguish the two, by design (plan §11: this is what
    makes ciphertext substitution between records structurally impossible, not just
    discouraged)."""
    key_version, nonce, ciphertext_and_tag = parse_ciphertext(ciphertext)
    if len(dek) != DEK_LENGTH_BYTES:
        raise ValueError(f"DEK must be {DEK_LENGTH_BYTES} bytes for AES-256-GCM.")
    aesgcm = AESGCM(dek)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext_and_tag, aad.encode("utf-8"))
    except InvalidTag as exc:
        raise DecryptionFailedError(
            f"Ciphertext authentication failed for key_version={key_version}."
        ) from exc
    return plaintext.decode("utf-8")
