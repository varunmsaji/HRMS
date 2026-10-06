"""PAY-A03 — a database guard against paying the same arrear twice.

Arrears for an earlier month are legitimately paid more than once when the month is corrected
more than once (₹5,000 now, a further ₹2,000 after a second revision), so (employee, month,
component) cannot simply be unique. What cannot repeat is the *same* payment. Each arrears row
therefore carries the number of the payment it is — 1 for the first payment against an
(employee, source run, component), 2 for the next — taken from what had been paid when the run
computed it. Two runs prepared on the same state both claim number 1; when a run is finalised
its rows are stamped `applied_at`, and a partial unique index over the number lets only one
run's stamp stand. The other run's finalisation fails instead of paying twice.

Finalisation also serialises per legal entity (`core/db/locks.py`); this is the backstop for it.

- `pay_run_arrear.payment_number` — NOT NULL. Existing rows of FINALISED/PAID runs are numbered
  in finalisation order; rows of unfinalised runs get one more than the finalised rows for the
  same key. No data is changed or deleted, and every existing payment keeps a distinct number, so
  the index cannot conflict with existing data.
- `pay_run_arrear.applied_at` — NULL until the run is finalised; existing finalised rows take
  their run's `finalised_at`.
- Partial unique index over (company_id, employee_id, source_pay_run_id, component_code,
  payment_number) WHERE applied_at IS NOT NULL. `company_id` leads, so it is tenant-safe; the
  table's row-level-security policy is untouched.

Revision ID: 20261012090000
Revises: 20261011090000
"""

from alembic import op

revision = "20261012090000"
down_revision = "20261011090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE pay_run_arrear
          ADD COLUMN IF NOT EXISTS payment_number INTEGER CHECK (payment_number >= 1),
          ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ;

        UPDATE pay_run_arrear a
           SET payment_number = numbered.seq, applied_at = numbered.finalised_at
          FROM (
            SELECT ar.id, r.finalised_at,
                   row_number() OVER (
                     PARTITION BY ar.company_id, ar.employee_id, ar.source_pay_run_id,
                                  ar.component_code
                     ORDER BY r.finalised_at, ar.pay_run_id, ar.id
                   ) AS seq
              FROM pay_run_arrear ar
              JOIN pay_run r ON r.id = ar.pay_run_id
             WHERE r.status IN ('FINALISED', 'PAID')
          ) AS numbered
         WHERE a.id = numbered.id;

        UPDATE pay_run_arrear a
           SET payment_number = 1 + (
                 SELECT count(*) FROM pay_run_arrear o
                  WHERE o.company_id = a.company_id AND o.employee_id = a.employee_id
                    AND o.source_pay_run_id = a.source_pay_run_id
                    AND o.component_code = a.component_code AND o.applied_at IS NOT NULL
               )
         WHERE a.payment_number IS NULL;

        ALTER TABLE pay_run_arrear ALTER COLUMN payment_number SET NOT NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS pay_run_arrear_applied_uq
          ON pay_run_arrear (company_id, employee_id, source_pay_run_id, component_code,
                             payment_number)
          WHERE applied_at IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS pay_run_arrear_applied_uq;
        ALTER TABLE pay_run_arrear DROP COLUMN IF EXISTS applied_at,
                                   DROP COLUMN IF EXISTS payment_number;
        """
    )
