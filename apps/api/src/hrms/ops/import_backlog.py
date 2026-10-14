"""Read-only reconciliation of queued employee-import messages against batch state.

    docker compose -f docker-compose.prod.yml exec -T worker python -m hrms.ops.import_backlog
    ... python -m hrms.ops.import_backlog --company-id <uuid> --stale-pending-hours 48

This answers one operator question before the worker is allowed to drain `reports_exports`:
*for each queued `employee_import.process_batch` message, what does the database say about the
batch, and is it safe to let that message run?* It **never** changes anything:

* Redis: only `LRANGE` / `LLEN`. No `RPOP`, `LREM`, `DEL`, `FLUSH*`, and no task is ever
  published, acknowledged or revoked.
* Postgres: every session runs `SET TRANSACTION READ ONLY` (the database refuses writes) and is
  rolled back, never committed.

Nothing is inferred from a queued message alone. A message proves only that *something once
asked* for the batch to run; the batch row is the source of truth for its state. When the
database cannot answer (batch not visible, company unknown, message unparseable) the verdict is
`MANUAL_REVIEW`, not a guess. The tool never decides whether old business data is reprocessed or
discarded: even `ELIGIBLE_TO_RUN` is a statement about the batch row, and running it remains an
explicit operator decision (see decision D-B in the execution report).

Verdicts (`recommendation`):

* `ELIGIBLE_TO_RUN` — PENDING, exactly one queued message, recent, no later batch for the same
  file. Would be claimed and processed exactly once.
* `SAFE_TO_DRAIN` — batch is terminal (COMPLETED / COMPLETED_WITH_ERRORS / FAILED) or already
  PROCESSING. The worker's atomic claim skips the message (`employee_import.batch.skipped`,
  `reason=not_pending`); it cannot create employees.
* `MANUAL_REVIEW` — anything ambiguous: stale PENDING, PENDING with no message, duplicate
  messages, a later batch with the same filename (possible manual resubmission), a batch the
  database cannot show, PROCESSING beyond the hard time limit (stuck), unknown status.

The verdict for a message whose batch is `PENDING` and **stale** is deliberately
`MANUAL_REVIEW`: the guard only prevents duplicate runs, it does not know the data is old.
Staleness threshold: `--stale-pending-hours` (default 24, a provisional value).
"""

import argparse
import asyncio
import base64
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID

import redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import get_settings
from hrms.core.db.session import session_scope

QUEUE = "reports_exports"
TASK_NAME = "employee_import.process_batch"
#: Matches `time_limit` on the task: a PROCESSING batch older than this plus a margin is stuck.
PROCESS_TIME_LIMIT_SECONDS = 3600
TERMINAL_STATUSES = {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"}
_PAGE = 500


class _SyncRedis(Protocol):
    def llen(self, name: str) -> int: ...
    def lrange(self, name: str, start: int, end: int) -> list[bytes]: ...


@dataclass(frozen=True)
class QueuedMessage:
    position: int  # 0 = newest; the worker consumes from the highest position (oldest) first
    task_id: str | None
    company_id: str | None
    batch_id: str | None
    enqueued_at: float | None
    retries: int | None


def _as_uuid(value: object) -> str | None:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def parse_message(position: int, raw: bytes) -> tuple[QueuedMessage | None, str | None]:
    """Returns `(message, other_task)`. `message` is set only for a parseable
    `employee_import.process_batch`; `other_task` carries the task name (or `"unparseable"`) for
    anything else so it is counted, never guessed at."""
    try:
        envelope = json.loads(raw)
        headers = envelope.get("headers") or {}
        task = headers.get("task")
    except (ValueError, AttributeError):
        return None, "unparseable"
    if task != TASK_NAME:
        return None, str(task) if task else "unparseable"
    company_id = batch_id = None
    try:
        body = json.loads(base64.b64decode(envelope["body"]))
        args = body[0]
        company_id, batch_id = _as_uuid(args[0]), _as_uuid(args[1])
    except (ValueError, KeyError, IndexError, TypeError):
        pass  # unparseable arguments: surfaced below as a message with no IDs
    enqueued = headers.get("hrms_enqueued_at")
    return (
        QueuedMessage(
            position=position,
            task_id=headers.get("id"),
            company_id=company_id,
            batch_id=batch_id,
            enqueued_at=float(enqueued) if isinstance(enqueued, (int, float)) else None,
            retries=headers.get("retries"),
        ),
        None,
    )


def read_queue(client: _SyncRedis, queue: str = QUEUE) -> tuple[list[QueuedMessage], Counter[str]]:
    """Non-consuming read of the whole queue, newest first."""
    messages: list[QueuedMessage] = []
    other: Counter[str] = Counter()
    total = int(client.llen(queue))
    for start in range(0, total, _PAGE):
        for offset, raw in enumerate(client.lrange(queue, start, start + _PAGE - 1)):
            message, other_task = parse_message(start + offset, raw)
            if message is not None:
                messages.append(message)
            elif other_task is not None:
                other[other_task] += 1
    return messages, other


def classify(
    *,
    batch: dict[str, Any] | None,
    message_count: int,
    later_same_file: list[str],
    now: datetime,
    stale_pending: timedelta,
) -> tuple[str, str, list[str]]:
    """`(state, recommendation, reasons)` for one batch. Pure: no I/O, easy to test."""
    if batch is None:
        return (
            "NOT_VISIBLE",
            "MANUAL_REVIEW",
            ["no batch row visible for this company/id (deleted, wrong company, or RLS)"],
        )
    status = str(batch["status"])
    reasons: list[str] = []
    if message_count > 1:
        reasons.append(f"{message_count} queued messages for this batch")
    if later_same_file:
        reasons.append(
            "a later batch for the same company/filename exists "
            f"({', '.join(later_same_file)}): possible manual resubmission"
        )

    if status in TERMINAL_STATUSES:
        reasons.append(f"batch is {status}; the worker's claim will skip the message")
        if status != "FAILED" and message_count == 0:
            reasons.append("no queued message")
        return "TERMINAL", "SAFE_TO_DRAIN", reasons

    if status == "PROCESSING":
        started = batch.get("started_at")
        limit = timedelta(seconds=PROCESS_TIME_LIMIT_SECONDS * 2)
        if started is not None and now - started > limit:
            reasons.append(
                f"PROCESSING since {started.isoformat()}, beyond the {PROCESS_TIME_LIMIT_SECONDS}s "
                "hard limit: stuck; rows may be partly created, do not re-run blindly"
            )
            return "STALE_PROCESSING", "MANUAL_REVIEW", reasons
        reasons.append("claimed by a worker; a redelivered message will be skipped")
        return "IN_PROGRESS", "SAFE_TO_DRAIN", reasons

    if status == "PENDING":
        if batch.get("processed_rows") or batch.get("success_count") or batch.get("error_count"):
            reasons.append("PENDING but has non-zero progress counters: inconsistent")
            return "AMBIGUOUS", "MANUAL_REVIEW", reasons
        age = now - batch["created_at"]
        if message_count == 0:
            reasons.append("PENDING with no queued message: lost, consumed, or never enqueued")
            return "PENDING_NO_MESSAGE", "MANUAL_REVIEW", reasons
        if age > stale_pending:
            reasons.append(
                f"PENDING for {round(age.total_seconds() / 3600, 1)}h "
                f"(> {round(stale_pending.total_seconds() / 3600, 1)}h): the data may be outdated; "
                "running it is a business decision"
            )
            return "STALE_PENDING", "MANUAL_REVIEW", reasons
        if message_count == 1 and not later_same_file:
            reasons.append("recent PENDING batch with a single message")
            return "PENDING", "ELIGIBLE_TO_RUN", reasons
        return "PENDING", "MANUAL_REVIEW", reasons

    reasons.append(f"unrecognised status {status!r}")
    return "AMBIGUOUS", "MANUAL_REVIEW", reasons


_BATCH_SQL = text(
    "SELECT id, company_id, status, original_filename, total_rows, processed_rows, "
    "success_count, error_count, created_at, started_at, completed_at, version "
    "FROM employee_import_batch WHERE company_id = :cid"
)


async def _fetch_company_batches(company_id: str) -> dict[str, dict[str, Any]]:
    """Every batch of one company (the table is small per tenant). All of them are needed:
    the wanted ones, the open ones, and same-filename siblings for resubmission detection."""
    async with session_scope(company_id=company_id) as session:
        await _read_only(session)
        rows = (await session.execute(_BATCH_SQL, {"cid": company_id})).mappings().all()
        await session.rollback()  # never commit from a reconciliation run
    return {str(row["id"]): dict(row) for row in rows}


async def _read_only(session: AsyncSession) -> None:
    await session.execute(text("SET TRANSACTION READ ONLY"))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def reconcile(
    messages: list[QueuedMessage],
    batches_by_company: dict[str, dict[str, dict[str, Any]]],
    *,
    now: datetime,
    stale_pending: timedelta,
    scanned_companies: set[str],
) -> list[dict[str, Any]]:
    by_batch: dict[tuple[str, str], list[QueuedMessage]] = defaultdict(list)
    unidentified = [m for m in messages if not (m.company_id and m.batch_id)]
    for m in messages:
        if m.company_id and m.batch_id:
            by_batch[(m.company_id, m.batch_id)].append(m)

    # Every batch we can see: those with messages, and (when scanned) open ones without.
    keys: set[tuple[str, str]] = set(by_batch)
    for company_id in scanned_companies:
        for batch_id, known in batches_by_company.get(company_id, {}).items():
            if known["status"] in {"PENDING", "PROCESSING"}:
                keys.add((company_id, batch_id))

    report: list[dict[str, Any]] = []
    for company_id, batch_id in sorted(keys):
        batch: dict[str, Any] | None = batches_by_company.get(company_id, {}).get(batch_id)
        queued = by_batch.get((company_id, batch_id), [])
        later: list[str] = []
        if batch is not None:
            later = sorted(
                str(other["id"])
                for other in batches_by_company.get(company_id, {}).values()
                if other["id"] != batch["id"]
                and other["original_filename"] == batch["original_filename"]
                and other["created_at"] > batch["created_at"]
            )
        state, recommendation, reasons = classify(
            batch=batch,
            message_count=len(queued),
            later_same_file=later,
            now=now,
            stale_pending=stale_pending,
        )
        report.append({
            "company_id": company_id,
            "batch_id": batch_id,
            "state": state,
            "recommendation": recommendation,
            "reasons": reasons,
            "status": batch["status"] if batch else None,
            "original_filename": batch["original_filename"] if batch else None,
            "created_at": batch["created_at"].isoformat() if batch else None,
            "started_at": _iso(batch["started_at"]) if batch else None,
            "counters": {
                k: batch[k]
                for k in ("total_rows", "processed_rows", "success_count", "error_count")
            } if batch else None,
            "queued_messages": [
                {"task_id": m.task_id, "position": m.position, "enqueued_at": m.enqueued_at}
                for m in queued
            ],
            "later_batches_same_filename": later,
        })  # fmt: skip
    for m in unidentified:
        report.append({
            "company_id": m.company_id,
            "batch_id": m.batch_id,
            "state": "UNIDENTIFIED_MESSAGE",
            "recommendation": "MANUAL_REVIEW",
            "reasons": ["queued import message whose arguments could not be read"],
            "queued_messages": [{"task_id": m.task_id, "position": m.position}],
        })  # fmt: skip
    return report


async def collect(
    client: _SyncRedis,
    *,
    company_ids: list[str],
    all_companies: bool,
    now: datetime | None = None,
    stale_pending: timedelta = timedelta(hours=24),
    queue: str = QUEUE,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    messages, other_tasks = read_queue(client, queue)
    queue_depth = int(client.llen(queue))

    message_companies = {m.company_id for m in messages if m.company_id}
    scanned = {c for c in (_as_uuid(c) for c in company_ids) if c}
    if all_companies:
        scanned |= await _all_company_ids()
    batches: dict[str, dict[str, dict[str, Any]]] = {}
    unreachable: dict[str, str] = {}
    for company_id in sorted(message_companies | scanned):
        try:
            batches[company_id] = await _fetch_company_batches(company_id)
        except Exception as exc:  # noqa: BLE001 - reported, never guessed around
            unreachable[company_id] = type(exc).__name__

    report = reconcile(
        messages, batches, now=now, stale_pending=stale_pending, scanned_companies=scanned
    )
    for item in report:
        if item["company_id"] in unreachable:
            item["recommendation"] = "MANUAL_REVIEW"
            item["reasons"].append(f"database lookup failed: {unreachable[item['company_id']]}")
    summary = Counter(item["recommendation"] for item in report)
    return {
        "read_only": True,
        "checked_at": now.isoformat(),
        "queue": {
            "name": queue,
            "depth": queue_depth,
            "import_messages": len(messages),
            "other_tasks": dict(other_tasks),
        },
        "companies_scanned_for_open_batches": sorted(scanned),
        "companies_unreachable": unreachable,
        "summary": dict(summary),
        "items": report,
    }


async def _all_company_ids() -> set[str]:
    async with session_scope() as session:
        await _read_only(session)
        rows = (await session.execute(text("SELECT id FROM company"))).all()
        await session.rollback()
    return {str(r[0]) for r in rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--company-id", action="append", default=[], help="also scan this company for open batches"
    )
    parser.add_argument(
        "--all-companies",
        action="store_true",
        help="scan every company (needs a role that can list them)",
    )
    parser.add_argument("--stale-pending-hours", type=float, default=24.0)
    parser.add_argument(
        "--queue", default=QUEUE, help="queue list to inspect (default: %(default)s)"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    client = redis.Redis.from_url(settings.celery_broker, socket_timeout=5)
    try:
        report = asyncio.run(
            collect(
                cast(_SyncRedis, client),
                company_ids=args.company_id,
                all_companies=args.all_companies,
                stale_pending=timedelta(hours=args.stale_pending_hours),
                queue=args.queue,
            )
        )
    except (redis.RedisError, OSError) as exc:
        print(json.dumps({"ok": False, "error": "redis_unavailable", "type": type(exc).__name__}))
        return 2
    finally:
        client.close()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
