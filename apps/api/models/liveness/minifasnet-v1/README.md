# Face liveness model assets — `minifasnet-v1`

Server-side presentation-attack detection for face attendance
(`src/hrms/modules/attendance/liveness.py`). Loaded only when `FACE_LIVENESS_ENGINE=minifasnet`
and `FACE_LIVENESS_MODEL_DIR` points here. Every file is checked against the SHA-256 pinned in
`liveness.py` (`_PINNED_SHA256`) before it is read as a model; any mismatch disables face
punching (fail closed).

| File | What | SHA-256 |
| --- | --- | --- |
| `minifasnet_v2_scale2.7_80x80.onnx` | MiniFASNetV2, 2.7x face crop, 80x80 — ONNX export of upstream `2.7_80x80_MiniFASNetV2.pth` | `079399882d651cb9126de6444ca0fabce952db7d5792823ef6c4ae004132534f` |
| `minifasnet_v1se_scale4.0_80x80.onnx` | MiniFASNetV1SE, 4.0x face crop, 80x80 — ONNX export of upstream `4_0_0_80x80_MiniFASNetV1SE.pth` | `828e4476ac4561c9185c092d173105f30c51f814d93fd71a892c1b67b41e5dd9` |
| `retinaface_deploy.prototxt` | Upstream face detector definition (byte-identical) | `9fe2f141b4baee039ed9442da2833e216af40a6ff3e639e7b39258812bcda808` |
| `retinaface_widerface.caffemodel` | Upstream face detector weights (byte-identical) | `d08338a2c207df16a9c566f767fea67fb43ba6fff76ce11e938fe3fabefb9402` |
| `LICENSE.upstream` | Upstream Apache License 2.0 text | `daf94bf1dc9cc5700fe5af2c7c0cbd1836e70d509ed78fd0bebef7432edee6fb` |
| `MANIFEST.json` | Machine-readable provenance written by the build script | — |

## Provenance

- Upstream: <https://github.com/minivision-ai/Silent-Face-Anti-Spoofing> (Minivision),
  commit `b6d5f04ad78778917853b25c778acef6d5626d15` (2020-08-05), Apache-2.0.
- Upstream checkpoint hashes: `2.7_80x80_MiniFASNetV2.pth`
  `a5eb02e1…99bec0`, `4_0_0_80x80_MiniFASNetV1SE.pth` `84ee1d37…5f990` (full values in
  `MANIFEST.json` and the build script).
- Converted by `scripts/liveness/build_minifasnet_assets.py` (torch 2.5.1+cpu, onnx 1.17.0,
  Python 3.12; checkpoints loaded with `weights_only=True`). The export is byte-reproducible
  with those versions; PyTorch/ONNX/OpenCV-DNN parity was checked (max logit diff < 1e-4).
- The upstream repository does not document the training data. Its licence covers code and
  weights; whether the (undisclosed) training data imposes further terms is an open legal
  question recorded in the implementation report.

## Rebuild

```bash
python -I scripts/liveness/build_minifasnet_assets.py --out models/liveness/minifasnet-v1
```

Needs torch, onnx, numpy and opencv-python-headless in a separate, throwaway environment — they
are not application dependencies. If the output hashes differ, do not edit the pinned hashes to
match: treat it as a new model version and review it.

## Licence notice

Silent-Face-Anti-Spoofing — Copyright Minivision. Licensed under the Apache License, Version 2.0
(`LICENSE.upstream`). The ONNX files are format conversions of the upstream weights; no weights
were retrained or modified.
