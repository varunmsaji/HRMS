"""DATA-01 — the existing-data backfill
(`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §6). Encrypts any remaining
plaintext-format value in the four DATA-01 storage locations. Callable directly — as a one-off
script or a Celery task — never runs automatically at import time, app boot, or on any request
path.

Design, matching the plan exactly:
- **Discovery is read-only** (`discover_plaintext_counts`) — run before any write, and again
  after a pass to confirm zero remain (plan §6.1).
- **Classification is the ciphertext format's own `v1:` prefix** (plan §6.2) — no separate
  migration-status column or table.
- **Batched, `FOR UPDATE SKIP LOCKED`, one transaction per batch** (plan §6.3) — safe to run
  concurrently with live application traffic; a batch failure (KMS transient error, a
  serialization conflict) rolls back only that batch, leaving already-committed batches intact.
- **Idempotent structurally** (plan §6.4) — a fully-migrated table's batch query naturally
  selects zero rows on re-run.
- **Verified per row, in the same transaction, before commit** (plan §6.6's own requirement,
  satisfied here even more strictly than a separate snapshot-comparison pass: the plaintext read
  in this transaction is compared against decrypting the ciphertext this same transaction is
  about to write, before that transaction commits — the plaintext read is a local Python
  variable, never logged, and goes out of scope the moment the batch function returns).
"""

from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hrms.core.config.settings import Settings
from hrms.core.crypto.field import is_ciphertext_shaped
from hrms.core.crypto.service import PiiCryptoService
from hrms.modules.employee.models import Employee, EmployeeBank
from hrms.modules.onboarding.models import OnboardingCase

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500

#: Postgres regex — matches this batch's own `v1:<int>:` ciphertext prefix (plan §6.2). Used in
#: the SQL `WHERE` clause so an already-migrated row is never even selected into a batch; the
#: Python-side `is_ciphertext_shaped` check in each loop below is a second, defense-in-depth
#: check against the exact same rows, not a different rule.
_PLAINTEXT_SQL_FILTER = "!~ '^v1:[0-9]+:'"


@dataclass
class BackfillResult:
    location: str
    rows_processed: int = 0
    rows_encrypted: int = 0
    rows_skipped_null: int = 0


async def discover_plaintext_counts(session: AsyncSession) -> dict[str, int]:
    """Plan §6.1 — read-only. Call before any write, and again after a pass to confirm zero
    remain (the closeout report's own required evidence, plan §12 gate 1)."""
    employee_row = (
        await session.execute(
            text(
                "SELECT "
                f"count(*) FILTER (WHERE pan_number_enc IS NOT NULL "
                f"AND pan_number_enc {_PLAINTEXT_SQL_FILTER}) AS pan_rows, "
                f"count(*) FILTER (WHERE aadhaar_number_enc IS NOT NULL "
                f"AND aadhaar_number_enc {_PLAINTEXT_SQL_FILTER}) AS aadhaar_rows "
                "FROM employee"
            )
        )
    ).mappings().first()
    bank_row = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE account_number_enc IS NOT NULL "
                f"AND account_number_enc {_PLAINTEXT_SQL_FILTER}) AS bank_rows "
                "FROM employee_bank"
            )
        )
    ).mappings().first()
    onboarding_row = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE bank_info ->> 'account_number_enc' IS NOT NULL "
                f"AND bank_info ->> 'account_number_enc' {_PLAINTEXT_SQL_FILTER}) "
                "AS onboarding_bank_rows FROM onboarding_case"
            )
        )
    ).mappings().first()
    assert employee_row is not None and bank_row is not None and onboarding_row is not None
    return {
        "employee.pan_number_enc": employee_row["pan_rows"],
        "employee.aadhaar_number_enc": employee_row["aadhaar_rows"],
        "employee_bank.account_number_enc": bank_row["bank_rows"],
        "onboarding_case.bank_info.account_number_enc": onboarding_row["onboarding_bank_rows"],
    }


async def _encrypt_and_verify(
    crypto: PiiCryptoService,
    session: AsyncSession,
    *,
    plaintext: str,
    table: str,
    column: str,
    record_id: UUID,
) -> str:
    """Encrypts, then immediately decrypts the result and compares it against the original
    plaintext (plan §6.6) — before the caller ever assigns the ciphertext to the row. Raising
    here aborts the whole batch's transaction (the caller's `try`/`except`), so a verification
    failure never leaves a partially-migrated, unverified row committed."""
    ciphertext = await crypto.encrypt_column(
        session, plaintext=plaintext, table=table, column=column, record_id=record_id
    )
    assert ciphertext is not None  # plaintext was not None, so encrypt_column cannot return None
    roundtrip = await crypto.decrypt_column(
        session, ciphertext=ciphertext, table=table, column=column, record_id=record_id
    )
    if roundtrip != plaintext:
        raise RuntimeError(
            f"Backfill verification failed for {table}.{column} id={record_id}: decrypted "
            "value did not match the original — aborting this batch without committing."
        )
    return ciphertext


async def backfill_employee_column(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    column: str,
) -> BackfillResult:
    """`employee.pan_number_enc` or `employee.aadhaar_number_enc` (plan §6, inventory §2 — both
    expected empty in every real environment today; this exists so the backfill is ready the
    moment E-02 ships a write path, per this plan's own instruction)."""
    if column not in ("pan_number_enc", "aadhaar_number_enc"):
        raise ValueError(f"Unsupported employee column for backfill: {column!r}")
    result = BackfillResult(location=f"employee.{column}")
    crypto = PiiCryptoService(settings)
    column_attr = getattr(Employee, column)

    while True:
        async with session_factory() as session:
            stmt = (
                select(Employee)
                .where(column_attr.isnot(None), column_attr.op("!~")(r"^v1:[0-9]+:"))
                .order_by(Employee.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            rows = (await session.execute(stmt)).scalars().all()
            candidates = [row for row in rows if not is_ciphertext_shaped(getattr(row, column))]
            if not candidates:
                await session.rollback()
                break

            for row in candidates:
                plaintext = getattr(row, column)
                ciphertext = await _encrypt_and_verify(
                    crypto, session, plaintext=plaintext, table="employee", column=column,
                    record_id=row.id,
                )
                setattr(row, column, ciphertext)
                result.rows_encrypted += 1
            result.rows_processed += len(candidates)
            await session.commit()

        logger.info(
            "data01_backfill_batch",
            location=result.location,
            rows_processed=result.rows_processed,
            rows_encrypted=result.rows_encrypted,
        )
        if len(rows) < BATCH_SIZE:
            break

    return result


async def backfill_employee_bank(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> BackfillResult:
    """`employee_bank.account_number_enc` (plan §6 — the live, highest-urgency location)."""
    result = BackfillResult(location="employee_bank.account_number_enc")
    crypto = PiiCryptoService(settings)

    while True:
        async with session_factory() as session:
            stmt = (
                select(EmployeeBank)
                .where(
                    EmployeeBank.account_number_enc.isnot(None),
                    EmployeeBank.account_number_enc.op("!~")(r"^v1:[0-9]+:"),
                )
                .order_by(EmployeeBank.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            rows = (await session.execute(stmt)).scalars().all()
            candidates = [
                row
                for row in rows
                if row.account_number_enc is not None
                and not is_ciphertext_shaped(row.account_number_enc)
            ]
            if not candidates:
                await session.rollback()
                break

            for row in candidates:
                plaintext = row.account_number_enc
                assert plaintext is not None  # narrowed by the `candidates` filter above
                ciphertext = await _encrypt_and_verify(
                    crypto, session, plaintext=plaintext, table="employee_bank",
                    column="account_number_enc", record_id=row.id,
                )
                row.account_number_enc = ciphertext
                result.rows_encrypted += 1
            result.rows_processed += len(candidates)
            await session.commit()

        logger.info(
            "data01_backfill_batch",
            location=result.location,
            rows_processed=result.rows_processed,
            rows_encrypted=result.rows_encrypted,
        )
        if len(rows) < BATCH_SIZE:
            break

    return result


async def backfill_onboarding_bank_info(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> BackfillResult:
    """`onboarding_case.bank_info`'s one sensitive key (plan §6 — the second, easy-to-miss live
    location, inventory §4). A JSONB dict has no per-key `WHERE`-clause hook comparable to a real
    column, so candidacy is still narrowed in SQL (`bank_info ->> 'account_number_enc'`) but the
    plaintext-vs-ciphertext classification is re-checked in Python exactly as for the two column
    backfills above — same rule, same function (`is_ciphertext_shaped`), applied to a dict value
    instead of a column value."""
    result = BackfillResult(location="onboarding_case.bank_info.account_number_enc")
    crypto = PiiCryptoService(settings)

    while True:
        async with session_factory() as session:
            key_astext = OnboardingCase.bank_info["account_number_enc"].astext
            stmt = (
                select(OnboardingCase)
                .where(key_astext.isnot(None), key_astext.op("!~")(r"^v1:[0-9]+:"))
                .order_by(OnboardingCase.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            rows = (await session.execute(stmt)).scalars().all()
            candidates = [
                row
                for row in rows
                if isinstance(row.bank_info.get("account_number_enc"), str)
                and not is_ciphertext_shaped(row.bank_info["account_number_enc"])
            ]
            if not candidates:
                await session.rollback()
                break

            for row in candidates:
                bank_info = dict(row.bank_info)
                plaintext = bank_info["account_number_enc"]
                ciphertext = await crypto.encrypt_jsonb_key(
                    session, plaintext=plaintext, table="onboarding_case", column="bank_info",
                    jsonb_key="account_number_enc", record_id=row.id,
                )
                assert ciphertext is not None
                roundtrip = await crypto.decrypt_jsonb_key(
                    session, ciphertext=ciphertext, table="onboarding_case", column="bank_info",
                    jsonb_key="account_number_enc", record_id=row.id,
                )
                if roundtrip != plaintext:
                    raise RuntimeError(
                        "Backfill verification failed for onboarding_case.bank_info."
                        f"account_number_enc id={row.id}: decrypted value did not match the "
                        "original — aborting this batch without committing."
                    )
                bank_info["account_number_enc"] = ciphertext
                row.bank_info = bank_info
                result.rows_encrypted += 1
            result.rows_processed += len(candidates)
            await session.commit()

        logger.info(
            "data01_backfill_batch",
            location=result.location,
            rows_processed=result.rows_processed,
            rows_encrypted=result.rows_encrypted,
        )
        if len(rows) < BATCH_SIZE:
            break

    return result


async def run_full_backfill(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> list[BackfillResult]:
    """Runs all four locations, in this order (matches inventory §1's own ordering — dormant
    PAN/Aadhaar first, since they are expected to be instant no-ops today, then the two live
    locations). Not required to run in this order for correctness (each location is fully
    independent); ordered for a readable closeout report only."""
    results = [
        await backfill_employee_column(session_factory, settings, column="pan_number_enc"),
        await backfill_employee_column(session_factory, settings, column="aadhaar_number_enc"),
        await backfill_employee_bank(session_factory, settings),
        await backfill_onboarding_bank_info(session_factory, settings),
    ]
    return results
