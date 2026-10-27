"""D11 guard - the application's runtime database role must not be able to rewrite or erase history.

`hrms_app` is the role the API connects as. Migrations REVOKE write privileges on append-only
tables, but `infra/docker/postgres/init/002_app_role.sh` grants broad DML with `ON ALL TABLES` and
default privileges, so *re-running it on an already-migrated database silently undoes the
migrations* (reproduced 2026-10-25: `leave_ledger` went from INSERT,SELECT to
DELETE,INSERT,SELECT,UPDATE). This test fails loudly if that - or any new migration/grant - hands
the runtime role UPDATE, DELETE or TRUNCATE on a table that must be append-only.

Only privileges are read (`has_table_privilege`); nothing is granted, revoked or written, and the
test runs against whatever disposable database `DATABASE_URL` names.

`punch`, `attendance_regularization_action` and `attendance_period_action` are documented as
immutable but are NOT enforced at the database level today (decision D11 in
docs/architecture/OBSERVABILITY_ARCHITECTURE.md section 15). When that is approved and migrated,
move them into `APPEND_ONLY` in the same change.
"""

import pytest
from sqlalchemy import text

from hrms.core.db.session import get_session_factory

pytestmark = pytest.mark.asyncio

RUNTIME_ROLE = "hrms_app"

#: INSERT and SELECT only. Corrections are new rows, never edits.
APPEND_ONLY = (
    "audit_log",
    "email_log",
    "leave_application_action",
    "leave_ledger",
    "leave_year_end_run",
    "platform_audit_log",
)

#: Rows may be updated (a key's response is filled in) but never deleted or truncated.
NO_DELETE = ("idempotency_key",)


async def _can(table: str, privilege: str) -> bool:
    async with get_session_factory()() as session:
        return bool(
            (
                await session.execute(
                    text("SELECT has_table_privilege(:role, :table, :privilege)"),
                    {"role": RUNTIME_ROLE, "table": table, "privilege": privilege},
                )
            ).scalar_one()
        )


async def test_every_guarded_table_exists_so_the_guard_cannot_go_vacuous() -> None:
    async with get_session_factory()() as session:
        present = {
            row[0]
            for row in (
                await session.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).all()
        }
    missing = sorted(set(APPEND_ONLY + NO_DELETE) - present)
    assert not missing, f"guarded tables no longer exist (renamed? update this list): {missing}"


@pytest.mark.parametrize("table", APPEND_ONLY)
async def test_append_only_tables_give_the_runtime_role_insert_and_select_only(table: str) -> None:
    for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
        assert await _can(table, privilege) is False, f"{RUNTIME_ROLE} can {privilege} {table}"
    for privilege in ("INSERT", "SELECT"):
        assert await _can(table, privilege) is True, f"{RUNTIME_ROLE} lost {privilege} on {table}"


@pytest.mark.parametrize("table", NO_DELETE)
async def test_tables_that_may_be_updated_can_still_not_be_deleted_or_truncated(table: str) -> None:
    for privilege in ("DELETE", "TRUNCATE"):
        assert await _can(table, privilege) is False, f"{RUNTIME_ROLE} can {privilege} {table}"


async def test_the_runtime_role_can_truncate_no_table_at_all() -> None:
    async with get_session_factory()() as session:
        truncatable = [
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT c.relname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                        "AND has_table_privilege(:role, c.oid, 'TRUNCATE') ORDER BY 1"
                    ),
                    {"role": RUNTIME_ROLE},
                )
            ).all()
        ]
    assert truncatable == [], f"{RUNTIME_ROLE} can TRUNCATE: {truncatable}"
