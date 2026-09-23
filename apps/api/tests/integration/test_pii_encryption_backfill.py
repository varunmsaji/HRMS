"""DATA-01 — integration tests for the existing-data backfill
(`docs/audits/DATA_01_PII_ENCRYPTION_TEST_MATRIX.md` §4, `hrms.core.crypto.backfill`), against the
real test database — matching this repository's existing convention of testing migrations/
backfills against real Postgres, not a mock. Every test seeds a plaintext value **directly via
raw SQL**, bypassing the API/ORM entirely, to simulate a row written before this batch's
encryption shipped (exactly what a real pre-migration production row looks like)."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
import redis.asyncio as redis
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.config.settings import get_settings
from hrms.core.crypto import backfill as backfill_module
from hrms.core.crypto.backfill import (
    backfill_employee_bank,
    backfill_employee_column,
    backfill_onboarding_bank_info,
    discover_plaintext_counts,
)
from hrms.core.crypto.field import is_ciphertext_shaped
from hrms.core.db.session import get_session_factory, session_scope

from .modules.employee.test_employee_banking import _create_employee, _register_tenant, _teardown
from .modules.onboarding.test_onboarding_case import _case_payload

pytestmark = pytest.mark.asyncio

_REGISTRATION_RATE_LIMIT_KEY = "ratelimit:auth:127.0.0.1"


@pytest.fixture(autouse=True)
async def _reset_registration_rate_limit() -> None:
    """This file lives directly under `tests/integration/`, not under `modules/organisation/`, so
    it does not inherit that directory's own `conftest.py` fixture of the same name — several
    tests in this file each register a fresh tenant, all sharing `ASGITransport`'s single
    127.0.0.1 client host, and would otherwise exhaust the real 10/min registration bucket."""
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    await client.delete(_REGISTRATION_RATE_LIMIT_KEY)
    yield
    await client.delete(_REGISTRATION_RATE_LIMIT_KEY)
    await client.aclose()


async def _seed_plaintext_bank_row(
    *, company_id: UUID, employee_id: UUID, account_number: str | None
) -> UUID:
    bank_id = uuid4()
    now = datetime.now(UTC)
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO employee_bank "
                "(id, company_id, employee_id, effective_from, account_holder_name, "
                " account_number_enc, bank_name, ifsc, branch_name, payment_mode, is_primary, "
                " verification_status, version, created_at, updated_at) "
                "VALUES (:id, :company_id, :employee_id, :effective_from, :holder, :account, "
                " :bank_name, :ifsc, :branch, :mode, true, 'PENDING', 1, :now, :now)"
            ),
            {
                "id": str(bank_id),
                "company_id": str(company_id),
                "employee_id": str(employee_id),
                "effective_from": date(2027, 1, 1),
                "holder": "Test Holder",
                "account": account_number,
                "bank_name": "State Bank",
                "ifsc": "SBIN0001234",
                "branch": "MG Road",
                "mode": "BANK",
                "now": now,
            },
        )
        await session.commit()
    return bank_id


async def _raw_account_number(bank_id: UUID) -> str | None:
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT account_number_enc FROM employee_bank WHERE id = :id"),
                {"id": str(bank_id)},
            )
        ).mappings().first()
        assert row is not None
        return row["account_number_enc"]


async def _delete_bank_rows(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employee_bank WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def test_backfill_on_an_empty_database() -> None:
    async with session_scope(get_settings()) as session:
        counts = await discover_plaintext_counts(session)
    assert set(counts) == {
        "employee.pan_number_enc",
        "employee.aadhaar_number_enc",
        "employee_bank.account_number_enc",
        "onboarding_case.bank_info.account_number_enc",
    }
    for value in counts.values():
        assert isinstance(value, int) and value >= 0


async def test_backfill_encrypts_a_single_plaintext_row(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        bank_id = await _seed_plaintext_bank_row(
            company_id=company_id, employee_id=UUID(employee["id"]), account_number="1234567890"
        )
        assert not is_ciphertext_shaped(await _raw_account_number(bank_id) or "")

        factory = get_session_factory()
        result = await backfill_employee_bank(factory, get_settings())

        assert result.rows_encrypted >= 1
        raw_after = await _raw_account_number(bank_id)
        assert raw_after is not None
        assert is_ciphertext_shaped(raw_after)
        assert raw_after != "1234567890"

        # Verify via the real authorized read path, not just the raw column shape.
        bank_response = await client.get(f"/v1/employees/{employee['id']}/bank", headers=headers)
        assert bank_response.status_code == 200, bank_response.text
        banks = bank_response.json()["data"]
        assert any(b["account_number_enc"] == "1234567890" for b in banks)
    finally:
        await _delete_bank_rows(company_id=company_id)
        await _teardown(company_id=company_id, user_id=user_id)


async def test_backfill_skips_null_values(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        bank_id = await _seed_plaintext_bank_row(
            company_id=company_id, employee_id=UUID(employee["id"]), account_number=None
        )
        factory = get_session_factory()
        await backfill_employee_bank(factory, get_settings())
        assert await _raw_account_number(bank_id) is None
    finally:
        await _delete_bank_rows(company_id=company_id)
        await _teardown(company_id=company_id, user_id=user_id)


async def test_backfill_is_a_no_op_on_already_encrypted_rows(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        bank_id = await _seed_plaintext_bank_row(
            company_id=company_id, employee_id=UUID(employee["id"]), account_number="1234567890"
        )
        factory = get_session_factory()
        await backfill_employee_bank(factory, get_settings())
        ciphertext_after_first_run = await _raw_account_number(bank_id)
        assert ciphertext_after_first_run is not None

        await backfill_employee_bank(factory, get_settings())
        ciphertext_after_second_run = await _raw_account_number(bank_id)

        # Byte-for-byte identical — the second run's batch query never selected this row again
        # (plan §6.4's structural idempotency), so it was never re-encrypted.
        assert ciphertext_after_first_run == ciphertext_after_second_run
    finally:
        await _delete_bank_rows(company_id=company_id)
        await _teardown(company_id=company_id, user_id=user_id)


async def test_backfill_spans_multiple_batches(client: AsyncClient) -> None:
    """A `BATCH_SIZE` override proves the `while True`/`LIMIT`-loop in `backfill_employee_bank`
    correctly continues past one batch, at a small, fast scale (plan §6.3's real 500 is
    impractical to seed per-test)."""
    headers, company_id, user_id = await _register_tenant(client)
    original_batch_size = backfill_module.BATCH_SIZE
    try:
        backfill_module.BATCH_SIZE = 2
        bank_ids = []
        for i in range(5):
            # A distinct employee per row — `employee_bank_no_overlap`'s GiST exclusion
            # constraint is scoped per employee, so this sidesteps that unrelated constraint
            # entirely rather than needing non-overlapping effective-dated ranges.
            employee = await _create_employee(client, headers, first_name=f"Batch{i}")
            bank_ids.append(
                await _seed_plaintext_bank_row(
                    company_id=company_id,
                    employee_id=UUID(employee["id"]),
                    account_number=f"100000000{i}",
                )
            )

        factory = get_session_factory()
        result = await backfill_employee_bank(factory, get_settings())

        assert result.rows_encrypted >= 5
        for bank_id in bank_ids:
            raw = await _raw_account_number(bank_id)
            assert raw is not None
            assert is_ciphertext_shaped(raw)
    finally:
        backfill_module.BATCH_SIZE = original_batch_size
        await _delete_bank_rows(company_id=company_id)
        await _teardown(company_id=company_id, user_id=user_id)


async def test_backfill_covers_employee_pan_and_aadhaar_columns(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        now = datetime.now(UTC)
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text(
                    "UPDATE employee SET pan_number_enc = :pan, aadhaar_number_enc = :aadhaar, "
                    "updated_at = :now WHERE id = :id"
                ),
                {"pan": "ABCDE1234F", "aadhaar": "123456789012", "now": now, "id": employee["id"]},
            )
            await session.commit()

        await backfill_employee_column(factory, get_settings(), column="pan_number_enc")
        await backfill_employee_column(factory, get_settings(), column="aadhaar_number_enc")

        async with factory() as session:
            row = (
                await session.execute(
                    text("SELECT pan_number_enc, aadhaar_number_enc FROM employee WHERE id = :id"),
                    {"id": employee["id"]},
                )
            ).mappings().first()
        assert row is not None
        assert is_ciphertext_shaped(row["pan_number_enc"])
        assert is_ciphertext_shaped(row["aadhaar_number_enc"])
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_backfill_covers_onboarding_case_bank_info(client: AsyncClient) -> None:
    """Guards specifically against the "backfill only remembers the bank table" failure mode the
    inventory's §4 finding warns about."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case_response = await client.post(
            "/v1/onboarding-cases", headers=headers, json=_case_payload()
        )
        assert case_response.status_code == 201, case_response.text
        case_id = case_response.json()["data"]["id"]

        now = datetime.now(UTC)
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text(
                    "UPDATE onboarding_case SET bank_info = :bank_info, updated_at = :now "
                    "WHERE id = :id"
                ),
                {
                    "bank_info": '{"account_number_enc": "1234567890", "payment_mode": "BANK"}',
                    "now": now,
                    "id": case_id,
                },
            )
            await session.commit()

        await backfill_onboarding_bank_info(factory, get_settings())

        async with factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT bank_info ->> 'account_number_enc' AS enc "
                        "FROM onboarding_case WHERE id = :id"
                    ),
                    {"id": case_id},
                )
            ).mappings().first()
        assert row is not None
        assert is_ciphertext_shaped(row["enc"])
    finally:
        async with get_session_factory()() as session:
            await session.execute(
                text("DELETE FROM onboarding_case WHERE company_id = :cid"),
                {"cid": str(company_id)},
            )
            await session.commit()
        await _teardown(company_id=company_id, user_id=user_id)


async def test_backfill_verification_catches_a_bad_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan §6.6 — the verification step is real, not a tautology: force `decrypt_column` to
    return a value that doesn't match what was just encrypted, and confirm the backfill raises
    rather than silently committing a corrupted row."""
    from hrms.core.crypto import service as crypto_service_module

    async def _wrong_decrypt(self: object, *args: object, **kwargs: object) -> str:
        return "not-the-original-value"

    monkeypatch.setattr(
        crypto_service_module.PiiCryptoService, "decrypt_column", _wrong_decrypt, raising=True
    )

    from hrms.core.crypto.backfill import _encrypt_and_verify
    from hrms.core.crypto.service import PiiCryptoService
    from hrms.core.db.session import session_scope

    crypto = PiiCryptoService(get_settings())
    async with session_scope(get_settings()) as session:
        with pytest.raises(RuntimeError, match="verification failed"):
            await _encrypt_and_verify(
                crypto, session, plaintext="1234567890", table="employee_bank",
                column="account_number_enc", record_id=uuid4(),
            )
