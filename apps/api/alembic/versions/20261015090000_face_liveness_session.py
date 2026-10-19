"""Face attendance (4/n) — server-issued liveness challenges for face punching.

`face_liveness_session` — a short-lived, single-use challenge the server issues to one employee
for one punch direction before the app captures any frame. A face punch must present an ISSUED,
unexpired session of the same employee and direction; presenting it burns it (CONSUMED) in its
own committed transaction, whatever the outcome, so it can never be presented twice. Issuing a
new session marks any still-ISSUED one SUPERSEDED (at most one ISSUED per employee, partial
unique index). Expiry is read from `expires_at`; nothing sweeps.

`frame_digests` — SHA-256 of each submitted frame's bytes (not an image, not a biometric
template). A later session presenting a byte-identical frame is rejected as a replayed capture.

`face_verification_attempt` gains `liveness_session_id` (which challenge an attempt answered) and
the server-side liveness outcomes as decisions. 'LIVENESS_FAILED' stays valid for rows written
before this revision.

Revision ID: 20261015090000
Revises: 20261014091000
"""

from alembic import op

revision = "20261015090000"
down_revision = "20261014091000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS face_liveness_session (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "direction" VARCHAR(3) NOT NULL,
            "status" VARCHAR(20) NOT NULL,
            "issued_by_user_id" UUID,
            "issued_at" TIMESTAMPTZ NOT NULL,
            "expires_at" TIMESTAMPTZ NOT NULL,
            "consumed_at" TIMESTAMPTZ,
            "frame_digests" TEXT[] NOT NULL DEFAULT '{}',
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "face_liveness_session_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "face_liveness_session_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_liveness_session_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_liveness_session_issued_by_user_id_fkey"
              FOREIGN KEY ("issued_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "face_liveness_session_direction_check" CHECK (direction IN ('IN', 'OUT')),
            CONSTRAINT "face_liveness_session_status_check"
              CHECK (status IN ('ISSUED', 'CONSUMED', 'SUPERSEDED')),
            CONSTRAINT "face_liveness_session_expiry_check" CHECK (expires_at > issued_at),
            CONSTRAINT "face_liveness_session_consumed_consistency_check"
              CHECK ((status = 'CONSUMED') = (consumed_at IS NOT NULL))
        );

        CREATE INDEX IF NOT EXISTS face_liveness_session_company_id_idx
          ON face_liveness_session (company_id);
        CREATE INDEX IF NOT EXISTS face_liveness_session_employee_created_idx
          ON face_liveness_session (company_id, employee_id, created_at);
        CREATE INDEX IF NOT EXISTS face_liveness_session_frame_digests_idx
          ON face_liveness_session USING GIN (frame_digests);
        CREATE UNIQUE INDEX IF NOT EXISTS face_liveness_session_one_issued_idx
          ON face_liveness_session (company_id, employee_id) WHERE status = 'ISSUED';

        ALTER TABLE face_liveness_session ENABLE ROW LEVEL SECURITY;
        ALTER TABLE face_liveness_session FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON face_liveness_session;
        CREATE POLICY tenant_isolation ON face_liveness_session
          USING (company_id = current_setting('app.company_id', true)::uuid);

        ALTER TABLE face_verification_attempt
          ADD COLUMN IF NOT EXISTS "liveness_session_id" UUID;
        ALTER TABLE face_verification_attempt
          ADD CONSTRAINT "face_verification_attempt_liveness_session_id_fkey"
            FOREIGN KEY ("liveness_session_id") REFERENCES "face_liveness_session"("id")
            ON DELETE SET NULL;

        ALTER TABLE face_verification_attempt
          DROP CONSTRAINT face_verification_attempt_decision_check;
        ALTER TABLE face_verification_attempt
          ADD CONSTRAINT face_verification_attempt_decision_check
          CHECK (decision IN (
            'MATCHED', 'NO_MATCH', 'NO_FACE', 'LIVENESS_FAILED', 'NOT_ENROLLED',
            'PROVIDER_ERROR', 'SPOOF_SUSPECTED', 'LIVENESS_INCONCLUSIVE', 'LIVENESS_ERROR',
            'CHALLENGE_REJECTED', 'CAPTURE_REPLAYED'
          ));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        -- Keeps the audit rows (still failed attempts) under the closest older decision.
        UPDATE face_verification_attempt SET decision = 'LIVENESS_FAILED' WHERE decision IN (
          'SPOOF_SUSPECTED', 'LIVENESS_INCONCLUSIVE', 'LIVENESS_ERROR', 'CHALLENGE_REJECTED',
          'CAPTURE_REPLAYED'
        );
        ALTER TABLE face_verification_attempt
          DROP CONSTRAINT face_verification_attempt_decision_check;
        ALTER TABLE face_verification_attempt
          ADD CONSTRAINT face_verification_attempt_decision_check
          CHECK (decision IN (
            'MATCHED', 'NO_MATCH', 'NO_FACE', 'LIVENESS_FAILED', 'NOT_ENROLLED',
            'PROVIDER_ERROR'
          ));
        ALTER TABLE face_verification_attempt
          DROP CONSTRAINT IF EXISTS "face_verification_attempt_liveness_session_id_fkey",
          DROP COLUMN IF EXISTS "liveness_session_id";

        DROP TABLE IF EXISTS face_liveness_session;
        """
    )
