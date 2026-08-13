"""Plan and plan_feature tables — Task C-05 (docs/modules/company/03_Database_Design.md §4-5).

Global reference tables (no `company_id`, no RLS — shared platform catalogue, not tenant
data) defining the plan catalogue that `subscription` (C-06) will reference and that
plan-vs-override feature resolution (C-11) will read. Seed data is loaded separately via
`hrms/seed/plan_catalogue.py`, not this migration — seeds are data, not schema, per
docs/modules/company/03_Database_Design.md §4 / §8 step 4.

Revision ID: 20260807160000
Revises: 20260807150000
"""

from alembic import op

revision = "20260807160000"
down_revision = "20260807150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS plan (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(40) NOT NULL UNIQUE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS plan_feature (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_id UUID NOT NULL REFERENCES plan(id) ON DELETE RESTRICT,
            feature_code VARCHAR(60) NOT NULL,
            is_enabled BOOLEAN NOT NULL DEFAULT true,
            limit_value INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE (plan_id, feature_code)
        );

        CREATE INDEX IF NOT EXISTS plan_feature_plan_id_idx ON plan_feature (plan_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS plan_feature;
        DROP TABLE IF EXISTS plan;
        """
    )
