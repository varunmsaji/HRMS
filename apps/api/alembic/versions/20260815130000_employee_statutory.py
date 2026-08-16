"""Employee statutory (E-07) — new table.

Per `docs/modules/employee/29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` §7/§20/§25.
`employee_statutory` does not exist anywhere in the live schema or in any prior migration
(reconfirmed by direct `psql` inspection, plan §4) — this is a genuine foundational `CREATE
TABLE`, not an additive `ALTER TABLE` against a pre-existing skeleton (unlike
`20260814120000_employee_compensation.py`), so this migration follows the shape of
`20260813180000_employee_foundation.py` instead.

- The employee's own PF/ESI/PT/LWF applicability flags and identifiers, plus tax-regime
  election — keyed on `employee_id`, **not** `employment_id` (plan §7/§8), effective-dated the
  same way as `employee_assignment`/`employee_compensation`. No FK to `employment` or
  `legal_entity` — both are read-only, indirectly resolved contexts, never stored redundantly
  (plan §8).
- `revision_reason` is one column beyond plan §7's literal DDL — added per plan §16/§27 item 7
  ("`revision_reason` required on every write... audit-trail parity with Compensation"), which
  requires a persisted column to be visible in `StatutoryRead`/the audit trail, mirroring
  `employee_compensation.revision_reason` exactly. Named explicitly here since it is the one
  deviation from plan §7's DDL as literally written; every other column matches verbatim.
- `employee_statutory_no_overlap` (GiST exclusion constraint, mirroring `employee_compensation_
  no_overlap`) prevents two rows for the same employee from having overlapping
  `[effective_from, effective_to]` ranges.
- Two indexes matching plan §7 exactly: `company_id` (tenant-scoped queries) and
  `(employee_id, effective_from)` (history/as-of lookups).
- RLS: `ENABLE`/`FORCE ROW LEVEL SECURITY` + a single `tenant_isolation` policy on `company_id`,
  matching every other Employee table's convention.

Revision ID: 20260815130000
Revises: 20260815120000
"""

from alembic import op

revision = "20260815130000"
down_revision = "20260815120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_statutory (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "effective_from" DATE NOT NULL,
            "effective_to" DATE,
            "is_pf_applicable" BOOLEAN NOT NULL DEFAULT false,
            "pf_number" VARCHAR(30),
            "pf_wage_ceiling_opt_out" BOOLEAN NOT NULL DEFAULT false,
            "vpf_amount" BIGINT,
            "vpf_percentage" NUMERIC(9,4),
            "is_esi_applicable" BOOLEAN NOT NULL DEFAULT false,
            "esi_ip_number" VARCHAR(30),
            "pt_state_code" VARCHAR(10),
            "is_lwf_applicable" BOOLEAN NOT NULL DEFAULT false,
            "tax_regime" VARCHAR(10),
            "is_director" BOOLEAN NOT NULL DEFAULT false,
            "is_international_worker" BOOLEAN NOT NULL DEFAULT false,
            "revision_reason" TEXT,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,
            "version" INTEGER NOT NULL DEFAULT 1,

            CONSTRAINT "employee_statutory_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "employee_statutory_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "employee_statutory_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        ALTER TABLE employee_statutory
          DROP CONSTRAINT IF EXISTS employee_statutory_no_overlap;
        ALTER TABLE employee_statutory
          ADD CONSTRAINT employee_statutory_no_overlap
          EXCLUDE USING gist (
            employee_id WITH =,
            daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
          );

        CREATE INDEX IF NOT EXISTS employee_statutory_company_id_idx
          ON employee_statutory (company_id);
        CREATE INDEX IF NOT EXISTS employee_statutory_employee_id_effective_from_idx
          ON employee_statutory (employee_id, effective_from);

        ALTER TABLE employee_statutory ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_statutory FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee_statutory;
        CREATE POLICY tenant_isolation ON employee_statutory
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS employee_statutory;
        """
    )
