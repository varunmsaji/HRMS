"""Transactional e-mail outbox (B13, Workstream A).

Why: B12 delivered e-mail from an in-process hook that ran after commit. That kept rolled-back work
from ever being mailed, but a process that died between the commit and the delivery lost the message
for good (at-most-once). This module makes the hand-over durable.

Producer (`enqueue_email`, inside the business transaction)
    Inserts one `email_outbox` row with the business change itself. The row commits with it and
    disappears with a rollback or a rolled-back SAVEPOINT; nothing is delivered before the commit
    because nothing is delivered by the producer at all. After a real commit a *dispatch* is
    triggered (`celery`: a task for the worker; `inline`: this process; `none`: leave it to the
    sweep) - it is only a hint, the row is the source of truth.

    `message_id` is the stable key of the logical message (UNIQUE). Enqueueing the same key again
    stores nothing new, so replaying the same business operation cannot produce a second message.

Consumer (`deliver_message` / `deliver_due`, in the Celery worker)
    1. CLAIM in a short transaction of its own: PENDING & due (or SENDING with an expired lease)
       becomes SENDING with a lease, `attempts` + 1. One UPDATE; concurrent claimers cannot both
       win the row (the loser re-evaluates the WHERE after the winner commits and no longer matches;
       the batch claim uses `FOR UPDATE SKIP LOCKED`). The transaction is committed before sending.
    2. SEND with no database transaction open.
    3. RECORD the outcome with a guarded UPDATE (`WHERE status='SENDING' AND locked_by=<my claim>`):
       SENT (bodies blanked), PENDING again with exponential backoff (transient failure), or FAILED
       (permanent failure, or attempts exhausted). A worker that dies leaves SENDING + an expiring
       lease, which the next sweep takes over; a row stuck in SENDING at max attempts becomes
       FAILED.

Guarantees (stated plainly): durable AT-LEAST-ONCE hand-over to the provider, with
duplicate-logical-message protection at enqueue time. It is NOT exactly-once: if a worker is killed
after the provider
accepted a message but before SENT is recorded, or a send times out after the provider took it
(`outcome="unknown"`), the retry sends it again. The providers used here (SMTP, Mailtrap, Hostinger)
give no idempotency key to prevent that.

`email_log` stays the per-attempt delivery ledger (written by the sender); the outbox is the
per-message state machine. Neither stores a token after the message is done (bodies are blanked).
"""

import asyncio
import os
import socket
import time
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.post_commit import defer_until_commit
from hrms.core.db.session import get_session_factory
from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.core.tenancy.context import TenantContext, current_request_id, tenant_scope
from hrms.modules.onboarding.email_sender import (
    _KIND_OVERRIDE,
    EmailDeliveryError,
    EmailSender,
    get_email_sender,
    log_email_failure,
)
from hrms.modules.platform.models import EmailOutbox

_logger = get_logger(__name__)

Outcome = Literal["sent", "retry", "failed", "skipped"]

_COLUMNS = (
    "id, message_id, company_id, kind, failure_kind, context, recipient, subject, "
    "text_body, html_body, attempts, max_attempts, locked_by"
)


@dataclass(frozen=True, slots=True)
class Claimed:
    id: UUID
    message_id: str
    company_id: UUID | None
    kind: str
    failure_kind: str
    context: dict[str, Any]
    recipient: str
    subject: str
    text_body: str
    html_body: str
    attempts: int
    max_attempts: int
    token: str


def backoff_seconds(attempts: int, settings: Settings) -> int:
    """Delay before the next try after `attempts` tries have failed: base * 2^(n-1), capped."""
    return int(
        min(
            settings.email_outbox_backoff_cap_seconds,
            settings.email_outbox_backoff_base_seconds * (2 ** max(0, attempts - 1)),
        )
    )


# --------------------------------------------------------------------------------------- producer


async def enqueue_email(
    session: AsyncSession,
    *,
    message_id: str,
    kind: str,
    failure_kind: str,
    to: str,
    subject: str,
    html_body: str,
    text_body: str,
    company_id: str | UUID | None = None,
    context: dict[str, Any] | None = None,
    inline_sender: EmailSender | None = None,
    settings: Settings | None = None,
) -> UUID:
    """Writes the outbox row in `session`'s transaction (inside its own SAVEPOINT, so a failure here
    leaves the surrounding transaction usable) and registers the post-commit dispatch. Returns the
    outbox id - of the existing row when `message_id` was already enqueued."""
    cfg = settings or get_settings()
    new_id = uuid4()
    values = {
        "id": new_id,
        "message_id": message_id[:200],
        "company_id": UUID(str(company_id)) if company_id else None,
        "kind": kind[:80],
        "failure_kind": failure_kind[:80],
        "context": context or {},
        "recipient": to[:320],
        "subject": subject,
        "text_body": text_body,
        "html_body": html_body,
        "max_attempts": cfg.email_outbox_max_attempts,
        "request_id": current_request_id(),
    }
    async with session.begin_nested():
        inserted = (
            await session.execute(
                pg_insert(EmailOutbox)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[EmailOutbox.message_id])
                .returning(EmailOutbox.id)
            )
        ).scalar_one_or_none()
        if inserted is None:  # the logical message already exists: no second row, no second send
            existing = (
                await session.execute(
                    text("SELECT id FROM email_outbox WHERE message_id = :m"),
                    {"m": values["message_id"]},
                )
            ).scalar_one()
            return UUID(str(existing))

    async def _dispatch() -> None:
        await dispatch(new_id, inline_sender=inline_sender, settings=cfg)

    defer_until_commit(session, _dispatch)
    return new_id


async def dispatch(
    outbox_id: UUID, *, inline_sender: EmailSender | None = None, settings: Settings | None = None
) -> None:
    """The post-commit hint. Never raises: the row is already durable and the sweep will find it."""
    cfg = settings or get_settings()
    mode = cfg.email_outbox_dispatch
    try:
        if mode == "inline":
            await deliver_message(outbox_id, sender=inline_sender, settings=cfg)
        elif mode == "celery":
            from hrms.modules.onboarding.tasks import deliver_outbox_message

            await asyncio.to_thread(deliver_outbox_message.delay, str(outbox_id))
    except Exception as exc:  # noqa: BLE001 - dispatch is only a hint, see above
        safe_log(_logger.warning, "email.outbox.dispatch_failed", mode=mode, **safe_error(exc))


# --------------------------------------------------------------------------------------- consumer


def _new_token() -> str:
    return f"{socket.gethostname()[:20]}:{os.getpid()}:{uuid4().hex[:16]}"


def _row_to_claim(row: Any) -> Claimed:
    return Claimed(
        id=row.id,
        message_id=row.message_id,
        company_id=row.company_id,
        kind=row.kind,
        failure_kind=row.failure_kind,
        context=dict(row.context or {}),
        recipient=row.recipient,
        subject=row.subject,
        text_body=row.text_body or "",
        html_body=row.html_body or "",
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        token=row.locked_by,
    )


_CLAIMABLE = (
    "attempts < max_attempts AND ("
    "(status = 'PENDING' AND next_attempt_at <= clock_timestamp()) OR "
    "(status = 'SENDING' AND locked_until < clock_timestamp()))"
)
_CLAIM_SET = (
    "status = 'SENDING', attempts = attempts + 1, locked_by = :tok, "
    "locked_until = clock_timestamp() + make_interval(secs => CAST(:lease AS double precision)), "
    "last_attempt_at = clock_timestamp(), updated_at = clock_timestamp()"
)


async def fail_exhausted() -> int:
    """A message whose lease expired with every attempt used (the worker died on its last try)
    can never be claimed again; it ends FAILED instead of lingering in SENDING."""
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                text(
                    "UPDATE email_outbox SET status = 'FAILED', failed_at = clock_timestamp(), "
                    "updated_at = clock_timestamp(), locked_by = NULL, locked_until = NULL, "
                    "text_body = NULL, html_body = NULL, "
                    "last_failure_class = coalesce(last_failure_class, 'lease_expired') "
                    "WHERE status = 'SENDING' AND locked_until < clock_timestamp() "
                    "AND attempts >= max_attempts RETURNING failure_kind, context"
                )
            )
        ).all()
        await session.commit()
    for failure_kind, context in rows:
        safe_log(
            _logger.error, "email.outbox.abandoned", email_kind=failure_kind, **(context or {})
        )
    return len(rows)


async def _claim_one(outbox_id: UUID, lease: int) -> Claimed | None:
    token = _new_token()
    async with get_session_factory()() as session:
        row = (
            await session.execute(
                text(
                    f"UPDATE email_outbox SET {_CLAIM_SET} WHERE id = :id AND {_CLAIMABLE} "
                    f"RETURNING {_COLUMNS}"
                ),
                {"id": outbox_id, "tok": token, "lease": lease},
            )
        ).first()
        await session.commit()
    return None if row is None else _row_to_claim(row)


async def _claim_batch(limit: int, lease: int) -> list[Claimed]:
    token = _new_token()
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                text(
                    "WITH due AS (SELECT id FROM email_outbox "
                    f"WHERE {_CLAIMABLE} ORDER BY next_attempt_at, created_at "
                    "LIMIT :n FOR UPDATE SKIP LOCKED) "
                    f"UPDATE email_outbox o SET {_CLAIM_SET} FROM due WHERE o.id = due.id "
                    f"RETURNING o.{_COLUMNS.replace(', ', ', o.')}"
                ),
                {"n": limit, "tok": token, "lease": lease},
            )
        ).all()
        await session.commit()
    return [_row_to_claim(r) for r in rows]


async def _record_success(c: Claimed) -> None:
    async with get_session_factory()() as session:
        done = cast(
            CursorResult[Any],
            await session.execute(
                text(
                    "UPDATE email_outbox SET status = 'SENT', sent_at = clock_timestamp(), "
                    "updated_at = clock_timestamp(), locked_by = NULL, locked_until = NULL, "
                    "text_body = NULL, html_body = NULL "
                    "WHERE id = :id AND status = 'SENDING' AND locked_by = :tok"
                ),
                {"id": c.id, "tok": c.token},
            ),
        ).rowcount
        await session.commit()
    if not done:  # the lease ran out and another worker took over: it may send a duplicate
        safe_log(_logger.warning, "email.outbox.stale_completion", email_kind=c.failure_kind)


async def _record_failure(c: Claimed, exc: BaseException, cfg: Settings) -> Outcome:
    retryable = exc.retryable if isinstance(exc, EmailDeliveryError) else True
    failure_class = exc.failure_class if isinstance(exc, EmailDeliveryError) else "internal"
    final = (not retryable) or c.attempts >= c.max_attempts
    delay = backoff_seconds(c.attempts, cfg)
    async with get_session_factory()() as session:
        done = cast(
            CursorResult[Any],
            await session.execute(
                text(
                    "UPDATE email_outbox SET "
                    "status = CASE WHEN :final THEN 'FAILED' ELSE 'PENDING' END, "
                    "failed_at = CASE WHEN :final THEN clock_timestamp() ELSE failed_at END, "
                    "next_attempt_at = CASE WHEN :final THEN next_attempt_at ELSE "
                    "clock_timestamp() + make_interval(secs => CAST(:delay AS double precision)) "
                    "END, "
                    "text_body = CASE WHEN :final THEN NULL ELSE text_body END, "
                    "html_body = CASE WHEN :final THEN NULL ELSE html_body END, "
                    "last_failure_class = :fc, last_error_type = :et, "
                    "locked_by = NULL, locked_until = NULL, updated_at = clock_timestamp() "
                    "WHERE id = :id AND status = 'SENDING' AND locked_by = :tok"
                ),
                {
                    "final": final,
                    "delay": delay,
                    "fc": failure_class[:40],
                    "et": type(exc).__name__[:80],
                    "id": c.id,
                    "tok": c.token,
                },
            ),
        ).rowcount
        await session.commit()
    if not done:
        safe_log(_logger.warning, "email.outbox.stale_completion", email_kind=c.failure_kind)
        return "skipped"
    # One `email.delivery.failed` record per failed attempt (LOG-06 / the failure metrics), as for
    # every best-effort send before the outbox existed; the retry line below adds the schedule.
    log_email_failure(c.failure_kind, exc, **c.context)
    if final:
        return "failed"
    safe_log(
        _logger.warning,
        "email.outbox.retry_scheduled",
        email_kind=c.failure_kind,
        attempt=c.attempts,
        retry_in_seconds=delay,
        failure_class=failure_class,
        **c.context,
    )
    return "retry"


async def _attempt(c: Claimed, sender: EmailSender | None, cfg: Settings) -> Outcome:
    """Step 2 and 3 for one claimed message. No database transaction is open while sending."""
    try:
        chosen = sender or get_email_sender(cfg)
        scope = TenantContext(company_id=c.company_id) if c.company_id else None
        with tenant_scope(scope):
            token = _KIND_OVERRIDE.set(c.kind)
            try:
                await chosen.send(
                    to=c.recipient, subject=c.subject, html_body=c.html_body, text_body=c.text_body
                )
            finally:
                _KIND_OVERRIDE.reset(token)
    except Exception as exc:  # noqa: BLE001 - classified and recorded, never propagated
        return await _record_failure(c, exc, cfg)
    await _record_success(c)
    return "sent"


async def deliver_message(
    outbox_id: UUID, *, sender: EmailSender | None = None, settings: Settings | None = None
) -> Outcome:
    """Claims and delivers one message if it is due. A duplicate task for a message that is already
    SENT, FAILED, backing off or leased by another worker claims nothing and returns `skipped`."""
    cfg = settings or get_settings()
    claimed = await _claim_one(outbox_id, cfg.email_outbox_lease_seconds)
    if claimed is None:
        return "skipped"
    return await _attempt(claimed, sender, cfg)


async def deliver_due(
    *,
    sender: EmailSender | None = None,
    settings: Settings | None = None,
    time_budget_seconds: float = 150.0,
) -> dict[str, int]:
    """The sweep: claims due messages in batches and delivers them until none is due or the time
    budget is spent. Safe to run from several workers at once (`SKIP LOCKED` + leases)."""
    cfg = settings or get_settings()
    counts = {"sent": 0, "retry": 0, "failed": 0, "skipped": 0}
    counts["failed"] += await fail_exhausted()
    started = time.monotonic()
    while time.monotonic() - started < time_budget_seconds:
        batch = await _claim_batch(cfg.email_outbox_batch_size, cfg.email_outbox_lease_seconds)
        if not batch:
            break
        for claimed in batch:
            counts[await _attempt(claimed, sender, cfg)] += 1
    return counts
