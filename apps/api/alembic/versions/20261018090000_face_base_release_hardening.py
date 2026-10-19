"""Face attendance (6/n) — base-release hardening: enrollment lease + deletion outbox.

1. `face_enrollment_window.submission_token` / `submission_started_at` — a lease taken (and
   committed) before a self-enrollment submission starts its slow provider calls. It replaces
   holding a `FOR UPDATE` row lock and an open transaction across ~18 Face++ requests: a second
   submission sees a live lease and is refused, and the finalising transaction checks the token
   is still the window's, so a window cancelled / reopened / superseded in the meantime is
   detected and the provider work is compensated. A lease past `FACE_ENROLLMENT_LEASE_SECONDS`
   is ignored, so a crashed worker can never wedge an employee.
2. `face_external_deletion` — a transactional outbox of external biometric resources (a Face++
   FaceSet, a stored review photo) that must be deleted. A row is written in the SAME
   transaction that authorises the deletion (approve / reject / revoke), so nothing external is
   touched before that transaction commits; a worker deletes after commit and retries with
   back-off. The row holds only the opaque provider id or the object key (random UUIDs) — no
   image, no personal data. Unique per (company, kind, resource) so enqueueing is idempotent.

Reversible: the downgrade drops both. Unlike 20261017090000 it discards no existing data except
outbox rows, which would then never be retried (see the base-release runbook, section 6).

Revision ID: 20261018090000
Revises: 20261017090000
"""

from alembic import op

revision = "20261018090000"
down_revision = "20261017090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE face_enrollment_window
          ADD COLUMN IF NOT EXISTS "submission_token" UUID,
          ADD COLUMN IF NOT EXISTS "submission_started_at" TIMESTAMPTZ;
        ALTER TABLE face_enrollment_window
          ADD CONSTRAINT "face_enrollment_window_submission_consistency_check"
          CHECK ((submission_token IS NULL) = (submission_started_at IS NULL));

        CREATE TABLE IF NOT EXISTS face_external_deletion (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "kind" VARCHAR(20) NOT NULL,
            "provider" VARCHAR(20),
            "resource_ref" VARCHAR(300) NOT NULL,
            "reason" VARCHAR(30) NOT NULL,
            "status" VARCHAR(10) NOT NULL DEFAULT 'PENDING',
            "attempts" INTEGER NOT NULL DEFAULT 0,
            "last_error_code" VARCHAR(64),
            "next_attempt_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "completed_at" TIMESTAMPTZ,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "face_external_deletion_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "face_external_deletion_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_external_deletion_kind_check"
              CHECK (kind IN ('PROVIDER_PERSON', 'REVIEW_PHOTO')),
            CONSTRAINT "face_external_deletion_status_check"
              CHECK (status IN ('PENDING', 'DONE', 'SKIPPED')),
            CONSTRAINT "face_external_deletion_reason_check" CHECK (reason IN (
              'APPROVED', 'REJECTED', 'REVOKED', 'ENROLLMENT_COMPENSATION'
            )),
            CONSTRAINT "face_external_deletion_unique_resource"
              UNIQUE (company_id, kind, resource_ref)
        );

        CREATE INDEX IF NOT EXISTS face_external_deletion_company_id_idx
          ON face_external_deletion (company_id);
        CREATE INDEX IF NOT EXISTS face_external_deletion_due_idx
          ON face_external_deletion (next_attempt_at) WHERE status = 'PENDING';

        ALTER TABLE face_external_deletion ENABLE ROW LEVEL SECURITY;
        ALTER TABLE face_external_deletion FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON face_external_deletion;
        CREATE POLICY tenant_isolation ON face_external_deletion
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS face_external_deletion;
        ALTER TABLE face_enrollment_window
          DROP CONSTRAINT IF EXISTS "face_enrollment_window_submission_consistency_check",
          DROP COLUMN IF EXISTS "submission_started_at",
          DROP COLUMN IF EXISTS "submission_token";
        """
    )
