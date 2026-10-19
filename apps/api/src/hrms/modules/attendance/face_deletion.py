"""Post-commit deletion of external face resources (Face++ FaceSets, stored review photos).

PostgreSQL and Face++ cannot commit atomically, so nothing here claims it. The guarantee is
narrower and checkable: **an external resource is never deleted before the database transaction
that authorises the deletion has committed**, and a deletion that fails is retried until it works.

How: approve / reject / revoke (and a compensated, failed enrollment) write a
`face_external_deletion` outbox row in the SAME transaction as the state change. This module is the
worker that acts on committed rows (`attendance.run_face_deletions`, every few minutes):

1. claim due rows in a short transaction (`FOR UPDATE SKIP LOCKED`, `next_attempt_at` pushed out
   by a lease) — overlapping runs never share a row, and a crashed worker's rows return later;
2. per row, outside any transaction: skip it if a live (PENDING_APPROVAL / ENROLLED) profile still
   references the resource, otherwise delete it (both deletions are idempotent: Face++ deletion
   treats an already-missing FaceSet as success, and so does object-store deletion);
3. mark it DONE / SKIPPED, or record a short error code and back off (2, 4, 8 ... 60 minutes).

Reassignment safety: provider person ids and review-photo keys are unique random values that are
never reused, and step 2 re-checks the profile table at deletion time, so an old queued row can
not delete a resource that has since been given to a newer enrollment.

Only identifiers are logged — never an image, a token's contents or a provider body. A row that
keeps failing is logged at ERROR on every run once it passes
`face_deletion_alert_after_attempts`, which is what the monitor greps for.
"""

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.session import dispose_engine, session_scope
from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.modules.attendance.face_service import FacePhotoStorage
from hrms.modules.attendance.face_verification import (
    FaceppFaceVerificationProvider,
    FaceProviderError,
    FaceVerificationProvider,
)
from hrms.modules.attendance.repository import (
    ClaimedDeletion,
    FaceExternalDeletionRepository,
    FaceProfileRepository,
)

_logger = get_logger(__name__)

#: A claimed row is invisible to other workers for this long; a worker that dies mid-delete has
#: its rows picked up again after it.
_CLAIM_LEASE = timedelta(minutes=10)


@dataclass
class DeletionReport:
    company_id: str
    claimed: int = 0
    done: int = 0
    skipped_in_use: int = 0
    failed: int = 0
    #: Rows left untouched because the dependency they need is not configured (e.g. the face
    #: provider is disabled), so they are not counted as failed attempts.
    deferred: int = 0
    persistently_failing: int = 0


def _backoff(attempts: int) -> timedelta:
    return timedelta(minutes=min(2 ** max(attempts, 1), 60))


def _error_code(exc: BaseException) -> str:
    return "PROVIDER_ERROR" if isinstance(exc, FaceProviderError) else type(exc).__name__[:64]


async def process_company(
    company_id: UUID,
    settings: Settings,
    *,
    provider: FaceVerificationProvider | None = None,
    storage: FacePhotoStorage | None = None,
    now: datetime | None = None,
) -> DeletionReport:
    """One company's pass. `provider` / `storage` are injectable for tests; otherwise they are
    built from settings, and a provider built here is closed here."""
    report = DeletionReport(company_id=str(company_id))
    moment = now or datetime.now(UTC)
    repo = FaceExternalDeletionRepository()

    async with session_scope(company_id=str(company_id)) as session:
        claimed = await repo.claim_due(
            session,
            company_id=company_id,
            now=moment,
            limit=settings.face_deletion_batch_size,
            lease=_CLAIM_LEASE,
        )
    report.claimed = len(claimed)
    if not claimed:
        return report

    owned_provider: FaceppFaceVerificationProvider | None = None
    if provider is None and settings.face_verification_provider == "facepp":
        owned_provider = provider = FaceppFaceVerificationProvider(settings)
    if storage is None:
        from hrms.core.storage import DocumentStorageService

        storage = DocumentStorageService(settings)
    try:
        for item in claimed:
            await _process_one(company_id, item, settings, repo, provider, storage, report, moment)
    finally:
        if owned_provider is not None:
            await owned_provider.aclose()

    safe_log(
        _logger.warning if report.failed or report.persistently_failing else _logger.info,
        "face_deletion_finished",
        **asdict(report),
    )
    return report


async def _process_one(
    company_id: UUID,
    item: ClaimedDeletion,
    settings: Settings,
    repo: FaceExternalDeletionRepository,
    provider: FaceVerificationProvider | None,
    storage: FacePhotoStorage,
    report: DeletionReport,
    moment: datetime,
) -> None:
    profiles = FaceProfileRepository()
    is_person = item.kind == "PROVIDER_PERSON"
    if is_person and provider is None:
        # Nothing to delete with. Put the attempt back so the row is not consumed by being
        # claimed, and let it wait for the provider to be configured again.
        report.deferred += 1
        async with session_scope(company_id=str(company_id)) as session:
            await repo.retry_later(
                session,
                company_id=company_id,
                row_id=item.id,
                error_code="PROVIDER_NOT_CONFIGURED",
                next_attempt_at=moment + _backoff(item.attempts),
            )
        return

    try:
        async with session_scope(company_id=str(company_id)) as session:
            in_use = await profiles.is_resource_in_use(
                session,
                company_id=company_id,
                provider_person_id=item.resource_ref if is_person else None,
                review_photo_key=None if is_person else item.resource_ref,
            )
            if in_use:
                await repo.finish(
                    session, company_id=company_id, row_id=item.id, status="SKIPPED", now=moment
                )
                report.skipped_in_use += 1
                safe_log(
                    _logger.warning,
                    "face_deletion_skipped_in_use",
                    kind=item.kind,
                    resource_ref=item.resource_ref,
                )
                return
        if is_person:
            assert provider is not None
            await provider.delete_person(person_id=item.resource_ref)
        else:
            await storage.delete_object(key=item.resource_ref)
    except Exception as exc:  # noqa: BLE001 - one bad row must not stop the rest of the batch
        report.failed += 1
        persistent = item.attempts >= settings.face_deletion_alert_after_attempts
        report.persistently_failing += int(persistent)
        safe_log(
            _logger.error if persistent else _logger.warning,
            "face_deletion_failed",
            kind=item.kind,
            resource_ref=item.resource_ref,
            attempts=item.attempts,
            **safe_error(exc),
        )
        async with session_scope(company_id=str(company_id)) as session:
            await repo.retry_later(
                session,
                company_id=company_id,
                row_id=item.id,
                error_code=_error_code(exc),
                next_attempt_at=moment + _backoff(item.attempts),
            )
        return

    async with session_scope(company_id=str(company_id)) as session:
        await repo.finish(session, company_id=company_id, row_id=item.id, status="DONE", now=moment)
    report.done += 1


async def _main(company_id: UUID | None) -> list[dict[str, Any]]:
    from hrms.modules.attendance.face_cleanup import _all_company_ids

    settings = get_settings()
    ids = [company_id] if company_id else await _all_company_ids()
    reports = [asdict(await process_company(c, settings)) for c in ids]
    print(json.dumps(reports, indent=2))
    await dispose_engine()
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the face external-deletion worker once.")
    parser.add_argument("--company-id", type=UUID, help="limit to one company")
    args = parser.parse_args()
    asyncio.run(_main(args.company_id))
