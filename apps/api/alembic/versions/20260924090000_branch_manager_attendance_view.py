"""`BRANCH_MANAGER` gains `ATTENDANCE.VIEW` at `BRANCH` scope.

`ATTENDANCE.VIEW`'s read paths (`RegularizationRequestService.get`/`.list`,
`OvertimeRecordService.get`/`.list`, `AttendanceDayService`, `PunchService.list_punches`,
`ShiftRosterService.list_roster_entries`) all resolve scope generically through
`EmployeeService.resolve_visible_employee_ids` — the same seam `EMPLOYEE.VIEW` already uses at
`BRANCH` scope (`20260923090000_branch_manager_role`) — so no service-layer change is needed for
this grant to work.

Deliberately does NOT grant `ATTENDANCE.REGULARIZATION_APPROVE`, `ATTENDANCE.OVERTIME_APPROVE`, or
`LEAVE.APPLICATION_APPROVE`: those services gate the MANAGER stage on an exact
`resolved_approver_manager_id`/`resolved_department_head_id` identity match and the HR stage on
`DataScopeLevel.COMPANY` specifically (`RegularizationRequestService._get_reviewable`,
`OvertimeRecordService._get_reviewable`, `LeaveApplicationService._get_reviewable`) — neither
branch treats `BRANCH` as satisfying anything, so granting those codes at `BRANCH` scope would be
a silent no-op today (see `organisation/service.py`'s `BRANCH_MANAGER_ROLE_CODE` comment).

`organisation/service.py::register_company` now seeds this grant for every *new* registration;
this migration is the one-time catch-up for companies (and their `BRANCH_MANAGER` role rows)
that already existed, mirroring `20260923090000_branch_manager_role`'s own catch-up pattern.
Purely additive and idempotent (`ON CONFLICT ... DO NOTHING`).

Revision ID: 20260924090000
Revises: 20260923090000
"""

from alembic import op

revision = "20260924090000"
down_revision = "20260923090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT bm.id, p.id, 'BRANCH'
        FROM role bm
        JOIN permission p ON p.code = 'ATTENDANCE.VIEW'
        WHERE bm.code = 'BRANCH_MANAGER' AND bm.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission
        WHERE role_id IN (SELECT id FROM role WHERE code = 'BRANCH_MANAGER')
          AND permission_id IN (SELECT id FROM permission WHERE code = 'ATTENDANCE.VIEW');
        """
    )
