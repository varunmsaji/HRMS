"""Shift coverage target (`shift.min_staff`) and shift swap requests (`shift_swap_request`).

Revision ID: 20261106090000
Revises: 20261105090000

Purely additive. `shift.min_staff` is the minimum headcount a shift needs per day (NULL = no
target). `shift_swap_request` is a peer swap of two employees' shifts on one date; approving it
rewrites both roster rows. Tenant isolation: FORCE row-level security on `company_id`.
"""

from alembic import op

revision = "20261106090000"
down_revision = "20261105090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE shift ADD COLUMN IF NOT EXISTS min_staff INTEGER;
        ALTER TABLE shift DROP CONSTRAINT IF EXISTS shift_min_staff_check;
        ALTER TABLE shift ADD CONSTRAINT shift_min_staff_check
          CHECK (min_staff IS NULL OR min_staff >= 0);

        CREATE TABLE IF NOT EXISTS shift_swap_request (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "reference" VARCHAR(20) NOT NULL,
            "swap_date" DATE NOT NULL,
            "requester_employee_id" UUID NOT NULL,
            "counterpart_employee_id" UUID NOT NULL,
            "requester_shift_id" UUID NOT NULL,
            "counterpart_shift_id" UUID NOT NULL,
            "reason" TEXT,
            "status" VARCHAR(12) NOT NULL DEFAULT 'PENDING',
            "counterpart_consented" BOOLEAN NOT NULL DEFAULT false,
            "decided_by" UUID,
            "decided_at" TIMESTAMPTZ,
            "decision_note" TEXT,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT "shift_swap_request_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "shift_swap_request_company_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT,
            CONSTRAINT "shift_swap_request_requester_fkey" FOREIGN KEY ("requester_employee_id")
              REFERENCES "employee"("id"),
            CONSTRAINT "shift_swap_request_counterpart_fkey" FOREIGN KEY ("counterpart_employee_id")
              REFERENCES "employee"("id"),
            CONSTRAINT "shift_swap_request_requester_shift_fkey" FOREIGN KEY ("requester_shift_id")
              REFERENCES "shift"("id"),
            CONSTRAINT "shift_swap_request_counterpart_shift_fkey" FOREIGN KEY ("counterpart_shift_id")
              REFERENCES "shift"("id"),
            CONSTRAINT "shift_swap_request_decider_fkey" FOREIGN KEY ("decided_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "shift_swap_request_status_check"
              CHECK ("status" IN ('PENDING', 'APPROVED', 'DECLINED')),
            CONSTRAINT "shift_swap_request_distinct_check"
              CHECK ("requester_employee_id" <> "counterpart_employee_id")
        );

        CREATE INDEX IF NOT EXISTS shift_swap_request_company_status_idx
          ON shift_swap_request (company_id, status, swap_date);
        CREATE UNIQUE INDEX IF NOT EXISTS shift_swap_request_reference_idx
          ON shift_swap_request (company_id, reference);

        ALTER TABLE shift_swap_request ENABLE ROW LEVEL SECURITY;
        ALTER TABLE shift_swap_request FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON shift_swap_request;
        CREATE POLICY tenant_isolation ON shift_swap_request
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS shift_swap_request;
        ALTER TABLE shift DROP CONSTRAINT IF EXISTS shift_min_staff_check;
        ALTER TABLE shift DROP COLUMN IF EXISTS min_staff;
        """
    )
