"""Verify (and optionally exercise) the face-liveness model assets.

Used as a Docker build gate and for inspecting a built image:

    python scripts/liveness/verify_assets.py models/liveness/minifasnet-v1 [--infer IMAGE]

Checks every asset against the SHA-256 pinned in `hrms.modules.attendance.liveness`, loads the
models through the production engine, and with `--infer` runs one image through it. Exits non-zero
(with the reason on stderr) on any missing file, checksum mismatch, load failure or invalid
inference. Prints no image data."""

import argparse
import asyncio
import sys
from pathlib import Path

from hrms.modules.attendance.liveness import (
    _PINNED_SHA256,
    LivenessError,
    MiniFasNetLivenessEngine,
    _sha256,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("--infer", type=Path, help="run this JPEG/PNG through the engine")
    args = parser.parse_args()

    try:
        for name, expected in _PINNED_SHA256.items():
            path = args.model_dir / name
            actual = _sha256(path) if path.is_file() else "MISSING"
            print(f"{'OK  ' if actual == expected else 'FAIL'} {actual}  {name}")
        engine = MiniFasNetLivenessEngine(
            args.model_dir,
            live_threshold=0.90,
            spoof_threshold=0.50,
            min_face_px=80,
            timeout_seconds=30.0,
        )
        engine.warm_up()
        print("OK   engine loaded")
        if args.infer is not None:
            result = asyncio.run(engine.assess([args.infer.read_bytes()]))
            print(f"OK   inference: decision={result.decision} live_score={result.live_score}")
    except (LivenessError, OSError) as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
