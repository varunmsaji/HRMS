"""Leave decisions 12 and 13 - default role grants and the approval-reassign permission.

- New permission `LEAVE.APPLICATION_REASSIGN` (decision 13): HR hands a stuck approval stage to
  another eligible approver.
- `EMPLOYEE` (SELF): `LEAVE.APPLICATION_SUBMIT`, `LEAVE.BALANCE_VIEW` - submit and see their own
  leave. Before this, the default employee role could do neither.
- `REPORTING_MANAGER` (REPORTEE_TREE) and `BRANCH_MANAGER` (BRANCH): `LEAVE.BALANCE_VIEW_ALL` -
  see their reportees' / branch's leave applications and balances.
- `HR_ADMIN` (COMPANY): `LEAVE.BALANCE_VIEW_ALL`, `LEAVE.BALANCE_ADJUST`,
  `LEAVE.APPLICATION_SUBMIT_ON_BEHALF`, `LEAVE.APPLICATION_REASSIGN`.
- `COMPANY_ADMIN` (COMPANY): `LEAVE.APPLICATION_REASSIGN` (it already holds every other code).

Purely additive and idempotent (`ON CONFLICT DO NOTHING`), the same shape as
`20260926090000_approval_authority_backfill.py`; `organisation/service.py::register_company`
makes the same grants for every new company. No leave-type or policy management is granted to
anyone new.

Revision ID: 20261010090000
Revises: 20261009091000
"""

from alembic import op

revision = "20261010090000"
down_revision = "20261009091000"
branch_labels = None
depends_on = None

# (role code, data scope, permission codes)
_GRANTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("EMPLOYEE", "SELF", ("LEAVE.APPLICATION_SUBMIT", "LEAVE.BALANCE_VIEW")),
    ("REPORTING_MANAGER", "REPORTEE_TREE", ("LEAVE.BALANCE_VIEW_ALL",)),
    ("BRANCH_MANAGER", "BRANCH", ("LEAVE.BALANCE_VIEW_ALL",)),
    (
        "HR_ADMIN",
        "COMPANY",
        (
            "LEAVE.BALANCE_VIEW_ALL",
            "LEAVE.BALANCE_ADJUST",
            "LEAVE.APPLICATION_SUBMIT_ON_BEHALF",
            "LEAVE.APPLICATION_REASSIGN",
        ),
    ),
    ("COMPANY_ADMIN", "COMPANY", ("LEAVE.APPLICATION_REASSIGN",)),
)


def _codes(codes: tuple[str, ...]) -> str:
    return ", ".join(f"'{code}'" for code in codes)


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permission (id, code, domain, description)
        VALUES (gen_random_uuid(), 'LEAVE.APPLICATION_REASSIGN', 'LEAVE',
                'Reassign a leave application''s current approval stage to another approver')
        ON CONFLICT (code) DO NOTHING;
        """
    )
    for role_code, scope, codes in _GRANTS:
        op.execute(
            f"""
            INSERT INTO role_permission (role_id, permission_id, data_scope)
            SELECT r.id, p.id, '{scope}'
            FROM role r
            JOIN permission p ON p.code IN ({_codes(codes)})
            WHERE r.code = '{role_code}' AND r.deleted_at IS NULL
            ON CONFLICT (role_id, permission_id) DO NOTHING;
            """
        )


def downgrade() -> None:
    for role_code, _scope, codes in _GRANTS:
        op.execute(
            f"""
            DELETE FROM role_permission
            WHERE permission_id IN (SELECT id FROM permission WHERE code IN ({_codes(codes)}))
              AND role_id IN (SELECT id FROM role WHERE code = '{role_code}');
            """
        )
    op.execute("DELETE FROM permission WHERE code = 'LEAVE.APPLICATION_REASSIGN';")
