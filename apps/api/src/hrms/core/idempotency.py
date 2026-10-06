"""Database-backed `Idempotency-Key` support for mutations a client may retry after a lost response.

Lifecycle, all inside the request's own transaction:

1. `claim`: `INSERT … ON CONFLICT DO NOTHING` on the unique `(company_id, operation, key)` row.
   A concurrent request with the same key blocks on that unique index until the first transaction
   ends, which serialises them with no lock of our own (the wait is bounded; see `claim`).
2. The business mutation runs. If anything fails the transaction rolls back, the claim goes with
   it, and the key stays usable: a failed attempt can never poison a key.
3. `complete` stores the response on the same row, and the one commit makes the mutation, its audit
   record and the stored response visible together.

A request that finds the row already committed compares fingerprints: equal replays the stored
response without running the operation, different is a 409. Every committed row therefore carries
its response; a row without one can only be this transaction's own claim.

The fingerprint is a SHA-256 over the canonical JSON of the fields the caller passes: the
operation's business fields and the acting user, nothing else. Transport details (headers, IP,
user agent, `If-Match`) are excluded, and no raw request body is stored, only that digest.
"""

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Header, Response
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import get_settings
from hrms.core.db.models.idempotency import IdempotencyKey
from hrms.core.db.timeouts import bounded_lock_wait
from hrms.core.errors.base import ConflictError, ValidationError

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:\-]{8,128}$")


class IdempotencyKeyRequiredError(ValidationError):
    code = "IDEMPOTENCY_KEY_REQUIRED"


class IdempotencyKeyInvalidError(ValidationError):
    code = "IDEMPOTENCY_KEY_INVALID"


class IdempotencyKeyConflictError(ConflictError):
    code = "IDEMPOTENCY_KEY_CONFLICT"


def _detail(code: str, message: str) -> list[dict[str, str]]:
    return [{"field": IDEMPOTENCY_KEY_HEADER, "code": code, "message": message}]


def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_KEY_HEADER)] = None,
) -> str:
    """FastAPI dependency for endpoints that make the header mandatory."""
    if idempotency_key is None or not idempotency_key.strip():
        raise IdempotencyKeyRequiredError(
            "The Idempotency-Key header is required for this request",
            details=_detail("IDEMPOTENCY_KEY_REQUIRED", "Send a unique Idempotency-Key header"),
        )
    key = idempotency_key.strip()
    if not _KEY_PATTERN.fullmatch(key):
        raise IdempotencyKeyInvalidError(
            "The Idempotency-Key header must be 8-128 characters: letters, digits, . _ : -",
            details=_detail("IDEMPOTENCY_KEY_INVALID", "Use a UUID or another opaque token"),
        )
    return key


def fingerprint(operation: str, fields: dict[str, Any]) -> str:
    """Deterministic digest of the operation and the fields that materially affect it."""
    canonical = json.dumps(
        {"operation": operation, "fields": fields},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def request_fingerprint_fields(
    body: BaseModel, actor_user_id: UUID | None, **extra: object
) -> dict[str, object]:
    """What makes two idempotent requests "the same": every business field of the body plus the
    acting user (and any server-resolved target). Transport details are deliberately excluded."""
    return {"actor": str(actor_user_id), "body": body.model_dump(mode="json"), **extra}


def mark_replay(response: Response, replayed: bool, status_code: int) -> None:
    """Tells the client a stored response was replayed rather than the operation run again."""
    if replayed:
        response.status_code = status_code
        response.headers["Idempotent-Replayed"] = "true"


@dataclass(frozen=True)
class IdempotentResult[T: BaseModel]:
    data: T
    status_code: int
    replayed: bool


async def run_idempotent[T: BaseModel](
    session: AsyncSession,
    *,
    company_id: UUID,
    operation: str,
    key: str,
    fingerprint_fields: dict[str, Any],
    response_model: type[T],
    status_code: int,
    execute: Callable[[], Awaitable[T]],
) -> IdempotentResult[T]:
    """Runs `execute` at most once per (company, operation, key); see the module docstring."""
    digest = fingerprint(operation, fingerprint_fields)
    claim_stmt = (
        pg_insert(IdempotencyKey)
        .values(
            id=uuid4(),
            company_id=company_id,
            operation=operation,
            idempotency_key=key,
            request_fingerprint=digest,
        )
        .on_conflict_do_nothing(constraint="uq_idempotency_key")
        .returning(IdempotencyKey.id)
    )
    async with bounded_lock_wait(session, lock_timeout_ms=get_settings().idempotency_wait_ms):
        claimed_id = (await session.execute(claim_stmt)).scalar_one_or_none()

    if claimed_id is None:
        # The row was committed by an earlier request (or the one we just waited on).
        existing = (
            await session.execute(
                select(IdempotencyKey).where(
                    IdempotencyKey.company_id == company_id,
                    IdempotencyKey.operation == operation,
                    IdempotencyKey.idempotency_key == key,
                )
            )
        ).scalar_one()
        if existing.request_fingerprint != digest or existing.response_body is None:
            raise IdempotencyKeyConflictError(
                "This Idempotency-Key was already used for a different request",
                details=_detail(
                    "IDEMPOTENCY_KEY_CONFLICT", "Use a new Idempotency-Key for a different request"
                ),
            )
        return IdempotentResult(
            data=response_model.model_validate(existing.response_body),
            status_code=existing.response_status or status_code,
            replayed=True,
        )

    result = await execute()
    await session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.id == claimed_id)
        .values(
            response_status=status_code,
            response_body=result.model_dump(mode="json"),
            completed_at=func.now(),
        )
    )
    return IdempotentResult(data=result, status_code=status_code, replayed=False)


__all__ = [
    "IDEMPOTENCY_KEY_HEADER",
    "IdempotencyKeyConflictError",
    "IdempotencyKeyInvalidError",
    "IdempotencyKeyRequiredError",
    "IdempotentResult",
    "fingerprint",
    "mark_replay",
    "request_fingerprint_fields",
    "require_idempotency_key",
    "run_idempotent",
]
