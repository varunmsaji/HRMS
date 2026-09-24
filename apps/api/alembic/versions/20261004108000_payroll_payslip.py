"""Payroll Phase 5.4 — payslips and bank advice (`docs/modules/payroll/
00_PAYROLL_IMPLEMENTATION_PLAN.md`, FR-PAY-017/018).

- `pay_run_employee.payslip_details` — the payslip's header facts (designation, department,
  joining date, masked PAN, legal entity) and leave balances at month end, captured when the run
  is finalised so a published payslip never changes afterwards.
- `PAYROLL.PAYSLIP_VIEW_OWN` — the EMPLOYEE role at SELF scope, and COMPANY_ADMIN.
- `PAYROLL.BANK_ADVICE_DOWNLOAD` — COMPANY_ADMIN only (the file carries full account numbers).

Revision ID: 20261004108000
Revises: 20261004107000
"""

from alembic import op

revision = "20261004108000"
down_revision = "20261004107000"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    (
        "PAYROLL.PAYSLIP_VIEW_OWN",
        "View one''s own payslips from finalised pay runs",
        (("EMPLOYEE", "SELF"), ("COMPANY_ADMIN", "COMPANY")),
    ),
    (
        "PAYROLL.BANK_ADVICE_DOWNLOAD",
        "Download a finalised pay run''s bank advice (full account numbers)",
        (("COMPANY_ADMIN", "COMPANY"),),
    ),
)


def upgrade() -> None:
    op.execute("ALTER TABLE pay_run_employee ADD COLUMN IF NOT EXISTS payslip_details JSONB")
    for code, description, grants in _PERMISSIONS:
        op.execute(
            f"""
            INSERT INTO permission (id, code, domain, description)
            VALUES (gen_random_uuid(), '{code}', 'PAYROLL', '{description}')
            ON CONFLICT (code) DO NOTHING;
            """
        )
        for role, scope in grants:
            op.execute(
                f"""
                INSERT INTO role_permission (role_id, permission_id, data_scope)
                SELECT r.id, p.id, '{scope}'
                FROM role r
                JOIN permission p ON p.code = '{code}'
                WHERE r.code = '{role}' AND r.deleted_at IS NULL
                ON CONFLICT (role_id, permission_id) DO NOTHING;
                """
            )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _, _ in _PERMISSIONS)
    op.execute(
        f"""
        DELETE FROM role_permission
        WHERE permission_id IN (SELECT id FROM permission WHERE code IN ({codes}));
        DELETE FROM permission WHERE code IN ({codes});
        ALTER TABLE pay_run_employee DROP COLUMN IF EXISTS payslip_details;
        """
    )
