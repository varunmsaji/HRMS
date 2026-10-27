"""Work that must happen only after the surrounding transaction has really committed.

An email (or any other external side effect) issued in the middle of a request cannot be taken
back if the transaction later rolls back: the recipient holds a link whose token never existed
(B12 / DEF-B11-04). `defer_until_commit` queues the action on the SQLAlchemy session instead.
The queue follows the transaction exactly like `observability.business_events`:

* an action queued inside a SAVEPOINT is dropped when that SAVEPOINT rolls back;
* every action is dropped when the whole transaction rolls back;
* on a real commit the queued actions become *ready*, and `run_post_commit` - called by
  `session_scope` / `get_session` right after `session.commit()` returns - awaits them in the
  order they were queued.

Delivery is therefore at-most-once and happens strictly after the business state is durable. It
is not a durable outbox: a process that dies between the commit and the delivery loses the
action. For the callers today (invite and activation emails, each re-issuable by HR) that is the
accepted trade; a persisted outbox table would be the next step if at-least-once delivery is ever
required (documented in the B12 report).

An action that raises is logged and swallowed - the business transaction has already committed and
cannot be undone by a failed notification.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from hrms.core.observability.logging import get_logger, safe_error, safe_log

_logger = get_logger(__name__)

Action = Callable[[], Awaitable[None]]
_PENDING = "hrms_post_commit_pending"
_READY = "hrms_post_commit_ready"
_Entry = tuple[SessionTransaction | None, Action]


def defer_until_commit(session: AsyncSession, action: Action) -> None:
    sync = session.sync_session
    txn = sync.get_nested_transaction() or sync.get_transaction()
    pending: list[_Entry] = sync.info.setdefault(_PENDING, [])
    pending.append((txn, action))


def _within(txn: SessionTransaction | None, ended: SessionTransaction) -> bool:
    if txn is None:
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
def _mark_ready(session: Session) -> None:
    pending: list[_Entry] = session.info.pop(_PENDING, None) or []
    if pending:
        session.info.setdefault(_READY, []).extend(action for _txn, action in pending)


async def run_post_commit(session: AsyncSession) -> None:
    """Awaits the actions made ready by the commit that just happened. Never raises."""
    ready: list[Action] = session.sync_session.info.pop(_READY, None) or []
    for action in ready:
        try:
            await action()
        except Exception as exc:  # noqa: BLE001 - the transaction is already committed
            safe_log(_logger.error, "post_commit_action_failed", **safe_error(exc))
