"""`BRANCH` data-scope level + `BRANCH_MANAGER` default role.

Widens `role_permission_data_scope_check` (added by `20260815120000_role_permission_data_scope`)
to allow `'BRANCH'` alongside the existing four levels — `core/rbac/types.py`'s `DataScopeLevel`
now includes `BRANCH`, resolved the same derived-from-own-assignment way as `REPORTEES`/
`REPORTEE_TREE` (`EmployeeService.resolve_visible_employee_ids`, `EmployeeAssignmentRepository.
get_branch_colleague_ids`) — no new storage beyond the existing `employee_assignment.branch_id`
column.

Also backfills a `BRANCH_MANAGER` role (`EMPLOYEE.VIEW`, `BRANCH` scope) for every existing
company, mirroring `20260920090000_default_roles_backfill`'s exact pattern and reasoning: a
company registered before this feature shipped shouldn't be permanently missing the role a future
role-assignment flow needs to grant it. `organisation/service.py::register_company` now seeds the
same grant for every *new* registration; this migration is the one-time catch-up. Purely additive
and idempotent (`ON CONFLICT ... DO NOTHING` throughout, safe to re-run). Does not assign the role
to any existing user, same as the backfill it mirrors.

Revision ID: 20260923090000
Revises: 20260922090000
"""

from alembic import op

revision = "20260923090000"
down_revision = "20260922090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE role_permission
          DROP CONSTRAINT IF EXISTS role_permission_data_scope_check;
        ALTER TABLE role_permission
          ADD CONSTRAINT role_permission_data_scope_check
          CHECK (data_scope IN ('SELF', 'REPORTEES', 'REPORTEE_TREE', 'BRANCH', 'COMPANY'));
        """
    )

    op.execute(
        """
        INSERT INTO role (id, company_id, code, name, is_system, created_at, updated_at)
        SELECT gen_random_uuid(), ca.company_id, 'BRANCH_MANAGER', 'Branch Manager', true,
               now(), now()
        FROM role ca
        WHERE ca.code = 'COMPANY_ADMIN' AND ca.deleted_at IS NULL
        ON CONFLICT (company_id, code) DO NOTHING;
        """
    )

    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT bm.id, p.id, 'BRANCH'
        FROM role bm
        JOIN permission p ON p.code = 'EMPLOYEE.VIEW'
        WHERE bm.code = 'BRANCH_MANAGER' AND bm.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission
        WHERE role_id IN (SELECT id FROM role WHERE code = 'BRANCH_MANAGER');

        DELETE FROM role WHERE code = 'BRANCH_MANAGER';

        ALTER TABLE role_permission
          DROP CONSTRAINT IF EXISTS role_permission_data_scope_check;
        ALTER TABLE role_permission
          ADD CONSTRAINT role_permission_data_scope_check
          CHECK (data_scope IN ('SELF', 'REPORTEES', 'REPORTEE_TREE', 'COMPANY'));
        """
    )
