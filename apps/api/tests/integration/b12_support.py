"""B12 regression-test support: exact before/after database snapshots for denied-operation
assertions ("a rejected request changes nothing").

Every function opens its own session with the tenant's RLS variable set, so the numbers are what
that tenant can see, read the way the application would read them."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import text

from hrms.core.db.session import get_session_factory, set_rls_company_id

#: Tables whose row set must be byte-for-byte identical after a denied operation. `audit_log` is
#: included on purpose: a denied call must not leave a success (or any) audit event behind.
_FINGERPRINT_TABLES = ("attendance_day", "audit_log", "account_invite", "overtime_record")


async def fingerprint(company_id: UUID) -> dict[str, Any]:
    """Row count plus an md5 over the full serialised rows, per table, for one tenant."""
    out: dict[str, Any] = {}
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in _FINGERPRINT_TABLES:
            row = (
                await session.execute(
                    text(
                        f"SELECT count(*), coalesce(md5(string_agg(to_jsonb(t)::text, '|' "
                        f"ORDER BY t.id::text)), '') FROM {table} t WHERE t.company_id = :cid"
                    ),
                    {"cid": str(company_id)},
                )
            ).one()
            out[table] = (row[0], row[1])
        out["email_log"] = (
            await session.execute(
                text("SELECT count(*) FROM email_log WHERE company_id = :cid"),
                {"cid": str(company_id)},
            )
        ).scalar_one()
    return out


async def scalar(company_id: UUID, sql: str, **params: Any) -> Any:
    """One value from a tenant-scoped query (`:cid` is always bound)."""
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        return (await session.execute(text(sql), {"cid": str(company_id), **params})).scalar_one()


async def audit_count(company_id: UUID, action: str | None = None) -> int:
    if action is None:
        return int(await scalar(company_id, "SELECT count(*) FROM audit_log WHERE company_id=:cid"))
    return int(
        await scalar(
            company_id,
            "SELECT count(*) FROM audit_log WHERE company_id=:cid AND action=:a",
            a=action,
        )
    )


# --- B13 --------------------------------------------------------------------------------------


async def run_in_processes(
    specs: list[dict[str, Any]], *, lead_seconds: float = 12.0
) -> list[dict[str, Any]]:
    """Runs each HTTP request spec (see `tests/integration/b13_mp.py`) in its OWN OS process and
    returns the decoded results in order. All processes are released at the same instant."""
    import asyncio
    import json
    import sys
    import time

    start_at = time.time() + lead_seconds
    procs = [
        await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tests.integration.b13_mp",
            json.dumps({**spec, "start_at": start_at}),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        for spec in specs
    ]
    results: list[dict[str, Any]] = []
    for proc in procs:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=lead_seconds + 90)
        assert proc.returncode == 0, (
            f"worker process failed rc={proc.returncode}: {err.decode()[-800:]}"
        )
        results.append(json.loads(out.decode().strip().splitlines()[-1]))
    return results


async def run_proc(*args: str, check: bool = True) -> tuple[int, str]:
    """Runs `tests.integration.b13_outbox_proc <args>` as a separate OS process; returns
    (returncode, last stdout line)."""
    import asyncio
    import sys

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.integration.b13_outbox_proc",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
    last = out.decode().strip().splitlines()[-1] if out.strip() else ""
    if check:
        assert proc.returncode in (0, 137), f"rc={proc.returncode}: {err.decode()[-1500:]}"
    return int(proc.returncode or 0), last


LIVE_EMAIL_INDEX = "onboarding_case_company_live_email_key"


@asynccontextmanager
async def live_email_index_absent() -> AsyncIterator[None]:
    """Runs a block as on a database that does not have migration 20261027091000 yet, i.e. without
    the unique index on live onboarding-case e-mails, so the B12 'legacy duplicate rows' shape can
    be built. The index is recreated on exit (the block must have removed its rows by then).
    Disposable QA database only - this is DDL."""
    async with get_session_factory()() as session:
        await session.execute(text(f"DROP INDEX IF EXISTS {LIVE_EMAIL_INDEX}"))
        await session.commit()
    try:
        yield
    finally:
        async with get_session_factory()() as session:
            await session.execute(
                text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {LIVE_EMAIL_INDEX} "
                    "ON onboarding_case (company_id, lower(personal_email)) "
                    "WHERE deleted_at IS NULL "
                    "AND status NOT IN ('ACTIVATED', 'EXPIRED', 'CANCELLED')"
                )
            )
            await session.commit()
