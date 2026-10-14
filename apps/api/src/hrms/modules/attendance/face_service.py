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

import hashlib
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import Settings
from hrms.core.db.session import session_scope
from hrms.core.errors.base import ValidationError
from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.core.rbac.types import DataScope
from hrms.modules.attendance.exceptions import (
    DuplicatePunchIdempotencyKeyError,
    FaceConsentRequiredError,
    FaceEnrollmentAngleMismatchError,
    FaceEnrollmentWindowNotFoundError,
    FaceEnrollmentWindowNotOpenError,
    FaceImageInvalidError,
    FaceLivenessFailedError,
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
    FaceVerificationUnavailableError,
)
from hrms.modules.attendance.face_verification import (
    FaceProviderError,
    FaceProviderNoFaceError,
    FaceVerificationProvider,
)
from hrms.modules.attendance.models import EmployeeFaceProfile, FaceEnrollmentWindow
from hrms.modules.attendance.repository import (
    FaceAttemptRepository,
    FaceEnrollmentWindowRepository,
    FaceProfileRepository,
    PunchRepository,
)
from hrms.modules.attendance.schemas import (
    FACE_ENROLLMENT_ANGLES,
    FACE_IMAGE_MAX_BYTES,
    FaceEnrollmentStatusRead,
    FaceEnrollmentWindowRead,
    FaceProfileRead,
    FacePunchRead,
    PunchRead,
    face_profile_to_read,
    face_window_to_read,
    punch_to_read,
)
from hrms.modules.attendance.service import (
    PunchService,
    _ensure_employee_visible,
    _resolve_visible_employee_ids,
)

_logger = get_logger(__name__)

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def sniff_face_image(image: bytes, *, field: str = "photo") -> str:
    """Returns the content type from the file's own bytes; the client-declared type is not
    trusted."""
    if not image:
        raise FaceImageInvalidError(f"The {field} photo is empty")
    if len(image) > FACE_IMAGE_MAX_BYTES:
        raise FaceImageInvalidError(
            f"The {field} photo exceeds the {FACE_IMAGE_MAX_BYTES // (1024 * 1024)} MB limit"
        )
    if image.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if image.startswith(_PNG_MAGIC):
        return "image/png"
    raise FaceImageInvalidError(f"The {field} photo must be a JPEG or PNG image")


class FacePhotoStorage(Protocol):
    async def put_object(self, *, key: str, body: bytes, content_type: str) -> None: ...

    async def get_object(self, *, key: str) -> bytes: ...

    async def delete_object(self, *, key: str) -> None: ...


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
    ) -> None:
        await self._audit.record(
            self._session,
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
        self, company_id: UUID, *, scope: DataScope, caller_employee_id: UUID | None
    ) -> list[FaceProfileRead]:
        visible = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        rows = await self._profiles.list_for_company(
            self._session, company_id=company_id, visible_employee_ids=visible
        )
        return [face_profile_to_read(r) for r in rows]

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
            profile=face_profile_to_read(profile) if profile else None,
            open_window=face_window_to_read(window) if window is not None and usable else None,
        )

    async def get_review_photo(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> tuple[bytes, str]:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        profile = await self._profiles.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if profile is None or profile.review_photo_key is None:
            raise FaceReviewPhotoNotFoundError()
        image = await self._storage.get_object(key=profile.review_photo_key)
        return image, sniff_face_image(image)

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
        if previous is not None:
            if previous.expires_at <= now:
                previous.status = "EXPIRED"
            else:
                previous.status = "CANCELLED"
                previous.cancelled_at = now
                previous.cancelled_by_user_id = actor_user_id
            await self._session.flush()

        window = await self._windows.insert(
            self._session,
            data={
                "id": uuid4(),
                "company_id": company_id,
                "employee_id": employee_id,
                "status": "OPEN",
                "opened_by_user_id": actor_user_id,
                "opened_at": now,
                "expires_at": now + timedelta(hours=self._settings.face_enrollment_window_hours),
            },
        )
        read = face_window_to_read(window)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="FACE_ENROLLMENT_OPENED",
            entity_type="face_enrollment_window",
            entity_id=window.id,
            after=read.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

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
        if not consent_confirmed:
            raise FaceConsentRequiredError()
        provider = self._require_provider()
        content_types = {
            angle: sniff_face_image(images[angle], field=angle) for angle in FACE_ENROLLMENT_ANGLES
        }

        now = datetime.now(UTC)
        window = await self._windows.get_open(
            self._session, company_id=company_id, employee_id=employee_id, for_update=True
        )
        if window is None or window.expires_at <= now:
            raise FaceEnrollmentWindowNotOpenError()
        profile = await self._profiles.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id, for_update=True
        )
        if profile is not None and profile.status == "ENROLLED":
            raise FaceProfileAlreadyEnrolledError()
        if profile is not None and profile.status == "PENDING_APPROVAL":
            raise FaceProfilePendingApprovalError()

        front, front_type = images["front"], content_types["front"]
        try:
            liveness = await provider.check_liveness(image=front, content_type=front_type)
        except FaceProviderError as exc:
            raise FaceProviderFailedError() from exc
        if liveness.decision == "NO_FACE":
            raise FaceNotDetectedError()
        if liveness.decision != "LIVE":
            raise FaceLivenessFailedError()

        try:
            person_id = await provider.enroll(
                label=str(employee_id), image=front, content_type=front_type
            )
        except FaceProviderNoFaceError as exc:
            raise FaceNotDetectedError() from exc
        except FaceProviderError as exc:
            raise FaceProviderFailedError() from exc

        review_key = f"face-review/{company_id}/{employee_id}/{uuid4()}"
        try:
            await self._verify_and_add_angles(provider, person_id, images, content_types)
            await self._storage.put_object(key=review_key, body=front, content_type=front_type)
        except FaceProviderError as exc:
            await self._discard_provider_person(provider, person_id)
            raise FaceProviderFailedError() from exc
        except Exception:
            await self._discard_provider_person(provider, person_id)
            raise

        before = _dump(profile)
        try:
            async with self._session.begin_nested():
                row = await self._write_submission(
                    profile,
                    company_id=company_id,
                    employee_id=employee_id,
                    provider_name=provider.provider_name,
                    person_id=person_id,
                    window=window,
                    review_key=review_key,
                    now=now,
                    actor_user_id=actor_user_id,
                )
        except Exception:
            await self._discard_provider_person(provider, person_id)
            await self._delete_review_photo(review_key)
            raise

        await self._audit_profile(
            company_id,
            "FACE_PROFILE_SUBMITTED",
            row,
            before=before,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return face_profile_to_read(row)

    async def _verify_and_add_angles(
        self,
        provider: FaceVerificationProvider,
        person_id: str,
        images: dict[str, bytes],
        content_types: dict[str, str],
    ) -> None:
        """Every turned capture must match the front one before any is added — so a profile is
        never built from a mix of faces."""
        minimum = Decimal(str(self._settings.face_enrollment_angle_min_similarity))
        others = [a for a in FACE_ENROLLMENT_ANGLES if a != "front"]
        for angle in others:
            match = await provider.verify(
                person_id=person_id, image=images[angle], content_type=content_types[angle]
            )
            if match.similarity is None or match.similarity < minimum:
                raise FaceEnrollmentAngleMismatchError(angle)
        for angle in others:
            try:
                await provider.add_reference_photo(
                    person_id=person_id, image=images[angle], content_type=content_types[angle]
                )
            except FaceProviderNoFaceError as exc:
                raise FaceEnrollmentAngleMismatchError(angle) from exc

    async def _write_submission(
        self,
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
                self._session,
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
        await self._session.flush()
        return row

    async def _discard_provider_person(
        self, provider: FaceVerificationProvider, person_id: str
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

    async def _delete_review_photo(self, key: str) -> None:
        try:
            await self._storage.delete_object(key=key)
        except Exception as exc:  # noqa: BLE001 - cleanup must never mask the real outcome
            # LOG-09 — the object key (company/employee UUIDs + a random id, no personal data)
            # is what locates the orphaned face photo for deletion.
            safe_log(
                _logger.error,
                "face_review_photo_delete_failed",
                object_key=key,
                **safe_error(exc),
            )

    # --- HR: review and revocation -----------------------------------------------------------

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
        row = await self._pending_profile_for_update(company_id, employee_id)
        before = _dump(row)
        review_key = row.review_photo_key
        row.status = "ENROLLED"
        row.reviewed_at = datetime.now(UTC)
        row.reviewed_by_user_id = actor_user_id
        row.review_photo_key = None
        await self._session.flush()
        await self._audit_profile(
            company_id,
            "FACE_PROFILE_APPROVED",
            row,
            before=before,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        if review_key:
            await self._delete_review_photo(review_key)
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
        provider = self._require_provider()
        row = await self._pending_profile_for_update(company_id, employee_id)
        try:
            await provider.delete_person(person_id=row.provider_person_id)
        except FaceProviderError as exc:
            raise FaceProviderFailedError() from exc

        before = _dump(row)
        review_key = row.review_photo_key
        row.status = "REJECTED"
        row.reviewed_at = datetime.now(UTC)
        row.reviewed_by_user_id = actor_user_id
        row.review_note = note
        row.review_photo_key = None
        await self._session.flush()
        await self._audit_profile(
            company_id,
            "FACE_PROFILE_REJECTED",
            row,
            before=before,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        if review_key:
            await self._delete_review_photo(review_key)
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
        provider = self._require_provider()
        row = await self._profiles.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id, for_update=True
        )
        if row is None:
            raise FaceProfileNotFoundError()
        if row.status != "ENROLLED":
            raise FaceProfileNotEnrolledError()

        try:
            await provider.delete_person(person_id=row.provider_person_id)
        except FaceProviderError as exc:
            raise FaceProviderFailedError() from exc

        before = _dump(row)
        row.status = "REVOKED"
        row.revoked_at = datetime.now(UTC)
        row.revoked_by_user_id = actor_user_id
        await self._session.flush()
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


class FacePunchService:
    """Self-service face punch: attempt limit -> enrollment -> liveness -> match -> punch.

    Rejections are logged in their own transaction (`session_scope`), because the request
    transaction rolls back when the rejection error propagates — and rejected attempts are
    exactly what the attempt limit and any spoofing review need. A MATCHED attempt is written in
    the request transaction alongside the punch it produced, so the two commit or fail together.
    The punch instant is always the server clock (`requested_punch_time=None`)."""

    def __init__(
        self,
        session: AsyncSession,
        provider: FaceVerificationProvider | None,
        settings: Settings,
    ) -> None:
        self._session = session
        self._provider = provider
        self._settings = settings
        self._profiles = FaceProfileRepository()
        self._attempts = FaceAttemptRepository()
        self._punches = PunchRepository()

    async def punch_self(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        image: bytes,
        direction: str,
        scope: DataScope,
        actor_user_id: UUID | None,
        idempotency_key: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FacePunchRead:
        """`idempotency_key` (optional, client-generated) makes a retry after a lost response
        safe: the same key from the same employee for the same direction returns the original
        result without a second verification or punch. Nothing is stored for a key until the
        punch itself commits, so a rejected or failed attempt leaves the key reusable."""
        if self._provider is None:
            raise FaceVerificationUnavailableError()
        provider = self._provider
        content_type = sniff_face_image(image)
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
        await self._enforce_attempt_limit(company_id, employee_id)

        profile = await self._profiles.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if profile is None or profile.status != "ENROLLED":
            await self._record_rejection(company_id, employee_id, decision="NOT_ENROLLED")
            raise FaceNotEnrolledForPunchError()
        person_id = profile.provider_person_id

        try:
            liveness = await provider.check_liveness(image=image, content_type=content_type)
        except FaceProviderError as exc:
            await self._record_rejection(
                company_id, employee_id, decision="PROVIDER_ERROR", person_id=person_id
            )
            raise FaceProviderFailedError() from exc
        if liveness.decision != "LIVE":
            no_face = liveness.decision == "NO_FACE"
            await self._record_rejection(
                company_id,
                employee_id,
                decision="NO_FACE" if no_face else "LIVENESS_FAILED",
                person_id=person_id,
                liveness_score=liveness.score,
                response={"liveness": liveness.provider_response},
            )
            raise FaceNotDetectedError() if no_face else FaceLivenessFailedError()

        try:
            match = await provider.verify(
                person_id=person_id, image=image, content_type=content_type
            )
        except FaceProviderError as exc:
            await self._record_rejection(
                company_id,
                employee_id,
                decision="PROVIDER_ERROR",
                person_id=person_id,
                liveness_score=liveness.score,
            )
            raise FaceProviderFailedError() from exc
        response = {"liveness": liveness.provider_response, "verify": match.provider_response}
        if match.decision != "MATCHED" or match.similarity is None:
            await self._record_rejection(
                company_id,
                employee_id,
                decision="NO_FACE" if match.decision == "NO_FACE" else "NO_MATCH",
                person_id=person_id,
                similarity=match.similarity,
                liveness_score=liveness.score,
                response=response,
            )
            raise FaceNotDetectedError() if match.decision == "NO_FACE" else FaceNotMatchedError()

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
                similarity=match.similarity,
                liveness_score=liveness.score,
                response=response,
                punch_id=punch.id,
            ),
        )
        return FacePunchRead(
            punch=punch, similarity=match.similarity, liveness_score=liveness.score
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
            "created_at": datetime.now(UTC),
        }

    async def _record_rejection(self, company_id: UUID, employee_id: UUID, **fields: Any) -> None:
        async with session_scope(company_id=str(company_id)) as session:
            await self._attempts.insert(
                session, data=self._attempt_data(company_id, employee_id, **fields)
            )
