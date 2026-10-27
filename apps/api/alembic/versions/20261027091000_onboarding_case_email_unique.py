"""One live onboarding case per candidate e-mail within a company (database-level backstop).

Revision ID: 20261027091000
Revises: 20261027090000

Rule (existing product policy, `OnboardingCaseRepository.get_active_case_by_email`, plan §13 Q5): per
company, case-insensitive on `personal_email`, among cases that are not soft-deleted and whose status
is not terminal (`ACTIVATED`, `EXPIRED`, `CANCELLED`). Historical (terminal / deleted) cases never
conflict. The application already enforces this with an advisory lock; the partial unique index makes
it hold for any other writer too.

The migration NEVER deletes, merges, edits or cancels rows. If live duplicates exist it stops before
creating the index and raises an error that names every conflicting (company, e-mail) group with the
case ids and statuses, so a person can decide which case to cancel/merge. It also refuses to run as a
role that is subject to row-level security, because such a role would see no rows and report a false
"clean" result.

Plain `CREATE UNIQUE INDEX` (a short write lock on `onboarding_case`, one transaction with the
check). On a very large table build it with `CREATE UNIQUE INDEX CONCURRENTLY` by hand instead.
Downgrade drops the index only.
"""

# ruff: noqa: E501 - long SQL / diagnostic strings

from alembic import op

revision = "20261027091000"
down_revision = "20261027090000"
branch_labels = None
depends_on = None

_LIVE = "deleted_at IS NULL AND status NOT IN ('ACTIVATED', 'EXPIRED', 'CANCELLED')"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        DECLARE
          groups bigint;
          detail text;
        BEGIN
          IF NOT (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user) THEN
            RAISE EXCEPTION 'cannot verify onboarding_case duplicates as role %: it is subject to row-level security'
              , current_user
              USING HINT = 'Run migrations as the schema-owner role (MIGRATIONS_DATABASE_URL).';
          END IF;

          SELECT count(*) INTO groups FROM (
            SELECT 1 FROM onboarding_case WHERE {_LIVE}
            GROUP BY company_id, lower(personal_email) HAVING count(*) > 1
          ) g;

          IF groups > 0 THEN
            SELECT string_agg(line, E'\\n' ORDER BY line) INTO detail FROM (
              SELECT format('company=%s email=%s cases=%s [%s]',
                            company_id, lower(personal_email), count(*),
                            string_agg(id::text || ':' || status, ', ' ORDER BY created_at, id)) AS line
              FROM onboarding_case WHERE {_LIVE}
              GROUP BY company_id, lower(personal_email) HAVING count(*) > 1
              ORDER BY company_id, lower(personal_email) LIMIT 100
            ) s;
            RAISE EXCEPTION 'onboarding_case: % company/e-mail group(s) have more than one live case; unique index NOT created, no row was changed'
              , groups
              USING DETAIL = detail,
                    HINT = 'Cancel or merge the duplicate cases listed (keep one per group), then re-run the upgrade. First 100 groups shown.';
          END IF;
        END $$;

        CREATE UNIQUE INDEX onboarding_case_company_live_email_key
          ON onboarding_case (company_id, lower(personal_email))
          WHERE {_LIVE};
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS onboarding_case_company_live_email_key;")
