# Third-party model notices (opensource-v1)

These notices accompany the model files provisioned by `scripts/face/fetch_opensource_assets.py`.
The model files themselves are not stored in git.

| File | Component | Licence text | Source |
|---|---|---|---|
| `face_detection_yunet_2023mar.onnx` | YuNet face detector, (c) 2020 Shiqi Yu | `LICENSES/YuNet-MIT.txt` | https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet (weights from ShiqiYu/libfacedetection.train @ a61a428) |
| `face_recognition_sface_2021dec.onnx` | SFace (MobileFaceNet, SFace loss), via OpenCV Zoo | `LICENSES/SFace-Apache-2.0.txt` | https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface (original: https://github.com/zhongyy/SFace) |

The weights are used unmodified. **Having a licence text here is not a legal clearance:** the training
data of both models is research-restricted or unspecified, and commercial use is blocked pending
counsel (docs/audits/OPEN_SOURCE_FACE_ATTENDANCE_AUDIT.md section 10).
