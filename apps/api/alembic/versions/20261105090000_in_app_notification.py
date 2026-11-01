"""Generic in-app notification feed: `notification`.

Revision ID: 20261105090000
Revises: 20261104090000

A new, purely additive table (no existing table or row is touched). One row = one notification for
one recipient user in one company. `type` is plain text so new notification types need no schema
change; `dedupe_key` + a partial unique index make a business event notify a recipient at most once.
Tenant isolation: FORCE row-level security on `company_id`, like every other tenant table.
"""

from alembic import op

revision = "20261105090000"
down_revision = "20261104090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notification (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "recipient_user_id" UUID NOT NULL,
            "type" VARCHAR(64) NOT NULL,
            "category" VARCHAR(32) NOT NULL,
            "priority" VARCHAR(16) NOT NULL DEFAULT 'NORMAL',
            "title" VARCHAR(200) NOT NULL,
            "body" TEXT NOT NULL,
            "entity_type" VARCHAR(64),
            "entity_id" UUID,
            "action_url" VARCHAR(500),
            "action_label" VARCHAR(80),
            "metadata" JSONB NOT NULL DEFAULT '{}'::jsonb,
            "dedupe_key" VARCHAR(200),
            "read_at" TIMESTAMPTZ,
            "dismissed_at" TIMESTAMPTZ,
            "expires_at" TIMESTAMPTZ,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT "notification_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "notification_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "notification_recipient_fkey" FOREIGN KEY ("recipient_user_id")
              REFERENCES "user"("id") ON DELETE CASCADE,
            CONSTRAINT "notification_priority_check"
              CHECK ("priority" IN ('LOW', 'NORMAL', 'HIGH'))
        );

        CREATE INDEX IF NOT EXISTS notification_company_id_idx ON notification (company_id);
        -- Feed: newest first, per recipient.
        CREATE INDEX IF NOT EXISTS notification_feed_idx
          ON notification (company_id, recipient_user_id, created_at DESC, id DESC)
          WHERE dismissed_at IS NULL;
        -- Unread badge count.
        CREATE INDEX IF NOT EXISTS notification_unread_idx
          ON notification (company_id, recipient_user_id)
          WHERE read_at IS NULL AND dismissed_at IS NULL;
        -- One notification per business event per recipient.
        CREATE UNIQUE INDEX IF NOT EXISTS notification_dedupe_idx
          ON notification (company_id, recipient_user_id, dedupe_key)
          WHERE dedupe_key IS NOT NULL;

        ALTER TABLE notification ENABLE ROW LEVEL SECURITY;
        ALTER TABLE notification FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON notification;
        CREATE POLICY tenant_isolation ON notification
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notification;")
