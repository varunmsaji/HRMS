import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import dotenv_values
from sqlalchemy import engine_from_config, pool

from hrms.core.config.settings import get_settings
from hrms.core.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# Migrations run DDL (CREATE TABLE, CREATE POLICY, ...), which requires the schema-owner role.
# That role must never be the same credential the running application authenticates as (see
# docs/architecture/POSTGRES_RLS_ROLE_MIGRATION_PLAN.md) — so migrations read a dedicated
# MIGRATIONS_DATABASE_URL when present, falling back to the app's own DATABASE_URL otherwise (e.g.
# for environments that haven't set the new variable yet). Read from the real OS environment first
# (how CI/deploy pipelines supply it) and only then from `.env` (how local dev supplies it) —
# `Settings` itself deliberately has no field for this, so the app's own process never loads the
# migration/admin credential into memory.
db_url = (
    os.environ.get("MIGRATIONS_DATABASE_URL")
    or dotenv_values(".env").get("MIGRATIONS_DATABASE_URL")
    or settings.database_url
)
if "?schema=" in db_url:
    db_url = db_url.split("?", 1)[0]
# Alembic runs synchronously; use the psycopg sync driver regardless of which async/plain scheme
# the source URL used.
if db_url.startswith("postgresql+asyncpg://"):
    sync_url = db_url.replace("+asyncpg", "+psycopg")
elif db_url.startswith("postgresql://"):
    sync_url = "postgresql+psycopg://" + db_url[len("postgresql://") :]
else:
    sync_url = db_url
config.set_main_option("sqlalchemy.url", sync_url)

target_metadata = Base.metadata


def run_sql_file(revision_dir: Path, filename: str) -> None:
    sql_path = revision_dir.parent.parent / "scripts" / "sql" / filename
    sql = sql_path.read_text(encoding="utf-8")
    context.execute(sql)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
