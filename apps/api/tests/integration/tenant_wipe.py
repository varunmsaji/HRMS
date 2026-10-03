"""Generic per-tenant teardown for tests that create many kinds of rows.

Discovers every table carrying a `company_id` column and deletes this tenant's rows, retrying in
passes so FK order never has to be hand-maintained — then defers to the registration suite's own
`_cleanup` for the identity/company rows. Tables it must not touch before `_cleanup` runs
(`company`, memberships, roles) are skipped here."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from hrms.core.db.session import get_session_factory, set_rls_company_id

from .modules.organisation.test_registration_flow import _cleanup

_SKIP = {"company", "user_company", "role", "session", "refresh_token", "audit_log"}


async def wipe_tenant(*, company_id: UUID, user_id: UUID | None) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        names = (
            (
                await session.execute(
                    text(
                        "SELECT DISTINCT table_name FROM information_schema.columns "
                        "WHERE column_name = 'company_id' AND table_schema = 'public'"
                    )
                )
            )
            .scalars()
            .all()
        )
        pending = [n for n in names if n not in _SKIP]
        for _ in range(8):
            still: list[str] = []
            for table in pending:
                try:
                    async with session.begin_nested():
                        await session.execute(
                            text(f'DELETE FROM "{table}" WHERE company_id = :cid'),
                            {"cid": str(company_id)},
                        )
                except DBAPIError:
                    still.append(table)
            pending = still
            if not pending:
                break
        await session.commit()
    await _cleanup(company_id=company_id, user_id=user_id)
