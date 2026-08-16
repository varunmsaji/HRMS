"""Employee banking (E-08) — new table.

Per `docs/modules/employee/33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` §6/§19/§22.
`employee_bank` does not exist anywhere in the live schema or in any prior migration
(reconfirmed by direct inspection before writing this migration) — a genuine foundational
`CREATE TABLE`, following `20260815130000_employee_statutory.py`'s exact shape.

- The employee's own payout-account facts — keyed on `employee_id`, **not** `employment_id`
  (plan §6), effective-dated the same way as `employee_compensation`/`employee_statutory`. No FK
  to `employment` or `legal_entity` (plan §6).
- No `revision_reason` column — unlike Statutory, no source document requires one for Banking
  (plan §5/§13); this migration's DDL matches plan §6's literal target verbatim, with no added
  column.
- `employee_bank_no_overlap` (GiST exclusion constraint, mirroring `employee_statutory_
  no_overlap`) prevents two rows for the same employee from having overlapping
  `[effective_from, effective_to]` ranges — this is also what makes "at most one current row per
  employee" a database-level guarantee (plan §6), the concrete resolution of `is_primary`'s own
  structurally-vestigial status under this single-current-row design.
- Two indexes matching plan §6 exactly: `company_id` (tenant-scoped queries) and
  `(employee_id, effective_from)` (history/as-of lookups).
- RLS: `ENABLE`/`FORCE ROW LEVEL SECURITY` + a single `tenant_isolation` policy on `company_id`,
  matching every other Employee table's convention.
- `account_number_enc` is a plain, unencrypted `TEXT` column, same as `employee.pan_number_enc`/
  `aadhaar_number_enc` today — no encryption mechanism exists anywhere in this codebase
  (confirmed by direct search before writing this migration), and building one is explicitly
  out of this slice's scope (plan §23). This is `HRMS_SYSTEM_DESIGN_BASELINE.md` Decision D-2's
  Option 2 (documented, accepted deferral), not a silent gap — real account numbers must not be
  written here before that decision is revisited (plan §14/§22 PD-4).

Revision ID: 20260815140000
Revises: 20260815130000
"""

from alembic import op

revision = "20260815140000"
down_revision = "20260815130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_bank (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "effective_from" DATE NOT NULL,
            "effective_to" DATE,
            "account_holder_name" VARCHAR(150),
            "account_number_enc" TEXT,
            "bank_name" VARCHAR(150),
            "ifsc" VARCHAR(15),
            "branch_name" VARCHAR(150),
            "payment_mode" VARCHAR(10),
            "is_primary" BOOLEAN NOT NULL DEFAULT true,
            "verification_status" VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            "penny_drop_reference" VARCHAR(60),
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,
            "version" INTEGER NOT NULL DEFAULT 1,

            CONSTRAINT "employee_bank_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "employee_bank_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "employee_bank_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        ALTER TABLE employee_bank
          DROP CONSTRAINT IF EXISTS employee_bank_no_overlap;
        ALTER TABLE employee_bank
          ADD CONSTRAINT employee_bank_no_overlap
          EXCLUDE USING gist (
            employee_id WITH =,
            daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
          );

        CREATE INDEX IF NOT EXISTS employee_bank_company_id_idx
          ON employee_bank (company_id);
        CREATE INDEX IF NOT EXISTS employee_bank_employee_id_effective_from_idx
          ON employee_bank (employee_id, effective_from);

        ALTER TABLE employee_bank ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_bank FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee_bank;
        CREATE POLICY tenant_isolation ON employee_bank
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS employee_bank;
        """
    )
