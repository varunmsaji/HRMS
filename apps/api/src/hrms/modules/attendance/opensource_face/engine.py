"""`OpenSourceFaceVerificationProvider` - the `FaceVerificationProvider` port implemented with
local inference and an encrypted embedding store (no Face++ account, no network).

Mapping of the port's vocabulary (so `FaceEnrollmentService` / `FacePunchService` need no
engine-specific branches):

- `person_id`: Face++ = FaceSet token; here `osf1.<company uuid>.<person_ref uuid>`.
- `enroll`: Face++ = detect + faceset/create; here = embed the front capture, store sample 0.
- `add_reference_photo`: Face++ = faceset/addface; here = embed and store another sample (capped).
- `verify`: Face++ = faceset/search; here = embed the probe, best cosine against THIS person's
  samples (1:1, never a tenant-wide search).
- `delete_person`: Face++ = faceset/delete; here = delete this person's embedding rows.

The person id carries the company so a Celery deletion (no request tenant) can open the right
row-level-security scope; when a request tenant *is* set it must equal the id's company, so a
forged or cross-tenant id fails closed. A person id that is not an `osf1.` id (e.g. a Face++
token reaching this engine) is an error, never a successful no-op. Embeddings made by a different
model version are not comparable and are refused (re-enrolment required) rather than compared.

Failure semantics match the Face++ adapter: infrastructure problems raise `FaceProviderError`
(recorded as PROVIDER_ERROR, which does not count toward the employee's lockout); an unusable
photo is NO_FACE / MULTIPLE_FACES; only a computed similarity can produce NO_MATCH or MATCHED.
No engine fallback exists - a failure here is a failure."""

import time
from decimal import Decimal
from uuid import UUID, uuid4

from hrms.core.config.settings import Settings
from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.core.observability.metrics import (
    DEPENDENCY_CALLS,
    DEPENDENCY_DURATION,
    DEPENDENCY_ERRORS,
    safe_count,
    safe_observe,
)
from hrms.core.tenancy.context import current_tenant_company_id
from hrms.modules.attendance.face_verification import (
    FaceMatchResult,
    FaceProviderError,
    FaceProviderMultipleFacesError,
    FaceProviderNoFaceError,
)
from hrms.modules.attendance.opensource_face.embedding_service import (
    EmbeddingError,
    EmbeddingOutcome,
    SFaceEmbeddingService,
)
from hrms.modules.attendance.opensource_face.similarity import best_similarity, to_score
from hrms.modules.attendance.opensource_face.store import (
    DbEmbeddingStore,
    EmbeddingStore,
    PersonNotFoundError,
    SampleLimitError,
)

PROVIDER_OPENSOURCE = "OPENSOURCE"
PERSON_ID_PREFIX = "osf1"
_DEPENDENCY = "face_local_engine"

_logger = get_logger(__name__)


def make_person_id(company_id: UUID, person_ref: UUID) -> str:
    return f"{PERSON_ID_PREFIX}.{company_id}.{person_ref}"


def parse_person_id(person_id: str) -> tuple[UUID, UUID]:
    """(company_id, person_ref); raises `FaceProviderError` for anything that is not an
    OPENSOURCE person id of the current request's tenant."""
    parts = person_id.split(".")
    if len(parts) != 3 or parts[0] != PERSON_ID_PREFIX:
        raise FaceProviderError("Not an open-source face engine person id.")
    try:
        company_id, person_ref = UUID(parts[1]), UUID(parts[2])
    except ValueError as exc:
        raise FaceProviderError("Malformed open-source face engine person id.") from exc
    tenant = current_tenant_company_id()
    if tenant is not None and tenant != str(company_id):
        raise FaceProviderError("Person id does not belong to the current tenant.")
    return company_id, person_ref


class OpenSourceFaceVerificationProvider:
    provider_name = PROVIDER_OPENSOURCE

    def __init__(
        self,
        settings: Settings,
        *,
        embedder: SFaceEmbeddingService | None = None,
        store: EmbeddingStore | None = None,
    ) -> None:
        self.match_threshold = Decimal(str(settings.face_os_match_threshold))
        self.angle_threshold = Decimal(str(settings.face_os_enrollment_angle_threshold))
        self._max_samples = settings.face_os_max_samples_per_person
        self._embedder = embedder
        self._settings = settings
        self._store: EmbeddingStore = store if store is not None else DbEmbeddingStore(settings)

    def _embedding_service(self) -> SFaceEmbeddingService:
        if self._embedder is None:
            from pathlib import Path

            self._embedder = SFaceEmbeddingService(
                Path(self._settings.face_os_model_dir),
                detector_score_threshold=self._settings.face_os_detector_score_threshold,
                min_face_px=self._settings.face_os_min_face_px,
                max_concurrency=self._settings.face_os_max_concurrency,
                timeout_seconds=self._settings.face_os_inference_timeout_seconds,
            )
        return self._embedder

    def warm_up(self) -> None:
        """Verifies assets and loads a model now - called at startup so a bad deployment fails
        on boot, not on the first punch."""
        self._embedding_service().warm_up()

    async def _embed(self, image: bytes, *, operation: str) -> EmbeddingOutcome:
        started = time.perf_counter()
        try:
            outcome = await self._embedding_service().embed(image)
        except EmbeddingError as exc:
            safe_count(DEPENDENCY_CALLS, _DEPENDENCY, "failure")
            safe_count(DEPENDENCY_ERRORS, _DEPENDENCY, type(exc).__name__)
            safe_observe(DEPENDENCY_DURATION, time.perf_counter() - started, _DEPENDENCY)
            safe_log(
                _logger.error,
                "face_os_inference_failed",
                provider=PROVIDER_OPENSOURCE,
                operation=operation,
                **safe_error(exc),
            )
            raise FaceProviderError(f"Face engine {operation} failed.") from exc
        safe_count(DEPENDENCY_CALLS, _DEPENDENCY, "success")
        safe_observe(DEPENDENCY_DURATION, time.perf_counter() - started, _DEPENDENCY)
        return outcome

    def _store_failure(self, operation: str, exc: Exception) -> FaceProviderError:
        safe_count(DEPENDENCY_ERRORS, _DEPENDENCY, "store")
        safe_log(
            _logger.error,
            "face_os_store_failed",
            provider=PROVIDER_OPENSOURCE,
            operation=operation,
            **safe_error(exc),
        )
        return FaceProviderError(f"Face engine {operation} failed.")

    @staticmethod
    def _usable(outcome: EmbeddingOutcome) -> tuple[float, ...]:
        if outcome.status == "MULTIPLE_FACES":
            raise FaceProviderMultipleFacesError("More than one face was detected in the photo.")
        if outcome.status != "OK" or outcome.embedding is None:
            raise FaceProviderNoFaceError("No usable face was detected in the photo.")
        return outcome.embedding

    async def enroll(self, *, label: str, image: bytes, content_type: str) -> str:
        tenant = current_tenant_company_id()
        if tenant is None:
            raise FaceProviderError("Open-source face enrollment needs a tenant context.")
        try:
            company_id, employee_id = UUID(tenant), UUID(label)
        except ValueError as exc:
            raise FaceProviderError("Enrollment label must be an employee id.") from exc
        embedding = self._usable(await self._embed(image, operation="enroll"))
        person_ref = uuid4()
        try:
            await self._store.create_person(
                company_id=company_id,
                employee_id=employee_id,
                person_ref=person_ref,
                model_version=self._embedding_service().model_version,
                embedding=embedding,
            )
        except Exception as exc:  # noqa: BLE001 - any store failure is an infrastructure error
            raise self._store_failure("enroll", exc) from exc
        return make_person_id(company_id, person_ref)

    async def add_reference_photo(self, *, person_id: str, image: bytes, content_type: str) -> None:
        company_id, person_ref = parse_person_id(person_id)
        embedding = self._usable(await self._embed(image, operation="add_reference_photo"))
        try:
            await self._store.add_sample(
                company_id=company_id,
                person_ref=person_ref,
                model_version=self._embedding_service().model_version,
                embedding=embedding,
                max_samples=self._max_samples,
            )
        except (PersonNotFoundError, SampleLimitError) as exc:
            raise FaceProviderError("Reference photo could not be added.") from exc
        except Exception as exc:  # noqa: BLE001
            raise self._store_failure("add_reference_photo", exc) from exc

    async def verify(self, *, person_id: str, image: bytes, content_type: str) -> FaceMatchResult:
        company_id, person_ref = parse_person_id(person_id)
        try:
            stored = await self._store.load(company_id=company_id, person_ref=person_ref)
        except Exception as exc:  # noqa: BLE001
            raise self._store_failure("verify", exc) from exc
        current = self._embedding_service().model_version
        references = [s.embedding for s in stored if s.model_version == current]
        if not references:
            # Nothing comparable (profile gone, or enrolled with another model version): an
            # infrastructure/state error that needs re-enrolment, never a biometric NO_MATCH.
            safe_log(
                _logger.error,
                "face_os_no_comparable_reference",
                provider=PROVIDER_OPENSOURCE,
                stored_samples=len(stored),
            )
            raise FaceProviderError("No comparable reference embeddings; re-enrolment required.")
        outcome = await self._embed(image, operation="verify")
        if outcome.status == "MULTIPLE_FACES":
            return FaceMatchResult("MULTIPLE_FACES", None)
        if outcome.status != "OK" or outcome.embedding is None:
            return FaceMatchResult("NO_FACE", None)
        similarity = to_score(best_similarity(outcome.embedding, references))
        if similarity >= self.match_threshold:
            return FaceMatchResult("MATCHED", similarity, None)
        return FaceMatchResult("NO_MATCH", similarity, None)

    async def delete_person(self, *, person_id: str) -> None:
        company_id, person_ref = parse_person_id(person_id)
        try:
            await self._store.delete_person(company_id=company_id, person_ref=person_ref)
        except Exception as exc:  # noqa: BLE001
            raise self._store_failure("delete_person", exc) from exc

    async def aclose(self) -> None:
        return None
