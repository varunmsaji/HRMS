"""Face attendance (5/n) — enrollment attempt log, per-frame identity decisions, provider-body
minimisation.

1. `face_enrollment_attempt` — one row per *rejected* self-enrollment submission (decision, the
   angle that failed, window, requester). No image, no score, no provider data. The window id is
   deliberately NOT a foreign key: the rejection is written in its own transaction while the
   submitting request still holds `FOR UPDATE` on the window row, and a foreign key would make
   that insert wait on the lock its own request holds.
2. `face_verification_attempt.decision` gains `AMBIGUOUS_FACE` (provider saw several faces in a
   frame) and `IDENTITY_INCONSISTENT` (some frames matched the enrolled employee, another did
   not).
3. Existing `face_verification_attempt.provider_response` rows stored the raw Face++ search body
   under `verify` (face tokens, rectangles, thresholds). It is replaced by the minimal shape the
   application now writes: `{"identity": {"legacy_redacted": true, "request_id": ...}}`. THIS
   PART IS IRREVERSIBLE: the downgrade restores the schema, not the discarded bodies. Liveness
   metadata in the same JSON is kept.

Revision ID: 20261017090000
Revises: 20261015090000
"""

from alembic import op

revision = "20261017090000"
down_revision = "20261015090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS face_enrollment_attempt (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "enrollment_window_id" UUID NOT NULL,
            "decision" VARCHAR(30) NOT NULL,
            "angle" VARCHAR(10),
            "actor_user_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "face_enrollment_attempt_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "face_enrollment_attempt_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_enrollment_attempt_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_enrollment_attempt_actor_user_id_fkey" FOREIGN KEY ("actor_user_id")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "face_enrollment_attempt_decision_check" CHECK (decision IN (
              'SPOOF_SUSPECTED', 'LIVENESS_INCONCLUSIVE', 'NO_FACE', 'MULTIPLE_FACES',
              'ANGLE_MISMATCH', 'INVALID_IMAGE', 'LIVENESS_ERROR', 'PROVIDER_ERROR'
            )),
            CONSTRAINT "face_enrollment_attempt_angle_check"
              CHECK (angle IS NULL OR angle IN ('front', 'left', 'right', 'up', 'down'))
        );

        CREATE INDEX IF NOT EXISTS face_enrollment_attempt_company_id_idx
          ON face_enrollment_attempt (company_id);
        CREATE INDEX IF NOT EXISTS face_enrollment_attempt_window_idx
          ON face_enrollment_attempt (company_id, employee_id, enrollment_window_id);
        CREATE INDEX IF NOT EXISTS face_enrollment_attempt_created_idx
          ON face_enrollment_attempt (created_at);

        ALTER TABLE face_enrollment_attempt ENABLE ROW LEVEL SECURITY;
        ALTER TABLE face_enrollment_attempt FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON face_enrollment_attempt;
        CREATE POLICY tenant_isolation ON face_enrollment_attempt
          USING (company_id = current_setting('app.company_id', true)::uuid);

        -- Retention cleanup selects by age.
        CREATE INDEX IF NOT EXISTS face_liveness_session_created_at_idx
          ON face_liveness_session (created_at);
        CREATE INDEX IF NOT EXISTS face_verification_attempt_created_at_idx
          ON face_verification_attempt (created_at);

        ALTER TABLE face_verification_attempt
          DROP CONSTRAINT face_verification_attempt_decision_check;
        ALTER TABLE face_verification_attempt
          ADD CONSTRAINT face_verification_attempt_decision_check
          CHECK (decision IN (
            'MATCHED', 'NO_MATCH', 'NO_FACE', 'LIVENESS_FAILED', 'NOT_ENROLLED',
            'PROVIDER_ERROR', 'SPOOF_SUSPECTED', 'LIVENESS_INCONCLUSIVE', 'LIVENESS_ERROR',
            'CHALLENGE_REJECTED', 'CAPTURE_REPLAYED', 'AMBIGUOUS_FACE', 'IDENTITY_INCONSISTENT'
          ));

        -- Irreversible minimisation of Face++ search bodies already stored (see docstring).
        UPDATE face_verification_attempt
        SET provider_response = (provider_response - 'verify') || jsonb_build_object(
          'identity', jsonb_build_object(
            'legacy_redacted', true,
            'request_id', provider_response -> 'verify' ->> 'request_id'
          )
        )
        WHERE provider_response ? 'verify';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        -- Keeps the audit rows (still failed attempts) under the closest older decision.
        UPDATE face_verification_attempt SET decision = 'NO_MATCH'
          WHERE decision IN ('AMBIGUOUS_FACE', 'IDENTITY_INCONSISTENT');
        ALTER TABLE face_verification_attempt
          DROP CONSTRAINT face_verification_attempt_decision_check;
        ALTER TABLE face_verification_attempt
          ADD CONSTRAINT face_verification_attempt_decision_check
          CHECK (decision IN (
            'MATCHED', 'NO_MATCH', 'NO_FACE', 'LIVENESS_FAILED', 'NOT_ENROLLED',
            'PROVIDER_ERROR', 'SPOOF_SUSPECTED', 'LIVENESS_INCONCLUSIVE', 'LIVENESS_ERROR',
            'CHALLENGE_REJECTED', 'CAPTURE_REPLAYED'
          ));

        DROP INDEX IF EXISTS face_verification_attempt_created_at_idx;
        DROP INDEX IF EXISTS face_liveness_session_created_at_idx;
        DROP TABLE IF EXISTS face_enrollment_attempt;
        """
    )
