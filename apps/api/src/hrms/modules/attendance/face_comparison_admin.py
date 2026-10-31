"""Admin / test-operator side of shadow comparison: shadow enrollment of consenting test
participants, the comparison report, and ground-truth labelling for FAR/FRR.

Everything here needs `ATTENDANCE.FACE_ENROLLMENT_MANAGE` (HR) - the same grant that already
guards face profiles - and none of it is reachable by an ordinary employee. Nothing here touches
`employee_face_profile`, a punch or an attempt row."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Select, and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from hrms.core.config.settings import Settings
from hrms.core.errors.base import ConflictError, NotFoundError, ValidationError
from hrms.core.rbac.types import DataScope
from hrms.modules.attendance.exceptions import (
    FaceConsentRequiredError,
    FaceVerificationUnavailableError,
)
from hrms.modules.attendance.face_service import sniff_face_image
from hrms.modules.attendance.face_verification import FaceProviderError, FaceVerificationProvider
from hrms.modules.attendance.models import FaceShadowEnrollment, FaceVerificationComparison
from hrms.modules.attendance.schemas import FACE_IMAGE_MAX_BYTES
from hrms.modules.attendance.service import (
    _ensure_employee_visible,
    _resolve_visible_employee_ids,
)
from hrms.shared.pagination import PageParams

MAX_SHADOW_PHOTOS = 8


class ShadowEnrollmentRead(BaseModel):
    """Never exposes `provider_person_id` (a handle into a biometric store)."""

    id: UUID
    employee_id: UUID
    provider: str
    consent_recorded_at: datetime
    enrolled_by_user_id: UUID | None


class ComparisonRead(BaseModel):
    id: UUID
    employee_id: UUID
    liveness_session_id: UUID | None
    primary_provider: str
    shadow_provider: str
    primary_result: str
    shadow_result: str
    primary_matched: bool
    shadow_matched: bool | None
    primary_score: Decimal | None
    shadow_score: Decimal | None
    primary_threshold: Decimal | None
    shadow_threshold: Decimal | None
    primary_latency_ms: int | None
    shadow_latency_ms: int | None
    results_agree: bool | None
    primary_error: str | None
    shadow_error: str | None
    shadow_timed_out: bool
    frames_compared: int
    liveness_score: Decimal | None
    ground_truth: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LatencyStats(BaseModel):
    samples: int
    avg_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None


class ErrorRates(BaseModel):
    """Out of all comparisons, how many the provider failed to produce a verdict for."""

    errors: int
    timeouts: int
    error_rate: float | None


class LabelledMetrics(BaseModel):
    """FAR/FRR over rows an admin labelled GENUINE / IMPOSTOR, per provider, on rows where that
    provider produced a verdict. FAR = impostor attempts accepted / impostor attempts. FRR =
    genuine attempts rejected / genuine attempts. None while there is nothing to divide by.
    Small samples give wide uncertainty; the counts are returned so that can be judged."""

    genuine_attempts: int
    impostor_attempts: int
    true_accepts: int
    false_rejects: int
    true_rejects: int
    false_accepts: int
    far: float | None
    frr: float | None


class ProviderReport(BaseModel):
    provider: str | None
    matched: int
    latency: LatencyStats
    failures: ErrorRates
    labelled: LabelledMetrics


class ComparisonSummary(BaseModel):
    total: int
    comparable: int
    """Rows where both providers produced a verdict (the only rows agreement is defined on)."""
    both_matched: int
    both_rejected: int
    primary_only_matched: int
    shadow_only_matched: int
    agreement_pct: float | None
    shadow_not_enrolled: int
    primary: ProviderReport
    shadow: ProviderReport


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 2) if whole else None


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


class FaceComparisonAdminService:
    def __init__(
        self,
        session: AsyncSession,
        shadow_provider: FaceVerificationProvider | None,
        settings: Settings,
    ) -> None:
        self._session = session
        self._shadow = shadow_provider
        self._settings = settings

    def _require_shadow(self) -> FaceVerificationProvider:
        if self._shadow is None:
            raise FaceVerificationUnavailableError(
                "Shadow comparison is not enabled for this deployment"
            )
        return self._shadow

    # -- shadow enrollment -------------------------------------------------------------------

    async def enroll_shadow(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        photos: list[bytes],
        consent_confirmed: bool,
        scope: DataScope,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
    ) -> ShadowEnrollmentRead:
        provider = self._require_shadow()
        if not consent_confirmed:
            raise FaceConsentRequiredError()
        if not 1 <= len(photos) <= MAX_SHADOW_PHOTOS:
            raise ValidationError(f"Between 1 and {MAX_SHADOW_PHOTOS} photos are required")
        content_types = [
            sniff_face_image(p, field=f"photo {i + 1}", max_bytes=FACE_IMAGE_MAX_BYTES)
            for i, p in enumerate(photos)
        ]
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        name = provider.provider_name
        existing = await self._get(company_id, employee_id, name)
        if existing is not None:
            raise ConflictError(
                "This employee already has a shadow enrollment; delete it to enroll again"
            )
        try:
            person_id = await provider.enroll(
                label=str(employee_id), image=photos[0], content_type=content_types[0]
            )
        except FaceProviderError as exc:
            raise ValidationError(f"The shadow provider rejected the first photo: {exc}") from exc
        try:
            for photo, content_type in zip(photos[1:], content_types[1:], strict=True):
                await provider.add_reference_photo(
                    person_id=person_id, image=photo, content_type=content_type
                )
        except FaceProviderError as exc:
            await self._discard(provider, person_id)
            raise ValidationError(f"The shadow provider rejected a photo: {exc}") from exc
        row = FaceShadowEnrollment(
            id=uuid4(),
            company_id=company_id,
            employee_id=employee_id,
            provider=name,
            provider_person_id=person_id,
            consent_recorded_at=datetime.now(UTC),
            enrolled_by_user_id=actor_user_id,
        )
        try:
            self._session.add(row)
            await self._session.flush()
        except Exception:
            await self._discard(provider, person_id)
            raise
        return self._enrollment_read(row)

    async def delete_shadow(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> None:
        provider = self._require_shadow()
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        row = await self._get(company_id, employee_id, provider.provider_name)
        if row is None:
            raise NotFoundError("No shadow enrollment for this employee")
        # Provider first: if it fails the row (and so the handle) is kept and the call can be
        # retried, instead of stranding a biometric record nobody can find.
        try:
            await provider.delete_person(person_id=row.provider_person_id)
        except FaceProviderError as exc:
            raise ValidationError("The shadow provider could not delete the enrollment") from exc
        await self._session.execute(
            delete(FaceShadowEnrollment).where(FaceShadowEnrollment.id == row.id)
        )

    async def list_shadow(
        self, company_id: UUID, *, scope: DataScope, caller_employee_id: UUID | None
    ) -> list[ShadowEnrollmentRead]:
        visible = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        stmt = select(FaceShadowEnrollment).where(FaceShadowEnrollment.company_id == company_id)
        if visible is not None:
            stmt = stmt.where(FaceShadowEnrollment.employee_id.in_(visible))
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._enrollment_read(r) for r in rows]

    async def _get(
        self, company_id: UUID, employee_id: UUID, provider: str
    ) -> FaceShadowEnrollment | None:
        stmt = select(FaceShadowEnrollment).where(
            FaceShadowEnrollment.company_id == company_id,
            FaceShadowEnrollment.employee_id == employee_id,
            FaceShadowEnrollment.provider == provider,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def _discard(provider: FaceVerificationProvider, person_id: str) -> None:
        try:
            await provider.delete_person(person_id=person_id)
        except Exception:  # noqa: BLE001 - best-effort cleanup of a half-made enrollment
            pass

    @staticmethod
    def _enrollment_read(row: FaceShadowEnrollment) -> ShadowEnrollmentRead:
        return ShadowEnrollmentRead(
            id=row.id,
            employee_id=row.employee_id,
            provider=row.provider,
            consent_recorded_at=row.consent_recorded_at,
            enrolled_by_user_id=row.enrolled_by_user_id,
        )

    # -- report ------------------------------------------------------------------------------

    def _filtered(
        self,
        stmt: Select,  # type: ignore[type-arg]
        company_id: UUID,
        *,
        date_from: datetime | None,
        date_to: datetime | None,
        employee_id: UUID | None,
        primary_provider: str | None,
        shadow_provider: str | None,
        agreement: Literal["agree", "disagree"] | None,
        errors_only: bool,
        visible: frozenset[UUID] | None = None,
    ) -> Select:  # type: ignore[type-arg]
        c = FaceVerificationComparison
        stmt = stmt.where(c.company_id == company_id)
        if visible is not None:
            stmt = stmt.where(c.employee_id.in_(visible))
        if date_from is not None:
            stmt = stmt.where(c.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(c.created_at < date_to)
        if employee_id is not None:
            stmt = stmt.where(c.employee_id == employee_id)
        if primary_provider is not None:
            stmt = stmt.where(c.primary_provider == primary_provider.upper())
        if shadow_provider is not None:
            stmt = stmt.where(c.shadow_provider == shadow_provider.upper())
        if agreement == "agree":
            stmt = stmt.where(c.results_agree.is_(True))
        elif agreement == "disagree":
            stmt = stmt.where(c.results_agree.is_(False))
        if errors_only:
            stmt = stmt.where((c.primary_error.is_not(None)) | (c.shadow_error.is_not(None)))
        return stmt

    async def list_comparisons(
        self,
        company_id: UUID,
        page: PageParams,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        **filters: object,
    ) -> tuple[list[ComparisonRead], int]:
        c = FaceVerificationComparison
        filters["visible"] = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        base = self._filtered(select(c), company_id, **filters)  # type: ignore[arg-type]
        total = (
            await self._session.execute(
                self._filtered(select(func.count()).select_from(c), company_id, **filters)  # type: ignore[arg-type]
            )
        ).scalar_one()
        rows = (
            (
                await self._session.execute(
                    base.order_by(c.created_at.desc(), c.id).limit(page.limit).offset(page.offset)
                )
            )
            .scalars()
            .all()
        )
        return [ComparisonRead.model_validate(r) for r in rows], total

    async def summary(
        self,
        company_id: UUID,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
        **filters: object,
    ) -> ComparisonSummary:
        c = FaceVerificationComparison
        filters["visible"] = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )

        def count(*conditions: ColumnElement[bool]) -> ColumnElement[int]:
            return func.count().filter(and_(*conditions)) if conditions else func.count()

        def latency(column: InstrumentedAttribute[int | None]) -> tuple[ColumnElement[Any], ...]:
            return (
                func.count(column),
                func.avg(column),
                func.percentile_cont(0.5).within_group(column),
                func.percentile_cont(0.95).within_group(column),
                func.percentile_cont(0.99).within_group(column),
            )

        gt, sm, pm = c.ground_truth, c.shadow_matched, c.primary_matched
        stmt = select(
            count(),
            count(c.results_agree.is_not(None)),
            count(pm.is_(True), sm.is_(True)),
            count(pm.is_(False), sm.is_(False)),
            count(pm.is_(True), sm.is_(False)),
            count(pm.is_(False), sm.is_(True)),
            count(c.shadow_result == "NOT_ENROLLED"),
            count(pm.is_(True)),
            count(sm.is_(True)),
            count(c.primary_error.is_not(None)),
            count(c.shadow_error.is_not(None)),
            count(c.shadow_timed_out.is_(True)),
            # labelled: genuine / impostor attempts, accepts, per provider
            count(gt == "GENUINE", c.primary_error.is_(None)),
            count(gt == "IMPOSTOR", c.primary_error.is_(None)),
            count(gt == "GENUINE", pm.is_(True)),
            count(gt == "IMPOSTOR", pm.is_(True)),
            count(gt == "GENUINE", sm.is_not(None)),
            count(gt == "IMPOSTOR", sm.is_not(None)),
            count(gt == "GENUINE", sm.is_(True)),
            count(gt == "IMPOSTOR", sm.is_(True)),
            *latency(c.primary_latency_ms),
            *latency(c.shadow_latency_ms),
            func.max(c.primary_provider),
            func.max(c.shadow_provider),
        )
        row = (
            await self._session.execute(
                self._filtered(stmt, company_id, **filters)  # type: ignore[arg-type]
            )
        ).one()
        (
            total,
            comparable,
            both_matched,
            both_rejected,
            primary_only,
            shadow_only,
            not_enrolled,
            primary_matched,
            shadow_matched,
            primary_errors,
            shadow_errors,
            shadow_timeouts,
            p_gen,
            p_imp,
            p_gen_acc,
            p_imp_acc,
            s_gen,
            s_imp,
            s_gen_acc,
            s_imp_acc,
            *rest,
        ) = row
        primary_latency, shadow_latency = tuple(rest[0:5]), tuple(rest[5:10])
        primary_name, shadow_name = rest[10], rest[11]

        def stats(values: tuple[Any, ...]) -> LatencyStats:
            n, avg, p50, p95, p99 = values
            return LatencyStats(
                samples=n,
                avg_ms=round(float(avg), 1) if avg is not None else None,
                p50_ms=round(float(p50), 1) if p50 is not None else None,
                p95_ms=round(float(p95), 1) if p95 is not None else None,
                p99_ms=round(float(p99), 1) if p99 is not None else None,
            )

        def labelled(gen: int, imp: int, gen_acc: int, imp_acc: int) -> LabelledMetrics:
            return LabelledMetrics(
                genuine_attempts=gen,
                impostor_attempts=imp,
                true_accepts=gen_acc,
                false_rejects=gen - gen_acc,
                true_rejects=imp - imp_acc,
                false_accepts=imp_acc,
                far=_ratio(imp_acc, imp),
                frr=_ratio(gen - gen_acc, gen),
            )

        return ComparisonSummary(
            total=total,
            comparable=comparable,
            both_matched=both_matched,
            both_rejected=both_rejected,
            primary_only_matched=primary_only,
            shadow_only_matched=shadow_only,
            agreement_pct=_pct(both_matched + both_rejected, comparable),
            shadow_not_enrolled=not_enrolled,
            primary=ProviderReport(
                provider=primary_name,
                matched=primary_matched,
                latency=stats(primary_latency),
                failures=ErrorRates(
                    errors=primary_errors, timeouts=0, error_rate=_ratio(primary_errors, total)
                ),
                labelled=labelled(p_gen, p_imp, p_gen_acc, p_imp_acc),
            ),
            shadow=ProviderReport(
                provider=shadow_name,
                matched=shadow_matched,
                latency=stats(shadow_latency),
                failures=ErrorRates(
                    errors=shadow_errors,
                    timeouts=shadow_timeouts,
                    error_rate=_ratio(shadow_errors, total),
                ),
                labelled=labelled(s_gen, s_imp, s_gen_acc, s_imp_acc),
            ),
        )

    async def label(
        self,
        company_id: UUID,
        comparison_id: UUID,
        ground_truth: Literal["GENUINE", "IMPOSTOR"] | None,
        *,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> ComparisonRead:
        c = FaceVerificationComparison
        visible = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        row = (
            await self._session.execute(
                select(c).where(c.company_id == company_id, c.id == comparison_id)
            )
        ).scalar_one_or_none()
        if row is None or (visible is not None and row.employee_id not in visible):
            raise NotFoundError("Comparison not found")
        row.ground_truth = ground_truth
        await self._session.flush()
        return ComparisonRead.model_validate(row)
