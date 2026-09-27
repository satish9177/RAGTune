"""Unit tests for leakage audit artifact schema and properties."""

import json
from pathlib import Path
import pytest


def test_leakage_audit_file_schema():
    audit_path = Path("benchmarks/leakage_audit.jsonl")
    assert audit_path.exists(), "Leakage audit artifact does not exist."

    with open(audit_path, "r", encoding="utf-8") as f:
        first_line = f.readline()

    assert first_line.strip(), "Audit artifact is empty."
    rec = json.loads(first_line)

    required_keys = [
        "chunk_id_a",
        "chunk_id_b",
        "ecosystem_a",
        "ecosystem_b",
        "source_partition_a",
        "source_partition_b",
        "similarity_metric",
        "score",
        "reason_flagged",
        "review_status",
    ]
    for k in required_keys:
        assert k in rec, f"Missing key {k} in leakage audit record"

    assert rec["review_status"] == "FLAGGED_FOR_REVIEW"
    assert rec["score"] >= 0.65
    # Must span cross-partitions
    assert rec["source_partition_a"] != rec["source_partition_b"]
