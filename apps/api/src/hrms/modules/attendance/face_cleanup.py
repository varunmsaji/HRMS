"""Retention cleanup for face-attendance records (docs/audits/FACE_ATTENDANCE_SECURITY_HARDENING_
REPORT.md §12).

What may go, what never does:

* `face_liveness_session` — challenge rows and the SHA-256 frame digests used for replay
  detection. DELETED once older than `face_liveness_session_retention_days`. A challenge that is
  still ISSUED and unexpired is never touched. After deletion a byte-identical frame older than
  the retention period would no longer be recognised as a replay, so the period must be at least
  as long as the replay horizon the business wants.
* `face_verification_attempt` — the audit trail of every face check. The ROW is kept (decision,
  similarity, liveness score, punch link: the evidence in an attendance dispute). After
  `face_attempt_detail_retention_days` only the free-form detail is irreversibly erased:
  `provider_response` (per-frame scores and request ids) and `provider_person_id` are set to NULL.
  Rows are never deleted here, and a MATCHED row is never altered beyond that detail.
* `face_enrollment_attempt` — rejected-enrollment records, DELETED after
  `face_enrollment_attempt_retention_days`.

Never touched: punches, attendance days, regularisations, employee face profiles, audit logs.

No retention period is defaulted: the periods are a privacy/legal decision that has not been
taken. An unset period means "keep". Even with periods set the scheduled run only *reports*
until `face_cleanup_dry_run` is turned off. Companies in `face_cleanup_hold_company_ids` are
skipped entirely.

Safety: work is done per company under that company's row-level-security scope, in bounded
batches (`face_cleanup_batch_size`, at most `face_cleanup_max_batches` per record type per run),
each batch in its own transaction using `FOR UPDATE SKIP LOCKED`. Every statement selects only
rows that still match, so a retry or an overlapping run repeats no work and cannot delete
anything twice; a run cut short by the batch cap simply continues next time.
"""

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.session import dispose_engine, session_scope
from hrms.core.observability.logging import get_logger, safe_log

_logger = get_logger(__name__)


@dataclass
class CleanupReport:
    company_id: str
    dry_run: bool
    held: bool = False
    liveness_sessions: int = 0
    attempt_details_erased: int = 0
    enrollment_attempts: int = 0
    #: True when a record type hit the per-run batch cap and rows are still waiting.
    truncated: bool = False


# Each query takes :company_id, :cutoff, :now, :n. The inner SELECT is the single definition of
# "eligible" for both the dry-run count and the destructive statement.
_SESSION_ELIGIBLE = """
    SELECT id FROM face_liveness_session
    WHERE company_id = :company_id AND created_at < :cutoff
      AND NOT (status = 'ISSUED' AND expires_at > :now)
    ORDER BY created_at LIMIT :n
"""
_ATTEMPT_ELIGIBLE = """
    SELECT id FROM face_verification_attempt
    WHERE company_id = :company_id AND created_at < :cutoff
      AND (provider_response IS NOT NULL OR provider_person_id IS NOT NULL)
    ORDER BY created_at LIMIT :n
"""
_ENROLLMENT_ELIGIBLE = """
    SELECT id FROM face_enrollment_attempt
    WHERE company_id = :company_id AND created_at < :cutoff
    ORDER BY created_at LIMIT :n
"""
_LOCK = " FOR UPDATE SKIP LOCKED"


def _batched(statement_head: str, eligible: str) -> str:
    """`statement_head` is the DML up to `WHERE id IN`. The batch is selected in a MATERIALIZED
    CTE: with a plain `WHERE id IN (SELECT ... LIMIT n FOR UPDATE SKIP LOCKED)` the planner may
    re-evaluate the subquery per candidate row, and then `LIMIT n` stops bounding the statement —
    observed here as 7 rows deleted by a batch of 2 whenever the table's statistics said it was
    (nearly) empty, which is the normal state of a table right after a bulk delete. Materializing
    evaluates the selection exactly once."""
    return f"WITH batch AS MATERIALIZED ({eligible}{_LOCK}) {statement_head} (SELECT id FROM batch)"


_DELETE_SESSIONS = _batched("DELETE FROM face_liveness_session WHERE id IN", _SESSION_ELIGIBLE)
_ERASE_ATTEMPTS = _batched(
    "UPDATE face_verification_attempt SET provider_response = NULL, provider_person_id = NULL "
    "WHERE id IN",
    _ATTEMPT_ELIGIBLE,
)
_DELETE_ENROLLMENT = _batched(
    "DELETE FROM face_enrollment_attempt WHERE id IN", _ENROLLMENT_ELIGIBLE
)


async def _count(session: AsyncSession, eligible: str, params: dict[str, object]) -> int:
    row = await session.execute(text(f"SELECT count(*) FROM ({eligible}) AS eligible"), params)
    return int(row.scalar_one())


async def _run_type(
    company_id: UUID,
    *,
    eligible: str,
    statement: str,
    cutoff: datetime,
    now: datetime,
    batch_size: int,
    max_batches: int,
    dry_run: bool,
) -> tuple[int, bool]:
    """Returns (rows affected or, in a dry run, rows that would be, truncated)."""
    params: dict[str, object] = {
        "company_id": company_id,
        "cutoff": cutoff,
        "now": now,
        "n": batch_size,
    }
    if dry_run:
        # Bounded the same way a real run is, so a dry run never scans unboundedly either.
        params["n"] = batch_size * max_batches
        async with session_scope(company_id=str(company_id)) as session:
            counted = await _count(session, eligible, params)
        return counted, counted >= batch_size * max_batches
    total = 0
    for _ in range(max_batches):
        async with session_scope(company_id=str(company_id)) as session:
            result = await session.execute(text(statement), params)
            affected = int(result.rowcount)  # type: ignore[attr-defined]
        total += affected
        if affected < batch_size:
            return total, False
    return total, True


async def cleanup_company(
    company_id: UUID,
    settings: Settings,
    *,
    dry_run: bool | None = None,
    now: datetime | None = None,
) -> CleanupReport:
    """One company's pass. `dry_run=None` follows `settings.face_cleanup_dry_run`."""
    effective_dry_run = settings.face_cleanup_dry_run if dry_run is None else dry_run
    report = CleanupReport(company_id=str(company_id), dry_run=effective_dry_run)
    if company_id in settings.face_cleanup_hold_company_id_set:
        report.held = True
        safe_log(_logger.info, "face_cleanup_skipped_hold", company_id=str(company_id))
        return report

    moment = now or datetime.now(UTC)
    plan = (
        (
            settings.face_liveness_session_retention_days,
            _SESSION_ELIGIBLE,
            _DELETE_SESSIONS,
            "liveness_sessions",
        ),
        (
            settings.face_attempt_detail_retention_days,
            _ATTEMPT_ELIGIBLE,
            _ERASE_ATTEMPTS,
            "attempt_details_erased",
        ),
        (
            settings.face_enrollment_attempt_retention_days,
            _ENROLLMENT_ELIGIBLE,
            _DELETE_ENROLLMENT,
            "enrollment_attempts",
        ),
    )
    for days, eligible, statement, field in plan:
        if days is None:
            continue
        affected, truncated = await _run_type(
            company_id,
            eligible=eligible,
            statement=statement,
            cutoff=moment - timedelta(days=days),
            now=moment,
            batch_size=settings.face_cleanup_batch_size,
            max_batches=settings.face_cleanup_max_batches,
            dry_run=effective_dry_run,
        )
        setattr(report, field, affected)
        report.truncated = report.truncated or truncated

    safe_log(
        _logger.warning if report.truncated else _logger.info,
        "face_cleanup_finished",
        **asdict(report),
    )
    return report


def retention_configured(settings: Settings) -> bool:
    return any(
        days is not None
        for days in (
            settings.face_liveness_session_retention_days,
            settings.face_attempt_detail_retention_days,
            settings.face_enrollment_attempt_retention_days,
        )
    )


async def _all_company_ids() -> list[UUID]:
    from sqlalchemy import select

    from hrms.core.db.models.identity import Company

    async with session_scope() as session:
        return list((await session.execute(select(Company.id))).scalars().all())


async def _main(apply: bool, company_id: UUID | None) -> list[CleanupReport]:
    settings = get_settings()
    if not retention_configured(settings):
        print(json.dumps({"status": "no retention period configured; nothing to do"}))
        return []
    ids = [company_id] if company_id else await _all_company_ids()
    reports = [await cleanup_company(c, settings, dry_run=not apply) for c in ids]
    print(json.dumps([asdict(r) for r in reports], indent=2))
    await dispose_engine()
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Face-record retention cleanup. Reports only unless --apply is given."
    )
    parser.add_argument("--apply", action="store_true", help="actually delete / erase")
    parser.add_argument("--company-id", type=UUID, help="limit to one company")
    args = parser.parse_args()
    asyncio.run(_main(args.apply, args.company_id))
