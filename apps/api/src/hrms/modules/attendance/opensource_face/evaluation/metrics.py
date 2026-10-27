"""Verification metrics from genuine / impostor similarity scores. Pure functions, no I/O."""

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class OperatingPoint:
    threshold: float
    far: float
    frr: float


def far_at(impostor: Sequence[float], threshold: float) -> float:
    """False acceptance rate: share of impostor trials scoring at or above the threshold."""
    return sum(s >= threshold for s in impostor) / len(impostor)


def frr_at(genuine: Sequence[float], threshold: float) -> float:
    """False rejection rate: share of genuine trials scoring below the threshold."""
    return sum(s < threshold for s in genuine) / len(genuine)


def point(genuine: Sequence[float], impostor: Sequence[float], threshold: float) -> OperatingPoint:
    return OperatingPoint(threshold, far_at(impostor, threshold), frr_at(genuine, threshold))


def equal_error_rate(genuine: Sequence[float], impostor: Sequence[float]) -> OperatingPoint:
    """The threshold where FAR and FRR are closest (reported as that point; not interpolated)."""
    candidates = sorted({*genuine, *impostor})
    best = min(
        (point(genuine, impostor, t) for t in candidates),
        key=lambda p: (abs(p.far - p.frr), p.threshold),
    )
    return best


def threshold_for_far(
    genuine: Sequence[float], impostor: Sequence[float], target_far: float
) -> OperatingPoint | None:
    """Lowest threshold whose FAR does not exceed `target_far` (lowest FRR for that bound)."""
    for t in sorted({*genuine, *impostor, max([*genuine, *impostor]) + 1e-9}):
        p = point(genuine, impostor, t)
        if p.far <= target_far:
            return p
    return None


def upper_bound_zero_events(trials: int) -> float:
    """'Rule of three': with 0 observed errors in `trials`, the 95% upper bound on the true
    rate is about 3/trials."""
    return 3.0 / trials if trials else 1.0


def percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    rank = (len(ordered) - 1) * q
    lo, hi = math.floor(rank), math.ceil(rank)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def distribution(values: Sequence[float], *, bins: int = 20) -> dict[str, object]:
    """Aggregate shape of a score list: count, mean, percentiles and a fixed-bin histogram over
    [-1, 1] (cosine range). No individual score is reported."""
    if not values:
        return {"n": 0}
    counts = [0] * bins
    for v in values:
        counts[min(bins - 1, max(0, int((v + 1.0) / 2.0 * bins)))] += 1
    return {
        "n": len(values),
        "mean": sum(values) / len(values),
        "p01": percentile(values, 0.01),
        "p05": percentile(values, 0.05),
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "histogram_bins": bins,
        "histogram_range": [-1.0, 1.0],
        "histogram_counts": counts,
    }


@dataclass(frozen=True)
class EvidenceRequirements:
    min_identities: int = 30
    min_genuine_trials: int = 300
    #: impostor trials needed to see a FAR of `target_far` at least ~10 times
    target_far: float = 1e-3
    min_attack_samples_per_type: int = 100
    #: Smallest identity count for a sub-group (condition / demographic) to be reported alone.
    min_group_identities: int = 20
    #: Largest allowed ratio between the most and least probed identity.
    max_probe_imbalance: float = 5.0


def evidence_gaps(
    *,
    identities: int,
    genuine: int,
    impostor: int,
    attack_samples: dict[str, int],
    probes_per_identity: Sequence[int] = (),
    req: EvidenceRequirements | None = None,
) -> list[str]:
    req = req or EvidenceRequirements()
    gaps: list[str] = []
    if identities < req.min_identities:
        gaps.append(f"identities {identities} < {req.min_identities}")
    if genuine < req.min_genuine_trials:
        gaps.append(f"genuine trials {genuine} < {req.min_genuine_trials}")
    needed = int(10 / req.target_far)
    if impostor < needed:
        gaps.append(
            f"impostor trials {impostor} < {needed} (needed to resolve FAR {req.target_far})"
        )
    if probes_per_identity and min(probes_per_identity) == 0:
        gaps.append("some identities have no genuine probes after enrolment")
    elif probes_per_identity and (
        max(probes_per_identity) / min(probes_per_identity) > req.max_probe_imbalance
    ):
        gaps.append(f"unbalanced probes per identity (> {req.max_probe_imbalance:g}x spread)")
    if not attack_samples:
        gaps.append("no presentation-attack samples (printed / replay / video)")
    for kind, n in sorted(attack_samples.items()):
        if n < req.min_attack_samples_per_type:
            gaps.append(f"attack samples '{kind}' {n} < {req.min_attack_samples_per_type}")
    return gaps


def verdict(gaps: Sequence[str]) -> str:
    """The only two statements the tool will make about its own numbers."""
    return (
        "INSUFFICIENT EVIDENCE"
        if gaps
        else "MINIMUM EVIDENCE MET (not a production approval: independent validation split, "
        "legal and staging gates still apply)"
    )
