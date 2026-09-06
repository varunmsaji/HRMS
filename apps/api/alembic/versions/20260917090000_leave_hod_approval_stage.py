"""Leave's third approval level — `MANAGER_THEN_HOD_THEN_HR` (LEAVE_DECISION_LOG.md LD-23).

Adds `leave_application.resolved_department_head_id`, snapshotted at submit time exactly like
`resolved_approver_manager_id` (resolved via the employee's assignment `department_id` →
`Department.head_employee_id`, now exposed by Organisation's own LD-23 change). Widens both
`leave_policy_version_approval_chain_check` and `leave_application`'s own
`approval_chain`/`approval_stage` CHECK constraints to allow the new chain value and its `HOD`
stage — `approval_stage` stays `VARCHAR(10)` (`'HOD'` fits) and `leave_application_action.stage`
has no CHECK constraint at all, so neither needs widening.

Revision ID: 20260917090000
Revises: 20260916090000
"""

from alembic import op

revision = "20260917090000"
down_revision = "20260916090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_application
          ADD COLUMN IF NOT EXISTS resolved_department_head_id UUID;

        ALTER TABLE leave_application
          ADD CONSTRAINT leave_application_resolved_department_head_id_fkey
            FOREIGN KEY (resolved_department_head_id) REFERENCES employee(id)
            ON DELETE SET NULL ON UPDATE CASCADE;

        ALTER TABLE leave_application
          DROP CONSTRAINT leave_application_approval_chain_check;
        ALTER TABLE leave_application
          ADD CONSTRAINT leave_application_approval_chain_check
            CHECK (approval_chain IN
              ('AUTO', 'MANAGER', 'MANAGER_THEN_HR', 'MANAGER_THEN_HOD_THEN_HR', 'HR'));

        ALTER TABLE leave_application
          DROP CONSTRAINT leave_application_approval_stage_check;
        ALTER TABLE leave_application
          ADD CONSTRAINT leave_application_approval_stage_check
            CHECK (approval_stage IS NULL OR approval_stage IN ('MANAGER', 'HOD', 'HR'));

        ALTER TABLE leave_policy_version
          DROP CONSTRAINT leave_policy_version_approval_chain_check;
        ALTER TABLE leave_policy_version
          ADD CONSTRAINT leave_policy_version_approval_chain_check
            CHECK (approval_chain IN
              ('AUTO', 'MANAGER', 'MANAGER_THEN_HR', 'MANAGER_THEN_HOD_THEN_HR', 'HR'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_policy_version
          DROP CONSTRAINT leave_policy_version_approval_chain_check;
        ALTER TABLE leave_policy_version
          ADD CONSTRAINT leave_policy_version_approval_chain_check
            CHECK (approval_chain IN ('AUTO', 'MANAGER', 'MANAGER_THEN_HR', 'HR'));

        ALTER TABLE leave_application
          DROP CONSTRAINT leave_application_approval_stage_check;
        ALTER TABLE leave_application
          ADD CONSTRAINT leave_application_approval_stage_check
            CHECK (approval_stage IS NULL OR approval_stage IN ('MANAGER', 'HR'));

        ALTER TABLE leave_application
          DROP CONSTRAINT leave_application_approval_chain_check;
        ALTER TABLE leave_application
          ADD CONSTRAINT leave_application_approval_chain_check
            CHECK (approval_chain IN ('AUTO', 'MANAGER', 'MANAGER_THEN_HR', 'HR'));

        ALTER TABLE leave_application
          DROP CONSTRAINT IF EXISTS leave_application_resolved_department_head_id_fkey;
        ALTER TABLE leave_application
          DROP COLUMN IF EXISTS resolved_department_head_id;
        """
    )
