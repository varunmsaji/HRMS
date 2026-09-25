"""RELEASE_HARDENING_PHASE_3B — the one-time operator step DATA-01's own plan documented but never
shipped a runnable entrypoint for (`core/crypto/provisioning.py`'s own docstring: "Called by an
operator-run step... never automatically at application boot"). `app.py`'s `lifespan()` refuses to
boot any non-development environment without exactly one `ACTIVE` `encryption_keys` row — this is
what creates that first row, wrapped under `PII_MASTER_KEY`. Idempotent by rejection, not by
silent no-op: a second run against an environment that already has an ACTIVE key fails loudly (the
database's own `encryption_keys_one_active_idx` partial unique index), rather than silently doing
nothing or generating a second key.

Run once per environment, before the first `api`/`worker`/`beat` container starts serving traffic
— see docs/deployment/PRODUCTION_DEPLOYMENT.md:

    docker compose -f docker-compose.prod.yml --profile tools run --rm migrate \\
        python scripts/provision_encryption_key.py
"""

import asyncio
import os

from hrms.core.config.settings import get_settings
from hrms.core.crypto.provisioning import provision_initial_key
from hrms.core.db.session import dispose_engine, get_engine, get_session_factory


async def main() -> None:
    settings = get_settings()
    get_engine(settings)
    factory = get_session_factory(settings)
    async with factory() as session:
        row = await provision_initial_key(session, settings=settings, created_by="deploy-script")
    await dispose_engine()
    print(f"Provisioned encryption_keys row: id={row.id} key_version={row.key_version}")


if __name__ == "__main__":
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev",
    )
    os.environ.setdefault("JWT_ACCESS_SECRET", "dev-access-secret-min-16-chars")
    os.environ.setdefault("JWT_REFRESH_SECRET", "dev-refresh-secret-min-16-chars")
    asyncio.run(main())
