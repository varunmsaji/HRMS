"""Password Reset Token — `docs/modules/employee/
41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md` Phase 3.

Same hash-only-storage, TTL-bound shape as `refresh_token`/`account_invite`. No RLS — matches
`refresh_token`'s own precedent (no `company_id` column at all here; a password reset is scoped
to a `User`, not a tenant, and `user` itself carries no RLS either).

Revision ID: 20260922090000
Revises: 20260921090000
"""

from alembic import op

revision = "20260922090000"
down_revision = "20260921090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_token (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "user_id" UUID NOT NULL,
            "token_hash" VARCHAR(64) NOT NULL,
            "expires_at" TIMESTAMPTZ NOT NULL,
            "used_at" TIMESTAMPTZ,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "password_reset_token_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "password_reset_token_user_id_fkey" FOREIGN KEY ("user_id")
              REFERENCES "user"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "password_reset_token_token_hash_key" UNIQUE ("token_hash")
        );

        CREATE INDEX IF NOT EXISTS password_reset_token_user_id_idx
          ON password_reset_token (user_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS password_reset_token;")
