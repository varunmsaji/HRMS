"""Two-role test harness support: a privileged *admin* role for fixtures and teardown, and the real
application runtime role (`hrms_app`) for the code under test.

Why (docs/blind-audit-2026-10-29/HRMS_P1_VERIFICATION_REPORT.md, V-1): the suite's default
`DATABASE_URL` is the schema owner `hrms` (SUPERUSER + BYPASSRLS), so RLS-dependent bugs pass. This
module does not switch the suite's default role (that is a module-by-module migration, a later
stage); it provides the pieces that make such a migration, and the proof that RLS is enforced, safe:

* `admin_async_url()` / `runtime_async_url()` - the two URLs, derived from the environment the
  suite was pointed at (never hard-coded to a shared database).
* `assert_role_is_unprivileged()` - the guard: the runtime role is not a superuser and does not
  bypass RLS (nor create roles/databases/replication).
* `target_problems()` - the runtime URL must name the same host/port/database as the admin URL
  (so an explicit `HRMS_APP_DATABASE_URL` cannot silently point at another database) and a
  different user.
* `app_as_runtime_role()` - repoints the app's global engine at `hrms_app` for a block and restores
  the admin role afterwards, so setup/cleanup written against the admin role keeps working without
  the runtime role ever being granted more than DML.
"""

import os
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from hrms.core.config.settings import get_settings
from hrms.core.db.session import dispose_engine

#: Repository-visible dev credential for the runtime role (docker-compose.yml, CI, the QA stack).
_DEFAULT_RUNTIME_USER = "hrms_app"
_DEFAULT_RUNTIME_PASSWORD = "hrms_app_dev_password"


def _plain(url: str) -> str:
    return url.split("?", 1)[0]


def _async(url: str) -> str:
    """Raw `create_async_engine` calls bypass `Settings.ensure_asyncpg_driver`."""
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


def admin_url(env: Mapping[str, str] | None = None) -> str:
    """The privileged role the suite runs as: whatever `DATABASE_URL` says."""
    return _plain((env or os.environ)["DATABASE_URL"])


def runtime_url(env: Mapping[str, str] | None = None) -> str:
    """The application role on the same host/port/database as the admin URL.

    `HRMS_APP_DATABASE_URL` wins when exported (the QA stack does); otherwise the repository-visible
    dev credentials are substituted into `DATABASE_URL`."""
    source = env or os.environ
    explicit = source.get("HRMS_APP_DATABASE_URL")
    if explicit:
        return _plain(explicit)
    parts = urlsplit(admin_url(source))
    host = parts.netloc.rsplit("@", 1)[-1]
    netloc = f"{_DEFAULT_RUNTIME_USER}:{_DEFAULT_RUNTIME_PASSWORD}@{host}"
    return parts._replace(netloc=netloc).geturl()


def target_problems(admin: str, runtime: str) -> list[str]:
    """Why `runtime` is not the application role on the same database as `admin`. Never echoes a
    URL: only the field names that differ."""
    a, r = urlsplit(admin), urlsplit(runtime)
    problems = [
        f"runtime and admin URLs differ in {field}"
        for field, left, right in (
            ("host", a.hostname, r.hostname),
            ("port", a.port, r.port),
            ("database", a.path, r.path),
        )
        if left != right
    ]
    if a.username == r.username:
        problems.append("runtime and admin URLs use the same user")
    return problems


def admin_async_url() -> str:
    return _async(admin_url())


def runtime_async_url() -> str:
    return _async(runtime_url())


def make_engine(url: str) -> AsyncEngine:
    """`NullPool`: a harness connection never lingers, so a transaction-local `app.company_id`
    cannot leak between checks through a pooled connection."""
    return create_async_engine(url, poolclass=NullPool)


_ATTRIBUTES_SQL = text(
    "SELECT current_user AS name, r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb, "
    "r.rolreplication FROM pg_roles r WHERE r.rolname = current_user"
)


async def role_attributes(conn: AsyncConnection) -> dict[str, object]:
    row = (await conn.execute(_ATTRIBUTES_SQL)).one()
    return dict(row._mapping)


def unprivileged_problems(attrs: dict[str, object]) -> list[str]:
    """Why `attrs` (from `role_attributes`) is not an acceptable application-under-test role."""
    problems: list[str] = []
    for flag, label in (
        ("rolsuper", "SUPERUSER"),
        ("rolbypassrls", "BYPASSRLS"),
        ("rolcreaterole", "CREATEROLE"),
        ("rolcreatedb", "CREATEDB"),
        ("rolreplication", "REPLICATION"),
    ):
        if attrs.get(flag) is not False:
            problems.append(f"role {attrs.get('name')!r} has {label} (or its state is unknown)")
    return problems


async def assert_role_is_unprivileged(conn: AsyncConnection) -> None:
    """The harness guard: fail loudly if the connection is not safe to use as the application."""
    problems = unprivileged_problems(await role_attributes(conn))
    if problems:
        raise AssertionError(
            "The application-under-test role would bypass RLS:\n  - " + "\n  - ".join(problems)
        )


@asynccontextmanager
async def app_as_runtime_role(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[None]:
    """Repoints the app's global engine at the runtime role for the block, verifies the role, and
    restores the admin role on exit so cleanup written against the admin role keeps working."""
    previous = os.environ["DATABASE_URL"]
    problems = target_problems(admin_url(), runtime_url())
    if problems:
        raise AssertionError("Unsafe two-role target:\n  - " + "\n  - ".join(problems))
    monkeypatch.setenv("DATABASE_URL", runtime_url())
    get_settings.cache_clear()
    await dispose_engine()
    try:
        engine = make_engine(runtime_async_url())
        try:
            async with engine.connect() as conn:
                await assert_role_is_unprivileged(conn)
        finally:
            await engine.dispose()
        yield
    finally:
        monkeypatch.setenv("DATABASE_URL", previous)
        get_settings.cache_clear()
        await dispose_engine()
