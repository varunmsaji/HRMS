"""Workforce Calendar W1 (5/5) — new `policy_assignment` table.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §15.1 and WD-09 (precedence
chain). **Scope note (recorded as WD-24 in the decision log):** the architecture's own §30/
WD-23 place `PolicyAssignment` in slice W3, alongside AttendancePolicy/OvertimePolicy/
RegularizationPolicy. It is pulled forward into W1 here because a WorkCalendar is otherwise
unassignable below COMPANY scope (§15.3 explicitly rejects a `branch.work_calendar_id`
shortcut in favour of this table), which would make W1's own calendar-assignment/calendar-
resolution requirements unsatisfiable. The `policy_kind` CHECK below is deliberately narrowed
to the two kinds W1 actually has policies for; W3 widens it, it does not replace it.

`policy_id` carries **no DB foreign key** — it is polymorphic, pointing at `work_calendar` or
`weekly_off_pattern` depending on `policy_kind` (and at `attendance_policy`/etc. from W3
onward). This mirrors the only existing polymorphic-reference precedent in this codebase,
`audit_log.entity_id` (also a bare UUID, for the identical reason). Ownership and existence
are validated at the service layer, the same way `EmployeeAssignment`'s FK-shaped-but-
unconstrained fields are validated in `EmployeeService`.

`scope_id` is nullable **iff** `scope_type = 'COMPANY'` (checked). The GiST exclusion
constraint below is this codebase's first *predicated* exclusion constraint (`WHERE
(deleted_at IS NULL)`) — Postgres supports a predicate clause on `EXCLUDE` exactly as it does
on a partial index. `scope_id` is wrapped in `COALESCE(..., '00000000-...'::uuid)` inside the
exclusion expression because EXCLUDE constraints, like unique indexes, never treat two `NULL`
values as conflicting — without the sentinel, multiple overlapping `COMPANY`-scope rows (which
all have `scope_id IS NULL`) would silently pass the constraint. `btree_gist` (already enabled
globally, see `infra/docker/postgres/init/001_extensions.sql`) supplies GiST equality support
for `uuid` (already proven elsewhere by `employee_id WITH =`) and `varchar`/`text` alike.

`priority` is stored (per §15.1, reserved for a future relaxation of the overlap rule) but is
**not** consulted by any W1 resolution logic — V1 locks "no overlap at same scope" regardless
of priority (§15.1).

Revision ID: 20260818130000
Revises: 20260818120000
"""

from alembic import op

revision = "20260818130000"
down_revision = "20260818120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_assignment (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "policy_kind" VARCHAR(30) NOT NULL,
            "policy_id" UUID NOT NULL,
            "scope_type" VARCHAR(20) NOT NULL,
            "scope_id" UUID,
            "effective_from" DATE NOT NULL,
            "effective_to" DATE,
            "priority" INTEGER NOT NULL DEFAULT 0,
            "reason" TEXT,
            "is_active" BOOLEAN NOT NULL DEFAULT true,
            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "policy_assignment_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "policy_assignment_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "policy_assignment_policy_kind_check"
              -- W1-restricted; W3 will ALTER ... DROP/ADD CONSTRAINT to widen this list with
              -- ATTENDANCE_POLICY / OVERTIME_POLICY / REGULARIZATION_POLICY.
              CHECK (policy_kind IN ('WORK_CALENDAR', 'WEEKLY_OFF')),
            CONSTRAINT "policy_assignment_scope_type_check" CHECK (scope_type IN (
              'COMPANY', 'LEGAL_ENTITY', 'BRANCH', 'DEPARTMENT', 'GRADE', 'DESIGNATION',
              'SHIFT', 'EMPLOYEE'
            )),
            CONSTRAINT "policy_assignment_scope_id_null_iff_company_check"
              CHECK ((scope_type = 'COMPANY') = (scope_id IS NULL)),
            CONSTRAINT "policy_assignment_date_range_check"
              CHECK (effective_to IS NULL OR effective_to >= effective_from)
        );

        CREATE INDEX IF NOT EXISTS policy_assignment_company_id_idx
          ON policy_assignment (company_id);
        CREATE INDEX IF NOT EXISTS policy_assignment_lookup_idx
          ON policy_assignment (company_id, policy_kind, scope_type, scope_id);

        ALTER TABLE policy_assignment
          DROP CONSTRAINT IF EXISTS policy_assignment_no_overlap;
        ALTER TABLE policy_assignment
          ADD CONSTRAINT policy_assignment_no_overlap
          EXCLUDE USING gist (
            company_id WITH =,
            policy_kind WITH =,
            scope_type WITH =,
            COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =,
            daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
          )
          WHERE (deleted_at IS NULL);

        ALTER TABLE policy_assignment ENABLE ROW LEVEL SECURITY;
        ALTER TABLE policy_assignment FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON policy_assignment;
        CREATE POLICY tenant_isolation ON policy_assignment
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS policy_assignment;
        """
    )
