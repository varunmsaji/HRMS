"""DATA-01 — unit tests for the pure crypto primitive
(`docs/audits/DATA_01_PII_ENCRYPTION_TEST_MATRIX.md` §1, `hrms.core.crypto.field`)."""

import base64

import pytest

from hrms.core.crypto.errors import DecryptionFailedError, MalformedCiphertextError
from hrms.core.crypto.field import (
    DEK_LENGTH_BYTES,
    FORMAT_VERSION,
    decrypt_value,
    encrypt_value,
    is_ciphertext_shaped,
    parse_ciphertext,
)

_DEK = b"\x11" * DEK_LENGTH_BYTES
_OTHER_DEK = b"\x22" * DEK_LENGTH_BYTES
_AAD = "employee_bank:account_number_enc:11111111-1111-1111-1111-111111111111"
_OTHER_AAD = "employee_bank:account_number_enc:22222222-2222-2222-2222-222222222222"


def test_decrypt_returns_the_original_value() -> None:
    for plaintext in (
        "ABCDE1234F",  # real-shaped PAN
        "123456789012",  # real-shaped Aadhaar
        "1234567890",  # real-shaped bank account number
        "",  # empty string
        "x" * 5000,  # very long string
        "value:with:colons:in:it",  # format-injection guard
    ):
        ciphertext = encrypt_value(plaintext, dek=_DEK, key_version=1, aad=_AAD)
        assert decrypt_value(ciphertext, dek=_DEK, aad=_AAD) == plaintext


def test_plaintext_never_persisted() -> None:
    plaintext = "ABCDE1234F"
    ciphertext = encrypt_value(plaintext, dek=_DEK, key_version=1, aad=_AAD)
    assert plaintext not in ciphertext
    assert base64.b64encode(plaintext.encode()).decode() not in ciphertext


def test_randomized_encryption_produces_different_ciphertext_each_time() -> None:
    plaintext = "1234567890"
    first = encrypt_value(plaintext, dek=_DEK, key_version=1, aad=_AAD)
    second = encrypt_value(plaintext, dek=_DEK, key_version=1, aad=_AAD)
    assert first != second
    # Both still decrypt to the same original value — different nonces, same plaintext.
    assert decrypt_value(first, dek=_DEK, aad=_AAD) == plaintext
    assert decrypt_value(second, dek=_DEK, aad=_AAD) == plaintext


def test_ciphertext_format_matches_the_versioned_shape() -> None:
    ciphertext = encrypt_value("1234567890", dek=_DEK, key_version=7, aad=_AAD)
    parts = ciphertext.split(":")
    assert len(parts) == 4
    assert parts[0] == FORMAT_VERSION
    assert parts[1] == "7"
    # Both remaining segments must be valid base64.
    base64.b64decode(parts[2], validate=True)
    base64.b64decode(parts[3], validate=True)


def test_key_version_is_recorded_and_parsed() -> None:
    ciphertext = encrypt_value("1234567890", dek=_DEK, key_version=42, aad=_AAD)
    key_version, _nonce, _ct = parse_ciphertext(ciphertext)
    assert key_version == 42


def test_tampered_ciphertext_fails_authentication() -> None:
    ciphertext = encrypt_value("1234567890", dek=_DEK, key_version=1, aad=_AAD)
    version, key_version, nonce_b64, ct_b64 = ciphertext.split(":")
    raw = bytearray(base64.b64decode(ct_b64))
    raw[0] ^= 0xFF
    tampered = f"{version}:{key_version}:{nonce_b64}:{base64.b64encode(bytes(raw)).decode()}"
    with pytest.raises(DecryptionFailedError):
        decrypt_value(tampered, dek=_DEK, aad=_AAD)


def test_tampered_nonce_fails_authentication() -> None:
    ciphertext = encrypt_value("1234567890", dek=_DEK, key_version=1, aad=_AAD)
    version, key_version, nonce_b64, ct_b64 = ciphertext.split(":")
    raw = bytearray(base64.b64decode(nonce_b64))
    raw[0] ^= 0xFF
    tampered = f"{version}:{key_version}:{base64.b64encode(bytes(raw)).decode()}:{ct_b64}"
    with pytest.raises(DecryptionFailedError):
        decrypt_value(tampered, dek=_DEK, aad=_AAD)


@pytest.mark.parametrize(
    "malformed",
    [
        "not-ciphertext-at-all",
        "v1:not-an-int:abc:def",
        "v2:1:abc:def",  # unsupported future version
        "v1:1:abc",  # missing segment
        "v1:1:abc:def:ghi",  # extra segment
        "v1:1:not!base64!:def",
        "",
    ],
)
def test_malformed_ciphertext_string_fails_safely(malformed: str) -> None:
    with pytest.raises(MalformedCiphertextError):
        decrypt_value(malformed, dek=_DEK, aad=_AAD)


def test_malformed_ciphertext_never_raises_an_unhandled_builtin_exception() -> None:
    # Guards specifically against IndexError/binascii.Error leaking past this module's own
    # error handling (plan §2.3).
    try:
        decrypt_value("garbage", dek=_DEK, aad=_AAD)
    except MalformedCiphertextError:
        pass
    else:
        pytest.fail("expected MalformedCiphertextError")


def test_wrong_aad_fails_authentication_cross_record_substitution() -> None:
    """The single most important AAD test (plan §2.4/§11) — encrypt for one record's AAD, then
    attempt to decrypt the same ciphertext under a *different* record's AAD (simulating a
    ciphertext copied/substituted between rows). Must fail, and must not return plaintext."""
    ciphertext = encrypt_value("1234567890", dek=_DEK, key_version=1, aad=_AAD)
    with pytest.raises(DecryptionFailedError):
        decrypt_value(ciphertext, dek=_DEK, aad=_OTHER_AAD)


def test_wrong_column_aad_fails_authentication() -> None:
    column_a_aad = "employee:pan_number_enc:11111111-1111-1111-1111-111111111111"
    column_b_aad = "employee:aadhaar_number_enc:11111111-1111-1111-1111-111111111111"
    ciphertext = encrypt_value("ABCDE1234F", dek=_DEK, key_version=1, aad=column_a_aad)
    with pytest.raises(DecryptionFailedError):
        decrypt_value(ciphertext, dek=_DEK, aad=column_b_aad)


def test_wrong_dek_fails_authentication() -> None:
    ciphertext = encrypt_value("1234567890", dek=_DEK, key_version=1, aad=_AAD)
    with pytest.raises(DecryptionFailedError):
        decrypt_value(ciphertext, dek=_OTHER_DEK, aad=_AAD)


def test_is_ciphertext_shaped_distinguishes_plaintext_from_ciphertext() -> None:
    ciphertext = encrypt_value("1234567890", dek=_DEK, key_version=1, aad=_AAD)
    assert is_ciphertext_shaped(ciphertext) is True
    assert is_ciphertext_shaped("1234567890") is False
    assert is_ciphertext_shaped("ABCDE1234F") is False
    assert is_ciphertext_shaped("v1-not-quite-the-format") is False


def test_encrypt_rejects_a_dek_of_the_wrong_length() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        encrypt_value("1234567890", dek=b"too-short", key_version=1, aad=_AAD)
