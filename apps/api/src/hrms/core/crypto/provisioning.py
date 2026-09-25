"""DATA-01 — operational key-provisioning/rotation
(`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §6.9 Phase A′, §10.2). Called by an
operator-run step against a real environment's own `pii_master_key`
(RELEASE_HARDENING_PHASE_3A — see `master_key.py`; this used AWS KMS before that phase)
— **never** automatically at application boot or on any request path. The migration that
creates `encryption_keys` (`20260927090000_encryption_key_registry.py`) deliberately does not
call this — a schema migration must not generate key material."""

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import Settings
from hrms.core.crypto.keys import DekCache
from hrms.core.crypto.master_key import MasterKeyService, fingerprint
from hrms.core.crypto.models import EncryptionKey
from hrms.core.crypto.registry import EncryptionKeyRegistry


def _wrapping_key_id(settings: Settings) -> str:
    secret = settings.dev_encryption_key if settings.is_development else settings.pii_master_key
    return fingerprint(secret)


async def provision_initial_key(
    session: AsyncSession,
    *,
    settings: Settings,
    created_by: str,
    dek_cache: DekCache | None = None,
) -> EncryptionKey:
    """The one-time first row for a new environment (plan §6.9 Phase A′). If an `ACTIVE` row
    already exists, `encryption_keys_one_active_idx` (the DB's own partial unique index) rejects
    the insert — this function does not itself guard against double-provisioning beyond that."""
    master = MasterKeyService(settings)
    registry = EncryptionKeyRegistry()
    _plaintext_dek, wrapped = await master.generate_data_key()
    row = await registry.provision_initial(
        session,
        key_version=1,
        wrapping_key_id=_wrapping_key_id(settings),
        wrapped_dek_base64=wrapped,
        created_by=created_by,
    )
    await session.commit()
    if dek_cache is not None:
        dek_cache.invalidate_current()
    return row


async def rotate_key(
    session: AsyncSession,
    *,
    settings: Settings,
    created_by: str,
    dek_cache: DekCache | None = None,
) -> EncryptionKey:
    """Plan §10.2 steps 1-4: generate a new DEK, wrap it, insert it as the new `ACTIVE` row and
    retire the previous one — all in one registry-level transaction (`registry.rotate`)."""
    master = MasterKeyService(settings)
    registry = EncryptionKeyRegistry()
    _plaintext_dek, wrapped = await master.generate_data_key()
    row = await registry.rotate(
        session,
        wrapping_key_id=_wrapping_key_id(settings),
        wrapped_dek_base64=wrapped,
        created_by=created_by,
    )
    await session.commit()
    if dek_cache is not None:
        dek_cache.invalidate_current()
    return row
