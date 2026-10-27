"""Local face detection + embedding (YuNet + SFace through OpenCV DNN).

Preprocessing is the OpenCV Zoo reference: YuNet finds faces and five landmarks, SFace's
`alignCrop` warps the face to the canonical 112x112 pose, `feature` returns a 128-d embedding
that this module L2-normalises. Frames are JPEG/PNG only; their dimensions are read from the
header and bounded before any pixel is decoded.

Concurrency: OpenCV `dnn.Net` / `FaceRecognizerSF` are not safe to call concurrently, so each
inference borrows one of at most `max_concurrency` model instances (built lazily, ~40 MB each).
Admission happens on the event loop (an `asyncio.Semaphore` of `max_concurrency` plus a bounded
waiting room of `_QUEUE_FACTOR x max_concurrency`), so requests waiting for a model never occupy
threads of the default executor that liveness inference and other `to_thread` users share. A
request that cannot be admitted before its deadline, or arrives when the waiting room is full,
fails with `EmbeddingTimeoutError` instead of queueing; the work itself runs in a worker thread so
the event loop is never blocked. The slot is released on success, error and cancellation.

What this does NOT do: no quality scoring (blur, exposure, pose), no passive or active liveness
(that is `attendance/liveness.py`), and no tenant-wide search. Nothing is logged but counts,
durations and enum reasons."""

import asyncio
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from hrms.core.observability.logging import get_logger, safe_log
from hrms.modules.attendance.liveness import LivenessImageError, image_dimensions
from hrms.modules.attendance.opensource_face.assets import (
    DETECTOR_FILE,
    MODEL_VERSION,
    RECOGNIZER_FILE,
    AssetError,
    verify_assets,
)
from hrms.modules.attendance.opensource_face.similarity import (
    EMBEDDING_DIM,
    InvalidEmbeddingError,
    normalise,
)

_logger = get_logger(__name__)

_MIN_SIDE = 160
_MAX_SIDE = 4096
#: Long side the frame is shrunk to before detection (keeps latency bounded for large photos).
_WORKING_LONG_SIDE = 1280
_NMS_THRESHOLD = 0.3
_TOP_K = 10
_OPENCV_THREADS = 2
#: Requests allowed to wait for a model, as a multiple of the concurrency (beyond it: fail fast).
_QUEUE_FACTOR = 4

EmbedStatus = Literal["OK", "NO_FACE", "MULTIPLE_FACES", "FACE_TOO_SMALL"]


class EmbeddingError(Exception):
    """Embedding could not be computed (infrastructure). Never carries image data."""


class EmbeddingUnavailableError(EmbeddingError):
    """OpenCV missing, or a model asset is missing / fails its checksum / will not load."""


class EmbeddingTimeoutError(EmbeddingError):
    """Inference did not finish in time, or every model instance stayed busy."""


class EmbeddingImageError(EmbeddingError):
    """The input is not a decodable JPEG/PNG within the accepted dimensions."""


@dataclass(frozen=True)
class EmbeddingOutcome:
    status: EmbedStatus
    embedding: tuple[float, ...] | None = None


def check_dimensions(data: bytes) -> None:
    try:
        width, height = image_dimensions(data)
    except LivenessImageError as exc:
        raise EmbeddingImageError("The image is not a readable JPEG or PNG.") from exc
    if min(width, height) < _MIN_SIDE or max(width, height) > _MAX_SIDE:
        raise EmbeddingImageError(
            f"The image must be between {_MIN_SIDE} and {_MAX_SIDE} pixels on each side."
        )


class SFaceEmbeddingService:
    model_version = MODEL_VERSION

    def __init__(
        self,
        model_dir: Path,
        *,
        detector_score_threshold: float,
        min_face_px: int,
        max_concurrency: int,
        timeout_seconds: float,
    ) -> None:
        self._model_dir = model_dir
        self._score = detector_score_threshold
        self._min_face_px = min_face_px
        self._max = max_concurrency
        self._timeout = timeout_seconds
        self._idle: queue.Queue[Any] = queue.Queue()
        self._built = 0
        self._build_lock = threading.Lock()
        self._verified = False
        # Event-loop admission, created lazily per running loop (a semaphore belongs to the loop
        # it first runs on; Celery tasks use their own loop per run).
        self._loop: asyncio.AbstractEventLoop | None = None
        self._gate: asyncio.Semaphore | None = None
        self._waiting = 0

    # Loading -------------------------------------------------------------------------------

    def _build_models(self) -> Any:
        """Called with `_build_lock` held."""
        os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(_MAX_SIDE * _MAX_SIDE))
        try:
            import cv2
        except ImportError as exc:
            raise EmbeddingUnavailableError("OpenCV is not installed (liveness extra).") from exc
        if not self._verified:
            try:
                verify_assets(self._model_dir)
            except AssetError as exc:
                raise EmbeddingUnavailableError(str(exc)) from exc
            self._verified = True
        try:
            cv2.setNumThreads(_OPENCV_THREADS)
            detector = cv2.FaceDetectorYN.create(
                str(self._model_dir / DETECTOR_FILE),
                "",
                (320, 320),
                self._score,
                _NMS_THRESHOLD,
                _TOP_K,
            )
            recognizer = cv2.FaceRecognizerSF.create(str(self._model_dir / RECOGNIZER_FILE), "")
        except cv2.error as exc:
            raise EmbeddingUnavailableError("Face models could not be loaded.") from exc
        return (detector, recognizer)

    def warm_up(self) -> None:
        """Verifies the assets and loads one model instance now (raises
        `EmbeddingUnavailableError`)."""
        models = self._acquire(time.monotonic() + self._timeout)
        self._idle.put(models)

    def _acquire(self, deadline: float) -> Any:
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            pass
        with self._build_lock:
            if self._built < self._max:
                models = self._build_models()
                self._built += 1
                return models
        remaining = deadline - time.monotonic()
        try:
            return self._idle.get(timeout=max(remaining, 0.001))
        except queue.Empty as exc:
            raise EmbeddingTimeoutError("Face engine is busy.") from exc

    # Inference -----------------------------------------------------------------------------

    def _admission(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._gate is None or self._loop is not loop:
            self._loop, self._gate, self._waiting = loop, asyncio.Semaphore(self._max), 0
        return self._gate

    async def embed(self, image: bytes) -> EmbeddingOutcome:
        check_dimensions(image)
        gate = self._admission()
        if self._waiting >= self._max * _QUEUE_FACTOR:
            raise EmbeddingTimeoutError("Face engine is busy.")
        deadline = time.monotonic() + self._timeout
        started = time.perf_counter()
        self._waiting += 1
        try:
            await asyncio.wait_for(gate.acquire(), self._timeout)
        except TimeoutError as exc:
            raise EmbeddingTimeoutError("Face engine is busy.") from exc
        finally:
            self._waiting -= 1
        try:
            outcome = await asyncio.wait_for(
                asyncio.to_thread(self._embed_sync, image, deadline),
                max(deadline - time.monotonic(), 0.001),
            )
        except TimeoutError as exc:
            raise EmbeddingTimeoutError("Face embedding timed out.") from exc
        finally:
            gate.release()
        safe_log(
            _logger.info,
            "face_os_embedded",
            engine=self.model_version,
            status=outcome.status,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return outcome

    def _embed_sync(self, image: bytes, deadline: float) -> EmbeddingOutcome:
        models = self._acquire(deadline)
        try:
            if time.monotonic() > deadline:
                raise EmbeddingTimeoutError("Face embedding timed out.")
            return self._run(models, image)
        finally:
            self._idle.put(models)

    def _run(self, models: Any, data: bytes) -> EmbeddingOutcome:
        import cv2
        import numpy as np

        detector, recognizer = models
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.ndim != 3 or image.shape[2] != 3:
            raise EmbeddingImageError("The image could not be decoded.")
        height, width = int(image.shape[0]), int(image.shape[1])
        if min(width, height) < _MIN_SIDE or max(width, height) > _MAX_SIDE:
            # Re-checked after decode: EXIF orientation can swap the header's sides.
            raise EmbeddingImageError("The image has unsupported dimensions.")
        long_side = max(width, height)
        if long_side > _WORKING_LONG_SIDE:
            ratio = _WORKING_LONG_SIDE / long_side
            image = cv2.resize(
                image, (round(width * ratio), round(height * ratio)), interpolation=cv2.INTER_AREA
            )
            height, width = int(image.shape[0]), int(image.shape[1])
        try:
            detector.setInputSize((width, height))
            _, faces = detector.detect(image)
            if faces is None or len(faces) == 0:
                return EmbeddingOutcome("NO_FACE")
            # Largest first; a second face only counts when it is itself usable-sized.
            faces = sorted(faces, key=lambda f: float(f[2]) * float(f[3]), reverse=True)
            if len(faces) > 1 and min(float(faces[1][2]), float(faces[1][3])) >= self._min_face_px:
                return EmbeddingOutcome("MULTIPLE_FACES")
            face = faces[0]
            if min(float(face[2]), float(face[3])) < self._min_face_px:
                return EmbeddingOutcome("FACE_TOO_SMALL")
            aligned = recognizer.alignCrop(image, face)
            feature = recognizer.feature(aligned)
        except cv2.error as exc:
            raise EmbeddingUnavailableError("Face inference failed.") from exc
        vector = [float(v) for v in np.asarray(feature, dtype=np.float64).reshape(-1)]
        if len(vector) != EMBEDDING_DIM:
            raise EmbeddingUnavailableError("Face model produced an unexpected embedding.")
        try:
            return EmbeddingOutcome("OK", normalise(vector))
        except InvalidEmbeddingError as exc:
            raise EmbeddingUnavailableError("Face model produced an invalid embedding.") from exc
