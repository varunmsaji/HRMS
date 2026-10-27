"""Pinned model assets for the open-source engine (`opensource-v1`).

Both files come from OpenCV Zoo (https://github.com/opencv/opencv_zoo, Apache-2.0 for SFace, MIT
for YuNet) and are fetched by `scripts/face/fetch_opensource_assets.py`, which refuses a file
whose SHA-256 differs from the value below. The service verifies the same digests before it loads
a model, and never downloads anything itself. Changing a model means a new `MODEL_VERSION`:
stored embeddings are only comparable with embeddings of the same version.

Run `python -m hrms.modules.attendance.opensource_face.assets <dir>` to verify a directory."""

import hashlib
import sys
from pathlib import Path

MODEL_VERSION = "sface-2021dec"

DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"

#: file -> (SHA-256, source URL (Git LFS media endpoint), licence)
ASSETS: dict[str, tuple[str, str, str]] = {
    DETECTOR_FILE: (
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "MIT",
    ),
    RECOGNIZER_FILE: (
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "Apache-2.0",
    ),
}


class AssetError(Exception):
    """An asset is missing or fails its pinned checksum."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_assets(model_dir: Path) -> None:
    for name, (expected, _url, _licence) in ASSETS.items():
        path = model_dir / name
        if not path.is_file():
            raise AssetError(f"Face model asset missing: {name}")
        if sha256_file(path) != expected:
            raise AssetError(f"Face model asset failed verification: {name}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    try:
        verify_assets(target)
    except AssetError as exc:
        print(f"FAIL: {exc}")
        raise SystemExit(1) from exc
    print(f"OK: {len(ASSETS)} assets verified ({MODEL_VERSION})")
