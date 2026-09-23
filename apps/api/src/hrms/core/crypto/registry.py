"""DATA-01 — `encryption_keys` registry access
(`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.2). Pure-query + rotation
repository, mirroring the rest of this codebase's repository convention (no business rules beyond
the registry's own "exactly one ACTIVE row" invariant, which is not a domain rule)."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.crypto.errors import NoActiveEncryptionKeyError, UnknownKeyVersionError
from hrms.core.crypto.models import STATUS_ACTIVE, STATUS_RETIRED, EncryptionKey


class EncryptionKeyRegistry:
    async def get_active(self, session: AsyncSession) -> EncryptionKey:
        """Plan §2.2 "how the current key is selected": exactly one `ACTIVE` row is expected.
        Zero or more than one is a data-integrity fault (caught by the DB's own partial unique
        index for "more than one"; this still fails closed defensively rather than assuming the
        DB constraint is the only thing preventing it)."""
        stmt = select(EncryptionKey).where(EncryptionKey.status == STATUS_ACTIVE)
        rows = (await session.execute(stmt)).scalars().all()
        if len(rows) != 1:
            raise NoActiveEncryptionKeyError(
                f"Expected exactly one ACTIVE encryption key, found {len(rows)}."
            )
        return rows[0]

    async def get_by_version(self, session: AsyncSession, *, key_version: int) -> EncryptionKey:
        """Plan §2.2 "how ciphertext key_version maps to key material" — a `key_version` with no
        matching row is a hard failure, never a fallback to the current key."""
        stmt = select(EncryptionKey).where(EncryptionKey.key_version == key_version)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise UnknownKeyVersionError(f"No encryption key registered for version {key_version}.")
        return row

    async def provision_initial(
        self,
        session: AsyncSession,
        *,
        key_version: int,
        kms_key_arn: str,
        wrapped_dek_base64: str,
        created_by: str,
    ) -> EncryptionKey:
        """Plan §6.9 Phase A′ — the one-time first row. Distinct from `rotate` (below) only in
        that there is no prior `ACTIVE` row to retire; the DB's partial unique index still refuses
        a second `ACTIVE` row if this is accidentally called twice."""
        now = datetime.now(UTC)
        row = EncryptionKey(
            id=uuid4(),
            key_version=key_version,
            kms_key_arn=kms_key_arn,
            wrapped_dek=wrapped_dek_base64,
            status=STATUS_ACTIVE,
            activated_at=now,
            created_by=created_by,
        )
        session.add(row)
        await session.flush()
        return row

    async def rotate(
        self,
        session: AsyncSession,
        *,
        kms_key_arn: str,
        wrapped_dek_base64: str,
        created_by: str,
    ) -> EncryptionKey:
        """Plan §10.2 application-level DEK rotation, steps 3-4: insert the new `ACTIVE` row and
        retire the previous one, in the same transaction (the caller's session/transaction — this
        method does not commit) — a failure between the two never leaves zero or two `ACTIVE`
        rows, per plan §2.2's stated invariant."""
        current = await self.get_active(session)
        now = datetime.now(UTC)
        current.status = STATUS_RETIRED
        current.retired_at = now
        next_version = current.key_version + 1
        new_row = EncryptionKey(
            id=uuid4(),
            key_version=next_version,
            kms_key_arn=kms_key_arn,
            wrapped_dek=wrapped_dek_base64,
            status=STATUS_ACTIVE,
            activated_at=now,
            created_by=created_by,
        )
        session.add(new_row)
        await session.flush()
        return new_row

    async def count_active(self, session: AsyncSession) -> int:
        """Boot-guard support (plan §10.3) — a lightweight existence check, distinct from
        `get_active` (which raises) so a caller that wants to report "not configured yet" rather
        than crash can do so."""
        stmt = select(EncryptionKey).where(EncryptionKey.status == STATUS_ACTIVE)
        return len((await session.execute(stmt)).scalars().all())
