"""Seed B1 identity foundation data (demo companies, users, RBAC)."""

import asyncio
import os

from hrms.core.config.settings import get_settings
from hrms.core.db.session import dispose_engine, get_engine, get_session_factory
from hrms.seed.bootstrap import seed_b1_foundation


async def main() -> None:
    settings = get_settings()
    get_engine(settings)
    factory = get_session_factory(settings)
    async with factory() as session:
        await seed_b1_foundation(session)
        await session.commit()
    await dispose_engine()
    print("B1 seed data applied successfully.")


if __name__ == "__main__":
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev",
    )
    os.environ.setdefault("JWT_ACCESS_SECRET", "dev-access-secret-min-16-chars")
    os.environ.setdefault("JWT_REFRESH_SECRET", "dev-refresh-secret-min-16-chars")
    asyncio.run(main())
