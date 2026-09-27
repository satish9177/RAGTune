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

        d = q["domain"]
        t = q["typology"]
        p = q["provenance_type"]

        domains[d] = domains.get(d, 0) + 1
        typologies[t] = typologies.get(t, 0) + 1
        provenances[p] = provenances.get(p, 0) + 1

        # Check relevant chunks
        grades = [r["grade"] for r in q["relevant_chunks"]]
        assert 3 in grades, f"Query {q['query_id']} must have a grade 3 canonical chunk"
        assert 2 in grades, f"Query {q['query_id']} must have a grade 2 chunk"

    assert domains == {"postgresql": 35, "pytorch": 35, "kubernetes": 35, "fastapi": 35}
    assert typologies == {"direct_lookup": 40, "comparative_discrimination": 60, "troubleshooting_scenario": 40}


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
    assert "overall_metrics" in man
    assert man["overall_metrics"]["recall_at_10"] > 0.40
    assert "git_commit_sha" in man
    assert len(man["git_commit_sha"]) == 40
