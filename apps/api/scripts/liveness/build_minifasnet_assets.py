"""Builds the face-liveness model assets (`models/liveness/minifasnet-v1/`) from pinned upstream
sources. A developer/release tool — never imported by the application, never run at boot.

Upstream: Silent-Face-Anti-Spoofing (Minivision), Apache-2.0,
https://github.com/minivision-ai/Silent-Face-Anti-Spoofing at commit `UPSTREAM_COMMIT`. Every
downloaded file is checked against the SHA-256 pinned below before it is used; a mismatch aborts.

What it does:
1. Downloads the two MiniFASNet checkpoints, the RetinaFace (Caffe) detector, the model
   definition and the licence from that exact commit.
2. Loads the checkpoints with `torch.load(..., weights_only=True)` — no pickle code execution.
3. Exports each to ONNX (opset 13, fixed 1x3x80x80 input) and checks the ONNX output against
   PyTorch on random inputs (max abs diff on logits < 1e-4) through OpenCV DNN, the runtime the
   API uses.
4. Writes MANIFEST.json (file -> sha256). The API pins the same hashes in
   `hrms/modules/attendance/liveness.py` and refuses to load anything else.

Needs (dev only, NOT application dependencies): torch, onnx, numpy, opencv-python-headless.
Byte-identical ONNX output was produced with torch 2.5.1+cpu, onnx 1.17.0, Python 3.12; other
versions can serialise differently, in which case the API's pinned hashes must be reviewed and
bumped deliberately (new model version), not edited to match.

Usage:
    python -I scripts/liveness/build_minifasnet_assets.py --out models/liveness/minifasnet-v1
"""

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

UPSTREAM_REPO = "minivision-ai/Silent-Face-Anti-Spoofing"
UPSTREAM_COMMIT = "b6d5f04ad78778917853b25c778acef6d5626d15"

#: upstream path -> sha256 (verified against a clone of UPSTREAM_COMMIT on 2026-10-15).
UPSTREAM_FILES = {
    "resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth": (
        "a5eb02e1843f19b5386b953cc4c9f011c3f985d0ee2bb9819eea9a142099bec0"
    ),
    "resources/anti_spoof_models/4_0_0_80x80_MiniFASNetV1SE.pth": (
        "84ee1d37d96894d5e82de5a57df044ef80a58be2b218b5ed7cdfd875ec2f5990"
    ),
    "resources/detection_model/deploy.prototxt": (
        "9fe2f141b4baee039ed9442da2833e216af40a6ff3e639e7b39258812bcda808"
    ),
    "resources/detection_model/Widerface-RetinaFace.caffemodel": (
        "d08338a2c207df16a9c566f767fea67fb43ba6fff76ce11e938fe3fabefb9402"
    ),
    "src/model_lib/MiniFASNet.py": (
        "e498c4ec5e1ddfaba62b941a126c19d65aa564999f3309661fe43ee8bf38acd7"
    ),
    "LICENSE": "daf94bf1dc9cc5700fe5af2c7c0cbd1836e70d509ed78fd0bebef7432edee6fb",
}

#: (checkpoint, constructor in MiniFASNet.py, output name). conv6 kernel for an 80x80 input is
#: ((80 + 15) // 16,) * 2 = (5, 5), as upstream's `get_kernel`.
MODELS = (
    ("2.7_80x80_MiniFASNetV2.pth", "MiniFASNetV2", "minifasnet_v2_scale2.7_80x80.onnx"),
    ("4_0_0_80x80_MiniFASNetV1SE.pth", "MiniFASNetV1SE", "minifasnet_v1se_scale4.0_80x80.onnx"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _download(dest_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for rel, expected in UPSTREAM_FILES.items():
        url = f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/{UPSTREAM_COMMIT}/{rel}"
        target = dest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - pinned https URL
            target.write_bytes(response.read())
        actual = _sha256(target)
        if actual != expected:
            raise SystemExit(f"checksum mismatch for {rel}: expected {expected}, got {actual}")
        paths[rel] = target
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="Use an existing checkout of UPSTREAM_COMMIT instead of downloading (still verified).",
    )
    args = parser.parse_args()

    import cv2
    import numpy as np
    import torch

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        if args.source_dir:
            src = {rel: args.source_dir / rel for rel in UPSTREAM_FILES}
            for rel, path in src.items():
                if _sha256(path) != UPSTREAM_FILES[rel]:
                    raise SystemExit(f"checksum mismatch for {rel} in --source-dir")
        else:
            src = _download(Path(tmp))

        spec = importlib.util.spec_from_file_location(
            "minifasnet_upstream", src["src/model_lib/MiniFASNet.py"]
        )
        assert spec is not None and spec.loader is not None
        arch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(arch)

        rng = np.random.default_rng(0)
        for checkpoint, ctor_name, onnx_name in MODELS:
            model = getattr(arch, ctor_name)(conv6_kernel=(5, 5))
            state = torch.load(
                src[f"resources/anti_spoof_models/{checkpoint}"],
                map_location="cpu",
                weights_only=True,
            )
            state = {k.removeprefix("module."): v for k, v in state.items()}
            model.load_state_dict(state)
            model.eval()
            target = out / onnx_name
            torch.onnx.export(
                model,
                torch.zeros(1, 3, 80, 80),
                str(target),
                input_names=["input"],
                output_names=["logits"],
                opset_version=13,
                do_constant_folding=True,
            )
            net = cv2.dnn.readNetFromONNX(str(target))
            for _ in range(8):
                # Upstream feeds raw 0..255 BGR pixels (its `to_tensor` skips the /255).
                x = rng.uniform(0, 255, size=(1, 3, 80, 80)).astype(np.float32)
                with torch.no_grad():
                    expected = model(torch.from_numpy(x)).numpy()
                net.setInput(x)
                actual = net.forward()
                diff = float(np.abs(expected - actual).max())
                if diff > 1e-4:
                    raise SystemExit(f"{onnx_name}: ONNX/PyTorch mismatch {diff}")
            print(f"{onnx_name}: exported, parity ok")

        shutil.copyfile(
            src["resources/detection_model/deploy.prototxt"], out / "retinaface_deploy.prototxt"
        )
        shutil.copyfile(
            src["resources/detection_model/Widerface-RetinaFace.caffemodel"],
            out / "retinaface_widerface.caffemodel",
        )
        shutil.copyfile(src["LICENSE"], out / "LICENSE.upstream")

    manifest = {
        "model_version": "minifasnet-v1",
        "upstream": f"https://github.com/{UPSTREAM_REPO}",
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_license": "Apache-2.0",
        "upstream_sha256": UPSTREAM_FILES,
        "build": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "opencv": cv2.__version__,
        },
        "files": {
            p.name: _sha256(p)
            for p in sorted(out.iterdir())
            if p.is_file() and p.name not in {"MANIFEST.json", "README.md"}
        },
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest["files"], indent=2))


if __name__ == "__main__":
    main()
