"""Metric arithmetic and the evaluation harness's refusal to overstate thin evidence. Scores
here are hand-built to test the maths; they are NOT used to pick any production threshold."""

import json
from pathlib import Path

import pytest

from hrms.modules.attendance.opensource_face.evaluation.metrics import (
    equal_error_rate,
    evidence_gaps,
    far_at,
    frr_at,
    percentile,
    threshold_for_far,
    upper_bound_zero_events,
)

GENUINE = [0.9, 0.8, 0.7, 0.4]
IMPOSTOR = [0.5, 0.3, 0.2, 0.1, 0.05]


def test_far_frr_boundaries() -> None:
    assert far_at(IMPOSTOR, 0.5) == pytest.approx(0.2)  # inclusive at the threshold
    assert far_at(IMPOSTOR, 0.51) == 0.0
    assert frr_at(GENUINE, 0.4) == 0.0  # score == threshold is accepted
    assert frr_at(GENUINE, 0.41) == pytest.approx(0.25)


def test_equal_error_rate_and_far_targeting() -> None:
    eer = equal_error_rate(GENUINE, IMPOSTOR)
    assert abs(eer.far - eer.frr) <= 0.2
    zero_far = threshold_for_far(GENUINE, IMPOSTOR, 0.0)
    assert zero_far is not None and zero_far.far == 0.0 and zero_far.threshold > 0.5
    assert threshold_for_far([0.1], [0.9, 0.9], 0.0) is not None


def test_percentiles_and_zero_event_bound() -> None:
    assert percentile([1, 2, 3, 4], 0.5) == pytest.approx(2.5)
    assert upper_bound_zero_events(300) == pytest.approx(0.01)


def test_small_data_is_labelled_insufficient() -> None:
    gaps = evidence_gaps(identities=3, genuine=12, impostor=40, attack_samples={})
    text = " ".join(gaps)
    for expected in ("identities", "genuine trials", "impostor trials", "presentation-attack"):
        assert expected in text
    assert (
        evidence_gaps(
            identities=60, genuine=900, impostor=20000, attack_samples={"print": 150, "replay": 150}
        )
        == []
    )
    assert any(
        "replay" in g
        for g in evidence_gaps(
            identities=60, genuine=900, impostor=20000, attack_samples={"replay": 5}
        )
    )


@pytest.mark.skipif(
    not (
        Path(__file__).resolve().parents[4]
        / "models/face/opensource-v1/face_detection_yunet_2023mar.onnx"
    ).is_file(),
    reason="assets not provisioned",
)
def test_report_contains_only_aggregates(tmp_path: Path) -> None:
    """An empty capture tree yields a report with evidence gaps and no paths/names/embeddings."""
    pytest.importorskip("cv2")
    import argparse
    import asyncio

    from hrms.modules.attendance.opensource_face.evaluation.evaluate_captures import evaluate

    (tmp_path / "secret_person_name").mkdir()
    args = argparse.Namespace(
        captures=str(tmp_path),
        model_dir=str(Path(__file__).resolve().parents[4] / "models/face/opensource-v1"),
        liveness_dir="",
        thresholds="0.45",
        report_threshold=0.45,
        enroll_samples=3,
        detector_score=0.9,
        min_face_px=80,
    )
    report = asyncio.run(evaluate(args))
    dumped = json.dumps(report, default=str)
    assert "secret_person_name" not in dumped and str(tmp_path) not in dumped
    assert report["identities"] == 0 and report["evidence_gaps"]


# --- report content with a stubbed embedder (tool plumbing only; scores are NOT evidence) -------


def _stub_args(captures: Path, model_dir: Path) -> "object":
    import argparse

    return argparse.Namespace(
        captures=str(captures),
        model_dir=str(model_dir),
        liveness_dir="",
        thresholds="0.363,0.45",
        report_threshold=0.45,
        enroll_samples=2,
        detector_score=0.9,
        min_face_px=80,
    )


def test_report_records_settings_provenance_distributions_and_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from hrms.modules.attendance.opensource_face import assets
    from hrms.modules.attendance.opensource_face.embedding_service import EmbeddingOutcome
    from hrms.modules.attendance.opensource_face.evaluation import evaluate_captures as ec
    from hrms.modules.attendance.opensource_face.similarity import EMBEDDING_DIM, normalise

    class Stub:
        model_version = "stub-model"

        def __init__(self, *a: object, **k: object) -> None: ...

        def warm_up(self) -> None: ...

        async def embed(self, image: bytes) -> EmbeddingOutcome:
            axis = int(image.decode().split(":")[0])  # file content "<axis>:<noise>"
            v = [0.0] * EMBEDDING_DIM
            v[axis], v[axis + 1] = 1.0, 0.1 * len(image)
            return EmbeddingOutcome("OK", normalise(v))

    monkeypatch.setattr(ec, "SFaceEmbeddingService", Stub)
    models = tmp_path / "models"
    models.mkdir()
    for name in assets.ASSETS:
        (models / name).write_bytes(b"dummy")
    captures = tmp_path / "caps"
    for i, name in enumerate(("alice_real_name", "bob_real_name")):
        for cond in ("indoor", "outdoor"):
            for n in range(4):
                folder = captures / name / cond
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{n}.jpg").write_bytes(f"{i * 4}:{'x' * n}".encode())
    (captures / "_meta").mkdir()
    (captures / "_meta" / "groups.json").write_text(
        json.dumps({"alice_real_name": "group_a", "bob_real_name": "group_b"})
    )

    report = asyncio.run(ec.evaluate(_stub_args(captures, models)))  # type: ignore[arg-type]
    dumped = json.dumps(report, default=str)

    assert report["verdict"] == "INSUFFICIENT EVIDENCE" and report["evidence_gaps"]
    assert report["settings"]["enroll_samples"] == 2 and report["settings"]["min_face_px"] == 80  # type: ignore[index]
    assert set(report["provenance"]["asset_sha256"]) == set(assets.ASSETS)  # type: ignore[index]
    assert report["provenance"]["opencv"]  # type: ignore[index]
    dist = report["score_distributions"]["genuine"]  # type: ignore[index]
    assert dist["n"] == report["genuine_trials"] and sum(dist["histogram_counts"]) == dist["n"]
    # Sub-groups far below the minimum are suppressed, not reported.
    assert all("INSUFFICIENT EVIDENCE" in str(v) for v in report["demographic_breakdown"].values())  # type: ignore[union-attr]
    # Aggregates only: no identity names, paths or raw vectors.
    for forbidden in ("alice_real_name", "bob_real_name", str(tmp_path)):
        assert forbidden not in dumped

    def has_vector(node: object) -> bool:  # a list of >= 100 floats would be a raw embedding
        if isinstance(node, dict):
            return any(has_vector(v) for v in node.values())
        if isinstance(node, list):
            return (len(node) >= 100 and all(isinstance(x, float) for x in node)) or any(
                has_vector(v) for v in node
            )
        return False

    assert not has_vector(report)


def test_unbalanced_probes_are_an_evidence_gap_and_complete_data_is_labelled() -> None:
    from hrms.modules.attendance.opensource_face.evaluation.metrics import verdict

    gaps = evidence_gaps(
        identities=60,
        genuine=900,
        impostor=20000,
        attack_samples={"print": 150},
        probes_per_identity=[1, 30, 10],
    )
    assert any("unbalanced" in g for g in gaps) and verdict(gaps) == "INSUFFICIENT EVIDENCE"
    ok = evidence_gaps(
        identities=60,
        genuine=900,
        impostor=20000,
        attack_samples={"print": 150},
        probes_per_identity=[10, 12, 15],
    )
    assert ok == [] and "not a production approval" in verdict(ok)
