-- Dedicated application runtime role (Doc: docs/architecture/POSTGRES_RLS_ROLE_MIGRATION_PLAN.md).
--
-- `hrms` (POSTGRES_USER, provisioned by the postgres:16-alpine image) is a superuser with
-- BYPASSRLS, which makes every RLS policy in this schema a no-op for its own connections
-- (Employee vertical audit Finding F1). `hrms` remains the schema owner and the role migrations
-- run as; it must never again be the role the application authenticates as.
--
-- `hrms_app` is a plain login role: NOT SUPERUSER, NOT BYPASSRLS, NOT CREATEDB/CREATEROLE. It owns
-- nothing, so it is unconditionally subject to every `tenant_isolation` RLS policy. It is granted
-- only the DML it needs (this app never issues DDL/TRUNCATE at runtime).
--
-- Idempotent: safe to re-run against an already-initialized database (this file is only picked up
-- automatically by Postgres on first container init; it is applied manually once against any
-- pre-existing data volume — see the migration plan's implementation sequence).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hrms_app') THEN
        CREATE ROLE hrms_app LOGIN PASSWORD 'hrms_app_dev_password'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO hrms_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hrms_app;
GRANT SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO hrms_app;

-- Any table a future migration creates (run as `hrms`, the schema owner) is automatically granted
-- to hrms_app without this script needing to be re-run.
ALTER DEFAULT PRIVILEGES FOR ROLE hrms IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hrms_app;
ALTER DEFAULT PRIVILEGES FOR ROLE hrms IN SCHEMA public
    GRANT SELECT, UPDATE ON SEQUENCES TO hrms_app;
