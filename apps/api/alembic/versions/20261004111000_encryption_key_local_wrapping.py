"""RELEASE_HARDENING_PHASE_3A — rename `encryption_keys.kms_key_arn` to `wrapping_key_id`
(`docs/audits/RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md` §9). This deployment no longer
wraps DEKs via AWS KMS (`hrms.core.crypto.master_key`, replacing `hrms.core.crypto.kms`) — the
column now stores a non-secret fingerprint of the application `pii_master_key` that wrapped a
row's DEK, not a KMS key ARN. Pure rename, no data transformation: any existing row's value is
carried over unchanged (this environment has never provisioned a real key outside tests, per the
Phase 3A audit — no ciphertext or wrapped DEK is invalidated by this migration).

Revision ID: 20261004111000
Revises: 20261004110000
"""

from alembic import op

revision = "20261004111000"
down_revision = "20261004110000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE encryption_keys RENAME COLUMN "kms_key_arn" TO "wrapping_key_id";')


def downgrade() -> None:
    op.execute('ALTER TABLE encryption_keys RENAME COLUMN "wrapping_key_id" TO "kms_key_arn";')
