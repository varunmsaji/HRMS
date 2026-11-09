"""Provider-level latency / concurrency benchmark for the face providers.

    # real open-source engine (needs the `liveness` extra: OpenCV + numpy, and the model files)
    python scripts/face/provider_benchmark.py opensource --images DIR --model-dir MODELS \
        --concurrency 1,4,10 --requests 40
    # real Face++ (reads FACEPP_API_KEY/SECRET from the environment; creates ONE FaceSet from the
    # first image and deletes it afterwards; every request is a billable API call)
    python scripts/face/provider_benchmark.py facepp --images DIR --concurrency 1,4,10 --requests 40
    # self-hosted CompreFace (reads COMPREFACE_BASE_URL/API_KEY; same one-subject enroll/delete as
    # Face++, no billing). Each verify is one call per enrolled example plus a listing.
    python scripts/face/provider_benchmark.py compreface --images DIR --concurrency 1,4,10
    # NO model or network: queueing model with fixed per-call latencies. A SIMULATION - it shows
    # how a concurrency cap shapes tail latency, it says nothing about real model speed.
    python scripts/face/provider_benchmark.py simulate --service-ms 150 --cap 1 \
        --concurrency 10,25,50,100 --requests 200

`--images` must hold JPEG/PNG files of consenting participants only; nothing is stored or logged
beyond timings. Output is JSON: per concurrency level p50/p95/p99/avg/max latency (ms), error and
timeout counts, throughput. The open-source number measures embedding inference only (detector +
recognizer under `face_os_max_concurrency`), the cost every punch frame pays on the API host."""

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * p))], 1)


async def drive(
    call: Callable[[int], Awaitable[None]], concurrency: int, requests: int
) -> dict[str, object]:
    latencies: list[float] = []
    errors = timeouts = 0
    gate = asyncio.Semaphore(concurrency)

    async def one(i: int) -> None:
        nonlocal errors, timeouts
        async with gate:
            started = time.perf_counter()
            try:
                await call(i)
            except TimeoutError:
                timeouts += 1
                return
            except Exception:  # noqa: BLE001 - a benchmark counts failures, it does not stop
                errors += 1
                return
            latencies.append((time.perf_counter() - started) * 1000)

    wall = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(requests)))
    wall = time.perf_counter() - wall
    return {
        "concurrency": concurrency,
        "requests": requests,
        "ok": len(latencies),
        "errors": errors,
        "timeouts": timeouts,
        "avg_ms": round(statistics.fmean(latencies), 1) if latencies else None,
        "p50_ms": pct(latencies, 0.50) if latencies else None,
        "p95_ms": pct(latencies, 0.95) if latencies else None,
        "p99_ms": pct(latencies, 0.99) if latencies else None,
        "max_ms": round(max(latencies), 1) if latencies else None,
        "throughput_per_s": round(len(latencies) / wall, 2) if wall else None,
    }


def load_images(directory: Path) -> list[bytes]:
    files = sorted(p for p in directory.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not files:
        raise SystemExit(f"no images in {directory}")
    return [f.read_bytes() for f in files]


async def run(args: argparse.Namespace) -> list[dict[str, object]]:
    levels = [int(c) for c in args.concurrency.split(",")]
    results: list[dict[str, object]] = []
    cleanup: Callable[[], Awaitable[None]] | None = None

    if args.mode == "simulate":
        gate = asyncio.Semaphore(args.cap)

        async def call(_: int) -> None:
            async with gate:
                await asyncio.sleep(args.service_ms / 1000)

    elif args.mode == "opensource":
        from hrms.modules.attendance.opensource_face.embedding_service import SFaceEmbeddingService

        images = load_images(Path(args.images))
        service = SFaceEmbeddingService(
            Path(args.model_dir),
            detector_score_threshold=0.9,
            min_face_px=80,
            max_concurrency=args.cap,
            timeout_seconds=args.timeout,
        )
        service.warm_up()

        async def call(i: int) -> None:
            await service.embed(images[i % len(images)])

    else:
        from hrms.core.config.settings import get_settings
        from hrms.modules.attendance.face_verification import (
            FaceppFaceVerificationProvider,
            FaceVerificationProvider,
        )

        images = load_images(Path(args.images))
        provider: FaceVerificationProvider
        if args.mode == "compreface":
            from hrms.modules.attendance.compreface_face_provider import (
                CompreFaceVerificationProvider,
            )

            provider = CompreFaceVerificationProvider(get_settings())
        else:
            provider = FaceppFaceVerificationProvider(get_settings())
        person = await provider.enroll(
            label="benchmark", image=images[0], content_type="image/jpeg"
        )

        async def call(i: int) -> None:
            async with asyncio.timeout(args.timeout):
                await provider.verify(
                    person_id=person, image=images[i % len(images)], content_type="image/jpeg"
                )

        async def cleanup() -> None:
            await provider.delete_person(person_id=person)
            await provider.aclose()

    try:
        for level in levels:
            results.append(await drive(call, level, args.requests))
    finally:
        if cleanup is not None:
            await cleanup()
    return results


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("mode", choices=["opensource", "facepp", "compreface", "simulate"])
    p.add_argument("--images")
    p.add_argument("--model-dir")
    p.add_argument("--concurrency", default="1,10,25,50,100")
    p.add_argument("--requests", type=int, default=100)
    p.add_argument("--cap", type=int, default=1, help="open-source / simulated concurrency cap")
    p.add_argument("--service-ms", type=float, default=150.0, help="simulate: time per call")
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()
    if args.mode != "simulate" and not args.images:
        p.error("--images is required")
    if args.mode == "opensource" and not args.model_dir:
        p.error("--model-dir is required")
    print(json.dumps({"mode": args.mode, "results": asyncio.run(run(args))}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
