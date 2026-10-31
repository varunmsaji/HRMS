"""Shadow face-provider comparison: configuration rules and the observation-only guarantees of
`face_comparison.py`. Providers are in-memory fakes; nothing contacts Face++ or loads a model."""

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hrms.core.config.settings import Settings
from hrms.modules.attendance import face_comparison
from hrms.modules.attendance.face_comparison import (
    ProviderObservation,
    build_row,
    finish_comparison,
    start_shadow,
    summarise_frames,
)
from hrms.modules.attendance.face_verification import (
    FaceMatchResult,
    FaceProviderError,
)

FACEPP = {"facepp_api_key": "k", "facepp_api_secret": "s"}
OS = {"face_os_enabled": True, "face_os_model_dir": "/models"}


def make(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


# -- configuration ---------------------------------------------------------------------------


def test_comparison_is_off_by_default() -> None:
    s = make()
    assert s.face_provider_comparison_enabled is False
    assert s.face_verification_shadow_provider == "disabled"


@pytest.mark.parametrize(
    ("primary", "shadow"), [("opensource", "facepp"), ("facepp", "opensource")]
)
def test_valid_pairs(primary: str, shadow: str) -> None:
    s = make(
        face_verification_provider=primary,
        face_verification_shadow_provider=shadow,
        face_provider_comparison_enabled=True,
        **FACEPP,
        **OS,
    )
    assert s.face_provider_comparison_enabled


def test_single_provider_modes_stay_valid() -> None:
    make(face_verification_provider="opensource", **OS)
    make(face_verification_provider="facepp", **FACEPP)


def test_disabled_comparison_ignores_the_shadow_setting() -> None:
    make(
        face_verification_provider="opensource",
        face_verification_shadow_provider="opensource",
        face_provider_comparison_enabled=False,
        **OS,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"face_verification_shadow_provider": "facepp"},  # no primary
        {"face_verification_provider": "opensource", **OS},  # shadow disabled
        {  # duplicate
            "face_verification_provider": "opensource",
            "face_verification_shadow_provider": "opensource",
            **OS,
        },
        {  # shadow facepp, no credentials
            "face_verification_provider": "opensource",
            "face_verification_shadow_provider": "facepp",
            **OS,
        },
        {  # shadow opensource, no engine
            "face_verification_provider": "facepp",
            "face_verification_shadow_provider": "opensource",
            **FACEPP,
        },
    ],
)
def test_invalid_combinations_fail_clearly(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make(face_provider_comparison_enabled=True, **overrides)


def test_unknown_provider_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make(face_verification_shadow_provider="luxand")


# -- fakes -----------------------------------------------------------------------------------


class Fake:
    def __init__(
        self,
        name: str,
        results: Sequence[FaceMatchResult] | None = None,
        *,
        error: Exception | None = None,
        delay: float = 0.0,
        threshold: Decimal | None = None,
    ) -> None:
        self.provider_name = name
        self.results = list(results or [])
        self.error = error
        self.delay = delay
        self.calls = 0
        if threshold is not None:
            self.match_threshold = threshold

    async def verify(self, *, person_id: str, image: bytes, content_type: str) -> FaceMatchResult:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.results.pop(0)


def matched(sim: str = "0.97") -> FaceMatchResult:
    return FaceMatchResult("MATCHED", Decimal(sim))


SETTINGS = make(
    face_verification_provider="opensource",
    face_verification_shadow_provider="facepp",
    face_provider_comparison_enabled=True,
    face_provider_shadow_timeout_seconds=0.2,
    **FACEPP,
    **OS,
)


@pytest.fixture
def enrolled(monkeypatch: pytest.MonkeyPatch) -> None:
    async def person(*_: object) -> str | None:
        return "person-1"

    monkeypatch.setattr(face_comparison, "_shadow_person_id", person)


def primary_obs(matched_: bool = True, result: str = "MATCHED") -> ProviderObservation:
    return ProviderObservation("OPENSOURCE", result, matched_, Decimal("0.6"), latency_ms=100)


async def run_shadow(shadow: Fake) -> ProviderObservation:
    task = start_shadow(
        shadow,  # type: ignore[arg-type]
        SETTINGS,
        company_id=uuid4(),
        employee_id=uuid4(),
        frames=[b"a", b"b", b"c"],
        content_types=["image/jpeg"] * 3,
    )
    assert task is not None
    return await task


# -- provider outcomes, mapped the way the official path maps them ---------------------------


async def test_shadow_match(enrolled: None) -> None:
    obs = await run_shadow(Fake("FACEPP", [matched(), matched("0.95"), matched()]))
    assert (obs.result, obs.matched, obs.score) == ("MATCHED", True, Decimal("0.95"))
    assert obs.latency_ms is not None


async def test_shadow_reject(enrolled: None) -> None:
    obs = await run_shadow(
        Fake("FACEPP", [matched(), FaceMatchResult("NO_MATCH", Decimal("0.4")), matched()])
    )
    assert (obs.result, obs.matched) == ("IDENTITY_INCONSISTENT", False)


async def test_below_threshold_is_not_a_match(enrolled: None) -> None:
    obs = await run_shadow(Fake("FACEPP", [matched("0.5")] * 3))
    assert obs.matched is False


async def test_shadow_provider_error_is_contained(enrolled: None) -> None:
    obs = await run_shadow(Fake("FACEPP", error=FaceProviderError("boom")))
    assert (obs.result, obs.matched, obs.error_code) == ("ERROR", None, "PROVIDER_ERROR")


async def test_shadow_unexpected_exception_is_contained(enrolled: None) -> None:
    obs = await run_shadow(Fake("FACEPP", error=RuntimeError("bug")))
    assert (obs.result, obs.error_code) == ("ERROR", "UNEXPECTED")


async def test_shadow_timeout_is_bounded_and_recorded(enrolled: None) -> None:
    started = asyncio.get_running_loop().time()
    obs = await run_shadow(Fake("FACEPP", [matched()] * 3, delay=5))
    assert asyncio.get_running_loop().time() - started < 1
    assert (obs.result, obs.timed_out, obs.matched) == ("TIMEOUT", True, None)


async def test_shadow_not_enrolled_is_recorded_without_calling_the_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def nobody(*_: object) -> None:
        return None

    monkeypatch.setattr(face_comparison, "_shadow_person_id", nobody)
    shadow = Fake("FACEPP")
    obs = await run_shadow(shadow)
    assert (obs.result, obs.matched) == ("NOT_ENROLLED", None)
    assert shadow.calls == 0


def test_comparison_off_starts_nothing() -> None:
    assert start_shadow(None, SETTINGS, company_id=uuid4(), employee_id=uuid4(), frames=[],
                        content_types=[]) is None  # fmt: skip
    off = make()
    shadow = Fake("FACEPP")
    assert start_shadow(shadow, off, company_id=uuid4(), employee_id=uuid4(), frames=[b"a"],  # type: ignore[arg-type]
                        content_types=["image/jpeg"]) is None  # fmt: skip
    assert shadow.calls == 0


def test_summarise_requires_every_frame() -> None:
    fake = Fake("X")
    summary = summarise_frames([matched()], fake, SETTINGS, expected_frames=3)  # type: ignore[arg-type]
    assert summary[:2] == ("NO_MATCH", False)


# -- agreement rows --------------------------------------------------------------------------


def row(primary: ProviderObservation, shadow: ProviderObservation) -> dict[str, object]:
    return build_row(
        primary, shadow, company_id=uuid4(), employee_id=uuid4(), session_id=None,
        liveness_score=None, frames=3,
    )  # fmt: skip


def test_agreement_is_on_the_binary_outcome_not_on_scores() -> None:
    shadow = ProviderObservation("FACEPP", "MATCHED", True, Decimal("0.99"))
    assert row(primary_obs(), shadow)["results_agree"] is True
    rejected = ProviderObservation("FACEPP", "NO_MATCH", False, Decimal("0.2"))
    assert row(primary_obs(), rejected)["results_agree"] is False
    assert row(primary_obs(False, "NO_MATCH"), rejected)["results_agree"] is True


def test_no_shadow_verdict_means_agreement_is_unknown() -> None:
    for result in ("ERROR", "TIMEOUT", "NOT_ENROLLED"):
        shadow = ProviderObservation("FACEPP", result, None)
        assert row(primary_obs(), shadow)["results_agree"] is None


# -- SHADOW SAFETY: nothing the shadow does can reach the caller ------------------------------


@pytest.mark.parametrize(
    "shadow",
    [
        Fake("FACEPP", [matched()] * 3),  # opposite verdict to a primary reject
        Fake("FACEPP", [FaceMatchResult("NO_MATCH", Decimal("0.1"))] * 3),  # opposite to a match
        Fake("FACEPP", error=FaceProviderError("x")),
        Fake("FACEPP", error=RuntimeError("x")),
        Fake("FACEPP", [matched()] * 3, delay=5),  # timeout
    ],
)
@pytest.mark.parametrize("persist_fails", [False, True])
async def test_finish_comparison_returns_nothing_and_never_raises(
    enrolled: None,
    monkeypatch: pytest.MonkeyPatch,
    shadow: Fake,
    persist_fails: bool,
) -> None:
    stored: list[object] = []

    class Scope:
        async def __aenter__(self) -> "Scope":
            if persist_fails:
                raise ConnectionError("db down")
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        def add(self, obj: object) -> None:
            stored.append(obj)

    monkeypatch.setattr(face_comparison, "session_scope", lambda **_: Scope())
    task = start_shadow(
        shadow,  # type: ignore[arg-type]
        SETTINGS,
        company_id=uuid4(),
        employee_id=uuid4(),
        frames=[b"a", b"b", b"c"],
        content_types=["image/jpeg"] * 3,
    )
    for primary in (primary_obs(True), primary_obs(False, "NO_MATCH")):
        result = await finish_comparison(
            task, SETTINGS, primary, company_id=uuid4(), employee_id=uuid4(),
            session_id=None, liveness_score=None, frames=3,
        )  # fmt: skip
        assert result is None
    assert bool(stored) != persist_fails


async def test_finish_with_no_shadow_is_a_noop() -> None:
    assert await finish_comparison(None, SETTINGS, primary_obs(), company_id=uuid4(),
                                   employee_id=uuid4(), session_id=None, liveness_score=None,
                                   frames=3) is None  # fmt: skip
