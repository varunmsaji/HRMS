"""Summarise end-to-end face-attendance trial results (staging gate, docs/operations/
FACE_ATTENDANCE_STAGING_READINESS_PLAN.md §C). Outcome logs only: no image, frame, embedding or
provider body is read or written. Complements `evaluate_captures.py` (per-frame engine accuracy).

    python scripts/liveness/summarise_trials.py TRIALS.csv [--report calibration|holdout|both]
                                                [--frozen-config LABEL]

TRIALS.csv, one row per ATTEMPT (one request to the API):
  trial_id        groups the attempts of one presentation (one person trying to get one punch,
                  including retries); unique per presentation
  participant_id  pseudonymous id of the person; independence is judged per participant
  phase           punch | enrollment
  kind            genuine | attack
  attack_type     e.g. print-matte, screen-photo, screen-video (blank for genuine)
  device          device model label
  condition       free text (lighting etc.)
  split           calibration | holdout
  attempt_no      1, 2, ... within the trial; for phase=enrollment, the participant's own
                  submission number (1 = first submission)
  outcome         ACCEPTED, a server rejection decision (see REJECTIONS), LOCKED (enrollment
                  limit reached, HTTP 429), or an excluded error (PROVIDER_ERROR, LIVENESS_ERROR,
                  ABORTED = test-procedure or client fault)
  latency_ms      request-to-response time as the client saw it (integer)
  facepp_requests Face++ requests this attempt caused (from server logs/provider dashboard)

Counting rules (the numerators and denominators):
  * Excluded errors are NOT in any accept/reject denominator; they are reported on their own as
    an availability figure so excluding them cannot hide an unreliable service.
  * A rejection of any kind (INCONCLUSIVE included) counts against a genuine user, because the
    punch is refused.
  * Attack presentations are scored worst case: accepted if ANY attempt of the trial was ACCEPTED.
  * Rates for genuine users are reported per attempt AND per participant (mean of each person's
    own rate, so a participant with many attempts does not dominate). Frames or attempts of one
    participant are never treated as independent participants; the output states n_participants
    next to every rate and flags small samples.
  * The calibration and holdout splits are never merged. A participant in both splits is an error.
    Reporting holdout requires --frozen-config, which records which thresholds were frozen from
    calibration data before the holdout was looked at; this script cannot verify that, so the
    declaration is written into the output for the sign-off record.

It reports measurements. It does NOT choose thresholds and does NOT declare a pass: acceptance
targets belong to the security owner and product owner."""

import argparse
import csv
import json
import math
import random
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from statistics import median
from typing import Any

REJECTIONS = frozenset(
    {
        "SPOOF_SUSPECTED",
        "LIVENESS_INCONCLUSIVE",
        "NO_MATCH",
        "NO_FACE",
        "AMBIGUOUS_FACE",
        "IDENTITY_INCONSISTENT",
        "CAPTURE_REPLAYED",
        "CHALLENGE_REJECTED",
        "ANGLE_MISMATCH",
        "INVALID_IMAGE",
        "MULTIPLE_FACES",
    }
)
EXCLUDED = frozenset({"PROVIDER_ERROR", "LIVENESS_ERROR", "ABORTED"})
OUTCOMES = REJECTIONS | EXCLUDED | {"ACCEPTED", "LOCKED"}
COLUMNS = (
    "trial_id participant_id phase kind attack_type device condition split attempt_no outcome "
    "latency_ms facepp_requests"
).split()
#: Data-adequacy flags (informational, adjustable), NOT acceptance targets.
LOW_SAMPLE_PRESENTATIONS = 30
LOW_SAMPLE_PARTICIPANTS = 5
BOOTSTRAP_ROUNDS = 2000


class TrialsError(ValueError):
    """The input file is not usable; the message says why and never echoes row contents."""


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile; deterministic, no interpolation."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def load(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise TrialsError(f"missing columns: {', '.join(missing)}")
        rows: list[dict[str, Any]] = []
        for number, raw in enumerate(reader, start=2):
            row: dict[str, Any] = {c: (raw[c] or "").strip() for c in COLUMNS}
            problems = []
            if row["outcome"] not in OUTCOMES:
                problems.append("unknown outcome")
            if row["phase"] not in ("punch", "enrollment"):
                problems.append("phase")
            if row["kind"] not in ("genuine", "attack"):
                problems.append("kind")
            if row["split"] not in ("calibration", "holdout"):
                problems.append("split")
            if row["kind"] == "attack" and not row["attack_type"]:
                problems.append("attack_type")
            if not row["participant_id"] or not row["trial_id"]:
                problems.append("participant_id/trial_id")
            for numeric in ("attempt_no", "latency_ms", "facepp_requests"):
                try:
                    row[numeric] = int(row[numeric])
                except ValueError:
                    problems.append(numeric)
            if problems:
                raise TrialsError(f"row {number}: invalid {', '.join(problems)}")
            rows.append(row)
    if not rows:
        raise TrialsError("no rows")
    return rows


def check_split_discipline(rows: Iterable[dict[str, Any]]) -> None:
    splits: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        splits[row["participant_id"]].add(row["split"])
    leaked = sorted(p for p, s in splits.items() if len(s) > 1)
    if leaked:
        raise TrialsError(
            f"{len(leaked)} participant(s) appear in both calibration and holdout "
            "(calibration/holdout must be disjoint people)"
        )


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4) if denominator else None,
        "wilson95": wilson(numerator, denominator),
    }


def _participant_bootstrap(per_participant: dict[str, tuple[int, int]]) -> list[float] | None:
    """95% interval for the mean of per-participant rejection rates, resampling PEOPLE."""
    usable = [(r, n) for r, n in per_participant.values() if n]
    if len(usable) < 2:
        return None
    rng = random.Random(0)  # fixed seed: the same file always yields the same interval
    means = []
    for _ in range(BOOTSTRAP_ROUNDS):
        sample = [usable[rng.randrange(len(usable))] for _ in usable]
        means.append(sum(r / n for r, n in sample) / len(sample))
    means.sort()
    return [
        round(means[int(0.025 * BOOTSTRAP_ROUNDS)], 4),
        round(means[int(0.975 * BOOTSTRAP_ROUNDS)], 4),
    ]


def _latency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(r["latency_ms"]) for r in rows]
    return {
        "n": len(values),
        "median_ms": median(values) if values else None,
        "p95_ms": percentile(values, 0.95),
    }


def _requests(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    return {"n": n, "mean": round(sum(r["facepp_requests"] for r in rows) / n, 2) if n else None}


def summarise_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    punch = [r for r in rows if r["phase"] == "punch"]
    out: dict[str, Any] = {
        "attempts": len(rows),
        "participants": len({r["participant_id"] for r in rows}),
    }

    # --- genuine punches -----------------------------------------------------------------
    genuine = [r for r in punch if r["kind"] == "genuine"]
    valid = [r for r in genuine if r["outcome"] not in EXCLUDED]
    rejected = [r for r in valid if r["outcome"] in REJECTIONS]
    per_person: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in valid:
        per_person[r["participant_id"]][1] += 1
        per_person[r["participant_id"]][0] += r["outcome"] in REJECTIONS
    person_rates = {p: (v[0], v[1]) for p, v in per_person.items()}
    trials: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in valid:
        trials[r["trial_id"]].append(r)
    first_ok = sum(
        1 for t in trials.values() if min(t, key=lambda r: r["attempt_no"])["outcome"] == "ACCEPTED"
    )
    eventually = sum(1 for t in trials.values() if any(r["outcome"] == "ACCEPTED" for r in t))
    out["genuine_punch"] = {
        "participants": len(person_rates),
        "false_rejection_per_attempt": _rate(len(rejected), len(valid)),
        "false_rejection_per_participant_mean": (
            round(sum(r / n for r, n in person_rates.values()) / len(person_rates), 4)
            if person_rates
            else None
        ),
        "false_rejection_per_participant_bootstrap95": _participant_bootstrap(person_rates),
        "participants_with_any_rejection": sum(1 for r, _ in person_rates.values() if r),
        "presentations": len(trials),
        "accepted_first_attempt": _rate(first_ok, len(trials)),
        "accepted_eventually": _rate(eventually, len(trials)),
        "rejections_by_decision": dict(sorted(_count(r["outcome"] for r in rejected).items())),
        "low_sample": len(person_rates) < LOW_SAMPLE_PARTICIPANTS,
    }

    # --- attacks: worst case per presentation ---------------------------------------------
    attacks: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in punch:
        if r["kind"] == "attack" and r["outcome"] not in EXCLUDED:
            attacks[(r["attack_type"], r["device"])][r["trial_id"]].append(r)
    attack_out = []
    for (attack_type, device), by_trial in sorted(attacks.items()):
        accepted = sum(1 for t in by_trial.values() if any(r["outcome"] == "ACCEPTED" for r in t))
        people = {r["participant_id"] for t in by_trial.values() for r in t}
        entry = {"attack_type": attack_type, "device": device, "participants": len(people)}
        entry.update(_rate(accepted, len(by_trial)))
        entry["low_sample"] = (
            len(by_trial) < LOW_SAMPLE_PRESENTATIONS or len(people) < LOW_SAMPLE_PARTICIPANTS
        )
        attack_out.append(entry)
    out["attack_acceptance_by_type_and_device"] = attack_out

    # --- timing, cost, availability -------------------------------------------------------
    scored = [r for r in punch if r["outcome"] not in EXCLUDED and r["outcome"] != "LOCKED"]
    ok = [r for r in scored if r["outcome"] == "ACCEPTED"]
    bad = [r for r in scored if r["outcome"] in REJECTIONS]
    out["latency_accepted"] = _latency(ok)
    out["latency_rejected"] = _latency(bad)
    out["facepp_requests_per_accepted_attempt"] = _requests(ok)
    out["facepp_requests_per_rejected_attempt"] = _requests(bad)
    errors = [r for r in punch if r["outcome"] in EXCLUDED]
    out["excluded_errors"] = {
        "by_outcome": dict(sorted(_count(r["outcome"] for r in errors).items())),
        "provider_error_rate": _rate(
            sum(1 for r in punch if r["outcome"] == "PROVIDER_ERROR"), len(punch)
        ),
        "excluded_share_of_all_punch_attempts": _rate(len(errors), len(punch)),
    }

    # --- enrollment -----------------------------------------------------------------------
    enrol = [r for r in rows if r["phase"] == "enrollment"]
    by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in enrol:
        by_person[r["participant_id"]].append(r)
    # A participant whose every submission hit an excluded error has no scored outcome yet and is
    # left out of the denominators (but still counted in "participants").
    counted = {
        p: scored_rows
        for p, rs in by_person.items()
        if (scored_rows := [r for r in rs if r["outcome"] not in EXCLUDED])
    }
    ever = sum(1 for rs in counted.values() if any(r["outcome"] == "ACCEPTED" for r in rs))
    first = sum(
        1
        for rs in counted.values()
        if rs and min(rs, key=lambda r: r["attempt_no"])["outcome"] == "ACCEPTED"
    )
    out["enrollment"] = {
        "participants": len(by_person),
        "enrolled_first_submission": _rate(first, len(counted)),
        "enrolled_eventually": _rate(ever, len(counted)),
        "attempts_exhausted_participants": sum(
            1 for rs in by_person.values() if any(r["outcome"] == "LOCKED" for r in rs)
        ),
        "rejections_by_decision": dict(
            sorted(_count(r["outcome"] for r in enrol if r["outcome"] in REJECTIONS).items())
        ),
    }
    return out


def _count(items: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[item] += 1
    return counts


def build_report(
    rows: list[dict[str, Any]], *, report: str, frozen_config: str | None
) -> dict[str, Any]:
    check_split_discipline(rows)
    wanted = ["calibration", "holdout"] if report == "both" else [report]
    if "holdout" in wanted and not frozen_config:
        raise TrialsError(
            "reporting holdout requires --frozen-config LABEL: state which thresholds were fixed "
            "from calibration data before the holdout was examined"
        )
    result: dict[str, Any] = {
        "note": "Measurements only; no pass/fail. Acceptance targets are set by the security and "
        "product owners. Splits are never merged.",
        "frozen_config": frozen_config,
    }
    for split in wanted:
        result[split] = summarise_split([r for r in rows if r["split"] == split])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("trials", type=Path)
    parser.add_argument(
        "--report", choices=["calibration", "holdout", "both"], default="calibration"
    )
    parser.add_argument("--frozen-config", help="required to report the holdout split")
    args = parser.parse_args(argv)
    try:
        report = build_report(
            load(args.trials), report=args.report, frozen_config=args.frozen_config
        )
    except (TrialsError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
