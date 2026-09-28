"""Tests asserting integrity of Development Promotion Gate artifacts."""

import json
from pathlib import Path


def test_promotion_gate_report_exists():
    report_path = Path("benchmarks/canonical/DEVELOPMENT_PROMOTION_GATE.md")
    assert report_path.exists(), "DEVELOPMENT_PROMOTION_GATE.md must exist"
    content = report_path.read_text(encoding="utf-8")
    assert "E5C" in content
    assert "E6C-Top20" in content
    assert "E6C-Top50" in content
    assert "SciFact" in content
    assert "HitRate@20" in content


def test_e6_reranker_artifacts():
    exp_dir = Path("benchmarks/experiments")
    for name in ["e6c_top20", "e6c_top50", "e6h_top50"]:
        metric_file = exp_dir / f"{name}_metrics.json"
        manifest_file = exp_dir / f"{name}_manifest.json"
        preds_file = exp_dir / f"{name}_predictions.jsonl"
        assert metric_file.exists(), f"Missing {metric_file}"
        assert manifest_file.exists(), f"Missing {manifest_file}"
        assert preds_file.exists(), f"Missing {preds_file}"

        with open(metric_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert "metrics" in data
            assert "latency" in data
            assert "ndcg_at_10" in data["metrics"]
            assert "recall_at_10" in data["metrics"]
            assert "hit_rate_at_10" in data["metrics"]
            assert "hit_rate_at_20" in data["metrics"]


def test_e6c_failure_transition_analysis():
    trans_file = Path("benchmarks/experiments/e6c_failure_transition_analysis.json")
    assert trans_file.exists(), "e6c_failure_transition_analysis.json must exist"
    with open(trans_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["summary"]["total_queries"] == 140
    assert data["summary"]["relevant_candidate_in_pool_but_demoted_outside_top10"] == 11
    assert data["summary"]["stage1_unrecoverable_misses_outside_depth50"] == 1


def test_ood_scifact_artifacts():
    metrics_file = Path("benchmarks/experiments/ood_scifact_metrics.json")
    manifest_file = Path("benchmarks/experiments/ood_scifact_manifest.json")
    assert metrics_file.exists(), "ood_scifact_metrics.json must exist"
    assert manifest_file.exists(), "ood_scifact_manifest.json must exist"

    with open(metrics_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["benchmark"] == "BEIR/SciFact (mteb/scifact)"
    assert data["num_queries"] == 300
    assert "E1a_ZeroShot_BGE" in data["results"]
    assert "E4C_MatchedEasy_BGE" in data["results"]
    assert "E4_HardNeg_BGE" in data["results"]
    assert "E5C_Hybrid_MatchedEasy" in data["results"]

    # Verify non-degradation for E4C and E5C
    for comp in ["E4C_MatchedEasy_BGE", "E5C_Hybrid_MatchedEasy"]:
        stat = data["statistical_comparisons_vs_e1a"][comp]
        assert stat["ci_upper"] >= -0.02, f"{comp} CI upper bound fell below -0.02"


def test_candidate_ledger_and_audit_companion():
    ledger_path = Path("data/training/hard_negative_candidate_ledger_v1.jsonl")
    assert ledger_path.exists(), "hard_negative_candidate_ledger_v1.jsonl must exist"
    with open(ledger_path, "r", encoding="utf-8") as f:
        count = sum(1 for line in f if line.strip())
    assert count == 10669, f"Expected 10669 candidates in ledger, got {count}"

    audit_json = Path("data/training/HARD_NEGATIVE_AUDIT_40.json")
    assert audit_json.exists(), "HARD_NEGATIVE_AUDIT_40.json must exist"
    with open(audit_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["status"] == "PENDING_HUMAN_AUDIT"
    assert len(data["audit_items"]) == 40
