"""`scripts/liveness/summarise_trials.py` — the staging-evaluation metric definitions. Synthetic
outcome rows only; no image, frame or provider data exists in these tests or in the tool."""

import csv
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "liveness" / "summarise_trials.py"
_spec = importlib.util.spec_from_file_location("summarise_trials", SCRIPT)
assert _spec is not None and _spec.loader is not None
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)  # type: ignore[union-attr]


def row(**kw: Any) -> dict[str, Any]:
    base = {
        "trial_id": "t",
        "participant_id": "p1",
        "phase": "punch",
        "kind": "genuine",
        "attack_type": "",
        "device": "phoneA",
        "condition": "bright",
        "split": "calibration",
        "attempt_no": 1,
        "outcome": "ACCEPTED",
        "latency_ms": 1000,
        "facepp_requests": 6,
    }
    return {**base, **kw}


def write(path: Path, rows: list[dict[str, Any]]) -> Path:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=st.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def split(rows: list[dict[str, Any]], name: str = "calibration") -> dict[str, Any]:
    return st.summarise_split([r for r in rows if r["split"] == name])


def test_genuine_rates_are_per_attempt_and_per_participant() -> None:
    rows = [
        # p1: 4 attempts, 1 rejected (0.25); p2: 1 of 1 rejected (1.0) -> 2/5 attempts, mean 0.625
        row(trial_id="a", attempt_no=1, outcome="LIVENESS_INCONCLUSIVE"),
        row(trial_id="a", attempt_no=2),
        row(trial_id="b"),
        row(trial_id="c"),
        row(trial_id="d", participant_id="p2", outcome="NO_MATCH"),
    ]
    g = split(rows)["genuine_punch"]
    assert (
        g["false_rejection_per_attempt"]["numerator"],
        g["false_rejection_per_attempt"]["denominator"],
    ) == (2, 5)
    assert g["false_rejection_per_participant_mean"] == pytest.approx(0.625)
    assert g["participants"] == 2 and g["participants_with_any_rejection"] == 2
    # Presentations: a (rejected then accepted), b, c, d  -> first attempt 2/4... a fails first
    assert (
        g["accepted_first_attempt"]["numerator"],
        g["accepted_first_attempt"]["denominator"],
    ) == (2, 4)
    assert (g["accepted_eventually"]["numerator"], g["accepted_eventually"]["denominator"]) == (
        3,
        4,
    )
    assert g["rejections_by_decision"] == {"LIVENESS_INCONCLUSIVE": 1, "NO_MATCH": 1}


def test_errors_are_excluded_from_rates_but_reported_as_availability() -> None:
    rows = [
        row(trial_id="a"),
        row(trial_id="b", outcome="PROVIDER_ERROR"),
        row(trial_id="c", outcome="ABORTED"),
    ]
    out = split(rows)
    assert out["genuine_punch"]["false_rejection_per_attempt"]["denominator"] == 1
    assert out["excluded_errors"]["by_outcome"] == {"ABORTED": 1, "PROVIDER_ERROR": 1}
    assert out["excluded_errors"]["provider_error_rate"]["numerator"] == 1
    assert out["excluded_errors"]["excluded_share_of_all_punch_attempts"]["denominator"] == 3


def test_attack_is_scored_worst_case_per_presentation() -> None:
    rows = [
        # trial x: rejected twice then accepted on the 3rd try -> the attack succeeded
        row(
            trial_id="x",
            kind="attack",
            attack_type="print",
            outcome="SPOOF_SUSPECTED",
            attempt_no=1,
        ),
        row(
            trial_id="x",
            kind="attack",
            attack_type="print",
            outcome="LIVENESS_INCONCLUSIVE",
            attempt_no=2,
        ),
        row(trial_id="x", kind="attack", attack_type="print", outcome="ACCEPTED", attempt_no=3),
        row(trial_id="y", kind="attack", attack_type="print", outcome="SPOOF_SUSPECTED"),
        row(
            trial_id="z",
            kind="attack",
            attack_type="screen",
            device="phoneB",
            outcome="IDENTITY_INCONSISTENT",
        ),
    ]
    by_key = {
        (a["attack_type"], a["device"]): a
        for a in split(rows)["attack_acceptance_by_type_and_device"]
    }
    assert (by_key["print", "phoneA"]["numerator"], by_key["print", "phoneA"]["denominator"]) == (
        1,
        2,
    )
    assert by_key["screen", "phoneB"]["numerator"] == 0
    assert by_key["print", "phoneA"]["low_sample"] is True  # tiny samples are flagged, not hidden
    assert by_key["print", "phoneA"]["wilson95"][1] > 0.5  # the interval is honest about n=2


def test_latency_and_request_cost_use_nearest_rank_percentiles() -> None:
    rows = [row(trial_id=str(i), latency_ms=100 * (i + 1), facepp_requests=6) for i in range(20)]
    rows.append(row(trial_id="r", outcome="NO_MATCH", latency_ms=400, facepp_requests=2))
    out = split(rows)
    assert out["latency_accepted"]["median_ms"] == 1050
    assert out["latency_accepted"]["p95_ms"] == 1900
    assert out["facepp_requests_per_accepted_attempt"]["mean"] == 6.0
    assert out["facepp_requests_per_rejected_attempt"]["mean"] == 2.0


def test_enrollment_metrics_count_exhaustion_and_exclude_errors() -> None:
    e = {"phase": "enrollment"}
    rows = [
        row(participant_id="e1", trial_id="e1a", outcome="ACCEPTED", **e),
        row(participant_id="e2", trial_id="e2a", outcome="ANGLE_MISMATCH", **e),
        row(participant_id="e2", trial_id="e2b", attempt_no=2, outcome="ACCEPTED", **e),
        row(participant_id="e3", trial_id="e3a", outcome="SPOOF_SUSPECTED", **e),
        row(participant_id="e3", trial_id="e3b", attempt_no=2, outcome="LOCKED", **e),
        row(participant_id="e4", trial_id="e4a", outcome="PROVIDER_ERROR", **e),
    ]
    out = split(rows)["enrollment"]
    assert out["participants"] == 4
    assert (
        out["enrolled_first_submission"]["numerator"],
        out["enrolled_first_submission"]["denominator"],
    ) == (1, 3)
    assert out["enrolled_eventually"]["numerator"] == 2
    assert out["attempts_exhausted_participants"] == 1


def test_bootstrap_is_deterministic_and_resamples_people() -> None:
    rows = [
        row(
            trial_id=f"{p}{i}",
            participant_id=p,
            outcome="NO_MATCH" if i == 0 and p < "p5" else "ACCEPTED",
        )
        for p in ("p1", "p2", "p3", "p4", "p5", "p6")
        for i in range(3)
    ]
    first = split(rows)["genuine_punch"]["false_rejection_per_participant_bootstrap95"]
    assert first == split(rows)["genuine_punch"]["false_rejection_per_participant_bootstrap95"]
    assert first is not None and first[0] <= 4 / 18 * 1.5 and first[0] < first[1]


def test_participants_may_not_straddle_calibration_and_holdout(tmp_path: Path) -> None:
    path = write(tmp_path / "t.csv", [row(), row(trial_id="u", split="holdout")])
    with pytest.raises(st.TrialsError, match="both calibration and holdout"):
        st.build_report(st.load(path), report="calibration", frozen_config=None)


def test_holdout_requires_a_declared_frozen_configuration(tmp_path: Path) -> None:
    path = write(tmp_path / "t.csv", [row(split="holdout")])
    rows = st.load(path)
    with pytest.raises(st.TrialsError, match="frozen-config"):
        st.build_report(rows, report="holdout", frozen_config=None)
    report = st.build_report(
        rows, report="holdout", frozen_config="live=0.90 spoof=0.50 (cal run 7)"
    )
    assert report["frozen_config"].startswith("live=0.90") and "calibration" not in report


def test_splits_are_reported_separately_never_merged(tmp_path: Path) -> None:
    path = write(
        tmp_path / "t.csv",
        [row(), row(participant_id="p9", trial_id="h", split="holdout", outcome="NO_MATCH")],
    )
    report = st.build_report(st.load(path), report="both", frozen_config="x")
    assert report["calibration"]["genuine_punch"]["false_rejection_per_attempt"]["numerator"] == 0
    assert report["holdout"]["genuine_punch"]["false_rejection_per_attempt"]["numerator"] == 1


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"outcome": "MAYBE"}, "unknown outcome"),
        ({"phase": "x"}, "phase"),
        ({"split": "train"}, "split"),
        ({"latency_ms": "fast"}, "latency_ms"),
        ({"kind": "attack", "attack_type": ""}, "attack_type"),
    ],
)
def test_malformed_rows_fail_loudly_without_echoing_content(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    path = write(tmp_path / "t.csv", [row(**change)])
    with pytest.raises(st.TrialsError, match=message) as info:
        st.load(path)
    assert "p1" not in str(info.value)


def test_missing_columns_and_empty_files_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad.csv").write_text("trial_id\n1\n")
    with pytest.raises(st.TrialsError, match="missing columns"):
        st.load(tmp_path / "bad.csv")
    write(tmp_path / "empty.csv", [])
    with pytest.raises(st.TrialsError, match="no rows"):
        st.load(tmp_path / "empty.csv")


def test_cli_prints_json_and_returns_2_on_bad_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = write(tmp_path / "g.csv", [row()])
    assert st.main([str(good)]) == 0
    assert json.loads(capsys.readouterr().out)["calibration"]["attempts"] == 1
    assert st.main([str(tmp_path / "nope.csv")]) == 2
