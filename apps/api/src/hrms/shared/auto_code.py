"""Server-generated identifying codes (`BR-001`, `DEPT-002`, `WC-001`, ...)."""

from typing import Any
from uuid import UUID

from sqlalchemy import Integer, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession


async def next_auto_code(
    session: AsyncSession, *, model: Any, company_id: UUID, prefix: str
) -> str:
    """Next `<PREFIX>-NNN` code for the company. Serialised per company and entity with a
    transaction-scoped advisory lock (the code columns have no unique constraint), and
    soft-deleted rows are counted so a code is never reused. Codes that do not match the
    pattern (older hand-typed ones) are ignored."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"{model.__tablename__}_code:{company_id}"},
    )
    stmt = select(
        func.coalesce(
            func.max(func.substring(model.code, rf"^{prefix}-(\d+)$").cast(Integer)),
            0,
        )
    ).where(model.company_id == company_id)
    highest = (await session.execute(stmt)).scalar_one()
    return f"{prefix}-{highest + 1:03d}"
