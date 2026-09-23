"""DATA-01 — the encryption-key registry
(`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.2). No data migration here — this
creates the (empty) table only; initial key provisioning
(plan §6.9 Phase A′) is an operational step run by the implementer against each real environment's
own KMS CMK, not something a migration can safely do (a migration must not call out to KMS or
generate key material).

No `company_id`, no RLS — this table is environment-scoped by which database it lives in (one
database per environment, per `PRODUCTION_HARDENING_BATCH_1_REPORT.md`'s own `ENVIRONMENT=`
convention), never tenant data.

Revision ID: 20260927090000
Revises: 20260926090000
"""

from alembic import op

revision = "20260927090000"
down_revision = "20260926090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS encryption_keys (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "key_version" INTEGER NOT NULL,
            "kms_key_arn" VARCHAR NOT NULL,
            "wrapped_dek" TEXT NOT NULL,
            "status" VARCHAR(10) NOT NULL DEFAULT 'ACTIVE',
            "activated_at" TIMESTAMPTZ,
            "retired_at" TIMESTAMPTZ,
            "created_by" VARCHAR(100),
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "encryption_keys_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "encryption_keys_key_version_key" UNIQUE ("key_version"),
            CONSTRAINT "encryption_keys_status_check" CHECK ("status" IN ('ACTIVE', 'RETIRED'))
        );

        CREATE INDEX IF NOT EXISTS encryption_keys_status_idx ON encryption_keys (status);

        -- Defense-in-depth against two ACTIVE rows existing simultaneously — the application's
        -- own rotation service (EncryptionKeyRegistry.rotate) already enforces this
        -- transactionally (plan §2.2); this partial unique index makes the invariant impossible
        -- to violate even from a bypassing script.
        CREATE UNIQUE INDEX IF NOT EXISTS encryption_keys_one_active_idx
            ON encryption_keys (status)
            WHERE status = 'ACTIVE';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS encryption_keys;
        """
    )
