"""RBAC data-scope — `role_permission.data_scope` (Employee `SELF`/`REPORTEES`/`REPORTEE_TREE`
slice, `docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §20).

Purely additive: one `NOT NULL DEFAULT 'COMPANY'` column on `role_permission`, restricted to the
four levels implemented in this slice (`SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY` — not the full
8-level model `docs/product/19_RBAC_and_Permission_Matrix.md §5` documents; `DEPARTMENT`/`BRANCH`/
`LEGAL_ENTITY`/`ALL_COMPANIES` are explicitly out of this slice's scope). The `DEFAULT` fills every
existing row with `'COMPANY'`, which is exactly what `require_permission()` returns unconditionally
today (`core/rbac/dependencies.py:29`) — no existing role's behavior changes as a result of this
migration by itself, including every `COMPANY_ADMIN` grant in every existing tenant
(`docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md`, Decision A/H). Verified against the live
database after applying: `role_permission_pkey`/`_role_id_fkey`/`_permission_id_fkey` unaffected,
21 pre-existing rows all read back `data_scope = 'COMPANY'`.

`role_permission` carries no RLS policy — confirmed against `scripts/sql/001_init_schema.sql`
(composite PK on `(role_id, permission_id)` only, no `company_id` column, no
`ENABLE ROW LEVEL SECURITY` statement for this table) and restated in the plan doc §14. No RLS
statement is added here; this is a join table that relies on its parent `role`'s tenant scoping,
matching every other join table's precedent in this codebase.

No new index. The plan doc (§16) proposed one, reasoning from `employee/models.py`'s ORM
`index=True` declarations alone — but `20260814100000_employee_assignment.py` already created
`employee_assignment_manager_idx` on exactly `(company_id, reporting_manager_id) WHERE
effective_to IS NULL` (verified directly against the live schema via `pg_indexes` before writing
this revision), anticipating this exact reporting-hierarchy query shape ahead of this task. Adding
a second, functionally-identical partial index under a different name would be pure duplication —
same columns, same predicate, no new query plan it could serve. This is a correction to the plan
doc's own §16, not a design change; the `REPORTEES`/`REPORTEE_TREE` resolver
(`employee/repository.py`) already benefits from `employee_assignment_manager_idx` with zero
migration needed for it.

Revision ID: 20260815120000
Revises: 20260814120000
"""

from alembic import op

revision = "20260815120000"
down_revision = "20260814120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE role_permission
          ADD COLUMN IF NOT EXISTS data_scope VARCHAR(20) NOT NULL DEFAULT 'COMPANY';

        ALTER TABLE role_permission
          DROP CONSTRAINT IF EXISTS role_permission_data_scope_check;
        ALTER TABLE role_permission
          ADD CONSTRAINT role_permission_data_scope_check
          CHECK (data_scope IN ('SELF', 'REPORTEES', 'REPORTEE_TREE', 'COMPANY'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE role_permission
          DROP CONSTRAINT IF EXISTS role_permission_data_scope_check;

        ALTER TABLE role_permission
          DROP COLUMN IF EXISTS data_scope;
        """
    )
