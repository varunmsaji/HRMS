"""R-1 (pre-commit review): `leave_application.half_day`.

Revision ID: 20261116110000
Revises: 20261116100000

A half-day application is one date; which half it covers was known only from its single
`leave_application_day` row. Calendar reconciliation deletes a day row when the date stops
consuming leave, so a half-day leave whose only day was released could never be rebuilt (the half
was lost with the row). The half is now also kept on the application, which is never deleted.

Additive and nullable. No CHECK: `leave_application_day.half` has no check and the dev data holds
the legacy value `FIRST`, which must copy across unchanged. Backfill: a single-date application with a stored day row takes that row's
half. An application whose only day was already released before this migration has no row to read
the half from directly; it is then recovered from its cancelled attendance projection only when
that evidence is unambiguous (see the upgrade), otherwise it stays NULL (restored as a full day if
its date becomes a working day again; the diagnostic query in `attendance_integrity_report.sql`
lists these). The downgrade refuses if a stored half would be lost.
"""

from alembic import op

revision = "20261116110000"
down_revision = "20261116100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE leave_application ADD COLUMN IF NOT EXISTS "half_day" VARCHAR(20)')
    op.execute(
        """
        SET LOCAL row_security = off;

        -- 1. A single-date application with a stored day row takes that row's half.
        UPDATE leave_application a
           SET half_day = d.half
          FROM leave_application_day d
         WHERE d.leave_application_id = a.id
           AND a.start_date = a.end_date
           AND d.half IS NOT NULL
           AND a.half_day IS NULL;

        -- 2. Recovery for an application whose only day row was already released: its attendance
        --    projection is CANCELLED, not deleted, and still holds the half. Written ONLY when the
        --    evidence is unambiguous - a single date, no half yet, and EVERY projection of the
        --    application carries the same, single, non-null half. Anything else (no projection,
        --    only NULL halves, two different halves, a mix of NULL and a half, several dates) stays
        --    NULL and is listed for HR by `attendance_integrity_report.sql`. Nothing is inferred
        --    from ledger amounts or any other indirect evidence.
        UPDATE leave_application a
           SET half_day = p.half
          FROM (
                SELECT leave_application_id, MIN(half) AS half
                  FROM leave_day_projection
                 GROUP BY leave_application_id
                HAVING COUNT(*) = COUNT(half) AND COUNT(DISTINCT half) = 1
               ) p
         WHERE p.leave_application_id = a.id
           AND a.start_date = a.end_date
           AND a.half_day IS NULL;
        """
    )


def downgrade() -> None:
    """Refuses if stored half-day information would be lost: an application with a `half_day` and
    NO day rows (its day was released) keeps the half nowhere else. Otherwise the column is only a
    copy of what its day rows hold and is dropped. `row_security = off` makes the check see every
    tenant's rows (it fails, never undercounts, if the migration role cannot bypass it)."""
    op.execute(
        """
        SET LOCAL row_security = off;
        DO $$
        DECLARE
          n bigint;
        BEGIN
          SELECT count(*) INTO n FROM leave_application a
           WHERE a.half_day IS NOT NULL
             AND NOT EXISTS (
               SELECT 1 FROM leave_application_day d WHERE d.leave_application_id = a.id
             );
          IF n > 0 THEN
            RAISE EXCEPTION
              'Refusing to downgrade 20261116110000: % leave application(s) keep their half-day '
              'marker only in leave_application.half_day (no day rows) and dropping the column '
              'would lose it. Restore from a pre-upgrade backup, or keep this revision.', n;
          END IF;
        END
        $$;
        ALTER TABLE leave_application DROP COLUMN IF EXISTS "half_day";
        """
    )
