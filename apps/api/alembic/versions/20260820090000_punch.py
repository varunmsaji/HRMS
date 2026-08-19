"""W4 (1/2) — new `punch` table.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §19/§27 and WD-11: immutable,
append-only raw IN/OUT events. No `updated_at` — mirrors `audit_log`, the only other insert-only
table in this codebase.

Partitioning ("PARTITION BY RANGE on local month... required before volume", §27) is deliberately
**not** implemented here — see decision log entry **WD-26**. Zero punch rows exist anywhere yet;
this ships as an ordinary RLS'd tenant table like every other table in this codebase, and
partitioning remains a valid additive migration once real volume exists.

Revision ID: 20260820090000
Revises: 20260819120000
"""

from alembic import op

revision = "20260820090000"
down_revision = "20260819120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS punch (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "punch_time" TIMESTAMPTZ NOT NULL,
            "direction" VARCHAR(10) NOT NULL,
            "source" VARCHAR(20) NOT NULL,
            "idempotency_key" VARCHAR(100),
            "recorded_by_user_id" UUID,
            "reference" VARCHAR(200),
            "raw_payload" JSONB,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "punch_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "punch_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "punch_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "punch_recorded_by_user_id_fkey" FOREIGN KEY ("recorded_by_user_id")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "punch_direction_check" CHECK (direction IN ('IN', 'OUT')),
            CONSTRAINT "punch_source_check"
              CHECK (source IN ('WEB', 'MOBILE', 'DEVICE', 'IMPORT', 'ADMIN', 'API'))
        );

        CREATE INDEX IF NOT EXISTS punch_company_id_idx ON punch (company_id);
        CREATE INDEX IF NOT EXISTS punch_employee_punch_time_idx
          ON punch (company_id, employee_id, punch_time);
        CREATE INDEX IF NOT EXISTS punch_company_punch_time_idx
          ON punch (company_id, punch_time);
        CREATE UNIQUE INDEX IF NOT EXISTS punch_company_idempotency_key_idx
          ON punch (company_id, idempotency_key)
          WHERE idempotency_key IS NOT NULL;

        ALTER TABLE punch ENABLE ROW LEVEL SECURITY;
        ALTER TABLE punch FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON punch;
        CREATE POLICY tenant_isolation ON punch
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS punch;")
