"""Default roles backfill — `HR_ADMIN`/`REPORTING_MANAGER`/`EMPLOYEE` for existing companies, plus
`SETTINGS.USER.MANAGE`/`SETTINGS.ROLE.MANAGE` granted to existing `COMPANY_ADMIN` roles.

`docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` Decision H locked these three roles; `docs/
modules/employee/41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md` §9 ("Rollout
Considerations") requires this backfill so a company registered before this feature shipped isn't
permanently missing the roles a future invite/role-assignment flow needs to assign. `organisation/
service.py::register_company` now seeds the same four grants (this migration's SQL mirrors that
code path exactly) for every *new* registration; this migration is the one-time catch-up for
every company that already exists.

Purely additive and idempotent — every insert is `ON CONFLICT ... DO NOTHING`, safe to re-run.
Does **not** assign any of the three new roles to any existing user — per Decision H and doc 41
Decision P2, an employee/second-admin only gets a role via an explicit future invite/role-
assignment action, never automatically as a side effect of this migration. `COMPANY_ADMIN`
role assignments for existing admins are untouched.

`permission.code` carries a real unique index (`permission_code_key`); `role.(company_id, code)`
carries a real unique index (`role_company_id_code_key`); `role_permission`'s composite PK is
`(role_id, permission_id)` — all three back the `ON CONFLICT` clauses below directly.

Revision ID: 20260920090000
Revises: 20260919090000
"""

from alembic import op

revision = "20260920090000"
down_revision = "20260919090000"
branch_labels = None
depends_on = None

_EMPLOYEE_PERMISSION_CODES = [
    "EMPLOYEE.VIEW_ALL",
    "EMPLOYEE.CREATE",
    "EMPLOYEE.UPDATE",
    "EMPLOYEE.DEACTIVATE",
    "EMPLOYEE.TERMINATE",
    "EMPLOYEE.TRANSFER",
    "EMPLOYEE.PROMOTE",
    "EMPLOYEE.VIEW_COMPENSATION",
    "EMPLOYEE.UPDATE_COMPENSATION",
    "EMPLOYEE.VIEW_STATUTORY",
    "EMPLOYEE.UPDATE_SENSITIVE",
    "EMPLOYEE.VIEW_BANKING",
    "EMPLOYEE.BULK_IMPORT",
    "EMPLOYEE.CONFIRM",
]


def upgrade() -> None:
    # `SETTINGS.USER.MANAGE`/`SETTINGS.ROLE.MANAGE` were never created by any live code path
    # before this — they may not exist in `permission` at all yet for a given environment.
    op.execute(
        """
        INSERT INTO permission (id, code, domain, description)
        VALUES
            (gen_random_uuid(), 'SETTINGS.USER.MANAGE', 'SETTINGS', 'Manage users'),
            (gen_random_uuid(), 'SETTINGS.ROLE.MANAGE', 'SETTINGS', 'Manage roles')
        ON CONFLICT (code) DO NOTHING;
        """
    )

    # Grant them to every existing COMPANY_ADMIN role — mirrors the new grant added to
    # `register_company` for new registrations.
    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT ca.id, p.id, 'COMPANY'
        FROM role ca
        JOIN permission p ON p.code IN ('SETTINGS.USER.MANAGE', 'SETTINGS.ROLE.MANAGE')
        WHERE ca.code = 'COMPANY_ADMIN' AND ca.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )

    # One HR_ADMIN / REPORTING_MANAGER / EMPLOYEE role per existing company (one row per company
    # already has exactly one COMPANY_ADMIN role, from that company's own registration).
    op.execute(
        """
        INSERT INTO role (id, company_id, code, name, is_system, created_at, updated_at)
        SELECT gen_random_uuid(), ca.company_id, 'HR_ADMIN', 'HR Administrator', true, now(), now()
        FROM role ca
        WHERE ca.code = 'COMPANY_ADMIN' AND ca.deleted_at IS NULL
        ON CONFLICT (company_id, code) DO NOTHING;

        INSERT INTO role (id, company_id, code, name, is_system, created_at, updated_at)
        SELECT gen_random_uuid(), ca.company_id, 'REPORTING_MANAGER', 'Reporting Manager', true,
               now(), now()
        FROM role ca
        WHERE ca.code = 'COMPANY_ADMIN' AND ca.deleted_at IS NULL
        ON CONFLICT (company_id, code) DO NOTHING;

        INSERT INTO role (id, company_id, code, name, is_system, created_at, updated_at)
        SELECT gen_random_uuid(), ca.company_id, 'EMPLOYEE', 'Employee', true, now(), now()
        FROM role ca
        WHERE ca.code = 'COMPANY_ADMIN' AND ca.deleted_at IS NULL
        ON CONFLICT (company_id, code) DO NOTHING;
        """
    )

    # HR_ADMIN — EMPLOYEE.VIEW plus the full EMPLOYEE.* catalogue, COMPANY scope (Decision H).
    employee_codes_sql = ", ".join(
        f"'{code}'" for code in ["EMPLOYEE.VIEW", *_EMPLOYEE_PERMISSION_CODES]
    )
    op.execute(
        f"""
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT hr.id, p.id, 'COMPANY'
        FROM role hr
        JOIN permission p ON p.code IN ({employee_codes_sql})
        WHERE hr.code = 'HR_ADMIN' AND hr.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )

    # REPORTING_MANAGER — EMPLOYEE.VIEW only, REPORTEE_TREE scope (Decision H).
    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT rm.id, p.id, 'REPORTEE_TREE'
        FROM role rm
        JOIN permission p ON p.code = 'EMPLOYEE.VIEW'
        WHERE rm.code = 'REPORTING_MANAGER' AND rm.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )

    # EMPLOYEE — VIEW/VIEW_COMPENSATION/VIEW_STATUTORY/VIEW_BANKING, SELF scope, no write
    # permissions at all (Decision H).
    op.execute(
        """
        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT emp.id, p.id, 'SELF'
        FROM role emp
        JOIN permission p ON p.code IN (
            'EMPLOYEE.VIEW', 'EMPLOYEE.VIEW_COMPENSATION', 'EMPLOYEE.VIEW_STATUTORY',
            'EMPLOYEE.VIEW_BANKING'
        )
        WHERE emp.code = 'EMPLOYEE' AND emp.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission
        WHERE role_id IN (
          SELECT id FROM role WHERE code IN ('HR_ADMIN', 'REPORTING_MANAGER', 'EMPLOYEE')
        );

        DELETE FROM role WHERE code IN ('HR_ADMIN', 'REPORTING_MANAGER', 'EMPLOYEE');

        DELETE FROM role_permission
        WHERE role_id IN (SELECT id FROM role WHERE code = 'COMPANY_ADMIN')
          AND permission_id IN (
              SELECT id FROM permission
              WHERE code IN ('SETTINGS.USER.MANAGE', 'SETTINGS.ROLE.MANAGE')
          );
        """
    )
