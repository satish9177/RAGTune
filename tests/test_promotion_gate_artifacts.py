"""Tests asserting integrity of Development Promotion Gate artifacts."""

import hashlib
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
    assert "E5C_DEVELOPMENT_PROMOTION_PASS_FINAL_OOD_PENDING" in content
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
    assert "6,414" in content
    assert "Candidate Depth" in content
    assert "RTX 5050" in content
    assert "E5C" in content
    assert "E6C-Top20" in content


def test_e7_readiness_artifact():
    readiness_path = Path("benchmarks/canonical/E7_READINESS.md")
    assert readiness_path.exists(), "E7_READINESS.md must exist"
    content = readiness_path.read_text(encoding="utf-8")
    assert "6,414 chunks" in content
    assert "188 queries" in content
    assert "READY_FOR_TRAINING_AFTER_E7_NEGATIVE_HUMAN_AUDIT" in content
    assert "OOD_DEV_CONSUMED" in content
    assert "PENDING_HUMAN_AUDIT" in content


def test_canonical_train_chunk_counts():
    manifest_path = Path("benchmarks/partition_manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["summary"]["train"]["chunk_count"] == 6414
    assert manifest["summary"]["validation"]["chunk_count"] == 1575
    assert manifest["summary"]["frozen_test"]["chunk_count"] == 3656
    assert (
        manifest["summary"]["train"]["chunk_count"]
        + manifest["summary"]["validation"]["chunk_count"]
        + manifest["summary"]["frozen_test"]["chunk_count"]
        == 11645
    )


def test_e7_training_inputs_containment():
    """Verify that all queries and passages permitted for E7 training come 100% from canonical train."""
    chunks_path = Path("data/processed/partitioned_chunks.jsonl")
    train_chunk_ids = set()
    val_chunk_ids = set()
    test_chunk_ids = set()
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                if c["partition"] == "train":
                    train_chunk_ids.add(c["chunk_id"])
                elif c["partition"] == "validation":
                    val_chunk_ids.add(c["chunk_id"])
                elif c["partition"] == "frozen_test":
                    test_chunk_ids.add(c["chunk_id"])

    assert len(train_chunk_ids) == 6414
    assert len(val_chunk_ids) == 1575
    assert len(test_chunk_ids) == 3656

    # Test retriever_train_v0.jsonl
    train_queries_path = Path("data/training/retriever_train_v0.jsonl")
    assert train_queries_path.exists()
    with open(train_queries_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                q = json.loads(line)
                assert q["positive_chunk_id"] in train_chunk_ids
                assert q["positive_chunk_id"] not in val_chunk_ids
                assert q["positive_chunk_id"] not in test_chunk_ids
                assert q["negative_chunk_id"] in train_chunk_ids
                assert q["negative_chunk_id"] not in val_chunk_ids
                assert q["negative_chunk_id"] not in test_chunk_ids

    # Test hard_negatives_v1.jsonl
    hn_path = Path("data/training/hard_negatives_v1.jsonl")
    assert hn_path.exists()
    with open(hn_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                q = json.loads(line)
                assert q["positive_chunk_id"] in train_chunk_ids
                assert q["positive_chunk_id"] not in val_chunk_ids
                assert q["positive_chunk_id"] not in test_chunk_ids
                assert q["negative_chunk_id"] in train_chunk_ids
                assert q["negative_chunk_id"] not in val_chunk_ids
                assert q["negative_chunk_id"] not in test_chunk_ids


def test_ood_datasets_reservation_integrity():
    """Verify that SciFact is marked OOD_DEV_CONSUMED, and FiQA / BRIGHT remain untouched."""
    report_path = Path("benchmarks/canonical/DEVELOPMENT_PROMOTION_GATE.md")
    content = report_path.read_text(encoding="utf-8")
    assert "OOD_DEV_CONSUMED" in content

    # Assert no FiQA or BRIGHT metric results are in benchmarks/experiments
    exp_dir = Path("benchmarks/experiments")
    for f in exp_dir.glob("*.json"):
        name = f.name.lower()
        assert "fiqa" not in name, f"FiQA metric file found: {f.name}"
        assert "bright" not in name, f"BRIGHT metric file found: {f.name}"


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


def test_historical_audit_ai_review():
    """Verify historical audit AI review classifications and defect documentation."""
    # Historical report must remain unchanged
    md_path = Path("data/training/HARD_NEGATIVE_AUDIT_40.md")
    assert md_path.exists()

    ai_review_path = Path("data/training/HARD_NEGATIVE_AUDIT_40_AI_REVIEW.json")
    assert ai_review_path.exists()
    with open(ai_review_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["status"] == "AI_RECOMMENDATION_PENDING_HUMAN_CONFIRMATION"
    summary = data["classification_summary"]["negative_semantic_status"]
    assert summary["FALSE_NEGATIVE"] == 4
    assert summary["AMBIGUOUS_UNSAFE_NEGATIVE"] == 6
    assert summary["LIKELY_TRUE_NEGATIVE"] == 30

    # Specific defect check on train_fa_0377
    defects = {d["query_id"]: d for d in data["identified_defects"]}
    assert "train_fa_0377" in defects
    assert defects["train_fa_0377"]["defect_type"] == "QUERY_POSITIVE_MAPPING_DEFECT"
    assert defects["train_fa_0377"]["semantic_status"] == "FALSE_NEGATIVE"


def test_e7_primary_manifest_and_quality():
    """Verify E7 primary query manifest (exactly 188 queries) and quality report."""
    manifest_path = Path("data/training/E7_PRIMARY_QUERY_MANIFEST.json")
    assert manifest_path.exists()
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["total_queries"] == 188
    assert len(manifest["queries"]) == 188
    
    # Assert exact file SHA-256
    file_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert file_sha == "a0cb391c36c1f1d54d8712d9bfe540e4792f0ae8eb6826e68d6bda02d14dffd5"

    # Verify quality report
    quality_path = Path("data/training/E7_QUERY_POSITIVE_QUALITY.json")
    assert quality_path.exists()
    with open(quality_path, "r", encoding="utf-8") as f:
        quality = json.load(f)
    assert quality["total_queries_evaluated"] == 188
    dist = quality["status_distribution"]
    assert dist["CLEAN"] == 125
    assert dist["REVIEW_QUERY"] == 59
    assert dist["REVIEW_POSITIVE_MAPPING"] == 4


def test_e7_candidate_ledger_and_safe_negatives():
    """Verify E7 candidate ledger, safe negatives pool, and human audit packet."""
    chunks_path = Path("data/processed/partitioned_chunks.jsonl")
    train_cids = set()
    val_cids = set()
    test_cids = set()
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                if c["partition"] == "train":
                    train_cids.add(c["chunk_id"])
                elif c["partition"] == "validation":
                    val_cids.add(c["chunk_id"])
                elif c["partition"] == "frozen_test":
                    test_cids.add(c["chunk_id"])

    # E7 Candidate Ledger
    ledger_path = Path("data/training/e7_candidate_ledger.jsonl")
    assert ledger_path.exists()
    ledger_count = 0
    with open(ledger_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                ledger_count += 1
                assert row["positive_chunk_id"] in train_cids
                assert row["positive_chunk_id"] not in val_cids
                assert row["positive_chunk_id"] not in test_cids
                assert row["candidate_chunk_id"] in train_cids
                assert row["candidate_chunk_id"] not in val_cids
                assert row["candidate_chunk_id"] not in test_cids
    assert ledger_count == 3760, f"Expected 3760 candidates in E7 ledger, got {ledger_count}"

    # E7 Safe Negatives Pool
    safe_path = Path("data/training/e7_safe_negatives.jsonl")
    assert safe_path.exists()
    safe_count = 0
    with open(safe_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                safe_count += 1
                assert row["classification"] == "SAFE_NEGATIVE"
                assert row["candidate_chunk_id"] in train_cids
                assert row["candidate_chunk_id"] not in val_cids
                assert row["candidate_chunk_id"] not in test_cids
    assert safe_count == 1216, f"Expected 1216 safe negatives, got {safe_count}"

    # E7 Disposition Summary
    disp_path = Path("data/training/e7_candidate_disposition.json")
    assert disp_path.exists()
    with open(disp_path, "r", encoding="utf-8") as f:
        disp = json.load(f)
    assert disp["total_candidates_mined"] == 3760
    assert disp["disposition_counts"]["SAFE_NEGATIVE"] == 1216
    assert disp["disposition_counts"]["QUARANTINE_POSSIBLE_FALSE_NEGATIVE"] == 1044
    assert disp["disposition_counts"]["REJECT_KNOWN_RELEVANT"] == 186
    assert disp["disposition_counts"]["REJECT_TOO_EASY"] == 1314

    # E7 Human Audit Packet
    audit_json = Path("data/training/E7_NEGATIVE_AUDIT_40.json")
    audit_md = Path("data/training/E7_NEGATIVE_AUDIT_40.md")
    assert audit_json.exists()
    assert audit_md.exists()
    with open(audit_json, "r", encoding="utf-8") as f:
        audit_data = json.load(f)
    assert audit_data["status"] == "PENDING_HUMAN_AUDIT"
    assert audit_data["total_sample_size"] == 40
    assert audit_data["ecosystem_distribution"] == {
        "postgresql": 10,
        "pytorch": 10,
        "kubernetes": 10,
        "fastapi": 10,
    }


def test_teacher_and_query_universe_provenance():
    """Verify teacher provenance and 3-universe overlap documentation."""
    teacher_path = Path("data/training/HARD_NEGATIVE_TEACHER_PROVENANCE.md")
    assert teacher_path.exists()
    teacher_content = teacher_path.read_text(encoding="utf-8")
    assert "BAAI/bge-reranker-base" in teacher_content
    assert "0.741149" in teacher_content
    assert "0.030097" in teacher_content

    univ_path = Path("data/training/TRAIN_QUERY_PROVENANCE.md")
    assert univ_path.exists()
    univ_content = univ_path.read_text(encoding="utf-8")
    assert "188" in univ_content
    assert "501" in univ_content
    assert "375" in univ_content
    assert "173" in univ_content
    assert "6,414 chunks" in univ_content

