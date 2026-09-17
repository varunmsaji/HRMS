"""Account Invite — `docs/modules/employee/41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md`
Phase 2, §6.

Direct structural copy of `onboarding_token` (`20260905090000_onboarding_o1.py`), corrected
up front to skip the RLS mistake that table needed a follow-up migration
(`20260906090000_onboarding_o2`) to fix: **no RLS policy on this table at all**. The public
accept-token flow (`GET/POST /public/account-invites/{token}...`) has no tenant context yet when
it looks this row up by hash — the whole point of the token is to *establish* `company_id` for
every subsequent, RLS-protected query in the same request. `company_id` stays as a plain,
unenforced column for that purpose, re-validated by every query that follows (identical reasoning
to `onboarding_token`'s own docstring).

Also grants the new `EMPLOYEE.INVITE` permission code (`employee/permissions.py`) to every
existing `COMPANY_ADMIN` and `HR_ADMIN` role — mirrors `20260920090000_default_roles_backfill.py`'s
own idempotent backfill pattern, needed because `HR_ADMIN` didn't exist in the live schema until
that migration, and `EMPLOYEE.INVITE` didn't exist in code until this one.

Revision ID: 20260921090000
Revises: 20260920090000
"""

from alembic import op

revision = "20260921090000"
down_revision = "20260920090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS account_invite (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "email" VARCHAR(255) NOT NULL,
            "employee_id" UUID,
            "role_code" VARCHAR(60) NOT NULL,
            "token_hash" VARCHAR(64) NOT NULL,
            "created_by_user_id" UUID NOT NULL,
            "expires_at" TIMESTAMPTZ NOT NULL,
            "accepted_at" TIMESTAMPTZ,
            "revoked_at" TIMESTAMPTZ,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "account_invite_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "account_invite_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "account_invite_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "account_invite_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id")
              REFERENCES "user"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "account_invite_token_hash_key" UNIQUE ("token_hash")
        );

        CREATE INDEX IF NOT EXISTS account_invite_company_id_idx ON account_invite (company_id);
        CREATE INDEX IF NOT EXISTS account_invite_email_idx ON account_invite (email);
        CREATE INDEX IF NOT EXISTS account_invite_employee_id_idx ON account_invite (employee_id);

        -- No RLS — see module docstring above and `hrms.modules.account_invite.models`.

        INSERT INTO permission (id, code, domain, description)
        VALUES (
            gen_random_uuid(), 'EMPLOYEE.INVITE', 'EMPLOYEE',
            'Invite an employee to create their login account'
        )
        ON CONFLICT (code) DO NOTHING;

        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT r.id, p.id, 'COMPANY'
        FROM role r
        JOIN permission p ON p.code = 'EMPLOYEE.INVITE'
        WHERE r.code IN ('COMPANY_ADMIN', 'HR_ADMIN') AND r.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission
        WHERE permission_id IN (SELECT id FROM permission WHERE code = 'EMPLOYEE.INVITE');

        DROP TABLE IF EXISTS account_invite;
        """
    )
