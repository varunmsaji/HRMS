"""Initial schema — ported from v1.0 SQL migration to Alembic (Document 08 §14)."""

from pathlib import Path

from alembic import op

revision = "20260803124757"
down_revision = None
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parent.parent.parent / "scripts" / "sql"


def _run(filename: str) -> None:
    sql = (SQL_DIR / filename).read_text(encoding="utf-8")
    connection = op.get_bind().connection.driver_connection
    connection.execute(sql)


def upgrade() -> None:
    # 001_init_schema.sql is self-contained (tables, RLS, effective-dating constraints).
    _run("001_init_schema.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade not supported for initial schema revision")
