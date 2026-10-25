"""Grant the system EMPLOYEE role SELF-scoped attendance permissions (API audit C-1).

Revision ID: 20261020090000
Revises: 20261019090000

New tenants get these grants from `OrganisationService.register_company`; this backfills tenants
that already exist. Only the three self-service codes are granted, only at SELF scope, and only to
the system `EMPLOYEE` role (`is_system`, not deleted). Roles that were customised to already hold
one of the codes keep their existing scope (ON CONFLICT DO NOTHING). Downgrade removes only SELF
grants of these three codes from system EMPLOYEE roles.
"""

from alembic import op

revision = "20261020090000"
down_revision = "20261019090000"
branch_labels = None
depends_on = None

_CODES = "('ATTENDANCE.PUNCH', 'ATTENDANCE.VIEW', 'ATTENDANCE.REGULARIZATION_REQUEST')"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT r.id, p.id, 'SELF'
        FROM role r
        JOIN permission p ON p.code IN {_CODES}
        WHERE r.code = 'EMPLOYEE' AND r.is_system AND r.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM role_permission rp
        USING role r, permission p
        WHERE rp.role_id = r.id AND rp.permission_id = p.id
          AND r.code = 'EMPLOYEE' AND r.is_system AND rp.data_scope = 'SELF'
          AND p.code IN {_CODES};
        """
    )
