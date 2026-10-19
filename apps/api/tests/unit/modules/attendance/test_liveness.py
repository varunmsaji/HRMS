"""`attendance/liveness.py`: score interpretation, aggregation, preprocessing geometry, frame
validation, asset verification, timeouts — and the real MiniFASNet engine on synthetic images.

What this does NOT prove: real-world accuracy against printed photos, screen replays or video
replays. That needs consented participants on real devices (see the implementation report's
evaluation plan). The real-model tests below only show the verified model loads and runs and
that faceless input never comes back LIVE."""

import asyncio
import shutil
import struct
import time
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from hrms.core.config.settings import Settings
from hrms.modules.attendance.liveness import (
    _PINNED_SHA256,
    FrameAssessment,
    LivenessError,
    LivenessImageError,
    LivenessTimeoutError,
    LivenessUnavailableError,
    MiniFasNetLivenessEngine,
    aggregate,
    check_frame_dimensions,
    classify_frame,
    detector_input_size,
    expand_box,
    get_liveness_engine,
    image_dimensions,
    unscored_frame,
)

MODEL_DIR = Path(__file__).resolve().parents[4] / "models" / "liveness" / "minifasnet-v1"
_T = {"live_threshold": 0.9, "spoof_threshold": 0.5}


def _jpeg_header(width: int, height: int, *, sof: int = 0xC0) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    frame = b"\xff" + bytes([sof]) + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\x00" * 9
    return b"\xff\xd8" + app0 + frame + b"\xff\xd9"


def _png_header(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height)


def _engine(model_dir: Path = MODEL_DIR, *, timeout: float = 10.0) -> MiniFasNetLivenessEngine:
    return MiniFasNetLivenessEngine(model_dir, min_face_px=80, timeout_seconds=timeout, **_T)


# --- score interpretation ----------------------------------------------------------------------


def test_high_real_probability_is_live() -> None:
    frame = classify_frame([0.01, 0.95, 0.04], **_T)
    assert frame == FrameAssessment("LIVE", None, Decimal("0.95"), Decimal("0.05"))


def test_live_threshold_is_inclusive() -> None:
    assert classify_frame([0.05, 0.90, 0.05], **_T).decision == "LIVE"
    assert classify_frame([0.05, 0.8999, 0.0501], **_T).decision == "INCONCLUSIVE"


def test_spoof_classes_are_summed() -> None:
    """Classes 0 and 2 are both spoof types upstream: neither alone needs to dominate."""
    frame = classify_frame([0.26, 0.48, 0.26], **_T)
    assert frame.decision == "SPOOF_SUSPECTED"
    assert frame.spoof_score == Decimal("0.52")


def test_between_thresholds_is_inconclusive_not_live() -> None:
    """Upstream's argmax rule would call this a real face; this module refuses to."""
    frame = classify_frame([0.30, 0.60, 0.10], **_T)
    assert frame.decision == "INCONCLUSIVE"
    assert frame.reason == "LOW_CONFIDENCE"


@pytest.mark.parametrize(
    "probs",
    [[0.5, 0.5], [0.2, 0.3, 0.3, 0.2], [float("nan"), 0.5, 0.5], [0.9, 0.9, 0.9], [-0.5, 1.0, 0.5]],
)
def test_malformed_model_output_is_an_error_not_a_verdict(probs: list[float]) -> None:
    with pytest.raises(LivenessError):
        classify_frame(probs, **_T)


# --- aggregation across frames -----------------------------------------------------------------


def _live(score: str) -> FrameAssessment:
    return FrameAssessment("LIVE", None, Decimal(score), Decimal("0.01"))


def test_all_live_frames_are_live_with_weakest_score() -> None:
    result = aggregate([_live("0.97"), _live("0.92"), _live("0.99")], model_version="v")
    assert result.decision == "LIVE"
    assert result.live_score == Decimal("0.92")
    assert result.best_frame_index() == 2


def test_best_frame_tie_goes_to_earliest() -> None:
    result = aggregate([_live("0.95"), _live("0.97"), _live("0.97")], model_version="v")
    assert result.best_frame_index() == 1


def test_any_spoof_frame_wins_over_inconclusive() -> None:
    spoof = classify_frame([0.1, 0.07, 0.83], **_T)
    result = aggregate([unscored_frame("NO_FACE"), _live("0.99"), spoof], model_version="v")
    assert result.decision == "SPOOF_SUSPECTED"
    assert result.live_score is None  # one frame had no score


def test_first_non_live_reason_is_reported() -> None:
    result = aggregate(
        [_live("0.99"), unscored_frame("MULTIPLE_FACES"), unscored_frame("NO_FACE")],
        model_version="v",
    )
    assert (result.decision, result.reason) == ("INCONCLUSIVE", "MULTIPLE_FACES")


def test_no_frames_is_an_error() -> None:
    with pytest.raises(LivenessError):
        aggregate([], model_version="v")


def test_audit_summary_is_image_free_metadata() -> None:
    result = aggregate([_live("0.97")], model_version="minifasnet-v1")
    assert result.audit_summary() == {
        "engine": "minifasnet-v1",
        "decision": "LIVE",
        "reason": None,
        "frames": [{"decision": "LIVE", "reason": None, "live": "0.97", "spoof": "0.01"}],
    }


# --- preprocessing geometry (upstream parity) --------------------------------------------------


def test_expand_box_centres_and_scales() -> None:
    # 100x100 face at (190, 270) in 480x640, scale 2.7 -> 270x270 around the same centre.
    assert expand_box(480, 640, (190, 270, 100, 100), 2.7) == (105, 185, 375, 455)


def test_expand_box_shifts_back_inside_the_image() -> None:
    left, top, right, bottom = expand_box(480, 640, (0, 0, 100, 100), 4.0)
    assert (left, top) == (0, 0)
    assert (right, bottom) == (400, 400)


def test_expand_box_shrinks_scale_that_cannot_fit() -> None:
    # 4x a 200px-wide face cannot fit 480px: scale clamps to (480-1)/200.
    left, top, right, bottom = expand_box(480, 640, (140, 100, 200, 200), 4.0)
    assert left == 0 and right == 479
    assert bottom - top == right - left


def test_detector_input_matches_upstream_resize() -> None:
    assert detector_input_size(480, 640) == (166, 221)
    assert detector_input_size(100, 100) is None


# --- frame validation before decode ------------------------------------------------------------


def test_image_dimensions_from_jpeg_and_png_headers() -> None:
    assert image_dimensions(_jpeg_header(480, 640)) == (480, 640)
    assert image_dimensions(_jpeg_header(720, 960, sof=0xC2)) == (720, 960)  # progressive
    assert image_dimensions(_png_header(300, 400)) == (300, 400)


@pytest.mark.parametrize(
    "data",
    [b"", b"GIF89a....", b"\xff\xd8\xff\xe0\x00", b"\xff\xd8" + b"\x00" * 64, b"\x89PNG\r\n\x1a\n"],
)
def test_unreadable_headers_are_rejected(data: bytes) -> None:
    with pytest.raises(LivenessImageError):
        image_dimensions(data)


@pytest.mark.parametrize("size", [(200, 640), (480, 239), (5000, 4000), (40000, 40000)])
def test_frame_dimension_bounds(size: tuple[int, int]) -> None:
    """Including a decompression bomb: refused from the header, before any pixel is decoded."""
    with pytest.raises(LivenessImageError):
        check_frame_dimensions(_jpeg_header(*size))


def test_frame_dimension_bounds_accept_phone_frames() -> None:
    check_frame_dimensions(_jpeg_header(480, 640))
    check_frame_dimensions(_jpeg_header(1080, 1440))


# --- configuration -----------------------------------------------------------------------------


def test_disabled_engine_is_none() -> None:
    assert get_liveness_engine(Settings(face_liveness_engine="disabled")) is None


def test_enabled_engine_requires_a_model_dir() -> None:
    with pytest.raises(ValidationError, match="face_liveness_model_dir"):
        Settings(face_liveness_engine="minifasnet", face_liveness_model_dir="")


def test_thresholds_must_not_overlap() -> None:
    with pytest.raises(ValidationError, match="must exceed 1.0"):
        Settings(face_liveness_live_threshold=0.6, face_liveness_spoof_threshold=0.3)


def test_engine_is_cached_per_configuration() -> None:
    settings = Settings(face_liveness_engine="minifasnet", face_liveness_model_dir="/nonexistent")
    assert get_liveness_engine(settings) is get_liveness_engine(settings)


# --- asset verification, timeouts (no inference needed) ----------------------------------------


async def test_missing_assets_fail_closed(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    with pytest.raises(LivenessUnavailableError, match="missing"):
        await _engine(tmp_path).assess([_jpeg_header(480, 640)])


async def test_tampered_asset_is_refused(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    if not MODEL_DIR.is_dir():
        pytest.skip("model assets not built (scripts/liveness/build_minifasnet_assets.py)")
    for name in _PINNED_SHA256:
        shutil.copyfile(MODEL_DIR / name, tmp_path / name)
    target = tmp_path / "minifasnet_v2_scale2.7_80x80.onnx"
    data = bytearray(target.read_bytes())
    data[-1] ^= 0x01
    target.write_bytes(bytes(data))

    with pytest.raises(LivenessUnavailableError, match="verification"):
        await _engine(tmp_path).assess([_jpeg_header(480, 640)])


async def test_no_frames_is_an_image_error() -> None:
    with pytest.raises(LivenessImageError):
        await _engine().assess([])


async def test_slow_inference_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(timeout=0.05)

    def slow(frames: list[bytes], deadline: float) -> list[FrameAssessment]:
        time.sleep(0.3)
        return [_live("0.99")]

    monkeypatch.setattr(engine, "_assess_sync", slow)
    with pytest.raises(LivenessTimeoutError):
        await engine.assess([_jpeg_header(480, 640)])


async def test_saturated_engine_gives_up_at_its_deadline() -> None:
    engine = _engine(timeout=0.1)
    engine._lock.acquire()
    try:
        started = time.monotonic()
        with pytest.raises(LivenessTimeoutError):
            await engine.assess([_jpeg_header(480, 640)])
        assert time.monotonic() - started < 1.0
    finally:
        engine._lock.release()


# --- the real model (needs the `liveness` extra and the built assets) --------------------------


@pytest.fixture(scope="module")
def real_engine() -> MiniFasNetLivenessEngine:
    pytest.importorskip("cv2")
    if not MODEL_DIR.is_dir():
        pytest.skip("model assets not built (scripts/liveness/build_minifasnet_assets.py)")
    engine = _engine()
    engine.warm_up()
    return engine


def _encode(image: object) -> bytes:
    import cv2

    ok, buffer = cv2.imencode(".jpg", image)
    assert ok
    return bytes(buffer)


async def test_real_engine_finds_no_face_in_blank_or_noise(
    real_engine: MiniFasNetLivenessEngine,
) -> None:
    import numpy as np

    blank = _encode(np.full((640, 480, 3), 128, dtype=np.uint8))
    noise = _encode(np.random.default_rng(1).integers(0, 255, (640, 480, 3), dtype=np.uint8))

    result = await real_engine.assess([blank, noise])

    assert result.decision == "INCONCLUSIVE"
    assert [f.reason for f in result.frames] == ["NO_FACE", "NO_FACE"]


async def test_real_engine_rejects_undecodable_frame(
    real_engine: MiniFasNetLivenessEngine,
) -> None:
    with pytest.raises(LivenessImageError):
        await real_engine.assess([_jpeg_header(480, 640)])


async def test_real_engine_serialises_concurrent_requests(
    real_engine: MiniFasNetLivenessEngine,
) -> None:
    import numpy as np

    frame = _encode(np.full((640, 480, 3), 90, dtype=np.uint8))
    results = await asyncio.gather(*[real_engine.assess([frame]) for _ in range(4)])
    assert all(r.decision == "INCONCLUSIVE" for r in results)
    assert not real_engine._lock.locked()


# --- API startup (lifespan) --------------------------------------------------------------------


async def _boot(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    from hrms import app as app_module

    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "get_engine", lambda _settings: None)

    async def _no_dispose() -> None:
        return None

    monkeypatch.setattr(app_module, "dispose_engine", _no_dispose)
    async with app_module.lifespan(app_module.FastAPI()):
        pass


async def test_boot_with_liveness_disabled_loads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    await _boot(monkeypatch, Settings(environment="development", face_liveness_engine="disabled"))


async def test_boot_refuses_enabled_liveness_with_missing_assets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings(
        environment="development",
        face_liveness_engine="minifasnet",
        face_liveness_model_dir=str(tmp_path),
    )
    with pytest.raises(LivenessUnavailableError, match="missing"):
        await _boot(monkeypatch, settings)


async def test_boot_with_enabled_liveness_and_verified_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="development",
        face_liveness_engine="minifasnet",
        face_liveness_model_dir=str(MODEL_DIR),
    )
    await _boot(monkeypatch, settings)


# --- evaluation harness metrics ----------------------------------------------------------------


def test_evaluation_rates_follow_apcer_and_bpcer_definitions() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "evaluate_captures", MODEL_DIR.parents[2] / "scripts" / "liveness" / "evaluate_captures.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    attacks = module.Tally()
    for decision in ("LIVE", "SPOOF_SUSPECTED", "SPOOF_SUSPECTED", "INCONCLUSIVE"):
        attacks.add(decision, 1.0)
    genuine = module.Tally()
    for decision in ("LIVE", "LIVE", "INCONCLUSIVE", None):
        genuine.add(decision, 1.0)

    assert module.rates("attack", attacks)["rate"] == 0.25  # 1 of 4 attacks accepted
    assert module.rates("genuine", genuine)["rate"] == 0.5  # inconclusive and error both refuse
    assert module.rates("attack", module.Tally())["rate"] is None
