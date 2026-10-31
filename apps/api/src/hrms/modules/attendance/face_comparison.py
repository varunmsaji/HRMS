"""Shadow face-provider comparison: strictly observational.

The primary provider alone decides a face punch (`FacePunchService.punch_self`). When
`face_provider_comparison_enabled` is on, this module runs the SHADOW provider on the same
in-memory frames and writes what it saw to `face_verification_comparison`. The safety rules,
enforced here and proven by `tests/unit/modules/attendance/test_face_comparison.py`:

* nothing in this module returns a value the punch path branches on; `finish_comparison` returns
  None and never raises (cancellation excepted);
* the shadow runs in its own task with its own wall-clock timeout, in its own DB transaction, so
  a shadow error, timeout or opposite verdict cannot fail, delay beyond that timeout or change the
  punch, the attempt log or the failed-attempt limit;
* no frame, embedding, provider body or credential is persisted or logged - only decisions,
  scores, thresholds, latencies and error codes. Frames are used from memory during the request
  and are not kept, so comparison adds no biometric retention.

Scores are never compared across providers (SFace cosine similarity and Face++ confidence are
different scales). Only the binary matched / not-matched outcome is, as `results_agree`.
"""

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from hrms.core.config.settings import Settings
from hrms.core.db.session import session_scope
from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.modules.attendance.face_verification import (
    FaceMatchResult,
    FaceProviderError,
    FaceVerificationProvider,
)
from hrms.modules.attendance.models import FaceShadowEnrollment, FaceVerificationComparison

_logger = get_logger(__name__)

# Slack beyond the shadow's own timeout before the awaiting side gives up on the task.
_AWAIT_MARGIN_SECONDS = 1.0

NOT_ENROLLED = "NOT_ENROLLED"
SHADOW_ERROR = "ERROR"
SHADOW_TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class ProviderObservation:
    """One provider's verdict for a whole punch attempt, on a provider-neutral footing.

    `result` uses the attempt vocabulary (MATCHED, NO_MATCH, NO_FACE, AMBIGUOUS_FACE,
    IDENTITY_INCONSISTENT, PROVIDER_ERROR) plus NOT_ENROLLED / ERROR / TIMEOUT for a shadow that
    produced no verdict. `matched` is None when there was no verdict. `score` and `threshold` are
    in the provider's OWN scale."""

    provider: str
    result: str
    matched: bool | None
    score: Decimal | None = None
    threshold: Decimal | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    timed_out: bool = False


def match_threshold(provider: FaceVerificationProvider, settings: Settings) -> Decimal:
    """The floor a frame's similarity must reach - the same rule `punch_self` applies."""
    return getattr(provider, "match_threshold", None) or Decimal(
        str(settings.face_match_min_similarity)
    )


def frame_is_match(
    result: FaceMatchResult, provider: FaceVerificationProvider, settings: Settings
) -> bool:
    return (
        result.decision == "MATCHED"
        and result.similarity is not None
        and result.similarity >= match_threshold(provider, settings)
    )


def _reject_code(decision: str, *, any_matched: bool) -> str:
    if decision == "MULTIPLE_FACES":
        return "AMBIGUOUS_FACE"
    if decision == "NO_FACE":
        return "NO_FACE"
    return "IDENTITY_INCONSISTENT" if any_matched else "NO_MATCH"


def summarise_frames(
    results: Sequence[FaceMatchResult],
    provider: FaceVerificationProvider,
    settings: Settings,
    *,
    expected_frames: int,
) -> tuple[str, bool, Decimal | None]:
    """(result, matched, score) for a punch from per-frame verdicts, with the same all-frames-
    must-match rule as the official path. The score is the lowest matched similarity, or the
    failing frame's."""
    matched_scores: list[Decimal] = []
    for index, frame in enumerate(results):
        if frame_is_match(frame, provider, settings):
            assert frame.similarity is not None
            matched_scores.append(frame.similarity)
            continue
        return _reject_code(frame.decision, any_matched=index > 0), False, frame.similarity
    if len(matched_scores) != expected_frames:
        return "NO_MATCH", False, min(matched_scores) if matched_scores else None
    return "MATCHED", True, min(matched_scores)


async def _shadow_person_id(company_id: UUID, employee_id: UUID, provider: str) -> str | None:
    async with session_scope(company_id=str(company_id)) as session:
        stmt = select(FaceShadowEnrollment.provider_person_id).where(
            FaceShadowEnrollment.company_id == company_id,
            FaceShadowEnrollment.employee_id == employee_id,
            FaceShadowEnrollment.provider == provider,
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def _run_shadow(
    provider: FaceVerificationProvider,
    settings: Settings,
    *,
    company_id: UUID,
    employee_id: UUID,
    frames: Sequence[bytes],
    content_types: Sequence[str],
) -> ProviderObservation:
    started = time.perf_counter()

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    threshold = match_threshold(provider, settings)
    name = provider.provider_name
    try:
        async with asyncio.timeout(settings.face_provider_shadow_timeout_seconds):
            person_id = await _shadow_person_id(company_id, employee_id, name)
            if person_id is None:
                return ProviderObservation(name, NOT_ENROLLED, None, threshold=threshold)
            results: list[FaceMatchResult] = []
            for frame, content_type in zip(frames, content_types, strict=True):
                results.append(
                    await provider.verify(
                        person_id=person_id, image=frame, content_type=content_type
                    )
                )
        result, matched, score = summarise_frames(
            results, provider, settings, expected_frames=len(frames)
        )
        return ProviderObservation(name, result, matched, score, threshold, elapsed_ms())
    except TimeoutError:
        return ProviderObservation(
            name,
            SHADOW_TIMEOUT,
            None,
            threshold=threshold,
            latency_ms=elapsed_ms(),
            error_code="TIMEOUT",
            timed_out=True,
        )
    except FaceProviderError as exc:
        safe_log(_logger.warning, "face_shadow_provider_error", provider=name, **safe_error(exc))
        return ProviderObservation(
            name,
            SHADOW_ERROR,
            None,
            threshold=threshold,
            latency_ms=elapsed_ms(),
            error_code="PROVIDER_ERROR",
        )
    except Exception as exc:  # noqa: BLE001 - a shadow must never surface anything
        safe_log(_logger.error, "face_shadow_unexpected_error", provider=name, **safe_error(exc))
        return ProviderObservation(
            name,
            SHADOW_ERROR,
            None,
            threshold=threshold,
            latency_ms=elapsed_ms(),
            error_code="UNEXPECTED",
        )


def start_shadow(
    provider: FaceVerificationProvider | None,
    settings: Settings,
    *,
    company_id: UUID,
    employee_id: UUID,
    frames: Sequence[bytes],
    content_types: Sequence[str],
) -> "asyncio.Task[ProviderObservation] | None":
    """Starts the shadow concurrently with the primary check. None when comparison is off or no
    shadow provider is configured - then no shadow code runs at all. The task is bounded by the
    shadow timeout and swallows its own errors, so abandoning it (the primary path raised) leaks
    nothing and logs no 'exception never retrieved'."""
    if provider is None or not settings.face_provider_comparison_enabled:
        return None
    return asyncio.create_task(
        _run_shadow(
            provider,
            settings,
            company_id=company_id,
            employee_id=employee_id,
            frames=frames,
            content_types=content_types,
        )
    )


def build_row(
    primary: ProviderObservation,
    shadow: ProviderObservation,
    *,
    company_id: UUID,
    employee_id: UUID,
    session_id: UUID | None,
    liveness_score: Decimal | None,
    frames: int,
) -> dict[str, object]:
    agree = (
        None
        if shadow.matched is None or primary.error_code is not None
        else primary.matched == shadow.matched
    )
    return {
        "id": uuid4(),
        "company_id": company_id,
        "employee_id": employee_id,
        "liveness_session_id": session_id,
        "primary_provider": primary.provider,
        "shadow_provider": shadow.provider,
        "primary_result": primary.result,
        "shadow_result": shadow.result,
        "primary_matched": bool(primary.matched),
        "shadow_matched": shadow.matched,
        "primary_score": primary.score,
        "shadow_score": shadow.score,
        "primary_threshold": primary.threshold,
        "shadow_threshold": shadow.threshold,
        "primary_latency_ms": primary.latency_ms,
        "shadow_latency_ms": shadow.latency_ms,
        "results_agree": agree,
        "primary_error": primary.error_code,
        "shadow_error": shadow.error_code,
        "shadow_timed_out": shadow.timed_out,
        "frames_compared": frames,
        "liveness_score": liveness_score,
    }


async def finish_comparison(
    task: "asyncio.Task[ProviderObservation] | None",
    settings: Settings,
    primary: ProviderObservation,
    *,
    company_id: UUID,
    employee_id: UUID,
    session_id: UUID | None,
    liveness_score: Decimal | None,
    frames: int,
) -> None:
    """Waits (bounded) for the shadow, records the comparison and logs it. Returns None and
    swallows every ordinary exception: it is called on the punch path, after the official outcome
    is already fixed, and has no way to alter it."""
    if task is None:
        return
    try:
        try:
            shadow = await asyncio.wait_for(
                task, settings.face_provider_shadow_timeout_seconds + _AWAIT_MARGIN_SECONDS
            )
        except TimeoutError:
            shadow = ProviderObservation(
                settings.face_verification_shadow_provider.upper(),
                SHADOW_TIMEOUT,
                None,
                error_code="TIMEOUT",
                timed_out=True,
            )
        row = build_row(
            primary,
            shadow,
            company_id=company_id,
            employee_id=employee_id,
            session_id=session_id,
            liveness_score=liveness_score,
            frames=frames,
        )
        async with session_scope(company_id=str(company_id)) as session:
            session.add(FaceVerificationComparison(**row))
        safe_log(
            _logger.info,
            "face_provider_comparison",
            primary_provider=primary.provider,
            shadow_provider=shadow.provider,
            primary_decision=primary.result,
            shadow_decision=shadow.result,
            results_agree=row["results_agree"],
            primary_latency_ms=primary.latency_ms,
            shadow_latency_ms=shadow.latency_ms,
            shadow_timed_out=shadow.timed_out,
            company_id=str(company_id),
            employee_id=str(employee_id),
        )
    except Exception as exc:  # noqa: BLE001 - observation must never touch the punch
        safe_log(_logger.error, "face_comparison_record_failed", **safe_error(exc))
