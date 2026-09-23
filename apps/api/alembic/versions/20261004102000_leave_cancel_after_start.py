"""Leave balance safety, step 2 — who may cancel an approved leave
(`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 10).

- New permission `LEAVE.APPLICATION_CANCEL_APPROVED` — cancel an approved application at any
  time, including after it has started (reason mandatory then). Granted to `COMPANY_ADMIN` (which
  holds every `LEAVE.*` code) and `HR_ADMIN`, both at `COMPANY` scope, for every existing company;
  `organisation/service.py::register_company` does the same for new ones. Employees keep the
  right to cancel their own approved leave *before* it starts; managers lose any post-approval
  cancel.
- `leave_application.cancellation_reason` — recorded on every cancel that supplies one.

Revision ID: 20261004102000
Revises: 20261004101000
"""

from alembic import op

revision = "20261004102000"
down_revision = "20261004101000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permission (id, code, domain, description)
        VALUES (gen_random_uuid(), 'LEAVE.APPLICATION_CANCEL_APPROVED', 'LEAVE',
                'Cancel an approved leave application, including after it has started')
        ON CONFLICT (code) DO NOTHING;

        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT r.id, p.id, 'COMPANY'
        FROM role r
        JOIN permission p ON p.code = 'LEAVE.APPLICATION_CANCEL_APPROVED'
        WHERE r.code IN ('COMPANY_ADMIN', 'HR_ADMIN') AND r.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;

        ALTER TABLE leave_application ADD COLUMN IF NOT EXISTS cancellation_reason TEXT;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_application DROP COLUMN IF EXISTS cancellation_reason;

        DELETE FROM role_permission
        WHERE permission_id IN (
            SELECT id FROM permission WHERE code = 'LEAVE.APPLICATION_CANCEL_APPROVED'
        );
        DELETE FROM permission WHERE code = 'LEAVE.APPLICATION_CANCEL_APPROVED';
        """
    )
