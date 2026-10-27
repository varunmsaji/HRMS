"""Grant the system HR_ADMIN role work-calendar and holiday management.

Revision ID: 20261029090000
Revises: 20261028090000

Approved product decision: Company Admin and HR Admin both manage work calendars, weekly-off
patterns, calendar exceptions, calendar assignments and holiday calendars (`ORG.CALENDAR.MANAGE`,
`ORG.HOLIDAY.MANAGE`). New tenants get these from `OrganisationService.register_company`; this
backfills tenants that already exist.

Additive data migration, no DDL and no database GRANT: only rows in `role_permission`, only for the
system `HR_ADMIN` role (`is_system`, not deleted), only at COMPANY scope. A role that already holds
a code keeps its existing scope (ON CONFLICT DO NOTHING). Codes whose `permission` row does not
exist yet are skipped by the join. A company that has customised its HR_ADMIN role is affected
only by additions, never removals. Downgrade removes COMPANY-scope grants of exactly these two
codes from system HR_ADMIN roles (including any a tenant had added by hand earlier).

NOT applied by the work-calendar implementation task: it must be reviewed and run deliberately
against each environment.
"""

from alembic import op

revision = "20261029090000"
down_revision = "20261028090000"
branch_labels = None
depends_on = None

_CODES = "('ORG.CALENDAR.MANAGE', 'ORG.HOLIDAY.MANAGE')"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT r.id, p.id, 'COMPANY'
        FROM role r
        JOIN permission p ON p.code IN {_CODES}
        WHERE r.code = 'HR_ADMIN' AND r.is_system AND r.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM role_permission rp
        USING role r, permission p
        WHERE rp.role_id = r.id AND rp.permission_id = p.id
          AND r.code = 'HR_ADMIN' AND r.is_system AND rp.data_scope = 'COMPANY'
          AND p.code IN {_CODES};
        """
    )
