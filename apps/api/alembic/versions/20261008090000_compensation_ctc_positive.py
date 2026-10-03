"""Employee compensation — CTC must be strictly positive (DB backstop).

The API already rejects `annual_ctc_minor <= 0`; this CHECK is the local-invariant backstop so no
other write path can store one. Company-currency equality is a cross-table rule (the currency
lives on `company`), so it stays a service-layer rule rather than a DB constraint.

The migration refuses to run, with a clear message, if legacy rows with a non-positive CTC exist:
those need a human decision (correct or remove), not a silent rewrite.

Revision ID: 20261008090000
Revises: 20261007090000
"""

from alembic import op

revision = "20261008090000"
down_revision = "20261007090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE bad integer;
        BEGIN
            SELECT count(*) INTO bad FROM employee_compensation WHERE annual_ctc_minor <= 0;
            IF bad > 0 THEN
                RAISE EXCEPTION
                    'employee_compensation has % row(s) with annual_ctc_minor <= 0; correct them before migrating',
                    bad;
            END IF;
        END $$;
        """
    )
    op.execute(
        "ALTER TABLE employee_compensation "
        "ADD CONSTRAINT employee_compensation_ctc_positive CHECK (annual_ctc_minor > 0)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE employee_compensation DROP CONSTRAINT IF EXISTS employee_compensation_ctc_positive"
    )
