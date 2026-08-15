"""Employee compensation (E-06) — `revision_type`/`revision_reason`.

Per `docs/modules/employee/17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md` §18. The live
`employee_compensation` table has existed since the very first migration
(`scripts/sql/001_init_schema.sql:279-293`) — RLS-forced, GiST no-overlap-constrained, FK-linked
to `employee.id` — and has zero rows at the time this migration was written (confirmed against
the dev database). It already carries every column the locked architecture record names as
load-bearing (`annual_ctc_minor`, `currency`, `effective_from`/`effective_to`, `version`); this
migration is purely additive, no backfill required.

- Two new columns: `revision_type` (`VARCHAR(20) NOT NULL DEFAULT 'JOINING'`), `revision_reason`
  (nullable `TEXT`). No `CHECK` constraint on `revision_type`'s value set — matches the
  established precedent (`employment.status`/`employee_assignment.change_type` are both
  Pydantic-`Literal`-validated only, not DB `CHECK`-constrained). The `DEFAULT` is safe only
  because the table has zero rows — it exists so the column can be declared `NOT NULL` in one
  statement with no separate backfill step.
- No new index — the live `employee_compensation_employee_id_effective_from_idx` and the GiST
  exclusion constraint already cover every query shape this slice's repository needs.
- No new FK — this slice adds no reference column.
- RLS re-asserted idempotently, matching every prior migration in this series.

Revision ID: 20260814120000
Revises: 20260814110000
"""

from alembic import op

revision = "20260814120000"
down_revision = "20260814110000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee_compensation
          ADD COLUMN IF NOT EXISTS revision_type VARCHAR(20) NOT NULL DEFAULT 'JOINING',
          ADD COLUMN IF NOT EXISTS revision_reason TEXT;

        ALTER TABLE employee_compensation ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_compensation FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee_compensation;
        CREATE POLICY tenant_isolation ON employee_compensation
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee_compensation
          DROP COLUMN IF EXISTS revision_reason,
          DROP COLUMN IF EXISTS revision_type;
        """
    )
