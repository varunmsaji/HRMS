"""Grant the system HR_ADMIN role company-wide attendance read and onboarding permissions.

Revision ID: 20261026090000
Revises: 20261022090000

HR_ADMIN policy: HR reads attendance company-wide (`ATTENDANCE.VIEW`, `ATTENDANCE.VIEW_ALL`) and
runs onboarding (`ONBOARDING.CREATE/VIEW/REVIEW/ACTIVATE/CANCEL`). New tenants get these from
`OrganisationService.register_company`; this backfills tenants that already exist.

Additive data migration, no DDL and no database GRANT: only rows in `role_permission`, only for the
system `HR_ADMIN` role (`is_system`, not deleted), only at COMPANY scope. A role that already holds
one of the codes keeps its existing scope (ON CONFLICT DO NOTHING). Codes whose `permission` row
does not exist yet are skipped by the join. Policy management, shifts, rosters and period
lock/unlock are deliberately NOT granted. Downgrade removes COMPANY-scope grants of exactly
these codes from system HR_ADMIN roles (including any a tenant had added by hand earlier).
"""

from alembic import op

revision = "20261026090000"
down_revision = "20261022090000"
branch_labels = None
depends_on = None

_CODES = (
    "('ATTENDANCE.VIEW', 'ATTENDANCE.VIEW_ALL', 'ONBOARDING.CREATE', 'ONBOARDING.VIEW',"
    " 'ONBOARDING.REVIEW', 'ONBOARDING.ACTIVATE', 'ONBOARDING.CANCEL')"
)


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
