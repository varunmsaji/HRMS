"""Shift remediation: punch-ownership limits, recalculation queue, punch dismissal, swap expiry.

Revision ID: 20261115090000
Revises: 20261114090000

`docs/audits/SHIFT_REMEDIATION_PLAN_2026-11-15.md` §4. Purely additive; no existing row is
rewritten.

* `attendance_policy_version.max_early_punch_minutes` / `max_late_punch_minutes` — how far
  before a shift's start and after its end a punch may still belong to that shift (P-13, owner
  decision 15 Nov 2026: 240 / 720). Every existing version gets the defaults, so after deploy a
  punch up to 12h after shift end is attributed instead of being ignored past 2h.
* `attendance_recalc_request` — the durable impact queue (Invariant C): a change to a shift
  version, assignment, roster, swap or policy assignment records which employee-dates it can
  affect; a Celery task recalculates the open ones.
* `punch_dismissal` — HR marks an orphan punch (owned by no attendance day) as reviewed and not
  attendance, so it stops blocking period close. Punches stay immutable (WD-11).
* `shift_swap_request.status` gains `EXPIRED` (a pending swap whose date has passed).

Tenant isolation: FORCE row-level security on `company_id`, like every tenant table.
"""

from alembic import op

revision = "20261115090000"
down_revision = "20261114090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_policy_version
          ADD COLUMN IF NOT EXISTS max_early_punch_minutes INTEGER NOT NULL DEFAULT 240,
          ADD COLUMN IF NOT EXISTS max_late_punch_minutes INTEGER NOT NULL DEFAULT 720;
        ALTER TABLE attendance_policy_version
          DROP CONSTRAINT IF EXISTS attendance_policy_version_punch_window_check;
        ALTER TABLE attendance_policy_version
          ADD CONSTRAINT attendance_policy_version_punch_window_check CHECK (
            max_early_punch_minutes BETWEEN 0 AND 1440
            AND max_late_punch_minutes BETWEEN 0 AND 1440
          );

        CREATE TABLE IF NOT EXISTS attendance_recalc_request (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID,
            "shift_id" UUID,
            "date_from" DATE NOT NULL,
            "date_to" DATE NOT NULL,
            "reason" VARCHAR(40) NOT NULL,
            "source_entity_type" VARCHAR(40),
            "source_entity_id" UUID,
            "requested_by" UUID,
            "attempts" INTEGER NOT NULL DEFAULT 0,
            "last_error" TEXT,
            "processed_at" TIMESTAMPTZ,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT "attendance_recalc_request_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_recalc_request_company_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT,
            CONSTRAINT "attendance_recalc_request_employee_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id"),
            CONSTRAINT "attendance_recalc_request_shift_fkey" FOREIGN KEY ("shift_id")
              REFERENCES "shift"("id"),
            CONSTRAINT "attendance_recalc_request_requester_fkey" FOREIGN KEY ("requested_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_recalc_request_range_check" CHECK ("date_from" <= "date_to")
        );
        CREATE INDEX IF NOT EXISTS attendance_recalc_request_pending_idx
          ON attendance_recalc_request (company_id, created_at) WHERE processed_at IS NULL;
        ALTER TABLE attendance_recalc_request ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_recalc_request FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_recalc_request;
        CREATE POLICY tenant_isolation ON attendance_recalc_request
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS punch_dismissal (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "punch_id" UUID NOT NULL,
            "reason" TEXT NOT NULL,
            "dismissed_by" UUID,
            "dismissed_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT "punch_dismissal_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "punch_dismissal_company_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT,
            CONSTRAINT "punch_dismissal_punch_fkey" FOREIGN KEY ("punch_id")
              REFERENCES "punch"("id"),
            CONSTRAINT "punch_dismissal_dismisser_fkey" FOREIGN KEY ("dismissed_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "punch_dismissal_reason_check" CHECK (length(btrim("reason")) > 0)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS punch_dismissal_punch_idx
          ON punch_dismissal (company_id, punch_id);
        ALTER TABLE punch_dismissal ENABLE ROW LEVEL SECURITY;
        ALTER TABLE punch_dismissal FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON punch_dismissal;
        CREATE POLICY tenant_isolation ON punch_dismissal
          USING (company_id = current_setting('app.company_id', true)::uuid);

        ALTER TABLE shift_swap_request DROP CONSTRAINT IF EXISTS shift_swap_request_status_check;
        ALTER TABLE shift_swap_request ADD CONSTRAINT shift_swap_request_status_check
          CHECK ("status" IN ('PENDING', 'APPROVED', 'DECLINED', 'EXPIRED'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE shift_swap_request SET status = 'DECLINED' WHERE status = 'EXPIRED';
        ALTER TABLE shift_swap_request DROP CONSTRAINT IF EXISTS shift_swap_request_status_check;
        ALTER TABLE shift_swap_request ADD CONSTRAINT shift_swap_request_status_check
          CHECK ("status" IN ('PENDING', 'APPROVED', 'DECLINED'));
        DROP TABLE IF EXISTS punch_dismissal;
        DROP TABLE IF EXISTS attendance_recalc_request;
        ALTER TABLE attendance_policy_version
          DROP CONSTRAINT IF EXISTS attendance_policy_version_punch_window_check,
          DROP COLUMN IF EXISTS max_late_punch_minutes,
          DROP COLUMN IF EXISTS max_early_punch_minutes;
        """
    )
