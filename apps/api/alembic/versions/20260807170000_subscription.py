"""Subscription table — Task C-06 (docs/modules/company/03_Database_Design.md §6).

New tenant-scoped table connecting a `company` to a `plan`. RLS enabled inline in this
migration, per the pattern established in `alembic/versions/20260803200000_b1_auth_audit.py`
(`audit_log`) — the standalone RLS SQL script is not invoked by any migration and must not
be treated as the live RLS registry. Depends on `plan` (Task C-05) as an FK target.

The partial unique index on `company_id` (excluding `CANCELED`/`EXPIRED` rows) enforces
"at most one live subscription per company" (docs/modules/company/02_Domain_Model.md §5.9).

Revision ID: 20260807170000
Revises: 20260807160000
"""

from alembic import op

revision = "20260807170000"
down_revision = "20260807160000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL
              REFERENCES company(id) ON DELETE RESTRICT ON UPDATE CASCADE,
            plan_id UUID NOT NULL REFERENCES plan(id) ON DELETE RESTRICT,
            status VARCHAR(20) NOT NULL DEFAULT 'TRIALING'
              CHECK (status IN ('TRIALING','ACTIVE','PAST_DUE','CANCELED','EXPIRED')),
            current_period_start TIMESTAMPTZ,
            current_period_end TIMESTAMPTZ,
            trial_ends_at TIMESTAMPTZ,
            canceled_at TIMESTAMPTZ,
            seat_limit_override INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL,
            deleted_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS subscription_company_id_idx ON subscription (company_id);
        CREATE INDEX IF NOT EXISTS subscription_plan_id_idx ON subscription (plan_id);
        CREATE UNIQUE INDEX IF NOT EXISTS subscription_company_live_uidx
          ON subscription (company_id)
          WHERE status NOT IN ('CANCELED','EXPIRED');

        ALTER TABLE subscription ENABLE ROW LEVEL SECURITY;
        ALTER TABLE subscription FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON subscription;
        CREATE POLICY tenant_isolation ON subscription
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS subscription;")
