"""DATA-01 — the encryption-key registry
(`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.2). Lives in `hrms.core` (not a
domain module) since it is infrastructure every module's
encrypted fields resolve against, mirroring `core.audit.models.AuditLog`'s own placement.

No `company_id` — this table is environment-scoped by which database it lives in (this
repository deploys one database per environment), not tenant-scoped; it is never subject to RLS
and never joined against tenant data."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hrms.core.db.base import Base, TimestampMixin

STATUS_ACTIVE = "ACTIVE"
STATUS_RETIRED = "RETIRED"


class EncryptionKey(Base, TimestampMixin):
    """One row per application DEK ever issued (plan §2.2). Rows are never deleted — a `RETIRED`
    row remains the only thing that can decrypt ciphertext still carrying its `key_version`
    (plan §10.2). Exactly one `ACTIVE` row is expected to exist at a time; enforced at the
    application/rotation-service level (`EncryptionKeyRegistry.rotate`, one transaction), not by a
    DB constraint — the same "no boolean-flag race" discipline `employee_bank`'s GiST exclusion
    constraint applies to effective-dated rows, applied here via transactional atomicity instead
    since a partial-unique-index equivalent is a defense-in-depth addition, not a substitute."""

    __tablename__ = "encryption_keys"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    key_version: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    # RELEASE_HARDENING_PHASE_3A — renamed from `kms_key_arn`: this deployment no longer wraps
    # DEKs via AWS KMS (`master_key.py`). A non-secret fingerprint of the `pii_master_key` that
    # wrapped this row's DEK, purely for record-keeping/future rotation-detection — never used to
    # look anything up externally.
    wrapping_key_id: Mapped[str] = mapped_column(String, nullable=False)
    wrapped_dek: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default=STATUS_ACTIVE)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
