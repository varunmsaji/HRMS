"""Login/token-refresh tenant lookup: a narrow SECURITY DEFINER function to resolve a user's
company memberships before tenant context (and therefore the `app.company_id` RLS GUC) can exist.

Per docs/architecture/POSTGRES_RLS_ROLE_MIGRATION_PLAN.md, the app's runtime role (`hrms_app`) has
no RLS bypass — correct and intentional, that plan's whole point. But `user_company` carries
`FORCE ROW LEVEL SECURITY`, and login/token-refresh must read a user's company memberships
*before* any company_id is known — there is no header, JWT, or prior verified state to derive
`app.company_id` from yet. Without an escape hatch, RLS hides every row and login/refresh can
never succeed under `hrms_app`. This gap was not caught by the role migration's own verification
because its test suite (and the app's default local test config) connects as `hrms`, which
bypasses RLS entirely — the login code path was never actually exercised under the restricted
runtime role.

Rather than widen `hrms_app`'s own privileges (would defeat the role split) or set a stateful
session-variable bypass for the duration of one query (risky under connection pooling — a
forgotten reset could leak across pooled connections into an unrelated later request), this adds
one narrow function: owned by `hrms` (the migration role), `SECURITY DEFINER` so it always runs
with the owner's RLS-bypass privileges regardless of caller, `EXECUTE` granted only to `hrms_app`
(not `PUBLIC`), `SET search_path = public` (mandatory hardening for `SECURITY DEFINER` functions —
prevents search-path hijacking). It takes only a user_id and returns only the two columns the
login/refresh code paths actually need (`company_id`, `is_primary`) — not the full `user_company`
row, and no company_id parameter, so it cannot be used to enumerate an arbitrary company's
membership list, only "this exact user's own memberships."

Revision ID: 20260828090000
Revises: 20260826090000
"""

from alembic import op

revision = "20260828090000"
down_revision = "20260826090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION login_lookup_user_companies(p_user_id UUID)
        RETURNS TABLE (company_id UUID, is_primary BOOLEAN)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT uc.company_id, uc.is_primary
            FROM user_company uc
            WHERE uc.user_id = p_user_id AND uc.status = 'ACTIVE';
        $$;

        REVOKE ALL ON FUNCTION login_lookup_user_companies(UUID) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION login_lookup_user_companies(UUID) TO hrms_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS login_lookup_user_companies(UUID);")
