"""Create (or reset the password of) a platform super admin. Run on the server; there is
deliberately no public endpoint for this.

    uv run python scripts/create_platform_admin.py --username admin --password '...'
    uv run python scripts/create_platform_admin.py --username admin --password '...' --reset

The password is hashed with the same Argon2 settings as tenant users. NOTE: unlike tenant
registration this script does not enforce the strength policy, so choose a strong password in any
shared environment. MFA is not implemented yet (deferred by decision)."""

import argparse
import asyncio
import os
import re
import sys
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev")

from sqlalchemy import select

from hrms.core.auth.passwords import hash_password
from hrms.core.config.settings import get_settings
from hrms.core.db.session import dispose_engine, get_engine, get_session_factory
from hrms.modules.platform.models import PlatformAdmin

_USERNAME = re.compile(r"^[a-z0-9._-]{3,64}$")


async def main(username: str, password: str, reset: bool) -> int:
    username = username.strip().lower()
    if not _USERNAME.fullmatch(username):
        print("username must be 3-64 chars of a-z 0-9 . _ -", file=sys.stderr)
        return 2
    settings = get_settings()
    get_engine(settings)
    factory = get_session_factory(settings)
    try:
        async with factory() as session:
            existing = (
                await session.execute(
                    select(PlatformAdmin).where(PlatformAdmin.username == username)
                )
            ).scalar_one_or_none()
            if existing is not None and not reset:
                print(f"platform admin {username!r} already exists (--reset to change it)")
                return 1
            if existing is None:
                session.add(
                    PlatformAdmin(
                        id=uuid4(), username=username, password_hash=hash_password(password)
                    )
                )
                print(f"created platform admin {username!r}")
            else:
                existing.password_hash = hash_password(password)
                existing.failed_login_count = 0
                existing.locked_until = None
                existing.status = "ACTIVE"
                print(f"password reset for platform admin {username!r}")
            await session.commit()
        return 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.username, args.password, args.reset)))
