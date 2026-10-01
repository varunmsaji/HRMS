"""Face enrollment: creating, extending, and revoking an employee's face profile.

Consistency with the provider: the provider call happens inside the request transaction. If the
DB write that follows a successful provider enrollment fails, the just-created provider person is
deleted again (best effort) so no orphaned biometric record is left at the vendor. Revocation
deletes at the provider *first*: if that fails the profile stays ENROLLED and the revoke can be
retried (provider deletion is idempotent)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import Settings
from hrms.core.db.session import session_scope
from hrms.core.observability.logging import get_logger
from hrms.core.rbac.types import DataScope
from hrms.modules.attendance.exceptions import (
    FaceConsentRequiredError,
    FaceImageInvalidError,
    FaceLivenessFailedError,
    FaceNotDetectedError,
    FaceNotEnrolledForPunchError,
    FaceNotMatchedError,
    FaceProfileAlreadyEnrolledError,
    FaceProfileNotEnrolledError,
    FaceProfileNotFoundError,
    FaceProviderFailedError,
    FacePunchAttemptsExceededError,
    FaceReferencePhotoLimitError,
    FaceVerificationUnavailableError,
)
from hrms.modules.attendance.face_verification import (
    FaceProviderError,
    FaceProviderNoFaceError,
    FaceVerificationProvider,
)
from hrms.modules.attendance.models import EmployeeFaceProfile
from hrms.modules.attendance.repository import FaceAttemptRepository, FaceProfileRepository
from hrms.modules.attendance.schemas import (
    FACE_IMAGE_MAX_BYTES,
    FACE_MAX_REFERENCE_PHOTOS,
    FaceProfileRead,
    FacePunchRead,
    face_profile_to_read,
)
from hrms.modules.attendance.service import (
    PunchService,
    _ensure_employee_visible,
    _resolve_visible_employee_ids,
)

_logger = get_logger(__name__)

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def sniff_face_image(image: bytes) -> str:
    """Returns the content type from the file's own bytes; the client-declared type is not
    trusted."""
    if not image:
        raise FaceImageInvalidError("The photo is empty")
    if len(image) > FACE_IMAGE_MAX_BYTES:
        raise FaceImageInvalidError(
            f"The photo exceeds the {FACE_IMAGE_MAX_BYTES // (1024 * 1024)} MB limit"
        )
    if image.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if image.startswith(_PNG_MAGIC):
        return "image/png"
    raise FaceImageInvalidError("The photo must be a JPEG or PNG image")


class FaceEnrollmentService:
    def __init__(self, session: AsyncSession, provider: FaceVerificationProvider | None) -> None:
        self._session = session
        self._provider = provider
        self._repo = FaceProfileRepository()
        self._audit = AuditService()

    def _require_provider(self) -> FaceVerificationProvider:
        if self._provider is None:
            raise FaceVerificationUnavailableError()
        return self._provider

    async def list_profiles(
        self, company_id: UUID, *, scope: DataScope, caller_employee_id: UUID | None
    ) -> list[FaceProfileRead]:
        visible = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        rows = await self._repo.list_for_company(
            self._session, company_id=company_id, visible_employee_ids=visible
        )
        return [face_profile_to_read(r) for r in rows]

    async def get_profile(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> FaceProfileRead:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        row = await self._repo.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if row is None:
            raise FaceProfileNotFoundError()
        return face_profile_to_read(row)

    async def enroll(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        image: bytes,
        consent_confirmed: bool,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FaceProfileRead:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        if not consent_confirmed:
            raise FaceConsentRequiredError()
        provider = self._require_provider()
        content_type = sniff_face_image(image)

        existing = await self._repo.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id, for_update=True
        )
        if existing is not None and existing.status == "ENROLLED":
            raise FaceProfileAlreadyEnrolledError()
        before = face_profile_to_read(existing).model_dump(mode="json") if existing else None

        try:
            person_id = await provider.enroll(
                label=str(employee_id), image=image, content_type=content_type
            )
        except FaceProviderNoFaceError as exc:
            raise FaceNotDetectedError() from exc
        except FaceProviderError as exc:
            raise FaceProviderFailedError() from exc

        now = datetime.now(UTC)
        try:
            async with self._session.begin_nested():
                row = await self._write_enrollment(
                    existing,
                    company_id=company_id,
                    employee_id=employee_id,
                    provider_name=provider.provider_name,
                    person_id=person_id,
                    now=now,
                    actor_user_id=actor_user_id,
                )
        except Exception as exc:
            await self._discard_provider_person(provider, person_id)
            if isinstance(exc, IntegrityError):
                raise FaceProfileAlreadyEnrolledError() from exc
            raise

        read = face_profile_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="FACE_PROFILE_ENROLLED",
            entity_type="employee_face_profile",
            entity_id=row.id,
            before=before,
            after=read.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def _write_enrollment(
        self,
        existing: EmployeeFaceProfile | None,
        *,
        company_id: UUID,
        employee_id: UUID,
        provider_name: str,
        person_id: str,
        now: datetime,
        actor_user_id: UUID | None,
    ) -> EmployeeFaceProfile:
        fields = {
            "provider": provider_name,
            "provider_person_id": person_id,
            "status": "ENROLLED",
            "reference_photo_count": 1,
            "consent_recorded_at": now,
            "enrolled_at": now,
            "enrolled_by_user_id": actor_user_id,
            "revoked_at": None,
            "revoked_by_user_id": None,
        }
        if existing is None:
            return await self._repo.insert(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": employee_id,
                    **fields,
                },
            )
        for name, value in fields.items():
            setattr(existing, name, value)
        await self._session.flush()
        return existing

    async def _discard_provider_person(
        self, provider: FaceVerificationProvider, person_id: str
    ) -> None:
        try:
            await provider.delete_person(person_id=person_id)
        except FaceProviderError:
            # Not `.exception()`: the chained httpx error text is not a log-safe contract.
            _logger.error(  # noqa: TRY400
                "face_enrollment_orphaned_provider_person", provider=provider.provider_name
            )

    async def add_reference_photo(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        image: bytes,
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
        content_type = sniff_face_image(image)
        row = await self._enrolled_profile_for_update(company_id, employee_id)
        if row.reference_photo_count >= FACE_MAX_REFERENCE_PHOTOS:
            raise FaceReferencePhotoLimitError(FACE_MAX_REFERENCE_PHOTOS)

        try:
            await provider.add_reference_photo(
                person_id=row.provider_person_id, image=image, content_type=content_type
            )
        except FaceProviderNoFaceError as exc:
            raise FaceNotDetectedError() from exc
        except FaceProviderError as exc:
            raise FaceProviderFailedError() from exc

        before = face_profile_to_read(row).model_dump(mode="json")
        row.reference_photo_count += 1
        await self._session.flush()
        read = face_profile_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="FACE_PROFILE_PHOTO_ADDED",
            entity_type="employee_face_profile",
            entity_id=row.id,
            before=before,
            after=read.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

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
        row = await self._enrolled_profile_for_update(company_id, employee_id)

        try:
            await provider.delete_person(person_id=row.provider_person_id)
        except FaceProviderError as exc:
            raise FaceProviderFailedError() from exc

        before = face_profile_to_read(row).model_dump(mode="json")
        row.status = "REVOKED"
        row.revoked_at = datetime.now(UTC)
        row.revoked_by_user_id = actor_user_id
        await self._session.flush()
        read = face_profile_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="FACE_PROFILE_REVOKED",
            entity_type="employee_face_profile",
            entity_id=row.id,
            before=before,
            after=read.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def _enrolled_profile_for_update(
        self, company_id: UUID, employee_id: UUID
    ) -> EmployeeFaceProfile:
        row = await self._repo.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id, for_update=True
        )
        if row is None:
            raise FaceProfileNotFoundError()
        if row.status != "ENROLLED":
            raise FaceProfileNotEnrolledError()
        return row


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

    async def punch_self(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        image: bytes,
        direction: str,
        scope: DataScope,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FacePunchRead:
        if self._provider is None:
            raise FaceVerificationUnavailableError()
        provider = self._provider
        content_type = sniff_face_image(image)
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
        if match.decision != "MATCHED" or match.similarity is None or liveness.score is None:
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

        punch = await PunchService(self._session).record_punch(
            company_id,
            employee_id,
            direction=direction,
            requested_punch_time=None,
            source="FACE",
            reference=None,
            idempotency_key=None,
            scope=scope,
            caller_employee_id=employee_id,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
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
        provider_name = self._provider.provider_name if self._provider else "LUXAND"
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
