"""`EMPLOYEE.VIEW_DOCUMENTS` backfill for existing companies.

Mirrors `20260928091000_employee_view_sensitive_backfill.py`'s exact shape, scoped to just this
one new permission code: `organisation/service.py::register_company` now grants it to every
*new* registration (COMPANY_ADMIN and HR_ADMIN both via the full `EMPLOYEE_PERMISSIONS` loop,
`COMPANY` scope; the base `EMPLOYEE` role via its SELF-scope tuple) — this is the one-time
catch-up for companies that already exist.

`COMPANY_ADMIN` was missing from the first draft of this migration even though
`register_company` grants it every `EMPLOYEE.*` code without exception (same COMPANY-scope loop
HR_ADMIN goes through) — verified against a live pre-existing tenant ("My Company"), whose
COMPANY_ADMIN role held every other `EMPLOYEE.*` permission at COMPANY scope except this one,
causing a 403 on `GET /employees/{id}/documents` for that role alone. Added below, same shape as
the HR_ADMIN block.

Purely additive and idempotent (`ON CONFLICT ... DO NOTHING`).

Revision ID: 20261014091000
Revises: 20261014090000
"""

from alembic import op

revision = "20261014091000"
down_revision = "20261014090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permission (id, code, domain, description)
        VALUES (gen_random_uuid(), 'EMPLOYEE.VIEW_DOCUMENTS', 'EMPLOYEE',
                'View an employee''s documents')
        ON CONFLICT (code) DO NOTHING;
        """
    )

    # COMPANY_ADMIN — COMPANY scope, matching every other EMPLOYEE.* code it already holds.
    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT ca.id, p.id, 'COMPANY'
        FROM role ca
        JOIN permission p ON p.code = 'EMPLOYEE.VIEW_DOCUMENTS'
        WHERE ca.code = 'COMPANY_ADMIN' AND ca.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )

    # HR_ADMIN — COMPANY scope, matching every other EMPLOYEE.* code it already holds.
    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT hr.id, p.id, 'COMPANY'
        FROM role hr
        JOIN permission p ON p.code = 'EMPLOYEE.VIEW_DOCUMENTS'
        WHERE hr.code = 'HR_ADMIN' AND hr.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )

    # EMPLOYEE — SELF scope, same posture as VIEW_SENSITIVE/VIEW_EXPERIENCE/VIEW_NOMINEE.
    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT emp.id, p.id, 'SELF'
        FROM role emp
        JOIN permission p ON p.code = 'EMPLOYEE.VIEW_DOCUMENTS'
        WHERE emp.code = 'EMPLOYEE' AND emp.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission
        WHERE permission_id IN (SELECT id FROM permission WHERE code = 'EMPLOYEE.VIEW_DOCUMENTS');

        DELETE FROM permission WHERE code = 'EMPLOYEE.VIEW_DOCUMENTS';
        """
    )
