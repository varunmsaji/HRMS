"""Payroll Phase 5.6 — income tax (TDS), new regime only (`docs/modules/payroll/
00_PAYROLL_IMPLEMENTATION_PLAN.md`, FR-PAY-011).

No new table: TDS reuses `statutory_rate` as a fifth national scheme (`state_code` NULL, like
`PF`/`ESI`) — effective-dated slab data, seeded unverified, verified by compliance before a run
using it can be approved, exactly the existing PF/ESI/PT/LWF shape. This migration only widens the
two CHECK constraints that named the four original schemes explicitly; `statutory_rate_no_overlap`
(the GiST exclusion) already keys on `scheme` generically and needs no change.

Revision ID: 20261004110000
Revises: 20261004109000
"""

from alembic import op

revision = "20261004110000"
down_revision = "20261004109000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE statutory_rate DROP CONSTRAINT statutory_rate_scheme_check;
        ALTER TABLE statutory_rate ADD CONSTRAINT statutory_rate_scheme_check CHECK (
          scheme IN ('PF', 'ESI', 'PT', 'LWF', 'TDS')
        );

        ALTER TABLE statutory_rate DROP CONSTRAINT statutory_rate_state_check;
        ALTER TABLE statutory_rate ADD CONSTRAINT statutory_rate_state_check CHECK (
          (scheme IN ('PF', 'ESI', 'TDS')) = (state_code IS NULL)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM statutory_rate WHERE scheme = 'TDS';

        ALTER TABLE statutory_rate DROP CONSTRAINT statutory_rate_state_check;
        ALTER TABLE statutory_rate ADD CONSTRAINT statutory_rate_state_check CHECK (
          (scheme IN ('PF', 'ESI')) = (state_code IS NULL)
        );

        ALTER TABLE statutory_rate DROP CONSTRAINT statutory_rate_scheme_check;
        ALTER TABLE statutory_rate ADD CONSTRAINT statutory_rate_scheme_check CHECK (
          scheme IN ('PF', 'ESI', 'PT', 'LWF')
        );
        """
    )
