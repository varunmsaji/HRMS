"""Tenant-scoped history of onboarding invitations HR approved and sent.

Revision ID: 20261028090000
Revises: 20261027092000

Adds `onboarding_message` (one row per invitation send): the approved subject, a plain-text body
with the credential-bearing link REDACTED, who sent it and when, and `outbox_message_key` linking to
`email_outbox.message_id`. No delivery status column - status is read from the outbox row so the two
cannot diverge. `send_request_id` (client-generated per compose session) makes a duplicate HTTP
send return the first result instead of issuing a second token; unique per case when present.

Tenant ownership: `company_id` + FORCE ROW LEVEL SECURITY with the same `tenant_isolation` policy
as every other onboarding table. No GRANT here: the cluster's default privileges already give
`hrms_app` DML on tables the schema owner creates (same as 20261027090000).

The case FK cascades: history belongs to its case (cases are soft-deleted in the app; a hard
delete is an operator/test action).

Downgrade drops the table (and with it the invitation history; outbox rows and tokens are
untouched). Additive and independent of existing tables' rows - no backfill needed.
"""

from alembic import op

revision = "20261028090000"
down_revision = "20261027092000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE onboarding_message (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          company_id UUID NOT NULL REFERENCES company(id) ON DELETE RESTRICT ON UPDATE CASCADE,
          onboarding_case_id UUID NOT NULL
            REFERENCES onboarding_case(id) ON DELETE CASCADE ON UPDATE CASCADE,
          message_type VARCHAR(30) NOT NULL DEFAULT 'INVITATION',
          recipient_email VARCHAR(320) NOT NULL,
          subject TEXT NOT NULL,
          rendered_text_body TEXT NOT NULL,
          created_by_user_id UUID NOT NULL
            REFERENCES "user"(id) ON DELETE RESTRICT ON UPDATE CASCADE,
          outbox_message_key VARCHAR(200),
          send_request_id UUID,
          queued_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT onboarding_message_type_check CHECK (message_type IN ('INVITATION'))
        );

        CREATE INDEX onboarding_message_company_idx ON onboarding_message (company_id);
        CREATE INDEX onboarding_message_case_idx
          ON onboarding_message (onboarding_case_id, created_at DESC);
        CREATE UNIQUE INDEX onboarding_message_send_request_key
          ON onboarding_message (onboarding_case_id, send_request_id)
          WHERE send_request_id IS NOT NULL;

        ALTER TABLE onboarding_message ENABLE ROW LEVEL SECURITY;
        ALTER TABLE onboarding_message FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON onboarding_message
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS onboarding_message;")
