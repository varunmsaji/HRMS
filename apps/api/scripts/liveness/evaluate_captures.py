"""Measure the liveness engine on a labelled, consented capture set (staging gate B-21).

    python scripts/liveness/evaluate_captures.py MANIFEST.csv MODEL_DIR [--live-threshold 0.90]

MANIFEST.csv columns: `path` (relative to the manifest), `label` (`genuine` | `attack`),
`category` (free text, e.g. `genuine-dim-indoor`, `attack-print-matte`, `attack-screen-replay`),
`device` (free text). One row per frame; the engine is run single-frame, like one of the three
frames of a punch.

Output is aggregate only — counts and rates per category and device, timing — never an image or a
per-person record. The images stay outside the repository. This reports measurements; it does NOT
choose thresholds or declare a pass: product, security and HR decide the acceptable APCER/BPCER.

APCER = attacks classified LIVE / attacks.  BPCER = genuine not classified LIVE / genuine
(INCONCLUSIVE counts as a rejection, because the punch is refused)."""

import argparse
import asyncio
import csv
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from hrms.modules.attendance.liveness import (
    LivenessError,
    MiniFasNetLivenessEngine,
)


@dataclass
class Tally:
    live: int = 0
    spoof: int = 0
    inconclusive: int = 0
    errors: int = 0
    millis: list[float] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.live + self.spoof + self.inconclusive + self.errors

    def add(self, decision: str | None, millis: float) -> None:
        if decision == "LIVE":
            self.live += 1
        elif decision == "SPOOF_SUSPECTED":
            self.spoof += 1
        elif decision == "INCONCLUSIVE":
            self.inconclusive += 1
        else:
            self.errors += 1
        self.millis.append(millis)


def rates(label: str, tally: Tally) -> dict[str, float | None]:
    """`attack`: share accepted as LIVE (APCER). `genuine`: share not accepted (BPCER)."""
    if tally.total == 0:
        return {"rate": None}
    rate = tally.live / tally.total if label == "attack" else 1 - tally.live / tally.total
    return {"rate": rate}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


async def evaluate(
    rows: list[dict[str, str]], base: Path, engine: MiniFasNetLivenessEngine
) -> dict[tuple[str, str, str], Tally]:
    tallies: dict[tuple[str, str, str], Tally] = defaultdict(Tally)
    for row in rows:
        data = (base / row["path"]).read_bytes()
        started = time.perf_counter()
        try:
            decision: str | None = (await engine.assess([data])).decision
        except LivenessError:
            decision = None
        tallies[(row["label"], row["category"], row["device"])].add(
            decision, (time.perf_counter() - started) * 1000
        )
    return tallies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("--live-threshold", type=float, default=0.90)
    parser.add_argument("--spoof-threshold", type=float, default=0.50)
    args = parser.parse_args()

    with args.manifest.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    bad = [r for r in rows if r.get("label") not in {"genuine", "attack"}]
    if not rows or bad:
        print("FAIL manifest is empty or has a label other than genuine/attack", file=sys.stderr)
        return 2
    engine = MiniFasNetLivenessEngine(
        args.model_dir,
        live_threshold=args.live_threshold,
        spoof_threshold=args.spoof_threshold,
        min_face_px=80,
        timeout_seconds=30.0,
    )
    tallies = asyncio.run(evaluate(rows, args.manifest.parent, engine))
    print(f"live_threshold={args.live_threshold} spoof_threshold={args.spoof_threshold}")
    print("label,category,device,n,live,spoof,inconclusive,error,rate,p50_ms,p95_ms")
    for (label, category, device), t in sorted(tallies.items()):
        rate = rates(label, t)["rate"]
        p50, p95 = percentile(t.millis, 0.5), percentile(t.millis, 0.95)
        print(
            f"{label},{category},{device},{t.total},{t.live},{t.spoof},{t.inconclusive},"
            f"{t.errors},{'' if rate is None else f'{rate:.4f}'},"
            f"{'' if p50 is None else f'{p50:.1f}'},{'' if p95 is None else f'{p95:.1f}'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
