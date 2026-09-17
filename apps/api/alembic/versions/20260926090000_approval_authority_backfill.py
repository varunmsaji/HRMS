"""Approval-authority backfill — grants the three `.APPROVE` codes to `HR_ADMIN` (`COMPANY`
scope), `REPORTING_MANAGER` (`REPORTEE_TREE` scope), and `BRANCH_MANAGER` (`BRANCH` scope) for
every existing company, mirroring `organisation/service.py::register_company`'s new grants for
every future registration.

Closes a real functional gap discovered while verifying `BRANCH_MANAGER`: `ATTENDANCE.
REGULARIZATION_APPROVE`, `ATTENDANCE.OVERTIME_APPROVE`, and `LEAVE.APPLICATION_APPROVE` were
previously held by no default role except `COMPANY_ADMIN`. Each of the three approval flows has a
MANAGER/HOD stage (identity-checked against the request's snapshotted `resolved_approver_manager_
id`/`resolved_department_head_id`, not scope) and an HR stage (checked against `DataScopeLevel.
COMPANY` on the matching code). Before this migration:

- The HR stage was only passable by whoever held `COMPANY_ADMIN` — not `HR_ADMIN`, despite the
  role's name and Decision H's own description of it as the role that "runs HR operations."
- The MANAGER/HOD stage was passable by literally nobody: the actual reporting manager/department
  head held none of these codes (`REPORTING_MANAGER` granted only `EMPLOYEE.VIEW`), and
  `COMPANY_ADMIN` — the one role that did hold the codes — typically has no `Employee` record at
  all (a registering admin never entered into the roster is the expected, documented case per
  `RBAC_DATA_SCOPE_DECISIONS.md` Decision B), so its `employee_id` is `None` and it fails the
  identity check immediately regardless.

Purely additive and idempotent (`ON CONFLICT ... DO NOTHING`), same shape as
`20260920090000_default_roles_backfill.py`. Does not change any request's outcome retroactively —
only which callers are now capable of reaching the approve/reject decision at all.

Revision ID: 20260926090000
Revises: 20260925090000
"""

from alembic import op

revision = "20260926090000"
down_revision = "20260925090000"
branch_labels = None
depends_on = None

_APPROVE_CODES = (
    "ATTENDANCE.REGULARIZATION_APPROVE",
    "ATTENDANCE.OVERTIME_APPROVE",
    "LEAVE.APPLICATION_APPROVE",
)


def upgrade() -> None:
    codes_sql = ", ".join(f"'{code}'" for code in _APPROVE_CODES)

    op.execute(
        f"""
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT r.id, p.id, 'COMPANY'
        FROM role r
        JOIN permission p ON p.code IN ({codes_sql})
        WHERE r.code = 'HR_ADMIN' AND r.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )

    op.execute(
        f"""
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT r.id, p.id, 'REPORTEE_TREE'
        FROM role r
        JOIN permission p ON p.code IN ({codes_sql})
        WHERE r.code = 'REPORTING_MANAGER' AND r.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )

    op.execute(
        f"""
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT r.id, p.id, 'BRANCH'
        FROM role r
        JOIN permission p ON p.code IN ({codes_sql})
        WHERE r.code = 'BRANCH_MANAGER' AND r.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    codes_sql = ", ".join(f"'{code}'" for code in _APPROVE_CODES)
    op.execute(
        f"""
        DELETE FROM role_permission
        WHERE permission_id IN (SELECT id FROM permission WHERE code IN ({codes_sql}))
          AND role_id IN (
              SELECT id FROM role WHERE code IN ('HR_ADMIN', 'REPORTING_MANAGER', 'BRANCH_MANAGER')
          );
        """
    )
