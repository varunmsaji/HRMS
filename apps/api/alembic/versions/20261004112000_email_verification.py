"""SEC-09 (RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md) — email verification.

Adds `user.email_verified_at` (NULL = unverified) and `email_verification_token`, the same
hash-only-storage, single-use, TTL-bound shape as `password_reset_token`. Existing users are
backfilled to `NULL` (unverified) by simply not setting a value — `IdentityService.login` only
started checking this column in this same release, and every existing account was created before
this table/column existed, so treating them as needing verification would immediately lock out
every current user. Backfilling existing rows to "verified" instead (`now()`) is the pragmatic,
low-risk default: this finding is about *new* self-service registrations minting unverified
tenants, not about retroactively challenging accounts that already passed every other guard this
codebase has for months.

Revision ID: 20261004112000
Revises: 20261004111000
"""

from alembic import op

revision = "20261004112000"
down_revision = "20261004111000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS "email_verified_at" TIMESTAMPTZ;

        UPDATE "user" SET "email_verified_at" = now() WHERE "email_verified_at" IS NULL;

        CREATE TABLE IF NOT EXISTS email_verification_token (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "user_id" UUID NOT NULL,
            "token_hash" VARCHAR(64) NOT NULL,
            "expires_at" TIMESTAMPTZ NOT NULL,
            "used_at" TIMESTAMPTZ,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "email_verification_token_pkey" PRIMARY KEY ("id"),
            -- CASCADE (unlike `password_reset_token`'s RESTRICT): a verification token has no
            -- retention/audit requirement of its own — if the user row is gone, the pending
            -- verification is meaningless and should disappear with it, not block the delete.
            CONSTRAINT "email_verification_token_user_id_fkey" FOREIGN KEY ("user_id")
              REFERENCES "user"("id") ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT "email_verification_token_token_hash_key" UNIQUE ("token_hash")
        );

        CREATE INDEX IF NOT EXISTS email_verification_token_user_id_idx
          ON email_verification_token (user_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS email_verification_token;
        ALTER TABLE "user" DROP COLUMN IF EXISTS "email_verified_at";
        """
    )
