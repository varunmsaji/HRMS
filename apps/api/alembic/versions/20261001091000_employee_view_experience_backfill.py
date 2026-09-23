"""`EMPLOYEE.VIEW_EXPERIENCE` backfill for existing companies.

Same shape as `20260928091000_employee_view_sensitive_backfill.py` — `organisation/service.py::
register_company` now grants it to every *new* registration (HR_ADMIN via the full
`EMPLOYEE_PERMISSIONS` loop, `COMPANY` scope; the base `EMPLOYEE` role at `SELF` scope); this is
the one-time catch-up for companies that already exist.

Revision ID: 20261001091000
Revises: 20261001090000
"""

from alembic import op

revision = "20261001091000"
down_revision = "20261001090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permission (id, code, domain, description)
        VALUES (gen_random_uuid(), 'EMPLOYEE.VIEW_EXPERIENCE', 'EMPLOYEE',
                'View an employee''s previous-employment / education history')
        ON CONFLICT (code) DO NOTHING;
        """
    )

    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT hr.id, p.id, 'COMPANY'
        FROM role hr
        JOIN permission p ON p.code = 'EMPLOYEE.VIEW_EXPERIENCE'
        WHERE hr.code = 'HR_ADMIN' AND hr.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )

    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT emp.id, p.id, 'SELF'
        FROM role emp
        JOIN permission p ON p.code = 'EMPLOYEE.VIEW_EXPERIENCE'
        WHERE emp.code = 'EMPLOYEE' AND emp.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission
        WHERE permission_id IN (SELECT id FROM permission WHERE code = 'EMPLOYEE.VIEW_EXPERIENCE');

        DELETE FROM permission WHERE code = 'EMPLOYEE.VIEW_EXPERIENCE';
        """
    )
