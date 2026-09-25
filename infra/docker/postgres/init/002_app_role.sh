#!/bin/sh
# Dedicated application runtime role (Doc: docs/architecture/POSTGRES_RLS_ROLE_MIGRATION_PLAN.md).
#
# `hrms` (POSTGRES_USER, provisioned by the postgres:16-alpine image) is a superuser with
# BYPASSRLS, which makes every RLS policy in this schema a no-op for its own connections
# (Employee vertical audit Finding F1). `hrms` remains the schema owner and the role migrations
# run as; it must never again be the role the application authenticates as.
#
# `hrms_app` is a plain login role: NOT SUPERUSER, NOT BYPASSRLS, NOT CREATEDB/CREATEROLE. It owns
# nothing, so it is unconditionally subject to every `tenant_isolation` RLS policy. It is granted
# only the DML it needs (this app never issues DDL/TRUNCATE at runtime).
#
# The role's password comes from HRMS_APP_PASSWORD (RELEASE_HARDENING_PHASE_6A / Finding DB-01) —
# never a literal in this file. It must be set by every environment's compose file: the dev
# compose (docker-compose.yml) sets it to a fixed, repo-visible dev-only value; the production
# compose (docker-compose.prod.yml) requires the operator to supply it (no default), so a missing
# value fails the stack closed instead of silently falling back to a repo-visible password.
#
# Fresh-volume vs. existing-volume semantics: this script, like every file in
# docker-entrypoint-initdb.d, is only executed by the postgres image on a *fresh* data volume
# (first-ever container start against an empty $PGDATA). It does NOT rerun just because
# HRMS_APP_PASSWORD later changes on an already-initialized volume — rotating the password on an
# existing production database is a separate, documented operator procedure
# (docs/deployment/PRODUCTION_DEPLOYMENT.md, "Rotating the hrms_app database password"), not
# something changing this env var alone will do.
#
# Idempotent: safe to re-run manually (e.g. via `psql -f` against an already-initialized database)
# — it only creates the role if it does not already exist; it does not reset the password of an
# existing role (see the rotation procedure above for that).

set -eu

: "${HRMS_APP_PASSWORD:?HRMS_APP_PASSWORD must be set — no hardcoded fallback password is provisioned (Finding DB-01)}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hrms_app') THEN
        CREATE ROLE hrms_app LOGIN PASSWORD '$HRMS_APP_PASSWORD'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END
\$\$;

GRANT USAGE ON SCHEMA public TO hrms_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hrms_app;
GRANT SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO hrms_app;

-- Any table a future migration creates (run as \`hrms\`, the schema owner) is automatically granted
-- to hrms_app without this script needing to be re-run.
ALTER DEFAULT PRIVILEGES FOR ROLE $POSTGRES_USER IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hrms_app;
ALTER DEFAULT PRIVILEGES FOR ROLE $POSTGRES_USER IN SCHEMA public
    GRANT SELECT, UPDATE ON SEQUENCES TO hrms_app;
EOSQL
