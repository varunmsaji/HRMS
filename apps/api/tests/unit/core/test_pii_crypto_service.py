"""DATA-01 — unit tests for `PiiCryptoService`
(`docs/audits/DATA_01_PII_ENCRYPTION_TEST_MATRIX.md` §1/§3, `hrms.core.crypto.service`). Runs in
`environment=development` (this suite's default, `tests/conftest.py`), so encryption goes through
the deterministic dev DEK — no real KMS/registry row needed, matching plan §5.4."""

from uuid import uuid4

import pytest

from hrms.core.config.settings import get_settings
from hrms.core.crypto.errors import DecryptionFailedError
from hrms.core.crypto.service import PiiCryptoService
from hrms.core.db.session import session_scope

pytestmark = pytest.mark.asyncio


async def test_none_passes_through_unchanged_for_columns() -> None:
    crypto = PiiCryptoService(get_settings())
    async with session_scope(get_settings()) as session:
        encrypted = await crypto.encrypt_column(
            session, plaintext=None, table="employee_bank", column="account_number_enc",
            record_id=uuid4(),
        )
        decrypted = await crypto.decrypt_column(
            session, ciphertext=None, table="employee_bank", column="account_number_enc",
            record_id=uuid4(),
        )
    assert encrypted is None
    assert decrypted is None


async def test_none_passes_through_unchanged_for_jsonb_keys() -> None:
    crypto = PiiCryptoService(get_settings())
    async with session_scope(get_settings()) as session:
        encrypted = await crypto.encrypt_jsonb_key(
            session, plaintext=None, table="onboarding_case", column="bank_info",
            jsonb_key="account_number_enc", record_id=uuid4(),
        )
        decrypted = await crypto.decrypt_jsonb_key(
            session, ciphertext=None, table="onboarding_case", column="bank_info",
            jsonb_key="account_number_enc", record_id=uuid4(),
        )
    assert encrypted is None
    assert decrypted is None


async def test_column_round_trip() -> None:
    crypto = PiiCryptoService(get_settings())
    record_id = uuid4()
    async with session_scope(get_settings()) as session:
        ciphertext = await crypto.encrypt_column(
            session, plaintext="ABCDE1234F", table="employee", column="pan_number_enc",
            record_id=record_id,
        )
        assert ciphertext is not None
        assert ciphertext.startswith("v1:")
        plaintext = await crypto.decrypt_column(
            session, ciphertext=ciphertext, table="employee", column="pan_number_enc",
            record_id=record_id,
        )
    assert plaintext == "ABCDE1234F"


async def test_jsonb_key_round_trip() -> None:
    crypto = PiiCryptoService(get_settings())
    record_id = uuid4()
    async with session_scope(get_settings()) as session:
        ciphertext = await crypto.encrypt_jsonb_key(
            session, plaintext="1234567890", table="onboarding_case", column="bank_info",
            jsonb_key="account_number_enc", record_id=record_id,
        )
        assert ciphertext is not None
        plaintext = await crypto.decrypt_jsonb_key(
            session, ciphertext=ciphertext, table="onboarding_case", column="bank_info",
            jsonb_key="account_number_enc", record_id=record_id,
        )
    assert plaintext == "1234567890"


async def test_column_and_jsonb_key_aad_differ_for_the_same_field_name_and_record() -> None:
    """A `pan_number_enc` column value and a same-shaped JSONB key sharing the same record id
    must not be decryptable as each other — proves the `table:column:record_id` vs.
    `table:column.jsonb_key:record_id` AAD forms (plan §2.4) are genuinely distinct."""
    crypto = PiiCryptoService(get_settings())
    record_id = uuid4()
    async with session_scope(get_settings()) as session:
        column_ciphertext = await crypto.encrypt_column(
            session, plaintext="1234567890", table="employee_bank",
            column="account_number_enc", record_id=record_id,
        )
        assert column_ciphertext is not None
        with pytest.raises(DecryptionFailedError):
            await crypto.decrypt_jsonb_key(
                session, ciphertext=column_ciphertext, table="employee_bank",
                column="account_number_enc", jsonb_key="account_number_enc", record_id=record_id,
            )


async def test_cross_record_substitution_fails_via_the_service() -> None:
    crypto = PiiCryptoService(get_settings())
    record_a = uuid4()
    record_b = uuid4()
    async with session_scope(get_settings()) as session:
        ciphertext_a = await crypto.encrypt_column(
            session, plaintext="1234567890", table="employee_bank",
            column="account_number_enc", record_id=record_a,
        )
        assert ciphertext_a is not None
        with pytest.raises(DecryptionFailedError):
            await crypto.decrypt_column(
                session, ciphertext=ciphertext_a, table="employee_bank",
                column="account_number_enc", record_id=record_b,
            )
