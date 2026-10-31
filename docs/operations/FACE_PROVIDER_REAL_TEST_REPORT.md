# Face provider real test report

Stage 5A only. Recognition accuracy is not measured here.

## Stage 5A — Open-source performance benchmark

The existing benchmark was inspected and **not run**. Open-source mode requires a directory of JPEG/PNG files, and the script states those files must be consenting participants. This machine has no consented captures (`/secure/consented/captures` is absent, and `apps/api` has no face fixtures). No substitute images were used.

### Environment

| Item | Value |
|---|---|
| Hardware | Intel Core i7-13700F, 16 cores / 24 threads |
| GPU | No usable NVIDIA driver on this machine. CPU only. |
| OS | Linux 6.8.0-138-generic, x86_64 |
| Python | 3.12.12 (`apps/api/.venv/bin/python`) |
| NumPy | 2.5.2 |
| OpenCV | 4.14.0 (`opencv-python-headless` 4.14.0.94) |
| Provider | Open-source engine, YuNet + SFace (`sface-2021dec`) |
| Models | `apps/api/models/face/opensource-v1/` (checksums verified in Stage 2) |
| Concurrency setting | `face_os_max_concurrency` default **1** per process (`settings.py`, range 1–8). Not changed. The benchmark's `--cap` also defaults to 1. |

### What the existing script does

`apps/api/scripts/face/provider_benchmark.py`. Not rewritten.

| Mode | What it runs | Inputs | Database |
|---|---|---|---|
| `opensource` | `SFaceEmbeddingService.embed` after `warm_up()`. Real YuNet + SFace. Embedding inference only: detector and recognizer under `max_concurrency`. It does not call `OpenSourceFaceVerificationProvider.verify()`, so it does not time a stored-embedding comparison. | `--images` directory of JPEG/PNG. Docstring: consenting participants only. `--model-dir` required. | No |
| `facepp` | `FaceppFaceVerificationProvider` enroll, then verify. Deletes the FaceSet afterwards. Billable. | `--images`. Credentials from the environment. | No local biometric store. One remote FaceSet is created and deleted. |
| `simulate` | `asyncio.sleep` behind a semaphore. Fixed per-call latency. | No images. `--service-ms` and `--cap`. | No |

JSON goes to stdout only. The script does not write a results file or a log. Per concurrency level it reports request count, ok / error / timeout counts, avg, p50, p95, p99, max latency (ms), and throughput. It does not report minimum, warm-up time, or a split of detection vs embedding vs comparison. `warm_up()` runs before the timed loop, so those timings are steady-state calls only, and the first call is not separated. Client concurrency is `--concurrency` (default `1,10,25,50,100`). The engine cap is `--cap` (default 1), which matches the production default and was not raised.

`embed()` returns `NO_FACE` before SFace `feature()` when the detector finds no face. The script has no NO_FACE mode. A noise image would be counted as a successful iteration and would time detection-miss only, not recognition. That was not done.

### Input classification

```text
Benchmark not run.
A valid real face image is required for meaningful inference benchmarking.
No consented captures are available on this machine.
```

Not used: internet faces, production employee images, marketing images, synthetic noise, or `simulate`.

### Results

No open-source benchmark timings were collected in this stage.

| Measurement | Result |
|---|---|
| Warm-up latency | Not measured by this run |
| Iterations | Not run |
| Average / min / max / p50 / p95 / p99 | Not run |
| CPU / memory during inference | Not observed; no inference was started |

Stage 2, separately, loaded the same models through `OpenSourceFaceVerificationProvider.warm_up()` in 81 ms. That was one model load, not this benchmark, and it is not a recognition latency.

### Limitations

No recognition accuracy conclusion is possible without labelled, consented genuine and impostor test captures.

Queueing at client concurrency above 1, with the production cap of 1, was not measured. `simulate` can show how a cap shapes tail latency and says nothing about model speed. It was not run.
