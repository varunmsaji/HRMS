"""Transactional e-mail outbox: one row per logical outgoing message, written in the business transaction.

Revision ID: 20261027090000
Revises: 20261026090000

`email_outbox` is the durable hand-over between a business transaction and e-mail delivery (B13
Workstream A). The row is inserted in the SAME transaction as the business change, so a rollback
removes it and a crash after commit cannot lose it; a Celery worker claims due rows, sends with no
database transaction open, and records the outcome. `message_id` is the stable key of the logical
message (UNIQUE): enqueueing the same key twice stores one row.

Tenant-free like `email_log` (the worker has no tenant context), so no RLS; it holds message bodies
(single-use links) only until the message is `SENT` or `FAILED`, when the bodies are blanked. No
database GRANT is issued here: the cluster's default privileges already give `hrms_app` DML on tables
created by the owner role. Downgrade drops the table (undelivered messages are lost - drain first).
"""

# ruff: noqa: E501 - long SQL / diagnostic strings

from alembic import op

revision = "20261027090000"
down_revision = "20261026090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE email_outbox (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          message_id VARCHAR(200) NOT NULL,
          company_id UUID,
          kind VARCHAR(80) NOT NULL,
          failure_kind VARCHAR(80) NOT NULL,
          context JSONB NOT NULL DEFAULT '{}'::jsonb,
          recipient VARCHAR(320) NOT NULL,
          subject TEXT NOT NULL,
          text_body TEXT,
          html_body TEXT,
          status VARCHAR(10) NOT NULL DEFAULT 'PENDING',
          attempts INTEGER NOT NULL DEFAULT 0,
          max_attempts INTEGER NOT NULL DEFAULT 6,
          next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          locked_by VARCHAR(64),
          locked_until TIMESTAMPTZ,
          last_attempt_at TIMESTAMPTZ,
          last_failure_class VARCHAR(40),
          last_error_type VARCHAR(80),
          request_id VARCHAR(64),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          sent_at TIMESTAMPTZ,
          failed_at TIMESTAMPTZ,
          CONSTRAINT email_outbox_message_id_key UNIQUE (message_id),
          CONSTRAINT email_outbox_status_check
            CHECK (status IN ('PENDING', 'SENDING', 'SENT', 'FAILED')),
          CONSTRAINT email_outbox_attempts_check CHECK (attempts >= 0 AND max_attempts >= 1),
          CONSTRAINT email_outbox_sent_at_check CHECK (status <> 'SENT' OR sent_at IS NOT NULL),
          CONSTRAINT email_outbox_failed_at_check CHECK (status <> 'FAILED' OR failed_at IS NOT NULL),
          CONSTRAINT email_outbox_lease_check
            CHECK (status <> 'SENDING' OR (locked_by IS NOT NULL AND locked_until IS NOT NULL))
        );
        CREATE INDEX email_outbox_due_idx ON email_outbox (next_attempt_at) WHERE status = 'PENDING';
        CREATE INDEX email_outbox_lease_idx ON email_outbox (locked_until) WHERE status = 'SENDING';
        CREATE INDEX email_outbox_company_idx ON email_outbox (company_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE email_outbox;")
