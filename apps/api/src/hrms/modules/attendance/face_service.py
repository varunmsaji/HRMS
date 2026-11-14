"""Face enrollment and face punching.

Enrollment is self-service inside a one-time, HR-opened window, followed by HR approval:
HR opens a window -> the employee submits five captures (front, left, right, up, down) from the
mobile app -> the profile is PENDING_APPROVAL -> HR approves (ENROLLED) or rejects. Only
ENROLLED profiles can punch.

Consistency with the provider: provider calls happen inside the request transaction. If anything
after a successful provider enrollment fails, the just-created provider person (and any stored
review photo) is deleted again, best effort, so nothing biometric is orphaned. Rejection and
revocation delete at the provider *first*: if that fails the profile is left unchanged and the
action can be retried (provider deletion is idempotent)."""

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import Settings
from hrms.core.db.session import session_scope
from hrms.core.errors.base import ValidationError
from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.core.observability.operations import logged_operation
from hrms.core.observability.security_events import security_event
from hrms.core.rbac.types import DataScope
from hrms.modules.attendance.email_templates import build_face_enrollment_requested_email
from hrms.modules.attendance.exceptions import (
    DuplicatePunchIdempotencyKeyError,
    FaceCaptureReplayedError,
    FaceConsentRequiredError,
    FaceEnrollmentAngleMismatchError,
    FaceEnrollmentAttemptsExceededError,
    FaceEnrollmentInProgressError,
    FaceEnrollmentSelfApprovalNotAllowedError,
    FaceEnrollmentWindowAlreadyOpenError,
    FaceEnrollmentWindowNotFoundError,
    FaceEnrollmentWindowNotOpenError,
    FaceImageInvalidError,
    FaceLivenessChallengeExpiredError,
    FaceLivenessChallengeInvalidError,
    FaceLivenessChallengeRequiredError,
    FaceLivenessChallengeUsedError,
    FaceLivenessInconclusiveError,
    FaceLivenessTimeoutError,
    FaceLivenessUnavailableError,
    FaceMultipleFacesError,
    FaceNotDetectedError,
    FaceNotEnrolledForPunchError,
    FaceNotMatchedError,
    FaceProfileAlreadyEnrolledError,
    FaceProfileNotEnrolledError,
    FaceProfileNotFoundError,
    FaceProfileNotPendingError,
    FaceProfilePendingApprovalError,
    FaceProviderFailedError,
    FacePunchAttemptsExceededError,
    FaceReviewPhotoNotFoundError,
    FaceSpoofSuspectedError,
    FaceVerificationUnavailableError,
)
from hrms.modules.attendance.face_comparison import (
    ProviderObservation,
    finish_comparison,
    match_threshold,
    start_shadow,
)
from hrms.modules.attendance.face_policy import FacePolicyService, derive_enrollment_state
from hrms.modules.attendance.face_verification import (
    FaceProviderError,
    FaceProviderMultipleFacesError,
    FaceProviderNoFaceError,
    FaceVerificationProvider,
)
from hrms.modules.attendance.geofence_service import GeofenceService
from hrms.modules.attendance.liveness import (
    LivenessAssessment,
    LivenessEngine,
    LivenessError,
    LivenessImageError,
    LivenessTimeoutError,
)
from hrms.modules.attendance.models import EmployeeFaceProfile, FaceEnrollmentWindow
from hrms.modules.attendance.repository import (
    FaceAttemptRepository,
    FaceEnrollmentAttemptRepository,
    FaceEnrollmentWindowRepository,
    FaceExternalDeletionRepository,
    FaceLivenessSessionRepository,
    FaceProfileRepository,
    PunchRepository,
)
from hrms.modules.attendance.schemas import (
    FACE_ENROLLMENT_ANGLES,
    FACE_IMAGE_MAX_BYTES,
    FACE_LIVENESS_FRAME_MAX_BYTES,
    FaceEnrollmentAngle,
    FaceEnrollmentStatusRead,
    FaceEnrollmentWindowRead,
    FaceLivenessSessionRead,
    FaceProfileRead,
    FacePunchRead,
    PunchLocation,
    PunchRead,
    face_profile_to_read,
    face_window_to_read,
    punch_to_read,
    review_photo_key_for,
    review_photo_keys,
)
from hrms.modules.attendance.service import (
    PunchService,
    _ensure_employee_visible,
    _resolve_visible_employee_ids,
)
from hrms.modules.notification.producer import employee_user_id, notify
from hrms.modules.notification.service import NotificationService
from hrms.modules.notification.types import (
    ATTENDANCE_PATH,
    FACE_ENROLLMENT_REQUESTED,
    FACE_PROFILE_DECIDED,
    FACE_SETUP_PATH,
)
from hrms.shared.pagination import PageParams

_logger = get_logger(__name__)

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def sniff_face_image(
    image: bytes,
    *,
    field: str = "photo",
    max_bytes: int = FACE_IMAGE_MAX_BYTES,
    error_field: str | None = None,
) -> str:
    """Returns the content type from the file's own bytes; the client-declared type is not
    trusted."""
    target = error_field or "photo"
    if not image:
        raise FaceImageInvalidError(f"The {field} photo is empty", field=target)
    if len(image) > max_bytes:
        limit = f"{max_bytes // (1024 * 1024)} MB" if max_bytes >= 1024 * 1024 else "size"
        raise FaceImageInvalidError(f"The {field} photo exceeds the {limit} limit", field=target)
    if image.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if image.startswith(_PNG_MAGIC):
        return "image/png"
    raise FaceImageInvalidError(f"The {field} photo must be a JPEG or PNG image", field=target)


def _dump_debug_captures(
    settings: Any, employee_id: UUID, kind: str, images: dict[str, bytes]
) -> Path | None:
    """Development only: when HRMS_DEBUG_FACE_DUMP_DIR is set, writes the received photos of
    one attempt to `<dir>/<employee_id>/<UTC time>-<kind>-<id>/<name>.jpg` and returns that
    folder (scores are added to it later by `_dump_debug_result`). Every attempt gets its own
    folder, so earlier captures are kept for comparison. Never active outside development. A
    folder that cannot be written is logged, not raised: debugging must never break a punch."""
    directory = os.environ.get("HRMS_DEBUG_FACE_DUMP_DIR")
    if not directory or settings.environment != "development":
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = Path(directory) / str(employee_id) / f"{stamp}-{kind}-{uuid4().hex[:8]}"
    try:
        target.mkdir(parents=True, exist_ok=True)
        for name, data in images.items():
            (target / f"{name}.jpg").write_bytes(data)
    except OSError as exc:
        safe_log(_logger.warning, "face_debug_dump_failed", error_type=type(exc).__name__)
        return None
    return target


def _debug_scores(assessment: LivenessAssessment) -> dict[str, Any]:
    return {
        "decision": assessment.decision,
        "reason": assessment.reason,
        "frames": [
            {
                "decision": f.decision,
                "reason": f.reason,
                "live": None if f.live_score is None else str(f.live_score),
                "spoof": None if f.spoof_score is None else str(f.spoof_score),
            }
            for f in assessment.frames
        ],
    }


def _dump_debug_result(target: Path | None, result: dict[str, Any]) -> None:
    """Writes (or rewrites) `result.json` beside an attempt's photos. No-op without a folder."""
    if target is None:
        return
    try:
        (target / "result.json").write_text(json.dumps(result, indent=2, default=str))
    except OSError as exc:
        safe_log(_logger.warning, "face_debug_dump_failed", error_type=type(exc).__name__)


async def assess_liveness(
    engine: LivenessEngine, frames: list[bytes], *, field: str = "frames"
) -> LivenessAssessment:
    """Runs server-side liveness, mapping engine failures to the API's error contract. An
    engine failure is never treated as LIVE."""
    try:
        return await engine.assess(frames)
    except LivenessImageError as exc:
        raise FaceImageInvalidError(str(exc), field=field) from exc
    except LivenessTimeoutError as exc:
        raise FaceLivenessTimeoutError() from exc
    except LivenessError as exc:
        # Missing/unverifiable model, OpenCV absent, malformed model output. Logged without
        # any image data; the message is our own text, never a third-party one.
        safe_log(_logger.error, "face_liveness_unavailable", error_type=type(exc).__name__)
        raise FaceLivenessUnavailableError() from exc


def liveness_rejection(assessment: LivenessAssessment) -> tuple[str, Exception] | None:
    """None when every frame is LIVE; otherwise the attempt decision to log and the error to
    raise. INCONCLUSIVE is a rejection, never a pass."""
    if assessment.decision == "LIVE":
        return None
    if assessment.decision == "SPOOF_SUSPECTED":
        return "SPOOF_SUSPECTED", FaceSpoofSuspectedError()
    if assessment.reason == "NO_FACE":
        return "NO_FACE", FaceNotDetectedError()
    if assessment.reason == "MULTIPLE_FACES":
        return "LIVENESS_INCONCLUSIVE", FaceMultipleFacesError()
    return "LIVENESS_INCONCLUSIVE", FaceLivenessInconclusiveError()


async def _release_request_connection(session: AsyncSession) -> None:
    """Ends the request session's transaction so its pooled connection (and any transaction-scoped
    lock, e.g. an advisory lock) is released BEFORE slow work — liveness inference and Face++ round
    trips of up to `face_provider_timeout_seconds` each. `get_tenant_context` has already opened
    that transaction (it sets the RLS variable), so without this a request would sit
    `idle in transaction` on a pooled connection for the whole provider conversation and a slow
    provider could exhaust the pool for every other endpoint. Nothing is pending to commit. The
    tenant variable is transaction-local, so a caller that goes on to use the session MUST call
    `_resume_request_transaction`; one that does not use it again need not."""
    await session.commit()


async def _resume_request_transaction(session: AsyncSession, company_id: UUID) -> None:
    from hrms.core.db.session import set_rls_company_id

    await set_rls_company_id(session, str(company_id))


class FacePhotoStorage(Protocol):
    async def put_object(self, *, key: str, body: bytes, content_type: str) -> None: ...

    async def get_object(self, *, key: str) -> bytes: ...

    async def delete_object(self, *, key: str) -> None: ...


def _is_missing_object(exc: Exception) -> bool:
    """True for the object store's "no such key" answer (botocore `ClientError`), read
    structurally so this module does not depend on botocore."""
    error = getattr(exc, "response", None)
    code = error.get("Error", {}).get("Code") if isinstance(error, dict) else None
    return code in ("NoSuchKey", "404", "NotFound")


def _dump(row: EmployeeFaceProfile | None) -> dict[str, Any] | None:
    return face_profile_to_read(row).model_dump(mode="json") if row is not None else None


class FaceEnrollmentService:
    def __init__(
        self,
        session: AsyncSession,
        provider: FaceVerificationProvider | None,
        settings: Settings,
        storage: FacePhotoStorage,
    ) -> None:
        self._session = session
        self._provider = provider
        self._settings = settings
        self._storage = storage
        self._profiles = FaceProfileRepository()
        self._windows = FaceEnrollmentWindowRepository()
        self._enrollment_attempts = FaceEnrollmentAttemptRepository()
        self._deletions = FaceExternalDeletionRepository()
        self._audit = AuditService()

    def _require_provider(self) -> FaceVerificationProvider:
        if self._provider is None:
            raise FaceVerificationUnavailableError()
        return self._provider

    async def _audit_profile(
        self,
        company_id: UUID,
        action: str,
        row: EmployeeFaceProfile,
        *,
        before: dict[str, Any] | None,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
        session: AsyncSession | None = None,
    ) -> None:
        await self._audit.record(
            session or self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="employee_face_profile",
            entity_id=row.id,
            before=before,
            after=_dump(row),
            ip=ip_address,
            user_agent=user_agent,
        )

    # --- reads -------------------------------------------------------------------------------

    async def list_profiles(
        self,
        company_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        page: PageParams,
    ) -> tuple[list[FaceProfileRead], int]:
        visible = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        rows, total = await self._profiles.page_for_company(
            self._session, company_id=company_id, visible_employee_ids=visible, page=page
        )
        active = self._provider.provider_name if self._provider else None
        return [face_profile_to_read(r, active_provider=active) for r in rows], total

    async def get_status(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> FaceEnrollmentStatusRead:
        """`scope=None` is the employee reading their own status."""
        if scope is not None:
            await _ensure_employee_visible(
                self._session, company_id, employee_id, scope, caller_employee_id
            )
        profile = await self._profiles.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        window = await self._windows.get_open(
            self._session, company_id=company_id, employee_id=employee_id
        )
        usable = window is not None and window.expires_at > datetime.now(UTC)
        return FaceEnrollmentStatusRead(
            profile=(
                face_profile_to_read(
                    profile,
                    active_provider=self._provider.provider_name if self._provider else None,
                )
                if profile
                else None
            ),
            open_window=face_window_to_read(window) if window is not None and usable else None,
            face_verification_required=profile is not None and profile.status == "ENROLLED",
            enrollment_state=derive_enrollment_state(profile, window),
            company_requires_enrollment=await FacePolicyService(self._session).is_required(
                company_id
            ),
        )

    async def get_review_photo(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        angle: FaceEnrollmentAngle = "front",
        actor_user_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[bytes, str]:
        """Serves one angle of the photos awaiting HR review. Every successful read leaves an
        audit record (who, which profile, when, request id — never the bytes); the
        record is written before the image is returned and in the request transaction, so if it
        cannot be written the image is not served. A refused read (no such photo) is a security
        event, not an audit row: the request transaction rolls back with the error. Profiles
        submitted before every angle was kept have only the front photo; the others are 404."""
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        profile = await self._profiles.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if profile is None or profile.review_photo_key is None:
            security_event(
                "face_review_photo.not_found",
                level="warning",
                company_id=str(company_id),
                employee_id=str(employee_id),
                actor_user_id=str(actor_user_id) if actor_user_id else None,
            )
            raise FaceReviewPhotoNotFoundError()
        key = review_photo_key_for(profile.review_photo_key, angle)
        try:
            image = await self._storage.get_object(key=key)
        except Exception as exc:
            if angle == "front" or not _is_missing_object(exc):
                raise
            raise FaceReviewPhotoNotFoundError() from exc
        content_type = sniff_face_image(image)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="FACE_REVIEW_PHOTO_VIEWED",
            entity_type="employee_face_profile",
            entity_id=profile.id,
            after={"outcome": "SERVED", "employee_id": str(employee_id)},
            ip=ip_address,
            user_agent=user_agent,
        )
        return image, content_type

    # --- HR: enrollment window ---------------------------------------------------------------

    async def open_window(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FaceEnrollmentWindowRead:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        return await self._open_window(
            company_id,
            employee_id,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            source="HR",
        )

    async def open_own_window(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FaceEnrollmentWindowRead:
        """Self-service "Start face enrollment". `employee_id` is always the caller's own (the
        router passes the authenticated user's employee), never a request value. Same rules and
        window as an HR-opened one: refused while ENROLLED or PENDING_APPROVAL, the capture still
        needs server-side liveness, consent and HR approval."""
        return await self._open_window(
            company_id,
            employee_id,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            source="SELF",
        )

    async def _open_window(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
        source: str,
    ) -> FaceEnrollmentWindowRead:
        self._require_provider()
        profile = await self._profiles.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id, for_update=True
        )
        if profile is not None and profile.status == "ENROLLED":
            raise FaceProfileAlreadyEnrolledError()
        if profile is not None and profile.status == "PENDING_APPROVAL":
            raise FaceProfilePendingApprovalError()

        now = datetime.now(UTC)
        previous = await self._windows.get_open(
            self._session, company_id=company_id, employee_id=employee_id, for_update=True
        )
        previous_window_live = previous is not None and previous.expires_at > now
        if previous_window_live and source == "HR":
            # HR must cancel a live window explicitly; initiating never silently replaces it.
            # (The employee's own "Start/Continue" keeps refreshing their window.)
            raise FaceEnrollmentWindowAlreadyOpenError()
        if previous is not None:
            if not previous_window_live:
                previous.status = "EXPIRED"
            else:
                previous.status = "CANCELLED"
                previous.cancelled_at = now
                previous.cancelled_by_user_id = actor_user_id
            await self._session.flush()

        try:
            # Savepoint: with no profile/window row to lock, two concurrent initiations race on
            # the one-OPEN-window unique index; the loser is a 409, not a 500.
            async with self._session.begin_nested():
                window = await self._windows.insert(
                    self._session,
                    data={
                        "id": uuid4(),
                        "company_id": company_id,
                        "employee_id": employee_id,
                        "status": "OPEN",
                        "opened_by_user_id": actor_user_id,
                        "opened_at": now,
                        "expires_at": now
                        + timedelta(hours=self._settings.face_enrollment_window_hours),
                    },
                )
        except IntegrityError as exc:
            raise FaceEnrollmentWindowAlreadyOpenError() from exc
        read = face_window_to_read(window)
        previous_state = derive_enrollment_state(
            profile, previous if previous_window_live else None
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="FACE_ENROLLMENT_OPENED",
            entity_type="face_enrollment_window",
            entity_id=window.id,
            before={"enrollment_state": previous_state},
            after={
                **read.model_dump(mode="json"),
                "source": source,
                "enrollment_state": "ENROLLMENT_AVAILABLE",
            },
            ip=ip_address,
            user_agent=user_agent,
        )
        if source == "HR":
            await self._create_requested_notification(company_id, employee_id, window)
            read = read.model_copy(
                update={
                    "notification_status": await self._queue_requested_email(
                        company_id, employee_id, window
                    )
                }
            )
        return read

    async def _create_requested_notification(
        self, company_id: UUID, employee_id: UUID, window: FaceEnrollmentWindow
    ) -> None:
        """In-app counterpart of the email: one FACE_ENROLLMENT_REQUESTED notification per window.

        Same transaction as the window (committed with it, gone if it rolls back) but inside a
        savepoint, so a notification problem can never undo or fail the enrollment window. The
        dedupe key is the window id: a retry or the losing side of a race adds nothing. Only
        non-sensitive ids and the expiry go into it - never anything biometric.
        """
        try:
            async with self._session.begin_nested():
                user_id = (
                    await self._session.execute(
                        text("SELECT user_id FROM employee WHERE id = :eid AND company_id = :cid"),
                        {"eid": employee_id, "cid": company_id},
                    )
                ).scalar_one_or_none()
                if user_id is None:
                    return
                await NotificationService(self._session).create_notification(
                    company_id=company_id,
                    recipient_user_id=user_id,
                    type=FACE_ENROLLMENT_REQUESTED,
                    title="Face Enrollment Required",
                    body=(
                        "Your HR team has requested you to complete face enrollment for attendance."
                    ),
                    entity_type="face_enrollment_window",
                    entity_id=window.id,
                    action_url=FACE_SETUP_PATH,
                    action_label="Complete Face Enrollment",
                    metadata={"expires_at": window.expires_at.isoformat()},
                    dedupe_key=f"{FACE_ENROLLMENT_REQUESTED.code}:{window.id}",
                    expires_at=window.expires_at,
                )
        except Exception as exc:  # noqa: BLE001 - the window is the source of truth
            safe_log(_logger.warning, "face.enrollment.in_app_notify_failed", **safe_error(exc))

    async def _notify_profile_decided(
        self,
        company_id: UUID,
        employee_id: UUID,
        profile_id: UUID,
        outcome: str,
        actor_user_id: UUID | None,
    ) -> None:
        """Tells the employee their face profile was reviewed. Never biometric content."""
        approved = outcome == "approved"
        await notify(
            self._session,
            company_id=company_id,
            recipients=[await employee_user_id(self._session, company_id, employee_id)],
            exclude=[actor_user_id],
            type=FACE_PROFILE_DECIDED,
            title=f"Your face enrollment was {outcome}",
            body=(
                "You can now mark attendance with face check-in."
                if approved
                else "HR could not approve your face enrollment. Please enroll again."
            ),
            dedupe_key=f"{FACE_PROFILE_DECIDED.code}:{profile_id}:{outcome}",
            entity_type="face_profile",
            entity_id=profile_id,
            action_url=ATTENDANCE_PATH if approved else FACE_SETUP_PATH,
            action_label="Open attendance" if approved else "Enroll again",
        )

    async def _queue_requested_email(
        self, company_id: UUID, employee_id: UUID, window: FaceEnrollmentWindow
    ) -> str:
        """Tells the employee (email, via the transactional outbox) that HR requested enrollment.

        Runs only after the window row exists, in the same transaction: the email commits with
        the window and is dropped if it rolls back, one message per window id (so a retry or the
        losing side of a race can never add a second). Nothing here can fail the initiation: any
        error is swallowed and reported as FAILED. QUEUED means "in the outbox", not "delivered".
        """
        try:
            async with self._session.begin_nested():
                row = (
                    await self._session.execute(
                        text(
                            "SELECT u.email, u.status, e.first_name FROM employee e"
                            ' JOIN "user" u ON u.id = e.user_id'
                            " WHERE e.id = :eid AND e.company_id = :cid"
                        ),
                        {"eid": employee_id, "cid": company_id},
                    )
                ).first()
                if row is None or not row.email or row.status != "ACTIVE":
                    return "NOT_SUPPORTED"
                from hrms.modules.onboarding.email_sender import (
                    get_email_sender,
                    queue_email_after_commit,
                )
                from hrms.modules.organisation.service import OrganisationService

                company = await OrganisationService(
                    self._session, self._settings
                ).get_company_profile(company_id)
                subject, html_body, text_body = build_face_enrollment_requested_email(
                    first_name=row.first_name,
                    company_name=company.name,
                    expires_at=window.expires_at.strftime("%d %b %Y, %H:%M UTC"),
                    app_url=self._settings.web_app_base_url,
                )
                await queue_email_after_commit(
                    self._session,
                    get_email_sender(self._settings),
                    to=row.email,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                    failure_kind="face_enrollment_requested",
                    message_key=f"face_enrollment_requested:{window.id}",
                    company_id=str(company_id),
                    employee_id=str(employee_id),
                )
                return "QUEUED"
        except Exception as exc:  # noqa: BLE001 - the window is the source of truth
            safe_log(_logger.warning, "face.enrollment.notify_failed", **safe_error(exc))
            return "FAILED"

    async def cancel_window(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        window = await self._windows.get_open(
            self._session, company_id=company_id, employee_id=employee_id, for_update=True
        )
        now = datetime.now(UTC)
        if window is None or window.expires_at <= now:
            raise FaceEnrollmentWindowNotFoundError()
        before = face_window_to_read(window).model_dump(mode="json")
        window.status = "CANCELLED"
        window.cancelled_at = now
        window.cancelled_by_user_id = actor_user_id
        await self._session.flush()
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="FACE_ENROLLMENT_CANCELLED",
            entity_type="face_enrollment_window",
            entity_id=window.id,
            before=before,
            after=face_window_to_read(window).model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )

    # --- Employee: self-enrollment -----------------------------------------------------------

    @logged_operation("attendance.face.enroll_submit")
    async def submit_self(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        images: dict[str, bytes],
        consent_confirmed: bool,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FaceProfileRead:
        """Three short phases, with NO database transaction open across the slow work:

        1. reserve — one short transaction takes `FOR UPDATE` on the window and profile, checks
           everything (open, not already enrolled, attempt limit, no live reservation) and
           commits a lease on the window (`submission_token`);
        2. work — the ~18 sequential Face++ calls (no liveness here: HR reviews the photo)
           under one wall-clock budget, holding no connection and no row lock;
        3. finalize — one short transaction re-locks the window and profile, proves the lease is
           still this submission's (HR may have cancelled or reopened the window meanwhile) and
           writes the PENDING_APPROVAL profile.

        If anything after the provider person was created cannot be completed, the person and the
        stored review photo are removed (queued for retry when that deletion itself fails)."""
        if not consent_confirmed:
            raise FaceConsentRequiredError()
        provider = self._require_provider()
        content_types = {
            angle: sniff_face_image(images[angle], field=angle) for angle in FACE_ENROLLMENT_ANGLES
        }

        # The reservation, the work and the finalisation each use their own short transaction;
        # the request session is not used again, so give its connection back now.
        await _release_request_connection(self._session)
        reservation = await self._reserve_submission(company_id, employee_id)
        completed = False
        try:
            read = await self._run_reserved_submission(
                company_id,
                employee_id,
                reservation,
                provider=provider,
                images=images,
                content_types=content_types,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            completed = True
            return read
        finally:
            if not completed:
                # Shielded: a client disconnect cancels this task, and the reservation must
                # still be released rather than left to lapse on its own.
                await asyncio.shield(self._release_reservation(company_id, reservation))

    async def _reserve_submission(
        self, company_id: UUID, employee_id: UUID
    ) -> "_SubmissionReservation":
        now = datetime.now(UTC)
        lease = timedelta(seconds=self._settings.face_enrollment_lease_seconds)
        async with session_scope(company_id=str(company_id)) as session:
            window = await self._windows.get_open(
                session, company_id=company_id, employee_id=employee_id, for_update=True
            )
            if window is None or window.expires_at <= now:
                raise FaceEnrollmentWindowNotOpenError()
            profile = await self._profiles.get_for_employee(
                session, company_id=company_id, employee_id=employee_id, for_update=True
            )
            if profile is not None and profile.status == "ENROLLED":
                raise FaceProfileAlreadyEnrolledError()
            if profile is not None and profile.status == "PENDING_APPROVAL":
                raise FaceProfilePendingApprovalError()
            if (
                window.submission_token is not None
                and window.submission_started_at is not None
                and window.submission_started_at + lease > now
            ):
                raise FaceEnrollmentInProgressError()
            await self._enforce_enrollment_limit(session, company_id, employee_id, window)
            token = uuid4()
            window.submission_token = token
            window.submission_started_at = now
            await session.flush()
            return _SubmissionReservation(window_id=window.id, token=token)

    async def _release_reservation(
        self, company_id: UUID, reservation: "_SubmissionReservation"
    ) -> None:
        """Best effort: if it fails, the lease lapses after `face_enrollment_lease_seconds`."""
        try:
            async with session_scope(company_id=str(company_id)) as session:
                await self._windows.release_submission(
                    session,
                    company_id=company_id,
                    window_id=reservation.window_id,
                    token=reservation.token,
                )
        except Exception as exc:  # noqa: BLE001 - must not mask the real outcome
            safe_log(
                _logger.warning,
                "face_enrollment_reservation_release_failed",
                window_id=str(reservation.window_id),
                **safe_error(exc),
            )

    async def _run_reserved_submission(
        self,
        company_id: UUID,
        employee_id: UUID,
        reservation: "_SubmissionReservation",
        *,
        provider: FaceVerificationProvider,
        images: dict[str, bytes],
        content_types: dict[str, str],
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> FaceProfileRead:
        window_id = reservation.window_id
        front, front_type = images["front"], content_types["front"]

        # No liveness check at enrollment: HR reviews the front photo before the profile is
        # switched on, and enrollment is already gated by the HR-opened window and the attempt
        # limit. Liveness is enforced where it matters, on every face punch. The provider's
        # same-person check below still has to pass for every angle.
        _dump_debug_captures(self._settings, employee_id, "enroll", images)

        review_key = f"face-review/{company_id}/{employee_id}/{uuid4()}"
        person_id: str | None = None
        photo_stored = False
        stage_is_front = True
        try:
            async with asyncio.timeout(self._settings.face_enrollment_provider_budget_seconds):
                person_id = await provider.enroll(
                    label=str(employee_id), image=front, content_type=front_type
                )
                stage_is_front = False
                # Crash safety: from here a provider person exists that no profile row knows
                # about yet. The guard row (due only after the reservation lease has lapsed)
                # lets the deletion worker reap it if this process dies before finalizing —
                # and skip it if a profile does reference it by then.
                await self._guard_provider_person(company_id, provider.provider_name, person_id)
                await self._verify_and_add_angles(provider, person_id, images, content_types)
                # Every angle is kept for HR's review (deleted again once HR decides). Marked
                # stored first, so a failure part-way still cleans up the ones already written.
                photo_stored = True
                for angle in FACE_ENROLLMENT_ANGLES:
                    await self._storage.put_object(
                        key=review_photo_key_for(review_key, angle),
                        body=images[angle],
                        content_type=content_types[angle],
                    )
        except FaceProviderNoFaceError as exc:
            await self._reject_enrollment(
                company_id, employee_id, window_id, "NO_FACE", "front", actor_user_id
            )
            raise FaceNotDetectedError() from exc
        except FaceProviderMultipleFacesError as exc:
            await self._reject_enrollment(
                company_id, employee_id, window_id, "MULTIPLE_FACES", "front", actor_user_id
            )
            raise FaceMultipleFacesError() from exc
        except FaceEnrollmentAngleMismatchError as exc:
            await self._compensate(company_id, provider, person_id, review_key, photo_stored)
            await self._reject_enrollment(
                company_id, employee_id, window_id, "ANGLE_MISMATCH", exc.angle, actor_user_id
            )
            raise
        except (FaceProviderError, TimeoutError) as exc:
            await self._compensate(company_id, provider, person_id, review_key, photo_stored)
            await self._reject_enrollment(
                company_id,
                employee_id,
                window_id,
                "PROVIDER_ERROR",
                "front" if stage_is_front else None,
                actor_user_id,
            )
            raise FaceProviderFailedError() from exc
        except BaseException:
            # Storage failure, an unexpected error, or cancellation (client disconnect).
            await asyncio.shield(
                self._compensate(company_id, provider, person_id, review_key, photo_stored)
            )
            raise

        assert person_id is not None
        try:
            async with session_scope(company_id=str(company_id)) as session:
                row = await self._finalize_submission(
                    session,
                    company_id=company_id,
                    employee_id=employee_id,
                    reservation=reservation,
                    provider_name=provider.provider_name,
                    person_id=person_id,
                    review_key=review_key,
                    actor_user_id=actor_user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                read = face_profile_to_read(row)
        except BaseException:
            # Includes a failed COMMIT: session_scope has rolled back, so no profile references
            # the provider person or the photo any more.
            await asyncio.shield(
                self._compensate(company_id, provider, person_id, review_key, photo_stored)
            )
            raise
        return read

    async def _finalize_submission(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        reservation: "_SubmissionReservation",
        provider_name: str,
        person_id: str,
        review_key: str,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> EmployeeFaceProfile:
        """Runs in the finalising transaction. Re-proves every assumption the reservation made."""
        now = datetime.now(UTC)
        window = await self._windows.get_for_update(
            session, company_id=company_id, window_id=reservation.window_id
        )
        if (
            window is None
            or window.status != "OPEN"
            or window.submission_token != reservation.token
            or window.expires_at <= now
        ):
            # Cancelled, reopened (superseded), expired, or the lease was lost to a newer
            # submission while the provider calls were running.
            raise FaceEnrollmentWindowNotOpenError()
        profile = await self._profiles.get_for_employee(
            session, company_id=company_id, employee_id=employee_id, for_update=True
        )
        if profile is not None and profile.status == "ENROLLED":
            raise FaceProfileAlreadyEnrolledError()
        if profile is not None and profile.status == "PENDING_APPROVAL":
            raise FaceProfilePendingApprovalError()
        before = _dump(profile)
        row = await self._write_submission(
            session,
            profile,
            company_id=company_id,
            employee_id=employee_id,
            provider_name=provider_name,
            person_id=person_id,
            window=window,
            review_key=review_key,
            now=now,
            actor_user_id=actor_user_id,
        )
        await self._audit_profile(
            company_id,
            "FACE_PROFILE_SUBMITTED",
            row,
            before=before,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            session=session,
        )
        return row

    async def _enforce_enrollment_limit(
        self,
        session: AsyncSession,
        company_id: UUID,
        employee_id: UUID,
        window: FaceEnrollmentWindow,
    ) -> None:
        """Called with the window row locked `FOR UPDATE` in the reservation transaction, and
        reservations are exclusive (a live lease refuses a second submission), so each
        submission sees the previous one's committed rejection: the limit cannot be overshot by
        racing requests. The count is per HR-opened window (tenant + employee + window);
        reopening is an HR action and starts afresh, and only the employee's own authenticated
        session can add to it, so nobody else can lock an employee out. A refused request writes
        nothing and starts no provider call."""
        failed = await self._enrollment_attempts.count_counted_for_window(
            session, company_id=company_id, employee_id=employee_id, window_id=window.id
        )
        if failed >= self._settings.face_enrollment_max_failed_attempts:
            raise FaceEnrollmentAttemptsExceededError()

    async def _reject_enrollment(
        self,
        company_id: UUID,
        employee_id: UUID,
        window_id: UUID,
        decision: str,
        angle: str | None,
        actor_user_id: UUID | None,
    ) -> None:
        """Records a rejected submission in its own committed transaction and emits the
        operational event. Only a fixed decision code, the angle name and identifiers are stored
        or logged — never an image, score or provider body. Volume is bounded: a refused request
        (limit reached) never reaches here, so at most `face_enrollment_max_failed_attempts`
        counted rows and events per window."""
        async with session_scope(company_id=str(company_id)) as session:
            await self._enrollment_attempts.insert(
                session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": employee_id,
                    "enrollment_window_id": window_id,
                    "decision": decision,
                    "angle": angle,
                    "actor_user_id": actor_user_id,
                    "created_at": datetime.now(UTC),
                },
            )
        security_event(
            "face_enrollment.rejected",
            level="warning",
            reason=decision,
            angle=angle,
            company_id=str(company_id),
            employee_id=str(employee_id),
            enrollment_window_id=str(window_id),
        )

    async def _verify_and_add_angles(
        self,
        provider: FaceVerificationProvider,
        person_id: str,
        images: dict[str, bytes],
        content_types: dict[str, str],
    ) -> None:
        """Every turned capture must match the front one before any is added — so a profile is
        never built from a mix of faces."""
        minimum = getattr(provider, "angle_threshold", None) or Decimal(
            str(self._settings.face_enrollment_angle_min_similarity)
        )
        others = [a for a in FACE_ENROLLMENT_ANGLES if a != "front"]
        for angle in others:
            match = await provider.verify(
                person_id=person_id, image=images[angle], content_type=content_types[angle]
            )
            safe_log(
                _logger.info,
                "face_enrollment_angle_similarity",
                angle=angle,
                decision=match.decision,
                similarity=str(match.similarity),
                minimum=str(minimum),
            )
            if match.similarity is None or match.similarity < minimum:
                raise FaceEnrollmentAngleMismatchError(angle)
        for angle in others:
            try:
                await provider.add_reference_photo(
                    person_id=person_id, image=images[angle], content_type=content_types[angle]
                )
            except (FaceProviderNoFaceError, FaceProviderMultipleFacesError) as exc:
                raise FaceEnrollmentAngleMismatchError(angle) from exc

    async def _write_submission(
        self,
        session: AsyncSession,
        existing: EmployeeFaceProfile | None,
        *,
        company_id: UUID,
        employee_id: UUID,
        provider_name: str,
        person_id: str,
        window: FaceEnrollmentWindow,
        review_key: str,
        now: datetime,
        actor_user_id: UUID | None,
    ) -> EmployeeFaceProfile:
        fields: dict[str, Any] = {
            "provider": provider_name,
            "provider_person_id": person_id,
            "status": "PENDING_APPROVAL",
            "reference_photo_count": len(FACE_ENROLLMENT_ANGLES),
            "consent_recorded_at": now,
            "enrolled_at": now,
            "enrolled_by_user_id": actor_user_id,
            "enrollment_window_id": window.id,
            "review_photo_key": review_key,
            "reviewed_at": None,
            "reviewed_by_user_id": None,
            "review_note": None,
            "revoked_at": None,
            "revoked_by_user_id": None,
        }
        if existing is None:
            row = await self._profiles.insert(
                session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": employee_id,
                    **fields,
                },
            )
        else:
            for name, value in fields.items():
                setattr(existing, name, value)
            row = existing
        window.status = "USED"
        window.used_at = now
        window.submission_token = None
        window.submission_started_at = None
        await session.flush()
        return row

    # --- external resources: queued, never deleted before the authorising commit --------------

    async def _queue_deletion(
        self,
        session: AsyncSession,
        company_id: UUID,
        *,
        kind: str,
        resource_ref: str,
        reason: str,
        provider: str | None = None,
        due_at: datetime | None = None,
    ) -> None:
        await self._deletions.enqueue(
            session,
            company_id=company_id,
            kind=kind,
            provider=provider,
            resource_ref=resource_ref,
            reason=reason,
            due_at=due_at,
        )

    async def _guard_provider_person(
        self, company_id: UUID, provider_name: str, person_id: str
    ) -> None:
        due = datetime.now(UTC) + timedelta(seconds=self._settings.face_enrollment_lease_seconds)
        async with session_scope(company_id=str(company_id)) as session:
            await self._queue_deletion(
                session,
                company_id,
                kind="PROVIDER_PERSON",
                resource_ref=person_id,
                reason="ENROLLMENT_COMPENSATION",
                provider=provider_name,
                due_at=due,
            )

    async def _compensate(
        self,
        company_id: UUID,
        provider: FaceVerificationProvider,
        person_id: str | None,
        review_key: str,
        photo_stored: bool,
    ) -> None:
        """Undo what a submission that cannot be completed created outside the database. Direct
        and best effort first; whatever fails is queued, so it is retried instead of orphaned."""
        if person_id is not None:
            await self._discard_provider_person(company_id, provider, person_id)
        if photo_stored:
            await self._delete_review_photo(company_id, review_key)

    async def _discard_provider_person(
        self, company_id: UUID, provider: FaceVerificationProvider, person_id: str
    ) -> None:
        try:
            await provider.delete_person(person_id=person_id)
        except FaceProviderError as exc:
            # Not `.exception()`: the chained httpx error text is not a log-safe contract.
            # LOG-09 — the provider's opaque person id is what an operator needs to delete the
            # orphaned biometric record by hand; without it the record could never be found.
            safe_log(
                _logger.error,
                "face_enrollment_orphaned_provider_person",
                provider=provider.provider_name,
                provider_person_id=person_id,
                **safe_error(exc),
            )
            await self._queue_after_failure(
                company_id,
                kind="PROVIDER_PERSON",
                resource_ref=person_id,
                provider=provider.provider_name,
            )

    async def _delete_review_photo(self, company_id: UUID, key: str) -> None:
        """Deletes every angle of the review photo set `key` names; on failure the whole set is
        queued (the worker deletes all of its angles)."""
        try:
            for angle_key in review_photo_keys(key):
                await self._storage.delete_object(key=angle_key)
        except Exception as exc:  # noqa: BLE001 - cleanup must never mask the real outcome
            # LOG-09 — the object key (company/employee UUIDs + a random id, no personal data)
            # is what locates the orphaned face photo for deletion.
            safe_log(
                _logger.error,
                "face_review_photo_delete_failed",
                object_key=key,
                **safe_error(exc),
            )
            await self._queue_after_failure(company_id, kind="REVIEW_PHOTO", resource_ref=key)

    async def _queue_after_failure(
        self, company_id: UUID, *, kind: str, resource_ref: str, provider: str | None = None
    ) -> None:
        try:
            async with session_scope(company_id=str(company_id)) as session:
                await self._queue_deletion(
                    session,
                    company_id,
                    kind=kind,
                    resource_ref=resource_ref,
                    reason="ENROLLMENT_COMPENSATION",
                    provider=provider,
                )
        except Exception as exc:  # noqa: BLE001 - last resort: the ERROR log above names it
            safe_log(
                _logger.error,
                "face_deletion_enqueue_failed",
                kind=kind,
                resource_ref=resource_ref,
                **safe_error(exc),
            )

    # --- HR: review and revocation -----------------------------------------------------------
    #
    # None of these touches Face++ or the object store. Each changes local state and queues the
    # external deletion in `face_external_deletion` IN THE SAME TRANSACTION; `face_deletion.py`
    # carries it out after that transaction commits, retrying until it succeeds. A rejected or
    # revoked profile stops being usable at commit (status), so the deferred provider-side
    # deletion never extends the time a face can punch.

    async def _pending_profile_for_update(
        self, company_id: UUID, employee_id: UUID
    ) -> EmployeeFaceProfile:
        row = await self._profiles.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id, for_update=True
        )
        if row is None:
            raise FaceProfileNotFoundError()
        if row.status != "PENDING_APPROVAL":
            raise FaceProfileNotPendingError()
        return row

    async def approve(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FaceProfileRead:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        if caller_employee_id is not None and caller_employee_id == employee_id:
            raise FaceEnrollmentSelfApprovalNotAllowedError()
        row = await self._pending_profile_for_update(company_id, employee_id)
        before = _dump(row)
        review_key = row.review_photo_key
        row.status = "ENROLLED"
        row.reviewed_at = datetime.now(UTC)
        row.reviewed_by_user_id = actor_user_id
        row.review_photo_key = None
        await self._session.flush()
        if review_key:
            # One row for the whole set: the worker deletes every angle's photo for it.
            await self._queue_deletion(
                self._session,
                company_id,
                kind="REVIEW_PHOTO",
                resource_ref=review_key,
                reason="APPROVED",
            )
        await self._audit_profile(
            company_id,
            "FACE_PROFILE_APPROVED",
            row,
            before=before,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._notify_profile_decided(
            company_id, employee_id, row.id, "approved", actor_user_id
        )
        return face_profile_to_read(row)

    async def reject(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        note: str | None,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FaceProfileRead:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        if caller_employee_id is not None and caller_employee_id == employee_id:
            raise FaceEnrollmentSelfApprovalNotAllowedError()
        row = await self._pending_profile_for_update(company_id, employee_id)
        before = _dump(row)
        review_key = row.review_photo_key
        row.status = "REJECTED"
        row.reviewed_at = datetime.now(UTC)
        row.reviewed_by_user_id = actor_user_id
        row.review_note = note
        row.review_photo_key = None
        await self._session.flush()
        await self._queue_deletion(
            self._session,
            company_id,
            kind="PROVIDER_PERSON",
            resource_ref=row.provider_person_id,
            reason="REJECTED",
            provider=row.provider,
        )
        if review_key:
            # One row for the whole set: the worker deletes every angle's photo for it.
            await self._queue_deletion(
                self._session,
                company_id,
                kind="REVIEW_PHOTO",
                resource_ref=review_key,
                reason="REJECTED",
            )
        await self._audit_profile(
            company_id,
            "FACE_PROFILE_REJECTED",
            row,
            before=before,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._notify_profile_decided(
            company_id, employee_id, row.id, "rejected", actor_user_id
        )
        return face_profile_to_read(row)

    async def revoke(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FaceProfileRead:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        row = await self._profiles.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id, for_update=True
        )
        if row is None:
            raise FaceProfileNotFoundError()
        if row.status != "ENROLLED":
            raise FaceProfileNotEnrolledError()

        before = _dump(row)
        row.status = "REVOKED"
        row.revoked_at = datetime.now(UTC)
        row.revoked_by_user_id = actor_user_id
        await self._session.flush()
        await self._queue_deletion(
            self._session,
            company_id,
            kind="PROVIDER_PERSON",
            resource_ref=row.provider_person_id,
            reason="REVOKED",
            provider=row.provider,
        )
        await self._audit_profile(
            company_id,
            "FACE_PROFILE_REVOKED",
            row,
            before=before,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return face_profile_to_read(row)


@dataclass(frozen=True)
class _SubmissionReservation:
    window_id: UUID
    token: UUID


# Client-generated face-punch idempotency keys. Short enough that the namespaced stored form
# (`face:<key>`) fits `punch.idempotency_key` (VARCHAR(100)); the character set keeps the value
# free of anything that needs escaping in logs or SQL.
FACE_PUNCH_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_FACE_KEY_NAMESPACE = "face:"


def _stored_face_key(key: str) -> str:
    """The operation-scoped form persisted on the punch. The namespace stops a key sent to the
    plain self-punch endpoint from replaying (or being replayed by) a face punch."""
    return f"{_FACE_KEY_NAMESPACE}{key}"


def key_ref(key: str) -> str:
    """Log-safe correlation for a client key: a short digest, never the key itself."""
    return hashlib.sha256(key.encode()).hexdigest()[:12]


#: Every `decision` a rejected face punch can carry (the non-MATCHED values of the
#: `face_verification_attempt.decision` check constraint that `FacePunchService` writes).
FACE_PUNCH_REJECTION_REASONS = frozenset(
    {
        "NO_MATCH",
        "NO_FACE",
        "NOT_ENROLLED",
        "PROVIDER_ERROR",
        "SPOOF_SUSPECTED",
        "LIVENESS_INCONCLUSIVE",
        "LIVENESS_ERROR",
        "CHALLENGE_REJECTED",
        "CAPTURE_REPLAYED",
        "AMBIGUOUS_FACE",
        "IDENTITY_INCONSISTENT",
    }
)


@dataclass(frozen=True)
class FrameIdentity:
    """One frame's identity verdict against the expected employee's FaceSet. Holds only what the
    attempt row keeps: the verdict, the similarity and Face++'s request id."""

    index: int
    decision: str
    similarity: Decimal | None
    request_id: str | None


def identity_evidence(primary: int, checked: list[FrameIdentity]) -> dict[str, Any]:
    """The minimal, typed identity evidence stored on `face_verification_attempt` (replacing the
    raw provider body): per checked frame its index, verdict, similarity and provider request id.
    No face tokens, rectangles or other provider fields."""
    return {
        "primary_frame": primary,
        "frames": [
            {
                "index": f.index,
                "decision": f.decision,
                "similarity": str(f.similarity) if f.similarity is not None else None,
                "request_id": f.request_id,
            }
            for f in checked
        ],
    }


def identity_rejection(decision: str, *, any_matched: bool) -> tuple[str, Exception]:
    """Maps a frame that did not MATCH to the attempt decision and the error to raise. Anything
    this does not recognise is a plain NO_MATCH: unknown never passes. `any_matched` means an
    earlier frame did match the enrolled employee, so this one disagrees with it."""
    if decision == "MULTIPLE_FACES":
        return "AMBIGUOUS_FACE", FaceMultipleFacesError()
    if decision == "NO_FACE":
        return "NO_FACE", FaceNotDetectedError()
    return ("IDENTITY_INCONSISTENT" if any_matched else "NO_MATCH"), FaceNotMatchedError()


class FacePunchService:
    """Self-service face punch, in two requests.

    1. `issue_liveness_session` — the server issues a short-lived, single-use challenge bound to
       this employee and punch direction (any older unused one is superseded).
    2. `punch_self` — the app presents that challenge with N freshly captured frames:
       idempotent replay -> attempt limit -> challenge burned (own transaction) -> frame replay
       check -> enrollment -> server-side liveness on EVERY frame -> Face++ identity match of
       EVERY frame (the exact bytes that passed liveness) against this employee's own enrolled
       FaceSet -> punch.

    The client never supplies a liveness verdict or score; nothing it could send would be read
    as one. Rejections are logged in their own transaction (`session_scope`), because the
    request transaction rolls back when the rejection error propagates — and rejected attempts
    are exactly what the attempt limit and any spoofing review need. A MATCHED attempt is
    written in the request transaction alongside the punch it produced, so the two commit or
    fail together. The punch instant is always the server clock (`requested_punch_time=None`)."""

    def __init__(
        self,
        session: AsyncSession,
        provider: FaceVerificationProvider | None,
        settings: Settings,
        liveness: LivenessEngine | None = None,
        shadow_provider: FaceVerificationProvider | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._settings = settings
        self._liveness = liveness
        # Observation only (`face_comparison.py`): never consulted for a decision.
        self._shadow_provider = shadow_provider
        self._profiles = FaceProfileRepository()
        self._attempts = FaceAttemptRepository()
        self._punches = PunchRepository()
        self._sessions = FaceLivenessSessionRepository()

    def _require_engines(self) -> tuple[FaceVerificationProvider, LivenessEngine]:
        if self._provider is None:
            raise FaceVerificationUnavailableError()
        if self._liveness is None:
            raise FaceLivenessUnavailableError()
        return self._provider, self._liveness

    async def issue_liveness_session(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        direction: str,
        actor_user_id: UUID | None,
    ) -> FaceLivenessSessionRead:
        self._require_engines()
        # One issuer at a time per employee, so "supersede then insert" cannot race the
        # one-ISSUED-per-employee unique index.
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"face-liveness-session:{company_id}:{employee_id}"},
        )
        await self._enforce_attempt_limit(company_id, employee_id)
        window = self._settings.face_punch_attempt_window_minutes
        now = datetime.now(UTC)
        issued = await self._sessions.count_issued_since(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            since=now - timedelta(minutes=window),
        )
        if issued >= self._settings.face_liveness_sessions_per_window:
            raise FacePunchAttemptsExceededError(window)
        profile = await self._profiles.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if profile is None or profile.status != "ENROLLED":
            raise FaceNotEnrolledForPunchError()

        await self._sessions.supersede_issued(
            self._session, company_id=company_id, employee_id=employee_id
        )
        row = await self._sessions.insert(
            self._session,
            data={
                "id": uuid4(),
                "company_id": company_id,
                "employee_id": employee_id,
                "direction": direction,
                "status": "ISSUED",
                "issued_by_user_id": actor_user_id,
                "issued_at": now,
                "expires_at": now
                + timedelta(seconds=self._settings.face_liveness_session_ttl_seconds),
                "frame_digests": [],
            },
        )
        return FaceLivenessSessionRead(
            session_id=row.id,
            direction=row.direction,
            expires_at=row.expires_at,
            frames_required=self._settings.face_liveness_frames,
        )

    @logged_operation("attendance.face.punch")
    async def punch_self(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        frames: list[bytes],
        liveness_session_id: UUID | None,
        direction: str,
        scope: DataScope,
        actor_user_id: UUID | None,
        idempotency_key: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        location: PunchLocation | None = None,
        location_error: str | None = None,
    ) -> FacePunchRead:
        """`idempotency_key` (optional, client-generated) makes a retry after a lost response
        safe: the same key from the same employee for the same direction returns the original
        result without a second verification or punch — even when the retry carries a new
        challenge and new frames. Nothing is stored for a key until the punch itself commits,
        so a rejected or failed attempt leaves the key reusable."""
        provider, liveness_engine = self._require_engines()
        if liveness_session_id is None or not frames:
            raise FaceLivenessChallengeRequiredError()
        required = self._settings.face_liveness_frames
        if len(frames) != required:
            raise FaceImageInvalidError(
                f"Exactly {required} face frames are required", field="frames"
            )
        content_types = [
            sniff_face_image(
                frame,
                field=f"frame {i + 1}",
                max_bytes=FACE_LIVENESS_FRAME_MAX_BYTES,
                error_field="frames",
            )
            for i, frame in enumerate(frames)
        ]
        digests = [hashlib.sha256(frame).hexdigest() for frame in frames]
        if len(set(digests)) != len(digests):
            raise FaceCaptureReplayedError()

        stored_key: str | None = None
        if idempotency_key is not None:
            if not FACE_PUNCH_KEY_PATTERN.fullmatch(idempotency_key):
                raise ValidationError(
                    "idempotency_key must be 16-64 characters of letters, digits, '_' or '-'"
                )
            stored_key = _stored_face_key(idempotency_key)
            replay = await self._replay_if_recorded(
                company_id, employee_id, stored_key, direction=direction, ref=key_ref(stored_key)
            )
            if replay is not None:
                return replay
        # Cheap location check up front so a refused location does not spend the one-time
        # liveness challenge or the (slow, possibly paid) face work. The authoritative check still
        # runs in `record_punch_outcome`, which every punch passes through.
        await GeofenceService(self._session).enforce(
            company_id,
            employee_id,
            direction=direction,
            source="FACE",
            location=location,
            location_error=location_error,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        # Same reasoning for a punch-in that is too early for the shift.
        await PunchService(self._session).enforce_shift_window(
            company_id,
            employee_id,
            direction=direction,
            source="FACE",
            punch_time=datetime.now(UTC),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._enforce_attempt_limit(company_id, employee_id)
        if stored_key is not None:
            awaited = await self._await_in_flight_duplicate(
                company_id,
                employee_id,
                liveness_session_id,
                stored_key,
                direction=direction,
                ref=key_ref(stored_key),
            )
            if awaited is not None:
                return awaited

        session_id = await self._consume_session(
            company_id, employee_id, liveness_session_id, direction=direction, digests=digests
        )
        if await self._sessions.any_digest_seen(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            digests=digests,
            exclude_id=session_id,
        ):
            await self._record_rejection(
                company_id, employee_id, decision="CAPTURE_REPLAYED", session_id=session_id
            )
            raise FaceCaptureReplayedError()

        profile = await self._profiles.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if profile is None or profile.status != "ENROLLED":
            await self._record_rejection(
                company_id, employee_id, decision="NOT_ENROLLED", session_id=session_id
            )
            raise FaceNotEnrolledForPunchError()
        if profile.provider != provider.provider_name:
            # The profile was made by the other engine (the operator switched engines). Its
            # person id means nothing to this one, and no fallback exists: re-enrolment is the
            # only way forward. Recorded as NOT_ENROLLED, which - like any non-infrastructure
            # rejection - is visible to HR, and nothing is sent to either engine.
            await self._record_rejection(
                company_id, employee_id, decision="NOT_ENROLLED", session_id=session_id
            )
            raise FaceNotEnrolledForPunchError(
                "Your face profile was created with a different face engine. "
                "Ask HR to re-enroll you."
            )
        person_id = profile.provider_person_id

        # Everything above was cheap database work. From here on the request does slow external
        # work (liveness model, then up to one Face++ detect + search per frame): end the
        # transaction first so no connection and no advisory lock (the idempotency-key lock) is
        # held across it. The punch itself is written in a fresh transaction below, which
        # re-takes the key lock and re-checks for a replay, so two concurrent same-key requests
        # still produce one punch (the unique index remains the backstop).
        await _release_request_connection(self._session)

        debug_dir = _dump_debug_captures(
            self._settings,
            employee_id,
            "punch",
            {f"frame_{i}": frame for i, frame in enumerate(frames)},
        )
        try:
            assessment = await assess_liveness(liveness_engine, frames)
            _dump_debug_result(
                debug_dir,
                {
                    "kind": "punch",
                    "live_threshold": self._settings.face_liveness_live_threshold,
                    **_debug_scores(assessment),
                },
            )
        except FaceImageInvalidError:
            await self._record_rejection(
                company_id,
                employee_id,
                decision="LIVENESS_INCONCLUSIVE",
                person_id=person_id,
                session_id=session_id,
                response={"liveness": {"error": "INVALID_IMAGE"}},
            )
            raise
        except (FaceLivenessTimeoutError, FaceLivenessUnavailableError) as exc:
            await self._record_rejection(
                company_id,
                employee_id,
                decision="LIVENESS_ERROR",
                person_id=person_id,
                session_id=session_id,
                response={"liveness": {"error": exc.code}},
            )
            raise
        rejection = liveness_rejection(assessment)
        if rejection is not None:
            decision, error = rejection
            await self._record_rejection(
                company_id,
                employee_id,
                decision=decision,
                person_id=person_id,
                liveness_score=assessment.live_score,
                session_id=session_id,
                response={"liveness": assessment.audit_summary()},
            )
            raise error

        # Identity is checked on EVERY frame that passed liveness in this same request, always
        # against this employee's own enrolled FaceSet (`person_id`, read from their profile) —
        # never a tenant-wide search and never a separately supplied image. The frame with the
        # best liveness score goes first (a failure there stops the loop before the rest are
        # paid for), then the others. All must MATCH: a liveness pass on one frame cannot
        # authorise an identity that only another frame showed.
        primary = assessment.best_frame_index()
        order = [primary] + [i for i in range(len(frames)) if i != primary]
        checked: list[FrameIdentity] = []
        # Shadow comparison (off by default -> None, nothing runs): the shadow provider sees the
        # same frames concurrently and is only ever observed; see `face_comparison.py`.
        shadow_task = start_shadow(
            self._shadow_provider,
            self._settings,
            company_id=company_id,
            employee_id=employee_id,
            frames=frames,
            content_types=content_types,
        )
        primary_ms = 0

        async def observe_shadow(
            result: str, matched: bool, score: Decimal | None, error_code: str | None = None
        ) -> None:
            await finish_comparison(
                shadow_task,
                self._settings,
                ProviderObservation(
                    provider.provider_name,
                    result,
                    matched,
                    score,
                    match_threshold(provider, self._settings),
                    primary_ms,
                    error_code,
                ),
                company_id=company_id,
                employee_id=employee_id,
                session_id=session_id,
                liveness_score=assessment.live_score,
                frames=len(frames),
            )

        def evidence() -> dict[str, Any]:
            return {
                "liveness": assessment.audit_summary(),
                "identity": identity_evidence(primary, checked),
            }

        for index in order:
            verify_started = time.perf_counter()
            try:
                match = await provider.verify(
                    person_id=person_id,
                    image=frames[index],
                    content_type=content_types[index],
                )
            except FaceProviderError as exc:
                primary_ms += int((time.perf_counter() - verify_started) * 1000)
                await self._record_rejection(
                    company_id,
                    employee_id,
                    decision="PROVIDER_ERROR",
                    person_id=person_id,
                    liveness_score=assessment.live_score,
                    session_id=session_id,
                    response=evidence(),
                )
                await observe_shadow("PROVIDER_ERROR", False, None, "PROVIDER_ERROR")
                raise FaceProviderFailedError() from exc
            primary_ms += int((time.perf_counter() - verify_started) * 1000)
            checked.append(
                FrameIdentity(index, match.decision, match.similarity, match.provider_request_id)
            )
            # Re-checked here, not only in the adapter: a provider that says MATCHED below our
            # configured floor (or without a score) is not a match.
            if (
                match.decision == "MATCHED"
                and match.similarity is not None
                and match.similarity
                >= (
                    getattr(provider, "match_threshold", None)
                    or Decimal(str(self._settings.face_match_min_similarity))
                )
            ):
                continue
            decision, error = identity_rejection(match.decision, any_matched=len(checked) > 1)
            await self._record_rejection(
                company_id,
                employee_id,
                decision=decision,
                person_id=person_id,
                similarity=match.similarity,
                liveness_score=assessment.live_score,
                session_id=session_id,
                response=evidence(),
            )
            await observe_shadow(decision, False, match.similarity)
            raise error

        # Invariant, checked rather than assumed: a punch needs one MATCHED verdict per frame.
        matched = [
            f.similarity for f in checked if f.decision == "MATCHED" and f.similarity is not None
        ]
        if len(checked) != len(frames) or len(matched) != len(frames):
            await self._record_rejection(
                company_id,
                employee_id,
                decision="NO_MATCH",
                person_id=person_id,
                liveness_score=assessment.live_score,
                session_id=session_id,
                response=evidence(),
            )
            await observe_shadow("NO_MATCH", False, None)
            raise FaceNotMatchedError()
        similarity = min(matched)
        response = evidence()
        # The official outcome is fixed here; the shadow can no longer affect it. Awaited before
        # the request transaction resumes so no DB connection is held while it finishes.
        await observe_shadow("MATCHED", True, similarity)

        await _resume_request_transaction(self._session, company_id)
        if stored_key is not None:
            replay = await self._replay_if_recorded(
                company_id, employee_id, stored_key, direction=direction, ref=key_ref(stored_key)
            )
            if replay is not None:
                return replay

        punch, replayed = await PunchService(self._session).record_punch_outcome(
            company_id,
            employee_id,
            direction=direction,
            requested_punch_time=None,
            source="FACE",
            reference=None,
            idempotency_key=stored_key,
            scope=scope,
            caller_employee_id=employee_id,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            location=location,
            location_error=location_error,
        )
        if replayed:
            # Lost a race with a concurrent request carrying the same key (the advisory lock
            # makes this unreachable in the normal path; the unique index is the backstop). The
            # winner already wrote its MATCHED attempt, so write none and return its result.
            assert stored_key is not None
            return await self._result_for_existing_punch(company_id, punch, ref=key_ref(stored_key))
        await self._attempts.insert(
            self._session,
            data=self._attempt_data(
                company_id,
                employee_id,
                decision="MATCHED",
                person_id=person_id,
                similarity=similarity,
                liveness_score=assessment.live_score,
                response=response,
                punch_id=punch.id,
                session_id=session_id,
            ),
        )
        return FacePunchRead(
            punch=punch, similarity=similarity, liveness_score=assessment.live_score
        )

    async def _consume_session(
        self,
        company_id: UUID,
        employee_id: UUID,
        session_id: UUID,
        *,
        direction: str,
        digests: list[str],
    ) -> UUID:
        """Burns the challenge in its own committed transaction before any verification work,
        so it stays burned whatever happens next (a rollback of the request transaction must
        not make it presentable again). Expired or wrong-direction challenges are burned too."""
        now = datetime.now(UTC)
        found = True
        async with session_scope(company_id=str(company_id)) as session:
            row = await self._sessions.get_for_update(
                session, company_id=company_id, employee_id=employee_id, session_id=session_id
            )
            if row is None or row.status == "SUPERSEDED":
                found = row is not None
                outcome: Exception | None = FaceLivenessChallengeInvalidError()
            elif row.status == "CONSUMED":
                outcome = FaceLivenessChallengeUsedError()
            else:
                row.status = "CONSUMED"
                row.consumed_at = now
                row.frame_digests = digests
                await session.flush()
                if row.expires_at <= now:
                    outcome = FaceLivenessChallengeExpiredError()
                elif row.direction != direction:
                    outcome = FaceLivenessChallengeInvalidError()
                else:
                    outcome = None
        if outcome is not None:
            await self._record_rejection(
                company_id,
                employee_id,
                decision="CHALLENGE_REJECTED",
                session_id=session_id if found else None,
                response={"challenge": getattr(outcome, "code", "INVALID")},
            )
            raise outcome
        return session_id

    def _in_flight_wait_seconds(self) -> float:
        """Longest a duplicate waits for the original request: its liveness run plus one
        detect + search per frame at the provider timeout, plus a margin."""
        settings = self._settings
        return (
            settings.face_liveness_timeout_seconds
            + 2 * settings.face_liveness_frames * settings.face_provider_timeout_seconds
            + 5.0
        )

    async def _await_in_flight_duplicate(
        self,
        company_id: UUID,
        employee_id: UUID,
        challenge_id: UUID,
        stored_key: str,
        *,
        direction: str,
        ref: str,
    ) -> FacePunchRead | None:
        """Same key, same challenge, original still running: a double-submit or an app retry.

        The original burns the challenge (own committed transaction) and then releases its
        request transaction — and with it the key's advisory lock — before the slow provider
        work, so a duplicate no longer queues on that lock. Without this it would find the
        challenge already used and be refused. Instead it waits (no connection held while it
        does) until the original has either produced the punch — then it returns that result — or
        recorded a rejection (or the wait window ends), and in those cases falls through to the
        normal path, exactly as a duplicate of a failed request always did."""
        state = await self._sessions.get_state(
            self._session, company_id=company_id, employee_id=employee_id, session_id=challenge_id
        )
        wait = self._in_flight_wait_seconds()
        if (
            state is None
            or state[0] != "CONSUMED"
            or state[1] != direction
            or state[2] is None
            or (datetime.now(UTC) - state[2]).total_seconds() > wait
        ):
            return None
        await _release_request_connection(self._session)
        deadline = time.monotonic() + wait
        delay = 0.1
        found = False
        while time.monotonic() < deadline:
            async with session_scope(company_id=str(company_id)) as session:
                # The attempt first: a MATCHED attempt commits together with its punch, so seeing
                # the attempt means the punch read below sees it too. The other way round, the
                # original can commit between the two reads and this request is wrongly refused.
                has_attempt = await self._attempts.exists_for_session(
                    session, company_id=company_id, session_id=challenge_id
                )
                found = (
                    await self._punches.get_by_idempotency_key(
                        session, company_id=company_id, idempotency_key=stored_key
                    )
                    is not None
                )
            if found or has_attempt:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 1.0)
        await _resume_request_transaction(self._session, company_id)
        if not found:
            return None
        return await self._replay_if_recorded(
            company_id, employee_id, stored_key, direction=direction, ref=ref
        )

    async def _replay_if_recorded(
        self,
        company_id: UUID,
        employee_id: UUID,
        stored_key: str,
        *,
        direction: str,
        ref: str,
    ) -> FacePunchRead | None:
        """Serialises same-key requests (transaction-scoped advisory lock, released at commit or
        rollback), then returns the original result if the key already produced a punch. The
        lock means a concurrent duplicate waits for the first request to commit instead of
        paying for a second provider round-trip and racing the unique index."""
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"face-punch:{company_id}:{employee_id}:{stored_key}"},
        )
        existing = await self._punches.get_by_idempotency_key(
            self._session, company_id=company_id, idempotency_key=stored_key
        )
        if existing is None:
            return None
        if existing.employee_id != employee_id or existing.direction != direction:
            safe_log(
                _logger.warning,
                "attendance.face_punch.idempotency_conflict",
                key_ref=ref,
                employee_id=str(employee_id),
            )
            raise DuplicatePunchIdempotencyKeyError(
                "This idempotency_key was already used for a different punch"
            )
        return await self._result_for_existing_punch(company_id, punch_to_read(existing), ref=ref)

    async def _result_for_existing_punch(
        self, company_id: UUID, punch: PunchRead, *, ref: str
    ) -> FacePunchRead:
        attempt = await self._attempts.get_matched_for_punch(
            self._session, company_id=company_id, punch_id=punch.id
        )
        if attempt is None or attempt.similarity is None:
            # A FACE punch always has its MATCHED attempt (same transaction). Refuse rather
            # than invent scores.
            raise DuplicatePunchIdempotencyKeyError(
                "This idempotency_key refers to a punch that cannot be replayed"
            )
        safe_log(
            _logger.info,
            "attendance.face_punch.replayed",
            key_ref=ref,
            punch_id=str(punch.id),
            employee_id=str(punch.employee_id),
        )
        return FacePunchRead(
            punch=punch, similarity=attempt.similarity, liveness_score=attempt.liveness_score
        )

    async def _enforce_attempt_limit(self, company_id: UUID, employee_id: UUID) -> None:
        window = self._settings.face_punch_attempt_window_minutes
        failed = await self._attempts.count_failed_since(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            since=datetime.now(UTC) - timedelta(minutes=window),
        )
        if failed >= self._settings.face_punch_max_failed_attempts:
            raise FacePunchAttemptsExceededError(window)

    def _attempt_data(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        decision: str,
        person_id: str | None = None,
        similarity: Decimal | None = None,
        liveness_score: Decimal | None = None,
        response: dict[str, Any] | None = None,
        punch_id: UUID | None = None,
        session_id: UUID | None = None,
    ) -> dict[str, Any]:
        provider_name = self._provider.provider_name if self._provider else "FACEPP"
        return {
            "id": uuid4(),
            "company_id": company_id,
            "employee_id": employee_id,
            "punch_id": punch_id,
            "provider": provider_name,
            "provider_person_id": person_id,
            "decision": decision,
            "similarity": similarity,
            "liveness_score": liveness_score,
            "provider_response": response,
            "liveness_session_id": session_id,
            "created_at": datetime.now(UTC),
        }

    async def _record_rejection(self, company_id: UUID, employee_id: UUID, **fields: Any) -> None:
        async with session_scope(company_id=str(company_id)) as session:
            await self._attempts.insert(
                session, data=self._attempt_data(company_id, employee_id, **fields)
            )
        # Operational signal beside the durable attempt row, so spoof / replay / challenge-abuse
        # spikes can be alerted on from logs (`infra/monitoring/hrms_monitor.sh`). Fixed decision
        # code and identifiers only — no scores, frames or provider bodies. `reason` is checked
        # against the known vocabulary so nothing free-form can ever be logged through it, and
        # volume is bounded by the failed-attempt limit that precedes every rejection path.
        decision = fields["decision"]
        security_event(
            "face_punch.rejected",
            level="warning",
            reason=decision if decision in FACE_PUNCH_REJECTION_REASONS else "UNKNOWN",
            company_id=str(company_id),
            employee_id=str(employee_id),
            liveness_session_id=str(fields["session_id"]) if fields.get("session_id") else None,
        )
