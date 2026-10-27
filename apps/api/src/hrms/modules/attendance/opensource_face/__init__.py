"""Open-source (local-inference) face-verification engine for face attendance.

A second implementation of `face_verification.FaceVerificationProvider`, selected with
`FACE_VERIFICATION_PROVIDER=opensource` (+ `FACE_OS_ENABLED=true`). It shares nothing with the
Face++ adapter except that port: recognition = YuNet detection + SFace embeddings (OpenCV DNN,
ONNX), liveness stays the existing server-side MiniFASNet engine (`attendance/liveness.py`),
which was never coupled to Face++. Nothing here calls an external service.

Modules: `similarity` (pure maths), `assets` (pinned checksums), `embedding_service`
(bounded local inference), `store` (encrypted embedding persistence), `engine` (the provider)."""
