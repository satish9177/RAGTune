"""Unit tests validating the 16-query pilot benchmark against schema and frozen-test chunks."""

import json
from pathlib import Path
import pytest
from ragtune.models import BenchmarkQuery, PassageChunk


def test_pilot_benchmark_schema_and_integrity():
    bench_path = Path("benchmarks/pilot_benchmark.jsonl")
    chunks_path = Path("data/processed/partitioned_chunks.jsonl")

    assert bench_path.exists(), "Pilot benchmark JSONL does not exist."
    assert chunks_path.exists(), "Partitioned chunks do not exist."

    # Load all valid frozen test chunk IDs
    frozen_test_chunk_ids = set()
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                if c["partition"] == "frozen_test":
                    frozen_test_chunk_ids.add(c["chunk_id"])

    queries = []
    with open(bench_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                q = BenchmarkQuery.model_validate_json(line)
                queries.append(q)

    assert len(queries) == 16, f"Expected 16 pilot queries, got {len(queries)}"

    domain_counts = {}
    typology_counts = {}
    provenance_counts = {}

    for q in queries:
        domain_counts[q.domain] = domain_counts.get(q.domain, 0) + 1
        typology_counts[q.typology] = typology_counts.get(q.typology, 0) + 1
        provenance_counts[q.provenance_type] = provenance_counts.get(q.provenance_type, 0) + 1

        assert len(q.relevant_chunks) >= 2, f"Query {q.query_id} must have multi-positive judgments"
        grades = [rc.grade for rc in q.relevant_chunks]
        assert 3 in grades, f"Query {q.query_id} must have at least one grade 3 (canonical) passage"

        for rc in q.relevant_chunks:
            assert rc.chunk_id in frozen_test_chunk_ids, (
                f"Referenced chunk {rc.chunk_id} in {q.query_id} is not in the frozen_test partition!"
            )

    # Verify domain balance: exactly 4 each
    assert domain_counts == {"postgresql": 4, "pytorch": 4, "kubernetes": 4, "fastapi": 4}

    # Verify typology representation
    assert "direct_lookup" in typology_counts
    assert "comparative_discrimination" in typology_counts
    assert "troubleshooting_scenario" in typology_counts

    # Verify provenance representation
    assert "synthetic_grounded" in provenance_counts
    assert "human_authored" in provenance_counts
    assert "external_derived" in provenance_counts
