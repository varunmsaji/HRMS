"""Leave — `reserve_balance_on_submission` on `leave_policy_version`.

Per `docs/architecture/LEAVE_DECISION_LOG.md` LD-15: the client spec (§8 Leave Balance
Calculation) wants Available Balance and Reserved/Pending Balance shown separately, with
whether a submitted-but-not-yet-resolved application actually reserves balance being a
per-policy configuration, not a hardcoded rule. Reserved balance itself needs no new column
anywhere — it's derived live from `leave_application` rows still in `SUBMITTED` status (LD-15) —
this migration only adds the toggle that controls whether `submit()` treats those pending
applications as blocking further balance.

Defaults to `false` — preserves today's exact behavior (pending never reserves) for every
existing policy version, matching this codebase's "off until explicitly turned on" convention
for every other such flag (`allow_negative_balance`, and originally `sandwich_rule_enabled`
before LD-06 flipped its default).

Revision ID: 20260910090000
Revises: 20260909090000
"""

from alembic import op

revision = "20260910090000"
down_revision = "20260909090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_policy_version
          ADD COLUMN IF NOT EXISTS reserve_balance_on_submission BOOLEAN NOT NULL DEFAULT false;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_policy_version
          DROP COLUMN IF EXISTS reserve_balance_on_submission;
        """
    )
