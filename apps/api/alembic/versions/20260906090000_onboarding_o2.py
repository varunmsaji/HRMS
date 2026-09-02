"""Onboarding O2 — disable RLS on onboarding_token.

Corrective migration: the O1 migration (`20260905090000_onboarding_o1`) gave `onboarding_token`
the same `tenant_isolation` RLS policy as every other onboarding table, but that table is looked
up by a raw public caller who has no tenant context yet — the whole point of the token is to
*establish* a `company_id` for RLS to key off of, so a `FORCE ROW LEVEL SECURITY` policy on the
lookup table itself makes every row invisible before `app.company_id` can ever be set (an empty
GUC compares `NULL`, which the policy's `USING` clause treats as no match).

`refresh_token` (`scripts/sql/001_init_schema.sql`) already has exactly this shape — a
pre-tenant-context lookup table, no RLS — confirmed by re-reading that file before writing this
migration, not assumed. `onboarding_token` now matches it: `company_id` stays as a plain,
unenforced column (`hrms.modules.onboarding.models.OnboardingToken` docstring explains why it's
still useful, unenforced), everything else about the table is unchanged.

Revision ID: 20260906090000
Revises: 20260905090000
"""

from alembic import op

revision = "20260906090000"
down_revision = "20260905090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE onboarding_token NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE onboarding_token DISABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON onboarding_token;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE onboarding_token ENABLE ROW LEVEL SECURITY;
        ALTER TABLE onboarding_token FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON onboarding_token;
        CREATE POLICY tenant_isolation ON onboarding_token
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )
