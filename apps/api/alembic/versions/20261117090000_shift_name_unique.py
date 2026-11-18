"""One live shift name per company, and no blank shift name (database-level backstop).

Revision ID: 20261117090000
Revises: 20261116120000

`docs/audits/SHIFT_CREATION_VALIDATION_AUDIT_2026-11-17.md` SC-01 / SC-02, owner decisions D-1 and D-2.

Rule (existing product policy, `OrganisationService._assert_shift_name_free`): per company, compared as
`lower(btrim(name))`, among shifts that are not soft-deleted. A deactivated shift keeps its name; only a
deleted shift releases it. The application already serialises creates and renames with an advisory lock;
the partial unique index makes the rule hold for any other writer too, and a second constraint refuses a
blank name on a live shift.

The migration NEVER edits, renames, merges or deletes a row (D-2: existing values are not normalised).
Before it changes anything it checks the live shifts and, if any of them would break either rule, stops
with an error that names every offending shift (company, shift id, code, active flag, the name quoted) so
a person can decide what to rename. It also refuses to run as a role that is subject to row-level
security, because such a role would see no rows and report a false "clean" result.

The table is locked (`SHARE ROW EXCLUSIVE`: reads continue, writes wait) for the check and the build, so no
shift can be created between them, and `lock_timeout` makes a stuck deploy fail instead of waiting behind
a long transaction. Plain `CREATE UNIQUE INDEX` on a small master table; one transaction with the check.

Downgrade drops the index and the constraint only.
"""

# ruff: noqa: E501 - long SQL / diagnostic strings

from alembic import op

revision = "20261117090000"
down_revision = "20261116120000"
branch_labels = None
depends_on = None

_BLANK = r"name ~ '^[[:space:]]*$'"


def upgrade() -> None:
    op.execute(
        f"""
        SET LOCAL lock_timeout = '15s';
        LOCK TABLE shift IN SHARE ROW EXCLUSIVE MODE;

        DO $$
        DECLARE
          blanks bigint;
          groups bigint;
          blank_detail text;
          group_detail text;
        BEGIN
          IF NOT (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user) THEN
            RAISE EXCEPTION 'cannot verify shift names as role %: it is subject to row-level security'
              , current_user
              USING HINT = 'Run migrations as the schema-owner role (MIGRATIONS_DATABASE_URL).';
          END IF;

          SELECT count(*) INTO blanks FROM shift WHERE deleted_at IS NULL AND {_BLANK};
          SELECT count(*) INTO groups FROM (
            SELECT 1 FROM shift WHERE deleted_at IS NULL
            GROUP BY company_id, lower(btrim(name)) HAVING count(*) > 1
          ) g;

          IF blanks > 0 OR groups > 0 THEN
            SELECT string_agg(line, E'\\n' ORDER BY line) INTO blank_detail FROM (
              SELECT format('BLANK company=%s shift=%s code=%s active=%s name=%L',
                            company_id, id, code, is_active, name) AS line
              FROM shift WHERE deleted_at IS NULL AND {_BLANK}
              ORDER BY company_id, id LIMIT 100
            ) b;
            SELECT string_agg(line, E'\\n' ORDER BY line) INTO group_detail FROM (
              SELECT format('DUPLICATE company=%s name=%L shifts=%s [%s]',
                            company_id, lower(btrim(name)), count(*),
                            string_agg(id::text || ' code=' || coalesce(code, '-')
                                       || ' active=' || is_active::text || ' name=' || quote_literal(name),
                                       '; ' ORDER BY created_at, id)) AS line
              FROM shift WHERE deleted_at IS NULL
              GROUP BY company_id, lower(btrim(name)) HAVING count(*) > 1
              ORDER BY company_id, lower(btrim(name)) LIMIT 100
            ) d;
            RAISE EXCEPTION 'shift: % blank name(s) and % duplicate name group(s) among live shifts; unique index and name check NOT created, no row was changed'
              , blanks, groups
              USING DETAIL = concat_ws(E'\\n', blank_detail, group_detail),
                    HINT = 'Rename the shifts listed (keep one name per company, none blank), then re-run the upgrade. First 100 of each kind shown.';
          END IF;
        END $$;

        CREATE UNIQUE INDEX shift_company_live_name_key
          ON shift (company_id, lower(btrim(name)))
          WHERE deleted_at IS NULL;

        ALTER TABLE shift
          ADD CONSTRAINT shift_live_name_not_blank_check
          CHECK (deleted_at IS NOT NULL OR NOT ({_BLANK}));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE shift DROP CONSTRAINT IF EXISTS shift_live_name_not_blank_check;
        DROP INDEX IF EXISTS shift_company_live_name_key;
        """
    )
