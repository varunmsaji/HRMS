"""Server-side face liveness (presentation-attack detection) for face attendance.

Replaces the former `FaceppFaceVerificationProvider.check_liveness`, which only detected a face
and always answered LIVE. Face++ stays responsible for identity matching; this module answers a
different question — "is this frame a live face in front of the camera, or a photo/screen?" —
on our own server, so the decision never depends on the mobile client's word.

Model: Silent-Face-Anti-Spoofing (Minivision, Apache-2.0), the two-model MiniFASNet fusion
(MiniFASNetV2 on a 2.7x face crop + MiniFASNetV1SE on a 4.0x crop, both 80x80) with the
upstream RetinaFace (Caffe) detector, exported to ONNX by
`scripts/liveness/build_minifasnet_assets.py` and run with OpenCV DNN. Preprocessing replicates
the upstream reference `test.py` exactly (BGR, raw 0..255 pixels — no /255 — detector resize to
~192x192 area, `CropImage._get_new_box`, `cv2.resize` to 80x80). Every asset is checked against
the SHA-256 pinned in `_PINNED_SHA256` before it is loaded; anything else is refused.

Score interpretation (upstream semantics): each model outputs 3 logits; after softmax class 1
is "real face", classes 0 and 2 are two spoof categories (upstream does not document which
attack each one is). The two models' probabilities are averaged (upstream sums and halves).
`live_score` = P(class 1); `spoof_score` = P(class 0) + P(class 2). Upstream's own rule is
argmax == 1; this module is stricter: LIVE needs `live_score >= live_threshold`,
SPOOF_SUSPECTED needs `spoof_score >= spoof_threshold`, and everything between is INCONCLUSIVE
(rejected, user retries). The default thresholds are uncalibrated engineering defaults.

What this is NOT: it is passive, single-frame classification applied to each submitted frame.
It is not an active (challenge-response) liveness check, it is not a depth/IR check, and it
cannot prove when or with which camera a frame was captured. See the implementation report for
the threat model and known bypasses.

OpenCV/numpy are imported lazily (the `liveness` extra), so the API boots — with liveness
unavailable — when the extra is not installed."""

import asyncio
import hashlib
import math
import os
import struct
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

from hrms.core.config.settings import Settings
from hrms.core.observability.logging import get_logger, safe_log

_logger = get_logger(__name__)

MODEL_VERSION_MINIFASNET_V1 = "minifasnet-v1"

LivenessDecision = Literal["LIVE", "SPOOF_SUSPECTED", "INCONCLUSIVE"]
#: Why a frame (or the whole capture) was INCONCLUSIVE.
InconclusiveReason = Literal["NO_FACE", "MULTIPLE_FACES", "FACE_TOO_SMALL", "LOW_CONFIDENCE"]

#: Asset file -> SHA-256 for `minifasnet-v1` (see models/liveness/minifasnet-v1/MANIFEST.json).
#: The detector files are byte-identical to upstream commit b6d5f04; the ONNX files are the
#: reproducible export of upstream's .pth checkpoints. Changing a model means a new version.
_PINNED_SHA256 = {
    "minifasnet_v2_scale2.7_80x80.onnx": (
        "079399882d651cb9126de6444ca0fabce952db7d5792823ef6c4ae004132534f"
    ),
    "minifasnet_v1se_scale4.0_80x80.onnx": (
        "828e4476ac4561c9185c092d173105f30c51f814d93fd71a892c1b67b41e5dd9"
    ),
    "retinaface_deploy.prototxt": (
        "9fe2f141b4baee039ed9442da2833e216af40a6ff3e639e7b39258812bcda808"
    ),
    "retinaface_widerface.caffemodel": (
        "d08338a2c207df16a9c566f767fea67fb43ba6fff76ce11e938fe3fabefb9402"
    ),
}
#: (asset, crop scale) — the fusion members, as upstream's file names encode them.
_CLASSIFIERS = (
    ("minifasnet_v2_scale2.7_80x80.onnx", 2.7),
    ("minifasnet_v1se_scale4.0_80x80.onnx", 4.0),
)
_INPUT_SIZE = 80
#: Upstream `Detection.detector_confidence`.
_DETECTOR_CONFIDENCE = 0.6
#: Frame bounds, checked from the image header before any pixel is decoded.
_MIN_SIDE = 240
_MAX_SIDE = 4096
_OPENCV_THREADS = 2


class LivenessError(Exception):
    """Liveness could not be evaluated (the ERROR outcome). Never carries image data."""


class LivenessUnavailableError(LivenessError):
    """Engine disabled, OpenCV missing, or a model asset missing / failing its checksum."""


class LivenessTimeoutError(LivenessError):
    """Inference did not finish within the configured time (or the engine was saturated)."""


class LivenessImageError(LivenessError):
    """A frame is not a decodable JPEG/PNG within the accepted dimensions."""


@dataclass(frozen=True)
class FrameAssessment:
    decision: LivenessDecision
    reason: InconclusiveReason | None
    live_score: Decimal | None
    spoof_score: Decimal | None


@dataclass(frozen=True)
class LivenessAssessment:
    decision: LivenessDecision
    reason: InconclusiveReason | None
    #: The weakest frame's P(real); None when any frame could not be scored.
    live_score: Decimal | None
    frames: tuple[FrameAssessment, ...]
    model_version: str

    def best_frame_index(self) -> int:
        """The frame with the highest P(real) — the one sent for identity matching. Ties go to
        the earliest frame, so the choice is deterministic."""
        scores = [f.live_score if f.live_score is not None else Decimal(-1) for f in self.frames]
        return scores.index(max(scores))

    def audit_summary(self) -> dict[str, Any]:
        """Safe, image-free metadata for `face_verification_attempt.provider_response`."""
        return {
            "engine": self.model_version,
            "decision": self.decision,
            "reason": self.reason,
            "frames": [
                {
                    "decision": f.decision,
                    "reason": f.reason,
                    "live": str(f.live_score) if f.live_score is not None else None,
                    "spoof": str(f.spoof_score) if f.spoof_score is not None else None,
                }
                for f in self.frames
            ],
        }


class LivenessEngine(Protocol):
    model_version: str

    async def assess(self, frames: Sequence[bytes]) -> LivenessAssessment: ...


# --- pure helpers (no OpenCV; unit-tested directly) -------------------------------------------


def _score(value: float) -> Decimal:
    """4 fixed decimals, matching `face_verification_attempt.liveness_score` NUMERIC(5,4), so a
    fresh response and an idempotent replay (read back from the column) render identically."""
    return Decimal(f"{min(max(value, 0.0), 1.0):.4f}")


def classify_frame(
    probabilities: Sequence[float], *, live_threshold: float, spoof_threshold: float
) -> FrameAssessment:
    """Fused 3-class probabilities -> verdict, per the module docstring. Rejects anything that
    is not a finite probability vector rather than guessing."""
    if len(probabilities) != 3 or not all(
        math.isfinite(p) and -1e-6 <= p <= 1 + 1e-6 for p in probabilities
    ):
        raise LivenessError("Liveness model produced an invalid output.")
    if abs(sum(probabilities) - 1.0) > 1e-3:
        raise LivenessError("Liveness model produced an invalid output.")
    live = float(probabilities[1])
    spoof = float(probabilities[0]) + float(probabilities[2])
    if live >= live_threshold:
        decision: LivenessDecision = "LIVE"
        reason: InconclusiveReason | None = None
    elif spoof >= spoof_threshold:
        decision, reason = "SPOOF_SUSPECTED", None
    else:
        decision, reason = "INCONCLUSIVE", "LOW_CONFIDENCE"
    return FrameAssessment(decision, reason, _score(live), _score(spoof))


def unscored_frame(reason: InconclusiveReason) -> FrameAssessment:
    return FrameAssessment("INCONCLUSIVE", reason, None, None)


def aggregate(frames: Sequence[FrameAssessment], *, model_version: str) -> LivenessAssessment:
    """All frames must be LIVE. Any SPOOF_SUSPECTED frame makes the capture SPOOF_SUSPECTED
    (the more severe outcome wins over INCONCLUSIVE); otherwise the first non-live frame's
    reason is reported."""
    if not frames:
        raise LivenessError("No frames were assessed.")
    scores = [f.live_score for f in frames]
    live_score = None if any(s is None for s in scores) else min(s for s in scores if s is not None)
    if any(f.decision == "SPOOF_SUSPECTED" for f in frames):
        return LivenessAssessment("SPOOF_SUSPECTED", None, live_score, tuple(frames), model_version)
    pending = next((f for f in frames if f.decision != "LIVE"), None)
    if pending is not None:
        return LivenessAssessment(
            "INCONCLUSIVE", pending.reason, live_score, tuple(frames), model_version
        )
    return LivenessAssessment("LIVE", None, live_score, tuple(frames), model_version)


def expand_box(
    src_w: int, src_h: int, bbox: tuple[int, int, int, int], scale: float
) -> tuple[int, int, int, int]:
    """Upstream `CropImage._get_new_box`, verbatim in behaviour: grow the (x, y, w, h) face box
    by `scale` around its centre (shrinking the scale if it would not fit), then shift it back
    inside the image. Returns (left, top, right, bottom), inclusive."""
    x, y, box_w, box_h = bbox
    scale = min((src_h - 1) / box_h, min((src_w - 1) / box_w, scale))
    new_w, new_h = box_w * scale, box_h * scale
    cx, cy = box_w / 2 + x, box_h / 2 + y
    left, top = cx - new_w / 2, cy - new_h / 2
    right, bottom = cx + new_w / 2, cy + new_h / 2
    if left < 0:
        right -= left
        left = 0
    if top < 0:
        bottom -= top
        top = 0
    if right > src_w - 1:
        left -= right - src_w + 1
        right = src_w - 1
    if bottom > src_h - 1:
        top -= bottom - src_h + 1
        bottom = src_h - 1
    return int(left), int(top), int(right), int(bottom)


def detector_input_size(width: int, height: int) -> tuple[int, int] | None:
    """Upstream `Detection.get_bbox` downsizes anything of at least 192x192 area to ~192x192
    area, keeping the aspect ratio; None means "use the image as is"."""
    if width * height < 192 * 192:
        return None
    ratio = width / height
    return int(192 * math.sqrt(ratio)), int(192 / math.sqrt(ratio))


_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def image_dimensions(data: bytes) -> tuple[int, int]:
    """(width, height) from a JPEG/PNG header, without decoding pixels — so a small file that
    would decode into a huge bitmap is refused before OpenCV allocates it."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24 and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if data.startswith(b"\xff\xd8"):
        i = 2
        while i + 4 <= len(data):
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker == 0xFF:
                i += 1
                continue
            if marker in (0x01, *range(0xD0, 0xD8)):
                i += 2
                continue
            (length,) = struct.unpack(">H", data[i + 2 : i + 4])
            if marker in _JPEG_SOF:
                if i + 9 > len(data):
                    break
                height, width = struct.unpack(">HH", data[i + 5 : i + 9])
                return int(width), int(height)
            if length < 2:
                break
            i += 2 + length
    raise LivenessImageError("A frame is not a readable JPEG or PNG image.")


def check_frame_dimensions(data: bytes) -> None:
    width, height = image_dimensions(data)
    if min(width, height) < _MIN_SIDE or max(width, height) > _MAX_SIDE:
        raise LivenessImageError(
            f"Each frame must be between {_MIN_SIDE} and {_MAX_SIDE} pixels on each side."
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- MiniFASNet engine (OpenCV DNN) ------------------------------------------------------------


class MiniFasNetLivenessEngine:
    model_version = MODEL_VERSION_MINIFASNET_V1

    def __init__(
        self,
        model_dir: Path,
        *,
        live_threshold: float,
        spoof_threshold: float,
        min_face_px: int,
        timeout_seconds: float,
    ) -> None:
        self._model_dir = model_dir
        self._live_threshold = live_threshold
        self._spoof_threshold = spoof_threshold
        self._min_face_px = min_face_px
        self._timeout = timeout_seconds
        # cv2.dnn.Net is not safe for concurrent forward(); one assessment at a time per
        # engine, and a waiter gives up at its deadline instead of queueing unboundedly.
        self._lock = threading.Lock()
        self._loaded: tuple[Any, Any, list[tuple[Any, float]]] | None = None

    # Loading -------------------------------------------------------------------------------

    def _load(self) -> tuple[Any, Any, list[tuple[Any, float]]]:
        """Called with `self._lock` held. Verifies every asset before reading it as a model."""
        if self._loaded is not None:
            return self._loaded
        # Defence in depth beside `check_frame_dimensions`: OpenCV's own decode ceiling.
        os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(_MAX_SIDE * _MAX_SIDE))
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise LivenessUnavailableError("OpenCV is not installed (liveness extra).") from exc
        for name, expected in _PINNED_SHA256.items():
            path = self._model_dir / name
            if not path.is_file():
                raise LivenessUnavailableError(f"Liveness model asset missing: {name}")
            if _sha256(path) != expected:
                raise LivenessUnavailableError(f"Liveness model asset failed verification: {name}")
        try:
            cv2.setNumThreads(_OPENCV_THREADS)
            detector = cv2.dnn.readNetFromCaffe(
                str(self._model_dir / "retinaface_deploy.prototxt"),
                str(self._model_dir / "retinaface_widerface.caffemodel"),
            )
            classifiers = [
                (cv2.dnn.readNetFromONNX(str(self._model_dir / name)), scale)
                for name, scale in _CLASSIFIERS
            ]
        except cv2.error as exc:
            raise LivenessUnavailableError("Liveness model could not be loaded.") from exc
        self._loaded = (np, detector, classifiers)
        return self._loaded

    def warm_up(self) -> None:
        """Loads and verifies the assets now (raises `LivenessUnavailableError`)."""
        with self._lock:
            self._load()

    # Inference -----------------------------------------------------------------------------

    async def assess(self, frames: Sequence[bytes]) -> LivenessAssessment:
        if not frames:
            raise LivenessImageError("No frames were submitted.")
        for frame in frames:
            check_frame_dimensions(frame)
        deadline = time.monotonic() + self._timeout
        started = time.perf_counter()
        try:
            assessed = await asyncio.wait_for(
                asyncio.to_thread(self._assess_sync, list(frames), deadline), self._timeout
            )
        except TimeoutError as exc:
            raise LivenessTimeoutError("Liveness inference timed out.") from exc
        result = aggregate(assessed, model_version=self.model_version)
        safe_log(
            _logger.info,
            "face_liveness_assessed",
            engine=self.model_version,
            decision=result.decision,
            reason=result.reason,
            frames=len(frames),
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return result

    def _assess_sync(self, frames: list[bytes], deadline: float) -> list[FrameAssessment]:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._lock.acquire(timeout=remaining):
            raise LivenessTimeoutError("Liveness engine is busy.")
        try:
            np, detector, classifiers = self._load()
            out: list[FrameAssessment] = []
            for frame in frames:
                if time.monotonic() > deadline:
                    raise LivenessTimeoutError("Liveness inference timed out.")
                out.append(self._assess_frame(np, detector, classifiers, frame))
            return out
        finally:
            self._lock.release()

    def _assess_frame(
        self, np: Any, detector: Any, classifiers: list[tuple[Any, float]], frame: bytes
    ) -> FrameAssessment:
        import cv2

        image = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.ndim != 3 or image.shape[2] != 3:
            raise LivenessImageError("A frame could not be decoded.")
        height, width = int(image.shape[0]), int(image.shape[1])
        if min(width, height) < _MIN_SIDE or max(width, height) > _MAX_SIDE:
            # Re-checked after decode: EXIF orientation can swap the header's sides.
            raise LivenessImageError("A frame has unsupported dimensions.")

        small = detector_input_size(width, height)
        det_input = cv2.resize(image, small, interpolation=cv2.INTER_LINEAR) if small else image
        detector.setInput(cv2.dnn.blobFromImage(det_input, 1, mean=(104, 117, 123)), "data")
        detections = detector.forward("detection_out").reshape(-1, 7)
        confident = detections[detections[:, 2] >= _DETECTOR_CONFIDENCE]
        if len(confident) == 0:
            return unscored_frame("NO_FACE")
        if len(confident) > 1:
            return unscored_frame("MULTIPLE_FACES")
        row = confident[0]
        left, top = row[3] * width, row[4] * height
        right, bottom = row[5] * width, row[6] * height
        bbox = (int(left), int(top), int(right - left + 1), int(bottom - top + 1))
        if bbox[2] <= 1 or bbox[3] <= 1:
            return unscored_frame("NO_FACE")
        if min(bbox[2], bbox[3]) < self._min_face_px:
            return unscored_frame("FACE_TOO_SMALL")

        fused = np.zeros(3, dtype=np.float64)
        for net, scale in classifiers:
            x0, y0, x1, y1 = expand_box(width, height, bbox, scale)
            crop = cv2.resize(image[y0 : y1 + 1, x0 : x1 + 1], (_INPUT_SIZE, _INPUT_SIZE))
            net.setInput(crop.transpose(2, 0, 1)[None].astype(np.float32))
            logits = net.forward()[0].astype(np.float64)
            exp = np.exp(logits - logits.max())
            fused += exp / exp.sum()
        fused /= len(classifiers)
        return classify_frame(
            [float(p) for p in fused],
            live_threshold=self._live_threshold,
            spoof_threshold=self._spoof_threshold,
        )


_engines: dict[tuple[Any, ...], MiniFasNetLivenessEngine] = {}
_engines_lock = threading.Lock()


def get_liveness_engine(settings: Settings) -> LivenessEngine | None:
    """None when liveness is disabled. Engines are cached per configuration so the models load
    once per process, not per request."""
    if settings.face_liveness_engine != "minifasnet":
        return None
    key = (
        settings.face_liveness_model_dir,
        settings.face_liveness_live_threshold,
        settings.face_liveness_spoof_threshold,
        settings.face_liveness_min_face_px,
        settings.face_liveness_timeout_seconds,
    )
    with _engines_lock:
        engine = _engines.get(key)
        if engine is None:
            engine = MiniFasNetLivenessEngine(
                Path(settings.face_liveness_model_dir),
                live_threshold=settings.face_liveness_live_threshold,
                spoof_threshold=settings.face_liveness_spoof_threshold,
                min_face_px=settings.face_liveness_min_face_px,
                timeout_seconds=settings.face_liveness_timeout_seconds,
            )
            _engines[key] = engine
    return engine
