"""Face attendance (2/n) — HR-opened, one-time self-enrollment windows + HR approval.

HR opens a `face_enrollment_window` for one employee (48h by default); the employee captures
their own face in the mobile app while it is OPEN; a successful submission marks it USED, so it
can never be reused. A window past `expires_at` is treated as expired without needing a sweep —
it is flipped to EXPIRED lazily the next time HR opens a new one for that employee. At most one
OPEN window per employee (partial unique index).

A submitted profile is `PENDING_APPROVAL` until HR approves (-> ENROLLED) or rejects
(-> REJECTED). Only ENROLLED profiles can punch. The straight-on capture is kept in object
storage (`review_photo_key`) solely so HR can compare it against the employee, and is deleted
on approval, rejection, or revocation.

Revision ID: 20261006090000
Revises: 20261005090000
"""

from alembic import op

revision = "20261006090000"
down_revision = "20261005090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS face_enrollment_window (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "status" VARCHAR(20) NOT NULL,
            "opened_by_user_id" UUID,
            "opened_at" TIMESTAMPTZ NOT NULL,
            "expires_at" TIMESTAMPTZ NOT NULL,
            "used_at" TIMESTAMPTZ,
            "cancelled_at" TIMESTAMPTZ,
            "cancelled_by_user_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "face_enrollment_window_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "face_enrollment_window_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_enrollment_window_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_enrollment_window_opened_by_user_id_fkey"
              FOREIGN KEY ("opened_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "face_enrollment_window_cancelled_by_user_id_fkey"
              FOREIGN KEY ("cancelled_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "face_enrollment_window_status_check"
              CHECK (status IN ('OPEN', 'USED', 'CANCELLED', 'EXPIRED')),
            CONSTRAINT "face_enrollment_window_expiry_check" CHECK (expires_at > opened_at),
            CONSTRAINT "face_enrollment_window_used_consistency_check"
              CHECK ((status = 'USED') = (used_at IS NOT NULL))
        );

        CREATE INDEX IF NOT EXISTS face_enrollment_window_company_id_idx
          ON face_enrollment_window (company_id);
        CREATE UNIQUE INDEX IF NOT EXISTS face_enrollment_window_one_open_idx
          ON face_enrollment_window (company_id, employee_id) WHERE status = 'OPEN';

        ALTER TABLE face_enrollment_window ENABLE ROW LEVEL SECURITY;
        ALTER TABLE face_enrollment_window FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON face_enrollment_window;
        CREATE POLICY tenant_isolation ON face_enrollment_window
          USING (company_id = current_setting('app.company_id', true)::uuid);

        ALTER TABLE employee_face_profile DROP CONSTRAINT employee_face_profile_status_check;
        ALTER TABLE employee_face_profile ADD CONSTRAINT employee_face_profile_status_check
          CHECK (status IN ('PENDING_APPROVAL', 'ENROLLED', 'REJECTED', 'REVOKED'));

        ALTER TABLE employee_face_profile
          ADD COLUMN IF NOT EXISTS "enrollment_window_id" UUID,
          ADD COLUMN IF NOT EXISTS "review_photo_key" VARCHAR(300),
          ADD COLUMN IF NOT EXISTS "reviewed_at" TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS "reviewed_by_user_id" UUID,
          ADD COLUMN IF NOT EXISTS "review_note" VARCHAR(500);

        ALTER TABLE employee_face_profile
          ADD CONSTRAINT "employee_face_profile_enrollment_window_id_fkey"
            FOREIGN KEY ("enrollment_window_id") REFERENCES "face_enrollment_window"("id")
            ON DELETE SET NULL,
          ADD CONSTRAINT "employee_face_profile_reviewed_by_user_id_fkey"
            FOREIGN KEY ("reviewed_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
          ADD CONSTRAINT "employee_face_profile_review_photo_only_pending_check"
            CHECK (review_photo_key IS NULL OR status = 'PENDING_APPROVAL');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee_face_profile
          DROP CONSTRAINT IF EXISTS "employee_face_profile_review_photo_only_pending_check",
          DROP CONSTRAINT IF EXISTS "employee_face_profile_reviewed_by_user_id_fkey",
          DROP CONSTRAINT IF EXISTS "employee_face_profile_enrollment_window_id_fkey",
          DROP COLUMN IF EXISTS "review_note",
          DROP COLUMN IF EXISTS "reviewed_by_user_id",
          DROP COLUMN IF EXISTS "reviewed_at",
          DROP COLUMN IF EXISTS "review_photo_key",
          DROP COLUMN IF EXISTS "enrollment_window_id";

        ALTER TABLE employee_face_profile DROP CONSTRAINT employee_face_profile_status_check;
        ALTER TABLE employee_face_profile ADD CONSTRAINT employee_face_profile_status_check
          CHECK (status IN ('ENROLLED', 'REVOKED'));

        DROP TABLE IF EXISTS face_enrollment_window;
        """
    )
