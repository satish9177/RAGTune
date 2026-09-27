"""Unit and integrity tests for Benchmark v0 and E0-v0 baseline artifacts."""

import json
from pathlib import Path
import pytest

from ragtune.training.guardrails import validate_validation_query


def test_benchmark_v0_schema_and_integrity():
    benchmark_path = Path("benchmarks/benchmark_v0.jsonl")
    assert benchmark_path.exists(), "Benchmark v0 file must exist"

    with open(benchmark_path, "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]

    assert len(queries) == 140, f"Expected 140 queries, got {len(queries)}"

    domains = {}
    typologies = {}
    provenances = {}

    for q in queries:
        validate_validation_query(q)
        assert q["source_partition"] == "validation"
        assert q["role"] == "development"
        assert q["review_status"] == "UNREVIEWED"
        assert q["reviewer"] is None
        assert q["provenance_type"] != "human_authored", "AI generated queries must not be labeled human_authored"
        assert q["provenance_type"] in ["ai_authored_project_query", "synthetic_grounded", "external_derived_verified"]
        assert q["ai_recommendation"] in ["APPROVE_CANDIDATE", "REVISE_CANDIDATE", "REJECT_CANDIDATE"]

        d = q["domain"]
        t = q["typology"]
        p = q["provenance_type"]

        domains[d] = domains.get(d, 0) + 1
        typologies[t] = typologies.get(t, 0) + 1
        provenances[p] = provenances.get(p, 0) + 1

        # Check relevant chunks: must have exactly one grade 3 canonical chunk, and total positives >= 1
        grades = [r["grade"] for r in q["relevant_chunks"]]
        assert grades.count(3) == 1, f"Query {q['query_id']} must have exactly one grade 3 canonical chunk"
        assert len(grades) >= 1

    assert domains == {"postgresql": 35, "pytorch": 35, "kubernetes": 35, "fastapi": 35}
    assert typologies == {"direct_lookup": 40, "comparative_discrimination": 60, "troubleshooting_scenario": 40}
    assert provenances["ai_authored_project_query"] == 88
    assert provenances["synthetic_grounded"] == 49
    assert provenances["external_derived_verified"] == 3


def test_e0_v0_manifest_and_metrics_artifacts():
    manifest_path = Path("benchmarks/e0_v0_manifest.json")
    metrics_path = Path("benchmarks/e0_v0_metrics.json")
    preds_path = Path("benchmarks/e0_v0_predictions.jsonl")
    failures_path = Path("benchmarks/e0_v0_failures.jsonl")

    assert manifest_path.exists()
    assert metrics_path.exists()
    assert preds_path.exists()
    assert failures_path.exists()

    with open(manifest_path, "r", encoding="utf-8") as f:
        man = json.load(f)

    assert man["total_queries"] == 140
    assert man["benchmark_source_partition"] == "validation"
    assert man["status"] == "PROVISIONAL_DRAFT"
    assert man["canonical_status"] == "PENDING_BENCHMARK_V0_HUMAN_REVIEW"
    assert "overall_metrics" in man
    assert man["overall_metrics"]["recall_at_10"] > 0.40


def test_quality_audit_and_review_packets_exist():
    audit_file = Path("benchmarks/benchmark_v0_quality_audit.json")
    master_review = Path("benchmarks/review/benchmark_v0_review.md")
    csv_review = Path("benchmarks/review/benchmark_v0_review.csv")
    json_review = Path("benchmarks/review/benchmark_v0_review.json")

    assert audit_file.exists()
    assert master_review.exists()
    assert csv_review.exists()
    assert json_review.exists()

    with open(audit_file, "r", encoding="utf-8") as f:
        audit = json.load(f)

    assert audit["total_queries_audited"] == 140
    assert audit["review_status_summary"]["UNREVIEWED"] == 140
    assert audit["anti_parroting_summary"]["max_jaccard_vs_evidence"] < 0.40

