"""PRA-16 - leave history and the audit log are append-only for the runtime role.

`leave_ledger` (ADR-0004/DEC-004) and `leave_application_action` are documented as append-only,
and the application never updates or deletes a row of either, nor of `audit_log` (corrections are
new offsetting rows). Until now nothing enforced that: the runtime role `hrms_app` held the blanket
`UPDATE`/`DELETE` that the bootstrap grants every table, so any bug or compromised credential could
silently rewrite a balance or erase its trail.

This revokes `UPDATE`, `DELETE` and `TRUNCATE` on those three tables from `hrms_app` only. Inserts
and reads are untouched, so no application behaviour changes. The migration/owner role keeps full
rights (retention jobs, tenant erasure and the test harness run as the owner, deliberately).
The role may not exist in every environment, hence the guard.

Revision ID: 20261009090000
Revises: 20261008090000
"""

from alembic import op

revision = "20261009090000"
down_revision = "20261008090000"
branch_labels = None
depends_on = None

_TABLES = ("leave_ledger", "leave_application_action", "audit_log")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hrms_app') THEN
                    REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM hrms_app;
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hrms_app') THEN
                    GRANT UPDATE, DELETE ON {table} TO hrms_app;
                END IF;
            END $$;
            """
        )
