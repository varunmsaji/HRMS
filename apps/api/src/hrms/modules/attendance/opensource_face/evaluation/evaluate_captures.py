"""Evaluate the open-source engine on a labelled capture set. Reproducible, local, aggregate-only.

    python -m hrms.modules.attendance.opensource_face.evaluation.evaluate_captures \\
        --captures /secure/path/captures --model-dir models/face/opensource-v1 \\
        --thresholds 0.363,0.45,0.55 --enroll-samples 3 \\
        [--liveness-dir models/liveness/minifasnet-v1]

Capture layout (consented, access-controlled data - NEVER inside the repository):

    <captures>/<identity>/<condition>/<image>.jpg        genuine captures; <condition> is a free
                                                         label (indoor, low_light, glasses, ...)
    <captures>/_attacks/<attack_type>/<image>.jpg        presentation attacks (print, replay,
                                                         video_frame, ...) - optional

For every identity the first `--enroll-samples` images (by name) enroll; the rest are genuine
probes. Impostor trials are each identity's enrolment set against every other identity's probes.
Output is JSON on stdout: counts, FAR/FRR per threshold, EER, TAR at target FARs, per-condition
FRR, latency percentiles, peak RSS, and `evidence_gaps` - the reasons the numbers must not be
used to approve a production threshold. It never prints a path, a name or an embedding."""

import argparse
import asyncio
import json
import resource
import time
from collections import defaultdict
from pathlib import Path

from hrms.modules.attendance.opensource_face.assets import ASSETS, MODEL_VERSION, sha256_file
from hrms.modules.attendance.opensource_face.embedding_service import (
    EmbeddingError,
    SFaceEmbeddingService,
)
from hrms.modules.attendance.opensource_face.evaluation.metrics import (
    EvidenceRequirements,
    distribution,
    equal_error_rate,
    evidence_gaps,
    percentile,
    point,
    threshold_for_far,
    upper_bound_zero_events,
    verdict,
)
from hrms.modules.attendance.opensource_face.similarity import best_similarity

_EXT = {".jpg", ".jpeg", ".png"}
_TARGET_FARS = (1e-2, 1e-3)


def _images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in _EXT)


async def evaluate(args: argparse.Namespace) -> dict[str, object]:
    service = SFaceEmbeddingService(
        Path(args.model_dir),
        detector_score_threshold=args.detector_score,
        min_face_px=args.min_face_px,
        max_concurrency=1,
        timeout_seconds=60.0,
    )
    service.warm_up()
    latencies_ms: list[float] = []
    excluded: dict[str, int] = defaultdict(int)

    async def embed(path: Path) -> tuple[float, ...] | None:
        started = time.perf_counter()
        try:
            outcome = await service.embed(path.read_bytes())
        except EmbeddingError:
            excluded["error"] += 1
            return None
        latencies_ms.append((time.perf_counter() - started) * 1000)
        if outcome.status != "OK" or outcome.embedding is None:
            excluded[outcome.status.lower()] += 1
            return None
        return outcome.embedding

    root = Path(args.captures)
    enrolled: dict[str, list[tuple[float, ...]]] = {}
    probes: dict[str, list[tuple[str, tuple[float, ...]]]] = {}
    for ident in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        files = _images(ident)
        refs = [e for f in files[: args.enroll_samples] if (e := await embed(f)) is not None]
        if not refs:
            excluded["identity_not_enrollable"] += 1
            continue
        enrolled[ident.name] = refs
        probes[ident.name] = [
            (f.parent.name, e) for f in files[args.enroll_samples :] if (e := await embed(f))
        ]

    genuine: list[float] = []
    impostor: list[float] = []
    by_condition: dict[str, list[float]] = defaultdict(list)
    for name, refs in enrolled.items():
        for condition, emb in probes[name]:
            score = best_similarity(emb, refs)
            genuine.append(score)
            by_condition[condition].append(score)
        for other, others in probes.items():
            if other != name:
                impostor.extend(best_similarity(emb, refs) for _, emb in others)

    report: dict[str, object] = {
        "tool": "opensource_face.evaluation v2",
        "model": service.model_version,
        "settings": {
            "detector_score_threshold": args.detector_score,
            "min_face_px": args.min_face_px,
            "enroll_samples": args.enroll_samples,
            "report_threshold": args.report_threshold,
            "thresholds": args.thresholds,
            "max_concurrency": 1,
            "similarity": "cosine, L2-normalised 128-d embeddings, best of enrolled samples",
            "preprocessing": "YuNet detect, SFace alignCrop 112x112 + feature; long side <= 1280",
        },
        "provenance": {
            "model_version": MODEL_VERSION,
            "asset_sha256": {n: sha256_file(Path(args.model_dir) / n) for n in sorted(ASSETS)},
            "opencv": __import__("cv2").__version__,
            "dataset_note": "dataset contents are not inspected for consent or provenance",
        },
        "identities": len(enrolled),
        "genuine_trials": len(genuine),
        "impostor_trials": len(impostor),
        "excluded_images": dict(excluded),
    }
    attack_counts: dict[str, int] = {}
    if genuine and impostor:
        report["operating_points"] = {
            f"{t:g}": vars(point(genuine, impostor, t))
            for t in (float(x) for x in args.thresholds.split(","))
        }
        report["score_distributions"] = {
            "genuine": distribution(genuine),
            "impostor": distribution(impostor),
        }
        report["equal_error_rate"] = vars(equal_error_rate(genuine, impostor))
        report["tar_at_far"] = {
            f"{far:g}": (
                None
                if (p := threshold_for_far(genuine, impostor, far)) is None
                else {"threshold": p.threshold, "tar": 1 - p.frr, "far": p.far}
            )
            for far in _TARGET_FARS
        }
        report["far_zero_event_upper_bound_95"] = upper_bound_zero_events(len(impostor))
        report["frr_by_condition_at_threshold"] = {
            cond: {
                "trials": len(scores),
                "frr": point(scores, impostor, args.report_threshold).frr,
            }
            for cond, scores in sorted(by_condition.items())
        }
    if args.liveness_dir:
        report["liveness"] = await _liveness(Path(args.liveness_dir), root, attack_counts)
    report["latency_ms"] = {
        "p50": percentile(latencies_ms, 0.5),
        "p95": percentile(latencies_ms, 0.95),
        "p99": percentile(latencies_ms, 0.99),
        "n": len(latencies_ms),
    }
    report["peak_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    report["evidence_gaps"] = evidence_gaps(
        identities=len(enrolled),
        genuine=len(genuine),
        impostor=len(impostor),
        attack_samples=attack_counts,
        probes_per_identity=[len(v) for v in probes.values()],
    )
    report["verdict"] = verdict(report["evidence_gaps"])  # type: ignore[arg-type]
    report["demographic_breakdown"] = _groups(root, probes, enrolled, args)
    return report


def _groups(
    root: Path,
    probes: dict[str, list[tuple[str, tuple[float, ...]]]],
    enrolled: dict[str, list[tuple[float, ...]]],
    args: argparse.Namespace,
) -> object:
    """Per-group FRR / FAR from an OPTIONAL `<captures>/_meta/groups.json` ({identity: label}),
    supplied only where collecting such labels is lawful and consented. A group with fewer than
    `min_group_identities` identities is suppressed (INSUFFICIENT EVIDENCE) - also a privacy
    measure, so small cohorts cannot be singled out. Without the file nothing is computed."""
    meta = root / "_meta" / "groups.json"
    if not meta.is_file():
        return "not computed: no _meta/groups.json supplied (collect only where lawful + consented)"
    labels: dict[str, str] = json.loads(meta.read_text())
    minimum = EvidenceRequirements().min_group_identities
    out: dict[str, object] = {}
    for group in sorted({labels[i] for i in enrolled if i in labels}):
        members = [i for i in enrolled if labels.get(i) == group]
        if len(members) < minimum:
            out[group] = f"INSUFFICIENT EVIDENCE: {len(members)} identities < {minimum}"
            continue
        gen = [best_similarity(e, enrolled[i]) for i in members for _, e in probes[i]]
        imp = [
            best_similarity(e, enrolled[i])
            for i in members
            for o, ps in probes.items()
            if o != i and labels.get(o) == group
            for _, e in ps
        ]
        if not gen or not imp:
            out[group] = "INSUFFICIENT EVIDENCE: no trials"
            continue
        p = point(gen, imp, args.report_threshold)
        out[group] = {
            "identities": len(members),
            "genuine_trials": len(gen),
            "impostor_trials": len(imp),
            "frr": p.frr,
            "far": p.far,
        }
    return out


async def _liveness(
    model_dir: Path, root: Path, attack_counts: dict[str, int]
) -> dict[str, object]:
    """APCER (attacks accepted as LIVE) per attack type and BPCER (genuine rejected) using the
    production MiniFASNet engine and its configured thresholds."""
    from hrms.core.config.settings import get_settings
    from hrms.modules.attendance.liveness import MiniFasNetLivenessEngine

    s = get_settings()
    engine = MiniFasNetLivenessEngine(
        model_dir,
        live_threshold=s.face_liveness_live_threshold,
        spoof_threshold=s.face_liveness_spoof_threshold,
        min_face_px=s.face_liveness_min_face_px,
        timeout_seconds=s.face_liveness_timeout_seconds,
    )

    errors = {"unscorable": 0}

    async def live_rate(files: list[Path]) -> tuple[int, int]:
        live = scored = 0
        for f in files:
            try:
                result = await engine.assess([f.read_bytes()])
            except Exception:  # noqa: BLE001 - an unreadable image is excluded, but COUNTED
                errors["unscorable"] += 1
                continue
            scored += 1
            live += result.decision == "LIVE"
        return live, scored

    out: dict[str, object] = {
        "engine": engine.model_version,
        "thresholds": {
            "live": s.face_liveness_live_threshold,
            "spoof": s.face_liveness_spoof_threshold,
        },
    }
    genuine_files = [
        f for d in root.iterdir() if d.is_dir() and not d.name.startswith("_") for f in _images(d)
    ]
    live, scored = await live_rate(genuine_files)
    out["bpcer"] = {"genuine_scored": scored, "rejected": scored - live}
    attacks = root / "_attacks"
    per_type: dict[str, object] = {}
    if attacks.is_dir():
        for kind in sorted(p for p in attacks.iterdir() if p.is_dir()):
            live, scored = await live_rate(_images(kind))
            attack_counts[kind.name] = scored
            per_type[kind.name] = {
                "scored": scored,
                "accepted_as_live": live,
                "apcer": (live / scored) if scored else None,
            }
    out["apcer_by_attack_type"] = per_type
    out["excluded_unscorable_images"] = errors["unscorable"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--captures", required=True)
    parser.add_argument("--model-dir", default="models/face/opensource-v1")
    parser.add_argument("--liveness-dir", default="")
    parser.add_argument("--thresholds", default="0.363,0.45,0.55")
    parser.add_argument("--report-threshold", type=float, default=0.45)
    parser.add_argument("--enroll-samples", type=int, default=3)
    parser.add_argument("--detector-score", type=float, default=0.9)
    parser.add_argument("--min-face-px", type=int, default=80)
    print(json.dumps(asyncio.run(evaluate(parser.parse_args())), indent=2, default=str))


if __name__ == "__main__":
    main()
