"""Period grain, step 3 — attendance periods per legal entity
(`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 14: payroll is run per legal entity, since
PF/ESI/TDS are filed per entity).

- `attendance_period.legal_entity_id` becomes required. Existing periods are backfilled with their
  company's legal entity when the company has exactly one (the only case where a company-wide
  period has an unambiguous owner). If any existing period belongs to a company with several legal
  entities, the migration stops rather than guess — split or delete those periods first. Check
  before deploying:

      SELECT p.company_id, count(*) FROM attendance_period p
      WHERE (SELECT count(*) FROM legal_entity le
             WHERE le.company_id = p.company_id AND le.deleted_at IS NULL) <> 1
      GROUP BY p.company_id;

- The no-overlap exclusion moves from `(company_id, range)` to
  `(company_id, legal_entity_id, range)`: each legal entity runs its own cycle.
- `attendance_day.locked_period_id` — the period whose finalize locked the day. Reopen now unlocks
  exactly those days instead of every day in the date range (which would also unlock another legal
  entity's closed days). Backfilled for already-locked days from the closed period covering them.

Revision ID: 20261004104000
Revises: 20261004103000
"""

from alembic import op

revision = "20261004104000"
down_revision = "20261004103000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE attendance_period p
           SET legal_entity_id = (
                 SELECT le.id FROM legal_entity le
                  WHERE le.company_id = p.company_id AND le.deleted_at IS NULL
               )
         WHERE p.legal_entity_id IS NULL
           AND (SELECT count(*) FROM legal_entity le
                 WHERE le.company_id = p.company_id AND le.deleted_at IS NULL) = 1;

        DO $$
        DECLARE
          ambiguous TEXT;
        BEGIN
          SELECT string_agg(DISTINCT company_id::text, ', ') INTO ambiguous
            FROM attendance_period WHERE legal_entity_id IS NULL;
          IF ambiguous IS NOT NULL THEN
            RAISE EXCEPTION
              'attendance_period rows without a legal entity for companies with zero or several '
              'legal entities: %. Assign legal_entity_id (or split the periods per legal entity) '
              'before running this migration.', ambiguous;
          END IF;
        END $$;

        ALTER TABLE attendance_period ALTER COLUMN legal_entity_id SET NOT NULL;

        ALTER TABLE attendance_period DROP CONSTRAINT IF EXISTS attendance_period_no_overlap;
        ALTER TABLE attendance_period
          ADD CONSTRAINT attendance_period_no_overlap
          EXCLUDE USING gist (
            company_id WITH =,
            legal_entity_id WITH =,
            daterange(period_start, period_end, '[]') WITH &&
          );

        CREATE INDEX IF NOT EXISTS ix_attendance_period_legal_entity_id
          ON attendance_period (legal_entity_id);

        ALTER TABLE attendance_day
          ADD COLUMN IF NOT EXISTS locked_period_id UUID
            REFERENCES attendance_period (id) ON DELETE SET NULL;

        UPDATE attendance_day d
           SET locked_period_id = p.id
          FROM attendance_period p
         WHERE d.is_locked
           AND d.locked_period_id IS NULL
           AND p.company_id = d.company_id
           AND p.status = 'CLOSED'
           AND d.attendance_date BETWEEN p.period_start AND p.period_end;

        CREATE INDEX IF NOT EXISTS ix_attendance_day_locked_period_id
          ON attendance_day (locked_period_id) WHERE locked_period_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    # Restoring the company-wide exclusion fails if two legal entities already have overlapping
    # periods — those must be removed first; a company-grain model cannot represent them.
    op.execute(
        """
        DROP INDEX IF EXISTS ix_attendance_day_locked_period_id;
        ALTER TABLE attendance_day DROP COLUMN IF EXISTS locked_period_id;

        DROP INDEX IF EXISTS ix_attendance_period_legal_entity_id;
        ALTER TABLE attendance_period DROP CONSTRAINT IF EXISTS attendance_period_no_overlap;
        ALTER TABLE attendance_period
          ADD CONSTRAINT attendance_period_no_overlap
          EXCLUDE USING gist (
            company_id WITH =,
            daterange(period_start, period_end, '[]') WITH &&
          );
        ALTER TABLE attendance_period ALTER COLUMN legal_entity_id DROP NOT NULL;
        """
    )
