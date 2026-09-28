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
    assert "OOD_DEV_CONSUMED" in content
    assert "E5C_PREFERRED_DEVELOPMENT_STAGE1" in content
    assert "E5C_PREDECLARED_GATE_PASS" in content
    assert "v0_k8s_032" in content


def test_e5c_candidate_rank_trace():
    trace_path = Path("benchmarks/experiments/e5c_candidate_rank_trace.jsonl")
    assert trace_path.exists(), "e5c_candidate_rank_trace.jsonl must exist"
    
    traces = {}
    with open(trace_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                t = json.loads(line)
                traces[t["query_id"]] = t

    assert len(traces) == 140, f"Expected 140 queries in trace, got {len(traces)}"
    
    # Assert exact rank properties for the investigated queries
    assert traces["v0_pt_003"]["best_positive_rank"] == 16, "v0_pt_003 must be at rank 16"
    assert traces["v0_pt_003"]["has_hit_at_20"] is True, "v0_pt_003 must be a hit at K=20"
    
    assert traces["v0_k8s_001"]["best_positive_rank"] == 13, "v0_k8s_001 must be at rank 13"
    assert traces["v0_k8s_001"]["has_hit_at_20"] is True, "v0_k8s_001 must be a hit at K=20"
    
    assert traces["v0_k8s_032"]["best_positive_rank"] is None, "v0_k8s_032 must be None (sole miss)"
    assert traces["v0_k8s_032"]["has_hit_at_20"] is False
    assert traces["v0_k8s_032"]["has_hit_at_50"] is False

    # Sole miss assertions
    misses_k20 = [qid for qid, t in traces.items() if not t["has_hit_at_20"]]
    misses_k50 = [qid for qid, t in traces.items() if not t["has_hit_at_50"]]
    assert misses_k20 == ["v0_k8s_032"], f"Expected only v0_k8s_032 missing at K=20, got {misses_k20}"
    assert misses_k50 == ["v0_k8s_032"], f"Expected only v0_k8s_032 missing at K=50, got {misses_k50}"


def test_e7_domain_reranker_plan_exists():
    plan_path = Path("docs/E7_DOMAIN_RERANKER_PLAN.md")
    assert plan_path.exists(), "E7_DOMAIN_RERANKER_PLAN.md must exist"
    content = plan_path.read_text(encoding="utf-8")
    assert "E7" in content
    assert "Candidate Depth" in content
    assert "RTX 5050" in content
    assert "E5C" in content
    assert "E6C-Top20" in content


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

    # Verify non-degradation against original threshold -0.015
    for comp in ["E4C_MatchedEasy_BGE", "E5C_Hybrid_MatchedEasy"]:
        stat = data["statistical_comparisons_vs_e1a"][comp]
        assert stat["observed_delta"] >= -0.015, f"{comp} observed delta fell below -0.015: {stat['observed_delta']}"


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
