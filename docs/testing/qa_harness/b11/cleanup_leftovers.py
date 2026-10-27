"""Removes tenants left behind by a harness run whose teardown failed (disposable DB only; owner role; run via stack.sh py)."""
import asyncio

from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_security import _cleanup_scoped_users
from tests.integration.tenant_wipe import wipe_tenant

from hrms.core.db.session import dispose_engine, get_session_factory, set_rls_company_id


async def main() -> None:
    async with get_session_factory()() as s:
        ids = [r[0] for r in (await s.execute(text("SELECT id FROM company"))).all()]
    print("companies before:", len(ids))
    for cid in ids:
        async with get_session_factory()() as s:
            await set_rls_company_id(s, str(cid))
            for t in ("attendance_break", "attendance_day"):
                await s.execute(text(f"DELETE FROM {t} WHERE company_id = :c"), {"c": str(cid)})
            for t in ("account_invite", "refresh_token", "session"):
                await s.execute(text(f'DELETE FROM "{t}" WHERE company_id = :c'), {"c": str(cid)}) if t == "account_invite" else None
            await s.commit()
    for cid in ids:
        await wipe_tenant(company_id=cid, user_id=None)
    await _cleanup_scoped_users()
    async with get_session_factory()() as s:
        n = (await s.execute(text("SELECT count(*) FROM company"))).scalar()
    print("companies after:", n)
    await dispose_engine()


asyncio.run(main())
