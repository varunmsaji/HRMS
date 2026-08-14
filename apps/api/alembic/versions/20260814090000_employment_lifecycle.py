"""Employment lifecycle (E-03) — status enum lock, rehire linkage, optimistic concurrency.

`docs/modules/employee/07_EMPLOYMENT_STATUS_DECISION.md` investigated but did not resolve
`employment.status`'s value set — that product decision has since been made (task-level
authoritative instruction, not re-derived here): exactly two stored values, `ACTIVE` and
`TERMINATED`. `ON_NOTICE` is explicitly not a stored value; notice state is derived from
`last_working_day` at the service layer. `TERMINATED` is used, not `EXITED` (`EXITED` remains
an `employee.status`-only concept, never written to `employment.status`).

The live `employment` table (`scripts/sql/001_init_schema.sql:243-256`) has zero rows at the
time this migration was written (confirmed against the dev database) — every change below is
safe to apply directly, no data to transform or lose:

- `exit_date` is renamed to `last_working_day` — the live column and the documented target
  field (`02_EMPLOYEE_DATA_MODEL.md` §3) describe the same fact (the day the spell ends); the
  data model doc's own proposed `ADD COLUMN last_working_day` alongside the pre-existing
  `exit_date` would have left two overlapping "end of spell" columns needing to stay in sync
  for no documented reason — a rename avoids that redundancy and adopts the authoritative
  task instruction's exact field name.
- `previous_employment_id` (self-referential FK, mirroring `designation.next_designation_id`'s
  existing self-referential precedent) links a rehire episode to the immediately preceding
  employment row for the same employee. Always system-computed at insert time, never
  client-settable (no application write path exposes it as an input).
- `version` (optimistic concurrency) — `employment` was the only employee-domain table without
  it (`00_EMPLOYEE_AUDIT.md` §3.2); a rehire/termination is a real mutation needing the same
  protection every other mutable table already has.
- Two `CHECK` constraints enforce the locked status vocabulary and its relationship to
  `last_working_day` at the database level, not just in application code:
  `employment_status_check` restricts `status` to `('ACTIVE','TERMINATED')`;
  `employment_status_last_working_day_check` requires `last_working_day` to be set if and only
  if `status = 'TERMINATED'` (an `ACTIVE` spell never carries a `last_working_day`, and a
  `TERMINATED` spell always does) — this is what makes "notice state is derived, not stored"
  actually safe: there is no way for the two facts to drift apart.
  `employment_last_working_day_after_joining_check` rejects a `last_working_day` before the
  spell's own `joining_date`.
- A GiST exclusion constraint (`employment_no_overlap`, same `btree_gist`-backed pattern
  already live for `employee_assignment`/`employee_compensation`) prevents two employment rows
  for the same employee from having overlapping `[joining_date, last_working_day]` ranges —
  `last_working_day IS NULL` (an open/`ACTIVE` spell) is treated as extending to `infinity`, so
  this single constraint enforces both "at most one `ACTIVE` employment per employee" and "no
  two historical spells overlap in time," with no separate partial-unique index needed.
- `previous_employment_id` is indexed (every FK indexed, per `docs/product/
  08_Database_Architecture.md` §1's global rule).
- RLS re-asserted idempotently, matching every prior migration in this series.

Revision ID: 20260814090000
Revises: 20260813180000
"""

from alembic import op

revision = "20260814090000"
down_revision = "20260813180000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE employment RENAME COLUMN exit_date TO last_working_day;

        ALTER TABLE employment
          ADD COLUMN IF NOT EXISTS previous_employment_id UUID
            REFERENCES employment(id) ON DELETE SET NULL,
          ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

        ALTER TABLE employment
          ADD CONSTRAINT employment_status_check
            CHECK (status IN ('ACTIVE', 'TERMINATED')),
          ADD CONSTRAINT employment_status_last_working_day_check
            CHECK ((status = 'TERMINATED') = (last_working_day IS NOT NULL)),
          ADD CONSTRAINT employment_last_working_day_after_joining_check
            CHECK (last_working_day IS NULL OR last_working_day >= joining_date);

        ALTER TABLE employment
          ADD CONSTRAINT employment_no_overlap
          EXCLUDE USING gist (
            employee_id WITH =,
            daterange(joining_date, COALESCE(last_working_day, 'infinity'::date), '[]') WITH &&
          );

        CREATE INDEX IF NOT EXISTS employment_previous_employment_id_idx
          ON employment (previous_employment_id);

        ALTER TABLE employment ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employment FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employment;
        CREATE POLICY tenant_isolation ON employment
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS employment_previous_employment_id_idx;

        ALTER TABLE employment
          DROP CONSTRAINT IF EXISTS employment_no_overlap,
          DROP CONSTRAINT IF EXISTS employment_last_working_day_after_joining_check,
          DROP CONSTRAINT IF EXISTS employment_status_last_working_day_check,
          DROP CONSTRAINT IF EXISTS employment_status_check;

        ALTER TABLE employment
          DROP COLUMN IF EXISTS version,
          DROP COLUMN IF EXISTS previous_employment_id;

        ALTER TABLE employment RENAME COLUMN last_working_day TO exit_date;
        """
    )
