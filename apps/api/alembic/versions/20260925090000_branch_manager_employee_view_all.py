"""`BRANCH_MANAGER` gains `EMPLOYEE.VIEW_ALL` at `BRANCH` scope.

`GET /v1/employees` (the list endpoint `/app/employees` calls) gates on `EMPLOYEE.VIEW_ALL`, not
`EMPLOYEE.VIEW` (`employee/router.py`: `list_employees` vs. `get_employee`). Without this grant, a
`BRANCH_MANAGER` (seeded so far with only `EMPLOYEE.VIEW` at `BRANCH` —
`20260923090000_branch_manager_role`) could fetch a single branch colleague's record by ID but
never list their own branch's roster, discovered while verifying the role end-to-end through the
real UI. Both permissions' read paths resolve scope through the same generic
`EmployeeService.resolve_visible_employee_ids` seam, so `BRANCH` scope filters the list
identically to the single-record read — no service-layer change needed.

`organisation/service.py::register_company` now seeds this grant for every *new* registration;
this migration is the one-time catch-up for companies that already existed, mirroring
`20260923090000_branch_manager_role`'s own catch-up pattern. Purely additive and idempotent
(`ON CONFLICT ... DO NOTHING`).

Revision ID: 20260925090000
Revises: 20260924090000
"""

from alembic import op

revision = "20260925090000"
down_revision = "20260924090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT bm.id, p.id, 'BRANCH'
        FROM role bm
        JOIN permission p ON p.code = 'EMPLOYEE.VIEW_ALL'
        WHERE bm.code = 'BRANCH_MANAGER' AND bm.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission
        WHERE role_id IN (SELECT id FROM role WHERE code = 'BRANCH_MANAGER')
          AND permission_id IN (SELECT id FROM permission WHERE code = 'EMPLOYEE.VIEW_ALL');
        """
    )
