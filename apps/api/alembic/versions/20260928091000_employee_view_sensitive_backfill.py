"""`EMPLOYEE.VIEW_SENSITIVE` backfill for existing companies.

Mirrors `20260920090000_default_roles_backfill.py`'s exact shape, scoped to just this one new
permission code: `organisation/service.py::register_company` now grants it to every *new*
registration (HR_ADMIN via the full `EMPLOYEE_PERMISSIONS` loop, `COMPANY` scope; the base
`EMPLOYEE` role via the `VIEW_COMPENSATION`/`VIEW_STATUTORY`/`VIEW_BANKING`/`VIEW_SENSITIVE`
tuple, `SELF` scope) — this is the one-time catch-up for companies that already exist.

Purely additive and idempotent (`ON CONFLICT ... DO NOTHING`).

Revision ID: 20260928091000
Revises: 20260928090000
"""

from alembic import op

revision = "20260928091000"
down_revision = "20260928090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permission (id, code, domain, description)
        VALUES (gen_random_uuid(), 'EMPLOYEE.VIEW_SENSITIVE', 'EMPLOYEE',
                'View an employee''s PAN/Aadhaar/UAN')
        ON CONFLICT (code) DO NOTHING;
        """
    )

    # HR_ADMIN — COMPANY scope, matching every other EMPLOYEE.* code it already holds.
    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT hr.id, p.id, 'COMPANY'
        FROM role hr
        JOIN permission p ON p.code = 'EMPLOYEE.VIEW_SENSITIVE'
        WHERE hr.code = 'HR_ADMIN' AND hr.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )

    # EMPLOYEE — SELF scope, same posture as VIEW_COMPENSATION/VIEW_STATUTORY/VIEW_BANKING.
    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT emp.id, p.id, 'SELF'
        FROM role emp
        JOIN permission p ON p.code = 'EMPLOYEE.VIEW_SENSITIVE'
        WHERE emp.code = 'EMPLOYEE' AND emp.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission
        WHERE permission_id IN (SELECT id FROM permission WHERE code = 'EMPLOYEE.VIEW_SENSITIVE');

        DELETE FROM permission WHERE code = 'EMPLOYEE.VIEW_SENSITIVE';
        """
    )
