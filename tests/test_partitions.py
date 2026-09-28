"""Unit tests for partition integrity and document-level isolation."""

import json
from pathlib import Path
import pytest


def test_partition_manifest_integrity():
    manifest_path = Path("benchmarks/partition_manifest.json")
    assert manifest_path.exists(), "Partition manifest not found"

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["seed"] == 42
    assert "train" in data["summary"]
    assert "validation" in data["summary"]
    assert "frozen_test" in data["summary"]

    train_files = {f"{item['ecosystem']}::{item['file_path']}" for item in data["files"]["train"]}
    val_files = {f"{item['ecosystem']}::{item['file_path']}" for item in data["files"]["validation"]}
    test_files = {f"{item['ecosystem']}::{item['file_path']}" for item in data["files"]["frozen_test"]}

    # Zero file overlap across partitions
    assert len(train_files.intersection(val_files)) == 0, "Train and Validation files overlap!"
    assert len(train_files.intersection(test_files)) == 0, "Train and Frozen Test files overlap!"
    assert len(val_files.intersection(test_files)) == 0, "Validation and Frozen Test files overlap!"


def test_chunk_partition_assignment():
    chunks_path = Path("data/processed/partitioned_chunks.jsonl")
    manifest_path = Path("benchmarks/partition_manifest.json")
    assert chunks_path.exists(), "Partitioned chunks not found"
    assert manifest_path.exists(), "Partition manifest not found"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    expected_total = sum(p["chunk_count"] for p in manifest["summary"].values())

    with open(chunks_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == expected_total
    valid_partitions = {"train", "validation", "frozen_test"}
    for line in lines[:500]:
        chunk = json.loads(line)
        assert chunk["partition"] in valid_partitions


def test_exact_partition_counts_against_manifest():
    """Assert exact document-partition chunk counts against the frozen partition manifest."""
    chunks_path = Path("data/processed/partitioned_chunks.jsonl")
    manifest_path = Path("benchmarks/partition_manifest.json")
    assert chunks_path.exists(), "Partitioned chunks not found"
    assert manifest_path.exists(), "Partition manifest not found"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    expected_train = manifest["summary"]["train"]["chunk_count"]
    expected_val = manifest["summary"]["validation"]["chunk_count"]
    expected_test = manifest["summary"]["frozen_test"]["chunk_count"]

    assert expected_train == 6414
    assert expected_val == 1575
    assert expected_test == 3656
    assert expected_train + expected_val + expected_test == 11645

    counts = {"train": 0, "validation": 0, "frozen_test": 0}
    total = 0
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                part = c["partition"]
                counts[part] += 1
                total += 1

    assert total == 11645
    assert counts["train"] == expected_train
    assert counts["validation"] == expected_val
    assert counts["frozen_test"] == expected_test
    assert counts["train"] + counts["validation"] + counts["frozen_test"] == 11645

