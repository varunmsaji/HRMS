"""Mission Phase 5 — operational business-lifecycle events that are emitted only once the
transaction that produced them has really committed.

A log line written in the middle of a request transaction that later rolls back would claim a
transition (a pay run approved, a leave decided) that never happened. `emit_after_commit`
queues the event on the SQLAlchemy session instead; it is written in `after_commit` and dropped
when the transaction — or the SAVEPOINT it was queued in — rolls back.

These are *operational* events for correlation by `request_id`/`task_id`. The business audit
trail stays in Postgres `audit_log` with its own redaction and retention; nothing here reads or
replaces it. Fields must be identifiers and fixed codes only — never names, amounts, salary
figures, document contents or a serialized entity.
"""

import re
from typing import Any

import structlog
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from hrms.core.observability.logging import get_logger, safe_log
from hrms.core.observability.metrics import COMMITTED_EVENTS, safe_count

_logger = get_logger("hrms.business")
_ENTITY_TYPE = re.compile(r"[a-z][a-z0-9_]{0,39}")
_PENDING = "hrms_pending_business_events"

_Entry = tuple[SessionTransaction | None, str, dict[str, Any], dict[str, Any]]


def emit_after_commit(session: AsyncSession | Session, event_name: str, **fields: Any) -> None:
    sync = session.sync_session if isinstance(session, AsyncSession) else session
    txn = sync.get_nested_transaction() or sync.get_transaction()
    # The log context (request_id, task_id, verified tenant) as it is *now*; the commit may run
    # in a dependency teardown after some of it has been unbound.
    context = structlog.contextvars.get_contextvars()
    pending: list[_Entry] = sync.info.setdefault(_PENDING, [])
    pending.append((txn, event_name, fields, context))


def _within(txn: SessionTransaction | None, ended: SessionTransaction) -> bool:
    if txn is None:
        # Queued before the session autobegan: it belongs to the root transaction.
        return ended.parent is None
    while txn is not None:
        if txn is ended:
            return True
        txn = txn.parent
    return False


@event.listens_for(Session, "after_soft_rollback")
def _drop_rolled_back(session: Session, previous_transaction: SessionTransaction) -> None:
    pending: list[_Entry] | None = session.info.get(_PENDING)
    if pending:
        session.info[_PENDING] = [e for e in pending if not _within(e[0], previous_transaction)]


@event.listens_for(Session, "after_commit")
def _emit_committed(session: Session) -> None:
    pending: list[_Entry] = session.info.pop(_PENDING, None) or []
    for _txn, event_name, fields, context in pending:
        with structlog.contextvars.bound_contextvars(**context):
            # Counted here - after_commit - so the metric, like the log line, never reports a
            # transition that rolled back. `entity_type` is a table-like name from code, bounded.
            entity = fields.get("entity_type")
            safe_count(
                COMMITTED_EVENTS,
                event_name,
                entity if isinstance(entity, str) and _ENTITY_TYPE.fullmatch(entity) else "other",
            )
            safe_log(_logger.info, event_name, **fields)
